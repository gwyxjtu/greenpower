import gurobipy as gp
from gurobipy import GRB
import time
import os
import numpy as np
import matplotlib.pyplot as plt
from matplotlib.ticker import FormatStrFormatter, ScalarFormatter
import pandas as pd
from concurrent.futures import ProcessPoolExecutor, as_completed

# Import parameters and synthetic data
import params as p

def run_optimization(X_GD_bound, output_dir="."):
    os.makedirs(output_dir, exist_ok=True)
    results_path = os.path.join(output_dir, "optimization_results.txt")
    csv_path = os.path.join(output_dir, "timeseries_results.csv")
    ilp_path = os.path.join(output_dir, "model.ilp")

    print("="*60)
    print(f" Green Power Microgrid Capacity Planning Model (x_GD >= {X_GD_bound} MW)")
    print(f" Output directory: {output_dir}")
    print("="*60)
    print("Building model...")
    
    start_time = time.time()
    
    # Create an environment (optional but good for silencing some outputs if needed)
    # env = gp.Env(empty=True)
    # env.setParam("OutputFlag", 1)
    # env.start()
    
    # Create a new Gurobi model
    model = gp.Model("GreenPowerMicrogrid")
    
    # Optional: set parameters for the solver
    model.setParam('MIPGap', MAIN_MIP_GAP)    # 1% gap
    model.setParam('TimeLimit', 300)  # 5 min time limit
    model.setParam('Heuristics', 0.5)    # More heuristics

    # ============================================================
    # 1. Variables Definition
    # ============================================================
    print("Adding variables...")
    
    # Planned capacities (Continuous, >= 0)
    x_WT = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="x_WT")
    x_PV = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="x_PV")
    x_ST = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="x_ST")
    x_GD = model.addVar(lb=X_GD_bound, vtype=GRB.CONTINUOUS, name="x_GD")
    
    # Operation variables for each time step t (0 to T-1)
    p_WT = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_WT")
    p_PV = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_PV")
    p_ST_C = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_ST_C")
    p_ST_D = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_ST_D")
    p_GD = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_GD")
    p_GD_U = model.addVars(p.T, ub=0, vtype=GRB.CONTINUOUS, name="p_GD_U")
    
    # Energy variables to linearize SOC_t * x_ST (E_t = SOC_t * x_ST)
    E = model.addVars(p.T + 1, lb=0, vtype=GRB.CONTINUOUS, name="E")
    
    # Auxiliary binary variables
    z1 = model.addVars(p.T, vtype=GRB.BINARY, name="z1")  # Charge state
    z2 = model.addVars(p.T, vtype=GRB.BINARY, name="z2")  # Discharge state
    y1 = model.addVars(p.T, vtype=GRB.BINARY, name="y1")  # Grid purchase state
    y2 = model.addVars(p.T, vtype=GRB.BINARY, name="y2")  # Grid sell state
    
    # ============================================================
    # 2. Objective Function
    # ============================================================
    print("Setting objective function...")
    
    cost_investment = p.CRF * (p.lambda_WT * x_WT + p.lambda_PV * x_PV + p.lambda_ST * x_ST + p.lambda_GD * x_GD)
    cost_grid_fixed = p.M * (p.mu_DC * x_GD + 730 * p.mu_ELE * x_GD * p.L_bar)
    cost_connection = p.nu * p.D
    revenue_market = gp.quicksum(p.mu_MKT_t[t] * p_GD_U[t] for t in range(p.T))
    
    J = cost_investment +  cost_grid_fixed + cost_connection - revenue_market      # append capital recovery factor
    
    model.setObjective(J, GRB.MINIMIZE)
    
    # ============================================================
    # 3. Constraints
    # ============================================================
    print("Adding constraints...")
    
    # (1) Capacity balance constraint
    model.addConstr(x_WT + x_PV + x_ST + x_GD >= p.L, name="c_cap_balance")
    
    # (2) Power balance constraint
    model.addConstrs((p_WT[t] + p_PV[t] - p_ST_C[t] + p_ST_D[t] + p_GD[t] - p_GD_U[t] == p.load_t[t] 
                      for t in range(p.T)), name="c_power_balance")
    
    # (3) & (4) Physical constraints of renewable energy
    model.addConstrs((p_WT[t] <= p.alpha_WT_t[t] * x_WT for t in range(p.T)), name="c_wt_max")
    model.addConstrs((p_PV[t] <= p.alpha_PV_t[t] * x_PV for t in range(p.T)), name="c_pv_max")
    
    # (5) Physical constraints of energy storage system
    # E_t = SOC_t * x_ST, so E_t bounds are SOC_min * x_ST <= E_t <= SOC_max * x_ST
    model.addConstrs((E[t] >= p.SOC_min * x_ST for t in range(p.T + 1)), name="c_soc_min")
    model.addConstrs((E[t] <= p.SOC_max * x_ST for t in range(p.T + 1)), name="c_soc_max")
    
    # Optional constraints for sustainability: ensure end of year energy >= initial energy
    model.addConstr(E[0] == p.SOC_init * x_ST, name="c_E_init")
    model.addConstr(E[p.T] >= p.SOC_init * x_ST, name="c_E_final")
    
    # State of charge dynamics (transformed to Energy):
    model.addConstrs((E[t+1] == E[t] + (p.eta_ch * p_ST_C[t] - p_ST_D[t] / p.eta_dis) * p.delta
                      for t in range(p.T)), name="c_E_trans")
    
    # Charge / discharge maximum power and mutual exclusivity
    model.addConstrs((p_ST_C[t] <= p.P_ST_MAX_C * z1[t] for t in range(p.T)), name="c_st_c_max")
    model.addConstrs((p_ST_D[t] <= p.P_ST_MAX_D * z2[t] for t in range(p.T)), name="c_st_d_max")
    model.addConstrs((z1[t] + z2[t] == 1 for t in range(p.T)), name="c_st_mut_excl")
    
    # (6) Physical constraints of power grid
    # To linearize x_GD * y1[t] -> standard big-M type constraints might be better if x_GD isn't fixed,
    # but Gurobi handles product of a continuous and binary variable linearly automatically via formulation 
    # or you can use indicator constraints. Given x_GD * binary, Gurobi natively supports it directly if NonConvex is not required.
    # Actually, Gurobi handles exactly this: x_GD * binary natively as a bilinear term but since it involves binary, 
    # it linearly maps it internally.
    model.addConstrs((p_GD[t] <= x_GD * y1[t] for t in range(p.T)), name="c_gd_buy_max")
    model.addConstrs((p_GD_U[t] <= x_GD * y2[t] for t in range(p.T)), name="c_gd_sell_max")
    model.addConstrs((y1[t] + y2[t] <= 1 for t in range(p.T)), name="c_gd_mut_excl")
    
    sum_gd_u = gp.quicksum(p_GD_U[t] * p.delta for t in range(p.T))
    sum_re = gp.quicksum((p_WT[t] + p_PV[t]) * p.delta for t in range(p.T))
    
    model.addConstr(sum_gd_u <= p.psi * sum_re, name="c_grid_prop")
    
    # (7) Renewable energy generation constraints
    model.addConstr(sum_re - sum_gd_u >= p.phi * sum_re, name="c_re_prop1")
    sum_load = gp.quicksum(p.load_t[t] * p.delta for t in range(p.T))
    model.addConstr(sum_re >= p.theta * sum_load, name="c_re_prop2")
    
    # ============================================================
    # 4. Model Optimization
    # ============================================================
    print(f"Model construction time: {time.time() - start_time:.2f} seconds")
    print("Starting optimization...")
    model.optimize()
    
    # ============================================================
    # 5. Result Output
    # ============================================================
    if model.SolCount > 0:
        with open(results_path, "w", encoding="utf-8") as f:
            f.write("="*60 + "\n")
            status_str = "OPTIMAL" if model.Status == GRB.OPTIMAL else f"UNFINISHED (Status {model.Status}, Feasible solution found)"
            f.write(f" Optimization Terminated! Status: {status_str}\n")
            f.write(f" Total Annualized Objective: {model.ObjVal:.2f} 万元/年\n")
            f.write("="*60 + "\n")
            f.write(" [Optimal Capacities] \n")
            f.write(f" - Wind Power (x_WT): {x_WT.X:.2f} MW\n")
            f.write(f" - Photovoltaic (x_PV): {x_PV.X:.2f} MW\n")
            f.write(f" - Energy Storage (x_ST): {x_ST.X:.2f} MWh\n")
            f.write(f" - Grid Transformer (x_GD): {x_GD.X:.2f} MW\n")
            
            # Real (un-annualized) cost breakdown
            N = p.project_life  # project lifetime in years
            c_inv = p.lambda_WT * x_WT.X + p.lambda_PV * x_PV.X + p.lambda_ST * x_ST.X + p.lambda_GD * x_GD.X
            c_conn = p.nu * p.D
            c_grid = p.M * (p.mu_DC * x_GD.X + 730 * p.mu_ELE * x_GD.X * p.L_bar)
            rev_mkt = sum(p.mu_MKT_t[t] * p_GD_U[t].X for t in range(p.T))
            total_load = sum(p.load_t[t] for t in range(p.T))
            # LCOE = lifetime total net cost / lifetime total energy
            # c_inv & c_conn are one-time; c_grid & rev_mkt are annual; ×10 converts 万元/MWh -> 元/kWh
            c_ele = ((c_inv + c_conn) + N * (c_grid - rev_mkt)) / (N * total_load) * 10
            
            f.write("\n [Cost Breakdown - Real Prices] \n")
            f.write(f" - Equipment Investment (one-time): {c_inv:.2f} 万元\n")
            f.write(f" - Direct Connection Cost (one-time): {c_conn:.2f} 万元\n")
            f.write(f" - Annual Grid Charge: {c_grid:.2f} 万元/年\n")
            f.write(f" - Annual Market Revenue: {rev_mkt:.2f} 万元/年\n")
            f.write(f" - Unit Electricity Cost (LCOE, {N}-yr lifecycle): {c_ele:.4f} 元/kWh\n")

            
            total_re = sum((p_WT[t].X + p_PV[t].X) * p.delta for t in range(p.T))
            total_load = sum(p.load_t[t] for t in range(p.T))
            f.write("\n [Energy Statistics] \n")
            f.write(f" - Total Renewable Generation: {total_re:.2f} MWh\n")
            f.write(f" - Total Load Demand: {total_load:.2f} MWh\n")
        
        print(f"Optimization successful! Results saved to '{results_path}'.")
        
        # Save time-series results to CSV
        import csv
        with open(csv_path, "w", newline='', encoding="utf-8") as csvfile:
            writer = csv.writer(csvfile)
            writer.writerow(["Hour", "Load", "P_WT", "P_PV", "P_ST_Charge", "P_ST_Discharge", "SOC", "P_Grid_Buy", "P_Grid_Sell"])
            for t in range(p.T):
                # E[t] is energy, SOC = E[t] / x_ST 
                soc_val = (E[t].X / x_ST.X) if x_ST.X > 1e-6 else 0.0
                writer.writerow([
                    t,
                    round(p.load_t[t], 2),
                    round(p_WT[t].X, 2),
                    round(p_PV[t].X, 2),
                    round(p_ST_C[t].X, 2),
                    round(p_ST_D[t].X, 2),
                    round(soc_val, 4),
                    round(p_GD[t].X, 2),
                    round(p_GD_U[t].X, 2)
                ])
        print(f"Time-series data saved to '{csv_path}'.")
        
    elif model.Status == GRB.INFEASIBLE:
        print("Model is Infeasible! Please check the parameters or constraints.")
        # Compute IIS to find the conflicting constraints
        model.computeIIS()
        model.write(ilp_path)
        print(f"IIS written to '{ilp_path}'")
    else:
        print(f"Optimization ended with status: {model.Status}")

