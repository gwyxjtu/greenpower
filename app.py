"""绿电直连数据中心能源系统容量规划平台。"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import auth
import solver_service as svc
from timeseries_io import SeriesFormatError, parse_series, summarize, write_template_csv

ROOT = Path(__file__).resolve().parent
BALANCE_TOL_MW = 0.05

INVEST_LOAD = "电源和专线由负荷投资"
INVEST_GENCO = "电源和专线由发电企业投资"
MODE_MANUAL = "手动输入"
MODE_OPTIMIZE = "由模型优化容量"
SRC_DEFAULT = "使用默认"
SRC_UPLOAD = "上传"

DEFAULTS = {
    "x_gd_mode": MODE_MANUAL,
    "x_gd": 60.0,
    "mu_PV_yuan": 0.0,
    "mu_WT_yuan": 0.0,
    "invest_mode": INVEST_LOAD,
    "crf_r": 0.1168,
    "phi": 60.0,
    "theta": 30.0,
    "psi": 20.0,
    "mip_gap": 0.01,
    "time_limit": 600.0,
    "L": 50.0,
    "lambda_WT": 410.0,
    "lambda_PV": 300.0,
    "lambda_ST": 80.0,
    "lambda_GD": 0.0,
    "mu_TL": 100.0,
    "D": 50.0,
    "a_PV": 12.0 / 1.1,
    "S_PV_MAX": 1500.0,
    "X_WT_MAX": 500.0,
    "X_ST_MAX": 2000.0,
    "X_GD_MAX": 200.0,
    "mu_DC_yuan": 25.6,
    "mu_ED_yuan": 0.060,
    "mu_EO_yuan": 0.039,
    "mu_EL_yuan": 0.0071,
    "mu_EG_yuan": 0.0213,
    "mu_EB_yuan": 0.50,
    "mu_ES_peak_yuan": 0.45,
    "mu_ES_flat_yuan": 0.35,
    "mu_ES_valley_yuan": 0.25,
    "L_bar": 0.6,
    "M": 12.0,
    "discount_rate_pct": 8.0,
    "project_life": 15,
    "Theta_PV_TARGET": 1500.0,
    "Theta_WT_TARGET": 1800.0,
    "normalize_pv": False,
    "eta_ch": 0.95,
    "eta_dis": 0.95,
    "E_init": 0.0,
    "P_ST_MAX_C": 50.0,
    "P_ST_MAX_D": 50.0,
    "scale_load_to_L": False,
    "upload_nonce": 0,
    "load_src": SRC_DEFAULT,
    "pv_src": SRC_DEFAULT,
    "wt_src": SRC_DEFAULT,
}


def _init_state():
    migrate_genco = "invest_mode" not in st.session_state and bool(st.session_state.get("r0"))
    for key, value in DEFAULTS.items():
        if key not in st.session_state:
            st.session_state[key] = value
    if migrate_genco:
        st.session_state.invest_mode = INVEST_GENCO
    mode = st.session_state.get("x_gd_mode")
    if mode in ("固定容量", "固定为填写容量"):
        st.session_state.x_gd_mode = MODE_MANUAL
    elif mode == "自由决策":
        st.session_state.x_gd_mode = MODE_OPTIMIZE
    for key in ("phi", "theta", "psi"):
        if float(st.session_state.get(key, 0)) <= 1.0:
            st.session_state[key] = float(st.session_state[key]) * 100.0


def _on_invest_mode_change():
    if st.session_state.invest_mode == INVEST_LOAD:
        st.session_state.mu_PV_yuan = 0.0
        st.session_state.mu_WT_yuan = 0.0


def _preset_min_case():
    nonce = int(st.session_state.get("upload_nonce", 0)) + 1
    for key, value in DEFAULTS.items():
        st.session_state[key] = value
    st.session_state.upload_nonce = nonce


def _to_internal(yuan):
    return float(yuan) * 0.1


def collect_config():
    s = st.session_state
    free = s.x_gd_mode == MODE_OPTIMIZE
    genco = s.invest_mode == INVEST_GENCO
    if genco:
        mu_pv = _to_internal(s.mu_PV_yuan)
        mu_wt = _to_internal(s.mu_WT_yuan)
        r0 = True
        crf_r = 0.0
    else:
        mu_pv = 0.0
        mu_wt = 0.0
        r0 = False
        crf_r = float(s.crf_r)
    return {
        "x_gd": 0.0 if free else float(s.x_gd),
        "x_gd_free": free,
        "r0": r0,
        "R": crf_r,
        "phi": float(s.phi) / 100.0,
        "theta": float(s.theta) / 100.0,
        "psi": float(s.psi) / 100.0,
        "mip_gap": float(DEFAULTS["mip_gap"]),
        "time_limit": float(s.time_limit),
        "L": float(s.L),
        "lambda_WT": float(s.lambda_WT),
        "lambda_PV": float(s.lambda_PV),
        "lambda_ST": float(s.lambda_ST),
        "lambda_GD": 0.0,
        "mu_TL": float(s.mu_TL),
        "D": float(s.D),
        "a_PV": float(s.a_PV),
        "S_PV_MAX": float(s.S_PV_MAX),
        "X_WT_MAX": float(s.X_WT_MAX),
        "X_ST_MAX": float(s.X_ST_MAX),
        "X_GD_MAX": float(s.X_GD_MAX),
        "mu_DC": _to_internal(s.mu_DC_yuan),
        "mu_ED": _to_internal(s.mu_ED_yuan),
        "mu_EO": _to_internal(s.mu_EO_yuan),
        "mu_EL": _to_internal(s.mu_EL_yuan),
        "mu_EG": _to_internal(s.mu_EG_yuan),
        "mu_EB": _to_internal(s.mu_EB_yuan),
        "mu_PV": mu_pv,
        "mu_WT": mu_wt,
        "mu_ES_peak": _to_internal(s.mu_ES_peak_yuan),
        "mu_ES_flat": _to_internal(s.mu_ES_flat_yuan),
        "mu_ES_valley": _to_internal(s.mu_ES_valley_yuan),
        "L_bar": float(s.L_bar),
        "M": float(s.M),
        "discount_rate": float(s.discount_rate_pct) / 100.0,
        "project_life": float(s.project_life),
        "Theta_PV_TARGET": float(s.Theta_PV_TARGET),
        "Theta_WT_TARGET": float(s.Theta_WT_TARGET),
        "normalize_pv": bool(s.normalize_pv),
        "eta_ch": float(s.eta_ch),
        "eta_dis": float(s.eta_dis),
        "E_init": float(s.E_init),
        "P_ST_MAX_C": float(s.P_ST_MAX_C),
        "P_ST_MAX_D": float(s.P_ST_MAX_D),
        "scale_load_to_L": bool(s.scale_load_to_L) and s.load_src == SRC_UPLOAD,
    }


def validate_config(cfg):
    errors = []
    if not cfg["x_gd_free"] and cfg["x_gd"] <= 0:
        errors.append("选择手动输入时，接网变压器设计容量必须大于 0 MW。")
    for name, key in (
        ("自发自用占总可用发电量比例下限", "phi"),
        ("余电上网占总可用发电量比例上限", "psi"),
        ("绿电发电量占总用电量比例下限", "theta"),
    ):
        val = cfg[key]
        if not 0.0 <= val <= 1.0:
            errors.append(f"{name}应在 0–100% 之间，当前为 {val * 100:.1f}%。")
    if not (cfg["mu_PV"] < cfg["mu_EB"] and cfg["mu_WT"] < cfg["mu_EB"]):
        errors.append("光伏、风电PPA电价必须低于网购电能量价。")
    if not cfg.get("r0") and cfg.get("R", 0) < 0:
        errors.append("资本回收系数不能为负。")
    if cfg["S_PV_MAX"] <= 0:
        errors.append("光伏可用地上限必须大于 0。")
    for name, key in (("充电效率", "eta_ch"), ("放电效率", "eta_dis")):
        if not 0.0 < cfg[key] <= 1.0:
            errors.append(f"{name}应在 0 到 1 之间（不含 0）。")
    return errors


@st.cache_resource
def load_preview_series():
    import params as p

    return {
        "load_t": np.array(p.load_t, copy=True),
        "alpha_PV_t": np.array(p.alpha_PV_t, copy=True),
        "alpha_WT_t": np.array(p.alpha_WT_t, copy=True),
        "Theta_PV": float(p.Theta_PV),
        "Theta_WT": float(p.Theta_WT),
        "T": int(p.T),
        "L": float(p.L),
    }


def _downsample(df, step=6):
    if len(df) <= 2000:
        return df
    return df.iloc[::step]


def _power_balance(df):
    bal = (
        df["P_WT"]
        + df["P_PV"]
        - df["P_ST_Charge"]
        + df["P_ST_Discharge"]
        + df["P_Grid_Buy"]
        - df["P_Grid_Sell"]
    )
    err = (bal - df["Load"]).abs()
    return err.max(), err.mean(), int((err > BALANCE_TOL_MW).sum())


BEIGE = "#F3E9D7"
BEIGE_CARD = "#FBF6EC"
BEIGE_MUTED = "#E8DCC6"
INK = "#2B2418"


def _inject_toggle_css():
    st.markdown(
        """
        <style>
        html, body, .stApp, [data-testid="stAppViewContainer"],
        [data-testid="stHeader"], [data-testid="stToolbar"],
        [data-testid="stMain"], .main, .block-container {
            background-color: #F3E9D7 !important;
            color: #2B2418 !important;
        }
        [data-testid="stHeader"] {
            background: #F3E9D7 !important;
        }
        section[data-testid="stSidebar"] {
            background-color: #E8DCC6 !important;
        }
        h1, h2, h3, h4, h5, h6, p, label, span, div, .stMarkdown, .stCaption {
            color: #2B2418;
        }
        .param-label {
            padding-top: 0.55rem;
            line-height: 1.4;
            color: #2B2418;
        }
        h5.param-section {
            margin: 1.4rem 0 0.6rem 0;
            padding-bottom: 0.35rem;
            border-bottom: 1px solid #CDBEA3;
            font-size: 1.05rem;
            color: #2B2418;
        }
        div[data-testid="stCheckbox"] {
            background: #FBF6EC;
            border: 1px solid #CDBEA3;
            border-radius: 8px;
            padding: 0.4rem 0.65rem;
            margin-bottom: 0.4rem;
        }
        div[data-testid="stCheckbox"]:hover {
            border-color: #8A6A2F;
            background: #F3E6C8;
        }
        .stButton > button {
            background: #E8DCC6 !important;
            color: #2B2418 !important;
            border: 1px solid #CDBEA3 !important;
        }
        .stButton > button[kind="primary"] {
            background: #C4A35A !important;
            color: #2B2418 !important;
            border: 1px solid #8A6A2F !important;
        }
        div[data-baseweb="input"] > div,
        div[data-baseweb="select"] > div,
        .stNumberInput input,
        .stTextInput input,
        textarea,
        [data-testid="stFileUploader"] section,
        [data-testid="stExpander"],
        [data-testid="stMetric"],
        [data-testid="stAlert"],
        [data-testid="stStatus"] {
            background-color: #FBF6EC !important;
            color: #2B2418 !important;
        }
        [data-testid="stCode"], pre, code, .stCodeBlock {
            background-color: #EDE3CF !important;
            color: #2B2418 !important;
        }
        div[data-testid="stForm"] {
            max-width: 480px;
            min-width: 360px;
            margin: 3.2rem auto 0 auto;
            background: #FBF6EC !important;
            padding: 1.8rem 2rem 1.4rem 2rem;
            border: 1px solid #CDBEA3;
            border-radius: 12px;
        }
        div[data-testid="stForm"] div[data-baseweb="input"] {
            min-width: 280px;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def _section(title):
    st.markdown(f'<h5 class="param-section">{title}</h5>', unsafe_allow_html=True)


def _num(label, **kwargs):
    name, field = st.columns([1.15, 1.35])
    name.markdown(f'<div class="param-label">{label}</div>', unsafe_allow_html=True)
    kwargs.setdefault("label_visibility", "collapsed")
    with field:
        st.number_input(label, **kwargs)


def _radio(label, options, **kwargs):
    name, field = st.columns([1.15, 1.35])
    name.markdown(f'<div class="param-label">{label}</div>', unsafe_allow_html=True)
    kwargs.setdefault("label_visibility", "collapsed")
    with field:
        st.radio(label, options, **kwargs)


def _gd_capacity_row():
    name, field = st.columns([1.15, 1.35])
    name.markdown(
        '<div class="param-label">接网变压器设计容量（MW）</div>',
        unsafe_allow_html=True,
    )
    with field:
        st.radio(
            "接网变压器设计容量（MW）",
            (MODE_MANUAL, MODE_OPTIMIZE),
            key="x_gd_mode",
            horizontal=True,
            label_visibility="collapsed",
        )
        if st.session_state.x_gd_mode == MODE_MANUAL:
            st.number_input(
                "接网变压器设计容量（MW）",
                min_value=0.0,
                step=1.0,
                key="x_gd",
                label_visibility="collapsed",
            )


def _csv_row(label, kind, src_key, widget_key, template_values, template_name):
    name, field = st.columns([1.15, 1.35])
    name.markdown(f'<div class="param-label">{label}</div>', unsafe_allow_html=True)
    arr = None
    err = None
    uploaded = None
    with field:
        st.radio(
            label,
            (SRC_DEFAULT, SRC_UPLOAD),
            key=src_key,
            horizontal=True,
            label_visibility="collapsed",
        )
        st.download_button(
            "下载模板",
            data=write_template_csv(kind, template_values).encode("utf-8-sig"),
            file_name=template_name,
            mime="text/csv",
            key=f"tpl_{widget_key}",
            use_container_width=True,
        )
        if st.session_state.get(src_key) == SRC_UPLOAD:
            uploaded = st.file_uploader(
                label,
                type=["csv"],
                key=widget_key,
                label_visibility="collapsed",
            )
    if uploaded is not None:
        try:
            arr = parse_series(uploaded.getvalue(), kind)
            st.caption(summarize(kind, arr))
        except SeriesFormatError as exc:
            err = str(exc)
            st.error(err)
    return arr, uploaded, err


def _pick_series(src_key, label, arr, uploaded, err):
    if st.session_state.get(src_key) != SRC_UPLOAD:
        return None, None, []
    if err:
        return None, None, [err]
    if arr is None or uploaded is None:
        return None, None, [f"已选择上传{label}，请上传 8760 小时 CSV，或改回使用默认。"]
    return arr, uploaded, []


def _check(label, **kwargs):
    name, field = st.columns([1.15, 1.35])
    name.markdown(f'<div class="param-label">{label}</div>', unsafe_allow_html=True)
    kwargs.setdefault("label_visibility", "collapsed")
    with field:
        st.checkbox(label, **kwargs)


def _compose_preview(default_series, load_arr, pv_arr, wt_arr):
    load_t = np.asarray(default_series["load_t"], dtype=float).copy()
    alpha_pv = np.asarray(default_series["alpha_PV_t"], dtype=float).copy()
    alpha_wt = np.asarray(default_series["alpha_WT_t"], dtype=float).copy()
    sources = {"负荷": "宁夏默认合成", "光伏": "宁夏默认", "风电": "宁夏默认"}
    if load_arr is not None:
        load_t = np.asarray(load_arr, dtype=float).copy()
        peak = float(load_t.max()) if load_t.size else 0.0
        if st.session_state.scale_load_to_L and peak > 0:
            load_t = load_t * (float(st.session_state.L) / peak)
            sources["负荷"] = "上传后按设计峰值调整"
        else:
            sources["负荷"] = "上传"
    else:
        l_ref = float(default_series.get("L") or 50.0)
        l_now = float(st.session_state.L)
        if l_ref > 1e-9:
            load_t = load_t * (l_now / l_ref)
        sources["负荷"] = f"宁夏默认（峰值约 {float(load_t.max()):.1f} MW）"
    if pv_arr is not None:
        alpha_pv = np.clip(np.asarray(pv_arr, dtype=float), 0.0, 1.0)
        sources["光伏"] = "上传"
    if wt_arr is not None:
        alpha_wt = np.clip(np.asarray(wt_arr, dtype=float), 0.0, 1.0)
        sources["风电"] = "上传"
    if st.session_state.normalize_pv:
        import params as p

        try:
            alpha_pv = p._normalize_cf_to_hours(
                alpha_pv, float(st.session_state.Theta_PV_TARGET), 1.0
            )
            if pv_arr is not None:
                sources["光伏"] = "上传后按目标小时数调整"
            else:
                sources["光伏"] = "宁夏默认并按目标小时数调整"
        except Exception as exc:
            st.warning(f"光伏曲线无法调整到目标小时数：{exc}")
    return {
        "load_t": load_t,
        "alpha_PV_t": alpha_pv,
        "alpha_WT_t": alpha_wt,
        "Theta_PV": float(np.sum(alpha_pv)),
        "Theta_WT": float(np.sum(alpha_wt)),
        "T": int(default_series["T"]),
        "sources": sources,
    }


def _trace_toggles(names, prefix):
    st.markdown("**显示曲线**")
    st.caption("点选左侧按钮，打开或关闭对应曲线")
    visible = {}
    for name in names:
        key = f"{prefix}_{name}"
        if key not in st.session_state:
            st.session_state[key] = True
        visible[name] = st.checkbox(name, key=key, help="点选后，右侧图中这条曲线会显示或隐藏")
    return visible


def _scatter(fig, x, y, name, visible, yaxis="y", width=1.2):
    if not visible.get(name, True):
        return
    fig.add_trace(go.Scatter(x=x, y=y, name=name, yaxis=yaxis, line=dict(width=width)))


def _chart_layout(fig, y2=False):
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=BEIGE,
        plot_bgcolor=BEIGE_CARD,
        font=dict(color=INK),
        height=400,
        margin=dict(l=20, r=20, t=20, b=40),
        xaxis_title="小时",
        yaxis=dict(title="MW", gridcolor=BEIGE_MUTED, zerolinecolor=BEIGE_MUTED),
        xaxis=dict(gridcolor=BEIGE_MUTED, zerolinecolor=BEIGE_MUTED),
        showlegend=False,
        hovermode="x unified",
    )
    if y2:
        fig.update_layout(yaxis2=dict(title="荷电状态", overlaying="y", side="right", range=[0, 1]))
    return fig


