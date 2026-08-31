# 结果目录

本目录**不入库**（gitignore）。下列文件夹是当前交付算例的本地输出，可用文末命令重新生成。

| 目录 | 含义 |
|------|------|
| `x_gd_60_mu_zero/` | 容量优化：μ=0，变压器固定 60 MW |
| `x_gd_free_mu_zero/` | 容量优化：μ=0，变压器 0–200 MW 自由 |
| `x_gd_60_R0_fixed_mu0plant/` | 上述 60 MW 最优厂锁死，R=0，扫 μ |
| `standalone_pv100_wt100_st160_gd60_R0/` | 示意厂 100/100/160，R=0 |
| `sensitivity_mu_zero_xgd_free/` | 容量仍优化，μ=0，φ/θ ∈ [80%, 100%] |

每个算例目录内：

- `optimization_results.txt` — 最优容量、成本拆解、政策比例、能量统计
- `timeseries_results.csv` — 8760 h 功率 / SOC / 购售电

灵敏度分点在子目录 `phi/`、`theta/`、`sensitivity_mu_re/` 等。汇总图与 Excel 在仓库根目录的 `plot/`。

重新生成（需 Gurobi License，在非沙箱环境运行）：

```bash
python green_power_opt.py solve --x-gd 60 --mu-re 0
python green_power_opt.py solve --x-gd 0 --mu-re 0
python green_power_opt.py sensitivity --mu-re 0 --x-gd 0
python standalone/run.py sweep-mu --preset mu0_gd60 --r0
python standalone/run.py sweep-mu --preset pv100_wt100_st160 --r0
python standalone/run.py sweep-phi --preset pv100_wt100_st160 --r0
```
