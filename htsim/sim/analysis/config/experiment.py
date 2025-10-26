from ..runner import BUILD_DIR, PROJECT_DIR
import yaml, itertools, subprocess, os
from typing import Dict, Any, List
from pathlib import Path
import yaml
from . import traffic_patterns
from ..runner import PROJECT_DIR, run_sim


# 定义项目根目录
from typing import Dict, Any, List
from . import traffic_patterns
from ..runner import BUILD_DIR, PROJECT_DIR, run_sim
import yaml


def deep_merge(a: Dict[str, Any], b: Dict[str, Any]) -> Dict[str, Any]:
    result = dict(a)
    for k, v in b.items():
        if k in result and isinstance(result[k], dict) and isinstance(v, dict):
            result[k] = deep_merge(result[k], v)
        else:
            result[k] = v
    return result


def expand_params_tree(params: Dict[str, Any]) -> List[Dict[str, Any]]:
    """递归展开任意层级的 list 值，生成参数组合列表"""
    if not params:
        return [{}]
    combos: List[Dict[str, Any]] = [{}]
    for key, val in params.items():
        new_combos: List[Dict[str, Any]] = []
        if isinstance(val, dict):
            subvariants = expand_params_tree(val)
            for base in combos:
                for sub in subvariants:
                    new_combos.append({**base, key: sub})
        elif isinstance(val, list) and key != "log":
            for base in combos:
                for v in val:
                    new_combos.append({**base, key: v})
        else:
            for base in combos:
                new_combos.append({**base, key: val})
        combos = new_combos
    return combos


def build_flags(params: Dict[str, Any]) -> List[str]:
    """将字典转换为命令行参数列表 [-k v ...]，忽略列表/字典类型"""
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
    """
    根据合并后的参数生成连接矩阵文件
    """
    # 若存在嵌套的 params，则将其平铺到顶层
    nested = (
        traffic_params.get("params", {})
        if isinstance(traffic_params.get("params"), dict)
        else {}
    )
    if nested:
        traffic_params = deep_merge(
            {k: v for k, v in traffic_params.items() if k != "params"}, nested
        )

    traffic_type = traffic_params.get("type")
    if not traffic_type:
        raise ValueError("traffic.type 未指定")

    # 默认与别名处理
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

    if traffic_type == "allreduce":
        cm_file = traffic_patterns.generate_allreduce_traffic(
            nodes, conns, groupsize, flowsize, locality, randseed
        )
    elif traffic_type == "allreduce_butterfly":
        cm_file = traffic_patterns.generate_allreduce_butterfly_traffic(
            nodes, groups, groupsize, flowsize, locality, randseed
        )
    elif traffic_type == "serial_alltoall":
        cm_file = traffic_patterns.generate_serial_alltoall_traffic(
            nodes, conns, groupsize, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "incast":
        cm_file = traffic_patterns.generate_incast_traffic(
            nodes, conns, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "outcast_incast":
        cm_file = traffic_patterns.generate_outcast_incast_traffic(
            nodes, conns_incast, conns_outcast, flowsize, randseed
        )
    elif traffic_type == "permutation":
        cm_file = traffic_patterns.generate_permutation_traffic(
            nodes, conns, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "permutation_full_bisection":
        cm_file = traffic_patterns.generate_permutation_full_bisection_traffic(
            nodes, conns, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "serialn_alltoall":
        cm_file = traffic_patterns.generate_serialn_alltoall_traffic(
            nodes, conns, groupsize, parallel, flowsize, extrastarttime, randseed
        )
    elif traffic_type == "serialn_alltoall_prio":
        cm_file = traffic_patterns.generate_serialn_alltoall_prio_traffic(
            nodes, conns, groupsize, parallel, flowsize, extrastarttime, randseed
        )
    else:
        raise ValueError(f"不支持的流量类型: {traffic_type}")

    return cm_file


def run_experiment(config: Dict[str, Any]):
    """
    运行实验：先展开参数组合（流量+模拟），再分别执行流量生成与模拟
    """
    common = config.get("common", {})
    common_traffic = common.get("traffic", {})
    common_sim = common.get("simulation", {})
    common_flat = {
        k: v for k, v in common.items() if k not in ("traffic", "simulation")
    }

    experiments = config.get("experiments", [])
    for exp in experiments:
        exp_name = exp.get("name", "exp")
        exe_name = exp.get("exe")
        if not exe_name:
            raise ValueError(f"实验 {exp_name} 缺少 exe 字段")
        exe = exe_name  # runner.run_sim 会在 BUILD_DIR 下寻找该二进制
        protocol = exp.get("protocol")
        execute = exp.get("execute", common.get("execute", False))

        # 从 common_flat 中移除 execute 字段，因为它不应该作为模拟器参数传递
        if "execute" in common_flat:
            del common_flat["execute"]

        base_traffic = deep_merge(common_traffic, exp.get("traffic", {}))
        base_sim = deep_merge(common_sim, exp.get("simulation", {}))

        traffic_variants = expand_params_tree(base_traffic)
        sim_variants = expand_params_tree(base_sim)

        for t_var in traffic_variants:
            # 生成 CM 文件
            cm_file = generate_traffic(t_var, common)
            for s_var in sim_variants:
                # 仿真参数：合并 common 的非 traffic/simulation 字段
                sim_params = s_var
                # 确保 execute 不作为模拟器参数传递
                if "execute" in sim_params:
                    del sim_params["execute"]
                if "conns" in sim_params:
                    del sim_params["conns"]
                flags = build_flags({**common_flat, **sim_params, "tm": cm_file})

                # 输出名称包含当前组合关键信息
                def flatten_for_label(d: Dict[str, Any]) -> List[str]:
                    items: List[str] = []
                    for k, v in d.items():
                        if isinstance(v, dict):
                            # 将嵌套键平铺
                            for sk, sv in v.items():
                                if not isinstance(sv, (list, dict)):
                                    items.append(f"{sk}{sv}")
                        elif not isinstance(v, (list, dict)):
                            items.append(f"{k}{v}")
                    return items

                label_parts: List[str] = flatten_for_label(s_var) + flatten_for_label(
                    t_var
                )
                label_suffix = "_".join(label_parts) if label_parts else "default"
                prefix = f"{exp_name}_" + (f"{protocol}_" if protocol else "")
                out_name = f"{prefix}{label_suffix}"

                if execute:
                    run_sim(exe, flags + ["-o", out_name])
                else:
                    print(f"[Run] {exe} {' '.join(flags)} -o {out_name}")


def load_config(config_file: str) -> Dict[str, Any]:
    """
    加载YAML配置文件

    参数:
        config_file: 配置文件路径

    返回:
        Dict[str, Any]: 配置字典
    """
    with open(config_file, "r") as f:
        return yaml.safe_load(f)


def main(config_file: str):
    """
    主函数，加载配置并运行实验

    参数:
        config_file: 配置文件路径
    """
    config = load_config(config_file)
    run_experiment(config)


if __name__ == "__main__":
    import sys

    if len(sys.argv) > 1:
        main(sys.argv[1])
    else:
        print("Usage: python experiment.py <config_file>")
