"""Le feature: da una finestra osservativa a numeri fra 0 e 1.

Due gruppi che **non si mescolano**, perché rispondono a domande diverse
(docs/modelli.md §11):

* **interesse** — quanto mi importa di quell'oggetto. Non dipende dalla notte,
  né dal setup: un oggetto con Tj = 2.1 che non si osserva da nove anni è
  interessante anche quando è sotto l'orizzonte.
* **fattibilità** — quanto bene riesce *stanotte, da lì*. È tutta geometria e
  fotometria della finestra.

Tre regole che valgono per tutte:

1. **Ogni feature satura.** Oltre due magnitudini di margine non serve altro
   margine, oltre quattro ore di finestra non serve altra finestra, oltre dieci
   anni di abbandono la rarità non cresce. Senza saturazione un solo termine
   estremo decide la classifica da solo.
2. **Una feature che non si può calcolare vale `None`** e sparisce dalla media
   pesata, invece di valere zero. Un asteroide senza CEU non è un asteroide con
   incertezza enorme, e un oggetto iperbolico senza Tisserand non è un oggetto
   con Tisserand alto.
3. **La Luna non compare.** È già dentro `depth_margin` attraverso `eff_vlim`.
   Contarla due volte è l'errore facile di questo file, e produce classifiche
   che puniscono il plenilunio due volte.
"""
from __future__ import annotations

# --- saturazioni, tutte in un posto solo ------------------------------------
# Sono soglie di *interesse*, non di fisica: si tarano guardando le classifiche
# che producono, e stanno qui perché siano tutte visibili insieme.

TISSERAND_SAT = 2.0         # Tj ≤ 2: pieno punteggio, più cometario di così
TISSERAND_MAX = 3.0         # Tj ≥ 3: niente punteggio, non è un ACO
RARITY_YEARS = 10.0         # anni dall'ultima osservazione per il pieno
RETURN_YEARS = 10.0         # anni dall'ultima buona apparizione
SHORT_ARC_DAYS = 30.0       # sotto un mese d'arco l'orbita è tutta da rifare
DEPTH_SAT = 2.0             # mag di margine oltre le quali non serve altro
WINDOW_SAT = 4.0            # ore di finestra utile
AIRMASS_SAT = 2.5           # X oltre la quale la fattibilità è nulla

INTEREST = ("tisserand", "rarity", "return", "watchlist", "short_arc")
FEASIBILITY = ("depth", "window", "airmass", "fov_fit", "exposure_fit")


def _clip01(x) -> float:
    return 0.0 if x < 0.0 else (1.0 if x > 1.0 else float(x))


def interest_features(target: dict) -> dict[str, float | None]:
    """Quanto mi interessa quell'oggetto. `target` è una riga target ⋈ orbit ⋈ stats."""
    tj = target.get("tisserand_j")
    anni_oss = target.get("years_since_last_obs")
    anni_app = target.get("years_since_good_apparition")
    arco = target.get("arc_days")
    opp = target.get("n_oppositions")

    return {
        "tisserand": None if tj is None else
        _clip01((TISSERAND_MAX - float(tj)) / (TISSERAND_MAX - TISSERAND_SAT)),
        "rarity": None if anni_oss is None else _clip01(float(anni_oss) / RARITY_YEARS),
        "return": None if anni_app is None else _clip01(float(anni_app) / RETURN_YEARS),
        # Bonus manuale: presente solo quando c'è. Vale 1.0 e si aggiunge alla
        # media, quindi mettere un oggetto in watchlist lo alza senza che
        # *tutti gli altri* vengano puniti da un termine a zero.
        "watchlist": 1.0 if target.get("watchlist") else None,
        "short_arc": _short_arc(arco, opp),
    }


def _short_arc(arc_days, n_oppositions) -> float | None:
    """Un'orbita fragile è un motivo per osservare, non un difetto dell'oggetto.

    L'arco è la misura migliore; le opposizioni sono il ripiego per quando
    l'MPC non pubblica l'arco, e sotto le tre l'orbita è ancora in gioco.
    """
    if arc_days is not None:
        return _clip01((SHORT_ARC_DAYS - float(arc_days)) / SHORT_ARC_DAYS)
    if n_oppositions is not None:
        return _clip01((3.0 - float(n_oppositions)) / 2.0)
    return None


def feasibility_features(window: dict) -> dict[str, float | None]:
    """Quanto bene riesce stanotte da quel setup. `window` è un `observation_window`."""
    margine = window.get("depth_margin")
    ore = window.get("useful_hours")
    x = window.get("best_airmass")
    fov = window.get("fov_fit_ratio")

    return {
        "depth": None if margine is None else _clip01(float(margine) / DEPTH_SAT),
        "window": None if ore is None else _clip01(float(ore) / WINDOW_SAT),
        "airmass": None if x is None else
        _clip01((AIRMASS_SAT - float(x)) / (AIRMASS_SAT - 1.0)),
        # 0 = l'incertezza riempie il campo, 1 = ci sta comodamente dentro.
        "fov_fit": None if fov is None else _clip01(1.0 - float(fov)),
        "exposure_fit": _exposure_fit(window),
    }


def _exposure_fit(window: dict) -> float | None:
    """Quanta finestra avanza dopo aver raccolto il segnale che serve.

    Non è un doppione di `depth`: il margine dice che l'oggetto *si vede*,
    questo dice se le pose ci stanno. È il caso in cui un'apertura più grande
    vince davvero — accorcia il tempo necessario, non il limite
    (docs/modelli.md §8).
    """
    ore = window.get("useful_hours")
    totale = window.get("rec_total_s")
    if not ore or totale is None:
        return None
    return _clip01(1.0 - float(totale) / (float(ore) * 3600.0))


def features(window: dict, target: dict | None = None) -> dict[str, float | None]:
    """Tutte le feature in un dizionario solo, nell'ordine in cui si leggono."""
    out = dict(interest_features(target or {}))
    out.update(feasibility_features(window))
    return out
