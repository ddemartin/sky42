"""Pagina Oggetto: l'effemeride di un target, dal catalogo locale.

È la prima pagina in cui si vede il motore orbitale al lavoro, e serve a una
cosa precisa: **controllare che i numeri siano credibili prima di fidarsene**
in una dashboard che ne mostrerà mille alla volta. Per questo mostra anche i
suoi avvisi — epoca degli elementi, fase estrapolata, incertezza ASTORB — che
in una tabella di ranking non ci starebbero.

Nessuna chiamata a JPL: tutto viene dagli elementi in archivio (regola 2).
"""
from __future__ import annotations

import logging

from nicegui import run, ui

from gui.layout import (
    cols,
    fmt_dec_dms,
    fmt_int,
    fmt_num,
    fmt_ra_hms,
    header,
    table,
)
from services import ephemeris_service as eph
from services import window_service

log = logging.getLogger("sky42.gui.oggetto")

INTERVALLI = {"7 giorni": (7, 1.0), "30 giorni": (30, 1.0), "90 giorni": (90, 3.0),
              "1 anno": (365, 10.0)}


@ui.page("/oggetto")
def oggetto_page(desig: str = "", giorni: str = "30 giorni") -> None:
    header("Oggetto")

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-5"):
        with ui.row().classes("w-full items-center gap-3 no-wrap"):
            campo = ui.input("Designazione, nome o numero", value=desig) \
                .props("outlined dense clearable").classes("grow")
            scelta = ui.select(list(INTERVALLI), value=giorni).props("outlined dense")
            cerca = ui.button("Effemeride", icon="search")
        ui.label(
            "Calcolata in casa: elementi del catalogo, propagazione a due corpi, "
            "posizione astrometrica geocentrica corretta per tempo luce. "
            "JPL non viene chiamato."
        ).classes("text-xs opacity-60 -mt-3")

        suggerimenti = ui.column().classes("w-full gap-1")
        scheda = ui.column().classes("w-full gap-4")

    def apri(nuovo: str) -> None:
        campo.value = nuovo
        disegna()

    def disegna_suggerimenti(q: str) -> None:
        suggerimenti.clear()
        with suggerimenti:
            trovati = eph.search(q, limit=8)
            if not trovati:
                ui.label(f"Nessun oggetto per «{q}»").classes("opacity-70")
                return
            ui.label("Forse cercavi:").classes("text-sm opacity-70")
            with ui.row().classes("gap-2 flex-wrap"):
                for t in trovati:
                    ui.button(t["display_name"], on_click=lambda d=t["primary_desig"]: apri(d)) \
                        .props("flat dense no-caps")

    async def disegna_async() -> None:
        q = (campo.value or "").strip()
        scheda.clear()
        suggerimenti.clear()
        if not q:
            return

        # `io_bound` e non `cpu_bound`: il calcolo è millisecondi, ma il primo
        # accesso carica 32 MB di DE440s e non deve bloccare il loop di eventi.
        dati = await run.io_bound(eph.ephemeris, q, *INTERVALLI[scelta.value])
        if dati is None:
            disegna_suggerimenti(q)
            return
        stanotte = await run.io_bound(window_service.tonight, q)
        _scheda(scheda, dati, stanotte)

    def disegna() -> None:
        ui.timer(0, disegna_async, once=True)

    cerca.on_click(disegna)
    campo.on("keydown.enter", disegna)
    scelta.on_value_change(lambda _: disegna())
    if desig:
        disegna()


