"""La dashboard: che legga la notte giusta, e che non calcoli niente.

Le tre sezioni rispondono a tre orizzonti diversi e non si sommano mai in una
classifica sola: qui si verifica il cablaggio — che le righe arrivino dai job e
non da un calcolo, che «stanotte» sia la notte del **sito** e non del database,
e che il confronto fra siti tenga dentro anche chi ha perso.
"""
from __future__ import annotations

import pytest

from core.db import connect
from services import (dashboard_service as dash, night_service, radar_service,
                      screening_service, window_service)
from tests.test_radar_service import catalogo  # noqa: F401  (fixture)


@pytest.fixture()
def acceso(catalogo):  # noqa: F811
    """La catena intera come gira di notte: screening, notti, finestre, radar."""
    screening_service.run_screening()
    night_service.plan_nights(2)
    window_service.run_windows(n_nights=2)
    radar_service.run_radar()
    return catalogo


def test_la_notte_in_corso_e_quella_del_sito(acceso):
    from core.timeutil import now_jd_tdb
    from core.visibility.night import night_date_for
    from core.visibility.site import Site
    from services import sites_service

    notti = dash.current_nights()
    assert len(notti) == 1
    sito = sites_service.overview()[0]
    atteso = night_date_for(Site.from_row(sito), now_jd_tdb())
    # La stessa funzione con cui il job ha scritto le finestre: due idee diverse
    # di «stanotte» leggerebbero righe che parlano di un'altra notte.
    assert notti[0]["night_date"] == atteso
    assert notti[0]["site_code"] == sito["code"]


def test_tonight_da_una_riga_per_oggetto_con_il_confronto_fra_siti(acceso):
    dati = dash.tonight()
    assert dati["nights"], "senza notti non c'è niente da mostrare"

    visti = [r["target_id"] for r in dati["rows"]]
    assert len(visti) == len(set(visti)), "un oggetto compare una volta sola"

    for r in dati["rows"]:
        assert r["score"] is not None and r["grade"] in (
            "PRIME", "GOOD", "POSSIBLE", "POOR")
        # Il confronto fra siti c'è sempre, e contiene almeno il vincitore.
        assert r["sites"] and r["sites"][0]["score"] == r["score"]
        # Gli orari sono anche in ISO: un JD non si legge in piedi.
        assert r["best_iso"].endswith("Z")
        assert r["useful_start_iso"] < r["useful_end_iso"]


def test_i_setup_da_cui_non_si_vede_restano_nel_confronto(acceso):
    """Sparire dalla lista non racconta la differenza fra «non si poteva» e
    «non ci ho provato» (regola 5)."""
    conn = connect()
    try:
        # Si rende inutile una finestra: resta scritta, con grade NOT_USEFUL.
        conn.execute("UPDATE observation_window SET score = NULL, "
                     "grade = 'NOT_USEFUL' WHERE id = (SELECT max(id) "
                     "FROM observation_window)")
        riga = conn.execute("SELECT target_id FROM observation_window "
                            "WHERE grade='NOT_USEFUL'").fetchone()
    finally:
        conn.close()
    assert riga is not None

    for r in dash.tonight()["rows"]:
        gradi = [s["grade"] for s in r["sites"]]
        assert all(g is not None for g in gradi)


def test_best_site_tonight_e_la_stessa_domanda_ordinata_per_sito(acceso):
    """Se i due oggetti finti non fossero utili stanotte il test non proverebbe
    niente, quindi il punteggio si mette a mano: `best_sites` **è** una query
    di aggregazione, e si verifica come tale."""
    conn = connect()
    try:
        notte = dash.current_nights()[0]["id"]
        conn.execute("""UPDATE observation_window
                        SET score = 0.8, grade = 'PRIME', useful_hours = 3.0
                        WHERE night_id = ?""", (notte,))
    finally:
        conn.close()

    righe = dash.best_sites()
    assert righe, "un setup attivo con oggetti utili deve comparire"
    r = righe[0]
    assert r["n_utili"] == r["n_prime"] and r["n_good"] == 0
    assert r["site_code"] and r["setup_code"]
    assert r["score_max"] == pytest.approx(0.8)
    assert r["ore_totali"] == pytest.approx(3.0 * r["n_utili"])
    # Lo stesso insieme di righe della sezione Stanotte, contato per setup.
    assert sum(x["n_utili"] for x in righe) >= dash.tonight()["n_totali"]


