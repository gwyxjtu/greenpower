# 固定厂 / R=0 实验（不改 `params.py`）

统一入口：

```bash
python standalone/run.py list
python standalone/run.py solve --preset mu0_gd60 --r0 --mu-re 0.36
python standalone/run.py sweep-mu --preset mu0_gd60 --r0
python standalone/run.py sweep-mu --preset pv100_wt100_st160 --r0
python standalone/run.py sweep-phi --preset pv100_wt100_st160 --r0
```

`--r0` 把投资年化系数 R 置 0（目标函数只含运行成本）。`--mu-re` 单位是 **元/kWh**。φ 默认 0.6，θ 默认 0.3（可用 `--phi` / `--theta` 改）。

## 预设厂

| preset | 容量 | 说明 |
|--------|------|------|
| `mu0_gd60` | WT 43.12 / PV 137.50 / ST 218.93 / GD 60 | μ=0、变压器 60 MW 时的最优厂 |
| `pv100_wt100_st160` | WT=PV=100 / ST 160 / GD 60，充放 40 MW | 示意固定厂 |

定义在 `standalone/fixed_plant.py` 的 `PRESETS`。

## 输出位置

- 分点：`results/<preset 目录>/sensitivity_mu_re/` 或 `sensitivity_phi/` 或 `mu_re_0.xx/`
- 图/表：`plot/mu_re_vs_c_ele_<stub>_R0.png`（及对应 xlsx）

旧脚本名仍可调用，内部转发到上面的 CLI。
