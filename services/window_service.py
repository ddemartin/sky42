"""Finestre osservative: «stanotte, quell'oggetto, da quale setup».

Orchestra e basta: prende sito, setup e notte dal database, chiede le posizioni
al positioner, e passa tutto al visibility engine. Nessuna formula.

Due strade sullo **stesso** calcolo, e la differenza è solo chi fornisce la
lista:

* `tonight(desig)` — un oggetto, tutti i setup, per la pagina Oggetto. Non
  scrive niente: è una domanda, non un risultato da conservare.
* `run_windows()` — il job notturno: la popolazione monitorata × i setup attivi
  × le prossime notti, scritta in `observation_window`. È quello che accende il
  criterio sulla durata nel radar e che rende la dashboard una query.

`observation_window` è **rigenerabile** (regola 1): si ricalcola in un minuto
dalle tracce e dalle notti, quindi non entra nel backup e le notti passate si
potano senza rimpianti — quel che è stato osservato davvero sta in
`observation_log`, che è un'altra tabella e un'altra storia.
"""
from __future__ import annotations

import json
import logging

import numpy as np

from core import config
from core.db import connect, get_setting, transaction
from core.orbits.positioner import Body, positions
from core.ranking.score import score_window
from core.timeutil import now_iso, now_jd_tdb
from core.visibility.instrument import Setup
from core.visibility.night import night_date_for, night_events
from core.visibility.site import Site
from core.visibility.windows import (STEP_MINUTES, night_grid, observation_window,
                                     observation_windows, sky_geometry)
from services import ephemeris_service, ranking_service, sites_service
from services.jobs import chunked, run_job, wait_if_busy

log = logging.getLogger("sky42.windows")

JOB_NAME = "windows"

# Quante notti avanti calcolare. Tre e non quattordici come il piano delle
# notti: le finestre invecchiano con gli elementi orbitali e con `target_stats`,
# che si riscrivono ogni giorno, mentre crepuscoli e Luna no. Calcolarne due
# settimane vorrebbe dire riscrivere ogni notte tredici notti che nessuno ha
# ancora guardato — e la terza serve per «domani sera conviene di più».
DEFAULT_NIGHTS = 3

# Chi entra nel calcolo: tutto ciò che sta entro questa fascia sopra il V_ref
# più profondo. È la stessa banda di guardia del radar (`states.APPROACH_BAND`),
# e non è un'ottimizzazione: un oggetto a V 26 avrebbe una riga per notte e per
# setup che dice sempre la stessa cosa — «invisibile» — al prezzo di ~1 kB di
# scomposizione ciascuna. Il radar legge l'assenza di riga come `useful_hours
# = None`, cioè «non lo so», e lo giudica sulla magnitudine: che per un oggetto
# fuori banda è esattamente la risposta giusta.
V_MARGIN = 1.5

# Le notti passate si potano: sono rigenerabili e non le guarda nessuno. Una
# settimana serve solo a poter dire «e ieri?» il lunedì mattina.
KEEP_NIGHTS_DAYS = 7


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

    # Il punteggio arriva **dopo** le finestre e non dentro: la finestra dice
    # se e quanto si vede, il punteggio dice se vale la pena, e sono due
    # domande con due tarature diverse. L'ordine resta quello del margine —
    # «da dove lo prendo meglio» — perché su un oggetto solo il ranking serve a
    # spiegare, non a scegliere.
    ranking_service.score_windows(risultati, target)

    risultati.sort(key=lambda r: (-(r["useful"]), -(r.get("depth_margin") or -99)))
    return {
        "target": {k: target[k] for k in
                   ("primary_desig", "display_name", "kind", "orbit_class",
                    "h_mag", "ceu_arcsec")},
        "windows": risultati,
    }


# --- il job: la popolazione monitorata × i setup attivi × le prossime notti --


