from ..runner import BUILD_DIR, PROJECT_DIR
import yaml, itertools, subprocess, os, sys, datetime
from typing import Dict, Any, List
from pathlib import Path
from . import traffic_patterns, status
from ..runner import run_sim
from ..plot import (
    plot_fct_comparison,
    plot_avg_fct_vs_nodes,
)  # 导入 FCT 绘图函数与 Avg FCT vs Nodes 绘图函数

# === 新增 rich 进度条支持 ===
from rich.progress import (
    Progress,
    TextColumn,
    BarColumn,
    MofNCompleteColumn,
    TimeElapsedColumn,
    TimeRemainingColumn,
)
from rich.console import Console

console = Console()


# === 工具函数 ===


def deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(a)
    for k, v in b.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def expand_params_tree(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """展开参数字典，其中允许 params 是“参数组的组合组合”"""
    if not params:
        return [{}]

    # 普通键值（非 params）的展开
    base_combos = [{}]
    for key, val in params.items():
        if key == "params" or key == "log":
            continue  # params 特殊处理
        new_combos = []
        if isinstance(val, list):
            for base in base_combos:
                for v in val:
                    new_combos.append({**base, key: v})
        else:
            for base in base_combos:
                new_combos.append({**base, key: val})
        base_combos = new_combos

    # 处理 params: list[list[dict]] 或 list[dict]
    param_groups = params.get("params", [])
    if param_groups:
        # 如果 params 是单层列表（即没有嵌套），视为只有一组参数
        if all(isinstance(x, dict) for x in param_groups):
            param_groups = [param_groups]

        def cartesian_product(groups: List[List[Dict[str, Any]]]):
            combos = [{}]
            for group in groups:
                new_combos = []
                for base in combos:
                    for option in group:
                        new_combos.append({**base, **option})
                combos = new_combos
            return combos

        param_combos = cartesian_product(param_groups)
    else:
        param_combos = [{}]

    # 与基础键笛卡尔积
    full_combos = []
    for base in base_combos:
        for combo in param_combos:
            result = {**base, **combo}
            if "log" in params:
                result["log"] = params["log"]
            full_combos.append(result)

    return full_combos


def build_flags(params: Dict[str, Any]) -> List[str]:
    """将字典转换为命令行参数列表 [-k v ...]"""
    flags: List[str] = []
    for k, v in params.items():
        if k == "log" and isinstance(v, list):
            for log_val in v:
                flags.extend([f"-{k}", str(log_val)])
            continue
        if isinstance(v, (list, dict)):
            continue
        if isinstance(v, bool):
            v = 1 if v else 0
        flags.extend([f"-{k}", str(v)])
    return flags


def generate_traffic(traffic_params: Dict[str, Any], common_config: Dict[str, Any]):
    """根据合并后的参数生成连接矩阵文件"""
    # nested = (
    #     traffic_params.get("params", {})
    #     if isinstance(traffic_params.get("params"), dict)
    #     else {}
    # )
    # if nested:
    #     traffic_params = deep_merge(
    #         {k: v for k, v in traffic_params.items() if k != "params"}, nested
    #     )
    #
    traffic_type = traffic_params.get("type")
    if not traffic_type:
        raise ValueError("traffic.type 未指定")

    # 默认参数
    nodes = traffic_params.get("nodes", common_config.get("nodes", 16))
    conns = traffic_params.get("conns", traffic_params.get("flows", 16))
    groupsize = traffic_params.get("groupsize", 16)
    flowsize = traffic_params.get("flowsize", "2MB")
    extrastarttime = traffic_params.get("extrastarttime", 0)
    parallel = traffic_params.get("parallel", 1)
    locality = traffic_params.get("locality", 0)
    groups = traffic_params.get("groups", 1)
    randseed = traffic_params.get("randseed", common_config.get("seed", 0))
    conns_incast = traffic_params.get("conns_incast", 8)
    conns_outcast = traffic_params.get("conns_outcast", 8)

    # 流量类型分派
    tp = traffic_patterns
    if traffic_type == "allreduce":
        cm_file = tp.generate_allreduce_traffic(
            nodes, conns, groupsize, flowsize, locality, randseed
        )
    elif traffic_type == "allreduce_butterfly":
        cm_file = tp.generate_allreduce_butterfly_traffic(
            nodes, groups, groupsize, flowsize, locality, randseed
        )
    elif traffic_type == "serial_alltoall":
        cm_file = tp.generate_serial_alltoall_traffic(
            nodes, conns, groupsize, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "incast":
        cm_file = tp.generate_incast_traffic(
            nodes, conns, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "outcast_incast":
        cm_file = tp.generate_outcast_incast_traffic(
            nodes, conns_incast, conns_outcast, flowsize, randseed
        )
    elif traffic_type == "permutation":
        cm_file = tp.generate_permutation_traffic(
            nodes, conns, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "permutation_full_bisection":
        cm_file = tp.generate_permutation_full_bisection_traffic(
            nodes, conns, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "serialn_alltoall":
        cm_file = tp.generate_serialn_alltoall_traffic(
            nodes, conns, groupsize, parallel, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "serialn_alltoall_prio":
        cm_file = tp.generate_serialn_alltoall_prio_traffic(
            nodes, conns, groupsize, parallel, flowsize, extrastarttime, randseed
        )
    else:
        raise ValueError(f"不支持的流量类型: {traffic_type}")

    return cm_file


def identify_variable_keys(all_variants: List[Dict[str, Any]]) -> List[str]:
    """识别所有变体中变化的键"""
    if not all_variants:
        return []
    variable_keys = {"name"}
    all_keys = {k for v in all_variants for k in v}
    for key in all_keys:
        values = {str(v.get(key)) for v in all_variants}
        if len(values) > 1:
            variable_keys.add(key)
    return sorted(list(variable_keys))


# === 主体函数 ===


def run_experiment(
    config: Dict[str, Any],
    config_file_path: str,
    force_rerun: bool = False,
    continue_on_error: bool = False,
):
    common = config.get("common", {})
    common_traffic = common.get("traffic", {})
    common_sim = common.get("simulation", {})
    common_flat = {
        k: v for k, v in common.items() if k not in ("traffic", "simulation")
    }

    experiments_dir = PROJECT_DIR / "experiments"
    results_base_dir = PROJECT_DIR / "results"

    config_file_path_obj = Path(config_file_path).resolve()
    relative_path = config_file_path_obj.relative_to(experiments_dir)
    output_dir_name = relative_path.with_suffix("").as_posix()
    current_exp_results_dir = results_base_dir / output_dir_name
    current_exp_results_dir.mkdir(parents=True, exist_ok=True)

    batch_log_path = current_exp_results_dir / "batch_summary.log"
    with open(batch_log_path, "w") as bf:
        bf.write(f"Batch started at {datetime.datetime.now()}\n")

    # === 展开参数组合 ===
    experiments = config.get("experiments", [])
    all_exp_variants = []
    for exp_idx, exp in enumerate(experiments):
        exp_name = exp.get("name", f"exp_{exp_idx}")
        base_traffic = deep_merge(common_traffic, exp.get("traffic", {}))
        base_sim = deep_merge(common_sim, exp.get("simulation", {}))
        for t_var in expand_params_tree(base_traffic):
            for s_var in expand_params_tree(base_sim):
                all_exp_variants.append(
                    {**common_flat, **t_var, **s_var, "name": exp_name}
                )

    variable_keys = identify_variable_keys(all_exp_variants)

    # === 构建任务列表 ===
    planned_tasks = []
    for exp_idx, exp in enumerate(experiments):
        exp_name = exp.get("name", f"exp_{exp_idx}")
        exe = exp.get("exe")
        if not exe:
            raise ValueError(f"实验 {exp_name} 缺少 exe 字段")
        execute = exp.get("execute", common.get("execute", False))

        base_traffic = deep_merge(common_traffic, exp.get("traffic", {}))
        base_sim = deep_merge(common_sim, exp.get("simulation", {}))
        traffic_variants = expand_params_tree(base_traffic)
        sim_variants = expand_params_tree(base_sim)

        for t_var in traffic_variants:
            for s_var in sim_variants:
                label_parts = []
                for key in variable_keys:
                    val = {**t_var, **s_var}.get(key)
                    if val is not None and not isinstance(val, dict):
                        label_parts.append(f"{key}{val}")
                label_suffix = "_".join(label_parts) or "default"

                out_name = current_exp_results_dir / label_suffix
                out_name.mkdir(parents=True, exist_ok=True)
                status_file = out_name / "status.yaml"

                planned_tasks.append(
                    {
                        "exp_name": exp_name,
                        "exe": exe,
                        "execute": execute,
                        "t_var": t_var,
                        "s_var": s_var,
                        "label_suffix": label_suffix,
                        "out_name": out_name,
                        "status_file": status_file,
                    }
                )

    total_count = len(planned_tasks)
    done = success = failed = skipped = 0
    durations: List[float] = []
    last_error = ""

    # === 检查可跳过任务 ===
    to_run = []
    for task in planned_tasks:
        if not status.should_run(task["status_file"], force_rerun):
            skipped += 1
            done += 1
            with open(batch_log_path, "a") as bf:
                bf.write(f"⚠ [SKIP] {task['label_suffix']}\n")
        else:
            to_run.append(task)

    console.print(
        f"[bold cyan]开始运行批量实验（共 {total_count} 项，跳过 {skipped} 项）[/bold cyan]"
    )

    # === Rich 进度条主循环 ===
    with Progress(
        TextColumn("[bold blue]{task.fields[status]}[/bold blue]"),
        BarColumn(),
        MofNCompleteColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeElapsedColumn(),
        TimeRemainingColumn(),
        TextColumn(
            "✔ {task.fields[success]} ✘ {task.fields[failed]} ⚠ {task.fields[skipped]}"
        ),
        console=console,
        transient=False,
        refresh_per_second=2,
    ) as progress:
        tid = progress.add_task(
            "[green]Running experiments...",
            total=total_count,
            status="",
            success=success,
            failed=failed,
            skipped=skipped,
            completed=skipped,
        )

        for task in to_run:
            label = task["label_suffix"]
            progress.update(tid, status=f"[cyan]{label}[/cyan]")
            start_time = datetime.datetime.now()

            try:
                cm_file = generate_traffic(task["t_var"], common)
                sim_params = dict(task["s_var"])
                sim_params.pop("execute", None)
                # effective_common = dict(common_flat)
                # effective_common.pop("execute", None)
                sim_params.pop("conns", None)
                # Extract nodes, conns from traffic
                nodes, conns = task["t_var"]["nodes"], task["t_var"]["conns"]

                # flags = build_flags({**effective_common, **sim_params, "tm": cm_file})
                flags = build_flags({**sim_params, "nodes": nodes, "tm": cm_file})
                full_command = f"{task['exe']} {' '.join(flags)} -o {(task['out_name'] / 'output.log').as_posix()}"
                status.initialize_status(task["status_file"], full_command, label)

                if task["execute"]:
                    run_result = run_sim(
                        task["exe"],
                        flags + ["-o", (task["out_name"] / "output.log").as_posix()],
                    )
                    end_time = datetime.datetime.now()
                    dur = (end_time - start_time).total_seconds()
                    durations.append(dur)
                    if run_result["exit_code"] == 0:
                        success += 1
                        status.update_status(
                            task["status_file"],
                            "success",
                            exit_code=0,
                            duration_sec=dur,
                        )
                    else:
                        failed += 1
                        last_error = f"{label} → exit {run_result['exit_code']}"
                        status.update_status(
                            task["status_file"],
                            "failed",
                            exit_code=int(run_result["exit_code"]),
                            duration_sec=dur,
                            error_log=str(run_result["stderr"]),
                        )
                        if not continue_on_error:
                            progress.console.print(f"[red]终止：{last_error}[/red]")
                            break
                else:
                    progress.console.print(f"[yellow]Dry run: {full_command}[/yellow]")
                    success += 1
                    status.update_status(
                        task["status_file"], "success", error_log="Dry run"
                    )

                done += 1

            except Exception as e:
                failed += 1
                done += 1
                last_error = str(e)
                progress.console.print(f"[red]任务 {label} 出错: {e}[/red]")
                if not continue_on_error:
                    break

            progress.update(
                tid, advance=1, success=success, failed=failed, skipped=skipped
            )

    console.print(
        f"\n[bold green]✔ 成功:[/bold green] {success}  [red]✘ 失败:[/red] {failed}  [yellow]⚠ 跳过:[/yellow] {skipped}"
    )
    console.print(f"[dim]详细日志: {batch_log_path.as_posix()}[/dim]")

    # === 绘图阶段 ===
    plots_to_generate = config.get("plots", [])
    if plots_to_generate:
        console.print(f"\n[bold magenta]开始生成图表...[/bold magenta]")
        for plot_type in plots_to_generate:
            if plot_type == "CDF-FCT":
                console.print(
                    f"  ▶️ 生成 FCT CDF 对比图 for {current_exp_results_dir.name}..."
                )
                try:
                    plot_fct_comparison.plot_fct_comparison(current_exp_results_dir)
                    console.print(f"  ✅ FCT CDF 对比图生成成功。")
                except Exception as e:
                    console.print(f"  ❌ 生成 FCT CDF 对比图失败: {e}")
            elif plot_type == "AvgFCT-Nodes":
                console.print(
                    f"  ▶️ 生成 Avg FCT vs Nodes 图 for {current_exp_results_dir.name}..."
                )
                try:
                    plot_avg_fct_vs_nodes.plot_avg_fct_vs_nodes(current_exp_results_dir)
                    console.print(f"  ✅ Avg FCT vs Nodes 图生成成功。")
                except Exception as e:
                    console.print(f"  ❌ 生成 Avg FCT vs Nodes 图失败: {e}")
            else:
                console.print(f"  ⚠️ 未知图表类型: {plot_type}，跳过。")
    else:
        console.print(f"\n[dim]未指定任何图表生成。[/dim]")


def load_config(config_file: str) -> Dict[str, Any]:
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


def main(
    config_file_path: str, force_rerun: bool = False, continue_on_error: bool = False
):
    config = load_config(config_file_path)
    run_experiment(config, config_file_path, force_rerun, continue_on_error)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Run network simulation experiments.")
    parser.add_argument("config_file", help="Path to the YAML configuration file.")
    parser.add_argument(
        "--force", action="store_true", help="Force rerun of all experiments."
    )
    parser.add_argument(
        "--continue",
        dest="continue_on_error",
        action="store_true",
        help="Continue on error.",
    )
    args = parser.parse_args()

    main(args.config_file, args.force, args.continue_on_error)
