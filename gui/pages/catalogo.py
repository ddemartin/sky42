"""Pagina Catalogo: quanti oggetti ci sono, da quando, e cosa se ne ricava.

È la prima pagina costruita perché è quella che risponde alla domanda che ci si
fa ogni mattina prima di fidarsi di qualunque altro numero: **i dati sono
freschi?** Un catalogo di tre settimane fa non sbaglia i conti, li fa sui
dati sbagliati, ed è molto peggio.
"""
from __future__ import annotations

import logging

from nicegui import run, ui

from gui.layout import age_color, cols, fmt_age, fmt_int, fmt_num, header, table
from services import catalog_service as cat
from services import ingest_service

log = logging.getLogger("sky42.gui.catalogo")


def _stat(label: str, value: str, hint: str = "", color: str = "") -> None:
    with ui.card().classes("min-w-44 gap-0 py-3"):
        ui.label(value).classes(f"text-2xl font-bold {color}")
        ui.label(label).classes("text-sm opacity-80")
        if hint:
            ui.label(hint).classes("text-xs opacity-60")


@ui.page("/catalogo")
def catalogo_page() -> None:
    header("Catalogo")

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):
        # --- riga dei numeri grossi ---------------------------------------
        totals = ui.row().classes("gap-4 flex-wrap")

        # --- sorgenti ------------------------------------------------------
        with ui.row().classes("w-full items-center gap-3"):
            ui.label("Sorgenti").classes("text-xl font-bold")
            ui.space()
            spinner = ui.spinner(size="sm")
            spinner.visible = False
            btn = ui.button("Aggiorna cataloghi", icon="cloud_download")
        sources_box = ui.column().classes("w-full gap-2")
        ui.label(
            "Lo scaricamento è condizionato all'ETag: se la sorgente non è cambiata "
            "non si scaricano 280 MB per scoprirlo."
        ).classes("text-xs opacity-60 -mt-4")

        # --- popolazione di punta -----------------------------------------
        ui.label("Popolazione Tj < 3").classes("text-xl font-bold")
        tj_box = ui.column().classes("w-full gap-3")

        # --- distribuzioni --------------------------------------------------
        with ui.row().classes("w-full gap-6 flex-wrap items-start"):
            ceu_box = ui.column().classes("gap-2 min-w-80 grow")
            obs_box = ui.column().classes("gap-2 min-w-80 grow")

        # --- anteprima ------------------------------------------------------
        ui.label("Asteroidi su orbita cometaria — anteprima").classes("text-xl font-bold")
        ui.label(
            "Ordinati per Tisserand crescente. Non è ancora una lista di osservazione: "
            "manca tutto il calcolo di visibilità."
        ).classes("text-xs opacity-60 -mt-3")
        aco_box = ui.column().classes("w-full")

        # --- job ------------------------------------------------------------
        ui.label("Ultimi lavori").classes("text-xl font-bold")
        jobs_box = ui.column().classes("w-full")

    def redraw() -> None:
        """Ridisegna tutto dai dati nel database. Nessuno stato tenuto in pagina."""
        c = cat.counts()
        totals.clear()
        with totals:
            _stat("oggetti in catalogo", fmt_int(c["target"]))
            _stat("asteroidi", fmt_int(c["asteroidi"]))
            _stat("comete", fmt_int(c["comete"]))
            _stat("numerati", fmt_int(c["numerati"]))
            _stat("con incertezza CEU", fmt_int(c["con_ceu"]), "strato ASTORB")
            _stat("con ultima osservazione", fmt_int(c["con_ultima_oss"]), "solo l'MPC ce l'ha")

        sources_box.clear()
        with sources_box:
            for s in cat.source_status():
                with ui.card().classes("w-full py-3"):
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        ui.label(s["label"]).classes("font-bold min-w-40")
                        # Il badge segue i **dati**, non il download: un import da
                        # file locale popola tutto senza lasciare traccia in
                        # catalog_version, e dire "mai importato" sarebbe falso.
                        ui.badge(fmt_age(s["age_days"])).props(f"color={age_color(s['age_days'])}")
                        ui.label(
                            f"{fmt_int(s['in_db'])} in archivio" if s["in_db"]
                            else "archivio vuoto"
                        ).classes("text-sm min-w-40")
                        ui.label(s["note"]).classes("text-xs opacity-60 grow")
                        if s["downloaded_at"]:
                            ui.label(
                                f"scaricato {fmt_age(s['download_age_days'])}"
                                f" · {s['size_mb'] or '—'} MB"
                            ).classes("text-xs opacity-70")
                        elif s["in_db"]:
                            ui.label("importato da file locale").classes("text-xs opacity-70")
                        else:
                            ui.label("mai scaricato").classes("text-xs opacity-70")

        tj = cat.tisserand_summary()
        tj_box.clear()
        with tj_box:
            with ui.row().classes("gap-4 flex-wrap"):
                _stat("Tj < 3.00", fmt_int(tj["tj_lt_3"]))
                _stat("Tj < 3.05", fmt_int(tj["tj_lt_305"]),
                      f"+{fmt_int(tj['tj_lt_305'] - tj['tj_lt_3'])} con la soglia larga")
                _stat("ACO effettivi", fmt_int(tj["aco"]),
                      "tolte le famiglie risonanti", "text-primary")
            ui.label(
                "Tutti i Troiani di Giove hanno Tj < 3 per costruzione: sono in risonanza 1:1, "
                "cioè il contrario di un asteroide su orbita cometaria. Esclusi: "
                + ", ".join(tj["escluse"])
            ).classes("text-xs opacity-70")
            rows = cat.tisserand_by_class()
            if rows:
                table(cols(("classe", "classe orbitale"), ("n", "oggetti Tj < 3", "right")), rows)

        ceu_box.clear()
        with ceu_box:
            ui.label("Incertezza (CEU) — quanto vale lo strato ASTORB").classes("font-bold")
            rows = [{**r, "quota": f"{r['quota']:.1f}%"} for r in cat.ceu_histogram()]
            table(cols(("fascia", "incertezza"), ("n", "oggetti", "right"),
                       ("quota", "quota", "right")), rows)
            ui.label(
                "Serve nella fascia degli arcominuti: lì decide fra una posa e un mosaico."
            ).classes("text-xs opacity-60")

        obs_box.clear()
        with obs_box:
            ui.label("Da quanto non si osservano — l'asse della rarità").classes("font-bold")
            table(cols(("fascia", "ultima osservazione"), ("n", "oggetti", "right")),
                  cat.last_obs_histogram())
            ui.label(
                "Campo assente in ASTORB: è una delle ragioni per cui la fonte è l'MPC."
            ).classes("text-xs opacity-60")

        aco_box.clear()
        with aco_box:
            table(cols(("oggetto", "oggetto"), ("classe", "classe"), ("tj", "Tj", "right"),
                       ("a", "a (AU)", "right"), ("e", "e", "right"), ("i", "i (°)", "right"),
                       ("q", "q (AU)", "right"), ("H", "H", "right"),
                       ("opp", "opp.", "right"), ("ultima_oss", "ultima oss."),
                       ("ceu", "CEU (\")", "right")),
                  cat.aco_preview(50))

        jobs_box.clear()
        with jobs_box:
            rows = [
                {**j, "n_processed": fmt_int(j["n_processed"]),
                 "error": (j["error"] or "")[:80]}
                for j in cat.recent_jobs()
            ]
            table(cols(("job_name", "lavoro"), ("started_at", "avvio"), ("status", "esito"),
                       ("n_processed", "elementi", "right"), ("durata_s", "durata (s)", "right"),
                       ("error", "errore")), rows)

    async def refresh_catalogs() -> None:
        """Scarica e importa in un processo separato.

        `run.cpu_bound` e non un thread: decomprimere e leggere 1,5 milioni di
        record tiene il GIL, e l'interfaccia deve restare viva mentre lavora.
        """
        btn.disable()
        spinner.visible = True
        ui.notify("Controllo le sorgenti…", type="ongoing")
        try:
            result = await run.cpu_bound(ingest_service.sync_all)
            done = [k for k, v in result.items() if "motivo" not in (v or {})]
            if done:
                ui.notify(f"Aggiornati: {', '.join(done)}", type="positive")
            else:
                ui.notify("Nessuna sorgente è cambiata", type="info")
        except Exception as exc:                      # la pagina non deve morire
            log.exception("aggiornamento cataloghi fallito")
            ui.notify(f"Aggiornamento fallito: {exc}", type="negative")
        finally:
            spinner.visible = False
            btn.enable()
            redraw()

    btn.on_click(refresh_catalogs)
    redraw()
