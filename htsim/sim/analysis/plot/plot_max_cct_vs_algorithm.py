import re
from pathlib import Path
import yaml
import matplotlib.pyplot as plt
import pandas as pd
from typing import Dict, List, Union

from ..parser import collective
from ..config import status

DEFAULT_PLOT_OPTIONS = {
    "title": "Collective Completion Time vs Algorithm",
    "y_label": "Max Collective Completion Time",
    "x_label": "Algorithm",
    "y_unit": "ms",
    "y_range_manual": None,
    "y_range_auto": True,
    "y_log_scale": False,
    "show_grid": True,
    "legend_loc": "best",
    "figsize": [12, 6],
    "output_format": "png",
    "x_axis_label_map": { # 新增：X轴标签映射
        "allreduce": "Allreduce Ring",
        "allreduce_butterfly": "Allreduce Butterfly"
    }
}


def parse_command_args(command_str: str) -> Dict[str, str]:
    """解析命令行参数 -k v"""
    args = {}
    matches = re.findall(r'-(\w+)\s+([^\s-]+)', command_str)
    for key, value in matches:
        if key not in ['o', 'tm', 'seed', 'nodes', 'end', 'logtime']:
            args[key] = value
    return args


def extract_tm_path(command_str: str) -> str:
    """提取 -tm 参数 CM 文件路径"""
    m = re.search(r"-tm\s+(\S+)", command_str)
    if not m:
        raise ValueError(f"无法从命令中找到 -tm 参数: {command_str}")
    return m.group(1)


def extract_algorithm_from_cm_filename(cm_path: str) -> str:
    """根据 CM 文件名提取算法名"""
    stem = Path(cm_path).stem
    parts = stem.split("_")
    for i, p in enumerate(parts):
        if re.match(r"^\d", p):
            return "_".join(parts[:i])
    return stem


def extract_flowsize_from_cm_filename(cm_path: str) -> str:
    """从 CM 文件名中提取流量大小"""
    stem = Path(cm_path).stem
    match = re.search(r'(\d+(?:KB|MB|GB))', stem)
    if match:
        return match.group(1)
    return "unknown"


def get_common_parameters(data_points: List[Dict]) -> Dict[str, str]:
    if not data_points:
        return {}
    param_dicts = [dp["label_params"] for dp in data_points]
    common = param_dicts[0].copy()
    for pdict in param_dicts[1:]:
        common = {k: v for k, v in common.items() if k in pdict and pdict[k] == v}
    return common