def _scheda(contenitore, dati: dict, stanotte: dict | None = None) -> None:
    t = dati["target"]
    with contenitore:
        with ui.card().classes("w-full gap-2"):
            with ui.row().classes("w-full items-center gap-3 no-wrap"):
                ui.label(t["display_name"]).classes("text-2xl font-bold")
                ui.badge(t["kind"]).props("color=primary outline")
                if t["orbit_class"]:
                    ui.badge(t["orbit_class"]).props("color=grey outline")
                ui.space()
                ui.label(f"elementi da {t['source']}").classes("text-xs opacity-60")

            with ui.row().classes("gap-6 flex-wrap text-sm opacity-90"):
                ui.label(f"a = {fmt_num(t['a_au'], 3)} AU")
                ui.label(f"e = {fmt_num(t['e'], 4)}")
                ui.label(f"i = {fmt_num(t['i_deg'], 2)}°")
                ui.label(f"q = {fmt_num(t['q_derived_au'], 3)} AU")
                if t["period_yr"]:
                    ui.label(f"P = {fmt_num(t['period_yr'], 2)} anni")
                if t["tisserand_j"] is not None:
                    ui.label(f"Tj = {fmt_num(t['tisserand_j'], 3)}")
                if t["h_mag"] is not None:
                    ui.label(f"H = {fmt_num(t['h_mag'], 2)} (G = {fmt_num(t['g_slope'], 2)})")
                if t["m1"] is not None:
                    ui.label(f"M1 = {fmt_num(t['m1'], 1)}, k1 = {fmt_num(t['k1'], 1)}")
                if t["last_obs_date"]:
                    ui.label(f"ultima oss. {t['last_obs_date']}")
                if t["n_oppositions"]:
                    ui.label(f"{fmt_int(t['n_oppositions'])} opposizioni")
                if t["ceu_arcsec"] is not None:
                    ui.label(f"CEU {fmt_num(t['ceu_arcsec'], 1)}″")

        for avviso in dati["avvisi"]:
            with ui.row().classes("w-full items-start gap-2 no-wrap"):
                ui.icon("warning").classes("text-amber-600")
                ui.label(avviso).classes("text-sm opacity-80")

        _stanotte(stanotte)

        righe = dati["rows"]
        migliore = min((r for r in righe if r["v_mag"] is not None),
                       key=lambda r: r["v_mag"], default=None)
        if migliore:
            ui.label(
                f"Nell'intervallo il massimo di luminosità è V {fmt_num(migliore['v_mag'], 1)} "
                f"il {migliore['data'][:10]}, a {fmt_num(migliore['elong_deg'], 0)}° dal Sole."
            ).classes("text-sm")

        table(
            cols(("data", "data (UTC)"), ("ra", "RA"), ("dec", "Dec"),
                 ("v", "V", "right"), ("delta", "Δ (AU)", "right"),
                 ("r", "r (AU)", "right"), ("elong", "elong (°)", "right"),
                 ("fase", "fase (°)", "right"), ("moto", "moto (\"/min)", "right"),
                 ("pa", "PA (°)", "right")),
            [{
                "data": r["data"],
                "ra": fmt_ra_hms(r["ra_deg"]),
                "dec": fmt_dec_dms(r["dec_deg"]),
                # L'asterisco dice che la funzione di fase è estrapolata: il
                # numero si mostra, ma non si finge che valga quanto gli altri.
                "v": fmt_num(r["v_mag"], 1) + ("" if r["v_reliable"] else " *"),
                "delta": fmt_num(r["delta_au"], 4),
                "r": fmt_num(r["r_au"], 4),
                "elong": fmt_num(r["elong_deg"], 1),
                "fase": fmt_num(r["phase_deg"], 1),
                "moto": fmt_num(r["motion_arcsec_min"], 2),
                "pa": fmt_num(r["motion_pa_deg"], 0),
            } for r in righe],
        )
        ui.label(
            "Posizioni astrometriche J2000 geocentriche. Il moto apparente è calcolato "
            "per differenze finite su ±30 minuti; PA è l'angolo di posizione, 0° = nord, "
            "90° = est."
        ).classes("text-xs opacity-60")


def _ora(jd, timezone: str) -> str:
    """JD → ora locale del sito: è l'unica forma in cui un orario è azionabile."""
    if jd is None:
        return "—"
    from zoneinfo import ZoneInfo

    from core.timeutil import datetime_from_jd, jd_utc_from_tdb

    return datetime_from_jd(jd_utc_from_tdb(jd)).astimezone(
        ZoneInfo(timezone)).strftime("%H:%M")


