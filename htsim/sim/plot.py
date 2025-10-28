#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
绘图命令行工具，用于从实验配置或绘图配置生成图表
"""

import argparse
import sys
from pathlib import Path

# 添加当前目录到路径
sys.path.insert(0, str(Path(__file__).parent))

from analysis.viz.plot_generator import write_plot_configs
from analysis.viz.plot_from_yaml import plot_from_config


def main():
    parser = argparse.ArgumentParser(description="网络实验绘图工具")
    subparsers = parser.add_subparsers(dest="command", help="子命令")

    # 从实验YAML生成绘图配置
    gen_parser = subparsers.add_parser("generate", help="从实验YAML生成绘图配置")
    gen_parser.add_argument("experiment_yaml", help="实验YAML文件路径")
    gen_parser.add_argument("--output-dir", help="输出目录路径")

    # 从绘图配置生成图表
    plot_parser = subparsers.add_parser("plot", help="从绘图配置生成图表")
    plot_parser.add_argument("plot_yaml", help="绘图配置YAML文件路径")

    # 一步完成从实验YAML到图表
    auto_parser = subparsers.add_parser("auto", help="从实验YAML自动生成图表")
    auto_parser.add_argument("experiment_yaml", help="实验YAML文件路径")

    args = parser.parse_args()

    if args.command == "generate":
        output_dir = Path(args.output_dir) if args.output_dir else None
        output_files = write_plot_configs(args.experiment_yaml, output_dir)
        print(f"生成了 {len(output_files)} 个绘图配置文件:")
        for file in output_files:
            print(f"  - {file}")

    elif args.command == "plot":
        try:
            output_file = plot_from_config(args.plot_yaml)
            if output_file:
                print(f"成功生成图表: {output_file}")
            else:
                print("生成图表失败")
                return 1
        except Exception as e:
            print(f"错误: {e}")
            return 1

    elif args.command == "auto":
        # 先生成绘图配置
        output_files = write_plot_configs(args.experiment_yaml)
        if not output_files:
            print("未找到绘图配置，请确认实验YAML中包含plot字段")
            return 1

        # 然后生成图表
        success_count = 0
        for config_file in output_files:
            try:
                output_file = plot_from_config(config_file)
                if output_file:
                    print(f"成功生成图表: {output_file}")
                    success_count += 1
            except Exception as e:
                print(f"处理 {config_file} 时出错: {e}")

        print(f"共生成 {success_count}/{len(output_files)} 个图表")
        if success_count < len(output_files):
            return 1

    else:
        parser.print_help()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())