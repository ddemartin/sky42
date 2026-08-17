"""Le liste dei candidati MPC: NEOCP e PCCP.

Sono l'unica sorgente del progetto che **non conserva niente**: l'MPC riscrive
la lista e quello che c'era ieri non è più recuperabile da nessuna parte. La
storia dei candidati esiste solo se ce la scriviamo noi (regola 1: per questo
`mpc_candidate` e `mpc_candidate_snapshot` stanno nel backup).

**La fonte è il testo, per tutte e due le liste.** NEOCP ha anche un JSON
(`Extended_Files/neocp.json`), PCCP no. Il JSON sembrava la scelta ovvia —
tipizzato, niente colonne da indovinare — ma i due prodotti dell'MPC **non
concordano**: misurato il 2026-08-17 sullo stesso istante, `RMM2026` ha arco
1821.94 giorni e H 18.9 nel testo, 821.94 e 18.0 nel JSON. Su 96 candidati è
l'unico che diverge, ed è l'unico con l'arco sopra i cento giorni. Non si può
sapere da fuori quale dei due sbagli; si può però scegliere di **avere un solo
percorso di lettura invece di due**, e quel percorso deve essere quello che
funziona anche per PCCP. Anche il testo ha ETag e Last-Modified, quindi non si
rinuncia a niente.

`parse_json` resta, e non è codice morto: è la controprova quando un numero non
torna, ed è la via di riserva il giorno in cui il formato del testo cambierà —
un servizio che gira da solo non deve restare cieco su NEOCP finché qualcuno
non aggiusta una regex.

**Il testo non è a colonne fisse come sembra.** Le righe sono lunghe 101 o 102
caratteri: la colonna dell'arco osservativo trabocca quando l'arco supera i
mille giorni, e succede proprio sugli oggetti che stanno in lista da mesi — cioè
i più interessanti. Si àncora quindi una regex alla *coda* numerica, che è
l'unica parte con struttura garantita, e si lascia libera la nota centrale, che
è l'unico campo con spazi dentro.

Quello che le liste **non** danno: moto apparente, incertezza di posizione ed
elementi orbitali. Per averli servirebbe una chiamata per oggetto a
`confirmeph2.cgi`, che è un'altra cosa e ha un altro costo. Le colonne restano
NULL, e restano NULL in modo visibile.
"""
from __future__ import annotations

import json
import logging
import re

from core.timeutil import jd_from_ymd

log = logging.getLogger("sky42.ingest.neocp")

LISTS = ("NEOCP", "PCCP")

# `desig score anno mese giorno RA Dec V <nota con spazi> NObs Arco H NonVisto`
#
# La nota è non greedy e tutto ciò che la segue è ancorato a destra: è il modo
# per non doversi fidare di nessuna larghezza di colonna. Un campo numerico che
# manca fa fallire la riga intera, che è quel che si vuole — mezza riga di
# candidato è peggio di nessuna riga.
_RIGA = re.compile(
    r"^(?P<temp_desig>\S+)\s+"
    r"(?P<score>-?\d+)\s+"
    r"(?P<year>\d{4})\s+(?P<month>\d{1,2})\s+(?P<day>[\d.]+)\s+"
    r"(?P<ra_hours>[\d.]+)\s+"
    r"(?P<dec_deg>[+-][\d.]+)\s+"
    r"(?P<v_mag>[\d.]+)\s+"
    r"(?P<note>.*?)\s+"
    r"(?P<n_obs>\d+)\s+"
    r"(?P<arc_days>[\d.]+)\s+"
    r"(?P<h_mag>-?[\d.]+)\s+"
    r"(?P<not_seen_days>[\d.]+)\s*$"
)


