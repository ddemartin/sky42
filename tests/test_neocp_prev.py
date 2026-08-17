"""Il destino dei candidati: la tabella dei trksub già usciti di lista.

Il campione è **markup vero**, copiato dalla pagina dell'MPC il 2026-08-17 con
i suoi link e i suoi «None» scritti a parole. Un HTML sintetico verificherebbe
la regex contro sé stessa: le sette righe qui sotto sono le sette combinazioni
che la pagina produce davvero.
"""
from __future__ import annotations

from core.ingest import neocp_prev

# Sette righe reali: designato con circolare, perso, inesistente, «na»,
# identificato con un altro candidato, e due designati senza circolare — uno
# con designazione dell'anno in corso, uno di tredici anni fa.
PAGINA = """
<table>
<tr>
<th>trksub</th><th>iau_desig</th><th>status</th><th>reference</th><th>datetime_ut</th>
</tr>
<tr>
<td>P22pq2q</td>
<td><a href="https://www.minorplanetcenter.net/db_search/show_object?utf8=True&amp;object_id=2026+PN9" target="_blank">2026 PN9</a></td>
<td>None</td>
<td><a href="https://www.minorplanetcenter.net/mpec/K26/K26Q11.html" target="_blank">MPEC 2026-Q11</a></td>
<td>2026-08-17T11:52:03</td>
</tr>
<tr><td>6H63K21</td><td>None</td><td>lost</td><td>None</td><td>2026-08-17T11:41:08</td></tr>
<tr><td>TF26H82</td><td>None</td><td>dne</td><td>None</td><td>2026-08-17T08:36:04</td></tr>
<tr><td>ZTF10FQ</td><td>None</td><td>na</td><td>None</td><td>2026-08-17T00:38:06</td></tr>
<tr><td>SK000Zy</td><td>None</td><td>ZTF10FQ</td><td>None</td><td>2026-08-17T00:37:40</td></tr>
<tr>
<td>W023205</td>
<td><a href="https://www.minorplanetcenter.net/db_search/show_object?object_id=2013+SS24">2013 SS24</a></td>
<td>None</td><td>None</td><td>2026-08-14T03:42:13</td>
</tr>
<tr>
<td>P22pkXQ</td>
<td><a href="https://www.minorplanetcenter.net/db_search/show_object?object_id=2026+NX3">2026 NX3</a></td>
<td>None</td><td>None</td><td>2026-08-13T15:30:46</td>
</tr>
</table>
"""


def _per_trksub(righe):
    return {r["trksub"]: r for r in righe}


def test_si_leggono_le_cinque_colonne_e_i_None_a_parole():
    righe = neocp_prev.parse(PAGINA)
    assert len(righe) == 7, "l'intestazione non è una riga di dati"

    r = _per_trksub(righe)["P22pq2q"]
    assert r["iau_desig"] == "2026 PN9"
    # «None» è una stringa, non una cella vuota: se passasse così com'è
    # finirebbe nel database come destino di quel candidato.
    assert r["status"] is None
    assert r["mpec_id"] == "2026-Q11"
    assert r["mpec_url"].endswith("/mpec/K26/K26Q11.html")
    # L'MPC scrive l'ora UT senza fuso; nel database ci va la Z, come tutto.
    assert r["seen_at"] == "2026-08-17T11:52:03Z"


def test_una_pagina_che_cambia_forma_da_zero_righe_non_righe_sbagliate():
    """Zero righe chi chiama lo tratta già come «non toccare niente»; una riga
    mezza letta scriverebbe un destino falso su un candidato vero."""
    assert neocp_prev.parse("<html><body>manutenzione</body></html>") == []
    assert neocp_prev.parse("<table><tr><td>solo</td><td>due</td></tr></table>") == []


