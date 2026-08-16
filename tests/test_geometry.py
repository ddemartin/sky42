"""Alt/az e airmass contro Horizons, dallo stesso sito.

Il confronto è fatto **dando in pasto alla nostra `altaz` le coordinate
astrometriche di Horizons**: così il test misura la rotazione dal cielo al
sito, e non la nostra propagazione (che ha i suoi test).

Verità scaricata il 2026-08-16: `CENTER='coord@399'`,
`SITE_COORD='-70.7647,-30.4728,1.560'`, `QUANTITIES='1,4,8'`, `TIME_TYPE=TT`,
elevazione airless.

Tolleranza dichiarata: **0.02°**. Non è larga per debolezza: l'azimut e
l'altezza di Horizons sono del posto *apparente* e includono l'aberrazione
annua (fino a 20″), mentre le coordinate che gli diamo in pasto sono
astrometriche. Il residuo misurato è 11″, cioè esattamente l'aberrazione, e
scenderebbe solo aggiungendo una correzione che a un telescopio non serve —
per puntare si passa da Horizons.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.visibility.geometry import (
    above_horizon,
    airmass,
    altaz,
    angular_separation,
)
from core.visibility.site import Site

TOL_DEG = 0.02

CILE = Site(latitude=-30.4728, longitude=-70.7647, altitude_m=1560,
            timezone="America/Santiago")

# (JD TT, RA, Dec astrometriche) → (azimut, altezza, airmass) secondo Horizons.
# I primi tre sono la Luna la sera del 2026-08-16 mentre cala verso l'orizzonte
# (48°, 31°, 13°: un caso alto, uno medio e uno dove l'airmass conta davvero),
# il quarto è Cerere che sorge prima dell'alba.
CASI = [
    (2461269.44, 193.909329555, -10.056171528, 291.294787478, 48.970305559, 1.324),
    (2461269.50, 194.416235720, -10.360866284, 276.418861808, 31.440638762, 1.911),
    (2461269.56, 195.019673785, -10.650816047, 265.263368575, 13.463494507, 4.204),
    (2461269.90, 91.490004330, 22.454550275, 50.478856724, 16.493423716, 3.473),
]


@pytest.mark.parametrize("jd,ra,dec,az_h,alt_h,x_h", CASI)
def test_altaz_contro_horizons(jd, ra, dec, az_h, alt_h, x_h):
    alt, az = altaz(CILE, jd, ra, dec)
    assert alt == pytest.approx(alt_h, abs=TOL_DEG)
    # L'azimut si confronta come differenza angolare vera: 359.9 e 0.1 distano
    # 0.2°, non 359.8.
    assert abs((az - az_h + 180) % 360 - 180) < TOL_DEG


@pytest.mark.parametrize("jd,ra,dec,az_h,alt_h,x_h", CASI)
def test_airmass_contro_horizons(jd, ra, dec, az_h, alt_h, x_h):
    """Kasten & Young sull'altezza di Horizons, contro l'airmass di Horizons.

    L'1% di tolleranza è la rifrazione: Horizons calcola la X sull'altezza
    rifratta, che alle basse altezze è mezzo grado più alta. Sopra i 30° le due
    coincidono a tre cifre.
    """
    assert airmass(alt_h) == pytest.approx(x_h, rel=0.01)


def test_la_precessione_non_si_puo_trascurare():
    """Fra J2000 e oggi la precessione vale 22′: un terzo di grado di altezza.

    Se qualcuno «semplificasse» la rotazione usando il tempo siderale medio su
    coordinate J2000 senza precessione, questo test cadrebbe — ed è l'errore
    più facile da fare in tutto il modulo, perché produce numeri credibili.
    """
    jd, ra, dec, _, alt_h, _ = CASI[0]
    alt_giusta, _ = altaz(CILE, jd, ra, dec)
    # Le stesse coordinate 26 anni prima puntano altrove di ~0.35°.
    alt_j2000, _ = altaz(CILE, 2451545.0, ra, dec)
    assert abs(alt_giusta - alt_h) < TOL_DEG
    assert abs(alt_giusta - alt_j2000) > 1.0


def test_airmass_ai_valori_noti():
    """Allo zenit 1, a 60° di distanza zenitale 2, all'orizzonte 38."""
    # Allo zenit esattamente 1. La formula di Kasten & Young darebbe 0.99971 —
    # proprietà nota dell'interpolazione, non un errore — ma un'airmass sotto 1
    # diventa estinzione negativa in `limits.py`, cioè un'atmosfera che
    # illumina. Il pavimento a 1 sta lì per quello.
    assert airmass(90.0) == 1.0
    grezza = 1 / (np.cos(0.0) + 0.50572 * (96.07995 - 0.0) ** -1.6364)
    assert grezza == pytest.approx(0.99971, abs=1e-5)
    assert airmass(30.0) == pytest.approx(2.0, abs=0.01)      # sec z = 2
    # All'orizzonte la formula non diverge: 38 airmass, che è già un modo
    # elegante di dire «no».
    assert airmass(0.0) == pytest.approx(38.0, abs=0.1)
    assert np.isinf(airmass(-5.0)), "sotto l'orizzonte non è un numero grande, è nulla"
    # Perché Kasten & Young e non la secante: a 10° di altezza `sec z`
    # sbaglia del 3%, a 5° dell'11%, a 2° del 47%, e all'orizzonte diverge.
    # Sono proprio le altezze in cui si decide se un oggetto è osservabile.
    assert airmass(10.0) == pytest.approx(5.586, abs=0.01)
    assert 1 / np.cos(np.radians(85)) / airmass(5.0) == pytest.approx(1.113, abs=0.01)


