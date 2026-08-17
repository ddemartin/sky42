"""Il polling dei candidati MPC: NEOCP e PCCP.

**È l'unico lavoro del progetto che perde dati se non gira.** Tutto il resto si
ricostruisce: il catalogo si riscarica, le tracce si ricalcolano, gli stati si
rifanno. La lista NEOCP no — l'MPC la riscrive, e un candidato che entra alle
02:10 e sparisce alle 05:40 esiste solo se qualcuno era sveglio. Per questo
`mpc_candidate` e `mpc_candidate_snapshot` sono due delle cinque tabelle non
rigenerabili (regola 1), e per questo il polling è stato anticipato a M1.

Tre cose che il servizio fa e che vanno sapute:

* **uno snapshot solo quando qualcosa cambia.** Ogni dieci minuti per novanta
  candidati farebbero mezzo milione di righe l'anno, quasi tutte identiche alla
  precedente. Si confrontano i campi che contano e si scrive solo se si sono
  mossi: la storia resta completa, il rumore no.
* **la sparizione è un evento, e adesso ha anche un perché.** Un candidato che
  non è più in lista diventa `still_listed = 0` con l'ora in cui ce ne siamo
  accorti; `poll_destiny` legge poi la tabella dei trksub già usciti e scrive
  *com'è finita* — designato con circolare, designato e basta, perso,
  inesistente, o identificato con un altro candidato. Finché nessuno l'ha
  detto, `resolution` resta NULL, che significa «non lo sappiamo ancora» e non
  «niente di interessante»; `unknown` invece significa che l'MPC l'ha chiuso in
  un modo che non sappiamo tradurre. Le due cose non si confondono.
* **una lista vuota non cancella niente.** Se l'MPC risponde 200 con zero
  candidati — succede, ed è successo ad altri — chiudere novanta candidati
  insieme sarebbe un danno silenzioso. Sotto la soglia si registra e non si
  tocca nulla.
"""
from __future__ import annotations

import logging

from core.db import connect, transaction
from core.ingest import http, neocp, neocp_prev
from core.timeutil import now_iso
from services.jobs import run_job

log = logging.getLogger("sky42.candidati")

# Il destino dei candidati: un job a parte, con la sua riga in `job_run`.
JOB_DESTINY = "destiny_poll"
DESTINY_SOURCE = ("neocp_prev", neocp_prev.URL, "neocp_prev_des.html")

# La lista NEOCP tipica ha 50-100 righe; la PCCP 2-10. Una risposta che ne
# porta zero è un guasto della sorgente molto più spesso di un cielo tranquillo:
# si annota e non si chiude niente.
MIN_PLAUSIBILE = {"NEOCP": 1, "PCCP": 0}

SOURCES = {
    "NEOCP": ("neocp", "https://www.minorplanetcenter.net/iau/NEO/neocp.txt", "neocp.txt"),
    "PCCP": ("pccp", "https://www.minorplanetcenter.net/iau/NEO/pccp.txt", "pccp.txt"),
}

# I campi che decidono se vale la pena un nuovo snapshot: quelli che dicono
# **cosa l'MPC sa** dell'oggetto. Tre esclusioni, tutte per la stessa ragione —
# cambiano da sole a ogni lettura, quindi non distinguono niente:
#
#   * la nota testuale, che cambia a ogni rigenerazione della pagina;
#   * `not_seen_days`, che è «adesso meno l'ultima osservazione», cioè un
#     orologio;
#   * **RA e Dec**, che nella lista sono un'*effemeride* calcolata per
#     l'istante in cui la si legge, non una misura: un candidato NEOCP si
#     sposta di arcosecondi in pochi minuti.
#
# Misurato il 2026-08-17, due giri consecutivi a sei minuti di distanza: fra i
# due cambiavano soltanto `not_seen_days` (0.183 → 0.186) e la declinazione
# (0.36″). Tenendoli nel confronto si scriveva un'istantanea per **ogni**
# candidato a **ogni** giro: 15.000 righe al giorno, cinque milioni l'anno,
# cioè esattamente il rumore che questo confronto esiste per evitare.
#
# Niente di importante sfugge. Una nuova osservazione muove `n_obs` e l'arco;
# una nuova soluzione orbitale che sposta davvero l'oggetto viene da nuove
# osservazioni, quindi muove gli stessi campi. E la posizione **corrente** —
# quella che serve per puntare — sta sempre aggiornata sulla riga del
# candidato, che è dove la si va a leggere.
SNAPSHOT_FIELDS = ("v_mag", "n_obs", "arc_hours", "score", "h_mag")