MAX_SENSITIVITY_WORKERS = 8
DEFAULT_D = 50.0
DEFAULT_PHI = 0.6
DEFAULT_THETA = 0.3
SENSITIVITY_RESULTS_DIR = "results/sensitivity"
SENSITIVITY_MIP_GAP = 0.05          # bulk sweep stopping tolerance (1%)
SENSITIVITY_REFINE_MIP_GAP = 0.01   # refined points stopping tolerance (1%)
MAIN_MIP_GAP = 0.01                 # run_optimization stopping tolerance (1%)


def _format_sensitivity_tag(sweep_key, value):
    """Build a stable directory name for one sensitivity case."""
    if sweep_key == "D":
        v = int(value) if float(value).is_integer() else value
        return f"D_{v}"
    return f"{sweep_key}_{float(value):.1f}"


def _sensitivity_case_dir(sweep_key, value):
    return os.path.join(SENSITIVITY_RESULTS_DIR, sweep_key, _format_sensitivity_tag(sweep_key, value))


def _solver_status_str(status):
    if status == GRB.OPTIMAL:
        return "OPTIMAL"
    if status == GRB.TIME_LIMIT:
        return f"TIME_LIMIT (Status {status})"
    return f"UNFINISHED (Status {status}, Feasible solution found)"