def v_limit() -> tuple[float, str | None]:
    """Fin dove si guarda: il `V_ref` più profondo, più la fascia di guardia.

    Lo stesso metro dello screening e del radar. Se cambiasse solo qui, la
    dashboard direbbe «osservabile» per oggetti che non hanno una finestra e
    nessuno saprebbe perché.
    """
    from services import screening_service

    v_ref, quale = screening_service.radar_reference_v()
    return v_ref + float(get_setting("windows_v_margin", V_MARGIN)), quale


def population_rows(v_max: float, limit: int | None = None) -> list[dict]:
    """Gli oggetti da calcolare, con orbita, incertezza, statistiche e watchlist.

    Una query sola: elementi per il positioner, `ceu` per il campo, e il
    contesto che serve al ranking. Chiederli a pezzi vorrebbe dire tre query per
    oggetto dentro il ciclo del job.

    La CEU è quella **propagata a oggi** dallo screening, non quella di ASTORB:
    l'incertezza cresce fra un'osservazione e l'altra, e «ci sta nel campo» è
    una domanda su stanotte.
    """
    sql = """
        SELECT t.id, t.kind, t.primary_desig, t.display_name,
               o.epoch_jd, o.a_au, o.q_au, o.e, o.i_deg, o.node_deg, o.argp_deg,
               o.m_deg, o.tp_jd, o.h_mag, o.g_slope, o.m1, o.k1,
               o.tisserand_j, o.arc_days, o.n_oppositions, o.last_obs_date,
               COALESCE(s.ceu_now_arcsec, x.ceu_arcsec) AS ceu_arcsec,
               s.v_now, s.years_since_good_apparition, s.years_since_last_obs,
               CASE WHEN w.target_id IS NULL THEN 0 ELSE 1 END AS watchlist
        FROM target_stats s
        JOIN target t     ON t.id = s.target_id
        JOIN orbit o      ON o.target_id = s.target_id
        LEFT JOIN astorb_extra x ON x.target_id = s.target_id
        LEFT JOIN watchlist w    ON w.target_id = s.target_id
        WHERE s.v_now IS NOT NULL AND s.v_now <= ?
        ORDER BY t.id
    """
    params: list = [v_max]
    if limit:
        sql += " LIMIT ?"
        params.append(limit)

    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _nights_of(conn, observatory_id: int, first_date: str, n: int) -> list[dict]:
    """Le notti già in tabella, dalla corrente in avanti.

    Le calcola `night_plan` e questo job le trova qui: un job non ne chiama un
    altro. Se non ce ne sono — sito appena aggiunto, piano mai girato — non si
    inventa niente: senza una riga in `night` non ci sarebbe nemmeno il
    `night_id` a cui agganciare la finestra.
    """
    rows = conn.execute(
        """SELECT * FROM night
           WHERE observatory_id = ? AND julianday(night_date) >= julianday(?)
           ORDER BY night_date LIMIT ?""",
        (observatory_id, first_date, n)).fetchall()
    return [dict(r) for r in rows]


