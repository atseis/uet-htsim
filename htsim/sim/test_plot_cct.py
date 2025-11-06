import sys
from pathlib import Path

# 将项目根目录添加到 Python 路径，以便正确导入 analysis 模块
project_root = Path(__file__).parent
sys.path.insert(0, str(project_root))

# 导入绘图模块
from analysis.plot import plot_cct_comparison

if __name__ == "__main__":
    # 定义要分析的结果目录
    base_results_dir = (
        "/root/code/uet-htsim/htsim/sim/results/SimpleTests/cct_algorithms/"
    )

    print(f"🚀 正在运行 FCT CDF 绘图测试...")
    print(f"   - 分析目录: {base_results_dir}")

    # 调用绘图函数
    plot_cct_comparison.plot_cct_comparison(base_results_dir)

    print(
        f"✅ FCT CDF 绘图测试完成。图表已保存到每个实验结果目录下的 'plots' 文件夹中。"
    )
