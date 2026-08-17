"""Pagina Stanotte: la decision console. Tre sezioni, tre orizzonti.

È la pagina per cui esiste il progetto, e non calcola **niente**: legge quello
che i tre job della notte hanno già scritto. Se qui dentro comparisse una
propagazione, vorrebbe dire che la dashboard è tornata a essere un calcolo
invece di una query.

Le tre sezioni non si fondono in una classifica sola perché rispondono a tre
domande con tre orizzonti diversi — stanotte, le prossime settimane, gli anni —
e un oggetto che manca da vent'anni non batterebbe mai, su una scala unica, un
oggetto comodo e brillante di stasera.

L'ora **locale del sito** si calcola qui: il servizio restituisce UTC e il fuso,
perché è l'interfaccia l'unico posto in cui esiste un osservatore che guarda un
orologio (CLAUDE.md).
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from nicegui import app, run, ui

from gui.layout import cols, fmt_age, fmt_int, fmt_num, header, table
from services import dashboard_service as dash

log = logging.getLogger("sky42.gui.stanotte")

# Il colore del giudizio. NOT_USEFUL resta grigio e **resta visibile**: sapere
# che da un sito non si poteva è informazione, non rumore (regola 5).
GRADI = {"PRIME": "positive", "GOOD": "primary", "POSSIBLE": "warning",
         "POOR": "grey", "NOT_USEFUL": "grey-5"}

# Oltre queste ore il risultato è vecchio: i tre job girano fra le 02:10 e le
# 02:40 UTC, quindi 30 ore vuol dire che un giro è stato saltato del tutto.
STANTIO_ORE = 30.0


def _locale(iso: str | None, tz: str) -> str:
    """Da ISO-8601 UTC all'ora locale del sito, in «HH:MM»."""
    if not iso:
        return "—"
    t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
    return t.astimezone(ZoneInfo(tz)).strftime("%H:%M")


@ui.page("/stanotte")
def stanotte_page() -> None:
    header("Stanotte")

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-5"):
        stato_box = ui.row().classes("w-full items-center gap-3")
        notti_box = ui.row().classes("w-full items-center gap-3 -mt-2")
        tonight_box = ui.column().classes("w-full gap-2")
        siti_box = ui.column().classes("w-full gap-2")
        arrivo_box = ui.column().classes("w-full gap-2")
        ritorni_box = ui.column().classes("w-full gap-2")

    async def redraw() -> None:
        # In un thread: sono cinque query, e una pagina che si blocca mentre il
        # Mac mini macina lo screening è una pagina che sembra rotta.
        dati = await run.io_bound(dash.overview)
        _disegna(dati, stato_box, notti_box, tonight_box, siti_box, arrivo_box,
                 ritorni_box, redraw)

    ui.timer(0.1, redraw, once=True)


def _disegna(dati, stato_box, notti_box, tonight_box, siti_box, arrivo_box,
             ritorni_box, redraw) -> None:
    _intestazione(dati["freshness"], stato_box, redraw)
    _notti(dati["tonight"]["nights"], notti_box)
    _tonight(dati["tonight"], tonight_box)
    _best_sites(dati["best_sites"], siti_box)
    _coming(dati["coming_into_range"], arrivo_box)
    _returns(dati["returns"], ritorni_box)


def _intestazione(fresh: dict, box, redraw) -> None:
    """L'età dei tre lavori, in cima e non in fondo.

    Una classifica calcolata su finestre di tre giorni fa è sbagliata in un modo
    che non si vede guardando le righe: il 16 agosto i job pesanti non giravano
    da un giorno e nessuno lo diceva (memorandum).
    """
    from core.timeutil import days_since

    box.clear()
    with box:
        ui.label("Cosa osservare stanotte").classes("text-2xl font-bold")
        ui.space()
        for nome, etichetta in (("screening", "screening"), ("windows", "finestre"),
                                ("radar_states", "radar")):
            j = fresh["jobs"].get(nome)
            eta = days_since(j["started_at"]) if j else None
            colore = ("grey" if eta is None
                      else "negative" if eta * 24 > STANTIO_ORE
                      else "positive" if (j or {}).get("status") == "ok" else "warning")
            ui.badge(f"{etichetta} {fmt_age(eta)}").props(f"color={colore}")
        ui.button("Aggiorna", icon="refresh").props("flat dense").on("click", redraw)


