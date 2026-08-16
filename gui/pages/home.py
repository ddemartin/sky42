"""Home: il pannello contenitore delle funzioni, con lo stato del catalogo in cima."""
from __future__ import annotations

from nicegui import ui

from gui.layout import FUNCTIONS, age_color, fmt_age, fmt_int, header
from services import catalog_service as cat


def _card(fn: dict) -> None:
    ready = fn["route"] is not None
    with ui.card().classes("w-80 h-40 gap-2") as card:
        with ui.row().classes("w-full items-center gap-2 no-wrap"):
            ui.icon(fn["icon"]).classes("text-2xl")
            ui.label(fn["title"]).classes("text-lg font-bold")
            if not ready:
                ui.badge("presto").props("color=grey")
        ui.label(fn["desc"]).classes("text-sm opacity-80")
    if ready:
        card.classes("cursor-pointer hover:shadow-lg active:shadow-sm transition-shadow")
        card.on("click", lambda f=fn: ui.navigate.to(f["route"]))
    else:
        card.classes("opacity-60")


@ui.page("/")
def home_page() -> None:
    header()
    with ui.column().classes("w-full max-w-6xl mx-auto p-6 gap-5"):
        # Lo stato del catalogo sta in cima e non dentro la sua pagina: se i dati
        # sono vecchi, va saputo prima di guardare qualunque altra cosa.
        counts = cat.counts()
        sources = cat.source_status()
        oldest = max((s["age_days"] for s in sources if s["age_days"] is not None), default=None)
        with ui.card().classes("w-full py-3"):
            with ui.row().classes("w-full items-center gap-4 no-wrap"):
                ui.icon("storage").classes("text-xl opacity-70")
                ui.label(f"{fmt_int(counts['target'])} oggetti").classes("font-bold")
                ui.label(f"{fmt_int(counts['comete'])} comete").classes("opacity-80")
                ui.badge(f"catalogo {fmt_age(oldest)}").props(f"color={age_color(oldest)}")
                ui.space()
                ui.button("Catalogo", icon="arrow_forward") \
                    .props("flat dense").on("click", lambda: ui.navigate.to("/catalogo"))

        ui.label("Funzioni").classes("text-2xl font-bold")
        with ui.row().classes("gap-4 flex-wrap"):
            for fn in FUNCTIONS:
                _card(fn)
