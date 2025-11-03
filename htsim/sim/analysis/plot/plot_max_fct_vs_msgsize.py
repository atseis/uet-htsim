import re
from pathlib import Path
import yaml
import matplotlib.pyplot as plt
import pandas as pd
from typing import Dict, Any, List

from ..data import metrics
from ..parser import flow
from ..config import status, traffic_patterns

import matplotlib.pyplot as plt
from matplotlib.ticker import FuncFormatter

DEFAULT_PLOT_OPTIONS = {
    "title": "Max FCT vs. Message Size",
    "y_label": "Max Flow Completion Time",
    "x_label": "Message Size",
    "x_unit": "bytes",
    "y_unit": "ms",
    "x_range_manual": None,
    "y_range_manual": None,
    "x_range_auto": True,
    "y_range_auto": True,
    "x_log_scale": True,
    "y_log_scale": False,
    "show_grid": True,
    "legend_loc": "best",
    "figsize": [10, 6],
    "output_format": "png",
}

def extract_flowsize_from_cm_filename(path: str) -> str:
    """
    从 CM 文件名中提取 flowsize（如 "2MB", "512KiB", "1.5GiB"）。
    要求 flowsize 以下划线分隔（前面有 "_"）并且后面跟下划线或文件尾 ".cm"。
    返回干净的字符串（不含下划线或额外空格）。
    如果找不到则抛出 ValueError。
    """
    filename = Path(path).name

    # 使用前瞻和后顾断言确保不把下划线包含进捕获组
    pattern = re.compile(r"(?i)(?<=_)(\d+(?:\.\d+)?\s*(?:[KMGT](?:i)?B))(?=_|\.cm$)")

    m = pattern.search(filename)
    if not m:
        # 作为最后手段，尝试在整个文件名中寻找常见单位（更宽松）
        fallback = re.search(r"(?i)(\d+(?:\.\d+)?\s*(?:[KMGT](?:i)?B))", filename)
        if fallback:
            return fallback.group(1).strip()
        raise ValueError(f"无法从文件名中提取 flowsize: {filename}")

    return m.group(1).strip()

def parse_command_args(command_str: str) -> Dict[str, str]:
    """
    解析命令行字符串，提取参数及其值。
    例如: "/path/to/executable -k1 v1 -k2 v2 -o output.log" -> {"k1": "v1", "k2": "v2"}
    """
    args = {}
    matches = re.findall(r'-(\w+)\s+([^\s-]+)', command_str)
    for key, value in matches:
        if key != 'o':
            args[key] = value
    return args

def parse_tm_from_command(command_str: str) -> str:
    """Extract CM file path from command line's -tm parameter."""
    pattern = re.compile(r'-tm\s+(\S+)')
    match = pattern.search(command_str)
    if not match:
        raise ValueError(f"无法从命令中提取 -tm 参数: {command_str}")
    return match.group(1)

def get_common_parameters(data_points: List[Dict]) -> Dict[str, str]:
    if not data_points:
        return {}
    param_dicts = [dp["label_params"] for dp in data_points]
    common_params = param_dicts[0].copy()
    for params in param_dicts[1:]:
        common_params = {k: v for k, v in common_params.items() if k in params and params[k] == v}
    return common_params

def bytes_to_human_readable(x, pos):
    """
    Formats byte values into human-readable strings (e.g., KB, MB, GB).
    """
    if x == 0:
        return "0B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while x >= 1024 and i < len(units) - 1:
        x /= 1024
        i += 1
    # For integer values, display without decimal, otherwise with one decimal place
    if x.is_integer():
        return f"{int(x)}{units[i]}"
    else:
        return f"{x:.1f}{units[i]}"

