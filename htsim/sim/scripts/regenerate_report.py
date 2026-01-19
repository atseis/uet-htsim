import json
import os

nb_path = "LHS_Analysis.ipynb"

# Define the structure of the new notebook
cells = [
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "# 🚀 智能实验分析报告 (Smart Experiment Analysis Report)\n",
            "\n",
            "本 Notebook 使用 `BatchVisualizer` 智能引擎对高维实验数据进行自动扫描与诊断。\n",
            "\n",
            "**分析流程指南:**\n",
            "1.  **数据体检 (Data Health)**: 确保数据加载正确，无大规模失败。\n",
            "2.  **敏感度扫描 (Sensitivity Scan Visualized)**: **重点关注**。量化“谁是罪魁祸首”。\n",
            "3.  **可视化深潜 (Visual Deep Dive)**: 针对关键参数看趋势。\n",
            "4.  **专家诊断 (Executive Summary)**: 自动给出优化建议和红黑榜。"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "%load_ext autoreload\n",
            "%autoreload 2\n",
            "\n",
            "import sys\n",
            "from pathlib import Path\n",
            "import matplotlib.pyplot as plt\n",
            "import pandas as pd\n",
            "\n",
            "from analysis.data.batch import BatchResult"
        ]
    },
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 1. 数据加载与体检 (Data Loading & Health Check)\n",
            "\n",
            "> **💡 分析师建议**:\n",
            "> *   检查 `experiments` 数量是否符合预期 (例如 LHS 采样数)。\n",
            "> *   如果大部分指标为 NaN，请检查日志目录是否存在。"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "batch = BatchResult()\n",
            "# 加载 Stage 2 结果 (如需分析其他阶段，请修改此处路径)\n",
            "target_dir = Path(\"results/LHS_tests/stage2-sensitivity-deepening\")\n",
            "\n",
            "if target_dir.exists():\n",
            "    print(f\"正在加载目录: {target_dir}...\")\n",
            "    batch.add_source(target_dir)\n",
            "    print(f\"成功加载试验数量: {len(batch.experiments)}\")\n",
            "else:\n",
            "    print(f\"[!] 目录未找到: {target_dir}\")"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "# 基础数据预览\n",
            "metrics = [\"p99_fct\", \"max_fct\", \"median_fct\", \"max_drop_rate\", \"util_avg\"]\n",
            "df = batch.get_summary_df(metrics)\n",
            "print(f\"数据维度 (Data Shape): {df.shape}\")\n",
            "df.head()"
        ]
    },
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 2. 敏感度扫描: 谁是瓶颈? (What Matters?)\n",
            "\n",
            "使用 **随机森林 (Random Forest)** 算法，在高维噪声中计算每个参数对结果的影响力权重。\n",
            "\n",
            "> **💡 分析师建议**:\n",
            "> *   **关注 Top 3**: 通常前 2-3 个参数决定了 80% 的性能变化。\n",
            "> *   **忽略长尾**: 贡献率低于 5% 的参数通常是“陪跑”的，后续分析中可以忽略。\n",
            "> *   如果 `randseed` 排名很高，说明系统极不稳定（运气成分大）。"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "# 分析 P99 时延的驱动因素\n",
            "batch.viz.analyze_feature_importance(\"p99_fct\", top_n=8)"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "# 分析长尾 Straggler (通常指代 Hash 冲突或重传)\n",
            "batch.viz.analyze_feature_importance(\"max_fct\", top_n=8)"
        ]
    },
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 3. 可视化深潜: 趋势与交互 (Visual Deep Dive)\n",
            "\n",
            "根据上面的扫描结果，针对性地查看关键参数的影响趋势。"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "# 3.1 主效应图 (Main Effects)\n",
            "# 绘制所有变化参数的单因素趋势图\n",
            "varying_params = batch.get_varying_params()\n",
            "print(f\"检测到变化参数: {varying_params}\")\n",
            "\n",
            "batch.viz.plot_main_effects(varying_params, [\"p99_fct\", \"max_drop_rate\"])"
        ]
    },
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "> **💡 图表解读指南**:\n",
            "> *   **寻找拐点 (Knee/Cliff)**: 性能是否在某个值突然恶化？这就是我们寻找的 Crash Boundary。\n",
            "> *   **平坦直线**: 说明该参数对结果无影响（与随机森林结论呼应）。"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "# 3.2 智能交互分析 (Intelligent Interactions)\n",
            "# 自动检测已知的关键参数对（如 ECN 高低阈值耦合）\n",
            "batch.viz.plot_auto_interactions(metrics=[\"p99_fct\"])"
        ]
    },
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "> **💡 交互图解读**:\n",
            "> *   **ECN Interaction**: 观察是否只有在 High/Low 阈值保持特定比例时，性能才好？（寻找“绿色孤岛”）\n",
            "> *   **BDP Impact**: 带宽和延迟是否呈现互补关系？"
        ]
    },
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "### 3.2.1 物理边界探测 (Crash Zone Detection)\n",
            "本节专门用于识别**物理墙 (Physical Wall)**：即无论算法如何优化，硬件（如 Buffer）都无法支撑的区域。\n",
            "如果看到大面积的黄色/深色区域（低性能/高丢包），说明该配置处于“死亡地带”。"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "# 自动探测：Buffer vs ECN 的红蓝对抗\n",
            "if \"queue_size_bdp_factor\" in batch.get_varying_params() and \"ecn_high\" in batch.get_varying_params():\n",
            "    # 1. 过滤掉低压力场景，只看高压下的表现 (Conns > median)\n",
            "    med_conns = batch.get_summary_df([])['conns'].median()\n",
            "    print(f\"[Crash Zone] Focusing on High Load: conns >= {med_conns}\")\n",
            "    subset = batch.filter(lambda r, t: r.params.get('conns', 0) >= med_conns)\n",
            "    \n",
            "    # 2. 绘制 FCT 热力图\n",
            "    subset.viz.plot_generic(\n",
            "        x='queue_size_bdp_factor', \n",
            "        y='ecn_high', \n",
            "        hue='p99_fct', \n",
            "        metrics=['p99_fct'],\n",
            "        kind='scatter', \n",
            "        title=\"1. Latency Crash Zone (High Load)\", \n",
            "        marker='o', s=100, palette='viridis_r'\n",
            "    )\n",
            "\n",
            "    # 3. 绘制 Drop Rate 热力图 (验证物理丢包)\n",
            "    subset.viz.plot_generic(\n",
            "        x='queue_size_bdp_factor', \n",
            "        y='ecn_high', \n",
            "        hue='max_drop_rate', \n",
            "        metrics=['max_drop_rate'],\n",
            "        kind='scatter', \n",
            "        title=\"2. Packet Loss Zone (High Load)\", \n",
            "        marker='o', s=100, palette='magma'\n",
            "    )"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "# 3.3 全局平行坐标图 (Star/Parallel Plot)\n",
            "# 高亮显示表现最好的 10% 配置 (Top 10%)\n",
            "batch.viz.plot_parallel_coordinates(\n",
            "    factors=varying_params,\n",
            "    metrics=[\"p99_fct\"],\n",
            "    highlight={\"metric\": \"p99_fct\", \"top\": True, \"fraction\": 0.1} \n",
            ")"
        ]
    },
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "## 4. 专家诊断与行动建议 (Executive Summary)\n",
            "\n",
            "本节基于领域知识库 (`docs/`) 自动匹配故障模式，并给出最优/最差配置列表。"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "# 4.1 故障模式自动诊断\n",
            "batch.viz.diagnose_failure_modes()"
        ]
    },
    {
        "cell_type": "markdown",
        "metadata": {},
        "source": [
            "> **💡 诊断对照表**:\n",
            "> *   **Bufferbloat (高 P99 + 低 Drop)**: 缓冲区太大或 ECN 太高。 -> **建议**: 调低 ECN 阈值。\n",
            "> *   **Congestion Collapse (高 Drop)**: Incast 甚至打爆了 buffer。 -> **建议**: 开启 PFC 或增大 Buffer（权衡）。\n",
            "> *   **Stragglers (Max >> P99)**: 若 P99 正常但 Max 很高，通常是 Hash 冲突。 -> **建议**: 考虑 Adaptive Routing。"
        ]
    },
    {
        "cell_type": "code",
        "execution_count": None,
        "metadata": {},
        "source": [
            "# 4.2 红黑榜: 最佳与最差配置 (Best & Worst Cases)\n",
            "# 能够直接照抄的作业\n",
            "batch.viz.find_best_worst_configs(\"p99_fct\", n=5, maximize=False)"
        ]
    }
]

# Create the notebook JSON structure
nb = {
    "cells": cells,
    "metadata": {
        "kernelspec": {
            "display_name": "Python 3",
            "language": "python",
            "name": "python3"
        },
        "language_info": {
            "codemirror_mode": {
                "name": "ipython",
                "version": 3
            },
            "file_extension": ".py",
            "mimetype": "text/x-python",
            "name": "python",
            "nbconvert_exporter": "python",
            "pygments_lexer": "ipython3",
            "version": "3.8.10"
        }
    },
    "nbformat": 4,
    "nbformat_minor": 5
}

# Write to file
with open(nb_path, 'w', encoding='utf-8') as f:
    json.dump(nb, f, indent=1)

print(f"Successfully overwrote {nb_path} with Localized Smart Analysis Report.")
