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
>
> **[Old Hypothesis 2025-01-15]**
> ~~在低延迟（浅 Buffer）的高速网络中，存在一个 **"临界 Incast 度"** 或 **"临界 Buffer/BDP 比"**。~~
> ~~一旦突破该临界点，无论 ECN 阈值如何设置，p99 FCT (尾延迟) 都会指数级恶化。~~
> ~~**根因假设**：微突发填满 Buffer 的速度快于拥塞控制算法（CC）生效并降速的速度，导致必然的丢包与超时。~~
>
> **[Updated Hypothesis 2026-01-20]**
> 1.  **Buffer Inefficacy (物理缓存无效论)**: 对于 Incast 微突发，单纯增加物理缓存（Buffer Size）仅能延缓但无法消除尾部丢包。存在一个 **"Critical Scalability Wall" (临界规模墙)**，一旦并发流数量突破该阈值，任何经济可行的 Buffer 都无法吸收瞬间冲击。
> 2.  **Control Plane Dominance (控制面主导)**: 解决问题的关键不在于物理层（扩容），而在于控制层（准入控制、窗口调节、ECN），必须在突发形成之前将其“抚平”。

---

## 2. 实验设计路线图 (Research Methodology)

本研究采用 **“宏观-微观-宏观” (Macro-Micro-Macro)** 的闭环实验设计，逻辑衔接如下：

### Step 1: 广域扫描 (Preliminary Scan - LHS Stage 1)
>
> **现状评估**: 初步的广度扫描（Stage 1）确实存在信息密度低的问题。
> ![Feature Importance](.assets/stage1_feature_importance.png)
> *图：Stage 1 关键因子重要性排序。*
>
> 如上图所示，`flowsize` 的权重 (0.9+) 碾压了 `linkspeed` 和 `cwnd`。这证实了 **"Masking Effect"（掩蔽效应）**：在大流量混跑背景下，物理属性（发多少数据）主导了结果，拥塞控制等精细参数（Control Parameters）的影响力被完全淹没。这导致我们无法在 Stage 1 看出参数的优劣。
>
> **修正定位**: 既然“大海捞针”不可行，我们**必须切入到特定的微突发场景（Deep Dive）**，剔除 `flowsize` 的干扰，才能看清算法的微观行为。

### Step 2: 深度诊断 (Deep Dive & Diagnostic)

**目标**: 在 Step 1 确定的“高风险区”（即 Incast 场景）进行单点爆破。

- **动作**: 选取 `conns=64` 这一崩溃点，进行显微镜级别的逐包分析（参见 3.3.6 节）。
- **产出**: 发现根因（CWND Collapse）并找到一组局部最优解（Optimal ECN）。

### Step 3: 靶向验证 (Targeted LHS - Robustness Mapping)

**目标**: 解决 Deep Dive 的“过拟合”风险。

- **逻辑**: 在 Step 2 中找到的解（ECN=0.05 0.2）可能只是针对 `conns=64` 的特解。
- **新 LHS 的价值**: 我们不是为了“探索”，而是为了 **“验收”** 。我们需要用 LHS 在 `conns=[32, 128]` 和 `buffer=[0.5x, 2.0x]` 的范围内进行高密度扫描，证明该参数组合能形成一个宽阔的**“安全平原”**，而非站立不稳的“针尖”。
- **可视化方案**: 绘制 `Buffer` vs `ECN` 的 2D 热力图（见后续计划），如果热力图显示出一大片绿色区域，则证明方案鲁棒。

---

## 3. 实验记录与发现 (Living Log)

### 3.1 [2025-01-15] Stage 1 Baseline 启动

- **Run ID**: `stage1_core`
- **结果**: 完成 150 组 LHS 采样，确定了初步的参数敏感度。

### 3.2 [2025-01-16] Stage 2 Sensitivity Deepening

