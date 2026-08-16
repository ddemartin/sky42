"""Configurazione dei test.

Ogni test gira su una cartella dati temporanea, **mai** su quella vera: qui c'è
un database da un gigabyte che è costato due minuti di import, e un test che lo
tocca è un test che prima o poi lo cancella.

L'assegnazione della variabile d'ambiente deve avvenire prima di qualunque
import di `core.config`, che la legge una volta sola al caricamento. `conftest.py`
è importato da pytest prima dei moduli di test, quindi qui è il posto giusto.
"""
from __future__ import annotations

import os
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="sky42-test-"))
os.environ["SKY42_DATA_DIR"] = str(_TMP)

# Le effemeridi planetarie sono l'unica eccezione alla cartella temporanea: 32 MB
# immutabili, uguali per chiunque, che non ha senso riscaricare a ogni sessione
# di test. Si leggono soltanto — il database vero resta fuori portata.
os.environ.setdefault("SKY42_EPHEM_DIR", str(Path(__file__).parent / "data" / "ephem"))
os.environ["SKY42_LOAD_LIMIT"] = "0"      # niente attese sul carico durante i test
os.environ["SKY42_TESTING"] = "1"         # main.py non deve controllare la porta

import pytest  # noqa: E402


@pytest.fixture()
def db():
    """Database vuoto e nuovo per ogni test."""
    from core import config
    from core.db import init_db

    if config.DB_PATH.exists():
        for suffix in ("", "-wal", "-shm"):
            Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
    init_db()
    yield
    for suffix in ("", "-wal", "-shm"):
        Path(str(config.DB_PATH) + suffix).unlink(missing_ok=True)
