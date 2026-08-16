"""Import dei cataloghi nel database locale.

Gerarchia delle fonti (MEMORANDUM 2026-08-15):

    mpcorb_extended.json.gz   fonte: identità, elementi, classe, Last_obs
    astorb.dat.gz             strato: CEU/PEU in arcsec, dati fisici IRAS
    CometEls.txt              comete (in MPCORB non ci sono)

Due regole che valgono per tutti e tre gli import:

  * **`target` non si sostituisce mai, si aggiorna.** `INSERT OR REPLACE`
    cancellerebbe la riga e con lei, a cascata, la storia collegata:
    osservazioni, transizioni di stato, watchlist. Si usa
    `ON CONFLICT DO UPDATE`, sempre. Su `orbit` invece REPLACE va bene, perché
    nessuno dipende da quella riga.
  * **Si lavora a blocchi**, con una transazione per blocco: l'import resta
    interrompibile e non tiene il database occupato per minuti.
"""
from __future__ import annotations

import logging
from pathlib import Path

from core import config
from core.db import connect, transaction
from core.ingest import astorb, cometels, http, mpcorb
from core.orbits.elements import tisserand_scalar
from core.timeutil import now_iso
from services.jobs import be_nice, chunked, run_job, wait_if_busy

log = logging.getLogger("sky42.ingest")

# --- colonne scritte, dichiarate una volta sola -----------------------------

ORBIT_COLS = [
    "source", "epoch_jd", "a_au", "q_au", "e", "i_deg", "node_deg", "argp_deg",
    "m_deg", "tp_jd", "n_deg_day", "h_mag", "g_slope", "m1", "k1",
    "arc_days", "arc_years", "n_obs", "n_oppositions", "first_obs_date",
    "last_obs_date", "rms_arcsec", "u_param", "hex_flags", "computer",
    "reference", "computed_date", "q_derived_au", "aphelion_au", "period_yr",
    "tisserand_j", "updated_at",
]

ASTORB_COLS = [
    "ceu_arcsec", "ceu_rate", "ceu_date", "peu_arcsec", "peu_date",
    "peu10_arcsec", "peu10_date", "bv_color", "diameter_km", "taxon_class",
    "astorb_epoch_jd", "astorb_a_au", "astorb_e", "astorb_i_deg",
    "arc_days", "n_obs", "computed_date", "updated_at",
]

SQL_TARGET_UPSERT = """
INSERT INTO target (kind, primary_desig, number, name, display_name, orbit_class,
                    created_at, updated_at)
VALUES (?,?,?,?,?,?,?,?)
ON CONFLICT(primary_desig) DO UPDATE SET
    number       = excluded.number,
    name         = excluded.name,
    display_name = excluded.display_name,
    orbit_class  = excluded.orbit_class,
    updated_at   = excluded.updated_at
"""

# INSERT ... SELECT FROM target WHERE: se il target non c'è, non si inserisce
# niente. È il modo di scartare in silenzio le righe orfane senza dover
# tenere in memoria una mappa da un milione e mezzo di chiavi.
SQL_ORBIT_UPSERT = (
    f"INSERT OR REPLACE INTO orbit (target_id, {', '.join(ORBIT_COLS)}) "
    f"SELECT t.id, {', '.join('?' * len(ORBIT_COLS))} "
    f"FROM target t WHERE t.primary_desig = ?"
)

# `kind='asteroid'` non è una precauzione teorica: la numerazione delle comete
# periodiche è un'altra numerazione, e 1P/Halley ha `number = 1` esattamente
# come (1) Ceres. Senza il filtro, la CEU di Ceres finiva anche su Halley —
# trovato contando gli agganci, che erano 461 più del previsto.
SQL_ASTORB_BY_NUMBER = (
    f"INSERT OR REPLACE INTO astorb_extra (target_id, {', '.join(ASTORB_COLS)}) "
    f"SELECT t.id, {', '.join('?' * len(ASTORB_COLS))} "
    f"FROM target t WHERE t.number = ? AND t.kind = 'asteroid'"
)

SQL_ASTORB_BY_DESIG = (
    f"INSERT OR REPLACE INTO astorb_extra (target_id, {', '.join(ASTORB_COLS)}) "
    f"SELECT t.id, {', '.join('?' * len(ASTORB_COLS))} "
    f"FROM target t WHERE t.primary_desig = ? AND t.number IS NULL AND t.kind = 'asteroid'"
)


# --- MPCORB -----------------------------------------------------------------


