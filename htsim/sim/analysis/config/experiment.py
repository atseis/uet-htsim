from ..runner import BUILD_DIR, PROJECT_DIR
import yaml, itertools, subprocess, os, sys, datetime, shutil
from typing import Dict, Any, List, Optional
from pathlib import Path
from . import traffic_patterns, status
from ..runner import run_sim
from . import sampling as sampling_utils
from ..plot import (
    plot_fct_comparison,
    plot_cct_comparison,
    plot_avg_fct_vs_nodes,
    plot_max_fct_vs_msgsize,
    plot_max_cct_vs_algorithm,
)  # 导入 FCT 绘图函数与 Avg FCT vs Nodes 绘图函数
from ..utils.calculator import (
    NetworkCalculator,
)  # [New] Import Calculator for ECN conversion

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

    # [Start] ECN Intelligent Parsing Logic
    # 1. Initialize Calculator if network params are present
    calc = None
    if "linkspeed" in params:
        try:
            calc = NetworkCalculator.from_simulation_params(params)
        except Exception:
            pass  # Fallback if params missing

    # Helper to resolve single value to packets
    def resolve_val(val):
        if calc is None:
            return val  # No calculator, pass through (risky if string)

        # If string "30KB", "20%" etc.
        if isinstance(val, str):
            val_lower = val.lower()
            if "kb" in val_lower or "mb" in val_lower:
                unit_str = val_lower.replace("kb", "").replace("mb", "")  # naive check
                val_num = float(unit_str)
                # re-delegate to calculator with specific unit
                # but calculator expects strict unit logic.
                # Let's simplify: pass to calculator.convert_ecn
                if "kb" in val_lower:
                    res = calc.convert_ecn(float(val_lower.split("kb")[0]), "kb")
                    return res["Packets"]
            if "p" in val_lower and "%" not in val_lower:  # "20p"
                return int(val_lower.replace("p", ""))
            if "%" in val_lower:
                num = float(val_lower.replace("%", ""))
                res = calc.convert_ecn(
                    num, "ratio_queue"
                )  # User said "ratio = % of queuesize"
                return res["Packets"]

            # [Fix] Handle pure numeric strings (e.g. "0.08")
            try:
                f_val = float(val)
                if 0 < f_val < 1.0:
                    res = calc.convert_ecn(f_val, "ratio_queue")
                    return res["Packets"]
                else:
                    return int(f_val)
            except ValueError:
                pass

        # If float/int
        if isinstance(val, (int, float)):
            if 0 < val < 1.0:
                # User request: "0.2 表示是 queuesize 的 0.2 倍"
                res = calc.convert_ecn(val, "ratio_queue")
                return res["Packets"]
            else:
                return int(val)  # Packets

        return val  # Fallback

    # [End] Helper defined

    for k, v in params.items():
        if v is None or (isinstance(v, str) and v.lower() == "none"):
            continue

        # Special handling for ecn parameter
        if k == "ecn":
            low, high = 0, 0
            if isinstance(v, str):
                parts = v.split()
                if len(parts) == 2:
                    low = resolve_val(parts[0])
                    high = resolve_val(parts[1])
                    flags.extend(["-ecn", str(low), str(high)])
            elif isinstance(v, list) and len(v) == 2:
                low = resolve_val(v[0])
                high = resolve_val(v[1])
                flags.extend(["-ecn", str(low), str(high)])
            continue

        # Skip consolidated ecn_low/high (handled later)
        if k in ("ecn_low", "ecn_high"):
            continue

        if isinstance(v, bool):
            if v:
                flags.append(f"-{k}")  # 仅在 True 时添加“开关型参数”
            continue
        if k == "log" and isinstance(v, list):
            for log_val in v:
                flags.extend([f"-{k}", str(log_val)])
            continue
        if isinstance(v, (list, dict)):
            continue
        flags.extend([f"-{k}", str(v)])

    # Consolidate ecn_low / ecn_high if they exist separately
    e_low = params.get("ecn_low")
    e_high = params.get("ecn_high")
    if e_low is not None and e_high is not None:
        l_val = resolve_val(e_low)
        h_val = resolve_val(e_high)
        flags.extend(["-ecn", str(l_val), str(h_val)])

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
    prefer_remote = traffic_params.get("prefer_remote", 0)

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
            nodes, conns, flowsize, extrastarttime, randseed, prefer_remote
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
    common_sampling = common.get("sampling", {})
    common_flat = {
        k: v for k, v in common.items() if k not in ("traffic", "simulation")
    }

    config_file_path_obj = Path(config_file_path).resolve()

    # [New] Dynamic Path Resolution
    # Locate the right-most "experiments" folder in the path to support relocation/archiving
    experiments_dir = None
    for parent in [config_file_path_obj] + list(config_file_path_obj.parents):
        if parent.name == "experiments":
            experiments_dir = parent
            break

    if experiments_dir:
        # Case A: Standard structure (.../experiments/subdir/test.yaml)
        # We output to sibling .../results/subdir/test
        project_root = experiments_dir.parent
        results_base_dir = project_root / "results"
        relative_path = config_file_path_obj.relative_to(experiments_dir)
    else:
        # Case B: Fallback (Legacy or custom placement)
        # If input is not inside an "experiments" folder, default to PROJECT_DIR logic
        # or just place results relative to the script?
        # For safety/backward compatibility, we default to Project Root logic if possible,
        # but if the file is totally outside, we fallback to CWD/results.
        experiments_dir = PROJECT_DIR / "experiments"
        results_base_dir = PROJECT_DIR / "results"

        try:
            relative_path = config_file_path_obj.relative_to(experiments_dir)
        except ValueError:
            # File is outside standard source tree.
            # Treat the file's parent directory as the "experiment group"
            # Output to <FileParent>/../results/<FileNameWithoutExt>
            # Example: /tmp/my_test.yaml -> /tmp/results/my_test
            results_base_dir = config_file_path_obj.parent.parent / "results"
            relative_path = Path(config_file_path_obj.stem)

    output_dir_name = relative_path.with_suffix("").as_posix()
    current_exp_results_dir = results_base_dir / output_dir_name
    current_exp_results_dir.mkdir(parents=True, exist_ok=True)

    batch_log_path = current_exp_results_dir / "batch_summary.log"
    with open(batch_log_path, "w") as bf:
        bf.write(f"Batch started at {datetime.datetime.now()}\n")

    # === 展开参数组合 ===
    experiments = config.get("experiments", [])

    # === 构建任务列表（支持 sampling） ===
    planned_tasks = []
    all_exp_variants = []

    for exp_idx, exp in enumerate(experiments):
        exp_name = exp.get("name", f"exp_{exp_idx}")
        exe = exp.get("exe")
        if not exe:
            raise ValueError(f"实验 {exp_name} 缺少 exe 字段")
        execute = exp.get("execute", common.get("execute", False))

        base_traffic = deep_merge(common_traffic, exp.get("traffic", {}))
        base_sim = deep_merge(common_sim, exp.get("simulation", {}))
        exp_sampling = deep_merge(common_sampling, exp.get("sampling", {}))

        # 1) 如果 sampling.method 为 lhs/orthogonal，则优先使用 sampling 模块生成组合
        sampled_variants = []
        try:
            sampled_variants = sampling_utils.generate_sampled_variants(
                base_traffic, base_sim, exp_sampling
            )
        except NotImplementedError as e:
            # orthogonal 目前不支持，直接报错避免“假实现”
            raise

        if sampled_variants:
            variants_iter = sampled_variants
        else:
            # 回落到原有笛卡尔积展开（cartesian 或未配置 sampling）
            traffic_variants = expand_params_tree(base_traffic)
            sim_variants = expand_params_tree(base_sim)
            variants_iter = [
                (t_var, s_var) for t_var in traffic_variants for s_var in sim_variants
            ]

        for t_var, s_var in variants_iter:
            # 用于 variable_keys 识别
            all_exp_variants.append({**common_flat, **t_var, **s_var, "name": exp_name})

            # 实际任务登记在后面统一使用 variable_keys 生成 label
            planned_tasks.append(
                {
                    "exp_name": exp_name,
                    "exe": exe,
                    "execute": execute,
                    "t_var": t_var,
                    "s_var": s_var,
                }
            )

    # 依据“真实要跑”的组合识别变量键
    variable_keys = identify_variable_keys(all_exp_variants)

    # 现在根据 variable_keys 补齐 planned_tasks 的输出目录等元信息
    enriched_tasks = []
    for task in planned_tasks:
        exp_name = task["exp_name"]
        t_var = task["t_var"]
        s_var = task["s_var"]

        label_parts = []
        for key in variable_keys:
            val = {**t_var, **s_var}.get(key)
            if val is not None and not isinstance(val, dict):
                clean_val = str(val).replace(" ", "_")
                label_parts.append(f"{key}{clean_val}")
        label_suffix = exp_name + "_".join(label_parts) or exp_name

        out_name = current_exp_results_dir / label_suffix
        out_name.mkdir(parents=True, exist_ok=True)
        status_file = out_name / "status.yaml"

        enriched = {
            **task,
            "label_suffix": label_suffix,
            "out_name": out_name,
            "status_file": status_file,
        }
        enriched_tasks.append(enriched)

    planned_tasks = enriched_tasks

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

            # ================= [Force Rerun: 清理所有旧数据] =================
            if force_rerun:
                # 清理所有旧数据，确保完全干净的重新运行
                # 避免 snapshot/plots 等缓存污染新结果

                # 1. summary.json (指标缓存)
                summary_file = task["out_name"] / "summary.json"
                if summary_file.exists():
                    summary_file.unlink()
                    progress.console.print(f"  [dim]🗑 Cleaned: summary.json[/dim]")

                # 2. snapshot/ 目录 (分析缓存 - parquet/json.gz)
                snapshot_dir = task["out_name"] / "snapshot"
                if snapshot_dir.exists():
                    shutil.rmtree(snapshot_dir)
                    progress.console.print(f"  [dim]🗑 Cleaned: snapshot/[/dim]")

                # 3. plots/ 目录 (旧图表)
                plots_dir = task["out_name"] / "plots"
                if plots_dir.exists():
                    shutil.rmtree(plots_dir)
                    progress.console.print(f"  [dim]🗑 Cleaned: plots/[/dim]")

                # 4. stdout.log (控制台输出)
                old_stdout = task["out_name"] / "stdout.log"
                if old_stdout.exists():
                    old_stdout.unlink()
                    progress.console.print(f"  [dim]🗑 Cleaned: stdout.log[/dim]")
            # =====================================================================

            start_time = datetime.datetime.now()

            try:
                cm_file = generate_traffic(task["t_var"], common)
                sim_params = dict(task["s_var"])
                sim_params.pop("execute", None)
                # effective_common = dict(common_flat)
                # effective_common.pop("execute", None)
                sim_params.pop("conns", None)
                sim_params.pop(
                    "flowsize", None
                )  # Exclude flowsize from simulation flags
                # Extract nodes, conns from traffic
                nodes, conns = task["t_var"]["nodes"], task["t_var"]["conns"]

                # flags = build_flags({**effective_common, **sim_params, "tm": cm_file})
                flags = build_flags({**sim_params, "nodes": nodes, "tm": cm_file})
                full_command = f"{task['exe']} {' '.join(flags)} -o {(task['out_name'] / 'output.log').as_posix()}"

                current_exp_config = deep_merge(task["t_var"], task["s_var"])

                # Construct variables based on identified variable_keys
                task_variables = []
                for key in variable_keys:
                    if (
                        key != "name"
                    ):  # 'name' is already part of the experiment ID/label
                        value = current_exp_config.get(key)
                        if value is not None:
                            task_variables.append({key: value})

                # 构造全量参数字典
                full_params_dict = {**common_flat, **task["t_var"], **task["s_var"]}

                # [New] Compute Relative Path for Source YAML (for archiving portability)
                try:
                    # Make path relative to the directory containing status.yaml (i.e. out_name)
                    source_yaml_rel = os.path.relpath(
                        config_file_path_obj, start=task["out_name"]
                    )
                except ValueError:
                    # Fallback for Windows different drives
                    source_yaml_rel = str(config_file_path_obj)

                status.initialize_status(
                    task["status_file"],
                    full_command,
                    label,
                    variables=task_variables,
                    all_params=full_params_dict,
                    source_yaml=source_yaml_rel,
                )

                if task["execute"]:
                    run_result = run_sim(
                        task["exe"],
                        flags + ["-o", (task["out_name"] / "output.log").as_posix()],
                    )
                    end_time = datetime.datetime.now()
                    dur = (end_time - start_time).total_seconds()
                    durations.append(dur)
                    # ========[新增] 保存 cout/printf 输出========================
                    console_log_path = task["out_name"] / "stdout.log"
                    stdout_content = run_result.get("stdout", "")
                    if stdout_content:
                        try:
                            with open(console_log_path, "w", encoding="utf-8") as f:
                                f.write(str(stdout_content))
                        except TypeError:
                            with open(console_log_path, "wb") as f:
                                f.write(stdout_content)

                    # ============================================================
                    if run_result["exit_code"] == 0:
                        success += 1
                        status.update_status(
                            task["status_file"],
                            "success",
                            exit_code=0,
                            duration_sec=dur,
                            variables=task_variables,
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
                            variables=task_variables,
                        )
                        if not continue_on_error:
                            progress.console.print(f"[red]终止：{last_error}[/red]")
                            break
                else:
                    progress.console.print(f"[yellow]Dry run: {full_command}[/yellow]")
                    success += 1
                    status.update_status(
                        task["status_file"],
                        "success",
                        error_log="Dry run",
                        variables=task_variables,
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
            elif plot_type == "CDF-CCT":
                console.print(
                    f"  ▶️ 生成 CCT CDF 对比图 for {current_exp_results_dir.name}..."
                )
                try:
                    plot_cct_comparison.plot_cct_comparison(current_exp_results_dir)
                    console.print(f"  ✅ CCT CDF 对比图生成成功。")
                except Exception as e:
                    console.print(f"  ❌ 生成 CCT CDF 对比图失败: {e}")
            elif plot_type == "AvgFCT-Nodes":
                console.print(
                    f"  ▶️ 生成 Avg FCT vs Nodes 图 for {current_exp_results_dir.name}..."
                )
                try:
                    plot_avg_fct_vs_nodes.plot_avg_fct_vs_nodes(current_exp_results_dir)
                    console.print(f"  ✅ Avg FCT vs Nodes 图生成成功。")
                except Exception as e:
                    console.print(f"  ❌ 生成 Avg FCT vs Nodes 图失败: {e}")
            elif plot_type == "MaxFCT-MsgSize":
                console.print(
                    f"  ▶️ 生成 Max FCT vs Message Size 图 for {current_exp_results_dir.name}..."
                )
                try:
                    plot_max_fct_vs_msgsize.plot_max_fct_vs_msgsize(
                        current_exp_results_dir
                    )
                    console.print(f"  ✅ Max FCT vs Message Size 图生成成功。")
                except Exception as e:
                    console.print(f"  ❌ 生成 Max FCT vs Message Size 图失败: {e}")
            elif plot_type == "CCT-Algo":
                console.print(
                    f"  ▶️ 生成 CCT vs Algorithm 图 for {current_exp_results_dir.name}..."
                )
                try:
                    plot_max_cct_vs_algorithm.plot_cct_vs_algorithm(
                        current_exp_results_dir
                    )
                    console.print(f"  ✅  CCT vs Algorithm 图生成成功。")
                except Exception as e:
                    console.print(f"  ❌ 生成 CCT vs Algorithm 图失败: {e}")
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
