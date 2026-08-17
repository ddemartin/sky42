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
    {"key": "oggetto", "title": "Oggetto", "icon": "my_location", "route": "/oggetto",
     "desc": "Effemeride di un oggetto del catalogo: posizione, distanza, magnitudine, moto."},
    {"key": "tonight", "title": "Stanotte", "icon": "nights_stay", "route": "/stanotte",
     "desc": "Cosa osservare stanotte, da quale sito e in quale finestra."},
    {"key": "radar", "title": "Returning radar", "icon": "radar", "route": None,
     "desc": "Chi sta rientrando nella portata dei telescopi dopo mesi o anni."},
    {"key": "comete", "title": "Comete", "icon": "auto_awesome", "route": None,
     "desc": "Comete e candidati cometari: geometria, perielio, finestra osservativa."},
    {"key": "candidati", "title": "Candidati MPC", "icon": "new_releases",
     "route": "/candidati",
     "desc": "NEOCP e PCCP: nuovi candidati, la loro evoluzione, e chi sparisce."},
    {"key": "osservatori", "title": "Osservatori", "icon": "photo_camera", "route": "/osservatori",
     "desc": "Siti, telescopi, camere e setup, con i limiti misurati sul campo."},
    {"key": "pianificatore", "title": "Pianificatore", "icon": "schedule", "route": "/pianificatore",
     "desc": "Cosa gira da solo: aggiornamenti, backup, manutenzione. Con esito e prossimo giro."},
]


# Il colore di casa. Il celestino è quello di serie di NiceGUI, cioè quello di
# stock42: con due schede aperte sullo stesso schermo non si distingue quale sia
# quale. Un rosso scuro tiene il contrasto con il bianco della barra in tema
# chiaro e in tema scuro, e nessun'altra app di casa lo usa.
PRIMARY = "#8B1A1A"


def header(subtitle: str = "") -> None:
    """Intestazione uguale su tutte le pagine: il nome torna sempre alla home.

    `ui.colors` va chiamata dentro la pagina e non una volta all'avvio: in
    NiceGUI è un elemento, e ogni pagina è un albero suo. Sta qui perché
    l'intestazione è l'unica cosa che tutte le pagine hanno in comune.
    """
    ui.colors(primary=PRIMARY)
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


def fmt_ra_hms(deg) -> str:
    """RA in ore, minuti, secondi: è così che si punta un telescopio."""
    if deg is None:
        return "—"
    ore = (float(deg) % 360.0) / 15.0
    h = int(ore)
    m = int((ore - h) * 60)
    s = (ore - h - m / 60) * 3600
    return f"{h:02d}h {m:02d}m {s:05.2f}s"


def fmt_dec_dms(deg) -> str:
    if deg is None:
        return "—"
    d = float(deg)
    segno = "-" if d < 0 else "+"
    d = abs(d)
    g = int(d)
    m = int((d - g) * 60)
    s = (d - g - m / 60) * 3600
    return f"{segno}{g:02d}° {m:02d}' {s:04.1f}\""


def fmt_duration(days) -> str:
    """Una durata, senza dire da che parte del presente sta: «30 min», «12 h».

    Sotto l'ora si scrivono i minuti: le sorgenti si aggiornano più volte al
    giorno e "adesso" per tutto ciò che è entro un'ora nasconde proprio la
    differenza che interessa dopo un aggiornamento.

    Sta separata da `fmt_age` perché la stessa scala serve **anche al futuro**,
    e le due direzioni hanno parole diverse: «fa» e «fra» non si compongono
    dallo stesso pezzo di testo. Metterle insieme è già costato un «fra 13 min
    fa» in pagina.
    """
    minutes = days * 1440
    if minutes < 60:
        return f"{minutes:.0f} min"
    if days < 2:
        return f"{days * 24:.0f} h"
    if days < 60:
        return f"{days:.0f} giorni"
    return f"{days / 365.25:.1f} anni"


def fmt_age(days) -> str:
    """Quanto tempo fa. Un catalogo vecchio deve saltare all'occhio."""
    if days is None:
        return "mai"
    if days * 1440 < 2:
        return "adesso"
    return f"{fmt_duration(days)} fa"


def fmt_delay(days) -> str:
    """Fra quanto. Il gemello di `fmt_age` per gli istanti che devono ancora venire.

    Un ritardo — un lavoro che doveva partire e non è partito — non si scrive
    come un tempo negativo: `fra -3 min` è un modo di dire «non lo so» che
    sembra un dato. Si dice «in ritardo», che è quello che è.
    """
    if days is None:
        return "mai"
    if days < 0 and days * 1440 < -2:
        return f"in ritardo di {fmt_duration(-days)}"
    if days * 1440 < 2:
        return "a momenti"
    return f"fra {fmt_duration(days)}"


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
