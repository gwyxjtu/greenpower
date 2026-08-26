# 绿电直连微电网容量规划

智能计算中心绿电直连场景下的 **风电 / 光伏 / 储能 / 并网变压器** 容量优化模型。以全年 8760 h 运行模拟为基础，用 Gurobi 求解混合整数线性规划（MILP），目标为最小化年化综合成本。

场景参数默认锚定 **宁夏 / 110kV 两部制工商业**（算例口径可参考交底书中卫场景）。

---

## 环境依赖

- Python 3.9+
- **Gurobi**（需有效学术/商业 License）及 `gurobipy`
- `numpy`、`pandas`、`matplotlib`、`openpyxl`（导出 Excel）

建议使用已配置 Gurobi 的 conda / venv，例如：

```bash
# 确认 gurobipy 可用
python -c "import gurobipy; print(gurobipy.gurobi.version())"
```

若出现 `HostID mismatch`，请在本机非沙箱环境运行（License 与机器绑定）。

---

## 仓库结构

| 路径 | 说明 |
|------|------|
| `params.py` | 默认标量参数 + 8760h 时序（负荷、风光出力、电价） |
| `green_power_opt.py` | Gurobi 建模、容量优化 CLI（`solve` / `sensitivity`） |
| `standalone/` | **固定厂、R=0、μ 扫描**（不改 `params.py`） |
| `green_power.tex` | 数学模型公式（与代码对应） |
| `data/pvwatts_hourly.csv` | 银川 PVWatts 小时数据（光伏 AC 出力 + 近地面风速） |
| `results/` | 各算例输出（gitignore，本地可再生） |
| `plot/` | 灵敏度曲线图与 Excel 汇总（gitignore） |

---

## 快速开始

### 1. 改默认参数

编辑 `params.py`，常用项：

| 参数 | 含义 | 默认（约） |
|------|------|------------|
| `lambda_WT/PV/ST/GD` | 单位投资（万元/MW 或 万元/MWh） | 风 410、光 300、储 80、变 12 |
| `mu_PV` / `mu_WT` | 风光自发自用转移电价（万元/MWh） | 0.02595（=0.2595 元/kWh） |
| `mu_EB` | 网购电能量价 | 0.05（=0.5 元/kWh） |
| `phi` | 自发自用 / 可用发电量 下限 | 0.6 |
| `psi` | 余电上网 / 可用发电量 上限 | 0.2 |
| `theta` | 绿电发电量 / 用电量 下限 | 0.3 |
| `S_PV_MAX` | 光伏占地上限（亩） | 1500（≈1 km² → x_PV≤137.5 MW） |
| `D` | 专线距离（km） | 50 |
| `project_life` / `discount_rate` | 寿命与贴现率 → CRF **R** | 15 年、8%（R≈0.1168） |

**单位约定**

- 电量价：`1 万元/MWh = 0.1 元/kWh`
- 容量价：`1 万元/MW/月 = 0.1 元/kW/月`

CLI 里的 `--mu-re` 一律用 **元/kWh**。

风光资源：光伏直接用 PVWatts AC 出力；风电由近地面风速外推至轮毂高度后再标定到 `Theta_WT≈1800 h`。

### 2. 容量优化（风光储为决策变量）

不要直接 `python green_power_opt.py`（需子命令）。常用：

```bash
# μ=0，变压器固定 60 MW（φ=60%、θ=30%、ψ=20% 用 params 默认）
python green_power_opt.py solve --x-gd 60 --mu-re 0

# μ=0，变压器自由 0–200 MW
python green_power_opt.py solve --x-gd 0 --mu-re 0

# 投资不进目标函数（R=0），其余同 params
python green_power_opt.py solve --x-gd 60 --r0 --mu-re 0.36
```

每个算例目录下会生成：

- `optimization_results.txt` — 最优容量、成本拆解、政策比例、能量统计
- `timeseries_results.csv` — 8760 h 逐时功率 / SOC / 购售电

默认写出目录：`results/x_gd_60_mu_zero/`、`results/x_gd_free_mu_zero/`（可用 `--out` 指定）。

### 3. 固定厂 + 电价灵敏度（推荐走 standalone）

容量锁死、不改 `params.py`。预设见 `standalone/run.py list`。

```bash
python standalone/run.py list

# μ=0 / x_GD=60 最优厂，R=0，扫 μ=0.30–0.40
python standalone/run.py sweep-mu --preset mu0_gd60 --r0

# 同上，只跑 μ=0.36 一点
python standalone/run.py solve --preset mu0_gd60 --r0 --mu-re 0.36

# 示意厂 100/100/160，R=0，扫 φ 或扫 μ
python standalone/run.py sweep-phi --preset pv100_wt100_st160 --r0
python standalone/run.py sweep-mu --preset pv100_wt100_st160 --r0
```

