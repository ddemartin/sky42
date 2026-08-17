"""Lo screening: chi torna alla portata dei telescopi, e quando.

È il pezzo che **produce la lista**. Tutto il resto della catena sa rispondere
su un oggetto che qualcuno ha già nominato; questo guarda tutta la popolazione
monitorata e distilla, per ciascuno, le poche grandezze su cui si decide.

Due griglie, e non è la stessa domanda:

* **avanti** 24 mesi con passo di un giorno — «quando torna a portata?». Un
  giorno è il passo giusto perché la quantità che interessa (V) cambia di
  centesimi al giorno anche per un NEO in avvicinamento, e perché 730 epoche
  per oggetto stanno in 4 kB di float32.
* **indietro** 15 anni con passo di dieci giorni — «da quanto non era
  osservabile?». Qui la posizione a due corpi ha derivato parecchio, ma la
  domanda ammette una risposta grossolana: *la data di un'apparizione sbaglia
  di giorni, non di anni*, e serve a dire «7.4 anni fa» (docs/modelli.md §10).

Questo modulo **non tocca il database e non sa che cosa sia un sito**: riceve
`Body` e griglie, restituisce array e dizionari. Chi legge il catalogo e chi
scrive `screening_track` è `services/screening_service.py`.

**Perché niente moto apparente.** `positions(..., with_motion=False)` risparmia
i due terzi del lavoro (il moto costa due propagazioni in più) e allo screening
non serve: il trailing è una penalità della *notte*, e la notte la calcola
`visibility/`. Chi ha bisogno del moto ha già una lista corta.
"""
from __future__ import annotations

import numpy as np

from core.orbits.positioner import Body, positions

# --- le due griglie ---------------------------------------------------------

FORWARD_MONTHS = 24
FORWARD_STEP_DAYS = 1.0
BACK_YEARS = 15
BACK_STEP_DAYS = 10.0

DAYS_PER_MONTH = 365.25 / 12.0
DAYS_PER_YEAR = 365.25

# Le due soglie di allerta hanno una colonna ciascuna in `target_stats`. Sono
# magnitudini «da telescopio amatoriale serio» e non dipendono dal setup: il
# limite del setup è V_ref, che sta nel radar. Queste servono a rispondere
# «quando diventa fotografabile in assoluto», che è la domanda del catalogo.
V_ALERT = {"next_v21_jd": 21.0, "next_v205_jd": 20.5}

# Le serie che finiscono in `screening_track`, nell'ordine in cui si leggono.
TRACK_FIELDS = ("v_mag", "r_au", "delta_au", "elong_deg", "ra_deg", "dec_deg")

# Quanto avanti si guarda per dire «sta migliorando». Un mese e non una
# derivata istantanea: la derivata di V su un giorno è rumore di
# arrotondamento, un mese è l'orizzonte con cui si decide se aspettare.
TREND_DAYS = 30.0


def forward_grid(jd0: float, months: float = FORWARD_MONTHS,
                 step_days: float = FORWARD_STEP_DAYS) -> np.ndarray:
    """Da adesso a `months` mesi avanti, estremo incluso."""
    n = int(round(months * DAYS_PER_MONTH / step_days)) + 1
    return jd0 + np.arange(n, dtype=float) * step_days


def back_grid(jd0: float, years: float = BACK_YEARS,
              step_days: float = BACK_STEP_DAYS) -> np.ndarray:
    """Da `years` anni fa fino a ieri, in ordine crescente.

    L'ultimo punto è *prima* di adesso: l'apparizione in corso, se c'è, è roba
    della griglia in avanti, e contarla anche qui farebbe leggere «ultima buona
    apparizione: oggi» a un oggetto che non si è mai osservato.
    """
    n = int(round(years * DAYS_PER_YEAR / step_days))
    return jd0 - np.arange(n, 0, -1, dtype=float) * step_days


# --- la traccia -------------------------------------------------------------


