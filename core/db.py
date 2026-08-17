"""Accesso a SQLite. Unico posto che apre connessioni e applica i PRAGMA.

Lo schema **è** `docs/schema.sql`: non esiste una seconda copia nel codice. Se
la documentazione e il database possono divergere, prima o poi divergono.
"""
from __future__ import annotations

import logging
import sqlite3
from contextlib import contextmanager
from typing import Iterator

from core import config
from core.timeutil import now_iso

log = logging.getLogger("sky42.db")

# Versione dello schema. Si alza quando si aggiunge una migrazione a MIGRATIONS.
SCHEMA_VERSION = 2

# Migrazioni successive alla prima creazione: {versione: [istruzioni SQL]}.
# Devono essere idempotenti e non distruttive.
MIGRATIONS: dict[int, list[str]] = {
    # 2 — il radar: il candidato in attesa di conferma, e il profilo di
    # punteggio iniziale. Le colonne mancavano perché la macchina a stati non
    # c'era; `ALTER TABLE ADD COLUMN` non tocca i dati esistenti e gira una
    # volta sola, protetta da `user_version`.
    2: [
        "ALTER TABLE target_state ADD COLUMN pending_state TEXT",
        "ALTER TABLE target_state ADD COLUMN pending_since TEXT",
        "ALTER TABLE target_state ADD COLUMN pending_count INTEGER NOT NULL DEFAULT 0",
    ],
}


def connect(readonly: bool = False) -> sqlite3.Connection:
    """Connessione con i PRAGMA di casa.

    WAL perché l'interfaccia legge mentre i job scrivono; `busy_timeout` perché
    un import lungo non deve far fallire una lettura della dashboard, deve
    farla aspettare.
    """
    config.ensure_dirs()
    conn = sqlite3.connect(config.DB_PATH, timeout=30.0, isolation_level=None)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA busy_timeout=10000")
    # 64 MB di cache: gli import toccano indici su milioni di righe, e il
    # default (2 MB) trasforma un import in una sequenza di letture su disco.
    conn.execute("PRAGMA cache_size=-64000")
    return conn


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    """Transazione esplicita: `isolation_level=None` disattiva quella implicita."""
    conn.execute("BEGIN")
    try:
        yield conn
    except Exception:
        conn.execute("ROLLBACK")
        raise
    else:
        conn.execute("COMMIT")


def init_db() -> None:
    """Crea lo schema se manca, poi applica le migrazioni mancanti.

    Idempotente: gira a ogni avvio.
    """
    conn = connect()
    try:
        tables = conn.execute(
            "SELECT count(*) FROM sqlite_master WHERE type='table'"
        ).fetchone()[0]

        if tables == 0:
            log.info("database vuoto: creo lo schema da %s", config.SCHEMA_PATH)
            conn.executescript(config.SCHEMA_PATH.read_text(encoding="utf-8"))
            conn.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
            _seed(conn)
            return

        current = conn.execute("PRAGMA user_version").fetchone()[0]
        for version in sorted(MIGRATIONS):
            if version > current:
                log.info("migrazione schema -> %d", version)
                for stmt in MIGRATIONS[version]:
                    _migrate(conn, stmt)
                conn.execute(f"PRAGMA user_version={version}")
        # Fuori dal ciclo delle migrazioni: è un dato di partenza, non una
        # modifica di schema, e deve comparire anche nei database creati prima
        # che il ranking esistesse. `INSERT OR IGNORE` sul nome, quindi un
        # profilo modificato a mano non viene mai riscritto.
        _seed_scoring_profile(conn)
    finally:
        conn.close()
    close_orphaned_jobs()


def _migrate(conn: sqlite3.Connection, stmt: str) -> None:
    """Esegue un'istruzione di migrazione, tollerando che sia già stata applicata.

    `user_version` si alza **dopo** l'ultima istruzione del gruppo: se una
    migrazione da tre `ALTER TABLE` si interrompe alla seconda, la versione
    resta indietro e al riavvio si riparte dalla prima — che a quel punto
    fallirebbe con «duplicate column name» e lascerebbe il database bloccato a
    ogni avvio, per sempre. Una colonna che c'è già è esattamente il risultato
    voluto, quindi si tira dritto.

    Qualunque altro errore si rilancia: una migrazione che fallisce davvero
    deve fermare l'avvio e comparire nel log, non passare inosservata.
    """
    try:
        conn.execute(stmt)
    except sqlite3.OperationalError as exc:
        if "duplicate column name" not in str(exc):
            raise
        log.debug("migrazione già applicata, salto: %s", stmt)


