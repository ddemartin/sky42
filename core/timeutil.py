"""Tempi. Unico posto in cui si converte fra UTC, Julian Date e date dei cataloghi.

Nel resto del codice esistono solo due forme:
  * JD (float) per i calcoli;
  * ISO-8601 UTC (str, con la Z) per le colonne testuali del database.

L'ora locale del sito compare **solo** in interfaccia.
"""
from __future__ import annotations

from datetime import date, datetime, timezone

# JD del 1970-01-01T00:00:00Z. Costante di conversione con il tempo Unix.
JD_UNIX_EPOCH = 2440587.5
SECONDS_PER_DAY = 86400.0


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def now_jd() -> float:
    return jd_from_datetime(datetime.now(timezone.utc))


def jd_from_datetime(dt: datetime) -> float:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return JD_UNIX_EPOCH + dt.timestamp() / SECONDS_PER_DAY


def datetime_from_jd(jd: float) -> datetime:
    return datetime.fromtimestamp((jd - JD_UNIX_EPOCH) * SECONDS_PER_DAY, tz=timezone.utc)


def iso_from_jd(jd: float) -> str:
    return datetime_from_jd(jd).strftime("%Y-%m-%dT%H:%M:%SZ")


def date_from_jd(jd: float) -> str:
    return datetime_from_jd(jd).strftime("%Y-%m-%d")


def jd_from_ymd(y: int, m: int, d: float) -> float:
    """JD alle 0h del giorno indicato (d può avere parte frazionaria).

    Algoritmo di Meeus, valido nel calendario gregoriano — cioè ovunque ci
    servano date di cataloghi moderni.
    """
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return int(365.25 * (y + 4716)) + int(30.6001 * (m + 1)) + d + b - 1524.5


def jd_from_yyyymmdd(s: str) -> float | None:
    """'20260917' -> JD alle 0h. Restituisce None su campo vuoto o malformato."""
    s = (s or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    return jd_from_ymd(int(s[:4]), int(s[4:6]), int(s[6:8]))


def iso_date_from_yyyymmdd(s: str) -> str | None:
    """'20260917' -> '2026-09-17'. None se il campo non è una data."""
    s = (s or "").strip()
    if len(s) != 8 or not s.isdigit():
        return None
    try:
        return date(int(s[:4]), int(s[4:6]), int(s[6:8])).isoformat()
    except ValueError:
        return None


def days_since(iso_ts: str | None) -> float | None:
    """Giorni trascorsi da un istante ISO, con la parte frazionaria.

    Non si passa da `years_between`, che lavora sulle date: i cataloghi si
    aggiornano più volte al giorno, e un'età troncata al giorno farebbe leggere
    "adesso" a qualcosa scaricato stamattina.
    """
    if not iso_ts:
        return None
    s = iso_ts.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - dt).total_seconds() / SECONDS_PER_DAY


def years_between(iso_a: str | None, iso_b: str | None = None) -> float | None:
    """Anni fra due date ISO ('YYYY-MM-DD'). iso_b None = oggi."""
    if not iso_a:
        return None
    try:
        a = date.fromisoformat(iso_a[:10])
    except ValueError:
        return None
    b = date.fromisoformat(iso_b[:10]) if iso_b else datetime.now(timezone.utc).date()
    return (b - a).days / 365.25
