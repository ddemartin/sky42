"""Magnitudine limite efficace, trailing e piano di posa.

Non c'è una verità esterna da scaricare — `vlim_ref` è una stima dichiarata dal
setup, e la sua taratura è la domanda aperta n. 5. Quello che si può verificare
qui, e che conta, è **la struttura**: il fattore giusto (1.25 e non 2.5), le
penalità che sommano esattamente al totale, e ogni caso limite che si comporta
come la fisica dice.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.visibility.instrument import Setup
from core.visibility.limits import (
    RESIDUAL_TOL,
    SKY_LIMITED,
    effective_limit,
    exposure_plan,
    max_exposure_for_trailing,
    required_exposure,
    trailing_penalty,
)
from core.visibility.site import Site

CILE = Site(latitude=-30.4728, longitude=-70.7647, altitude_m=1560,
            sky_zenith_mag=21.8, extinction_k=0.14)

RC700 = Setup(vlim_ref=21.3, vlim_ref_exposure_s=120.0, typical_exposure_s=120.0,
              max_exposure_s=600.0, typical_seeing_arcsec=1.6,
              pixel_scale_arcsec=0.342, vlim_astrometric_delta=-0.5, code="rc700")


def test_allo_zenit_in_notte_scura_il_limite_e_quello_dichiarato():
    """Nessuna penalità inventata: `vlim_ref` è definito proprio così."""
    r = effective_limit(site=CILE, setup=RC700, target_alt_deg=90.0)
    assert float(r["eff_vlim"]) == pytest.approx(21.3, abs=1e-9)
    assert float(r["eff_vlim_astrometric"]) == pytest.approx(20.8, abs=1e-9)
    for pen in ("pen_airmass", "pen_moon", "pen_twilight", "pen_trailing"):
        assert float(r[pen]) == pytest.approx(0.0, abs=1e-9)


def test_le_penalita_sommano_esattamente():
    """La scomposizione deve tornare, in ogni condizione, non solo nelle facili."""
    casi = [
        dict(target_alt_deg=60.0),
        dict(target_alt_deg=30.0, moon_alt_deg=40.0, moon_phase_deg=90.0,
             moon_sep_deg=90.0, sun_alt_deg=-16.0),
        dict(target_alt_deg=25.0, moon_alt_deg=60.0, moon_phase_deg=0.0,
             moon_sep_deg=30.0, sun_alt_deg=-14.0, motion_arcsec_min=6.0),
        dict(target_alt_deg=80.0, moon_alt_deg=-10.0, moon_phase_deg=0.0,
             moon_sep_deg=120.0, sun_alt_deg=-18.0, motion_arcsec_min=0.5),
    ]
    for kw in casi:
        r = effective_limit(site=CILE, setup=RC700, **kw)
        assert abs(float(r["residual"])) < RESIDUAL_TOL
        somma = sum(float(r[p]) for p in
                    ("pen_airmass", "pen_moon", "pen_twilight", "pen_trailing"))
        assert RC700.vlim_ref - float(r["eff_vlim"]) == pytest.approx(somma, abs=1e-9)


def test_il_fattore_e_uno_e_venticinque_non_due_e_mezzo():
    """Una magnitudine di cielo in più ne costa **mezza** di limite.

    È l'errore più insidioso di tutto il modulo: con 2.5 tutte le penalità
    raddoppiano e i numeri restano plausibili. Il cielo si schiarisce qui con il
    crepuscolo, che è l'unico contributo di cui possiamo fissare esattamente
    quanto vale: coefficiente 1.0 e Sole a −17° fanno esattamente 1 magnitudine
    di cielo.
    """
    sito = Site(latitude=0, longitude=0, sky_zenith_mag=21.8, extinction_k=0.14,
                twilight_coeff=1.0)
    r = effective_limit(site=sito, setup=RC700, target_alt_deg=90.0, sun_alt_deg=-17.0)
    assert float(r["pen_twilight"]) == pytest.approx(0.5, abs=1e-4)
    assert SKY_LIMITED == 1.25


def test_il_cielo_del_sito_e_gia_dentro_vlim_ref():
    """Due siti con lo stesso `vlim_ref` e cieli diversi danno lo stesso limite.

    Non è una svista: `eff_vlim` misura le penalità **rispetto alla notte
    migliore di quel sito**, e quanto quella notte sia buona sta già in
    `vlim_ref`. La conseguenza va saputa perché tocca il confronto fra siti: se
    un `vlim_ref` è ottimistico, quel sito vincerà sempre — ed è la ragione per
    cui la sua taratura è la domanda aperta n. 5 e non un dettaglio.
    """
    scuro = Site(latitude=0, longitude=0, sky_zenith_mag=21.8, extinction_k=0.14)
    chiaro = Site(latitude=0, longitude=0, sky_zenith_mag=20.5, extinction_k=0.14)
    a = float(effective_limit(site=scuro, setup=RC700, target_alt_deg=90)["eff_vlim"])
    b = float(effective_limit(site=chiaro, setup=RC700, target_alt_deg=90)["eff_vlim"])
    assert a == pytest.approx(b, abs=1e-9)


def test_quadruplicare_la_posa_guadagna_una_magnitudine_e_mezza():
    """1.25·log₁₀(4) = 0.75 mag. La radice del tempo, non il tempo."""
    corta = effective_limit(site=CILE, setup=RC700, target_alt_deg=90, exposure_s=120)
    lunga = effective_limit(site=CILE, setup=RC700, target_alt_deg=90, exposure_s=480)
    assert float(lunga["eff_vlim"]) - float(corta["eff_vlim"]) == pytest.approx(
        1.25 * np.log10(4.0), abs=1e-9)


def test_l_airmass_costa_estinzione_piu_fondo():
    """Due effetti distinti nello stesso `pen_airmass`, entrambi positivi."""
    alto = effective_limit(site=CILE, setup=RC700, target_alt_deg=90)
    basso = effective_limit(site=CILE, setup=RC700, target_alt_deg=25)
    assert float(basso["pen_airmass"]) > float(alto["pen_airmass"])
    assert 0.3 < float(basso["pen_airmass"]) < 1.0
    assert float(basso["airmass"]) == pytest.approx(2.36, abs=0.02)


def test_la_luna_pesa_e_il_crepuscolo_pure():
    r = effective_limit(site=CILE, setup=RC700, target_alt_deg=60,
                        moon_alt_deg=60, moon_phase_deg=0, moon_sep_deg=40,
                        sun_alt_deg=-18)
    # Luna piena a 40°: si perdono due magnitudini abbondanti di profondità.
    assert 1.5 < float(r["pen_moon"]) < 3.0
    assert float(r["pen_twilight"]) == 0.0

    crep = effective_limit(site=CILE, setup=RC700, target_alt_deg=60, sun_alt_deg=-15)
    # 0.55 mag/grado × 3 gradi = 1.65 mag di cielo, cioè 0.83 di limite.
    assert float(crep["pen_twilight"]) == pytest.approx(0.5 * 1.65, abs=0.01)


def test_il_trailing_dipende_dal_prodotto_moto_per_posa():
    """Quel che conta è la lunghezza della traccia, non la velocità da sola."""
    assert trailing_penalty(0.0, 300.0, 1.6) == 0.0
    # μ = 2″/min per 120 s = 4″ di traccia su 1.6″ di seeing.
    atteso = SKY_LIMITED * np.log10(1.0 + 4.0 / 1.6)
    assert trailing_penalty(2.0, 120.0, 1.6) == pytest.approx(atteso)
    # Metà velocità e posa doppia danno la stessa traccia, quindi la stessa penalità.
    assert trailing_penalty(1.0, 240.0, 1.6) == pytest.approx(atteso)
    # Un seeing peggiore *riduce* la penalità di trailing: la traccia si nota meno.
    assert trailing_penalty(2.0, 120.0, 3.0) < atteso


def test_la_posa_massima_per_non_impastare():
    """60·θ/μ, ma con il pixel come pavimento nei setup sottocampionati."""
    # Seeing 1.6″, scala 0.342″: comanda il seeing.
    assert max_exposure_for_trailing(4.0, 1.6, 0.342) == pytest.approx(24.0)
    # Scala 2″: 1.5 pixel = 3″ > seeing, comanda il pixel.
    assert max_exposure_for_trailing(4.0, 1.6, 2.0) == pytest.approx(45.0)
    # Oggetto fermo: nessun limite.
    assert np.isinf(max_exposure_for_trailing(0.0, 1.6, 0.342))


def test_esposizione_necessaria_e_il_giro_inverso():
    """`required_exposure` deve essere l'inversa del guadagno in √t."""
    t = required_exposure(v_mag=22.0, eff_vlim_at_ref=21.3, ref_exposure_s=120.0)
    piu_profondo = effective_limit(site=CILE, setup=RC700, target_alt_deg=90,
                                   exposure_s=t)
    assert float(piu_profondo["eff_vlim"]) == pytest.approx(22.0, abs=1e-9)
    # Un oggetto più brillante del limite richiede meno del riferimento.
    assert required_exposure(20.0, 21.3, 120.0) < 120.0


