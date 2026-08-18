"""Pagina Stanotte: la decision console. Tre sezioni, tre orizzonti.

È la pagina per cui esiste il progetto, e non calcola **niente**: legge quello
che i tre job della notte hanno già scritto. Se qui dentro comparisse una
propagazione, vorrebbe dire che la dashboard è tornata a essere un calcolo
invece di una query.

Le tre sezioni non si fondono in una classifica sola perché rispondono a tre
domande con tre orizzonti diversi — stanotte, le prossime settimane, gli anni —
e un oggetto che manca da vent'anni non batterebbe mai, su una scala unica, un
oggetto comodo e brillante di stasera.

I filtri stanno **solo sulla prima sezione**, e nemmeno lì sono un
raffinamento estetico: la classifica per punteggio risponde alla domanda
«cosa conviene stanotte», ma la sera in cui si vuole una cometa, o un oggetto
che stia alto perché il tetto del box copre l'orizzonte est, la domanda è
un'altra e la classifica generale non la sa. Filtrare non riordina: **riduce**
l'insieme e lascia intatto l'ordine per punteggio, che è l'unica cosa che il
ranking sa fare bene (regola 5).

L'ora **locale del sito** si calcola qui: il servizio restituisce UTC e il fuso,
perché è l'interfaccia l'unico posto in cui esiste un osservatore che guarda un
orologio (CLAUDE.md).
"""
from __future__ import annotations

import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from nicegui import app, run, ui

from gui.layout import cols, fmt_age, fmt_int, fmt_num, header, link_oggetto, table
from services import dashboard_service as dash

log = logging.getLogger("sky42.gui.stanotte")

# Il colore del giudizio. NOT_USEFUL resta grigio e **resta visibile**: sapere
# che da un sito non si poteva è informazione, non rumore (regola 5).
GRADI = {"PRIME": "positive", "GOOD": "primary", "POSSIBLE": "warning",
         "POOR": "grey", "NOT_USEFUL": "grey-5"}

# Oltre queste ore il risultato è vecchio: i tre job girano fra le 02:10 e le
# 02:40 UTC, quindi 30 ore vuol dire che un giro è stato saltato del tutto.
STANTIO_ORE = 30.0

# Quante righe si aggiungono a ogni «mostra di più». Uguale al primo blocco: la
# pagina si apre con venti righe — quelle che si leggono in piedi con il caffè
# in mano — e chi vuole scendere lo dice, invece di ricevere quattordicimila
# righe che nessuno scorrerà mai.
PASSO = dash.DEFAULT_LIMIT

TIPI = {"": "tutti", "asteroid": "asteroidi", "comet": "comete"}
GRADI_MIN = {"": "qualunque", "PRIME": "solo PRIME", "GOOD": "GOOD o meglio",
             "POSSIBLE": "POSSIBLE o meglio", "POOR": "POOR o meglio"}


def _locale(iso: str | None, tz: str) -> str:
    """Da ISO-8601 UTC all'ora locale del sito, in «HH:MM»."""
    if not iso:
        return "—"
    t = datetime.strptime(iso, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=ZoneInfo("UTC"))
    return t.astimezone(ZoneInfo(tz)).strftime("%H:%M")


