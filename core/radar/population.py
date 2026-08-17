"""Chi si monitora: regole dichiarative, non un `WHERE` scritto nel codice.

La popolazione di partenza del progetto sono gli asteroidi su orbita cometaria
(Tj < 3, tolte le famiglie risonanti stabili), ma **non è né sarà l'unica**:
un oggetto curioso, una cometa che rientra, un NEO brillante, una lista fatta a
mano per un mese, gli oggetti che serviranno a cercare congiunzioni strette.
Inchiodare quel criterio in una query significa che ogni nuova curiosità è una
modifica al codice, un rebuild dell'immagine e un riavvio del servizio.

Qui invece i criteri sono **dati**: stanno in `setting.screening_selectors`,
sono una lista di regole con un nome, e si accendono e si spengono senza
toccare niente. Ogni regola compila in un pezzo di `WHERE`; le condizioni
dentro una regola sono in AND, le regole fra loro in OR.

**Vocabolario chiuso, non SQL nella configurazione.** Le chiavi ammesse sono
quelle di `PREDICATES` e basta: una configurazione che contenesse SQL sarebbe
una superficie di iniezione, e soprattutto un modo per scoprire un errore di
sintassi alle due di notte dentro un job. Una chiave sconosciuta è un errore
esplicito, non una regola ignorata in silenzio.

**Ogni oggetto si porta dietro il perché.** La query restituisce, per ciascuno,
quali regole l'hanno preso: senza, la domanda «perché sto guardando questo
sasso» non ha risposta appena le regole diventano più di una — e diventano
più di una subito.
"""
from __future__ import annotations

from collections.abc import Mapping

# Ogni predicato è (frammento SQL, quanti parametri, come si passano).
# `?` viene sostituito posizionalmente; le liste si espandono in un IN.
#
# Le tabelle disponibili nel frammento sono quelle della query di popolazione:
#   t = target, o = orbit, x = astorb_extra (LEFT JOIN, può essere NULL)
_SCALAR = {
    "kind": "t.kind = ?",
    "tisserand_max": "(o.tisserand_j IS NOT NULL AND o.tisserand_j < ?)",
    "tisserand_min": "(o.tisserand_j IS NOT NULL AND o.tisserand_j >= ?)",
    "h_max": "(o.h_mag IS NOT NULL AND o.h_mag <= ?)",
    "h_min": "(o.h_mag IS NOT NULL AND o.h_mag >= ?)",
    "q_max": "(o.q_derived_au IS NOT NULL AND o.q_derived_au <= ?)",
    "q_min": "(o.q_derived_au IS NOT NULL AND o.q_derived_au >= ?)",
    "a_max": "(o.a_au IS NOT NULL AND o.a_au <= ?)",
    "a_min": "(o.a_au IS NOT NULL AND o.a_au >= ?)",
    "e_max": "o.e <= ?",
    "e_min": "o.e >= ?",
    "i_max": "o.i_deg <= ?",
    "i_min": "o.i_deg >= ?",
    "period_max_yr": "(o.period_yr IS NOT NULL AND o.period_yr <= ?)",
    # L'incertezza **è** il segnale di rarità: un oggetto con CEU alta è un
    # oggetto che nessuno riprende da anni (memorandum del 15 agosto).
    "ceu_min_arcsec": "(x.ceu_arcsec IS NOT NULL AND x.ceu_arcsec >= ?)",
    "ceu_max_arcsec": "(x.ceu_arcsec IS NOT NULL AND x.ceu_arcsec <= ?)",
    # Confronto fra date via julianday da entrambe le parti, mai come stringhe.
    "not_observed_since_years":
        "(o.last_obs_date IS NOT NULL AND "
        " julianday('now') - julianday(o.last_obs_date) > ? * 365.25)",
    "n_oppositions_max": "(o.n_oppositions IS NOT NULL AND o.n_oppositions <= ?)",
    "arc_days_max": "(o.arc_days IS NOT NULL AND o.arc_days <= ?)",
}

_LIST = {
    "kind_in": "t.kind IN ({})",
    "orbit_class_in": "t.orbit_class IN ({})",
    # Gli oggetti senza classe **restano dentro**: una classe che manca non è
    # una classe esclusa, e a escluderli si perderebbero gli oggetti nuovi,
    # che sono quelli che interessano di più.
    "orbit_class_not_in": "(t.orbit_class IS NULL OR t.orbit_class NOT IN ({}))",
    "desig_in": "t.primary_desig IN ({})",
}

_FLAG = {
    "watchlist": ("t.id IN (SELECT target_id FROM watchlist)",
                  "t.id NOT IN (SELECT target_id FROM watchlist)"),
    "unnumbered": ("t.number IS NULL", "t.number IS NOT NULL"),
    "has_ceu": ("x.ceu_arcsec IS NOT NULL", "x.ceu_arcsec IS NULL"),
}

# Chiavi che descrivono la regola invece di filtrare.
_META = {"name", "enabled", "note"}

PREDICATES = frozenset(_SCALAR) | frozenset(_LIST) | frozenset(_FLAG)


class SelectorError(ValueError):
    """Regola non valida. Il messaggio dice **quale regola** e **quale chiave**."""


