"""Il job delle finestre: cosa scrive, e che dica lo stesso numero della pagina.

Il test che conta è il primo: **il calcolo in massa e quello a un oggetto sono
la stessa funzione**. Se un giorno divergessero, la pagina Oggetto e la
dashboard direbbero due cose diverse dello stesso oggetto nella stessa notte, e
non ci sarebbe modo di sapere quale delle due credere.
"""
from __future__ import annotations

import json

import numpy as np
import pytest

from core.db import connect
from core.visibility.instrument import Setup
from core.visibility.night import night_events
from core.visibility.site import Site
from core.visibility.windows import (night_grid, observation_window,
                                     observation_windows, sky_geometry)
from services import (night_service, radar_service, screening_service,
                      window_service)
from tests.test_radar_service import catalogo  # noqa: F401  (fixture)

CILE = Site(latitude=-30.4728, longitude=-70.7647, altitude_m=1560,
            timezone="America/Santiago", sky_zenith_mag=21.8, extinction_k=0.14)

RC700 = Setup(vlim_ref=21.3, vlim_ref_exposure_s=120.0, typical_exposure_s=120.0,
              max_exposure_s=600.0, min_altitude_deg=25.0, max_airmass=2.0,
              sun_alt_max_deg=-15.0, typical_seeing_arcsec=1.6,
              pixel_scale_arcsec=0.342, fov_x_arcmin=27.3, fov_y_arcmin=18.2,
              code="rc700")

NOTTE = night_events(CILE, "2026-08-16")
JD = night_grid(NOTTE)


# --- l'invariante: una funzione sola -----------------------------------------


def test_il_calcolo_in_massa_da_gli_stessi_numeri_di_quello_singolo():
    """Tre oggetti insieme, o uno alla volta: le stesse cifre, non «circa»."""
    dec = np.array([-30.0, -10.0, -60.0])
    ra = np.array([120.0, 300.0, 45.0])
    v = np.array([18.0, 24.0, 20.5])
    mu = np.array([0.5, 3.0, 12.0])

    ra_grid = np.repeat(ra[:, None], JD.size, axis=1)
    dec_grid = np.repeat(dec[:, None], JD.size, axis=1)
    v_grid = np.repeat(v[:, None], JD.size, axis=1)
    mu_grid = np.repeat(mu[:, None], JD.size, axis=1)
    ceu = np.array([2.0, np.nan, 400.0])

    insieme = observation_windows(
        site=CILE, setup=RC700, night=NOTTE, jd=JD,
        geometry=sky_geometry(CILE, JD, ra_grid, dec_grid),
        v_mag=v_grid, motion_arcsec_min=mu_grid, ceu_arcsec=ceu)

    for i in range(3):
        solo = observation_window(
            site=CILE, setup=RC700, night=NOTTE, jd=JD,
            ra_deg=ra_grid[i], dec_deg=dec_grid[i], v_mag=v_grid[i],
            motion_arcsec_min=mu_grid[i],
            ceu_arcsec=None if np.isnan(ceu[i]) else ceu[i])
        assert insieme[i] == solo, f"oggetto {i}: massa e singolo divergono"


def test_la_geometria_non_dipende_dal_setup():
    """`sky_geometry` non riceve un `Setup`, e non deve poterlo ricevere: il
    costo scala con i siti, non con gli strumenti (CLAUDE.md)."""
    import inspect

    firma = inspect.signature(sky_geometry).parameters
    assert "setup" not in firma
    g = sky_geometry(CILE, JD, np.full((2, JD.size), 120.0),
                     np.full((2, JD.size), -30.0))
    assert g["alt_deg"].shape == (2, JD.size)
    assert np.asarray(g["sun_alt_deg"]).shape == (JD.size,)


def test_una_griglia_vuota_da_una_riga_vuota_per_oggetto():
    vuote = observation_windows(
        site=CILE, setup=RC700, night=NOTTE, jd=np.empty(0),
        geometry={}, v_mag=np.empty((3, 0)))
    assert len(vuote) == 3
    assert all(not w["observable"] and w["useful_hours"] == 0.0 for w in vuote)


# --- il job sul database ------------------------------------------------------


def _righe(sql, params=()):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


@pytest.fixture()
def pronto(catalogo):  # noqa: F811
    """Due oggetti propagati e le notti calcolate: quel che il job si aspetta."""
    screening_service.run_screening()
    night_service.plan_nights(3)
    return catalogo


def test_il_job_scrive_una_riga_per_oggetto_setup_e_notte(pronto):
    # Senza soglia sulla magnitudine non si sa quanti oggetti entrano: si
    # allarga la fascia perché il test verifichi il conteggio, non il cielo.
    esito = window_service.run_windows(n_nights=2)

    righe = _righe("SELECT * FROM observation_window")
    n_notti = len({r["night_id"] for r in righe})
    n_target = len({r["target_id"] for r in righe})
    assert esito["finestre"] == len(righe)
    assert len(righe) == n_notti * n_target * 1, "un setup attivo"
    assert n_notti == 2

    for r in righe:
        # Regola 5: il numero non esce mai senza la sua scomposizione.
        assert r["grade"] in ("PRIME", "GOOD", "POSSIBLE", "POOR", "NOT_USEFUL")
        j = json.loads(r["score_json"])
        assert "features" in j and "weights" in j
        if r["score"] is None:
            assert j["gates_failed"]
        # Un oggetto mai sopra l'orizzonte non ha una profondità da scomporre, e
        # la riga resta a NULL: la finestra c'è lo stesso, e dice che non c'era
        # niente da fare. Quando invece la finestra geometrica esiste, `eff_vlim`
        # e le sue quattro penalità viaggiano insieme (regola 5).
        if r["geo_start_jd"] is None:
            assert r["eff_vlim"] is None and r["useful_hours"] == 0.0
            continue
        for c in ("eff_vlim", "pen_airmass", "pen_moon", "pen_twilight",
                  "pen_trailing", "depth_margin"):
            assert r[c] is not None