def test_i_quattro_destini_che_la_pagina_sa_dire():
    esiti = _per_trksub(neocp_prev.resolve(neocp_prev.parse(PAGINA)))

    # Designato **e** annunciato da una circolare: la scoperta vera.
    assert esiti["P22pq2q"]["resolution"] == "confirmed_neo"
    assert esiti["P22pq2q"]["resolved_desig"] == "2026 PN9"
    assert esiti["P22pq2q"]["resolution_source"] == "mpec:2026-Q11"

    assert esiti["6H63K21"]["resolution"] == "not_confirmed"   # lost
    assert esiti["TF26H82"]["resolution"] == "removed"         # dne
    # `na` non è documentato dall'MPC: si tiene il codice grezzo, e il destino
    # dice solo ciò che è certo — è uscito di lista senza designazione.
    assert esiti["ZTF10FQ"]["resolution"] == "removed"
    assert esiti["ZTF10FQ"]["resolution_source"] == "neocp_prev:na"

    # Designato senza circolare: un pianetino ordinario, che è come finiscono
    # quasi tutti i candidati.
    for trksub in ("W023205", "P22pkXQ"):
        assert esiti[trksub]["resolution"] == "known_object"
        assert esiti[trksub]["resolution_source"] == "neocp_prev:designato"


def test_un_candidato_identificato_con_un_altro_eredita_il_suo_destino():
    """Lo stato che non è un codice ma un trksub: i due sono lo stesso oggetto."""
    esiti = _per_trksub(neocp_prev.resolve(neocp_prev.parse(PAGINA)))
    assert esiti["SK000Zy"]["resolution"] == esiti["ZTF10FQ"]["resolution"] == "removed"
    # La fonte resta l'identificazione, non il destino ereditato: fra un anno,
    # «perché questo candidato è chiuso» deve avere la risposta giusta.
    assert esiti["SK000Zy"]["resolution_source"] == "neocp_prev:=ZTF10FQ"


def test_una_catena_che_non_si_chiude_resta_unknown_e_non_gira_in_cerchio():
    pagina = PAGINA.replace(
        "<tr><td>ZTF10FQ</td><td>None</td><td>na</td><td>None</td><td>2026-08-17T00:38:06</td></tr>",
        "<tr><td>ZTF10FQ</td><td>None</td><td>SK000Zy</td><td>None</td><td>2026-08-17T00:38:06</td></tr>")
    esiti = _per_trksub(neocp_prev.resolve(neocp_prev.parse(pagina)))
    # Due righe che si rimandano l'un l'altra: un salto solo, e si esce.
    assert esiti["SK000Zy"]["resolution"] == "unknown"
    assert esiti["ZTF10FQ"]["resolution"] == "unknown"
    # `unknown` non è NULL: NULL è «non l'abbiamo ancora cercato».
    assert esiti["SK000Zy"]["resolution_source"] == "neocp_prev:=ZTF10FQ"


def test_una_cometa_non_diventa_un_neo():
    pagina = PAGINA.replace(">2026 PN9<", ">C/2026 Q1<")
    esiti = _per_trksub(neocp_prev.resolve(neocp_prev.parse(pagina)))
    assert esiti["P22pq2q"]["resolution"] == "confirmed_comet"
    assert neocp_prev.is_comet_designation("P/2013 YG46")
    assert neocp_prev.is_comet_designation("161P")
    assert not neocp_prev.is_comet_designation("2026 PN9")


def test_l_indirizzo_di_una_circolare_sopra_il_99_non_e_decimale():
    """Verificato sull'MPC il 2026-08-17: K26Q11 e K26P99 rispondono 200,
    K26P114 dà 404 e la forma giusta è K26PB4. Un link sbagliato in pagina è
    peggio di nessun link: sembra che la circolare non esista."""
    assert neocp_prev.mpec_url("2026-Q11").endswith("/mpec/K26/K26Q11.html")
    assert neocp_prev.mpec_url("2026-P99").endswith("/mpec/K26/K26P99.html")
    assert neocp_prev.mpec_url("2026-P114").endswith("/mpec/K26/K26PB4.html")
    assert neocp_prev.mpec_url("2026-P100").endswith("/mpec/K26/K26PA0.html")
    assert neocp_prev.mpec_url("non un identificativo") is None
