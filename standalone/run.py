#!/usr/bin/env python3
"""
Fixed-plant experiments (does not write params.py).

Examples
--------
  python standalone/run.py list
  python standalone/run.py solve --preset mu0_gd60 --r0 --mu-re 0.36
  python standalone/run.py sweep-mu --preset mu0_gd60 --r0
  python standalone/run.py sweep-mu --preset pv100_wt100_st160 --r0
  python standalone/run.py sweep-phi --preset pv100_wt100_st160 --r0
"""
import argparse
import os
import sys
from concurrent.futures import ProcessPoolExecutor, as_completed

import numpy as np

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_HERE, ".."))
os.chdir(_ROOT)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from standalone.fixed_plant import PRESETS, capacities_of, solve_pinned  # noqa: E402


def _preset_pst_max(preset):
    return PRESETS[preset]["P_ST_MAX"]


def _out_base(preset, r0):
    base = PRESETS[preset]["results_dir"]
    if not r0 and base.endswith("_R0"):
        base = base[: -len("_R0")] + "_Rcrf"
    return base


def _worker(kwargs):
    return solve_pinned(**kwargs)


def cmd_list(_args):
    print("Presets (standalone/fixed_plant.py):\n")
    for name, cfg in PRESETS.items():
        print(f"  {name}")
        print(f"    {cfg['desc']}")
        print(
            f"    WT={cfg['x_WT']} MW  PV={cfg['x_PV']} MW  "
            f"ST={cfg['x_ST']} MWh  GD={cfg['x_GD']} MW  "
            f"P_ST_MAX={cfg['P_ST_MAX']}"
        )
        print(f"    results: {cfg['results_dir']}/")
        print()


def cmd_solve(args):
    preset = args.preset
    cap = capacities_of(preset)
    r0 = args.r0
    out = args.out
    if not out:
        tag = "solve"
        if args.mu_re is not None:
            tag = f"mu_re_{args.mu_re:.2f}"
        out = os.path.join(_out_base(preset, r0), tag)
    print(
        f"[solve] preset={preset} R={'0' if r0 else 'CRF'} "
        f"mu_re={args.mu_re} phi={args.phi} theta={args.theta} -> {out}"
    )
    r = solve_pinned(
        cap,
        r0=r0,
        p_st_max=_preset_pst_max(preset),
        mu_re_yuan=args.mu_re,
        phi=args.phi,
        theta=args.theta,
        output_dir=out,
    )
    if r is None:
        sys.exit("no solution")
    print(
        f"  c_ele={r['c_ele']:.4f}  obj={r['obj']:.2f}  "
        f"WT={r['x_WT']:.2f} PV={r['x_PV']:.2f} ST={r['x_ST']:.2f} GD={r['x_GD']:.2f}"
    )
    print(f"  files: {out}/optimization_results.txt")


def _parallel(jobs, label_key):
    results = []
    n = len(jobs)
    max_workers = min(n, 8)
    with ProcessPoolExecutor(max_workers=max_workers) as ex:
        futures = {ex.submit(_worker, job): job for job in jobs}
        done = 0
        for fut in as_completed(futures):
            job = futures[fut]
            done += 1
            try:
                r = fut.result()
            except Exception as exc:
                print(f"   [{done}/{n}] failed {label_key}={job.get(label_key)}: {exc}")
                continue
            if r is None:
                print(f"   [{done}/{n}] infeasible {label_key}={job.get(label_key)}")
                continue
            results.append(r)
            gap = r.get("mip_gap_achieved")
            gap_str = f"{gap:.2%}" if gap is not None else "N/A"
            print(
                f"   [{done}/{n}] {label_key}={job.get(label_key)}  "
                f"c_ele={r['c_ele']:.4f}  obj={r['obj']:.1f}  gap={gap_str}"
            )
    return results


