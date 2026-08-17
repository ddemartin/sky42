"""La dashboard: tre domande, tre query. **Nessun calcolo.**

È il punto in cui il progetto risponde alla domanda per cui esiste — *cosa
osservo stanotte, da quale sito e in quale finestra* — e ci arriva senza
propagare niente: le finestre le ha scritte il job `windows`, gli stati il job
`radar_states`, le statistiche lo screening. Se in questo file comparisse una
propagazione o una chiamata al positioner, vorrebbe dire che uno di quei tre
lavori non ha distillato abbastanza.

Le tre sezioni rispondono a **tre orizzonti temporali diversi**, ed è la
ragione per cui restano separate invece di essere un'unica classifica:

* `tonight` — stanotte. Quel che si può puntare fra qualche ora.
* `coming_into_range` — le prossime settimane. Quel che conviene aspettare.
* `returns` — gli anni. Chi torna dopo tanto tempo, che è il senso del radar.

Un oggetto brillante e comodo stanotte e un oggetto che nessuno riprende da
vent'anni non si confrontano su una scala sola: fonderli darebbe una classifica
in cui il secondo non compare mai.

Restituisce dict e liste, mai righe di sqlite3 e mai HTML: la pagina è una
lettura di questi dati, e l'endpoint JSON gemello sarà la stessa chiamata.
"""
from __future__ import annotations

import json
import logging

from core.db import connect
from core.radar import states
from core.timeutil import iso_from_jd, jd_utc_from_tdb, now_jd_tdb
from core.visibility.night import night_date_for
from core.visibility.site import Site

log = logging.getLogger("sky42.dashboard")

# Quanti oggetti per sezione. Una decision console si legge in piedi con il
# caffè in mano: venti righe si guardano, duecento si scorrono e basta.
DEFAULT_LIMIT = 20


def current_nights() -> list[dict]:
    """La notte in corso per ogni sito attivo, con il suo `night_id`.

    «Quale notte» è una domanda **per sito** e non per il database: alle 02:30
    UTC a Río Hurtado sono le 22:30 di ieri sera, e la notte in corso è quella
    cominciata ieri. È la stessa `night_date_for` con cui il job ha scritto le
    finestre — usare qui un'altra idea di «stanotte» significherebbe leggere
    righe che parlano di un'altra notte.
    """
    adesso = now_jd_tdb()
    conn = connect()
    try:
        siti = [dict(r) for r in conn.execute(
            "SELECT * FROM observatory WHERE active = 1 ORDER BY code").fetchall()]
        out = []
        for sito in siti:
            data = night_date_for(Site.from_row(sito), adesso)
            riga = conn.execute(
                "SELECT * FROM night WHERE observatory_id=? AND night_date=?",
                (sito["id"], data)).fetchone()
            if riga is None:
                # Il piano delle notti non copre questo sito: si dice, non si
                # inventa. Senza `night_id` non esistono nemmeno le finestre.
                log.warning("dashboard: nessuna notte %s per %s", data, sito["code"])
                continue
            out.append({**dict(riga), "site_code": sito["code"],
                        "site_name": sito["name"], "timezone": sito["timezone"]})
        return out
    finally:
        conn.close()


def _night_filter(nights: list[dict]) -> tuple[str, list]:
    """`WHERE` sulle notti in corso, una coppia (sito, data) per sito."""
    if not nights:
        return "0", []
    return " OR ".join(["w.night_id = ?"] * len(nights)), [n["id"] for n in nights]


# Le colonne della lista. `score_json` **non** c'è di proposito: è la
# scomposizione, si guarda su un oggetto alla volta, e moltiplicata per
# cinquemila righe sarebbe qualche megabyte per disegnare venti righe.
_LIST_COLS = """
    w.target_id, w.setup_id, w.useful_hours, w.useful_start_jd, w.useful_end_jd,
    w.best_jd, w.best_alt_deg, w.best_airmass, w.v_pred, w.eff_vlim,
    w.depth_margin, w.moon_sep_deg, w.moon_illum, w.motion_arcsec_min,
    w.rec_exposure_s, w.rec_n_subs, w.fov_fit_ratio, w.needs_mosaic,
    w.score, w.grade,
    t.primary_desig, t.display_name, t.kind, t.orbit_class,
    o.tisserand_j, o.h_mag,
    st.years_since_last_obs, st.years_since_good_apparition,
    st.v_trend_mag_month, st.selectors,
    s.code AS setup_code, s.name AS setup_name,
    ob.code AS site_code, ob.name AS site_name, ob.timezone, n.night_date
"""

