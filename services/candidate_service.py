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
* **la sparizione è un evento.** Un candidato che non è più in lista diventa
  `still_listed = 0` con l'ora in cui ce ne siamo accorti. *Perché* sia sparito
  — designato, identificato con un oggetto noto, scartato — lo dirà il watcher
  MPEC; fino ad allora `resolution` resta NULL, che significa «non lo sappiamo»
  e non «niente di interessante».
* **una lista vuota non cancella niente.** Se l'MPC risponde 200 con zero
  candidati — succede, ed è successo ad altri — chiudere novanta candidati
  insieme sarebbe un danno silenzioso. Sotto la soglia si registra e non si
  tocca nulla.
"""
from __future__ import annotations

import logging

from core.db import connect, transaction
from core.ingest import http, neocp
from core.timeutil import now_iso
from services.jobs import run_job

log = logging.getLogger("sky42.candidati")

# La lista NEOCP tipica ha 50-100 righe; la PCCP 2-10. Una risposta che ne
# porta zero è un guasto della sorgente molto più spesso di un cielo tranquillo:
# si annota e non si chiude niente.
MIN_PLAUSIBILE = {"NEOCP": 1, "PCCP": 0}

SOURCES = {
    "NEOCP": ("neocp", "https://www.minorplanetcenter.net/iau/NEO/neocp.txt", "neocp.txt"),
    "PCCP": ("pccp", "https://www.minorplanetcenter.net/iau/NEO/pccp.txt", "pccp.txt"),
}

# I campi che decidono se vale la pena un nuovo snapshot. Due esclusioni, per
# la stessa ragione: sono **orologi, non osservazioni**.
#
#   * la nota testuale dell'MPC cambia a ogni rigenerazione della pagina anche
#     quando i numeri sono identici;
#   * `not_seen_days` è «adesso meno l'ultima osservazione», quindi cresce da
#     solo a ogni giro, per definizione. Misurato il 2026-08-17 al primo giro
#     vero: 103 candidati, e fra due letture consecutive cambiava **solo**
#     quello (0.179 → 0.183). Tenendolo nel confronto si scriveva un'istantanea
#     per ogni candidato a ogni giro — 15.000 righe al giorno, cinque milioni
#     l'anno: precisamente il rumore che questo confronto esiste per evitare.
#
# Il momento che conta — «è arrivata una nuova osservazione» — resta preso:
# quando `not_seen_days` si azzera davvero, cambia anche `n_obs`.
SNAPSHOT_FIELDS = ("ra_deg", "dec_deg", "v_mag", "n_obs", "arc_hours", "score",
                   "h_mag")


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

    È la coda di lavoro del watcher MPEC che arriverà: finché non c'è, questa
    lista è il promemoria di quello che stiamo *non* sapendo.
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
