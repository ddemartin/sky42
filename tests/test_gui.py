"""Le pagine si costruiscono davvero.

Una rotta che risponde 200 non dimostra niente: in NiceGUI il contenuto nasce
quando il client si collega, e un errore dentro `redraw()` produce una pagina
vuota con un log che nessuno guarda. Qui c'è un client simulato, senza browser.
"""
from __future__ import annotations

import gzip
import json

import pytest
from nicegui import ui
from nicegui.testing import User

from services import ingest_service as ing
from tests.test_parsers import ASTORB_CERES, COMET_HALEBOPP, MPCORB_SAMPLE

# `user_plugin` e non `plugin`: quello completo tira dentro selenium e un
# browser vero, che qui non serve — le pagine si verificano in memoria.
pytest_plugins = ["nicegui.testing.user_plugin"]


@pytest.fixture()
def catalogo_minimo(db, tmp_path):
    """Un catalogo di tre oggetti: basta a far disegnare ogni riquadro."""
    mpc = tmp_path / "mpcorb.json.gz"
    with gzip.open(mpc, "wt", encoding="utf-8") as fh:
        json.dump(MPCORB_SAMPLE, fh, indent=1)
    ast = tmp_path / "astorb.dat"
    ast.write_text(ASTORB_CERES + "\n", encoding="utf-8")
    com = tmp_path / "CometEls.txt"
    com.write_text(COMET_HALEBOPP + "\n", encoding="utf-8")

    ing.sync_mpcorb(local_path=mpc)
    ing.sync_cometels(local_path=com)
    ing.sync_astorb(local_path=ast)


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.catalogo")
async def test_home_si_disegna(user: User, catalogo_minimo):
    await user.open("/")
    await user.should_see("Funzioni")
    await user.should_see("Catalogo")
    # Le funzioni non ancora costruite si vedono, spente: la home dice sempre
    # a che punto è il progetto.
    await user.should_see("presto")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.catalogo")
async def test_catalogo_mostra_i_numeri(user: User, catalogo_minimo):
    await user.open("/catalogo")
    await user.should_see("Sorgenti")
    await user.should_see("Popolazione Tj < 3")
    await user.should_see("oggetti in catalogo")
    await user.should_see("con incertezza CEU")
    # Il numero vero: 2 asteroidi + 1 cometa.
    await user.should_see("3")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.catalogo")
async def test_catalogo_conta_gli_oggetti_nuovi(user: User, catalogo_minimo):
    """Quanti ne sono comparsi da ieri, dalla settimana scorsa, dal mese scorso.

    Appena importati sono tutti nuovi in tutte e tre le finestre, ed è proprio il
    caso che la pagina deve saper spiegare invece di far passare l'età del
    database per una notizia astronomica.
    """
    await user.open("/catalogo")
    await user.should_see("Oggetti nuovi in catalogo")
    await user.should_see("ultime 24 ore")
    await user.should_see("ultimi 30 giorni")
    await user.should_see("archivio più giovane della finestra")
    await user.should_see("non la data di scoperta")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.catalogo")
async def test_catalogo_regge_il_database_vuoto(user: User, db):
    """Al primo avvio non c'è niente: la pagina deve dirlo, non rompersi."""
    await user.open("/catalogo")
    await user.should_see("Sorgenti")
    await user.should_see("archivio vuoto")
    await user.should_see("mai scaricato")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.catalogo")
async def test_import_da_file_locale_non_dice_mai_importato(user: User, catalogo_minimo):
    """Regressione: i dati ci sono, quindi la pagina non deve dire che mancano.

    `catalog_version` racconta gli scaricamenti; un import da file locale — o un
    database ripristinato da backup — popola tutto senza lasciarne traccia. Lo
    stato si legge dai dati.
    """
    await user.open("/catalogo")
    await user.should_see("in archivio")
    await user.should_see("importato da file locale")
    await user.should_not_see("archivio vuoto")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.catalogo",
                               "gui.pages.pianificatore")
async def test_pianificatore_si_disegna_anche_da_fermo(user: User, db):
    """Il pianificatore nei test non è avviato: la pagina deve dirlo, non rompersi.

    È lo stesso stato in cui si trova chi apre la pagina dopo che il servizio è
    morto — cioè proprio quando serve che la pagina funzioni.
    """
    await user.open("/pianificatore")
    await user.should_see("fermo")
    await user.should_see("Backup")
    await user.should_see("Nessuna copia ancora")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.osservatori")