def sync_mpcorb(force: bool = False, local_path: Path | None = None) -> dict:
    """Scarica e importa mpcorb_extended. Salta l'import se il file non è cambiato."""
    with run_job("mpcorb_sync") as ctx:
        be_nice()
        if local_path is None:
            dl = http.fetch("mpcorb", config.MPCORB_URL, "mpcorb_extended.json.gz", force)
            if not dl.changed and not force:
                ctx.cancelled = True
                ctx.detail = {"motivo": "sorgente non modificata"}
                return ctx.detail
            path, version_id = dl.path, dl.version_id
        else:
            path, version_id = Path(local_path), None

        stats = _import_mpcorb(path)
        http.mark_imported(version_id, stats["importati"])
        ctx.n_processed = stats["importati"]
        ctx.detail = stats
        return stats


def _import_mpcorb(path: Path) -> dict:
    now = now_iso()
    imported = skipped = 0

    conn = connect()
    try:
        for batch in chunked(mpcorb.iter_records(path)):
            wait_if_busy()
            targets, orbits = [], []
            for r in batch:
                if not _elements_complete(r):
                    skipped += 1
                    continue
                targets.append((
                    "asteroid", r["primary_desig"], r["number"], r["name"],
                    r["display_name"], r["orbit_class"], now, now,
                ))
                orbits.append(_orbit_row(r, source="mpcorb", now=now))
            with transaction(conn):
                conn.executemany(SQL_TARGET_UPSERT, targets)
                conn.executemany(SQL_ORBIT_UPSERT, orbits)
            imported += len(targets)
            if imported % 200_000 < config.CHUNK_SIZE:
                log.info("mpcorb: %d oggetti", imported)

        # ANALYZE non è manutenzione rimandabile: senza statistiche il planner
        # sceglie l'indice sbagliato per le ricerche per numero, e l'aggancio di
        # ASTORB passa da 14 secondi a più di un'ora (MEMORANDUM 2026-08-15).
        log.info("mpcorb: ANALYZE")
        conn.execute("ANALYZE")
    finally:
        conn.close()

    return {"importati": imported, "scartati": skipped, "file": path.name}


def _elements_complete(r: dict) -> bool:
    """Le colonne NOT NULL di `orbit` devono esserci tutte.

    Un'orbita senza inclinazione o senza nodo non è propagabile: tenerla
    significa solo far fallire un calcolo più in là, dove sarà più difficile
    capire da dove veniva.
    """
    return all(r.get(k) is not None for k in ("e", "i_deg", "node_deg", "argp_deg"))


def _orbit_row(r: dict, source: str, now: str) -> tuple:
    """Riga di `orbit` nell'ordine di ORBIT_COLS, più la chiave di aggancio in coda."""
    a, e, i = r.get("a_au"), r.get("e"), r.get("i_deg")
    return (
        source, r.get("epoch_jd"), a, r.get("q_au"), e, i,
        r.get("node_deg"), r.get("argp_deg"), r.get("m_deg"), r.get("tp_jd"),
        r.get("n_deg_day"), r.get("h_mag"), r.get("g_slope"),
        r.get("m1"), r.get("k1"),
        r.get("arc_days"), r.get("arc_years"), r.get("n_obs"),
        r.get("n_oppositions"), r.get("first_obs_date"), r.get("last_obs_date"),
        r.get("rms_arcsec"), r.get("u_param"), r.get("hex_flags"),
        r.get("computer"), r.get("reference"), r.get("computed_date"),
        r.get("q_au") if r.get("q_au") is not None else _q(a, e),
        r.get("aphelion_au") if r.get("aphelion_au") is not None else _Q(a, e),
        r.get("period_yr"),
        tisserand_scalar(a, e, i),
        now,
        r["primary_desig"],
    )


def _q(a, e):
    return a * (1 - e) if (a and e is not None and 0 <= e < 1) else None


def _Q(a, e):
    return a * (1 + e) if (a and e is not None and 0 <= e < 1) else None


# --- ASTORB -----------------------------------------------------------------


def sync_astorb(force: bool = False, local_path: Path | None = None) -> dict:
    """Scarica e importa lo strato ASTORB (CEU e dati fisici).

    Gli oggetti che ASTORB ha e l'MPC no (~800 orbite perse da decenni) non
    creano `target`: la fonte dell'identità è una sola. Si contano e si
    riportano, così se il numero cresce ce ne accorgiamo.
    """
    with run_job("astorb_sync") as ctx:
        be_nice()
        if local_path is None:
            dl = http.fetch("astorb", config.ASTORB_URL, "astorb.dat.gz", force)
            if not dl.changed and not force:
                ctx.cancelled = True
                ctx.detail = {"motivo": "sorgente non modificata"}
                return ctx.detail
            path, version_id = dl.path, dl.version_id
        else:
            path, version_id = Path(local_path), None

        stats = _import_astorb(path)
        http.mark_imported(version_id, stats["agganciati"])
        ctx.n_processed = stats["agganciati"]
        ctx.detail = stats
        return stats


