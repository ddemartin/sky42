"""Le regole della popolazione monitorata: compilazione, unione, attribuzione.

Il punto di questi test non è che «Tj < 3 funziona»: è che **la regola non sta
nel codice**. Se un domani si vorrà seguire i NEO brillanti, o gli oggetti che
nessuno riprende da dieci anni, o una lista scritta a mano per cercare
congiunzioni, deve bastare una riga di configurazione — e questi test sono la
prova che basta davvero.
"""
from __future__ import annotations

import pytest

from core.db import connect, get_setting
from core.radar import population as pop
from services import screening_service

# --- la compilazione --------------------------------------------------------


def test_una_regola_diventa_un_pezzo_di_where():
    sql, params = pop.compile_selector({"name": "x", "kind": "comet"})
    assert sql == "t.kind = ?"
    assert params == ["comet"]


def test_le_condizioni_di_una_regola_sono_in_and():
    sql, params = pop.compile_selector(
        {"name": "neo brillanti", "orbit_class_in": ["Apollo", "Aten"], "h_max": 22.0})
    assert " AND " in sql and sql.count("?") == 3
    assert params == ["Apollo", "Aten", 22.0]


def test_le_chiavi_di_servizio_non_filtrano():
    sql, params = pop.compile_selector(
        {"name": "x", "enabled": True, "note": "un commento", "kind": "asteroid"})
    assert sql == "t.kind = ?" and params == ["asteroid"]


def test_una_chiave_sconosciuta_e_un_errore_esplicito():
    """Ignorarla in silenzio significherebbe monitorare una popolazione diversa
    da quella che si crede di aver chiesto — e non accorgersene mai."""
    with pytest.raises(pop.SelectorError) as e:
        pop.compile_selector({"name": "sbagliata", "tisserannd_max": 3.0})
    assert "sbagliata" in str(e.value) and "tisserannd_max" in str(e.value)


def test_una_regola_senza_criteri_non_passa():
    with pytest.raises(pop.SelectorError, match="prenderebbe tutto"):
        pop.compile_selector({"name": "vuota"})


def test_una_lista_vuota_non_passa():
    with pytest.raises(pop.SelectorError, match="lista vuota"):
        pop.compile_selector({"name": "x", "orbit_class_in": []})


def test_niente_sql_nella_configurazione():
    """Il vocabolario è chiuso: quello che non è un predicato noto non entra."""
    with pytest.raises(pop.SelectorError):
        pop.compile_selector({"name": "cattiva", "sql": "1=1 OR 1=1"})


def test_le_regole_spente_non_contano():
    attive = pop.enabled_selectors([{"name": "a", "kind": "comet"},
                                    {"name": "b", "kind": "asteroid", "enabled": False}])
    assert [s["name"] for s in attive] == ["a"]


def test_senza_regole_attive_non_si_indovina():
    with pytest.raises(pop.SelectorError, match="nessuna regola attiva"):
        pop.population_query([{"name": "a", "kind": "comet", "enabled": False}])


def test_le_regole_di_partenza_compilano_tutte():
    """Comprese quelle spente: sono esempi, e un esempio rotto è peggio che
    nessun esempio — si scopre il giorno in cui lo si accende."""
    for sel in pop.DEFAULT_SELECTORS:
        sql, params = pop.compile_selector(sel)
        assert sql and isinstance(params, list)


# --- sul database -----------------------------------------------------------


def _popola(conn):
    """Un catalogo minimo con un rappresentante per ogni caso che serve."""
    oggetti = [
        # (desig, kind, classe, tj, H, ultima oss, numero, ceu)
        ("aco1", "asteroid", "Apollo", 2.5, 17.0, "2024-01-01", 1001, 0.5),
        ("hilda1", "asteroid", "Hilda", 2.9, 12.0, "2025-01-01", 1002, 0.2),
        ("mba1", "asteroid", "MBA", 3.4, 14.0, "2025-06-01", 1003, 0.3),
        ("cometa1", "comet", "JFC", 2.1, None, None, None, None),
        ("perso1", "asteroid", "Amor", 3.8, 18.5, "2009-01-01", None, 250.0),
    ]
    for desig, kind, classe, tj, h, ultima, numero, ceu in oggetti:
        cur = conn.execute(
            """INSERT INTO target (kind, primary_desig, display_name, orbit_class, number)
               VALUES (?,?,?,?,?)""", (kind, desig, desig, classe, numero))
        tid = cur.lastrowid
        conn.execute(
            """INSERT INTO orbit (target_id, source, epoch_jd, a_au, e, i_deg, node_deg,
                                  argp_deg, m_deg, h_mag, tisserand_j, last_obs_date,
                                  q_derived_au, updated_at)
               VALUES (?,'mpcorb',2461135.5,2.5,0.4,10,100,50,10,?,?,?,1.5,
                       '2026-08-17T00:00:00Z')""", (tid, h, tj, ultima))
        if ceu is not None:
            conn.execute(
                """INSERT INTO astorb_extra (target_id, ceu_arcsec, updated_at)
                   VALUES (?,?,'2026-08-17T00:00:00Z')""", (tid, ceu))
    return oggetti


