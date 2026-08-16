"""Log su file. Copiato nello spirito da stock42: se l'app parte senza console
(container, LaunchAgent) un errore all'import sparirebbe senza lasciare traccia.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys
from pathlib import Path

from core import config

_configured = False


def setup_file_logging(level: int = logging.INFO) -> Path:
    """Configura il log su file (con rotazione) e su console se c'è.

    Restituisce il percorso del file, così l'avvio può dirlo.
    """
    global _configured
    config.ensure_dirs()
    path = config.LOG_DIR / "sky42.log"
    if _configured:
        return path

    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)-24s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    root = logging.getLogger()
    root.setLevel(level)

    fh = logging.handlers.RotatingFileHandler(
        path, maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    root.addHandler(fh)

    if has_console():
        sh = logging.StreamHandler(sys.stderr)
        sh.setFormatter(fmt)
        root.addHandler(sh)

    # NiceGUI e httpx sono loquaci a INFO: non devono coprire i nostri messaggi.
    for noisy in ("httpx", "httpcore", "watchfiles", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _configured = True
    return path


def has_console() -> bool:
    return sys.stderr is not None and sys.stderr.isatty()
