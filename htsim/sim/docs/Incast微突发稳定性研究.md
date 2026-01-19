# 高并发推理场景下的 Incast 微突发稳定性研究

**创建时间**: 2025-01-15 (更新: 2026-01-19)
**状态**: 深度优化中 (Deep Dive)

本文档用于记录关于 **LLM Inference Incast Micro-burst** 的完整研究过程，包括研究假设、实验设计、数据发现、根因分析及最终结论。

---

## 1. 研究背景与核心假设

### 1.1 背景
在 LLM Tensor Parallelism (TP) 推理过程中，`AllReduce` 通信模式的最后阶段（Reduce-Scatter / All-Gather）会产生典型的 **Incast (多对一)** 流量。
虽然单个流的数据量不大（KB级），但在大规模集群（64+ GPU）中，这些流**同时**到达接收端 Switch，形成瞬间流量尖峰（Micro-burst）。

### 1.2 核心目标 (Objective)
通过基于 UEC (Ultra Ethernet Consortium) 架构的改进，实现对微突发流量的**端到端延迟（FCT）最小化**。
- **安全边界**：必须消除由尾部丢包（Tail Loss）导致的长尾延迟（RTO）。
- **性能边界**：在保证安全的前提下，尽可能提高链路利用率，降低平均延迟。

### 1.3 核心假设 (Research Hypothesis)
> 在低延迟（浅 Buffer）的高速网络中，存在一个 **"临界 Incast 度"** 或 **"临界 Buffer/BDP 比"**。
> 一旦突破该临界点，无论 ECN 阈值如何设置，p99 FCT (尾延迟) 都会指数级恶化。
> **根因**：微突发填满 Buffer 的速度快于拥塞控制算法（CC）生效并降速的速度，导致必然的丢包与超时。

---

## 2. 实验设计路线图

### Step 1: 广域扫描 (The Broad Search) - Baseline
**目标**: 确定 "Crash Boundary"（崩溃边界）。
*   **关键参数**: `incast`, `flowsize`, `linkspeed`, `queue_size_bdp_factor`.
*   **方法**: 使用 `Response Surface` 寻找 p99_fct 突变的“悬崖”。

### Step 2: 深度单点验证 (The Deep Dive)
**目标**: 捕捉微突发发生的瞬间动态。
*   **操作**: 选取悬崖边缘点，扫描 `Conns` [32, 64, 128]。
*   **观测**: 使用 `plot_queue` 观察队列波形。

### Step 3: 算法优化与干预 (Optimization)
**目标**: 通过改进拥塞控制参数（ECN / Sleek）消除长尾延迟。

---

## 3. 实验记录与发现 (Living Log)

### 3.1 [2025-01-15] Stage 1 Baseline 启动
*   **Run ID**: `stage1_core`
*   **结果**: 完成 150 组 LHS 采样，确定了初步的参数敏感度。

### 3.2 [2025-01-16] Stage 2 Sensitivity Deepening
*   **Run ID**: `stage2_sensitivity`
*   **发现 1 (物理墙)**: Buffer < 0.6x BDP 时，丢包不可避免。
*   **发现 2 (Sleek有效性)**: UEC 的 Trimming 机制能有效将拥塞转化为重传开销，而非排队延迟。

### 3.3 [2025-01-19] Stage 3: ECN Deep Dive (The ECN Journey)
**(本节详细记录了针对 Conns=64 尖峰问题的攻坚过程)**

为了定位问题并寻找优化空间，我们进行了一系列的渐进式实验。

#### 3.3.1 初始探索：Incast 规模的影响
*   **实验配置**：`001-incast-scalability.yaml`
*   **现象**：当并发连接数 `conns=64` 时，尾部延迟（P99/Max）出现剧烈跳变（图1中红线所示）。其他并发度下表现则较为线性。
*   **诊断**：确认为 **尾部丢包 (Tail Loss)**。拥塞导致拥塞窗口（cwnd）降至 1 MSS，后续无新包触发 ACK，不仅吞吐受损，更导致长达数毫秒的 RTO 等待。

![Baseline Incast Spike](.assets/fig1_incast_baseline.png)
*图1：基线 Incast 扩展性测试。conns=64 处出现明显尖峰。*

#### 3.3.2 参数扫描与 Sleek 机制的发现
*   **实验配置**：`001a-调整randseed-锁定事故点.yaml`
*   **验证**：通过扫描随机种子，确认为系统性问题而非单纯的 Hash 冲突（图2红线）。
*   **Sleek 机制对比**：启用 UEC 代码中的 Sleek 机制后（图2绿线），尖峰完全消失。
*   **局限性**：虽然 Sleek 解决了不稳定性（Safety），但其平均 FCT 显著高于未启用时的基线水平。这意味着它通过牺牲一定的“激进性”换取了“稳定性”。

