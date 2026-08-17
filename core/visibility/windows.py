"""La finestra osservativa: quando quell'oggetto si vede, e quando conviene.

È il pezzo che mette insieme tutti gli altri, e l'unico che risponde alla
domanda del progetto. Due finestre distinte, che **non si fondono mai** in un
flag solo (regola 5):

* `geo_*` — **GEOMETRICALLY OBSERVABLE**: l'oggetto è abbastanza alto, dentro
  l'airmass massima, e il Sole è abbastanza sotto per quel setup.
* `useful_*` — **ACTUALLY USEFUL**: dentro la finestra geometrica, la
  magnitudine prevista sta sotto il limite efficace.

Sapere che un oggetto era alto 60° ma irrimediabilmente sotto il limite per
colpa della Luna è informazione, non rumore: è la differenza fra «stanotte non
si poteva» e «stanotte non ci ho provato».

**Si campiona, non si risolve.** La notte diventa una griglia da cinque minuti
e i massimi e gli attraversamenti si prendono lì sopra. Costa niente, non
assume che il meglio stia al transito — con la Luna che si sposta spesso non
c'è — e vale identico per qualunque positioner, anche per quello degli oggetti
estesi che un domani non avrà un'orbita. Il prezzo è che gli estremi sono
quantizzati al passo, ed è scritto nel risultato (`step_minutes`).

Questo modulo non sa che cosa sia un asteroide: riceve array di RA, Dec, V e
moto già calcolati da qualcun altro.

**Un oggetto o diecimila, la fisica è la stessa funzione.** `sky_geometry`
calcola alt/az, airmass, Sole e Luna **una volta per sito** su coordinate di
forma (N, M) — N oggetti × M istanti — e `observation_windows` ci applica sopra
i limiti di un setup, che è aritmetica. `observation_window` (singolare) è il
caso N = 1 della stessa funzione: due implementazioni della stessa finestra
sarebbero due tarature da tenere allineate, e la pagina Oggetto e il job
notturno devono dire *lo stesso numero*.
"""
from __future__ import annotations

import numpy as np

from core.visibility.geometry import above_horizon, airmass, altaz, angular_separation
from core.visibility.instrument import Setup
from core.visibility.limits import effective_limit, exposure_plan
from core.visibility.night import moon_state, sun_altitude
from core.visibility.site import Site

# Passo della griglia. Cinque minuti sono ~1.2° di rotazione del cielo: sotto
# la risoluzione con cui ha senso pianificare, e sopra la soglia in cui il
# campionamento costerebbe qualcosa.
STEP_MINUTES = 5.0


def night_grid(night: dict, step_minutes: float = STEP_MINUTES) -> np.ndarray:
    """Gli istanti da valutare, dal tramonto all'alba. Vuota se non fa mai notte."""
    inizio, fine = night.get("sunset_jd"), night.get("sunrise_jd")
    if inizio is None or fine is None or fine <= inizio:
        return np.empty(0)
    passo = step_minutes / 1440.0
    return np.arange(inizio, fine + passo / 2, passo)


def _segments(mask: np.ndarray) -> list[tuple[int, int]]:
    """Gli intervalli contigui di `True`, come coppie di indici inclusivi."""
    if not mask.any():
        return []
    bordi = np.diff(mask.astype(np.int8))
    inizi = list(np.flatnonzero(bordi == 1) + 1)
    fini = list(np.flatnonzero(bordi == -1))
    if mask[0]:
        inizi.insert(0, 0)
    if mask[-1]:
        fini.append(len(mask) - 1)
    return list(zip(inizi, fini))


def _longest(mask: np.ndarray) -> tuple[int, int] | None:
    """Il tratto più lungo.

    Un oggetto può avere due tratti in una notte — un profilo di orizzonte con
    una collina in mezzo, o una Luna che sorge e poi tramonta. Si tiene il più
    lungo e si dice quanti erano: fondere due tratti in un intervallo unico
    racconterebbe una finestra che non è mai esistita.
    """
    segmenti = _segments(mask)
    return max(segmenti, key=lambda s: s[1] - s[0]) if segmenti else None