def _save_sensitivity_case_files(
    output_dir,
    *,
    D_val,
    phi_val,
    theta_val,
    mip_gap_target,
    mip_gap_achieved,
    status,
    obj_val,
    x_WT,
    x_PV,
    x_ST,
    x_GD,
    p_WT,
    p_PV,
    p_ST_C,
    p_ST_D,
    p_GD,
    p_GD_U,
    E,
    c_inv,
    c_conn,
    c_grid,
    rev_mkt,
    c_ele,
):
    """Write optimization_results.txt and timeseries_results.csv for one sensitivity case."""
    import csv

    os.makedirs(output_dir, exist_ok=True)
    results_path = os.path.join(output_dir, "optimization_results.txt")
    csv_path = os.path.join(output_dir, "timeseries_results.csv")

    total_re = sum((p_WT[t].X + p_PV[t].X) * p.delta for t in range(p.T))
    total_load = sum(p.load_t[t] for t in range(p.T))
    status_str = _solver_status_str(status)
    gap_achieved_str = f"{mip_gap_achieved:.4%}" if mip_gap_achieved is not None else "N/A"

    with open(results_path, "w", encoding="utf-8") as f:
        f.write("=" * 60 + "\n")
        f.write(f" Sensitivity Case: D={D_val}, phi={phi_val}, theta={theta_val}\n")
        f.write(f" Optimization Terminated! Status: {status_str}\n")
        f.write(f" MIP Gap Target: {mip_gap_target:.2%}\n")
        f.write(f" MIP Gap Achieved: {gap_achieved_str}\n")
        f.write(f" Total Annualized Objective: {obj_val:.2f} 万元/年\n")
        f.write("=" * 60 + "\n")
        f.write(" [Optimal Capacities] \n")
        f.write(f" - Wind Power (x_WT): {x_WT.X:.2f} MW\n")
        f.write(f" - Photovoltaic (x_PV): {x_PV.X:.2f} MW\n")
        f.write(f" - Energy Storage (x_ST): {x_ST.X:.2f} MWh\n")
        f.write(f" - Grid Transformer (x_GD): {x_GD.X:.2f} MW\n")
        f.write("\n [Cost Breakdown - Real Prices] \n")
        f.write(f" - Equipment Investment (one-time): {c_inv:.2f} 万元\n")
        f.write(f" - Direct Connection Cost (one-time): {c_conn:.2f} 万元\n")
        f.write(f" - Annual Grid Charge: {c_grid:.2f} 万元/年\n")
        f.write(f" - Annual Market Revenue: {rev_mkt:.2f} 万元/年\n")
        f.write(f" - Unit Electricity Cost (LCOE, {p.project_life}-yr lifecycle): {c_ele:.4f} 元/kWh\n")
        f.write("\n [Energy Statistics] \n")
        f.write(f" - Total Renewable Generation: {total_re:.2f} MWh\n")
        f.write(f" - Total Load Demand: {total_load:.2f} MWh\n")

    with open(csv_path, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Hour", "Load", "P_WT", "P_PV", "P_ST_Charge", "P_ST_Discharge", "SOC", "P_Grid_Buy", "P_Grid_Sell"])
        for t in range(p.T):
            soc_val = (E[t].X / x_ST.X) if x_ST.X > 1e-6 else 0.0
            writer.writerow([
                t,
                round(p.load_t[t], 2),
                round(p_WT[t].X, 2),
                round(p_PV[t].X, 2),
                round(p_ST_C[t].X, 2),
                round(p_ST_D[t].X, 2),
                round(soc_val, 4),
                round(p_GD[t].X, 2),
                round(p_GD_U[t].X, 2),
            ])


def _run_sensitivity_point(D, phi, theta, mip_gap, output_dir):
    """Process-pool worker: one sensitivity case with explicit parameters."""
    return run_single_optimization(
        D=D,
        phi=phi,
        theta=theta,
        mip_gap=mip_gap,
        output_dir=output_dir,
    )


def _parallel_sensitivity_sweep(tasks, sort_key, mip_gap=SENSITIVITY_MIP_GAP):
    """
    Run sensitivity cases in parallel (up to MAX_SENSITIVITY_WORKERS).
    Each task is a dict with keys D, phi, theta.
    """
    if not tasks:
        return []

    max_workers = min(len(tasks), MAX_SENSITIVITY_WORKERS)
    print(f"   Running {len(tasks)} cases in parallel (max_workers={max_workers}, MIPGap={mip_gap:.0%})...")
    results = []
    with ProcessPoolExecutor(max_workers=max_workers) as executor:
        futures = {}
        for t in tasks:
            output_dir = _sensitivity_case_dir(sort_key, t[sort_key])
            futures[executor.submit(
                _run_sensitivity_point,
                t["D"],
                t["phi"],
                t["theta"],
                mip_gap,
                output_dir,
            )] = t
        done = 0
        for future in as_completed(futures):
            task = futures[future]
            done += 1
            try:
                result = future.result()
                if result is not None:
                    results.append(result)
                    gap_str = (
                        f"{result['mip_gap_achieved']:.2%}"
                        if result.get("mip_gap_achieved") is not None
                        else "N/A"
                    )
                    print(
                        f"   [{done}/{len(tasks)}] done: {sort_key}={task[sort_key]}, "
                        f"gap={gap_str} -> {result['output_dir']}"
                    )
                else:
                    print(f"   [{done}/{len(tasks)}] no solution: {sort_key}={task[sort_key]}")
            except Exception as exc:
                print(f"   [{done}/{len(tasks)}] failed: {sort_key}={task[sort_key]}: {exc}")

    results.sort(key=lambda r: r[sort_key])
    return results


def _refine_sensitivity_points(results, sort_key, refine_values, fixed_params, mip_gap=SENSITIVITY_REFINE_MIP_GAP):
    """Re-run selected points with a tighter MIP gap and merge into results."""
    if not results:
        return results

    refined = []
    for val in refine_values:
        task = {**fixed_params, sort_key: val}
        output_dir = _sensitivity_case_dir(sort_key, val)
        print(f"   Refining {sort_key}={val} with MIPGap={mip_gap:.0%}...")
        result = run_single_optimization(
            D=task["D"],
            phi=task["phi"],
            theta=task["theta"],
            mip_gap=mip_gap,
            output_dir=output_dir,
        )
        if result is not None:
            refined.append(result)
            gap_str = (
                f"{result['mip_gap_achieved']:.2%}"
                if result.get("mip_gap_achieved") is not None
                else "N/A"
            )
            print(
                f"   ✓ {sort_key}={val}: LCOE={result['c_ele']:.4f} 元/kWh, "
                f"gap={gap_str} -> {result['output_dir']}"
            )
        else:
            print(f"   ✗ {sort_key}={val}: no solution")

    if not refined:
        return results

    refined_map = {r[sort_key]: r for r in refined}
    merged = [refined_map.get(r[sort_key], r) for r in results]
    merged.sort(key=lambda r: r[sort_key])
    return merged


_SENSITIVITY_EXPORT_COLUMNS = [
    ("D", "Distance (km)"),
    ("phi", "Min Self-consumption Ratio"),
    ("theta", "Min RE Generation Ratio"),
    ("c_ele", "LCOE (元/kWh)"),
    ("c_inv", "Equipment Investment (万元, one-time)"),
    ("c_grid", "Annual Grid Cost (万元/yr)"),
    ("c_conn", "Connection Cost (万元, one-time)"),
    ("rev_mkt", "Annual Market Revenue (万元/yr)"),
    ("obj", "Annualized Objective (万元/yr)"),
    ("mip_gap_target", "MIP Gap Target"),
    ("mip_gap_achieved", "MIP Gap Achieved"),
    ("x_WT", "Wind (MW)"),
    ("x_PV", "PV (MW)"),
    ("x_ST", "Storage (MWh)"),
    ("x_GD", "Grid (MW)"),
    ("output_dir", "Output Directory"),
]


def _save_sensitivity_summary(results, sweep_key, plot_filename, excel_filename, title, xlabel, marker, color):
    """Save one sensitivity plot and Excel summary."""
    if not results:
        return

    x_vals = [r[sweep_key] for r in results]
    c_ele_vals = [r["c_ele"] for r in results]

    plt.figure(figsize=(10, 6))
    ax = plt.gca()
    ax.plot(x_vals, c_ele_vals, marker, linewidth=2, markersize=8, color=color)
    ax.set_xlabel(xlabel, fontsize=12)
    ax.set_ylabel("Unit Electricity Cost (元/kWh)", fontsize=12)
    ax.set_title(title, fontsize=14, fontweight="bold")
    ax.grid(True, alpha=0.3)
    if sweep_key in ("phi", "theta"):
        ax.set_xticks(x_vals)

    # Show actual LCOE values; disable Matplotlib offset/scientific notation (e.g. 1e-6+4.4125e-1).
    y_min, y_max = min(c_ele_vals), max(c_ele_vals)
    y_span = y_max - y_min
    y_pad = max(y_span * 0.15, 0.002)
    ax.set_ylim(y_min - y_pad, y_max + y_pad)
    if y_span < 0.01:
        ax.yaxis.set_major_formatter(FormatStrFormatter("%.5f"))
    else:
        formatter = ScalarFormatter(useOffset=False)
        formatter.set_scientific(False)
        ax.yaxis.set_major_formatter(formatter)

    plt.tight_layout()
    plt.savefig(plot_filename, dpi=300, bbox_inches="tight")
    print(f"   ✓ Plot saved: {plot_filename}")
    plt.close()

    df = pd.DataFrame(results)
    export_cols = [src for src, _ in _SENSITIVITY_EXPORT_COLUMNS if src in df.columns]
    df_export = df[export_cols].copy()
    rename_map = {src: label for src, label in _SENSITIVITY_EXPORT_COLUMNS if src in export_cols}
    df_export.rename(columns=rename_map, inplace=True)
    df_export.to_excel(excel_filename, index=False, sheet_name=f"{sweep_key} Analysis")
    print(f"   ✓ Excel saved: {excel_filename}")


def run_sensitivity_analysis():
    """Run sensitivity analysis for three key parameters and generate plots."""
    print("\n" + "="*60)
    print(" Sensitivity Analysis: Parameter Impact on Unit Cost")
    print("="*60)
    
    # Create output folders
    os.makedirs("plot", exist_ok=True)
    os.makedirs(SENSITIVITY_RESULTS_DIR, exist_ok=True)
    
    # ============================================================
    # 1. Sensitivity Analysis: D (Direct Connection Distance)
    # ============================================================
    # print("\n1. Analyzing impact of D (connection distance)...")
    # D_values = np.arange(10, 100, 10)  # 10 to 80 km, step 10
    # D_tasks = [
    #     {"D": float(D_val), "phi": DEFAULT_PHI, "theta": DEFAULT_THETA}
    #     for D_val in D_values
    # ]
    # D_results = _parallel_sensitivity_sweep(D_tasks, sort_key="D")
    # _save_sensitivity_summary(
    #     D_results,
    #     sweep_key="D",
    #     plot_filename="plot/D_vs_c_ele.png",
    #     excel_filename="plot/sensitivity_D.xlsx",
    #     title="Impact of Connection Distance on Unit Electricity Cost",
    #     xlabel="Direct Connection Distance (km)",
    #     marker="o-",
    #     color="#2E86AB",
    # )
    
    # ============================================================
    # 2. Sensitivity Analysis: phi (Min RE self-consumption ratio)
    # ============================================================
    print("\n2. Analyzing impact of phi (RE self-consumption ratio)...")
    phi_values = np.arange(0.1, 1.0, 0.1)
    phi_tasks = [
        {"D": DEFAULT_D, "phi": round(float(phi_val), 1), "theta": DEFAULT_THETA}
        for phi_val in phi_values
    ]
    phi_results = _parallel_sensitivity_sweep(phi_tasks, sort_key="phi")
    _save_sensitivity_summary(
        phi_results,
        sweep_key="phi",
        plot_filename="plot/phi_vs_c_ele.png",
        excel_filename="plot/sensitivity_phi.xlsx",
        title="Impact of RE Self-consumption Ratio on Unit Electricity Cost",
        xlabel="Min RE Self-consumption Ratio (φ)",
        marker="s-",
        color="#A23B72",
    )
    
    # # ============================================================
    # # 3. Sensitivity Analysis: theta (Min RE generation to load ratio)
    # # ============================================================
    print("\n3. Analyzing impact of theta (RE generation ratio)...")
    theta_values = np.arange(0.1, 1.0, 0.1)
    theta_tasks = [
        {"D": DEFAULT_D, "phi": DEFAULT_PHI, "theta": round(float(theta_val), 1)}
        for theta_val in theta_values
    ]
    theta_results = _parallel_sensitivity_sweep(theta_tasks, sort_key="theta")
    # theta_results = _refine_sensitivity_points(
    #     theta_results,
    #     sort_key="theta",
    #     refine_values=[0.3, 0.9],
    #     fixed_params={"D": DEFAULT_D, "phi": DEFAULT_PHI},
    # )
    _save_sensitivity_summary(
        theta_results,
        sweep_key="theta",
        plot_filename="plot/theta_vs_c_ele.png",
        excel_filename="plot/sensitivity_theta.xlsx",
        title="Impact of RE Generation Ratio on Unit Electricity Cost",
        xlabel="Min RE Generation to Load Ratio (θ)",
        marker="^-",
        color="#F18F01",
    )
    
    print("\n" + "="*60)
    print(" All sensitivity analysis plots and data exported!")
    print("="*60)

def run_single_optimization(D=None, phi=None, theta=None, mip_gap=SENSITIVITY_MIP_GAP, output_dir=None):
    """
    Run single optimization and return key results.
    Used for sensitivity analysis.

    D, phi, theta: optional overrides (defaults from params module).
    mip_gap: Gurobi MIP optimality gap tolerance (stopping criterion).
    output_dir: if set, save optimization_results.txt and timeseries_results.csv.
    """
    D_val = p.D if D is None else D
    phi_val = p.phi if phi is None else phi
    theta_val = p.theta if theta is None else theta

    try:
        # Create model
        model = gp.Model("GreenPowerMicrogrid")
        model.setParam('OutputFlag', 0)      # Suppress output
        model.setParam('MIPGap', mip_gap)
        # model.setParam('TimeLimit', 300)     # 5 min limit for sensitivity analysis
        model.setParam('Method', 3)          # Concurrent method
        model.setParam('Heuristics', 0.5)    # More heuristics
        
        # Variables
        x_WT = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="x_WT")
        x_PV = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="x_PV")
        x_ST = model.addVar(lb=0, vtype=GRB.CONTINUOUS, name="x_ST")
        x_GD = model.addVar(lb=30,ub=30, vtype=GRB.CONTINUOUS, name="x_GD")
        
        p_WT = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_WT")
        p_PV = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_PV")
        p_ST_C = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_ST_C")
        p_ST_D = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_ST_D")
        p_GD = model.addVars(p.T, lb=0, vtype=GRB.CONTINUOUS, name="p_GD")
        p_GD_U = model.addVars(p.T, lb=0,ub=0, vtype=GRB.CONTINUOUS, name="p_GD_U")
        
        E = model.addVars(p.T + 1, lb=0, vtype=GRB.CONTINUOUS, name="E")
        
        z1 = model.addVars(p.T, vtype=GRB.BINARY, name="z1")
        z2 = model.addVars(p.T, vtype=GRB.BINARY, name="z2")
        y1 = model.addVars(p.T, vtype=GRB.BINARY, name="y1")
        y2 = model.addVars(p.T, vtype=GRB.BINARY, name="y2")
        
        # Objective
        cost_investment = p.CRF * (p.lambda_WT * x_WT + p.lambda_PV * x_PV + p.lambda_ST * x_ST + p.lambda_GD * x_GD)
        cost_grid_fixed = p.M * (p.mu_DC * x_GD + 730 * p.mu_ELE * x_GD * p.L_bar)
        cost_connection = p.nu * D_val
        revenue_market = gp.quicksum(p.mu_MKT_t[t] * p_GD_U[t] for t in range(p.T))
        
        J = cost_investment + cost_grid_fixed + cost_connection - revenue_market
        model.setObjective(J, GRB.MINIMIZE)
        
        # Constraints
        model.addConstr(x_WT + x_PV + x_ST + x_GD >= p.L, name="c_cap_balance")
        model.addConstrs((p_WT[t] + p_PV[t] - p_ST_C[t] + p_ST_D[t] + p_GD[t] - p_GD_U[t] == p.load_t[t] 
                          for t in range(p.T)), name="c_power_balance")
        
        model.addConstrs((p_WT[t] <= p.alpha_WT_t[t] * x_WT for t in range(p.T)), name="c_wt_max")
        model.addConstrs((p_PV[t] <= p.alpha_PV_t[t] * x_PV for t in range(p.T)), name="c_pv_max")
        
        model.addConstrs((E[t] >= p.SOC_min * x_ST for t in range(p.T + 1)), name="c_soc_min")
        model.addConstrs((E[t] <= p.SOC_max * x_ST for t in range(p.T + 1)), name="c_soc_max")
        
        model.addConstr(E[0] == p.SOC_init * x_ST, name="c_E_init")
        model.addConstr(E[p.T] >= p.SOC_init * x_ST, name="c_E_final")
        
        model.addConstrs((E[t+1] == E[t] + (p.eta_ch * p_ST_C[t] - p_ST_D[t] / p.eta_dis) * p.delta
                          for t in range(p.T)), name="c_E_trans")
        
        model.addConstrs((p_ST_C[t] <= p.P_ST_MAX_C * z1[t] for t in range(p.T)), name="c_st_c_max")
        model.addConstrs((p_ST_D[t] <= p.P_ST_MAX_D * z2[t] for t in range(p.T)), name="c_st_d_max")
        model.addConstrs((z1[t] + z2[t] == 1 for t in range(p.T)), name="c_st_mut_excl")
        
        model.addConstrs((p_GD[t] <= x_GD * y1[t] for t in range(p.T)), name="c_gd_buy_max")
        model.addConstrs((p_GD_U[t] <= x_GD * y2[t] for t in range(p.T)), name="c_gd_sell_max")
        model.addConstrs((y1[t] + y2[t] <= 1 for t in range(p.T)), name="c_gd_mut_excl")
        
        sum_gd_u = gp.quicksum(p_GD_U[t] * p.delta for t in range(p.T))
        sum_re = gp.quicksum((p_WT[t] + p_PV[t]) * p.delta for t in range(p.T))
        
        model.addConstr(sum_gd_u <= p.psi * sum_re, name="c_grid_prop")
        model.addConstr(sum_re - sum_gd_u >= phi_val * sum_re, name="c_re_prop1")
        sum_load = gp.quicksum(p.load_t[t] * p.delta for t in range(p.T))
        model.addConstr(sum_re >= theta_val * sum_load, name="c_re_prop2")
        
        # Optimize
        model.optimize()
        
        if model.SolCount > 0:
            mip_gap_achieved = model.MIPGap
            # Real (un-annualized) cost breakdown
            N = p.project_life  # project lifetime in years
            c_inv = p.lambda_WT * x_WT.X + p.lambda_PV * x_PV.X + p.lambda_ST * x_ST.X + p.lambda_GD * x_GD.X
            c_conn = p.nu * D_val
            c_grid = p.M * (p.mu_DC * x_GD.X + 730 * p.mu_ELE * x_GD.X * p.L_bar)
            rev_mkt = sum(p.mu_MKT_t[t] * p_GD_U[t].X for t in range(p.T))
            total_load = sum(p.load_t[t] for t in range(p.T))
            # LCOE = lifetime total net cost / lifetime total energy; ×10 converts 万元/MWh -> 元/kWh
            c_ele = ((c_inv + c_conn) + N * (c_grid - rev_mkt)) / (N * total_load) * 10 if total_load > 0 else 0

            if output_dir is not None:
                _save_sensitivity_case_files(
                    output_dir,
                    D_val=D_val,
                    phi_val=phi_val,
                    theta_val=theta_val,
                    mip_gap_target=mip_gap,
                    mip_gap_achieved=mip_gap_achieved,
                    status=model.Status,
                    obj_val=model.ObjVal,
                    x_WT=x_WT,
                    x_PV=x_PV,
                    x_ST=x_ST,
                    x_GD=x_GD,
                    p_WT=p_WT,
                    p_PV=p_PV,
                    p_ST_C=p_ST_C,
                    p_ST_D=p_ST_D,
                    p_GD=p_GD,
                    p_GD_U=p_GD_U,
                    E=E,
                    c_inv=c_inv,
                    c_conn=c_conn,
                    c_grid=c_grid,
                    rev_mkt=rev_mkt,
                    c_ele=c_ele,
                )
            
            return {
                'D': D_val,
                'phi': phi_val,
                'theta': theta_val,
                'c_ele': c_ele,
                'c_inv': c_inv,           # 设备投资总额(一次性,万元)
                'c_grid': c_grid,         # 年电网费(万元/年)
                'c_conn': c_conn,         # 直连建设费(一次性,万元)
                'rev_mkt': rev_mkt,       # 年市场收益(万元/年)
                'obj': model.ObjVal,
                'mip_gap_target': mip_gap,
                'mip_gap_achieved': mip_gap_achieved,
                'status': model.Status,
                'x_WT': x_WT.X,
                'x_PV': x_PV.X,
                'x_ST': x_ST.X,
                'x_GD': x_GD.X,
                'output_dir': output_dir,
            }
    except Exception as e:
        print(f"   Error in optimization: {e}")
        return None