_LIST_JOINS = """
    FROM observation_window w
    JOIN night n       ON n.id = w.night_id
    JOIN target t      ON t.id = w.target_id
    JOIN setup s       ON s.id = w.setup_id
    JOIN observatory ob ON ob.id = n.observatory_id
    LEFT JOIN orbit o        ON o.target_id = w.target_id
    LEFT JOIN target_stats st ON st.target_id = w.target_id
"""


def tonight(limit: int = DEFAULT_LIMIT, grade_min: str | None = None) -> dict:
    """Cosa osservare stanotte, in ordine di punteggio, con il **sito migliore**.

    Una riga per oggetto — quella del setup da cui viene meglio — e accanto il
    confronto fra tutti gli altri setup, compresi quelli da cui *non* si vede.
    È il pannello di IDEA.md: «Chile ★★★★★ PRIME / Namibia ★★★☆☆ POSSIBLE /
    Spain — NOT USEFUL». Un setup che sparisce dalla lista non racconta la
    differenza fra «non si poteva» e «non ci ho provato» (regola 5).

    Due query e non una: prima *quali* oggetti, ordinati per punteggio, poi
    tutte le finestre di quei soli oggetti per il confronto fra siti. Una query
    sola che portasse tutto ordinato per punteggio taglierebbe le alternative
    degli ultimi in classifica proprio mentre le si vuole mostrare.
    """
    notti = current_nights()
    dove, params = _night_filter(notti)
    if not notti:
        return {"nights": [], "rows": [], "n_totali": 0}

    filtro_grado = ""
    if grade_min:
        ammessi = _grades_from(grade_min)
        filtro_grado = f" AND w.grade IN ({','.join('?' * len(ammessi))})"

    conn = connect()
    try:
        migliori = [dict(r) for r in conn.execute(
            f"""SELECT {_LIST_COLS} {_LIST_JOINS}
                WHERE ({dove}) AND w.score IS NOT NULL{filtro_grado}
                ORDER BY w.score DESC, w.depth_margin DESC
                LIMIT ?""",
            (*params, *(_grades_from(grade_min) if grade_min else ()), limit * 4)
        ).fetchall()]

        # Il migliore per oggetto: le righe arrivano già ordinate per punteggio,
        # quindi la prima che si incontra è quella. Si prendono più righe del
        # necessario (limit × 4) perché lo stesso oggetto compare una volta per
        # setup, e con quattro setup la ventesima riga non è il ventesimo oggetto.
        per_target: dict[int, dict] = {}
        for r in migliori:
            per_target.setdefault(r["target_id"], r)
        scelti = list(per_target.values())[:limit]
        if not scelti:
            return {"nights": notti, "rows": [], "n_totali": 0}

        ids = [r["target_id"] for r in scelti]
        alternative = [dict(r) for r in conn.execute(
            f"""SELECT {_LIST_COLS} {_LIST_JOINS}
                WHERE ({dove}) AND w.target_id IN ({','.join('?' * len(ids))})""",
            (*params, *ids)).fetchall()]

        n_totali = conn.execute(
            f"""SELECT count(DISTINCT w.target_id) FROM observation_window w
                WHERE ({dove}) AND w.score IS NOT NULL""", params).fetchone()[0]
    finally:
        conn.close()

    per_oggetto: dict[int, list] = {}
    for r in alternative:
        per_oggetto.setdefault(r["target_id"], []).append(r)

    righe = []
    for r in scelti:
        siti = sorted(per_oggetto.get(r["target_id"], []),
                      key=lambda x: (-(x["score"] or -1), -(x["depth_margin"] or -99)))
        righe.append({**_leggibile(r), "sites": [_sito_breve(x) for x in siti]})
    return {"nights": notti, "rows": righe, "n_totali": n_totali}


def _grades_from(grade_min: str) -> tuple:
    """I gradi da `grade_min` in su. `GRADES` è ordinato dal migliore al peggiore."""
    from core.ranking.score import GRADES

    if grade_min not in GRADES:
        raise ValueError(f"grado sconosciuto: {grade_min}")
    return GRADES[:GRADES.index(grade_min) + 1]


def _iso(jd: float) -> str:
    """JD (TDB) → ISO-8601 UTC. I nostri JD sono TDB, e i 69 secondi di
    differenza sono già costati una diagnosi (memorandum del 16 agosto)."""
    return iso_from_jd(jd_utc_from_tdb(float(jd)))


def _leggibile(r: dict) -> dict:
    """Le colonne come le legge una pagina: JD anche in ISO, niente formattazione.

    I JD restano — sono quelli su cui si fanno i conti — e accanto compare
    l'ISO, perché una finestra si legge in ore e minuti. L'ora **locale** la fa
    la pagina: qui non si sa in che fuso stia chi guarda (CLAUDE.md).
    """
    out = dict(r)
    for campo in ("useful_start_jd", "useful_end_jd", "best_jd"):
        out[campo.replace("_jd", "_iso")] = (
            _iso(r[campo]) if r.get(campo) is not None else None)
    out["selectors"] = [s for s in (r.get("selectors") or "").split(",") if s]
    return out


