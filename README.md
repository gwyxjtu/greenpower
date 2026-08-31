# 绿电直连微电网容量规划

智算中心绿电直连场景下的 **风电 / 光伏 / 储能 / 并网变压器** 容量优化。以全年 8760 h 运行模拟为基础，用 Gurobi 求解混合整数线性规划（MILP），目标为最小化年化综合成本。

场景参数默认锚定 **宁夏 / 110 kV 两部制工商业**（算例口径见交底书中卫场景）。

---

## 交付清单

| 路径 | 说明 |
|------|------|
| `params.py` | 标量参数与 8760 h 时序（负荷、风光出力、电价） |
| `green_power_opt.py` | Gurobi 建模与 CLI：`solve` / `sensitivity` |
| `standalone/` | 固定厂、R=0、μ / φ 扫描（不改 `params.py`） |
| `data/pvwatts_hourly.csv` | 银川 PVWatts 小时数据（光伏 AC + 近地面风速） |
| `green_power.tex` / `green_power.pdf` | 数学模型 |
| `requirements.txt` | Python 依赖（不含 Gurobi） |
| `results/` | 本地算例输出（gitignore，可再生） |
| `plot/` | 灵敏度曲线与 Excel 汇总（gitignore） |

交底书 Word 与本仓库同目录，文件名以「技术交底书」开头。

---

## 环境

- Python 3.9+
- **Gurobi**（有效学术/商业 License）及 `gurobipy`
- `numpy`、`pandas`、`matplotlib`、`openpyxl`

```bash
pip install -r requirements.txt
python -c "import gurobipy; print(gurobipy.gurobi.version())"
```

License 与机器绑定。出现 `HostID mismatch` 时请在本机非沙箱环境运行。

---

## 单位约定

| 类型 | 模型内部 | 与常用单位 |
|------|----------|------------|
| 电量价 | 万元/MWh | = 0.1 × (元/kWh) |
| 容量价 | 万元/MW/月 | = 0.1 × (元/kW/月) |

CLI 的 `--mu-re` **一律用元/kWh**。Python 函数 `run_single_optimization(..., mu_re=)` 用 **万元/MWh**。

---

## 使用方法

工作目录为仓库根目录。不要直接 `python green_power_opt.py`（必须带子命令）。

### 1. 容量优化（风光储为决策变量）

```bash
# μ=0，变压器固定 60 MW（φ / θ / ψ 用 params.py 默认）
python green_power_opt.py solve --x-gd 60 --mu-re 0

# μ=0，变压器自由 0–200 MW
python green_power_opt.py solve --x-gd 0 --mu-re 0

# 投资不进目标函数（R=0）
python green_power_opt.py solve --x-gd 60 --r0 --mu-re 0.36
```

常用选项：`--x-gd` 变压器 MW（`0` = 自由）、`--mu-re` 风光转移电价（元/kWh）、`--r0`、`--phi`、`--theta`、`--out`。

每个算例目录生成：

- `optimization_results.txt` — 最优容量、成本拆解、政策比例、能量统计
- `timeseries_results.csv` — 8760 h 功率 / SOC / 购售电

默认写出：`results/x_gd_60_mu_zero/`、`results/x_gd_free_mu_zero/`。

### 2. 固定厂 + 电价 / 政策扫描

容量锁死，不改 `params.py`。预设见 `python standalone/run.py list`。

```bash
python standalone/run.py list

# μ=0 / x_GD=60 最优厂，R=0，扫 μ=0.30–0.40
python standalone/run.py sweep-mu --preset mu0_gd60 --r0

# 同一预设，单点
python standalone/run.py solve --preset mu0_gd60 --r0 --mu-re 0.36

# 示意厂 100/100/160，R=0，扫 φ 或扫 μ
python standalone/run.py sweep-phi --preset pv100_wt100_st160 --r0
python standalone/run.py sweep-mu --preset pv100_wt100_st160 --r0
```

| preset | 容量 | 说明 |
|--------|------|------|
| `mu0_gd60` | WT 43.12 / PV 137.50 / ST 218.93 / GD 60 | μ=0、变压器 60 MW 时的最优厂 |
| `pv100_wt100_st160` | WT=PV=100 / ST 160 / GD 60，充放 40 MW | 示意固定厂 |

预设定义在 `standalone/fixed_plant.py`。`--mu-re` 单位为元/kWh；φ 默认 0.6，θ 默认 0.3。

### 3. φ / θ 容量灵敏度（80%–100%）

风光储仍为决策变量，内部最多 8 进程并行：

```bash
python green_power_opt.py sensitivity --mu-re 0 --x-gd 0
python green_power_opt.py sensitivity --mu-re 0 --x-gd 60
```

图/表在 `plot/`，分点在 `results/sensitivity_*/`。

### 4. Python 调用

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

## 改参数

编辑 `params.py`。常用项：

