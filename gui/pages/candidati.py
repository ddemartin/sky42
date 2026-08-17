"""Pagina Candidati: la lista NEOCP e PCCP, e la storia che nessun altro tiene.

Serve a tre domande diverse, e per questo ci sono tre elenchi:

* **chi è in lista adesso**, ordinato per quanto è urgente — score alto e
  «non ripreso da» che cresce vuol dire un candidato che si sta per perdere;
* **che fine hanno fatto** quelli usciti: NEO confermato con la sua circolare,
  pianetino designato, perso, inesistente. È la parte che l'MPC pubblica in una
  tabella che tiene quattro giorni, e che dopo non esiste più da nessuna parte;
* **chi è sparito e non ha ancora una risposta**: la lista di quello che
  stiamo non sapendo. Più resta corta, meglio funziona il controllo.

Nessun calcolo qui dentro: le liste arrivano da `candidate_service`.
"""
from __future__ import annotations

import logging

from nicegui import run, ui

from core.timeutil import days_since
from gui.layout import (cols, fmt_age, fmt_dec_dms, fmt_duration, fmt_int, fmt_num,
                        fmt_ra_hms, header, table)
from services import candidate_service as cand

log = logging.getLogger("sky42.gui.candidati")

# Sopra questo score l'MPC lo considera quasi certamente un NEO.
SCORE_ALTO = 90

# Da quanti giorni senza riprese un candidato è «in fuga»: gli oggetti della
# NEOCP hanno archi di ore, e due giorni senza osservazioni sono spesso la
# differenza fra un recupero e un oggetto perso.
IN_FUGA_GIORNI = 2.0

# I sei destini dello schema, in italiano. `unknown` non è «non lo sappiamo
# ancora» (quello è NULL, e quei candidati stanno nell'altro elenco): è «l'MPC
# l'ha chiuso in un modo che non sappiamo tradurre».
DESTINI = {
    "confirmed_neo": "NEO confermato",
    "confirmed_comet": "cometa confermata",
    "known_object": "pianetino designato",
    "not_confirmed": "perso, mai confermato",
    "removed": "tolto dalla lista",
    "unknown": "chiuso, motivo non tradotto",
}


def _durata(c: dict) -> str:
    """Quanto è rimasto in lista: dal primo avvistamento alla decisione dell'MPC."""
    from core.timeutil import days_since

    if not c["resolved_at"] or not c["first_seen"]:
        return "—"
    giorni = days_since(c["first_seen"]) - (days_since(c["resolved_at"]) or 0)
    return fmt_duration(giorni) if giorni > 0 else "—"


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
        destino_box = ui.column().classes("w-full gap-2")
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

        destino_box.clear()
        with destino_box:
            chiusi = cand.resolved_candidates()
            ui.label("Che fine hanno fatto").classes("text-xl font-bold")
            if not chiusi:
                ui.label("Nessun candidato ancora chiuso. La tabella dell'MPC "
                         "tiene quattro giorni, e il controllo gira ogni "
                         "mezz'ora.").classes("opacity-70")
            else:
                ui.label(
                    "Dalla tabella dei trksub usciti di lista: designato con "
                    "circolare, designato e basta (un pianetino ordinario, che è "
                    "come finiscono quasi tutti), perso, inesistente, o "
                    "identificato con un altro candidato."
                ).classes("text-xs opacity-60")
                table(
                    cols(("desig", "designazione"), ("lista", "lista"),
                         ("destino", "destino"), ("diventato", "diventato"),
                         ("classe", "classe"), ("quando", "chiuso il"),
                         ("durata", "in lista per"), ("fonte", "fonte")),
                    [{
                        "desig": c["temp_desig"], "lista": c["list"],
                        "destino": DESTINI.get(c["resolution"], c["resolution"]),
                        "diventato": c["target_name"] or c["resolved_desig"] or "—",
                        "classe": c["orbit_class"] or "—",
                        "quando": (c["resolved_at"] or "")[:16].replace("T", " "),
                        "durata": _durata(c),
                        "fonte": c["resolution_source"] or "—",
                    } for c in chiusi],
                )

        spariti_box.clear()
        with spariti_box:
            spariti = cand.recent_departures()
            ui.label("Spariti dalla lista, e ancora senza risposta").classes(
                "text-xl font-bold")
            if not spariti:
                ui.label("Nessuno: ogni candidato uscito di lista ha il suo "
                         "perché.").classes("opacity-70")
                return
            ui.label(
                "La tabella dell'MPC copre quattro giorni: chi è sparito prima "
                "che il controllo esistesse non ha più una risposta da nessuna "
                "parte. Questa lista è quello che stiamo non sapendo."
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
            # Le liste dicono chi c'è; la tabella dei trksub usciti dice com'è
            # finita. Interrogare l'MPC a mano e non chiedere anche quello
            # lascerebbe la pagina a metà.
            destino = await run.io_bound(cand.poll_destiny)
            ui.notify(f"destino: {destino['risolti']} candidati chiusi",
                      type="positive")
        except Exception as exc:  # la pagina non deve morire se l'MPC non risponde
            log.exception("polling manuale fallito")
            ui.notify(f"non ha funzionato: {exc}", type="negative")
        redraw()

    redraw()


def _giorni(x) -> str:
    return "—" if x is None else f"{float(x):.2f} g"
