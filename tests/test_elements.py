"""Il Tisserand con numeri veri.

I valori attesi non sono "quello che restituisce il codice": sono presi dagli
elementi pubblicati e confrontati con i valori di letteratura. La tolleranza è
dichiarata, non aggiustata finché passa.
"""
from __future__ import annotations

import numpy as np

from core.orbits import elements as el


def test_tisserand_ceres():
    """(1) Ceres, elementi MPCORB del 2026-08-15. Valore atteso ~3.31."""
    tj = el.tisserand(2.7655526, 0.0796923, 10.58803)
    assert abs(tj - 3.31) < 0.01


def test_tisserand_encke():
    """2P/Encke: cometa di famiglia gioviana, Tj ~3.03.

    Serve a coprire il caso che interessa davvero al progetto: un oggetto
    appena sopra la soglia, dove il segno della disuguaglianza conta.
    """
    tj = el.tisserand(2.2155, 0.8480, 11.78)
    assert 3.0 < tj < 3.06


def test_tisserand_non_definito():
    """Iperboliche e paraboliche non hanno Tisserand: NaN, non un numero finto."""
    assert np.isnan(el.tisserand(-3.0, 1.2, 44.0))
    assert np.isnan(el.tisserand(2.0, 1.0, 10.0))


def test_scalare_identico_al_vettoriale():
    """`tisserand_scalar` esiste solo per velocità: se diverge, è un bug muto."""
    rng = np.random.default_rng(42)
    for _ in range(200):
        a = float(rng.uniform(0.5, 40.0))
        e = float(rng.uniform(0.0, 0.99))
        i = float(rng.uniform(0.0, 180.0))
        assert abs(el.tisserand_scalar(a, e, i) - float(el.tisserand(a, e, i))) < 1e-12


def test_tisserand_vettoriale_su_array():
    a = np.array([2.7655526, 2.2155, -3.0])
    e = np.array([0.0796923, 0.8480, 1.2])
    i = np.array([10.58803, 11.78, 44.0])
    tj = el.tisserand(a, e, i)
    assert tj.shape == (3,)
    assert np.isnan(tj[2])


def test_derivati():
    d = el.derive_all(a=2.7655526, e=0.0796923, i_deg=10.58803)
    assert abs(d["q_derived_au"] - 2.5451) < 1e-3      # MPCORB: Perihelion_dist 2.5451594
    assert abs(d["aphelion_au"] - 2.9859) < 1e-3       # MPCORB: Aphelion_dist  2.9859458
    assert abs(d["period_yr"] - 4.5991) < 1e-3         # MPCORB: Orbital_period 4.5991003
    assert abs(d["n_deg_day"] - 0.21430445) < 1e-6     # MPCORB: n


def test_semiasse_da_q_e():
    """Per le comete il catalogo dà q: `a` si ricava, e per le iperboliche non esiste."""
    assert abs(el.semimajor_from_q_e(0.5871, 0.9673) - 17.96) < 0.05   # 1P/Halley
    assert np.isnan(el.semimajor_from_q_e(2.0, 3.35))                  # 2I/Borisov
