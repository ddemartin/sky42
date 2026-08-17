"""Lo screening: le griglie, i BLOB, e la distillazione.

Le serie di magnitudini sono in gran parte **sintetiche**, come per le
finestre: la propagazione ha già i suoi test contro Horizons, e mescolare le
due cose darebbe un test che fallisce quando cambia la fisica invece di quando
si rompe la logica della distillazione.

L'unico caso con dati veri è Cerere, e verifica una cosa sola che nessuna serie
inventata può verificare: che il minimo di V cada all'opposizione.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.radar import screening
from core.timeutil import now_jd_tdb

JD0 = 2461000.5


# --- le griglie -------------------------------------------------------------


def test_griglia_avanti_copre_due_anni_a_passo_di_un_giorno():
    jd = screening.forward_grid(JD0)
    assert jd[0] == JD0
    assert jd.size == 731                        # 730 giorni + l'estremo
    assert np.allclose(np.diff(jd), 1.0)
    assert jd[-1] - jd[0] == pytest.approx(24 * 365.25 / 12, abs=0.5)


def test_griglia_indietro_finisce_prima_di_adesso():
    jd = screening.back_grid(JD0)
    assert jd[-1] < JD0, "l'apparizione in corso è roba della griglia in avanti"
    assert jd[0] == pytest.approx(JD0 - 15 * 365.25, abs=10.0)
    assert np.allclose(np.diff(jd), 10.0)


def test_blob_va_e_torna():
    a = np.array([21.3456789, -30.1, 359.99, np.nan], dtype=float)
    b = screening.unpack(screening.pack(a))
    assert np.allclose(a[:3], b[:3], atol=1e-4)  # float32: 7 cifre
    assert np.isnan(b[3])
    assert len(screening.pack(a)) == 4 * 4


# --- la distillazione -------------------------------------------------------


def _serie(valori):
    """Una griglia giornaliera e una matrice (1, N) di magnitudini."""
    v = np.asarray(valori, dtype=float)
    return JD0 + np.arange(v.size, dtype=float), v[None, :]


def test_picco_trend_e_finestra():
    # Una V a forma di V: parte a 23, tocca 19.5 al giorno 40, risale.
    valori = list(np.linspace(23.0, 19.5, 41)) + list(np.linspace(19.58, 23.0, 40))
    jd, v = _serie(valori)

    s = screening.distill(jd_fwd=jd, v_fwd=v, v_ref=21.0)[0]

    assert s["peak_v"] == pytest.approx(19.5)
    assert s["peak_jd"] == pytest.approx(JD0 + 40)
    assert s["v_now"] == pytest.approx(23.0)
    # Sta migliorando: il trend è negativo, ed è la convenzione della colonna.
    # È la differenza a trenta giorni riportata al mese (30.44 giorni), non la
    # derivata: 30 × 0.0875 mag / 0.9856 mesi.
    assert s["v_trend_mag_month"] == pytest.approx(-2.663, abs=0.01)
    # Sotto V_ref = 21 fra il giorno 23 e il giorno 56 circa: quel che conta è
    # che inizio e fine siano dentro la discesa e la risalita, non il campione.
    assert JD0 + 22 <= s["visibility_start_jd"] <= JD0 + 24
    assert JD0 + 54 <= s["visibility_end_jd"] <= JD0 + 58
    assert s["next_v205_jd"] > s["next_v21_jd"], "20.5 si raggiunge dopo 21"


def test_quello_che_non_succede_resta_none():
    jd, v = _serie(np.full(40, 24.0))
    s = screening.distill(jd_fwd=jd, v_fwd=v, v_ref=21.0)[0]

    assert s["next_v21_jd"] is None and s["next_v205_jd"] is None
    assert s["visibility_start_jd"] is None and s["visibility_end_jd"] is None
    assert s["peak_v"] == pytest.approx(24.0)


def test_i_nan_non_diventano_oggetti_brillanti():
    """Una magnitudine che non si sa calcolare non è una magnitudine bassa."""
    jd, v = _serie([np.nan, np.nan, 22.0, 22.5])
    s = screening.distill(jd_fwd=jd, v_fwd=v, v_ref=21.0)[0]

    assert s["v_now"] is None
    assert s["peak_v"] == pytest.approx(22.0)
    assert s["visibility_start_jd"] is None


def test_la_finestra_e_la_prima_non_la_piu_lunga():
    """«Quand'è la prossima volta» ha per risposta la prossima, non la migliore."""
    valori = [22, 20.5, 20.5, 22, 22] + [19.0] * 10 + [22]
    jd, v = _serie(valori)
    s = screening.distill(jd_fwd=jd, v_fwd=v, v_ref=21.0)[0]

    assert s["visibility_start_jd"] == pytest.approx(JD0 + 1)
    assert s["visibility_end_jd"] == pytest.approx(JD0 + 2)


