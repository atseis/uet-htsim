#!/usr/bin/env python3
"""
Quick FCT Comparison Script for Probe Fix Verification

Usage:
  python3 quick_fct_compare.py <original_flow_events> <fixed_flow_events> <output_png>
"""

import sys
import re
import numpy as np
import matplotlib.pyplot as plt


def parse_fct_from_ascii(filename):
    """
    从 parse_output -ascii -filter FLOW_EVENT 的输出中提取 FCT

    格式示例:
    0.000123 Type FLOW_EVENT SrcID 1 Ev START FlowID 100
    0.000456 Type FLOW_EVENT SrcID 1 Ev FINISH FlowID 100 Bytes 51200 Pkts 13

    Returns: FCT 列表 (单位：纳秒)
    """
    flow_starts = {}
    fcts = []

    with open(filename, "r") as f:
        for line in f:
            # 提取时间戳 (秒)
            time_match = re.match(r"^(\d+\.\d+)", line)
            if not time_match:
                continue

            time_sec = float(time_match.group(1))
            time_ns = time_sec * 1e9  # 转换为纳秒

            # 查找 FlowID
            flow_match = re.search(r"FlowID\s+(\d+)", line)
            if not flow_match:
                continue

            flow_id = int(flow_match.group(1))

            # 检查是 START 还是 FINISH
            if "START" in line:
                flow_starts[flow_id] = time_ns
            elif "FINISH" in line:
                if flow_id in flow_starts:
                    fct = time_ns - flow_starts[flow_id]
                    fcts.append(fct)

    return np.array(fcts)


def calculate_stats(fcts):
    """计算 FCT 统计"""
    if len(fcts) == 0:
        return {}

    percentiles = {
        "min": np.min(fcts),
        "max": np.max(fcts),
        "mean": np.mean(fcts),
        "median": np.median(fcts),
        "p50": np.percentile(fcts, 50),
        "p90": np.percentile(fcts, 90),
        "p95": np.percentile(fcts, 95),
        "p99": np.percentile(fcts, 99),
        "count": len(fcts),
    }
    return percentiles


