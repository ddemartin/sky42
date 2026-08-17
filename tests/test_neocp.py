"""Le liste dei candidati: il parser, e il servizio che ne tiene la storia.

Il campione è **vero**, catturato dall'MPC il 2026-08-17: sette righe di NEOCP e
tre di PCCP, compresa quella con l'arco a quattro cifre su cui i due prodotti
dell'MPC non concordano. Un campione inventato non avrebbe mai contenuto il
caso che ha deciso quale formato leggere.
"""
from __future__ import annotations

import json

import pytest

from core.db import connect
from core.ingest import neocp
from services import candidate_service as cand

NEOCP_TXT = """\
ST26H52 100 2026 08 17.3  20.8233 +12.7517 19.7 Added Aug. 17.30 UT              2   0.00 26.7  0.032
ST26H50 100 2026 08 16.5  22.6102  +8.2259 19.6 Updated Aug. 17.25 UT            4   0.02 24.2  0.817
ST26H49  98 2026 08 16.5  22.4061 +16.2087 20.0 Updated Aug. 17.30 UT           11   0.83 24.8  0.018
ZTF10FR 100 2026 08 16.5   2.7935 +17.5684 18.3 Updated Aug. 17.04 UT            8   0.58 22.5  0.279
X89913  100 2026 08 15.8  23.9145  -4.2332 21.6 Added Aug. 16.67 UT              3   0.03 20.9  1.528
orA4767 100 2026 08 16.1  23.4042  +3.9441 20.8 Added Aug. 16.28 UT              3   0.01 23.1  1.193
RMM2026  35 2026 07 06.3  19.5046 -23.5010 22.5 Updated Aug. 16.29 UT           80 1821.94 18.9 16.878
"""

PCCP_TXT = """\
P12pb3b  35 2026 08 11.6   2.0136  -2.4172 19.1 Updated Aug. 17.18 UT           61   5.59 11.6  0.163
P12p4Jx  35 2026 08 09.5  23.3026 -12.5120 19.8 Updated Aug. 17.30 UT           49   7.59 14.3  0.248
P22oVrz  99 2026 08 06.5  21.5691 -22.9792 21.0 Updated Aug. 17.25 UT           23   9.05 16.5  1.771
"""

NEOCP_JSON = json.dumps([
    {"Temp_Desig": "ST26H52", "Score": 100, "Discovery_year": 2026,
     "Discovery_month": 8, "Discovery_day": 17.3, "R.A.": 20.8233,
     "Decl.": 12.7517, "V": 19.7, "Updated": "Added Aug. 17.30 UT",
     "NObs": 2, "Arc": 0.0, "H": 26.7, "Not_Seen_dys": 0.032},
])


# --- il parser --------------------------------------------------------------


def test_legge_tutte_le_righe():
    r = neocp.parse_text(NEOCP_TXT, "NEOCP")
    assert len(r) == 7
    assert {x["list"] for x in r} == {"NEOCP"}


def test_la_ra_esce_in_gradi():
    """L'MPC pubblica la RA in **ore**: se questo test sparisce, un giorno un
    candidato finirà a 20.8° invece che a 312° e nessuno se ne accorgerà."""
    primo = neocp.parse_text(NEOCP_TXT, "NEOCP")[0]
    assert primo["ra_deg"] == pytest.approx(20.8233 * 15.0)
    assert primo["dec_deg"] == pytest.approx(12.7517)


def test_i_campi_di_un_candidato_nuovo():
    primo = neocp.parse_text(NEOCP_TXT, "NEOCP")[0]
    assert primo["temp_desig"] == "ST26H52"
    assert primo["score"] == 100
    assert primo["v_mag"] == 19.7
    assert primo["n_obs"] == 2
    assert primo["h_mag"] == 26.7
    assert primo["not_seen_days"] == 0.032
    assert primo["arc_hours"] == 0.0
    assert primo["mpc_added"] is True, "«Added» = l'MPC lo pubblica adesso"
    # 2026-08-17.3 UT
    assert primo["discovery_jd"] == pytest.approx(2461269.8, abs=1e-6)


def test_updated_non_e_added():
    secondo = neocp.parse_text(NEOCP_TXT, "NEOCP")[1]
    assert secondo["mpc_added"] is False
    assert secondo["note"].startswith("Updated")


