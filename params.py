"""
Green Power Microgrid Capacity Planning - Parameter Configuration
=================================================================
All input parameters for the optimization model are defined here.
Time-series data (load, wind/PV coefficients, electricity prices)
are generated as synthetic placeholders. Replace with real data.
"""

import numpy as np

# ============================================================
# 1. Time Parameters
# ============================================================
T = 8760          # Total time steps (hours in a year)
delta = 1.0       # Duration of each time step (hours)

# ============================================================
# 2. Equipment Unit Prices (万元/MW or 万元/MWh)
# ============================================================
lambda_WT = 600.0     # Wind turbine unit price (万元/MW)
lambda_PV = 300.0     # PV panel unit price (万元/MW)
lambda_ST = 50.0     # Energy storage unit price (万元/MWh)
lambda_GD = 12.0      # Grid transformer unit price (万元/MW)

# ============================================================
# 3. Electricity Price Parameters
# ============================================================
mu_DC  = 3.0         # Monthly demand charge (万元/MW/month)
mu_ELE = 0.05         # Electricity unit price (万元/MWh)

# ============================================================
# 4. Economic Parameters
# ============================================================
discount_rate = 0.08  # Annual discount rate (%)
project_life = 25     # Project lifetime (years)

# Calculate Capital Recovery Factor (CRF)
# CRF = r * (1 + r)^n / ((1 + r)^n - 1)
def calculate_crf(discount_rate, project_life):
    """Calculate Capital Recovery Factor for annualizing investment costs."""
    r = discount_rate
    n = project_life
    crf = (r * (1 + r) ** n) / ((1 + r) ** n - 1)
    return crf

CRF = calculate_crf(discount_rate, project_life)  # Capital Recovery Factor

M = 12                # Months per year
L_bar = 0.6           # Provincial average load coefficient
nu = 100.0             # Unit price on direct power connection (万元/km)
D = 50.0              # Distance of direct power connection (km)                           # plot D-c_ele, D scales from 10-80 (10km stepsize)

# ============================================================
# 5. Design Load
# ============================================================
L = 50.0             # Maximum / designed computing load (MW)

# ============================================================
# 6. Energy Storage Parameters
# ============================================================
eta_ch  = 0.95        # Charging efficiency
eta_dis = 0.95        # Discharging efficiency
SOC_min = 0.1         # Minimum SOC
SOC_max = 0.9         # Maximum SOC
SOC_init = 0.5        # Initial SOC at t=0
P_ST_MAX_C = 50.0     # Maximum charging power (MW)
P_ST_MAX_D = 50.0     # Maximum discharging power (MW)

# ============================================================
# 7. Policy Parameters
# ============================================================
psi   = 0.2           # Max ratio of on-grid electricity to total RE generation
phi   = 0.6           # Min RE self-consumption ratio                                              # plot phi-c_ele, phi scales from 0.1-0.9 (0.1 stepsize)
theta = 0.3           # Min ratio of total RE generation to load                             # plot theta-c_ele, phi scales from 0.1-0.9 (0.1 stepsize)


# ============================================================
# 8. Time-Series Data (8760h) — SYNTHETIC PLACEHOLDERS
# ============================================================
# Users should replace these with real data arrays of length T.

def generate_synthetic_data(T):
    """
    Generate synthetic time-series data for testing.
    Returns: load_t, alpha_WT_t, alpha_PV_t, mu_MKT_t
    """
    hours = np.arange(T)
    hour_of_day = hours % 24
    day_of_year = hours // 24

    # --- Load profile (MW) ---
    # Base load + daily pattern (higher during daytime)
    base_load = L * 0.7
    daily_variation = L * 0.2 * np.sin(np.pi * (hour_of_day - 6) / 16)
    daily_variation = np.clip(daily_variation, 0, None)
    seasonal_variation = L * 0.05 * np.sin(2 * np.pi * day_of_year / 365)
    load_t = base_load + daily_variation + seasonal_variation
    load_t = np.clip(load_t, L * 0.5, L)

    # --- Wind power output coefficient (0~1) ---
    # Wind tends to be stronger at night and in winter
    wind_base = 0.25
    wind_diurnal = 0.1 * np.cos(2 * np.pi * hour_of_day / 24)
    wind_seasonal = 0.1 * np.cos(2 * np.pi * day_of_year / 365)
    wind_noise = 0.1 * np.random.RandomState(42).randn(T)
    alpha_WT_t = wind_base + wind_diurnal + wind_seasonal + wind_noise
    alpha_WT_t = np.clip(alpha_WT_t, 0.0, 1.0)

    # --- PV output coefficient (0~1) ---
    # Solar follows daylight pattern, stronger in summer
    solar_envelope = np.maximum(0, np.sin(np.pi * (hour_of_day - 6) / 12))
    solar_envelope[hour_of_day < 6] = 0.0
    solar_envelope[hour_of_day >= 18] = 0.0
    solar_seasonal = 0.8 + 0.2 * np.sin(2 * np.pi * (day_of_year - 80) / 365)
    solar_noise = 0.05 * np.random.RandomState(123).rand(T)
    alpha_PV_t = solar_envelope * solar_seasonal - solar_noise
    alpha_PV_t = np.clip(alpha_PV_t, 0.0, 1.0)

    # --- Market electricity price (万元/MWh) ---
    # Time-of-use pricing: peak / flat / valley
    mu_MKT_t = np.full(T, 0.05)  # flat
    peak_hours = (hour_of_day >= 8) & (hour_of_day < 12) | \
                 (hour_of_day >= 17) & (hour_of_day < 21)
    valley_hours = (hour_of_day >= 23) | (hour_of_day < 7)
    mu_MKT_t[peak_hours] = 0.08
    mu_MKT_t[valley_hours] = 0.03

    return load_t, alpha_WT_t, alpha_PV_t, mu_MKT_t


# Generate and export
load_t, alpha_WT_t, alpha_PV_t, mu_MKT_t = generate_synthetic_data(T)