- **Run ID**: `stage2_sensitivity`
- **发现 1 (物理墙)**: Buffer < 0.6x BDP 时，丢包不可避免。
- **发现 2 (Sleek有效性)**: UEC 的 Trimming 机制能有效将拥塞转化为重传开销，而非排队延迟。

### 3.3 [2025-01-19] Stage 3: ECN Deep Dive (The ECN Journey)

**(本节详细记录了针对 Conns=64 尖峰问题的攻坚过程)**

为了定位问题并寻找优化空间，我们进行了一系列的渐进式实验。

#### 3.3.1 初始探索：Incast 规模的影响

- **实验配置**：`001-incast-scalability.yaml`
- **现象**：当并发连接数 `conns=64` 时，尾部延迟（P99/Max）出现剧烈跳变（图1中红线所示）。其他并发度下表现则较为线性。
- **诊断**：确认为 **尾部丢包 (Tail Loss)**。拥塞导致拥塞窗口（cwnd）降至 1 MSS，后续无新包触发 ACK，不仅吞吐受损，更导致长达数毫秒的 RTO 等待。

![Baseline Incast Spike](.assets/fig1_incast_baseline.png)
*图1：基线 Incast 扩展性测试。conns=64 处出现明显尖峰。*

#### 3.3.2 参数扫描与 Sleek 机制的发现

- **实验配置**：`001a-调整randseed-锁定事故点.yaml`
- **验证**：通过扫描随机种子，确认为系统性问题而非单纯的 Hash 冲突（图2红线）。
- **Sleek 机制对比**：启用 UEC 代码中的 Sleek 机制后（图2绿线），尖峰完全消失。
- **局限性**：虽然 Sleek 解决了不稳定性（Safety），但其平均 FCT 显著高于未启用时的基线水平。这意味着它通过牺牲一定的“激进性”换取了“稳定性”。

![Sleek vs Baseline](.assets/fig2_randseed_spikes.png)
*图2：Baseline（红）与 Sleek（绿）对比。Sleek 削平了尖峰，但整体水位上升。*

#### 3.3.3 “甜点区” (Sweet Spot) 的假设

- **实验配置**：`001a1-测试默认设置.yaml`
- **发现**：UEC 的默认配置（特定的 ECN 阈值 + 目标队列延迟）意外地达到了**“既稳又快”**的效果——既没有长尾尖峰，平均延迟也保持在低位。
- **推论**：存在一组参数（特别是 ECN），可以在不依赖重型机制（如 Sleek）的情况下解决尾部丢包问题。

![Default Settings](.assets/fig3_sleek_comparison.png)
*图3：默认配置下的性能表现，达到了理想的平衡点。*

#### 3.3.4 关键变量控制：ECN 阈值

- **实验配置**：`001c-测试不同ecn阈值.yaml`
- **测试**：剥离其他变量，仅调整 ECN 阈值。
- **现象**：系统对 ECN 阈值表现出**极高的敏感性**。看似接近的阈值（如 `0.08` 与 `0.0806`）会导致截然不同的性能结果（图4）。这表明最佳工作点可能是一个非常狭窄的“峡谷”，而非宽阔的平原。

![Coarse ECN Sweep](.assets/fig4_ecn_sweep_coarse.png)
*图4：不同 ECN 设置下的性能方差极大。*

#### 3.3.5 精细化 ECN 分析

- **实验配置**：`001c1-控制变量确认ecn阈值效果.yaml`
- **关键前提 (Controlled Variables)**: 为了隔离 ECN 的影响，我们将其他变量**手动锁定**在基线事故点：`target_q_delay=12us` (非默认), `queue_size=8*BDP` (非默认)。
- **结论**：较低的阈值（如 `0.05 0.2`）在该场景下表现最佳（图5）。
- **机理**：提前的拥塞感知（Early Brake）在队列积压形成“悬崖”（丢包）之前介入，避免了 RTO，同时又不像 Sleek 那样过度保守。

![Detailed ECN Sweep](.assets/fig5_ecn_sweep_detailed.png)
*图5：ECN 阈值精细对比。较低的阈值 (0.05 0.2) 表现最优。*

