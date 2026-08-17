"""Il punteggio: i cancelli, le saturazioni, e la scomposizione che deve tornare.

Un ranking si tara guardando `score_json`: se la scomposizione non somma al
punteggio, quello che si legge la mattina non è quello che il codice ha fatto.
Metà di questi test difendono proprio quell'uguaglianza.
"""
from __future__ import annotations

import json

import pytest

from core.ranking import features as feat
from core.ranking.score import (
    DEFAULT_GATES,
    DEFAULT_WEIGHTS,
    Profile,
    check_gates,
    grade_of,
    score_window,
)

# Una finestra che passa comodamente tutti i cancelli.
BUONA = {
    "useful": True, "depth_margin": 1.5, "useful_hours": 3.0,
    "best_airmass": 1.3, "fov_fit_ratio": 0.1, "motion_arcsec_min": 1.2,
    "rec_total_s": 1800.0,
}

# Un oggetto interessante: cometario, trascurato, orbita fragile.
INTERESSANTE = {
    "tisserand_j": 2.2, "years_since_last_obs": 8.0,
    "years_since_good_apparition": 6.0, "arc_days": 12.0, "n_oppositions": 1,
}


# --- le feature -------------------------------------------------------------


def test_le_feature_saturano_e_non_escono_da_0_1():
    f = feat.features({**BUONA, "depth_margin": 9.0, "useful_hours": 40.0,
                       "best_airmass": 1.0},
                      {**INTERESSANTE, "tisserand_j": 1.0,
                       "years_since_last_obs": 90.0})
    assert f["depth"] == 1.0 and f["window"] == 1.0 and f["airmass"] == 1.0
    assert f["tisserand"] == 1.0 and f["rarity"] == 1.0
    assert all(v is None or 0.0 <= v <= 1.0 for v in f.values())


def test_tisserand_alto_non_da_punteggio_negativo():
    f = feat.features(BUONA, {"tisserand_j": 3.6})
    assert f["tisserand"] == 0.0


def test_quello_che_non_si_sa_e_none_e_non_zero():
    """Un'iperbolica senza Tisserand non è un oggetto con Tisserand alto."""
    f = feat.features({"useful": True}, {})
    assert f["tisserand"] is None and f["rarity"] is None
    assert f["depth"] is None and f["fov_fit"] is None
    assert f["watchlist"] is None, "il bonus manuale c'è solo quando c'è"


def test_la_watchlist_alza_e_non_punisce_gli_altri():
    senza = score_window(BUONA, INTERESSANTE)["score"]
    con = score_window(BUONA, {**INTERESSANTE, "watchlist": True})["score"]
    assert con > senza


def test_l_esposizione_che_non_ci_sta_nella_finestra():
    stretta = {**BUONA, "useful_hours": 0.6, "rec_total_s": 3600.0}
    assert feat.feasibility_features(stretta)["exposure_fit"] == 0.0


# --- i cancelli -------------------------------------------------------------


def test_i_cancelli_dicono_quale_e_non_solo_che():
    corta = {**BUONA, "useful_hours": 0.2, "depth_margin": 0.1}
    falliti = check_gates(corta, Profile())
    assert len(falliti) == 2
    assert any("margine" in f for f in falliti) and any("finestra" in f for f in falliti)


def test_fuori_dai_cancelli_non_c_e_punteggio():
    esito = score_window({**BUONA, "depth_margin": 0.1}, INTERESSANTE)
    assert esito["score"] is None, "None e non zero: è un «non pertinente»"
    assert esito["grade"] == "NOT_USEFUL"
    # La scomposizione c'è lo stesso, e dice perché.
    assert esito["score_json"]["gates_failed"]
    assert esito["score_json"]["features"]["tisserand"] is not None


def test_una_finestra_inutile_e_fermata_anche_con_margine():
    esito = score_window({**BUONA, "useful": False}, INTERESSANTE)
    assert esito["grade"] == "NOT_USEFUL"


