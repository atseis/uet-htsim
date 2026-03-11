---
name: run-experiments
description: |
  Standard workflow for running htsim simulator experiments after code changes.
  Ensures all tests are based on actual simulation data, not speculation.
  Provides test templates for different scenarios (smoke tests, comparisons, sensitivity analysis).
---

# 🧪 htsim 模拟器实验运行工作流 (Simulator Testing Workflow)

**核心原则**：**实事求是** - 所有测试结论必须基于实际运行的模拟数据，禁止"靠猜"或编造数据。

**适用场景**：
- ✅ Bug 修复后验证修复效果
- ✅ 新功能开发后对比性能
- ✅ 参数调优后寻找最优配置
- ✅ 代码重构后确保无回归

---

## 🔑 核心原则 (NON-NEGOTIABLE)

1. **必须实际运行实验** - 不能跳过模拟步骤
2. **必须基于真实数据** - 结论必须有 summary.json 或 DataFrame 支撑
3. **结论必须附带证据** - 图表保存到 `.sisyphus/evidence/` 目录
4. **禁止编造数据** - 不能"估计"或"推测"性能指标

---

## 📋 完整测试工作流

### Step 1: 确定测试类型

根据修改类型选择测试策略：

| 修改类型 | 推荐测试 | 置信度 | 预期时间 | 运行命令 |
|---------|---------|--------|---------|---------|
| **Bug Fixes** | Seed Sensitivity (11+ seeds) | High if variance < 2× | 10-20 min | `python run.py experiments/seed-sensitivity.yaml` |
| **New Features** | Fast Comparison → ECN Tuning → Seed Sensitivity | Medium → High | 30-60 min | Sequential execution |
| **Performance Optimizations** | Smoke → Fast Comparison → Full Scalability | Scales with tier | 5-60 min | Tiered approach |
| **Parameter Tuning** | LHS Robustness Scan (200 samples) | Very High | 2-4 hours | `python run.py experiments/lhs_scan.yaml` |

### Step 2: 准备 YAML 配置

**选项 A: 使用现有配置**
```bash
ls experiments/*.yaml
```

**选项 B: 从 AtomicRecords 复制配置**
```bash
# AtomicRecords/Processed/ 目录中查找 config 卡片
grep -r "type: config" AtomicRecords/ --include="*.md" | head -5
```

**选项 C: 基于模板创建新配置** (参考下方"测试模板"章节)

### Step 3: 编译代码

```bash
cmake -S . -B out/Debug -DCMAKE_BUILD_TYPE=Debug
make --directory=out/Debug -j$(nproc)
```

### Step 4: 运行实验

```bash
micromamba run -n sim python run.py experiments/my-test.yaml
micromamba run -n sim python run.py experiments/my-test.yaml --force
micromamba run -n sim python run.py experiments/my-test.yaml --continue
```

### Step 5: 查看结果

**结果位置**: `results/{experiment-name}/{params}/`

```bash
cat results/my-comparison/*/status.yaml | grep status
cat results/my-comparison/*/summary.json | jq '{p99_fct, median_fct, max_fct}'
```

### Step 6: 数据分析与可视化

```python
from analysis.data.batch import BatchResult

batch = BatchResult()
batch.add_source("experiments/my-test.yaml", tags={'version': 'v2'})

# 智能分析建议
batch.suggest()

# 获取汇总数据
df = batch.get_summary_df(['p99_fct', 'median_fct', 'max_drop_rate'])
print(df)

# 可视化
batch.viz.plot_statistical_summary(
    x='randseed',
    hue='sleek',
    metrics=['max_fct', 'p99_fct', 'median_fct'],
    title='Sleek Impact on FCT'
)
```

---

## 📦 测试模板库

### 模板 1: 快速冒烟测试 (Smoke Test) - <1 分钟

**目的**: 验证代码能编译、能运行、无崩溃

```yaml
# experiments/smoke-test.yaml
common:
  execute: True
  traffic:
    type: incast
    nodes: 8
    conns: 4
    flowsize: "100KB"
    randseed: 42
  simulation:
    tiers: 2
    linkspeed: 100000
    end: 500
    log: [sink, flow_events]

experiments:
  - name: smoke-test
    exe: htsim_uec
    simulation:
      sleek: [False]
      ecn: "20p 80p"
```