def compile_selector(sel: Mapping) -> tuple[str, list]:
    """Una regola → (frammento SQL in AND, parametri).

    Una regola senza nessun predicato prenderebbe tutto il catalogo: è quasi
    sempre un errore di battitura in una chiave, e si rifiuta invece di
    propagare un milione e mezzo di oggetti a uno screening.
    """
    nome = sel.get("name") or "(senza nome)"
    pezzi, params = [], []

    for chiave, valore in sel.items():
        if chiave in _META:
            continue
        if chiave not in PREDICATES:
            raise SelectorError(
                f"regola «{nome}»: chiave sconosciuta «{chiave}». "
                f"Ammesse: {', '.join(sorted(PREDICATES))}")

        if chiave in _SCALAR:
            pezzi.append(_SCALAR[chiave])
            params.append(valore)
        elif chiave in _LIST:
            valori = list(valore or [])
            if not valori:
                raise SelectorError(f"regola «{nome}»: «{chiave}» è una lista vuota")
            pezzi.append(_LIST[chiave].format(",".join("?" * len(valori))))
            params.extend(valori)
        else:
            vero, falso = _FLAG[chiave]
            pezzi.append(vero if valore else falso)

    if not pezzi:
        raise SelectorError(f"regola «{nome}»: nessun criterio, prenderebbe tutto")
    return " AND ".join(pezzi), params


def enabled_selectors(selectors) -> list[dict]:
    return [dict(s) for s in (selectors or []) if s.get("enabled", True)]


def population_query(selectors, limit: int | None = None) -> tuple[str, list, list[str]]:
    """La query della popolazione monitorata, con una colonna per regola.

    Restituisce `(sql, params, nomi)`. Le colonne `sel_0 … sel_n` valgono 1
    quando quella regola ha preso quell'oggetto: si ricompongono in nomi a
    valle, e finiscono in `target_stats.selectors`.

    L'ordine è per `t.id` e non è un dettaglio: lo screening lavora a blocchi e
    un ordine stabile rende ripetibile *quale* oggetto sta in quale blocco,
    che è la differenza fra un job che si può confrontare con quello di ieri e
    uno che no.
    """
    regole = enabled_selectors(selectors)
    if not regole:
        raise SelectorError("nessuna regola attiva: la popolazione sarebbe vuota")

    frammenti, params_where, colonne, params_col, nomi = [], [], [], [], []
    for i, sel in enumerate(regole):
        sql, params = compile_selector(sel)
        frammenti.append(f"({sql})")
        params_where.extend(params)
        # Lo stesso frammento serve due volte — una per filtrare, una per dire
        # chi ha preso cosa — e i parametri vanno passati due volte: SQLite
        # numera i `?` posizionalmente, e le colonne vengono prima del WHERE.
        colonne.append(f"CASE WHEN ({sql}) THEN 1 ELSE 0 END AS sel_{i}")
        params_col.extend(params)
        nomi.append(sel.get("name") or f"regola_{i}")

    sql = f"""
        SELECT t.id, t.kind, t.primary_desig, t.display_name, t.orbit_class, t.number,
               o.epoch_jd, o.a_au, o.q_au, o.e, o.i_deg, o.node_deg, o.argp_deg,
               o.m_deg, o.tp_jd, o.h_mag, o.g_slope, o.m1, o.k1,
               o.tisserand_j, o.last_obs_date, o.arc_days, o.n_oppositions,
               x.ceu_arcsec, x.ceu_rate, x.ceu_date,
               {', '.join(colonne)}
        FROM target t
        JOIN orbit o ON o.target_id = t.id
        LEFT JOIN astorb_extra x ON x.target_id = t.id
        WHERE {' OR '.join(frammenti)}
        ORDER BY t.id
    """
    params = params_col + params_where
    if limit:
        sql += " LIMIT ?"
        params = params + [limit]
    return sql, params, nomi


def why(row: Mapping, nomi: list[str]) -> list[str]:
    """Le regole che hanno preso questa riga, per nome."""
    return [n for i, n in enumerate(nomi) if row.get(f"sel_{i}")]


# Le regole di partenza. Le prime tre sono la popolazione di oggi; le altre
# sono spente e stanno lì come esempio funzionante — accenderne una è una
# modifica a una impostazione, non al codice, ed è esattamente il punto.
DEFAULT_SELECTORS = [
    {
        "name": "aco",
        "enabled": True,
        "kind": "asteroid",
        "tisserand_max": 3.0,
        "orbit_class_not_in": ["Jupiter Trojan", "Hilda", "Distant Object"],
        "note": "asteroidi su orbita cometaria: la popolazione del progetto",
    },
    {
        "name": "comete",
        "enabled": True,
        "kind": "comet",
        "note": "poche migliaia, ed è dove «torna a portata» conta di più",
    },
    {
        "name": "watchlist",
        "enabled": True,
        "watchlist": True,
        "note": "quello che ho messo lì a mano entra comunque, senza discutere",
    },
    {
        "name": "neo",
        "enabled": False,
        "orbit_class_in": ["Apollo", "Aten", "Amor", "Atira"],
        "h_max": 22.0,
        "note": "i NEO alla portata di un 700 mm",
    },
    {
        "name": "trascurati",
        "enabled": False,
        "not_observed_since_years": 10.0,
        "h_max": 19.0,
        "note": "brillanti e dimenticati: nessuno li riprende da dieci anni",
    },
    {
        "name": "incerti",
        "enabled": False,
        "ceu_min_arcsec": 60.0,
        "h_max": 20.0,
        "note": "la CEU alta è il segnale di rarità, non un difetto",
    },
]
