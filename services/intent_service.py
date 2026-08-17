"""I propositi osservativi: «questo lo voglio riprendere», e come va a finire.

È il pezzo che chiude il giro del progetto. Fino a qui sky42 sapeva
**suggerire** — il radar dice chi torna a portata, la dashboard dice cosa fare
stanotte — ma non teneva traccia di cosa l'osservatore avesse deciso di farne.
Un suggerimento che nessuno registra è un suggerimento che si ripete uguale il
giorno dopo, e un'occasione persa non lascia niente da cui imparare.

Un proposito nasce da un suggerimento, si porta dietro la **fotografia del
perché** (stato del radar, V prevista, punteggio, finestra di quella notte) e
finisce in uno di quattro modi:

* `observed` — è stato ripreso, e c'è una riga in `observation_log`;
* `expired` — **l'occasione è passata**, e il motivo si registra:
  `out_of_range` (è sceso sotto il limite) oppure `no_window` (da quel setup non
  ha più una finestra utile). Sono due fallimenti diversi: il primo dice che
  bisognava muoversi prima, il secondo che serviva un altro sito;
* `dropped` — lasciato perdere a mano;
* `planned` — ancora aperto.

**Non ricalcola niente.** Legge `target_state` (il radar) e `observation_window`
(il job delle finestre), esattamente come la dashboard: se qui comparisse una
propagazione, vorrebbe dire che il proposito ha cominciato a farsi un'idea sua
di quando un oggetto è osservabile, diversa da quella di tutto il resto.
"""
from __future__ import annotations

import json
import logging

from core.db import connect, transaction
from core.timeutil import now_iso
from services.jobs import run_job

log = logging.getLogger("sky42.propositi")

JOB_NAME = "intents_refresh"

# Gli stati in cui un proposito è ancora vivo.
APERTI = ("planned",)


# --- creare un proposito -----------------------------------------------------


def add(desig: str, setup_code: str | None = None, purpose: str | None = None,
        priority: int = 0, source: str = "manuale", note: str | None = None,
        deadline: str | None = None) -> dict | None:
    """«Voglio osservare questo». `None` se la designazione non è in catalogo.

    Un proposito già aperto sullo stesso oggetto e sullo stesso setup non si
    duplica: si restituisce quello, perché premere due volte lo stesso pulsante
    è un incidente, non una seconda intenzione.
    """
    conn = connect()
    try:
        target = _target(conn, desig)
        if target is None:
            return None
        setup = _setup(conn, setup_code)
        if setup_code and setup is None:
            raise ValueError(f"setup sconosciuto: {setup_code}")
        setup_id = setup["id"] if setup else None

        esistente = conn.execute(
            f"""SELECT * FROM observing_intent
                WHERE desig=? AND setup_id IS ? AND status IN
                      ({','.join('?' * len(APERTI))})""",
            (target["primary_desig"], setup_id, *APERTI)).fetchone()
        if esistente is not None:
            return dict(esistente)

        ora = now_iso()
        contesto = context_of(conn, target["id"], setup_id)
        with transaction(conn):
            cur = conn.execute(
                """INSERT INTO observing_intent
                       (desig, target_id, setup_id, created_at, created_from,
                        purpose, priority, deadline, status, status_at,
                        context_json, note)
                   VALUES (?,?,?,?,?,?,?,?,'planned',?,?,?)""",
                (target["primary_desig"], target["id"], setup_id, ora, source,
                 purpose, priority, deadline, ora,
                 json.dumps(contesto, default=str), note))
            riga = conn.execute("SELECT * FROM observing_intent WHERE id=?",
                                (cur.lastrowid,)).fetchone()
        log.info("proposito: %s%s (%s)", target["primary_desig"],
                 f" con {setup_code}" if setup_code else "", source)
        return dict(riga)
    finally:
        conn.close()


