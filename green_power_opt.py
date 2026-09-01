"""
Green-power direct-connection microgrid capacity planning (SCIP MILP).

  python green_power_opt.py --x-gd 60 --mu-re 0
  python green_power_opt.py --x-gd 0 --mu-re 0
"""
import argparse
import csv
import os
import time

import pyscipopt
from pyscipopt import SCIP_PARAMEMPHASIS, SCIP_PARAMSETTING, Model, quicksum

import params as p

MAIN_MIP_GAP = 0.01
MAIN_TIME_LIMIT = 600


def unit_electricity_cost(c_inv, c_conn, annual_net, total_load):
    """
    Unit cost aligned with the objective: J / annual load.
    J = R * (c_inv + c_conn) + annual_net  [万元/年]
    Returns 元/kWh (×10 converts 万元/MWh).
    """
    if total_load <= 0:
        return 0.0
    J = p.R * (c_inv + c_conn) + annual_net
    return J / total_load * 10


def unit_cost_label():
    """Result-file label; R=0 means opex-only (capex not in J)."""
    if abs(p.R) < 1e-12:
        return "Unit Electricity Cost (R=0, opex only)"
    return f"Unit Electricity Cost (CRF {p.discount_rate:.0%}/{p.project_life}yr)"


def apply_runtime_overrides(mu_re_yuan=None, r0=False, phi=None, theta=None):
    """In-memory overrides. mu_re_yuan is 元/kWh. Does not write params.py."""
    if r0:
        p.R = 0.0
        p.CRF = 0.0
    if mu_re_yuan is not None:
        v = float(mu_re_yuan) * 0.1  # 万元/MWh
        p.mu_PV = v
        p.mu_WT = v
        p.mu_PV_t[:] = v
        p.mu_WT_t[:] = v
    if phi is not None:
        p.phi = float(phi)
    if theta is not None:
        p.theta = float(theta)


def _add_vars(model, n, name, vtype="C", lb=0.0, ub=None):
    vars_ = []
    for i in range(n):
        kw = {"vtype": vtype, "name": f"{name}[{i}]"}
        if vtype != "B":
            kw["lb"] = lb
            if ub is not None:
                kw["ub"] = ub
        vars_.append(model.addVar(**kw))
    return vars_


def _status_label(model):
    status = model.getStatus()
    if status in ("optimal", "gaplimit"):
        return "OPTIMAL"
    return f"UNFINISHED (Status {status}, Feasible solution found)"


def _gap_str(model):
    try:
        gap = model.getGap()
    except (ArithmeticError, ValueError, OverflowError):
        return "inf"
    if gap != gap or gap > 1e12:
        return "inf"
    return f"{gap:.2%}"


def _configure_scip(model, mip_gap, time_limit):
    model.hideOutput(False)
    model.setParam("limits/gap", float(mip_gap))
    model.setParam("limits/time", float(time_limit))
    model.setParam("timing/clocktype", 2)  # wall-clock seconds
    # Root LP is already near the integer bound; skip expensive cuts and hunt for a feasible MIP.
    model.setEmphasis(SCIP_PARAMEMPHASIS.FEASIBILITY)
    model.setHeuristics(SCIP_PARAMSETTING.AGGRESSIVE)
    model.setSeparating(SCIP_PARAMSETTING.OFF)