#### 3.3.6 Case Study: Conns=64 尖峰解剖 (Anatomy of a Spike)

为了深入理解 "Crash Boundary" 的微观机制，我们对 `001-incast-scalability.yaml` 中 `conns=64` 的异常点进行了高精度的重现与诊断（配置：`D_001-incast-scalability_conns64_sleekFalse.yaml`）。

##### 3.3.6.1. FCT 尾部失控 (Tail Latency Explosion)

![FCT CDF](.assets/fig6_conns64_diagnostic_fct_cdf.png)
*图6：Max FCT 高达 732us，远超中位数 246us。*
CDF 曲线显示了一个极其陡峭的长尾。P99 (457us) 和 Max (732us) 之间的巨大差距表明，尽管绝大多数流能正常完成，但有少数几个“受害者”流经历极其严重的停顿。

##### 3.3.6.2. NIC 层的惨烈拥塞 (Congestion at NIC)

![NIC Traffic](.assets/fig7_conns64_diagnostic_nic_traffic.png)
*图7：NIC 吞吐量的有效性分析（绿色=有效，红色=裁剪/丢弃）。*
在 Incast 爆发的初期（20-80us），NIC 接收到了大量的流量，但其中很大一部分（红色区域）是 **被 Trim（裁剪）或 Drop（丢弃）的无效流量**。
这直接证明了 **Incast 导致的 Buffer Overflow 是性能恶化的根因**。即使开启了 Trim，大量的重传包依然占据了宝贵的带宽资源。有趣的是，在 700us 左右出现了一个延迟极高的小尖峰，这正是那个“最倒霉”的流重传成功的时间点。

##### 3.3.6.3. 事件时空分布 (Spatial-Temporal Incident)

![Congestion Spatial](.assets/fig8_conns64_diagnostic_congestion_spatial.png)
*图8：拥塞事件（Trim）在时间轴上的密集爆发。*
所有的拥塞事件都集中在模拟的最前端（20-80us）。这证实了 **Micro-burst（微突发）** 的特征：极短时间内的极高强度冲击。系统没有“喘息”的机会来调整 Rate。

##### 3.3.6.4. 核心矛盾：反馈脆弱性与记账僵局 (Feedback Fragility & Deadlock)

![CWND Trace](.assets/fig9_conns64_full_stack_trace.png)
*图9：受害流 (Flow 9098) 的 CWND 变化与完整状态轨迹。*

这是一个教科书式的 **通过 RTO 跳出记账死锁** 的案例，其根因并非文档此前猜测的“SACK 不敏感”，而是**反馈信号的脆弱性**：

1. **0-50us**: 初始爆发阶段。CWND 维持在高位（~250KB），数据包（Pkt 0-13）快速发出。
2. **50us+**: 遭遇 Incast 冲击。Switch 开始产生 Physical TRIM（橘色三角），Pkt 5 和 Pkt 6 被裁剪。CWND 被拥塞算法强制压制到 **1 MSS** (4.1KB)。
3. **100-700us**: **进入逻辑死锁 (Logic Deadlock)**。
    - **机制确认**：代码审计 (`uec.cpp`) 证实 `_in_flight` 实际上是 **SACK-aware** 的，它会根据 ACK 中携带的 `recvd_bytes` 实时扣减。
    - **反馈丢失 (Feedback Loss)**：但在 Flow 9098 的案例中，Pkt 5 和 6 产生的 TRIM 反馈（NACK）中，Seq 6 对应的 NACK 在回程中丢失。
    - **幽灵数据包 (Ghost Packet)**：由于丢失了该 NACK，Seq 6 对应的 1 MSS 负载一直“幽灵般”残留在发送端的 `_in_flight` 计数器中。
    - **窗口封锁**：由于 `cwnd` 已被压死在 **1 MSS**，而 `in_flight` 此时也为 1 MSS，导致 `can_send_NSCC` 检查判定 `cwnd < in_flight + 1_MSS` 永远为假。发送端认为窗口已满，拒绝发出任何后续包（如 Pkt 7 之后的数据）或重传包。
