"""La macchina a stati: le bande, l'isteresi, e la conferma.

Non c'è nessuna verità esterna da confrontare — gli stati sono una convenzione
nostra, scritta in docs/modelli.md §10. Quello che questi test difendono è che
la convenzione resti quella, e soprattutto che le due difese contro il rumore
(isteresi e conferma) non si annullino a vicenda.
"""
from __future__ import annotations

import pytest

from core.radar import states

V_REF = 21.0


def stato(v, **kw):
    return states.classify(v_pred=v, v_ref=V_REF, **kw)


# --- le bande ---------------------------------------------------------------


def test_le_bande_di_docs_modelli():
    assert stato(20.0) == "PRIME"                       # ≤ 21 − 0.75
    assert stato(20.9) == "OBSERVABLE"
    assert stato(21.4, trend_mag_month=-0.5) == "APPROACHING"
    assert stato(23.0) == "OUT_OF_RANGE"                # > 21 + 1.5


def test_oltre_il_picco_e_fading_anche_se_brilla():
    """`FADING` non è «debole»: è «era meglio ieri», e la magnitudine non lo dice."""
    assert stato(20.0, trend_mag_month=+0.4) == "FADING"
    assert stato(20.9, trend_mag_month=+0.4) == "FADING"


def test_nella_fascia_di_guardia_conta_il_verso():
    assert stato(22.0, trend_mag_month=-0.5) == "APPROACHING"
    # Sta sbiadendo ma non è mai stato a portata: non è un tramonto, è un
    # oggetto che non ci riguarda.
    assert stato(22.0, trend_mag_month=+0.5, current="OUT_OF_RANGE") == "OUT_OF_RANGE"
    assert stato(22.0, trend_mag_month=+0.5, current="OBSERVABLE") == "FADING"


def test_senza_trend_non_si_inventa_un_verso():
    assert stato(20.0) == "PRIME"
    assert stato(22.0) == "APPROACHING"


def test_una_magnitudine_che_non_esiste_e_fuori_portata():
    assert states.classify(v_pred=None, v_ref=V_REF) == "OUT_OF_RANGE"


# --- la durata --------------------------------------------------------------


def test_la_finestra_corta_declassa():
    assert stato(20.0, useful_hours=3.0) == "PRIME"
    # Brillantissimo ma alto solo un'ora: è OBSERVABLE con un problema.
    assert stato(20.0, useful_hours=1.0) == "OBSERVABLE"
    # Dieci minuti non sono un'osservazione, per quanto brilli.
    assert stato(20.0, useful_hours=0.2) == "OUT_OF_RANGE"


def test_finestra_sconosciuta_non_e_finestra_corta():
    """`None` = «il job delle finestre non c'è ancora», non «zero ore»."""
    assert stato(20.0, useful_hours=None) == "PRIME"


# --- l'isteresi -------------------------------------------------------------


def test_lo_sfioramento_della_soglia_non_sposta_niente():
    # A 21.10 sarebbe APPROACHING, ma da OBSERVABLE non ci si muove per 0.10.
    assert stato(21.10, current="OBSERVABLE", trend_mag_month=-0.1) == "OBSERVABLE"
    assert stato(21.20, current="OBSERVABLE", trend_mag_month=-0.1) == "APPROACHING"


def test_l_isteresi_vale_in_tutte_e_due_le_direzioni():
    assert stato(20.90, current="APPROACHING", trend_mag_month=-0.1) == "APPROACHING"
    assert stato(20.80, current="APPROACHING", trend_mag_month=-0.1) == "OBSERVABLE"


def test_crosses_limit_sta_nella_banda_di_observable():
    """Altrimenti l'isteresi tratterebbe l'attraversamento come un posto a sé,
    e l'oggetto resterebbe «ha attraversato il limite» per sempre."""
    assert stato(21.10, current="CROSSES_LIMIT", trend_mag_month=-0.1) == "OBSERVABLE"


# --- la conferma ------------------------------------------------------------


def test_il_primo_stato_non_aspetta_conferme():
    p = states.advance(None, "OBSERVABLE")
    assert p["state"] == "OBSERVABLE" and p["changed"] and p["from_state"] is None


def test_servono_due_calcoli_d_accordo():
    prima = {"state": "OUT_OF_RANGE", "pending_state": None, "pending_count": 0}

    uno = states.advance(prima, "APPROACHING")
    assert uno["state"] == "OUT_OF_RANGE" and not uno["changed"]
    assert uno["pending_state"] == "APPROACHING" and uno["pending_count"] == 1

    due = states.advance({**prima, **uno}, "APPROACHING")
    assert due["state"] == "APPROACHING" and due["changed"]
    assert due["pending_state"] is None


