"""Pagina Osservatori: siti, telescopi, camere e setup, come li vede il calcolo.

Non è un inventario: è la verifica che i numeri con cui si deciderà cosa
osservare siano quelli giusti. Scala del pixel e campo si vedono **derivati**,
accanto ai loro ingredienti, perché è così che ci si accorge di un riduttore
dichiarato male — un campo di 27' che diventa 41' salta all'occhio, un
`focal_reducer: 0.67` copiato dal telescopio sbagliato no.
"""
from __future__ import annotations

import logging

from nicegui import run, ui

from core.sites.reconcile import SiteConfigError
from gui.layout import cols, fmt_age, fmt_num, header, table
from services import night_service as notti
from services import sites_service as sites

log = logging.getLogger("sky42.gui.osservatori")


def _stat(label: str, value: str, hint: str = "") -> None:
    with ui.card().classes("min-w-40 gap-0 py-3"):
        ui.label(value).classes("text-2xl font-bold")
        ui.label(label).classes("text-sm opacity-80")
        if hint:
            ui.label(hint).classes("text-xs opacity-60")


def _coord(lat: float, lon: float) -> str:
    """Gradi con l'emisfero scritto: −30.4728 è chiaro solo a chi l'ha scritto."""
    ns = "N" if lat >= 0 else "S"
    ew = "E" if lon >= 0 else "W"
    return f"{abs(lat):.4f}° {ns}, {abs(lon):.4f}° {ew}"


def _ora_locale(jd, timezone: str) -> str:
    """JD → ora locale del sito. È l'unico posto in cui l'ora locale esiste.

    Un tramonto scritto in UTC non dice niente a chi deve decidere se stasera
    vale la pena: le 22:18 UTC sono le 18:18 in Cile.
    """
    if jd is None:
        return "—"
    from zoneinfo import ZoneInfo

    from core.timeutil import datetime_from_jd, jd_utc_from_tdb

    return datetime_from_jd(jd_utc_from_tdb(jd)).astimezone(
        ZoneInfo(timezone)).strftime("%H:%M")


def _notti(sito: dict) -> None:
    """Le prossime notti del sito: buio disponibile e quanto disturba la Luna."""
    righe = notti.upcoming(sito["id"], limit=10)
    ui.label("Prossime notti").classes("font-bold mt-2")
    if not righe:
        ui.label(
            "Non ancora calcolate: le scrive il lavoro «Piano delle notti», "
            "che gira ogni sei ore e all'avvio."
        ).classes("text-xs opacity-70")
        return

    tz = sito["timezone"]
    table(
        cols(("data", "notte"), ("tramonto", "tramonto", "right"),
             ("buio", "buio da", "right"), ("fine", "buio fino a", "right"),
             ("alba", "alba", "right"), ("ore", "ore di buio", "right"),
             ("luna", "Luna", "right"), ("luna_su", "Luna in cielo")),
        [{
            "data": r["night_date"],
            "tramonto": _ora_locale(r["sunset_jd"], tz),
            "buio": _ora_locale(r["twilight_end_jd"], tz),
            "fine": _ora_locale(r["twilight_start_jd"], tz),
            "alba": _ora_locale(r["sunrise_jd"], tz),
            "ore": fmt_num(r["dark_hours"], 1),
            # Frazione illuminata e altezza massima insieme: una Luna piena che
            # resta sotto l'orizzonte non disturba nessuno, e il solo numero
            # della fase farebbe scartare una notte buona.
            "luna": f"{r['moon_illum'] * 100:.0f}%",
            "luna_su": (f"max {fmt_num(r['moon_max_alt_deg'], 0)}° · "
                        f"sorge {_ora_locale(r['moon_rise_jd'], tz)}, "
                        f"tramonta {_ora_locale(r['moon_set_jd'], tz)}"),
        } for r in righe],
    )
    ui.label(
        "Orari in ora locale del sito. «Buio» è il crepuscolo astronomico "
        "(Sole a −18°); quanto crepuscolo accettare lo decide il setup."
    ).classes("text-xs opacity-60")