def test_il_piano_di_posa_di_un_neo_veloce():
    """Un oggetto veloce e debole: tante pose corte, e magari non ci stanno.

    È il caso che `eff_vlim` da solo racconterebbe male — direbbe «si vede» —
    ed è la ragione per cui il piano di posa esiste.
    """
    r = effective_limit(site=CILE, setup=RC700, target_alt_deg=45,
                        motion_arcsec_min=4.0, moon_alt_deg=-20)
    p = exposure_plan(setup=RC700, v_mag=20.5, eff_vlim=r["eff_vlim"],
                      motion_arcsec_min=4.0, window_hours=2.0)

    assert float(p["t_sub_s"]) == pytest.approx(24.0)      # trailing, non max_exposure
    assert float(p["n_subs"]) >= 1
    assert float(p["total_s"]) >= float(p["t_needed_s"])
    assert p["fits_window"] in (True, False, np.True_, np.False_)

    # Lo stesso oggetto fermo: una posa lunga basta, e ci sta comodamente.
    fermo = exposure_plan(setup=RC700, v_mag=20.5, eff_vlim=r["eff_vlim"],
                          motion_arcsec_min=0.0, window_hours=2.0)
    assert float(fermo["t_sub_s"]) == RC700.max_exposure_s
    assert float(fermo["n_subs"]) < float(p["n_subs"])
    assert bool(fermo["fits_window"])


