"""Conversioni di tempo, con i valori attesi presi da fonti indipendenti."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from core import timeutil as tu


def test_jd_epoca_unix():
    """JD del 1970-01-01T00:00Z: costante nota."""
    assert abs(tu.jd_from_datetime(datetime(1970, 1, 1, tzinfo=timezone.utc)) - 2440587.5) < 1e-9


def test_jd_epoca_mpcorb():
    """L'epoca di MPCORB del 2026-08-15 è JD 2461200.5 = 2026-06-09."""
    assert tu.date_from_jd(2461200.5) == "2026-06-09"
    assert abs(tu.jd_from_ymd(2026, 6, 9) - 2461200.5) < 1e-9


def test_jd_da_yyyymmdd_dei_cataloghi():
    """ASTORB scrive l'epoca come '20260917'."""
    assert abs(tu.jd_from_yyyymmdd("20260917") - tu.jd_from_ymd(2026, 9, 17)) < 1e-9
    assert tu.iso_date_from_yyyymmdd("20260917") == "2026-09-17"
    assert tu.jd_from_yyyymmdd("") is None
    assert tu.iso_date_from_yyyymmdd("0") is None
    assert tu.iso_date_from_yyyymmdd("20261332") is None      # mese 13: non è una data


def test_andata_e_ritorno():
    jd = tu.now_jd()
    assert abs(tu.jd_from_datetime(tu.datetime_from_jd(jd)) - jd) < 1e-9


def test_days_since_ha_la_parte_frazionaria():
    """Regressione: l'età si calcolava sulla sola data.

    Un catalogo scaricato stamattina risultava vecchio zero giorni e
    l'interfaccia diceva "adesso" — proprio quando serviva sapere che erano
    passate delle ore. I cataloghi cambiano più volte al giorno.
    """
    tre_ore_fa = datetime.now(timezone.utc) - timedelta(hours=3)
    d = tu.days_since(tre_ore_fa.strftime("%Y-%m-%dT%H:%M:%SZ"))
    assert 0.11 < d < 0.14                    # 3 ore = 0.125 giorni
    assert tu.days_since(None) is None
    assert tu.days_since("non una data") is None