def run_windows(n_nights: int | None = None, block: int | None = None,
                limit: int | None = None) -> dict:
    """Scrive `observation_window` per (target × setup × notte). Idempotente.

    Rilanciarlo riscrive le stesse righe con la data di adesso
    (`INSERT OR REPLACE` sulla terna): non si tenta di capire cos'è cambiato,
    perché gli elementi e le statistiche cambiano ogni giorno e una finestra
    vecchia non si distingue da una giusta guardandola.
    """
    with run_job(JOB_NAME) as ctx:
        n_nights = n_nights or DEFAULT_NIGHTS
        v_max, quale = v_limit()
        righe = population_rows(v_max, limit)
        ora_jd = now_jd_tdb()

        ctx.detail = {"v_max": round(v_max, 2), "setup_ref": quale,
                      "n_popolazione": len(righe), "notti": n_nights,
                      "siti": 0, "finestre": 0, "utili": 0}
        if not righe:
            log.info("finestre: nessun oggetto entro V %.1f", v_max)
            return dict(ctx.detail)

        profili = {}        # per `kind`: il profilo di punteggio si legge una volta
        conn = connect()
        try:
            potate = _prune(conn)
            for sito in sites_service.overview():
                setups = [r for r in sito["setups"] if r["active"]]
                if not sito["active"] or not setups:
                    continue
                site = Site.from_row(sito)
                notti = _nights_of(conn, sito["id"], night_date_for(site, ora_jd),
                                   n_nights)
                if not notti:
                    log.warning("finestre: %s non ha notti calcolate, saltato",
                                sito["code"])
                    continue
                ctx.detail["siti"] += 1

                for notte in notti:
                    for blocco in chunked(righe, block or config.SCREENING_BLOCK):
                        # Fra un blocco e l'altro, come per lo screening: il Mac
                        # mini fa girare altro.
                        wait_if_busy()
                        scritte, utili = _window_block(
                            conn, site=site, sito=sito, setups=setups,
                            night=notte, rows=blocco, profili=profili)
                        ctx.detail["finestre"] += scritte
                        ctx.detail["utili"] += utili
                        ctx.n_processed += scritte
        finally:
            conn.close()

        ctx.detail["potate"] = potate
        log.info("finestre: %d righe (%d utili) per %d oggetti × %d siti × %d notti",
                 ctx.detail["finestre"], ctx.detail["utili"], len(righe),
                 ctx.detail["siti"], n_nights)
        return dict(ctx.detail)


def _prune(conn) -> int:
    """Toglie le finestre che non descrivono più niente: notti passate e setup
    usciti di servizio.

    Le due potature sembrano indipendenti e non lo sono: il job **salta** i
    setup inattivi invece di ricalcolarli, quindi senza la seconda le righe
    scritte ieri — quando quel setup era ancora attivo — restano per le notti di
    oggi e di domani, e ci restano **per sempre**, perché nessuno le riscriverà
    mai. Un telescopio andato offline continuava a comparire in `/stanotte` con
    le sue finestre di ieri (T17 a Siding Spring, 14.724 righe): non è una
    stima vecchia, è un invito a puntare uno strumento che non c'è.

    `julianday` da entrambe le parti sulle date, che è la regola di casa.
    """
    with transaction(conn):
        cur = conn.execute(
            """DELETE FROM observation_window WHERE night_id IN (
                   SELECT id FROM night
                   WHERE julianday(night_date) < julianday('now') - ?)""",
            (KEEP_NIGHTS_DAYS,))
        n_notti = cur.rowcount
        cur = conn.execute(
            """DELETE FROM observation_window WHERE setup_id IN (
                   SELECT id FROM setup WHERE active = 0)""")
    return n_notti + cur.rowcount


def _window_block(conn, *, site: Site, sito: dict, setups: list[dict],
                  night: dict, rows: list[dict], profili: dict) -> tuple[int, int]:
    """Un blocco di oggetti, una notte, tutti i setup del sito.

    **La geometria si calcola una volta**: le posizioni degli oggetti, il Sole e
    la Luna non sanno che telescopio c'è sotto. Ogni setup ci applica sopra i
    propri limiti, che è aritmetica su array già pronti.
    """
    jd = night_grid(night)
    if jd.size == 0:
        return 0, 0

    p = positions(Body.from_rows(rows), jd)
    geom = sky_geometry(site, jd, p["ra_deg"], p["dec_deg"])
    ceu = np.array([np.nan if r["ceu_arcsec"] is None else float(r["ceu_arcsec"])
                    for r in rows])
    contesti = [ranking_service.context_from_row(r) for r in rows]
    ora = now_iso()

    valori, utili = [], 0
    for riga_setup in setups:
        finestre = observation_windows(
            site=site, setup=Setup.from_row(riga_setup), night=night, jd=jd,
            geometry=geom, v_mag=p["v_mag"],
            motion_arcsec_min=p["motion_arcsec_min"], ceu_arcsec=ceu,
        )
        for i, (riga, w) in enumerate(zip(rows, finestre)):
            profilo = profili.get(riga["kind"])
            if profilo is None:
                profilo = profili[riga["kind"]] = ranking_service.active_profile(
                    riga["kind"])
            w.update(score_window(w, contesti[i], profilo))
            utili += bool(w["useful"])
            valori.append(_valori(night["id"], riga["id"], riga_setup["id"], w, p,
                                  i, ora))

    with transaction(conn):
        conn.executemany(
            f"""INSERT OR REPLACE INTO observation_window
                    ({', '.join(_WINDOW_COLS)}) VALUES ({','.join('?' * len(_WINDOW_COLS))})""",
            valori)
    return len(valori), utili


