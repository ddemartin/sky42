"""Il job che produce la lista: propaga la popolazione monitorata e la distilla.

Orchestra e basta — chi legge il catalogo, chi chiama il calcolo, chi scrive
`screening_track` e `target_stats`. Le formule stanno in `core/radar/screening.py`
e la propagazione in `core/orbits/`.

**La popolazione monitorata** è tre cose messe insieme, e ognuna ha una ragione:

* gli asteroidi con **Tj < 3** tolte le classi risonanti stabili (Troiani,
  Hilda, oggetti distanti): sono ~14.000 su 1,5 milioni, ed è la popolazione
  del progetto — asteroidi su orbita cometaria;
* **tutte le comete**, che sono poche migliaia e sono il caso in cui «torna a
  portata» ha il significato più forte;
* tutto ciò che sta in **watchlist**, perché un oggetto messo lì a mano deve
  comparire nelle liste anche se non passa nessun filtro automatico.

**Un job non ne chiama un altro.** Questo pubblica le tracce e le statistiche;
`radar_states` le troverà lì al giro successivo.
"""
from __future__ import annotations

import logging

import numpy as np

from core import config
from core.db import connect, get_setting, transaction
from core.orbits.positioner import Body
from core.radar import screening
from core.timeutil import jd_from_iso_date, now_iso, now_jd_tdb, years_between
from core.visibility.instrument import Setup
from core.visibility.limits import reference_limit
from core.visibility.site import Site
from services.jobs import chunked, run_job, wait_if_busy

log = logging.getLogger("sky42.screening")

JOB_NAME = "screening"

# Il metro quando non c'è nemmeno un setup attivo: un telescopio amatoriale
# serio in una notte buona. Serve solo a far girare lo screening su una
# macchina appena installata — appena c'è un setup vero, vince quello.
FALLBACK_V_REF = 21.0

_POPULATION_SQL = """
    SELECT t.id, t.kind, t.primary_desig, t.display_name, t.orbit_class,
           o.epoch_jd, o.a_au, o.q_au, o.e, o.i_deg, o.node_deg, o.argp_deg,
           o.m_deg, o.tp_jd, o.h_mag, o.g_slope, o.m1, o.k1,
           o.tisserand_j, o.last_obs_date,
           x.ceu_arcsec, x.ceu_rate, x.ceu_date
    FROM target t
    JOIN orbit o ON o.target_id = t.id
    LEFT JOIN astorb_extra x ON x.target_id = t.id
    WHERE (
        (t.kind = 'asteroid' AND o.tisserand_j IS NOT NULL AND o.tisserand_j < ?
         AND (t.orbit_class IS NULL OR t.orbit_class NOT IN ({escluse})))
        OR t.kind = 'comet'
        OR t.id IN (SELECT target_id FROM watchlist)
    )
    ORDER BY t.id
"""


def population(limit: int | None = None) -> list[dict]:
    """Le righe target ⋈ orbit ⋈ astorb della popolazione monitorata."""
    tj_max = get_setting("tisserand_max", config.TISSERAND_MAX)
    escluse = get_setting("aco_excluded_classes", list(config.ACO_EXCLUDED_CLASSES))
    sql = _POPULATION_SQL.format(escluse=",".join("?" * len(escluse)) or "''")
    if limit:
        sql += " LIMIT ?"

    conn = connect()
    try:
        params = (tj_max, *escluse) + ((limit,) if limit else ())
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def radar_reference_v() -> tuple[float, str | None]:
    """`V_ref` del radar: il setup attivo che arriva **più in profondità**.

    Uno solo e non uno per setup, perché `target_stats` è per oggetto: la
    domanda a cui risponde è «questo oggetto è alla portata di qualcosa che ho»
    e la risposta la dà lo strumento migliore. Gli stati per singolo setup —
    quelli sì uno per setup — li calcola `radar_states` con lo stesso metro.
    """
    from services import sites_service

    migliore, quale = None, None
    for sito in sites_service.overview():
        if not sito["active"]:
            continue
        site = Site.from_row(sito)
        for riga in sito["setups"]:
            if not riga["active"]:
                continue
            v = reference_limit(site=site, setup=Setup.from_row(riga))["eff_vlim"]
            if migliore is None or v > migliore:
                migliore, quale = v, f"{sito['code']}/{riga['code']}"
    if migliore is None:
        log.warning("nessun setup attivo: V_ref di ripiego %.1f", FALLBACK_V_REF)
        return FALLBACK_V_REF, None
    return float(migliore), quale


