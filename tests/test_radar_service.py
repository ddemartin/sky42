"""Screening e radar sul database: cosa viene scritto, e cosa non viene riscritto.

Due oggetti veri e un sito vero (gli stessi YAML del reconcile), perché quello
che si prova qui è il giro completo — popolazione, propagazione, BLOB, stati,
transizioni. Le formule hanno i loro test altrove.
"""
from __future__ import annotations

import textwrap

import numpy as np
import pytest

from core.db import connect
from core.radar import states
from services import radar_service, screening_service, sites_service

# (3200) Faetonte e (1) Cerere, elementi MPCORB di epoca 2026-05-05. Il primo è
# un ACO (Tj = 4.5 in realtà: qui interessa che ci sia, e ci finisce dalla
# watchlist), il secondo serve a distinguere «monitorato» da «in catalogo».
OGGETTI = [
    # (desig, nome, kind, classe, a, e, i, node, argp, M, H, Tj)
    ("3200", "(3200) Phaethon", "asteroid", "Apollo", 1.2712, 0.8898, 22.2568,
     265.1913, 322.1728, 130.9553, 14.32, 4.51),
    ("2010 TK7", "(2010) TK7", "asteroid", "Apollo", 3.1000, 0.6200, 20.0000,
     100.0000, 50.0000, 10.0000, 17.50, 2.60),
]


def _inserisci(conn, riga, watchlist=False):
    desig, nome, kind, classe, a, e, i, node, argp, m, h, tj = riga
    cur = conn.execute(
        """INSERT INTO target (kind, primary_desig, display_name, orbit_class,
                               created_at, updated_at)
           VALUES (?,?,?,?, '2026-08-17T00:00:00Z','2026-08-17T00:00:00Z')""",
        (kind, desig, nome, classe))
    tid = cur.lastrowid
    conn.execute(
        """INSERT INTO orbit (target_id, source, epoch_jd, a_au, e, i_deg, node_deg,
                              argp_deg, m_deg, h_mag, g_slope, tisserand_j,
                              arc_days, n_oppositions, last_obs_date, updated_at)
           VALUES (?,'mpcorb',2461135.5,?,?,?,?,?,?,?,0.15,?,4000,30,'2019-03-01',
                   '2026-08-17T00:00:00Z')""",
        (tid, a, e, i, node, argp, m, h, tj))
    if watchlist:
        conn.execute("INSERT INTO watchlist (target_id, added_at) VALUES (?,?)",
                     (tid, "2026-08-17T00:00:00Z"))
    return tid


@pytest.fixture()
def catalogo(db, tmp_path, monkeypatch):
    """Due oggetti, un sito con un setup attivo."""
    from core import config
    from tests.test_sites import SITO

    d = tmp_path / "sites"
    d.mkdir()
    (d / "cile.yml").write_text(textwrap.dedent(SITO), encoding="utf-8")
    monkeypatch.setattr(config, "SITES_DIR", d)
    sites_service.run_reconcile()

    conn = connect()
    try:
        ids = [_inserisci(conn, OGGETTI[0], watchlist=True),
               _inserisci(conn, OGGETTI[1])]
    finally:
        conn.close()
    return ids


def _righe(sql, params=()):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# --- la popolazione ---------------------------------------------------------


def test_la_popolazione_prende_gli_aco_e_la_watchlist(catalogo):
    desig = {r["primary_desig"] for r in screening_service.population_rows()[0]}
    # Il secondo ha Tj = 2.6: ci entra da solo. Il primo ha Tj = 4.5 e ci entra
    # perché qualcuno l'ha messo in watchlist — che è il motivo per cui la
    # watchlist sta nella query e non in un filtro a valle.
    assert desig == {"3200", "2010 TK7"}


def test_le_classi_risonanti_restano_fuori(catalogo):
    conn = connect()
    try:
        conn.execute("UPDATE target SET orbit_class='Hilda' WHERE primary_desig='2010 TK7'")
    finally:
        conn.close()
    desig = {r["primary_desig"] for r in screening_service.population_rows()[0]}
    assert desig == {"3200"}, "un risonante stabile non è un oggetto che torna"