@ui.page("/stanotte")
def stanotte_page() -> None:
    header("Stanotte")

    # Quanto si è chiesto finora, per sezione, e con quali filtri. Sta in una
    # variabile di pagina e non nell'URL perché è lo stato di una sessione di
    # lettura, non un indirizzo da mandare a qualcuno: chi vuole condividere una
    # selezione ha `/api/stanotte`, che gli stessi filtri li prende in query.
    stato = {"limit": PASSO, "coming": PASSO, "returns": PASSO, "filtri": {}}
    # I controlli, e il valore con cui sono nati. «Azzera» rimette *quelli* e
    # non un vuoto indovinato dal tipo: un `ui.select` multiplo azzerato a
    # `None` invece che a `[]` è un menù che smette di funzionare.
    campi: dict = {}
    vuoti: dict = {}

    with ui.column().classes("w-full max-w-7xl mx-auto p-6 gap-5"):
        stato_box = ui.row().classes("w-full items-center gap-3")
        notti_box = ui.row().classes("w-full items-center gap-3 -mt-2")
        # I controlli si costruiscono **una volta sola** e non si ridisegnano
        # mai: un campo di ricerca ricreato a ogni battuta perde il fuoco e il
        # cursore, e la ricerca "in tempo reale" diventa una lettera per volta.
        filtri_box = ui.column().classes("w-full gap-2")
        tonight_box = ui.column().classes("w-full gap-2")
        siti_box = ui.column().classes("w-full gap-2")
        arrivo_box = ui.column().classes("w-full gap-2")
        ritorni_box = ui.column().classes("w-full gap-2")

    def leggi_filtri() -> dict:
        """Dai controlli al vocabolario chiuso del servizio. Nessun SQL qui."""
        f = {k: (c.value or None) for k, c in campi.items()}
        # `q` sotto i due caratteri non filtra: con una lettera sola resta tutto
        # dentro e la pagina sembra rotta mentre si sta ancora scrivendo.
        if f.get("q") and len(f["q"].strip()) < 2:
            f["q"] = None
        elif f.get("q"):
            f["q"] = f["q"].strip()
        return {k: v for k, v in f.items() if v not in (None, "", [])}

    async def redraw() -> None:
        # In un thread: sono cinque query, e una pagina che si blocca mentre il
        # Mac mini macina lo screening è una pagina che sembra rotta.
        # «Mostra di più» alza il **limite** e ricarica da capo, invece di
        # chiedere la sola pagina successiva e attaccarla in fondo: fra un click
        # e l'altro passa un job della notte, e due pagine prese da classifiche
        # diverse si sovrappongono e si saltano righe senza dirlo. Venti righe
        # in più costano una query, la coerenza dell'elenco no.
        dati = await run.io_bound(
            dash.overview, stato["limit"], 0, stato["filtri"], stato["coming"],
            stato["returns"])

        _intestazione(dati["freshness"], stato_box, redraw)
        _notti(dati["tonight"]["nights"], notti_box)
        if not campi:
            _filtri(dati["facets"], filtri_box, campi, vuoti, cambia_filtri, azzera)
        _tonight(dati["tonight"], tonight_box, ancora_stanotte)
        _best_sites(dati["best_sites"], siti_box)
        _coming(dati["coming_into_range"], arrivo_box, stato,
                lambda: ancora("coming"))
        _returns(dati["returns"], ritorni_box, stato, lambda: ancora("returns"))

    async def cambia_filtri() -> None:
        """Un filtro cambiato riparte da capo: restare alla riga 140 di un
        insieme che ora ne ha 12 mostrerebbe una pagina vuota per «fine lista»."""
        stato["limit"] = PASSO
        stato["filtri"] = leggi_filtri()
        await redraw()

    async def azzera() -> None:
        for chiave, c in campi.items():
            c.value = vuoti[chiave]
        await cambia_filtri()

    async def ancora_stanotte() -> None:
        stato["limit"] += PASSO
        await redraw()

    async def ancora(sezione: str) -> None:
        stato[sezione] += PASSO
        await redraw()

    ui.timer(0.1, redraw, once=True)


def _intestazione(fresh: dict, box, redraw) -> None:
    """L'età dei tre lavori, in cima e non in fondo.

    Una classifica calcolata su finestre di tre giorni fa è sbagliata in un modo
    che non si vede guardando le righe: il 16 agosto i job pesanti non giravano
    da un giorno e nessuno lo diceva (memorandum).
    """
    from core.timeutil import days_since

    box.clear()
    with box:
        ui.label("Cosa osservare stanotte").classes("text-2xl font-bold")
        ui.space()
        for nome, etichetta in (("screening", "screening"), ("windows", "finestre"),
                                ("radar_states", "radar")):
            j = fresh["jobs"].get(nome)
            eta = days_since(j["started_at"]) if j else None
            colore = ("grey" if eta is None
                      else "negative" if eta * 24 > STANTIO_ORE
                      else "positive" if (j or {}).get("status") == "ok" else "warning")
            ui.badge(f"{etichetta} {fmt_age(eta)}").props(f"color={colore}")
        ui.button("Aggiorna", icon="refresh").props("flat dense").on("click", redraw)


def _notti(notti: list[dict], box) -> None:
    box.clear()
    with box:
        if not notti:
            ui.label(
                "Nessuna notte calcolata per i siti attivi: il piano delle notti "
                "gira ogni 6 ore, e senza di lui non esistono finestre."
            ).classes("text-sm text-negative")
            return
        for n in notti:
            luna = f"Luna {fmt_pct_illum(n['moon_illum'])}"
            ui.label(f"{n['site_name']} · notte del {n['night_date']} · "
                     f"{fmt_num(n['dark_hours'], 1)} h di buio · {luna}") \
                .classes("text-sm opacity-70")


