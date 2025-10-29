# viz/cdf.py
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
from typing import List, Dict, Any, Optional, Tuple, Union


def plot_fct_cdf(
    df: pd.DataFrame,
    save_path: Optional[str] = None,
    title: str = "Flow Completion Time CDF",
    x_label: str = "FCT (ms)",
    y_label: str = "CDF",
    convert_to_ms: bool = True,
    stats_loc: Tuple[float, float] = (0.05, 0.7),
) -> None:
    if "fct_ns" not in df.columns:
        raise ValueError("DataFrame必须包含'fct_ns'列")

    if len(df) < 2:
        print(f"⚠️ 数据量仅 {len(df)}，CDF 可能无统计意义")

    fct_values = df["fct_ns"].to_numpy(dtype=np.float64)
    if convert_to_ms:
        fct_values /= 1e6  # ns → ms
    fct_values = np.sort(fct_values)

    y_values = np.arange(1, len(fct_values) + 1) / len(fct_values)

    plt.figure(figsize=(10, 6))
    plt.plot(fct_values, y_values, marker=".", linestyle="-", markersize=5)
    plt.grid(True, linestyle="--", alpha=0.7)
    plt.title(title)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.ylim(0, 1.05)

    stats = {p: np.percentile(fct_values, p) for p in [0, 50, 95, 99, 100]}
    stats_text = (
        f"Min: {stats[0]:.2f} ms\n"
        f"Median: {stats[50]:.2f} ms\n"
        f"95th: {stats[95]:.2f} ms\n"
        f"99th: {stats[99]:.2f} ms\n"
        f"Max: {stats[100]:.2f} ms"
    )

    plt.annotate(
        stats_text,
        xy=stats_loc,
        xycoords="axes fraction",
        bbox=dict(boxstyle="round,pad=0.3", fc="white", ec="gray", alpha=0.8),
        fontsize=10,
    )

    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=300, bbox_inches="tight")
        plt.close()
    else:
        plt.tight_layout()
        plt.show()


def plot_multiple_fct_cdf(
    dfs: List[pd.DataFrame],
    labels: List[str],
    save_path: str,
    plot_options: Dict[str, Any],
    line_configs: List[Dict[str, Any]],
):
    """
    绘制多个 FCT CDF 图，并将它们叠加在同一张图上。

    参数:
        dfs (List[pd.DataFrame]): 包含 FCT 数据的 DataFrame 列表。
        labels (List[str]): 对应每个 DataFrame 的标签列表，用于图例。
        save_path (str): 图表保存路径。
        plot_options (Dict[str, Any]): 包含全局绘图选项的字典，例如 title, x_label, y_label, convert_to_ms, x_cut_percentile, show_stats, x_range_manual, x_range_auto。
        line_configs (List[Dict[str, Any]]): 包含每条线配置的字典列表，例如 color, linestyle。
    """
    if len(dfs) != len(labels):
        raise ValueError("❌ dfs 与 labels 长度必须相同")
    if len(dfs) != len(line_configs):
        raise ValueError("❌ dfs 与 line_configs 长度必须相同")

    # 从 plot_options 中获取全局绘图设置
    title = plot_options.get("title", "Flow Completion Time CDF Comparison")
    x_label = plot_options.get("x_label", "FCT (ms)")
    y_label = plot_options.get("y_label", "CDF")
    x_unit = plot_options.get("x_unit", "ms") # 获取 X 轴单位
    # convert_to_ms = plot_options.get("convert_to_ms", True) # 不再直接使用 convert_to_ms
    x_cut_percentile = plot_options.get("x_cut_percentile", 99.9)
    show_stats = plot_options.get("show_stats", True)
    x_range_manual = plot_options.get("x_range_manual", None)
    x_range_auto = plot_options.get("x_range_auto", True)

    plt.figure(figsize=(10, 6))
    plt.grid(True, linestyle="--", alpha=0.7)

    max_cut_value = 0  # 用于裁剪横轴
    all_fct_values_flat = [] # 用于 x_range_auto 模式下收集所有 FCT 值

    for i, (df, label) in enumerate(zip(dfs, labels)):
        line_config = line_configs[i]
        color = line_config.get("color", None)
        linestyle = line_config.get("linestyle", "-")
        marker = line_config.get("marker", ".")
        markersize = line_config.get("markersize", 4)

        if "fct_ns" not in df.columns:
            raise ValueError(f"DataFrame '{label}' 缺少 'fct_ns' 列")

        fct_values = df["fct_ns"].to_numpy(dtype=np.float64)
        # 根据 x_unit 进行单位转换
        if x_unit == "us":
            fct_values /= 1e3  # ns -> us
        elif x_unit == "ms":
            fct_values /= 1e6  # ns -> ms
        elif x_unit == "s":
            fct_values /= 1e9  # ns -> s
        # 否则保持纳秒 (ns) 不变

        fct_values = np.sort(fct_values)
        all_fct_values_flat.extend(fct_values)

        if len(fct_values) == 0:
            print(f"⚠️ 警告: '{label}' 数据为空，跳过")
            continue

        # 计算CDF
        y_values = np.arange(1, len(fct_values) + 1) / len(fct_values)
        plt.plot(
            fct_values, y_values, linestyle=linestyle, marker=marker, markersize=markersize, label=label, color=color
        )

        # 更新横轴裁剪范围
        max_cut_value = max(max_cut_value, np.percentile(fct_values, x_cut_percentile))

        # 打印统计信息
        if show_stats:
            stats = {
                "min": np.min(fct_values),
                "median": np.median(fct_values),
                "p95": np.percentile(fct_values, 95),
                "p99": np.percentile(fct_values, 99),
                "max": np.max(fct_values),
            }
            print(
                f"📊 [{label}] FCT统计 ({x_unit}): " # 使用 x_unit
                f"min={stats['min']:.2f}, median={stats['median']:.2f}, "
                f"p95={stats['p95']:.2f}, p99={stats['p99']:.2f}, max={stats['max']:.2f}"
            )

    # 设置图表样式
    plt.title(title)
    plt.xlabel(x_label)
    plt.ylabel(y_label)
    plt.ylim(0, 1.05)

    if x_range_manual:
        plt.xlim(left=x_range_manual[0], right=x_range_manual[1])
    elif x_range_auto and len(all_fct_values_flat) > 0:
        min_fct = np.min(all_fct_values_flat)
        max_fct = np.max(all_fct_values_flat)
        # 增加一些边距
        padding = (max_fct - min_fct) * 0.05
        plt.xlim(left=max(0, min_fct - padding), right=max_fct + padding)
    else:
        plt.xlim(left=0, right=max_cut_value)

    plt.legend(loc="lower right", fontsize=10)
    plt.tight_layout()

    # 保存或显示
    if save_path:
        os.makedirs(os.path.dirname(save_path), exist_ok=True)
        plt.savefig(save_path, dpi=300, bbox_inches="tight")
        plt.close()
        print(f"✅ 图像已保存到 {save_path}")
    else:
        plt.show()
