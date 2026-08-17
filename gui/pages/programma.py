"""Pagina Programma: cosa ho deciso di osservare, e com'è andata.

È il lato dell'utente della console: le altre pagine suggeriscono, questa
registra le decisioni. Tre elenchi, e il secondo è quello che il progetto non
aveva:

* **aperti** — i propositi in piedi, con accanto com'è messo l'oggetto *adesso*
  e la finestra migliore fra quelle calcolate;
* **chiusi** — osservati, scaduti o lasciati perdere, **con il motivo**. Un
  proposito scaduto per `out_of_range` dice «bisognava muoversi prima»; uno
  scaduto per `no_window` dice «serviva un altro sito». Sono due lezioni
  diverse, e sono l'unica cosa che resta di un'occasione persa;
* **sessioni** — quello che si è ripreso davvero.

Nessun calcolo: tutto arriva da `intent_service`.
"""
from __future__ import annotations

import logging

from nicegui import app, run, ui

from gui.layout import (cols, fmt_age, fmt_int, fmt_num, header, link_oggetto,
                        table)
from services import intent_service as prop

log = logging.getLogger("sky42.gui.programma")

MOTIVI = {
    "out_of_range": "sceso sotto il limite",
    "no_window": "niente finestra utile da lì",
    "deadline": "scaduta la data che avevo messo",
    "observed": "osservato",
    "manuale": "lasciato perdere",
}

STATI = {"planned": ("in programma", "primary"), "observed": ("osservato", "positive"),
         "expired": ("occasione passata", "warning"), "dropped": ("lasciato", "grey")}


@ui.page("/programma")
def programma_page() -> None:
    header("Programma")

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-5"):
        intestazione = ui.row().classes("w-full items-center gap-3")
        aggiungi = ui.row().classes("w-full items-end gap-3")
        aperti_box = ui.column().classes("w-full gap-2")
        chiusi_box = ui.column().classes("w-full gap-2")
        sessioni_box = ui.column().classes("w-full gap-2")

    async def redraw() -> None:
        dati = await run.io_bound(prop.overview)
        n = await run.io_bound(prop.counts)
        _intestazione(n, intestazione, redraw)
        _aperti(dati["open"], aperti_box, redraw)
        _chiusi(dati["closed"], chiusi_box, redraw)
        _sessioni(dati["sessions"], sessioni_box)

    _form(aggiungi, redraw)
    ui.timer(0.1, redraw, once=True)


def _form(box, redraw) -> None:
    """Aggiungere a mano: la scorciatoia per quando si sa già cosa si vuole."""
    with box:
        campo = ui.input("Designazione", placeholder="3200, C/2019 E3, Ceres") \
            .props("outlined dense").classes("grow")
        scopo = ui.input("Scopo", placeholder="astrometria, attività cometaria") \
            .props("outlined dense").classes("grow")

        async def aggiungi() -> None:
            if not campo.value:
                return
            p = await run.io_bound(prop.add, campo.value, None, scopo.value or None,
                                   0, "programma")
            if p is None:
                ui.notify(f"«{campo.value}» non è in catalogo", type="negative")
                return
            ui.notify(f"{p['desig']} è in programma", type="positive")
            campo.value = ""
            await redraw()

        ui.button("Voglio osservarlo", icon="add_task").on("click", aggiungi)


def _intestazione(n: dict, box, redraw) -> None:
    box.clear()
    with box:
        ui.label("Programma osservativo").classes("text-2xl font-bold")
        for stato, (etichetta, colore) in STATI.items():
            ui.badge(f"{etichetta}: {n['per_stato'][stato]}").props(f"color={colore}")
        ui.label(f"{fmt_int(n['sessioni'])} sessioni · "
                 f"{fmt_int(n['riportate'])} riportate all'MPC").classes("text-sm opacity-70")
        ui.space()
        ui.button("Aggiorna", icon="refresh").props("flat dense").on("click", redraw)


def _aperti(righe: list[dict], box, redraw) -> None:
    box.clear()
    with box:
        ui.label("In programma").classes("text-xl font-bold")
        if not righe:
            ui.label("Niente in programma. Dalla pagina Stanotte, il pulsante "
                     "«Osserva» mette qui quel che si decide.").classes("opacity-70")
            return
        for r in righe:
            _scheda(r, redraw)