def _target(conn, desig: str) -> dict | None:
    """Gli stessi quattro modi di cercare della pagina Oggetto: «1», «Ceres», «(1) Ceres»."""
    numero = int(desig) if desig.strip().isdigit() else -1
    riga = conn.execute(
        """SELECT id, primary_desig, display_name, kind FROM target
           WHERE primary_desig = ? OR display_name = ? OR name = ? COLLATE NOCASE
              OR (number = ? AND kind = 'asteroid') LIMIT 1""",
        (desig, desig, desig, numero)).fetchone()
    return dict(riga) if riga else None


def _setup(conn, code: str | None) -> dict | None:
    if not code:
        return None
    riga = conn.execute("SELECT id, code FROM setup WHERE code=?", (code,)).fetchone()
    return dict(riga) if riga else None


def context_of(conn, target_id: int, setup_id: int | None) -> dict:
    """Cosa si sapeva dell'oggetto quando si è deciso di osservarlo.

    Serve fra sei mesi, guardando un proposito scaduto: «cosa mi aveva
    convinto» non ha risposta se nel frattempo lo screening ha riscritto le
    statistiche — e le riscrive ogni notte.
    """
    stato = conn.execute(
        "SELECT state, v_pred, eff_vlim_ref, since FROM target_state "
        "WHERE target_id=? AND setup_id IS ?", (target_id, setup_id)).fetchone()
    if stato is None:      # nessuno stato per quel setup: si ripiega sul rollup
        stato = conn.execute(
            "SELECT state, v_pred, eff_vlim_ref, since FROM target_state "
            "WHERE target_id=? AND setup_id IS NULL", (target_id,)).fetchone()
    stats = conn.execute(
        """SELECT v_now, v_trend_mag_month, peak_v, peak_jd, visibility_end_jd,
                  years_since_last_obs, years_since_good_apparition, ceu_now_arcsec
           FROM target_stats WHERE target_id=?""", (target_id,)).fetchone()
    finestra = conn.execute(
        """SELECT w.useful_hours, w.depth_margin, w.score, w.grade, n.night_date
           FROM observation_window w JOIN night n ON n.id = w.night_id
           WHERE w.target_id=? AND (? IS NULL OR w.setup_id=?)
           ORDER BY w.score DESC LIMIT 1""",
        (target_id, setup_id, setup_id)).fetchone()
    return {"radar": dict(stato) if stato else None,
            "stats": dict(stats) if stats else None,
            "window": dict(finestra) if finestra else None}


# --- chiuderlo ---------------------------------------------------------------


def close(intent_id: int, status: str, reason: str | None = None) -> None:
    """Chiude un proposito. `status_at` è quando l'abbiamo chiuso, non quando è deciso."""
    if status not in ("observed", "expired", "dropped", "planned"):
        raise ValueError(f"stato sconosciuto: {status}")
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE observing_intent SET status=?, status_at=?, closed_reason=? "
                "WHERE id=?", (status, now_iso(), reason, intent_id))
    finally:
        conn.close()


def drop(intent_id: int, note: str | None = None) -> None:
    """«Lascio perdere». Non si cancella: un proposito abbandonato è informazione."""
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                """UPDATE observing_intent SET status='dropped', status_at=?,
                       closed_reason='manuale',
                       note=COALESCE(?, note) WHERE id=?""",
                (now_iso(), note, intent_id))
    finally:
        conn.close()


def reopen(intent_id: int) -> None:
    """Riapre un proposito scaduto: l'oggetto può tornare, e spesso torna."""
    conn = connect()
    try:
        with transaction(conn):
            conn.execute(
                "UPDATE observing_intent SET status='planned', status_at=?, "
                "closed_reason=NULL WHERE id=?", (now_iso(), intent_id))
    finally:
        conn.close()


# --- il job: chi è ancora in tempo, e chi no --------------------------------


