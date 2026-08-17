"""I propositi osservativi: dal suggerimento alla sessione, o alla scadenza.

La catena vera gira davvero — screening, notti, finestre, radar — perché quello
che si prova qui è che il proposito **legga** il verdetto degli altri invece di
farsi un'idea sua di quando un oggetto è osservabile.
"""
from __future__ import annotations

import pytest

from core.db import connect
from services import (intent_service, night_service, radar_service,
                      screening_service, window_service)
from tests.test_radar_service import catalogo  # noqa: F401  (fixture)


@pytest.fixture()
def acceso(catalogo):  # noqa: F811
    screening_service.run_screening()
    night_service.plan_nights(2)
    window_service.run_windows(n_nights=2)
    radar_service.run_radar()
    return catalogo


def _righe(sql, params=()):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


# --- nascere -----------------------------------------------------------------


def test_un_proposito_si_porta_dietro_il_perche(acceso):
    """Fra sei mesi, guardando un proposito scaduto, «cosa mi aveva convinto»
    deve avere una risposta: le statistiche di allora saranno state riscritte."""
    p = intent_service.add("3200", purpose="astrometria", source="stanotte")
    assert p["status"] == "planned" and p["desig"] == "3200"

    import json
    ctx = json.loads(p["context_json"])
    assert ctx["radar"]["state"] in ("OUT_OF_RANGE", "APPROACHING", "CROSSES_LIMIT",
                                     "OBSERVABLE", "PRIME", "FADING")
    assert ctx["stats"]["v_now"] is not None


def test_premere_due_volte_non_e_una_seconda_intenzione(acceso):
    a = intent_service.add("3200")
    b = intent_service.add("3200")
    assert a["id"] == b["id"]
    assert len(_righe("SELECT * FROM observing_intent")) == 1


def test_un_oggetto_che_non_esiste_non_diventa_un_proposito(acceso):
    assert intent_service.add("non esiste") is None


def test_lo_stesso_oggetto_su_due_setup_sono_due_propositi(acceso):
    intent_service.add("3200")
    intent_service.add("3200", setup_code="rc700-qhy600-bin2")
    righe = _righe("SELECT * FROM observing_intent")
    assert len(righe) == 2
    assert {r["setup_id"] for r in righe} == {None, 1}


# --- scadere -----------------------------------------------------------------


def test_scade_quando_esce_di_portata_e_lo_dice(acceso):
    intent_service.add("3200")
    conn = connect()
    try:
        conn.execute("UPDATE target_state SET state='OUT_OF_RANGE'")
    finally:
        conn.close()

    esito = intent_service.refresh()
    assert esito["scaduti"] == 1
    assert esito["per_motivo"] == {"out_of_range": 1}
    riga = _righe("SELECT * FROM observing_intent")[0]
    assert riga["status"] == "expired" and riga["closed_reason"] == "out_of_range"


def test_fading_non_e_scaduto_ma_ultima_occasione(acceso):
    """Il caso vero che ha corretto la regola, con i suoi numeri.

    C/2019 E3 (ATLAS) il 2026-08-17: **V 18.33 contro un limite di 21.06**, 7,6
    ore utili, primo della classifica di stanotte — e stato `FADING`, perché il
    trend era di +0.035 mag/mese, cioè aveva passato il picco. La prima versione
    chiudeva tutto ciò che non era IN_RANGE e l'ha dichiarato scaduto al primo
    giro. `FADING` vuol dire l'opposto: è l'ultima occasione, ed è quello da
    fare per primo (`states.py` lo scrive).
    """
    intent_service.add("3200")
    conn = connect()
    try:
        conn.execute("UPDATE target_state SET state='FADING', v_pred=18.33, "
                     "eff_vlim_ref=21.06")
        # La finestra c'è: così l'unico motivo possibile di scadenza resta lo
        # stato, che è quello che il test vuole isolare.
        conn.execute("UPDATE observation_window SET useful_hours=7.6")
    finally:
        conn.close()

    assert intent_service.refresh()["scaduti"] == 0
    riga = intent_service.list_intents("planned")[0]
    assert riga["status"] == "planned"
    assert riga["ultima_occasione"] is True


