# 高并发推理场景下的 Incast 微突发稳定性研究

**创建时间**: 2025-01-15
**状态**: 进行中 (Phase 1)

本文档用于记录关于 **LLM Inference Incast Micro-burst** 的完整研究过程，包括研究假设、实验设计、数据发现、根因分析及最终结论。

---

## 1. 研究背景与核心假设

### 1.1 背景
在 LLM Tensor Parallelism (TP) 推理过程中，`AllReduce` 通信模式的最后阶段（Reduce-Scatter / All-Gather）会产生典型的 **Incast (多对一)** 流量。
虽然单个流的数据量不大（KB级），但在大规模集群（64+ GPU）中，这些流**同时**到达接收端 Switch，形成瞬间流量尖峰（Micro-burst）。

### 1.2 核心假设 (Research Hypothesis)
> 在低延迟（浅 Buffer）的高速网络中，存在一个 **"临界 Incast 度"** 或 **"临界 Buffer/BDP 比"**。
> 一旦突破该临界点，无论 ECN 阈值如何设置，p99 FCT (尾延迟) 都会指数级恶化。
> **根因**：微突发填满 Buffer 的速度快于拥塞控制算法（CC）生效并降速的速度，导致必然的丢包与超时。

---

## 2. 实验设计路线图

### Step 1: 广域扫描 (The Broad Search) - Baseline
**目标**: 确定 "Crash Boundary"（崩溃边界），即系统从稳定转为不稳定的临界参数区域。

*   **配置文件**: `experiments/LHS_tests/stage1-core-exploration.yaml`
*   **关键参数**:
    *   `traffic`: `incast` (Nodes=432, Conns=64)
    *   `flowsize`: `[10KB, 5MB]` (Log-uniform sampling)
    *   `linkspeed`: `[25G, 400G]`
    *   `queue_size_bdp_factor`: `[0.5, 5.0]` (重点关注 < 1.0 的区域)
*   **分析方法**:
    *   使用 `Response Surface` 绘制 `p99_fct` vs `queue_size` 图，寻找颜色突变的“悬崖”。
    *   验证在悬崖外侧，调节 `ecn_high` 是否失效。

### Step 2: 深度单点验证 (The Deep Dive)
**目标**: 捕捉微突发发生的瞬间动态，验证 "Buffer 填满速度 > CC 响应速度" 的假设。

*   **操作**: 选取 Step 1 中位于“悬崖边缘”的配置（例如 `queue=1.0 BDP` 时好时坏的点）。
*   **变量控制**: 固定其他参数，仅扫描 `Conns` (Incast度) `[32, 64, 128]`。
*   **观测手段**:
    *   开启高频日志: `log: [flow_events, queue_usage, switch]`
    *   利用 `plot_queue.ipynb` 观察队列波形：寻找“垂直升降”特征（Micro-burst）。

### Step 3: 算法优化与干预 (Optimization)
**目标**: 通过改进协议逻辑消除长尾延迟。

*   **潜在方案**:
    1.  **Sender-side Pacing**: 减缓突发发送速率。
    2.  **Dynamic ECN / Fast Start**: 提高 CC 对队列梯度的敏感度。

---

## 3. 实验记录与发现 (Living Log)

*(在此处记录每次实验的 ID、日期、关键发现图表与结论)*

### [2025-01-15] Stage 1 Baseline 启动
*   **Run ID**: `stage1_core`
*   **配置概览**: 150 组 LHS 采样，涵盖 Incast 场景。
*   **预期**: ...

---

## 4. 结论 (Conclusions)

*(研究结束后汇总)*