4. **700us**: **RTO 破局**。重传计时器超时（黄色虚线），强制触发 `mark_packet_for_retransmission`。该函数**显式递减** `_in_flight` 并将 Seq 6 重新排队，从而瞬间释放了被占用的窗口。
5. **700us+**: 窗口打开后，Pkt 5 到达使得 CumAck 推进，后续重传顺利进行。

**结论**：死锁的本质是 **“反馈信号丢失”** 与 **“极小窗口检查”** 的碰撞。

##### 3.3.6.5. 逐跳轨迹 (Detailed Path Trace)

![Path Trace](.assets/fig10_conns64_diagnostic_flow_trace.png)
*图10：Flow 9098 的全链路微观轨迹（含标注）。*
从图中可以清晰看到：

- **Packet Loss**: 在 ToR (Last Hop) 处，黄/红色的方块密集，代表严重的排队和丢包。
- **Gap**: 在 50us 到 700us 之间出现巨大的空白区（Gap），这是 RTO 等待的铁证。
- **Lost Trigger**: 注意图中绿色实心圆（SACK）依然在产生，但序列号线（蓝色）在长达 600us 的时间内完全水平，证明发送端即使收到了反馈也拒绝发包。

##### 3.3.6.6. 根因深挖：实现层面的逻辑死锁 (Implementation Deadlock)

经过对 `uec.cpp` 源码的深度审计，确认 700us 停顿的本质是 **反馈机制的非鲁棒性** 与 **恢复门槛的静态缺陷** 共同导致的“系统僵死”。

**1. 窗口钳制 (1-MSS Window Muzzle)**
在 Incast 爆发时，`quick_adapt` 机制将 `cwnd` 压制到最小的 `1 MSS`。这使得发送端对 `_in_flight` 的容错率降为零：任何 1 字节的记账偏差都会锁死发送。

**2. 记账漂移 (Accounting Drift due to Feedback Loss)**
`_in_flight` 计数器是 **Event-Driven（事件驱动）** 的。虽然它支持 SACK，但强依赖于 NACK/ACK 信号的到达。
- **缺陷**：在极度拥塞的 Incast 路径上，反向路径的反馈包（NACK）也可能丢失。
- **后果**：丢失一个 NACK 等同于丢失了“释放窗口”的凭证。在 `cwnd = 1 MSS` 下，这构成了永久性的窗口占用。

**3. SLEEK 机制的“盲点” (SLEEK Threshold Blindness)**
UEC 的 Loss Recovery 机制（代码代号 SLEEK）在关键时刻失灵了：
- **阈值过高**：`runSleek` 要求乱序空隙 `ooo >= 5` 个包（代码中 `min_retx_config = 5`）。在 Flow 9098 的案例中，丢失包很少且后续包被窗口锁死无法发出，导致 `ooo` 永远达不到触发阈值。
- **探针失效 (Probe High-RTT Rejection)**：SLEEK 包含探针机制，但 `processAck` 中规定只有当探针延迟 `delay < target_Qdelay` 时才激活 Recovery。在 Incast 拥塞时，探针 RTT 极高，导致即使探针成功返回，发送端也拒绝进入恢复模式。

**结论**：本次 RTO 事故是由于 **“SACK-Aware 但反馈不鲁棒”** 的记账逻辑，配合 **“固定阈值的快速重传”** 在极小窗口场景下发生碰撞导致的“逻辑停摆”。

##### 3.3.6.7. SLEEK 机制内涵与规范一致性

虽然 "SLEEK" 是代码中的私有代号，但其逻辑高度符合 UEC 1.0 规范：
- **探测 (Probing)**：对应规范的 `Tail Loss Detection` 及 `Probe CP`。
- **判决 (Decision)**：利用 Probe RTT 与 `target_Qdelay` 的对比来区分布分丢包与拥塞丢包，这是 UEC 的核心特征。
- **恢复 (Recovery)**：扫描 `_tx_bitmap` 将丢失包加入 `_rtx_queue`。