def sky_geometry(site: Site, jd, ra_deg, dec_deg) -> dict:
    """Dove stanno gli oggetti, il Sole e la Luna. **Una volta per sito.**

    Tutto quello che qui dentro non dipende dallo strumento, e non ce n'è
    nessuno che ne dipenda: alt/az, airmass, altezza del Sole, stato della Luna
    e separazione lunare sono proprietà del cielo sopra quel sito. Ogni setup ci
    applica sopra i propri limiti, che è aritmetica su array già pronti — è la
    ragione per cui aggiungere una camera costa poco e aggiungere un sito costa
    (CLAUDE.md).

    Le coordinate si portano a forma (N, M) — N oggetti × M istanti — anche
    quando l'oggetto è uno solo: a valle esiste un caso solo da leggere.
    """
    jd = np.asarray(jd, dtype=float)
    ra = np.atleast_2d(np.asarray(ra_deg, dtype=float))
    dec = np.atleast_2d(np.asarray(dec_deg, dtype=float))

    alt, az = altaz(site, jd, ra, dec)
    luna = moon_state(site, jd)
    return {
        "alt_deg": alt, "az_deg": az, "airmass": airmass(alt),
        "sun_alt_deg": sun_altitude(site, jd),
        "moon": luna,
        "moon_sep_deg": angular_separation(ra, dec, luna["ra_deg"], luna["dec_deg"]),
    }


def observation_windows(*, site: Site, setup: Setup, night: dict, jd,
                        geometry: dict, v_mag, motion_arcsec_min=0.0,
                        step_minutes: float = STEP_MINUTES,
                        ceu_arcsec=None) -> list[dict]:
    """Le finestre di N oggetti per **un** setup, una riga di risultato ciascuno.

    `geometry` viene da `sky_geometry` sullo stesso sito e sulla stessa griglia;
    `v_mag` e `motion_arcsec_min` hanno forma (N, M) — o (M,) per un oggetto
    solo. `ceu_arcsec` è per oggetto: uno scalare, un array (N,) o `None`.

    L'ordine delle righe è quello degli oggetti in ingresso e non cambia: chi
    chiama tiene la corrispondenza con i propri identificatori per posizione, e
    una funzione che riordinasse la romperebbe in silenzio.
    """
    jd = np.asarray(jd, dtype=float)
    v = np.atleast_2d(np.asarray(v_mag, dtype=float))
    n = v.shape[0]
    ceu = _per_oggetto(ceu_arcsec, n)

    if jd.size == 0 or v.shape[1] == 0:
        return [_vuoto(night, step_minutes, 0) for _ in range(n)]

    mu = np.broadcast_to(np.atleast_2d(np.asarray(motion_arcsec_min, dtype=float)),
                         v.shape)
    alt, az, x = geometry["alt_deg"], geometry["az_deg"], geometry["airmass"]
    luna, sep, h_sole = geometry["moon"], geometry["moon_sep_deg"], geometry["sun_alt_deg"]

    limiti = effective_limit(
        site=site, setup=setup, target_alt_deg=alt, motion_arcsec_min=mu,
        moon_alt_deg=luna["alt_deg"], moon_phase_deg=luna["phase_deg"],
        moon_sep_deg=sep, sun_alt_deg=h_sole,
    )
    margine = limiti["eff_vlim"] - v

    # --- le due finestre, per tutti gli oggetti in una volta ----------------
    alt_min = setup.min_altitude_deg if setup.min_altitude_deg is not None else 0.0
    geometrica = (above_horizon(site, alt, az, alt_min)
                  & (x <= setup.max_airmass)
                  & (h_sole <= setup.sun_alt_max_deg))
    utile = geometrica & (margine > 0.0)

    # Quel che resta è per riga, e resta in Python: trovare il tratto contiguo
    # più lungo su ~150 booleani costa microsecondi, mentre la trigonometria —
    # che è il costo vero — è già stata fatta una volta sola qui sopra.
    fisso = {"setup": setup, "night": night, "jd": jd, "step_minutes": step_minutes}
    return [
        _riga(**fisso, alt=alt[i], az=az[i], x=x[i], v=v[i], mu=mu[i],
              margine=margine[i], limiti=_riga_limiti(limiti, v.shape, i),
              sep=sep[i], luna_alt=np.broadcast_to(luna["alt_deg"], v.shape)[i],
              luna_illum=np.broadcast_to(np.asarray(luna["illum"]), v.shape)[i],
              h_sole=np.broadcast_to(h_sole, v.shape)[i],
              geometrica=geometrica[i], utile=utile[i], ceu_arcsec=ceu[i])
        for i in range(n)
    ]


