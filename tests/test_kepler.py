"""Verità del solutore a due corpi, contro JPL Horizons.

I casi qui sotto sono stati scaricati da Horizons il 2026-08-16 con
`EPHEM_TYPE=ELEMENTS` e `EPHEM_TYPE=VECTORS` alla **stessa** epoca,
CENTER='500@10' (Sole), REF_PLANE='ECLIPTIC', OUT_UNITS='AU-D'. Sono elementi
*osculatori*: alla loro epoca definiscono lo stato esatto, quindi il confronto
misura il nostro solutore e non le perturbazioni. Il residuo a 1 giorno dice
quanto valgono le nostre f e g; quanto sbagli la propagazione a due mesi o due
anni è un'altra domanda (memorandum, domanda aperta n. 2) e si misura con un
lavoro di validazione, non con un test unitario.

Tolleranze dichiarate: 1e-8 AU all'epoca (≈ 1.5 km, il livello a cui Horizons
arrotonda i suoi elementi) e 1e-6 AU dopo un giorno di propagazione, dove
entrano le perturbazioni vere.
"""
from __future__ import annotations

import numpy as np
import pytest

from core.orbits.kepler import (
    GM_SUN,
    heliocentric_state,
    solve_elliptic,
    solve_universal,
    stumpff_c,
    stumpff_s,
)

EPOCH = 2460676.5          # 2025-01-01T00:00 TDB
NEXT_DAY = 2460677.5

TOL_AT_EPOCH = 1e-8        # AU
TOL_ONE_DAY = 1e-6         # AU

# Ogni caso: elementi osculatori all'epoca + vettore di stato alla stessa
# epoca + posizione un giorno dopo. Copre i due rami e le tre coniche.
CASES = {
    # (1) Cerere — fascia principale, e piccola: il ramo ellittico normale.
    "ceres": dict(
        e=7.927929080437446e-02,
        q_au=2.547045156152441e00,
        i_deg=1.058793299269121e01,
        node_deg=8.025430838169864e01,
        argp_deg=7.326238274195768e01,
        tp_jd=2459919.534301203210,
        m_deg=1.621500827709824e02,
        a_au=2.766360233580095e00,
        pos=(2.176976419651001e00, -1.976334607788391e00, -4.635983995150979e-01),
        vel=(6.458869996727684e-03, 7.014609820398378e-03, -9.679562505890902e-04),
        pos_next=(2.183423063690559e00, -1.969308927603476e00, -4.645637529988568e-01),
    ),
    # (3200) Faetonte — e = 0.89, ancora ramo ellittico ma vicino al limite.
    "phaethon": dict(
        e=8.897686313565482e-01,
        q_au=1.401524896512653e-01,
        i_deg=2.231295046272242e01,
        node_deg=2.650942188491840e02,
        argp_deg=3.223065368665398e02,
        tp_jd=2460762.008671561256,
        m_deg=3.012144199998648e02,
        a_au=1.271439258861013e00,
        pos=(5.796085479509947e-01, 1.490899725279083e00, 1.846720720532758e-01),
        vel=(-8.369845649246447e-03, -7.399061818076538e-03, -3.162674485644211e-03),
        pos_next=(5.712181300729963e-01, 1.483447582962023e00, 1.815028480809858e-01),
    ),
    # C/2023 A3 (Tsuchinshan-ATLAS) — e = 1.00011, il caso quasi-parabolico
    # per cui esiste il ramo universale: `a` è negativa e priva di senso.
    "c2023a3": dict(
        e=1.000110458814593e00,
        q_au=3.914286438440888e-01,
        i_deg=1.391107902997593e02,
        node_deg=2.156065255897651e01,
        argp_deg=3.084912914242084e02,
        tp_jd=2460581.242432254832,
        pos=(9.880431834530281e-01, -1.166882161726510e00, 1.254102272017870e00),
        vel=(1.337179657900878e-03, -1.322495781003934e-02, 1.107568740696098e-02),
        pos_next=(9.893615972470550e-01, -1.180084887834606e00, 1.265154082030613e00),
    ),
    # 1I/'Oumuamua — e = 1.20, iperbolica e ormai a 45 AU: qui il ramo
    # universale lavora lontanissimo dal perielio (Δt ≈ 7 anni).
    "oumuamua": dict(
        e=1.203943444121803e00,
        q_au=2.598198710237596e-01,
        i_deg=1.220921643693658e02,
        node_deg=2.423744195196767e01,
        argp_deg=2.418110108591102e02,
        tp_jd=2458004.288119059987,
        pos=(4.075438050646078e01, 6.569904063040213e00, 1.712569884064255e01),
        vel=(1.422249555422767e-02, 2.123075176287523e-03, 6.223286317793386e-03),
        pos_next=(4.076860293256308e01, 6.572027121073760e00, 1.713192209859570e01),
    ),
}


