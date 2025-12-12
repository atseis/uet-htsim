import os
import pandas as pd
from pathlib import Path
from typing import Union, Dict

# 引入重构后的类
from .fileinfo import ExperimentResult

# 引入具体的计算逻辑 (保持 metrics 纯粹负责数学计算)
from .metrics import compute_fct_statistics


def get_latencies_from_exp(exp: ExperimentResult, var="conns") -> Dict:
    """
    针对单个实验对象计算 Latency 统计信息。
    注意：输入参数从 path 变成了 ExperimentResult 对象。
    """
    # 1. 获取配置变量 (直接从缓存取)
    var_value = exp.status_vars[var]

    # 2. 获取 DataFrame (直接从缓存取)
    df = exp.flow_df

    # 3. 计算统计指标 (调用外部数学函数)
    stats = compute_fct_statistics(df)

    # 4. 组装结果
    stats[var] = var_value
    stats["path"] = str(exp.base_dir)  # 记录路径方便回溯

    return stats


def collect_latencies_by_var(root_path: Union[str, Path], var="conns"):
    """
    扫描目录，批量聚合结果
    """
    results = []
    root = Path(root_path)

    if not root.exists():
        print(f"Error: {root} not found.")
        return pd.DataFrame()

    # 遍历目录
    for entry in os.scandir(root):
        if entry.is_dir() and entry.name != "plots":
            try:
                # A. 实例化对象 (此时只做基本路径检查)
                exp = ExperimentResult(entry.path)

                # B. 计算并收集 (此时才会触发耗时的日志读取)
                stats = get_latencies_from_exp(exp, var=var)
                results.append(stats)

            except FileNotFoundError as e:
                # 容错处理：如果某个子文件夹不是有效实验，跳过并记录
                print(f"Skipping {entry.name}: {e}")
            except Exception as e:
                print(f"Error processing {entry.name}: {e}")

    # 生成最终报表
    df = pd.DataFrame(results)

    # 简单的排序逻辑
    if not df.empty and var in df.columns:
        df = df.sort_values(by=var)

    return df