# L'ordine delle colonne che il job scrive, in una costante sola: la tupla e
# l'INSERT devono restare allineati, e due elenchi che devono restare allineati
# sono un elenco solo (come in `screening_service`).
_WINDOW_COLS = (
    "night_id", "target_id", "setup_id",
    "geo_start_jd", "geo_end_jd", "useful_start_jd", "useful_end_jd", "useful_hours",
    "best_jd", "best_alt_deg", "best_az_deg", "best_airmass", "transit_jd",
    "max_alt_deg", "v_pred", "elong_deg", "moon_sep_deg", "moon_alt_deg",
    "moon_illum", "sky_brightness_mag", "eff_vlim", "pen_airmass", "pen_moon",
    "pen_twilight", "pen_trailing", "depth_margin", "motion_arcsec_min",
    "motion_pa_deg", "trail_arcsec", "rec_exposure_s", "rec_n_subs",
    "fov_fit_arcsec", "fov_fit_ratio", "needs_mosaic",
    "score", "score_json", "grade", "computed_at",
)


def _valori(night_id: int, target_id: int, setup_id: int, w: dict, p: dict,
            i: int, ora: str) -> tuple:
    """La riga da scrivere, nell'ordine di `_WINDOW_COLS`.

    Elongazione e angolo di posizione si leggono dal positioner **nello stesso
    campione** in cui è stata scelta la finestra (`best_index`): presi altrove
    racconterebbero un istante diverso da quello di tutte le altre colonne.
    """
    k = w.get("best_index")
    elong = float(p["elong_deg"][i, k]) if k is not None else None
    pa = float(p["motion_pa_deg"][i, k]) if k is not None else None
    return (
        night_id, target_id, setup_id,
        w["geo_start_jd"], w["geo_end_jd"], w["useful_start_jd"], w["useful_end_jd"],
        w["useful_hours"], w["best_jd"], w.get("best_alt_deg"), w.get("best_az_deg"),
        w.get("best_airmass"), w.get("transit_jd"), w.get("max_alt_deg"),
        w.get("v_pred"), elong, w.get("moon_sep_deg"), w.get("moon_alt_deg"),
        w.get("moon_illum"), w.get("sky_brightness_mag"), w.get("eff_vlim"),
        w.get("pen_airmass"), w.get("pen_moon"), w.get("pen_twilight"),
        w.get("pen_trailing"), w.get("depth_margin"), w.get("motion_arcsec_min"),
        pa, w.get("trail_arcsec"), w.get("rec_exposure_s"), w.get("rec_n_subs"),
        w.get("fov_fit_arcsec"), w.get("fov_fit_ratio"),
        int(bool(w.get("needs_mosaic"))),
        w.get("score"), json.dumps(w.get("score_json"), default=str), w.get("grade"),
        ora,
    )


def windows_age_hours() -> float | None:
    """Da quante ore esiste l'ultima finestra. Serve al recupero all'avvio."""
    from core.timeutil import days_since

    conn = connect()
    try:
        row = conn.execute(
            "SELECT max(computed_at) AS t FROM observation_window").fetchone()
    finally:
        conn.close()
    giorni = days_since(row["t"] if row else None)
    return giorni * 24.0 if giorni is not None else None


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
