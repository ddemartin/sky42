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


def cmd_siti(args) -> None:
    from services import sites_service

    if not args.solo_lettura:
        report = sites_service.run_reconcile()
        print(f"— reconcile — {report['siti']} file")
        for chiave in ("creati", "aggiornati", "disattivati"):
            voci = report[chiave]
            print(f"  {chiave:<14} {len(voci):>3}  {', '.join(voci) if voci else ''}")
        if report["vlim_tenuti"]:
            print(f"  vlim misurato tenuto per: {', '.join(report['vlim_tenuti'])}")
        print()

    for sito in sites_service.overview():
        stato = "" if sito["active"] else "  [dismesso]"
        print(f"{sito['name']} ({sito['code']}){stato}")
        print(f"  {sito['latitude']:+.4f}, {sito['longitude']:+.4f}  "
              f"{sito['altitude_m']:.0f} m  {sito['timezone']}  "
              f"cielo {sito['sky_zenith_mag']:.1f}  k={sito['extinction_k']:.2f}")
        for s in sito["setups"]:
            print(f"    {s['code']:<28} {s['pixel_scale_arcsec']:.3f}\"/px  "
                  f"{s['fov_x_arcmin']:.1f}' × {s['fov_y_arcmin']:.1f}'  "
                  f"f/{s['f_ratio']:.1f}  Vlim {s['vlim_ref']:.1f}"
                  f"{'' if s['active'] else '  [dismesso]'}")


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

    pl = sub.add_parser("siti", help="riallinea l'hardware dai file YAML e lo mostra")
    pl.add_argument("--solo-lettura", action="store_true", dest="solo_lettura",
                    help="mostra soltanto, senza riallineare")
    pl.set_defaults(func=cmd_siti)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
