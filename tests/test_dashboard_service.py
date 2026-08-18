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
    assert set(o) == {"freshness", "facets", "tonight", "best_sites",
                      "coming_into_range", "returns"}
    import json
    json.loads(dash.as_json())


@pytest.fixture()
def classificato(acceso):
    """Le finestre di stanotte con un punteggio, deterministico e distinto.

    Gli oggetti finti non sono per forza utili nella notte in cui gira la suite,
    e senza punteggio `tonight` non restituisce niente. Come in `best_sites`, il
    punteggio si mette a mano: qui si provano **filtri e paginazione**, non il
    ranking, che ha i suoi test. Punteggi distinti per oggetto, o «la seconda
    riga» non sarebbe una domanda con una risposta sola.
    """
    conn = connect()
    try:
        notte = dash.current_nights()[0]["id"]
        ids = sorted(r[0] for r in conn.execute(
            "SELECT DISTINCT target_id FROM observation_window WHERE night_id=?",
            (notte,)).fetchall())
        for i, tid in enumerate(ids):
            conn.execute(
                """UPDATE observation_window
                   SET score = ?, grade = 'PRIME', useful_hours = 3.0,
                       best_alt_deg = 55.0, depth_margin = 1.5, v_pred = 19.0
                   WHERE night_id = ? AND target_id = ?""",
                (0.9 - 0.1 * i, notte, tid))
    finally:
        conn.close()
    assert len(ids) >= 2, "servono due oggetti utili per provare la paginazione"
    return ids


def test_i_filtri_riducono_senza_riordinare(classificato):
    """Filtrare non è riclassificare: l'ordine per punteggio resta quello, e chi
    passa il filtro lo trova nella stessa posizione relativa di prima."""
    tutti = dash.tonight(limit=50)["rows"]
    assert len(tutti) >= 2

    # Tj: la domanda del radar. Dei due oggetti finti uno sta a 4.51 e l'altro a
    # 2.60, quindi la soglia ne toglie esattamente uno.
    stretto = dash.tonight(limit=50, filters={"tisserand_max": 3.0})
    assert all(r["tisserand_j"] < 3.0 for r in stretto["rows"])
    assert stretto["n_disponibili"] == len(tutti), "il totale non filtrato resta"
    assert stretto["n_totali"] == len(stretto["rows"]) < len(tutti)
    atteso = [r["primary_desig"] for r in tutti if (r["tisserand_j"] or 99) < 3.0]
    assert [r["primary_desig"] for r in stretto["rows"]] == atteso

    # Un tipo che stanotte non c'è dà zero righe, non un errore.
    comete = dash.tonight(limit=50, filters={"kind": "comet"})
    assert comete["rows"] == [] and comete["n_disponibili"] == len(tutti)


def test_un_filtro_toglie_anche_chi_il_dato_non_ce_l_ha(classificato):
    """NULL non risponde di sì: «Tj sotto 3» esclude chi il Tisserand non ce
    l'ha. È voluto, ed è la ragione per cui la pagina lo scrive."""
    conn = connect()
    try:
        conn.execute("UPDATE orbit SET tisserand_j = NULL")
    finally:
        conn.close()
    assert dash.tonight(limit=50, filters={"tisserand_max": 3.0})["rows"] == []
    assert dash.tonight(limit=50)["rows"], "senza filtro ci sono ancora"


def test_il_confronto_fra_siti_non_si_filtra(classificato):
    """I filtri scelgono la finestra migliore *fra quelle che passano*, ma il
    confronto fra siti accanto alla riga resta intero: filtrarlo lo renderebbe
    un elenco di sole buone notizie, ed è l'opposto della regola 5."""
    notte = dash.current_nights()[0]["id"]
    conn = connect()
    try:
        # Un setup da cui non si vede: resta scritto, con grade NOT_USEFUL.
        conn.execute("""UPDATE observation_window SET score = NULL,
                        grade = 'NOT_USEFUL' WHERE id = (SELECT max(id)
                        FROM observation_window WHERE night_id = ?)""", (notte,))
        # Contato sulla **notte in corso**: `windows` ne scrive più d'una, e
        # sommarle tutte confronterebbe i siti di stanotte con quelli di domani.
        n_finestre = dict(conn.execute(
            """SELECT target_id, count(*) FROM observation_window
               WHERE night_id = ? GROUP BY target_id""", (notte,)).fetchall())
    finally:
        conn.close()

    righe = dash.tonight(limit=50, filters={"alt_min_deg": 50.0})["rows"]
    assert righe
    for r in righe:
        assert r["best_alt_deg"] >= 50.0, "la riga scelta rispetta il filtro"
        assert len(r["sites"]) == n_finestre[r["target_id"]], \
            "i siti ci sono tutti, filtro o no"
        assert all(s["grade"] is not None for s in r["sites"])


def test_la_ricerca_guarda_nome_e_designazione(classificato):
    riga = dash.tonight(limit=50)["rows"][0]
    per_desig = dash.tonight(limit=50, filters={"q": riga["primary_desig"]})
    assert riga["primary_desig"] in [r["primary_desig"] for r in per_desig["rows"]]
    # Un pezzo di nome basta: la ricerca è per sottostringa, non per uguaglianza.
    pezzo = riga["display_name"][2:6]
    assert any(r["primary_desig"] == riga["primary_desig"]
               for r in dash.tonight(limit=50, filters={"q": pezzo})["rows"])
    assert dash.tonight(filters={"q": "zzzznonesiste"})["rows"] == []


def test_offset_non_salta_e_non_ripete(classificato):
    """`OFFSET` su un insieme già ridotto a una riga per oggetto: «mostra altri
    venti» deve dare le righe successive, non altre righe a caso."""
    tutte = dash.tonight(limit=50)
    primo = dash.tonight(limit=1)
    secondo = dash.tonight(limit=1, offset=1)
    assert primo["rows"][0]["primary_desig"] == tutte["rows"][0]["primary_desig"]
    assert secondo["rows"][0]["primary_desig"] == tutte["rows"][1]["primary_desig"]
    assert primo["has_more"] is True
    assert tutte["has_more"] is False
    # Un oggetto compare una volta sola anche paginando.
    assert primo["rows"][0]["target_id"] != secondo["rows"][0]["target_id"]
    # E il conto totale non dipende da quante righe si sono chieste.
    assert primo["n_totali"] == tutte["n_totali"] == len(tutte["rows"])


def test_un_filtro_sconosciuto_e_un_errore_non_un_silenzio(acceso):
    """Una pagina che sbaglia il nome di un filtro mostrerebbe la lista intera e
    sembrerebbe funzionare: è il modo peggiore di sbagliare."""
    with pytest.raises(ValueError, match="filtro sconosciuto"):
        dash.tonight(filters={"tisserand_massimo": 3.0})


def test_le_facce_dei_filtri_vengono_da_stanotte(classificato):
    f = dash.tonight_facets()
    assert set(f) == {"orbit_classes", "kinds", "ranges"}
    assert f["kinds"] == ["asteroid"], "i due oggetti finti sono asteroidi"
    assert "Apollo" in f["orbit_classes"]
    # I valori servono a tarare i cursori: devono essere numeri, non NULL.
    assert f["ranges"]["v_max"] >= f["ranges"]["v_min"]
    assert f["ranges"]["alt_max"] is not None


def test_senza_notti_la_dashboard_lo_dice_invece_di_mentire(catalogo):  # noqa: F811
    screening_service.run_screening()
    dati = dash.tonight()
    assert dati["nights"] == [] and dati["rows"] == []
    assert dash.best_sites() == []