def _plot_overview(df, visible):
    shown = _downsample(df, step=6)
    fig = go.Figure()
    _scatter(fig, shown["Hour"], shown["Load"], "负荷", visible, width=1.6)
    _scatter(fig, shown["Hour"], shown["P_WT"], "风电", visible)
    _scatter(fig, shown["Hour"], shown["P_PV"], "光伏", visible)
    _scatter(fig, shown["Hour"], shown["P_Grid_Buy"], "购电", visible)
    _scatter(fig, shown["Hour"], shown["P_Grid_Sell"], "上网", visible)
    return _chart_layout(fig)


def _plot_day(df, day, visible):
    start = (int(day) - 1) * 24
    sl = df.iloc[start : start + 24]
    fig = go.Figure()
    mapping = (
        ("负荷", sl["Load"], "y"),
        ("风电", sl["P_WT"], "y"),
        ("光伏", sl["P_PV"], "y"),
        ("充电", sl["P_ST_Charge"], "y"),
        ("放电", sl["P_ST_Discharge"], "y"),
        ("购电", sl["P_Grid_Buy"], "y"),
        ("上网", sl["P_Grid_Sell"], "y"),
        ("荷电状态", sl["SOC"], "y2"),
    )
    for name, y, axis in mapping:
        _scatter(fig, sl["Hour"], y, name, visible, yaxis=axis)
    return _chart_layout(fig, y2=True)


