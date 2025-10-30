import yaml
import matplotlib.pyplot as plt
import pandas as pd
import re
from pathlib import Path
from typing import Dict, Any, List

from ..data import metrics
from ..parser import flow
from ..config import status

DEFAULT_PLOT_OPTIONS = {
    "title": "Average FCT vs. Nodes",
    "y_label": "Average Flow Completion Time",
    "x_label": "Network Size (hosts)",
    "x_unit": "",
    "y_unit": "ms",
    "x_range_manual": None,
    "y_range_manual": None,
    "x_range_auto": True,
    "y_range_auto": True,
    "x_log_scale": False,
    "y_log_scale": False,
    "show_grid": True,
    "legend_loc": "best",
    "figsize": [10, 6],
    "output_format": "png",
}

def parse_command_args(command_str: str) -> Dict[str, str]:
    """
    解析命令行字符串，提取参数及其值。
    例如: "/path/to/executable -k1 v1 -k2 v2 -o output.log" -> {"k1": "v1", "k2": "v2"}
    """
    args = {}
    # 使用正则表达式匹配 -key value 对
    matches = re.findall(r'-(\w+)\s+([^\s-]+)', command_str)
    for key, value in matches:
        if key != 'o': # 忽略输出文件参数
            args[key] = value
    return args

def get_common_parameters(data_points: List[Dict]) -> Dict[str, str]:
    """
    计算所有实验数据点的公共参数（键值对均相同的参数）
    """
    if not data_points:
        return {}
    param_dicts = [dp["label_params"] for dp in data_points]
    common_params = param_dicts[0].copy()
    for params in param_dicts[1:]:
        common_params = {k: v for k, v in common_params.items() if k in params and params[k] == v}
    return common_params