def cmd_sweep_mu(args):
    import pandas as pd
    import matplotlib.pyplot as plt
    from matplotlib.ticker import ScalarFormatter

    preset = args.preset
    cap = capacities_of(preset)
    r0 = args.r0
    mu_values = [
        round(float(v), 2)
        for v in np.arange(args.mu_min, args.mu_max + 1e-9, args.mu_step)
    ]
    case_dir = os.path.join(_out_base(preset, r0), "sensitivity_mu_re")
    stub = PRESETS[preset]["plot_stub"]
    suffix = "R0" if r0 else "Rcrf"
    plot_png = os.path.join("plot", f"mu_re_vs_c_ele_{stub}_{suffix}.png")
    plot_xlsx = os.path.join("plot", f"sensitivity_mu_re_{stub}_{suffix}.xlsx")
    os.makedirs("plot", exist_ok=True)
    os.makedirs(case_dir, exist_ok=True)

    print("=" * 60)
    print(f" sweep-mu preset={preset} R={'0' if r0 else 'CRF'}")
    print(f" cap={cap}")
    print(f" mu grid (yuan/kWh): {mu_values}")
    print("=" * 60)

    jobs = []
    for mu in mu_values:
        jobs.append(
            dict(
                fixed_cap=cap,
                r0=r0,
                p_st_max=_preset_pst_max(preset),
                mu_re_yuan=mu,
                phi=args.phi,
                theta=args.theta,
                output_dir=os.path.join(case_dir, f"mu_re_{mu:.2f}"),
            )
        )
    results = _parallel(jobs, "mu_re_yuan")
    results.sort(key=lambda r: r["mu_re"])

    x_vals = [r["mu_re"] for r in results]
    c_vals = [r["c_ele"] for r in results]
    plt.figure(figsize=(10, 6))
    ax = plt.gca()
    ax.plot(x_vals, c_vals, "o-", linewidth=2, markersize=8, color="#2E86AB")
    ax.set_xlabel("RE transfer price (yuan/kWh)", fontsize=12)
    ylab = "Unit Electricity Cost (yuan/kWh, R=0)" if r0 else "Unit Electricity Cost (yuan/kWh, CRF)"
    ax.set_ylabel(ylab, fontsize=12)
    ax.set_title(f"RE buy price $\\mu$ ({stub}, {'R=0' if r0 else 'CRF'})", fontsize=13, fontweight="bold")
    ax.set_xticks(x_vals)
    ax.grid(True, alpha=0.3)
    y_min, y_max = min(c_vals), max(c_vals)
    y_pad = max((y_max - y_min) * 0.15, 0.002)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)
    formatter = ScalarFormatter(useOffset=False)
    formatter.set_scientific(False)
    ax.yaxis.set_major_formatter(formatter)
    plt.tight_layout()
    plt.savefig(plot_png, dpi=300, bbox_inches="tight")
    plt.close()
    print(f"   ✓ Plot saved: {plot_png}")

    df = pd.DataFrame(results)
    cols = [
        "mu_re", "c_ele", "obj", "c_inv", "c_grid_demand", "c_grid_energy",
        "c_grid", "rev_mkt", "x_WT", "x_PV", "x_ST", "x_GD",
        "mip_gap_achieved", "output_dir",
    ]
    df = df[[c for c in cols if c in df.columns]].rename(columns={
        "mu_re": "RE price (yuan/kWh)",
        "c_ele": "Unit cost (yuan/kWh, R=0)" if r0 else "Unit cost (yuan/kWh, CRF)",
        "obj": "Annualized Objective (万元/yr)",
        "c_inv": "Equipment Investment (万元, one-time)",
        "c_grid_demand": "Annual Grid Demand Charge (万元/yr)",
        "c_grid_energy": "Annual Grid Energy Cost (万元/yr)",
        "c_grid": "Annual Grid Cost (万元/yr)",
        "rev_mkt": "Annual Market Revenue (万元/yr)",
        "x_WT": "Wind (MW)",
        "x_PV": "PV (MW)",
        "x_ST": "Storage (MWh)",
        "x_GD": "Grid (MW)",
        "mip_gap_achieved": "MIP Gap Achieved",
        "output_dir": "Output Directory",
    })
    df.to_excel(plot_xlsx, index=False, sheet_name="mu_re Analysis")
    print(f"   ✓ Excel saved: {plot_xlsx}")
    print(f"Finished {len(results)}/{len(mu_values)} points.")


def cmd_sweep_phi(args):
    from green_power_opt import _save_sensitivity_summary

    preset = args.preset
    cap = capacities_of(preset)
    r0 = args.r0
    phi_values = [round(float(v), 2) for v in np.arange(0.0, 1.01, 0.1)]
    case_dir = os.path.join(_out_base(preset, r0), "sensitivity_phi")
    stub = PRESETS[preset]["plot_stub"]
    suffix = "R0" if r0 else "Rcrf"
    plot_png = os.path.join("plot", f"phi_vs_c_ele_{stub}_{suffix}.png")
    plot_xlsx = os.path.join("plot", f"sensitivity_phi_{stub}_{suffix}.xlsx")
    os.makedirs("plot", exist_ok=True)
    os.makedirs(case_dir, exist_ok=True)

    print("=" * 60)
    print(f" sweep-phi preset={preset} R={'0' if r0 else 'CRF'}")
    print(f" phi grid: {phi_values}")
    print("=" * 60)

    jobs = []
    for phi in phi_values:
        jobs.append(
            dict(
                fixed_cap=cap,
                r0=r0,
                p_st_max=_preset_pst_max(preset),
                mu_re_yuan=args.mu_re,
                phi=phi,
                theta=args.theta,
                output_dir=os.path.join(case_dir, f"phi_{phi:.2f}"),
            )
        )
    results = _parallel(jobs, "phi")
    results = [r for r in results if r is not None]
    results.sort(key=lambda r: r["phi"])
    _save_sensitivity_summary(
        results,
        sweep_key="phi",
        plot_filename=plot_png,
        excel_filename=plot_xlsx,
        title=f"Self-consumption φ ({stub}, {'R=0' if r0 else 'CRF'})",
        xlabel="Min RE Self-consumption Ratio (φ)",
        marker="s-",
        color="#A23B72",
    )
    print(f"Finished {len(results)}/{len(phi_values)} points.")


def _add_common(sp):
    sp.add_argument("--preset", required=True, choices=sorted(PRESETS))
    sp.add_argument("--r0", action="store_true", help="set investment CRF R=0 (opex-only J)")
    sp.add_argument("--phi", type=float, default=0.6)
    sp.add_argument("--theta", type=float, default=0.3)


def build_parser():
    p = argparse.ArgumentParser(
        description="Fixed-plant solves (params.py is not modified).",
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="show capacity presets")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("solve", help="one fixed-plant solve")
    _add_common(sp)
    sp.add_argument("--mu-re", type=float, default=None, help="μ_PV=μ_WT in 元/kWh")
    sp.add_argument("--out", type=str, default=None)
    sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("sweep-mu", help="μ_PV=μ_WT sensitivity (元/kWh)")
    _add_common(sp)
    sp.add_argument("--mu-min", type=float, default=0.30)
    sp.add_argument("--mu-max", type=float, default=0.40)
    sp.add_argument("--mu-step", type=float, default=0.02)
    sp.set_defaults(func=cmd_sweep_mu)

    sp = sub.add_parser("sweep-phi", help="phi 0-100 percent, step 10 percent")
    _add_common(sp)
    sp.add_argument("--mu-re", type=float, default=None, help="μ_PV=μ_WT in 元/kWh")
    sp.set_defaults(func=cmd_sweep_phi)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
