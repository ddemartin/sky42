"""Migrazioni e valori di partenza: quel che succede a un database già esistente.

Il database di casa è vecchio di settimane e sta a un gigabyte: le migrazioni
si provano qui, o si provano lì.
"""
from __future__ import annotations

from core.db import SCHEMA_VERSION, connect, init_db
from core.ranking.score import DEFAULT_WEIGHTS


def _colonne(conn, tabella: str) -> set[str]:
    return {r[1] for r in conn.execute(f"PRAGMA table_info({tabella})")}


def test_un_database_nuovo_nasce_alla_versione_corrente(db):
    conn = connect()
    try:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert {"pending_state", "pending_since", "pending_count"} <= \
            _colonne(conn, "target_state")
    finally:
        conn.close()


def test_la_migrazione_riporta_le_colonne_del_radar(db):
    """Si simula il database di prima del radar — versione 1, senza le colonne
    di conferma — e si verifica che `init_db` lo riallinei senza toccare altro."""
    conn = connect()
    try:
        conn.execute("INSERT INTO target (kind, primary_desig, display_name) "
                     "VALUES ('asteroid','1','(1) Ceres')")
        for c in ("pending_state", "pending_since", "pending_count"):
            conn.execute(f"ALTER TABLE target_state DROP COLUMN {c}")
        conn.execute("PRAGMA user_version=1")
    finally:
        conn.close()

    init_db()

    conn = connect()
    try:
        assert {"pending_state", "pending_since", "pending_count"} <= \
            _colonne(conn, "target_state")
        assert conn.execute("PRAGMA user_version").fetchone()[0] == SCHEMA_VERSION
        assert conn.execute("SELECT count(*) FROM target").fetchone()[0] == 1, \
            "una migrazione non distruttiva non tocca i dati"
    finally:
        conn.close()


def test_una_migrazione_interrotta_a_meta_non_blocca_l_avvio(db):
    """`user_version` si alza in fondo al gruppo: se la seconda `ALTER` fallisce,
    al riavvio si ripete la prima, e una colonna che c'è già non è un errore."""
    conn = connect()
    try:
        conn.execute("ALTER TABLE target_state DROP COLUMN pending_count")
        conn.execute("PRAGMA user_version=1")       # come se si fosse interrotta
    finally:
        conn.close()

    init_db()

    conn = connect()
    try:
        assert "pending_count" in _colonne(conn, "target_state")
    finally:
        conn.close()


def test_init_db_e_idempotente(db):
    init_db()
    init_db()
    conn = connect()
    try:
        assert conn.execute("SELECT count(*) FROM scoring_profile").fetchone()[0] == 1
    finally:
        conn.close()


def test_il_profilo_di_partenza_arriva_anche_ai_database_vecchi(db):
    """Chi ha un database creato prima del ranking non deve ricrearlo per
    avere un profilo: il seed gira a ogni avvio, con `INSERT OR IGNORE`."""
    import json

    conn = connect()
    try:
        conn.execute("DELETE FROM scoring_profile")
        conn.execute("PRAGMA user_version=1")
    finally:
        conn.close()

    init_db()

    conn = connect()
    try:
        row = conn.execute("SELECT * FROM scoring_profile").fetchone()
    finally:
        conn.close()
    assert row["name"] == "default" and row["active"] == 1
    assert json.loads(row["weights"]) == DEFAULT_WEIGHTS
    assert "grades" in json.loads(row["gates"])


def test_un_profilo_modificato_a_mano_non_viene_riscritto(db):
    import json

    conn = connect()
    try:
        conn.execute("UPDATE scoring_profile SET weights=? WHERE name='default'",
                     (json.dumps({"depth": 99.0}),))
    finally:
        conn.close()

    init_db()

    conn = connect()
    try:
        pesi = json.loads(conn.execute(
            "SELECT weights FROM scoring_profile WHERE name='default'").fetchone()[0])
    finally:
        conn.close()
    assert pesi == {"depth": 99.0}, "la taratura è dell'utente, non del codice"


def test_il_database_puo_stare_fuori_da_data_dir(tmp_path, monkeypatch):
    """In container il database vive in un volume Docker e **non** sul bind
    mount: la WAL di SQLite non regge virtiofs (memorandum 17 agosto). Il
    percorso è quindi indipendente da `DATA_DIR`, e `ensure_dirs` deve creare
    la sua cartella — al primo avvio su un volume vuoto non esiste ancora.
    """
    import importlib

    altrove = tmp_path / "volume" / "sky42.db"
    monkeypatch.setenv("SKY42_DATA_DIR", str(tmp_path / "dati"))
    monkeypatch.setenv("SKY42_DB_PATH", str(altrove))

    from core import config as config_modulo

    config = importlib.reload(config_modulo)
    try:
        assert config.DB_PATH == altrove.resolve()
        assert config.CATALOG_DIR.parent == config.DATA_DIR, "i download restano lì"
        assert not altrove.parent.exists()
        config.ensure_dirs()
        assert altrove.parent.is_dir(), "la cartella del database va creata"
    finally:
        # Il modulo è globale: lasciarlo puntato alla cartella di prova
        # farebbe fallire i test successivi in un modo difficile da capire.
        monkeypatch.undo()
        importlib.reload(config_modulo)


def test_senza_variabile_il_database_resta_in_data_dir():
    """Il default è quello che serve al venv di sviluppo e ai test."""
    from core import config

    assert config.DB_PATH == (config.DATA_DIR / "sky42.db").resolve()
