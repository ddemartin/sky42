"""Infrastruttura comune dei job di fondo.

Due sole cose, ma vanno rispettate da tutti:

  * ogni job lascia una riga in `job_run` — anche quando fallisce, soprattutto
    quando fallisce;
  * ogni job pesante è **interrompibile e cortese**: lavora a blocchi e fra un
    blocco e l'altro guarda il carico della macchina. Il Mac mini fa girare
    altro, e sky42 è un ospite (MEMORANDUM 2026-08-15).
"""
from __future__ import annotations

import logging
import os
import time
from contextlib import contextmanager
from dataclasses import dataclass, field

from core import config
from core.db import job_finished, job_started

log = logging.getLogger("sky42.jobs")


@dataclass
class JobContext:
    """Passato al corpo del job: ci si scrive quanto è stato fatto."""

    run_id: int
    name: str
    n_processed: int = 0
    detail: dict = field(default_factory=dict)
    cancelled: bool = False


@contextmanager
def run_job(name: str):
    """Registra inizio, fine, durata ed errore di un job.

    Un'eccezione viene registrata e **rilanciata**: lo scheduler deve sapere
    che è andata male, e la riga in `job_run` deve dire perché.
    """
    run_id = job_started(name)
    ctx = JobContext(run_id=run_id, name=name)
    t0 = time.monotonic()
    log.info("job %s: avvio", name)
    try:
        yield ctx
    except Exception as exc:
        job_finished(run_id, "failed", ctx.n_processed, time.monotonic() - t0,
                     ctx.detail, f"{type(exc).__name__}: {exc}")
        log.exception("job %s: fallito", name)
        raise
    else:
        status = "skipped" if ctx.cancelled else "ok"
        dt = time.monotonic() - t0
        job_finished(run_id, status, ctx.n_processed, dt, ctx.detail)
        log.info("job %s: %s in %.1fs (%d elementi)", name, status, dt, ctx.n_processed)


def machine_busy() -> bool:
    """True se la macchina è sotto carico e conviene aspettare.

    `os.getloadavg()` sta nella libreria standard: nessuna dipendenza per una
    misura che serve solo a non dare fastidio. Il carico è normalizzato per
    core, perché un load di 4 su un Mac mini a 8 core non è lo stesso che su 2.
    """
    if config.LOAD_LIMIT <= 0:
        return False
    try:
        load1 = os.getloadavg()[0]
    except (OSError, AttributeError):
        return False        # piattaforma senza load average: si procede
    return load1 / (os.cpu_count() or 1) > config.LOAD_LIMIT


def wait_if_busy(max_wait_s: float = 60.0, poll_s: float = 5.0) -> float:
    """Aspetta che il carico scenda, al massimo `max_wait_s`. Restituisce l'attesa.

    Non aspetta all'infinito: un job che non finisce mai è peggio di un job che
    dà un po' di fastidio. Passato il tempo massimo si procede comunque.
    """
    waited = 0.0
    while machine_busy() and waited < max_wait_s:
        time.sleep(poll_s)
        waited += poll_s
    if waited:
        log.info("carico alto: atteso %.0fs prima di proseguire", waited)
    return waited


def be_nice() -> None:
    """Abbassa la priorità del processo corrente. Idempotente.

    `os.nice(0)` restituisce la priorità attuale senza cambiarla; l'incremento
    si calcola da lì, o chiamandola due volte si scenderebbe ogni volta.
    """
    try:
        current = os.nice(0)
        if current < config.NICE_LEVEL:
            os.nice(config.NICE_LEVEL - current)
    except (OSError, AttributeError):
        pass


def chunked(iterable, size: int | None = None):
    """Genera liste di al più `size` elementi da un iteratore.

    È il modo in cui un import di un milione e mezzo di righe resta una
    sequenza di transazioni brevi invece di una lunghissima che tiene il
    database occupato e non si può interrompere.
    """
    size = size or config.CHUNK_SIZE
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= size:
            yield batch
            batch = []
    if batch:
        yield batch
