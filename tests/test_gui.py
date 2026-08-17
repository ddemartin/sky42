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
async def test_candidati_regge_il_database_vuoto(user: User, db):
    await user.open("/candidati")
    await user.should_see("Nessun candidato in lista")
