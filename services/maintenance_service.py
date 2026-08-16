"""Manutenzione settimanale: potare i registri e tenere il planner informato.

Due registri crescono senza limite e non servono a nulla dopo qualche mese:
`job_run` (una riga per esecuzione) e `external_call` (una riga per chiamata a
MPC o JPL). Vanno potati, o fra un anno il database contiene più cronaca che
astronomia.

`ANALYZE` sta qui e non solo dopo l'import perché le statistiche invecchiano:
è già costato un'ora di CPU una volta (MEMORANDUM 2026-08-15), e rifarlo una
volta a settimana costa qualche secondo.

**Niente VACUUM automatico.** Su un database da un gigabyte riscrive tutto il
file e blocca gli scrittori per minuti, per recuperare spazio che gli import
successivi riuseranno comunque. Si fa a mano, quando serve davvero.
"""
from __future__ import annotations

import logging

from core.db import connect, transaction
from services.jobs import run_job

log = logging.getLogger("sky42.manutenzione")

KEEP_JOB_RUN_DAYS = 90
KEEP_EXTERNAL_CALL_DAYS = 30


def run_housekeeping() -> dict:
    with run_job("housekeeping") as ctx:
        conn = connect()
        try:
            with transaction(conn):
                # julianday e non confronto fra stringhe: i nostri timestamp
                # hanno la 'T' e la 'Z', datetime('now') no, e come testo il
                # confronto sbaglia in silenzio (MEMORANDUM 2026-08-15).
                cur = conn.execute(
                    "DELETE FROM job_run WHERE julianday(started_at) < julianday('now') - ?",
                    (KEEP_JOB_RUN_DAYS,),
                )
                job_rows = cur.rowcount
                cur = conn.execute(
                    "DELETE FROM external_call WHERE julianday(called_at) < julianday('now') - ?",
                    (KEEP_EXTERNAL_CALL_DAYS,),
                )
                call_rows = cur.rowcount

                # Le versioni di catalogo si tengono tutte: sono poche righe e
                # dicono da dove viene ogni dato. Si potano solo i file scaricati
                # che non sono più l'ultima versione della loro sorgente.
                conn.execute(
                    """DELETE FROM catalog_version
                       WHERE id NOT IN (SELECT max(id) FROM catalog_version GROUP BY source)
                         AND julianday(downloaded_at) < julianday('now') - 180"""
                )

            conn.execute("ANALYZE")
            pagine = conn.execute("PRAGMA page_count").fetchone()[0]
            libere = conn.execute("PRAGMA freelist_count").fetchone()[0]
            pagina = conn.execute("PRAGMA page_size").fetchone()[0]
        finally:
            conn.close()

        ctx.n_processed = job_rows + call_rows
        ctx.detail = {
            "job_run_potati": job_rows,
            "external_call_potati": call_rows,
            "db_mb": round(pagine * pagina / 1e6, 1),
            "spazio_libero_mb": round(libere * pagina / 1e6, 1),
        }
        log.info("manutenzione: %s", ctx.detail)
        return ctx.detail