def _elements(case: dict) -> dict:
    keys = ("e", "i_deg", "node_deg", "argp_deg", "q_au", "tp_jd", "a_au", "m_deg")
    return {k: case[k] for k in keys if k in case}


@pytest.mark.parametrize("name", sorted(CASES))
def test_stato_all_epoca(name):
    """Elementi osculatori → stato, alla loro stessa epoca."""
    case = CASES[name]
    pos, vel = heliocentric_state(EPOCH, epoch_jd=EPOCH, **_elements(case))

    assert np.allclose(pos, case["pos"], atol=TOL_AT_EPOCH, rtol=0)
    # La velocità è AU/giorno: 1e-10 AU/d sono ~17 cm/ora, cioè il livello di
    # arrotondamento degli elementi pubblicati.
    assert np.allclose(vel, case["vel"], atol=1e-10, rtol=0)


@pytest.mark.parametrize("name", sorted(CASES))
def test_propagazione_di_un_giorno(name):
    """Un giorno avanti: qui entrano le perturbazioni che non modelliamo."""
    case = CASES[name]
    pos, _ = heliocentric_state(NEXT_DAY, epoch_jd=EPOCH, **_elements(case))
    assert np.allclose(pos, case["pos_next"], atol=TOL_ONE_DAY, rtol=0)


def test_le_due_parametrizzazioni_coincidono():
    """(a, M₀) e (q, tp) devono dare lo stesso risultato per la stessa orbita.

    È il contratto che permette a un ingestore di dare quello che ha: astorb
    scrive a e M, cometels scrive q e Tp, e a valle nessuno se ne accorge.
    """
    case = CASES["phaethon"]
    jd = EPOCH + np.array([0.0, 40.0, 400.0])
    common = dict(
        e=case["e"],
        i_deg=case["i_deg"],
        node_deg=case["node_deg"],
        argp_deg=case["argp_deg"],
    )
    per_a, _ = heliocentric_state(
        jd, epoch_jd=EPOCH, a_au=case["a_au"], m_deg=case["m_deg"], **common
    )
    per_q, _ = heliocentric_state(
        jd, epoch_jd=EPOCH, q_au=case["q_au"], tp_jd=case["tp_jd"], **common
    )
    assert np.allclose(per_a, per_q, atol=1e-9, rtol=0)


def test_i_due_rami_coincidono_sulla_stessa_ellisse():
    """Ellittico e universale sono due strade per lo stesso punto.

    Faetonte con e = 0.89 va nel ramo ellittico; alzando artificialmente la
    soglia lo si forza nell'altro. Se i due non coincidono, uno dei due mente.
    """
    from core.orbits import kepler

    case = CASES["phaethon"]
    jd = EPOCH + np.array([0.0, 137.0, 1000.0])
    args = dict(epoch_jd=EPOCH, **_elements(case))

    ellittico, v_ell = heliocentric_state(jd, **args)
    soglia = kepler.E_UNIVERSAL
    try:
        kepler.E_UNIVERSAL = 0.0          # tutto passa dalle variabili universali
        universale, v_uni = heliocentric_state(jd, **args)
    finally:
        kepler.E_UNIVERSAL = soglia

    assert np.allclose(ellittico, universale, atol=1e-10, rtol=0)
    assert np.allclose(v_ell, v_uni, atol=1e-12, rtol=0)


def test_ritorno_dopo_un_periodo():
    """Un periodo esatto riporta l'oggetto dov'era: chiusura dell'orbita."""
    case = CASES["ceres"]
    periodo = 2.0 * np.pi * np.sqrt(case["a_au"] ** 3 / GM_SUN)
    pos0, _ = heliocentric_state(EPOCH, epoch_jd=EPOCH, **_elements(case))
    pos1, _ = heliocentric_state(EPOCH + periodo, epoch_jd=EPOCH, **_elements(case))
    assert np.allclose(pos0, pos1, atol=1e-11, rtol=0)


