"""Notte, crepuscoli e Luna per un sito, contro Horizons.

La verifica è in due mosse, e insieme inchiodano gli eventi a meno di un
decimo di secondo:

1. **La geometria contro Horizons.** Agli istanti indicati, Horizons dice che
   dal sito di Río Hurtado il Sole (o la Luna) sta a una certa altezza: la
   nostra `sun_altitude` deve dare lo stesso numero. Questo verifica
   osservatore topocentrico, effemeridi e conversione dei tempi in una volta.
2. **La ricerca degli eventi contro la geometria.** L'istante che chiamiamo
   «fine del crepuscolo astronomico» deve essere quello in cui *la nostra*
   altezza del Sole vale −18.000.

Verità scaricata il 2026-08-16 con `EPHEM_TYPE=OBSERVER`, `CENTER='coord@399'`,
`SITE_COORD='-70.7647,-30.4728,1.560'` (lon, lat, km), `QUANTITIES='4,10'`,
`TIME_TYPE=TT`, elevazione **airless** — come Skyfield, che non applica
rifrazione: le due convenzioni vanno tenute insieme o si confrontano mele con
pere per qualche primo d'arco.

Tolleranza dichiarata: **0.002°** in altezza, che a Río Hurtado (il Sole scende
di ~0.2°/minuto) vale mezzo secondo di tempo.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.visibility.night import (
    TWILIGHT_ASTRONOMICAL,
    moon_state,
    night_date_for,
    night_events,
    nights,
    sun_altitude,
)
from core.visibility.site import Site

TOL_ALT_DEG = 0.002

CILE = Site(
    latitude=-30.4728, longitude=-70.7647, altitude_m=1560,
    timezone="America/Santiago", sky_zenith_mag=21.8, extinction_k=0.14,
    code="cile-rio-hurtado",
)

NOTTE = "2026-08-16"

# (JD TT, altezza del Sole secondo Horizons). I tre istanti sono il tramonto e
# i due crepuscoli astronomici della notte del 2026-08-16 a Río Hurtado.
SOLE_HORIZONS = [
    (2461269.430518, -0.833131709),
    (2461269.486831, -17.999720421),
    (2461269.913474, -18.000184261),
]

# (JD TT, altezza della Luna, frazione illuminata) al suo tramonto.
LUNA_HORIZONS = (2461269.608397, -0.799770034, 0.2124259)


@pytest.mark.parametrize("jd,alt", SOLE_HORIZONS)
def test_altezza_del_sole_contro_horizons(jd, alt):
    assert sun_altitude(CILE, jd) == pytest.approx(alt, abs=TOL_ALT_DEG)


def test_luna_contro_horizons():
    jd, alt, illum = LUNA_HORIZONS
    m = moon_state(CILE, jd)
    assert m["alt_deg"] == pytest.approx(alt, abs=TOL_ALT_DEG)
    # Frazione illuminata topocentrica: con quella geocentrica lo scarto sarebbe
    # 0.007, la parallasse lunare. Non cambierebbe una brillanza di cielo, ma
    # renderebbe il confronto con Horizons inutile.
    assert float(m["illum"]) == pytest.approx(illum, abs=0.001)


def test_i_crepuscoli_stanno_dove_dicono_di_stare():
    """L'evento e la geometria devono essere d'accordo fra loro."""
    n = night_events(CILE, NOTTE)
    for chiave in ("twilight_end_jd", "twilight_start_jd"):
        assert sun_altitude(CILE, n[chiave]) == pytest.approx(
            TWILIGHT_ASTRONOMICAL, abs=TOL_ALT_DEG)
    for chiave, soglia in (("civil_end_jd", -6.0), ("nautical_end_jd", -12.0),
                           ("civil_start_jd", -6.0), ("nautical_start_jd", -12.0)):
        assert sun_altitude(CILE, n[chiave]) == pytest.approx(soglia, abs=TOL_ALT_DEG)
    # Tramonto e alba: −0.8333°, cioè bordo superiore e rifrazione media, che è
    # la convenzione di tutte le tabelle pubblicate.
    for chiave in ("sunset_jd", "sunrise_jd"):
        assert sun_altitude(CILE, n[chiave]) == pytest.approx(-0.8333, abs=TOL_ALT_DEG)


def test_gli_eventi_sono_quelli_di_horizons():
    """Gli istanti calcolati coincidono con quelli verificati sopra, a 2 secondi."""
    n = night_events(CILE, NOTTE)
    due_secondi = 2.0 / 86400.0
    assert n["sunset_jd"] == pytest.approx(SOLE_HORIZONS[0][0], abs=due_secondi)
    assert n["twilight_end_jd"] == pytest.approx(SOLE_HORIZONS[1][0], abs=due_secondi)
    assert n["twilight_start_jd"] == pytest.approx(SOLE_HORIZONS[2][0], abs=due_secondi)
    assert n["moon_set_jd"] == pytest.approx(LUNA_HORIZONS[0], abs=due_secondi)


def test_l_ordine_della_notte():
    """Gli eventi si susseguono nell'ordine giusto: sembra ovvio, e non lo è.

    È il controllo che accorge di una notte agganciata al giorno sbagliato: se
    la finestra fosse ancorata alla mezzanotte UTC invece che al mezzogiorno
    locale, in Cile il tramonto uscirebbe *dopo* l'alba.
    """
    n = night_events(CILE, NOTTE)
    sequenza = [n["sunset_jd"], n["civil_end_jd"], n["nautical_end_jd"],
                n["twilight_end_jd"], n["twilight_start_jd"],
                n["nautical_start_jd"], n["civil_start_jd"], n["sunrise_jd"]]
    assert sequenza == sorted(sequenza)
    assert n["dark_hours"] == pytest.approx(
        (n["twilight_start_jd"] - n["twilight_end_jd"]) * 24, abs=1e-9)
    # Agosto in Cile è inverno: notte lunga, ma non lunghissima a −30°.
    assert 9.5 < n["dark_hours"] < 11.0


def test_la_notte_e_quella_della_sera():
    """Le due di notte del 17 appartengono alla notte del 16."""
    n = night_events(CILE, NOTTE)
    meta = 0.5 * (n["twilight_end_jd"] + n["twilight_start_jd"])
    assert night_date_for(CILE, meta) == NOTTE
    assert night_date_for(CILE, n["sunset_jd"]) == NOTTE
    assert night_date_for(CILE, n["sunrise_jd"]) == NOTTE


def test_sole_di_mezzanotte_e_notte_polare():
    """A Tromsø d'estate non fa mai buio, d'inverno il Sole non sorge.

    Nessuno dei due è un errore, e nessuno dei due deve produrre uno zero
    silenzioso: la differenza fra «zero ore di buio» e «non lo so» è tutta la
    differenza fra un sito inutile quella notte e un bug.
    """
    tromso = Site(latitude=69.65, longitude=18.96, altitude_m=100,
                  timezone="Europe/Oslo")

    estate = night_events(tromso, "2026-06-21")
    assert estate["sunset_jd"] is None          # il Sole non tramonta
    assert estate["dark_hours"] == 0.0

    inverno = night_events(tromso, "2026-12-21")
    assert inverno["sunrise_jd"] is None        # il Sole non sorge
    assert inverno["dark_hours"] > 12.0
    assert sun_altitude(tromso, inverno["twilight_end_jd"]) == pytest.approx(
        TWILIGHT_ASTRONOMICAL, abs=TOL_ALT_DEG)


def test_la_luna_alta_di_giorno_non_conta():
    """`moon_max_alt_deg` è il disturbo notturno, non l'altezza astronomica.

    Nella notte del 2026-08-16 la Luna culmina a 69° ma di giorno; fra tramonto
    e alba non supera i 52°. Contare il culmine diurno significherebbe scartare
    un cielo che era buio.
    """
    n = night_events(CILE, NOTTE)
    assert n["moon_max_alt_deg"] < 60.0
    campioni = np.linspace(n["sunset_jd"], n["sunrise_jd"], 200)
    assert n["moon_max_alt_deg"] == pytest.approx(
        max(moon_state(CILE, campioni)["alt_deg"]), abs=0.05)


def test_piu_notti_di_fila():
    tre = nights(CILE, NOTTE, 3)
    assert [x["night_date"] for x in tre] == ["2026-08-16", "2026-08-17", "2026-08-18"]
    # La Luna cresce di ~6 punti al giorno in questa fase: se due notti dessero
    # la stessa illuminazione, staremmo calcolando due volte la stessa notte.
    assert tre[0]["moon_illum"] < tre[1]["moon_illum"] < tre[2]["moon_illum"]


def test_orizzonte_locale_interpolato():
    """Il profilo del terreno si interpola in azimut, chiudendo il cerchio."""
    sito = Site(latitude=45.0, longitude=7.0,
                horizon=((0, 20.0), (90, 10.0), (180, 30.0), (270, 10.0)))
    assert sito.horizon_altitude(0) == pytest.approx(20.0)
    assert sito.horizon_altitude(45) == pytest.approx(15.0)
    assert sito.horizon_altitude(135) == pytest.approx(20.0)
    # Fra 270° e 360° si passa per nord: 315° sta a metà fra 10 e 20.
    assert sito.horizon_altitude(315) == pytest.approx(15.0)
    assert np.all(Site(latitude=0, longitude=0).horizon_altitude([0, 90, 180]) == 0)


def test_site_da_una_riga_di_observatory():
    riga = {
        "code": "cile", "latitude": -30.4728, "longitude": -70.7647,
        "altitude_m": 1560, "timezone": "America/Santiago",
        "sky_zenith_mag": 21.8, "extinction_k": 0.14,
        "horizon_json": "[[0.0, 22.0], [180.0, 30.0]]",
    }
    s = Site.from_row(riga)
    assert s.horizon == ((0.0, 22.0), (180.0, 30.0))
    assert s.horizon_altitude(90) == pytest.approx(26.0)
    assert Site.from_row({**riga, "horizon_json": None}).horizon is None