def _sito_breve(r: dict) -> dict:
    """Una riga del confronto fra siti: quel tanto che serve a dire chi vince."""
    return {
        "site_code": r["site_code"], "site_name": r["site_name"],
        "setup_code": r["setup_code"], "grade": r["grade"], "score": r["score"],
        "useful_hours": r["useful_hours"], "depth_margin": r["depth_margin"],
        "best_alt_deg": r["best_alt_deg"], "eff_vlim": r["eff_vlim"],
    }


def best_sites(limit: int = DEFAULT_LIMIT) -> list[dict]:
    """`BEST SITE TONIGHT`: la stessa domanda di `tonight`, ordinata per sito.

    Quanti oggetti utili offre stanotte ciascun setup, e quanto vale il
    migliore. **Vale quanto valgono i `vlim_ref` dichiarati** (domanda aperta 5
    del memorandum): finché sono stime e non misure, il confronto fra siti è
    un'opinione informata, e la pagina lo dice invece di far finta di no.
    """
    notti = current_nights()
    dove, params = _night_filter(notti)
    if not notti:
        return []

    conn = connect()
    try:
        rows = conn.execute(
            f"""SELECT ob.code AS site_code, ob.name AS site_name,
                       s.code AS setup_code, n.night_date, n.dark_hours, n.moon_illum,
                       count(*) AS n_utili,
                       sum(CASE WHEN w.grade='PRIME' THEN 1 ELSE 0 END) AS n_prime,
                       sum(CASE WHEN w.grade='GOOD' THEN 1 ELSE 0 END) AS n_good,
                       max(w.score) AS score_max,
                       sum(w.useful_hours) AS ore_totali
                FROM observation_window w
                JOIN night n        ON n.id = w.night_id
                JOIN setup s        ON s.id = w.setup_id
                JOIN observatory ob ON ob.id = n.observatory_id
                WHERE ({dove}) AND w.score IS NOT NULL
                GROUP BY w.setup_id
                ORDER BY n_prime DESC, score_max DESC
                LIMIT ?""", (*params, limit)).fetchall()
    finally:
        conn.close()
    return [dict(r) for r in rows]


