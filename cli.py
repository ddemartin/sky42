"""Riga di comando di sky42: serve a far girare i lavori senza l'interfaccia.

    .venv/bin/python cli.py ingest all            scarica e importa tutto
    .venv/bin/python cli.py ingest mpcorb --force ignora ETag e reimporta
    .venv/bin/python cli.py ingest astorb --file data/catalogs/astorb.dat.gz
    .venv/bin/python cli.py stato                 cosa c'è nel database

Gli stessi moduli che usa l'interfaccia: qui non c'è logica, solo argomenti.
"""
from __future__ import annotations

import os

# Come in main.py, prima di numpy: il parallelismo lo decidiamo noi.
os.environ.setdefault("OMP_NUM_THREADS", "1")
os.environ.setdefault("VECLIB_MAXIMUM_THREADS", "1")

import argparse  # noqa: E402
import json  # noqa: E402
from pathlib import Path  # noqa: E402

from core.applog import setup_file_logging  # noqa: E402
from core.db import init_db  # noqa: E402


def cmd_ingest(args) -> None:
    from services import ingest_service as ing

    path = Path(args.file) if args.file else None
    jobs = {
        "mpcorb": ing.sync_mpcorb,
        "astorb": ing.sync_astorb,
        "cometels": ing.sync_cometels,
    }
    if args.what == "all":
        if path:
            raise SystemExit("--file vale per una sorgente sola, non per 'all'")
        result = ing.sync_all(force=args.force)
    else:
        result = jobs[args.what](force=args.force, local_path=path)
    print(json.dumps(result, indent=2, ensure_ascii=False))


def cmd_stato(args) -> None:
    from services import catalog_service as cat

    print("— sorgenti —")
    for s in cat.source_status():
        eta = f"{s['age_days']:.1f} giorni fa" if s["age_days"] is not None else "mai"
        print(f"  {s['label']:<20} {eta:<16} {s['n_records'] or 0:>10,} record")
    print("\n— catalogo —")
    for k, v in cat.counts().items():
        print(f"  {k:<24} {v:>12,}")
    print("\n— Tisserand —")
    tj = cat.tisserand_summary()
    print(f"  Tj < 3.00                {tj['tj_lt_3']:>12,}")
    print(f"  Tj < 3.05                {tj['tj_lt_305']:>12,}")
    print(f"  ACO (tolte risonanti)    {tj['aco']:>12,}")
    for r in cat.tisserand_by_class():
        print(f"      {r['classe']:<46} {r['n']:>8,}")
    print("\n— incertezza (CEU) —")
    for r in cat.ceu_histogram():
        print(f"  {r['fascia']:<10} {r['n']:>10,}  {r['quota']:>6.2f}%")
    print("\n— da quanto non si osservano —")
    for r in cat.last_obs_histogram():
        print(f"  {r['fascia']:<16} {r['n']:>10,}")


def main() -> None:
    setup_file_logging()
    init_db()

    p = argparse.ArgumentParser(prog="sky42")
    sub = p.add_subparsers(dest="cmd", required=True)

    pi = sub.add_parser("ingest", help="scarica e importa i cataloghi")
    pi.add_argument("what", choices=["all", "mpcorb", "astorb", "cometels"])
    pi.add_argument("--force", action="store_true",
                    help="scarica e reimporta anche se la sorgente non è cambiata")
    pi.add_argument("--file", help="usa un file locale invece di scaricarlo")
    pi.set_defaults(func=cmd_ingest)

    ps = sub.add_parser("stato", help="cosa c'è nel database")
    ps.set_defaults(func=cmd_stato)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