def _plot_preview(series):
    hours = list(range(0, series["T"], 6))
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=hours, y=series["load_t"][hours], name="负荷"))
    fig.add_trace(go.Scatter(x=hours, y=series["alpha_PV_t"][hours], name="光伏出力系数", yaxis="y2"))
    fig.add_trace(go.Scatter(x=hours, y=series["alpha_WT_t"][hours], name="风电出力系数", yaxis="y2"))
    fig.update_layout(
        template="plotly_white",
        paper_bgcolor=BEIGE,
        plot_bgcolor=BEIGE_CARD,
        font=dict(color=INK),
        height=280,
        margin=dict(l=90, r=50, t=20, b=40),
        xaxis_title="小时（每 6 小时抽样）",
        yaxis=dict(title="负荷（MW）", gridcolor=BEIGE_MUTED, zerolinecolor=BEIGE_MUTED),
        xaxis=dict(gridcolor=BEIGE_MUTED, zerolinecolor=BEIGE_MUTED),
        yaxis2=dict(title="出力系数", overlaying="y", side="right", range=[0, 1]),
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="right", x=-0.02),
        hovermode="x unified",
    )
    return fig


def _fmt(v, nd=2):
    return f"{v:,.{nd}f}"


def _unit_cost_name(label):
    if "opex" in str(label).lower() or "R=0" in str(label):
        return "度电成本（仅运行成本，不含投资）"
    return "度电成本（含投资年化）"


