"""Lettura di `CometEls.txt` — le comete, che in MPCORB non ci sono.

Formato a colonne fisse dell'MPC. Gli offset sono 0-based ed esclusivi,
verificati sul file vero il 2026-08-15: l'epoca sta una colonna più a destra di
come la riporta la descrizione pubblicata, e su questo si sbaglia in silenzio.

Le comete non hanno `a` e `M`: hanno `q` e il tempo del passaggio al perielio.
Per le iperboliche (2I/Borisov, e = 3.35) `a` non esiste proprio, e resta NULL.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Iterator

from core.timeutil import jd_from_ymd

log = logging.getLogger("sky42.ingest.cometels")

COLUMNS: dict[str, tuple[int, int]] = {
    "number":     (0, 4),        # numero di cometa periodica
    "orbit_type": (4, 5),        # C / P / D / X / I (interstellare)
    "packed":     (5, 12),
    "tp_year":    (14, 18),
    "tp_month":   (19, 21),
    "tp_day":     (22, 29),      # con decimali
    "q_au":       (30, 39),
    "e":          (40, 49),
    "argp_deg":   (50, 59),
    "node_deg":   (60, 69),
    "i_deg":      (70, 79),
    "ep_year":    (81, 85),      # epoca della soluzione perturbata
    "ep_month":   (85, 87),
    "ep_day":     (87, 89),
    "m1":         (91, 95),      # magnitudine totale
    "k1":         (96, 100),     # parametro di pendenza
    "name":       (102, 158),    # '1P/Halley', 'C/1995 O1 (Hale-Bopp)'
    "reference":  (159, 168),
}


def parse_line(line: str) -> dict | None:
    if len(line.rstrip("\n\r")) < 100:
        return None
    raw = {k: line[a:b].strip() for k, (a, b) in COLUMNS.items()}

    name = raw["name"] or None
    if not name:
        return None

    q = _f(raw["q_au"])
    e = _f(raw["e"])
    if q is None or e is None:
        return None

    tp_jd = None
    if raw["tp_year"] and raw["tp_month"] and raw["tp_day"]:
        tp_jd = jd_from_ymd(int(raw["tp_year"]), int(raw["tp_month"]), _f(raw["tp_day"]))

    epoch_jd = None
    if raw["ep_year"].isdigit() and raw["ep_month"].isdigit() and raw["ep_day"].isdigit():
        epoch_jd = jd_from_ymd(int(raw["ep_year"]), int(raw["ep_month"]), int(raw["ep_day"]))

    # La designazione principale è il nome fino alla parentesi: '1P/Halley' da
    # '1P/Halley', 'C/1995 O1' da 'C/1995 O1 (Hale-Bopp)'.
    primary = name.split("(")[0].strip()

    return {
        "number": int(raw["number"]) if raw["number"].isdigit() else None,
        "orbit_type_code": raw["orbit_type"] or None,
        "packed_desig": raw["packed"] or None,
        "primary_desig": primary,
        "display_name": name,
        "q_au": q,
        "e": e,
        "i_deg": _f(raw["i_deg"]),
        "node_deg": _f(raw["node_deg"]),
        "argp_deg": _f(raw["argp_deg"]),
        "tp_jd": tp_jd,
        "epoch_jd": epoch_jd or tp_jd,   # le non perturbate non hanno epoca propria
        "m1": _f(raw["m1"]),
        "k1": _f(raw["k1"]),
        "reference": raw["reference"] or None,
    }


def iter_records(path: Path) -> Iterator[dict]:
    with open(path, "rt", encoding="utf-8", errors="replace") as fp:
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
