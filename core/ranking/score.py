"""Il punteggio, e la sua scomposizione — che è la parte che conta.

`score` da solo è un numero senza appello. Quello che si salva accanto, in
`score_json`, è il motivo: quali cancelli sono stati superati, quanto valeva
ogni feature, quanto ha pesato, e quanto ha contribuito. Un ranking che non si
sa spiegare non si tara, e **la taratura è il progetto** (regola 5).

Per lo stesso motivo i pesi non stanno nel codice ma in `scoring_profile`: qui
c'è solo il profilo di partenza, che è un punto da cui muoversi guardando le
classifiche vere, non un valore giusto.

**Prima i cancelli.** Fuori da questi non c'è punteggio: un oggetto che non sta
sotto il limite con margine non è ultimo in classifica, è `NOT_USEFUL`. La
distinzione conta perché un ultimo posto si guarda comunque, e un NOT_USEFUL no.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field

from core.ranking.features import FEASIBILITY, INTEREST, features

# Il profilo di partenza. I due gruppi pesano quasi uguale di proposito: uno
# strumento che vede tutto senza niente di interessante e un oggetto
# irresistibile che non si riesce a riprendere sono due modi diversi di
# perdere la notte.
DEFAULT_WEIGHTS = {
    # interesse
    "tisserand": 1.0,
    "rarity": 0.8,
    "return": 0.8,
    "watchlist": 1.2,
    "short_arc": 0.4,
    # fattibilità
    "depth": 1.2,
    "window": 0.8,
    "airmass": 0.5,
    "fov_fit": 0.4,
    "exposure_fit": 0.6,
}

DEFAULT_GATES = {
    "depth_margin_min": 0.3,        # mag: sotto il limite *con margine*
    "useful_hours_min": 0.5,
    "max_track_rate_arcsec_min": None,   # se il setup ne dichiara uno
}

# Soglie di giudizio. Stanno nel profilo perché si spostano insieme ai pesi:
# ritoccare un peso senza ritoccare queste sposta metà catalogo di grado
# facendo credere che sia cambiato il cielo.
DEFAULT_GRADES = {"PRIME": 0.75, "GOOD": 0.55, "POSSIBLE": 0.35}

GRADES = ("PRIME", "GOOD", "POSSIBLE", "POOR", "NOT_USEFUL")


@dataclass(frozen=True)
class Profile:
    """Pesi, cancelli e soglie. Da `scoring_profile`, o quello di partenza."""

    name: str = "default"
    target_kind: str | None = None
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    gates: dict = field(default_factory=lambda: dict(DEFAULT_GATES))
    grades: dict = field(default_factory=lambda: dict(DEFAULT_GRADES))

    @classmethod
    def from_row(cls, row: Mapping) -> "Profile":
        """Da una riga di `scoring_profile`: `weights` e `gates` sono JSON.

        Le chiavi mancanti prendono il valore di partenza invece di sparire: un
        profilo scritto a mano che elenca tre pesi vuole dire «questi tre sono
        diversi», non «gli altri sette valgono zero».
        """
        pesi ={**DEFAULT_WEIGHTS, **(_loads(row.get("weights")) or {})}
        cancelli = {**DEFAULT_GATES, **(_loads(row.get("gates")) or {})}
        gradi = {**DEFAULT_GRADES, **(cancelli.pop("grades", None) or {})}
        return cls(name=row.get("name") or "default",
                   target_kind=row.get("target_kind"),
                   weights=pesi, gates=cancelli, grades=gradi)


def _loads(value):
    import json

    if value is None or isinstance(value, dict):
        return value
    return json.loads(value)


def check_gates(window: Mapping, profile: Profile) -> list[str]:
    """I cancelli non superati, per nome. Vuoto = si passa.

    Si restituisce l'elenco e non un booleano perché «perché questo oggetto non
    è in lista» è la domanda che si fa la mattina dopo, e `NOT_USEFUL` da solo
    non risponde.
    """
    g = profile.gates
    falliti = []

    if not window.get("useful"):
        falliti.append("finestra utile assente")
    margine = window.get("depth_margin")
    minimo = g.get("depth_margin_min")
    if minimo is not None and (margine is None or float(margine) < float(minimo)):
        falliti.append(f"margine < {minimo} mag")
    ore = window.get("useful_hours")
    min_ore = g.get("useful_hours_min")
    if min_ore is not None and (ore is None or float(ore) < float(min_ore)):
        falliti.append(f"finestra < {min_ore} h")
    mu, max_mu = window.get("motion_arcsec_min"), g.get("max_track_rate_arcsec_min")
    if max_mu is not None and mu is not None and float(mu) > float(max_mu):
        falliti.append(f"moto > {max_mu}\"/min")
    return falliti


def combine(feats: Mapping[str, float | None], profile: Profile) -> dict:
    """Media pesata delle feature presenti, con i contributi uno per uno.

    Le feature `None` **non entrano né al numeratore né al denominatore**: un
    oggetto senza Tisserand viene giudicato su quello che si sa di lui, non
    punito per quello che non si sa. La conseguenza da tenere a mente è che due
    oggetti con feature diverse non hanno lo stesso denominatore — è il prezzo
    di non inventare dati, e si legge in `score_json`.
    """
    contributi, peso_totale, somma = {}, 0.0, 0.0
    for nome, valore in feats.items():
        peso = float(profile.weights.get(nome, 0.0))
        if valore is None or peso == 0.0:
            continue
        contributi[nome] = peso * float(valore)
        somma += contributi[nome]
        peso_totale += peso
    punteggio = somma / peso_totale if peso_totale > 0 else 0.0
    return {"score": punteggio, "contributions": contributi,
            "weight_total": peso_totale}


def grade_of(score: float | None, profile: Profile, gated: bool = False) -> str:
    if gated or score is None:
        return "NOT_USEFUL"
    for nome in ("PRIME", "GOOD", "POSSIBLE"):
        if score >= float(profile.grades[nome]):
            return nome
    return "POOR"


def score_window(window: Mapping, target: Mapping | None = None,
                 profile: Profile | None = None) -> dict:
    """Punteggio, giudizio e scomposizione per una coppia (target × setup).

    Restituisce le tre colonne di `observation_window` — `score`, `score_json`,
    `grade` — dove `score_json` è un dizionario, non una stringa: la
    serializzazione la fa chi scrive nel database, come per ogni altro JSON del
    progetto.

    Un oggetto fermato da un cancello ha `score = None`: non è zero, perché
    zero è un punteggio e questo è un «non pertinente». La scomposizione c'è
    lo stesso, e dice quale cancello.
    """
    profile = profile or Profile()
    falliti = check_gates(window, profile)
    feats = features(dict(window), dict(target or {}))

    esito = combine(feats, profile)
    scomposizione = {
        "profile": profile.name,
        "gates_failed": falliti,
        "features": feats,
        "weights": {k: profile.weights.get(k) for k in feats},
        "contributions": esito["contributions"],
        "weight_total": esito["weight_total"],
        "interest": _gruppo(esito["contributions"], profile, INTEREST),
        "feasibility": _gruppo(esito["contributions"], profile, FEASIBILITY),
        "score": esito["score"],
    }
    punteggio = None if falliti else esito["score"]
    return {"score": punteggio, "score_json": scomposizione,
            "grade": grade_of(punteggio, profile, gated=bool(falliti))}


def _gruppo(contributi: Mapping, profile: Profile, nomi) -> float | None:
    """Il sottototale di un gruppo, normalizzato sui suoi pesi.

    Serve a leggere la classifica: «è alto perché è interessante o perché è
    facile» è la domanda con cui si tara un profilo, e sommare i due gruppi
    in un numero solo la cancella.
    """
    peso = sum(float(profile.weights.get(n, 0.0)) for n in nomi if n in contributi)
    if peso <= 0:
        return None
    return sum(contributi[n] for n in nomi if n in contributi) / peso