说明：`standalone/README.md`。

### 4. φ / θ 容量灵敏度（80%–100%）

```bash
python green_power_opt.py sensitivity --mu-re 0 --x-gd 0
python green_power_opt.py sensitivity --mu-re 0 --x-gd 60
```

内部并行最多 8 进程。图/表在 `plot/`，分点在 `results/sensitivity_*/`。

也可用函数：

```python
from green_power_opt import run_single_optimization

r = run_single_optimization(
    D=50, phi=0.6, theta=0.3,
    mip_gap=0.01,
    mu_re=0.0,          # 万元/MWh；0 表示风光转移电价免费
    x_GD_bound=60,      # 0 = 变压器自由
    output_dir="results/my_case",
)
print(r["c_ele"], r["x_PV"], r["x_WT"], r["x_GD"])
```

---

## 模型在优化什么

**决策变量（容量）**

- \(x^{WT}, x^{PV}, x^{ST}, x^{GD}\)：风电、光伏、储能、变压器装机

**目标（年化）**  
设备投资 × CRF + 容量/电度/基金等电网费用 + 专线年化 − 余电上网收益  
（详见 `green_power.tex` / `run_optimization` 目标函数）

**关键约束**

- 逐时功率平衡、风光出力上限、储能动力学与互斥充放
- 购售电互斥、变压器容量限制
- 政策：φ 自发自用、ψ 上网上限、θ 绿电占比
- 光伏占地：\(a_{PV}\, x^{PV} \le S^{PV,MAX}\)

求解默认 `MIPGap=1%`；主求解另设 `TimeLimit=300` s。大规模 8760h MILP 可能较慢，可调 `MAIN_MIP_GAP` / `TimeLimit`。

---

## 常见情景怎么改

| 想做什么 | 怎么改 |
|----------|--------|
| 变压器固定 60 MW | `python green_power_opt.py solve --x-gd 60` |
| 变压器自由 | `--x-gd 0` |
| 风光转移电价=0 | `--mu-re 0`（CLI，元/kWh）或函数 `mu_re=0`（万元/MWh） |
| 投资不进目标 | `--r0`（R=CRF=0） |
| 固定已有最优厂再扫 μ | `python standalone/run.py sweep-mu --preset mu0_gd60 --r0` |
| 收紧光伏用地 | 改 `S_PV_MAX`（亩） |
| 扫 φ / θ（容量仍优化） | `python green_power_opt.py sensitivity --mu-re 0 --x-gd 60` |

本地结果目录（均 gitignore）对照：

| 目录 | 含义 |
|------|------|
| `results/x_gd_60_mu_zero/` | μ=0，x_GD=60，容量优化 |
| `results/x_gd_free_mu_zero/` | μ=0，x_GD 自由 |
| `results/x_gd_60_R0_fixed_mu0plant/` | 上述最优厂锁死，R=0，μ 扫描 |
| `results/standalone_pv100_wt100_st160_gd60_R0/` | 100/100/160 示意厂 |

---

## 结果怎么读

`optimization_results.txt` 中重点关注：

1. **Optimal Capacities** — 装机方案  
2. **Cost Breakdown** — 投资、容量费、电度费、售电收益、度电成本  
3. **Policy Ratios** — 实际上网比例、自发自用、绿电发电量/负荷（是否贴 φ/ψ/θ）  
4. **Energy Statistics** — 年发电量、负荷、可用发电量 avail（\(x\cdot\Theta\)）

**度电成本口径**：与目标函数一致，\(c = J /\) 年用电量。  
\(J = R\cdot(\text{设备}+\text{专线}) + \text{年运行净支出}\)。R=CRF（默认 8%、15 年 ≈0.1168）；`--r0` 时投资不进 J。单位 **元/kWh**。

负荷中由本地绿电供上的比例是 \((\text{年用电}-\text{网购})/\text{年用电}\)，与「绿电发电量/负荷」不是同一个数。

---

## 注意

1. **不要在沙箱/容器里硬跑**（易触发 Gurobi HostID 不匹配）。  
2. 风资源已相对宁夏典型小时数标定；若换真实风电场数据，请同步检查 `Theta_WT` 与 `alpha_WT_t`。  
3. `params.py` 里 `assert mu_PV < mu_EB`：内部转移价须低于网购电价。  
4. 并行灵敏度会同时起多个 Gurobi 进程，注意 License 线程/进程数限制。
