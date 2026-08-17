"""Backup delle tabelle che non si possono riscaricare.

Il database sta a 1 GB ed è **quasi tutto rigenerabile**: catalogo, orbite,
tracce, statistiche si riscaricano dall'MPC e da Lowell e si ricalcolano. Un
backup da un giga al giorno per salvare qualche kilobyte di dati veri sarebbe
tutto costo e nessun beneficio.

Quello che non si recupera in nessun modo è poco e prezioso:

  * `mpc_candidate` e `mpc_candidate_snapshot` — l'MPC riscrive la lista NEOCP
    e non conserva niente. La storia di un candidato, dopo la rimozione,
    esiste solo qui;
  * `state_transition` — lo stesso, applicato al nostro archivio;
  * `observation_log` e `watchlist` — di chi osserva;
  * `setup_calibration` — misure fatte sul campo, di notte.

Quindi il backup copia **solo quelle**, in un file SQLite a parte. Oggi pesa
qualche decina di kilobyte; anche fra dieci anni starà in pochi megabyte.

Il backup fuori casa (restic/rclone) è un problema dell'host, come in brain42:
qui si produce solo un'istantanea coerente che il copiatore esterno può
prendere in mano senza fermare il servizio.
"""
from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from core import config
from core.db import connect
from services.jobs import run_job

log = logging.getLogger("sky42.backup")

# Le cinque (sei tabelle) del gruppo non rigenerabile. Se se ne aggiunge una al
# progetto, va aggiunta qui: è l'unico posto che decide cosa sopravvive.
TABLES = [
    "mpc_candidate",
    "mpc_candidate_snapshot",
    "state_transition",
    "observing_intent",
    "observation_log",
    "watchlist",
    "setup_calibration",
]

KEEP_COPIES = 14


def backup_dir() -> Path:
    d = config.DATA_DIR / "backup"
    d.mkdir(parents=True, exist_ok=True)
    return d


def run_backup() -> dict:
    """Scrive data/backup/sky42-dati-<data>.db con le sole tabelle non rigenerabili."""
    with run_job("backup") as ctx:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M")
        dest = backup_dir() / f"sky42-dati-{stamp}.db"
        tmp = dest.with_suffix(".db.part")
        tmp.unlink(missing_ok=True)

        conn = connect()
        counts: dict[str, int] = {}
        try:
            # ATTACH e INSERT ... SELECT: una sola lettura coerente della
            # sorgente, senza fermare il servizio e senza copiare il gigabyte
            # di catalogo che si riscarica.
            conn.execute("ATTACH DATABASE ? AS bkp", (str(tmp),))
            try:
                for table in TABLES:
                    ddl = conn.execute(
                        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?",
                        (table,),
                    ).fetchone()
                    if not ddl or not ddl[0]:
                        continue
                    # Le chiavi esterne verso il gruppo rigenerabile non hanno
                    # senso qui: nel file di backup `target` non esiste.
                    create = ddl[0].replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
                    conn.execute(_strip_references(create).replace(table, f"bkp.{table}", 1))
                    conn.execute(f"INSERT INTO bkp.{table} SELECT * FROM main.{table}")
                    counts[table] = conn.execute(
                        f"SELECT count(*) FROM bkp.{table}"
                    ).fetchone()[0]
            finally:
                conn.execute("DETACH DATABASE bkp")
        finally:
            conn.close()

        tmp.replace(dest)
        removed = _prune()

        ctx.n_processed = sum(counts.values())
        ctx.detail = {
            "file": dest.name,
            "kb": round(dest.stat().st_size / 1024, 1),
            "righe": counts,
            "copie_rimosse": removed,
        }
        log.info("backup: %s (%.1f kB, %d righe)", dest.name,
                 dest.stat().st_size / 1024, ctx.n_processed)
        return ctx.detail


def _strip_references(ddl: str) -> str:
    """Toglie le clausole REFERENCES dal DDL copiato.

    Nel file di backup le tabelle del gruppo rigenerabile non ci sono: una
    chiave esterna verso `target` renderebbe il file irrestituibile senza
    ricostruire prima tutto il catalogo, che è l'opposto di ciò che serve
    quando si sta recuperando.
    """
    import re

    ddl = re.sub(r"\s+REFERENCES\s+\w+\s*\([^)]*\)(\s+ON\s+DELETE\s+\w+(\s+\w+)?)?", "", ddl)
    return ddl


def _prune() -> int:
    """Tiene le ultime KEEP_COPIES copie. Le altre sono spazio e basta."""
    files = sorted(backup_dir().glob("sky42-dati-*.db"))
    removed = 0
    for old in files[:-KEEP_COPIES]:
        old.unlink(missing_ok=True)
        removed += 1
    return removed


def list_backups() -> list[dict]:
    out = []
    for p in sorted(backup_dir().glob("sky42-dati-*.db"), reverse=True):
        st = p.stat()
        out.append({
            "file": p.name,
            "kb": round(st.st_size / 1024, 1),
            "quando": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
            .strftime("%Y-%m-%dT%H:%M:%SZ"),
        })
    return out


def restore_counts(path: Path) -> dict[str, int]:
    """Quante righe contiene un file di backup. Serve a *verificare* un ripristino.

    Un backup che non si è mai provato a leggere non è un backup.
    """
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = [r[0] for r in conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table'").fetchall()]
        return {n: conn.execute(f"SELECT count(*) FROM {n}").fetchone()[0] for n in names}
    finally:
        conn.close()
