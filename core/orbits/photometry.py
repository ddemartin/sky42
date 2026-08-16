"""Magnitudine prevista. Due sistemi che non si mescolano mai.

Gli asteroidi usano H-G (Bowell et al. 1989), le comete la magnitudine totale
M1/K1. Non sono due varianti della stessa formula: una cometa con una H
asteroidale è un bug, non un'approssimazione, e per questo le due funzioni non
condividono niente e `apparent_magnitude` sceglie su una maschera esplicita.

La fotometria cometaria **sbaglia regolarmente di 2-3 magnitudini**: è un
ordinamento, non una previsione. Chi la mostra deve dirlo (docs/modelli.md §4).
"""
from __future__ import annotations

import numpy as np

# Coefficienti delle funzioni di fase H-G, Bowell et al. 1989 (Asteroids II).
_A1, _B1 = 3.33, 0.63
_A2, _B2 = 1.87, 1.22

# Pendenza di default quando il catalogo non dà G. È il valore convenzionale
# usato dall'MPC e da JPL per gli oggetti senza fotometria dedicata.
G_DEFAULT = 0.15

# Oltre questo angolo di fase la funzione H-G è fuori dal suo dominio di
# validità: la si continua a calcolare, ma il valore va marcato inaffidabile
# invece di essere mostrato come se fosse buono.
PHASE_VALID_MAX_DEG = 120.0

# Pendenza cometaria di default: MPC pubblica k ≈ 4 quando non ha di meglio.
K1_DEFAULT = 4.0


def hg_magnitude(h_mag, r_au, delta_au, phase_deg, g_slope=None):
    """V = H + 5 log₁₀(r Δ) − 2.5 log₁₀[(1−G) Φ₁ + G Φ₂].

    Restituisce NaN dove H manca: una magnitudine inventata entrerebbe nel
    ranking indistinguibile da una misurata.
    """
    h = np.asarray(h_mag, dtype=float)
    r = np.asarray(r_au, dtype=float)
    d = np.asarray(delta_au, dtype=float)
    alpha = np.radians(np.asarray(phase_deg, dtype=float))
    g = G_DEFAULT if g_slope is None else np.asarray(g_slope, dtype=float)
    g = np.where(np.isfinite(g), g, G_DEFAULT)

    with np.errstate(invalid="ignore", divide="ignore"):
        tan_half = np.tan(np.clip(alpha, 0.0, np.pi - 1e-9) / 2.0)
        phi1 = np.exp(-_A1 * np.power(tan_half, _B1))
        phi2 = np.exp(-_A2 * np.power(tan_half, _B2))
        # A fase zero tan(α/2) = 0 e le due Φ valgono 1: il termine si annulla,
        # ma `0**0.63` in numpy dà 0 e non NaN, quindi non serve un caso a parte.
        v = h + 5.0 * np.log10(r * d) - 2.5 * np.log10((1.0 - g) * phi1 + g * phi2)
    v = np.where(np.isfinite(h), v, np.nan)
    return v if np.ndim(v) else float(v)


def comet_magnitude(m1, r_au, delta_au, k1=None):
    """m1 = M1 + 5 log₁₀(Δ) + 2.5·k1·log₁₀(r).

    **Attenzione alla convenzione, che ha due forme con lo stesso nome.** MPC
    pubblica in CometEls il parametro `k` (tipicamente 4, e nei nostri dati
    va da 2 a 16); JPL pubblica invece il coefficiente già moltiplicato per
    2.5, cioè 10 dove MPC scrive 4. Qui entra il `k1` **dell'MPC**, che è
    quello che sta nella colonna `orbit.k1`, e il 2.5 lo mette la formula.
    Scambiare le due dà due magnitudini e mezzo di errore su una cometa a
    r = 2 AU, in silenzio.
    """
    m = np.asarray(m1, dtype=float)
    r = np.asarray(r_au, dtype=float)
    d = np.asarray(delta_au, dtype=float)
    k = K1_DEFAULT if k1 is None else np.asarray(k1, dtype=float)
    k = np.where(np.isfinite(k), k, K1_DEFAULT)

    with np.errstate(invalid="ignore", divide="ignore"):
        v = m + 5.0 * np.log10(d) + 2.5 * k * np.log10(r)
    v = np.where(np.isfinite(m), v, np.nan)
    return v if np.ndim(v) else float(v)


def phase_reliable(phase_deg) -> np.ndarray:
    """Dove H-G è dentro il suo dominio. Si salva accanto alla magnitudine."""
    a = np.asarray(phase_deg, dtype=float)
    return (a >= 0.0) & (a <= PHASE_VALID_MAX_DEG)


def apparent_magnitude(*, is_comet, r_au, delta_au, phase_deg,
                       h_mag=None, g_slope=None, m1=None, k1=None):
    """La magnitudine giusta per ciascun oggetto, su array misti.

    `is_comet` è una maschera booleana e non un tentativo di indovinare dal
    catalogo: la scelta del sistema fotometrico appartiene a `target.kind`, e
    un oggetto senza il parametro del suo sistema resta NaN anche se ha quello
    dell'altro.
    """
    is_comet = np.asarray(is_comet, dtype=bool)
    forma = np.broadcast(np.asarray(r_au, dtype=float), is_comet).shape

    asteroide = np.broadcast_to(
        hg_magnitude(np.nan if h_mag is None else h_mag, r_au, delta_au, phase_deg, g_slope),
        forma,
    )
    cometa = np.broadcast_to(
        comet_magnitude(np.nan if m1 is None else m1, r_au, delta_au, k1), forma
    )
    v = np.where(is_comet, cometa, asteroide)
    return v if v.ndim else float(v)
