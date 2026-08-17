"""Il destino sul database: chiudere i candidati con il loro perché.

Si parte dalla stessa lista NEOCP degli altri test — quindi da candidati veri,
scritti dal polling vero — e poi si dà loro una fine. Verificare il destino su
candidati inventati a mano proverebbe soltanto che una UPDATE funziona.
"""
from __future__ import annotations

from core.db import connect
from services import candidate_service as cand
from tests.test_neocp import NEOCP_TXT

# Gli stessi trksub della lista di prova, con i quattro esiti possibili più
# un'identificazione. Il formato è quello vero (vedi test_neocp_prev.py).
#
# **Gli istanti sono relativi a adesso**, e non una data fissa: l'MPC decide
# *dopo* che noi abbiamo visto il candidato in lista, e il polling scrive
# `first_seen` con l'ora corrente. Con una data fissa nel passato ogni destino
# sembrerebbe riguardare un passaggio precedente — cioè si verificherebbe un
# mondo che non esiste (CLAUDE.md), e i test lo hanno detto subito.
_RIGHE = [
    ("ST26H52",
     '<a href="https://www.minorplanetcenter.net/db_search/show_object?object_id=2026+PN9">2026 PN9</a>',
     "None",
     '<a href="https://www.minorplanetcenter.net/mpec/K26/K26Q11.html">MPEC 2026-Q11</a>'),
    ("ST26H50", "None", "lost", "None"),
    ("ST26H49", "None", "dne", "None"),
    ("ZTF10FR", "None", "ST26H49", "None"),
    ("X89913",
     '<a href="https://www.minorplanetcenter.net/db_search/show_object?object_id=2013+SS24">2013 SS24</a>',
     "None", "None"),
    # Un trksub che non abbiamo mai visto: la pagina copre quattro giorni, noi
    # no. Deve essere ignorato senza rumore.
    ("MAI0000", "None", "lost", "None"),
]


def _pagina(quando: str | None = None, solo: dict | None = None) -> str:
    """La tabella dell'MPC, con le decisioni prese un minuto fa."""
    from datetime import datetime, timedelta, timezone

    base = quando or (datetime.now(timezone.utc) + timedelta(minutes=1)
                      ).strftime("%Y-%m-%dT%H:%M:%S")
    corpo = "".join(
        f"<tr><td>{t}</td><td>{d}</td><td>{s}</td><td>{rif}</td>"
        f"<td>{(solo or {}).get(t, base)}</td></tr>"
        for t, d, s, rif in _RIGHE)
    return ("<table><tr><th>trksub</th><th>iau_desig</th><th>status</th>"
            "<th>reference</th><th>datetime_ut</th></tr>" + corpo + "</table>")


def _righe(sql, params=()):
    conn = connect()
    try:
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def _lista(tmp_path, testo=NEOCP_TXT):
    f = tmp_path / "neocp.txt"
    f.write_text(testo, encoding="utf-8")
    return cand.poll("NEOCP", local_path=f)


def _destini(tmp_path, pagina=None):
    f = tmp_path / "prev.html"
    f.write_text(pagina if pagina is not None else _pagina(), encoding="utf-8")
    return cand.poll_destiny(local_path=f)


def test_il_destino_chiude_i_candidati_con_il_loro_perche(db, tmp_path):
    _lista(tmp_path)
    esito = _destini(tmp_path)

    assert esito["risolti"] == 5
    # Un trksub che non abbiamo mai visto non è un errore: è la maggioranza
    # della pagina, che copre quattro giorni e non solo i nostri candidati.
    assert esito["senza_candidato"] == 1
    assert esito["per_destino"] == {"confirmed_neo": 1, "not_confirmed": 1,
                                    "removed": 2, "known_object": 1}

    per_desig = {r["temp_desig"]: r for r in _righe("SELECT * FROM mpc_candidate")}
    neo = per_desig["ST26H52"]
    assert neo["resolution"] == "confirmed_neo"
    assert neo["resolved_desig"] == "2026 PN9"
    assert neo["resolution_source"] == "mpec:2026-Q11"
    # `resolved_at` è quando l'MPC l'ha deciso, non quando l'abbiamo letto:
    # è il numero che fra un anno dice quanto è durato quel candidato. Qui la
    # decisione è un minuto dopo il nostro avvistamento, come nella realtà.
    assert neo["resolved_at"].endswith("Z")
    assert neo["resolved_at"] > neo["first_seen"]

    # Identificato con un altro candidato: ne eredita il destino, ma la fonte
    # resta l'identificazione.
    assert per_desig["ZTF10FR"]["resolution"] == "removed"
    assert per_desig["ZTF10FR"]["resolution_source"] == "neocp_prev:=ST26H49"

    # Chi non compare nella pagina resta senza destino: NULL è «non lo sappiamo
    # ancora», e non si inventa una chiusura.
    assert per_desig["orA4767"]["resolution"] is None