def test_l_arco_lungo_non_manda_fuori_fase_le_colonne():
    """La riga che ha deciso il formato: l'arco a quattro cifre trabocca dalla
    sua colonna, e un parser a fette fisse leggerebbe H e arco sbagliati."""
    riga = [r for r in neocp.parse_text(NEOCP_TXT, "NEOCP")
            if r["temp_desig"] == "RMM2026"][0]
    assert riga["arc_days"] == pytest.approx(1821.94)
    assert riga["h_mag"] == pytest.approx(18.9)
    assert riga["n_obs"] == 80
    assert riga["not_seen_days"] == pytest.approx(16.878)


def test_la_magnitudine_ignota_non_e_una_magnitudine():
    """L'MPC scrive 99.9 quando non la conosce. Preso alla lettera sarebbe un
    oggetto inosservabile con qualunque telescopio, cioè un dato invece di un
    buco — e finirebbe in fondo alle classifiche come se lo sapessimo."""
    riga = "A11FAuF 100 2026 08 12.4  18.0000  +5.0000 99.9 Updated Aug. 17.20 UT    6   0.06 25.0  4.820"
    r = neocp.parse_text(riga, "NEOCP")[0]
    assert r["v_mag"] is None
    assert r["h_mag"] == 25.0, "il resto della riga si legge lo stesso"


def test_la_declinazione_negativa_e_lo_score_basso():
    riga = [r for r in neocp.parse_text(PCCP_TXT, "PCCP")
            if r["temp_desig"] == "P22oVrz"][0]
    assert riga["dec_deg"] == pytest.approx(-22.9792)
    assert riga["score"] == 99
    assert riga["list"] == "PCCP"


def test_una_riga_storta_non_ferma_le_altre(caplog):
    testo = NEOCP_TXT + "questa non e' una riga di candidato\n"
    r = neocp.parse_text(testo, "NEOCP")
    assert len(r) == 7, "le buone passano"
    assert "non riconosciuta" in caplog.text, "e quella storta si vede nel log"


def test_il_json_dice_le_stesse_cose_del_testo():
    """La controprova: sugli oggetti normali i due percorsi coincidono, ed è
    quello che rende il JSON una riserva utilizzabile."""
    dal_testo = neocp.parse_text(NEOCP_TXT, "NEOCP")[0]
    dal_json = neocp.parse_json(NEOCP_JSON)[0]
    for campo in ("temp_desig", "ra_deg", "dec_deg", "v_mag", "n_obs",
                  "arc_hours", "h_mag", "not_seen_days", "discovery_jd"):
        assert dal_testo[campo] == dal_json[campo], campo


# --- il servizio ------------------------------------------------------------


def _poll(testo: str, tmp_path, lista="NEOCP", nome="lista.txt"):
    f = tmp_path / nome
    f.write_text(testo, encoding="utf-8")
    return cand.poll(lista, local_path=f)


def _righe(sql, params=()):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def test_il_primo_giro_scrive_tutto(db, tmp_path):
    esito = _poll(NEOCP_TXT, tmp_path)
    assert esito["nuovi"] == 7 and esito["snapshot"] == 7 and esito["spariti"] == 0

    righe = _righe("SELECT * FROM mpc_candidate ORDER BY temp_desig")
    assert len(righe) == 7
    assert all(r["still_listed"] == 1 for r in righe)
    assert all(r["first_seen"] == r["last_seen"] for r in righe)


def test_un_giro_identico_non_scrive_snapshot(db, tmp_path):
    _poll(NEOCP_TXT, tmp_path)
    esito = _poll(NEOCP_TXT, tmp_path)

    assert esito["nuovi"] == 0 and esito["aggiornati"] == 7
    assert esito["snapshot"] == 0, "ogni 10 minuti sarebbero 500.000 righe l'anno"
    assert len(_righe("SELECT * FROM mpc_candidate_snapshot")) == 7