def _scheda(r: dict, redraw) -> None:
    with ui.card().classes("w-full py-3"):
        with ui.row().classes("w-full items-center gap-4 no-wrap"):
            with ui.column().classes("gap-0 min-w-64"):
                ui.label(r["display_name"] or r["desig"]).classes("font-bold cursor-pointer") \
                    .on("click", lambda d=r["desig"]: ui.navigate.to(link_oggetto(d)))
                pezzi = [f"deciso {fmt_age(_giorni(r['created_at']))}"]
                if r["setup_code"]:
                    pezzi.append(f"con {r['setup_code']}")
                if r["purpose"]:
                    pezzi.append(r["purpose"])
                ui.label(" · ".join(pezzi)).classes("text-xs opacity-60")

            with ui.column().classes("gap-0 min-w-56"):
                # Com'è messo **adesso**, non quando l'ho deciso: è la domanda
                # per cui si apre questa pagina.
                with ui.row().classes("items-center gap-2 no-wrap"):
                    ui.label(f"adesso: {r['state'] or '—'} · V {fmt_num(r['v_now'], 1)}") \
                        .classes("text-sm")
                    # `FADING` non è «è andata»: è «è l'ultima occasione», e va
                    # detto forte perché è quello da fare per primo.
                    if r.get("ultima_occasione"):
                        ui.badge("ultima occasione").props("color=warning")
                t = r["tonight"]
                if t and (t["useful_hours"] or 0) > 0:
                    ui.label(f"{t['night_date']}: {fmt_num(t['useful_hours'], 1)} h utili "
                             f"da {t['setup_code']} · {t['grade']}") \
                        .classes("text-xs text-positive")
                elif t:
                    ui.label(f"{t['night_date']}: nessuna finestra utile") \
                        .classes("text-xs opacity-70")
                else:
                    ui.label("nessuna finestra calcolata").classes("text-xs opacity-50")

            with ui.column().classes("gap-0 min-w-40"):
                ctx = (r["context"] or {}).get("radar") or {}
                ui.label(f"quando l'ho deciso: {ctx.get('state', '—')}") \
                    .classes("text-xs opacity-60")
                if r["v_trend_mag_month"] is not None:
                    verso = "migliora" if r["v_trend_mag_month"] < 0 else "peggiora"
                    ui.label(f"{verso} di {abs(r['v_trend_mag_month']):.2f} mag/mese") \
                        .classes("text-xs opacity-60")

            ui.space()
            with ui.row().classes("gap-1"):
                ui.button("Osservato", icon="check").props("flat dense") \
                    .on("click", lambda i=r: _dialogo_sessione(i, redraw))
                ui.button("Lascio perdere", icon="close").props("flat dense") \
                    .on("click", lambda i=r["id"]: _lascia(i, redraw))


def _dialogo_sessione(intent: dict, redraw) -> None:
    """La sessione: pochi campi obbligatori, il resto quando si sa.

    Le misure di qualità (FWHM, SNR, magnitudine limite, residui) arrivano
    *dopo* l'elaborazione, e infatti restano vuote qui e si riempiono più tardi.
    Chiederle al momento della ripresa vorrebbe dire non compilarle mai.
    """
    from core.timeutil import now_iso

    with ui.dialog() as dialogo, ui.card().classes("w-[36rem] gap-3"):
        ui.label(f"Sessione su {intent['display_name'] or intent['desig']}") \
            .classes("text-lg font-bold")
        quando = ui.input("Inizio UT", value=now_iso()).props("outlined dense")
        with ui.row().classes("w-full gap-2 no-wrap"):
            n_pose = ui.number("Pose", value=None, format="%d").props("outlined dense")
            posa = ui.number("Posa singola (s)", value=None).props("outlined dense")
        esito = ui.select(["detected", "not_detected", "clouded", "aborted"],
                          value="detected", label="Esito").props("outlined dense")
        with ui.row().classes("w-full gap-2 no-wrap"):
            mag = ui.number("V misurata", value=None).props("outlined dense")
            limite = ui.number("Mag. limite raggiunta", value=None).props("outlined dense")
        cartella = ui.input("Cartella d'archivio").props("outlined dense")
        nota = ui.input("Note").props("outlined dense")

        async def salva() -> None:
            totale = ((n_pose.value or 0) * (posa.value or 0)) or None
            await run.io_bound(
                lambda: prop.log_observation(
                    intent["desig"], obs_start=quando.value,
                    setup_code=intent["setup_code"], intent_id=intent["id"],
                    n_frames=int(n_pose.value) if n_pose.value else None,
                    exposure_s=posa.value, total_exposure_s=totale,
                    outcome=esito.value, measured_mag=mag.value,
                    limiting_mag=limite.value, archive_folder=cartella.value or None,
                    note=nota.value or None))
            dialogo.close()
            ui.notify("sessione registrata", type="positive")
            await redraw()

        with ui.row().classes("w-full justify-end gap-2"):
            ui.button("Annulla").props("flat").on("click", dialogo.close)
            ui.button("Registra", icon="save").on("click", salva)
    dialogo.open()


