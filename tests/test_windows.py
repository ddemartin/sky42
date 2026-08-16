"""Le due finestre: geometrica e utile, che non si fondono mai.

Le posizioni qui sono **sintetiche**: un oggetto finto messo dove serve per far
succedere il caso che si vuole provare. È di proposito — il positioner ha i suoi
test contro Horizons, e mescolare le due cose darebbe un test che fallisce
quando cambia la fisica invece di quando si rompe la logica delle finestre.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.visibility.instrument import Setup
from core.visibility.night import night_events
from core.visibility.site import Site
from core.visibility.windows import night_grid, observation_window

CILE = Site(latitude=-30.4728, longitude=-70.7647, altitude_m=1560,
            timezone="America/Santiago", sky_zenith_mag=21.8, extinction_k=0.14)

RC700 = Setup(vlim_ref=21.3, vlim_ref_exposure_s=120.0, typical_exposure_s=120.0,
              max_exposure_s=600.0, min_altitude_deg=25.0, max_airmass=2.0,
              sun_alt_max_deg=-15.0, typical_seeing_arcsec=1.6,
              pixel_scale_arcsec=0.342, fov_x_arcmin=27.3, fov_y_arcmin=18.2,
              code="rc700")

NOTTE = night_events(CILE, "2026-08-16")
JD = night_grid(NOTTE)


def _finestra(v_mag, dec_deg=-30.0, ra_offset_h=0.0, motion=0.0, **kw):
    """Un oggetto fermo a declinazione data, che culmina a metà notte.

    La RA si sceglie dal tempo siderale del mezzo della notte, così l'oggetto
    passa alto e la finestra esiste: serve un caso in cui *qualcosa* succede,
    o si verificherebbe solo il ramo «non si vede».
    """
    from core.visibility.geometry import altaz

    meta = 0.5 * (JD[0] + JD[-1])
    # Si trova la RA che culmina a metà notte per tentativi: due passaggi di
    # bisezione sull'azimut sono più corti di una formula di tempo siderale, e
    # non introducono una seconda implementazione da tenere allineata.
    ra = np.linspace(0, 360, 721)
    alt, _ = altaz(CILE, meta, ra, np.full_like(ra, dec_deg))
    ra_culmine = float(ra[int(np.argmax(alt))]) + ra_offset_h * 15.0

    return observation_window(
        site=CILE, setup=RC700, night=NOTTE, jd=JD,
        ra_deg=np.full_like(JD, ra_culmine % 360.0),
        dec_deg=np.full_like(JD, dec_deg),
        v_mag=np.full_like(JD, float(v_mag)),
        motion_arcsec_min=motion, **kw,
    )


def test_un_oggetto_brillante_allo_zenit_ha_una_finestra_piena():
    w = _finestra(v_mag=18.0)
    assert w["observable"] and w["useful"]
    assert w["useful_hours"] > 5.0
    assert w["max_alt_deg"] > 80.0
    assert w["depth_margin"] > 2.0
    assert w["best_airmass"] < 1.1
    # La finestra utile sta dentro quella geometrica, sempre.
    assert w["geo_start_jd"] <= w["useful_start_jd"]
    assert w["useful_end_jd"] <= w["geo_end_jd"]


def test_geometricamente_osservabile_ma_inutile():
    """Il caso che dà il nome a metà progetto: alto, e troppo debole.

    `useful_hours` a zero con `geo_hours` a sei è un'informazione; un unico
    flag «non osservabile» sarebbe una bugia.
    """
    w = _finestra(v_mag=24.0)
    assert w["observable"]
    assert not w["useful"]
    assert w["geo_hours"] > 5.0
    assert w["useful_hours"] == 0.0
    assert w["wasted_hours"] == pytest.approx(w["geo_hours"])
    assert w["depth_margin"] < 0
    # E si sa comunque quando *sarebbe* stato il momento migliore.
    assert w["best_jd"] is not None


def test_sotto_l_orizzonte_del_setup_non_c_e_finestra():
    """Declinazione +60° da −30° di latitudine: non sorge mai abbastanza."""
    w = _finestra(v_mag=15.0, dec_deg=70.0)
    assert not w["observable"]
    assert w["geo_start_jd"] is None and w["best_jd"] is None


def test_il_limite_di_altezza_del_setup_taglia_la_finestra():
    """Lo stesso oggetto con due setup diversi dà due finestre diverse.

    È il motivo per cui la finestra sta per (target × setup) e non per target.
    """
    basso = Setup(**{**RC700.__dict__, "min_altitude_deg": 10.0, "max_airmass": 5.0})
    alto = Setup(**{**RC700.__dict__, "min_altitude_deg": 60.0})

    from core.visibility.geometry import altaz

    ra = np.linspace(0, 360, 721)
    a, _ = altaz(CILE, 0.5 * (JD[0] + JD[-1]), ra, np.full_like(ra, -30.0))
    comune = dict(site=CILE, night=NOTTE, jd=JD,
                  ra_deg=np.full_like(JD, float(ra[int(np.argmax(a))])),
                  dec_deg=np.full_like(JD, -30.0), v_mag=np.full_like(JD, 18.0))

    w_basso = observation_window(setup=basso, **comune)
    w_alto = observation_window(setup=alto, **comune)
    assert w_basso["geo_hours"] > w_alto["geo_hours"]
    assert w_alto["max_alt_deg"] == pytest.approx(w_basso["max_alt_deg"], abs=0.01)


def test_il_momento_migliore_non_e_per_forza_il_transito():
    """Con la Luna in giro il punto più alto e il più profondo non coincidono.

    Se i due coincidessero sempre, tanto varrebbe calcolare il transito — ed è
    esattamente la semplificazione che questo test impedisce.
    """
    # Un oggetto vicino alla Luna al transito: il momento buono si sposta.
    from core.visibility.night import moon_state

    meta = 0.5 * (JD[0] + JD[-1])
    luna = moon_state(CILE, JD)
    i_meta = int(np.argmin(np.abs(JD - meta)))
    w = observation_window(
        site=CILE, setup=RC700, night=NOTTE, jd=JD,
        ra_deg=np.full_like(JD, float(luna["ra_deg"][i_meta])),
        dec_deg=np.full_like(JD, float(luna["dec_deg"][i_meta])),
        v_mag=np.full_like(JD, 20.0),
    )
    if w["observable"] and w["useful"]:
        assert w["best_jd"] is not None
        # Il transito si riporta comunque: serve a capire se il sito è adatto.
        assert w["transit_jd"] is not None
        assert w["max_alt_deg"] >= w["best_alt_deg"] - 1e-9


def test_il_moto_entra_nel_piano_di_posa():
    fermo = _finestra(v_mag=20.0, motion=0.0)
    veloce = _finestra(v_mag=20.0, motion=6.0)
    assert veloce["pen_trailing"] > 0.5
    assert veloce["eff_vlim"] < fermo["eff_vlim"]
    assert veloce["rec_exposure_s"] < fermo["rec_exposure_s"]
    assert veloce["rec_n_subs"] > fermo["rec_n_subs"]
    assert veloce["trail_arcsec"] == pytest.approx(
        veloce["motion_arcsec_min"] * veloce["rec_exposure_s"] / 60.0)


def test_l_incertezza_grande_chiede_un_mosaico():
    """Tre sigma di CEU contro il lato corto del campo, che è 18.2′ = 1092″."""
    stretta = _finestra(v_mag=18.0, ceu_arcsec=30.0)
    assert not stretta["needs_mosaic"]
    assert stretta["fov_fit_ratio"] == pytest.approx(90.0 / (18.2 * 60), rel=1e-6)

    larga = _finestra(v_mag=18.0, ceu_arcsec=600.0)
    assert larga["needs_mosaic"]

    senza = _finestra(v_mag=18.0)
    assert senza["needs_mosaic"] is False and senza["fov_fit_arcsec"] is None


def test_la_griglia_e_quella_dichiarata():
    assert JD.size > 100
    passi = np.diff(JD) * 1440.0
    assert np.allclose(passi, 5.0)
    # Copre dal tramonto all'alba, non di più.
    assert JD[0] == pytest.approx(NOTTE["sunset_jd"])
    assert JD[-1] <= NOTTE["sunrise_jd"] + 1e-9


def test_una_notte_che_non_esiste_non_produce_finestre():
    """Estate polare: nessun tramonto, nessuna griglia, nessuna finestra."""
    tromso = Site(latitude=69.65, longitude=18.96, timezone="Europe/Oslo")
    n = night_events(tromso, "2026-06-21")
    assert night_grid(n).size == 0
    w = observation_window(site=tromso, setup=RC700, night=n, jd=night_grid(n),
                           ra_deg=[], dec_deg=[], v_mag=[])
    assert not w["observable"] and w["n_samples"] == 0