def observation_window(*, site: Site, setup: Setup, night: dict, jd,
                       ra_deg, dec_deg, v_mag, motion_arcsec_min=0.0,
                       step_minutes: float = STEP_MINUTES,
                       ceu_arcsec=None) -> dict:
    """Le due finestre, l'istante migliore, e tutto ciò che serve a spiegarli.

    `jd`, `ra_deg`, `dec_deg`, `v_mag` e `motion_arcsec_min` sono array sulla
    stessa griglia — li produce un positioner, e questo modulo non sa quale.

    L'istante migliore è quello di **massimo margine di profondità**
    (`eff_vlim − V`), non il transito: con la Luna in giro il punto più alto e
    il punto più profondo non coincidono quasi mai, e il transito si riporta
    lo stesso perché è quello che si guarda per capire se il sito è adatto.

    È il caso N = 1 di `observation_windows`, e passa dalla stessa geometria:
    chi guarda un oggetto solo paga il Sole e la Luna per lui, chi ne guarda
    diecimila li paga una volta.
    """
    jd = np.asarray(jd, dtype=float)
    if jd.size == 0:
        return _vuoto(night, step_minutes, 0)
    return observation_windows(
        site=site, setup=setup, night=night, jd=jd,
        geometry=sky_geometry(site, jd, ra_deg, dec_deg),
        v_mag=v_mag, motion_arcsec_min=motion_arcsec_min,
        step_minutes=step_minutes, ceu_arcsec=ceu_arcsec,
    )[0]


def _vuoto(night: dict, step_minutes: float, n_samples: int) -> dict:
    """Il risultato quando non c'è niente da dire. Sempre le stesse chiavi."""
    return {"night_date": night.get("night_date"), "step_minutes": step_minutes,
            "n_samples": int(n_samples), "geo_start_jd": None, "geo_end_jd": None,
            "useful_start_jd": None, "useful_end_jd": None, "useful_hours": 0.0,
            "best_jd": None, "n_segments": 0, "observable": False, "useful": False}


def _per_oggetto(valore, n: int) -> list:
    """Un valore per oggetto: da `None`, uno scalare o un array, sempre `n` voci."""
    if valore is None:
        return [None] * n
    arr = np.atleast_1d(np.asarray(valore, dtype=float))
    return list(np.broadcast_to(arr, (n,)))


# I campi di `effective_limit` che viaggiano nel risultato: hanno tutti la forma
# della griglia. Gli altri (`exposure_s`, `residual`) sono scalari o diagnostica
# e non si affettano per oggetto.
_LIMIT_FIELDS = ("eff_vlim", "eff_vlim_astrometric", "sky_mag",
                 "pen_airmass", "pen_moon", "pen_twilight", "pen_trailing")


def _riga_limiti(limiti: dict, shape: tuple, i: int) -> dict:
    return {k: np.broadcast_to(np.asarray(limiti[k]), shape)[i] for k in _LIMIT_FIELDS}


