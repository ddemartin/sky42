"""Il radar: da `target_stats` agli stati, e alla storia di come ci sono arrivati.

Legge quello che lo screening ha già distillato e **non ricalcola nessuna
posizione**. Se in questo file comparisse una propagazione, vorrebbe dire che
lo screening non ha distillato abbastanza.

Scrive due tabelle che vanno tenute distinte:

* `target_state` — dov'è adesso ogni coppia (target, setup). Si sovrascrive.
* `state_transition` — **come ci è arrivato**. Non si sovrascrive mai, è una
  delle cinque tabelle non rigenerabili (regola 1): l'MPC non conserva niente e
  nemmeno noi conserviamo un secondo posto da cui rifare questa storia.

Le righe con `setup_id NULL` sono il rollup «il migliore fra tutti i setup
attivi», ed è quello che legge la dashboard: la domanda della mattina è «posso
riprenderlo», non «posso riprenderlo con la camera piccola».
"""
from __future__ import annotations

import json
import logging

from core.db import connect, transaction
from core.radar import states
from core.timeutil import now_iso, now_jd_tdb
from core.visibility.instrument import Setup
from core.visibility.limits import reference_limit
from core.visibility.site import Site
from services.jobs import run_job

log = logging.getLogger("sky42.radar")

JOB_NAME = "radar_states"

# I setup, con il loro metro. `None` come chiave è il rollup.
_ROLLUP = None


def setup_references() -> list[tuple[int | None, str, float]]:
    """`(setup_id, etichetta, V_ref)` per ogni setup attivo, più il rollup.

    Il rollup prende il V_ref più profondo: è lo stesso metro con cui lo
    screening ha scritto `target_stats`, e le due cose devono coincidere o la
    dashboard direbbe OBSERVABLE su statistiche calcolate con un'altra soglia.
    """
    from services import sites_service

    out: list[tuple[int | None, str, float]] = []
    for sito in sites_service.overview():
        if not sito["active"]:
            continue
        site = Site.from_row(sito)
        for riga in sito["setups"]:
            if not riga["active"]:
                continue
            v = reference_limit(site=site, setup=Setup.from_row(riga))["eff_vlim"]
            out.append((riga["id"], f"{sito['code']}/{riga['code']}", float(v)))
    if out:
        migliore = max(out, key=lambda r: r[2])
        out.append((_ROLLUP, f"migliore ({migliore[1]})", migliore[2]))
    return out


