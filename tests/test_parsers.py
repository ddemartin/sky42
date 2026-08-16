"""I tre parser, su righe vere prese dai file scaricati il 2026-08-15.

Sono formati a colonne fisse pubblicati da terzi: l'unico modo di accorgersi
che sono cambiati è avere qui dentro una riga vera con i valori attesi scritti
a mano dal file, non prodotti dal codice.
"""
from __future__ import annotations

import gzip
import io
import json

from core.ingest import astorb, cometels, mpcorb

# --- righe vere, copiate da astorb.dat (267 colonne) ------------------------

ASTORB_CERES = (
    "     1 Ceres              L.H. Wasserman   3.34  0.15 0.72 848.4 G?    "
    "  0   0   0   2   0   7 82151 6914 20260917 295.937548  73.208090  "
    "80.248993 10.587505 0.07975072   2.76592189 20260606 1.2E-02  4.2E-05 "
    "20260815 2.5E-02 20270107 2.7E-02 20320221 2.7E-02 20320221"
)

ASTORB_PERSO = (
    "       1927 LA            L.H. Wasserman  11.0   0.15                 "
    "   0   0   0   0   0   3    34    3 20260917 153.934066 338.821813 "
    "191.009626 17.776448 0.34991985   3.30908436 20230806 2.7E+04  1.4E+00 "
    "20260815 2.7E+04 20260816 7.8E+04 20300107 3.1E+02 20300108"
)


def test_astorb_lunghezza_record():
    """Se questa cambia, il formato è cambiato e gli offset non valgono più."""
    assert len(ASTORB_CERES) == astorb.RECORD_LENGTH
    assert len(ASTORB_PERSO) == astorb.RECORD_LENGTH


def test_astorb_numerato():
    r = astorb.parse_line(ASTORB_CERES)
    assert r["number"] == 1
    assert r["designation"] == "Ceres"
    assert r["is_numbered"] is True
    assert r["ceu_arcsec"] == 0.012
    assert r["ceu_rate"] == 4.2e-05
    assert r["ceu_date"] == "2026-08-15"
    assert r["bv_color"] == 0.72
    assert r["diameter_km"] == 848.4
    assert r["taxon_class"] == "G?"
    assert r["astorb_a_au"] == 2.76592189
    assert r["n_obs"] == 6914


def test_astorb_non_numerato_e_perso():
    """Un oggetto perso: CEU di 27000 arcsec, cioè più di 7 gradi.

    È il caso che giustifica tenere ASTORB: nessun altro catalogo dice quanto
    è irrecuperabile un oggetto.
    """
    r = astorb.parse_line(ASTORB_PERSO)
    assert r["number"] is None
    assert r["designation"] == "1927 LA"
    assert r["is_numbered"] is False
    assert r["ceu_arcsec"] == 27000.0
    assert r["diameter_km"] is None


def test_astorb_riga_corta_scartata():
    assert astorb.parse_line("     1 Ceres\n") is None


# --- CometEls ---------------------------------------------------------------

COMET_HALEBOPP = (
    "    CJ95O010  1997 03 29.0337  0.924189  0.994900  130.7161  281.7940  "
    " 89.7413  20260814  -2.0  4.0  C/1995 O1 (Hale-Bopp)                    "
    "               MPC194091"
)

COMET_INTERSTELLARE = (
    "0002I         2019 12  9.0572  1.997724  3.345952  209.2911  307.8024  "
    " 44.2624  20251121  11.0  4.0  2I/Borisov                               "
    "               MPC1234  "
)


def test_cometels_periodica():
    r = cometels.parse_line(COMET_HALEBOPP)
    assert r["primary_desig"] == "C/1995 O1"
    assert r["display_name"] == "C/1995 O1 (Hale-Bopp)"
    assert r["q_au"] == 0.924189
    assert r["e"] == 0.9949
    assert r["i_deg"] == 89.7413
    assert r["m1"] == -2.0
    # epoca 2026-08-14: sta una colonna più a destra di come la descrive la
    # documentazione pubblicata, ed è l'errore che si fa in silenzio
    assert abs(r["epoch_jd"] - 2461266.5) < 1e-6


