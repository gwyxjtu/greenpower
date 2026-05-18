# 敏感性分析数据导出说明

## 新增功能

已更新敏感性分析模块，现在不仅生成图表，还会自动导出详细的分析数据到Excel文件。

## 导出数据内容

### 1. D敏感性分析 (`plot/sensitivity_D.xlsx`)

参数范围：直连距离 10 km - 80 km（每10 km一步）

**导出的列**：
- Distance (km) - 直连距离
- Unit Cost (元/kWh) - 单位电价
- **Investment Cost (万元)** - 年化投资成本 ⭐
- Grid Cost (万元) - 电网固定成本
- Connection Cost (万元) - 直连成本
- Market Revenue (万元) - 市场收益
- Objective (万元) - 目标函数值
- Wind (MW) - 风电容量
- PV (MW) - 光伏容量
- Storage (MWh) - 储能容量
- Grid (MW) - 电网容量

### 2. phi敏感性分析 (`plot/sensitivity_phi.xlsx`)

参数范围：最小自消比 0.1 - 0.9（每0.1一步）

**导出的列**：
- Min Self-consumption Ratio - 最小自消比
- Unit Cost (元/kWh) - 单位电价
- **Investment Cost (万元)** - 年化投资成本 ⭐
- Grid Cost (万元) - 电网固定成本
- Connection Cost (万元) - 直连成本
- Market Revenue (万元) - 市场收益
- Objective (万元) - 目标函数值
- Wind (MW) - 风电容量
- PV (MW) - 光伏容量
- Storage (MWh) - 储能容量
- Grid (MW) - 电网容量

### 3. theta敏感性分析 (`plot/sensitivity_theta.xlsx`)

参数范围：最小RE发电比 0.1 - 0.9（每0.1一步）

**导出的列**：
- Min RE Generation Ratio - 最小RE发电比
- Unit Cost (元/kWh) - 单位电价
- **Investment Cost (万元)** - 年化投资成本 ⭐
- Grid Cost (万元) - 电网固定成本
- Connection Cost (万元) - 直连成本
- Market Revenue (万元) - 市场收益
- Objective (万元) - 目标函数值
- Wind (MW) - 风电容量
- PV (MW) - 光伏容量
- Storage (MWh) - 储能容量
- Grid (MW) - 电网容量

## 关键成本项解释

### 投资成本 (c_inv)
```
c_inv = CRF × (λ_WT × x_WT + λ_PV × x_PV + λ_ST × x_ST + λ_GD × x_GD)
```
- CRF = 0.1019（资本回收因子）
- λ_i = 各设备单位价格（万元/MW或万元/MWh）
- x_i = 各设备装机容量

### 电网成本 (c_grid)
```
c_grid = M × (μ_DC × x_GD + 730 × μ_ELE × x_GD × L_bar)
```
- M = 12（年月数）
- μ_DC = 需量电价（万元/MW/月）
- μ_ELE = 电价（万元/MWh）

### 直连成本 (c_conn)
```
c_conn = ν × D
```
- ν = 单位直连价格（万元/km）
- D = 直连距离（km）

### 市场收益 (rev_mkt)
```
rev_mkt = Σ_t μ_MKT_t[t] × p_GD_U[t]
```
- μ_MKT_t[t] = 市场电价（万元/MWh）
- p_GD_U[t] = 向电网售电功率

## 单位电价计算

```
c_ele = (c_inv + U × (c_grid + c_conn - rev_mkt)) / (U × total_load)

其中：
- U = 25（利用小时数）
- total_load = 全年总负荷（MWh）
```

## 使用Excel数据进行分析

### 在Excel中进行的操作

1. **绘制曲线图**
   - 选择参数列和单位电价列
   - 插入XY散点图或折线图

2. **成本分解分析**
   - 比较投资成本、电网成本、直连成本的变化趋势
   - 分析哪个成本分量最敏感

3. **容量规划分析**
   - 查看不同参数下各类设备的装机容量变化
   - 理解约束条件对设备配置的影响

4. **目标函数分析**
   - 验证目标函数值与单位电价的一致性

## 技术细节

### 为什么需要这些数据

1. **投资成本是关键指标**
   - 反映年化投资支出
   - 直接影响项目经济性
   - 设备配置决策的基础

2. **成本分解很重要**
   - 不同参数下成本结构不同
   - 帮助找到经济最优点
   - 支持决策制定

3. **容量数据的价值**
   - 反映系统规划的合理性
   - 不同约束下的权衡关系
   - 指导实际工程设计

## 文件输出位置

所有数据文件保存在 `plot/` 文件夹：
```
plot/
├── sensitivity_D.xlsx          # D参数敏感性分析
├── sensitivity_phi.xlsx        # phi参数敏感性分析
├── sensitivity_theta.xlsx      # theta参数敏感性分析
├── D_vs_c_ele.png             # D参数图表
├── phi_vs_c_ele.png           # phi参数图表
└── theta_vs_c_ele.png         # theta参数图表
```

## 运行方法

```bash
python green_power_opt.py
```

程序将自动生成所有图表和Excel文件。

---

**更新日期**：2026-05-17  
**功能**：敏感性分析数据导出  
**格式**：Excel(.xlsx) + PNG(图表)