def test_tutto_su_una_griglia():
    """La forma in cui lo userà il calcolo delle finestre."""
    alt = np.linspace(20, 80, 7)
    r = effective_limit(site=CILE, setup=RC700, target_alt_deg=alt,
                        motion_arcsec_min=1.5, moon_alt_deg=30.0,
                        moon_phase_deg=60.0, moon_sep_deg=np.linspace(20, 140, 7),
                        sun_alt_deg=-18.0)
    assert r["eff_vlim"].shape == (7,)
    assert np.all(np.abs(r["residual"]) < RESIDUAL_TOL)
    # Più alto è meglio, a parità del resto: la penalità di airmass cala.
    assert np.all(np.diff(r["pen_airmass"]) < 0)


def test_setup_da_una_riga_del_database():
    riga = {
        "code": "cile-rc700-qhy600-bin2", "vlim_ref": 21.3,
        "vlim_ref_exposure_s": 120.0, "vlim_astrometric_delta": -0.5,
        "typical_exposure_s": 120.0, "max_exposure_s": 600.0, "max_airmass": 2.0,
        "min_altitude_deg": None, "min_altitude_eff_deg": 25.0,
        "typical_seeing_arcsec": 1.6, "sun_alt_max_deg": -15.0,
        "pixel_scale_arcsec": 0.342, "fov_x_arcmin": 27.3, "fov_y_arcmin": 18.2,
    }
    s = Setup.from_row(riga)
    assert s.min_altitude_deg == 25.0, "l'altezza minima ereditata dal telescopio"
    assert s.fov_min_arcmin == 18.2
    assert s.vlim_ref == 21.3