def test_cometels_interstellare_iperbolica():
    """2I/Borisov ha e = 3.35: `a` non esiste e non deve essere inventato."""
    r = cometels.parse_line(COMET_INTERSTELLARE)
    assert r["number"] == 2
    assert r["orbit_type_code"] == "I"
    assert r["primary_desig"] == "2I/Borisov"
    assert r["e"] > 1


# --- MPCORB extended --------------------------------------------------------

MPCORB_SAMPLE = [
    {
        "H": 3.34, "G": 0.15, "Num_obs": 7297, "rms": 0.83, "U": "0",
        "Arc_years": "1801-2026", "Number": "(1)", "Name": "Ceres",
        "Principal_desig": "A801 AA", "Other_desigs": ["A899 OF", "1943 XB"],
        "Epoch": 2461200.5, "M": 274.41935, "Peri": 73.2942, "Node": 80.24863,
        "i": 10.58803, "e": 0.0796923, "n": 0.21430445, "a": 2.7655526,
        "Num_opps": 126, "Computer": "Veres", "Hex_flags": "4000",
        "Last_obs": "2026-01-03", "Tp": 2461599.84154,
        "Orbital_period": 4.5991003, "Perihelion_dist": 2.5451594,
        "Aphelion_dist": 2.9859458, "Orbit_type": "MBA",
    },
    {
        "H": 19.59, "G": 0.15, "Num_obs": 12, "U": "9", "Arc_years": "23 days",
        "Principal_desig": "2025 MB218", "Epoch": 2461200.5, "M": 102.33998,
        "Peri": 52.89608, "Node": 196.76775, "i": 3.26557, "e": 0.1402939,
        "n": 0.2781073, "a": 2.3244906, "Num_opps": 1,
        "Last_obs": "2025-07-14", "Orbit_type": "MBA",
    },
]


def test_mpcorb_stream_json_indentato():
    """Il file è indentato oggi; il lettore non deve dipenderne."""
    testo = json.dumps(MPCORB_SAMPLE, indent=1)
    letti = list(mpcorb.iter_json_array(io.StringIO(testo)))
    assert len(letti) == 2
    assert letti[0]["Name"] == "Ceres"


def test_mpcorb_stream_json_compatto():
    testo = json.dumps(MPCORB_SAMPLE, separators=(",", ":"))
    letti = list(mpcorb.iter_json_array(io.StringIO(testo)))
    assert len(letti) == 2


def test_mpcorb_stream_buffer_minuscolo():
    """Un record spezzato su più letture non deve perdersi."""
    testo = json.dumps(MPCORB_SAMPLE, indent=1)
    letti = list(mpcorb.iter_json_array(io.StringIO(testo), bufsize=7))
    assert len(letti) == 2
    assert letti[1]["Principal_desig"] == "2025 MB218"


def test_mpcorb_normalizza_numerato():
    r = mpcorb.normalize(MPCORB_SAMPLE[0])
    assert r["number"] == 1
    assert r["primary_desig"] == "A801 AA"     # la designazione, non il nome
    assert r["display_name"] == "(1) Ceres"
    assert r["orbit_class"] == "MBA"
    assert r["last_obs_date"] == "2026-01-03"
    assert r["n_oppositions"] == 126
    assert abs(r["arc_days"] - 225 * 365.25) < 400


def test_mpcorb_normalizza_arco_in_giorni():
    """Gli oggetti appena scoperti hanno l'arco in giorni, non in anni."""
    r = mpcorb.normalize(MPCORB_SAMPLE[1])
    assert r["number"] is None
    assert r["primary_desig"] == "2025 MB218"
    assert r["arc_days"] == 23.0
    assert r["first_obs_date"] is None


def test_mpcorb_scarta_senza_elementi():
    assert mpcorb.normalize({"Name": "senza orbita"}) is None


def test_mpcorb_da_file_gz(tmp_path):
    p = tmp_path / "mini.json.gz"
    with gzip.open(p, "wt", encoding="utf-8") as fh:
        json.dump(MPCORB_SAMPLE, fh, indent=1)
    assert len(list(mpcorb.iter_records(p))) == 2