def plot_cct_vs_algorithm(experiment_results_dir: Path):
    experiment_results_dir = Path(experiment_results_dir)
    plots_dir = experiment_results_dir / "plots"
    plots_dir.mkdir(parents=True, exist_ok=True)

    config_path = plots_dir / "cct-vs-algo.yaml"

    plot_options = DEFAULT_PLOT_OPTIONS.copy()
    lines_config = []

    # 创建默认配置文件
    if not config_path.exists():
        with open(config_path, "w") as f:
            yaml.safe_dump({"plot_options": plot_options, "lines": []}, f, sort_keys=False)

    with open(config_path, "r") as f:
        user_config = yaml.safe_load(f) or {}
        plot_options.update(user_config.get("plot_options", {}))
        lines_config = user_config.get("lines", [])

    y_unit = plot_options.get("y_unit", "ms")
    y_factor = {"ms": 1e3, "us": 1e6, "ns": 1e9}.get(y_unit, 1e3)  # collective 返回秒，转 ms

    output_format = plot_options["output_format"]
    save_path = plots_dir / f"cct-vs-algo.{output_format}"

    console = []
    console.append(f"🚀 生成 CCT vs Algorithm 图表...")
    console.append(f"   - 目录: {experiment_results_dir}")
    console.append(f"   - 配置文件: {config_path}")

    data_points = []

    # 扫描子实验
    for subdir in experiment_results_dir.iterdir():
        if not subdir.is_dir() or subdir.name == "plots":
            continue

        status_file = subdir / "status.yaml"
        if not status_file.exists():
            console.append(f"⚠️ {subdir.name} 缺少 status.yaml，跳过")
            continue

        try:
            exp_status = status.load_status(status_file)
            cmd = exp_status.get("command", "")
            cm_path = extract_tm_path(cmd)
            algo = extract_algorithm_from_cm_filename(cm_path)
            # 从 status.yaml 的 variables 字段中提取参数组合
            param_combination = {}
            if "variables" in exp_status:
                for var_item in exp_status["variables"]:
                    for k, v in var_item.items():
                        if k != "type":  # 排除 type 参数
                            param_combination[k] = v
            
            param_combination_str = ", ".join([f"{k}={v}" for k, v in sorted(param_combination.items())]) or "default"

            ccts = collective.get_collective_ccts_from_directory(subdir)
            if not ccts:
                console.append(f"⚠️ {subdir.name} 的 CCT 为空，跳过")
                continue

            max_cct = max(ccts) * y_factor  # 转换到 ms

            data_points.append({
                "algo": algo,
                "max_cct": max_cct,
                "param_combination_str": param_combination_str, # 使用新的参数组合字符串
                "param_combination": param_combination, # 存储参数组合字典
            })
        except Exception as e:
            console.append(f"❌ 处理 {subdir.name} 出错: {e}")

    if not data_points:
        console.append("❌ 未找到有效数据点")
        print("\n".join(console))
        return

    df = pd.DataFrame(data_points)
    # common_params = get_common_parameters(data_points) # 不再需要 common_params

    # 更新 YAML 配置（基于 param_combination_str 生成颜色条目）
    unique_param_combinations = df["param_combination_str"].unique().tolist()
    existing_sources = [l.get("data_source") for l in lines_config]
    for param_str in unique_param_combinations:
        if param_str not in existing_sources:
            param_dict = next(dp["param_combination"] for dp in data_points if dp["param_combination_str"] == param_str)
            simplified_label = ", ".join([f"{k}={v}" for k, v in sorted(param_dict.items())]) or "default"
            lines_config.append({
                "data_source": param_str,
                "label": simplified_label,
                "color": None
            })
    with open(config_path, "w") as f:
        yaml.safe_dump({"plot_options": plot_options, "lines": lines_config}, f, sort_keys=False)

    console.append(f"✅ 配置文件已更新: {config_path}")

    # ---------------- 绘图 ----------------
    plt.figure(figsize=plot_options["figsize"])
    algos = sorted(df["algo"].unique())
    colors_map = {line["data_source"]: line.get("color", None) for line in lines_config}

    # 计算每组最大参数组合数量
    max_params_per_algo = df.groupby("algo")["param_combination_str"].nunique().max()
    width = 0.8 / max_params_per_algo  # 每根柱子宽度

    # 跟踪已添加的图例标签以避免重复
    added_labels = set()

    for i, algo in enumerate(algos):
        df_algo = df[df["algo"] == algo]
        param_combination_strs = df_algo["param_combination_str"].unique()
        n_params = len(param_combination_strs)

        for j, param_str in enumerate(param_combination_strs):
            subset = df_algo[df_algo["param_combination_str"] == param_str]
            y_val = subset["max_cct"].iloc[0] if not subset.empty else 0
            x_pos = i - 0.4 + j * width + width / 2

            cfg = next((l for l in lines_config if l["data_source"] == param_str), {})
            label = cfg.get("label", param_str)
            color = cfg.get("color", None)
            # 仅添加未出现过的图例标签
            current_label = label if label not in added_labels else None
            if current_label:
                added_labels.add(label)
            plt.bar(x_pos, y_val, width=width, color=color, label=current_label)

    x_axis_label_map = plot_options.get("x_axis_label_map", {})
    display_algos = [x_axis_label_map.get(algo, algo) for algo in algos]
    plt.xticks([i for i in range(len(algos))], display_algos, rotation=20)
    plt.title(plot_options["title"])
    plt.xlabel(plot_options["x_label"])
    plt.ylabel(f"{plot_options['y_label']} ({y_unit})")

    if plot_options["y_log_scale"]:
        plt.yscale("log")
    if plot_options["show_grid"]:
        plt.grid(True, axis="y", alpha=0.6)
    plt.legend(loc=plot_options["legend_loc"])
    plt.tight_layout()
    plt.savefig(save_path)
    plt.close()

    console.append(f"✅ 图像已保存: {save_path}")
    print("\n".join(console))


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Generate CCT vs Algorithm plot")
    parser.add_argument("results_dir", help="Path to experiment results directory")
    args = parser.parse_args()
    plot_cct_vs_algorithm(Path(args.results_dir))