def test_approaching_non_e_scaduto_sta_arrivando(acceso):
    """L'altro stato fuori portata che non vuol dire «è andata»."""
    intent_service.add("3200")
    conn = connect()
    try:
        conn.execute("UPDATE target_state SET state='APPROACHING'")
        conn.execute("UPDATE observation_window SET useful_hours=2.0")
    finally:
        conn.close()
    assert intent_service.refresh()["scaduti"] == 0


def test_scade_anche_quando_resta_brillante_ma_non_si_vede_piu(acceso):
    """Il secondo motivo, che è un fallimento diverso: «serviva un altro sito»
    invece di «bisognava muoversi prima». Fonderli in uno solo cancellerebbe
    proprio l'informazione che serve a decidere se comprare tempo altrove."""
    intent_service.add("3200", setup_code="rc700-qhy600-bin2")
    conn = connect()
    try:
        conn.execute("UPDATE target_state SET state='PRIME'")     # brillante
        conn.execute("UPDATE observation_window SET useful_hours = 0")  # ma mai su
    finally:
        conn.close()

    esito = intent_service.refresh()
    assert esito["per_motivo"] == {"no_window": 1}


def test_senza_finestre_calcolate_non_scade_niente(acceso):
    """«Non l'ho calcolato» non è «non si vede»: senza questa guardia il primo
    avvio scadrebbe tutti i propositi insieme."""
    intent_service.add("3200", setup_code="rc700-qhy600-bin2")
    conn = connect()
    try:
        conn.execute("UPDATE target_state SET state='PRIME'")
        conn.execute("DELETE FROM observation_window")
    finally:
        conn.close()

    assert intent_service.refresh()["scaduti"] == 0


def test_una_scadenza_scelta_a_mano_vince_da_sola(acceso):
    intent_service.add("3200", deadline="2020-01-01T00:00:00Z")
    esito = intent_service.refresh()
    assert esito["per_motivo"] == {"deadline": 1}


def test_refresh_e_idempotente(acceso):
    intent_service.add("3200")
    conn = connect()
    try:
        conn.execute("UPDATE target_state SET state='OUT_OF_RANGE'")
    finally:
        conn.close()
    intent_service.refresh()
    secondo = intent_service.refresh()
    assert secondo["aperti"] == 0 and secondo["scaduti"] == 0


def test_un_proposito_scaduto_si_puo_riaprire(acceso):
    p = intent_service.add("3200")
    intent_service.close(p["id"], "expired", "out_of_range")
    intent_service.reopen(p["id"])
    riga = _righe("SELECT * FROM observing_intent")[0]
    assert riga["status"] == "planned" and riga["closed_reason"] is None


def test_lasciare_perdere_non_cancella(acceso):
    p = intent_service.add("3200")
    intent_service.drop(p["id"], note="cielo coperto tutta la settimana")
    riga = _righe("SELECT * FROM observing_intent")[0]
    assert riga["status"] == "dropped" and riga["closed_reason"] == "manuale"
    assert "coperto" in riga["note"]


# --- osservare ---------------------------------------------------------------


def test_registrare_una_sessione_chiude_il_proposito(acceso):
    p = intent_service.add("3200", setup_code="rc700-qhy600-bin2",
                           purpose="astrometria")
    sess = intent_service.log_observation(
        "3200", obs_start="2026-08-17T03:10:00Z", setup_code="rc700-qhy600-bin2",
        n_frames=12, exposure_s=120.0, total_exposure_s=1440.0,
        outcome="detected", measured_mag=19.4, fwhm_arcsec=1.8, snr_median=14.0,
        limiting_mag=21.1, residual_arcsec=0.32, processed=1, reported_mpc="yes",
        archive_folder="2026-08-17_3200")

    assert sess["intent_id"] == p["id"]
    assert sess["desig"] == "3200"
    # `limiting_mag` è il numero che serve alla domanda aperta 5: il vlim_ref
    # dichiarato contro quello misurato davvero.
    assert sess["limiting_mag"] == 21.1

    riga = _righe("SELECT * FROM observing_intent")[0]
    assert riga["status"] == "observed" and riga["closed_reason"] == "observed"


