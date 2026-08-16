"""Import completo su cataloghi in miniatura.

Qui si verificano le due regole che, se saltano, si perdono dati senza
accorgersene: `target` non si sostituisce mai, e la numerazione delle comete
non è quella degli asteroidi.
"""
from __future__ import annotations

import gzip
import json

from core.db import connect
from services import ingest_service as ing
from tests.test_parsers import (ASTORB_CERES, ASTORB_PERSO, COMET_HALEBOPP,
                                COMET_INTERSTELLARE, MPCORB_SAMPLE)

# 1P/Halley ha `number = 1`, esattamente come (1) Ceres.
COMET_HALLEY = (
    "0001P         2061 07 28.4141  0.586597  0.967142  112.2626   59.0810  "
    "162.2626  20260814   5.5  4.0  1P/Halley                                "
    "               MPC 1234 "
)


def _scrivi_cataloghi(tmp_path):
    mpc = tmp_path / "mpcorb.json.gz"
    with gzip.open(mpc, "wt", encoding="utf-8") as fh:
        json.dump(MPCORB_SAMPLE, fh, indent=1)

    ast = tmp_path / "astorb.dat"
    ast.write_text("\n".join([ASTORB_CERES, ASTORB_PERSO]) + "\n", encoding="utf-8")

    com = tmp_path / "CometEls.txt"
    com.write_text("\n".join([COMET_HALEBOPP, COMET_INTERSTELLARE, COMET_HALLEY]) + "\n",
                   encoding="utf-8")
    return mpc, ast, com


def test_import_completo(db, tmp_path):
    mpc, ast, com = _scrivi_cataloghi(tmp_path)

    r1 = ing.sync_mpcorb(local_path=mpc)
    assert r1["importati"] == 2 and r1["scartati"] == 0

    r2 = ing.sync_cometels(local_path=com)
    assert r2["importate"] == 3

    r3 = ing.sync_astorb(local_path=ast)
    # (1) Ceres si aggancia per numero; 1927 LA non esiste nell'MPC e resta fuori:
    # la fonte dell'identità è una sola.
    assert r3["letti"] == 2
    assert r3["agganciati"] == 1
    assert r3["senza_corrispondenza"] == 1

    conn = connect()
    try:
        assert conn.execute("SELECT count(*) FROM target WHERE kind='asteroid'").fetchone()[0] == 2
        assert conn.execute("SELECT count(*) FROM target WHERE kind='comet'").fetchone()[0] == 3

        # Il Tisserand è calcolato all'import, non a ogni interrogazione.
        tj = conn.execute(
            "SELECT tisserand_j FROM orbit o JOIN target t ON t.id=o.target_id "
            "WHERE t.number=1 AND t.kind='asteroid'"
        ).fetchone()[0]
        assert abs(tj - 3.31) < 0.01

        # Derivati presenti anche quando il catalogo non li dà espliciti.
        q = conn.execute(
            "SELECT q_derived_au FROM orbit o JOIN target t ON t.id=o.target_id "
            "WHERE t.primary_desig='2025 MB218'"
        ).fetchone()[0]
        assert abs(q - 2.3245 * (1 - 0.1402939)) < 1e-4
    finally:
        conn.close()


def test_comete_e_asteroidi_non_condividono_la_numerazione(db, tmp_path):
    """Regressione: la CEU di (1) Ceres non deve finire su 1P/Halley.

    Trovato contando gli agganci sul catalogo vero: erano 461 più del previsto,
    cioè quante sono le comete periodiche numerate.
    """
    mpc, ast, com = _scrivi_cataloghi(tmp_path)
    ing.sync_mpcorb(local_path=mpc)
    ing.sync_cometels(local_path=com)
    ing.sync_astorb(local_path=ast)

    conn = connect()
    try:
        righe = conn.execute(
            """SELECT t.kind, t.display_name, x.ceu_arcsec
               FROM astorb_extra x JOIN target t ON t.id = x.target_id"""
        ).fetchall()
        assert len(righe) == 1
        assert righe[0]["kind"] == "asteroid"
        assert righe[0]["ceu_arcsec"] == 0.012
    finally:
        conn.close()


def test_reimport_non_cancella_la_storia(db, tmp_path):
    """`target` si aggiorna, non si sostituisce.

    Con INSERT OR REPLACE la riga verrebbe cancellata e ricreata con un id
    nuovo, portandosi via a cascata watchlist, osservazioni e transizioni di
    stato. È la regola 1 di CLAUDE.md e si rompe senza fare rumore.
    """
    mpc, ast, com = _scrivi_cataloghi(tmp_path)
    ing.sync_mpcorb(local_path=mpc)

    conn = connect()
    try:
        tid = conn.execute("SELECT id FROM target WHERE number=1").fetchone()[0]
        conn.execute(
            "INSERT INTO watchlist (target_id, priority, note, added_at) VALUES (?,?,?,?)",
            (tid, 5, "prova", "2026-08-15T00:00:00Z"),
        )
        conn.execute(
            """INSERT INTO observation_log (target_id, obs_start, outcome)
               VALUES (?, '2026-08-15T02:00:00Z', 'detected')""",
            (tid,),
        )
    finally:
        conn.close()

    ing.sync_mpcorb(local_path=mpc, force=True)

    conn = connect()
    try:
        assert conn.execute("SELECT id FROM target WHERE number=1").fetchone()[0] == tid
        assert conn.execute("SELECT count(*) FROM watchlist").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM observation_log").fetchone()[0] == 1
    finally:
        conn.close()


def test_job_registrati(db, tmp_path):
    """Ogni import lascia una riga in job_run: è la prima cosa che si guarda."""
    mpc, _, _ = _scrivi_cataloghi(tmp_path)
    ing.sync_mpcorb(local_path=mpc)

    conn = connect()
    try:
        row = conn.execute(
            "SELECT job_name, status, n_processed FROM job_run ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert row["job_name"] == "mpcorb_sync"
        assert row["status"] == "ok"
        assert row["n_processed"] == 2
    finally:
        conn.close()
