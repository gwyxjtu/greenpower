# 绿电直连微电网容量规划

智算中心绿电直连场景：优化 **风电 / 光伏 / 储能 / 并网变压器** 装机。全年 8760 h 运行模拟，开源求解器 **SCIP**（PySCIPOpt）求解 MILP，目标为最小化年化综合成本。

场景默认锚定 **宁夏 / 110 kV 两部制工商业**。

## 内容

| 路径 | 说明 |
|------|------|
| `params.py` | 标量参数与 8760 h 时序（负荷、风光出力、电价） |
| `green_power_opt.py` | SCIP 建模与求解入口 |
| `data/pvwatts_hourly.csv` | 银川 PVWatts 小时数据（光伏 AC + 近地面风速） |
| `requirements.txt` | Python 依赖（numpy、pyscipopt） |
| `绿电直连微电网容量规划-使用说明.docx` | 仓库介绍、参数列表与输出字段释义 |

求解输出写到 `out/`（不入库，可本地删除）。

## 环境

- Python 3.9+
- 开源求解器 SCIP，通过 `pyscipopt` 调用（无需商业 License）
- `numpy`

```bash
pip install -r requirements.txt
python -c "import pyscipopt; print(pyscipopt.__version__)"
```

较新的 `pyscipopt` pip 包会自带 SCIP 动态库。也可用 conda：

```bash
conda install --channel conda-forge pyscipopt numpy
```

## 单位

| 类型 | 模型内部 | 换算 |
|------|----------|------|
| 电量价 | 万元/MWh | = 0.1 × (元/kWh) |
| 容量价 | 万元/MW/月 | = 0.1 × (元/kW/月) |

CLI `--mu-re` 用 **元/kWh**。

## 运行

```bash
# μ=0，变压器固定 60 MW
python green_power_opt.py --x-gd 60 --mu-re 0

# μ=0，变压器自由 0–200 MW
python green_power_opt.py --x-gd 0 --mu-re 0

# 投资不进目标（R=0）
python green_power_opt.py --x-gd 60 --r0 --mu-re 0.36
```

选项：`--x-gd`（`0` = 变压器自由）、`--mu-re`、`--r0`、`--phi`、`--theta`、`--out`、`--mip-gap`、`--time-limit`。

每次求解生成：

- `optimization_results.txt` — 最优容量、成本拆解、政策比例
- `timeseries_results.csv` — 8760 h 功率 / SOC / 购售电

不可行时写出 `model.lp`（完整 LP，便于排查）。

## 改参数

编辑 `params.py`。常用项：

| 参数 | 含义 | 默认（约） |
|------|------|------------|
| `lambda_WT/PV/ST/GD` | 单位投资（万元/MW 或 万元/MWh） | 风 410、光 300、储 80、变 12 |
| `mu_PV` / `mu_WT` | 风光转移电价（万元/MWh） | 0.02595（=0.2595 元/kWh） |
| `mu_EB` | 网购电能量价 | 0.05（=0.5 元/kWh） |
| `phi` | 自发自用 / 可用发电量 下限 | 0.6 |
| `psi` | 余电上网 / 可用发电量 上限 | 0.2 |
| `theta` | 绿电发电量 / 用电量 下限 | 0.3 |
| `S_PV_MAX` | 光伏占地上限（亩） | 1500（→ x_PV ≤ 137.5 MW） |
| `X_WT_MAX` / `X_ST_MAX` / `X_GD_MAX` | 风电 / 储能 / 变压器决策上界 | 500 MW / 2000 MWh / 200 MW |
| `D` | 专线距离（km） | 50 |
| `project_life` / `discount_rate` | 寿命与贴现率 → CRF R | 15 年、8%（R≈0.1168） |

临时改 μ / R / φ / θ 用命令行，不要写回 `params.py`。内部转移价须低于网购电价（`assert mu_PV < mu_EB`）。

## 模型

决策变量：\(x^{WT}, x^{PV}, x^{ST}, x^{GD}\)。

目标：设备投资 × CRF + 电网费用 + 专线年化 − 余电上网收益。

约束：逐时功率平衡、风光出力上限、储能动力学与互斥充放、购售电互斥、φ/ψ/θ 政策、光伏占地。购售电 `p ≤ x·y`（`y` 为 0-1）已线性化为 big-M，保证模型是 MILP。

度电成本 \(c = J/\) 年用电量（元/kWh）。`--r0` 时投资不进 \(J\)。默认相对 MIP 间隙 1%，墙钟时限 600 s。开源 SCIP 通常比商业求解器慢，8760 h 规模更容易碰到时限；可用 `--time-limit` / `--mip-gap` 放宽。结果文件会写出 `MIP gap`，时限到达时仍可能是可行解而非 1% 最优。