async def _lascia(intent_id: int, redraw) -> None:
    await run.io_bound(prop.drop, intent_id)
    ui.notify("lasciato perdere — resta in elenco, con il suo motivo")
    await redraw()


def _chiusi(righe: list[dict], box, redraw) -> None:
    box.clear()
    with box:
        ui.label("Come sono andati").classes("text-xl font-bold")
        if not righe:
            ui.label("Ancora niente di chiuso.").classes("opacity-70")
            return
        ui.label(
            "«Sceso sotto il limite» e «niente finestra da lì» sono due modi "
            "diversi di perdere un'occasione: il primo dice che bisognava "
            "muoversi prima, il secondo che serviva un altro sito."
        ).classes("text-xs opacity-60")
        table(
            cols(("oggetto", "oggetto"), ("stato", "com'è finita"),
                 ("motivo", "perché"), ("setup", "setup"),
                 ("deciso", "deciso il"), ("chiuso", "chiuso il"),
                 ("allora", "stato di allora"), ("adesso", "stato adesso")),
            [{
                "oggetto": r["display_name"] or r["desig"],
                "stato": STATI.get(r["status"], (r["status"], ""))[0],
                "motivo": MOTIVI.get(r["closed_reason"], r["closed_reason"] or "—"),
                "setup": r["setup_code"] or "qualunque",
                "deciso": r["created_at"][:10],
                "chiuso": (r["status_at"] or "")[:10],
                "allora": ((r["context"] or {}).get("radar") or {}).get("state", "—"),
                "adesso": r["state"] or "—",
            } for r in righe])


def _sessioni(righe: list[dict], box) -> None:
    box.clear()
    with box:
        ui.label("Sessioni").classes("text-xl font-bold")
        if not righe:
            ui.label("Nessuna sessione registrata.").classes("opacity-70")
            return
        ui.label("La magnitudine limite raggiunta è il numero che tara i "
                 "`vlim_ref` dichiarati: misurata batte stimata.") \
            .classes("text-xs opacity-60")
        table(
            cols(("quando", "inizio UT"), ("oggetto", "oggetto"), ("setup", "setup"),
                 ("pose", "pose", "right"), ("posa", "posa (s)", "right"),
                 ("esito", "esito"), ("v", "V misurata", "right"),
                 ("limite", "mag. limite", "right"), ("fwhm", "FWHM", "right"),
                 ("mpc", "a MPC"), ("cartella", "archivio")),
            [{
                "quando": (r["obs_start"] or "")[:16].replace("T", " "),
                "oggetto": r["display_name"] or r["desig"] or "—",
                "setup": r["setup_code"] or "—",
                "pose": fmt_int(r["n_frames"]),
                "posa": fmt_num(r["exposure_s"], 0),
                "esito": r["outcome"] or "—",
                "v": fmt_num(r["measured_mag"], 1),
                "limite": fmt_num(r["limiting_mag"], 1),
                "fwhm": fmt_num(r["fwhm_arcsec"], 1),
                "mpc": r["reported_mpc"] or "—",
                "cartella": r["archive_folder"] or "—",
            } for r in righe])


def _giorni(iso: str | None):
    from core.timeutil import days_since

    return days_since(iso)


@app.get("/api/programma")
def programma_json(limit: int = 100) -> dict:
    """Il gemello JSON: la stessa chiamata della pagina."""
    return {**prop.overview(limit), "counts": prop.counts()}