def fmt_pct_illum(x) -> str:
    return "—" if x is None else f"{x * 100:.0f}%"


def _filtri(facets: dict, box, campi: dict, vuoti: dict, cambia, azzera) -> None:
    """La barra dei filtri. Costruita **una volta**, poi vive da sola.

    In prima riga le tre domande che si fanno ogni sera — *come si chiama*,
    *cometa o asteroide*, *quanto buono* — e sotto, chiuse, quelle che si fanno
    quando si sta cercando qualcosa di preciso. Tenerle tutte aperte
    trasformerebbe la decision console in un modulo da compilare.

    I menù si riempiono con quello che c'è **stanotte** e non con tutto il
    catalogo: una classe orbitale che stanotte non ha nemmeno un oggetto darebbe
    una lista vuota indistinguibile da un guasto.

    La ricerca è `debounce=300`: NiceGUI manda un evento per battuta, e con
    quattordicimila finestre una query per lettera vuol dire una pagina che
    scatta mentre si scrive.
    """
    box.clear()
    r = facets.get("ranges") or {}

    def registra(chiave: str, controllo, vuoto):
        controllo.on_value_change(cambia)
        campi[chiave] = controllo
        vuoti[chiave] = vuoto
        return controllo

    def num(chiave: str, etichetta: str, suffisso: str = "", passo: float = 1.0):
        c = ui.number(label=etichetta, step=passo, format="%g") \
            .props("dense outlined clearable").classes("w-40")
        if suffisso:
            c.props(f'suffix="{suffisso}"')
        return registra(chiave, c, None)

    with box:
        with ui.row().classes("w-full items-center gap-3 flex-wrap"):
            registra("q", ui.input(placeholder="cerca: nome o designazione…")
                     .props("dense outlined clearable debounce=300")
                     .classes("grow min-w-64"), "")
            registra("kind", ui.toggle(TIPI, value="").props("dense no-caps"), "")
            registra("grade_min",
                     ui.select(GRADI_MIN, value="", label="giudizio")
                     .props("dense outlined").classes("w-44"), "")
            registra("orbit_class",
                     ui.select(facets.get("orbit_classes") or [], value=[],
                               multiple=True, label="classe orbitale")
                     .props("dense outlined use-chips clearable").classes("w-64"), [])

            ui.button("Azzera", icon="backspace").props("flat dense").on("click", azzera)

        with ui.expansion("Altri filtri", icon="tune").classes("w-full"):
            with ui.row().classes("w-full items-start gap-3 flex-wrap"):
                num("tisserand_max", "Tj sotto", "", 0.1)
                num("ceu_max_arcsec", "incertezza fino a", '"', 1.0)
                num("unobserved_min_years", "non osservato da almeno", "anni", 1.0)
                num("unobserved_max_years", "non osservato da al più", "anni", 1.0)
                num("alt_min_deg", "altezza almeno", "°", 5.0)
                num("v_max", "non più debole di", "V", 0.5)
                num("margin_min", "margine almeno", "mag", 0.2)
                num("useful_hours_min", "finestra almeno", "h", 0.5)
            ui.label(
                "Un filtro esclude anche chi il dato non ce l'ha: «Tj sotto 3» "
                "toglie gli oggetti senza Tisserand, «incertezza fino a 10\"» "
                "quelli senza CEU. È voluto — non si può rispondere di sì a una "
                "domanda su un numero che manca — ma vuol dire che una lista si "
                "può accorciare per assenza di dato invece che per merito."
            ).classes("text-xs opacity-60")
            if r:
                ui.label(
                    f"Stanotte: V da {fmt_num(r.get('v_min'), 1)} a "
                    f"{fmt_num(r.get('v_max'), 1)} · altezza fino a "
                    f"{fmt_num(r.get('alt_max'), 0)}° · finestra fino a "
                    f"{fmt_num(r.get('ore_max'), 1)} h · Tj da "
                    f"{fmt_num(r.get('tj_min'), 2)} a {fmt_num(r.get('tj_max'), 2)} · "
                    f"assenza fino a {fmt_num(r.get('oss_max'), 1)} anni"
                ).classes("text-xs opacity-60")


