"""Il positioner contro Horizons: effemeridi geocentriche, non solo posizioni.

Stessa disciplina di `test_kepler.py`: elementi osculatori all'epoca, effemeride
alla **stessa** epoca, così il residuo misura la nostra catena (Keplero → tempo
luce → Terra da DE440s → fotometria) e non le perturbazioni.

Scaricato il 2026-08-16 con `EPHEM_TYPE=OBSERVER`, `CENTER=500@399`,
`TIME_TYPE=TT` (TT e TDB differiscono di 2 ms, cioè 1e-4 arcsec di moto),
`QUANTITIES='1,3,9,19,20,23,24'`, `ANG_FORMAT=DEG`, `EXTRA_PREC=YES`.

Le tolleranze dichiarate, e perché non sono più strette:

* **0.05″ in posizione.** La quantità 1 di Horizons è astrometrica J2000 come
  la nostra, ma i nostri elementi sono eclittici J2000 mentre DE440s è ICRF, e
  fra i due c'è il frame bias, ~0.02″. Residuo misurato: 0.008″.
* **0.01 mag.** Residuo misurato: 0.000 su tutti e tre.
* **0.2″/ora sul moto**, ed è l'unica larga: i tassi di Horizons sono del
  *posto apparente* (aberrazione annua inclusa), il nostro è la derivata del
  posto astrometrico. Sono due grandezze diverse che differiscono di ~0.1″/ora,
  cioè 0.002″ su una posa da 120 s: irrilevante per il trailing, che è l'unica
  cosa per cui il moto serve.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.orbits.positioner import Body, positions

EPOCH = 2460676.5           # 2025-01-01 00:00 TT

TOL_POS_ARCSEC = 0.05
TOL_MAG = 0.01
TOL_MOTION_ARCSEC_HOUR = 0.2

CASI = {
    # (1) Cerere. H e G sono quelli di Horizons: confrontare la nostra
    # fotometria usando parametri diversi dai suoi non direbbe niente.
    "ceres": dict(
        body=dict(
            epoch_jd=EPOCH, e=7.927929080437446e-02, i_deg=1.058793299269121e01,
            node_deg=8.025430838169864e01, argp_deg=7.326238274195768e01,
            a_au=2.766360233580095e00, m_deg=1.621500827709824e02,
            h_mag=3.34, g_slope=0.12,
        ),
        ra=313.110898159, dec=-24.848251265,
        r=2.976578692952, delta=3.79833439789668,
        v=9.245, elong=28.9894, phase=9.2148,
        d_ra=54.13820, d_dec=15.22753,       # arcsec/ora
    ),
    # (3200) Faetonte: vicino (Δ < 1 AU) e veloce, dove il tempo luce e il moto
    # contano davvero.
    "phaethon": dict(
        body=dict(
            epoch_jd=EPOCH, e=8.897686313565482e-01, i_deg=2.231295046272242e01,
            node_deg=2.650942188491840e02, argp_deg=3.223065368665398e02,
            a_au=1.271439258861013e00, m_deg=3.012144199998648e02,
            h_mag=14.38, g_slope=0.15,
        ),
        ra=28.236302413, dec=23.703608161,
        r=1.610282774766, delta=0.94007215580046,
        v=16.694, elong=113.6792, phase=34.0028,
        d_ra=-59.2337, d_dec=-62.3055,
    ),
    # C/2023 A3: ramo universale, fotometria cometaria, e la convenzione su k1.
    # JPL pubblica k1 = 5.5 già moltiplicato per 2.5; nella colonna `orbit.k1`
    # sta il k dell'MPC, quindi qui si divide. Se un giorno qualcuno «semplifica»
    # togliendo il 2.5 dalla formula, questo test cade di 2.4 mag.
    "c2023a3": dict(
        body=dict(
            epoch_jd=EPOCH, e=1.000110458814593, i_deg=139.1107902997593,
            node_deg=21.56065255897651, argp_deg=308.4912914242084,
            q_au=0.3914286438440888, tp_jd=2460581.242432254832,
            is_comet=True, m1=8.9, k1=5.5 / 2.5,
        ),
        ra=295.406153142, dec=6.332463957,
        r=1.977282895189, delta=2.73608308554972,
        v=12.714, elong=32.3985, phase=15.4579,
        d_ra=34.24856, d_dec=12.32963,
    ),
}


@pytest.mark.parametrize("nome", sorted(CASI))
def test_effemeride_contro_horizons(nome):
    c = CASI[nome]
    p = positions(Body(**c["body"]), EPOCH)

    cos_dec = np.cos(np.radians(c["dec"]))
    d_ra_arcsec = (p["ra_deg"] - c["ra"]) * 3600.0 * cos_dec
    d_dec_arcsec = (p["dec_deg"] - c["dec"]) * 3600.0
    assert abs(d_ra_arcsec) < TOL_POS_ARCSEC
    assert abs(d_dec_arcsec) < TOL_POS_ARCSEC
    assert np.hypot(d_ra_arcsec, d_dec_arcsec) < TOL_POS_ARCSEC

    # Le distanze entrano nella fotometria al quadrato: 1e-6 AU è già mille
    # volte meglio di quanto serva, ed è il livello a cui il modello a due
    # corpi coincide con la realtà all'epoca degli elementi.
    assert p["r_au"] == pytest.approx(c["r"], abs=1e-6)
    assert p["delta_au"] == pytest.approx(c["delta"], abs=1e-6)
    assert p["elong_deg"] == pytest.approx(c["elong"], abs=0.01)
    assert p["phase_deg"] == pytest.approx(c["phase"], abs=0.01)

    assert p["v_mag"] == pytest.approx(c["v"], abs=TOL_MAG)

    assert p["motion_ra_arcsec_min"] * 60 == pytest.approx(
        c["d_ra"], abs=TOL_MOTION_ARCSEC_HOUR)
    assert p["motion_dec_arcsec_min"] * 60 == pytest.approx(
        c["d_dec"], abs=TOL_MOTION_ARCSEC_HOUR)


def test_il_tempo_luce_non_e_trascurabile():
    """Toglierlo sposta Faetonte di parecchi arcosecondi: è un errore reale.

    Serve a impedire la «semplificazione» di chi, guardando il codice fra un
    anno, decidesse che una iterazione in più non serve a niente.
    """
    from core.ephemeris import earth_equatorial
    from core.orbits.positioner import C_AU_DAY, _radec, heliocentric_equatorial

    c = CASI["phaethon"]
    body = Body(**c["body"])

    terra = earth_equatorial(EPOCH)
    istantanea = heliocentric_equatorial(body, EPOCH) - terra
    ra0, dec0 = _radec(istantanea)

    p = positions(body, EPOCH, with_motion=False)
    scostamento = np.hypot((p["ra_deg"] - ra0) * np.cos(np.radians(dec0)),
                           p["dec_deg"] - dec0) * 3600.0
    # Misurato: 1.93″ — quaranta volte la tolleranza del test contro Horizons.
    # (È lo spostamento *eliocentrico* dell'oggetto durante il volo della luce,
    # non il suo moto apparente: quello include anche la Terra, che qui sta
    # ferma perché la si guarda all'istante di osservazione.)
    assert scostamento > 1.0, "il tempo luce sembra non essere applicato"
    # E il ritardo è quello geometrico, non un numero a caso.
    assert p["delta_au"] / C_AU_DAY * 1440 == pytest.approx(7.8, abs=0.3)  # minuti


def test_scalare_dentro_scalare_fuori():
    p = positions(Body(**CASI["ceres"]["body"]), EPOCH)
    assert isinstance(float(p["ra_deg"]), float)
    assert np.ndim(p["ra_deg"]) == 0


def test_griglia_oggetti_per_epoche():
    """N oggetti × M epoche: la forma in cui lo screening chiamerà il positioner."""
    righe = [
        {"kind": "asteroid", **CASI["ceres"]["body"]},
        {"kind": "asteroid", **CASI["phaethon"]["body"]},
        {"kind": "comet", **CASI["c2023a3"]["body"]},
    ]
    for r in righe:
        r.pop("is_comet", None)

    body = Body.from_rows(righe)
    jd = EPOCH + np.array([0.0, 1.0, 30.0])
    p = positions(body, jd)

    assert p["ra_deg"].shape == (3, 3)
    assert p["v_mag"].shape == (3, 3)
    for riga, nome in enumerate(("ceres", "phaethon", "c2023a3")):
        assert p["ra_deg"][riga, 0] == pytest.approx(CASI[nome]["ra"], abs=1e-4)
        assert p["v_mag"][riga, 0] == pytest.approx(CASI[nome]["v"], abs=TOL_MAG)

    # `from_rows` deve aver capito da `kind` chi è cometa: se sbagliasse, la
    # magnitudine della cometa uscirebbe NaN (non ha h_mag) invece che 12.7.
    assert bool(body.is_comet[2, 0]) is True
    assert np.isfinite(p["v_mag"]).all()


def test_ra_attraversa_lo_zero_senza_saltare():
    """Un oggetto vicino a RA = 0 non deve mostrare un moto di 360° in un'ora."""
    c = CASI["phaethon"]
    jd = EPOCH + np.arange(0, 60, 5.0)      # Faetonte passa per RA ≈ 0 in questo tratto
    p = positions(Body(**c["body"]), jd)
    assert (p["ra_deg"] < 360.0).all() and (p["ra_deg"] >= 0.0).all()
    assert p["motion_arcsec_min"].max() < 20.0, "salto di RA scambiato per moto"


def test_elementi_assurdi_non_producono_una_posizione():
    p = positions(
        Body(epoch_jd=EPOCH, e=0.5, i_deg=10, node_deg=0, argp_deg=0,
             q_au=-1.0, tp_jd=EPOCH, h_mag=15.0),
        EPOCH,
    )
    assert np.isnan(p["ra_deg"]) and np.isnan(p["v_mag"])
