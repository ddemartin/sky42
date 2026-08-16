"""Entry point di sky42.

    .venv/bin/python main.py        avvia l'interfaccia su http://127.0.0.1:8242

Il servizio in esercizio gira in Docker sul Mac mini; questo è lo stesso
processo, con l'ascolto su 0.0.0.0 via variabile d'ambiente.
"""
from __future__ import annotations

import os

# PRIMA di importare numpy: su macOS Accelerate si prende tutti i core per una
# singola operazione su array, e il Mac mini fa girare altro. Il parallelismo lo
# decidiamo noi (MEMORANDUM 2026-08-15). Va fatto qui perché queste variabili si
# leggono al caricamento della libreria, non all'uso.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
os.environ.setdefault("MKL_NUM_THREADS", "1")

import logging  # noqa: E402
import socket  # noqa: E402

from core.applog import has_console, setup_file_logging  # noqa: E402

LOG_PATH = setup_file_logging()

from nicegui import app, ui  # noqa: E402

from core.config import APP_NAME, HOST, PORT  # noqa: E402
from core.db import init_db  # noqa: E402
from services.scheduler import scheduler  # noqa: E402

# La sola importazione registra le rotte con i decoratori @ui.page.
import gui.pages.home  # noqa: E402,F401
import gui.pages.catalogo  # noqa: E402,F401
import gui.pages.osservatori  # noqa: E402,F401
import gui.pages.oggetto  # noqa: E402,F401
import gui.pages.pianificatore  # noqa: E402,F401
import gui.health  # noqa: E402,F401  registra GET /health sul FastAPI di NiceGUI

log = logging.getLogger("sky42.avvio")


def _porta_occupata(port: int) -> bool:
    """Un'altra istanza è già viva? Meglio dirlo che morire su un errore di socket."""
    try:
        with socket.create_connection(("127.0.0.1", port), timeout=0.5):
            return True
    except OSError:
        return False


if __name__ in {"__main__", "__mp_main__"}:
    log.info("avvio %s — log in %s", APP_NAME, LOG_PATH)

    # Il client simulato dei test esegue questo file come se fosse `__main__`
    # (è così che intercetta `ui.run`). Senza questa guardia, un'istanza aperta
    # sulla 8242 farebbe fallire i test con un SystemExit incomprensibile.
    if not os.environ.get("SKY42_TESTING") and _porta_occupata(PORT):
        log.warning("porta %d già in uso: un'altra istanza è attiva, esco", PORT)
        raise SystemExit(0)

    # Crea lo schema al primo avvio e applica le migrazioni mancanti.
    init_db()

    # L'hardware descritto negli YAML deve essere nel database prima che si
    # apra una pagina: i file sono la fonte di verità e un `git pull` non deve
    # richiedere che qualcuno si ricordi di premere un pulsante. Costa
    # millisecondi ed è idempotente; se un file è rotto, lo dice il log e il
    # servizio parte lo stesso.
    from services.sites_service import startup_reconcile  # noqa: E402

    startup_reconcile()

    # Il pianificatore sta dentro questo processo: un cron separato che apre il
    # database mentre l'app gira sarebbe un secondo scrittore su SQLite.
    # `on_startup` e non qui: deve partire quando c'è già il loop di eventi, e
    # non deve ritardare l'apertura della porta.
    app.on_startup(scheduler.start)
    app.on_shutdown(scheduler.shutdown)

    ui.run(title=APP_NAME, host=HOST, port=PORT, reload=False,
           show=has_console(), dark=None, favicon="🔭")
