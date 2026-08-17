"""Pianificatore, backup e manutenzione.

Il pianificatore vero non si avvia nei test: farebbe partire un pool di
processi e dei download. Si verifica ciò che si può sbagliare in silenzio — le
cadenze, l'attivazione persistente, il recupero dopo un riavvio — e i due
lavori che toccano i dati.
"""
from __future__ import annotations

import gzip
import json
from pathlib import Path

from core import config
from core.db import connect, get_setting
from services import backup_service, ingest_service, maintenance_service
from services.scheduler import Scheduler, _age_hours, _cron_label, _jobs, _source_of
from tests.test_parsers import MPCORB_SAMPLE


def _iso_fa(giorni: int = 0, ore: int = 0, minuti: int = 0) -> str:
    """Un timestamp passato **nel formato che scrive l'applicazione**.

    Non `datetime('now','-9 hours')` di SQLite: quello produce
    `2026-08-15 07:46:00`, noi scriviamo `2026-08-15T07:46:00Z`. Usare il
    formato di SQLite nei test faceva passare una query che in produzione
    sbagliava — il confronto fra stringhe mette 'T' dopo lo spazio, quindi
    nessuna riga dello stesso giorno risultava vecchia (MEMORANDUM 2026-08-15).
    """
    from datetime import datetime, timedelta, timezone

    t = datetime.now(timezone.utc) - timedelta(days=giorni, hours=ore, minutes=minuti)
    return t.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_ogni_lavoro_ha_una_cadenza(db):
    """Un lavoro senza trigger non gira mai, e non se ne accorge nessuno."""
    for spec in _jobs():
        assert spec.minutes or spec.hours or spec.cron, f"{spec.name} non ha cadenza"
        assert spec.label and spec.description
        trigger, kwargs = Scheduler._trigger(spec)
        assert trigger == "cron"
        assert "minute" in kwargs


def test_i_watcher_girano_a_minuti_e_sono_leggeri(db):
    """I watcher MPC sono l'unico lavoro che **perde dati** se non gira, e
    devono poter girare mentre lo screening macina: quindi a minuti, e non nel
    pool dei lavori pesanti, che ha un posto solo.

    `destiny_poll` è il terzo della famiglia: la tabella dei trksub usciti di
    lista tiene quattro giorni, e quel che passa non torna."""
    watcher = {s.name: s for s in _jobs() if s.name.endswith("_poll")}
    assert set(watcher) == {"neocp_poll", "pccp_poll", "destiny_poll"}
    for spec in watcher.values():
        assert spec.minutes and not spec.heavy
        assert spec.catchup_after_hours is not None, "al riavvio si recupera subito"
        _, kwargs = Scheduler._trigger(spec)
        assert kwargs["minute"] == f"*/{spec.minutes}"


def test_i_sync_sono_sfalsati(db):
    """Tre download nello stesso minuto sono tre download nello stesso minuto."""
    minuti = [s.minute for s in _jobs() if s.name.endswith("_sync")]
    assert len(minuti) == len(set(minuti))


def test_nome_lavoro_a_sorgente():
    assert _source_of("mpcorb_sync") == "mpcorb"
    assert _source_of("astorb_sync") == "astorb"
    assert _source_of("housekeeping") == "housekeeping"


def test_etichetta_cadenza():
    specs = {s.name: s for s in _jobs()}
    assert _cron_label(specs["backup"]).startswith("ogni giorno 03:")
    assert "domenica" in _cron_label(specs["housekeeping"])


def test_attivazione_persiste(db):
    """Sospendere un lavoro deve sopravvivere al riavvio: sta in `setting`."""
    s = Scheduler()
    s.specs = {spec.name: spec for spec in _jobs()}
    assert s.is_enabled("backup") is True
    s.set_enabled("backup", False)
    assert s.is_enabled("backup") is False
    assert get_setting("job_enabled")["backup"] is False
    s.set_enabled("backup", True)
    assert s.is_enabled("backup") is True


def test_eta_in_ore(db):
    assert _age_hours(None) is None
    assert _age_hours("2000-01-01T00:00:00Z") > 100_000


# --- backup -----------------------------------------------------------------