def _stats_rows() -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT s.*, t.display_name, t.kind
               FROM target_stats s JOIN target t ON t.id = s.target_id
               WHERE s.v_now IS NOT NULL""").fetchall()]
    finally:
        conn.close()


def _previous_states(conn) -> dict[tuple[int, int | None], dict]:
    rows = conn.execute("SELECT * FROM target_state").fetchall()
    return {(r["target_id"], r["setup_id"]): dict(r) for r in rows}


def _useful_hours(conn) -> dict[tuple[int, int | None], float]:
    """Ore utili della **notte in corso**, per coppia (target, setup).

    «La notte in corso» è una domanda per sito, non per il database: alle 02:30
    UTC a Río Hurtado sono le 22:30 di *ieri sera*, e la notte che interessa è
    quella cominciata ieri. Chiedere `max(night_date) <= date('now')` darebbe la
    notte che deve ancora cominciare, e lo farebbe in silenzio — un turno di
    ritardo su ogni stato, senza nessun errore. Si passa quindi da
    `night_date_for`, che è la stessa funzione con cui il job ha scritto le
    finestre.

    Il rollup (`setup_id = None`) prende il **massimo** fra i setup: è lo stesso
    «il migliore fra tutti» con cui si sceglie il suo V_ref, e la domanda della
    mattina è «posso riprenderlo», non «posso riprenderlo con la camera piccola».

    Una coppia che non compare vale `useful_hours = None`, cioè «non lo so»: gli
    oggetti fuori dalla fascia di guardia non hanno una finestra scritta e
    restano giudicati sulla sola magnitudine (vedi `window_service.V_MARGIN`).
    """
    from core.visibility.night import night_date_for
    from services import sites_service

    adesso = now_jd_tdb()
    ore: dict[tuple[int, int | None], float] = {}
    for sito in sites_service.overview():
        setups = [r["id"] for r in sito["setups"] if r["active"]]
        if not sito["active"] or not setups:
            continue
        data = night_date_for(Site.from_row(sito), adesso)
        rows = conn.execute(
            f"""SELECT w.target_id, w.setup_id, w.useful_hours
                FROM observation_window w
                JOIN night n ON n.id = w.night_id
                WHERE n.observatory_id = ? AND n.night_date = ?
                  AND w.setup_id IN ({','.join('?' * len(setups))})
                  AND w.useful_hours IS NOT NULL""",
            (sito["id"], data, *setups)).fetchall()
        for r in rows:
            ore[(r["target_id"], r["setup_id"])] = r["useful_hours"]
            chiave = (r["target_id"], _ROLLUP)
            ore[chiave] = max(ore.get(chiave, 0.0), r["useful_hours"])
    return ore


def run_radar() -> dict:
    """Ricalcola gli stati e registra le transizioni. Idempotente.

    Rilanciarlo due volte di fila non produce transizioni doppie: la seconda
    volta il candidato coincide con lo stato già scritto, e non cambia niente.
    Produce invece la **conferma** di un candidato in attesa, ed è voluto — è
    il meccanismo con cui due calcoli consecutivi diventano una notifica.
    """
    with run_job(JOB_NAME) as ctx:
        riferimenti = setup_references()
        if not riferimenti:
            log.info("nessun setup attivo: niente stati da calcolare")
            ctx.detail = {"setup": 0}
            return {"setup": 0, "transizioni": 0}

        righe = _stats_rows()
        ora = now_iso()
        transizioni: list[dict] = []

        conn = connect()
        try:
            precedenti = _previous_states(conn)
            ore_utili = _useful_hours(conn)
            stati, storia = [], []

            for setup_id, etichetta, v_ref in riferimenti:
                for s in righe:
                    chiave = (s["target_id"], setup_id)
                    prima = precedenti.get(chiave)
                    candidato = states.classify(
                        v_pred=s["v_now"], v_ref=v_ref,
                        trend_mag_month=s["v_trend_mag_month"],
                        useful_hours=ore_utili.get(chiave),
                        current=(prima or {}).get("state"),
                    )
                    passo = states.advance(prima, candidato)

                    since = ora if passo["changed"] else (prima or {}).get("since", ora)
                    stati.append((s["target_id"], setup_id, passo["state"], since,
                                  s["v_now"], v_ref,
                                  passo["pending_state"],
                                  _pending_since(prima, passo, ora),
                                  passo["pending_count"], ora))

                    if passo["changed"] and passo["from_state"] is not None:
                        contesto = _context(s, v_ref, etichetta)
                        storia.append((s["target_id"], setup_id, passo["from_state"],
                                       passo["state"], ora, s["v_now"],
                                       json.dumps(contesto, default=str)))
                        transizioni.append({
                            "target": s["display_name"], "setup": etichetta,
                            "da": passo["from_state"], "a": passo["state"],
                            "v": s["v_now"],
                        })

            with transaction(conn):
                # Si svuota e si riscrive invece di `INSERT OR REPLACE`: la
                # chiave primaria contiene `setup_id`, che per il rollup è
                # NULL, e in SQLite due NULL non sono uguali fra loro — un
                # upsert lascerebbe una riga di rollup in più a ogni giro. Lo
                # stato corrente è rigenerabile per costruzione (la storia sta
                # in `state_transition`, che non si tocca).
                conn.execute("DELETE FROM target_state")
                conn.executemany(
                    """INSERT INTO target_state
                           (target_id, setup_id, state, since, v_pred, eff_vlim_ref,
                            pending_state, pending_since, pending_count, updated_at)
                       VALUES (?,?,?,?,?,?,?,?,?,?)""", stati)
                if storia:
                    conn.executemany(
                        """INSERT INTO state_transition
                               (target_id, setup_id, from_state, to_state, at,
                                v_pred, context_json)
                           VALUES (?,?,?,?,?,?,?)""", storia)
        finally:
            conn.close()

        ctx.n_processed = len(righe)
        ctx.detail = {
            "setup": len(riferimenti), "oggetti": len(righe),
            "transizioni": len(transizioni),
            # Le prime venti in chiaro: la riga di `job_run` deve dire *cos'è
            # successo*, non solo quante volte è successo.
            "esempi": transizioni[:20],
        }
        log.info("radar: %d oggetti × %d riferimenti, %d transizioni",
                 len(righe), len(riferimenti), len(transizioni))
        return dict(ctx.detail)


def _pending_since(prima: dict | None, passo: dict, ora: str) -> str | None:
    """Da quando quel candidato è in attesa — l'istante del **primo** giro.

    Riscriverlo a ogni giro sarebbe corretto per caso finché le conferme sono
    due; alzando `CONFIRMATIONS` racconterebbe che un candidato in attesa da
    tre giorni è arrivato adesso, e «da quanto sta insistendo» è precisamente
    la domanda che ci si fa guardando uno stato che non si decide.
    """
    if not passo["pending_state"]:
        return None
    if prima and prima.get("pending_state") == passo["pending_state"]:
        return prima.get("pending_since") or ora
    return ora


def radar_age_hours() -> float | None:
    """Da quante ore gli stati sono stati ricalcolati. Per il recupero all'avvio."""
    from core.timeutil import days_since

    conn = connect()
    try:
        row = conn.execute("SELECT max(updated_at) AS t FROM target_state").fetchone()
    finally:
        conn.close()
    giorni = days_since(row["t"] if row else None)
    return giorni * 24.0 if giorni is not None else None


