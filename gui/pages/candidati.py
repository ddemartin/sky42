"""Pagina Candidati: la lista NEOCP e PCCP, e la storia che nessun altro tiene.

Serve a due domande diverse, e per questo ci sono due elenchi:

* **chi è in lista adesso**, ordinato per quanto è urgente — score alto e
  «non ripreso da» che cresce vuol dire un candidato che si sta per perdere;
* **chi è sparito**, che è la parte che l'MPC non conserva. Finché non c'è il
  watcher MPEC, il destino resta ignoto e la pagina lo dice invece di far
  finta che quei candidati non siano mai esistiti.

Nessun calcolo qui dentro: le liste arrivano da `candidate_service`.
"""
from __future__ import annotations

import logging

from nicegui import run, ui

from core.timeutil import days_since
from gui.layout import cols, fmt_age, fmt_dec_dms, fmt_int, fmt_num, fmt_ra_hms, header, table
from services import candidate_service as cand

log = logging.getLogger("sky42.gui.candidati")

# Sopra questo score l'MPC lo considera quasi certamente un NEO.
SCORE_ALTO = 90

# Da quanti giorni senza riprese un candidato è «in fuga»: gli oggetti della
# NEOCP hanno archi di ore, e due giorni senza osservazioni sono spesso la
# differenza fra un recupero e un oggetto perso.
IN_FUGA_GIORNI = 2.0


@ui.page("/candidati")
def candidati_page() -> None:
    header("Candidati MPC")

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-5"):
        intestazione = ui.row().classes("w-full items-center gap-3")
        ui.label(
            "L'MPC riscrive queste liste e non conserva niente: un candidato che entra "
            "alle 02:10 e sparisce alle 05:40 esiste solo qui. Per questo si guarda ogni "
            "dieci minuti, e per questo `mpc_candidate` sta nel backup."
        ).classes("text-xs opacity-60 -mt-3")

        aperti_box = ui.column().classes("w-full gap-2")
        spariti_box = ui.column().classes("w-full gap-2")

    def redraw() -> None:
        n = cand.counts()
        intestazione.clear()
        with intestazione:
            for lista in ("NEOCP", "PCCP"):
                ui.badge(f"{lista}: {n[lista]['aperti']} in lista") \
                    .props("color=primary")
            ui.label(f"{fmt_int(n['NEOCP']['visti'] + n['PCCP']['visti'])} visti in tutto · "
                     f"{fmt_int(n['snapshot'])} istantanee").classes("text-sm opacity-70")
            ui.space()
            ui.button("Aggiorna", icon="refresh").props("flat dense").on("click", redraw)
            ui.button("Interroga l'MPC", icon="cloud_download").props("flat dense") \
                .on("click", _poll_now)

        aperti_box.clear()
        with aperti_box:
            ui.label("In lista adesso").classes("text-xl font-bold")
            righe = cand.open_candidates()
            if not righe:
                ui.label("Nessun candidato in lista. Se è appena stato installato, "
                         "il primo giro arriva entro dieci minuti.").classes("opacity-70")
            else:
                ui.label(
                    "Ordinati per score e per quanto tempo è passato dall'ultima "
                    "osservazione: in cima c'è quello che si sta per perdere."
                ).classes("text-xs opacity-60")
                table(
                    cols(("desig", "designazione"), ("lista", "lista"),
                         ("score", "score", "right"), ("v", "V", "right"),
                         ("ra", "RA"), ("dec", "Dec"),
                         ("nobs", "oss.", "right"), ("arco", "arco (h)", "right"),
                         ("h", "H", "right"), ("nonvisto", "non ripreso da", "right"),
                         ("visto", "in lista da")),
                    [{
                        "desig": c["temp_desig"],
                        "lista": c["list"],
                        "score": fmt_num(c["score"], 0),
                        "v": fmt_num(c["v_mag"], 1),
                        "ra": fmt_ra_hms(c["ra_deg"]),
                        "dec": fmt_dec_dms(c["dec_deg"]),
                        "nobs": fmt_int(c["n_obs"]),
                        "arco": fmt_num(c["arc_hours"], 1),
                        "h": fmt_num(c["h_mag"], 1),
                        "nonvisto": _giorni(c["not_seen_days"]),
                        "visto": fmt_age(days_since(c["first_seen"])),
                    } for c in righe],
                )
                _riassunto(righe)

        spariti_box.clear()
        with spariti_box:
            spariti = cand.recent_departures()
            ui.label("Spariti dalla lista negli ultimi sette giorni").classes(
                "text-xl font-bold")
            if not spariti:
                ui.label("Nessuno.").classes("opacity-70")
                return
            ui.label(
                "Designati, identificati con un oggetto noto, o scartati per "
                "osservazioni insufficienti: quale dei tre lo dirà il watcher MPEC. "
                "Finché non c'è, questa lista è quello che stiamo non sapendo."
            ).classes("text-xs opacity-60")
            table(
                cols(("desig", "designazione"), ("lista", "lista"),
                     ("score", "score", "right"), ("v", "V", "right"),
                     ("nobs", "oss.", "right"), ("dal", "prima volta"),
                     ("al", "ultima volta")),
                [{
                    "desig": c["temp_desig"], "lista": c["list"],
                    "score": fmt_num(c["score"], 0), "v": fmt_num(c["v_mag"], 1),
                    "nobs": fmt_int(c["n_obs"]),
                    "dal": c["first_seen"][:16].replace("T", " "),
                    "al": c["last_seen"][:16].replace("T", " "),
                } for c in spariti],
            )

    def _riassunto(righe: list[dict]) -> None:
        alti = [c for c in righe if (c["score"] or 0) >= SCORE_ALTO]
        fuga = [c for c in alti if (c["not_seen_days"] or 0) >= IN_FUGA_GIORNI]
        with ui.row().classes("gap-6 flex-wrap text-sm"):
            ui.label(f"{len(alti)} con score ≥ {SCORE_ALTO}")
            if fuga:
                ui.badge(f"{len(fuga)} non ripresi da più di {IN_FUGA_GIORNI:.0f} giorni") \
                    .props("color=warning")

    async def _poll_now() -> None:
        ui.notify("interrogo l'MPC…", type="ongoing")
        try:
            for lista in ("NEOCP", "PCCP"):
                esito = await run.io_bound(cand.poll, lista)
                ui.notify(f"{lista}: {esito['in_lista']} in lista, "
                          f"{esito['nuovi']} nuovi, {esito['spariti']} spariti",
                          type="positive")
        except Exception as exc:  # la pagina non deve morire se l'MPC non risponde
            log.exception("polling manuale fallito")
            ui.notify(f"non ha funzionato: {exc}", type="negative")
        redraw()

    redraw()


def _giorni(x) -> str:
    return "—" if x is None else f"{float(x):.2f} g"
