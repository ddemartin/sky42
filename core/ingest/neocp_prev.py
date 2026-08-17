"""Il **destino** dei candidati NEOCP: la tabella dei trksub già usciti di lista.

È la seconda metà della storia che nessun altro conserva. `neocp.py` legge chi
è in lista adesso; questo legge com'è finita: designato e annunciato da una
circolare, designato e basta, perso, inesistente, oppure identificato con un
altro candidato.

**La fonte non è quella prevista.** Il progetto dava per scontato di doverla
ricavare dalle circolari MPEC (`mpec_poll` in CLAUDE.md), leggendo il testo di
ogni circolare per cercarci dentro le designazioni temporanee. Non serve:
l'MPC pubblica la corrispondenza già fatta, in tabella, a
`/mpcops/neocp/neocp_prev_des/` — cinque colonne, un centinaio di righe,
quattro giorni di storia. Verificato il 2026-08-17; il vecchio indirizzo
`iau/NEO/PreviousNEOCPObjects.html` risponde 404 e la voce di menu porta qui.

**Il vocabolario degli stati è misurato, non documentato.** L'MPC non pubblica
una legenda, quindi i codici si tengono **testuali** in `resolution_source` e
si traducono solo dove il significato è certo. `na` compare otto volte su cento
e il suo significato non è verificato: finisce in `removed` — è certo che sia
uscito di lista senza designazione — con il codice grezzo accanto, così il
giorno in cui si saprà cosa vuol dire sarà una rilettura e non un dato perso.
"""
from __future__ import annotations

import html as html_mod
import logging
import re

log = logging.getLogger("sky42.ingest.neocp_prev")

URL = "https://www.minorplanetcenter.net/mpcops/neocp/neocp_prev_des/"

# Le cinque colonne, nell'ordine in cui l'MPC le pubblica.
COLUMNS = ("trksub", "iau_desig", "status", "reference", "datetime_ut")

# L'MPC scrive «None» come stringa, non una cella vuota.
_VUOTO = {"", "None", "none", "-"}

# I codici di stato osservati il 2026-08-17 su cento righe:
#   lost 17, na 8, dne 7, e 63 righe senza stato (designate).
# Tutto ciò che non è un codice noto e non è vuoto è un **altro trksub**: il
# candidato è stato identificato con un altro candidato, e il destino è quello
# dell'altro (vedi `resolve`).
STATUS_RESOLUTION = {
    # Non si è più ripreso: nessuno l'ha confermato.
    "lost": "not_confirmed",
    # «Does not exist»: le osservazioni non reggevano.
    "dne": "removed",
    # Significato non verificato — probabilmente «not an asteroid», ma l'MPC
    # non lo documenta e non lo si inventa. Certo è che è uscito di lista senza
    # designazione, e questo `removed` lo dice.
    "na": "removed",
}

_TRKSUB = re.compile(r"^[A-Za-z0-9]{5,12}$")