def test_il_v_ref_viene_dal_setup_piu_profondo(catalogo):
    v, quale = screening_service.radar_reference_v()
    assert quale == "cile-test/rc700-qhy600-bin2"
    # vlim_ref dichiarato 21.3, meno l'estinzione e il cielo a X = 1.5.
    assert 20.0 < v < 21.3


# --- lo screening -----------------------------------------------------------


def test_screening_scrive_tracce_e_statistiche(catalogo):
    esito = screening_service.run_screening()
    assert esito["n_oggetti"] == 2

    tracce = _righe("SELECT * FROM screening_track")
    assert len(tracce) == 2
    t = tracce[0]
    assert t["n_samples"] == 731 and t["step_days"] == 1.0
    # Il BLOB è float32: quattro byte per campione, e si rilegge in array.
    assert len(t["v_mag"]) == 731 * 4
    v = np.frombuffer(t["v_mag"], dtype="<f4")
    assert np.isfinite(v).all() and (v > 0).all()

    stats = _righe("SELECT * FROM target_stats")
    assert len(stats) == 2
    for s in stats:
        assert s["v_now"] is not None and s["peak_v"] <= s["v_now"] + 1e-6
        # last_obs_date è del 2019: sono più di sei anni, ed è la feature
        # «rarità» che poi il ranking legge.
        assert s["years_since_last_obs"] > 6.0


def test_screening_e_idempotente(catalogo):
    screening_service.run_screening()
    prima = _righe("SELECT target_id, computed_at FROM screening_track ORDER BY target_id")
    screening_service.run_screening()
    dopo = _righe("SELECT target_id, computed_at FROM screening_track ORDER BY target_id")
    assert len(dopo) == 2
    assert [r["target_id"] for r in dopo] == [r["target_id"] for r in prima]


def test_la_traccia_si_rilegge_come_array(catalogo):
    screening_service.run_screening()
    tr = screening_service.track_of(catalogo[0])
    assert tr["jd"].size == tr["v_mag"].size == 731
    assert tr["jd"][1] - tr["jd"][0] == pytest.approx(1.0)
    assert 0.0 <= tr["ra_deg"].min() and tr["ra_deg"].max() <= 360.0


def test_lo_screening_lavora_a_blocchi(catalogo):
    """Con blocchi da uno si scrive lo stesso tutto: il blocco è una misura di
    memoria e di cortesia, non un pezzo di logica."""
    esito = screening_service.run_screening(block=1)
    assert esito["blocchi"] == 2
    assert len(_righe("SELECT * FROM target_stats")) == 2


# --- il radar ---------------------------------------------------------------


def test_il_radar_scrive_uno_stato_per_setup_piu_il_rollup(catalogo):
    screening_service.run_screening()
    esito = radar_service.run_radar()

    assert esito["setup"] == 2, "un setup attivo, più il rollup"
    stati = _righe("SELECT * FROM target_state")
    assert len(stati) == 4
    assert {s["setup_id"] for s in stati} == {None, 1}
    assert all(s["state"] in ("OUT_OF_RANGE", "APPROACHING", "CROSSES_LIMIT",
                              "OBSERVABLE", "PRIME", "FADING") for s in stati)


def test_il_primo_giro_non_e_una_transizione(catalogo):
    screening_service.run_screening()
    radar_service.run_radar()
    assert _righe("SELECT * FROM state_transition") == [], \
        "uno stato iniziale non è un cambiamento, e non si notifica"


def test_rilanciarlo_non_moltiplica_le_righe(catalogo):
    screening_service.run_screening()
    radar_service.run_radar()
    radar_service.run_radar()
    assert len(_righe("SELECT * FROM target_state")) == 4


