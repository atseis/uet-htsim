# LHS 实验批次说明

本目录包含分阶段的 Latin Hypercube Sampling (LHS) 实验配置，用于系统性探索 htsim 参数空间。

## 实验设计原则

1. **分批进行**：参数过多（20+），分 3-4 阶段逐步探索
2. **核心变量优先**：每阶段都包含核心变量（queuesize, ECN 阈值, cwnd, hop_latency, linkspeed）
3. **敏感性驱动**：后续阶段基于前阶段结果，聚焦高敏感参数
4. **约束处理**：ECN 阈值满足 `ecn_low < ecn_high` 约束

## 阶段说明

### Stage 1: 初步筛选 (`stage1-core-exploration.yaml`)
- **目标**：获得整体参数敏感性，识别主效应和交互
- **维度**：6-8
- **样本数**：150
- **核心变量**：
  - `queue_size_bdp_factor`: [1.0, 10.0]
  - `ecn_low`: [0.05, 0.3] (相对 queuesize 比例)
  - `ecn_high`: [0.4, 0.8] (相对 queuesize 比例)
  - `cwnd`: [10, 100] (整数)
  - `hop_latency`: [0.1, 10.0] (us)
  - `linkspeed`: [10000, 100000] (Mbps)
- **离散变量**：
  - `queue_type`: [composite, composite_ecn, aeolus, aeolus_ecn]
  - `strat`: [ecmp_host, ecmp_host_ecn, reactive_ecn]

### Stage 2: 敏感性深化 (`stage2-sensitivity-deepening.yaml`)
- **目标**：基于阶段 1 结果，聚焦高敏感变量，测试交互
- **维度**：8-10
- **样本数**：250
- **新增变量**：
  - `mtu`: [1500, 9000] (bytes)
  - `target_q_delay`: [1.0, 20.0] (us)
  - `load_balancing_algo`: [mixed, reps, bitmap]
  - `sender_cc_algo`: [nscc, dctcp]
  - `sleek`: [False, True]

### Stage 3: 扩展与条件测试 (`stage3-extension-conditional.yaml`)
- **目标**：探索边缘场景，如故障或 AR
- **维度**：10-12
- **样本数**：300
- **新增变量**：
  - `failed`: [0, 10] (整数，失败链接数)
  - `paths`: [1, 128] (整数，路径熵大小)
  - `tiers`: [2, 3] (离散)
  - `planes`: [1, 2, 4] (离散)
  - `trimsize`: [64, 1500] (bytes, 条件于 disable_trim=false)

### Stage 4: 验证与优化 (`stage4-validation.yaml`)
- **目标**：验证高影响组合，优化参数（Pareto 前沿）
- **维度**：5-8
- **样本数**：200
- **注意**：此阶段应基于前 3 阶段的敏感性分析结果，仅包含高敏感参数，范围已精炼

## ECN 阈值特殊处理

ECN 阈值已修改为相对 `queuesize` 的比例（见 `main/main_uec.cpp:705-717`）。

### 离散情况（默认）
```yaml
simulation:
  ecn: "0.2 0.8"                    # 单个字符串
  # 或
  ecn: ["0.2 0.8", "0.1 0.6", ...]  # 字符串列表
```

### 连续情况（LHS 采样）
```yaml
sampling:
  continuous: [ecn_low, ecn_high]

simulation:
  ecn_low: [0.05, 0.3]    # 低阈值范围（相对 queuesize 比例）
  ecn_high: [0.4, 0.8]    # 高阈值范围（相对 queuesize 比例）
```

系统会自动：
1. 对 `ecn_low` 和 `ecn_high` 分别进行 LHS 采样
2. 确保约束 `ecn_low < ecn_high`（如果违反会自动调整）
3. 在 `build_flags` 中合成 `-ecn low high` 命令行参数

## 运行方式

```bash
# 阶段 1
python run.py experiments/LHS_tests/stage1-core-exploration.yaml

# 阶段 2（需先完成阶段 1 并分析结果）
python run.py experiments/LHS_tests/stage2-sensitivity-deepening.yaml

# 阶段 3
python run.py experiments/LHS_tests/stage3-extension-conditional.yaml

# 阶段 4（可选，基于前阶段敏感性分析）
python run.py experiments/LHS_tests/stage4-validation.yaml
```

## 数据分析

每个阶段完成后，使用 `BatchResult` 进行敏感性分析：

```python
from analysis.data.batch import BatchResult

batch = BatchResult()
batch.add_source("experiments/LHS_tests/stage1-core-exploration.yaml")

# 主效应图
batch.viz.plot_main_effects(
    factors=["queue_size_bdp_factor", "ecn_low", "ecn_high", "cwnd"],
    metric="max_fct",
    agg="mean"
)

# 平行坐标图
batch.viz.plot_parallel_coordinates(
    factors=["queue_size_bdp_factor", "ecn_low", "ecn_high"],
    metrics=["max_fct", "p99_fct"]
)

# 散点矩阵
batch.viz.plot_scatter_matrix(
    columns=["queue_size_bdp_factor", "ecn_low", "ecn_high", "max_fct"]
)
```

## 注意事项

1. **整数参数**：`cwnd`, `failed`, `paths` 等整数参数在 YAML 中应使用整数列表（如 `[10, 100]`），系统会自动识别为整数区间并取整。

2. **约束处理**：ECN 阈值的 `ecn_low < ecn_high` 约束会在采样后自动检查并调整。

3. **条件变量**：某些参数只在特定条件下有效（如 `trimsize` 仅在 `disable_trim=false` 时），需在 YAML 中明确固定条件。

4. **样本数调整**：根据计算资源，可适当调整各阶段的 `samples` 数量。

5. **固定参数**：后续阶段应基于前阶段结果固定低敏感参数，减少维度。