def plot_max_fct_vs_msgsize(experiment_results_dir: Path):
    experiment_results_dir = Path(experiment_results_dir)
    plots_dir = experiment_results_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    plot_config_path = plots_dir / "max-fct-vs-msgsize.yaml"
    plot_options = DEFAULT_PLOT_OPTIONS.copy()
    lines_config = []

    if not plot_config_path.exists():
        default_config_to_save = {
            "plot_options": DEFAULT_PLOT_OPTIONS,
            "lines": []
        }
        with open(plot_config_path, "w") as f:
            yaml.safe_dump(default_config_to_save, f, sort_keys=False)

    with open(plot_config_path, "r") as f:
        user_config = yaml.safe_load(f)
        if user_config:
            plot_options.update(user_config.get("plot_options", {}))
            lines_config = user_config.get("lines", [])

    y_unit = plot_options.get("y_unit", "ms")
    y_conversion_factor = 1e6
    if y_unit == "us":
        y_conversion_factor = 1e3
    elif y_unit == "ns":
        y_conversion_factor = 1

    output_format = plot_options["output_format"]
    save_path = plots_dir / f"max-fct-vs-msgsize.{output_format}"

    console_output = []
    data_points = []

    console_output.append(f"🚀 正在生成 Max FCT vs. Message Size 图表...")
    console_output.append(f"   - 分析目录: {experiment_results_dir.name}")
    console_output.append(f"   - 绘图配置文件: {plot_config_path}")
    console_output.append(f"   - 输出图表: {save_path}")

    for sub_exp_dir in experiment_results_dir.iterdir():
        if sub_exp_dir.is_dir() and sub_exp_dir.name != "plots":
            status_file = sub_exp_dir / "status.yaml"
            output_log_file = sub_exp_dir / "output.log"

            if status_file.exists() and output_log_file.exists():
                try:
                    exp_status = status.load_status(status_file)
                    command_str = exp_status.get("command", "")

                    tm_path = parse_tm_from_command(command_str)
                    flowsize_str = extract_flowsize_from_cm_filename(tm_path)
                    flowsize_bytes = traffic_patterns.convert_to_bytes(flowsize_str)

                    df_flows = flow.parse_flow_events_from_file(output_log_file.as_posix())
                    if not df_flows.empty:
                        df_flows = metrics.compute_fct(df_flows)
                        max_fct_ns = metrics.compute_max_fct(df_flows)
                        max_fct_converted = max_fct_ns / y_conversion_factor

                        cmd_args = parse_command_args(command_str)
                        label_params = {k: v for k, v in cmd_args.items() if k not in ["o", "tm", "seed", "nodes", "end", "logtime"]}
                        label_params_str = ", ".join([f"{k}={v}" for k, v in sorted(label_params.items())]) or "default_config"

                        data_points.append({
                            "flowsize_bytes": flowsize_bytes,
                            "flowsize_label": flowsize_str,
                            "max_fct_converted": max_fct_converted,
                            "label_params_str": label_params_str,
                            "label_params": label_params
                        })
                    else:
                        console_output.append(f"     ⚠️ {sub_exp_dir.name} 的 output.log 为空或无法解析，跳过。")
                except Exception as e:
                    console_output.append(f"     ❌ 处理 {sub_exp_dir.name} 失败: {e}")
            else:
                console_output.append(f"     ⚠️ {sub_exp_dir.name} 缺少 status.yaml 或 output.log，跳过。")

    if not data_points:
        console_output.append(f"❌ 未找到有效数据点来生成 Max FCT vs. Message Size 图表。")
        print("\n".join(console_output))
        return

    df_data = pd.DataFrame(data_points)
    common_params = get_common_parameters(data_points)
    unique_data_sources = df_data["label_params_str"].unique().tolist()
    existing_data_sources = [line["data_source"] for line in lines_config if "data_source" in line]

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
                "marker": 'o'  # Set default marker to 'o' in YAML for configurability
            })

    updated_config_to_save = {
        "plot_options": plot_options,
        "lines": lines_config
    }
    with open(plot_config_path, "w") as f:
        yaml.safe_dump(updated_config_to_save, f, sort_keys=False)
    console_output.append(f"   - 更新绘图配置文件: {plot_config_path}")

    # Create a mapping from flowsize_bytes to original label and linear index for plotting
    # Assume df_data has 'flowsize_label' column (added during data processing from extract_flowsize_from_cm_filename)
    # First, ensure we have unique (bytes, label) pairs sorted by bytes
    unique_flow_pairs = df_data[['flowsize_bytes', 'flowsize_label']].drop_duplicates().sort_values(by='flowsize_bytes').reset_index(drop=True)
    flowsize_to_index = {row['flowsize_bytes']: i for i, row in unique_flow_pairs.iterrows()}
    df_data['flowsize_index'] = df_data['flowsize_bytes'].map(flowsize_to_index)

    configured_lines_map = {line_cfg["data_source"]: line_cfg for line_cfg in lines_config if "data_source" in line_cfg}

    plt.figure(figsize=plot_options["figsize"])

    for label_params_str, group_df in df_data.groupby("label_params_str"):
        group_df_sorted = group_df.sort_values(by="flowsize_bytes")
        line_cfg = configured_lines_map.get(label_params_str, {})

        plot_label = line_cfg.get("label", label_params_str)
        plot_color = line_cfg.get("color", None)
        plot_linestyle = line_cfg.get("linestyle", '-')
        plot_marker = line_cfg.get("marker", 'o')

        plt.plot(
            group_df_sorted["flowsize_index"], # Use index for plotting
            group_df_sorted["max_fct_converted"],
            marker=plot_marker,
            linestyle=plot_linestyle,
            color=plot_color,
            label=plot_label
        )

    plt.title(plot_options["title"])
    plt.xlabel(f"{plot_options['x_label']} ({plot_options['x_unit']})")
    plt.ylabel(f"{plot_options['y_label']} ({y_unit})")

    if plot_options["x_range_manual"]:
        plt.xlim(plot_options["x_range_manual"])
    elif plot_options["x_range_auto"]:
        plt.autoscale(enable=True, axis='x')

    if plot_options["y_range_manual"]:
        plt.ylim(plot_options["y_range_manual"])
    elif plot_options["y_range_auto"]:
        plt.autoscale(enable=True, axis='y')

    # Set x-axis ticks to linear indices and labels to original extracted strings
    tick_positions = list(range(len(unique_flow_pairs)))
    original_labels = unique_flow_pairs['flowsize_label'].tolist()
    plt.xticks(tick_positions, original_labels)

    # Remove the x_log_scale option as we are using linear indexing for equal spacing
    # if plot_options["x_log_scale"]:
    #     plt.xscale("log")
    #     # Apply custom formatter for human-readable byte sizes
    #     plt.gca().xaxis.set_major_formatter(FuncFormatter(bytes_to_human_readable))

    # The previous unique_flow_sizes and plt.xticks are replaced by the new logic above
    # unique_flow_sizes = sorted(df_data["flowsize_bytes"].unique())
    # plt.xticks(unique_flow_sizes)

    if plot_options["y_log_scale"]:
        plt.yscale("log")

    if plot_options["show_grid"]:
        plt.grid(True, which="both", ls="-", alpha=0.6)

    plt.legend(loc=plot_options["legend_loc"])
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()

    console_output.append(f"✅ 图像已保存到 {save_path}")
    console_output.append(f"✅ Max FCT vs. Message Size 图表生成完成。")
    print("\n".join(console_output))

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate Max FCT vs Message Size plot")
    parser.add_argument("results_dir", help="Path to experiment results directory")
    args = parser.parse_args()
    plot_max_fct_vs_msgsize(Path(args.results_dir))