def test_ultima_apparizione_e_il_minimo_dell_ultimo_tratto():
    # Due apparizioni passate: una a metà, una più recente e meno favorevole.
    indietro = [24.0] * 5 + [19.0, 18.5, 19.2] + [24.0] * 6 + [20.5, 20.2, 20.8] + [24.0] * 3
    jd_b = JD0 - (len(indietro) - np.arange(len(indietro), dtype=float)) * 10.0
    jd_f, v_f = _serie([24.0] * 40)

    s = screening.distill(jd_fwd=jd_f, v_fwd=v_f, jd_back=jd_b,
                          v_back=np.asarray(indietro)[None, :], v_ref=21.0,
                          jd_now=JD0)[0]

    # L'ultima, non la migliore: indice 15 (V 20.2), non l'indice 6 (V 18.5).
    assert s["last_good_apparition_jd"] == pytest.approx(jd_b[15])
    assert s["years_since_good_apparition"] == pytest.approx(
        (JD0 - jd_b[15]) / 365.25, rel=1e-6)


def test_mai_stato_a_portata():
    jd_f, v_f = _serie([24.0] * 10)
    jd_b = JD0 - np.arange(20, 0, -1, dtype=float) * 10.0
    s = screening.distill(jd_fwd=jd_f, v_fwd=v_f, jd_back=jd_b,
                          v_back=np.full((1, 20), 25.0), v_ref=21.0)[0]

    assert s["last_good_apparition_jd"] is None
    assert s["years_since_good_apparition"] is None


def test_distilla_piu_oggetti_in_una_volta():
    jd = JD0 + np.arange(30, dtype=float)
    v = np.vstack([np.linspace(23, 19, 30), np.full(30, 24.5)])
    a, b = screening.distill(jd_fwd=jd, v_fwd=v, v_ref=21.0)

    assert a["next_v21_jd"] is not None and b["next_v21_jd"] is None
    assert a["peak_v"] < b["peak_v"]


# --- l'incertezza propagata -------------------------------------------------


def test_ceu_propagata_cresce_e_non_va_sotto_zero():
    assert screening.propagated_uncertainty(None, 0.1, JD0, JD0) is None
    assert screening.propagated_uncertainty(2.0, None, None, JD0) == 2.0
    assert screening.propagated_uncertainty(2.0, 0.01, JD0, JD0 + 100) == pytest.approx(3.0)
    # Una CEU in calo non diventa negativa: sarebbe un'incertezza al contrario.
    assert screening.propagated_uncertainty(2.0, -0.1, JD0, JD0 + 100) == 0.0


# --- l'unico caso con dati veri ---------------------------------------------


def test_cerere_e_piu_brillante_all_opposizione():
    """Il minimo di V cade dove l'elongazione è massima. Nessuna serie inventata
    può verificarlo: lega la fotometria alla geometria, che è il punto in cui
    uno scambio di segno nella distillazione passerebbe inosservato.

    Elementi di Cerere all'epoca 2026-05-05 (MPCORB), tenuti come costante: al
    test serve un'orbita vera, non l'orbita aggiornata.
    """
    from core.orbits.positioner import Body

    cerere = Body(epoch_jd=2461135.5, a_au=2.7666197, e=0.0785, i_deg=10.5868,
                  node_deg=80.2549, argp_deg=73.6339, m_deg=145.8437,
                  h_mag=3.33, g_slope=0.12)

    jd = screening.forward_grid(now_jd_tdb(), months=14, step_days=5.0)
    tr = screening.track(cerere, jd)
    s = screening.distill(jd_fwd=jd, v_fwd=tr["v_mag"][None, :], v_ref=21.0)[0]

    i_picco = int(np.argmin(tr["v_mag"]))
    assert s["peak_jd"] == pytest.approx(float(jd[i_picco]))
    assert tr["elong_deg"][i_picco] > 150.0, "il picco non è all'opposizione"
    # Cerere sta fra V 6.6 e V 9.3: se questo cambia, è cambiata la fotometria.
    assert 6.0 < s["peak_v"] < 8.0
