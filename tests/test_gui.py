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


@pytest.mark.module_under_test("gui.pages.home", "gui.pages.osservatori")
async def test_osservatori_regge_il_database_vuoto(user: User, db):
    await user.open("/osservatori")
    await user.should_see("Nessun sito in archivio")
    await user.should_see("mai riallineato")
