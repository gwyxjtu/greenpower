# 敏感性分析功能实现总结

## ✅ 已完成的功能

根据 `params.py` 中的三个 plot 需求，已在 `green_power_opt.py` 中添加了完整的参数敏感性分析和绘图功能。

### 三个图表的生成

程序运行时会自动生成以下三张图表到 `plot/` 文件夹：

#### 1️⃣ **D_vs_c_ele.png** - 直连距离对单位电价的影响
```
参数范围：D = 10, 20, 30, ..., 80 km (每10km一步)
纵轴：单位电价 (元/kWh)
使用技术：蓝色圆点线图
```

#### 2️⃣ **phi_vs_c_ele.png** - RE自消比对单位电价的影响
```
参数范围：phi = 0.1, 0.2, 0.3, ..., 0.9 (每0.1一步)
纵轴：单位电价 (元/kWh)
使用技术：紫色方形线图
```

#### 3️⃣ **theta_vs_c_ele.png** - RE发电比例对单位电价的影响
```
参数范围：theta = 0.1, 0.2, 0.3, ..., 0.9 (每0.1一步)
纵轴：单位电价 (元/kWh)
使用技术：橙色三角形线图
```

## 🔧 核心实现

### 新增函数

1. **`run_sensitivity_analysis()`** - 主敏感性分析函数
   - 创建 plot 文件夹
   - 依次扫描三个关键参数
   - 调用 `run_single_optimization()` 获取结果
   - 使用 matplotlib 绘制并保存图表
   - 绘图完成后自动恢复参数为默认值

2. **`run_single_optimization()`** - 单次优化函数
   - 根据当前参数值构建和求解优化模型
   - 返回包含所有关键结果的字典
   - 计算单位电价 c_ele
   - 错误处理：若优化失败则返回 None

### 参数修改

- **params.py**：
  - 新增 CRF（资本回收因子）计算
  - 参数保持可调整性

- **green_power_opt.py**：
  - 添加导入：`os`, `numpy`, `matplotlib.pyplot`
  - 修复代码中的变量定义问题（U, c_ele）
  - 添加两个新函数进行敏感性分析
  - main 函数调用顺序：先运行基础优化，再运行敏感性分析

## 📊 使用方法

```bash
cd /Users/guoguoguo/Seafile/guo_file/sf_2026/绿电直连/greenpower
python green_power_opt.py
```

程序执行流程：
1. 🔨 运行基础优化（默认参数）
   - 输出：`optimization_results.txt` 和 `timeseries_results.csv`
   
2. 📈 运行敏感性分析
   - 分析 D 参数的影响（8个点）
   - 分析 phi 参数的影响（9个点）
   - 分析 theta 参数的影响（9个点）
   - 总计：26 次优化计算
   
3. 💾 生成三张高分辨率 PNG 图表
   - 路径：`plot/D_vs_c_ele.png`
   - 路径：`plot/phi_vs_c_ele.png`
   - 路径：`plot/theta_vs_c_ele.png`

## 🎨 图表特性

- **分辨率**：300 DPI（适合论文发表）
- **大小**：10" × 6"
- **格式**：PNG，自动紧凑布局
- **风格**：
  - 专业配色
  - 网格参考线
  - 清晰的轴标签和标题
  - 自适应刻度标签

## ⚙️ 性能优化

敏感性分析中的优化器配置为加速求解：

```python
model.setParam('OutputFlag', 0)      # 关闭求解器输出
model.setParam('MIPGap', 0.01)       # 1% 优化间隙
model.setParam('TimeLimit', 300)     # 300秒时限
```

## 📝 注意事项

1. **参数恢复**：每个参数扫描完成后自动恢复为默认值
2. **错误处理**：若某个参数值的优化失败，程序跳过该点继续
3. **文件夹创建**：plot 文件夹会自动创建
4. **增量更新**：可根据需要调整 `np.arange()` 的参数范围和步长

## 📚 输出文件

运行后生成的文件结构：

```
greenpower/
├── plot/
│   ├── D_vs_c_ele.png          ✅
│   ├── phi_vs_c_ele.png        ✅
│   └── theta_vs_c_ele.png      ✅
├── optimization_results.txt
├── timeseries_results.csv
└── ...其他文件
```

## ✨ 后续可定制项

若需要修改参数范围或步长，编辑 `run_sensitivity_analysis()` 中的以下行：

```python
# 修改 D 的扫描范围
D_values = np.arange(10, 90, 10)    # 改为所需范围

# 修改 phi 的扫描范围
phi_values = np.arange(0.1, 1.0, 0.1)  # 改为所需范围

# 修改 theta 的扫描范围
theta_values = np.arange(0.1, 1.0, 0.1)  # 改为所需范围
```

---

**状态**：✅ 完成并测试  
**日期**：2026-05-17  
**文档**：PLOT_README.md
