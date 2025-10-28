#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从绘图配置YAML文件生成图表
"""

import yaml
import os
import sys
import pandas as pd
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

# 导入现有分析组件
from ..parser import flow as flow_parser
from ..data import metrics
from . import cdf

# 项目根目录
PROJECT_DIR = Path(__file__).parent.parent.parent


def load_plot_config(config_file: str) -> Dict[str, Any]:
    """加载绘图配置文件"""
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


def get_output_files(source_dir: Path) -> List[Path]:
    """获取源目录中的所有output.log文件"""
    output_files = []
    for root, _, files in os.walk(source_dir):
        for file in files:
            if file == "output.log":
                output_files.append(Path(root) / file)
    return output_files


def plot_cdf_fct(config: Dict[str, Any]) -> str:
    """绘制FCT CDF图"""
    sources = config.get("sources", [])
    if not sources:
        raise ValueError("未指定数据源")

    results_dir = PROJECT_DIR / "results"
    dfs = []
    labels = []

    for source in sources:
        source_path = results_dir / source
        if not source_path.exists():
            print(f"警告: 源目录不存在: {source_path}")
            continue

        output_files = get_output_files(source_path)
        if not output_files:
            print(f"警告: 未找到输出文件: {source_path}")
            continue

        # 处理每个输出文件
        for output_file in output_files:
            try:
                # 解析流信息
                flow_data = flow_parser.parse_flow_events_from_file(str(output_file))
                if flow_data.empty:
                    continue

                # 计算FCT指标
                fct_df = metrics.compute_fct(flow_data)
                if fct_df.empty:
                    continue

                # 添加到数据集
                variant_name = output_file.parent.name
                fct_df["variant"] = variant_name
                dfs.append(fct_df)
                if variant_name not in labels:
                    labels.append(variant_name)
            except Exception as e:
                print(f"处理文件时出错 {output_file}: {e}")

    if not dfs:
        raise ValueError("未找到有效的FCT数据")

    # 合并所有数据
    all_data = pd.concat(dfs, ignore_index=True)

    # 绘制CDF
    output_path = config.get("output", "fct_cdf.png")
    title = config.get("title", "Flow Completion Time CDF")
    x_label = config.get("x_label", "FCT (ms)")
    y_label = config.get("y_label", "CDF")

    # 调用现有的CDF绘图函数
    cdf.plot_multiple_fct_cdf(
        dfs,
        labels,
        save_path=output_path,
        title=title,
        x_label=x_label,
        y_label=y_label,
    )
    print(f"已保存FCT CDF图表: {output_path}")

    return str(output_path)


def plot_throughput(config: Dict[str, Any]) -> str:
    """绘制吞吐量图表"""
    # 这里实现吞吐量绘图逻辑，类似于plot_cdf_fct
    # 使用现有的分析组件
    print("吞吐量绘图功能尚未实现")
    return ""


def plot_from_config(config_file: str) -> Optional[str]:
    """根据配置文件生成图表"""
    config = load_plot_config(config_file)
    plot_type = config.get("plot_type")

    if not plot_type:
        raise ValueError("配置文件中未指定plot_type")

    # 根据绘图类型调用相应的绘图函数
    if plot_type == "cdf-fct":
        return plot_cdf_fct(config)
    elif plot_type == "throughput":
        return plot_throughput(config)
    else:
        print(f"不支持的绘图类型: {plot_type}")
        return None


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="从绘图配置YAML生成图表")
    parser.add_argument("config_file", help="绘图配置YAML文件路径")
    args = parser.parse_args()

    try:
        output_file = plot_from_config(args.config_file)
        if output_file:
            print(f"成功生成图表: {output_file}")
            sys.exit(0)
        else:
            print("生成图表失败")
            sys.exit(1)
    except Exception as e:
        print(f"错误: {e}")
        sys.exit(1)