def test_backup_salva_solo_il_non_rigenerabile(db, tmp_path):
    """Il catalogo non entra nel backup: si riscarica dall'MPC."""
    mpc = tmp_path / "mpcorb.json.gz"
    with gzip.open(mpc, "wt", encoding="utf-8") as fh:
        json.dump(MPCORB_SAMPLE, fh, indent=1)
    ingest_service.sync_mpcorb(local_path=mpc)

    conn = connect()
    try:
        tid = conn.execute("SELECT id FROM target WHERE number=1").fetchone()[0]
        conn.execute(
            "INSERT INTO watchlist (target_id, priority, note, added_at) VALUES (?,?,?,?)",
            (tid, 3, "da recuperare", "2026-08-15T00:00:00Z"),
        )
        conn.execute(
            """INSERT INTO observation_log (target_id, obs_start, outcome)
               VALUES (?, '2026-08-15T02:00:00Z', 'detected')""", (tid,),
        )
    finally:
        conn.close()

    detail = backup_service.run_backup()
    path = backup_service.backup_dir() / detail["file"]
    assert path.exists()

    contenuto = backup_service.restore_counts(path)
    assert contenuto["watchlist"] == 1
    assert contenuto["observation_log"] == 1
    # 1,5 milioni di orbite non devono finire qui dentro
    assert "orbit" not in contenuto
    assert "target" not in contenuto


def test_backup_leggibile_da_solo(db):
    """Il file di backup si apre senza il database di origine.

    Con le chiavi esterne copiate dal DDL, ripristinare avrebbe richiesto prima
    di ricostruire tutto il catalogo — l'opposto di ciò che serve quando si sta
    recuperando.
    """
    backup_service.run_backup()
    copie = backup_service.list_backups()
    assert copie
    conteggi = backup_service.restore_counts(
        backup_service.backup_dir() / copie[0]["file"])
    assert set(backup_service.TABLES) <= set(conteggi)


def test_backup_pota_le_copie_vecchie(db):
    d = backup_service.backup_dir()
    for i in range(backup_service.KEEP_COPIES + 3):
        (d / f"sky42-dati-2020010{i % 10}-{i:04d}.db").write_bytes(b"x")
    backup_service.run_backup()
    assert len(list(d.glob("sky42-dati-*.db"))) <= backup_service.KEEP_COPIES


# --- manutenzione -----------------------------------------------------------


def test_manutenzione_pota_i_registri(db):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO job_run (job_name, started_at, status) VALUES ('vecchio',?,'ok')",
            (_iso_fa(giorni=200),),
        )
        conn.execute(
            "INSERT INTO job_run (job_name, started_at, status) VALUES ('recente',?,'ok')",
            (_iso_fa(giorni=2),),
        )
        conn.execute(
            "INSERT INTO external_call (service, called_at, status) VALUES ('horizons',?,200)",
            (_iso_fa(giorni=90),),
        )
    finally:
        conn.close()

    maintenance_service.run_housekeeping()

    conn = connect()
    try:
        nomi = {r[0] for r in conn.execute("SELECT job_name FROM job_run").fetchall()}
        assert "vecchio" not in nomi
        assert "recente" in nomi
        assert conn.execute("SELECT count(*) FROM external_call").fetchone()[0] == 0
    finally:
        conn.close()


def test_esecuzioni_appese_vengono_chiuse(db):
    """Un job ucciso resta 'running' e mentirebbe sulla pagina del pianificatore."""
    from core.db import close_orphaned_jobs

    conn = connect()
    try:
        conn.execute(
            "INSERT INTO job_run (job_name, started_at, status) VALUES ('morto',?,'running')",
            (_iso_fa(ore=9),),
        )
        # Uno appena partito: potrebbe essere davvero in corso, non si tocca.
        conn.execute(
            "INSERT INTO job_run (job_name, started_at, status) VALUES ('vivo',?,'running')",
            (_iso_fa(minuti=2),),
        )
    finally:
        conn.close()

    assert close_orphaned_jobs() == 1

    conn = connect()
    try:
        stati = dict(conn.execute(
            "SELECT job_name, status FROM job_run WHERE job_name IN ('morto','vivo')").fetchall())
        assert stati["morto"] == "failed"
        assert stati["vivo"] == "running"
    finally:
        conn.close()