def test_il_job_e_idempotente(pronto):
    window_service.run_windows(n_nights=1)
    prima = _righe("SELECT id, target_id, setup_id, night_id FROM observation_window "
                   "ORDER BY id")
    window_service.run_windows(n_nights=1)
    dopo = _righe("SELECT id, target_id, setup_id, night_id FROM observation_window "
                  "ORDER BY id")
    assert len(dopo) == len(prima), "rilanciarlo non moltiplica le righe"


def test_la_fascia_di_guardia_tiene_fuori_i_troppo_deboli(pronto):
    conn = connect()
    try:
        conn.execute("UPDATE target_stats SET v_now = 30.0")
    finally:
        conn.close()
    esito = window_service.run_windows(n_nights=1)
    assert esito["n_popolazione"] == 0
    assert _righe("SELECT * FROM observation_window") == []


def test_senza_notti_calcolate_il_job_non_inventa_niente(catalogo):  # noqa: F811
    """Senza una riga in `night` non c'è nemmeno il `night_id` a cui agganciare
    la finestra: si salta il sito e lo si dice, non si calcola una notte al volo."""
    screening_service.run_screening()
    esito = window_service.run_windows(n_nights=1)
    assert esito["siti"] == 0 and esito["finestre"] == 0


def test_le_finestre_delle_notti_passate_si_potano(pronto):
    window_service.run_windows(n_nights=1)
    conn = connect()
    try:
        # Si sposta la notte nel passato: la finestra ci va dietro.
        conn.execute("UPDATE night SET night_date = date('now', '-30 day') "
                     "WHERE id = (SELECT min(night_id) FROM observation_window)")
    finally:
        conn.close()
    window_service.run_windows(n_nights=1)
    rimaste = _righe(
        """SELECT w.id FROM observation_window w JOIN night n ON n.id = w.night_id
           WHERE julianday(n.night_date) < julianday('now') - 7""")
    assert rimaste == []


# --- il criterio sulla durata, che ora si accende ----------------------------


def test_il_radar_legge_le_ore_utili_e_il_rollup_prende_il_meglio(pronto):
    window_service.run_windows(n_nights=1)
    conn = connect()
    try:
        mappa = radar_service._useful_hours(conn)
    finally:
        conn.close()

    assert mappa, "le finestre ci sono: il criterio sulla durata non è più cieco"
    per_setup = {k: v for k, v in mappa.items() if k[1] is not None}
    for (target_id, _), ore in per_setup.items():
        # Il rollup è il migliore fra i setup, mai meno di uno di essi.
        assert mappa[(target_id, None)] >= ore


def test_una_finestra_corta_declassa_lo_stato(pronto):
    """È la ragione per cui il job esiste: un oggetto brillantissimo che sta su
    venti minuti non è PRIME."""
    screening_service.run_screening()
    window_service.run_windows(n_nights=1)
    conn = connect()
    try:
        conn.execute("UPDATE target_stats SET v_now = 12.0, v_trend_mag_month = -0.5")
        conn.execute("UPDATE observation_window SET useful_hours = 0.2")
        mappa = radar_service._useful_hours(conn)
    finally:
        conn.close()

    assert mappa and all(v == pytest.approx(0.2) for v in mappa.values())
    from core.radar import states
    assert states.classify(v_pred=12.0, v_ref=21.0, useful_hours=0.2) == "OUT_OF_RANGE"
    assert states.classify(v_pred=12.0, v_ref=21.0, useful_hours=None) == "PRIME"


def test_un_setup_fuori_servizio_esce_dalle_finestre(pronto):  # noqa: F811
    """Il job **salta** i setup inattivi invece di ricalcolarli: senza una
    potatura apposta, le righe scritte ieri — quando il setup era ancora
    attivo — resterebbero per le notti di oggi e di domani, e ci resterebbero
    per sempre. Un telescopio andato offline continuava a comparire in
    `/stanotte` con le finestre del giorno prima."""
    from core.db import connect

    night_service.plan_nights(2)
    window_service.run_windows(n_nights=2)

    conn = connect()
    try:
        setup_id, code = conn.execute(
            "SELECT id, code FROM setup WHERE active=1 LIMIT 1").fetchone()
        prima = conn.execute(
            "SELECT count(*) FROM observation_window WHERE setup_id=?",
            (setup_id,)).fetchone()[0]
        assert prima > 0, "senza righe il test non prova niente"
        conn.execute("UPDATE setup SET active=0 WHERE id=?", (setup_id,))
    finally:
        conn.close()

    esito = window_service.run_windows(n_nights=2)
    assert esito["potate"] >= prima

    conn = connect()
    try:
        dopo = conn.execute(
            "SELECT count(*) FROM observation_window WHERE setup_id=?",
            (setup_id,)).fetchone()[0]
    finally:
        conn.close()
    assert dopo == 0, f"{code} è fuori servizio ma ha ancora {dopo} finestre"