### 模板 2: 快速对比测试 (Fast Comparison) - 2-5 分钟

**目的**: 对比 2-3 种配置，识别明显优劣

```yaml
# experiments/fast-comparison.yaml
common:
  traffic:
    nodes: 64
    conns: [32, 64]
    flowsize: "50KB"
    randseed: [1, 2, 3]
  simulation:
    end: 1000
    log: [sink, flow_events]

experiments:
  - name: algo-comparison
    exe: htsim_uec
    simulation:
      sender_cc_algo: [nscc, dcqcn]
      sleek: [False, True]
```

### 模板 3: 随机种子鲁棒性测试 (Seed Sensitivity) - 10-20 分钟

**目的**: 验证修改在不同 ECMP 哈希结果下的稳定性

```yaml
# experiments/seed-sensitivity.yaml
common:
  traffic:
    nodes: 432
    conns: [64]
    flowsize: "50KB"
    randseed: [1, 5, 10, 15, 20, 25, 30, 35, 40, 45, 50]
  simulation:
    end: 2000
    log: [sink, flow_events, queue_usage]

experiments:
  - name: robustness-check
    exe: htsim_uec
    simulation:
      sleek: [False, True]
```

### 模板 4: ECN 阈值调优 (ECN Tuning) - 5-15 分钟

**目的**: 寻找最优 ECN 标记阈值

```yaml
# experiments/ecn-tuning.yaml
common:
  traffic:
    nodes: 432
    conns: [64, 96]
    flowsize: "50KB"
    randseed: [4]
  simulation:
    end: 2000
    log: [sink, flow_events, queue_usage]

experiments:
  - name: ecn-sweep
    exe: htsim_uec
    simulation:
      ecn: ["0.03 0.12", "0.05 0.20", "0.08 0.32", "0.10 0.40", "0.20 0.80"]
```

### 模板 5: 针对性调试运行 (Targeted Debug) - 深度诊断

**目的**: 深度诊断特定失败案例

```yaml
# experiments/D_debug-specific.yaml
common:
  simulation:
    debug: true
    debug_flowid: 24
    logtime: 0.01
    log: [sink, flow_events, tor_downqueue, traffic, nic, queue_usage]

experiments:
  - name: diag-conns64-seed4
    exe: htsim_uec
    traffic:
      conns: 64
      randseed: 4
```

### 模板 6: 复现运行 (Reproduction Run)

**目的**: 复现 Paper/实验结果

```yaml
# 从 AtomicRecords 复制配置
# 或使用 export_config() 生成的配置
```

---

## 📊 分析 API 快速参考

### ExperimentResult (单体实验)

```python
from analysis.data.fileinfo import ExperimentResult

res = ExperimentResult("results/path/")

# DataFrames
res.flow_df           # Flow events
res.queue_df          # Queue sampling
res.traffic_df        # Packet trace
res.cwnd_df           # CWND trace

# Metrics
res.get_cached_metric('p99_fct')
res.get_cached_metric('max_drop_rate')
res.get_cached_metric('fairness_index')

# Tools
res.report.show()        # AutoVisualizer
res.export_config()      # Generate reproduction YAML
res.diagnose_deadlock()  # Check for deadlocks
```

### BatchResult (批量实验)

```python
from analysis.data.batch import BatchResult

batch = BatchResult()
batch.add_source("experiments/test.yaml", tags={'version': 'v2'})

# Filtering
subset = batch.filter(conns=[64, 128])
subset = batch.filter(linkspeed=lambda x: x > 100000)

# Analysis
df = batch.get_summary_df(['p99_fct', 'max_drop_rate'])
batch.aggregate(groupby=['version'], metrics=['p99_fct'])

# Smart Tools
batch.suggest()                # Auto-recommend analysis
batch.diagnose_failure_modes() # Detect Bufferbloat, Collapse, Tail
```

### BatchVisualizer

