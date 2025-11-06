import os
import yaml
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional, Union

# Relative imports for modules within analysis
from ..parser import collective
from ..viz import cdf
from ..data import metrics

# 默认绘图配置
DEFAULT_PLOT_OPTIONS = {
    "title": "Collective Completion Time CDF Comparison",
    "y_label": "CDF",
    "x_cut_percentile": 99.9,
    "show_stats": True,
    "x_range_manual": None,
    "x_range_auto": True,
    "x_unit": "ms",  # 新增 X 轴单位配置
    "output_format": "png",  # 新增输出图片格式配置，默认为 png
}


def plot_cct_comparison(base_results_dir: Union[str, Path]):
    base_results_dir = Path(base_results_dir)
    if not base_results_dir.is_dir():
        print(f"❌ 错误: 结果目录不存在: {base_results_dir}")
        return
    # 定义保存图表的路径
    output_plot_dir = base_results_dir / "plots"
    output_plot_dir.mkdir(exist_ok=True)  # 确保目录存在
    image_base_name = "cdf-cct"
    plot_config_path = output_plot_dir / f"{image_base_name}.yaml"

    plot_options = DEFAULT_PLOT_OPTIONS.copy()
    line_configs = []

    if plot_config_path.is_file():
        print(f"🔍 发现绘图配置文件: {plot_config_path}，正在加载...")
        try:
            with open(plot_config_path, "r") as f:
                loaded_config = yaml.safe_load(f)
            if loaded_config:
                plot_options.update(loaded_config.get("plot_options", {}))
                line_configs = loaded_config.get("lines", [])
            print("✅ 绘图配置加载成功。")
        except Exception as e:
            print(
                f"❌ 错误: 加载绘图配置文件 {plot_config_path} 失败: {e}，将使用默认配置。"
            )
    else:
        print(f"⚠️ 未找到绘图配置文件: {plot_config_path}，将生成默认配置并保存。")
        # 动态生成 line_configs
        for sub_exp_dir in sorted(base_results_dir.iterdir()):
            if sub_exp_dir.is_dir() and sub_exp_dir.name != "plots":
                status_file = sub_exp_dir / "status.yaml"
                label = sub_exp_dir.name
                if status_file.is_file():
                    try:
                        with open(status_file, "r") as f:
                            status_data = yaml.safe_load(f)
                        label = status_data.get("label", sub_exp_dir.name)
                    except Exception:
                        pass  # Fallback to directory name
                line_configs.append(
                    {
                        "data_source": sub_exp_dir.name,
                        "label": label,
                        "color": None,  # Default color
                        "linestyle": None,  # Default linestyle
                        "marker": None,  # Default marker
                    }
                )

        # 保存新生成的配置
        with open(plot_config_path, "w") as f:
            yaml.safe_dump(
                {"plot_options": plot_options, "lines": line_configs},
                f,
                sort_keys=False,
            )
        print(f"✅ 已生成并保存新的绘图配置文件到: {plot_config_path}")

    # 根据 x_unit 设置 x_label 和 convert_to_ms
    x_unit = plot_options.get("x_unit", "ms")  # 默认为 ms
    plot_options["x_label"] = f"cct ({x_unit})"
    plot_options["convert_to_ms"] = x_unit == "ms"

    # 根据 output_format 设置 output_plot_path
    output_format = plot_options.get("output_format", "png")
    output_plot_path = output_plot_dir / f"{image_base_name}.{output_format}"

    print(f"   - 输出图表: {output_plot_path}")

    all_ccts = []
    labels = []
    processed_line_configs = []  # 存储实际处理的线条配置

    print(f"🔍 开始处理目录: {base_results_dir}")

    # 遍历 line_configs 来处理数据
    for line_config in line_configs:
        data_source = line_config["data_source"]
        sub_exp_dir = base_results_dir / data_source
        # log_file = sub_exp_dir / "output.log"  # 假设日志文件名为 output.log

        if not sub_exp_dir.is_dir():
            print(f"⚠️ 警告: 数据源目录 {sub_exp_dir} 不存在，跳过此配置项。")
            continue
        label = line_config["label"]
        try:
            ccts = collective.get_collective_ccts_from_directory(sub_exp_dir)
            # print("提取到 CCTS: ", ccts)
            if ccts:
                df_cct = pd.DataFrame(
                    ccts, columns=["fct_ns"]
                )  # 为了直接调用 fct 的函数
                all_ccts.append(df_cct)
                labels.append(label)
                processed_line_configs.append(line_config)  # 记录实际处理的配置
            else:
                print(
                    f"  ⚠️ 警告: {sub_exp_dir} 未解析到有效的集合通信，跳过 {data_source}"
                )
        except Exception as e:
            print(f"  ❌ 错误: 处理 {sub_exp_dir} 时出错: {e}，跳过 {data_source}")
            continue

    if not all_ccts:
        print("没有找到任何有效的cct数据进行绘图。")
        return

    print("📊 正在生成 cct CDF 对比图...")
    # 调用 viz.cdf 中的 plot_multiple_cct_cdf 函数
    cdf.plot_multiple_fct_cdf(
        dfs=all_ccts,
        labels=labels,
        save_path=output_plot_path.as_posix(),
        plot_options=plot_options,
        line_configs=processed_line_configs,
    )
    print("✅ cct CDF 对比图生成完成。")


if __name__ == "__main__":
    # 这是一个示例用法，当脚本直接运行时执行
    # 在实际测试中，我们将使用 test_plot_cct.py 来调用它
    project_root = Path(__file__).parent.parent.parent.parent
    test_dir = project_root / "results" / "SimpleTests" / "oblivious_trim_ecn"
    print(f"--- 内部测试运行 plot_cct_comparison ---")
    plot_cct_comparison(test_dir)
    print(f"--- 内部测试完成 ---")