async def test_osservatori_mostra_i_derivati(user: User, db, monkeypatch, tmp_path):
    """La pagina esiste per far vedere scala e campo *calcolati*: se mostrasse
    solo quello che c'è nel file, non servirebbe a niente."""
    import textwrap

    from core import config
    from tests.test_sites import SITO
    from services import sites_service

    siti = tmp_path / "sites"
    siti.mkdir()
    (siti / "cile.yml").write_text(textwrap.dedent(SITO), encoding="utf-8")
    monkeypatch.setattr(config, "SITES_DIR", siti)
    sites_service.run_reconcile()

    from services import night_service
    night_service.plan_nights(3)

    await user.open("/osservatori")
    await user.should_see("Río Hurtado, Cile")
    await user.should_see("cielo allo zenit 21.80 mag/arcsec²")
    await user.should_see("Scala e campo non stanno nei file")

    # Il contenuto delle tabelle non è testo della pagina (Quasar lo disegna
    # nel browser), quindi si guarda la riga che la pagina ha costruito: è lì
    # che si vede se i derivati sono arrivati fin qui.
    righe = [r for t in user.find(ui.table).elements for r in t.rows]
    setup = next(r for r in righe if r.get("code") == "rc700-qhy600-bin2")
    assert setup["scala"] == "0.342"            # arcsec/px, derivata
    assert setup["campo"] == "27.3 × 18.2"      # arcmin, derivato
    assert setup["f"] == "6.5"                  # 4540/700
    assert setup["vlim"].startswith("21.3 / 20.8 astr.")

    # Le notti ci sono, e con gli orari in ora locale del sito: un tramonto
    # scritto in UTC non aiuta a decidere se stasera vale la pena.
    notte = next(r for r in righe if "night" not in r and r.get("ore"))
    assert float(notte["ore"]) > 0
    assert ":" in notte["tramonto"] and ":" in notte["buio"]


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.osservatori")
async def test_osservatori_regge_il_database_vuoto(user: User, db):
    await user.open("/osservatori")
    await user.should_see("Nessun sito in archivio")
    await user.should_see("mai riallineato")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.oggetto")
async def test_oggetto_mostra_l_effemeride(user: User, catalogo_minimo):
    """Cerere dal catalogo di prova: la pagina deve calcolare, non solo cercare."""
    await user.open("/oggetto?desig=1")
    await user.should_see("Ceres")
    await user.should_see("Tj =")

    righe = [r for t in user.find(ui.table).elements for r in t.rows]
    assert len(righe) == 31, "trenta giorni più il primo"
    prima = righe[0]
    assert prima["ra"].endswith("s") and "h" in prima["ra"]
    assert float(prima["v"]) < 15, "Cerere non può essere più debole di V 15"
    assert 0.5 < float(prima["delta"]) < 5.0


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.oggetto")
async def test_oggetto_suggerisce_quando_non_trova(user: User, catalogo_minimo):
    await user.open("/oggetto?desig=Cer")
    await user.should_see("Forse cercavi")
    await user.should_see("Ceres")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.oggetto")
async def test_una_cometa_arriva_con_i_suoi_avvisi(user: User, catalogo_minimo):
    """La magnitudine cometaria non si mostra mai senza la sua incertezza."""
    await user.open("/oggetto?desig=C/1995 O1")
    await user.should_see("Hale-Bopp")
    await user.should_see("è un ordinamento, non una previsione")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.oggetto")
async def test_si_cerca_anche_col_solo_nome(user: User, catalogo_minimo):
    """«Ceres», non «(1) Ceres» né «A801 AA»: è così che si chiama a voce."""
    await user.open("/oggetto?desig=Ceres")
    await user.should_see("Tj =")
    righe = [r for t in user.find(ui.table).elements for r in t.rows]
    assert righe, "trovato l'oggetto ma nessuna effemeride"


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.oggetto")
async def test_oggetto_mostra_le_finestre_di_stanotte(user: User, catalogo_minimo,
                                                      monkeypatch, tmp_path):
    """La domanda del progetto, sulla pagina: da dove e in che finestra."""
    import textwrap

    from core import config
    from services import sites_service
    from tests.test_sites import SITO

    siti = tmp_path / "sites"
    siti.mkdir()
    (siti / "cile.yml").write_text(textwrap.dedent(SITO), encoding="utf-8")
    monkeypatch.setattr(config, "SITES_DIR", siti)
    sites_service.run_reconcile()

    await user.open("/oggetto?desig=1")
    await user.should_see("Stanotte")
    await user.should_see("RC700 + QHY600 bin2 L")


