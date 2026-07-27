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
lambda_WT = 800.0     # Wind turbine unit price (万元/MW)
lambda_PV = 300.0     # PV panel unit price (万元/MW)
lambda_ST = 80.0      # Energy storage unit price (万元/MWh)
lambda_GD = 12.0      # Grid transformer unit price (万元/MW)

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
# 5. Design Load
# ============================================================
L = 50.0             # Maximum / designed computing load (MW)

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
# 8. Time-Series Data (8760h) — SYNTHETIC PLACEHOLDERS
# ============================================================
# Users should replace these with real data arrays of length T.

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


def generate_synthetic_data(T):
    """
    Load real PV/WT coefficients from data/pvwatts_hourly.csv (Yinchuan).
    Returns raw α series and actual Θ values computed from data.
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
    wind_speed = raw[:, 6]
    ac_output = raw[:, 11]

    # PV capacity factor: AC output per 1 kW DC → MW/MW (0–1), raw, no normalization
    alpha_PV_t = ac_output / 1000.0
    alpha_PV_t = np.clip(alpha_PV_t, 0.0, 1.0)

    # Wind capacity factor from wind speed via power curve, raw
    alpha_WT_t = _wind_power_curve(wind_speed)

    # Actual Θ from data (used in policy constraints)
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

    return load_t, alpha_WT_t, alpha_PV_t, mu_ES_t, mu_PV_t, mu_WT_t, mu_EB_t, theta_pv_actual, theta_wt_actual


# Generate and export — use actual Θ from real data
load_t, alpha_WT_t, alpha_PV_t, mu_ES_t, mu_PV_t, mu_WT_t, mu_EB_t, _theta_pv, _theta_wt = generate_synthetic_data(T)
# Override Θ with real data values (so policy constraints match actual α series)
Theta_PV = _theta_pv
Theta_WT = _theta_wt
mu_MKT_t = mu_ES_t  # backward-compatible alias
mu_EO_t = np.full(T, mu_EO)
mu_EL_t = np.full(T, mu_EL)
mu_EG_t = np.full(T, mu_EG)

# Consistency check: Θ should match Σ α Δ after normalization
_Theta_PV_from_alpha = float(np.sum(alpha_PV_t * delta))
_Theta_WT_from_alpha = float(np.sum(alpha_WT_t * delta))
print(
    f"[params] Θ_PV={Theta_PV:.1f} h (from PVWatts AC output), "
    f"Θ_WT={Theta_WT:.1f} h (from wind speed→power curve)"
)

# MILP relaxation of Word's strict inequality 0 < E_{t+1}
E_eps = 1e-4