def _stanotte(stanotte: dict | None) -> None:
    """Stanotte, da quale setup, e con quale margine.

    Le due finestre restano separate anche qui: «geometrica» dice quando
    l'oggetto è sopra i limiti dello strumento, «utile» quando è anche sotto il
    limite di magnitudine. Un setup da cui non si vede resta nell'elenco con il
    suo motivo — sparire non spiega niente.
    """
    if not stanotte or not stanotte["windows"]:
        return
    ui.label("Stanotte").classes("text-xl font-bold")
    for w in stanotte["windows"]:
        tz = w["timezone"]
        with ui.card().classes("w-full py-3 gap-1"):
            with ui.row().classes("w-full items-center gap-3 no-wrap"):
                ui.icon("nights_stay" if w["useful"] else "block") \
                    .classes("text-lg " + ("text-primary" if w["useful"] else "opacity-40"))
                ui.label(w["setup_name"]).classes("font-bold")
                ui.badge(w["site_code"]).props("color=grey outline")
                ui.label(f"notte del {w['night_date']}").classes("text-xs opacity-60")
                ui.space()
                if w["useful"]:
                    ui.badge(f"margine {w['depth_margin']:+.1f} mag") \
                        .props("color=positive")
                else:
                    ui.badge(w["motivo"]).props("color=grey")

            if not w["observable"]:
                continue

            with ui.row().classes("gap-6 flex-wrap text-sm"):
                ui.label(f"geometrica {_ora(w['geo_start_jd'], tz)}–"
                         f"{_ora(w['geo_end_jd'], tz)} ({w['geo_hours']:.1f} h)")
                if w["useful"]:
                    ui.label(f"**utile** {_ora(w['useful_start_jd'], tz)}–"
                             f"{_ora(w['useful_end_jd'], tz)} "
                             f"({w['useful_hours']:.1f} h)").classes("text-primary")
                else:
                    ui.label(f"utile: nessuna — {w['wasted_hours']:.1f} h buttate") \
                        .classes("opacity-70")
                ui.label(f"meglio alle {_ora(w['best_jd'], tz)} a {w['best_alt_deg']:.0f}° "
                         f"(X {w['best_airmass']:.2f})")
                ui.label(f"transito {_ora(w['transit_jd'], tz)} a {w['max_alt_deg']:.0f}°") \
                    .classes("opacity-70")

            with ui.row().classes("gap-6 flex-wrap text-sm opacity-90"):
                ui.label(f"V {w['v_pred']:.1f} contro limite {w['eff_vlim']:.1f} "
                         f"(astrometrico {w['eff_vlim_astrometric']:.1f})")
                # La scomposizione si mostra sempre: è il motivo per cui un
                # numero si può tarare invece che solo leggere.
                ui.label(f"penalità — airmass {w['pen_airmass']:.2f}, "
                         f"Luna {w['pen_moon']:.2f}, crepuscolo {w['pen_twilight']:.2f}, "
                         f"moto {w['pen_trailing']:.2f}").classes("opacity-70")

            with ui.row().classes("gap-6 flex-wrap text-sm opacity-90"):
                ui.label(f"cielo {w['sky_brightness_mag']:.1f} mag/arcsec²")
                ui.label(f"Luna {w['moon_illum'] * 100:.0f}% a {w['moon_sep_deg']:.0f}° "
                         f"(altezza {w['moon_alt_deg']:+.0f}°)")
                ui.label(f"moto {w['motion_arcsec_min']:.2f}\"/min")
                if w["rec_n_subs"]:
                    ui.label(f"consigliate {w['rec_n_subs']} × {w['rec_exposure_s']:.0f} s "
                             f"(traccia {w['trail_arcsec']:.1f}\")")
                if w["needs_mosaic"]:
                    ui.badge("serve un mosaico").props("color=warning")