def test_il_moto_oltre_il_limite_del_setup():
    profilo = Profile(gates={**DEFAULT_GATES, "max_track_rate_arcsec_min": 1.0})
    assert check_gates(BUONA, profilo)          # μ = 1.2 > 1.0
    assert not check_gates(BUONA, Profile())    # senza limite dichiarato, passa


# --- la scomposizione -------------------------------------------------------


def test_la_scomposizione_somma_al_punteggio():
    esito = score_window(BUONA, INTERESSANTE)
    j = esito["score_json"]
    assert sum(j["contributions"].values()) / j["weight_total"] == pytest.approx(
        esito["score"])


def test_le_feature_assenti_non_pesano_nel_denominatore():
    """È il prezzo di non inventare dati, e si deve poter leggere."""
    esito = score_window(BUONA, {})
    pesi_attesi = sum(DEFAULT_WEIGHTS[k] for k in
                      ("depth", "window", "airmass", "fov_fit", "exposure_fit"))
    assert esito["score_json"]["weight_total"] == pytest.approx(pesi_attesi)


def test_i_due_gruppi_restano_separati():
    facile_e_noioso = score_window(BUONA, {"tisserand_j": 3.0,
                                           "years_since_last_obs": 0.1,
                                           "years_since_good_apparition": 0.1,
                                           "arc_days": 9000.0})
    j = facile_e_noioso["score_json"]
    assert j["feasibility"] > 0.6 and j["interest"] < 0.2, \
        "un oggetto facile e senza interesse deve leggersi come tale"


def test_score_json_e_serializzabile():
    """Ci finisce in una colonna TEXT: se non è serializzabile si scopre in
    produzione, non qui — a meno che qui non si provi."""
    j = score_window(BUONA, INTERESSANTE)["score_json"]
    assert json.loads(json.dumps(j))["profile"] == "default"


# --- giudizi e profilo ------------------------------------------------------


def test_le_soglie_di_giudizio():
    p = Profile()
    assert grade_of(0.80, p) == "PRIME"
    assert grade_of(0.60, p) == "GOOD"
    assert grade_of(0.40, p) == "POSSIBLE"
    assert grade_of(0.10, p) == "POOR"
    assert grade_of(0.90, p, gated=True) == "NOT_USEFUL"


def test_un_profilo_parziale_eredita_il_resto():
    p = Profile.from_row({"name": "solo_profondita",
                          "weights": json.dumps({"depth": 5.0}),
                          "gates": json.dumps({"useful_hours_min": 1.0,
                                               "grades": {"PRIME": 0.9}})})
    assert p.weights["depth"] == 5.0
    assert p.weights["tisserand"] == DEFAULT_WEIGHTS["tisserand"], "non azzerato"
    assert p.gates["useful_hours_min"] == 1.0
    assert p.gates["depth_margin_min"] == DEFAULT_GATES["depth_margin_min"]
    assert p.grades["PRIME"] == 0.9 and p.grades["GOOD"] == 0.55
    assert "grades" not in p.gates, "le soglie non sono un cancello"


def test_i_pesi_cambiano_la_classifica():
    """La prova che i pesi vivono davvero nel profilo e non nel codice."""
    profondo = {**BUONA, "depth_margin": 2.0}
    poco_profondo = {**BUONA, "depth_margin": 0.4}
    noioso, curioso = {"tisserand_j": 3.0}, {"tisserand_j": 2.0}

    solo_fattibilita = Profile(name="tecnico", weights={"depth": 1.0})
    solo_interesse = Profile(name="curioso", weights={"tisserand": 1.0})

    a = score_window(profondo, noioso, solo_fattibilita)["score"]
    b = score_window(poco_profondo, curioso, solo_fattibilita)["score"]
    assert a > b
    a = score_window(profondo, noioso, solo_interesse)["score"]
    b = score_window(poco_profondo, curioso, solo_interesse)["score"]
    assert b > a