def track(body: Body, jd, fields=TRACK_FIELDS) -> dict[str, np.ndarray]:
    """Le serie geocentriche per un blocco di oggetti, in float32.

    `body` ha colonne (N, 1) — `Body.from_rows` le costruisce così — e `jd` è
    (M,): il risultato è (N, M) senza nessun ciclo Python sugli oggetti.

    float32 e non float64 perché queste serie servono a *cercare*: 7 cifre
    significative su una magnitudine e su un grado di RA sono quattro ordini di
    grandezza più di quel che qualunque soglia dello screening distingue, e
    dimezzano sia la memoria del blocco sia il BLOB su disco.
    """
    p = positions(body, np.asarray(jd, dtype=float), with_motion=False)
    return {k: np.asarray(p[k], dtype=np.float32) for k in fields}


def pack(a: np.ndarray) -> bytes:
    """Una serie in BLOB. float32 little-endian, che è come si rilegge."""
    return np.ascontiguousarray(a, dtype="<f4").tobytes()


def unpack(blob: bytes) -> np.ndarray:
    """Da BLOB a float64: chi legge fa conti, e li fa nella precisione di casa."""
    return np.frombuffer(blob, dtype="<f4").astype(float)


# --- la distillazione -------------------------------------------------------


def distill(*, jd_fwd, v_fwd, jd_back=None, v_back=None, v_ref, jd_now=None) -> list[dict]:
    """Da due matrici di magnitudini alle righe di `target_stats`.

    `v_fwd` è (N, M) sulla griglia avanti, `v_back` (N, K) su quella indietro;
    `v_ref` è la soglia del radar, uno scalare o un array (N,).

    Tutto è vettoriale sui due assi, e il ciclo Python finale serve solo a
    impacchettare N dizionari: su 14.000 oggetti la distillazione costa meno
    della propagazione di un singolo blocco.

    Le grandezze che non esistono sono `None` e non zeri: un oggetto che non
    scende mai sotto V 21 nei prossimi due anni non ha un `next_v21_jd`, e
    scriverci una data qualunque sarebbe una bugia che poi qualcuno ordina.
    """
    jd_fwd = np.asarray(jd_fwd, dtype=float)
    v = np.atleast_2d(np.asarray(v_fwd, dtype=float))
    n = v.shape[0]
    jd_now = float(jd_fwd[0]) if jd_now is None else float(jd_now)

    # I NaN (fase estrapolata, fotometria mancante) diventano +inf: «non si
    # vede» è la risposta giusta a ogni confronto che segue, e nessuna delle
    # funzioni di minimo va poi difesa caso per caso.
    vf = np.where(np.isfinite(v), v, np.inf)
    vref = np.broadcast_to(np.asarray(v_ref, dtype=float).reshape(-1), (n,))

    righe = np.arange(n)
    i_peak = np.argmin(vf, axis=1)
    peak_v = vf[righe, i_peak]

    # Trend: la differenza a trenta giorni, non una derivata. Negativo =
    # sta migliorando, che è la convenzione della colonna.
    k = min(int(round(TREND_DAYS / (jd_fwd[1] - jd_fwd[0]))), v.shape[1] - 1)
    mesi = (jd_fwd[k] - jd_fwd[0]) / DAYS_PER_MONTH
    # `inf − inf` per un oggetto senza fotometria a nessuna delle due epoche:
    # il risultato è NaN, cioè «non lo so», che è la risposta giusta. Si tace
    # il warning invece di riempire il log dello screening con una riga per
    # ciascuno dei trenta blocchi.
    with np.errstate(invalid="ignore"):
        trend = (vf[:, k] - vf[:, 0]) / mesi if mesi > 0 else np.full(n, np.nan)

    sotto = vf <= vref[:, None]
    inizio, fine = _first_run(sotto, jd_fwd)

    out = []
    ultima_app = (_last_apparition(jd_back, v_back, vref)
                  if jd_back is not None and v_back is not None
                  else np.full(n, np.nan))

    for i in range(n):
        anni = ((jd_now - ultima_app[i]) / DAYS_PER_YEAR
                if np.isfinite(ultima_app[i]) else None)
        riga = {
            "v_now": _num(vf[i, 0]),
            "v_trend_mag_month": _num(trend[i]),
            "peak_v": _num(peak_v[i]),
            "peak_jd": float(jd_fwd[i_peak[i]]) if np.isfinite(peak_v[i]) else None,
            "visibility_start_jd": _num(inizio[i]),
            "visibility_end_jd": _num(fine[i]),
            "last_good_apparition_jd": _num(ultima_app[i]),
            "years_since_good_apparition": anni,
        }
        out.append(riga)

    for colonna, soglia in V_ALERT.items():
        quando, _ = _first_run(vf <= soglia, jd_fwd)
        for i in range(n):
            out[i][colonna] = _num(quando[i])
    return out