def coming_into_range(limit: int = DEFAULT_LIMIT, days: float = 120.0) -> list[dict]:
    """Chi **sta per** entrare a portata: le prossime settimane, non stanotte.

    Si legge da `target_state` (il rollup, cioè il migliore fra i setup) e da
    `target_stats`, che lo screening ha già distillato: `next_v21_jd` è la
    prossima volta che quell'oggetto scende sotto il limite di riferimento.

    Il criterio è **lo stato più la data**, non la sola magnitudine: un oggetto
    che sta migliorando ma resta tre anni fuori portata non è una notizia di
    questo mese, ed è precisamente quello che `next_v21_jd` sa e `v_now` no.
    """
    limite_jd = now_jd_tdb() + days
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT t.primary_desig, t.display_name, t.kind, t.orbit_class,
                      o.tisserand_j, o.h_mag,
                      ts.state, ts.since, ts.v_pred, ts.eff_vlim_ref,
                      s.v_now, s.v_trend_mag_month, s.peak_v, s.peak_jd,
                      s.next_v21_jd, s.visibility_start_jd, s.visibility_end_jd,
                      s.years_since_last_obs, s.years_since_good_apparition,
                      s.ceu_now_arcsec, s.selectors
               FROM target_state ts
               JOIN target t       ON t.id = ts.target_id
               JOIN target_stats s ON s.target_id = ts.target_id
               LEFT JOIN orbit o   ON o.target_id = ts.target_id
               WHERE ts.setup_id IS NULL
                 AND ts.state IN ('APPROACHING','CROSSES_LIMIT')
                 AND s.next_v21_jd IS NOT NULL AND s.next_v21_jd <= ?
               ORDER BY s.next_v21_jd
               LIMIT ?""", (limite_jd, limit)).fetchall()
    finally:
        conn.close()

    adesso = now_jd_tdb()
    return [{**_stats_leggibili(dict(r)),
             "giorni_alla_portata": round(r["next_v21_jd"] - adesso, 1)}
            for r in rows]


def returns(limit: int = DEFAULT_LIMIT, tisserand_max: float = 3.0) -> list[dict]:
    """Tj < 3 che tornano: gli **anni**, non le settimane.

    Ordinati per «da quanto non c'era una buona apparizione», che è la
    definizione di rientro del progetto e non la magnitudine di oggi: un
    oggetto a V 20 che si vede ogni anno è meno interessante di uno a V 21 che
    mancava da vent'anni, ed è l'unica sezione in cui questo ordine ha senso.

    **`years_since_good_apparition` a NULL è un valore censurato, non mancante.**
    Significa che in tutta la finestra di back-propagation — quindici anni — non
    c'è stata nemmeno una volta in cui l'oggetto stesse sotto il limite: è
    l'assenza *più lunga di tutte*, non un dato che manca. Ordinarli per ultimi
    (`NULLS LAST`, che è il default naturale) seppellisce esattamente gli
    oggetti per cui la sezione esiste — è successo alla prima lettura sul
    catalogo vero, e in cima c'era un oggetto tornato dopo 14,9 anni mentre uno
    che non si vedeva da più di quindici stava in fondo. Escono con
    `apparition_censored` a `True` e la pagina scrive «≥ 15 anni», che è quel
    che si sa: mettere 15 tondo sarebbe inventare una misura.
    """
    from core.radar.screening import BACK_YEARS

    # Più grande di qualunque assenza misurabile: ordina i censurati in cima
    # senza far finta che quel numero sia la loro età.
    OLTRE_LA_FINESTRA = 9999.0

    conn = connect()
    try:
        rows = conn.execute(
            f"""SELECT t.primary_desig, t.display_name, t.kind, t.orbit_class,
                       o.tisserand_j, o.h_mag, o.last_obs_date,
                       ts.state, ts.since, ts.v_pred, ts.eff_vlim_ref,
                       s.v_now, s.v_trend_mag_month, s.peak_v, s.peak_jd,
                       s.visibility_start_jd, s.visibility_end_jd,
                       s.last_good_apparition_jd, s.years_since_good_apparition,
                       s.years_since_last_obs, s.ceu_now_arcsec, s.selectors
                FROM target_state ts
                JOIN target t       ON t.id = ts.target_id
                JOIN target_stats s ON s.target_id = ts.target_id
                JOIN orbit o        ON o.target_id = ts.target_id
                WHERE ts.setup_id IS NULL
                  AND ts.state IN ({','.join('?' * len(states.IN_RANGE))})
                  AND o.tisserand_j IS NOT NULL AND o.tisserand_j < ?
                ORDER BY COALESCE(s.years_since_good_apparition, ?) DESC,
                         s.years_since_last_obs DESC
                LIMIT ?""",
            (*states.IN_RANGE, tisserand_max, OLTRE_LA_FINESTRA, limit)).fetchall()
    finally:
        conn.close()
    return [{**_stats_leggibili(dict(r)),
             "apparition_censored": r["years_since_good_apparition"] is None,
             "apparition_window_years": BACK_YEARS}
            for r in rows]


def _stats_leggibili(r: dict) -> dict:
    """I JD di `target_stats` anche in ISO, e i selettori come lista."""
    for campo in ("next_v21_jd", "peak_jd", "visibility_start_jd",
                  "visibility_end_jd", "last_good_apparition_jd"):
        if campo in r:
            r[campo.replace("_jd", "_iso")] = (
                _iso(r[campo]) if r[campo] is not None else None)
    r["selectors"] = [s for s in (r.get("selectors") or "").split(",") if s]
    return r


def freshness() -> dict:
    """Quanto sono vecchi i tre lavori da cui la dashboard dipende.

    Va **in cima alla pagina**, non in fondo: una classifica calcolata su
    finestre di tre giorni fa è sbagliata in un modo che non si vede guardando
    le righe. Il 16 agosto i job pesanti non giravano da un giorno e nessuno lo
    diceva (memorandum): l'età di un risultato è parte del risultato.
    """
    conn = connect()
    try:
        rows = conn.execute(
            """SELECT job_name, started_at, status, n_processed, duration_s
               FROM job_run r
               WHERE started_at = (SELECT max(started_at) FROM job_run
                                   WHERE job_name = r.job_name)
                 AND job_name IN ('screening','windows','radar_states')"""
        ).fetchall()
        n_finestre = conn.execute(
            "SELECT count(*) FROM observation_window").fetchone()[0]
    finally:
        conn.close()
    return {"jobs": {r["job_name"]: dict(r) for r in rows}, "n_finestre": n_finestre}


def overview(limit: int = DEFAULT_LIMIT) -> dict:
    """Le tre sezioni più il contesto, in una chiamata sola.

    È quello che la pagina disegna e quello che l'endpoint JSON restituirà:
    una sola forma, o le due sorgenti divergono appena qualcuno tocca una query.
    """
    return {
        "freshness": freshness(),
        "tonight": tonight(limit),
        "best_sites": best_sites(),
        "coming_into_range": coming_into_range(limit),
        "returns": returns(limit),
    }


def as_json(limit: int = DEFAULT_LIMIT) -> str:
    return json.dumps(overview(limit), indent=2, ensure_ascii=False, default=str)