def poll(list_name: str, force: bool = False, local_path=None) -> dict:
    """Scarica una lista, la confronta con quella in archivio, scrive le novità."""
    job = f"{list_name.lower()}_poll"
    with run_job(job) as ctx:
        source, url, filename = SOURCES[list_name]

        if local_path is not None:
            testo = local_path.read_text(encoding="utf-8")
            cambiato = True
        else:
            dl = http.fetch(source, url, filename, force=force)
            testo = dl.path.read_text(encoding="utf-8")
            cambiato = dl.changed

        record = neocp.parse_text(testo, list_name)
        esito = _apply(list_name, record, sorgente_cambiata=cambiato)
        ctx.n_processed = len(record)
        ctx.detail = esito
        return esito


def _apply(list_name: str, record: list[dict], sorgente_cambiata: bool) -> dict:
    """Confronta la lista appena letta con quella in archivio, in una transazione."""
    ora = now_iso()
    esito = {"lista": list_name, "in_lista": len(record), "nuovi": 0,
             "aggiornati": 0, "snapshot": 0, "spariti": 0,
             "sorgente_cambiata": sorgente_cambiata}

    if len(record) < MIN_PLAUSIBILE[list_name]:
        log.warning("%s: lista vuota o implausibile (%d righe): non tocco niente",
                    list_name, len(record))
        esito["sospetto"] = "lista vuota: nessuna chiusura"
        return esito

    conn = connect()
    try:
        aperti = {r["temp_desig"]: dict(r) for r in conn.execute(
            "SELECT * FROM mpc_candidate WHERE list=? AND still_listed=1",
            (list_name,)).fetchall()}

        with transaction(conn):
            visti = set()
            for r in record:
                visti.add(r["temp_desig"])
                prima = aperti.get(r["temp_desig"])
                if prima is None:
                    cand_id = _insert_candidate(conn, r, ora)
                    esito["nuovi"] += 1
                    _insert_snapshot(conn, cand_id, r, ora)
                    esito["snapshot"] += 1
                    continue

                _update_candidate(conn, prima["id"], r, ora)
                esito["aggiornati"] += 1
                if _changed(prima, r):
                    _insert_snapshot(conn, prima["id"], r, ora)
                    esito["snapshot"] += 1

            spariti = [c for d, c in aperti.items() if d not in visti]
            for c in spariti:
                conn.execute(
                    "UPDATE mpc_candidate SET still_listed=0, updated_at=? WHERE id=?",
                    (ora, c["id"]))
            esito["spariti"] = len(spariti)
            if spariti:
                log.info("%s: %d candidati non più in lista: %s", list_name,
                         len(spariti), ", ".join(c["temp_desig"] for c in spariti))
    finally:
        conn.close()

    log.info("%s: %d in lista, %d nuovi, %d snapshot, %d spariti", list_name,
             esito["in_lista"], esito["nuovi"], esito["snapshot"], esito["spariti"])
    return esito


def _changed(prima: dict, r: dict) -> bool:
    """Qualcosa che conta si è mosso?

    Il confronto è su valori arrotondati come li scriviamo: senza, un float
    riletto da SQLite differisce dall'originale all'ultimo bit e ogni giro
    produrrebbe uno snapshot «nuovo» identico al precedente.
    """
    for campo in SNAPSHOT_FIELDS:
        a, b = prima.get(campo), r.get(campo)
        if a is None and b is None:
            continue
        if a is None or b is None:
            return True
        if abs(float(a) - float(b)) > 1e-6:
            return True
    return False