def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    original_file = sys.argv[1]
    fixed_file = sys.argv[2]
    output_png = sys.argv[3]

    print(f"Parsing original: {original_file}")
    fct_original = parse_fct_from_ascii(original_file)
    print(f"  Found {len(fct_original)} flows")

    print(f"Parsing fixed: {fixed_file}")
    fct_fixed = parse_fct_from_ascii(fixed_file)
    print(f"  Found {len(fct_fixed)} flows")

    # 计算统计
    stats_orig = calculate_stats(fct_original)
    stats_fixed = calculate_stats(fct_fixed)

    # 绘制 CDF 图
    fig, ax = plt.subplots(figsize=(12, 7))

    # Original CDF
    sorted_orig = np.sort(fct_original)
    cdf_orig = np.arange(1, len(sorted_orig) + 1) / len(sorted_orig)
    ax.plot(
        sorted_orig / 1e3,
        cdf_orig,
        "r--",
        label="Original (Before Fix)",
        linewidth=2.5,
        alpha=0.7,
    )

    # Fixed CDF
    sorted_fixed = np.sort(fct_fixed)
    cdf_fixed = np.arange(1, len(sorted_fixed) + 1) / len(sorted_fixed)
    ax.plot(
        sorted_fixed / 1e3,
        cdf_fixed,
        "b-",
        label="Fixed (After Fix)",
        linewidth=2.5,
        alpha=0.7,
    )

    # 标注关键点
    for pct, label in [(50, "P50"), (95, "P95"), (99, "P99")]:
        if stats_orig and stats_fixed:
            v_orig = stats_orig[f"p{pct}"] / 1e3
            v_fixed = stats_fixed[f"p{pct}"] / 1e3

            ax.axvline(v_orig, color="r", linestyle=":", alpha=0.3)
            ax.axvline(v_fixed, color="b", linestyle=":", alpha=0.3)

            # 在顶部添加标注
            if pct == 99:
                ax.annotate(
                    f"{label}: {v_orig:.1f}μs",
                    xy=(v_orig, 0.95),
                    xytext=(5, 5),
                    textcoords="offset points",
                    color="darkred",
                    fontsize=9,
                    rotation=90,
                )
                ax.annotate(
                    f"{label}: {v_fixed:.1f}μs",
                    xy=(v_fixed, 0.85),
                    xytext=(5, -5),
                    textcoords="offset points",
                    color="darkblue",
                    fontsize=9,
                    rotation=90,
                )

    ax.set_xlabel("Flow Completion Time (μs)", fontsize=12, fontweight="bold")
    ax.set_ylabel("CDF", fontsize=12, fontweight="bold")
    ax.set_title(
        "FCT Comparison: Probe Mechanism Fix\n(Original vs Fixed)",
        fontsize=14,
        fontweight="bold",
    )
    ax.legend(loc="lower right", fontsize=11)
    ax.grid(True, alpha=0.3, linestyle="--")
    ax.set_ylim(0, 1.02)
    ax.set_xlim(left=0)

    plt.tight_layout()
    plt.savefig(output_png, dpi=200, bbox_inches="tight")
    print(f"\n✓ Saved CDF plot to: {output_png}")

    # 打印统计报告
    print("\n" + "=" * 80)
    print("FLOW COMPLETION TIME STATISTICS")
    print("=" * 80)

    if stats_orig and stats_fixed:
        print(
            f"\n{'Metric':<12} {'Original (μs)':<18} {'Fixed (μs)':<18} {'Improvement':<18}"
        )
        print("-" * 66)

        for key in ["p50", "p90", "p95", "p99"]:
            orig_val = stats_orig[key] / 1e3
            fixed_val = stats_fixed[key] / 1e3
            if orig_val > 0:
                improvement = (orig_val - fixed_val) / orig_val * 100
            else:
                improvement = 0

            label = key.upper()
            print(
                f"{label:<12} {orig_val:>12.2f}     {fixed_val:>12.2f}     {improvement:>+11.1f}%"
            )

        print(
            f"\n{'Count':<12} {stats_orig['count']:>12}     {stats_fixed['count']:>12}"
        )
        print(
            f"{'Mean (μs)':<12} {stats_orig['mean'] / 1e3:>12.2f}     {stats_fixed['mean'] / 1e3:>12.2f}"
        )
        print(
            f"{'Min (μs)':<12} {stats_orig['min'] / 1e3:>12.2f}     {stats_fixed['min'] / 1e3:>12.2f}"
        )
        print(
            f"{'Max (μs)':<12} {stats_orig['max'] / 1e3:>12.2f}     {stats_fixed['max'] / 1e3:>12.2f}"
        )

    print("\n" + "=" * 80)

    # 结论
    if stats_orig and stats_fixed:
        p99_improvement = (
            (stats_orig["p99"] - stats_fixed["p99"]) / stats_orig["p99"] * 100
        )

        print("\nCONCLUSION:")
        if p99_improvement > 50:
            print(
                f"  ✓✓✓ Significant improvement! P99 FCT reduced by {p99_improvement:.1f}%"
            )
            print(
                "      Probe fix successfully enables fast retransmit, reducing tail latency."
            )
        elif p99_improvement > 20:
            print(
                f"  ✓ Moderate improvement. P99 FCT reduced by {p99_improvement:.1f}%"
            )
        elif p99_improvement > 0:
            print(f"  ○ Slight improvement. P99 FCT reduced by {p99_improvement:.1f}%")
        else:
            print(
                f"  ✗ No improvement observed. P99 FCT increased by {-p99_improvement:.1f}%"
            )
            print(
                "      This may indicate: (1) No packet loss in this run, (2) Configuration issue"
            )

    print()


if __name__ == "__main__":
    main()
