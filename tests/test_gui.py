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
