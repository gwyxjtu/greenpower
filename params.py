"""
Green Power Microgrid Capacity Planning - Parameter Configuration
=================================================================
All input parameters for the optimization model are defined here.
Time-series data (load, wind/PV coefficients, electricity prices)
are generated as synthetic placeholders. Replace with real data.
"""

import os
import numpy as np



# ============================================================
# 1. Time Parameters
# ============================================================
T = 8760          # Total time steps (hours in a year)
delta = 1.0       # Duration of each time step (hours)

# ============================================================
# 2. Equipment Unit Prices (万元/MW or 万元/MWh)
# ============================================================
lambda_WT = 410.0     # Wind turbine unit price (万元/MW) = 4100 元/kW (水电总院2025全国均价)
lambda_PV = 300.0     # PV panel unit price (万元/MW)
lambda_ST = 80.0      # Energy storage unit price (万元/MWh)
lambda_GD = 12.0      # Grid transformer unit price (万元/MW)

# Engineering capacity caps (keep the MILP bounded for the open-source solver)
X_WT_MAX = 500.0      # MW
X_ST_MAX = 2000.0     # MWh
X_GD_MAX = 200.0      # MW；--x-gd 0 时的决策上界

# ============================================================
# 3. Electricity Price Parameters
# ------------------------------------------------------------
# 单位约定（与模型一致）：
#   电量类: 万元/MWh  ≡  0.1 × (元/kWh)
#   容量类: 万元/MW/月 ≡ 0.1 × (元/kW/月)
# 场景锚定：宁夏 / 110kV 两部制工商业（交底书算例为宁夏中卫）
# ============================================================

# μ^{DC}: 容(需)量电价。宁夏第三监管周期 110kV 需量电价 25.6 元/kW·月
# 来源：宁发改价格〔2023〕314号 / 第三监管周期宁夏电网输配电价表
mu_DC = 2.56          # 万元/MW/month

# μ^{ED}: 电度输配电价。宁夏 110kV 两部制 0.0600 元/kWh
# 来源：同上
mu_ED = 0.0060        # 万元/MWh  (= 0.060 元/kWh)

# μ^{EO}: 系统运行费折价（辅助服务、煤电/抽蓄容量电费等分摊，月度浮动）
# 东部省份常见约 0.02–0.04 元/kWh；西部相对偏低，取中位偏低
# 参考：各省电网企业代理购电月度公告（如皖/苏约 0.02–0.038）
mu_EO = 0.0039        # 万元/MWh  (= 0.039 元/kWh)

# μ^{EL}: 上网环节线损电价 ≈ 上网电价 × 综合线损率
# 宁夏综合线损率 2.59%（第三监管周期）；取购电价≈0.35 元/kWh → ≈0.009 元/kWh
# 来源：宁夏输配电价表注（线损率 2.59%）
mu_EL = 0.00071        # 万元/MWh  (= 0.009 元/kWh)

# μ^{EG}: 政府性基金及附加
# 宁夏：重大水利 0.1125 分 + 移民扶持 0.12 分 + 可再生附加 1.9 分 ≈ 0.0213 元/kWh
# 来源：宁夏第三监管周期输配电价表注释；全国可再生附加多为 1.9 分/kWh
mu_EG = 0.00213       # 万元/MWh  (= 0.0213 元/kWh)

# μ^{EB}: 电力市场/代理购电电能量价格（不含输配、基金等，后者已分项）
# 西部代理购电常见约 0.30–0.40 元/kWh，取 0.35
mu_EB = 0.05          # 万元/MWh  (= 0.5 元/kWh)

# μ^{PV}/μ^{WT}: 风光自发自用内部转移价，按电力市场 PPA/长协（机制电价）参考
# 宁夏 2025–2026 新能源机制电价竞价出清 0.2595 元/kWh（=燃煤标杆上限）
# 来源：宁夏发改委机制电价竞价结果公示；须严格小于 μ^{EB}（相对电网购电有价差）
mu_PV = 0.02595       # 万元/MWh  (= 0.2595 元/kWh)
mu_WT = 0.02595       # 万元/MWh  (= 0.2595 元/kWh)
assert mu_PV < mu_EB and mu_WT < mu_EB, "内部转移价 μ^{PV}/μ^{WT} 必须小于购电价 μ^{EB}"

# μ^{TL}: 绿电直连专线单位造价
# 行业公开口径约 100 万元/km（含线路；升压站另计）
# 来源：经济观察网等绿电直连成本访谈（2025）
mu_TL = 100.0         # 万元/km

# Backward-compatible aliases
mu_ELE = mu_ED
mu_BUY = mu_EB
nu = mu_TL

# ============================================================
# 4. Economic Parameters
# ============================================================
discount_rate = 0.08  # Annual discount rate
project_life = 15     # Project lifetime (years)