def _status_text(status, gap):
    if str(status).startswith("OPTIMAL"):
        return "已得到可接受最优解。", "success"
    return (
        f"已到求解时限，当前为可行方案，装机结果可参考，但尚未证明全局最优。求解间隙为 {gap}。",
        "warning",
    )


def render_results(payload, csv_path, txt_path, lp_path, key_prefix=""):
    pfx = str(key_prefix or "job")
    if not payload:
        st.error("没有找到结果文件。")
        return
    if not payload.get("ok"):
        st.error(payload.get("message") or "求解失败。")
        if lp_path:
            st.warning("当前参数下模型不可行。请放宽自发自用或绿电占比下限，或增大占地、变压器容量。")
            st.download_button(
                "下载不可行模型文件",
                data=Path(lp_path).read_bytes(),
                file_name="model.lp",
                key=f"{pfx}_dl_lp",
            )
        return

    cap = payload["capacities"]
    cost = payload["cost"]
    pol = payload["policy"]
    ene = payload["energy"]
    msg, kind = _status_text(payload["status"], payload.get("mip_gap", "—"))
    getattr(st, kind)(msg)

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("年化综合成本", f"{_fmt(payload['objective_wan_per_year'])} 万元/年")
    c2.metric("度电成本", f"{cost['unit_cost_yuan_per_kwh']:.4f} 元/kWh")
    c3.metric("求解间隙", payload.get("mip_gap", "—"))
    c4.metric("求解器", "开源求解器")

    st.subheader("最优装机")
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("风电", f"{_fmt(cap['x_WT_MW'])} MW")
    k2.metric("光伏", f"{_fmt(cap['x_PV_MW'])} MW")
    k3.metric("储能", f"{_fmt(cap['x_ST_MWh'])} MWh")
    k4.metric("接网变压器容量", f"{_fmt(cap['x_GD_MW'])} MW")

    st.subheader("成本拆解")
    st.caption("设备投资、专线投资为一次性总价；计入年化综合成本时再按资本回收系数折算。电费与上网收益本身已是年值。")
    st.table(
        pd.DataFrame(
            [
                ["设备投资（一次性）", f"{_fmt(cost['equipment_investment_wan'])} 万元"],
                ["专线投资（一次性）", f"{_fmt(cost['direct_connection_wan'])} 万元"],
                ["年容量电费", f"{_fmt(cost['annual_demand_charge_wan'])} 万元/年"],
                ["年电量类支出", f"{_fmt(cost['annual_energy_tariff_wan'])} 万元/年"],
                ["年电网费用合计", f"{_fmt(cost['annual_grid_charge_total_wan'])} 万元/年"],
                ["年余电上网收益", f"{_fmt(cost['annual_market_revenue_wan'])} 万元/年"],
                [_unit_cost_name(cost["unit_cost_label"]), f"{cost['unit_cost_yuan_per_kwh']:.4f} 元/kWh"],
            ],
            columns=["项目", "数值"],
        )
    )

    st.subheader("政策比例")
    p1, p2, p3 = st.columns(3)
    p1.metric("余电上网比例", f"{pol['ratio_export']:.2%}", delta=f"上限 {pol['psi']:.0%}")
    p2.metric("自发自用比例", f"{pol['ratio_self']:.2%}", delta=f"下限 {pol['phi']:.0%}")
    p3.metric("绿电发电量占比", f"{pol['ratio_re_load']:.2%}", delta=f"下限 {pol['theta']:.0%}")
    hints = []
    if abs(pol["ratio_export"] - pol["psi"]) < 0.005:
        hints.append("余电上网比例贴着上限，说明上网约束起作用。")
    if pol["ratio_self"] + 1e-6 >= pol["phi"]:
        hints.append("自发自用比例高于下限。")
    if pol["ratio_re_load"] + 1e-6 >= pol["theta"]:
        hints.append("绿电发电量占年用电量的比例高于下限。")
    if hints:
        st.info(" ".join(hints))

    st.subheader("能量统计")
    st.table(
        pd.DataFrame(
            [
                ["年风光实际发电", f"{_fmt(ene['total_re_mwh'])} MWh"],
                ["年用电量", f"{_fmt(ene['total_load_mwh'])} MWh"],
                ["年可用发电量", f"{_fmt(ene['avail_re_mwh'])} MWh"],
                ["年余电上网", f"{_fmt(ene['export_mwh'])} MWh"],
            ],
            columns=["项目", "数值"],
        )
    )

    if csv_path:
        df = pd.read_csv(csv_path)
        max_err, mean_err, n_bad = _power_balance(df)
        st.subheader("逐时功率")
        if max_err <= BALANCE_TOL_MW:
            st.success(
                f"功率平衡校核通过：各小时风电＋光伏－充电＋放电＋购电－上网等于负荷，"
                f"最大偏差 {max_err:.4f} MW。"
            )
        else:
            st.error(
                f"功率平衡偏差过大：最大 {max_err:.4f} MW，均值 {mean_err:.4f} MW，"
                f"超过 {BALANCE_TOL_MW} MW 的小时数 {n_bad}。"
            )

        left, right = st.columns([0.22, 0.78])
        with left:
            ov_vis = _trace_toggles(["负荷", "风电", "光伏", "购电", "上网"], f"{pfx}_ov")
        with right:
            st.plotly_chart(_plot_overview(df, ov_vis), use_container_width=True)

        day = st.slider("查看全年中的第几天", min_value=1, max_value=365, key=f"{pfx}_result_day")
        dleft, dright = st.columns([0.22, 0.78])
        with dleft:
            day_vis = _trace_toggles(
                ["负荷", "风电", "光伏", "充电", "放电", "购电", "上网", "荷电状态"],
                f"{pfx}_day",
            )
        with dright:
            st.plotly_chart(_plot_day(df, day, day_vis), use_container_width=True)

    dl1, dl2, dl3 = st.columns(3)
    if txt_path:
        dl1.download_button(
            "下载文字结果",
            data=Path(txt_path).read_bytes(),
            file_name="optimization_results.txt",
            key=f"{pfx}_dl_txt",
        )
    if csv_path:
        dl2.download_button(
            "下载逐时数据",
            data=Path(csv_path).read_bytes(),
            file_name="timeseries_results.csv",
            key=f"{pfx}_dl_csv",
        )
    json_path = Path(txt_path).with_name("optimization_results.json") if txt_path else None
    if json_path and json_path.exists():
        dl3.download_button(
            "下载结构化结果",
            data=json_path.read_bytes(),
            file_name="optimization_results.json",
            key=f"{pfx}_dl_json",
        )