def refresh() -> dict:
    """Riesamina i propositi aperti. Idempotente: rilanciarlo non cambia niente.

    Due motivi di scadenza, e restano **distinti** perché si tarano in modo
    opposto: `out_of_range` dice che bisognava muoversi prima, `no_window` che
    serviva un altro sito.
    """
    with run_job(JOB_NAME) as ctx:
        ora = now_iso()
        esito = {"aperti": 0, "scaduti": 0, "riagganciati": 0, "per_motivo": {}}

        conn = connect()
        try:
            esito["riagganciati"] = _riaggancia(conn)
            aperti = [dict(r) for r in conn.execute(
                f"""SELECT * FROM observing_intent WHERE status IN
                    ({','.join('?' * len(APERTI))})""", APERTI).fetchall()]
            esito["aperti"] = len(aperti)

            # Le notti con finestre calcolate, per setup: senza almeno una, la
            # mappa è vuota e «nessuna finestra utile» non significherebbe
            # niente. È la differenza fra «non si vede» e «non l'ho calcolato»,
            # e senza questa guardia il primo avvio scaderebbe tutto.
            coperti = _setup_con_finestre(conn)

            chiusure = []
            for intent in aperti:
                motivo = _perche_scade(conn, intent, coperti, ora)
                if motivo:
                    chiusure.append((ora, motivo, intent["id"]))
                    esito["per_motivo"][motivo] = esito["per_motivo"].get(motivo, 0) + 1

            if chiusure:
                with transaction(conn):
                    conn.executemany(
                        "UPDATE observing_intent SET status='expired', status_at=?, "
                        "closed_reason=? WHERE id=?", chiusure)
            esito["scaduti"] = len(chiusure)
        finally:
            conn.close()

        ctx.n_processed = esito["aperti"]
        ctx.detail = esito
        if esito["scaduti"]:
            log.info("propositi: %d scaduti (%s) su %d aperti", esito["scaduti"],
                     esito["per_motivo"], esito["aperti"])
        return esito


def _riaggancia(conn) -> int:
    """Ritenta l'aggancio al catalogo per designazione.

    Serve dopo un ripristino da backup su un catalogo riscaricato, dove gli id
    sono altri: la designazione è la chiave che sopravvive (regola 1). Stessa
    logica dei candidati risolti.
    """
    with transaction(conn):
        cur = conn.execute(
            """UPDATE observing_intent
               SET target_id=(SELECT id FROM target WHERE primary_desig=desig)
               WHERE target_id IS NULL
                 AND EXISTS (SELECT 1 FROM target WHERE primary_desig=desig)""")
    return cur.rowcount


def _setup_con_finestre(conn) -> set:
    """I setup per cui esistono finestre calcolate da oggi in avanti.

    `None` nell'insieme significa «esiste almeno una finestra, per qualunque
    setup»: è la copertura che serve ai propositi senza setup scelto.
    """
    righe = conn.execute(
        """SELECT DISTINCT w.setup_id FROM observation_window w
           JOIN night n ON n.id = w.night_id
           WHERE julianday(n.night_date) >= julianday('now') - 1""").fetchall()
    coperti = {r["setup_id"] for r in righe}
    if coperti:
        coperti.add(None)
    return coperti