def _context(stats: dict, v_ref: float, etichetta: str) -> dict:
    """La fotografia delle grandezze al momento della transizione.

    Serve fra sei mesi, quando si guarderà una notifica vecchia e ci si chiederà
    perché era stata mandata: senza il contesto la riga dice solo che qualcosa
    è cambiato, e le statistiche di allora nel frattempo sono state riscritte.
    """
    return {
        "setup": etichetta, "v_ref": round(v_ref, 3),
        "v_now": stats["v_now"], "trend": stats["v_trend_mag_month"],
        "peak_v": stats["peak_v"], "peak_jd": stats["peak_jd"],
        "years_since_last_obs": stats["years_since_last_obs"],
        "years_since_good_apparition": stats["years_since_good_apparition"],
        "ceu_now_arcsec": stats["ceu_now_arcsec"],
    }


def recent_transitions(limit: int = 50, only_rollup: bool = True) -> list[dict]:
    """Le ultime transizioni, per la dashboard. Solo il rollup, di default.

    Con dieci setup la stessa notizia comparirebbe dieci volte: il rollup dice
    «è tornato a portata», e da quale strumento è una domanda successiva.
    """
    sql = """SELECT tr.at, tr.from_state, tr.to_state, tr.v_pred, tr.context_json,
                    t.display_name, t.primary_desig, t.kind, tr.setup_id
             FROM state_transition tr JOIN target t ON t.id = tr.target_id
             {dove} ORDER BY tr.at DESC, tr.id DESC LIMIT ?"""
    conn = connect()
    try:
        rows = conn.execute(
            sql.format(dove="WHERE tr.setup_id IS NULL" if only_rollup else ""),
            (limit,)).fetchall()
    finally:
        conn.close()
    return [{**dict(r), "context": json.loads(r["context_json"] or "{}")} for r in rows]


def object_summary(desig: str) -> dict | None:
    """Screening e stati per un oggetto solo: quel che la pagina Oggetto mostra.

    `None` quando lo screening non l'ha ancora toccato — che non è un errore,
    è la maggioranza del catalogo: la popolazione monitorata sono quindicimila
    oggetti su un milione e mezzo.
    """
    # Gli stessi quattro modi di `ephemeris_service.target_row`: la pagina passa
    # quello che ha scritto l'utente, e «1», «Ceres» e «(1) Ceres» devono
    # portare alla stessa scheda qui e là.
    numero = int(desig) if desig.strip().isdigit() else -1
    conn = connect()
    try:
        stats = conn.execute(
            """SELECT s.* FROM target_stats s JOIN target t ON t.id = s.target_id
               WHERE t.primary_desig = ? OR t.display_name = ?
                  OR t.name = ? COLLATE NOCASE
                  OR (t.number = ? AND t.kind = 'asteroid')""",
            (desig, desig, desig, numero)).fetchone()
        if stats is None:
            return None
        stati = conn.execute(
            "SELECT * FROM target_state WHERE target_id=? ORDER BY setup_id IS NOT NULL",
            (stats["target_id"],)).fetchall()
        storia = conn.execute(
            """SELECT from_state, to_state, at, v_pred FROM state_transition
               WHERE target_id=? AND setup_id IS NULL ORDER BY at DESC LIMIT 5""",
            (stats["target_id"],)).fetchall()
    finally:
        conn.close()
    return {"stats": dict(stats), "states": [dict(r) for r in stati],
            "history": [dict(r) for r in storia]}


def state_counts(setup_id: int | None = _ROLLUP) -> list[dict]:
    """Quanti oggetti per stato. L'intestazione della dashboard."""
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT state, count(*) AS n FROM target_state
               WHERE setup_id IS ? GROUP BY state""", (setup_id,)).fetchall()
    finally:
        conn.close()
    per_stato = {r["state"]: r["n"] for r in rows}
    return [{"stato": s, "n": per_stato.get(s, 0)} for s in states.STATES]
