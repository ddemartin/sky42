"""Letture sul catalogo per l'interfaccia. Nessuna scrittura.

Ogni funzione restituisce strutture Python semplici (dict, liste di dict), mai
righe di sqlite3 e mai HTML: sono le stesse che serviranno a un endpoint JSON
quando la dashboard vorrà i grafici invece delle tabelle.
"""
from __future__ import annotations

from core import config
from core.db import connect, get_setting
from core.timeutil import days_since

SOURCES = [
    ("mpcorb", "MPCORB extended", "fonte: identità, elementi, classe, ultima osservazione"),
    ("astorb", "ASTORB", "strato: incertezza CEU/PEU, dati fisici IRAS"),
    ("cometels", "CometEls", "comete: elementi q/Tp"),
]


def _rows(sql: str, params=()) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _one(sql: str, params=()):
    conn = connect()
    try:
        row = conn.execute(sql, params).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def data_state() -> dict[str, dict]:
    """Cosa c'è **davvero** in archivio, per sorgente, letto dai dati stessi.

    Non da `catalog_version`: quella tabella racconta gli *scaricamenti*, e un
    import fatto da file locale (o un database ripristinato da backup) non ne
    lascia traccia pur avendo popolato tutto. La domanda «i dati ci sono e di
    quando sono» si risponde guardando i dati.
    """
    state = {}
    for r in _rows("SELECT source, count(*) AS n, max(updated_at) AS ts FROM orbit GROUP BY source"):
        state[r["source"]] = {"n": r["n"], "ts": r["ts"]}
    r = _rows("SELECT count(*) AS n, max(updated_at) AS ts FROM astorb_extra")[0]
    state["astorb"] = {"n": r["n"], "ts": r["ts"]}
    return state


def source_status() -> list[dict]:
    """Per ogni sorgente: cosa c'è in archivio, e quando è stata scaricata.

    Le due cose sono distinte e vanno mostrate distinte: il badge di freschezza
    segue **i dati**, non il download.
    """
    data = data_state()
    out = []
    for source, label, note in SOURCES:
        row = _rows(
            """SELECT downloaded_at, imported_at, n_records, size_bytes, sha256, url
               FROM catalog_version WHERE source=? ORDER BY downloaded_at DESC LIMIT 1""",
            (source,),
        )
        info = row[0] if row else {}
        stato = data.get(source, {"n": 0, "ts": None})
        out.append({
            "source": source,
            "label": label,
            "note": note,
            # cosa c'è in archivio
            "in_db": stato["n"],
            "data_at": stato["ts"],
            "age_days": _age_days(stato["ts"]),
            # come ci è arrivato
            "downloaded_at": info.get("downloaded_at"),
            "download_age_days": _age_days(info.get("downloaded_at")),
            "n_records": info.get("n_records"),
            "size_mb": round(info["size_bytes"] / 1e6, 1) if info.get("size_bytes") else None,
            "sha_short": (info.get("sha256") or "")[:12] or None,
        })
    return out


def _age_days(iso: str | None) -> float | None:
    """Età in giorni con la parte frazionaria: i cataloghi cambiano più volte al giorno."""
    d = days_since(iso)
    return round(d, 4) if d is not None else None


def counts() -> dict:
    """I numeri grossi, quelli che si guardano per primi."""
    return {
        "target": _one("SELECT count(*) FROM target") or 0,
        "asteroidi": _one("SELECT count(*) FROM target WHERE kind='asteroid'") or 0,
        "comete": _one("SELECT count(*) FROM target WHERE kind='comet'") or 0,
        "orbite": _one("SELECT count(*) FROM orbit") or 0,
        "con_ceu": _one("SELECT count(*) FROM astorb_extra WHERE ceu_arcsec IS NOT NULL") or 0,
        "con_ultima_oss": _one("SELECT count(*) FROM orbit WHERE last_obs_date IS NOT NULL") or 0,
        "numerati": _one("SELECT count(*) FROM target WHERE number IS NOT NULL") or 0,
    }


# Le tre finestre di «da quando è comparso». Un giorno perché i sync girano
# ogni sei ore e una giornata è il passo con cui il catalogo cambia davvero;
# una settimana e un mese perché è la scala su cui l'MPC pubblica le nuove
# designazioni in blocco dopo le campagne di survey.
NEW_WINDOWS = [("ultime 24 ore", 1.0), ("ultimi 7 giorni", 7.0),
               ("ultimi 30 giorni", 30.0)]