def _ensure_session_id():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False


def _render_job_body(job_id):
    rec = svc.get_job(job_id)
    if rec is None:
        st.warning("未找到所选计算结果。")
        return None
    status = rec.get("status")
    out_dir = rec.get("dir")
    log = svc.read_log(out_dir) if out_dir else ""
    qst = svc.queue_status()
    poll_key = f"_poll_{job_id}"

    if status == "queued":
        st.session_state[poll_key] = True
        st.info(
            f"该任务正在排队。当前计算中 {qst['running']} 个，排队 {qst['waiting']} 个"
            f"（最多同时 {qst['max_running']} 个）。"
        )
        if log:
            with st.expander("求解日志", expanded=True):
                st.code(log[-12000:], language="text")
        return "pending"

    if status == "running":
        st.session_state[poll_key] = True
        st.info("该任务正在计算，通常需要数分钟。完成后会自动显示结果。")
        with st.expander("求解日志", expanded=True):
            st.code(log[-12000:] if log else "正在启动求解器…", language="text")
        return "pending"

    if st.session_state.pop(poll_key, None):
        st.rerun()

    if log:
        with st.expander("求解日志", expanded=False):
            st.code(log[-12000:], language="text")

    packed = svc.load_result(out_dir) if out_dir else {}
    has_files = packed.get("json") or packed.get("lp_path") or packed.get("txt_path")
    if has_files:
        render_results(
            packed.get("json"),
            packed.get("csv_path"),
            packed.get("txt_path"),
            packed.get("lp_path"),
            key_prefix=job_id,
        )
        return status
    if status in ("failed", "infeasible"):
        st.error(rec.get("summary") or "求解失败。")
    else:
        st.error("没有找到结果文件。")
    return status


