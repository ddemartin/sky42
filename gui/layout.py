"""Elementi comuni dell'interfaccia: registro delle funzioni, intestazione, formati.

Come in stock42, ogni funzione è una rotta autonoma e la home è un pannello
contenitore. `route=None` significa "progettata ma non ancora costruita": la
card si vede spenta, così la home dice sempre a che punto è il progetto.
"""
from __future__ import annotations

from nicegui import ui

from core.config import APP_NAME

FUNCTIONS = [
    {"key": "catalogo", "title": "Catalogo", "icon": "storage", "route": "/catalogo",
     "desc": "Stato dei cataloghi orbitali: quanti oggetti, da quando, e la popolazione Tj < 3."},
    {"key": "tonight", "title": "Stanotte", "icon": "nights_stay", "route": None,
     "desc": "Cosa osservare stanotte, da quale sito e in quale finestra."},
    {"key": "radar", "title": "Returning radar", "icon": "radar", "route": None,
     "desc": "Chi sta rientrando nella portata dei telescopi dopo mesi o anni."},
    {"key": "comete", "title": "Comete", "icon": "auto_awesome", "route": None,
     "desc": "Comete e candidati cometari: geometria, perielio, finestra osservativa."},
    {"key": "candidati", "title": "Candidati MPC", "icon": "new_releases", "route": None,
     "desc": "NEOCP, PCCP e MPEC: nuovi candidati e il loro destino."},
    {"key": "osservatori", "title": "Osservatori", "icon": "photo_camera", "route": None,
     "desc": "Siti, telescopi, camere e setup, con i limiti misurati sul campo."},
    {"key": "pianificatore", "title": "Pianificatore", "icon": "schedule", "route": "/pianificatore",
     "desc": "Cosa gira da solo: aggiornamenti, backup, manutenzione. Con esito e prossimo giro."},
]


def header(subtitle: str = "") -> None:
    """Intestazione uguale su tutte le pagine: il nome torna sempre alla home."""
    with ui.header().classes("items-center px-4"):
        ui.icon("travel_explore").classes("text-2xl")
        ui.label(APP_NAME).classes("text-xl font-bold cursor-pointer") \
            .on("click", lambda: ui.navigate.to("/"))
        if subtitle:
            ui.label("·").classes("opacity-50")
            ui.label(subtitle).classes("text-sm opacity-80")
        ui.space()
        ui.label("console di follow-up del Sistema Solare").classes("text-sm opacity-60")


def fmt_int(n) -> str:
    """Migliaia con il punto: 1.556.465 si legge, 1556465 no."""
    return "—" if n is None else f"{int(n):,}".replace(",", ".")


def fmt_num(x, dec: int = 2) -> str:
    return "—" if x is None else f"{float(x):.{dec}f}"


def fmt_pct(x, dec: int = 1) -> str:
    return "—" if x is None else f"{float(x):.{dec}f}%"


def fmt_age(days) -> str:
    """Età di un dato in forma leggibile. Un catalogo vecchio deve saltare all'occhio.

    Sotto l'ora si scrivono i minuti: le sorgenti si aggiornano più volte al
    giorno e "adesso" per tutto ciò che è entro un'ora nasconde proprio la
    differenza che interessa dopo un aggiornamento.
    """
    if days is None:
        return "mai"
    minutes = days * 1440
    if minutes < 2:
        return "adesso"
    if minutes < 60:
        return f"{minutes:.0f} min fa"
    if days < 2:
        return f"{days * 24:.0f} h fa"
    if days < 60:
        return f"{days:.0f} giorni fa"
    return f"{days / 365.25:.1f} anni fa"


def age_color(days) -> str:
    """Verde/ambra/rosso sull'età del catalogo. I cataloghi si aggiornano ogni giorno."""
    if days is None:
        return "grey"
    if days <= 2:
        return "positive"
    if days <= 7:
        return "warning"
    return "negative"


def table(columns: list[dict], rows: list[dict], **props) -> ui.table:
    """Tabella con le impostazioni di casa: densa, senza paginazione forzata."""
    t = ui.table(columns=columns, rows=rows, row_key=columns[0]["name"])
    t.props("dense flat bordered wrap-cells")
    t.classes("w-full")
    for k, v in props.items():
        t.props(f"{k}={v}")
    return t


def cols(*specs) -> list[dict]:
    """Colonne da tuple (campo, etichetta) o (campo, etichetta, allineamento)."""
    out = []
    for s in specs:
        field, label = s[0], s[1]
        align = s[2] if len(s) > 2 else "left"
        out.append({"name": field, "label": label, "field": field,
                    "align": align, "sortable": True})
    return out