def test_il_costo_di_una_sessione_viene_dalle_ore_di_posa(acceso):
    """Su un telescopio affittato il tempo si paga, e nessuno fa quel conto alle
    tre di notte. Si contano le **ore di posa**, non la durata della finestra:
    è quello che i servizi remoti fatturano."""
    conn = connect()
    try:
        conn.execute("UPDATE setup SET cost_per_hour=30.0, currency='EUR'")
    finally:
        conn.close()

    sess = intent_service.log_observation(
        "3200", obs_start="2026-08-17T03:10:00Z", setup_code="rc700-qhy600-bin2",
        n_frames=30, exposure_s=120.0, total_exposure_s=3600.0)
    assert sess["cost"] == 30.0                     # un'ora esatta

    # Un costo dichiarato vince: le sessioni vere hanno sovrapprezzi e notti
    # perse a metà.
    altra = intent_service.log_observation(
        "2010 TK7", obs_start="2026-08-17T04:10:00Z",
        setup_code="rc700-qhy600-bin2", total_exposure_s=3600.0, cost=12.5)
    assert altra["cost"] == 12.5

    spesa = intent_service.spesa()
    assert spesa["totale"] == pytest.approx(42.5)
    assert spesa["per_setup"][0]["currency"] == "EUR"


def test_senza_listino_il_costo_resta_ignoto_non_zero(acceso):
    """`None` è «non si paga», e un totale che lo contasse come zero direbbe che
    il telescopio di casa costa quanto quello affittato."""
    sess = intent_service.log_observation(
        "3200", obs_start="2026-08-17T03:10:00Z", setup_code="rc700-qhy600-bin2",
        total_exposure_s=3600.0)
    assert sess["cost"] is None


def test_una_sessione_si_aggancia_da_sola_al_proposito_aperto(acceso):
    """Nessuno vuole scegliere da un elenco la cosa che ha appena deciso di fare."""
    p = intent_service.add("3200")
    sess = intent_service.log_observation("3200", obs_start="2026-08-17T03:10:00Z")
    assert sess["intent_id"] == p["id"]


def test_si_registra_anche_quel_che_non_era_in_programma(acceso):
    """Capita di riprendere qualcosa perché era lì: un registro che accetta solo
    il pianificato racconta una notte più ordinata di com'è stata."""
    sess = intent_service.log_observation("2010 TK7", obs_start="2026-08-17T04:00:00Z",
                                          outcome="not_detected")
    assert sess["intent_id"] is None and sess["outcome"] == "not_detected"
    assert _righe("SELECT * FROM observing_intent") == []


def test_un_campo_inventato_e_un_errore_non_un_silenzio(acceso):
    with pytest.raises(ValueError, match="campi sconosciuti"):
        intent_service.log_observation("3200", obs_start="2026-08-17T03:10:00Z",
                                       seeing_arcsec=2.0)


# --- letture -----------------------------------------------------------------


def test_l_elenco_porta_anche_com_e_messo_adesso(acceso):
    """Un proposito aperto senza «e adesso?» costringerebbe a controllare a mano
    oggetto per oggetto, che è il lavoro che questa tabella evita."""
    intent_service.add("3200", setup_code="rc700-qhy600-bin2")
    riga = intent_service.list_intents("planned")[0]
    assert riga["display_name"] == "(3200) Phaethon"
    assert riga["state"] is not None and riga["v_now"] is not None
    assert riga["setup_code"] == "rc700-qhy600-bin2"
    assert riga["tonight"] is not None and "useful_hours" in riga["tonight"]


def test_i_conteggi_dell_intestazione(acceso):
    a = intent_service.add("3200")
    intent_service.add("2010 TK7")
    intent_service.close(a["id"], "expired", "out_of_range")

    n = intent_service.counts()
    assert n["per_stato"]["planned"] == 1 and n["per_stato"]["expired"] == 1
    assert n["per_motivo"] == {"out_of_range": 1}
    assert n["sessioni"] == 0


def test_la_designazione_e_la_chiave_che_sopravvive(acceso):
    """`target` è rigenerabile: dopo un ripristino su un catalogo riscaricato
    gli id sono altri, e il proposito si riaggancia dalla designazione."""
    intent_service.add("3200")
    conn = connect()
    try:
        conn.execute("UPDATE observing_intent SET target_id = NULL")
    finally:
        conn.close()

    assert intent_service.refresh()["riagganciati"] == 1
    assert _righe("SELECT target_id FROM observing_intent")[0]["target_id"] is not None