def test_uno_snapshot_quando_qualcosa_si_muove(db, tmp_path):
    _poll(NEOCP_TXT, tmp_path)
    # Stessa lista, ma il primo candidato ha due osservazioni in più.
    mosso = NEOCP_TXT.replace(
        "ST26H52 100 2026 08 17.3  20.8233 +12.7517 19.7 Added Aug. 17.30 UT              2   0.00 26.7  0.032",
        "ST26H52 100 2026 08 17.3  20.8240 +12.7519 19.6 Updated Aug. 17.40 UT            4   0.10 26.5  0.012")
    esito = _poll(mosso, tmp_path)

    assert esito["snapshot"] == 1, "solo quello che si è mosso"
    storia = _righe("""SELECT s.* FROM mpc_candidate_snapshot s
                       JOIN mpc_candidate c ON c.id = s.candidate_id
                       WHERE c.temp_desig='ST26H52' ORDER BY s.id""")
    assert len(storia) == 2
    assert storia[0]["n_obs"] == 2 and storia[1]["n_obs"] == 4
    # L'ultimo valore sta anche sulla riga del candidato, per non dover
    # rileggere la storia solo per mostrare una lista.
    corrente = _righe("SELECT * FROM mpc_candidate WHERE temp_desig='ST26H52'")[0]
    assert corrente["n_obs"] == 4 and corrente["v_mag"] == 19.6


def test_quello_che_cambia_da_solo_non_e_una_notizia(db, tmp_path):
    """L'orologio e l'effemeride cambiano a ogni lettura: se contassero come
    cambiamento si scriverebbe un'istantanea per ogni candidato ogni dieci
    minuti, cinque milioni di righe l'anno. Misurato il 2026-08-17 sul serio,
    ed è il motivo per cui questo test esiste."""
    _poll(NEOCP_TXT, tmp_path)
    # Passa il tempo (not_seen) e l'oggetto si sposta di qualche arcosecondo.
    solo_rumore = (NEOCP_TXT
                   .replace(" 0.032", " 0.036").replace(" 0.817", " 0.821")
                   .replace("+12.7517", "+12.7519").replace("22.6102", "22.6104"))
    esito = _poll(solo_rumore, tmp_path)

    assert esito["snapshot"] == 0
    assert len(_righe("SELECT * FROM mpc_candidate_snapshot")) == 7
    # I valori correnti si aggiornano lo stesso: la posizione per puntare e il
    # «non ripreso da» si leggono dalla riga del candidato, non dalla storia.
    corrente = _righe("SELECT * FROM mpc_candidate WHERE temp_desig='ST26H52'")[0]
    assert corrente["not_seen_days"] == 0.036
    assert corrente["dec_deg"] == pytest.approx(12.7519)


def test_una_osservazione_nuova_invece_e_una_notizia(db, tmp_path):
    """Quando `not_seen_days` si azzera davvero cambia anche `n_obs`, ed è
    quello a far scattare l'istantanea: il momento che conta non si perde."""
    _poll(NEOCP_TXT, tmp_path)
    ripreso = NEOCP_TXT.replace(
        "UT              2   0.00 26.7  0.032", "UT              5   0.20 26.7  0.001")
    esito = _poll(ripreso, tmp_path)

    assert esito["snapshot"] == 1
    storia = _righe("""SELECT s.n_obs FROM mpc_candidate_snapshot s
                       JOIN mpc_candidate c ON c.id=s.candidate_id
                       WHERE c.temp_desig='ST26H52' ORDER BY s.id""")
    assert [r["n_obs"] for r in storia] == [2, 5]


def test_chi_sparisce_resta_con_la_sua_storia(db, tmp_path):
    _poll(NEOCP_TXT, tmp_path)
    ridotta = "\n".join(NEOCP_TXT.splitlines()[:3]) + "\n"
    esito = _poll(ridotta, tmp_path)

    assert esito["spariti"] == 4
    spariti = _righe("SELECT * FROM mpc_candidate WHERE still_listed=0")
    assert len(spariti) == 4
    # La riga resta, con la sua storia: è tutto ciò che si saprà mai di un
    # candidato che l'MPC ha tolto dalla lista.
    assert all(s["resolution"] is None for s in spariti), "il destino lo dirà l'MPEC"
    assert _righe("SELECT * FROM mpc_candidate_snapshot")