```python
batch.viz.plot_pivot(x='randseed', y='p99_fct', hue='version', kind='line')
batch.viz.plot_statistical_summary(x='conns', hue='version', metrics=['max_fct','p99_fct','median_fct'])
batch.viz.plot_distribution(y='p99_fct', kind='box')
batch.viz.plot_fct_cdf_overlap(hue='version')
batch.viz.plot_tradeoff(x='conns', y1='p99_fct', y2='max_drop_rate')
batch.viz.plot_response_surface(x='ecn_low', y='ecn_high', z='p99_fct')
batch.viz.analyze_feature_importance('p99_fct', top_n=10)
```

---

## 🔍 典型分析模式

### 模式 1: A/B 版本对比

```python
batch = BatchResult()
batch.add_source("experiments/ab-test.yaml")

df = batch.get_summary_df(['p99_fct', 'median_fct', 'max_fct'])
print(df.groupby('version').mean())

batch.viz.plot_statistical_summary(
    x='randseed',
    hue='version',
    metrics=['max_fct', 'p99_fct', 'median_fct']
)

batch.viz.plot_fct_cdf_overlap(hue='version')
```

### 模式 2: 参数敏感性分析

```python
batch = BatchResult()
batch.add_source("results/sensitivity_conns/")

factors = batch.get_varying_params()
batch.suggest()

batch.viz.plot_pivot(x='conns', y='p99_fct', kind='line', ref_line=500)
```

### 模式 3: 双因子交互 (Heatmap)

```python
batch = BatchResult()
batch.add_source("results/ecn_sweep/")

batch.viz.plot_pivot(
    x='ecn_low',
    hue='ecn_high',
    y='p99_fct',
    kind='heatmap'
)
```

### 模式 4: 根因分析 (Drill-Down)

```python
worst = batch.get_worst_experiment(metric='max_fct')
config_path = worst.export_config()
worst.report.show()
```

---

## ⚠️ 故障排查

### 错误 1: 找不到二进制文件

```
FileNotFoundError: out/Debug/htsim_uec not found
```

**解决**: `cmake -S . -B out/Debug && make --directory=out/Debug -j$(nproc)`

### 错误 2: Python 环境错误

```
ModuleNotFoundError: No module named 'pandas'
```

**解决**: `micromamba run -n sim python run.py experiments/test.yaml`

### 错误 3: 实验状态失败

**解决**: 查看 stdout.log 和 output.log，简化配置重试

### 错误 4: 结果加载失败

```
[!] No valid experiments found in results/...
```

**解决**: 确认 status.yaml 包含 `status: success`

### 错误 5: 图表不显示

**解决**: 确认数据已加载，参数匹配

---

## 📈 YAML 参数参考

### Traffic 参数

| 参数 | 说明 | 典型值 | 快速测试值 |
|------|------|--------|-----------|
| `nodes` | 服务器总数 | 432 | 8-16 |
| `conns` | Incast 连接数 | 64, 96, 128 | 4-8 |
| `flowsize` | 流大小 | "50KB", "1MB" | "100KB" |
| `randseed` | 随机种子 | 1-50 | 42 |

### Simulation 参数

| 参数 | 说明 | 典型值 | 快速测试值 |
|------|------|--------|-----------|
| `tiers` | 拓扑层级 | 3 | 2 |
| `linkspeed` | 链路速度 (Mbps) | 100000 | 100000 |
| `end` | 模拟时长 (μs) | 2000 | 500 |
| `logtime` | 日志采样间隔 (s) | 0.1 | 1.0 |

### Protocol 参数

| 参数 | 说明 | 典型值 |
|------|------|--------|
| `sleek` | 是否启用 Sleek | True/False |
| `ecn` | ECN 阈值 | "20p 80p", "0.05 0.20" |
| `queue_size_bdp_factor` | 队列大小 BDP 倍数 | 8 |

---

## 🔗 相关 Skills

- [[compile-simulator]] - 编译 htsim 模拟器标准流程
- [[run-python-scripts]] - 在正确的 micromamba 环境中运行 Python
- [[atomic-records]] - 实验结果原子化记录与分析

---

## 版本信息

- **最后更新**: 2026-03-11
- **适用项目**: htsim UEC 协议模拟器
- **维护者**: 项目基础设施规范
