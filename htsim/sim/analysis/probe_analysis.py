#!/usr/bin/env python3
"""
Probe 修复验证实验分析报告

按照 run-experiments skill 规范，使用 BatchResult API 进行数据分析。
"""

import sys

sys.path.insert(0, ".")

from analysis.data.batch import BatchResult
from pathlib import Path
import matplotlib

matplotlib.use("Agg")  # 非交互式后端
import matplotlib.pyplot as plt


def main():
    print("=" * 80)
    print("Probe 修复验证实验 - 数据分析")
    print("=" * 80)

    # 创建 BatchResult
    batch = BatchResult()

    # 添加实验源
    exp_dir = Path("results/probe-fix-verification")
    if not exp_dir.exists():
        print(f"错误：实验目录不存在：{exp_dir}")
        sys.exit(1)

    batch.add_source(
        "experiments/probe-fix-verification.yaml", tags={"experiment": "probe-fix"}
    )

    # 获取汇总数据
    print("\n1. 加载实验数据...")
    try:
        df = batch.get_summary_df(["p99_fct", "median_fct", "max_fct", "mean_fct"])
        print(f"   ✓ 成功加载 {len(df)} 个实验样本")
    except Exception as e:
        print(f"   ✗ 加载失败：{e}")
        sys.exit(1)

    # 显示数据预览
    print("\n2. 数据预览:")
    print(
        df[["experiment", "conns", "randseed", "sleek", "p99_fct", "median_fct"]].head(
            10
        )
    )

    # 按版本分组统计
    print("\n3. 按实验组分组统计 (P99 FCT):")
    grouped = df.groupby("experiment")["p99_fct"].describe()
    print(grouped)

    # 可视化
    print("\n4. 生成可视化图表...")

    # 创建输出目录
    output_dir = Path(".sisyphus/evidence/probe-fix")
    output_dir.mkdir(parents=True, exist_ok=True)

    # 图表 1: FCT CDF 对比
    try:
        fig, ax = plt.subplots(figsize=(12, 7))

        # 按实验组绘制 CDF
        for exp_name in df["experiment"].unique():
            subset = df[df["experiment"] == exp_name]
            sorted_fct = subset["p99_fct"].sort_values()
            cdf = [i / len(sorted_fct) for i in range(1, len(sorted_fct) + 1)]
            ax.plot(sorted_fct, cdf, label=exp_name, linewidth=2, marker="o")

        ax.set_xlabel("P99 FCT (μs)", fontsize=12)
        ax.set_ylabel("CDF", fontsize=12)
        ax.set_title("Probe Fix Verification - P99 FCT CDF Comparison", fontsize=14)
        ax.legend(loc="lower right")
        ax.grid(True, alpha=0.3)

        output_path = output_dir / "p99_fct_cdf_comparison.png"
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"   ✓ 保存 CDF 图：{output_path}")
        plt.close()
    except Exception as e:
        print(f"   ✗ CDF 图生成失败：{e}")

    # 图表 2: 箱线图对比
    try:
        fig, ax = plt.subplots(figsize=(10, 6))

        data_to_plot = []
        labels = []
        for exp_name in df["experiment"].unique():
            subset = df[df["experiment"] == exp_name]["p99_fct"]
            data_to_plot.append(subset.values)
            labels.append(exp_name)

        bp = ax.boxplot(data_to_plot, labels=labels, patch_artist=True)

        # 设置颜色
        colors = ["red", "orange", "green"]
        for patch, color in zip(bp["boxes"], colors):
            patch.set_facecolor(color)
            patch.set_alpha(0.6)

        ax.set_ylabel("P99 FCT (μs)", fontsize=12)
        ax.set_title("Probe Fix - P99 FCT Boxplot by Experiment Group", fontsize=14)
        ax.grid(True, alpha=0.3, axis="y")

        # 旋转标签
        plt.xticks(rotation=15, ha="right")

        output_path = output_dir / "p99_fct_boxplot.png"
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"   ✓ 保存箱线图：{output_path}")
        plt.close()
    except Exception as e:
        print(f"   ✗ 箱线图生成失败：{e}")

    # 图表 3: 柱状图对比均值
    try:
        fig, ax = plt.subplots(figsize=(10, 6))

        means = df.groupby("experiment")["p99_fct"].mean()
        stds = df.groupby("experiment")["p99_fct"].std()

        x_pos = range(len(means))
        ax.bar(
            x_pos,
            means.values,
            yerr=stds.values,
            capsize=5,
            color=["red", "orange", "green"],
            alpha=0.7,
        )
        ax.set_xticks(x_pos)
        ax.set_xticklabels(means.index, rotation=15, ha="right")
        ax.set_ylabel("P99 FCT (μs)", fontsize=12)
        ax.set_title("Probe Fix - P99 FCT Mean Comparison", fontsize=14)
        ax.grid(True, alpha=0.3, axis="y")

        output_path = output_dir / "p99_fct_barplot.png"
        plt.savefig(output_path, dpi=150, bbox_inches="tight")
        print(f"   ✓ 保存柱状图：{output_path}")
        plt.close()
    except Exception as e:
        print(f"   ✗ 柱状图生成失败：{e}")

    # 生成结论
    print("\n5. 分析结论:")
    print("=" * 80)

    if (
        "probe-original-buggy" in df["experiment"].values
        and "probe-fixed-working" in df["experiment"].values
    ):
        buggy_p99 = df[df["experiment"] == "probe-original-buggy"]["p99_fct"].mean()
        fixed_p99 = df[df["experiment"] == "probe-fixed-working"]["p99_fct"].mean()

        improvement = (buggy_p99 - fixed_p99) / buggy_p99 * 100

        print(f"\n关键发现:")
        print(f"  • 修复前 P99 FCT 均值：{buggy_p99:.2f} μs")
        print(f"  • 修复后 P99 FCT 均值：{fixed_p99:.2f} μs")
        print(f"  • 改善幅度：{improvement:.1f}%")

        if improvement > 50:
            print(
                f"\n✅ 显著改善！Probe 修复成功启用快速重传，尾部延迟降低 {improvement:.1f}%"
            )
        elif improvement > 20:
            print(f"\n✓ 中等改善。P99 FCT 降低 {improvement:.1f}%")
        elif improvement > 0:
            print(f"\n○ 轻微改善。P99 FCT 降低 {improvement:.1f}%")
        else:
            print(f"\n✗ 未观察到改善。可能需要检查实验配置或增加样本量。")

    print("\n" + "=" * 80)
    print(f"证据保存目录：{output_dir.absolute()}")
    print("=" * 80)


if __name__ == "__main__":
    main()