def test_un_candidato_che_cambia_idea_azzera_l_attesa():
    prima = {"state": "OUT_OF_RANGE", "pending_state": "APPROACHING", "pending_count": 1}
    p = states.advance(prima, "OBSERVABLE")
    assert p["state"] == "OUT_OF_RANGE" and p["pending_count"] == 1
    assert p["pending_state"] == "OBSERVABLE"


def test_tornare_sui_propri_passi_cancella_l_attesa():
    prima = {"state": "OBSERVABLE", "pending_state": "FADING", "pending_count": 1}
    p = states.advance(prima, "OBSERVABLE")
    assert not p["changed"] and p["pending_state"] is None and p["pending_count"] == 0


def test_l_attraversamento_ha_un_nome_suo():
    prima = {"state": "APPROACHING", "pending_state": "OBSERVABLE", "pending_count": 1}
    p = states.advance(prima, "OBSERVABLE")
    assert p["state"] == "CROSSES_LIMIT", "l'evento del radar"

    # E dura un giro solo: al successivo si assesta, **senza** aspettare
    # conferme e senza scrivere una riga nella storia — un
    # `CROSSES_LIMIT → OBSERVABLE` meccanico non racconta niente.
    dopo = states.advance({"state": "CROSSES_LIMIT", "pending_state": None,
                           "pending_count": 0}, "OBSERVABLE")
    assert dopo["state"] == "OBSERVABLE"
    assert not dopo["changed"], "l'evento era già stato registrato entrando"


def test_da_crosses_limit_si_puo_anche_ricadere_fuori():
    """L'uscita verso il basso non è un assestamento: passa dalle conferme."""
    prima = {"state": "CROSSES_LIMIT", "pending_state": None, "pending_count": 0}
    uno = states.advance(prima, "APPROACHING")
    assert uno["state"] == "CROSSES_LIMIT" and not uno["changed"]
    due = states.advance({**prima, **uno}, "APPROACHING")
    assert due["state"] == "APPROACHING" and due["changed"]


def test_uscendo_non_si_attraversa_niente():
    prima = {"state": "OBSERVABLE", "pending_state": "APPROACHING", "pending_count": 1}
    assert states.advance(prima, "APPROACHING")["state"] == "APPROACHING"


def test_l_oscillazione_sulla_soglia_non_produce_transizioni():
    """Le due difese insieme: un oggetto che ondeggia di ±0.1 mag attorno al
    limite per venti giri non deve generare venti notifiche. Nemmeno una."""
    riga = {"state": "OBSERVABLE", "pending_state": None, "pending_count": 0}
    cambi = 0
    for i in range(20):
        v = V_REF + (0.10 if i % 2 else -0.10)
        candidato = states.classify(v_pred=v, v_ref=V_REF, trend_mag_month=0.0,
                                    current=riga["state"])
        p = states.advance(riga, candidato)
        cambi += p["changed"]
        riga = {**riga, **p}
    assert cambi == 0
    assert riga["state"] == "OBSERVABLE"


def test_una_discesa_vera_invece_passa():
    """La stessa macchina, con un oggetto che si avvicina davvero: arriva in
    fondo, e ci arriva con due giri di ritardo per ogni gradino — l'isteresi
    costa latenza, non deve diventare un tappo."""
    riga = {"state": "OUT_OF_RANGE", "pending_state": None, "pending_count": 0}
    percorso = []
    for v in [23.0, 22.4, 21.8, 21.2, 20.6, 20.0, 19.4, 19.0, 18.6]:
        candidato = states.classify(v_pred=v, v_ref=V_REF, trend_mag_month=-0.6,
                                    current=riga["state"])
        p = states.advance(riga, candidato)
        riga = {**riga, **p}
        percorso.append(riga["state"])

    assert "CROSSES_LIMIT" in percorso
    assert percorso[-1] == "PRIME"
    assert percorso.index("APPROACHING") < percorso.index("CROSSES_LIMIT")


@pytest.mark.parametrize("stato_iniziale", states.STATES)
def test_ogni_stato_ha_una_banda(stato_iniziale):
    """Uno stato senza banda passerebbe di soppiatto: `classify` non gli
    applicherebbe l'isteresi, e nessun test se ne accorgerebbe."""
    assert states._band_of(stato_iniziale) is not None
