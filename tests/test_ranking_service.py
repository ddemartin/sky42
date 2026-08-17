"""Il punteggio applicato ai dati veri: profilo dal database, finestre in pagina.

Qui si prova il cablaggio — che il profilo attivo venga letto, che il contesto
dell'oggetto arrivi dalle tre tabelle giuste, e che le finestre di `tonight`
escano con `score`, `grade` e la loro scomposizione. Le formule stanno in
test_ranking.py.
"""
from __future__ import annotations

import json

import pytest

from core.db import connect
from core.ranking.score import DEFAULT_WEIGHTS
from services import ranking_service, screening_service, window_service
from tests.test_radar_service import catalogo  # noqa: F401  (fixture)


def test_il_profilo_di_partenza_e_nel_database(db):
    profilo = ranking_service.active_profile()
    assert profilo.name == "default"
    assert profilo.weights == DEFAULT_WEIGHTS
    assert profilo.grades["PRIME"] == 0.75


def test_un_profilo_piu_specifico_vince(db):
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO scoring_profile (name, target_kind, weights, gates, active,
                                            updated_at)
               VALUES ('comete','comet',?,'{}',1,'2026-08-17T00:00:00Z')""",
            (json.dumps({"depth": 3.0}),))
    finally:
        conn.close()

    assert ranking_service.active_profile("comet").name == "comete"
    assert ranking_service.active_profile("asteroid").name == "default"


def test_senza_profili_si_usano_i_valori_di_partenza(db):
    """Un database su cui nessuno ha ancora tarato niente deve produrre
    classifiche lo stesso, non un errore."""
    conn = connect()
    try:
        conn.execute("DELETE FROM scoring_profile")
    finally:
        conn.close()
    assert ranking_service.active_profile().weights == DEFAULT_WEIGHTS


def test_il_contesto_mette_insieme_orbita_stats_e_watchlist(catalogo):  # noqa: F811
    screening_service.run_screening()

    conn = connect()
    try:
        riga = dict(conn.execute(
            """SELECT t.id, t.kind, o.tisserand_j, o.arc_days, o.n_oppositions,
                      o.last_obs_date
               FROM target t JOIN orbit o ON o.target_id=t.id
               WHERE t.primary_desig='3200'""").fetchone())
    finally:
        conn.close()

    ctx = ranking_service.target_context(riga)
    assert ctx["watchlist"] is True                      # da `watchlist`
    assert ctx["tisserand_j"] == pytest.approx(4.51)     # da `orbit`
    assert ctx["years_since_last_obs"] > 6.0             # da `target_stats`
    assert "years_since_good_apparition" in ctx


def test_tonight_porta_il_punteggio_con_la_sua_scomposizione(catalogo):  # noqa: F811
    dati = window_service.tonight("3200")
    assert dati is not None and dati["windows"]

    for w in dati["windows"]:
        assert w["grade"] in ("PRIME", "GOOD", "POSSIBLE", "POOR", "NOT_USEFUL")
        # Il punteggio non esce mai da solo (regola 5).
        assert w["score_json"]["profile"] == "default"
        assert "features" in w["score_json"] and "weights" in w["score_json"]
        if w["score"] is None:
            assert w["grade"] == "NOT_USEFUL" and w["score_json"]["gates_failed"]
        else:
            j = w["score_json"]
            assert sum(j["contributions"].values()) / j["weight_total"] == \
                pytest.approx(w["score"])


def test_l_ordine_resta_quello_del_margine(catalogo):  # noqa: F811
    """Su un oggetto solo il ranking spiega, non sceglie: se cominciasse a
    riordinare, la pagina «da dove lo prendo meglio» direbbe un'altra cosa."""
    dati = window_service.tonight("3200")
    margini = [w.get("depth_margin") for w in dati["windows"] if w["useful"]]
    assert margini == sorted(margini, reverse=True)