@pytest.fixture()
def sito_e_screening(catalogo_minimo, monkeypatch, tmp_path):
    """Un sito attivo e uno screening già girato: il caso in cui c'è tutto."""
    import textwrap

    from core import config
    from core.db import connect
    from services import screening_service, sites_service
    from tests.test_sites import SITO

    siti = tmp_path / "sites"
    siti.mkdir()
    (siti / "cile.yml").write_text(textwrap.dedent(SITO), encoding="utf-8")
    monkeypatch.setattr(config, "SITES_DIR", siti)
    sites_service.run_reconcile()

    # Cerere ha Tj > 3 e non è nella popolazione: ce la mette la watchlist,
    # che è precisamente il motivo per cui la watchlist esiste.
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO watchlist (target_id, added_at) "
            "SELECT id, '2026-08-17T00:00:00Z' FROM target WHERE primary_desig='A801 AA'")
    finally:
        conn.close()
    screening_service.run_screening()


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.oggetto")
async def test_oggetto_mostra_il_radar_e_il_punteggio(user: User, sito_e_screening):
    """Le tre cose nuove di M1, sulla pagina: stato, finestra dei due anni, score."""
    await user.open("/oggetto?desig=1")
    await user.should_see("Radar")
    await user.should_see("V adesso")
    # Il punteggio non compare mai senza la sua scomposizione (regola 5).
    await user.should_see("profilo default")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.oggetto")
async def test_senza_screening_la_sezione_radar_non_compare(user: User, catalogo_minimo):
    """Un oggetto fuori dalla popolazione monitorata non mostra una scheda vuota:
    «nessun dato» per un milione e mezzo di righe è rumore, non informazione."""
    await user.open("/oggetto?desig=1")
    await user.should_see("Tj =")
    await user.should_not_see("V adesso")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.stanotte")
async def test_stanotte_si_disegna_con_la_catena_accesa(user: User, sito_e_screening):
    """La pagina per cui esiste il progetto: tre sezioni, e l'età dei tre job."""
    from services import night_service, radar_service, window_service

    night_service.plan_nights(2)
    window_service.run_windows(n_nights=1)
    radar_service.run_radar()

    await user.open("/stanotte")
    await user.should_see("Cosa osservare stanotte")
    await user.should_see("Best site tonight")
    await user.should_see("Coming into range")
    await user.should_see("Tj < 3 che tornano")
    # L'età dei lavori sta in cima: una classifica su finestre di tre giorni fa
    # è sbagliata in un modo che non si vede guardando le righe.
    await user.should_see("finestre")
    # I filtri e la ricerca fanno parte della pagina, non di una sotto-pagina.
    await user.should_see("cerca: nome o designazione…")
    await user.should_see("Altri filtri")
    await user.should_see("classe orbitale")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.stanotte")
async def test_stanotte_dice_quando_e_l_elenco_a_finire(user: User, sito_e_screening):
    """«Fine dell'elenco» e non il silenzio: un elenco che finisce esattamente
    su un multiplo di venti è indistinguibile da un pulsante che non ha
    funzionato.

    Il punteggio si mette a mano: gli oggetti finti non sono per forza utili
    nella notte in cui gira la suite, e senza punteggio non c'è nessun elenco da
    far finire. Il ranking ha i suoi test.
    """
    from core.db import connect
    from services import night_service, radar_service, window_service

    night_service.plan_nights(2)
    window_service.run_windows(n_nights=1)
    radar_service.run_radar()
    conn = connect()
    try:
        conn.execute("UPDATE observation_window SET score=0.8, grade='PRIME', "
                     "useful_hours=3.0")
    finally:
        conn.close()

    await user.open("/stanotte")
    await user.should_see("fine dell'elenco")
    await user.should_see("hanno una finestra utile stanotte")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.catalogo",
                               "gui.pages.stanotte")
