#!/usr/bin/env python3
# run_analysis.py - 端到端分析流程

import os
import sys
import argparse
import pandas as pd
import matplotlib.pyplot as plt

from analysis.runner import run_parse
from analysis.parser.flow import parse_flow_events_from_file
from analysis.data.metrics import compute_fct, compute_fct_statistics
from analysis.viz.cdf import plot_fct_cdf


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="分析htsim日志并生成FCT CDF图")
    parser.add_argument("log_file", help="日志文件路径")
    parser.add_argument("--output-dir", "-o", default="./output", help="输出目录")
    args = parser.parse_args()

    # 创建输出目录
    os.makedirs(args.output_dir, exist_ok=True)

    # 运行parse_output并获取ASCII输出
    print(f"正在解析日志文件: {args.log_file}")
    # 直接使用文件，跳过parse_output调用
    print("跳过parse_output调用，直接解析文件")

    # 解析流事件
    print("正在提取流事件...")
    df = parse_flow_events_from_file(args.log_file)

    # 如果DataFrame为空，则退出
    if df.empty:
        print("未找到流事件，请检查日志文件")
        sys.exit(1)

    # 计算FCT
    df = compute_fct(df)

    # 保存到CSV
    csv_path = os.path.join(args.output_dir, "fct.csv")
    df.to_csv(csv_path, index=False)
    print(f"已保存FCT数据到 {csv_path}")

    # 计算统计信息
    stats = compute_fct_statistics(df)
    print("FCT统计信息:")
    for key, value in stats.items():
        print(f"  {key}: {value:.2f} ns")

    # 绘制CDF图
    cdf_path = os.path.join(args.output_dir, "fct_cdf.png")
    plot_fct_cdf(df, save_path=cdf_path)
    print(f"已保存CDF图到 {cdf_path}")

    print("分析完成！")