def run_screening(limit: int | None = None, block: int | None = None) -> dict:
    """Propaga la popolazione, scrive le tracce e le statistiche. Idempotente.

    Idempotente nel senso che conta: rilanciarlo riscrive tutto da capo con la
    data di adesso. Non si tenta di capire «cos'è cambiato» — gli elementi
    orbitali cambiano a ogni sync e una traccia vecchia di ieri non si
    distingue da una giusta guardandola.
    """
    with run_job(JOB_NAME) as ctx:
        v_ref, quale = radar_reference_v()
        righe = population(limit)
        jd0 = now_jd_tdb()
        jd_avanti = screening.forward_grid(jd0)
        jd_indietro = screening.back_grid(jd0)

        ctx.detail = {
            "v_ref": round(v_ref, 2), "setup_ref": quale,
            "n_popolazione": len(righe),
            "epoche_avanti": int(jd_avanti.size), "epoche_indietro": int(jd_indietro.size),
        }
        log.info("screening: %d oggetti, V_ref %.2f da %s", len(righe), v_ref,
                 quale or "(ripiego)")

        n_blocchi = 0
        for blocco in chunked(righe, block or config.SCREENING_BLOCK):
            # Fra un blocco e l'altro, non dentro: il Mac mini fa girare altro
            # e un job pesante deve poter aspettare senza lasciare il database
            # a metà.
            wait_if_busy()
            _screen_block(blocco, jd_avanti, jd_indietro, v_ref, jd0)
            ctx.n_processed += len(blocco)
            n_blocchi += 1
            log.debug("screening: %d/%d", ctx.n_processed, len(righe))

        ctx.detail["blocchi"] = n_blocchi
        return {**ctx.detail, "n_oggetti": ctx.n_processed}


def _screen_block(righe: list[dict], jd_avanti, jd_indietro, v_ref: float,
                  jd0: float) -> None:
    """Propaga un blocco, ne distilla le statistiche e le scrive in transazione."""
    body = Body.from_rows(righe)
    avanti = screening.track(body, jd_avanti)
    # All'indietro serve **solo la magnitudine**: la domanda è «quand'è stata
    # l'ultima volta buona», e RA/Dec di sette anni fa non li guarderà nessuno.
    # Sono cinque array in meno da tenere in memoria e zero byte su disco.
    indietro = screening.track(body, jd_indietro, fields=("v_mag",))

    stats = screening.distill(
        jd_fwd=jd_avanti, v_fwd=avanti["v_mag"],
        jd_back=jd_indietro, v_back=indietro["v_mag"],
        v_ref=v_ref, jd_now=jd0,
    )

    ora = now_iso()
    tracce, statistiche = [], []
    for i, riga in enumerate(righe):
        tracce.append((
            riga["id"], float(jd_avanti[0]),
            float(jd_avanti[1] - jd_avanti[0]), int(jd_avanti.size),
            *[screening.pack(avanti[campo][i]) for campo in screening.TRACK_FIELDS],
            ora,
        ))
        s = stats[i]
        s["years_since_last_obs"] = years_between(riga.get("last_obs_date"))
        s["ceu_now_arcsec"] = screening.propagated_uncertainty(
            riga.get("ceu_arcsec"), riga.get("ceu_rate"),
            jd_from_iso_date(riga.get("ceu_date")), jd0,
        )
        statistiche.append((riga["id"], *[s[c] for c in _STATS_COLS], ora))

    conn = connect()
    try:
        with transaction(conn):
            conn.executemany(
                """INSERT OR REPLACE INTO screening_track
                       (target_id, jd_start, step_days, n_samples,
                        v_mag, r_au, delta_au, elong_deg, ra_deg, dec_deg, computed_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?)""", tracce)
            conn.executemany(
                f"""INSERT OR REPLACE INTO target_stats
                        (target_id, {', '.join(_STATS_COLS)}, computed_at)
                    VALUES (?{',?' * (len(_STATS_COLS) + 1)})""", statistiche)
    finally:
        conn.close()


# L'ordine delle colonne di `target_stats` che il job scrive. In una costante
# perché compare due volte — nella tupla e nell'INSERT — e due elenchi che
# devono restare allineati sono un elenco solo.
_STATS_COLS = (
    "v_now", "v_trend_mag_month", "peak_v", "peak_jd",
    "next_v21_jd", "next_v205_jd", "visibility_start_jd", "visibility_end_jd",
    "last_good_apparition_jd", "years_since_good_apparition",
    "years_since_last_obs", "ceu_now_arcsec",
)


def screening_age_hours() -> float | None:
    """Da quante ore esiste l'ultima traccia. Serve al recupero all'avvio."""
    from core.timeutil import days_since

    conn = connect()
    try:
        row = conn.execute("SELECT max(computed_at) AS t FROM screening_track").fetchone()
    finally:
        conn.close()
    giorni = days_since(row["t"] if row else None)
    return giorni * 24.0 if giorni is not None else None


def track_of(target_id: int) -> dict | None:
    """La traccia di un oggetto, riletta in array. Per la pagina e per il grafico."""
    conn = connect()
    try:
        row = conn.execute("SELECT * FROM screening_track WHERE target_id=?",
                           (target_id,)).fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    jd = row["jd_start"] + np.arange(row["n_samples"]) * row["step_days"]
    return {"jd": jd, "computed_at": row["computed_at"],
            **{campo: screening.unpack(row[campo]) for campo in screening.TRACK_FIELDS}}