def test_una_lista_vuota_non_chiude_niente(db, tmp_path):
    """Un 200 con zero righe è un guasto della sorgente molto più spesso di un
    cielo tranquillo, e chiudere novanta candidati insieme è irreversibile."""
    _poll(NEOCP_TXT, tmp_path)
    esito = _poll("", tmp_path)

    assert esito["spariti"] == 0 and "sospetto" in esito
    assert len(_righe("SELECT * FROM mpc_candidate WHERE still_listed=1")) == 7


def test_un_candidato_che_ritorna_e_una_riga_nuova(db, tmp_path, monkeypatch):
    """Stessa designazione temporanea, ma è passato per il limbo: due storie
    distinte, o si mescolerebbero due comparse che l'MPC ha trattato a parte.

    I tre giri si datano a mano perché nella realtà distano dieci minuti: con
    l'orologio vero finirebbero tutti nello stesso secondo, che è un altro caso
    e ha un altro test.
    """
    istanti = iter(["2026-08-17T01:00:00Z", "2026-08-17T01:10:00Z",
                    "2026-08-17T01:20:00Z"])
    adesso = ["2026-08-17T01:00:00Z"]
    monkeypatch.setattr(cand, "now_iso", lambda: adesso[0])

    for testo in (NEOCP_TXT, "\n".join(NEOCP_TXT.splitlines()[1:]) + "\n", NEOCP_TXT):
        adesso[0] = next(istanti)
        _poll(testo, tmp_path)

    righe = _righe("SELECT * FROM mpc_candidate WHERE temp_desig='ST26H52' "
                   "ORDER BY first_seen")
    assert len(righe) == 2
    assert [r["still_listed"] for r in righe] == [0, 1]
    assert righe[0]["last_seen"] == "2026-08-17T01:00:00Z", "la prima comparsa si chiude"
    assert righe[1]["first_seen"] == "2026-08-17T01:20:00Z"


def test_due_giri_nello_stesso_secondo_non_perdono_il_ciclo(db, tmp_path):
    """Un `cli.py` lanciato mentre parte il job: la chiave collide, e una
    IntegrityError farebbe rotolare indietro tutto il giro, non una riga."""
    _poll(NEOCP_TXT, tmp_path)

    conn = connect()
    try:  # si chiude il primo a mano, come farebbe un giro intermedio
        conn.execute("UPDATE mpc_candidate SET still_listed=0 WHERE temp_desig='ST26H52'")
    finally:
        conn.close()

    esito = _poll(NEOCP_TXT, tmp_path)      # stesso secondo del primo giro
    assert esito["in_lista"] == 7
    righe = _righe("SELECT * FROM mpc_candidate WHERE temp_desig='ST26H52'")
    assert len(righe) == 1 and righe[0]["still_listed"] == 1
    assert len(_righe("SELECT * FROM mpc_candidate")) == 7, "niente duplicati"


def test_le_due_liste_non_si_mescolano(db, tmp_path):
    _poll(NEOCP_TXT, tmp_path)
    _poll(PCCP_TXT, tmp_path, lista="PCCP", nome="pccp.txt")

    n = cand.counts()
    assert n["NEOCP"]["aperti"] == 7 and n["PCCP"]["aperti"] == 3
    assert [c["list"] for c in cand.open_candidates("PCCP")] == ["PCCP"] * 3


def test_l_ordine_mette_in_cima_quello_che_si_sta_perdendo(db, tmp_path):
    _poll(NEOCP_TXT, tmp_path)
    aperti = cand.open_candidates("NEOCP")
    # Score decrescente, e a parità di score chi è più «non ripreso».
    assert aperti[0]["score"] == 100
    punteggi = [c["score"] for c in aperti]
    assert punteggi == sorted(punteggi, reverse=True)
    cento = [c["not_seen_days"] for c in aperti if c["score"] == 100]
    assert cento == sorted(cento, reverse=True)


def test_il_job_lascia_la_sua_riga(db, tmp_path):
    _poll(NEOCP_TXT, tmp_path)
    run = _righe("SELECT * FROM job_run WHERE job_name='neocp_poll'")
    assert len(run) == 1 and run[0]["status"] == "ok"
    assert run[0]["n_processed"] == 7
    assert json.loads(run[0]["detail_json"])["nuovi"] == 7