@st.fragment(run_every=2.0)
def _render_live_job():
    job_id = st.session_state.get("selected_job_id")
    if job_id:
        _render_job_body(job_id)


def _render_history_panel():
    flash = st.session_state.pop("job_flash", None)
    if flash:
        st.success(flash)

    items = svc.list_history()
    if not items:
        st.caption("尚未运行。可先点「输入宁夏省案例参数」，再点「计算最优容量配置方案」。")
        return

    ids = [rec["id"] for rec in items if rec.get("id")]
    labels = {rec["id"]: svc.job_label(rec) for rec in items if rec.get("id")}
    current = st.session_state.get("selected_job_id")
    if current not in ids:
        st.session_state.selected_job_id = ids[0]

    st.selectbox(
        "历史计算结果",
        ids,
        key="selected_job_id",
        format_func=lambda job_id: labels.get(job_id, job_id),
        help="保留最近 5 次已完成结果；正在排队或计算的任务也会出现在列表中。",
    )
    st.caption("可在此切换查看历史方案。正在排队或计算的任务也会列入，完成后自动显示结果。")

    job_id = st.session_state.selected_job_id
    rec = next((x for x in items if x.get("id") == job_id), None)
    if rec and rec.get("status") in ("queued", "running"):
        _render_live_job()
    else:
        _render_job_body(job_id)