def _num(x) -> float | None:
    x = float(x)
    return None if not np.isfinite(x) else x


def _first_run(mask: np.ndarray, jd: np.ndarray):
    """Inizio e fine del **primo** tratto contiguo di `True`, per riga.

    Il primo e non il più lungo: la domanda è «quand'è la prossima volta»,
    e la prossima volta è la prima. Se il tratto arriva in fondo alla griglia
    la fine è l'ultimo punto, ed è vero solo nel senso che oltre non sappiamo —
    per questo `visibility_end_jd` non va letto come «poi sparisce».
    """
    m = np.atleast_2d(mask)
    cols = m.shape[1]
    esiste = m.any(axis=1)
    start = np.argmax(m, axis=1)

    idx = np.arange(cols)
    dopo_inizio = idx[None, :] > start[:, None]
    risale = (~m) & dopo_inizio
    ha_fine = risale.any(axis=1)
    end = np.where(ha_fine, np.argmax(risale, axis=1) - 1, cols - 1)

    return (np.where(esiste, jd[start], np.nan),
            np.where(esiste, jd[np.clip(end, 0, cols - 1)], np.nan))


def _last_apparition(jd_back, v_back, v_ref) -> np.ndarray:
    """L'istante migliore dell'**ultima** apparizione passata, per riga.

    Non l'inizio e non la fine dell'ultimo tratto sotto soglia: il suo minimo
    di V, cioè il momento in cui l'oggetto è stato più alla portata. È quello
    che risponde a «l'ultima volta buona», e non si sposta se la soglia cambia
    di un decimo.
    """
    jd = np.asarray(jd_back, dtype=float)
    v = np.atleast_2d(np.asarray(v_back, dtype=float))
    vf = np.where(np.isfinite(v), v, np.inf)
    n, cols = vf.shape
    vref = np.broadcast_to(np.asarray(v_ref, dtype=float).reshape(-1), (n,))

    sotto = vf <= vref[:, None]
    mai = ~sotto.any(axis=1)

    # Ultimo True: argmax sulla riga rovesciata. Poi l'inizio di quel tratto,
    # che è l'ultimo False *prima* di lì — con un massimo cumulativo, invece
    # che scorrendo indietro riga per riga.
    ultimo = cols - 1 - np.argmax(sotto[:, ::-1], axis=1)
    idx = np.arange(cols)
    falsi = np.where(~sotto, idx[None, :], -1)
    primo = np.maximum.accumulate(falsi, axis=1)[np.arange(n), ultimo] + 1

    dentro = (idx[None, :] >= primo[:, None]) & (idx[None, :] <= ultimo[:, None])
    migliore = np.argmin(np.where(dentro, vf, np.inf), axis=1)
    return np.where(mai, np.nan, jd[migliore])


def propagated_uncertainty(ceu_arcsec, ceu_rate, ceu_date_jd, jd) -> float | None:
    """CEU propagata linearmente: `ceu + ceu_rate · (t − t_ceu)`.

    Lineare, quindi **stima per difetto** su tempi lunghi (docs/modelli.md §9):
    oltre l'anno vale come ordine di grandezza e non come numero. Restituisce
    `None` quando ASTORB non copre l'oggetto, che è metà del catalogo.
    """
    if ceu_arcsec is None:
        return None
    if ceu_rate is None or ceu_date_jd is None:
        return float(ceu_arcsec)
    return float(max(ceu_arcsec + ceu_rate * (float(jd) - float(ceu_date_jd)), 0.0))