**故障总结**：本次 RTO 事故是由于 **“过于保守的恢复门槛”** 与 **“过时的窗口记账逻辑”** 在极小窗口场景下发生碰撞导致的“逻辑停摆”。

### 3.4 [2026-01-20] Targeted LHS: Robustness Validation (鲁棒性验证)

为了验证 "Deep Dive" 结论的普适性，并回答 "Buffer Size 是否关键" 这一疑问，我们执行了 `robustness_scan` (Stage 2/4)。

#### 3.4.1 核心发现：物理缓存的无效性 ("Buffer Inefficacy")

![Buffer Efficacy Heatmap](.assets/robustness_buffer_efficacy.png)
*图11：Queue Size vs Conns 的 P99 FCT 热力图。*

这是一张极具颠覆性的图表：
*   **垂直等高线 (Vertical Contours)**：颜色的变化完全取决于 X 轴 (Conns)，而 Y 轴 (Buffer Size) 的增加几乎不能延缓颜色的变深（性能恶化）。
*   **结论**：**堆物理缓存无效**。Incast 是微秒级的瞬时流量海啸，即使将缓存从 0.5x BDP 增加到 4.0x BDP，也无法吸收这种冲击。这有力地反驳了“加大缓存就能解决问题”的传统直觉。

> **[关于采样范围的效度分析]**
> 用户质疑：Robustness Scan 的采样范围是 `0.5~4.0` BDP，而最初发生崩溃的基线 (001) 使用了更大的 `8.0` BDP。是否需要重新扫描 `4.0~8.0`？
> **答**: **无需重测**。
> 1.  LHS 扫描显示 `0.5 -> 4.0` 性能没有任何改善趋势（垂直等高线）。
> 2.  基线实验 (001) 已经证明了 `8.0` BDP 依然会崩溃 (Max FCT Spikes)。
> 3.  **综合结论**: "Buffer Inefficacy" 现象在 `[0.5, 8.0]` 区间内均成立。物理缓存的边际收益在 Incast 面前几乎为零。

#### 3.4.2 规模暴政 (The Tyranny of Scale)

![Feature Importance](.assets/robustness_feature_importance.png)
*图12：Robustness Scan 因子重要性。*

`conns` 的权重 (>0.9) 再次碾压了其他所有变量（包括 `queue_size`）。这进一步证实了：系统的生死存亡完全取决于**并发规模**。一旦突破规模阈值 (Scale Wall)，任何静态参数调优（如 Target Queue Delay, ECN）都失效。

#### 3.4.3 结论：从“参数调优”转向“架构控制”

基于上述发现，我们的优化方向必须发生根本性转变：
*   **Stop**: 停止寻找“完美的 Buffer 大小”或“完美的 ECN 阈值”。
*   **Start**: 转向 **Admission Control** (准入控制) 或 **Window Sizing**。既然 Buffer 无法无限吸收突发，唯一的出路就是限制同时到达的微突发数量。

---

## 4. 逻辑衔接与深度反思 (Deep Dive Reflection)

### 4.1 认知跃迁：从“调参”到“修路” (The Cognitive Shift)

本阶段的研究经历了一个关键的认知跃迁：最初我们试图通过“调参”（ECN, Buffer Size）来平衡性能与稳定，但最终发现问题根源在于“机制缺陷”。

- **Stage 1 (LHS)**: 发现了性能悬崖。
- **Stage 3 (Deep Dive)**: 钻进 `conns=64` 细节，通过逐包审计发现了 **“记账死锁 (Accounting Deadlock)”**。
- **发现的意义**: 这证明了 700us 的长尾不是网络由于拥塞而“慢”，而是协议栈由于逻辑互锁而“僵死”。

### 4.2 核心矛盾：Scale Wall vs. Logic Deadlock

