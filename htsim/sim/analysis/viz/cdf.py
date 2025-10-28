# viz/cdf.py
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os
from typing import Optional, Tuple, List, Union


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
    save_path: Optional[str] = None,
    title: str = "Flow Completion Time CDF Comparison",
    x_label: str = "FCT (ms)",
    y_label: str = "CDF",
    convert_to_ms: bool = True,
    x_cut_percentile: float = 99.9,  # 裁剪横轴范围到 99.9% 分位
    show_stats: bool = True,  # 是否打印每组统计
    x_range_auto: bool = False, # 新增：是否自动识别X轴范围
    x_range_manual: Optional[List[Union[int, float]]] = None, # 新增：手动指定X轴范围 [min, max]
) -> None:
    """
    绘制多个实验的流完成时间(FCT)累积分布函数(CDF)对比图

    Args:
        dfs: 含'fct_ns'列的 DataFrame 列表
        labels: 每个 DataFrame 的标签
        save_path: 若非 None，则保存图片到路径
        title, x_label, y_label: 图表标题与坐标轴标签
        convert_to_ms: 是否将纳秒转换为毫秒
        x_cut_percentile: 用于限制横轴范围的分位点 (默认99.9%)
        show_stats: 是否打印每组统计结果
    """
    if len(dfs) != len(labels):
        raise ValueError("❌ dfs 与 labels 长度必须相同")

    plt.figure(figsize=(10, 6))
    plt.grid(True, linestyle="--", alpha=0.7)

    max_cut_value = 0  # 用于裁剪横轴

    for df, label in zip(dfs, labels):
        if "fct_ns" not in df.columns:
            raise ValueError(f"DataFrame '{label}' 缺少 'fct_ns' 列")

        fct_values = df["fct_ns"].to_numpy(dtype=np.float64)
        if convert_to_ms:
            fct_values /= 1e6
        fct_values = np.sort(fct_values)

        if len(fct_values) == 0:
            print(f"⚠️ 警告: '{label}' 数据为空，跳过")
            continue

        # 计算CDF
        y_values = np.arange(1, len(fct_values) + 1) / len(fct_values)
        plt.plot(
            fct_values, y_values, linestyle="-", marker=".", markersize=4, label=label
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
                f"📊 [{label}] FCT统计 (ms): "
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
    elif x_range_auto:
        # 自动识别范围，可以根据实际数据进行微调
        all_fct_values = np.concatenate([df["fct_ns"].to_numpy(dtype=np.float64) / 1e6 for df in dfs if not df.empty])
        if len(all_fct_values) > 0:
            min_val = np.min(all_fct_values)
            max_val = np.max(all_fct_values)
            # 稍微扩展一下范围，避免数据点正好在边界上
            plt.xlim(left=min_val * 0.9, right=max_val * 1.1)
        else:
            plt.xlim(left=0, right=max_cut_value)
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