_CAND_COLS = ("score", "ra_deg", "dec_deg", "v_mag", "n_obs", "arc_hours",
              "h_mag", "not_seen_days", "discovery_jd", "mpc_note")


def _insert_candidate(conn, r: dict, ora: str) -> int:
    """Apre una riga per un candidato che non era in lista.

    La chiave è `(lista, designazione, first_seen)`, e `first_seen` ha la
    risoluzione del secondo: due giri nello **stesso secondo** — un `cli.py`
    lanciato mentre parte il job, un recupero all'avvio che si accavalla —
    collidono. Non è teorico e non è innocuo: la `IntegrityError` fa rotolare
    indietro l'intera transazione, cioè si perde il giro *completo* invece di
    una riga. Se la chiave esiste già è lo stesso istante, quindi è la stessa
    comparsa: si riapre quella riga invece di inventarne una seconda.
    """
    esistente = conn.execute(
        "SELECT id FROM mpc_candidate WHERE list=? AND temp_desig=? AND first_seen=?",
        (r["list"], r["temp_desig"], ora)).fetchone()
    if esistente is not None:
        _update_candidate(conn, esistente["id"], r, ora)
        return int(esistente["id"])

    cur = conn.execute(
        f"""INSERT INTO mpc_candidate
                (list, temp_desig, first_seen, last_seen, still_listed,
                 {', '.join(_CAND_COLS)}, updated_at)
            VALUES (?,?,?,?,1,{','.join('?' * len(_CAND_COLS))},?)""",
        (r["list"], r["temp_desig"], ora, ora,
         *[r.get(c if c != "mpc_note" else "note") for c in _CAND_COLS], ora))
    log.info("%s: nuovo candidato %s (score %s, V %s, %s obs)", r["list"],
             r["temp_desig"], r["score"], r["v_mag"], r["n_obs"])
    return int(cur.lastrowid)


def _update_candidate(conn, cand_id: int, r: dict, ora: str) -> None:
    conn.execute(
        f"""UPDATE mpc_candidate SET last_seen=?, still_listed=1,
                {', '.join(f'{c}=?' for c in _CAND_COLS)}, updated_at=?
            WHERE id=?""",
        (ora, *[r.get(c if c != "mpc_note" else "note") for c in _CAND_COLS],
         ora, cand_id))


