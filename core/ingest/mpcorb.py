"""Lettura di `mpcorb_extended.json.gz` — la fonte principale del catalogo.

Si usa il JSON e non MPCORB.DAT: niente designazioni ed epoche impacchettate da
decodificare, e in più `Orbit_type`, `Tp`, `Other_desigs`, `Last_obs`.
Vedi MEMORANDUM 2026-08-15.

Il file è un array JSON da ~1,5 GB decompresso: si legge in streaming con
`raw_decode` su un buffer scorrevole, senza mai tenerlo tutto in memoria e
senza dipendere dal fatto che sia indentato (oggi lo è, domani chissà).
"""
from __future__ import annotations

import gzip
import json
import logging
import re
from pathlib import Path
from typing import Iterator

log = logging.getLogger("sky42.ingest.mpcorb")

_NUM_RE = re.compile(r"\((\d+)\)")
_DAYS_RE = re.compile(r"^\s*(\d+)\s*days?\s*$", re.I)
_YEARS_RE = re.compile(r"^\s*(\d{4})\s*-\s*(\d{4})\s*$")


def iter_json_array(fp, bufsize: int = 1 << 20) -> Iterator[dict]:
    """Genera gli oggetti di un array JSON letto a pezzi.

    Non è un parser JSON scritto a mano: usa `JSONDecoder.raw_decode`, che è
    quello della libreria standard, su un buffer che cresce solo quando un
    record è incompleto.
    """
    dec = json.JSONDecoder()
    buf = ""
    started = False

    while True:
        buf = buf.lstrip(" \t\r\n")
        if not started:
            if not buf:
                chunk = fp.read(bufsize)
                if not chunk:
                    return
                buf += chunk
                continue
            if buf[0] == "[":
                buf = buf[1:]
                started = True
                continue
            raise ValueError("il file non comincia con un array JSON")

        if buf.startswith(","):
            buf = buf[1:]
            continue
        if buf.startswith("]"):
            return
        if not buf:
            chunk = fp.read(bufsize)
            if not chunk:
                return
            buf += chunk
            continue

        try:
            obj, idx = dec.raw_decode(buf)
        except ValueError:
            chunk = fp.read(bufsize)
            if not chunk:
                return          # coda troncata: meglio fermarsi che inventare
            buf += chunk
            continue

        yield obj
        buf = buf[idx:]


def iter_records(path: Path) -> Iterator[dict]:
    """Record normalizzati, pronti per il database."""
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rt", encoding="utf-8", errors="replace") as fp:
        for raw in iter_json_array(fp):
            rec = normalize(raw)
            if rec is not None:
                yield rec


def normalize(r: dict) -> dict | None:
    """Da record MPC a dizionario con i nomi delle colonne di sky42.

    Restituisce None per i record senza elementi utilizzabili: un'orbita senza
    `a` o senza `e` non è propagabile, e tenerla significherebbe solo far
    fallire un calcolo più avanti.
    """
    a = _f(r.get("a"))
    e = _f(r.get("e"))
    if a is None or e is None:
        return None

    number = None
    if r.get("Number"):
        m = _NUM_RE.search(str(r["Number"]))
        if m:
            number = int(m.group(1))

    principal = (r.get("Principal_desig") or "").strip() or None
    name = (r.get("Name") or "").strip() or None

    # Identità: la designazione principale è la chiave stabile. Il nome cambia
    # (un oggetto viene battezzato), il numero arriva dopo, la designazione no.
    primary = principal or name or (f"({number})" if number else None)
    if not primary:
        return None

    if number and name:
        display = f"({number}) {name}"
    elif number:
        display = f"({number}) {primary}"
    else:
        display = primary

    arc_days, first_obs = _arc(r)

    return {
        "number": number,
        "primary_desig": primary,
        "name": name,
        "display_name": display,
        "orbit_class": (r.get("Orbit_type") or "").strip() or None,
        "other_desigs": r.get("Other_desigs") or [],
        # elementi
        "epoch_jd": _f(r.get("Epoch")),
        "a_au": a,
        "e": e,
        "i_deg": _f(r.get("i")),
        "node_deg": _f(r.get("Node")),
        "argp_deg": _f(r.get("Peri")),
        "m_deg": _f(r.get("M")),
        "n_deg_day": _f(r.get("n")),
        "tp_jd": _f(r.get("Tp")),
        "q_au": _f(r.get("Perihelion_dist")),
        "aphelion_au": _f(r.get("Aphelion_dist")),
        "period_yr": _f(r.get("Orbital_period")),
        # fotometria
        "h_mag": _f(r.get("H")),
        "g_slope": _f(r.get("G")),
        # qualità
        "arc_days": arc_days,
        "arc_years": (r.get("Arc_years") or "").strip() or None,
        "first_obs_date": first_obs,
        "last_obs_date": _date(r.get("Last_obs")),
        "n_obs": _i(r.get("Num_obs")),
        "n_oppositions": _i(r.get("Num_opps")),
        "rms_arcsec": _f(r.get("rms")),
        "u_param": _f(r.get("U")),        # può essere 'E'/'D': diventa None
        "hex_flags": (r.get("Hex_flags") or "").strip() or None,
        "computer": (r.get("Computer") or "").strip() or None,
        "reference": (r.get("Ref") or "").strip() or None,
    }


def _arc(r: dict) -> tuple[float | None, str | None]:
    """Arco osservativo in giorni e data della prima osservazione, se ricavabili.

    L'MPC lo pubblica in due forme: '1801-2026' per gli oggetti a più
    opposizioni e '23 days' per quelli appena scoperti.
    """
    for key in ("Arc_years", "Arc_length"):
        v = r.get(key)
        if v is None:
            continue
        s = str(v).strip()
        m = _DAYS_RE.match(s)
        if m:
            return float(m.group(1)), None
        m = _YEARS_RE.match(s)
        if m:
            y0, y1 = int(m.group(1)), int(m.group(2))
            return (y1 - y0) * 365.25, f"{y0}-01-01"
        if s.replace(".", "", 1).isdigit():      # Arc_length numerico = giorni
            return float(s), None
    return None, None


def _f(v):
    if v is None or v == "":
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _i(v):
    f = _f(v)
    return int(f) if f is not None else None


def _date(v):
    """'2026-01-03' o '20260103' -> 'YYYY-MM-DD'."""
    if not v:
        return None
    s = str(v).strip()
    if len(s) == 8 and s.isdigit():
        return f"{s[:4]}-{s[4:6]}-{s[6:8]}"
    return s[:10] if len(s) >= 10 else None