# Calculate Capital Recovery Factor (CRF) = R in the disclosure doc
# CRF = r * (1 + r)^n / ((1 + r)^n - 1)
def calculate_crf(discount_rate, project_life):
    """Calculate Capital Recovery Factor for annualizing investment costs."""
    r = discount_rate
    n = project_life
    crf = (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    return crf

CRF = calculate_crf(discount_rate, project_life)  # R: 年均投资折算系数
R = CRF

M = 12                # Months per year
# \bar{L}: 110kV 及以上工商业平均负荷率（就近消纳/绿电直连容量电费公式）
# 各省按上一年样本测算后公布；暂无公开精确值时取 0.6 作为工程常用假定
L_bar = 0.6
D = 50.0              # 专线距离 (km)

# ============================================================
# 5. Design Load & PV Land-Use Limit
# ============================================================
L = 50.0             # Maximum / designed computing load (MW)

# A(x^{PV}) ≤ S^{PV,MAX}: 占地面积约束
# 估算：1.1 MW ≈ 12 亩 → a_PV = 12/1.1 亩/MW
# 项目可用光伏用地最大 1 km² = 1500 亩 → x_PV ≤ 1500 × 1.1/12 = 137.5 MW
a_PV = 12.0 / 1.1    # 亩/MW
S_PV_MAX = 1500.0    # 亩 (= 1 km²)

# ============================================================
# 6. Energy Storage Parameters
# ============================================================
eta_ch  = 0.95        # Charging efficiency ψ^{ST,C}
eta_dis = 0.95        # Discharging efficiency ψ^{ST,D}
E_init  = 0.0         # Initial stored energy E_0^{ST} = E (MWh)
P_ST_MAX_C = 50.0     # Maximum charging power P^{ST,C,MAX} (MW)
P_ST_MAX_D = 50.0     # Maximum discharging power P^{ST,D,MAX} (MW)

# ============================================================
# 7. Policy Parameters
# ============================================================
# Θ: 年等效利用小时数 (h)。合成 α 将按此目标归一：Σ α_t Δ = Θ
# 来源：宁夏典型年——光伏约 1500h、风电约 2000h（国家能源局“塞上绿电”）
Theta_PV = 1500.0
Theta_WT = 1800.0

phi   = 0.6           # φ: 自发自用 / 可用发电量 下限 (15)；政策常用 ≥60%
psi   = 0.20          # α: 余电上网 / 可用发电量 上限 (17)
theta = 0.30          # β: 新能源发电量 / 用电量 下限 (16)


# ============================================================
# 8. Time-Series Data (8760 h)
# ============================================================
# Load: synthetic diurnal + seasonal profile scaled to design load L.
# PV:   PVWatts hourly AC (Yinchuan) in data/pvwatts_hourly.csv.
# Wind: same file's 10 m wind → hub-height shear → calibrated to Theta_WT.

def _normalize_cf_to_hours(alpha, target_hours, delta):
    """Scale capacity-factor series so Σ α·Δ = target_hours, keep α ∈ [0, 1]."""
    alpha = np.asarray(alpha, dtype=float)
    s = float(np.sum(alpha * delta))
    if s <= 1e-12:
        raise ValueError("capacity factor series sums to ~0; cannot normalize")
    scaled = alpha * (target_hours / s)
    # If scaling pushes above 1, clip and re-scale once on the unclipped mass if needed
    if scaled.max() > 1.0 + 1e-12:
        scaled = np.clip(scaled, 0.0, 1.0)
        s2 = float(np.sum(scaled * delta))
        if s2 < target_hours - 1e-6:
            raise ValueError(
                f"cannot reach {target_hours} h after clipping to [0,1] (got {s2:.1f} h); "
                "relax shape or lower target"
            )
        scaled = scaled * (target_hours / s2)
        scaled = np.clip(scaled, 0.0, 1.0)
    return scaled


def _wind_power_curve(v):
    """Simplified wind power curve: v→capacity factor (0–1)."""
    v_cut_in, v_rated, v_cut_out = 3.0, 12.0, 25.0
    v = np.asarray(v, dtype=float)
    cf = np.zeros_like(v)
    mid = (v >= v_cut_in) & (v < v_rated)
    cf[mid] = ((v[mid] - v_cut_in) / (v_rated - v_cut_in)) ** 3
    cf[(v >= v_rated) & (v <= v_cut_out)] = 1.0
    return cf


def _hub_height_wind(v_ref, h_ref=10.0, h_hub=100.0, shear_exp=0.14):
    """Extrapolate near-surface wind to hub height (power-law shear)."""
    return np.asarray(v_ref, dtype=float) * (h_hub / h_ref) ** shear_exp


def _calibrate_wind_cf(v_hub, target_hours, delta=1.0):
    """
    Scale hub-height wind so annual equivalent hours ≈ target_hours.
    Preserves the temporal shape; only adjusts overall intensity.
    Ningxia onshore wind farms typically ~1800–2000 h (mean hub wind ~6–7 m/s).
    """
    v_hub = np.asarray(v_hub, dtype=float)

    def hours_at(scale):
        return float(np.sum(_wind_power_curve(v_hub * scale) * delta))

    # If already at/above target with scale=1, just use raw (optionally soft-normalize)
    h0 = hours_at(1.0)
    if h0 >= target_hours - 1e-6:
        return _normalize_cf_to_hours(_wind_power_curve(v_hub), target_hours, delta), 1.0, h0

    # Binary search speed scale so Θ ≈ target
    lo, hi = 1.0, 4.0
    if hours_at(hi) < target_hours:
        raise ValueError(
            f"cannot reach Θ_WT={target_hours} h even at {hi}× hub wind "
            f"(got {hours_at(hi):.0f} h; mean hub wind={v_hub.mean():.2f} m/s)"
        )
    for _ in range(40):
        mid = 0.5 * (lo + hi)
        if hours_at(mid) < target_hours:
            lo = mid
        else:
            hi = mid
    scale = 0.5 * (lo + hi)
    cf = _wind_power_curve(v_hub * scale)
    return cf, scale, hours_at(scale)


def generate_synthetic_data(T):
    """
    Load PV from data/pvwatts_hourly.csv (Yinchuan AC output).
    Wind: same file's near-surface wind → hub-height shear → calibrate to Θ_WT.
    """
    hours = np.arange(T)
    hour_of_day = hours % 24
    day_of_year = hours // 24

    # --- Load profile (MW) ---
    base_load = L * 0.7
    daily_variation = L * 0.2 * np.sin(np.pi * (hour_of_day - 6) / 16)
    daily_variation = np.clip(daily_variation, 0, None)
    seasonal_variation = L * 0.05 * np.sin(2 * np.pi * day_of_year / 365)
    load_t = base_load + daily_variation + seasonal_variation
    load_t = np.clip(load_t, L * 0.5, L)

    # --- Real PV and wind data from PVWatts CSV (Yinchuan) ---
    csv_path = os.path.join(os.path.dirname(__file__), "data", "pvwatts_hourly.csv")
    import csv
    with open(csv_path, "r", encoding="utf-8") as f:
        for _ in range(32):
            next(f)
        reader = csv.reader(f)
        rows = []
        for row in reader:
            if not row:
                continue
            rows.append([float(v) for v in row])
    raw = np.array(rows)
    wind_speed_10m = raw[:, 6]
    ac_output = raw[:, 11]

    # PV capacity factor: AC output per 1 kW DC → MW/MW (0–1)
    alpha_PV_t = np.clip(ac_output / 1000.0, 0.0, 1.0)

    # Wind: 10 m AGL (PVWatts) is far too weak for utility turbines.
    # Extrapolate to 100 m hub height, then calibrate intensity to Θ_WT (宁夏典型 ~1800 h).
    v_hub = _hub_height_wind(wind_speed_10m, h_ref=10.0, h_hub=100.0, shear_exp=0.14)
    alpha_WT_t, wind_scale, theta_wt_raw = _calibrate_wind_cf(v_hub, Theta_WT, delta)
    alpha_WT_t = np.clip(alpha_WT_t, 0.0, 1.0)

    theta_pv_actual = float(np.sum(alpha_PV_t * delta))
    theta_wt_actual = float(np.sum(alpha_WT_t * delta))

    # --- Price time series (万元/MWh) ---
    mu_PV_t = np.full(T, mu_PV)
    mu_WT_t = np.full(T, mu_WT)
    mu_EB_t = np.full(T, mu_EB)

    # Market / on-grid sell price μ^{ES}: peak / flat / valley
    mu_ES_t = np.full(T, 0.035)  # flat
    peak_hours = (hour_of_day >= 8) & (hour_of_day < 12) | \
                 (hour_of_day >= 17) & (hour_of_day < 21)
    valley_hours = (hour_of_day >= 23) | (hour_of_day < 7)
    mu_ES_t[peak_hours] = 0.045
    mu_ES_t[valley_hours] = 0.025

    return (
        load_t, alpha_WT_t, alpha_PV_t, mu_ES_t, mu_PV_t, mu_WT_t, mu_EB_t,
        theta_pv_actual, theta_wt_actual, float(v_hub.mean()), wind_scale,
    )


# Generate and export
(
    load_t, alpha_WT_t, alpha_PV_t, mu_ES_t, mu_PV_t, mu_WT_t, mu_EB_t,
    _theta_pv, _theta_wt, _v_hub_mean, _wind_scale,
) = generate_synthetic_data(T)
# PV Θ from measured AC; WT Θ from calibrated series (≈ target Theta_WT)
Theta_PV = _theta_pv
Theta_WT = _theta_wt
mu_MKT_t = mu_ES_t  # backward-compatible alias
mu_EO_t = np.full(T, mu_EO)
mu_EL_t = np.full(T, mu_EL)
mu_EG_t = np.full(T, mu_EG)

print(
    f"[params] Θ_PV={Theta_PV:.1f} h (PVWatts AC), "
    f"Θ_WT={Theta_WT:.1f} h (hub-height shear + scale×{_wind_scale:.2f}, "
    f"v_hub_mean_raw={_v_hub_mean:.2f} m/s → {_v_hub_mean*_wind_scale:.2f} m/s)"
)

# MILP relaxation of Word's strict inequality 0 < E_{t+1}
E_eps = 1e-4