def test_griglia_oggetti_per_epoche():
    """N oggetti × M epoche in una chiamata sola, senza cicli Python.

    È la forma in cui lo screening userà il solutore: se il broadcasting non
    regge, ogni lavoro a valle finisce per scrivere un ciclo sugli oggetti.
    """
    nomi = sorted(CASES)
    col = lambda k: np.array([[CASES[n][k]] for n in nomi])  # noqa: E731
    jd = EPOCH + np.array([0.0, 1.0, 10.0])

    pos, vel = heliocentric_state(
        jd,
        epoch_jd=EPOCH,
        e=col("e"),
        i_deg=col("i_deg"),
        node_deg=col("node_deg"),
        argp_deg=col("argp_deg"),
        q_au=col("q_au"),
        tp_jd=col("tp_jd"),
    )
    assert pos.shape == (len(nomi), 3, 3)
    assert vel.shape == (len(nomi), 3, 3)

    for riga, nome in enumerate(nomi):
        assert np.allclose(pos[riga, 0], CASES[nome]["pos"], atol=TOL_AT_EPOCH)
        assert np.allclose(pos[riga, 1], CASES[nome]["pos_next"], atol=TOL_ONE_DAY)


def test_elementi_senza_senso_danno_nan():
    """NaN e non un numero plausibile: un valore sbagliato verrebbe ordinato."""
    pos, vel = heliocentric_state(
        EPOCH,
        epoch_jd=EPOCH,
        e=0.5,
        i_deg=10.0,
        node_deg=0.0,
        argp_deg=0.0,
        q_au=-1.0,          # perielio negativo: non esiste
        tp_jd=EPOCH,
    )
    assert np.all(np.isnan(pos))
    assert np.all(np.isnan(vel))


def test_servono_almeno_una_coppia_di_elementi():
    with pytest.raises(ValueError):
        heliocentric_state(EPOCH, epoch_jd=EPOCH, e=0.1, i_deg=0, node_deg=0, argp_deg=0)


# --- i mattoni, verificati da soli ------------------------------------------

def test_keplero_torna_indietro():
    """E risolta e reinserita nell'equazione: residuo sotto la tolleranza.

    Le e vanno fino a 0.97 perché è dove il ramo ellittico è più in difficoltà,
    subito sotto la soglia in cui passa la mano alle variabili universali.
    """
    e = np.array([0.0, 0.1, 0.5, 0.9, 0.97])[:, None]
    m = np.radians(np.arange(0.0, 360.0, 7.0))[None, :]
    ecc = solve_elliptic(m, e)
    residuo = ecc - e * np.sin(ecc) - (np.mod(m + np.pi, 2 * np.pi) - np.pi)
    assert np.max(np.abs(residuo)) < 1e-11


def test_stumpff_continue_attorno_a_zero():
    """Serie e forma chiusa devono raccordarsi: è lì che vive la parabola."""
    z = np.array([-1e-3, -1e-6, 0.0, 1e-6, 1e-3])
    assert np.allclose(stumpff_c(z), 0.5, atol=1e-4)
    assert np.allclose(stumpff_s(z), 1.0 / 6.0, atol=1e-5)

    # Sulla soglia interna, la serie deve valere quanto la forma chiusa: se la
    # tronchiamo troppo presto la propagazione prende un gradino. Il confronto
    # è allo *stesso* z, altrimenti si misura la pendenza di C invece
    # dell'errore di troncamento (dC/dz ≈ -1/24, che a 2e-10 di distanza vale
    # già 8e-12 e maschera tutto).
    from core.orbits.kepler import _Z_SMALL

    z = _Z_SMALL * (1.0 - 1e-12)          # subito sotto: ramo in serie
    for segno in (+1.0, -1.0):
        zz = segno * z
        if zz > 0:
            atteso_c = (1.0 - np.cos(np.sqrt(zz))) / zz
            atteso_s = (np.sqrt(zz) - np.sin(np.sqrt(zz))) / np.sqrt(zz) ** 3
        else:
            atteso_c = (np.cosh(np.sqrt(-zz)) - 1.0) / (-zz)
            atteso_s = (np.sinh(np.sqrt(-zz)) - np.sqrt(-zz)) / np.sqrt(-zz) ** 3
        assert stumpff_c(zz) == pytest.approx(atteso_c, abs=1e-13)
        assert stumpff_s(zz) == pytest.approx(atteso_s, abs=1e-13)


def test_anomalia_universale_risolve_la_sua_equazione():
    """Il residuo di √GM Δt = q x + e x³ S(αx²), su tutte e tre le coniche."""
    from core.orbits.kepler import SQRT_GM

    q = np.array([0.3, 0.39, 0.26])[:, None]
    e = np.array([0.995, 1.0, 1.2])[:, None]
    dt = np.array([-2000.0, -10.0, 0.0, 10.0, 2000.0])[None, :]

    x = solve_universal(dt, q, e)
    alpha = (1.0 - e) / q
    residuo = q * x + e * x**3 * stumpff_s(alpha * x * x) - SQRT_GM * dt
    assert np.max(np.abs(residuo)) < 1e-9