async def test_la_fascetta_porta_alle_altre_pagine(user: User, catalogo_minimo):
    """Le scorciatoie in intestazione, come in stock42: passare dalla home per
    andare da una funzione all'altra è un giro in più su un gesto che si fa
    venti volte a sera.

    Si verifica che i link *ci siano* e che le funzioni con `route=None` restino
    fuori — un pulsante che non porta da nessuna parte insegna solo a non
    fidarsi della barra. La navigazione vera no: `ui.navigate.to` sta su un
    pulsante con dentro icona ed etichetta, e il click simulato di NiceGUI
    colpisce l'etichetta, non il pulsante.
    """
    await user.open("/catalogo")
    await user.should_see("Stanotte")
    await user.should_see("Osservatori")
    await user.should_see("Candidati MPC")
    await user.should_not_see("Returning radar")   # route=None: non è un link
    # Sulla home no: lì l'elenco delle funzioni *è* la pagina.
    await user.open("/")
    await user.should_see("console di follow-up del Sistema Solare")


def test_il_link_alla_scheda_usa_il_parametro_giusto_e_codifica():
    """Regressione: il collegamento puntava a `?q=`, che la pagina Oggetto
    ignora — si apriva una scheda vuota, indistinguibile da «non trovato». E le
    designazioni cometarie hanno barre e spazi, che senza `quote` troncano
    l'URL."""
    from gui.layout import link_oggetto

    assert link_oggetto("3200") == "/oggetto?desig=3200"
    assert link_oggetto("C/2019 E3") == "/oggetto?desig=C%2F2019%20E3"
    assert "?q=" not in link_oggetto("C/2019 E3")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.oggetto",
                               "gui.pages.stanotte")
async def test_il_link_costruito_apre_davvero_la_scheda(user: User, catalogo_minimo):
    """Il link non si verifica come stringa e basta: si apre, e dentro ci deve
    essere l'oggetto. È il giro che era rotto."""
    from gui.layout import link_oggetto

    await user.open(link_oggetto("C/1995 O1"))
    await user.should_see("Hale-Bopp")
    await user.should_see("Tj =")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.programma")
async def test_programma_mostra_propositi_sessioni_e_scaduti(user: User,
                                                             sito_e_screening):
    """Il giro completo dell'utente: decido, osservo, e quel che non ho fatto
    resta in elenco con il suo motivo."""
    from services import intent_service, radar_service

    radar_service.run_radar()
    intent_service.add("1", purpose="astrometria", source="test")
    intent_service.add("C/1995 O1", source="test")
    intent_service.log_observation("1", obs_start="2026-08-17T03:00:00Z",
                                   n_frames=10, exposure_s=120.0,
                                   outcome="detected", limiting_mag=21.0)

    await user.open("/programma")
    await user.should_see("Programma osservativo")
    await user.should_see("In programma")
    await user.should_see("Come sono andati")
    await user.should_see("Sessioni")

    righe = [r for t in user.find(ui.table).elements for r in t.rows]
    chiuso = next(r for r in righe if r.get("motivo") == "osservato")
    assert chiuso["stato"] == "osservato"
    sessione = next(r for r in righe if r.get("limite") == "21.0")
    assert sessione["esito"] == "detected" and sessione["pose"] == "10"


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.programma")
async def test_programma_regge_il_database_vuoto(user: User, db):
    await user.open("/programma")
    await user.should_see("Niente in programma")
    await user.should_see("Nessuna sessione registrata")


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.stanotte")
async def test_stanotte_regge_il_database_vuoto(user: User, db):
    """Chi apre la pagina prima che i job abbiano girato deve leggere *perché*
    è vuota, non trovarsi davanti tre tabelle senza righe."""
    await user.open("/stanotte")
    await user.should_see("Cosa osservare stanotte")
    await user.should_see("Nessuna notte calcolata")


