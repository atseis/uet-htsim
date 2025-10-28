#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从实验YAML配置文件生成绘图配置文件
"""

import yaml
import os
import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional
from ..runner import PROJECT_DIR

# 绘图类型及其默认配置
PLOT_TEMPLATES = {
    "cdf-fct": {
        "title": "Flow Completion Time CDF",
        "x_label": "FCT (ms)",
        "y_label": "CDF",
        "output_format": "png",
        "legend_loc": "lower right",
        "grid": True,
        "x_range_auto": False, # 新增：是否自动识别X轴范围
        "x_range_manual": None, # 新增：手动指定X轴范围 [min, max]
    },
    "throughput": {
        "title": "Throughput Comparison",
        "x_label": "Time (s)",
        "y_label": "Throughput (Gbps)",
        "output_format": "png",
        "legend_loc": "upper right",
        "grid": True,
    },
    "queue-delay": {
        "title": "Queue Delay",
        "x_label": "Time (s)",
        "y_label": "Delay (μs)",
        "output_format": "png",
        "legend_loc": "upper right",
        "grid": True,
    },
    "cwnd": {
        "title": "Congestion Window",
        "x_label": "Time (s)",
        "y_label": "CWND (packets)",
        "output_format": "png",
        "legend_loc": "upper right",
        "grid": True,
    }
}


def generate_plot_config(
    experiment_yaml_path: str,
    plot_type: str,
    results_dir: Optional[Path] = None,
    output_dir: Optional[Path] = None
) -> Dict[str, Any]:
    """
    为指定的绘图类型生成绘图配置

    Args:
        experiment_yaml_path: 实验YAML文件路径
        plot_type: 绘图类型 (cdf-fct, throughput等)
        results_dir: 结果目录路径，如果为None则从experiment_yaml推断
        output_dir: 输出目录路径，如果为None则使用results_dir/plots

    Returns:
        绘图配置字典
    """
    if plot_type not in PLOT_TEMPLATES:
        raise ValueError(f"不支持的绘图类型: {plot_type}")

    # 加载实验配置
    with open(experiment_yaml_path, 'r') as f:
        experiment_config = yaml.safe_load(f)

    # 确定结果目录
    if results_dir is None:
        # 从实验YAML路径推断结果目录
        experiment_path = Path(experiment_yaml_path).resolve()
        relative_path = experiment_path.relative_to(PROJECT_DIR / "experiments")
        output_dir_name = relative_path.with_suffix("").as_posix()
        results_dir = PROJECT_DIR / "results" / output_dir_name

    # 确定输出目录
    if output_dir is None:
        output_dir = results_dir / "plots"
        output_dir.mkdir(parents=True, exist_ok=True)

    # 获取实验变体目录
    experiment_variants = []
    if results_dir.exists():
        for item in results_dir.iterdir():
            if item.is_dir() and not item.name.startswith('.') and not item.name == "plots":
                experiment_variants.append(item)

    # 创建绘图配置
    plot_config = {
        "generated_from": str(Path(experiment_yaml_path).resolve()),
        "generated_time": datetime.datetime.now().isoformat(),
        "plot_type": plot_type,
        "sources": [
            {
                "path": str(variant.relative_to(PROJECT_DIR / "results")),
                "name": variant.name  # 默认使用目录名作为名称
            }
            for variant in experiment_variants
        ],
        **PLOT_TEMPLATES[plot_type],
        "output": str(output_dir / f"{plot_type}.{PLOT_TEMPLATES[plot_type]['output_format']}")
    }

    # 从实验配置中获取绘图设置并覆盖默认值
    plot_settings = experiment_config.get("plot_settings", {})
    if "x_range_auto" in plot_settings:
        plot_config["x_range_auto"] = plot_settings["x_range_auto"]
    if "x_range_manual" in plot_settings:
        plot_config["x_range_manual"] = plot_settings["x_range_manual"]

    return plot_config


def generate_all_plot_configs(experiment_yaml_path: str) -> Dict[str, Dict[str, Any]]:
    """
    为实验YAML中指定的所有绘图类型生成配置

    Args:
        experiment_yaml_path: 实验YAML文件路径

    Returns:
        绘图类型到配置的映射
    """
    # 加载实验配置
    with open(experiment_yaml_path, 'r') as f:
        experiment_config = yaml.safe_load(f)

    # 获取plot字段
    plot_types = experiment_config.get("plot", [])
    if not plot_types:
        return {}

    # 为每种绘图类型生成配置
    configs = {}
    for plot_type in plot_types:
        configs[plot_type] = generate_plot_config(experiment_yaml_path, plot_type)

    return configs


def write_plot_configs(experiment_yaml_path: str, output_dir: Optional[Path] = None) -> List[str]:
    """
    为实验YAML中指定的所有绘图类型生成配置文件

    Args:
        experiment_yaml_path: 实验YAML文件路径
        output_dir: 输出目录，如果为None则使用实验结果目录

    Returns:
        生成的配置文件路径列表
    """
    configs = generate_all_plot_configs(experiment_yaml_path)
    if not configs:
        return []

    # 确定输出目录
    if output_dir is None:
        experiment_path = Path(experiment_yaml_path).resolve()
        relative_path = experiment_path.relative_to(PROJECT_DIR / "experiments")
        output_dir_name = relative_path.with_suffix("").as_posix()
        output_dir = PROJECT_DIR / "results" / output_dir_name / "plots"
        output_dir.mkdir(parents=True, exist_ok=True)

    # 写入配置文件
    output_files = []
    for plot_type, config in configs.items():
        output_file = output_dir / f"plot_{plot_type}.yaml"
        with open(output_file, 'w') as f:
            yaml.dump(config, f, default_flow_style=False, sort_keys=False)
        output_files.append(str(output_file))

    return output_files


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="从实验YAML生成绘图配置文件")
    parser.add_argument("experiment_yaml", help="实验YAML文件路径")
    parser.add_argument("--output-dir", help="输出目录路径")
    args = parser.parse_args()

    output_dir = Path(args.output_dir) if args.output_dir else None
    output_files = write_plot_configs(args.experiment_yaml, output_dir)
    
    print(f"生成了 {len(output_files)} 个绘图配置文件:")
    for file in output_files:
        print(f"  - {file}")