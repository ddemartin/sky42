"""Il piano delle notti finisce nel database, e ci resta coerente."""
from __future__ import annotations

import textwrap

import pytest

from core.db import connect
from services import night_service, sites_service


@pytest.fixture()
def sito(db, tmp_path, monkeypatch):
    """Un sito attivo, dagli stessi YAML che usa il reconcile."""
    from core import config
    from tests.test_sites import SITO

    d = tmp_path / "sites"
    d.mkdir()
    (d / "cile.yml").write_text(textwrap.dedent(SITO), encoding="utf-8")
    monkeypatch.setattr(config, "SITES_DIR", d)
    sites_service.run_reconcile()


def _righe(sql: str = "SELECT * FROM night ORDER BY night_date") -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql).fetchall()]
    finally:
        conn.close()


def test_scrive_una_riga_per_notte(sito):
    out = night_service.plan_nights(5)
    assert out == {"siti": 1, "notti": 5}

    righe = _righe()
    assert len(righe) == 5
    prima = righe[0]
    assert prima["dark_hours"] > 0
    assert 0.0 <= prima["moon_illum"] <= 1.0
    assert prima["twilight_end_jd"] < prima["twilight_start_jd"]
    # Le date sono consecutive: se il piano saltasse un giorno, la dashboard
    # mostrerebbe un buco senza dire che è un buco.
    date = [r["night_date"] for r in righe]
    assert date == sorted(date) and len(set(date)) == 5


def test_e_idempotente(sito):
    night_service.plan_nights(3)
    prima = _righe()
    night_service.plan_nights(3)
    dopo = _righe()
    assert len(dopo) == 3
    assert [r["id"] for r in dopo] == [r["id"] for r in prima], "righe riscritte da capo"


def test_senza_siti_non_fa_niente(db):
    assert night_service.plan_nights(3) == {"siti": 0, "notti": 0}
    assert _righe() == []


def test_l_eta_del_piano_guida_il_recupero(sito):
    """`plan_age_hours` è ciò che dice al pianificatore se rifare il lavoro."""
    assert night_service.plan_age_hours() is None
    night_service.plan_nights(2)
    eta = night_service.plan_age_hours()
    assert eta is not None and eta < 0.1


def test_il_job_lascia_la_sua_riga(sito):
    night_service.run_night_plan(2)
    righe = _righe(
        "SELECT * FROM job_run WHERE job_name='night_plan' ORDER BY started_at DESC")
    assert righe and righe[0]["status"] == "ok"
    assert righe[0]["n_processed"] == 2


def test_upcoming_non_torna_il_passato(sito):
    night_service.plan_nights(4)
    righe = night_service.upcoming()
    assert len(righe) == 4
    assert righe[0]["site_code"] == "cile-test"
    assert righe[0]["timezone"] == "America/Santiago"


def test_un_sito_disattivato_esce_dal_piano(sito, tmp_path, monkeypatch):
    """Le notti si calcolano per i siti attivi: un sito chiuso non ne consuma."""
    from core import config
    from tests.test_sites import SITO

    night_service.plan_nights(2)
    (config.SITES_DIR / "cile.yml").write_text(
        textwrap.dedent(SITO).replace("code: cile-test", "code: cile-test\nactive: false"),
        encoding="utf-8",
    )
    sites_service.run_reconcile()
    assert night_service.plan_nights(2) == {"siti": 0, "notti": 0}