def test_separazione_angolare():
    assert angular_separation(0, 0, 0, 90) == pytest.approx(90.0)
    assert angular_separation(10, 20, 10, 20) == pytest.approx(0.0, abs=1e-12)
    # Attraversando RA = 0: 359° e 1° distano 2°, non 358.
    assert angular_separation(359, 0, 1, 0) == pytest.approx(2.0, abs=1e-9)
    # Vicino al polo la differenza in RA conta poco.
    assert angular_separation(0, 89.9, 180, 89.9) == pytest.approx(0.2, abs=1e-6)
    # Separazioni piccolissime: è il caso per cui non si usa arccos.
    assert angular_separation(10, 20, 10, 20.001) == pytest.approx(0.001, rel=1e-6)


def test_broadcasting_oggetti_per_istanti():
    """La forma dello screening: (N, M) coordinate contro (M,) istanti."""
    jd = np.array([c[0] for c in CASI])
    ra = np.array([[c[1] for c in CASI]] * 3)
    dec = np.array([[c[2] for c in CASI]] * 3)
    alt, az = altaz(CILE, jd, ra, dec)
    assert alt.shape == az.shape == (3, 4)
    for i, c in enumerate(CASI):
        assert alt[0, i] == pytest.approx(c[4], abs=TOL_DEG)
    assert airmass(alt).shape == (3, 4)


def test_orizzonte_del_terreno_e_della_montatura():
    """I due limiti restano distinti fino all'ultimo, e vince il più alto."""
    sito = Site(latitude=45.0, longitude=7.0, horizon=((0, 25.0), (180, 5.0)))
    # A nord il terreno sale a 25°: un oggetto a 20° non si vede, anche se la
    # montatura arriverebbe a 15°.
    assert not above_horizon(sito, 20.0, 0.0, min_altitude_deg=15.0)
    assert above_horizon(sito, 30.0, 0.0, min_altitude_deg=15.0)
    # A sud il terreno è basso, ma la montatura si ferma a 15°.
    assert not above_horizon(sito, 10.0, 180.0, min_altitude_deg=15.0)
    assert above_horizon(sito, 20.0, 180.0, min_altitude_deg=15.0)
    # Senza profilo del terreno decide solo lo strumento.
    piatto = Site(latitude=45.0, longitude=7.0)
    assert np.array_equal(
        above_horizon(piatto, np.array([10.0, 30.0]), np.array([0.0, 0.0]), 20.0),
        np.array([False, True]),
    )
