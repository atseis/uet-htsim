#!/usr/bin/env python3
"""
Probe 修复验证实验分析报告 - 改进版

直接从结果目录读取 summary.json 进行分析
"""

import json
from pathlib import Path
import pandas as pd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import re


def parse_experiment_name(dirname):
    """从目录名解析实验配置"""
    # 示例：probe-original-buggyconns32_randseed1_sleekTrue (注意 conns 前没有连字符)
    # 使用 [\\w-]+ 来匹配包含连字符的实验组名
    pattern = r"^(probe-[\w-]+)conns(\d+)_randseed(\d+)_sleek(True|False)$"
    match = re.match(pattern, dirname)
    if match:
        return {
            "experiment_group": match.group(1),
            "conns": int(match.group(2)),
            "randseed": int(match.group(3)),
            "sleek": match.group(4) == "True",
        }

    return None


def main():
    print("=" * 80)
    print("Probe 修复验证实验 - 数据分析 (改进版)")
    print("=" * 80)

    results_dir = Path("results/probe-fix-verification")
    if not results_dir.exists():
        print(f"错误：结果目录不存在：{results_dir}")
        return

    # 收集所有实验数据
    data = []

    print("\n1. 读取实验结果...")
    for subdir in results_dir.iterdir():
        if not subdir.is_dir():
            continue

        # 跳过 batch_summary.log
        if subdir.name == "batch_summary.log":
            continue

        # 解析实验名
        config = parse_experiment_name(subdir.name)
        if not config:
            print(f"   ⚠ 跳过无法解析的目录：{subdir.name}")
            continue

        # 读取 summary.json
        summary_file = subdir / "summary.json"
        if not summary_file.exists():
            print(f"   ⚠ 缺少 summary.json: {subdir.name}")
            continue

        with open(summary_file, "r") as f:
            summary = json.load(f)

        # 添加配置信息
        row = {**config, **summary}
        data.append(row)
        print(f"   ✓ {subdir.name}: p99_fct={summary.get('p99_fct', 'N/A')} μs")

    if not data:
        print("   ✗ 没有找到有效的实验数据!")
        return

    df = pd.DataFrame(data)
    print(f"\n   共加载 {len(df)} 个实验样本")

    # 数据预览
    print("\n2. 数据预览:")
    print(
        df[
            ["experiment_group", "conns", "randseed", "sleek", "p99_fct", "median_fct"]
        ].head(10)
    )

    # 分组统计
    print("\n3. 按实验组分组统计 (P99 FCT):")
    grouped = df.groupby("experiment_group")["p99_fct"].describe()
    print(grouped)

    # 创建输出目录
    output_dir = Path(".sisyphus/evidence/probe-fix")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 可视化
    print("\n4. 生成可视化图表...")

    # 按 conns 分组显示
    for conns in sorted(df["conns"].unique()):
        subset = df[df["conns"] == conns]

        if len(subset["experiment_group"].unique()) < 2:
            continue

        # 图表 1: 柱状图对比
        fig, ax = plt.subplots(figsize=(12, 6))

        exp_groups = subset.groupby("experiment_group")["p99_fct"].mean().sort_index()
        stds = subset.groupby("experiment_group")["p99_fct"].std()

        x_pos = range(len(exp_groups))
        colors = {
            "probe-original-buggy": "red",
            "probe-original-baseline": "orange",
            "probe-fixed-working": "green",
        }
        bar_colors = [colors.get(name, "blue") for name in exp_groups.index]

        ax.bar(
            x_pos,
            exp_groups.values,
            yerr=[stds.get(name, 0) for name in exp_groups.index],
            capsize=5,
            color=bar_colors,
            alpha=0.7,
        )
        ax.set_xticks(x_pos)
        ax.set_xticklabels(
            [
                name.replace("probe-", "").replace("-", " ").title()
                for name in exp_groups.index
            ],
            rotation=15,
            ha="right",
        )
        ax.set_ylabel("P99 FCT (μs)", fontsize=12)
        ax.set_title(
            f"Probe Fix Verification - P99 FCT Comparison (conns={conns})", fontsize=14
        )
        ax.grid(True, alpha=0.3, axis="y")

        output_path = output_dir / f"p99_fct_comparison_conns{conns}.png"
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"   ✓ 保存柱状图：{output_path}")
        plt.close()

        # 图表 2: CDF 图
        fig, ax = plt.subplots(figsize=(10, 7))

        for exp_name, color in colors.items():
            if exp_name not in subset["experiment_group"].values:
                continue
            exp_data = subset[subset["experiment_group"] == exp_name][
                "p99_fct"
            ].sort_values()
            cdf = [i / len(exp_data) for i in range(1, len(exp_data) + 1)]
            ax.plot(
                exp_data,
                cdf,
                label=exp_name.replace("probe-", "").replace("-", " ").title(),
                color=color,
                linewidth=2,
                marker="o",
            )

        ax.set_xlabel("P99 FCT (μs)", fontsize=12)
        ax.set_ylabel("CDF", fontsize=12)
        ax.set_title(f"P99 FCT CDF Comparison (conns={conns})", fontsize=14)
        ax.legend(loc="lower right")
        ax.grid(True, alpha=0.3)

        output_path = output_dir / f"p99_fct_cdf_conns{conns}.png"
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"   ✓ 保存 CDF 图：{output_path}")
        plt.close()

    # 生成结论
    print("\n5. 分析结论:")
    print("=" * 80)

    for conns in sorted(df["conns"].unique()):
        subset = df[df["conns"] == conns]

        if (
            "probe-original-buggy" not in subset["experiment_group"].values
            or "probe-fixed-working" not in subset["experiment_group"].values
        ):
            continue

        buggy_p99 = subset[subset["experiment_group"] == "probe-original-buggy"][
            "p99_fct"
        ].mean()
        fixed_p99 = subset[subset["experiment_group"] == "probe-fixed-working"][
            "p99_fct"
        ].mean()

        improvement = (buggy_p99 - fixed_p99) / buggy_p99 * 100

        print(f"\nConns={conns} 关键发现:")
        print(f"  • 修复前 (buggy) P99 FCT 均值：{buggy_p99:.2f} μs")
        print(f"  • 修复后 (fixed) P99 FCT 均值：{fixed_p99:.2f} μs")
        print(f"  • 改善幅度：{improvement:.1f}%")

        if improvement > 50:
            print(
                f"  ✅ 显著改善！Probe 修复成功启用快速重传，尾部延迟降低 {improvement:.1f}%"
            )
        elif improvement > 20:
            print(f"  ✓ 中等改善。P99 FCT 降低 {improvement:.1f}%")
        elif improvement > 0:
            print(f"  ○ 轻微改善。P99 FCT 降低 {improvement:.1f}%")
        else:
            print(f"  ✗ 未观察到改善。可能需要更多样本或检查实验配置。")

    print("\n" + "=" * 80)
    print(f"证据保存目录：{output_dir.absolute()}")
    print("=" * 80)


if __name__ == "__main__":
    main()