def _tonight(dati: dict, box, ancora) -> None:
    box.clear()
    with box:
        righe = dati["rows"]
        n_tot = dati["n_totali"]
        n_disp = dati.get("n_disponibili", n_tot)

        if not righe:
            if n_disp and not n_tot:
                # La differenza conta: «i filtri sono troppo stretti» e «i job
                # non sono girati» si risolvono in due modi opposti.
                ui.label(f"Nessuno dei {fmt_int(n_disp)} oggetti con una finestra "
                         f"utile stanotte passa i filtri impostati.") \
                    .classes("opacity-70")
            else:
                ui.label(
                    "Nessun oggetto con una finestra utile stanotte. Se il job "
                    "`windows` non è ancora girato, la tabella è vuota per quello — "
                    "e lo dicono i badge qui sopra."
                ).classes("opacity-70")
            return

        filtrata = n_tot != n_disp
        testo = (f"{fmt_int(n_tot)} oggetti passano i filtri "
                 f"(su {fmt_int(n_disp)} con una finestra utile stanotte); "
                 f"ne vedi {len(righe)}."
                 if filtrata else
                 f"{fmt_int(n_disp)} oggetti hanno una finestra utile stanotte; "
                 f"ne vedi i migliori {len(righe)}.")
        ui.label(testo).classes("text-xs opacity-60")

        for r in righe:
            _scheda(r)

        _ancora(dati.get("has_more"), len(righe), n_tot, ancora)


def _ancora(has_more: bool | None, visti: int, totale: int | None, ancora) -> None:
    """«Mostra altri venti», o la riga che dice che sono finiti.

    Dire «fine dell'elenco» invece di non mostrare niente non è cortesia: senza
    quella riga, un elenco che finisce esattamente su un multiplo di venti è
    indistinguibile da un pulsante che non ha funzionato.
    """
    with ui.row().classes("w-full items-center gap-3 justify-center py-2"):
        if has_more:
            ui.button(f"Mostra altri {PASSO}", icon="expand_more") \
                .props("flat dense").on("click", ancora)
            if totale:
                ui.label(f"{visti} di {fmt_int(totale)}").classes("text-xs opacity-60")
        else:
            ui.label(f"fine dell'elenco · {visti} righe").classes("text-xs opacity-50")


def _scheda(r: dict) -> None:
    """Una riga della sezione Stanotte: l'oggetto, la finestra, e i siti.

    Il confronto fra siti sta **dentro la riga** e non in una pagina a parte: la
    domanda «da dove lo prendo» non è una domanda successiva a «cosa osservo»,
    è la stessa domanda (IDEA.md).
    """
    with ui.card().classes("w-full py-3"):
        with ui.row().classes("w-full items-center gap-4 no-wrap"):
            with ui.column().classes("gap-0 min-w-64"):
                ui.label(r["display_name"]).classes("font-bold cursor-pointer") \
                    .on("click", lambda d=r["primary_desig"]:
                        ui.navigate.to(link_oggetto(d)))
                dettagli = [r["kind"], r.get("orbit_class") or ""]
                if r.get("tisserand_j") is not None:
                    dettagli.append(f"Tj {fmt_num(r['tisserand_j'], 2)}")
                if r.get("ceu_now_arcsec") is not None:
                    dettagli.append(f"CEU {fmt_num(r['ceu_now_arcsec'], 1)}\"")
                if r.get("years_since_last_obs") is not None:
                    dettagli.append(f"non ripreso da {fmt_num(r['years_since_last_obs'], 1)} anni")
                ui.label(" · ".join(x for x in dettagli if x)).classes("text-xs opacity-60")

            with ui.column().classes("gap-0 min-w-48"):
                ui.label(f"V {fmt_num(r['v_pred'], 1)} · limite {fmt_num(r['eff_vlim'], 1)} · "
                         f"margine {fmt_num(r['depth_margin'], 1)} mag").classes("text-sm")
                ui.label(f"{_locale(r['useful_start_iso'], r['timezone'])}–"
                         f"{_locale(r['useful_end_iso'], r['timezone'])} locali · "
                         f"{fmt_num(r['useful_hours'], 1)} h · "
                         f"alt {fmt_num(r['best_alt_deg'], 0)}° · X {fmt_num(r['best_airmass'], 2)}") \
                    .classes("text-xs opacity-70")

            with ui.column().classes("gap-0 min-w-40"):
                ui.label(f"{fmt_num(r['rec_exposure_s'], 0)} s × {r['rec_n_subs'] or '—'}") \
                    .classes("text-sm")
                nota = f"moto {fmt_num(r['motion_arcsec_min'], 1)}\"/min"
                if r.get("needs_mosaic"):
                    nota += " · serve un mosaico"
                ui.label(nota).classes("text-xs opacity-70")

            ui.space()
            with ui.column().classes("gap-1 items-end"):
                # Il pulsante che chiude il giro: da suggerimento a decisione.
                # Nasce **qui** e non nella pagina Programma perché è qui che si
                # guarda la lista e si sceglie — un programma che si compila
                # altrove è un programma che resta vuoto.
                ui.button("Osserva", icon="add_task").props("flat dense") \
                    .on("click", lambda x=r: _in_programma(x))
                ui.badge(f"{r['grade']} {fmt_num(r['score'], 2)}") \
                    .props(f"color={GRADI.get(r['grade'], 'grey')}")
                # BEST SITE: il primo della lista, e gli altri accanto con il
                # loro giudizio — anche quando è NOT_USEFUL.
                with ui.row().classes("gap-1 items-center"):
                    for s in r["sites"]:
                        ui.badge(f"{s['site_code']} {s['grade']}") \
                            .props(f"color={GRADI.get(s['grade'], 'grey')} outline") \
                            .tooltip(f"{s['setup_code']} · "
                                     f"{fmt_num(s['useful_hours'], 1)} h utili · "
                                     f"margine {fmt_num(s['depth_margin'], 1)} mag")


