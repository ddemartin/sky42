"""Lettura di `astorb.dat` — lo strato dell'incertezza.

ASTORB **non** è la fonte degli elementi (lo è l'MPC): serve per la CEU, cioè
l'incertezza dell'effemeride in secondi d'arco, che l'MPC non pubblica.
Vedi MEMORANDUM 2026-08-15.

Le colonne stanno in una tabella dichiarativa e non in slice sparsi nel codice,
perché il formato è vecchio, a larghezza fissa, e l'unico modo di accorgersi
che è cambiato è avere un solo posto da guardare.

Riferimento: il FORTRAN pubblicato da Lowell (revisione 2018/01/02)

    A6,1X,A18,1X,A15,1X,A5,1X,F5.2,1X,A4,1X,A5,1X,A4,
    1X,6I4,1X,2I5,1X,I4,2I2.2,1X,2(F10.6,1X),F10.6,F10.6,1X,F10.8,
    1X,F12.8,1X,I4,2I2.2,1X,F7.2,1X,F8.2,1X,I4,2I2,3(1X,F7.2,1X,I4,2I2)

Gli offset qui sotto sono 0-based ed esclusivi (pronti per uno slice Python),
verificati sul file vero il 2026-08-15 su (1) Ceres e su record non numerati.
"""
from __future__ import annotations

import gzip
import logging
from pathlib import Path
from typing import Iterator

from core.timeutil import iso_date_from_yyyymmdd, jd_from_yyyymmdd

log = logging.getLogger("sky42.ingest.astorb")

RECORD_LENGTH = 267     # righe più corte = file troncato o formato cambiato

COLUMNS: dict[str, tuple[int, int]] = {
    "number":     (0, 6),        # (1)  vuoto se non numerato
    "name":       (7, 25),       # (2)  nome se numerato, designazione altrimenti
    "computer":   (26, 41),      # (3)
    "h_mag":      (42, 47),      # (4)  precisione variabile: '3.34', '17', '12.0'
    "g_slope":    (48, 53),      # (5)
    "bv_color":   (54, 58),      # (6)
    "diameter":   (59, 64),      # (7)  IRAS, km
    "taxon":      (65, 69),      # (8)  IRAS
    "codes":      (70, 94),      # (9)  sei interi; la doc li dichiara inaffidabili
    "arc_days":   (95, 100),     # (10)
    "n_obs":      (100, 105),    # (11)
    "epoch":      (106, 114),    # (12) yyyymmdd TDT
    "m_deg":      (115, 125),    # (13)
    "argp_deg":   (126, 136),    # (14)
    "node_deg":   (137, 147),    # (15)
    "i_deg":      (147, 157),    # (16)
    "e":          (158, 168),    # (17)
    "a_au":       (169, 181),    # (18)
    "comp_date":  (182, 190),    # (19)
    "ceu":        (191, 198),    # (20) arcsec
    "ceu_rate":   (199, 207),    # (21) arcsec/giorno
    "ceu_date":   (208, 216),    # (22)
    "peu":        (217, 224),    # (23) prossimo picco
    "peu_date":   (225, 233),
    "peu10":      (234, 241),    # (24) massimo nei 10 anni dalla data CEU
    "peu10_date": (242, 250),
}


def parse_line(line: str) -> dict | None:
    """Un record ASTORB. None se la riga è troppo corta per essere valida."""
    if len(line.rstrip("\n\r")) < 250:
        return None
    raw = {k: line[a:b].strip() for k, (a, b) in COLUMNS.items()}

    number = int(raw["number"]) if raw["number"].isdigit() else None
    designation = raw["name"] or None

    return {
        # chiavi di aggancio all'MPC: numero se numerato, designazione altrimenti.
        # Verificato: combaciano senza normalizzare (895.910 numerati, 0 scarti).
        "number": number,
        "designation": designation,
        "is_numbered": number is not None,
        # ciò per cui teniamo ASTORB
        "ceu_arcsec": _f(raw["ceu"]),
        "ceu_rate": _f(raw["ceu_rate"]),
        "ceu_date": iso_date_from_yyyymmdd(raw["ceu_date"]),
        "peu_arcsec": _f(raw["peu"]),
        "peu_date": iso_date_from_yyyymmdd(raw["peu_date"]),
        "peu10_arcsec": _f(raw["peu10"]),
        "peu10_date": iso_date_from_yyyymmdd(raw["peu10_date"]),
        # dati fisici: pochi e spesso vuoti, ma non li ha nessun altro file
        "bv_color": _f(raw["bv_color"]),
        "diameter_km": _f(raw["diameter"]),
        "taxon_class": raw["taxon"] or None,
        # elementi ASTORB: si conservano per confronto, non per propagare
        "astorb_epoch_jd": jd_from_yyyymmdd(raw["epoch"]),
        "astorb_a_au": _f(raw["a_au"]),
        "astorb_e": _f(raw["e"]),
        "astorb_i_deg": _f(raw["i_deg"]),
        "arc_days": _f(raw["arc_days"]),
        "n_obs": _i(raw["n_obs"]),
        "h_mag": _f(raw["h_mag"]),
        "computed_date": iso_date_from_yyyymmdd(raw["comp_date"]),
    }


def iter_records(path: Path) -> Iterator[dict]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fp:
        for line in fp:
            rec = parse_line(line)
            if rec is not None:
                yield rec


def _f(s: str):
    if not s:
        return None
    try:
        return float(s)
    except ValueError:
        return None


def _i(s: str):
    if not s:
        return None
    try:
        return int(s)
    except ValueError:
        return None