![Sleek vs Baseline](.assets/fig2_randseed_spikes.png)
*图2：Baseline（红）与 Sleek（绿）对比。Sleek 削平了尖峰，但整体水位上升。*

#### 3.3.3 “甜点区” (Sweet Spot) 的假设
*   **实验配置**：`001a1-测试默认设置.yaml`
*   **发现**：UEC 的默认配置（特定的 ECN 阈值 + 目标队列延迟）意外地达到了**“既稳又快”**的效果——既没有长尾尖峰，平均延迟也保持在低位。
*   **推论**：存在一组参数（特别是 ECN），可以在不依赖重型机制（如 Sleek）的情况下解决尾部丢包问题。

![Default Settings](.assets/fig3_sleek_comparison.png)
*图3：默认配置下的性能表现，达到了理想的平衡点。*

#### 3.3.4 关键变量控制：ECN 阈值
*   **实验配置**：`001c-测试不同ecn阈值.yaml`
*   **测试**：剥离其他变量，仅调整 ECN 阈值。
*   **现象**：系统对 ECN 阈值表现出**极高的敏感性**。看似接近的阈值（如 `0.08` 与 `0.0806`）会导致截然不同的性能结果（图4）。这表明最佳工作点可能是一个非常狭窄的“峡谷”，而非宽阔的平原。

![Coarse ECN Sweep](.assets/fig4_ecn_sweep_coarse.png)
*图4：不同 ECN 设置下的性能方差极大。*

#### 3.3.5 精细化 ECN 分析
*   **实验配置**：`001c1-控制变量确认ecn阈值效果.yaml`
*   **结论**：较低的阈值（如 `0.05 0.2`）在该场景下表现最佳（图5）。
*   **机理**：提前的拥塞感知（Early Brake）在队列积压形成“悬崖”（丢包）之前介入，避免了 RTO，同时又不像 Sleek 那样过度保守。

![Detailed ECN Sweep](.assets/fig5_ecn_sweep_detailed.png)
*图5：ECN 阈值精细对比。较低的阈值 (0.05 0.2) 表现最优。*

---

## 4. 逻辑衔接与第一性原理 (Bridging the Gap)

### 4.1 为什么要回到 LHS？(The Logic Link)
目前的实验处于一个尴尬的节点：
*   **Stage 1 (LHS)**: 我们做了一次粗略的广度扫描，发现了问题（悬崖）。
*   **Stage 3 (Deep Dive)**: 我们钻进一个具体的点 (`conns=64`)，通过手动调参找到了一个解 (`ECN=0.05 0.2`)。

**但这个解是通用的吗？**
我们还是不知道：
1.  如果 Buffer 变小了 (e.g. 0.5 BDP)，这个 ECN 参数是否会导致吞吐崩塌？
2.  如果 Incast 规模变大了 (e.g. 128 Nodes)，这个 ECN 是否还压得住排队？

**衔接逻辑**: 我们已经从“大海捞针”（找故障）阶段，进入了“地图测绘”（找安全边界）阶段。我们需要用 LHS 这种高维扫描工具，不是为了“瞎撞运气”，而是为了**量化我们找到的这个“解”的鲁棒性边界**。

### 4.2 核心矛盾 (The Core Conflict)
微突发优化的本质是在**激进 (Efficiency)** 与 **保守 (Robustness)** 之间寻找平衡。
*   **激进 (Baseline)**：追求带宽打满，但缓冲容忍度低，易发生尾部丢包（RTO）。
*   **保守 (Sleek)**：通过严格的检查和回退避免丢包，但增加了处理开销和延迟基数。
*   **新平衡点 (Optimized ECN)**：我们试图找到中间态——既不丢包，也不过度回退。

### 4.3 缺口分析 (Gap Analysis)
虽然找到了 `0.05 0.2` 这一组好参数，但仍存在以下缺口：
1. **全局最优性**：这是全局最优解，还是局部最优解？当前的“人工猜测”可能遗漏了更好的组合。
2. **场景耦合性**：最佳 ECN 阈值大概率与 `queue_size`（物理缓冲区大小）强耦合。当前的静态设置可能无法适应不同 Buffer 大小的交换机。

---

## 5. 下一步策略：鲁棒性制图 (Next Steps: Robustness Mapping)

我们不再进行盲目的 LHS 扫描，而是进行 **Targeted LHS (靶向正交实验)**。

1. **构建假设空间**: 
    *   以 `ECN=0.05 0.2` 为中心，向四周发散扫描。
    *   引入干扰变量 `queue_size` (0.5x - 2.0x BDP) 和 `load` (30% - 80%)。

2. **响应曲面建模 (Response Surface)**: 
    *   **目标**: 绘制出“安全区”（Zero Loss & Low Latency）的等高线图。
    *   **预期产出**: 一个经验公式 $ECN_{optimal} = f(Buffer, Load)$。

3. **极限压力测试**: 
    *   只在模型预测的“最危险边缘”进行大规模 (Conns=128+) 验证。