def plot_avg_fct_vs_nodes(experiment_results_dir: Path):
    """
    给定实验目录，画出其中不同配置下 Avg FCT 随节点数的变化。
    每个子实验对应图上的一个点。
    """
    experiment_results_dir = Path(experiment_results_dir)
    plots_dir = experiment_results_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    console_output = [] # 确保 console_output 始终被初始化

    plot_config_path = plots_dir / "avg-fct-vs-nodes.yaml"
    plot_options = DEFAULT_PLOT_OPTIONS.copy()
    lines_config = []

    if not plot_config_path.exists():
        # 如果配置文件不存在，则创建默认配置文件
        default_config_to_save = {
            "plot_options": DEFAULT_PLOT_OPTIONS,
            "lines": []
        }
        with open(plot_config_path, "w") as f:
            yaml.safe_dump(default_config_to_save, f, sort_keys=False)
        console_output.append(f"   - 生成默认绘图配置文件: {plot_config_path}")

    # 无论是否存在，都从配置文件加载
    with open(plot_config_path, "r") as f:
        user_config = yaml.safe_load(f)
        if user_config:
            plot_options.update(user_config.get("plot_options", {}))
            lines_config = user_config.get("lines", [])

    # Determine y-axis unit conversion
    y_unit = plot_options.get("y_unit", "ms")
    y_conversion_factor = 1e6 # Default to convert ns to ms (1e9 ns / 1e6 = 1e3 us = 1 ms)
    if y_unit == "us":
        y_conversion_factor = 1e3 # Convert ns to us (1e9 ns / 1e3 = 1e6 us = 1e3 ms)
    elif y_unit == "ns":
        y_conversion_factor = 1 # Keep ns as ns
    # Update y_label to reflect the unit
    # plot_options["y_label"] = f"{plot_options['y_label']}{f' ({y_unit})' if y_unit else ''}"

    output_format = plot_options["output_format"]
    save_path = plots_dir / f"avg-fct-vs-nodes.{output_format}"

    console_output = []
    data_points = []

    console_output.append(f"🚀 正在生成 Avg FCT vs. Nodes 图表...")
    console_output.append(f"   - 分析目录: {experiment_results_dir.name}")
    console_output.append(f"   - 绘图配置文件: {plot_config_path}")
    console_output.append(f"   - 输出图表: {save_path}")

    for sub_exp_dir in experiment_results_dir.iterdir():
        if sub_exp_dir.is_dir():
            if sub_exp_dir.name == "plots":
                continue
            status_file = sub_exp_dir / "status.yaml"
            output_log_file = sub_exp_dir / "output.log"

            if status_file.exists() and output_log_file.exists():
                try:
                    exp_status = status.load_status(status_file)
                    command_str = exp_status.get("command", "")

                    # 解析命令参数
                    cmd_args = parse_command_args(command_str)

                    nodes = int(cmd_args.pop("nodes", 0)) # 提取节点数

                    if nodes == 0:
                        console_output.append(f"     ⚠️ 无法从 {sub_exp_dir.name} 的命令中解析出节点数，跳过。")
                        continue

                    # 剩余的参数作为该数据点的唯一标识（完整参数组合）
                    label_params = {k: v for k, v in cmd_args.items() if k not in ["o", "tm", "seed", "nodes"]}
                    label_params_str = ", ".join([f"{k}={v}" for k, v in sorted(label_params.items())])
                    if not label_params_str:
                        label_params_str = "default_config"

                    # 解析 output.log 并计算 Avg FCT
                    df_flows = flow.parse_flow_events_from_file(output_log_file)
                    if not df_flows.empty:
                        df_flows = metrics.compute_fct(df_flows)
                        avg_fct_ns = metrics.compute_avg_fct(df_flows)
                        # avg_fct_ms = avg_fct_ns / 1e6 # 转换为毫秒
                        avg_fct_converted = avg_fct_ns / y_conversion_factor # 转换为指定单位

                        data_points.append({
                            "nodes": nodes,
                            "avg_fct_converted": avg_fct_converted, # Store converted value
                            "label_params_str": label_params_str,
                            "label_params": label_params # 存储原始参数字典用于分组
                        })
                    else:
                        console_output.append(f"     ⚠️ {sub_exp_dir.name} 的 output.log 为空或无法解析，跳过。")
                except Exception as e:
                    console_output.append(f"     ❌ 处理 {sub_exp_dir.name} 失败: {e}")
            else:
                console_output.append(f"     ⚠️ {sub_exp_dir.name} 缺少 status.yaml 或 output.log，跳过。")

    if not data_points:
        console_output.append(f"❌ 未找到有效数据点来生成 Avg FCT vs. Nodes 图表。")
        print("\n".join(console_output))
        return

    df_data = pd.DataFrame(data_points)

    # 计算公共参数并生成/更新线条配置
    common_params = get_common_parameters(data_points)
    unique_data_sources = df_data["label_params_str"].unique().tolist()
    existing_data_sources = [line["data_source"] for line in lines_config if "data_source" in line]

    # 添加新的data_source并生成智能简化标签
    for data_source in unique_data_sources:
        if data_source not in existing_data_sources:
            params_dict = next(dp["label_params"] for dp in data_points if dp["label_params_str"] == data_source)
            simplified_params = {k: v for k, v in params_dict.items() if k not in common_params}
            simplified_label = ", ".join([f"{k}={v}" for k, v in sorted(simplified_params.items())]) or "default_config"
            lines_config.append({
                "data_source": data_source,
                "label": simplified_label,
                "color": None,
                "linestyle": None,
                "marker": None
            })

    # 将更新后的 lines_config 和 plot_options 保存回 YAML 文件
    updated_config_to_save = {
        "plot_options": plot_options,
        "lines": lines_config
    }
    with open(plot_config_path, "w") as f:
        yaml.safe_dump(updated_config_to_save, f, sort_keys=False)
    console_output.append(f"   - 更新绘图配置文件: {plot_config_path}")

    # 构建data_source到线条配置的映射
    configured_lines_map = {line_cfg["data_source"]: line_cfg for line_cfg in lines_config if "data_source" in line_cfg}

    plt.figure(figsize=plot_options["figsize"])

    # 按参数组合分组并绘图

    plt.figure(figsize=plot_options["figsize"])
    
    # 按参数组合分组并绘图
    for label_params_str, group_df in df_data.groupby("label_params_str"):
        group_df_sorted = group_df.sort_values(by="nodes")
        
        line_cfg = configured_lines_map.get(label_params_str, {})
        
        plot_label = line_cfg.get("label", label_params_str)
        plot_color = line_cfg.get("color", None)
        plot_linestyle = line_cfg.get("linestyle", '-')
        plot_marker = line_cfg.get("marker", 'o')

        plt.plot(
            group_df_sorted["nodes"],
            group_df_sorted["avg_fct_converted"], # Use converted value
            marker=plot_marker,
            linestyle=plot_linestyle,
            color=plot_color,
            label=plot_label
        )

    plt.title(plot_options["title"])
    plt.xlabel(f"{plot_options["x_label"]}{f' ({plot_options["x_unit"]})' if plot_options["x_unit"] else ''}")
    plt.ylabel(f"{plot_options["y_label"]}{f' ({y_unit})' if y_unit else ''}") # Use the already formatted y_label

    if plot_options["x_range_manual"]:
        plt.xlim(plot_options["x_range_manual"])
    elif plot_options["x_range_auto"]:
        plt.autoscale(enable=True, axis='x')
    
    if plot_options["y_range_manual"]:
        plt.ylim(plot_options["y_range_manual"])
    elif plot_options["y_range_auto"]:
        plt.autoscale(enable=True, axis='y')

    if plot_options["x_log_scale"]:
        plt.xscale("log")
    if plot_options["y_log_scale"]:
        plt.yscale("log")
    
    if plot_options["show_grid"]:
        plt.grid(True, which="both", ls="-", alpha=0.6)

    plt.legend(loc=plot_options["legend_loc"])
    if not plot_options["x_log_scale"]:
        plt.ticklabel_format(style='plain', axis='x') # 禁用 X 轴科学计数法
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()

    console_output.append(f"✅ 图像已保存到 {save_path}")
    console_output.append(f"✅ Avg FCT vs. Nodes 图表生成完成。")
    print("\n".join(console_output))

if __name__ == "__main__":
    # 指定实验结果目录（来自之前的绘图配置文件路径）
    experiment_dir = Path("/root/code/uet-htsim/htsim/sim/results/SimpleTests/spray_comparison/")
    plot_avg_fct_vs_nodes(experiment_dir)