我们现在面临两个层面的挑战：
1. **物理层面 (Scale Wall)**: 即使解决了死锁，当并发（Incast 度）继续拉升，物理 Buffer 依然会溢出（见 3.4.1 节“Buffer 无效论”）。
2. **协议层面 (Logic Deadlock)**: 实现层面的 SACK-Ignorant 记账和 OOO 门槛过高，导致系统在最需要恢复的时候失去了自我修复能力。

### 4.3 缺口分析 (Gap Analysis)

*   **机制缺口**: UEC 代码实现需要一次“外科手术”，修正 `_in_flight` 的 SACK 敏感性，并针对极小窗口场景（cwnd=1）降低恢复门槛。
*   **架构缺口**: 单纯靠端到端的协议调优无法解决 Incast 的瞬时海啸。必须引入 **Admission Control (准入控制)** 或 **Fabric-Aware Window Sizing**。

---

## 5. 下一步策略：从恢复到预防 (Next Steps: From Recovery to Prevention)

**[Status Update 2026-01-20]**
战术重心发生质变：不再纠结于具体的 ECN 数值，而是转向“机制修复”与“架构预防”。

**[New Plan] 机制优化与架构准入 (Stage 5)**

1.  **Protocol Surgery (机制外科手术)**:
    *   **Action**: 修改 `uec.cpp -> handleAckno`，实现 SACK-Aware 的 `in_flight` 减支，消除“死重”。
    *   **Action**: 优化 SLEEK 重传激活逻辑，确保在 `cwnd=1` 且收到 `NACK/TRIM` 时能立即无条件触发恢复。

2.  **Admission Control (架构准入控制)**:
    *   **方向**: 既然物理吸收（Buffer）失效，必须从源头消减突发强度。
    *   **手段**: 调研 UEC 的 `Initial Window Sizing` 策略，确保 `Total Burst (Init_CWND * Conns) < k * BDP`。

3.  **Stress Test (极限压测)**:
    *   在修复机制并开启准入后，验证系统能否平滑支撑 `Conns=128/256` 的超大规模 Incast。

---

## 6. 进度盘点与结案思考 (Progress Analysis & Final Thoughts)

### 6.1 目标達成度 (Goal Status)

- **核心目标**：消除 Incast 微突发导致的尾部延迟 —— **已定位根因**（死锁），待实施修复。
- **量化指标**：使 P99 FCT 逼近理想值 —— **已通过 ECN 优化验证了局部潜力，通过 RTO 分析指明了技术瓶颈**。

### 6.2 问题识别 (Defects)

- **逻辑僵化**：当前 UEC 仿真实现对于“极小窗口 + 多点丢包”的容错性极低。
- **物理盲信**：实验已粉碎“加大 Buffer 解决 Incast”的直觉，迫使研究转向对突发流量流控起源（Sender-side）的研究。

### 6.3 现状盘点 (Current Status)

- **Done**:
  - [x] **根因定罪**: 驳回了“SACK 忽略”论点，确认为“反馈丢失造成的幽灵包死锁”与“SLEEK/Probe 恢复盲区”的互锁问题。
  - [x] **物理定性**: 证明了 Buffer 扩容对 Incast 抑制的边际效应递减至零。
  - [x] **规范对齐**: 确认 SLEEK 逻辑符合 UEC 1.0 Spec 但在极端场景下需要实现补丁。
- **In Progress**:
  - [/] **方案验证**: 准备实施 `in_flight` 记账逻辑的修正。
  - [/] **架构转向**: 准备从“被动丢包恢复”转向“主动并发控制”。

### 6.4 执行路线 (Action Plan)

1.  **UEC 协议栈补丁 (The Patch)**:
    *   修复 SACK 记账与重传激活逻辑。
2.  **准入控制验证 (The Control)**:
    *   实施 Initial Window Sizing 并进行全域扫描。
3.  **全尺度验证 (The Scale)**:
    *   绘制修复后的扩展性曲线，完成研究结案。