def _riga(*, setup: Setup, night: dict, jd, step_minutes: float,
          alt, az, x, v, mu, margine, limiti: dict, sep, luna_alt, luna_illum,
          h_sole, geometrica, utile, ceu_arcsec) -> dict:
    """Un oggetto, un setup, una notte: la riga di `observation_window`.

    Tutti gli array sono già ridotti alla singola riga della griglia.
    """
    tratto_geo = _longest(geometrica)
    tratto_utile = _longest(utile)

    if tratto_geo is None:
        return _vuoto(night, step_minutes, jd.size)

    g0, g1 = tratto_geo

    # L'istante migliore si cerca **dentro la finestra utile** se c'è, altrimenti
    # dentro quella geometrica: anche di una notte fallita si vuole sapere qual
    # era il momento meno peggio, o non si capisce di quanto si è mancato.
    dominio = utile if tratto_utile else geometrica
    indici = np.flatnonzero(dominio)
    i_best = indici[np.argmax(margine[indici])]
    i_transito = g0 + int(np.argmax(alt[g0:g1 + 1]))

    piano = exposure_plan(
        setup=setup, v_mag=v[i_best], eff_vlim=limiti["eff_vlim"][i_best],
        motion_arcsec_min=mu[i_best],
        window_hours=((jd[tratto_utile[1]] - jd[tratto_utile[0]]) * 24.0
                      if tratto_utile else 0.0),
    )

    out = {
        "night_date": night.get("night_date"),
        "step_minutes": step_minutes,
        "n_samples": int(jd.size),
        "observable": True,
        "useful": tratto_utile is not None,
        "n_segments": len(_segments(utile if tratto_utile else geometrica)),

        "geo_start_jd": float(jd[g0]),
        "geo_end_jd": float(jd[g1]),
        "geo_hours": float((jd[g1] - jd[g0]) * 24.0),

        "useful_start_jd": float(jd[tratto_utile[0]]) if tratto_utile else None,
        "useful_end_jd": float(jd[tratto_utile[1]]) if tratto_utile else None,
        "useful_hours": float((jd[tratto_utile[1]] - jd[tratto_utile[0]]) * 24.0)
                        if tratto_utile else 0.0,

        "best_jd": float(jd[i_best]),
        # L'indice sulla griglia, non solo l'istante: chi ha altri array sulla
        # stessa griglia — elongazione, angolo di posizione — deve poterli
        # leggere nello stesso punto senza ricostruirlo da `best_jd`, che
        # significherebbe una seconda idea di dove cade il campione.
        "best_index": int(i_best),
        "best_alt_deg": float(alt[i_best]),
        "best_az_deg": float(az[i_best]),
        "best_airmass": float(x[i_best]),
        "transit_jd": float(jd[i_transito]),
        "max_alt_deg": float(alt[i_transito]),

        "v_pred": float(v[i_best]),
        "eff_vlim": float(limiti["eff_vlim"][i_best]),
        "eff_vlim_astrometric": float(limiti["eff_vlim_astrometric"][i_best]),
        "depth_margin": float(margine[i_best]),
        "sky_brightness_mag": float(limiti["sky_mag"][i_best]),
        "pen_airmass": float(limiti["pen_airmass"][i_best]),
        "pen_moon": float(limiti["pen_moon"][i_best]),
        "pen_twilight": float(limiti["pen_twilight"][i_best]),
        "pen_trailing": float(limiti["pen_trailing"][i_best]),

        "moon_sep_deg": float(sep[i_best]),
        "moon_alt_deg": float(luna_alt[i_best]),
        "moon_illum": float(luna_illum[i_best]),
        "sun_alt_deg": float(h_sole[i_best]),

        "motion_arcsec_min": float(mu[i_best]),
        "trail_arcsec": float(mu[i_best] * float(piano["t_sub_s"]) / 60.0),
        "rec_exposure_s": float(piano["t_sub_s"]),
        "rec_n_subs": int(piano["n_subs"]) if np.isfinite(piano["n_subs"]) else None,
        "rec_total_s": float(piano["total_s"]),
        "fits_window": bool(piano["fits_window"]) if piano["fits_window"] is not None else None,
    }
    out.update(_campo(setup, ceu_arcsec))

    # Quanto della finestra geometrica è stato buttato: è il numero che dice se
    # è stata la Luna a rovinare la notte o se l'oggetto era proprio troppo
    # debole. Senza, `useful_hours = 0` non distingue i due casi.
    out["wasted_hours"] = out["geo_hours"] - out["useful_hours"]
    return out


def _campo(setup: Setup, ceu_arcsec) -> dict:
    """L'incertezza di posizione ci sta nel campo, o serve un mosaico?

    Il confronto è con il **lato corto**: un'ellisse di incertezza che sta nel
    lato lungo e non nel corto richiede comunque di puntare bene o di muoversi.
    Tre sigma perché un oggetto perso al primo tentativo costa una notte.
    """
    if ceu_arcsec is None or not np.isfinite(float(ceu_arcsec)):
        return {"fov_fit_arcsec": None, "fov_fit_ratio": None, "needs_mosaic": False}
    incertezza = 3.0 * float(ceu_arcsec)
    lato = setup.fov_min_arcmin * 60.0
    return {
        "fov_fit_arcsec": incertezza,
        "fov_fit_ratio": incertezza / lato,
        "needs_mosaic": bool(incertezza > lato),
    }