def _perche_scade(conn, intent: dict, coperti: set, ora: str) -> str | None:
    """Il motivo per cui questo proposito è andato, o `None` se è ancora in tempo."""
    if intent["deadline"] and intent["deadline"] < ora:
        return "deadline"

    if intent["target_id"] is None:
        # Non agganciato al catalogo: non si sa niente di lui, e «non lo so»
        # non è un motivo per chiudere.
        return None

    stato = conn.execute(
        "SELECT state FROM target_state WHERE target_id=? AND setup_id IS ?",
        (intent["target_id"], intent["setup_id"])).fetchone()
    if stato is None and intent["setup_id"] is not None:
        stato = conn.execute(
            "SELECT state FROM target_state WHERE target_id=? AND setup_id IS NULL",
            (intent["target_id"],)).fetchone()
    if stato is not None and stato["state"] == "OUT_OF_RANGE":
        # **Solo** OUT_OF_RANGE chiude, e non «tutto ciò che non è IN_RANGE».
        # Gli altri due stati fuori portata dicono il contrario di «è andata»:
        # APPROACHING è «sta arrivando», e FADING è «ultima occasione». La
        # prima versione li trattava da scaduti e il servizio vero ha chiuso
        # subito C/2019 E3 (ATLAS) — primo della classifica di stanotte, V 18.33
        # contro un limite di 21.06, 7,6 ore utili — perché il suo trend era di
        # +0.035 mag/mese, cioè aveva passato il picco. Il radar ha già isteresi
        # e conferma su due giri: quando dice OUT_OF_RANGE, è andata davvero.
        return "out_of_range"

    if intent["setup_id"] in coperti:
        finestre = conn.execute(
            """SELECT count(*) FROM observation_window w
               JOIN night n ON n.id = w.night_id
               WHERE w.target_id=? AND w.useful_hours > 0
                 AND (? IS NULL OR w.setup_id = ?)
                 AND julianday(n.night_date) >= julianday('now') - 1""",
            (intent["target_id"], intent["setup_id"], intent["setup_id"])).fetchone()[0]
        if finestre == 0:
            return "no_window"
    return None


# --- registrare una sessione -------------------------------------------------


# Le colonne che una sessione può portare. In una costante perché l'elenco
# compare due volte — nella firma e nell'INSERT — e due elenchi che devono
# restare allineati sono un elenco solo.
SESSION_FIELDS = (
    "obs_end", "exposure_s", "n_frames", "total_exposure_s", "tracking_mode",
    "purpose", "outcome", "measured_mag", "fwhm_arcsec", "snr_median",
    "limiting_mag", "residual_arcsec", "processed", "reported_mpc",
    "reported_cobs", "archive_folder", "cost", "note",
)


def log_observation(desig: str, obs_start: str, setup_code: str | None = None,
                    intent_id: int | None = None, **campi) -> dict | None:
    """Registra una sessione. Chiude il proposito collegato, se c'è.

    Si può registrare **anche senza proposito**: capita di riprendere qualcosa
    perché era lì, e un registro che accetta solo il pianificato racconta una
    notte più ordinata di com'è stata.

    Se `intent_id` non è dato ma esiste un proposito aperto per quell'oggetto e
    quel setup, si aggancia da sé: nessuno vuole scegliere da un elenco la cosa
    che ha appena deciso di fare.
    """
    ignoti = set(campi) - set(SESSION_FIELDS)
    if ignoti:
        raise ValueError(f"campi sconosciuti: {', '.join(sorted(ignoti))}")

    conn = connect()
    try:
        target = _target(conn, desig)
        if target is None:
            return None
        setup = _setup(conn, setup_code)
        setup_id = setup["id"] if setup else None

        if intent_id is None:
            riga = conn.execute(
                """SELECT id FROM observing_intent
                   WHERE desig=? AND status='planned'
                     AND (setup_id IS ? OR setup_id IS NULL)
                   ORDER BY setup_id IS NULL, created_at DESC LIMIT 1""",
                (target["primary_desig"], setup_id)).fetchone()
            intent_id = riga["id"] if riga else None

        colonne = ["target_id", "desig", "intent_id", "setup_id", "obs_start"]
        valori = [target["id"], target["primary_desig"], intent_id, setup_id, obs_start]
        for campo in SESSION_FIELDS:
            if campo in campi and campi[campo] is not None:
                colonne.append(campo)
                valori.append(campi[campo])

        # Il costo si calcola dal tempo di posa, se il setup ha un listino e
        # nessuno l'ha scritto a mano: è aritmetica, e nessuno la fa volentieri
        # alle tre di notte. Un costo dichiarato vince sempre — le sessioni
        # vere hanno sovrapprezzi, notti perse, tariffe di Luna piena.
        if "cost" not in colonne:
            costo = _costo(conn, setup_id, campi.get("total_exposure_s"))
            if costo is not None:
                colonne.append("cost")
                valori.append(costo)

        with transaction(conn):
            cur = conn.execute(
                f"""INSERT INTO observation_log ({', '.join(colonne)})
                    VALUES ({', '.join('?' * len(colonne))})""", valori)
            if intent_id is not None:
                conn.execute(
                    """UPDATE observing_intent SET status='observed', status_at=?,
                           closed_reason='observed' WHERE id=?""",
                    (now_iso(), intent_id))
            riga = conn.execute("SELECT * FROM observation_log WHERE id=?",
                                (cur.lastrowid,)).fetchone()
        log.info("sessione: %s il %s%s", target["primary_desig"], obs_start[:16],
                 f" ({setup_code})" if setup_code else "")
        return dict(riga)
    finally:
        conn.close()


