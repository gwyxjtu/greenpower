"""
Pin capacities / R / storage power in-memory (params.py untouched).

Call ``prepare_process()`` in every ProcessPool worker before solving.
"""
import os
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

# Named plants used in this repo. Capacities in MW / MWh.
PRESETS = {
    "mu0_gd60": {
        "desc": "μ=0, x_GD=60 最优厂（容量曾自由优化）",
        "x_WT": 43.12,
        "x_PV": 137.50,
        "x_ST": 218.93,
        "x_GD": 60.0,
        "P_ST_MAX": None,  # keep params.py (50 MW)
        "results_dir": "results/x_gd_60_R0_fixed_mu0plant",
        "plot_stub": "pv137.5_wt43.12_st218.93_gd60",
    },
    "pv100_wt100_st160": {
        "desc": "示意厂 PV=WT=100, ST=160, 充放 40 MW",
        "x_WT": 100.0,
        "x_PV": 100.0,
        "x_ST": 160.0,
        "x_GD": 60.0,
        "P_ST_MAX": 40.0,
        "results_dir": "results/standalone_pv100_wt100_st160_gd60_R0",
        "plot_stub": "pv100_wt100_st160_gd60",
    },
}


def ensure_root_on_path():
    os.chdir(ROOT)
    if ROOT not in sys.path:
        sys.path.insert(0, ROOT)


def capacities_of(preset_or_cap):
    if isinstance(preset_or_cap, str):
        if preset_or_cap not in PRESETS:
            raise KeyError(f"unknown preset {preset_or_cap!r}; choose {list(PRESETS)}")
        cfg = PRESETS[preset_or_cap]
        return {
            "x_WT": cfg["x_WT"],
            "x_PV": cfg["x_PV"],
            "x_ST": cfg["x_ST"],
            "x_GD": cfg["x_GD"],
        }
    return dict(preset_or_cap)


def prepare_process(fixed_cap, r0=False, p_st_max=None):
    """
    In this process: chdir, optionally set R=0 / P_ST_MAX, pin x_WT/PV/ST/GD via addVar.
    Import green_power_opt only after this returns.
    """
    ensure_root_on_path()
    import gurobipy as gp
    import params as p

    if r0:
        p.R = 0.0
        p.CRF = 0.0
    if p_st_max is not None:
        p.P_ST_MAX_C = float(p_st_max)
        p.P_ST_MAX_D = float(p_st_max)

    cap = capacities_of(fixed_cap)
    orig_addVar = gp.Model.addVar

    def addVar_fixed(self, *args, **kwargs):
        name = kwargs.get("name")
        if name in cap:
            kwargs["lb"] = cap[name]
            kwargs["ub"] = cap[name]
        return orig_addVar(self, *args, **kwargs)

    gp.Model.addVar = addVar_fixed
    return cap, p


def solve_pinned(
    fixed_cap,
    *,
    r0=False,
    p_st_max=None,
    mu_re_yuan=None,
    phi=0.6,
    theta=0.3,
    D=50.0,
    mip_gap=0.01,
    output_dir=None,
):
    """One MILP. mu_re_yuan is 元/kWh (None = params.py)."""
    cap, _p = prepare_process(fixed_cap, r0=r0, p_st_max=p_st_max)
    from green_power_opt import run_single_optimization

    mu_wan = None if mu_re_yuan is None else float(mu_re_yuan) * 0.1
    x_gd = cap["x_GD"]
    r = run_single_optimization(
        D=D,
        phi=phi,
        theta=theta,
        mip_gap=mip_gap,
        mu_re=mu_wan,
        x_GD_bound=x_gd,
        output_dir=output_dir,
    )
    if r is not None and mu_re_yuan is not None:
        r["mu_re"] = float(mu_re_yuan)
    return r