def new_objects() -> dict:
    """Quanti oggetti sono **comparsi in catalogo** nelle tre finestre recenti.

    «Nuovo» qui vuol dire *la prima volta che l'abbiamo visto noi*, non la data
    di scoperta: `target.created_at` la scrive l'upsert al primo incontro e
    l'`ON CONFLICT DO UPDATE` non la tocca mai più, quindi sopravvive a tutti i
    reimport successivi. È l'unica data di primo avvistamento che abbiamo — nei
    cataloghi MPC/ASTORB non ce n'è una.

    E per questo esce anche `catalog_age_days`: `target` è **rigenerabile**
    (regola 1), quindi un database ricostruito da zero ha tutti i `created_at`
    al giorno del ripristino e direbbe «1,5 milioni di oggetti nuovi». Una
    finestra più lunga dell'archivio è marcata `parziale`, e la pagina lo dice
    invece di far passare un artefatto per una notizia astronomica. (Sul
    servizio vero è il caso di adesso: il database sta in un volume Docker dal
    17 agosto, e tutto ciò che contiene è «nuovo» da allora.)

    **La soglia si calcola in Python e si confronta come testo**, che è
    l'eccezione alla regola di CLAUDE.md sulle date in SQL — e vale la pena
    dire perché non è una violazione. La regola nasce dal confronto fra i nostri
    `2026-08-15T07:46:00Z` e i `2026-08-15 10:46:52` di `datetime('now')`, dove
    la `'T'` viene dopo lo spazio e ogni riga sembra recente. Qui entrambe le
    parti escono da `iso_from_jd`, cioè dalla stessa funzione che scrive la
    colonna: stesso formato, lunghezza fissa, ordine lessicografico uguale
    all'ordine cronologico. Ed è l'unica forma che l'indice sappia usare —
    `julianday(created_at)` è una funzione sulla colonna, e obbliga a leggere
    tutte e 1,5 milioni di righe (misurato: 1,37 s).
    """
    from core.timeutil import iso_from_jd, now_jd

    adesso = now_jd()
    estremi = _rows("SELECT min(created_at) AS primo, max(created_at) AS ultimo "
                    "FROM target")[0]
    eta = _age_days(estremi["primo"])
    out = []
    for label, giorni in NEW_WINDOWS:
        soglia = iso_from_jd(adesso - giorni)
        r = _rows(
            """SELECT count(*) AS n,
                      sum(kind = 'asteroid') AS asteroidi,
                      sum(kind = 'comet') AS comete
               FROM target WHERE created_at > ?""", (soglia,))[0]
        out.append({"fascia": label, "giorni": giorni, "n": r["n"] or 0,
                    "asteroidi": r["asteroidi"] or 0, "comete": r["comete"] or 0,
                    "parziale": eta is not None and eta < giorni})
    return {"windows": out, "catalog_age_days": eta,
            "last_new_days": _age_days(estremi["ultimo"])}


def tisserand_summary() -> dict:
    """La popolazione di punta, prima e dopo l'esclusione delle famiglie risonanti.

    Senza l'esclusione il 58% degli oggetti con Tj < 3 sono Troiani, Hilda e
    oggetti distanti: risonanti stabili, il contrario di quello che si cerca.
    """
    excluded = get_setting("aco_excluded_classes", list(config.ACO_EXCLUDED_CLASSES))
    placeholders = ",".join("?" * len(excluded)) or "''"
    return {
        "tj_lt_3": _one("SELECT count(*) FROM orbit WHERE tisserand_j < 3.0") or 0,
        "tj_lt_305": _one("SELECT count(*) FROM orbit WHERE tisserand_j < 3.05") or 0,
        # `kind='asteroid'`: un oggetto con Tj < 3 che è già una cometa non è un
        # "asteroide su orbita cometaria", è una cometa. Senza il filtro entravano
        # 740 comete nel conteggio della popolazione di punta.
        "aco": _one(
            f"""SELECT count(*) FROM orbit o JOIN target t ON t.id=o.target_id
                WHERE o.tisserand_j < 3.0 AND t.kind = 'asteroid'
                  AND (t.orbit_class IS NULL OR t.orbit_class NOT IN ({placeholders}))""",
            tuple(excluded),
        ) or 0,
        "escluse": excluded,
    }