def _costo(conn, setup_id: int | None, total_exposure_s) -> float | None:
    """Il costo di una sessione: ore di posa × listino del setup.

    Si conta il **tempo di posa**, non la durata della finestra: è quello che i
    servizi remoti fatturano, ed è l'unico numero che sky42 conosce davvero.
    `None` se il setup non ha un listino — che significa «non si paga», ed è
    diverso da zero.
    """
    if setup_id is None or not total_exposure_s:
        return None
    riga = conn.execute("SELECT cost_per_hour FROM setup WHERE id=?",
                        (setup_id,)).fetchone()
    if riga is None or riga["cost_per_hour"] is None:
        return None
    return round(float(total_exposure_s) / 3600.0 * float(riga["cost_per_hour"]), 2)


def spesa(days: float = 365.0) -> dict:
    """Quanto si è speso, per setup. La domanda di fine mese.

    Le sessioni senza costo non valgono zero: valgono «non si paga», e si
    contano a parte — un totale che le mescolasse direbbe che il telescopio di
    casa costa quanto quello affittato.
    """
    conn = connect()
    try:
        righe = conn.execute(
            """SELECT s.code AS setup_code, s.currency,
                      count(*) AS sessioni,
                      sum(l.cost IS NOT NULL) AS con_costo,
                      round(sum(COALESCE(l.cost, 0)), 2) AS totale,
                      round(sum(COALESCE(l.total_exposure_s, 0)) / 3600.0, 2) AS ore
               FROM observation_log l
               LEFT JOIN setup s ON s.id = l.setup_id
               WHERE julianday(l.obs_start) > julianday('now') - ?
               GROUP BY l.setup_id ORDER BY totale DESC""", (days,)).fetchall()
    finally:
        conn.close()
    return {"per_setup": [dict(r) for r in righe],
            "totale": round(sum(r["totale"] or 0 for r in righe), 2)}


# --- letture per l'interfaccia -----------------------------------------------


def overview(limit: int = 100) -> dict:
    """Propositi aperti, chiusi, e le ultime sessioni. Per la pagina e per il JSON."""
    return {"open": list_intents("planned", limit),
            "closed": list_intents(None, limit, chiusi=True),
            "sessions": sessions(limit)}


