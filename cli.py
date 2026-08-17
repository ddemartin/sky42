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


def cmd_effemeride(args) -> None:
    from gui.layout import fmt_dec_dms, fmt_ra_hms
    from services import ephemeris_service as eph

    dati = eph.ephemeris(args.oggetto, days=args.giorni, step_days=args.passo)
    if dati is None:
        print(f"«{args.oggetto}» non è in catalogo. Forse:")
        for t in eph.search(args.oggetto, limit=10):
            print(f"  {t['display_name']}")
        raise SystemExit(1)

    t = dati["target"]
    print(f"{t['display_name']}  [{t['kind']}"
          + (f", {t['orbit_class']}" if t["orbit_class"] else "") + "]")
    # `a` e Tj non esistono per le iperboliche, e `—` è la risposta giusta:
    # riempirli con uno zero racconterebbe un'orbita che non c'è.
    from gui.layout import fmt_num

    print(f"  a={fmt_num(t['a_au'], 4)} e={fmt_num(t['e'], 4)} "
          f"i={fmt_num(t['i_deg'], 3)}°  q={fmt_num(t['q_derived_au'], 4)} AU  "
          f"Tj={fmt_num(t['tisserand_j'], 3)}")
    for a in dati["avvisi"]:
        print(f"  ! {a}")
    print(f"\n{'data (UTC)':<17}{'RA':>15}{'Dec':>16}{'V':>7}{'Δ (AU)':>10}"
          f"{'r (AU)':>9}{'elong':>8}{'fase':>7}{'\"/min':>8}")
    for r in dati["rows"]:
        v = "  —  " if r["v_mag"] is None else f"{r['v_mag']:5.1f}"
        print(f"{r['data']:<17}{fmt_ra_hms(r['ra_deg']):>15}{fmt_dec_dms(r['dec_deg']):>16}"
              f"{v:>7}{r['delta_au']:>10.4f}{r['r_au']:>9.4f}"
              f"{r['elong_deg']:>8.1f}{r['phase_deg']:>7.1f}"
              f"{r['motion_arcsec_min']:>8.2f}")


def cmd_screening(args) -> None:
    from services import screening_service as scr

    if args.solo_popolazione:
        from core.radar import population as pop

        righe, nomi = scr.population_rows(limit=args.limite)
        v_ref, quale = scr.radar_reference_v()
        print(f"popolazione monitorata: {len(righe):,} oggetti  "
              f"V_ref {v_ref:.2f} ({quale or 'ripiego'})")
        print("\n— per regola —")
        for i, n in enumerate(nomi):
            print(f"  {n:<16} {sum(1 for r in righe if r[f'sel_{i}']):>8,}")
        print()
        for r in righe[:20]:
            tj = r["tisserand_j"]
            print(f"  {r['display_name']:<34} {r['kind']:<9} "
                  f"Tj={'—' if tj is None else round(tj, 3):<7} "
                  f"[{', '.join(pop.why(r, nomi))}]")
        return

    esito = scr.run_screening(limit=args.limite)
    print(json.dumps(esito, indent=2, ensure_ascii=False))


def cmd_radar(args) -> None:
    from services import radar_service as rad

    if not args.solo_lettura:
        print(json.dumps(rad.run_radar(), indent=2, ensure_ascii=False))
        print()

    print("— stati (rollup migliore) —")
    for r in rad.state_counts():
        print(f"  {r['stato']:<16} {r['n']:>8,}")
    print("\n— ultime transizioni —")
    for t in rad.recent_transitions(limit=args.limite):
        v = "—" if t["v_pred"] is None else f"V {t['v_pred']:.1f}"
        print(f"  {t['at'][:16]}  {t['display_name']:<32} "
              f"{t['from_state']} → {t['to_state']}  {v}")


def cmd_candidati(args) -> None:
    from services import candidate_service as cand

    if not args.solo_lettura:
        for lista in (["NEOCP", "PCCP"] if args.lista == "tutte" else [args.lista]):
            print(json.dumps(cand.poll(lista, force=args.force), indent=2,
                             ensure_ascii=False))
        print()

    for lista, n in cand.counts().items():
        if lista == "snapshot":
            print(f"  snapshot in archivio: {n:,}")
        else:
            print(f"  {lista:<8} {n['aperti']:>4} aperti  "
                  f"{n['visti']:>6} visti in tutto  {n['risolti']:>5} risolti")

    print("\n— in lista adesso —")
    for c in cand.open_candidates(limit=args.limite):
        print(f"  {c['temp_desig']:<10} {c['list']:<6} score {c['score']:>5.0f}  "
              f"V {c['v_mag']:>5.1f}  {c['n_obs']:>4} obs  "
              f"arco {c['arc_hours'] / 24:>7.2f} g  "
              f"non ripreso da {c['not_seen_days']:>6.2f} g")

    spariti = cand.recent_departures()
    if spariti:
        print("\n— spariti di recente, destino ancora ignoto —")
        for c in spariti:
            print(f"  {c['temp_desig']:<10} {c['list']:<6} visto fino al {c['last_seen'][:16]}")


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

    pe = sub.add_parser("effemeride", help="effemeride di un oggetto, dal catalogo locale")
    pe.add_argument("oggetto", help="designazione, nome o numero: '1', 'Ceres', 'C/2023 A3'")
    pe.add_argument("--giorni", type=int, default=14)
    pe.add_argument("--passo", type=float, default=1.0, help="giorni fra due righe")
    pe.set_defaults(func=cmd_effemeride)

    pc = sub.add_parser("screening", help="propaga la popolazione monitorata e la distilla")
    pc.add_argument("--limite", type=int, default=None,
                    help="ferma la popolazione ai primi N oggetti (per provare)")
    pc.add_argument("--solo-popolazione", action="store_true", dest="solo_popolazione",
                    help="mostra chi verrebbe propagato, senza propagare")
    pc.set_defaults(func=cmd_screening)

    pr = sub.add_parser("radar", help="ricalcola gli stati e mostra le transizioni")
    pr.add_argument("--solo-lettura", action="store_true", dest="solo_lettura",
                    help="mostra soltanto, senza ricalcolare")
    pr.add_argument("--limite", type=int, default=20, help="quante transizioni mostrare")
    pr.set_defaults(func=cmd_radar)

    pk = sub.add_parser("candidati", help="polling NEOCP/PCCP e stato dei candidati")
    pk.add_argument("--lista", choices=["tutte", "NEOCP", "PCCP"], default="tutte")
    pk.add_argument("--force", action="store_true",
                    help="scarica anche se la lista non è cambiata")
    pk.add_argument("--solo-lettura", action="store_true", dest="solo_lettura",
                    help="mostra soltanto, senza interrogare l'MPC")
    pk.add_argument("--limite", type=int, default=20)
    pk.set_defaults(func=cmd_candidati)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
