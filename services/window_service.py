"""Finestre osservative: «stanotte, quell'oggetto, da quale setup».

Orchestra e basta: prende sito, setup e notte dal database, chiede le posizioni
al positioner, e passa tutto al visibility engine. Nessuna formula.

Per ora si lavora **su un oggetto alla volta**, perché la lista dei candidati
la produrrà lo screening, che non c'è ancora. Il calcolo per (target × setup)
è già quello definitivo: quando arriverà lo screening cambierà chi fornisce la
lista, non questo codice.
"""
from __future__ import annotations

import logging

from core.db import connect
from core.orbits.positioner import Body, positions
from core.timeutil import now_jd_tdb
from core.visibility.instrument import Setup
from core.visibility.night import night_date_for, night_events
from core.visibility.site import Site
from core.visibility.windows import STEP_MINUTES, night_grid, observation_window
from services import ephemeris_service, sites_service

log = logging.getLogger("sky42.windows")


def _night_row(conn, observatory_id: int, night_date: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM night WHERE observatory_id=? AND night_date=?",
        (observatory_id, night_date),
    ).fetchone()
    return dict(row) if row else None


def tonight(desig: str, night_date: str | None = None,
            step_minutes: float = STEP_MINUTES) -> dict | None:
    """Per ogni setup attivo: se e quando si vede, e quanto in profondità.

    Ordinato per margine di profondità decrescente — il primo della lista è la
    risposta a «da dove lo prendo meglio». I setup da cui **non** si vede
    restano nell'elenco con il loro perché: è la differenza fra «non si poteva»
    e «non ci ho provato», e sparire dalla lista non la racconta.
    """
    target = ephemeris_service.target_row(desig)
    if target is None:
        return None

    body = Body.from_row(target)
    siti = sites_service.overview()
    adesso = now_jd_tdb()

    risultati = []
    conn = connect()
    try:
        for sito in siti:
            if not sito["active"] or not sito["setups"]:
                continue
            site = Site.from_row(sito)
            data = night_date or night_date_for(site, adesso)

            # Le notti le calcola il job `night_plan` e le pubblica nel
            # database; se manca (sito nuovo, o data fuori dalla finestra) si
            # calcola al volo invece di rispondere «non lo so»: costa
            # millisecondi e la pagina non deve dipendere da quando è girato
            # un lavoro di fondo.
            notte = _night_row(conn, sito["id"], data) or night_events(site, data)
            jd = night_grid(notte, step_minutes)
            if jd.size == 0:
                continue

            p = positions(body, jd)
            for riga in sito["setups"]:
                if not riga["active"]:
                    continue
                setup = Setup.from_row(riga)
                w = observation_window(
                    site=site, setup=setup, night=notte, jd=jd,
                    ra_deg=p["ra_deg"], dec_deg=p["dec_deg"], v_mag=p["v_mag"],
                    motion_arcsec_min=p["motion_arcsec_min"],
                    step_minutes=step_minutes, ceu_arcsec=target["ceu_arcsec"],
                )
                risultati.append({
                    **w,
                    "site_code": sito["code"], "site_name": sito["name"],
                    "timezone": sito["timezone"], "setup_code": riga["code"],
                    "setup_name": riga["name"], "night_date": data,
                    "motivo": _motivo(w),
                })
    finally:
        conn.close()

    risultati.sort(key=lambda r: (-(r["useful"]), -(r.get("depth_margin") or -99)))
    return {
        "target": {k: target[k] for k in
                   ("primary_desig", "display_name", "kind", "orbit_class",
                    "h_mag", "ceu_arcsec")},
        "windows": risultati,
    }


def _motivo(w: dict) -> str:
    """Perché non si vede, in una riga. Serve più della finestra quando è vuota."""
    if not w["observable"]:
        return "mai abbastanza alto sopra l'orizzonte del setup"
    if w["useful"]:
        return ""
    pen = max(("Luna", w.get("pen_moon") or 0.0),
              ("crepuscolo", w.get("pen_twilight") or 0.0),
              ("airmass", w.get("pen_airmass") or 0.0),
              ("moto", w.get("pen_trailing") or 0.0),
              key=lambda x: x[1])
    manca = -(w.get("depth_margin") or 0.0)
    if pen[1] < 0.2:
        return f"troppo debole: mancano {manca:.1f} mag, cielo pulito"
    return (f"troppo debole: mancano {manca:.1f} mag, e la penalità maggiore "
            f"è {pen[0]} ({pen[1]:.1f} mag)")
