"""Letture sull'hardware osservativo, e l'esecuzione del reconcile.

Come `catalog_service`: solo dict e liste di dict, mai righe di sqlite3 e mai
HTML — la pagina e il futuro endpoint JSON leggono la stessa cosa.
"""
from __future__ import annotations

import logging
from pathlib import Path

from core.db import connect
from core.sites.reconcile import SiteConfigError, reconcile
from services.jobs import run_job

log = logging.getLogger("sky42.sites")

JOB_NAME = "sites_reconcile"


def _rows(sql: str, params=()) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def run_reconcile(sites_dir: Path | None = None) -> dict:
    """Riallinea il database agli YAML, lasciando una riga in `job_run`.

    È un job come gli altri anche se lo lancia una persona: quando fra un mese
    la pagina Osservatori mostrerà un setup che non ci si aspetta, la prima
    domanda sarà «quando è girato il reconcile e cosa ha scritto».
    """
    with run_job(JOB_NAME) as ctx:
        report = reconcile(sites_dir)
        ctx.n_processed = len(report["creati"]) + len(report["aggiornati"])
        ctx.detail = report
        return report


def startup_reconcile() -> dict | None:
    """Chiamato all'avvio: il database deve riflettere i file, sempre.

    Un errore di configurazione **non** impedisce l'avvio: viene registrato nel
    log e nel job, e la pagina Osservatori lo mostra. Un servizio che si
    rifiuta di partire per un campo storto in uno YAML è un servizio che, alle
    tre di notte, non risponde nemmeno per dirti cos'ha.
    """
    try:
        return run_reconcile()
    except SiteConfigError as exc:
        log.error("reconcile dei siti saltato: %s", exc)
        return None
    except Exception:
        log.exception("reconcile dei siti fallito")
        return None


def last_reconcile() -> dict | None:
    """L'ultima esecuzione, per dire in pagina quando e com'è andata."""
    rows = _rows(
        """SELECT started_at, finished_at, status, error, detail_json
           FROM job_run WHERE job_name=? ORDER BY started_at DESC LIMIT 1""",
        (JOB_NAME,),
    )
    return rows[0] if rows else None


def overview() -> list[dict]:
    """Tutto l'hardware, annidato come lo si legge: sito → setup.

    I setup dismessi restano nell'elenco con `active = 0`. È una scelta, non una
    dimenticanza: l'hardware non si cancella, e una pagina che mostra solo
    l'attivo racconta che la storia non è mai esistita.
    """
    siti = _rows(
        """SELECT id, code, name, mpc_code, latitude, longitude, altitude_m, timezone,
                  sky_zenith_mag, extinction_k, horizon_json, specs_checked_at,
                  valid_from, valid_to, active, notes
           FROM observatory ORDER BY active DESC, name"""
    )
    setups = _rows(
        """SELECT s.*, t.code AS telescope_code, t.name AS telescope_name,
                  t.aperture_mm, t.focal_length_mm, t.design,
                  t.min_altitude_deg AS telescope_min_altitude_deg,
                  t.max_track_rate_arcsec_min, t.meridian_flip,
                  c.code AS camera_code, c.name AS camera_name, c.sensor,
                  c.pixel_um, c.pixels_x, c.pixels_y, c.read_noise_e,
                  (SELECT count(*) FROM setup_calibration k WHERE k.setup_id = s.id)
                      AS n_calibrazioni
           FROM setup s
           JOIN telescope t ON t.id = s.telescope_id
           JOIN camera c    ON c.id = s.camera_id
           ORDER BY s.active DESC, s.code"""
    )
    per_sito: dict[int, list[dict]] = {}
    for s in setups:
        # L'altezza minima efficace: quella del setup se c'è, altrimenti quella
        # della montatura. La regola sta qui e non in pagina, perché il
        # visibility engine dovrà applicare esattamente la stessa.
        s["min_altitude_eff_deg"] = (
            s["min_altitude_deg"] if s["min_altitude_deg"] is not None
            else s["telescope_min_altitude_deg"]
        )
        s["focal_eff_mm"] = s["focal_length_mm"] * s["focal_reducer"]
        s["f_ratio"] = s["focal_eff_mm"] / s["aperture_mm"] if s["aperture_mm"] else None
        per_sito.setdefault(s["observatory_id"], []).append(s)

    telescopi = _rows("SELECT * FROM telescope ORDER BY active DESC, code")
    camere = _rows("SELECT * FROM camera ORDER BY active DESC, code")
    per_sito_tel: dict[int, list[dict]] = {}
    for t in telescopi:
        per_sito_tel.setdefault(t["observatory_id"], []).append(t)

    for sito in siti:
        sito["telescopes"] = per_sito_tel.get(sito["id"], [])
        sito["setups"] = per_sito.get(sito["id"], [])
        # Le camere non appartengono a un sito (possono spostarsi): si mostrano
        # quelle effettivamente usate dai setup del sito.
        usate = {s["camera_code"] for s in sito["setups"]}
        sito["cameras"] = [c for c in camere if c["code"] in usate]
    return siti


def counts() -> dict:
    """I numeri dell'intestazione: attivi e totali, che non sono la stessa cosa."""
    conn = connect()
    try:
        out = {}
        for table in ("observatory", "telescope", "camera", "setup"):
            row = conn.execute(
                f"SELECT count(*) AS n, sum(active) AS attivi FROM {table}"
            ).fetchone()
            out[table] = {"totali": row["n"], "attivi": row["attivi"] or 0}
        return out
    finally:
        conn.close()
