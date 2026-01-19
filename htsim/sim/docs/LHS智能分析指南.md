# 🧠 LHS 智能分析指南 (Smart Analysis Manual)

本文档介绍了 `htsim` 分析框架中引入的“智能分析引擎”，旨在解决高维参数空间（High-Dimensional Parameter Space）下的归因难题。

## 1. 为什么需要智能扫描？

传统的控制变量法（Control Variable）在分析简单场景时非常有效，但在面对复杂网络调优时存在局限：
*   **交互掩蔽**：参数 A 的效果可能依赖于参数 B 的取值（例如 ECN 阈值必须配合 Buffer 大小才有意义）。
*   **维度灾难**：当同时调整 5 个以上参数时，人眼无法通过二维散点图看清规律。

智能引擎引入了 **Machine Learning (Random Forest)** 和 **Rule-Based Diagnostics**，实现了“数据到结论”的自动化。

## 2. 核心功能模块

### 2.1 敏感度扫描 (Sensitivity Scan)
*   **原理**: 使用随机森林回归模型（Random Forest Regressor）拟合实验数据，计算 Feature Importance。
*   **API**: `batch.viz.analyze_feature_importance(metric="p99_fct")`
*   **如何解读**:
    *   **Top 1 Factor**: 如果某个参数（如 `linkspeed`）权重超过 0.5，说明它是**主导因素**。任何优化都必须优先解决它。
    *   **Noise**: 权重低于 0.05 的参数通常是噪音，可以在后续分析中忽略。

### 2.2 自动交互分析 (Auto-Interactions)
*   **原理**: 自动识别领域内已知的“强耦合参数对”，并绘制 2D 响应面图。
*   **支持的耦合模式**:
    *   `ecn_low` vs `ecn_high`: 检测 ECN 双阈值设置是否合理。
    *   `conns` vs `queue_size`: 检测缓冲区应对突发的能力。
    *   `linkspeed` vs `hop_latency`: 检测 BDP 相关性。

### 2.3 专家诊断系统 (Expert Diagnostics)
*   **原理**: 基于规则库（Rule Base）匹配已知的故障物理指纹。
*   **故障模式库**:
    | 故障模式 | 物理指纹 (Signature) | 建议操作 |
    | :--- | :--- | :--- |
    | **Bufferbloat** | P99 极高 + 几乎无丢包 | 减小 Buffer 或调低 ECN |
    | **Congestion Collapse** | 丢包数 > 1000 | 开启 PFC 流控 |
    | **Hash Collision** | Max FCT >> P99 FCT | 开启自适应路由 (Adaptive Routing) |

### 2.4 极值配置推荐 (Best/Worst Finding)
*   **功能**: 自动扫描整个数据集，输出表现最好和最差的配置参数表。
*   **用途**: 直接获取可执行的“金标配置” (Golden Config)。

### 2.5 危机探测 (Crash Zone Detection)
*   **原理**: “物理墙”理论。通过锁定高负载场景（Filter），绘制 Buffer vs ECN 的 2D 热力图。
*   **用途**: 识别无论算法如何优化都无法逾越的物理边界（如 Buffer 因容量不足导致的必丢包区域）。
*   **图谱特征**:
    *   **Latency Zone**: 左下角（小 Buffer）呈现深色高延时。
    *   **Drop Zone**: 对应区域呈现亮色高丢包。

## 3. 进阶：分层分析策略 (Tiered Analysis Strategy)

为了应对不同阶段的研究需求，建议采用**漏斗式分析法**，从宏观到微观逐步推进：

### Phase 1: 广域侦察 (Discovery)
*   **目标**: 在茫茫参数海中寻找“什么因素最重要”以及“哪里是危险区”。
*   **工具**: `LHS_Analysis.ipynb` (通用扫描器)
*   **核心动作**: Feature Importance, Heatmap, Best/Worst Config。
*   **适用场景**: `Stage 1` (探索), `Stage 3` (边缘测试)。

### Phase 2: 定向攻坚 (Validation)
*   **目标**: 针对特定的假设进行验证（例如：“系统能否扛住 400 并发？”）。
*   **工具**: `Targeted_Analysis.ipynb` (专用靶向分析) 或 Python 脚本。
*   **核心动作**:
    *   **Scaling Test**: 如果 X 轴是压力 (Conns/Load)，使用 `batch.viz.plot_tradeoff()` 绘制双轴图。
    *   **Param Sweep**: 如果 X 轴是算法参数 (Kmin/Pmax)，使用 `batch.viz.plot_pivot()` 观察单变量影响。
*   **适用场景**: `Stage 2` (深度), `Stage 2.5` (扩展性)。

### Phase 3: 机理溯源 (Diagnosis)
*   **目标**: 解释 Phase 2 中看到的异常现象（例如：“为什么 200 并发时丢包率突然上升？”）。
*   **工具**: 原始日志分析 (Raw Log Inspector)。
*   **核心动作**:
    *   检查 `queue_usage` 时序图：看缓存是否被打爆。
    *   检查 `flow_events` 具体流行为：看是否有流饿死。

---

## 4. 使用工作流

1.  **运行实验**: 使用 `LHS_tests/*.yaml` 跑完批量实验。
2.  **选择武器**:
    *   **不知道找什么规律** -> 打开 `LHS_Analysis.ipynb`。
    *   **验证特定假设** -> 打开 `Targeted_Analysis.ipynb`。
3.  **阅读建议**: 关注 Notebook 输出中的 **[Insight]** 和 **[Action]** 提示段落。

