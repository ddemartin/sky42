"""Pagina Pianificatore: cosa gira da solo, quando, e com'è finito l'ultima volta.

Un servizio che lavora senza che nessuno glielo chieda ha bisogno di una pagina
che risponda a tre domande in un colpo d'occhio: **sta girando? quando tocca di
nuovo? l'ultima volta è andata bene?** Senza quella pagina, un job che fallisce
in silenzio da tre settimane si scopre dai dati vecchi.
"""
from __future__ import annotations

import logging

from nicegui import run, ui

from gui.layout import fmt_age, fmt_int, fmt_num, header
from services import backup_service
from services.scheduler import scheduler
from core.timeutil import days_since

log = logging.getLogger("sky42.gui.pianificatore")

ESITO = {"ok": ("positive", "check_circle"),
         "failed": ("negative", "error"),
         "skipped": ("grey", "remove_circle_outline"),
         "running": ("info", "hourglass_top")}


@ui.page("/pianificatore")
def pianificatore_page() -> None:
    header("Pianificatore")

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-5"):
        stato_box = ui.row().classes("w-full items-center gap-3")
        ui.label(
            "I controlli girano ogni 6 ore invece che a un orario fisso: le sorgenti "
            "pubblicano a orari che si spostano (Lowell slitta a Luna piena), e con "
            "l'ETag un controllo a vuoto costa qualche kilobyte."
        ).classes("text-xs opacity-60 -mt-3")

        lavori_box = ui.column().classes("w-full gap-2")

        ui.label("Backup").classes("text-xl font-bold")
        ui.label(
            "Solo le tabelle che non si riscaricano: candidati NEOCP e loro storia, "
            "transizioni di stato, osservazioni, watchlist, calibrazioni. Il catalogo "
            "non entra nel backup — quello si riscarica dall'MPC."
        ).classes("text-xs opacity-60 -mt-3")
        backup_box = ui.column().classes("w-full gap-2")

    def redraw() -> None:
        stato_box.clear()
        with stato_box:
            if scheduler.running:
                ui.badge("in funzione").props("color=positive")
            else:
                ui.badge("fermo").props("color=negative")
            ui.label(f"{fmt_int(len(scheduler.specs))} lavori registrati").classes("opacity-80")
            ui.space()
            ui.button("Aggiorna", icon="refresh").props("flat dense").on("click", redraw)

        lavori_box.clear()
        with lavori_box:
            for j in scheduler.status():
                with ui.card().classes("w-full py-3"):
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        colore, icona = ESITO.get(j["last_status"] or "", ("grey", "help_outline"))
                        ui.icon(icona).classes(f"text-{colore}")
                        with ui.column().classes("gap-0 min-w-64"):
                            ui.label(j["label"]).classes("font-bold")
                            ui.label(j["description"]).classes("text-xs opacity-60")

                        with ui.column().classes("gap-0 min-w-40"):
                            ui.label(j["cadenza"]).classes("text-sm")
                            ui.label(
                                f"prossimo: fra {fmt_age(_days_to(j['next_run']))}"
                                if j["next_run"] else "in pausa"
                            ).classes("text-xs opacity-70")

                        with ui.column().classes("gap-0 grow"):
                            if j["last_start"]:
                                ui.label(
                                    f"ultimo giro {fmt_age(days_since(j['last_start']))}"
                                    f" · {j['last_status']}"
                                    + (f" · {fmt_int(j['last_n'])} elementi" if j["last_n"] else "")
                                    + (f" · {fmt_num(j['last_duration'], 1)} s"
                                       if j["last_duration"] else "")
                                ).classes("text-sm")
                            else:
                                ui.label("mai eseguito").classes("text-sm opacity-70")
                            if j["last_error"]:
                                ui.label(j["last_error"][:120]).classes("text-xs text-negative")

                        ui.switch(value=j["enabled"],
                                  on_change=lambda e, n=j["name"]: _toggle(n, e.value)) \
                            .props("dense").tooltip("attiva / sospendi")
                        ui.button(icon="play_arrow").props("flat round dense") \
                            .on("click", lambda n=j["name"]: _esegui(n)) \
                            .tooltip("esegui adesso")

        backup_box.clear()
        with backup_box:
            copie = backup_service.list_backups()
            if not copie:
                ui.label("Nessuna copia ancora. Oggi non c'è niente da salvare: "
                         "le tabelle non rigenerabili si riempiono con i watcher NEOCP "
                         "e con le tue osservazioni.").classes("text-sm opacity-70")
            for c in copie[:5]:
                with ui.row().classes("items-center gap-3"):
                    ui.icon("save").classes("opacity-70")
                    ui.label(c["file"]).classes("font-mono text-sm")
                    ui.label(f"{c['kb']} kB").classes("text-sm opacity-70")
                    ui.label(fmt_age(days_since(c["quando"]))).classes("text-sm opacity-70")

    def _toggle(name: str, value: bool) -> None:
        scheduler.set_enabled(name, value)
        ui.notify(f"{name}: {'attivo' if value else 'sospeso'}", type="info")
        redraw()

    async def _esegui(name: str) -> None:
        try:
            scheduler.run_now(name)
            ui.notify(f"{name}: avviato", type="ongoing")
        except KeyError:
            ui.notify("pianificatore non avviato", type="negative")
            return
        # Il lavoro gira in un processo a parte: qui si aspetta un momento e si
        # ridisegna, invece di bloccare la pagina finché ha finito.
        await run.io_bound(_attendi_un_poco)
        redraw()

    redraw()


def _attendi_un_poco() -> None:
    import time

    time.sleep(2)


def _days_to(iso_ts: str | None) -> float | None:
    d = days_since(iso_ts)
    return -d if d is not None else None