def list_intents(status: str | None = "planned", limit: int = 100,
                 chiusi: bool = False) -> list[dict]:
    """I propositi, con quel che si sa **adesso** dell'oggetto accanto.

    Lo stato del radar e la finestra di stanotte arrivano dalla stessa query:
    un proposito aperto senza «e adesso com'è messo» costringerebbe a
    controllare a mano oggetto per oggetto, che è esattamente il lavoro che
    questa tabella esiste per evitare.
    """
    dove = "WHERE i.status != 'planned'" if chiusi else \
           ("WHERE i.status = ?" if status else "")
    params: list = [] if chiusi else ([status] if status else [])

    conn = connect()
    try:
        righe = conn.execute(
            f"""SELECT i.*, t.display_name, t.kind, t.orbit_class, o.tisserand_j,
                       s.code AS setup_code, ob.code AS site_code,
                       ts.state, ts.v_pred, ts.eff_vlim_ref,
                       st.v_now, st.v_trend_mag_month, st.visibility_end_jd,
                       st.years_since_last_obs
                FROM observing_intent i
                LEFT JOIN target t   ON t.id = i.target_id
                LEFT JOIN orbit o    ON o.target_id = i.target_id
                LEFT JOIN setup s    ON s.id = i.setup_id
                LEFT JOIN observatory ob ON ob.id = s.observatory_id
                LEFT JOIN target_state ts ON ts.target_id = i.target_id
                                         AND ts.setup_id IS i.setup_id
                LEFT JOIN target_stats st ON st.target_id = i.target_id
                {dove}
                ORDER BY i.priority DESC, i.created_at DESC LIMIT ?""",
            (*params, limit)).fetchall()
        out = []
        for r in righe:
            d = dict(r)
            d["context"] = json.loads(d.pop("context_json") or "{}")
            d["tonight"] = _finestra_stanotte(conn, d)
            # `FADING` non è «è andata»: è «ultima occasione». Un oggetto può
            # stare due magnitudini sotto il limite ed essere già oltre il
            # picco, ed è precisamente quello da fare per primo.
            d["ultima_occasione"] = d["state"] == "FADING"
            out.append(d)
        return out
    finally:
        conn.close()


def _finestra_stanotte(conn, intent: dict) -> dict | None:
    """La finestra migliore fra quelle calcolate, per quel proposito."""
    if intent["target_id"] is None:
        return None
    riga = conn.execute(
        """SELECT w.useful_hours, w.depth_margin, w.score, w.grade, w.v_pred,
                  w.best_alt_deg, n.night_date, s.code AS setup_code
           FROM observation_window w
           JOIN night n ON n.id = w.night_id
           JOIN setup s ON s.id = w.setup_id
           WHERE w.target_id=? AND (? IS NULL OR w.setup_id=?)
             AND julianday(n.night_date) >= julianday('now') - 1
           ORDER BY w.useful_hours > 0 DESC, w.score DESC, n.night_date LIMIT 1""",
        (intent["target_id"], intent["setup_id"], intent["setup_id"])).fetchone()
    return dict(riga) if riga else None


def sessions(limit: int = 100) -> list[dict]:
    """Le sessioni registrate, dalla più recente."""
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT l.*, t.display_name, s.code AS setup_code
               FROM observation_log l
               LEFT JOIN target t ON t.id = l.target_id
               LEFT JOIN setup s  ON s.id = l.setup_id
               ORDER BY l.obs_start DESC LIMIT ?""", (limit,)).fetchall()]
    finally:
        conn.close()


def counts() -> dict:
    """Quanti propositi per stato, e quante sessioni. L'intestazione della pagina."""
    conn = connect()
    try:
        per_stato = {r["status"]: r["n"] for r in conn.execute(
            "SELECT status, count(*) AS n FROM observing_intent GROUP BY status")}
        per_motivo = {r["closed_reason"]: r["n"] for r in conn.execute(
            """SELECT closed_reason, count(*) AS n FROM observing_intent
               WHERE status='expired' GROUP BY closed_reason""")}
        sessioni = conn.execute("SELECT count(*) FROM observation_log").fetchone()[0]
        riportate = conn.execute(
            "SELECT count(*) FROM observation_log WHERE reported_mpc='yes'").fetchone()[0]
    finally:
        conn.close()
    return {"per_stato": {s: per_stato.get(s, 0) for s in
                          ("planned", "observed", "expired", "dropped")},
            "per_motivo": per_motivo, "sessioni": sessioni, "riportate": riportate}