def run_optimization(X_GD_bound, output_dir=".", mip_gap=MAIN_MIP_GAP, time_limit=MAIN_TIME_LIMIT):
    os.makedirs(output_dir, exist_ok=True)
    results_path = os.path.join(output_dir, "optimization_results.txt")
    csv_path = os.path.join(output_dir, "timeseries_results.csv")
    lp_path = os.path.join(output_dir, "model.lp")

    print("=" * 60)
    print(" Green Power Microgrid Capacity Planning Model")
    print(f" Solver: SCIP (PySCIPOpt)  gap={mip_gap}  time={time_limit}s")
    print(f" Output directory: {output_dir}")
    print("=" * 60)
    print("Building model...")

    start_time = time.time()
    model = Model("GreenPowerMicrogrid")
    _configure_scip(model, mip_gap, time_limit)

    print("Adding variables...")
    x_pv_ub = p.S_PV_MAX / p.a_PV
    x_WT = model.addVar(lb=0, ub=p.X_WT_MAX, vtype="C", name="x_WT")
    x_PV = model.addVar(lb=0, ub=x_pv_ub, vtype="C", name="x_PV")
    x_ST = model.addVar(lb=0, ub=p.X_ST_MAX, vtype="C", name="x_ST")
    if X_GD_bound > 0:
        x_GD = model.addVar(lb=X_GD_bound, ub=X_GD_bound, vtype="C", name="x_GD")
        x_gd_ub = float(X_GD_bound)
    else:
        x_GD = model.addVar(lb=0, ub=p.X_GD_MAX, vtype="C", name="x_GD")
        x_gd_ub = float(p.X_GD_MAX)

    p_WT = _add_vars(model, p.T, "p_WT", ub=p.X_WT_MAX)
    p_PV = _add_vars(model, p.T, "p_PV", ub=x_pv_ub)
    p_ST_C = _add_vars(model, p.T, "p_ST_C", ub=p.P_ST_MAX_C)
    p_ST_D = _add_vars(model, p.T, "p_ST_D", ub=p.P_ST_MAX_D)
    p_GD = _add_vars(model, p.T, "p_GD", ub=x_gd_ub)
    p_GD_U = _add_vars(model, p.T, "p_GD_U", ub=x_gd_ub)
    E = _add_vars(model, p.T + 1, "E", ub=p.X_ST_MAX)
    z1 = _add_vars(model, p.T, "z1", vtype="B")
    z2 = _add_vars(model, p.T, "z2", vtype="B")
    y1 = _add_vars(model, p.T, "y1", vtype="B")
    y2 = _add_vars(model, p.T, "y2", vtype="B")
    w_ST_C = _add_vars(model, p.T, "w_ST_C", ub=p.P_ST_MAX_C)
    w_ST_D = _add_vars(model, p.T, "w_ST_D", ub=p.P_ST_MAX_D)

    print("Setting objective function...")
    cost_investment = p.R * (
        p.lambda_WT * x_WT + p.lambda_PV * x_PV + p.lambda_ST * x_ST + p.lambda_GD * x_GD
    )
    cost_re_energy = quicksum(
        (p.mu_PV_t[t] * p_PV[t] + p.mu_WT_t[t] * p_WT[t]) * p.delta for t in range(p.T)
    )
    cost_grid_buy = quicksum(p.mu_EB_t[t] * p_GD[t] * p.delta for t in range(p.T))
    cost_grid_fixed = p.M * (p.mu_DC * x_GD + 730 * p.mu_ED * x_GD * p.L_bar)
    cost_grid_surcharge = quicksum(
        (p.mu_EO_t[t] + p.mu_EL_t[t]) * p_GD[t] * p.delta for t in range(p.T)
    )
    cost_fund_EG = quicksum(
        p.mu_EG_t[t] * (p_PV[t] + p_WT[t] + p_GD[t]) * p.delta for t in range(p.T)
    )
    cost_connection = p.mu_TL * p.D * p.CRF
    revenue_market = quicksum(p.mu_ES_t[t] * p_GD_U[t] * p.delta for t in range(p.T))
    J = (
        cost_investment
        + cost_re_energy
        + cost_grid_buy
        + cost_grid_fixed
        + cost_grid_surcharge
        + cost_fund_EG
        + cost_connection
        - revenue_market
    )
    model.setObjective(J, "minimize")

    print("Adding constraints...")
    for t in range(p.T):
        model.addCons(
            p_WT[t] + p_PV[t] - w_ST_C[t] + w_ST_D[t] + p_GD[t] - p_GD_U[t] == p.load_t[t],
            name=f"c_power_balance[{t}]",
        )
        model.addCons(p_WT[t] <= p.alpha_WT_t[t] * x_WT, name=f"c_wt_max[{t}]")
        model.addCons(p_PV[t] <= p.alpha_PV_t[t] * x_PV, name=f"c_pv_max[{t}]")
        model.addCons(w_ST_C[t] <= p.P_ST_MAX_C * z1[t], name=f"c_wC_z[{t}]")
        model.addCons(w_ST_C[t] <= p_ST_C[t], name=f"c_wC_p[{t}]")
        model.addCons(
            w_ST_C[t] >= p_ST_C[t] - p.P_ST_MAX_C * (1 - z1[t]),
            name=f"c_wC_lb[{t}]",
        )
        model.addCons(w_ST_D[t] <= p.P_ST_MAX_D * z2[t], name=f"c_wD_z[{t}]")
        model.addCons(w_ST_D[t] <= p_ST_D[t], name=f"c_wD_p[{t}]")
        model.addCons(
            w_ST_D[t] >= p_ST_D[t] - p.P_ST_MAX_D * (1 - z2[t]),
            name=f"c_wD_lb[{t}]",
        )
        model.addCons(
            E[t + 1] == E[t] + (p.eta_ch * w_ST_C[t] - w_ST_D[t] / p.eta_dis) * p.delta,
            name=f"c_E_trans[{t}]",
        )
        model.addCons(p_ST_C[t] <= p.P_ST_MAX_C, name=f"c_st_c_max[{t}]")
        model.addCons(p_ST_D[t] <= p.P_ST_MAX_D, name=f"c_st_d_max[{t}]")
        model.addCons(z1[t] + z2[t] == 1, name=f"c_st_mut_excl[{t}]")
        # p <= x * y  (y binary) → McCormick / big-M: p <= x and p <= x_ub * y
        model.addCons(p_GD[t] <= x_GD, name=f"c_gd_buy_cap[{t}]")
        model.addCons(p_GD[t] <= x_gd_ub * y1[t], name=f"c_gd_buy_ind[{t}]")
        model.addCons(p_GD_U[t] <= x_GD, name=f"c_gd_sell_cap[{t}]")
        model.addCons(p_GD_U[t] <= x_gd_ub * y2[t], name=f"c_gd_sell_ind[{t}]")
        model.addCons(y1[t] + y2[t] <= 1, name=f"c_gd_mut_excl[{t}]")

    model.addCons(p.a_PV * x_PV <= p.S_PV_MAX, name="c_pv_area")
    for t in range(1, p.T + 1):
        model.addCons(E[t] >= p.E_eps, name=f"c_E_min[{t}]")
    for t in range(p.T + 1):
        model.addCons(E[t] <= x_ST, name=f"c_E_max[{t}]")
    model.addCons(E[0] == p.E_init, name="c_E_init")

    sum_gd_u = quicksum(p_GD_U[t] * p.delta for t in range(p.T))
    sum_re = quicksum((p_WT[t] + p_PV[t]) * p.delta for t in range(p.T))
    avail_re = x_PV * p.Theta_PV + x_WT * p.Theta_WT
    model.addCons(sum_gd_u <= p.psi * avail_re, name="c_grid_prop")
    model.addCons(sum_re - sum_gd_u >= p.phi * avail_re, name="c_re_prop1")
    sum_load = quicksum(p.load_t[t] * p.delta for t in range(p.T))
    model.addCons(sum_re >= p.theta * sum_load, name="c_re_prop2")

    print(f"Model construction time: {time.time() - start_time:.2f} seconds")
    print("Starting optimization...")
    model.optimize()

    status = model.getStatus()
    nsols = model.getNSols()

    if nsols > 0:
        val = model.getVal
        obj = model.getObjVal()
        with open(results_path, "w", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            f.write(f" Optimization Terminated! Status: {_status_label(model)}\n")
            f.write(f" Solver: SCIP (PySCIPOpt {pyscipopt.__version__})\n")
            f.write(f" MIP gap: {_gap_str(model)}\n")
            f.write(f" Total Annualized Objective: {obj:.2f} 万元/年\n")
            f.write("=" * 60 + "\n")
            f.write(" [Optimal Capacities] \n")
            f.write(f" - Wind Power (x_WT): {val(x_WT):.2f} MW\n")
            f.write(f" - Photovoltaic (x_PV): {val(x_PV):.2f} MW\n")
            f.write(f" - Energy Storage (x_ST): {val(x_ST):.2f} MWh\n")
            f.write(f" - Grid Transformer (x_GD): {val(x_GD):.2f} MW\n")

            c_inv = (
                p.lambda_WT * val(x_WT)
                + p.lambda_PV * val(x_PV)
                + p.lambda_ST * val(x_ST)
                + p.lambda_GD * val(x_GD)
            )
            c_conn = p.mu_TL * p.D
            c_grid = p.M * (p.mu_DC * val(x_GD) + 730 * p.mu_ED * val(x_GD) * p.L_bar)
            c_grid_energy = sum(
                (p.mu_EB_t[t] + p.mu_EO_t[t] + p.mu_EL_t[t]) * val(p_GD[t]) * p.delta
                + p.mu_EG_t[t] * (val(p_PV[t]) + val(p_WT[t]) + val(p_GD[t])) * p.delta
                + (p.mu_PV_t[t] * val(p_PV[t]) + p.mu_WT_t[t] * val(p_WT[t])) * p.delta
                for t in range(p.T)
            )
            rev_mkt = sum(p.mu_ES_t[t] * val(p_GD_U[t]) * p.delta for t in range(p.T))
            total_load = sum(p.load_t[t] for t in range(p.T))
            c_ele = unit_electricity_cost(c_inv, c_conn, c_grid + c_grid_energy - rev_mkt, total_load)

            f.write("\n [Cost Breakdown - Real Prices] \n")
            f.write(f" - Equipment Investment (one-time): {c_inv:.2f} 万元\n")
            f.write(f" - Direct Connection Cost (one-time): {c_conn:.2f} 万元\n")
            f.write(f" - Annual Grid Demand Charge: {c_grid:.2f} 万元/年\n")
            f.write(f" - Annual Energy/Tariff Cost (EB+EO+EL+EG+RE): {c_grid_energy:.2f} 万元/年\n")
            f.write(f" - Annual Grid Charge (total): {c_grid + c_grid_energy:.2f} 万元/年\n")
            f.write(f" - Annual Market Revenue: {rev_mkt:.2f} 万元/年\n")
            f.write(f" - {unit_cost_label()}: {c_ele:.4f} 元/kWh\n")

            total_re = sum((val(p_WT[t]) + val(p_PV[t])) * p.delta for t in range(p.T))
            total_gd_u = sum(val(p_GD_U[t]) * p.delta for t in range(p.T))
            total_load_e = sum(p.load_t[t] * p.delta for t in range(p.T))
            avail_re_val = val(x_PV) * p.Theta_PV + val(x_WT) * p.Theta_WT
            ratio_export = total_gd_u / avail_re_val if avail_re_val > 1e-9 else 0.0
            ratio_self = (total_re - total_gd_u) / avail_re_val if avail_re_val > 1e-9 else 0.0
            ratio_re_load = total_re / total_load_e if total_load_e > 1e-9 else 0.0

            f.write("\n [Policy Ratios] \n")
            f.write(f" - 余电上网比例 (sum_gd_u/avail_re): {ratio_export:.4f}\n")
            f.write(f" - 自发自用比例 ((sum_re-sum_gd_u)/avail_re): {ratio_self:.4f}\n")
            f.write(f" - 绿电使用占比 (sum_re/sum_load): {ratio_re_load:.4f}\n")
            f.write("\n [Energy Statistics] \n")
            f.write(f" - Total Renewable Generation: {total_re:.2f} MWh\n")
            f.write(f" - Total Load Demand: {total_load_e:.2f} MWh\n")
            f.write(f" - Available RE (x*Θ): {avail_re_val:.2f} MWh\n")
            f.write(f" - On-grid Export (sum_gd_u): {total_gd_u:.2f} MWh\n")

        print(f"Optimization successful! Results saved to '{results_path}'.")
        x_st_val = val(x_ST)
        with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(
                [
                    "Hour",
                    "Load",
                    "P_WT",
                    "P_PV",
                    "P_ST_Charge",
                    "P_ST_Discharge",
                    "SOC",
                    "P_Grid_Buy",
                    "P_Grid_Sell",
                ]
            )
            for t in range(p.T):
                soc_val = (val(E[t]) / x_st_val) if x_st_val > 1e-6 else 0.0
                writer.writerow(
                    [
                        t,
                        round(p.load_t[t], 2),
                        round(val(p_WT[t]), 2),
                        round(val(p_PV[t]), 2),
                        round(val(w_ST_C[t]), 2),
                        round(val(w_ST_D[t]), 2),
                        round(soc_val, 4),
                        round(val(p_GD[t]), 2),
                        round(val(p_GD_U[t]), 2),
                    ]
                )
        print(f"Time-series data saved to '{csv_path}'.")

    elif status == "infeasible":
        print("Model is Infeasible! Please check the parameters or constraints.")
        model.writeProblem(lp_path)
        print(f"LP written to '{lp_path}'")
    else:
        print(f"Optimization ended with status: {status}")


def _cli(argv=None):
    parser = argparse.ArgumentParser(
        description="Green-power MILP capacity planning (SCIP; params.py defaults, optional overrides).",
    )
    parser.add_argument("--x-gd", type=float, default=60.0, help="transformer MW; 0 = free 0–X_GD_MAX")
    parser.add_argument(
        "--mu-re",
        type=float,
        default=None,
        help="μ_PV=μ_WT in 元/kWh; omit = params.py",
    )
    parser.add_argument("--r0", action="store_true", help="set CRF R=0 (opex-only objective)")
    parser.add_argument("--phi", type=float, default=None)
    parser.add_argument("--theta", type=float, default=None)
    parser.add_argument("--out", type=str, default=None)
    parser.add_argument(
        "--mip-gap",
        type=float,
        default=MAIN_MIP_GAP,
        help=f"relative MIP gap (default {MAIN_MIP_GAP})",
    )
    parser.add_argument(
        "--time-limit",
        type=float,
        default=MAIN_TIME_LIMIT,
        help=f"wall-clock time limit in seconds (default {MAIN_TIME_LIMIT})",
    )
    args = parser.parse_args(argv)

    apply_runtime_overrides(mu_re_yuan=args.mu_re, r0=args.r0, phi=args.phi, theta=args.theta)
    xgd = args.x_gd
    if args.out:
        out = args.out
    else:
        stem = (
            f"x_gd_{int(xgd) if xgd and float(xgd).is_integer() else xgd}" if xgd else "x_gd_free"
        )
        if args.mu_re == 0.0:
            stem += "_mu_zero"
        elif args.mu_re is not None:
            stem += f"_mu{args.mu_re:.2f}"
        if args.r0:
            stem += "_R0"
        out = os.path.join("out", stem)
    print(
        f"[solve] SCIP  x_GD={'free' if not xgd else xgd}  mu_re={args.mu_re}  "
        f"R={'0' if args.r0 else f'{p.R:.4f}'}  phi={p.phi} theta={p.theta} "
        f"gap={args.mip_gap} time={args.time_limit}s -> {out}"
    )
    run_optimization(
        0 if not xgd else xgd,
        output_dir=out,
        mip_gap=args.mip_gap,
        time_limit=args.time_limit,
    )


if __name__ == "__main__":
    _cli()