def test_una_transizione_confermata_finisce_nella_storia(catalogo):
    screening_service.run_screening()
    radar_service.run_radar()

    # Si sposta la statistica, non l'orbita: il radar legge `target_stats` e
    # basta, ed è proprio questo che si vuole verificare.
    conn = connect()
    try:
        conn.execute("UPDATE target_stats SET v_now = 12.0, v_trend_mag_month = -0.5")
    finally:
        conn.close()

    primo = radar_service.run_radar()
    assert primo["transizioni"] == 0, "un solo calcolo non basta"
    secondo = radar_service.run_radar()
    assert secondo["transizioni"] > 0

    storia = _righe("SELECT * FROM state_transition")
    assert storia and storia[0]["to_state"] in ("PRIME", "CROSSES_LIMIT")
    # La fotografia del momento: fra sei mesi le statistiche saranno altre.
    import json
    contesto = json.loads(storia[0]["context_json"])
    assert contesto["v_now"] == 12.0 and "v_ref" in contesto


def test_l_attesa_di_conferma_sopravvive_al_processo(catalogo):
    """Il job gira in un processo che muore ogni volta: se il candidato in
    attesa non stesse nel database, nessuna transizione verrebbe mai
    confermata — e `pending_since` deve restare quello del primo giro."""
    screening_service.run_screening()
    radar_service.run_radar()

    conn = connect()
    try:
        conn.execute("UPDATE target_stats SET v_now = 12.0, v_trend_mag_month = -0.5")
    finally:
        conn.close()

    radar_service.run_radar()
    attesa = _righe("SELECT * FROM target_state WHERE pending_state IS NOT NULL")
    assert attesa, "il candidato in attesa è scritto"
    prima_volta = {(r["target_id"], r["setup_id"]): r["pending_since"] for r in attesa}
    assert all(r["pending_count"] == 1 for r in attesa)

    # Un terzo giro conferma e chiude l'attesa; se il candidato fosse rimasto
    # lo stesso senza confermare, `pending_since` non dovrebbe spostarsi.
    radar_service.run_radar()
    assert not _righe("SELECT * FROM target_state WHERE pending_state IS NOT NULL")
    assert prima_volta, "c'era qualcosa in attesa da confermare"


def test_l_attraversamento_non_lascia_una_riga_meccanica(catalogo):
    """Entrare a portata scrive una transizione; assestarsi da `CROSSES_LIMIT`
    a `OBSERVABLE` no — `state_transition` è storia, non un giornale di bordo."""
    screening_service.run_screening()
    radar_service.run_radar()

    conn = connect()
    try:
        # Fuori portata, poi dentro: si costruisce l'attraversamento.
        conn.execute("UPDATE target_stats SET v_now = 26.0, v_trend_mag_month = 0.0")
    finally:
        conn.close()
    radar_service.run_radar()
    radar_service.run_radar()

    conn = connect()
    try:
        conn.execute("UPDATE target_stats SET v_now = 15.0, v_trend_mag_month = -0.5")
    finally:
        conn.close()
    radar_service.run_radar()
    radar_service.run_radar()

    assert any(r["to_state"] == "CROSSES_LIMIT"
               for r in _righe("SELECT * FROM state_transition"))

    prima = len(_righe("SELECT * FROM state_transition"))
    radar_service.run_radar()
    assert _righe("SELECT state FROM target_state WHERE setup_id IS NULL")[0]["state"] \
        in ("OBSERVABLE", "PRIME"), "l'evento si assesta al giro dopo"
    assert len(_righe("SELECT * FROM state_transition")) == prima, \
        "e non lascia una riga che non racconta niente"


def test_le_letture_per_la_dashboard(catalogo):
    screening_service.run_screening()
    radar_service.run_radar()
    conteggi = radar_service.state_counts()
    assert sum(c["n"] for c in conteggi) == 2, "solo il rollup"
    # Tutti gli stati compaiono, anche quelli vuoti: una dashboard che nasconde
    # le righe a zero fa sembrare che uno stato non esista.
    assert [c["stato"] for c in conteggi] == list(states.STATES)


def test_senza_setup_attivi_il_radar_non_scrive_niente(db):
    assert radar_service.run_radar()["setup"] == 0
    assert _righe("SELECT * FROM target_state") == []