def parse(page: str) -> list[dict]:
    """Le righe della tabella, senza interpretarle. Una riga malformata si salta.

    Si legge l'HTML con una regex sulle celle e non con un parser DOM: la
    tabella è generata dal server, ha cinque colonne fisse, e aggiungere una
    dipendenza per centinaia di byte di struttura sarebbe sproporzionato. Se un
    giorno la pagina cambierà forma, `parse` restituirà zero righe — e zero
    righe è un caso che chi chiama tratta già come «non toccare niente».
    """
    righe = []
    for blocco in re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I):
        celle = [_testo(c) for c in
                 re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", blocco, re.S | re.I)]
        if len(celle) != len(COLUMNS) or celle[0] == "trksub":
            continue                                    # intestazione o riga d'altro tipo
        riga = dict(zip(COLUMNS, celle))
        if not riga["trksub"]:
            continue
        grezze = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", blocco, re.S | re.I)
        mpec_id = _mpec_id(riga["reference"])
        righe.append({
            "trksub": riga["trksub"],
            "iau_desig": _oppure_none(riga["iau_desig"]),
            "status": _oppure_none(riga["status"]),
            "mpec_id": mpec_id,
            # L'indirizzo della circolare è già nella cella, come collegamento:
            # si prende quello. `mpec_url` resta la riserva per quando non c'è —
            # una regola di impacchettamento verificata è comunque meno
            # affidabile di un link scritto da chi pubblica.
            "mpec_url": _href(grezze[3]) or mpec_url(mpec_id),
            "seen_at": _istante(riga["datetime_ut"]),
        })
    if not righe:
        log.warning("neocp_prev: nessuna riga riconosciuta (%d byte)", len(page))
    return righe


def _testo(cella: str) -> str:
    return html_mod.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", cella))).strip()


def _oppure_none(v: str) -> str | None:
    return None if v in _VUOTO else v


def _href(cella: str) -> str | None:
    m = re.search(r'href="([^"]+)"', cella or "")
    return html_mod.unescape(m.group(1)) if m else None


def _mpec_id(riferimento: str) -> str | None:
    """«MPEC 2026-Q11» → «2026-Q11». Qualunque altra forma resta None."""
    if riferimento in _VUOTO:
        return None
    m = re.search(r"(\d{4}-[A-Z]\d+)", riferimento)
    return m.group(1) if m else None


def _istante(v: str) -> str | None:
    """«2026-08-17T11:52:03» → il nostro ISO con la Z.

    L'MPC scrive l'ora UT senza fuso; il resto del progetto scrive sempre la Z,
    e due formati di timestamp nello stesso database sono un confronto
    sbagliato che aspetta di succedere.
    """
    if v in _VUOTO:
        return None
    m = re.match(r"(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})", v)
    return f"{m.group(1)}T{m.group(2)}Z" if m else None


def resolve(rows: list[dict]) -> list[dict]:
    """Da riga grezza a destino, seguendo **una** identificazione fra candidati.

    Le combinazioni osservate, e cosa significano:

    * designazione + circolare → `confirmed_neo` (o `confirmed_comet` se la
      designazione è cometaria): l'MPC ha ritenuto l'oggetto degno di un MPEC.
    * designazione senza circolare → `known_object`: ha un numero di catalogo,
      ma nessuna circolare. È il caso più frequente dopo i persi — un pianetino
      ordinario, che è come vanno a finire quasi tutti i candidati. La
      designazione dice da sola se era già noto: `2013 SS24` esisteva dal 2013.
    * uno dei codici di `STATUS_RESOLUTION` → perso, inesistente, rimosso.
    * uno stato che è **un altro trksub** → i due sono lo stesso oggetto, e il
      destino è quello dell'altro. Si segue un salto solo: le catene più lunghe
      di uno non si sono mai viste, e un ciclo fra due righe manderebbe in
      cerchio un job che gira da solo alle tre di notte.

    Quel che non si sa resta `unknown`, che è diverso da NULL: NULL significa
    «non l'abbiamo ancora cercato», `unknown` significa «l'MPC l'ha chiuso in un
    modo che non sappiamo tradurre».
    """
    per_trksub = {r["trksub"]: r for r in rows}
    out = []
    for r in rows:
        esito = _esito(r)
        if esito is None and r["status"] and _TRKSUB.match(r["status"]):
            # Identificato con un altro candidato: si eredita il suo destino,
            # ma la fonte resta l'identificazione — o fra un anno sembrerebbe
            # che quella circolare parlasse di questo trksub.
            altro = per_trksub.get(r["status"])
            esito = _esito(altro) if altro else None
            if esito:
                esito = {**esito, "resolution_source": f"neocp_prev:={r['status']}"}
            else:
                esito = {"resolution": "unknown", "resolved_desig": None,
                         "mpec_id": None,
                         "resolution_source": f"neocp_prev:={r['status']}"}
        if esito is None:
            esito = {"resolution": "unknown", "resolved_desig": None, "mpec_id": None,
                     "resolution_source": f"neocp_prev:{r['status'] or '?'}"}
        out.append({**r, **esito})
    return out


def _esito(r: dict | None) -> dict | None:
    """Il destino di una riga presa da sola. `None` = non traducibile qui."""
    if r is None:
        return None
    if r["iau_desig"]:
        cometa = is_comet_designation(r["iau_desig"])
        return {
            "resolution": ("confirmed_comet" if cometa else
                           "confirmed_neo" if r["mpec_id"] else "known_object"),
            "resolved_desig": r["iau_desig"],
            "mpec_id": r["mpec_id"],
            "resolution_source": (f"mpec:{r['mpec_id']}" if r["mpec_id"]
                                  else "neocp_prev:designato"),
        }
    if r["status"] in STATUS_RESOLUTION:
        return {"resolution": STATUS_RESOLUTION[r["status"]], "resolved_desig": None,
                "mpec_id": None, "resolution_source": f"neocp_prev:{r['status']}"}
    return None


def is_comet_designation(desig: str) -> bool:
    """`C/2026 K1`, `P/2013 YG46`, `123P` sono comete; `2026 PN9` no."""
    return bool(re.match(r"^[CPDXAI]/", desig) or re.match(r"^\d+[PD](-[A-Z])?$", desig))


# --- l'indirizzo di una circolare ------------------------------------------
# `2026-Q11` → `/mpec/K26/K26Q11.html`. Il numero **non** è decimale sopra il
# 99: l'MPC lo impacchetta con una lettera per le centinaia e decine, ed è la
# differenza fra un collegamento che funziona e un 404. Verificato il
# 2026-08-17 su quattro casi veri: K26Q11 e K26P99 rispondono 200, K26P114 dà
# 404 e la forma giusta è **K26PB4** (114 → B4), come K26PA0 per il 100.
_PACK = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz"


def mpec_url(mpec_id: str) -> str | None:
    """L'indirizzo della circolare, o `None` se l'identificativo non ha la forma attesa."""
    m = re.match(r"^(\d{4})-([A-Z])(\d+)$", mpec_id or "")
    if not m:
        return None
    anno, mezzo_mese, numero = int(m.group(1)), m.group(2), int(m.group(3))
    secolo = _PACK[anno // 100 - 10]        # 2026 → 'K'
    if numero < 100:
        coda = f"{numero:02d}"
    else:
        decine = numero // 10 - 10
        if decine >= len(_PACK):
            return None                      # oltre le nostre regole: meglio nessun link
        coda = f"{_PACK[decine]}{numero % 10}"
    return (f"https://www.minorplanetcenter.net/mpec/"
            f"{secolo}{anno % 100:02d}/{secolo}{anno % 100:02d}{mezzo_mese}{coda}.html")
