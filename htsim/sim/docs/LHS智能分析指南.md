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

## 3. 使用工作流

1.  **运行实验**: 使用 `LHS_tests/*.yaml` 跑完批量实验。
2.  **一键报告**: 打开 `LHS_Analysis.ipynb`，重启 Kernel 并运行所有单元格。
3.  **阅读建议**: 关注 Notebook 输出中的 **[Insight]** 和 **[Action]** 提示段落。
