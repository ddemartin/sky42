"""Il punteggio applicato ai dati veri: profilo dal database, contesto dal catalogo.

`core/ranking/` non sa che esista SQLite; questo modulo gli porta i due
ingredienti — il profilo attivo e quello che si sa dell'oggetto — e gli chiede
il numero. Nessuna formula qui dentro.
"""
from __future__ import annotations

import logging

from core.db import connect
from core.ranking.score import Profile, score_window
from core.timeutil import years_between

log = logging.getLogger("sky42.ranking")


def active_profile(target_kind: str | None = None) -> Profile:
    """Il profilo attivo, il più specifico per quel tipo di oggetto.

    L'ordine è: profilo attivo per quel `target_kind`, poi quello attivo
    generico (`target_kind IS NULL`), poi i valori di partenza del codice. Un
    database senza profili non è un errore: è un database su cui nessuno ha
    ancora tarato niente, e deve produrre classifiche lo stesso.

    A parità di specificità vince **l'ultimo scritto** (`id` più alto): con due
    profili generici attivi la scelta dev'essere ripetibile, o la stessa
    finestra prenderebbe punteggi diversi a due caricamenti di pagina e nessuno
    capirebbe perché.
    """
    conn = connect()
    try:
        row = conn.execute(
            """SELECT * FROM scoring_profile
               WHERE active = 1 AND (target_kind = ? OR target_kind IS NULL)
               ORDER BY target_kind IS NULL, id DESC LIMIT 1""",
            (target_kind,)).fetchone()
    finally:
        conn.close()
    if row is None:
        log.debug("nessun profilo attivo in `scoring_profile`: uso i valori di partenza")
        return Profile()
    return Profile.from_row(dict(row))


def target_context(target: dict) -> dict:
    """Quel che serve alle feature d'interesse, messo insieme da tre posti.

    L'orbita dice l'arco e le opposizioni, `target_stats` dice da quanto non è
    una buona apparizione, `watchlist` dice se qualcuno l'ha marcato a mano.
    Nessuno dei tre da solo basta, e cercarli dentro `core/ranking` significa
    metterci dentro SQL.
    """
    tid = target.get("id")
    ctx = {
        "tisserand_j": target.get("tisserand_j"),
        "arc_days": target.get("arc_days"),
        "n_oppositions": target.get("n_oppositions"),
        "years_since_last_obs": years_between(target.get("last_obs_date")),
    }
    if tid is None:
        return ctx

    conn = connect()
    try:
        stats = conn.execute(
            "SELECT years_since_good_apparition, years_since_last_obs "
            "FROM target_stats WHERE target_id=?", (tid,)).fetchone()
        watch = conn.execute(
            "SELECT priority FROM watchlist WHERE target_id=?", (tid,)).fetchone()
    finally:
        conn.close()

    if stats is not None:
        ctx["years_since_good_apparition"] = stats["years_since_good_apparition"]
        # Lo screening ha già fatto questo conto; il calcolo da `last_obs_date`
        # resta come ripiego per gli oggetti che lo screening non copre.
        if stats["years_since_last_obs"] is not None:
            ctx["years_since_last_obs"] = stats["years_since_last_obs"]
    ctx["watchlist"] = watch is not None
    return ctx


def score_windows(windows: list[dict], target: dict,
                  profile: Profile | None = None) -> list[dict]:
    """Aggiunge `score`, `score_json` e `grade` a ogni finestra, in ordine.

    Non riordina la lista: l'ordine è una decisione di chi mostra, e una
    funzione che ordina *e* calcola è una funzione che poi qualcuno chiama due
    volte per un ordine diverso.
    """
    profile = profile or active_profile(target.get("kind"))
    ctx = target_context(target)
    for w in windows:
        w.update(score_window(w, ctx, profile))
    return windows
