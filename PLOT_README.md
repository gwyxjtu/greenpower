# 参数敏感性分析和绘图功能

## 概述

该项目已添加参数敏感性分析功能，在运行优化后自动生成三张关键参数对单位电价的影响图表。

## 新增功能

### 1. D-c_ele 图表（直连距离的影响）
- **参数范围**：10-80 km，每10 km一步
- **纵轴**：单位电价（元/kWh）
- **输出**：`plot/D_vs_c_ele.png`
- **说明**：展示直连距离增加对成本的影响

### 2. phi-c_ele 图表（可再生能源自消比的影响）
- **参数范围**：0.1-0.9，每0.1一步
- **纵轴**：单位电价（元/kWh）
- **输出**：`plot/phi_vs_c_ele.png`
- **说明**：展示最小自消比对成本的影响

### 3. theta-c_ele 图表（可再生能源发电比例的影响）
- **参数范围**：0.1-0.9，每0.1一步
- **纵轴**：单位电价（元/kWh）
- **输出**：`plot/theta_vs_c_ele.png`
- **说明**：展示最小发电比例对成本的影响

## 使用方法

运行优化程序：

```bash
python green_power_opt.py
```

程序将按顺序执行：
1. **第一步**：基础优化 - 使用默认参数运行完整优化
2. **第二步**：敏感性分析 - 自动扫描三个关键参数并生成图表
3. **输出**：所有图表自动保存到 `plot/` 文件夹

## 参数调整

### 修改参数范围和步长

在 `run_sensitivity_analysis()` 函数中修改以下行：

```python
# D 值范围（km）
D_values = np.arange(10, 90, 10)  # 改为需要的范围

# phi 值范围（0-1）
phi_values = np.arange(0.1, 1.0, 0.1)  # 改为需要的范围

# theta 值范围（0-1）
theta_values = np.arange(0.1, 1.0, 0.1)  # 改为需要的范围
```

### 修改参数默认值

在 `params.py` 中修改对应的默认参数：

```python
D = 50.0      # 直连距离（km）
phi = 0.6     # 最小RE自消比
theta = 0.3   # 最小RE发电比例
```

## 输出说明

- **图表格式**：PNG格式，300 DPI 高分辨率
- **保存位置**：`plot/` 文件夹
- **命名规则**：`{参数}_vs_c_ele.png`

## 技术细节

### 单位电价计算公式

```
c_ele = (c_inv + U * (c_grid + c_conn - rev_mkt)) / (U * total_load)
```

其中：
- `c_inv`：年化投资成本（万元）
- `c_grid`：电网固定成本（万元）
- `c_conn`：直连成本（万元）
- `rev_mkt`：市场收益（万元）
- `U`：利用小时数（25h）
- `total_load`：全年总负荷（MWh）

### 优化器设置（敏感性分析）

为了加速敏感性分析，使用以下设置：

```python
model.setParam('OutputFlag', 0)  # 关闭求解器输出
model.setParam('MIPGap', 0.01)   # 1% 优化间隙
model.setParam('TimeLimit', 300)  # 300秒时限
```

## 故障排除

### 绘图保存失败

确保：
1. 工作目录有写入权限
2. `plot` 文件夹已创建（程序会自动创建）
3. matplotlib 已正确安装

### 优化超时

如果某个参数值的优化超时，程序会跳过该点并继续。检查：
- 模型的可行性
- 约束条件是否冲突
- 参数范围是否过大

## 依赖项

```
gurobipy
numpy
matplotlib
```

安装：
```bash
pip install gurobipy numpy matplotlib
```