def test_le_tre_sezioni_non_si_confondono(acceso):
    """`coming_into_range` guarda avanti, `returns` guarda indietro: se una
    delle due cominciasse a pescare nell'insieme dell'altra, la sezione che
    perde è sempre quella dei rientri rari."""
    avanti = dash.coming_into_range()
    indietro = dash.returns()
    assert all(r["state"] in ("APPROACHING", "CROSSES_LIMIT") for r in avanti)
    assert all(r["state"] in ("PRIME", "OBSERVABLE", "CROSSES_LIMIT")
               for r in indietro)
    assert all(r["tisserand_j"] < 3.0 for r in indietro)


def test_chi_manca_da_piu_di_quindici_anni_va_in_cima_non_in_fondo(acceso):
    """`years_since_good_apparition` a NULL è **censurato**, non mancante: vuol
    dire «mai, in tutta la finestra di back-propagation», cioè l'assenza più
    lunga di tutte. Ordinarli per ultimi seppellisce gli oggetti per cui la
    sezione esiste — sul catalogo vero è successo alla prima lettura."""
    conn = connect()
    try:
        conn.execute("UPDATE target_state SET state='PRIME' WHERE setup_id IS NULL")
        conn.execute("UPDATE orbit SET tisserand_j = 2.5")
        ids = [r[0] for r in conn.execute(
            "SELECT target_id FROM target_stats ORDER BY target_id").fetchall()]
        conn.execute("UPDATE target_stats SET years_since_good_apparition = 14.9 "
                     "WHERE target_id = ?", (ids[0],))
        conn.execute("UPDATE target_stats SET years_since_good_apparition = NULL "
                     "WHERE target_id = ?", (ids[1],))
    finally:
        conn.close()

    righe = dash.returns()
    assert len(righe) == 2
    assert righe[0]["apparition_censored"] is True, "il censurato viene prima"
    assert righe[0]["apparition_window_years"] == 15
    assert righe[1]["years_since_good_apparition"] == pytest.approx(14.9)


def test_coming_into_range_ordina_per_quando_non_per_magnitudine(acceso):
    conn = connect()
    try:
        # Due oggetti in avvicinamento, con date di rientro invertite rispetto
        # alla magnitudine: se l'ordine seguisse V, uscirebbero al contrario.
        conn.execute("UPDATE target_state SET state='APPROACHING'")
        conn.execute("""UPDATE target_stats SET next_v21_jd = julianday('now') + 90,
                        v_now = 21.0 WHERE target_id = (SELECT min(target_id)
                        FROM target_stats)""")
        conn.execute("""UPDATE target_stats SET next_v21_jd = julianday('now') + 10,
                        v_now = 22.0 WHERE target_id = (SELECT max(target_id)
                        FROM target_stats)""")
    finally:
        conn.close()

    righe = dash.coming_into_range()
    assert [r["v_now"] for r in righe] == [22.0, 21.0]
    assert righe[0]["giorni_alla_portata"] < righe[1]["giorni_alla_portata"]
    assert righe[0]["next_v21_iso"].endswith("Z")


def test_la_freschezza_dei_tre_lavori_e_parte_del_risultato(acceso):
    f = dash.freshness()
    assert set(f["jobs"]) == {"screening", "windows", "radar_states"}
    assert f["n_finestre"] > 0
    assert all(j["status"] == "ok" for j in f["jobs"].values())


def test_overview_e_una_forma_sola(acceso):
    """La pagina e l'endpoint JSON leggono la stessa chiamata, o divergono
    appena qualcuno tocca una query."""
    o = dash.overview()
    assert set(o) == {"freshness", "tonight", "best_sites", "coming_into_range",
                      "returns"}
    import json
    json.loads(dash.as_json())


def test_senza_notti_la_dashboard_lo_dice_invece_di_mentire(catalogo):  # noqa: F811
    screening_service.run_screening()
    dati = dash.tonight()
    assert dati["nights"] == [] and dati["rows"] == []
    assert dash.best_sites() == []
