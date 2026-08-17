"""La macchina a stati del radar: da una magnitudine a «cos'è successo».

Legge quello che lo screening ha distillato e **non ricalcola niente**. Il suo
lavoro è tutto qui: decidere in quale stato sta la coppia (target, setup), e
soprattutto decidere *quando dirlo*.

**Il metro è `V_ref`**, il limite del setup in condizioni tipiche
(`visibility.limits.reference_limit`): X = 1.5, niente Luna, posa tipica. Se la
soglia si muovesse con il cielo di stanotte, ogni plenilunio farebbe uscire
mezzo catalogo da OBSERVABLE e ogni novilunio lo farebbe rientrare — venti
transizioni al mese che non dicono niente sull'oggetto.

**Isteresi e conferma, che sono due difese diverse.** L'isteresi (0.15 mag)
serve all'oggetto che *sta* sulla soglia: per uscire da uno stato bisogna
superarla di un margine, non sfiorarla. La conferma su due calcoli consecutivi
serve al calcolo che *cambia idea*: elementi orbitali aggiornati, una CEU
diversa, un arrotondamento. Senza la prima si notifica un oggetto che oscilla;
senza la seconda si notifica un aggiornamento di catalogo (MEMORANDUM
2026-08-15).

`CROSSES_LIMIT` è un **evento**, non un posto in cui si sta: lo si attraversa
scendendo sotto V_ref e al giro successivo si è OBSERVABLE o PRIME. È
volutamente uno stato e non solo una riga di transizione, perché la dashboard
deve poter chiedere «chi ha attraversato il limite oggi» con una query sola.
"""
from __future__ import annotations

STATES = ("OUT_OF_RANGE", "APPROACHING", "CROSSES_LIMIT", "OBSERVABLE", "PRIME", "FADING")

# Gli stati in cui l'oggetto è, di fatto, a portata.
IN_RANGE = ("PRIME", "OBSERVABLE", "CROSSES_LIMIT")

HYSTERESIS = 0.15           # mag di margine per *uscire* da uno stato
PRIME_MARGIN = 0.75         # quanto sotto V_ref per essere PRIME
APPROACH_BAND = 1.5         # quanto sopra V_ref si continua a guardare
PRIME_HOURS = 2.0
OBSERVABLE_HOURS = 0.5
CONFIRMATIONS = 2           # calcoli consecutivi d'accordo prima di cambiare


def classify(*, v_pred, v_ref, trend_mag_month=None, useful_hours=None,
             current: str | None = None) -> str:
    """Lo stato **candidato** per questo calcolo, con l'isteresi già applicata.

    `trend_mag_month` negativo = sta migliorando. `useful_hours` è la durata
    della finestra utile di stanotte: `None` significa «non lo so ancora» — il
    job che scrive `observation_window` in massa non c'è — e in quel caso il
    criterio è la sola magnitudine. Non è un valore di comodo: è la differenza
    fra «la finestra è corta» e «la finestra non è stata calcolata», e quando
    arriverà il job questo parametro comincerà ad arrivare pieno senza che
    niente qui cambi.

    Il risultato è un *candidato*: chi decide se lo stato cambia davvero è
    `advance`, che conta le conferme.
    """
    if v_pred is None or v_ref is None:
        return "OUT_OF_RANGE"

    v, ref = float(v_pred), float(v_ref)
    soglie = [ref - PRIME_MARGIN, ref, ref + APPROACH_BAND]

    # L'isteresi si applica *rispetto allo stato attuale*: le soglie che
    # porterebbero via da qui si spostano di 0.15 mag nella direzione che
    # rende più difficile andarsene. Le soglie interne allo stato attuale
    # restano dove sono, o l'isteresi diventerebbe una banda morta.
    banda_attuale = _band_of(current)
    if banda_attuale is not None:
        soglie = [t - HYSTERESIS if i < banda_attuale else t + HYSTERESIS
                  for i, t in enumerate(soglie)]

    banda = sum(v > t for t in soglie)
    peggiora = trend_mag_month is not None and float(trend_mag_month) > 0.0

    # Sotto il limite, ma oltre il picco: `FADING` e non `PRIME`, perché la
    # domanda del radar è «conviene aspettare o è l'ultima occasione», e le due
    # risposte non si distinguono dalla sola magnitudine.
    if banda == 0:
        return "FADING" if peggiora else _con_durata("PRIME", useful_hours, PRIME_HOURS)
    if banda == 1:
        return "FADING" if peggiora else _con_durata("OBSERVABLE", useful_hours,
                                                     OBSERVABLE_HOURS)
    if banda == 2:
        # Nella fascia di guardia il verso conta più della magnitudine: lo
        # stesso V 21.8 è una notizia se sta scendendo e non è niente se sta
        # salendo dopo essere già stato osservabile.
        if not peggiora:
            return "APPROACHING"
        return "FADING" if current in IN_RANGE or current == "FADING" else "OUT_OF_RANGE"
    return "OUT_OF_RANGE"


