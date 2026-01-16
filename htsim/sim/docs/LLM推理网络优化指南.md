# LLM 推理网络优化指南

本文档是使用 `htsim` 对 LLM 推理（Inference）负载进行网络性能模拟与优化的行动指南。它结合了理论上的核心痛点分析与实战中的执行 SOP。

## 第一部分：LLM 推理中的核心网络挑战

理解大语言模型（LLM）的流量特征是进行有效模拟的关键。网络瓶颈主要在 **Prefill（预填充）** 阶段（带宽敏感）和 **Decode（解码/生成）** 阶段（时延敏感）之间切换。

### 1.1 Incast 微突发（长尾时延杀手）
*   **场景**：在张量并行（Tensor Parallelism, TP）中，每个 Token 的生成步骤都以一次 `AllReduce` 操作结束。该操作的最后阶段（Reduce-Scatter 或 All-Gather）会产生同步的 **Incast**（多对一）流量模式。
*   **行为**：数十个小流（例如 50KB - 500KB）同时到达接收端交换机。
*   **风险**：
    *   **微突发（Micro-bursts）** 瞬间填满交换机缓冲区。
    *   **丢包（Packet Drops）** 导致基于超时（RTO）的重传，将 **p99 FCT** 从微秒级推高到毫秒级。
    *   **抖动（Jitter）** 延迟了那个“最慢的流”（Straggler），从而卡住整个同步的推理步骤。
*   **模拟策略**：
    *   使用 `traffic: incast`。
    *   关注指标：**p99_fct**（而非平均值）。

### 1.2 Hash 冲突（"Straggler" 问题）
*   **场景**：在使用标准的 ECMP（等价多路径路由）时，流是根据哈希值映射到路径的。
*   **风险**：两个关键流可能会碰撞在同一条物理链路上，而其他链路却是空闲的。在同步的 LLM 训练/推理中，**一条**慢路径就会拖慢整个集群。
*   **模拟策略**：
    *   对比 `strat: ecmp_host` 与 `strat: reactive_ecn`（自适应路由，Adaptive Routing）。
    *   关注指标：**max_fct**。

### 1.3 缓冲区膨胀 (Bufferbloat) 与 ECN 调优
*   **场景**：为了防止丢包，交换机配置了很深的队列（Queue）。
*   **风险**：
    *   如果 ECN 阈值设置得过高，拥塞控制（CC）算法未能及时降速，导致缓冲区一直处于满载状态。
    *   **缓冲区膨胀（Bufferbloat）** 给每个数据包都增加了巨大的排队时延。
*   **模拟策略**：
    *   通过 LHS 扫描变化 `queue_size_bdp_factor` 和 `ecn_high`。
    *   关注指标：**queue_usage**（需要开启详细日志）。

---

## 第二部分：执行 SOP（标准操作程序）

遵循以下 4 阶段工作流来系统地识别和修复这些问题。

### Phase 1: 广域侦察 (LHS 探索)
**目标**：使用随机采样识别“故障区域”并确立性能基准（Baseline）。

1.  **配置 `LHS_tests/stage1`**：
    *   **Traffic**: `incast`（模拟 TP 通信）。
    *   **Flowsize**: `[20KB, 500KB]`（典型的 TP 载荷大小）。
    *   **Variables**: `linkspeed`, `queue_size`, `ecn_low/high`。
2.  **执行智能分析**：
    *   运行 `LHS_Analysis.ipynb`。
    *   **Step 1 全局体检**：确认数据无大面积失败。
    *   **Step 2 敏感度扫描 (Random Forest)**：根据排名条形图，确定哪个参数是核心瓶颈（例如："Linkspeed 贡献了 80% 的方差"）。
    *   **Step 3 自动交互分析**：观察 `ECN High vs Low` 等自动生成的交互热力图。
    *   **Step 4 专家诊断**：查看脚本输出的 **Actionable Insights**（如 "检测到 5 组 Bufferbloat，建议调低 ECN"）。

### Phase 2: 深度诊断 (Deep Dive)
**目标**：理解某个特定配置**为什么**失败。

1.  **挑选案例**：从 Phase 1 中挑选一个显示出高长尾时延的 `sim_id`。
2.  **开启全量日志**：
    *   创建一个单次运行配置（例如 `debug_run.yaml`），复制失败案例的参数。
    *   **关键步骤**：设置 `log: [flow_events, queue_usage, switch]`。
3.  **动态分析**：
    *   使用 `plot_queue.ipynb`。
    *   *场景 A*：队列激增至最大值并保持满载 -> **CC 算法太被动（降速太慢）**。
    *   *场景 B*：队列激增，发生丢包，然后队列排空 -> **缓冲区太小** 或 **ECN 响应太慢**。
    *   *场景 C*：队列是空的但 FCT 很高 -> **ECMP 冲突** 或 **链路故障/重传超时**。

### Phase 3: 算法优化 (Dev Loop)
**目标**：修复 C++ 协议逻辑中的缺陷。

1.  **提出假设**：例如，“UEC 需要针对小流 Incast 采用更激进的启动策略。”
2.  **代码修改**：修改 `src/protocols/uec.cpp`。
3.  **单元测试**：运行 `experiments/SimpleTests/incast_test.yaml` 验证特定的修复效果。

### Phase 4: 回归与泛化
**目标**：确保修复在全局范围内有效。

1.  **重跑 Phase 1 (LHS)**：使用**相同的随机种子**。
2.  **对比**：使用 `BatchVisualizer` 绘制 "修复后 vs 修复前" 的 Delta 图。
    *   确认在“故障区域”的 `p99_fct` 显著降低。
    *   确保在“良好区域”的 `utilization`（带宽利用率）没有显著下降。

## 第三部分：关键指标速查表

| 指标 | 高值意味着... | 潜在解决方案 |
| :--- | :--- | :--- |
| **p99 FCT** | 长尾时延 / 丢包 / 队头阻塞 (HoL) | 增加缓冲区, 降低 ECN 阈值, 开启 PFC |
| **Max FCT** | Straggler 问题 (通常是 Hash 冲突) | 开启自适应路由 (Adaptive Routing), Swift 风格的多路径 |
| **Queue Usage** | 缓冲区膨胀 (高排队时延) | 更激进的 CC (降低 ECN), 减小缓冲区 |
| **Drop Count** | 拥塞崩溃 (Congestion Collapse) | 流量控制 (PFC), 更快的 CC 响应速度 |
