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
### [2025-01-16] Stage 2 Sensitivity Deepening
*   **Run ID**: `stage2_sensitivity`
*   **关键发现 1: 物理墙 (The Physical Wall)**
    *   **现象**: 在 800G @ 400 Conns 高压下，当 Buffer < 0.6x BDP 时，无论 ECN 如何设置，丢包率均 > 40%，且 P99 FCT 极高。
    *   **结论**: 存在硬物理约束。小缓存无法吸收微突发，算法优化无效。
*   **关键发现 2: UEC 的带宽-延时交换 (Trade-off)**
    *   **现象**: 在 Buffer > 1.0x BDP 的“安全区”，最佳性能点（低 FCT）往往伴随着较高的 Trim Rate (~50%)。
    *   **机制**: UEC 通过主动剪裁 (Trimming) 来换取低排队延迟。**高 Trim Rate 是机制生效的特征，而非故障**。
*   **黄金配置 (Golden Config)**:
    *   `queue_size_bdp_factor` > 1.0
    *   `ecn_high` ≈ 0.6 - 0.8
    *   `ecn_low` ≈ 0.2 - 0.4 (需保持 gap)
*   **下一步**: 验证动态 ECN 是否能自动收敛到该区域。

### [2025-01-16] Stage 2.5 Scalability Test (The Breaking Point?)
*   **Run ID**: `stage2.5_scalability`
*   **配置**:
    *   **Baseline**: Queue=1.0 BDP (Safe Zone), ECN=0.5
    *   **Variable**: Incast Degree (Conns) [16 -> 420]
*   **现象 (See Plot)**:
    *   **FCT 线性增长**: P99 FCT 随并发数呈现完美的线性上升 (0.2ms -> 4.5ms)，**没有出现指数级崩塌 (Crash)**。
    *   **高 Trim Rate**: 即使在低并发下，Trim Rate 也维持在 30%-60% 的高位。
*   **关键结论**:
    1.  **没有悬崖**: 在 Queue=1.0 BDP 的黄金配置下，UEC 协议成功支撑住了直到物理极限 (420/432 nodes) 的 Incast 压力。
    2.  **Trim = Stability**: 图中红色的高 Trim Rate 反而是系统稳定的证明。UEC 通过及其激进的丢包（裁剪），避免了长尾延迟的失控。**它把“拥塞”转化为了“重传开销”，而不是“排队延迟”。**
    3.  **容量验证**: 400G 网络承载 500KB Incast 的物理极限是线性的，未见吞吐量黑洞。

---

## 4. 结论 (Conclusions)

*(研究结束后汇总)*
