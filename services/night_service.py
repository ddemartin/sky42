"""Il piano delle notti: calcola per ogni sito attivo e scrive in `night`.

Un job non ne chiama un altro: questo pubblica le notti nel database, e il
lavoro sulle finestre le troverà lì (MEMORANDUM 2026-08-15). Per lo stesso
motivo `night` è rigenerabile e non entra nel backup: si ricalcola in
millisecondi da DE440s.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta

from core.db import connect, transaction
from core.timeutil import now_iso, now_jd_tdb
from core.visibility.night import night_date_for, night_events
from core.visibility.site import Site
from services.jobs import run_job

log = logging.getLogger("sky42.night")

JOB_NAME = "night_plan"

# Quante notti avanti tenere pronte. Due settimane: abbastanza per pianificare
# una trasferta o aspettare che la Luna se ne vada, poco abbastanza da restare
# qualche decina di righe per sito.
DEFAULT_NIGHTS = 14


def _sites() -> list[tuple[int, Site]]:
    conn = connect()
    try:
        righe = conn.execute(
            "SELECT * FROM observatory WHERE active = 1 ORDER BY code").fetchall()
    finally:
        conn.close()
    return [(r["id"], Site.from_row(dict(r))) for r in righe]


def plan_nights(n_nights: int = DEFAULT_NIGHTS) -> dict:
    """Calcola e riscrive le prossime `n_nights` notti per ogni sito attivo.

    Idempotente: `INSERT ... ON CONFLICT` sulla coppia (sito, data). Ricalcolare
    è più semplice — e più onesto — che decidere se qualcosa è cambiato: le
    effemeridi non cambiano, ma le coordinate del sito sì, e una notte vecchia
    calcolata per il posto sbagliato non si distinguerebbe da una giusta.
    """
    siti = _sites()
    if not siti:
        log.info("nessun sito attivo: niente notti da calcolare")
        return {"siti": 0, "notti": 0}

    adesso = now_jd_tdb()
    scritte = 0
    conn = connect()
    try:
        with transaction(conn):
            for obs_id, site in siti:
                # La prima notte è quella in corso, non quella di domani: se si
                # guarda la dashboard alle due di notte, la notte che interessa
                # è cominciata ieri sera.
                prima = datetime.strptime(night_date_for(site, adesso), "%Y-%m-%d")
                for i in range(n_nights):
                    data = (prima + timedelta(days=i)).strftime("%Y-%m-%d")
                    _salva(conn, obs_id, night_events(site, data))
                    scritte += 1
    finally:
        conn.close()

    log.info("piano notti: %d siti, %d notti", len(siti), scritte)
    return {"siti": len(siti), "notti": scritte}


def _salva(conn, observatory_id: int, n: dict) -> None:
    conn.execute(
        """INSERT INTO night (observatory_id, night_date, sunset_jd, sunrise_jd,
                              twilight_end_jd, twilight_start_jd, dark_hours,
                              moon_illum, moon_rise_jd, moon_set_jd,
                              moon_max_alt_deg, computed_at)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT (observatory_id, night_date) DO UPDATE SET
               sunset_jd=excluded.sunset_jd, sunrise_jd=excluded.sunrise_jd,
               twilight_end_jd=excluded.twilight_end_jd,
               twilight_start_jd=excluded.twilight_start_jd,
               dark_hours=excluded.dark_hours, moon_illum=excluded.moon_illum,
               moon_rise_jd=excluded.moon_rise_jd, moon_set_jd=excluded.moon_set_jd,
               moon_max_alt_deg=excluded.moon_max_alt_deg,
               computed_at=excluded.computed_at""",
        (observatory_id, n["night_date"], n["sunset_jd"], n["sunrise_jd"],
         n["twilight_end_jd"], n["twilight_start_jd"], n["dark_hours"],
         n["moon_illum"], n["moon_rise_jd"], n["moon_set_jd"],
         n["moon_max_alt_deg"], now_iso()),
    )


def run_night_plan(n_nights: int = DEFAULT_NIGHTS) -> dict:
    """Il job: come `plan_nights`, ma con la sua riga in `job_run`."""
    with run_job(JOB_NAME) as ctx:
        out = plan_nights(n_nights)
        ctx.n_processed = out["notti"]
        ctx.detail = out
        return out


def upcoming(observatory_id: int | None = None, limit: int = 14) -> list[dict]:
    """Le notti già calcolate, dalla corrente in avanti, per l'interfaccia."""
    sql = """SELECT n.*, o.code AS site_code, o.name AS site_name, o.timezone
             FROM night n JOIN observatory o ON o.id = n.observatory_id
             WHERE n.night_date >= date('now', '-1 day')"""
    params: list = []
    if observatory_id is not None:
        sql += " AND n.observatory_id = ?"
        params.append(observatory_id)
    sql += " ORDER BY o.code, n.night_date LIMIT ?"
    params.append(limit)

    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def plan_age_hours() -> float | None:
    """Da quanto è stato calcolato il piano. `None` se non c'è.

    Serve al recupero all'avvio: dopo uno spegnimento lungo la finestra di due
    settimane si accorcia da sola, e il modo per accorgersene è l'età del
    calcolo, non l'orario mancato.
    """
    from core.timeutil import days_since

    conn = connect()
    try:
        ts = conn.execute("SELECT max(computed_at) FROM night").fetchone()[0]
    finally:
        conn.close()
    giorni = days_since(ts)
    return giorni * 24 if giorni is not None else None