def _insert_snapshot(conn, cand_id: int, r: dict, ora: str) -> None:
    conn.execute(
        """INSERT INTO mpc_candidate_snapshot
               (candidate_id, observed_at, ra_deg, dec_deg, v_mag, n_obs,
                arc_hours, score, h_mag, not_seen_days, raw)
           VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
        (cand_id, ora, r["ra_deg"], r["dec_deg"], r["v_mag"], r["n_obs"],
         r["arc_hours"], r["score"], r["h_mag"], r["not_seen_days"], r["raw"]))


# --- il destino: che fine hanno fatto ---------------------------------------


def poll_destiny(force: bool = False, local_path=None) -> dict:
    """Legge la tabella dei trksub già usciti di lista e chiude i candidati aperti.

    È la seconda metà del watcher: `poll` sa *chi c'è*, questo sa *com'è finita*.
    La fonte non è quella prevista — non serve leggere le circolari, l'MPC
    pubblica la corrispondenza già fatta (vedi `core/ingest/neocp_prev.py`).

    **Non tocca `still_listed`.** Chi è ancora in lista lo decide `poll`, e una
    colonna con due padroni è una colonna che prima o poi si contraddice: un
    candidato può comparire qui e restare in lista qualche minuto, e al giro
    dopo il polling della lista sistema da solo.
    """
    with run_job(JOB_DESTINY) as ctx:
        source, url, filename = DESTINY_SOURCE
        if local_path is not None:
            pagina = local_path.read_text(encoding="utf-8")
        else:
            dl = http.fetch(source, url, filename, force=force)
            pagina = dl.path.read_text(encoding="utf-8")

        righe = neocp_prev.resolve(neocp_prev.parse(pagina))
        esito = _apply_destiny(righe)
        ctx.n_processed = esito["risolti"]
        ctx.detail = esito
        return esito


def _apply_destiny(righe: list[dict]) -> dict:
    """Scrive i destini, le circolari, e ritenta gli agganci al catalogo."""
    esito = {"righe": len(righe), "risolti": 0, "senza_candidato": 0,
             "fuori_tempo": 0, "riagganciati": 0, "mpec": 0, "per_destino": {}}
    if not righe:
        # La pagina ha cambiato forma, o è in manutenzione. Zero righe non
        # chiude niente: è la stessa difesa della lista vuota di `_apply`.
        log.warning("destino: nessuna riga letta, non tocco niente")
        esito["sospetto"] = "pagina vuota o cambiata: nessuna chiusura"
        return esito

    ora = now_iso()
    conn = connect()
    try:
        # I candidati ancora senza destino, il più recente per ogni trksub: lo
        # stesso trksub può tornare in lista mesi dopo, e il destino di oggi
        # riguarda l'ultimo passaggio, non il primo.
        aperti: dict[str, dict] = {}
        for r in conn.execute(
                """SELECT id, temp_desig, list, first_seen FROM mpc_candidate
                   WHERE resolution IS NULL ORDER BY first_seen"""):
            aperti[r["temp_desig"]] = dict(r)

        with transaction(conn):
            for r in righe:
                cand = aperti.get(r["trksub"])
                if cand is not None and _fuori_tempo(r, cand):
                    # Il destino è **più vecchio** del nostro avvistamento:
                    # parla di un passaggio precedente dello stesso trksub, non
                    # di questo. Visto il 2026-08-17 su `A11FAuF`, dichiarato
                    # inesistente il 13 e rientrato in lista il 17 con score 100
                    # e sei osservazioni: applicarglielo avrebbe scritto «non
                    # esiste» su un candidato che quella notte era da guardare.
                    esito["fuori_tempo"] += 1
                    cand = None
                elif cand is None:
                    esito["senza_candidato"] += 1
                else:
                    _scrivi_destino(conn, cand["id"], r, ora)
                    esito["risolti"] += 1
                    esito["per_destino"][r["resolution"]] = \
                        esito["per_destino"].get(r["resolution"], 0) + 1
                if r["mpec_id"]:
                    esito["mpec"] += _scrivi_mpec(
                        conn, r, cand["id"] if cand else None, ora)

            esito["riagganciati"] = _riaggancia(conn)
    finally:
        conn.close()

    log.info("destino: %d righe, %d candidati chiusi (%s), %d circolari, "
             "%d riagganciati al catalogo", esito["righe"], esito["risolti"],
             esito["per_destino"], esito["mpec"], esito["riagganciati"])
    return esito


def _fuori_tempo(r: dict, cand: dict) -> bool:
    """Il destino riguarda un passaggio **precedente** dello stesso trksub?

    L'MPC riusa le designazioni temporanee: un oggetto dichiarato inesistente
    può rientrare in lista giorni dopo con lo stesso trksub, e allora la
    decisione vecchia non parla del candidato di adesso. Il confronto è fra
    l'istante della decisione e il nostro primo avvistamento; senza data si
    applica, perché una riga senza istante è comunque l'ultima cosa che l'MPC
    ha detto di quel trksub.

    Misurato il 2026-08-17: `A11FAuF`, «dne» il 13 alle 23:17, era in lista il
    17 con score 100 e sei osservazioni. Sarebbe stato marcato «non esiste»
    proprio la notte in cui andava guardato.
    """
    if not r["seen_at"] or not cand.get("first_seen"):
        return False
    return r["seen_at"] < cand["first_seen"]


def _scrivi_destino(conn, candidate_id: int, r: dict, ora: str) -> None:
    """`resolved_at` è **quando l'MPC l'ha deciso**, non quando l'abbiamo letto.

    La pagina porta l'istante della decisione, ed è quello che serve fra un
    anno per dire quanto è durato un candidato. Se manca si ripiega su adesso,
    che è comunque un limite superiore.
    """
    conn.execute(
        """UPDATE mpc_candidate
           SET resolution=?, resolved_at=?, resolved_desig=?, resolution_source=?,
               resolved_target_id=(SELECT id FROM target WHERE primary_desig=?),
               updated_at=?
           WHERE id=?""",
        (r["resolution"], r["seen_at"] or ora, r["resolved_desig"],
         r["resolution_source"], r["resolved_desig"], ora, candidate_id))


def _scrivi_mpec(conn, r: dict, candidate_id: int | None, ora: str) -> int:
    """La circolare come **riferimento**, non come contenuto.

    Di questa circolare sappiamo l'identificativo, l'indirizzo e di quale
    oggetto parla — l'abbiamo saputo di rimbalzo, senza leggerla. `title`,
    `published_at` e `body_hash` restano NULL di proposito: riempirli con
    l'istante in cui il candidato è stato chiuso significherebbe scrivere un
    numero plausibile e falso in una colonna che ha un significato preciso.
    """
    conn.execute(
        """INSERT INTO mpec (mpec_id, url, kind, fetched_at)
           VALUES (?,?,?,?)
           ON CONFLICT (mpec_id) DO UPDATE SET url=COALESCE(excluded.url, url)""",
        (r["mpec_id"], r["mpec_url"], _kind(r), ora))
    riga = conn.execute("SELECT id FROM mpec WHERE mpec_id=?", (r["mpec_id"],)).fetchone()
    if riga is None or not r["resolved_desig"]:
        return 1
    conn.execute(
        """INSERT OR REPLACE INTO mpec_object (mpec_id_ref, designation, target_id,
                                               candidate_id)
           VALUES (?,?,(SELECT id FROM target WHERE primary_desig=?),?)""",
        (riga["id"], r["resolved_desig"], r["resolved_desig"], candidate_id))
    return 1


def _kind(r: dict) -> str:
    return "comet" if r["resolution"] == "confirmed_comet" else "neo"


def _riaggancia(conn) -> int:
    """Ritenta l'aggancio al catalogo dei candidati già risolti.

    Serve perché **l'MPC designa prima di pubblicare MPCORB**: `2026 PN9` è
    stato designato il 17 agosto alle 11:52 e quel giorno non era ancora in
    catalogo. Senza questo secondo tentativo, `resolved_target_id` resterebbe
    NULL per sempre proprio per gli oggetti più nuovi — cioè quelli per cui la
    domanda «che fine ha fatto» ha più senso.
    """
    cur = conn.execute(
        """UPDATE mpc_candidate
           SET resolved_target_id=(SELECT id FROM target WHERE primary_desig=resolved_desig)
           WHERE resolved_desig IS NOT NULL AND resolved_target_id IS NULL
             AND EXISTS (SELECT 1 FROM target WHERE primary_desig=resolved_desig)""")
    return cur.rowcount


def destiny_age_hours() -> float | None:
    """Da quante ore non si guarda il destino dei candidati."""
    from core.timeutil import days_since

    conn = connect()
    try:
        row = conn.execute(
            "SELECT max(started_at) AS t FROM job_run WHERE job_name=? AND status='ok'",
            (JOB_DESTINY,)).fetchone()
    finally:
        conn.close()
    giorni = days_since(row["t"] if row else None)
    return giorni * 24.0 if giorni is not None else None


# --- i job ------------------------------------------------------------------


def poll_neocp(force: bool = False, local_path=None) -> dict:
    return poll("NEOCP", force=force, local_path=local_path)


def poll_pccp(force: bool = False, local_path=None) -> dict:
    return poll("PCCP", force=force, local_path=local_path)


def poll_age_hours(list_name: str = "NEOCP") -> float | None:
    """Da quante ore non si guarda quella lista. Per il recupero all'avvio."""
    from core.timeutil import days_since

    conn = connect()
    try:
        row = conn.execute(
            """SELECT max(started_at) AS t FROM job_run
               WHERE job_name=? AND status='ok'""", (f"{list_name.lower()}_poll",)
        ).fetchone()
    finally:
        conn.close()
    giorni = days_since(row["t"] if row else None)
    return giorni * 24.0 if giorni is not None else None


# --- letture ----------------------------------------------------------------


def open_candidates(list_name: str | None = None, limit: int = 200) -> list[dict]:
    """I candidati ancora in lista, i più urgenti in cima.

    L'ordine è **score, poi da quanto non li riprende nessuno**: un oggetto con
    score 100 non ancora perso è la cosa più utile che si possa fare stanotte,
    e uno score 100 che nessuno segue da tre giorni è quello che sta per essere
    perso davvero.
    """
    dove = "WHERE still_listed = 1" + (" AND list = ?" if list_name else "")
    conn = connect()
    try:
        righe = conn.execute(
            f"""SELECT * FROM mpc_candidate {dove}
                ORDER BY score DESC, not_seen_days DESC LIMIT ?""",
            ((list_name, limit) if list_name else (limit,))).fetchall()
        return [dict(r) for r in righe]
    finally:
        conn.close()


def history(candidate_id: int) -> list[dict]:
    """Tutti gli snapshot di un candidato, dal primo all'ultimo."""
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT * FROM mpc_candidate_snapshot WHERE candidate_id=?
               ORDER BY observed_at""", (candidate_id,)).fetchall()]
    finally:
        conn.close()


def recent_departures(days: float = 7.0, limit: int = 50) -> list[dict]:
    """Chi è sparito dalla lista di recente, e non sappiamo ancora perché.

    Resta la coda di lavoro: `poll_destiny` copre quattro giorni di storia, e
    un candidato sparito prima che il watcher esistesse non ha più una risposta
    da nessuna parte. Questa lista è il promemoria di quello che stiamo *non*
    sapendo — e più resta corta, meglio sta funzionando il destino.
    """
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT * FROM mpc_candidate
               WHERE still_listed = 0 AND resolution IS NULL
                 AND julianday(updated_at) > julianday('now') - ?
               ORDER BY updated_at DESC LIMIT ?""", (days, limit)).fetchall()]
    finally:
        conn.close()