async def _in_programma(r: dict) -> None:
    """«Voglio osservarlo»: il proposito nasce con il setup da cui viene meglio.

    Non con «qualunque setup»: la riga in cima dice *da dove* conviene, e
    buttare via quella scelta significherebbe far ricominciare il ragionamento
    a chi apre il programma domani.
    """
    from services import intent_service as prop

    p = await run.io_bound(prop.add, r["primary_desig"], r["setup_code"],
                           None, 0, "stanotte")
    if p is None:
        ui.notify("non trovato in catalogo", type="negative")
        return
    ui.notify(f"{r['display_name']} è in programma con {r['setup_code']}",
              type="positive")


def _best_sites(righe: list[dict], box) -> None:
    box.clear()
    with box:
        ui.label("Best site tonight").classes("text-xl font-bold")
        if not righe:
            ui.label("Nessun setup con oggetti utili stanotte.").classes("opacity-70")
            return
        ui.label(
            "Vale quanto valgono i `vlim_ref` dichiarati: finché sono stime e non "
            "misure di `setup_calibration`, il confronto fra siti è un'opinione "
            "informata (domanda aperta 5). I filtri qui sopra non lo toccano: è il "
            "conto di tutta la notte, non di quel che si sta cercando adesso."
        ).classes("text-xs opacity-60")
        table(
            cols(("sito", "sito"), ("setup", "setup"), ("notte", "notte"),
                 ("utili", "oggetti utili", "right"), ("prime", "PRIME", "right"),
                 ("good", "GOOD", "right"), ("score", "score migliore", "right"),
                 ("ore", "ore utili in totale", "right")),
            [{"sito": r["site_name"], "setup": r["setup_code"],
              "notte": r["night_date"], "utili": r["n_utili"],
              "prime": r["n_prime"], "good": r["n_good"],
              "score": fmt_num(r["score_max"], 3),
              "ore": fmt_num(r["ore_totali"], 1)} for r in righe])