def parse_text(text: str, list_name: str) -> list[dict]:
    """Da `neocp.txt` / `pccp.txt` ai record dei candidati.

    Le righe che non corrispondono si contano e si registrano nel log invece di
    far fallire tutto: una lista con un record storto vale ancora, e accorgersi
    che il formato è cambiato è un'altra cosa dal fermarsi.
    """
    fuori = 0
    out = []
    for riga in text.splitlines():
        if not riga.strip():
            continue
        m = _RIGA.match(riga)
        if m is None:
            fuori += 1
            log.warning("%s: riga non riconosciuta: %r", list_name, riga[:80])
            continue
        out.append(_record(m.groupdict(), list_name, riga))
    if fuori:
        log.warning("%s: %d righe su %d non riconosciute", list_name, fuori,
                    fuori + len(out))
    return out


def parse_json(payload: str | bytes, list_name: str = "NEOCP") -> list[dict]:
    """Da `neocp.json` agli stessi record di `parse_text`.

    Le chiavi dell'MPC hanno punti e maiuscole (`R.A.`, `Not_Seen_dys`): si
    traducono qui, in un posto solo, come per le colonne di ASTORB.
    """
    dati = json.loads(payload)
    out = []
    for r in dati:
        grezzo = {
            "temp_desig": r.get("Temp_Desig"),
            "score": r.get("Score"),
            "year": r.get("Discovery_year"),
            "month": r.get("Discovery_month"),
            "day": r.get("Discovery_day"),
            "ra_hours": r.get("R.A."),
            "dec_deg": r.get("Decl."),
            "v_mag": r.get("V"),
            "note": r.get("Updated"),
            "n_obs": r.get("NObs"),
            "arc_days": r.get("Arc"),
            "h_mag": r.get("H"),
            "not_seen_days": r.get("Not_Seen_dys"),
        }
        out.append(_record(grezzo, list_name, json.dumps(r, sort_keys=True)))
    return out


# L'MPC riempie la colonna della magnitudine con 99.9 quando non la conosce.
# Preso alla lettera è un oggetto di magnitudine 99.9, cioè inosservabile con
# qualunque telescopio esistente: finirebbe in fondo a ogni classifica come se
# fosse un dato, invece che in un elenco a parte come «non lo sappiamo».
# Visto davvero al primo giro sul catalogo vero (A11FAuF, 2026-08-17).
V_IGNOTA = 99.0


def _record(g: dict, list_name: str, raw: str) -> dict:
    """La forma unica: gradi, giorni, JD. Le unità dell'MPC restano fuori."""
    v = _num(g["v_mag"])
    return {
        "list": list_name,
        "temp_desig": str(g["temp_desig"]).strip(),
        "score": _num(g["score"]),
        # **L'MPC pubblica la RA in ore.** Moltiplicarla per 15 è l'unico punto
        # in cui questa conversione deve esistere: da qui in poi, e in tutto il
        # resto del progetto, la RA è in gradi.
        "ra_deg": None if _num(g["ra_hours"]) is None else _num(g["ra_hours"]) * 15.0,
        "dec_deg": _num(g["dec_deg"]),
        "v_mag": None if v is None or v >= V_IGNOTA else v,
        "n_obs": _int(g["n_obs"]),
        "arc_days": _num(g["arc_days"]),
        # Lo schema tiene le ore: un candidato NEOCP vive di ore d'arco, e
        # «0.02 giorni» non si legge.
        "arc_hours": None if _num(g["arc_days"]) is None else _num(g["arc_days"]) * 24.0,
        "h_mag": _num(g["h_mag"]),
        "not_seen_days": _num(g["not_seen_days"]),
        "discovery_jd": _discovery_jd(g),
        "note": (g.get("note") or "").strip(),
        # «Added» è la prima comparsa secondo l'MPC, «Updated» un aggiornamento.
        # Non coincide con il nostro `first_seen`, che è quando l'abbiamo visto
        # noi: fra i due c'è la latenza del polling, e servono entrambi.
        "mpc_added": (g.get("note") or "").strip().lower().startswith("added"),
        "raw": raw,
    }


def _discovery_jd(g: dict) -> float | None:
    try:
        return jd_from_ymd(int(g["year"]), int(g["month"]), float(g["day"]))
    except (TypeError, ValueError):
        return None


def _num(x) -> float | None:
    if x is None or x == "":
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _int(x) -> int | None:
    v = _num(x)
    return None if v is None else int(v)
