"""Da RA/Dec ad altezza, azimut e airmass, per un sito e un array di istanti.

Il costo scala con gli **istanti**, non con gli oggetti: la rotazione dal cielo
al sito dipende solo dal tempo, quindi si calcola una volta per epoca e poi si
fanno prodotti scalari. Diecimila oggetti su cento istanti sono cento matrici e
un milione di moltiplicazioni, non un milione di conversioni di coordinate.

Questo modulo non sa che cosa siano gli oggetti di cui riceve le coordinate
(regola 4): un asteroide, una cometa e una galassia sono tre array di RA e Dec.

**Le coordinate in ingresso sono geocentriche e astrometriche**, come le dà il
positioner. La parallasse diurna (8.8″/Δ in AU) sposta l'altezza di 0.05° per un
NEO a 0.05 AU e di un millesimo di grado per la fascia principale: irrilevante
per decidere *se* si vede, e irrilevante per l'airmass. Per puntare si passa da
Horizons, e allora la parallasse la mette lui.
"""
from __future__ import annotations

import numpy as np

from core.ephemeris import kernel_and_timescale
from core.visibility.site import Site

# Kasten & Young (1989), airmass in funzione della distanza zenitale in gradi.
# Vale fino all'orizzonte, dove `sec z` diverge. Scarto misurato della secante:
# 0.3% a 30° di altezza, 3% a 10°, 11% a 5°, 47% a 2° — cioè esattamente nella
# fascia in cui si decide se un oggetto è osservabile.
_KY_A, _KY_B, _KY_C = 0.50572, 96.07995, 1.6364


def local_frame(site: Site, jd) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Zenit, nord ed est del sito come versori ICRF, agli istanti dati.

    Passa dalla rotazione ITRS→ICRS di Skyfield, che contiene precessione,
    nutazione, tempo siderale e moto dei poli. È la parte che *deve* essere
    esatta: fra J2000 e oggi la precessione vale 22 primi d'arco, cioè un terzo
    di grado di altezza buttato via se si trascura.
    """
    from skyfield.framelib import itrs

    _, ts = kernel_and_timescale()
    t = ts.tt_jd(np.asarray(jd, dtype=float))

    lat = np.radians(site.latitude)
    lon = np.radians(site.longitude)
    zenit = np.array([np.cos(lat) * np.cos(lon), np.cos(lat) * np.sin(lon), np.sin(lat)])
    nord = np.array([-np.sin(lat) * np.cos(lon), -np.sin(lat) * np.sin(lon), np.cos(lat)])
    est = np.array([-np.sin(lon), np.cos(lon), 0.0])

    # `rotation_at` porta da ICRS a ITRS; i versori del sito sono definiti in
    # ITRS, quindi si usa la trasposta per riportarli in cielo.
    rot = itrs.rotation_at(t)                      # (3, 3) oppure (3, 3, n)
    if rot.ndim == 2:
        return rot.T @ zenit, rot.T @ nord, rot.T @ est
    return (np.einsum("jin,j->ni", rot, zenit),
            np.einsum("jin,j->ni", rot, nord),
            np.einsum("jin,j->ni", rot, est))


def unit_vector(ra_deg, dec_deg) -> np.ndarray:
    """Versore ICRF da RA e Dec in gradi, forma (..., 3)."""
    ra = np.radians(np.asarray(ra_deg, dtype=float))
    dec = np.radians(np.asarray(dec_deg, dtype=float))
    return np.stack([np.cos(dec) * np.cos(ra), np.cos(dec) * np.sin(ra), np.sin(dec)],
                    axis=-1)


def altaz(site: Site, jd, ra_deg, dec_deg):
    """Altezza e azimut in gradi. Azimut da nord verso est, 0-360.

    `jd`, `ra_deg` e `dec_deg` si combinano con le regole di broadcasting: la
    forma tipica dello screening è `jd` di forma (M,) e coordinate (N, M).
    """
    zenit, nord, est = local_frame(site, jd)
    v = unit_vector(ra_deg, dec_deg)

    su = np.sum(v * zenit, axis=-1)
    n = np.sum(v * nord, axis=-1)
    e = np.sum(v * est, axis=-1)

    alt = np.degrees(np.arcsin(np.clip(su, -1.0, 1.0)))
    az = np.degrees(np.arctan2(e, n)) % 360.0
    return alt, az


def airmass(alt_deg):
    """Airmass di Kasten & Young (1989). Sotto l'orizzonte è infinita, non negativa.

        X = 1 / [cos z + 0.50572 (96.07995 − z)^(−1.6364)]

    Il valore è quello *geometrico*, senza rifrazione: alle basse altezze la
    rifrazione alza l'oggetto di mezzo grado e Horizons riporta una X un po'
    più bassa (4.204 contro 4.208 a 13°). La differenza è nell'ordine del
    percento e sotto l'incertezza di qualunque modello di trasparenza.

    All'orizzonte esatto la formula vale 38 e non diverge: non serve nessun
    troncamento, e infatti non ce n'è uno. Sotto l'orizzonte il risultato è
    `inf`, che è la risposta giusta — un oggetto tramontato non ha una via
    d'aria un po' lunga, non ce l'ha proprio.
    """
    alt = np.asarray(alt_deg, dtype=float)
    z = 90.0 - alt
    with np.errstate(invalid="ignore", divide="ignore"):
        denom = np.cos(np.radians(z)) + _KY_A * np.power(np.maximum(_KY_B - z, 1e-9), -_KY_C)
        x = np.where(denom > 0, 1.0 / denom, np.inf)
    x = np.where(alt >= 0.0, x, np.inf)
    return x if np.ndim(x) else float(x)


def angular_separation(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
    """Separazione angolare in gradi, dalla formula dell'emisenoverso.

    Non `arccos` del prodotto scalare: per separazioni piccole — che sono
    proprio quelle che interessano quando si chiede «quanto dista dalla Luna» —
    l'arcocoseno perde metà delle cifre significative.
    """
    ra1, dec1 = np.radians(np.asarray(ra1_deg, dtype=float)), np.radians(np.asarray(dec1_deg, dtype=float))
    ra2, dec2 = np.radians(np.asarray(ra2_deg, dtype=float)), np.radians(np.asarray(dec2_deg, dtype=float))
    d_ra, d_dec = ra2 - ra1, dec2 - dec1
    a = np.sin(d_dec / 2.0) ** 2 + np.cos(dec1) * np.cos(dec2) * np.sin(d_ra / 2.0) ** 2
    sep = 2.0 * np.arcsin(np.sqrt(np.clip(a, 0.0, 1.0)))
    return np.degrees(sep)


def above_horizon(site: Site, alt_deg, az_deg, min_altitude_deg: float = 0.0):
    """È sopra *tutti* gli orizzonti: quello del terreno e quello dello strumento.

    Le due cose restano separate fino a qui perché sono di due proprietari
    diversi — il profilo del terreno appartiene al sito, l'altezza minima alla
    montatura — e perché il giorno in cui si aggiunge un telescopio al sito
    l'orizzonte non cambia.
    """
    alt = np.asarray(alt_deg, dtype=float)
    limite = np.maximum(site.horizon_altitude(az_deg), float(min_altitude_deg))
    return alt >= limite
