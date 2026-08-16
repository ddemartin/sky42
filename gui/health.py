"""`GET /health`: il servizio è vivo e i dati sono freschi?

Non è una pagina ma un endpoint JSON sul FastAPI che NiceGUI si porta dietro.
Serve a tre cose: al `HEALTHCHECK` del container, a un `curl` dopo un
`docker compose up --build` per verificare che sia cambiato davvero, e a un
controllo esterno.

Deve restare **economico**: gira ogni 30 secondi. Niente conteggi su un milione
e mezzo di righe — solo lo stato dei job, che è indicizzato, e l'età del dato
più recente.
"""
from __future__ import annotations

import logging

from nicegui import app

from core.db import connect
from core.timeutil import days_since

log = logging.getLogger("sky42.health")

# Oltre questa età il catalogo è vecchio: i sync girano ogni 6 ore, quindi 36 h
# significa che qualcosa non gira da almeno cinque tentativi.
STALE_HOURS = 36


@app.get("/health")
def health() -> dict:
    try:
        conn = connect()
        try:
            row = conn.execute(
                """SELECT job_name, started_at, status FROM job_run r
                   WHERE started_at = (SELECT max(started_at) FROM job_run
                                       WHERE job_name = r.job_name)
                     AND job_name LIKE '%_sync'"""
            ).fetchall()
            ultimo = conn.execute(
                "SELECT max(updated_at) FROM orbit WHERE source='mpcorb'"
            ).fetchone()[0]
        finally:
            conn.close()
    except Exception as exc:               # database irraggiungibile o corrotto
        log.exception("health: database non leggibile")
        return {"status": "error", "errore": str(exc)}

    eta_h = (days_since(ultimo) or 0) * 24 if ultimo else None
    stantio = eta_h is None or eta_h > STALE_HOURS

    return {
        # 'degraded' e non 'error': il servizio risponde, sono i dati a essere
        # vecchi. Il container non va riavviato per questo — riavviarlo non
        # farebbe apparire i dati.
        "status": "degraded" if stantio else "ok",
        "catalogo_ore": round(eta_h, 1) if eta_h is not None else None,
        "sync": {r["job_name"]: r["status"] for r in row},
    }