@pytest.fixture()
def candidati(db, tmp_path):
    """Una lista NEOCP già letta, come dopo un giro del watcher."""
    from services import candidate_service
    from tests.test_neocp import NEOCP_TXT

    f = tmp_path / "neocp.txt"
    f.write_text(NEOCP_TXT, encoding="utf-8")
    candidate_service.poll("NEOCP", local_path=f)
    # Poi uno sparisce: la pagina deve mostrare anche quello.
    f.write_text("\n".join(NEOCP_TXT.splitlines()[1:]) + "\n", encoding="utf-8")
    candidate_service.poll("NEOCP", local_path=f)


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.candidati")
async def test_candidati_mostra_lista_e_spariti(user: User, candidati):
    """Il contenuto delle tabelle si legge da `.rows`: `should_see` confronta la
    rappresentazione dell'elemento, che per una tabella è troncata."""
    await user.open("/candidati")
    await user.should_see("In lista adesso")
    # Chi è sparito non sparisce anche dalla pagina: è la parte che l'MPC non
    # conserva, ed è tutto il motivo per cui il watcher esiste.
    await user.should_see("Spariti dalla lista")

    # Le due tabelle si distinguono dalle colonne e non dall'ordine in cui
    # `find` le restituisce, che non è garantito: solo quella dei candidati
    # ancora in lista porta le coordinate, perché è l'unica che si punta.
    tabelle = user.find(ui.table).elements
    assert len(tabelle) == 2
    per_colonne = {tuple(c["name"] for c in t.columns): list(t.rows) for t in tabelle}
    in_lista = next(r for c, r in per_colonne.items() if "ra" in c)
    spariti = next(r for c, r in per_colonne.items() if "ra" not in c)

    assert len(in_lista) == 6 and len(spariti) == 1
    assert spariti[0]["desig"] == "ST26H52", "il candidato tolto dalla lista"
    aperto = [r for r in in_lista if r["desig"] == "ST26H50"][0]
    assert aperto["lista"] == "NEOCP"
    # La RA si mostra in ore, ma il database la tiene in gradi: 22.6102 h.
    assert aperto["ra"].startswith("22h")
    assert aperto["nonvisto"] == "0.82 g"


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.candidati")
async def test_candidati_mostra_che_fine_hanno_fatto(user: User, candidati, tmp_path):
    """Il destino in pagina: prima si chiude un candidato, poi lo si legge."""
    from services import candidate_service
    from tests.test_destiny import _pagina

    f = tmp_path / "prev.html"
    f.write_text(_pagina(), encoding="utf-8")
    candidate_service.poll_destiny(local_path=f)

    await user.open("/candidati")
    await user.should_see("Che fine hanno fatto")
    # E la lista di quel che non si sa resta, perché non è vuota: la pagina non
    # deve far credere di sapere tutto.
    await user.should_see("Spariti dalla lista")

    tabelle = user.find(ui.table).elements
    righe = [r for t in tabelle for r in t.rows if "destino" in r]
    assert righe, "la tabella dei destini è stata costruita"
    neo = next(r for r in righe if r["desig"] == "ST26H52")
    assert neo["destino"] == "NEO confermato"
    assert neo["diventato"] == "2026 PN9"
    assert neo["fonte"] == "mpec:2026-Q11"


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.candidati")
async def test_candidati_regge_il_database_vuoto(user: User, db):
    await user.open("/candidati")
    await user.should_see("Nessun candidato in lista")
    await user.should_see("Nessun candidato ancora chiuso")


def test_i_badge_dei_siti_si_raggruppano_per_sito_non_per_setup():
    """Con dieci telescopi su quattro siti, un badge per setup ripeteva
    «utah-great-basin-desert» tre volte senza mai dire quale dei tre: l'unica
    informazione era il *numero* di badge, cioè nessun posto leggibile."""
    from gui.pages.stanotte import _per_sito

    sites = [
        {"site_code": "utah", "site_name": "Utah", "setup_code": "T11",
         "grade": "POOR", "score": 0.2, "useful_hours": 1.0, "depth_margin": 0.1},
        {"site_code": "utah", "site_name": "Utah", "setup_code": "T25",
         "grade": "GOOD", "score": 0.6, "useful_hours": 3.0, "depth_margin": 1.2},
        {"site_code": "utah", "site_name": "Utah", "setup_code": "T21",
         "grade": "NOT_USEFUL", "score": None, "useful_hours": 0.0,
         "depth_margin": -1.0},
        {"site_code": "sso", "site_name": "SSO", "setup_code": "T59",
         "grade": "PRIME", "score": 0.9, "useful_hours": 7.0, "depth_margin": 2.0},
    ]
    righe = _per_sito(sites)
    assert [r["site_code"] for r in righe] == ["sso", "utah"], "il migliore in testa"

    utah = righe[1]
    assert utah["n_setup"] == 3, "un badge solo per i tre strumenti"
    # Il grado del sito è quello del suo setup **migliore**: da Utah stanotte si
    # può fare GOOD, e dirlo POOR o NOT_USEFUL sarebbe una media senza senso.
    assert utah["grade"] == "GOOD"
    # I setup restano tutti nel tooltip, NOT_USEFUL compresi (regola 5), in
    # ordine di punteggio: serve a sapere su cosa ripiegare se il primo è preso.
    assert utah["dettaglio"].index("T25") < utah["dettaglio"].index("T11")
    assert "T21" in utah["dettaglio"] and "NOT_USEFUL" in utah["dettaglio"]