def close_orphaned_jobs(older_than_hours: int = 2) -> int:
    """Chiude le righe rimaste 'running' da un processo morto.

    Un job interrotto da un riavvio, da un `kill` o da un crash non arriva mai a
    scrivere il proprio esito, e resterebbe «in corso» per sempre — sulla pagina
    del pianificatore, esattamente dove si va a guardare se qualcosa è rotto.

    Solo le righe più vecchie di `older_than_hours`: il lavoro più lungo che
    abbiamo misurato è un import di catalogo da 2 minuti e mezzo, quindi due ore
    sono un margine di quarantacinque volte. La soglia evita che un `cli.py`
    lanciato a mano dichiari interrotto un lavoro che l'interfaccia sta davvero
    eseguendo in quel momento.

    Il confronto passa da `julianday` e **non** dal confronto fra stringhe: i
    nostri timestamp sono `2026-08-15T15:28:07Z` mentre `datetime('now', ...)`
    produce `2026-08-15 10:46:40`. Confrontarli come testo dà il risultato
    sbagliato per tutte le righe dello stesso giorno, perché 'T' viene dopo lo
    spazio — e lo sbaglia in silenzio.
    """
    conn = connect()
    try:
        cur = conn.execute(
            """UPDATE job_run SET status='failed',
                   finished_at=?, error='interrotto: processo terminato'
               WHERE status='running'
                 AND julianday(started_at) < julianday('now') - ?""",
            (now_iso(), older_than_hours / 24.0),
        )
        if cur.rowcount:
            log.info("chiuse %d esecuzioni rimaste appese", cur.rowcount)
        return cur.rowcount
    finally:
        conn.close()


def _seed(conn: sqlite3.Connection) -> None:
    """Valori iniziali. Da qui in poi si modificano dall'interfaccia, non nel codice."""
    import json

    settings = {
        "tisserand_max": config.TISSERAND_MAX,
        "aco_excluded_classes": list(config.ACO_EXCLUDED_CLASSES),
        "screening_months_ahead": 24,
        "screening_years_back": 15,
    }
    conn.executemany(
        "INSERT OR IGNORE INTO setting (key, value, updated_at) VALUES (?,?,?)",
        [(k, json.dumps(v), now_iso()) for k, v in settings.items()],
    )
    _seed_scoring_profile(conn)


def _seed_scoring_profile(conn: sqlite3.Connection) -> None:
    """Il profilo di punteggio di partenza, **solo se non ce n'è nessuno**.

    I pesi vivono nel database e non nel codice (regola 5): questo è il punto
    da cui muoversi guardando le classifiche vere, non un valore giusto. Il
    codice ne tiene una copia come default — `core.ranking.score` — perché il
    calcolo deve funzionare anche su un database in cui qualcuno ha cancellato
    tutti i profili.

    La condizione è «la tabella è vuota» e non «manca quello che si chiama
    default»: chi ha cancellato il profilo di partenza per sostituirlo con il
    proprio non deve vederselo tornare a ogni avvio, e riapparire *attivo*
    accanto al suo sarebbe anche peggio.
    """
    import json

    from core.ranking.score import DEFAULT_GATES, DEFAULT_GRADES, DEFAULT_WEIGHTS

    if conn.execute("SELECT count(*) FROM scoring_profile").fetchone()[0]:
        return

    conn.execute(
        """INSERT OR IGNORE INTO scoring_profile
               (name, target_kind, weights, gates, active, updated_at)
           VALUES ('default', NULL, ?, ?, 1, ?)""",
        (json.dumps(DEFAULT_WEIGHTS),
         json.dumps({**DEFAULT_GATES, "grades": DEFAULT_GRADES}),
         now_iso()),
    )


# --- registro dei job -------------------------------------------------------
# Ogni job lascia una riga. È la prima cosa da guardare quando qualcosa non
# torna: "quale job ha girato per ultimo e cosa ha scritto".


def job_started(job_name: str) -> int:
    conn = connect()
    try:
        cur = conn.execute(
            "INSERT INTO job_run (job_name, started_at, status) VALUES (?,?,'running')",
            (job_name, now_iso()),
        )
        return int(cur.lastrowid)
    finally:
        conn.close()


def job_finished(
    run_id: int,
    status: str,
    n_processed: int | None = None,
    duration_s: float | None = None,
    detail: dict | None = None,
    error: str | None = None,
) -> None:
    import json

    conn = connect()
    try:
        conn.execute(
            """UPDATE job_run SET finished_at=?, status=?, n_processed=?,
                                  duration_s=?, detail_json=?, error=?
               WHERE id=?""",
            (
                now_iso(),
                status,
                n_processed,
                duration_s,
                json.dumps(detail, default=str) if detail else None,
                (error or "")[:2000] or None,
                run_id,
            ),
        )
    finally:
        conn.close()


def last_job_runs(limit: int = 20) -> list[sqlite3.Row]:
    conn = connect()
    try:
        return conn.execute(
            "SELECT * FROM job_run ORDER BY started_at DESC LIMIT ?", (limit,)
        ).fetchall()
    finally:
        conn.close()


def get_setting(key: str, default=None):
    import json

    conn = connect()
    try:
        row = conn.execute("SELECT value FROM setting WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default
    finally:
        conn.close()