def _import_astorb(path: Path) -> dict:
    now = now_iso()
    letti = 0

    conn = connect()
    try:
        before = conn.total_changes
        for batch in chunked(astorb.iter_records(path)):
            wait_if_busy()
            by_number, by_desig = [], []
            for r in batch:
                row = (
                    r["ceu_arcsec"], r["ceu_rate"], r["ceu_date"],
                    r["peu_arcsec"], r["peu_date"], r["peu10_arcsec"], r["peu10_date"],
                    r["bv_color"], r["diameter_km"], r["taxon_class"],
                    r["astorb_epoch_jd"], r["astorb_a_au"], r["astorb_e"],
                    r["astorb_i_deg"], r["arc_days"], r["n_obs"],
                    r["computed_date"], now,
                )
                if r["is_numbered"]:
                    by_number.append(row + (r["number"],))
                elif r["designation"]:
                    by_desig.append(row + (r["designation"],))
            with transaction(conn):
                conn.executemany(SQL_ASTORB_BY_NUMBER, by_number)
                conn.executemany(SQL_ASTORB_BY_DESIG, by_desig)
            letti += len(batch)
        agganciati = conn.total_changes - before
    finally:
        conn.close()

    return {
        "letti": letti,
        "agganciati": agganciati,
        "senza_corrispondenza": letti - agganciati,
        "file": path.name,
    }


# --- comete -----------------------------------------------------------------


def sync_cometels(force: bool = False, local_path: Path | None = None) -> dict:
    with run_job("cometels_sync") as ctx:
        be_nice()
        if local_path is None:
            dl = http.fetch("cometels", config.COMETELS_URL, "CometEls.txt", force)
            if not dl.changed and not force:
                ctx.cancelled = True
                ctx.detail = {"motivo": "sorgente non modificata"}
                return ctx.detail
            path, version_id = dl.path, dl.version_id
        else:
            path, version_id = Path(local_path), None

        stats = _import_cometels(path)
        http.mark_imported(version_id, stats["importate"])
        ctx.n_processed = stats["importate"]
        ctx.detail = stats
        return stats


def _import_cometels(path: Path) -> dict:
    now = now_iso()
    imported = 0
    conn = connect()
    try:
        for batch in chunked(cometels.iter_records(path), size=2000):
            targets, orbits = [], []
            for r in batch:
                if r["i_deg"] is None or r["node_deg"] is None or r["argp_deg"] is None:
                    continue
                targets.append((
                    "comet", r["primary_desig"], r["number"], None,
                    r["display_name"], _comet_class(r), now, now,
                ))
                # Le comete non hanno né `a` né anomalia media: hanno q e Tp.
                # `a` si ricava solo per le ellittiche; per le iperboliche resta
                # NULL, ed è giusto che sia così.
                a = r["q_au"] / (1 - r["e"]) if r["e"] < 1 else None
                orbits.append((
                    "cometels", r["epoch_jd"], a, r["q_au"], r["e"], r["i_deg"],
                    r["node_deg"], r["argp_deg"], None, r["tp_jd"], None,
                    None, None, r["m1"], r["k1"],
                    None, None, None, None, None, None, None, None, None,
                    None, r["reference"], None,
                    r["q_au"], (a * (1 + r["e"]) if a else None),
                    (a ** 1.5 if a else None),
                    tisserand_scalar(a, r["e"], r["i_deg"]),
                    now, r["primary_desig"],
                ))
            with transaction(conn):
                conn.executemany(SQL_TARGET_UPSERT, targets)
                conn.executemany(SQL_ORBIT_UPSERT, orbits)
            imported += len(targets)
    finally:
        conn.close()
    return {"importate": imported, "file": path.name}


def _comet_class(r: dict) -> str:
    """Classe leggibile dal codice di tipo dell'MPC."""
    return {
        "C": "Comet (long period)",
        "P": "Comet (periodic)",
        "D": "Comet (lost)",
        "X": "Comet (no orbit)",
        "I": "Interstellar",
    }.get(r.get("orbit_type_code") or "", "Comet")


# --- tutto insieme ----------------------------------------------------------


def sync_all(force: bool = False) -> dict:
    """L'ordine conta: l'MPC crea i target, ASTORB ci si aggancia sopra."""
    return {
        "mpcorb": sync_mpcorb(force=force),
        "cometels": sync_cometels(force=force),
        "astorb": sync_astorb(force=force),
    }
