# 绿电直连数据中心能源系统容量规划平台

智算中心绿电直连场景：优化 **风电 / 光伏 / 储能 / 并网变压器** 装机。全年 8760 h 运行模拟，开源求解器 **SCIP**（PySCIPOpt）求解 MILP，目标为最小化年化综合成本。

场景默认锚定 **宁夏 / 110 kV 两部制工商业**。

## 内容

| 路径 | 说明 |
|------|------|
| `params.py` | 全部标量参数，并生成 8760 h 负荷、风光出力系数与电价时序 |
| `green_power_opt.py` | SCIP 建模、求解与结果写出 |
| `app.py` | Streamlit 网页（2.2 / 2.3 / 第 4 节） |
| `solver_service.py` | 网页子进程求解与单任务锁 |
| `timeseries_io.py` | 负荷 / 光伏 / 风电 8760 小时 CSV 模板与校验 |
| `data/pvwatts_hourly.csv` | 银川 PVWatts 小时数据（光伏 AC 出力、近地面风速） |
| `requirements.txt` | Python 依赖（numpy、pyscipopt、streamlit、pandas、plotly） |
| `deploy/` | systemd 与 frpc 代理示例 |
| `绿电直连微电网容量规划-使用说明.docx` | 仓库介绍、参数列表与输出字段释义 |
| `README.md` | 简要命令说明 |

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

## 网页（Streamlit）

本机只监听 `127.0.0.1:8501`，由用户 systemd 服务 `greenpower-web` 拉起：

```bash
systemctl --user status greenpower-web
```

外网需经已有 frpc 把 8501 打到 frpserver **18501**。配置已写入 `/home/guo/app/frp/frpc.toml`（代理名 `greenpower-web`）。**root 的 frpc 需要重启后才生效**：

```bash
sudo bash deploy/enable-frp.sh
# 或：sudo systemctl restart frpc
```

然后访问 `http://47.116.1.6:18501`。若连不上，检查 frps 是否放行 18501（`allowPorts`）。

界面覆盖说明书 2.2 运行项、2.3 最小案例与结果解读、第 4 节参数；求解在子进程中执行，结果写到 `out/jobs/<id>/`。

可在「时间与负荷」「资源曲线预览」分别上传全年 8760 小时 CSV（UTF-8，逗号分隔，第 1 行表头）：

```text
小时,负荷（MW）
0,35.2
...
8759,36.1
```

光伏 / 风电表头为 `小时,光伏出力系数` / `小时,风电出力系数`，数值必须是 0–1 出力系数。页面提供模板下载。求解时会把校验通过的表复制到任务目录。JSON 配置可用 `load_csv` / `pv_csv` / `wt_csv` 指向同样格式的文件，`scale_load_to_L` 为 true 时把负荷峰值缩放到 `L`。

本地手动启动：

```bash
/home/guo/anaconda3/bin/python -m streamlit run app.py --server.address 127.0.0.1 --server.port 8501
```

## 运行

```bash
# μ=0，变压器固定 60 MW
python green_power_opt.py --x-gd 60 --mu-re 0

# μ=0，变压器自由 0–200 MW
python green_power_opt.py --x-gd 0 --mu-re 0

# 投资不进目标（R=0）
python green_power_opt.py --x-gd 60 --r0 --mu-re 0.36
```

选项：`--x-gd`（`0` = 变压器自由）、`--mu-re`、`--r0`、`--phi`、`--theta`、`--out`、`--mip-gap`、`--time-limit`、`--config`（JSON 覆盖第 4 节参数）。

每次求解生成：

- `optimization_results.txt` — 最优容量、成本拆解、政策比例
- `optimization_results.json` — 同上（网页读取）
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
