# data/metrics.py
import pandas as pd
from typing import Dict


def compute_fct(df: pd.DataFrame) -> pd.DataFrame:
    """
    计算流完成时间（FCT）

    Args:
        df: 包含流信息的DataFrame

    Returns:
        添加了fct_ns字段的DataFrame
    """
    if "fct_ns" not in df.columns:
        df["fct_ns"] = df["finish_time"] - df["start_time"]
    return df


def compute_max_fct(df: pd.DataFrame) -> float:
    """
    计算最大流完成时间

    Args:
        df: 包含流信息的DataFrame

    Returns:
        最大FCT值（纳秒）
    """
    # return float(df["fct_ns"].max().fillna(0.0))
    return float(df["fct_ns"].fillna(0.0).max())


def compute_avg_fct(df: pd.DataFrame) -> float:
    """
    计算平均流完成时间

    Args:
        df: 包含流信息的DataFrame

    Returns:
        平均FCT值（纳秒）
    """
    # return float(df["fct_ns"].mean().fillna(0.0))
    return float(df["fct_ns"].fillna(0.0).mean())


def compute_percentile_fct(df: pd.DataFrame, percentile: float = 99) -> float:
    """
    计算特定百分位的流完成时间

    Args:
        df: 包含流信息的DataFrame
        percentile: 百分位数（0-100）

    Returns:
        指定百分位的FCT值（纳秒）
    """
    quantile_val = df["fct_ns"].fillna(0.0).quantile(percentile / 100)
    return float(quantile_val)


def compute_fct_statistics(df: pd.DataFrame) -> Dict[str, float]:
    """
    计算FCT的各种统计指标

    Args:
        df: 包含流信息的DataFrame

    Returns:
        包含各种FCT统计指标的字典
    """
    df = compute_fct(df)

    # 确保所有值都是float类型
    min_val = df["fct_ns"].fillna(0.0).min()
    max_val = df["fct_ns"].fillna(0.0).max()
    mean_val = df["fct_ns"].fillna(0.0).mean()
    median_val = df["fct_ns"].fillna(0.0).median()
    p95_val = df["fct_ns"].fillna(0.0).quantile(0.95)
    p99_val = df["fct_ns"].fillna(0.0).quantile(0.99)
    std_val = df["fct_ns"].fillna(0.0).std()

    stats = {
        "min_fct_ns": float(min_val),
        "max_fct_ns": float(max_val),
        "avg_fct_ns": float(mean_val),
        "median_fct_ns": float(median_val),
        "p95_fct_ns": float(p95_val),
        "p99_fct_ns": float(p99_val),
        "std_fct_ns": float(std_val),
    }

    return stats


def compute_throughput(df: pd.DataFrame) -> float:
    """
    计算总吞吐量（字节/秒）

    Args:
        df: 包含流信息的DataFrame

    Returns:
        总吞吐量（字节/秒）
    """
    total_bytes = float(df["size_bytes"].sum())
    max_time_ns = float(df["finish_time"].max())
    min_time_ns = float(df["start_time"].min())

    duration_sec = (max_time_ns - min_time_ns) / 1e9
    throughput = total_bytes / duration_sec if duration_sec > 0 else 0.0

    return float(throughput)