def _run_optimization_job(X_GD_bound):
    output_dir = os.path.join("results", f"x_gd_{X_GD_bound}")
    run_optimization(X_GD_bound, output_dir=output_dir)
    return X_GD_bound


if __name__ == "__main__":
    # from concurrent.futures import ProcessPoolExecutor, as_completed

    # X_GD_bounds = list(range(35, 40, 5))
    # # Parallel: each job uses its own Gurobi model and output directory.
    # # Set PARALLEL=False to run sequentially (writes to results/x_gd_<bound>/ either way).
    # PARALLEL = True

    # if PARALLEL and len(X_GD_bounds) > 1:
    #     max_workers = min(len(X_GD_bounds), os.cpu_count() or 1)
    #     print(f"Running {len(X_GD_bounds)} optimizations in parallel (max_workers={max_workers})...")
    #     with ProcessPoolExecutor(max_workers=max_workers) as executor:
    #         futures = {executor.submit(_run_optimization_job, b): b for b in X_GD_bounds}
    #         for future in as_completed(futures):
    #             bound = futures[future]
    #             try:
    #                 future.result()
    #                 print(f"[done] X_GD_bound={bound}")
    #             except Exception as exc:
    #                 print(f"[failed] X_GD_bound={bound}: {exc}")
    # else:
    #     for X_GD_bound in X_GD_bounds:
    #         _run_optimization_job(X_GD_bound)
    # run_optimization(0)
    run_sensitivity_analysis()