def _coming(righe: list[dict], box, stato: dict, ancora) -> None:
    box.clear()
    with box:
        ui.label("Coming into range").classes("text-xl font-bold")
        ui.label("Le prossime settimane: chi conviene aspettare, e da quando. "
                 "La data viene dallo screening, non da stanotte.") \
            .classes("text-xs opacity-60")
        if not righe:
            ui.label("Nessun oggetto in avvicinamento entro quattro mesi.") \
                .classes("opacity-70")
            return
        table(
            cols(("oggetto", "oggetto"), ("tipo", "tipo"), ("tj", "Tj", "right"),
                 ("stato", "stato"), ("v", "V ora", "right"),
                 ("trend", "mag/mese", "right"), ("quando", "a portata dal"),
                 ("giorni", "fra (giorni)", "right"),
                 ("picco", "picco V", "right"),
                 ("assenza", "manca da (anni)", "right")),
            [{"oggetto": r["display_name"], "tipo": r["kind"],
              "tj": fmt_num(r["tisserand_j"], 2), "stato": r["state"],
              "v": fmt_num(r["v_now"], 1),
              "trend": fmt_num(r["v_trend_mag_month"], 2),
              "quando": (r["next_v21_iso"] or "—")[:10],
              "giorni": fmt_num(r["giorni_alla_portata"], 0),
              "picco": fmt_num(r["peak_v"], 1),
              "assenza": fmt_num(r["years_since_good_apparition"], 1)}
             for r in righe])
        # Senza un conto totale la fine si riconosce così: se ne sono tornate
        # meno di quante chieste, non ce n'erano altre.
        _ancora(len(righe) >= stato["coming"], len(righe), None, ancora)


def _returns(righe: list[dict], box, stato: dict, ancora) -> None:
    box.clear()
    with box:
        ui.label("Tj < 3 che tornano").classes("text-xl font-bold")
        ui.label("Gli anni, non le settimane: a portata adesso, ordinati per "
                 "quanto tempo è passato dall'ultima buona apparizione.") \
            .classes("text-xs opacity-60")
        if not righe:
            ui.label("Nessun oggetto su orbita cometaria a portata in questo momento.") \
                .classes("opacity-70")
            return
        table(
            cols(("oggetto", "oggetto"), ("classe", "classe"), ("tj", "Tj", "right"),
                 ("stato", "stato"), ("v", "V ora", "right"),
                 ("assenza", "buona apparizione (anni fa)", "right"),
                 ("oss", "non osservato da (anni)", "right"),
                 ("ceu", "CEU (\")", "right"), ("regole", "perché")),
            [{"oggetto": r["display_name"], "classe": r["orbit_class"] or "—",
              "tj": fmt_num(r["tisserand_j"], 2), "stato": r["state"],
              "v": fmt_num(r["v_now"], 1),
              # «≥ 15» e non «15»: fuori dalla finestra di back-propagation non
              # si sa quanto è passato, si sa che è di più.
              "assenza": (f"≥ {r['apparition_window_years']}"
                          if r["apparition_censored"]
                          else fmt_num(r["years_since_good_apparition"], 1)),
              "oss": fmt_num(r["years_since_last_obs"], 1),
              "ceu": fmt_num(r["ceu_now_arcsec"], 1),
              "regole": ", ".join(r["selectors"])} for r in righe])
        _ancora(len(righe) >= stato["returns"], len(righe), None, ancora)


@app.get("/api/stanotte")
def stanotte_json(
    limit: int = dash.DEFAULT_LIMIT,
    offset: int = 0,
    q: str | None = None,
    kind: str | None = None,
    orbit_class: str | None = None,
    grade_min: str | None = None,
    tisserand_max: float | None = None,
    ceu_max_arcsec: float | None = None,
    unobserved_min_years: float | None = None,
    unobserved_max_years: float | None = None,
    alt_min_deg: float | None = None,
    v_max: float | None = None,
    margin_min: float | None = None,
    useful_hours_min: float | None = None,
) -> dict:
    """Il gemello JSON della pagina: **la stessa chiamata**, non una seconda query.

    Gli stessi filtri della pagina, con gli stessi nomi: `orbit_class` accetta
    più classi separate da virgola. Il giorno delle curve di visibilità la
    sorgente dati deve già esserci, o ogni grafico diventa una riscrittura della
    pagina che lo contiene (CLAUDE.md).
    """
    filtri = {
        "q": q, "kind": kind, "grade_min": grade_min,
        "orbit_class": [c.strip() for c in orbit_class.split(",") if c.strip()]
                       if orbit_class else None,
        "tisserand_max": tisserand_max, "ceu_max_arcsec": ceu_max_arcsec,
        "unobserved_min_years": unobserved_min_years,
        "unobserved_max_years": unobserved_max_years,
        "alt_min_deg": alt_min_deg, "v_max": v_max, "margin_min": margin_min,
        "useful_hours_min": useful_hours_min,
    }
    return dash.overview(limit, offset,
                         {k: v for k, v in filtri.items() if v not in (None, "", [])})