| 参数 | 含义 | 默认（约） |
|------|------|------------|
| `lambda_WT/PV/ST/GD` | 单位投资（万元/MW 或 万元/MWh） | 风 410、光 300、储 80、变 12 |
| `mu_PV` / `mu_WT` | 风光自发自用转移电价（万元/MWh） | 0.02595（=0.2595 元/kWh） |
| `mu_EB` | 网购电能量价 | 0.05（=0.5 元/kWh） |
| `phi` | 自发自用 / 可用发电量 下限 | 0.6 |
| `psi` | 余电上网 / 可用发电量 上限 | 0.2 |
| `theta` | 绿电发电量 / 用电量 下限 | 0.3 |
| `S_PV_MAX` | 光伏占地上限（亩） | 1500（≈1 km² → x_PV ≤ 137.5 MW） |
| `D` | 专线距离（km） | 50 |
| `project_life` / `discount_rate` | 寿命与贴现率 → CRF **R** | 15 年、8%（R≈0.1168） |

风光资源：光伏直接用 PVWatts AC 出力；风电由近地面风速外推至轮毂高度后再标定到 `Theta_WT≈1800 h`。内部转移价必须低于网购电价（`assert mu_PV < mu_EB`）。

临时改 μ / R / φ / θ **不要写回** `params.py`，用 CLI 覆盖或 `standalone/run.py`。

| 想做什么 | 怎么改 |
|----------|--------|
| 变压器固定 60 MW | `python green_power_opt.py solve --x-gd 60` |
| 变压器自由 | `--x-gd 0` |
| 风光转移电价 = 0 | `--mu-re 0` |
| 投资不进目标 | `--r0` |
| 固定已有最优厂再扫 μ | `python standalone/run.py sweep-mu --preset mu0_gd60 --r0` |
| 收紧光伏用地 | 改 `S_PV_MAX`（亩） |
| 扫 φ / θ（容量仍优化） | `python green_power_opt.py sensitivity --mu-re 0 --x-gd 60` |

---

## 模型在优化什么

**决策变量（容量）**

- \(x^{WT}, x^{PV}, x^{ST}, x^{GD}\)：风电、光伏、储能、变压器装机

**目标（年化）**  
设备投资 × CRF + 容量/电度/基金等电网费用 + 专线年化 − 余电上网收益。公式见 `green_power.tex`，实现见 `run_optimization`。

**关键约束**

- 逐时功率平衡、风光出力上限、储能动力学与互斥充放
- 购售电互斥、变压器容量限制
- 政策：φ 自发自用、ψ 上网上限、θ 绿电占比
- 光伏占地：\(a_{PV}\, x^{PV} \le S^{PV,MAX}\)

默认 `MIPGap=1%`；主求解另设 `TimeLimit=300` s。8760 h MILP 可能较慢，可调 `MAIN_MIP_GAP` / `TimeLimit`。并行灵敏度会同时起多个 Gurobi 进程，注意 License 席位数。

---

## 结果怎么读

`optimization_results.txt` 中重点关注：

1. **Optimal Capacities** — 装机方案
2. **Cost Breakdown** — 投资、容量费、电度费、售电收益、度电成本
3. **Policy Ratios** — 实际上网比例、自发自用、绿电发电量/负荷（是否贴 φ/ψ/θ）
4. **Energy Statistics** — 年发电量、负荷、可用发电量 avail（\(x\cdot\Theta\)）

**度电成本口径**：与目标函数一致，\(c = J /\) 年用电量。  
\(J = R\cdot(\text{设备}+\text{专线}) + \text{年运行净支出}\)。R = CRF（默认 8%、15 年 ≈0.1168）；`--r0` 时投资不进 J。单位 **元/kWh**。

负荷中由本地绿电供上的比例是 \((\text{年用电}-\text{网购})/\text{年用电}\)，与「绿电发电量/负荷」不是同一个数。

### 示例算例（μ=0，CRF 8%/15 年）

| 算例 | WT / PV / ST / GD | 年化目标 | 度电成本 |
|------|-------------------|----------|----------|
| 变压器 60 MW | 43.12 MW / 137.50 MW / 218.93 MWh / 60 MW | 17892 万元/年 | 0.5206 元/kWh |
| 变压器自由 | 36.82 MW / 137.50 MW / 159.37 MWh / 31.19 MW | 16466 万元/年 | 0.4791 元/kWh |

光伏均顶到占地上限 137.50 MW。目录对照见 `results/README.md`。

### 图与表（`plot/`）

| 文件（png + xlsx） | 内容 |
|------|------|
| `phi_vs_c_ele_mu_zero_80_100_xgd_free` | 容量优化，φ ∈ [0.8, 1.0] |
| `theta_vs_c_ele_mu_zero_80_100_xgd_free` | 容量优化，θ ∈ [0.8, 1.0] |
| `mu_re_vs_c_ele_pv137.5_wt43.12_st218.93_gd60_R0` | 固定最优厂，R=0，扫 μ |
| `mu_re_vs_c_ele_pv100_wt100_st160_gd60_R0` | 示意厂，R=0，扫 μ |
| `phi_vs_c_ele_pv100_wt100_st160_gd60_R0` | 示意厂，R=0，扫 φ |

---

## 注意

1. 不要在沙箱/容器里硬跑（易触发 Gurobi HostID 不匹配）。
2. 风资源已相对宁夏典型小时数标定；若换真实风电场数据，请同步检查 `Theta_WT` 与 `alpha_WT_t`。
3. `results/` 与 `plot/` 体积大、可本地再生，不纳入版本库。
