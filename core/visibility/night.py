"""La notte di un sito: crepuscoli, Luna, e quante ore di buio restano.

Una riga per (osservatorio × notte), e **non** per setup: il Sole e la Luna non
sanno che telescopio c'è sotto. È la ragione per cui aggiungere una camera costa
niente e aggiungere un sito costa (MEMORANDUM 2026-08-15).

Il confine di questo modulo è un `Site` e una data. Non conosce il database, non
conosce gli asteroidi, e restituisce JD: chi vuole un'ora locale se la converte
in interfaccia.

**I tempi sono JD TT**, che è la scala di Skyfield e — a 1.7 ms — la stessa cosa
del TDB in cui parla il positioner. La conversione da e verso UTC vive in
`core/timeutil.py` e da nessun'altra parte.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np

from core.ephemeris import kernel_and_timescale
from core.timeutil import datetime_from_jd, jd_utc_from_tdb
from core.visibility.site import Site

log = logging.getLogger("sky42.visibility.night")

# Le soglie di altezza del Sole che definiscono le fasi, in gradi: sono
# definizioni convenzionali, non parametri da tarare. Quale di queste sia
# «abbastanza buio» lo decide il setup con `sun_alt_max_deg`, non questo modulo.
TWILIGHT_CIVIL = -6.0
TWILIGHT_NAUTICAL = -12.0
TWILIGHT_ASTRONOMICAL = -18.0

# Codici di `almanac.dark_twilight_day`, dal più buio al più chiaro.
NOTTE, ASTRO, NAUTICO, CIVILE, GIORNO = range(5)

# L'altezza a cui si considera sorta la Luna: bordo superiore all'orizzonte,
# rifrazione inclusa. È la convenzione delle tabelle pubblicate; con 0° gli
# orari si scostano di qualche minuto da qualunque fonte con cui confrontarsi.
HORIZON_MOON_DEG = -0.8

# Passo di campionamento per l'altezza massima della Luna. Dieci minuti: vicino
# al culmine la Luna cambia altezza di ~0.5°/ora, quindi l'errore sul massimo
# resta sotto 0.01° — e serve a sapere quanto ha disturbato, non a puntarla.
MOON_STEP_MIN = 10.0


def _observer(site: Site):
    """Kernel, scala dei tempi e osservatore topocentrico per il sito."""
    from skyfield.api import wgs84

    kernel, ts = kernel_and_timescale()
    topos = wgs84.latlon(site.latitude, site.longitude, elevation_m=site.altitude_m)
    return kernel, ts, kernel["earth"] + topos, topos


def _finestra(site: Site, night_date: str):
    """Da mezzogiorno locale della data al mezzogiorno dopo.

    La notte si chiama con la data della **sera** — «la notte del 15» comincia
    la sera del 15 anche se il grosso del buio cade il 16 — e l'unico ancoraggio
    che tiene a ogni latitudine e in ogni stagione è il mezzogiorno locale. A
    Río Hurtado la mezzanotte UTC cade in piena sera del giorno prima.
    """
    tz = ZoneInfo(site.timezone)
    y, m, d = (int(x) for x in night_date.split("-"))
    inizio = datetime.combine(datetime(y, m, d).date(), time(12, 0), tzinfo=tz)
    return inizio, inizio + timedelta(days=1)


def night_events(site: Site, night_date: str) -> dict:
    """Crepuscoli, Luna e ore di buio per la notte che comincia la sera di `night_date`.

    I valori mancanti sono `None` e non zeri: a certe latitudini e in certe
    stagioni il Sole non tramonta, la notte astronomica non arriva mai e la Luna
    non sorge. Sono risposte, non errori, e un `None` lo si vede — uno zero no.
    """
    from skyfield import almanac

    kernel, ts, osservatore, topos = _observer(site)
    da, a = _finestra(site, night_date)
    t0, t1 = ts.from_datetime(da), ts.from_datetime(a)

    fase = almanac.dark_twilight_day(kernel, topos)
    tempi, codici = almanac.find_discrete(t0, t1, fase)
    jd = np.asarray(tempi.tt, dtype=float)
    codici = np.asarray(codici, dtype=int)

    eventi = {
        "sunset_jd": _verso(jd, codici, CIVILE, sera=True),
        "civil_end_jd": _verso(jd, codici, NAUTICO, sera=True),
        "nautical_end_jd": _verso(jd, codici, ASTRO, sera=True),
        "twilight_end_jd": _verso(jd, codici, NOTTE, sera=True),
        "twilight_start_jd": _verso(jd, codici, ASTRO, sera=False),
        "nautical_start_jd": _verso(jd, codici, NAUTICO, sera=False),
        "civil_start_jd": _verso(jd, codici, CIVILE, sera=False),
        "sunrise_jd": _verso(jd, codici, GIORNO, sera=False),
    }

    return {
        "night_date": night_date,
        "jd_start": float(t0.tt),
        "jd_end": float(t1.tt),
        **eventi,
        "dark_hours": _ore_di_buio(eventi, fase, ts, t0, t1),
        **_luna(kernel, ts, osservatore, t0, t1, eventi),
    }


def _verso(jd: np.ndarray, codici: np.ndarray, codice: int, sera: bool):
    """Il passaggio *verso* una fase, nel verso giusto.

    `find_discrete` restituisce gli istanti di transizione e la fase in cui si
    entra; la stessa fase si attraversa due volte, una scendendo verso il buio e
    una risalendo. Si distingue dal verso, non dall'ora: confrontare con la
    mezzanotte fallirebbe proprio nei casi estremi per cui esiste questo codice.

    Alla prima transizione della finestra non c'è un «prima» da confrontare: la
    finestra comincia a mezzogiorno, quindi quella transizione è per forza
    serale.
    """
    for i in np.flatnonzero(codici == codice):
        precedente = codici[i - 1] if i > 0 else GIORNO
        if sera and precedente > codice:
            return float(jd[i])
        if not sera and i > 0 and precedente < codice:
            return float(jd[i])
    return None


def _ore_di_buio(eventi: dict, fase, ts, t0, t1):
    """Ore fra la fine e l'inizio del crepuscolo astronomico.

    Quando le due transizioni non ci sono la risposta non è «non so»: o non fa
    mai abbastanza buio (estate polare, e allora sono zero) oppure è buio per
    tutta la finestra (inverno polare, e allora sono ventiquattro). Si distingue
    guardando che fase è a metà finestra.
    """
    fine, inizio = eventi["twilight_end_jd"], eventi["twilight_start_jd"]
    if fine is not None and inizio is not None:
        return (inizio - fine) * 24.0
    meta = ts.tt_jd(0.5 * (t0.tt + t1.tt))
    if int(fase(meta)) == NOTTE:
        return 24.0
    return 0.0


def _luna(kernel, ts, osservatore, t0, t1, eventi: dict) -> dict:
    """Sorgere, tramontare, frazione illuminata e altezza massima della Luna.

    L'altezza massima si campiona invece di cercare il culmine: la Luna può
    culminare fuori dalla finestra, e la domanda non è «quando culmina» ma
    «quanto ha dato fastidio stanotte», che ha sempre una risposta. Per lo
    stesso motivo si campiona **fra tramonto e alba** e non su tutta la
    finestra: una Luna alta a mezzogiorno non ha disturbato nessuno.
    """
    from skyfield import almanac

    luna = kernel["moon"]
    sorgere, e_sorta = almanac.find_risings(
        osservatore, luna, t0, t1, horizon_degrees=HORIZON_MOON_DEG)
    tramonto, e_tramontata = almanac.find_settings(
        osservatore, luna, t0, t1, horizon_degrees=HORIZON_MOON_DEG)

    da = eventi["sunset_jd"] or t0.tt
    a = eventi["sunrise_jd"] or t1.tt
    passo = MOON_STEP_MIN / 1440.0
    campioni = ts.tt_jd(np.arange(da, a + passo / 2, passo))
    alt = osservatore.at(campioni).observe(luna).apparent().altaz()[0].degrees

    return {
        "moon_rise_jd": float(sorgere.tt[0]) if len(sorgere) and e_sorta[0] else None,
        "moon_set_jd": float(tramonto.tt[0]) if len(tramonto) and e_tramontata[0] else None,
        # A metà finestra: la frazione illuminata cambia di ~1% in una notte,
        # cioè meno di quanto la si sappia usare.
        "moon_illum": float(osservatore.at(ts.tt_jd(0.5 * (t0.tt + t1.tt)))
                            .observe(luna).apparent()
                            .fraction_illuminated(kernel["sun"])),
        "moon_max_alt_deg": float(np.max(alt)),
    }


def sun_altitude(site: Site, jd) -> np.ndarray:
    """Altezza apparente del Sole sull'orizzonte del sito, in gradi.

    Il modello di crepuscolo è una funzione dell'altezza del Sole e non
    dell'ora: è l'unico modo perché valga uguale a Río Hurtado e in Val d'Aosta.
    """
    kernel, ts, osservatore, _ = _observer(site)
    t = ts.tt_jd(np.asarray(jd, dtype=float))
    return osservatore.at(t).observe(kernel["sun"]).apparent().altaz()[0].degrees


def moon_state(site: Site, jd) -> dict:
    """Altezza, azimut, posizione e frazione illuminata della Luna agli istanti dati.

    Si calcola **una volta per sito** e ogni setup ci applica sopra i propri
    limiti: la Luna non sa che telescopio c'è sotto.
    """
    kernel, ts, osservatore, _ = _observer(site)
    t = ts.tt_jd(np.asarray(jd, dtype=float))
    apparente = osservatore.at(t).observe(kernel["moon"]).apparent()
    alt, az, distanza = apparente.altaz()
    ra, dec, _ = apparente.radec()
    return {
        "alt_deg": alt.degrees,
        "az_deg": az.degrees,
        "ra_deg": ra.hours * 15.0,
        "dec_deg": dec.degrees,
        # Frazione illuminata e angolo di fase **topocentrici**: la parallasse
        # lunare arriva a 1° e sposta la frazione di quasi un punto percentuale
        # rispetto al valore geocentrico. Non cambia una brillanza di cielo, ma
        # rende confrontabili i nostri numeri con quelli di Horizons — e un
        # numero che non si può confrontare non si può verificare.
        "illum": apparente.fraction_illuminated(kernel["sun"]),
        "phase_deg": apparente.phase_angle(kernel["sun"]).degrees,
        "distance_km": distanza.km,
    }


def nights(site: Site, first_date: str, n: int = 1) -> list[dict]:
    """Le prossime `n` notti a partire dalla sera di `first_date`."""
    y, m, d = (int(x) for x in first_date.split("-"))
    base = datetime(y, m, d)
    return [night_events(site, (base + timedelta(days=i)).strftime("%Y-%m-%d"))
            for i in range(n)]


def night_date_for(site: Site, jd: float) -> str:
    """A quale notte appartiene un istante: la data locale della *sera*.

    Le due di notte del 16 agosto appartengono alla notte del 15. Sbagliarlo
    significa cercare le finestre di stanotte fra quelle di ieri, ed è un errore
    che si scopre solo dopo aver perso un oggetto.
    """
    locale = datetime_from_jd(jd_utc_from_tdb(jd)).astimezone(ZoneInfo(site.timezone))
    if locale.hour < 12:
        locale -= timedelta(days=1)
    return locale.strftime("%Y-%m-%d")