def test_un_destino_piu_vecchio_del_candidato_parla_di_un_altro_passaggio(db, tmp_path):
    """L'MPC riusa i trksub. Caso vero del 2026-08-17: `A11FAuF` dichiarato
    inesistente il 13 alle 23:17, e in lista il 17 con score 100 e sei
    osservazioni. Applicare quella decisione avrebbe scritto «non esiste» su un
    candidato che quella notte era da guardare."""
    _lista(tmp_path)
    esito = _destini(tmp_path, _pagina(solo={"ST26H50": "2020-01-01T00:00:00"}))
    assert esito["fuori_tempo"] == 1
    riga = _righe("SELECT * FROM mpc_candidate WHERE temp_desig='ST26H50'")[0]
    assert riga["resolution"] is None, "il destino del passaggio precedente non è il suo"
    assert riga["still_listed"] == 1


def test_il_destino_non_tocca_chi_e_ancora_in_lista(db, tmp_path):
    """`still_listed` ha un padrone solo — il polling della lista. Una colonna
    con due padroni prima o poi si contraddice."""
    _lista(tmp_path)
    _destini(tmp_path)
    assert all(r["still_listed"] == 1 for r in _righe("SELECT * FROM mpc_candidate"))


def test_la_circolare_resta_un_riferimento_non_un_contenuto(db, tmp_path):
    _lista(tmp_path)
    _destini(tmp_path)

    mpec = _righe("SELECT * FROM mpec")
    assert len(mpec) == 1
    assert mpec[0]["mpec_id"] == "2026-Q11"
    assert mpec[0]["url"].endswith("K26Q11.html")
    assert mpec[0]["kind"] == "neo"
    # Non l'abbiamo letta: titolo e data di pubblicazione restano vuoti invece
    # di essere riempiti con numeri plausibili.
    assert mpec[0]["title"] is None and mpec[0]["published_at"] is None

    legami = _righe("SELECT * FROM mpec_object")
    assert len(legami) == 1 and legami[0]["designation"] == "2026 PN9"
    assert legami[0]["candidate_id"] is not None


def test_e_idempotente_e_non_riapre_quel_che_ha_chiuso(db, tmp_path):
    _lista(tmp_path)
    primo = _destini(tmp_path)
    secondo = _destini(tmp_path)

    assert primo["risolti"] == 5
    # Al secondo giro non c'è più niente da chiudere: i candidati risolti non
    # rientrano nella coda.
    assert secondo["risolti"] == 0
    assert len(_righe("SELECT * FROM mpec")) == 1
    assert len(_righe("SELECT * FROM mpc_candidate WHERE resolution IS NOT NULL")) == 5


def test_una_pagina_cambiata_non_chiude_niente(db, tmp_path):
    """Zero righe lette è la stessa difesa della lista vuota: se la pagina
    cambia forma, il job non deve chiudere tutto o non chiudere niente **in
    silenzio**."""
    _lista(tmp_path)
    esito = _destini(tmp_path, "<html><body>manutenzione</body></html>")
    assert esito["risolti"] == 0 and "sospetto" in esito
    assert _righe("SELECT * FROM mpc_candidate WHERE resolution IS NOT NULL") == []


def test_l_aggancio_al_catalogo_si_ritenta_ai_giri_dopo(db, tmp_path):
    """L'MPC designa **prima** di pubblicare MPCORB: `2026 PN9` è stato
    designato il 17 agosto alle 11:52 e quel giorno non era in catalogo. Senza
    un secondo tentativo resterebbe scollegato proprio l'oggetto più nuovo."""
    _lista(tmp_path)
    _destini(tmp_path)
    assert _righe("SELECT resolved_target_id FROM mpc_candidate "
                  "WHERE temp_desig='ST26H52'")[0]["resolved_target_id"] is None

    # Arriva il catalogo del giorno dopo.
    conn = connect()
    try:
        conn.execute(
            """INSERT INTO target (kind, primary_desig, display_name, created_at,
                                   updated_at)
               VALUES ('asteroid','2026 PN9','2026 PN9','2026-08-18T00:00:00Z',
                       '2026-08-18T00:00:00Z')""")
    finally:
        conn.close()

    esito = _destini(tmp_path)
    assert esito["riagganciati"] == 1
    riga = _righe("SELECT * FROM mpc_candidate WHERE temp_desig='ST26H52'")[0]
    assert riga["resolved_target_id"] is not None


def test_le_letture_per_la_pagina(db, tmp_path):
    _lista(tmp_path)
    _destini(tmp_path)

    chiusi = cand.resolved_candidates()
    assert len(chiusi) == 5
    neo = next(c for c in chiusi if c["temp_desig"] == "ST26H52")
    assert neo["resolution"] == "confirmed_neo"
    assert neo["mpec_url"].endswith("K26Q11.html")

    # Chi resta senza destino continua a comparire fra gli spariti: è il
    # promemoria di quello che stiamo non sapendo.
    conn = connect()
    try:
        conn.execute("UPDATE mpc_candidate SET still_listed=0 WHERE resolution IS NULL")
    finally:
        conn.close()
    assert {c["temp_desig"] for c in cand.recent_departures()} == {"orA4767", "RMM2026"}

    n = cand.counts()
    assert n["NEOCP"]["risolti"] == 5