def _render_login():
    st.title("绿电直连数据中心能源系统容量规划平台")
    st.caption("请登录后使用。多名用户可同时登录；计算任务最多同时进行 3 个，其余自动排队。")
    _, mid, _ = st.columns([1, 1.4, 1])
    with mid:
        with st.form("login_form"):
            username = st.text_input("用户名")
            password = st.text_input("密码", type="password")
            submitted = st.form_submit_button("登录", type="primary", use_container_width=True)
        if submitted:
            ok, msg = auth.try_login(username, password)
            if ok:
                st.session_state.logged_in = True
                st.rerun()
            else:
                st.error(msg)


def _top_bar_logout():
    left, right = st.columns([4.2, 1])
    with left:
        st.caption("当前用户：cmcc。计算任务最多同时 3 个，其余自动排队。")
    with right:
        if st.button("退出登录"):
            st.session_state.logged_in = False
            st.rerun()


def main():
    st.set_page_config(page_title="绿电直连数据中心能源系统容量规划平台", layout="wide")
    _inject_toggle_css()
    _ensure_session_id()
    if not st.session_state.logged_in:
        _render_login()
        return

    _init_state()
    _top_bar_logout()

    st.title("绿电直连数据中心能源系统容量规划平台")
    st.caption(
        "优化风电、光伏、储能与接网变压器装机。"
        "按全年 8760 小时运行模拟。默认场景锚定宁夏 110 千伏两部制工商业。"
    )
    st.button("输入宁夏省案例参数", on_click=_preset_min_case)
    st.caption("将负荷、造价、电价、储能、政策比例、出力曲线来源等全部参数恢复为宁夏案例默认值。")

    st.header("参数配置")

    _section("运行与政策参数配置")
    _gd_capacity_row()
    _radio(
        "投资模式",
        (INVEST_LOAD, INVEST_GENCO),
        key="invest_mode",
        on_change=_on_invest_mode_change,
    )
    if st.session_state.invest_mode == INVEST_LOAD:
        _num("资本回收系数", min_value=0.0, step=0.01, format="%.4f", key="crf_r")
        _num("利率（%）", min_value=0.0, step=0.5, key="discount_rate_pct")
    else:
        _num("光伏PPA电价（元/kWh）", min_value=0.0, step=0.01, format="%.4f", key="mu_PV_yuan")
        _num("风电PPA电价（元/kWh）", min_value=0.0, step=0.01, format="%.4f", key="mu_WT_yuan")
    _num("自发自用占总可用发电量比例下限（%）", min_value=0.0, max_value=100.0, step=5.0, key="phi")
    _num("绿电发电量占总用电量比例下限（%）", min_value=0.0, max_value=100.0, step=5.0, key="theta")
    _num("余电上网占总可用发电量比例上限（%）", min_value=0.0, max_value=100.0, step=5.0, key="psi")

    _section("时间与负荷参数配置")
    _num("负荷设计峰值（MW）", min_value=0.1, step=1.0, key="L")
    nonce = st.session_state.upload_nonce
    try:
        default_series = load_preview_series()
    except Exception as exc:
        default_series = None
        st.warning(f"无法加载默认曲线：{exc}")
    load_tpl = None if default_series is None else default_series["load_t"]
    load_arr, load_file, load_err = _csv_row(
        "负荷时序表",
        "load",
        "load_src",
        f"up_load_{nonce}",
        load_tpl,
        "负荷.csv",
    )
    if st.session_state.load_src == SRC_UPLOAD:
        _check("按设计峰值调整负荷", key="scale_load_to_L")
        st.caption("必须上传全年 8760 小时负荷，单位为 MW。勾选调整时，把曲线峰值拉到上面填写的设计峰值。")
    else:
        st.caption("使用默认时，按设计峰值合成全年负荷，无需上传。")

    _section("设备造价与专线")
    _num("风电单位造价（万元/MW）", min_value=0.0, step=10.0, key="lambda_WT")
    _num("光伏单位造价（万元/MW）", min_value=0.0, step=10.0, key="lambda_PV")
    _num("储能单位造价（万元/MWh）", min_value=0.0, step=5.0, key="lambda_ST")
    _num("专线单位造价（万元/km）", min_value=0.0, step=10.0, key="mu_TL")
    _num("专线距离（km）", min_value=0.0, step=1.0, key="D")
    _num("光伏可用地上限（亩）", min_value=0.0, step=50.0, key="S_PV_MAX")
    _num("风电装机上限（MW）", min_value=0.0, step=10.0, key="X_WT_MAX")
    _num("储能能量上限（MWh）", min_value=0.0, step=50.0, key="X_ST_MAX")
    _num("接网变压器容量上限（MW）", min_value=0.0, step=10.0, key="X_GD_MAX")

    _section("电价参数配置")
    _num("所在电压等级容（需）量电价（元/kW·月）", min_value=0.0, step=0.1, format="%.2f", key="mu_DC_yuan")
    _num("所在电压等级输配电度电价（元/kWh）", min_value=0.0, step=0.001, format="%.4f", key="mu_ED_yuan")
    _num("系统运行费（元/kWh）", min_value=0.0, step=0.001, format="%.4f", key="mu_EO_yuan")
    _num("线损折价（元/kWh）", min_value=0.0, step=0.0001, format="%.4f", key="mu_EL_yuan")
    _num("政府性基金及附加（元/kWh）", min_value=0.0, step=0.0001, format="%.4f", key="mu_EG_yuan")
    _num("网购电能量价（元/kWh）", min_value=0.0, step=0.01, format="%.4f", key="mu_EB_yuan")
    _num("上网电价·峰（元/kWh）", min_value=0.0, step=0.01, format="%.4f", key="mu_ES_peak_yuan")
    _num("上网电价·平（元/kWh）", min_value=0.0, step=0.01, format="%.4f", key="mu_ES_flat_yuan")
    _num("上网电价·谷（元/kWh）", min_value=0.0, step=0.01, format="%.4f", key="mu_ES_valley_yuan")
    _num("所在省份平均负荷率", min_value=0.0, max_value=1.0, step=0.05, key="L_bar")
    _num("年月份数", min_value=1.0, step=1.0, key="M")

    _section("经济参数配置")
    _num("项目设计使用年限（年）", min_value=1, step=1, key="project_life")

    _section("储能参数配置")
    _num("充电效率", min_value=0.01, max_value=1.0, step=0.01, key="eta_ch")
    _num("放电效率", min_value=0.01, max_value=1.0, step=0.01, key="eta_dis")
    _num("初始能量（MWh）", min_value=0.0, step=1.0, key="E_init")
    _num("最大充电功率（MW）", min_value=0.0, step=1.0, key="P_ST_MAX_C")
    _num("最大放电功率（MW）", min_value=0.0, step=1.0, key="P_ST_MAX_D")

    _section("新能源逐时出力参数配置")
    pv_tpl = None if default_series is None else default_series["alpha_PV_t"]
    wt_tpl = None if default_series is None else default_series["alpha_WT_t"]
    _num("所在省份光伏年等效利用小时数", min_value=0.0, step=50.0, key="Theta_PV_TARGET")
    pv_arr, pv_file, pv_err = _csv_row(
        "光伏出力系数表",
        "pv",
        "pv_src",
        f"up_pv_{nonce}",
        pv_tpl,
        "光伏出力系数.csv",
    )
    _check("按目标小时数调整光伏出力", key="normalize_pv")
    _num("所在省份风电年等效利用小时数", min_value=0.0, step=50.0, key="Theta_WT_TARGET")
    wt_arr, wt_file, wt_err = _csv_row(
        "风电出力系数表",
        "wt",
        "wt_src",
        f"up_wt_{nonce}",
        wt_tpl,
        "风电出力系数.csv",
    )
    st.caption("选择上传时必须提供 0 到 1 的出力系数，不要上传某座已建电站的 MW 出力。选择使用默认则用宁夏默认曲线。")
    load_arr, load_file, load_need = _pick_series("load_src", "负荷时序表", load_arr, load_file, load_err)
    pv_arr, pv_file, pv_need = _pick_series("pv_src", "光伏出力系数表", pv_arr, pv_file, pv_err)
    wt_arr, wt_file, wt_need = _pick_series("wt_src", "风电出力系数表", wt_arr, wt_file, wt_err)
    series_errors = load_need + pv_need + wt_need
    series_bytes = {}
    if load_arr is not None and load_file is not None:
        series_bytes["load_csv"] = load_file.getvalue()
    if pv_arr is not None and pv_file is not None:
        series_bytes["pv_csv"] = pv_file.getvalue()
    if wt_arr is not None and wt_file is not None:
        series_bytes["wt_csv"] = wt_file.getvalue()
    if default_series is not None:
        series = _compose_preview(default_series, load_arr, pv_arr, wt_arr)
        src = series["sources"]
        st.caption(
            f"当前预览：光伏年等效利用小时 {series['Theta_PV']:.0f} 小时，"
            f"风电 {series['Theta_WT']:.0f} 小时。"
            f"负荷来源：{src['负荷']}；光伏来源：{src['光伏']}；风电来源：{src['风电']}。"
            "预览随上传即时更新；点「计算最优容量配置方案」后才会写入本次计算。"
        )
        st.plotly_chart(_plot_preview(series), use_container_width=True)

    run_row, busy_row = st.columns([2.2, 2.8])
    run_clicked = run_row.button("计算最优容量配置方案", type="primary")
    qst = svc.queue_status()
    if qst["running"] or qst["waiting"]:
        busy_row.info(
            f"当前计算中 {qst['running']} 个，排队 {qst['waiting']} 个"
            f"（最多同时 {qst['max_running']} 个）。"
        )

    st.header("求解结果")
    if run_clicked:
        cfg = collect_config()
        errors = validate_config(cfg)
        errors.extend(series_errors)
        if errors:
            for msg in errors:
                st.error(msg)
        else:
            try:
                job_id, _out_dir = svc.start_job(cfg, series_bytes=series_bytes)
                st.session_state.selected_job_id = job_id
                st.session_state.last_job_id = job_id
                st.session_state.job_flash = "已开始计算。可在下方历史记录中查看进度或切换其他结果。"
                st.rerun()
            except Exception as exc:
                st.error(str(exc))

    _render_history_panel()


if __name__ == "__main__":
    main()
