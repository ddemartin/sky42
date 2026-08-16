"""Il contratto verso il resto del mondo: `positions(body, jd)`.

Chi sta a valle — visibilità, finestre, ranking, pagine — riceve array di
RA/Dec/Δ/r/V/moto e **non sa** con quale modello sono stati prodotti. È la
regola 4 al contrario: il visibility engine non deve sapere cosa sia
un'anomalia media, e per riuscirci qualcuno deve fargli da traduttore. Questo
è il traduttore.

Il giorno degli oggetti deep sky, `positions` per una riga di `fixed_target`
sarà un'altra funzione con la stessa firma e lo stesso dizionario di ritorno:
è la ragione per cui il valore di ritorno non contiene niente di orbitale.

Tutto è geocentrico e **astrometrico**: posizione corretta per tempo luce,
senza aberrazione annua né rifrazione, cioè esattamente la quantità 1 di
Horizons. Il passaggio a topocentrico appartiene al visibility engine, che è
l'unico a sapere che esistono i siti.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields

import numpy as np

from core.ephemeris import earth_equatorial, ecliptic_to_equatorial
from core.orbits import photometry
from core.orbits.kepler import heliocentric_state

# Velocità della luce in AU/giorno (IAU 2012, esatta per definizione dell'AU).
C_AU_DAY = 173.1446326846693

# Mezz'ora avanti e indietro per il moto apparente: differenze finite sulla
# stessa funzione di posizione, non una formula chiusa. Così il moto vale
# identico per asteroidi, comete e qualunque positioner futuro
# (docs/modelli.md §3), e nessuno deve derivare a mano una nuova espressione
# ogni volta che cambia il modello.
MOTION_DT_DAYS = 30.0 / 1440.0


@dataclass(frozen=True)
class Body:
    """Ciò che serve per calcolare una posizione: elementi più fotometria.

    I campi accettano scalari o array: passando colonne di forma (N, 1) e
    un array di epoche (M,) si ottiene la griglia (N, M) che serve allo
    screening, senza cicli Python.
    """

    epoch_jd: object
    e: object
    i_deg: object
    node_deg: object
    argp_deg: object
    a_au: object = None
    m_deg: object = None
    q_au: object = None
    tp_jd: object = None
    is_comet: object = False
    h_mag: object = None
    g_slope: object = None
    m1: object = None
    k1: object = None

    @classmethod
    def from_row(cls, row: Mapping) -> "Body":
        """Da una riga `target` ⋈ `orbit`. Le chiavi in più vengono ignorate."""
        noti = {f.name for f in fields(cls)}
        dati = {k: v for k, v in row.items() if k in noti}
        if "is_comet" not in dati:
            # `kind` e non «ha un m1»: il sistema fotometrico lo decide
            # l'identità dell'oggetto, non quali colonne sono piene.
            dati["is_comet"] = row.get("kind") == "comet"
        return cls(**dati)

    @classmethod
    def from_rows(cls, rows) -> "Body":
        """Molte righe in un solo Body con colonne (N, 1), pronto per la griglia."""
        righe = list(rows)
        singoli = [cls.from_row(r) for r in righe]

        def colonna(nome):
            valori = [getattr(b, nome) for b in singoli]
            if all(v is None for v in valori):
                return None
            if nome == "is_comet":
                return np.array([bool(v) for v in valori])[:, None]
            return np.array([np.nan if v is None else float(v) for v in valori])[:, None]

        return cls(**{f.name: colonna(f.name) for f in fields(cls)})

    def _kepler_args(self) -> dict:
        return {
            "epoch_jd": self.epoch_jd, "e": self.e, "i_deg": self.i_deg,
            "node_deg": self.node_deg, "argp_deg": self.argp_deg,
            "a_au": self.a_au, "m_deg": self.m_deg,
            "q_au": self.q_au, "tp_jd": self.tp_jd,
        }


def heliocentric_equatorial(body: Body, jd) -> np.ndarray:
    """Posizione eliocentrica in coordinate equatoriali ICRF, forma (..., 3)."""
    pos, _ = heliocentric_state(jd, **body._kepler_args())
    return ecliptic_to_equatorial(pos)


def _astrometric(body: Body, jd):
    """Vettore geocentrico corretto per tempo luce, e le distanze che ne seguono.

    Una sola iterazione: il residuo è sotto 0.1″ per Δ < 5 AU perché la
    correzione è quadratica nel piccolo spostamento (docs/modelli.md §3). Farne
    due costerebbe un terzo del tempo di tutto lo screening per un guadagno che
    nessun telescopio vede.
    """
    jd = np.asarray(jd, dtype=float)
    terra = earth_equatorial(jd)                        # (..., 3), eliocentrica

    obj = heliocentric_equatorial(body, jd)
    rel = obj - terra
    tau = np.linalg.norm(rel, axis=-1) / C_AU_DAY

    obj = heliocentric_equatorial(body, jd - tau)       # dove *era* quando è partita la luce
    rel = obj - terra

    delta = np.linalg.norm(rel, axis=-1)
    r = np.linalg.norm(obj, axis=-1)
    r_terra = np.linalg.norm(terra, axis=-1)
    return rel, delta, r, r_terra


def _radec(rel: np.ndarray):
    ra = np.degrees(np.arctan2(rel[..., 1], rel[..., 0])) % 360.0
    dec = np.degrees(np.arcsin(rel[..., 2] / np.linalg.norm(rel, axis=-1)))
    return ra, dec


def positions(body: Body, jd, with_motion: bool = True) -> dict:
    """RA, Dec, Δ, r, V e moto apparente. Il contratto di tutto ciò che sta a valle.

    Restituisce un dizionario di array (o di float, se gli ingressi sono
    scalari) con:

        ra_deg, dec_deg      astrometriche J2000, gradi
        delta_au, r_au       distanze geocentrica ed eliocentrica
        elong_deg            elongazione solare
        phase_deg            angolo di fase
        v_mag                magnitudine prevista
        v_reliable           False dove la funzione di fase è estrapolata
        motion_arcsec_min    moto apparente totale, e le sue due componenti
        motion_pa_deg        angolo di posizione del moto, 0 = nord, 90 = est
    """
    rel, delta, r, r_terra = _astrometric(body, jd)
    ra, dec = _radec(rel)

    with np.errstate(invalid="ignore", divide="ignore"):
        # Legge dei coseni sul triangolo Sole-Terra-oggetto. Il `clip` non è
        # cosmetico: a distanze molto piccole l'arrotondamento porta il coseno
        # a 1.0000000002 e arccos restituirebbe NaN proprio sugli oggetti
        # vicini, che sono quelli che interessano.
        cos_fase = np.clip((r * r + delta * delta - r_terra * r_terra)
                           / (2.0 * r * delta), -1.0, 1.0)
        cos_elong = np.clip((delta * delta + r_terra * r_terra - r * r)
                            / (2.0 * delta * r_terra), -1.0, 1.0)
    fase = np.degrees(np.arccos(cos_fase))
    elong = np.degrees(np.arccos(cos_elong))

    v = photometry.apparent_magnitude(
        is_comet=body.is_comet, r_au=r, delta_au=delta, phase_deg=fase,
        h_mag=body.h_mag, g_slope=body.g_slope, m1=body.m1, k1=body.k1,
    )
    affidabile = photometry.phase_reliable(fase) | np.asarray(body.is_comet, dtype=bool)

    out = {
        "ra_deg": ra, "dec_deg": dec,
        "delta_au": delta, "r_au": r, "r_earth_au": r_terra,
        "elong_deg": elong, "phase_deg": fase,
        "v_mag": v, "v_reliable": affidabile,
    }

    if with_motion:
        out.update(_motion(body, jd))
    return out


def _motion(body: Body, jd) -> dict:
    """Moto apparente per differenze finite, in arcosecondi al minuto."""
    jd = np.asarray(jd, dtype=float)
    prima, _, _, _ = _astrometric(body, jd - MOTION_DT_DAYS)
    dopo, _, _, _ = _astrometric(body, jd + MOTION_DT_DAYS)
    ra0, dec0 = _radec(prima)
    ra1, dec1 = _radec(dopo)

    minuti = 2.0 * MOTION_DT_DAYS * 1440.0
    # (ra1 − ra0 + 180) mod 360 − 180: senza il rientro, un oggetto che passa
    # per RA = 0 mostrerebbe un moto di 360° in un'ora.
    d_ra = ((ra1 - ra0 + 180.0) % 360.0 - 180.0) * 3600.0 / minuti
    d_dec = (dec1 - dec0) * 3600.0 / minuti
    d_ra_cos = d_ra * np.cos(np.radians((dec0 + dec1) / 2.0))

    return {
        "motion_ra_arcsec_min": d_ra_cos,
        "motion_dec_arcsec_min": d_dec,
        "motion_arcsec_min": np.hypot(d_ra_cos, d_dec),
        "motion_pa_deg": np.degrees(np.arctan2(d_ra_cos, d_dec)) % 360.0,
    }