@pytest.fixture()
def catalogo(db):
    conn = connect()
    try:
        _popola(conn)
    finally:
        conn.close()


def _chi(selectors, limit=None):
    sql, params, nomi = pop.population_query(selectors, limit)
    conn = connect()
    try:
        righe = [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()
    return {r["primary_desig"]: pop.why(r, nomi) for r in righe}


def test_le_regole_di_partenza_prendono_gli_aco_e_le_comete(catalogo):
    chi = _chi(pop.DEFAULT_SELECTORS)
    assert set(chi) == {"aco1", "cometa1"}
    assert chi["aco1"] == ["aco"] and chi["cometa1"] == ["comete"]


def test_le_regole_si_uniscono_in_or(catalogo):
    chi = _chi([{"name": "comete", "kind": "comet"},
                {"name": "brillanti", "h_max": 13.0}])
    assert set(chi) == {"cometa1", "hilda1"}


def test_un_oggetto_preso_da_due_regole_le_dichiara_entrambe(catalogo):
    """«Perché sto guardando questo sasso» deve avere una risposta completa,
    non la prima che capita."""
    chi = _chi([{"name": "aco", "kind": "asteroid", "tisserand_max": 3.0},
                {"name": "numerati", "unnumbered": False}])
    assert sorted(chi["aco1"]) == ["aco", "numerati"]
    assert chi["hilda1"] == ["aco", "numerati"]


def test_la_watchlist_entra_comunque(catalogo):
    conn = connect()
    try:
        conn.execute(
            "INSERT INTO watchlist (target_id, added_at) "
            "SELECT id, '2026-08-17T00:00:00Z' FROM target WHERE primary_desig='mba1'")
    finally:
        conn.close()
    chi = _chi(pop.DEFAULT_SELECTORS)
    assert "mba1" in chi and chi["mba1"] == ["watchlist"]


def test_gli_esempi_spenti_funzionano_quando_si_accendono(catalogo):
    """La promessa del meccanismo: accendere una regola è una impostazione."""
    regole = [dict(s, enabled=True) if s["name"] == "trascurati" else s
              for s in pop.DEFAULT_SELECTORS]
    chi = _chi(regole)
    assert "perso1" in chi and chi["perso1"] == ["trascurati"]


def test_una_classe_assente_non_e_una_classe_esclusa(catalogo):
    """Gli oggetti senza classe orbitale sono quelli nuovi: escluderli per
    distrazione significherebbe perdere proprio quelli."""
    conn = connect()
    try:
        conn.execute("UPDATE target SET orbit_class=NULL WHERE primary_desig='aco1'")
    finally:
        conn.close()
    chi = _chi(pop.DEFAULT_SELECTORS)
    assert "aco1" in chi


def test_l_incertezza_come_criterio(catalogo):
    """La CEU alta è il segnale di rarità, ed è un criterio di ricerca a pieno
    titolo: è il genere di curiosità che non deve richiedere una modifica."""
    chi = _chi([{"name": "incerti", "ceu_min_arcsec": 60.0}])
    assert set(chi) == {"perso1"}


def test_una_lista_scritta_a_mano(catalogo):
    """Il caso più semplice e più utile: «voglio questi tre, punto»."""
    chi = _chi([{"name": "curiosita", "desig_in": ["mba1", "hilda1"]}])
    assert set(chi) == {"mba1", "hilda1"}


def test_il_limite_non_cambia_le_regole(catalogo):
    assert len(_chi(pop.DEFAULT_SELECTORS, limit=1)) == 1


# --- il collegamento con il servizio ----------------------------------------


def test_le_regole_arrivano_dal_database(catalogo):
    assert get_setting("screening_selectors") is not None, "seminate all'avvio"
    assert [s["name"] for s in screening_service.selectors()][:3] == \
        ["aco", "comete", "watchlist"]


def test_cambiare_le_regole_cambia_la_popolazione_senza_toccare_il_codice(catalogo):
    """Il test che vale per tutti gli altri: si scrive una impostazione, e la
    popolazione monitorata è un'altra."""
    import json

    prima = {r["primary_desig"] for r in screening_service.population_rows()[0]}
    assert prima == {"aco1", "cometa1"}

    conn = connect()
    try:
        conn.execute(
            "UPDATE setting SET value=? WHERE key='screening_selectors'",
            (json.dumps([{"name": "solo_persi", "not_observed_since_years": 10.0}]),))
    finally:
        conn.close()

    dopo, nomi = screening_service.population_rows()
    assert {r["primary_desig"] for r in dopo} == {"perso1"}
    assert nomi == ["solo_persi"]


def test_lo_screening_scrive_perche_ogni_oggetto_e_in_lista(catalogo):
    screening_service.run_screening()
    conn = connect()
    try:
        righe = {r["primary_desig"]: r["selectors"] for r in conn.execute(
            """SELECT t.primary_desig, s.selectors FROM target_stats s
               JOIN target t ON t.id = s.target_id""")}
    finally:
        conn.close()
    assert righe == {"aco1": "aco", "cometa1": "comete"}
