"""Configurazione e percorsi. È l'unico modulo che sa dove stanno i file.

Nessun altro modulo costruisce percorsi assoluti: si importa da qui, così lo
stesso codice gira dal venv, dal container e dai test (che puntano DATA_DIR a
una cartella temporanea).
"""
from __future__ import annotations

import os
from pathlib import Path

APP_NAME = "sky42"

# Porta di servizio. brain42 sta su 8142, stock42 su 8042.
PORT = int(os.environ.get("SKY42_PORT", 8242))
HOST = os.environ.get("SKY42_HOST", "127.0.0.1")

ROOT = Path(__file__).resolve().parent.parent

# Radice dei dati: unico bind mount del container.
DATA_DIR = Path(os.environ.get("SKY42_DATA_DIR", ROOT / "data")).resolve()
DB_PATH = DATA_DIR / "sky42.db"
CATALOG_DIR = DATA_DIR / "catalogs"   # i file scaricati, con il loro hash
EPHEM_DIR = DATA_DIR / "ephem"        # DE440s e simili
CACHE_DIR = DATA_DIR / "cache"        # risposte JPL
LOG_DIR = DATA_DIR / "logs"

# Configurazione osservativa: file YAML versionati in git, non nel database.
SITES_DIR = Path(os.environ.get("SKY42_SITES_DIR", ROOT / "config" / "sites"))

SCHEMA_PATH = ROOT / "docs" / "schema.sql"

# --- Il Mac mini fa girare altro: sky42 è un ospite -------------------------
# Vedi MEMORANDUM 2026-08-15. Questi numeri sono la differenza fra "non te ne
# accorgi" e "la macchina arranca", e vanno tenuti bassi di proposito.

# Processi paralleli per il lavoro numerico. Mai os.cpu_count().
MAX_WORKERS = int(os.environ.get("SKY42_MAX_WORKERS", 2))

# Priorità: i job di sky42 perdono contro tutto il resto.
NICE_LEVEL = int(os.environ.get("SKY42_NICE", 10))

# Carico medio a 1 minuto **per core** oltre il quale i job pesanti aspettano
# invece di proseguire. 1.0 = la macchina è già occupata quanto i suoi core.
# 0 = controllo disattivato.
LOAD_LIMIT = float(os.environ.get("SKY42_LOAD_LIMIT", 1.0))

# Oggetti per blocco negli import e nei calcoli: fra un blocco e l'altro il
# job guarda il carico e può fermarsi. Piccolo = più reattivo, più overhead.
CHUNK_SIZE = int(os.environ.get("SKY42_CHUNK_SIZE", 20_000))

# --- Sorgenti dati ----------------------------------------------------------
# La fonte è l'MPC; ASTORB è lo strato dell'incertezza. Vedi MEMORANDUM.

MPCORB_URL = "https://www.minorplanetcenter.net/Extended_Files/mpcorb_extended.json.gz"
ASTORB_URL = "https://ftp.lowell.edu/pub/elgb/astorb.dat.gz"
COMETELS_URL = "https://www.minorplanetcenter.net/iau/MPCORB/CometEls.txt"

# L'MPC chiede di identificarsi. Un contatto vero evita di essere bloccati in
# silenzio, ed è educazione verso un servizio pubblico e gratuito.
USER_AGENT = os.environ.get(
    "SKY42_USER_AGENT",
    "sky42/0.1 (osservatore privato; ddemartin@gmail.com)",
)

HTTP_TIMEOUT = float(os.environ.get("SKY42_HTTP_TIMEOUT", 120))

# --- Soglie scientifiche ----------------------------------------------------
# Stanno qui solo come valore iniziale: la copia autorevole vive nella tabella
# `setting`, modificabile senza toccare il codice.

TISSERAND_MAX = 3.0

# Classi orbitali escluse dalla popolazione "asteroidi su orbita cometaria".
# Misurato il 2026-08-15: senza questa esclusione il 58% degli oggetti con
# Tj < 3 sono Troiani, Hilda e oggetti distanti, cioè risonanti stabili — il
# contrario di quello che si cerca. Vedi MEMORANDUM.
ACO_EXCLUDED_CLASSES = ("Jupiter Trojan", "Hilda", "Distant Object")


def ensure_dirs() -> None:
    """Crea le cartelle dati. Idempotente, si chiama a ogni avvio."""
    for d in (DATA_DIR, CATALOG_DIR, EPHEM_DIR, CACHE_DIR, LOG_DIR):
        d.mkdir(parents=True, exist_ok=True)
