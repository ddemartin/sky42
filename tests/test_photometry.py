"""H-G e magnitudine cometaria: i due sistemi, e il fatto che non si mescolano."""
from __future__ import annotations

import numpy as np
import pytest

from core.orbits.photometry import (
    G_DEFAULT,
    K1_DEFAULT,
    PHASE_VALID_MAX_DEG,
    apparent_magnitude,
    comet_magnitude,
    hg_magnitude,
    phase_reliable,
)


def test_hg_contro_horizons():
    """Cerere il 2025-01-01: Horizons dà V = 9.245 con H = 3.34 e G = 0.12.

    r, Δ e fase sono quelli di Horizons, così il test misura la sola funzione
    di fase e non la propagazione (che ha già i suoi test).
    """
    v = hg_magnitude(3.34, 2.976578692952, 3.79833439789668, 9.2148, g_slope=0.12)
    assert v == pytest.approx(9.245, abs=0.01)


def test_hg_contro_horizons_a_fase_alta():
    """(3200) Faetonte a 34° di fase: V = 16.694 con H = 14.38, G = 0.15.

    Il secondo caso serve a distinguere un errore nella funzione di fase da uno
    nel termine 5log(rΔ): a 9° di fase le due Φ contano poco, a 34° pesano.
    """
    v = hg_magnitude(14.38, 1.610282774766, 0.94007215580046, 34.0028)
    assert v == pytest.approx(16.694, abs=0.01)


def test_a_fase_zero_le_funzioni_di_fase_valgono_uno():
    """V = H + 5log(rΔ) esatto: è la definizione di H, opposizione perfetta."""
    v = hg_magnitude(10.0, 2.0, 1.0, 0.0)
    assert v == pytest.approx(10.0 + 5 * np.log10(2.0), abs=1e-12)


def test_g_mancante_usa_il_default_e_non_produce_nan():
    con = hg_magnitude(15.0, 2.0, 1.5, 20.0, g_slope=G_DEFAULT)
    senza = hg_magnitude(15.0, 2.0, 1.5, 20.0, g_slope=np.nan)
    assert senza == pytest.approx(con)


def test_senza_h_niente_magnitudine():
    """NaN e non un numero: una magnitudine inventata entra nel ranking come
    le altre e non si distingue più."""
    assert np.isnan(hg_magnitude(np.nan, 2.0, 1.5, 20.0))


def test_la_fase_alta_e_marcata_inaffidabile():
    assert phase_reliable(30.0)
    assert not phase_reliable(PHASE_VALID_MAX_DEG + 1)
    # Il valore si calcola comunque: si mostra marcato, non si nasconde.
    assert np.isfinite(hg_magnitude(15.0, 1.0, 0.5, 150.0))


def test_cometa_contro_horizons_e_la_convenzione_su_k1():
    """C/2023 A3 il 2025-01-01: Horizons dà 12.714 con M1 = 8.9 e k1 = 5.5.

    Il k1 di JPL è già moltiplicato per 2.5; quello dell'MPC, che è ciò che sta
    in `orbit.k1`, no. Questo test tiene ferma la conversione: sbagliarla vale
    2.4 magnitudini su questa cometa.
    """
    v = comet_magnitude(8.9, 1.977282895189, 2.73608308554972, k1=5.5 / 2.5)
    assert v == pytest.approx(12.714, abs=0.01)

    sbagliata = comet_magnitude(8.9, 1.977282895189, 2.73608308554972, k1=5.5)
    assert abs(sbagliata - 12.714) > 2.0


def test_k1_mancante_usa_il_default_dell_mpc():
    atteso = comet_magnitude(10.0, 2.0, 1.5, k1=K1_DEFAULT)
    assert comet_magnitude(10.0, 2.0, 1.5) == pytest.approx(atteso)


def test_i_due_sistemi_non_si_mescolano():
    """Una cometa con una H asteroidale resta senza magnitudine.

    È il punto della regola: `kind` decide il sistema fotometrico, e un oggetto
    a cui manca il parametro del *suo* sistema non prende in prestito l'altro.
    """
    v = apparent_magnitude(
        is_comet=[False, True, True],
        r_au=2.0, delta_au=1.5, phase_deg=15.0,
        h_mag=[15.0, 15.0, 15.0],          # anche la cometa ha una H...
        m1=[np.nan, np.nan, 9.0],          # ...ma solo la terza ha una M1
        k1=4.0,
    )
    assert np.isfinite(v[0])
    assert np.isnan(v[1]), "la cometa ha usato la H asteroidale"
    assert np.isfinite(v[2])