def tisserand_by_class(limit: int = 12) -> list[dict]:
    return _rows(
        """SELECT t.orbit_class AS classe, count(*) AS n
           FROM orbit o JOIN target t ON t.id=o.target_id
           WHERE o.tisserand_j < 3.0 AND t.orbit_class IS NOT NULL
           GROUP BY t.orbit_class ORDER BY n DESC LIMIT ?""",
        (limit,),
    )


def orbit_class_histogram(limit: int = 15) -> list[dict]:
    return _rows(
        """SELECT COALESCE(orbit_class,'(non classificato)') AS classe, count(*) AS n
           FROM target GROUP BY classe ORDER BY n DESC LIMIT ?""",
        (limit,),
    )


CEU_BUCKETS = [
    ("< 1\"", 0, 1),
    ("1-10\"", 1, 10),
    ("10-60\"", 10, 60),
    ("1'-10'", 60, 600),
    ("10'-60'", 600, 3600),
    ("> 1°", 3600, None),
]


def ceu_histogram() -> list[dict]:
    """Distribuzione dell'incertezza: dice quanto vale davvero lo strato ASTORB.

    L'82% del catalogo ha CEU < 1" e non ne ha bisogno; serve nella fascia
    degli arcominuti, dove decide fra una posa e un mosaico.
    """
    out = []
    total = _one("SELECT count(*) FROM astorb_extra WHERE ceu_arcsec IS NOT NULL") or 0
    for label, lo, hi in CEU_BUCKETS:
        if hi is None:
            n = _one("SELECT count(*) FROM astorb_extra WHERE ceu_arcsec >= ?", (lo,))
        else:
            n = _one(
                "SELECT count(*) FROM astorb_extra WHERE ceu_arcsec >= ? AND ceu_arcsec < ?",
                (lo, hi),
            )
        n = n or 0
        out.append({
            "fascia": label,
            "n": n,
            "quota": round(100 * n / total, 2) if total else 0.0,
        })
    return out


LAST_OBS_BUCKETS = [
    ("ultimo anno", 0, 1),
    ("1-3 anni", 1, 3),
    ("3-10 anni", 3, 10),
    ("10-25 anni", 10, 25),
    ("oltre 25 anni", 25, None),
]


def last_obs_histogram() -> list[dict]:
    """Da quanto non si osservano. È l'asse della rarità, e ce l'ha solo l'MPC."""
    out = []
    for label, lo, hi in LAST_OBS_BUCKETS:
        upper = "" if hi is None else f"AND julianday('now') - julianday(last_obs_date) < {hi * 365.25}"
        n = _one(
            f"""SELECT count(*) FROM orbit WHERE last_obs_date IS NOT NULL
                AND julianday('now') - julianday(last_obs_date) >= {lo * 365.25} {upper}"""
        )
        out.append({"fascia": label, "n": n or 0})
    return out


def aco_preview(limit: int = 50) -> list[dict]:
    """Anteprima della popolazione di punta: Tj basso e non risonante.

    Ordinata per Tisserand crescente. Non è ancora una lista di osservazione —
    manca tutto il calcolo di visibilità — ma è ciò che il catalogo sa già dire.
    """
    excluded = get_setting("aco_excluded_classes", list(config.ACO_EXCLUDED_CLASSES))
    placeholders = ",".join("?" * len(excluded)) or "''"
    return _rows(
        f"""SELECT t.display_name AS oggetto, t.orbit_class AS classe,
                   round(o.tisserand_j, 3) AS tj, round(o.a_au, 3) AS a,
                   round(o.e, 3) AS e, round(o.i_deg, 1) AS i,
                   round(o.q_derived_au, 3) AS q, o.h_mag AS H,
                   o.last_obs_date AS ultima_oss, o.n_oppositions AS opp,
                   round(x.ceu_arcsec, 1) AS ceu
            FROM orbit o
            JOIN target t ON t.id = o.target_id
            LEFT JOIN astorb_extra x ON x.target_id = o.target_id
            WHERE o.tisserand_j < 3.0 AND t.kind = 'asteroid'
              AND (t.orbit_class IS NULL OR t.orbit_class NOT IN ({placeholders}))
            ORDER BY o.tisserand_j ASC LIMIT ?""",
        tuple(excluded) + (limit,),
    )


def recent_jobs(limit: int = 15) -> list[dict]:
    return _rows(
        """SELECT job_name, started_at, finished_at, status, n_processed,
                  round(duration_s,1) AS durata_s, error
           FROM job_run ORDER BY started_at DESC LIMIT ?""",
        (limit,),
    )