def _notti(notti: list[dict], box) -> None:
    box.clear()
    with box:
        if not notti:
            ui.label(
                "Nessuna notte calcolata per i siti attivi: il piano delle notti "
                "gira ogni 6 ore, e senza di lui non esistono finestre."
            ).classes("text-sm text-negative")
            return
        for n in notti:
            luna = f"Luna {fmt_pct_illum(n['moon_illum'])}"
            ui.label(f"{n['site_name']} · notte del {n['night_date']} · "
                     f"{fmt_num(n['dark_hours'], 1)} h di buio · {luna}") \
                .classes("text-sm opacity-70")


def fmt_pct_illum(x) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def _tonight(dati: dict, box) -> None:
    box.clear()
    with box:
        righe = dati["rows"]
        if not righe:
            ui.label(
                "Nessun oggetto con una finestra utile stanotte. Se il job "
                "`windows` non è ancora girato, la tabella è vuota per quello — "
                "e lo dicono i badge qui sopra."
            ).classes("opacity-70")
            return

        ui.label(f"{fmt_int(dati['n_totali'])} oggetti hanno una finestra utile "
                 f"stanotte; questi sono i migliori {len(righe)}.") \
            .classes("text-xs opacity-60")

        for r in righe:
            _scheda(r)


def _scheda(r: dict) -> None:
    """Una riga della sezione Stanotte: l'oggetto, la finestra, e i siti.

    Il confronto fra siti sta **dentro la riga** e non in una pagina a parte: la
    domanda «da dove lo prendo» non è una domanda successiva a «cosa osservo»,
    è la stessa domanda (IDEA.md).
    """
    with ui.card().classes("w-full py-3"):
        with ui.row().classes("w-full items-center gap-4 no-wrap"):
            with ui.column().classes("gap-0 min-w-64"):
                ui.label(r["display_name"]).classes("font-bold cursor-pointer") \
                    .on("click", lambda d=r["primary_desig"]:
                        ui.navigate.to(f"/oggetto?q={d}"))
                dettagli = [r["kind"], r.get("orbit_class") or ""]
                if r.get("tisserand_j") is not None:
                    dettagli.append(f"Tj {fmt_num(r['tisserand_j'], 2)}")
                if r.get("years_since_last_obs") is not None:
                    dettagli.append(f"non ripreso da {fmt_num(r['years_since_last_obs'], 1)} anni")
                ui.label(" · ".join(x for x in dettagli if x)).classes("text-xs opacity-60")

            with ui.column().classes("gap-0 min-w-48"):
                ui.label(f"V {fmt_num(r['v_pred'], 1)} · limite {fmt_num(r['eff_vlim'], 1)} · "
                         f"margine {fmt_num(r['depth_margin'], 1)} mag").classes("text-sm")
                ui.label(f"{_locale(r['useful_start_iso'], r['timezone'])}–"
                         f"{_locale(r['useful_end_iso'], r['timezone'])} locali · "
                         f"{fmt_num(r['useful_hours'], 1)} h · "
                         f"alt {fmt_num(r['best_alt_deg'], 0)}° · X {fmt_num(r['best_airmass'], 2)}") \
                    .classes("text-xs opacity-70")

            with ui.column().classes("gap-0 min-w-40"):
                ui.label(f"{fmt_num(r['rec_exposure_s'], 0)} s × {r['rec_n_subs'] or '—'}") \
                    .classes("text-sm")
                nota = f"moto {fmt_num(r['motion_arcsec_min'], 1)}\"/min"
                if r.get("needs_mosaic"):
                    nota += " · serve un mosaico"
                ui.label(nota).classes("text-xs opacity-70")

            ui.space()
            with ui.column().classes("gap-1 items-end"):
                ui.badge(f"{r['grade']} {fmt_num(r['score'], 2)}") \
                    .props(f"color={GRADI.get(r['grade'], 'grey')}")
                # BEST SITE: il primo della lista, e gli altri accanto con il
                # loro giudizio — anche quando è NOT_USEFUL.
                with ui.row().classes("gap-1 items-center"):
                    for s in r["sites"]:
                        ui.badge(f"{s['site_code']} {s['grade']}") \
                            .props(f"color={GRADI.get(s['grade'], 'grey')} outline") \
                            .tooltip(f"{s['setup_code']} · "
                                     f"{fmt_num(s['useful_hours'], 1)} h utili · "
                                     f"margine {fmt_num(s['depth_margin'], 1)} mag")