def resolved_candidates(days: float = 30.0, limit: int = 100) -> list[dict]:
    """Che fine hanno fatto: i candidati chiusi di recente, con il loro perché.

    Porta con sé il nome dell'oggetto in cui si è trasformato, quando c'è: un
    trksub non dice niente a nessuno fra sei mesi, `2026 PN9` sì.
    """
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(
            """SELECT c.*, t.display_name AS target_name, t.orbit_class,
                      m.url AS mpec_url
               FROM mpc_candidate c
               LEFT JOIN target t ON t.id = c.resolved_target_id
               LEFT JOIN mpec m ON m.mpec_id =
                    replace(c.resolution_source, 'mpec:', '')
               WHERE c.resolution IS NOT NULL
                 AND julianday(c.resolved_at) > julianday('now') - ?
               ORDER BY c.resolved_at DESC LIMIT ?""", (days, limit)).fetchall()]
    finally:
        conn.close()


def counts() -> dict:
    """I numeri dell'intestazione: quanti aperti, quanti visti, quanti risolti."""
    conn = connect()
    try:
        out = {}
        for lista in neocp.LISTS:
            row = conn.execute(
                """SELECT count(*) AS visti,
                          sum(still_listed) AS aperti,
                          sum(resolution IS NOT NULL) AS risolti
                   FROM mpc_candidate WHERE list=?""", (lista,)).fetchone()
            out[lista] = {"visti": row["visti"], "aperti": row["aperti"] or 0,
                          "risolti": row["risolti"] or 0}
        out["snapshot"] = conn.execute(
            "SELECT count(*) FROM mpc_candidate_snapshot").fetchone()[0]
        return out
    finally:
        conn.close()
