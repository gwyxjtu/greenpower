"""
Green-power direct-connection microgrid capacity planning (Gurobi MILP).

  python green_power_opt.py --x-gd 60 --mu-re 0
  python green_power_opt.py --x-gd 0 --mu-re 0
"""
import argparse
import csv
import os
import time

import gurobipy as gp
from gurobipy import GRB

import params as p

MAIN_MIP_GAP = 0.01


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


def run_optimization(X_GD_bound, output_dir="."):
    os.makedirs(output_dir, exist_ok=True)
    results_path = os.path.join(output_dir, "optimization_results.txt")
    csv_path = os.path.join(output_dir, "timeseries_results.csv")
    ilp_path = os.path.join(output_dir, "model.ilp")

    print("=" * 60)
    print(" Green Power Microgrid Capacity Planning Model")
    print(f" Output directory: {output_dir}")
    print("=" * 60)
    print("Building model...")

    start_time = time.time()
    model = gp.Model("GreenPowerMicrogrid")
    model.setParam("MIPGap", MAIN_MIP_GAP)
    model.setParam("TimeLimit", 300)
    model.setParam("Heuristics", 0.5)

    print("Adding variables...")
    x_WT = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="x_WT")
    x_PV = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="x_PV")
    x_ST = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="x_ST")
    if X_GD_bound > 0:
        x_GD = model.addVar(lb=X_GD_bound, ub=X_GD_bound, vtype=GRB.CONTINUOUS, name="x_GD")
    else:
        x_GD = model.addVar(lb=0, ub=200, vtype=GRB.CONTINUOUS, name="x_GD")

    p_WT = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_WT")
    p_PV = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_PV")
    p_ST_C = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_ST_C")
    p_ST_D = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_ST_D")
    p_GD = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_GD")
    p_GD_U = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_GD_U")
    E = model.addVars(p.T + 1, lb=0, vtype=GRB.CONTINUOUS, name="E")
    z1 = model.addVars(p.T, vtype=GRB.BINARY, name="z1")
    z2 = model.addVars(p.T, vtype=GRB.BINARY, name="z2")
    y1 = model.addVars(p.T, vtype=GRB.BINARY, name="y1")
    y2 = model.addVars(p.T, vtype=GRB.BINARY, name="y2")
    w_ST_C = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="w_ST_C")
    w_ST_D = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="w_ST_D")

    print("Setting objective function...")
    cost_investment = p.R * (
        p.lambda_WT * x_WT + p.lambda_PV * x_PV + p.lambda_ST * x_ST + p.lambda_GD * x_GD
    )
    cost_re_energy = gp.quicksum(
        (p.mu_PV_t[t] * p_PV[t] + p.mu_WT_t[t] * p_WT[t]) * p.delta for t in range(p.T)
    )
    cost_grid_buy = gp.quicksum(p.mu_EB_t[t] * p_GD[t] * p.delta for t in range(p.T))
    cost_grid_fixed = p.M * (p.mu_DC * x_GD + 730 * p.mu_ED * x_GD * p.L_bar)
    cost_grid_surcharge = gp.quicksum(
        (p.mu_EO_t[t] + p.mu_EL_t[t]) * p_GD[t] * p.delta for t in range(p.T)
    )
    cost_fund_EG = gp.quicksum(
        p.mu_EG_t[t] * (p_PV[t] + p_WT[t] + p_GD[t]) * p.delta for t in range(p.T)
    )
    cost_connection = p.mu_TL * p.D * p.CRF
    revenue_market = gp.quicksum(p.mu_ES_t[t] * p_GD_U[t] * p.delta for t in range(p.T))
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
    model.setObjective(J, GRB.MINIMIZE)

    print("Adding constraints...")
    model.addConstrs(
        (
            p_WT[t] + p_PV[t] - w_ST_C[t] + w_ST_D[t] + p_GD[t] - p_GD_U[t] == p.load_t[t]
            for t in range(p.T)
        ),
        name="c_power_balance",
    )
    model.addConstrs((p_WT[t] <= p.alpha_WT_t[t] * x_WT for t in range(p.T)), name="c_wt_max")
    model.addConstrs((p_PV[t] <= p.alpha_PV_t[t] * x_PV for t in range(p.T)), name="c_pv_max")
    model.addConstr(p.a_PV * x_PV <= p.S_PV_MAX, name="c_pv_area")

    model.addConstrs((w_ST_C[t] <= p.P_ST_MAX_C * z1[t] for t in range(p.T)), name="c_wC_z")
    model.addConstrs((w_ST_C[t] <= p_ST_C[t] for t in range(p.T)), name="c_wC_p")
    model.addConstrs(
        (w_ST_C[t] >= p_ST_C[t] - p.P_ST_MAX_C * (1 - z1[t]) for t in range(p.T)),
        name="c_wC_lb",
    )
    model.addConstrs((w_ST_D[t] <= p.P_ST_MAX_D * z2[t] for t in range(p.T)), name="c_wD_z")
    model.addConstrs((w_ST_D[t] <= p_ST_D[t] for t in range(p.T)), name="c_wD_p")
    model.addConstrs(
        (w_ST_D[t] >= p_ST_D[t] - p.P_ST_MAX_D * (1 - z2[t]) for t in range(p.T)),
        name="c_wD_lb",
    )
    model.addConstrs(
        (
            E[t + 1] == E[t] + (p.eta_ch * w_ST_C[t] - w_ST_D[t] / p.eta_dis) * p.delta
            for t in range(p.T)
        ),
        name="c_E_trans",
    )
    model.addConstrs((E[t] >= p.E_eps for t in range(1, p.T + 1)), name="c_E_min")
    model.addConstrs((E[t] <= x_ST for t in range(p.T + 1)), name="c_E_max")
    model.addConstr(E[0] == p.E_init, name="c_E_init")
    model.addConstrs((p_ST_C[t] <= p.P_ST_MAX_C for t in range(p.T)), name="c_st_c_max")
    model.addConstrs((p_ST_D[t] <= p.P_ST_MAX_D for t in range(p.T)), name="c_st_d_max")
    model.addConstrs((z1[t] + z2[t] == 1 for t in range(p.T)), name="c_st_mut_excl")
    model.addConstrs((p_GD[t] <= x_GD * y1[t] for t in range(p.T)), name="c_gd_buy_max")
    model.addConstrs((p_GD_U[t] <= x_GD * y2[t] for t in range(p.T)), name="c_gd_sell_max")
    model.addConstrs((y1[t] + y2[t] <= 1 for t in range(p.T)), name="c_gd_mut_excl")

    sum_gd_u = gp.quicksum(p_GD_U[t] * p.delta for t in range(p.T))
    sum_re = gp.quicksum((p_WT[t] + p_PV[t]) * p.delta for t in range(p.T))
    avail_re = x_PV * p.Theta_PV + x_WT * p.Theta_WT
    model.addConstr(sum_gd_u <= p.psi * avail_re, name="c_grid_prop")
    model.addConstr(sum_re - sum_gd_u >= p.phi * avail_re, name="c_re_prop1")
    sum_load = gp.quicksum(p.load_t[t] * p.delta for t in range(p.T))
    model.addConstr(sum_re >= p.theta * sum_load, name="c_re_prop2")

    print(f"Model construction time: {time.time() - start_time:.2f} seconds")
    print("Starting optimization...")
    model.optimize()

    if model.SolCount > 0:
        with open(results_path, "w", encoding="utf-8") as f:
            status_str = (
                "OPTIMAL"
                if model.Status == GRB.OPTIMAL
                else f"UNFINISHED (Status {model.Status}, Feasible solution found)"
            )
            f.write("=" * 60 + "\n")
            f.write(f" Optimization Terminated! Status: {status_str}\n")
            f.write(f" Total Annualized Objective: {model.ObjVal:.2f} 万元/年\n")
            f.write("=" * 60 + "\n")
            f.write(" [Optimal Capacities] \n")
            f.write(f" - Wind Power (x_WT): {x_WT.X:.2f} MW\n")
            f.write(f" - Photovoltaic (x_PV): {x_PV.X:.2f} MW\n")
            f.write(f" - Energy Storage (x_ST): {x_ST.X:.2f} MWh\n")
            f.write(f" - Grid Transformer (x_GD): {x_GD.X:.2f} MW\n")

            c_inv = (
                p.lambda_WT * x_WT.X
                + p.lambda_PV * x_PV.X
                + p.lambda_ST * x_ST.X
                + p.lambda_GD * x_GD.X
            )
            c_conn = p.mu_TL * p.D
            c_grid = p.M * (p.mu_DC * x_GD.X + 730 * p.mu_ED * x_GD.X * p.L_bar)
            c_grid_energy = sum(
                (p.mu_EB_t[t] + p.mu_EO_t[t] + p.mu_EL_t[t]) * p_GD[t].X * p.delta
                + p.mu_EG_t[t] * (p_PV[t].X + p_WT[t].X + p_GD[t].X) * p.delta
                + (p.mu_PV_t[t] * p_PV[t].X + p.mu_WT_t[t] * p_WT[t].X) * p.delta
                for t in range(p.T)
            )
            rev_mkt = sum(p.mu_ES_t[t] * p_GD_U[t].X * p.delta for t in range(p.T))
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

            total_re = sum((p_WT[t].X + p_PV[t].X) * p.delta for t in range(p.T))
            total_gd_u = sum(p_GD_U[t].X * p.delta for t in range(p.T))
            total_load_e = sum(p.load_t[t] * p.delta for t in range(p.T))
            avail_re_val = x_PV.X * p.Theta_PV + x_WT.X * p.Theta_WT
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
                soc_val = (E[t].X / x_ST.X) if x_ST.X > 1e-6 else 0.0
                writer.writerow(
                    [
                        t,
                        round(p.load_t[t], 2),
                        round(p_WT[t].X, 2),
                        round(p_PV[t].X, 2),
                        round(w_ST_C[t].X, 2),
                        round(w_ST_D[t].X, 2),
                        round(soc_val, 4),
                        round(p_GD[t].X, 2),
                        round(p_GD_U[t].X, 2),
                    ]
                )
        print(f"Time-series data saved to '{csv_path}'.")

    elif model.Status == GRB.INFEASIBLE:
        print("Model is Infeasible! Please check the parameters or constraints.")
        model.computeIIS()
        model.write(ilp_path)
        print(f"IIS written to '{ilp_path}'")
    else:
        print(f"Optimization ended with status: {model.Status}")


def _cli(argv=None):
    parser = argparse.ArgumentParser(
        description="Green-power MILP capacity planning (params.py defaults, optional overrides).",
    )
    parser.add_argument("--x-gd", type=float, default=60.0, help="transformer MW; 0 = free 0–200")
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
        f"[solve] x_GD={'free' if not xgd else xgd}  mu_re={args.mu_re}  "
        f"R={'0' if args.r0 else f'{p.R:.4f}'}  phi={p.phi} theta={p.theta} -> {out}"
    )
    run_optimization(0 if not xgd else xgd, output_dir=out)


if __name__ == "__main__":
    _cli()
