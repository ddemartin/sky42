"""Elementi orbitali derivati. È l'unico posto in cui si calcola il Tisserand.

Tutte le funzioni accettano scalari o array numpy e restituiscono la stessa
forma: lo stesso codice serve una riga della dashboard e un milione di orbite
in fase di import.
"""
from __future__ import annotations

from math import cos as _cos
from math import radians as _radians
from math import sqrt as _sqrt

import numpy as np

# Semiasse maggiore di Giove. Il valore convenzionale usato in letteratura per
# il Tisserand: cambiarlo renderebbe i nostri Tj non confrontabili con le liste
# pubblicate di asteroidi in orbita cometaria.
A_JUPITER = 5.2038
_A_J = A_JUPITER      # alias locale per il percorso scalare

# Moto medio in gradi/giorno per a = 1 AU (costante di Gauss convertita).
N_AT_1AU_DEG = 0.9856076686


def tisserand(a, e, i_deg):
    """Parametro di Tisserand rispetto a Giove.

        Tj = aJ/a + 2 cos(i) sqrt[(a/aJ)(1 - e²)]

    L'inclinazione è quella eclittica del catalogo (convenzione della
    letteratura, vedi docs/modelli.md). Restituisce NaN dove non è definito:
    a <= 0 (iperboliche) oppure e >= 1.
    """
    a = np.asarray(a, dtype=float)
    e = np.asarray(e, dtype=float)
    i = np.radians(np.asarray(i_deg, dtype=float))

    valid = (a > 0) & (e >= 0) & (e < 1)
    with np.errstate(divide="ignore", invalid="ignore"):
        tj = A_JUPITER / a + 2.0 * np.cos(i) * np.sqrt((a / A_JUPITER) * (1.0 - e * e))
    tj = np.where(valid, tj, np.nan)
    return tj if tj.ndim else float(tj)


def tisserand_scalar(a, e, i_deg):
    """Stessa formula di `tisserand`, per un oggetto solo.

    Esiste perché l'import fa 1,5 milioni di chiamate una alla volta e il
    passaggio da/verso numpy costerebbe più del calcolo. Deve restare
    numericamente identica a `tisserand`: c'è un test che lo verifica.
    """
    if a is None or e is None or i_deg is None:
        return None
    if a <= 0 or e < 0 or e >= 1:
        return None
    return _A_J / a + 2.0 * _cos(_radians(i_deg)) * _sqrt((a / _A_J) * (1.0 - e * e))


def perihelion(a, e):
    """q = a(1-e). Per le iperboliche il catalogo dà q direttamente: non usare qui."""
    a = np.asarray(a, dtype=float)
    e = np.asarray(e, dtype=float)
    q = np.where((a > 0) & (e < 1), a * (1.0 - e), np.nan)
    return q if q.ndim else float(q)


def aphelion(a, e):
    a = np.asarray(a, dtype=float)
    e = np.asarray(e, dtype=float)
    q = np.where((a > 0) & (e < 1), a * (1.0 + e), np.nan)
    return q if q.ndim else float(q)


def period_years(a):
    """Terza legge di Keplero, massa dell'asteroide trascurata."""
    a = np.asarray(a, dtype=float)
    p = np.where(a > 0, np.power(a, 1.5), np.nan)
    return p if p.ndim else float(p)


def mean_motion_deg_day(a):
    a = np.asarray(a, dtype=float)
    n = np.where(a > 0, N_AT_1AU_DEG / np.power(a, 1.5), np.nan)
    return n if n.ndim else float(n)


def semimajor_from_q_e(q, e):
    """a = q/(1-e). NaN per paraboliche e iperboliche, dove `a` non ha senso."""
    q = np.asarray(q, dtype=float)
    e = np.asarray(e, dtype=float)
    a = np.where(e < 1, q / (1.0 - e), np.nan)
    return a if a.ndim else float(a)


def derive_all(a=None, e=None, i_deg=None, q=None) -> dict:
    """Tutti i derivati che finiscono in `orbit`, per un oggetto solo.

    Accetta la coppia (a, e) degli asteroidi o (q, e) delle comete.
    """
    if a is None and q is not None and e is not None:
        a = semimajor_from_q_e(q, e)
    out = {
        "a_au": _clean(a),
        "e": _clean(e),
        "i_deg": _clean(i_deg),
        "q_derived_au": _clean(q if q is not None else perihelion(a, e)),
        "aphelion_au": _clean(aphelion(a, e)) if a is not None else None,
        "period_yr": _clean(period_years(a)) if a is not None else None,
        "n_deg_day": _clean(mean_motion_deg_day(a)) if a is not None else None,
        "tisserand_j": None,
    }
    if a is not None and e is not None and i_deg is not None:
        out["tisserand_j"] = _clean(tisserand(a, e, i_deg))
    return out


def _clean(x):
    """NaN e infiniti diventano NULL: in SQLite un NaN è un valore che mente."""
    if x is None:
        return None
    x = float(x)
    return None if (np.isnan(x) or np.isinf(x)) else x