def _best_sites(righe: list[dict], box) -> None:
    box.clear()
    with box:
        ui.label("Best site tonight").classes("text-xl font-bold")
        if not righe:
            ui.label("Nessun setup con oggetti utili stanotte.").classes("opacity-70")
            return
        ui.label(
            "Vale quanto valgono i `vlim_ref` dichiarati: finché sono stime e non "
            "misure di `setup_calibration`, il confronto fra siti è un'opinione "
            "informata (domanda aperta 5)."
        ).classes("text-xs opacity-60")
        table(
            cols(("sito", "sito"), ("setup", "setup"), ("notte", "notte"),
                 ("utili", "oggetti utili", "right"), ("prime", "PRIME", "right"),
                 ("good", "GOOD", "right"), ("score", "score migliore", "right"),
                 ("ore", "ore utili in totale", "right")),
            [{"sito": r["site_name"], "setup": r["setup_code"],
              "notte": r["night_date"], "utili": r["n_utili"],
              "prime": r["n_prime"], "good": r["n_good"],
              "score": fmt_num(r["score_max"], 3),
              "ore": fmt_num(r["ore_totali"], 1)} for r in righe])


def _coming(righe: list[dict], box) -> None:
    box.clear()
    with box:
        ui.label("Coming into range").classes("text-xl font-bold")
        ui.label("Le prossime settimane: chi conviene aspettare, e da quando. "
                 "La data viene dallo screening, non da stanotte.") \
            .classes("text-xs opacity-60")
        if not righe:
            ui.label("Nessun oggetto in avvicinamento entro quattro mesi.") \
                .classes("opacity-70")
            return
        table(
            cols(("oggetto", "oggetto"), ("tipo", "tipo"), ("tj", "Tj", "right"),
                 ("stato", "stato"), ("v", "V ora", "right"),
                 ("trend", "mag/mese", "right"), ("quando", "a portata dal"),
                 ("giorni", "fra (giorni)", "right"),
                 ("picco", "picco V", "right"),
                 ("assenza", "manca da (anni)", "right")),
            [{"oggetto": r["display_name"], "tipo": r["kind"],
              "tj": fmt_num(r["tisserand_j"], 2), "stato": r["state"],
              "v": fmt_num(r["v_now"], 1),
              "trend": fmt_num(r["v_trend_mag_month"], 2),
              "quando": (r["next_v21_iso"] or "—")[:10],
              "giorni": fmt_num(r["giorni_alla_portata"], 0),
              "picco": fmt_num(r["peak_v"], 1),
              "assenza": fmt_num(r["years_since_good_apparition"], 1)}
             for r in righe])


def _returns(righe: list[dict], box) -> None:
    box.clear()
    with box:
        ui.label("Tj < 3 che tornano").classes("text-xl font-bold")
        ui.label("Gli anni, non le settimane: a portata adesso, ordinati per "
                 "quanto tempo è passato dall'ultima buona apparizione.") \
            .classes("text-xs opacity-60")
        if not righe:
            ui.label("Nessun oggetto su orbita cometaria a portata in questo momento.") \
                .classes("opacity-70")
            return
        table(
            cols(("oggetto", "oggetto"), ("classe", "classe"), ("tj", "Tj", "right"),
                 ("stato", "stato"), ("v", "V ora", "right"),
                 ("assenza", "buona apparizione (anni fa)", "right"),
                 ("oss", "non osservato da (anni)", "right"),
                 ("ceu", "CEU (\")", "right"), ("regole", "perché")),
            [{"oggetto": r["display_name"], "classe": r["orbit_class"] or "—",
              "tj": fmt_num(r["tisserand_j"], 2), "stato": r["state"],
              "v": fmt_num(r["v_now"], 1),
              # «≥ 15» e non «15»: fuori dalla finestra di back-propagation non
              # si sa quanto è passato, si sa che è di più.
              "assenza": (f"≥ {r['apparition_window_years']}"
                          if r["apparition_censored"]
                          else fmt_num(r["years_since_good_apparition"], 1)),
              "oss": fmt_num(r["years_since_last_obs"], 1),
              "ceu": fmt_num(r["ceu_now_arcsec"], 1),
              "regole": ", ".join(r["selectors"])} for r in righe])


@app.get("/api/stanotte")
def stanotte_json(limit: int = dash.DEFAULT_LIMIT) -> dict:
    """Il gemello JSON della pagina: **la stessa chiamata**, non una seconda query.

    Il giorno delle curve di visibilità la sorgente dati deve già esserci, o
    ogni grafico diventa una riscrittura della pagina che lo contiene
    (CLAUDE.md).
    """
    return dash.overview(limit)