def _band_of(state: str | None) -> int | None:
    if state in ("PRIME",):
        return 0
    if state in ("OBSERVABLE", "CROSSES_LIMIT", "FADING"):
        return 1
    if state in ("APPROACHING",):
        return 2
    if state in ("OUT_OF_RANGE",):
        return 3
    return None


def _abbastanza(useful_hours, minimo: float) -> bool:
    """Con finestra sconosciuta si risponde di sì: il criterio è la magnitudine."""
    return useful_hours is None or float(useful_hours) >= minimo


def _con_durata(stato: str, useful_hours, minimo: float) -> str:
    """Declassa se la finestra utile è troppo corta per quello stato.

    Un oggetto brillantissimo che sta sopra l'orizzonte venti minuti non è
    PRIME: è OBSERVABLE con un problema. E uno che ci sta dieci minuti non è
    osservabile per niente, per quanto brilli.
    """
    if _abbastanza(useful_hours, minimo):
        return stato
    if stato == "PRIME":
        return _con_durata("OBSERVABLE", useful_hours, OBSERVABLE_HOURS)
    return "OUT_OF_RANGE"


def advance(previous: dict | None, candidate: str) -> dict:
    """Da (stato precedente, candidato) allo stato nuovo, contando le conferme.

    `previous` è la riga di `target_state` (o `None` la prima volta) e serve
    solo per `state`, `pending_state`, `pending_count`. Restituisce sempre un
    dizionario con lo stato da scrivere, il candidato in attesa e se c'è stata
    una transizione da registrare.

    Alla **prima** osservazione non si aspettano conferme: uno stato iniziale
    non è un cambiamento, e far passare due giri prima di sapere in che stato
    sta un oggetto nuovo significherebbe una dashboard vuota il primo giorno.
    """
    if previous is None or previous.get("state") is None:
        return {"state": candidate, "from_state": None, "changed": True,
                "pending_state": None, "pending_count": 0, "confirmed": True}

    attuale = previous["state"]
    if candidate == attuale:
        return {"state": attuale, "from_state": attuale, "changed": False,
                "pending_state": None, "pending_count": 0, "confirmed": True}

    # `CROSSES_LIMIT` è un evento e si assesta al giro dopo, **senza** conferme
    # e senza lasciare traccia: la transizione interessante è già stata scritta
    # entrando, e un `CROSSES_LIMIT → OBSERVABLE` meccanico sporcherebbe
    # `state_transition` — che è storia e non si riscrive — con una riga che non
    # racconta niente. Senza questa scorciatoia servirebbero due giri anche per
    # uscirne, cioè l'evento durerebbe tre giorni invece di uno.
    if attuale == "CROSSES_LIMIT" and candidate in ("OBSERVABLE", "PRIME"):
        return {"state": candidate, "from_state": attuale, "changed": False,
                "pending_state": None, "pending_count": 0, "confirmed": True}

    conteggio = (previous.get("pending_count") or 0) + 1 \
        if previous.get("pending_state") == candidate else 1

    if conteggio < CONFIRMATIONS:
        return {"state": attuale, "from_state": attuale, "changed": False,
                "pending_state": candidate, "pending_count": conteggio,
                "confirmed": False}

    nuovo = _crossing(attuale, candidate)
    return {"state": nuovo, "from_state": attuale, "changed": True,
            "pending_state": None, "pending_count": 0, "confirmed": True}


def _crossing(previous: str, candidate: str) -> str:
    """L'attraversamento del limite ha un nome suo, e si scrive una volta sola.

    Da fuori portata a dentro: è *l'evento* che il radar esiste per riportare.
    Al giro successivo il candidato sarà di nuovo OBSERVABLE o PRIME e lo stato
    ci si assesterà da sé — con `CROSSES_LIMIT` nella banda 1, cioè senza che
    l'isteresi lo tratti come un posto diverso da OBSERVABLE.
    """
    entrando = previous in ("OUT_OF_RANGE", "APPROACHING")
    return "CROSSES_LIMIT" if entrando and candidate in ("OBSERVABLE", "PRIME") \
        else candidate
