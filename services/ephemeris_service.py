"""Effemeridi per un oggetto del catalogo: la prima cosa che il positioner sa dire.

Legge target + orbita dal database, chiama `core.orbits.positioner` e
restituisce righe pronte da mostrare. Nessun calcolo qui dentro: se una formula
compare in questo file, sta nel posto sbagliato.
"""
from __future__ import annotations

import logging

import numpy as np

from core.db import connect
from core.orbits.positioner import Body, positions
from core.timeutil import days_since, iso_from_jd, jd_utc_from_tdb, now_jd_tdb

log = logging.getLogger("sky42.ephemeris")

# Oltre questo scarto fra l'epoca degli elementi e la data richiesta, la
# propagazione a due corpi va dichiarata per quello che è. Sei mesi non è una
# soglia fisica: è il punto oltre il quale non abbiamo ancora misurato niente
# (domanda aperta n. 2 del memorandum), e finché non lo sappiamo si avvisa.
EPOCH_WARN_DAYS = 180.0


def _rows(sql: str, params=()) -> list[dict]:
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def search(query: str, limit: int = 20) -> list[dict]:
    """Cerca per designazione, nome o numero. Solo oggetti che hanno un'orbita."""
    q = (query or "").strip()
    if not q:
        return []
    like = f"%{q}%"
    numero = int(q) if q.isdigit() else -1
    return _rows(
        """SELECT t.primary_desig, t.display_name, t.kind, t.number, t.orbit_class,
                  o.h_mag, o.tisserand_j, o.epoch_jd
           FROM target t JOIN orbit o ON o.target_id = t.id
           WHERE t.number = ? OR t.primary_desig LIKE ? OR t.display_name LIKE ?
           ORDER BY (t.primary_desig = ?) DESC, t.number IS NULL, t.number, t.primary_desig
           LIMIT ?""",
        (numero, like, like, q, limit),
    )


def target_row(desig: str) -> dict | None:
    """Un oggetto solo, per designazione, nome, nome visualizzato o numero.

    Quattro modi perché sono i quattro modi in cui un asteroide si chiama:
    «A801 AA» è la designazione, «(1) Ceres» il nome visualizzato, «Ceres» il
    nome e basta, «1» il numero. Il numero nudo va con `kind` perché la
    numerazione delle comete è un'altra: 1P non è (1).
    """
    numero = int(desig) if desig.strip().isdigit() else -1
    righe = _rows(
        """SELECT t.id, t.kind, t.primary_desig, t.display_name, t.number, t.orbit_class,
                  o.*, a.ceu_arcsec, a.ceu_date, a.diameter_km, a.taxon_class
           FROM target t
           JOIN orbit o ON o.target_id = t.id
           LEFT JOIN astorb_extra a ON a.target_id = t.id
           WHERE t.primary_desig = ? OR t.display_name = ?
              OR t.name = ? COLLATE NOCASE
              OR (t.number = ? AND t.kind = 'asteroid')
           LIMIT 1""",
        (desig, desig, desig, numero),
    )
    return righe[0] if righe else None


def ephemeris(desig: str, days: int = 30, step_days: float = 1.0,
              start_jd: float | None = None) -> dict | None:
    """Effemeride geocentrica per `days` giorni, un punto ogni `step_days`.

    Restituisce anche gli avvisi che accompagnano i numeri: senza, un V 21.4
    calcolato con elementi di due anni fa sembra lo stesso numero di uno
    calcolato ieri.
    """
    t = target_row(desig)
    if t is None:
        return None

    # La griglia è in TDB perché è la scala degli elementi; le etichette
    # tornano in UTC perché è la scala degli esseri umani.
    jd0 = now_jd_tdb() if start_jd is None else start_jd
    jd = jd0 + np.arange(0.0, days + 1e-9, step_days)

    body = Body.from_row(t)
    p = positions(body, jd)

    righe = [
        {
            "jd": float(j),
            "data": iso_from_jd(jd_utc_from_tdb(float(j)))[:16].replace("T", " "),
            "ra_deg": float(p["ra_deg"][i]),
            "dec_deg": float(p["dec_deg"][i]),
            "v_mag": _num(p["v_mag"][i]),
            "v_reliable": bool(p["v_reliable"][i]),
            "delta_au": _num(p["delta_au"][i]),
            "r_au": _num(p["r_au"][i]),
            "elong_deg": _num(p["elong_deg"][i]),
            "phase_deg": _num(p["phase_deg"][i]),
            "motion_arcsec_min": _num(p["motion_arcsec_min"][i]),
            "motion_pa_deg": _num(p["motion_pa_deg"][i]),
        }
        for i, j in enumerate(jd)
    ]

    return {
        "target": {
            "primary_desig": t["primary_desig"], "display_name": t["display_name"],
            "kind": t["kind"], "number": t["number"], "orbit_class": t["orbit_class"],
            "h_mag": t["h_mag"], "g_slope": t["g_slope"],
            "m1": t["m1"], "k1": t["k1"],
            "a_au": t["a_au"], "e": t["e"], "i_deg": t["i_deg"],
            "q_derived_au": t["q_derived_au"], "period_yr": t["period_yr"],
            "tisserand_j": t["tisserand_j"], "epoch_jd": t["epoch_jd"],
            "source": t["source"], "last_obs_date": t["last_obs_date"],
            "n_oppositions": t["n_oppositions"], "u_param": t["u_param"],
            "ceu_arcsec": t["ceu_arcsec"], "ceu_date": t["ceu_date"],
        },
        "rows": righe,
        "avvisi": _avvisi(t, jd0, righe),
    }


def _num(x):
    x = float(x)
    return None if not np.isfinite(x) else x


def _avvisi(t: dict, jd0: float, righe: list[dict]) -> list[str]:
    out = []
    scarto = abs(jd0 - t["epoch_jd"])
    if scarto > EPOCH_WARN_DAYS:
        out.append(
            f"Gli elementi hanno epoca {iso_from_jd(t['epoch_jd'])[:10]}, "
            f"{scarto / 365.25:.1f} anni dalla data richiesta: la propagazione è a due "
            "corpi e l'errore cresce con il tempo dall'epoca. Per puntare, verificare "
            "con Horizons."
        )
    if t["kind"] == "comet":
        out.append(
            "Magnitudine cometaria: è un ordinamento, non una previsione. Sbaglia "
            "regolarmente di 2-3 magnitudini, e le comete si giudicano prima sulla "
            "geometria (r, Δ, elongazione)."
        )
    if any(not r["v_reliable"] for r in righe):
        out.append(
            "In parte dell'intervallo l'angolo di fase supera i 120° in cui la "
            "funzione H-G è definita: lì la magnitudine è estrapolata."
        )
    if t["ceu_arcsec"] and t["ceu_arcsec"] > 60:
        out.append(
            f"Incertezza di effemeride ASTORB {t['ceu_arcsec']:.0f}″ alla data "
            f"{t['ceu_date'] or '—'}: la posizione può non stare in un campo stretto."
        )
    eta = days_since(t["updated_at"])
    if eta is not None and eta > 30:
        out.append(f"Gli elementi in archivio sono stati aggiornati {eta:.0f} giorni fa.")
    return out
