import sys
from pathlib import Path

# 导入绘图模块
from analysis.plot import plot_max_cct_vs_algorithm

if __name__ == "__main__":
    # 定义要分析的结果目录
    # 请将此路径替换为您的实际实验结果目录
    base_results_dir = "/root/code/uet-htsim/htsim/sim/results/SimpleTests/cct_algorithms"

    print(f"🚀 正在运行 Max CCT vs. Algorithm 绘图测试...")
    print(f"   - 分析目录: {base_results_dir}")

    # 调用绘图函数
    plot_max_cct_vs_algorithm.plot_cct_vs_algorithm(base_results_dir)

    print(f"✅ Max CCT vs. Algorithm 绘图测试完成。图表已保存到每个实验结果目录下的 'plots' 文件夹中。")