@ui.page("/osservatori")
def osservatori_page() -> None:
    header("Osservatori")

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-6"):
        with ui.row().classes("w-full items-center gap-3"):
            ui.label("Hardware osservativo").classes("text-xl font-bold")
            ui.space()
            spinner = ui.spinner(size="sm")
            spinner.visible = False
            btn = ui.button("Riallinea dai file", icon="sync")
        ui.label(
            "La fonte di verità sono i file YAML in config/sites/, versionati in git: "
            "il database li indicizza e il riallineamento è idempotente. Ciò che sparisce "
            "da un file non viene cancellato ma disattivato — le osservazioni fatte con "
            "quel setup devono restare leggibili."
        ).classes("text-xs opacity-60 -mt-4")

        stato_box = ui.row().classes("w-full items-center gap-3")
        totali = ui.row().classes("gap-4 flex-wrap")
        siti_box = ui.column().classes("w-full gap-6")

    def redraw() -> None:
        ultimo = sites.last_reconcile()
        stato_box.clear()
        with stato_box:
            if ultimo is None:
                ui.badge("mai riallineato").props("color=grey")
            else:
                from core.timeutil import days_since

                colore = "positive" if ultimo["status"] == "ok" else "negative"
                ui.badge(f"riallineato {fmt_age(days_since(ultimo['started_at']))}") \
                    .props(f"color={colore}")
                if ultimo["error"]:
                    ui.label(ultimo["error"]).classes("text-xs text-negative")

        c = sites.counts()
        totali.clear()
        with totali:
            for chiave, etichetta in (("observatory", "siti"), ("telescope", "telescopi"),
                                      ("camera", "camere"), ("setup", "setup")):
                n = c[chiave]
                dismessi = n["totali"] - n["attivi"]
                _stat(etichetta, str(n["attivi"]),
                      f"+{dismessi} dismessi" if dismessi else "")

        siti_box.clear()
        with siti_box:
            elenco = sites.overview()
            if not elenco:
                ui.label(
                    "Nessun sito in archivio. Il riallineamento legge config/sites/*.yml."
                ).classes("opacity-70")
                return

            for sito in elenco:
                with ui.card().classes("w-full gap-3"):
                    with ui.row().classes("w-full items-center gap-3 no-wrap"):
                        ui.icon("place").classes("text-xl opacity-70")
                        ui.label(sito["name"]).classes("text-lg font-bold")
                        ui.badge(sito["code"]).props("color=grey outline")
                        if not sito["active"]:
                            ui.badge("dismesso").props("color=negative")
                        if sito["mpc_code"]:
                            ui.badge(f"MPC {sito['mpc_code']}").props("color=primary outline")
                        ui.space()
                        ui.label(_coord(sito["latitude"], sito["longitude"])) \
                            .classes("text-sm opacity-80")
                        ui.label(f"{fmt_num(sito['altitude_m'], 0)} m").classes("text-sm opacity-80")
                        ui.label(sito["timezone"]).classes("text-sm opacity-60")

                    with ui.row().classes("gap-6 text-sm opacity-80 flex-wrap"):
                        ui.label(f"cielo allo zenit {fmt_num(sito['sky_zenith_mag'])} mag/arcsec²")
                        ui.label(f"estinzione k = {fmt_num(sito['extinction_k'])} mag/airmass")
                        ui.label("orizzonte locale: "
                                 + ("definito" if sito["horizon_json"] else "nessuno"))

                    ui.label("Setup").classes("font-bold mt-2")
                    table(
                        cols(("code", "setup"), ("telescope_name", "telescopio"),
                             ("camera_name", "camera"), ("bin", "bin", "right"),
                             ("filtro", "filtro"), ("scala", "scala (\"/px)", "right"),
                             ("campo", "campo (')", "right"), ("f", "f/", "right"),
                             ("vlim", "V lim", "right"), ("posa", "posa (s)", "right"),
                             ("alt", "alt. min (°)", "right"), ("airmass", "airmass max", "right"),
                             ("stato", "stato")),
                        [{
                            "code": s["code"],
                            "telescope_name": s["telescope_name"],
                            "camera_name": s["camera_name"],
                            "bin": s["binning"],
                            "filtro": s["filter"] or "—",
                            "scala": fmt_num(s["pixel_scale_arcsec"], 3),
                            "campo": f"{fmt_num(s['fov_x_arcmin'], 1)} × {fmt_num(s['fov_y_arcmin'], 1)}",
                            "f": fmt_num(s["f_ratio"], 1),
                            # Il limite dichiarato e quello astrometrico sono due
                            # numeri diversi e vanno letti insieme: rilevare un
                            # oggetto non vuol dire poterlo misurare.
                            "vlim": f"{fmt_num(s['vlim_ref'], 1)}"
                                    f" / {fmt_num(s['vlim_ref'] + s['vlim_astrometric_delta'], 1)} astr."
                                    + (f" · {s['n_calibrazioni']} misure" if s["n_calibrazioni"] else ""),
                            "posa": f"{fmt_num(s['typical_exposure_s'], 0)}"
                                    f" (max {fmt_num(s['max_exposure_s'], 0)})",
                            "alt": fmt_num(s["min_altitude_eff_deg"], 0),
                            "airmass": fmt_num(s["max_airmass"], 1),
                            "stato": "attivo" if s["active"] else f"dismesso {s['valid_to'] or ''}",
                        } for s in sito["setups"]],
                    )
                    ui.label(
                        "Scala e campo non stanno nei file: sono derivati da focale, "
                        "riduttore, pixel e binning a ogni riallineamento."
                    ).classes("text-xs opacity-60")

                    _notti(sito)

                    with ui.row().classes("w-full gap-6 flex-wrap items-start mt-2"):
                        with ui.column().classes("gap-1 min-w-96 grow"):
                            ui.label("Telescopi").classes("font-bold")
                            table(
                                cols(("code", "codice"), ("name", "nome"),
                                     ("apertura", "apertura (mm)", "right"),
                                     ("focale", "focale (mm)", "right"),
                                     ("design", "schema"),
                                     ("alt", "alt. min (°)", "right"),
                                     ("flip", "flip meridiano")),
                                [{
                                    "code": t["code"], "name": t["name"],
                                    "apertura": fmt_num(t["aperture_mm"], 0),
                                    "focale": fmt_num(t["focal_length_mm"], 0),
                                    "design": t["design"] or "—",
                                    "alt": fmt_num(t["min_altitude_deg"], 0),
                                    "flip": "sì" if t["meridian_flip"] else "no",
                                } for t in sito["telescopes"]],
                            )
                        with ui.column().classes("gap-1 min-w-96 grow"):
                            ui.label("Camere").classes("font-bold")
                            table(
                                cols(("code", "codice"), ("name", "nome"), ("sensor", "sensore"),
                                     ("pixel", "pixel (µm)", "right"),
                                     ("formato", "formato", "right"),
                                     ("rn", "rumore (e⁻)", "right")),
                                [{
                                    "code": cam["code"], "name": cam["name"],
                                    "sensor": cam["sensor"] or "—",
                                    "pixel": fmt_num(cam["pixel_um"], 2),
                                    "formato": f"{cam['pixels_x']} × {cam['pixels_y']}",
                                    "rn": fmt_num(cam["read_noise_e"], 1),
                                } for cam in sito["cameras"]],
                            )

    async def riallinea() -> None:
        btn.disable()
        spinner.visible = True
        try:
            report = await run.io_bound(sites.run_reconcile)
            # Se l'hardware è cambiato le notti possono essere di un sito che
            # non c'è più — o mancare per uno nuovo. Ricalcolarle costa
            # millisecondi e toglie una finestra di incoerenza.
            await run.io_bound(notti.run_night_plan)
            cambiati = len(report["creati"]) + len(report["aggiornati"]) \
                + len(report["disattivati"])
            if cambiati:
                ui.notify(
                    f"{len(report['creati'])} creati, {len(report['aggiornati'])} aggiornati, "
                    f"{len(report['disattivati'])} disattivati",
                    type="positive",
                )
            else:
                ui.notify("Già allineato: nessuna modifica", type="info")
            if report["vlim_tenuti"]:
                ui.notify(
                    "Limite misurato mantenuto per: " + ", ".join(report["vlim_tenuti"]),
                    type="info",
                )
        except SiteConfigError as exc:
            # L'errore di configurazione si mostra per intero: dice quale file e
            # quale campo, ed è l'unica cosa che serve per correggerlo.
            ui.notify(str(exc), type="negative", multi_line=True, close_button=True)
        except Exception as exc:
            log.exception("reconcile fallito")
            ui.notify(f"Riallineamento fallito: {exc}", type="negative")
        finally:
            spinner.visible = False
            btn.enable()
            redraw()

    btn.on_click(riallinea)
    redraw()
