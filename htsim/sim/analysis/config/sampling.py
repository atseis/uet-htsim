import numpy as np
from typing import Dict, Any, List, Tuple, Set


def _normalize_sampling_config(sampling_cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    归一化 sampling 配置:
    - method: cartesian | lhs | orthogonal(暂未实现)
    - samples: int
    - seed: int | None
    - continuous: List[str]
    """
    method = sampling_cfg.get("method", sampling_cfg.get("type", "cartesian"))
    if method not in ("cartesian", "lhs", "orthogonal"):
        raise ValueError(f"未知 sampling.method: {method}")

    samples = int(sampling_cfg.get("samples", 0) or 0)
    seed = sampling_cfg.get("seed", None)
    if seed is not None:
        seed = int(seed)
    continuous = sampling_cfg.get("continuous", []) or []
    if not isinstance(continuous, list):
        raise ValueError("sampling.continuous 必须是参数名列表")

    return {
        "method": method,
        "samples": samples,
        "seed": seed,
        "continuous": set(map(str, continuous)),
        "log_continuous": set(map(str, sampling_cfg.get("log_continuous", []) or [])),
    }


def _extract_param_domains(
    params: Dict[str, Any],
    continuous_keys: Set[str],
    log_continuous_keys: Set[str] = set(),
) -> Dict[str, Dict[str, Any]]:
    """
    从一个平坦参数字典中提取“域”信息。
    域类型:
        - fixed: 固定值
        - discrete: 离散集合
        - continuous: 连续区间 [low, high]
    说明:
        - 对于 key 在 continuous_keys 中:
            * 若值为 [a, b] 或 (a, b) 且 a!=b => 视为连续区间
            * 否则仍按 fixed 处理（避免误解）
        - 对于不在 continuous_keys 中:
            * list/tuple => discrete
            * 其他 => fixed
    """
    domains: Dict[str, Dict[str, Any]] = {}
    for k, v in params.items():
        # 跳过嵌套结构，这类复杂组合仍由上层逻辑处理
        if isinstance(v, dict):
            continue

        if k in continuous_keys or k in log_continuous_keys:
            if isinstance(v, (list, tuple)) and len(v) == 2:
                # 根据 YAML 原始类型判断是“整数区间”还是“实数区间”
                orig_low, orig_high = v[0], v[1]
                is_int_interval = isinstance(orig_low, int) and isinstance(
                    orig_high, int
                )
                low, high = float(orig_low), float(orig_high)
                if low == high:
                    # 退化为单点：保持原有整数/浮点语义
                    domains[k] = {
                        "type": "fixed",
                        "value": int(low) if is_int_interval else float(low),
                    }
                else:
                    domains[k] = {
                        "type": "log_continuous" if k in log_continuous_keys else "continuous",
                        "low": low,
                        "high": high,
                        "as_int": is_int_interval,
                    }
            else:
                domains[k] = {"type": "fixed", "value": v}
        else:
            if k == "log":
                domains[k] = {"type": "fixed", "value": v}
            elif isinstance(v, (list, tuple)):
                vals = list(v)
                if len(vals) == 1:
                    domains[k] = {"type": "fixed", "value": vals[0]}
                else:
                    domains[k] = {"type": "discrete", "values": vals}
            else:
                domains[k] = {"type": "fixed", "value": v}
    return domains


def _sample_lhs(
    domains: Dict[str, Dict[str, Any]],
    samples: int,
    seed: int | None = None,
) -> List[Dict[str, Any]]:
    """
    针对给定 domains 执行简单的 LHS 采样。
    - 连续变量: 标准 LHS 分层采样
    - 离散变量: 在 [0,1] 分层后映射到索引 (近似 LHS，允许重复)
    - 固定变量: 所有样本一致
    """
    if samples <= 0:
        raise ValueError("LHS 采样需要 samples > 0")

    rng = np.random.default_rng(seed)
    keys = list(domains.keys())
    dim = len(keys)

    # 每个维度一个随机排列，实现分层不重叠
    perms = [rng.permutation(samples) for _ in range(dim)]

    results: List[Dict[str, Any]] = []
    for s in range(samples):
        point: Dict[str, Any] = {}
        for i, k in enumerate(keys):
            info = domains[k]
            t = info["type"]
            if t == "fixed":
                # 避免 numpy 标量写进 YAML/JSON
                val = info["value"]
                if isinstance(val, np.generic):
                    val = val.item()
                point[k] = val
                continue

            j = perms[i][s]
            u = (j + rng.random()) / samples  # u in (j/n, (j+1)/n)

            if t == "continuous":
                low, high = float(info["low"]), float(info["high"])
                as_int = bool(info.get("as_int", False))
                sampled = low + float(u) * (high - low)
                if as_int:
                    # 1) 在 [low, high] 上按连续 LHS 采样
                    # 2) 映射到整数网格并截断到边界，保证整数 randseed / conns 等
                    iv = int(round(sampled))
                    lo_i, hi_i = int(round(low)), int(round(high))
                    iv = max(lo_i, min(hi_i, iv))
                    point[k] = iv
                else:
                    point[k] = float(sampled)
            elif t == "log_continuous":
                low, high = float(info["low"]), float(info["high"])
                as_int = bool(info.get("as_int", False))
                # Log sampling: sample exponent u in [0, 1] mapped to [log(low), log(high)]
                log_low, log_high = np.log10(max(low, 1e-10)), np.log10(high)
                sampled_log = log_low + float(u) * (log_high - log_low)
                sampled = 10**sampled_log
                
                if as_int:
                    iv = int(round(sampled))
                    lo_i, hi_i = int(round(low)), int(round(high))
                    iv = max(lo_i, min(hi_i, iv))
                    point[k] = iv
                else:
                    point[k] = float(sampled)
            elif t == "discrete":
                vals = info["values"]
                idx = min(int(float(u) * len(vals)), len(vals) - 1)
                val = vals[idx]
                if isinstance(val, np.generic):
                    val = val.item()
                point[k] = val
            else:
                raise RuntimeError(f"未知域类型: {t}")
        
        # 后处理：ECN 约束 (ecn_low < ecn_high)
        if "ecn_low" in point and "ecn_high" in point:
            el, eh = point["ecn_low"], point["ecn_high"]
            if el >= eh:
                # 如果违反约束，交换或调整
                # 策略：保持 ecn_low 不变，将 ecn_high 设为 ecn_low + 一个小增量
                # 但不超过 ecn_high 的原始上界
                if "ecn_high" in domains:
                    eh_info = domains["ecn_high"]
                    if eh_info["type"] == "continuous":
                        eh_max = eh_info["high"]
                        point["ecn_high"] = min(el + 0.1, eh_max)
                    else:
                        point["ecn_high"] = el + 0.1
                else:
                    point["ecn_high"] = el + 0.1
        
        results.append(point)
    return results


def generate_sampled_variants(
    base_traffic: Dict[str, Any],
    base_sim: Dict[str, Any],
    sampling_cfg: Dict[str, Any],
) -> List[Tuple[Dict[str, Any], Dict[str, Any]]]:
    """
    统一入口:
    - method=cartesian: 保持原有行为（基于 list 进行笛卡尔积），忽略 continuous 语义。
    - method=lhs: 使用 continuous+离散定义在 traffic+simulation 的并集上做 LHS 采样，
                  然后拆回 t_var/s_var。
    - method=orthogonal: 暂未实现，显式抛错。

    约束（当前版本）:
    - 若 method 为 lhs，则不支持在 traffic/simulation 中继续使用嵌套的 params 列表结构，
      即 base_traffic/base_sim 应该是“展开后”的平坦参数字典。
    """
    cfg = _normalize_sampling_config(sampling_cfg or {})
    method = cfg["method"]

    # 默认/兼容路径：完全沿用旧的笛卡尔积逻辑，由上层的 expand_params_tree 处理
    if method == "cartesian" or not sampling_cfg:
        return []  # 上层用“空列表”表示“按旧逻辑处理”

    if method == "orthogonal":
        raise NotImplementedError(
            "sampling.method='orthogonal' 暂未实现，请先使用 'cartesian' 或 'lhs'"
        )

    # method == 'lhs'
    continuous_keys: Set[str] = set(cfg["continuous"])
    log_continuous_keys: Set[str] = set(cfg.get("log_continuous", []))
    joint: Dict[str, Any] = {}

    # 注意：traffic/simulation 中同名键必须语义一致；冲突直接由调用者规避
    joint.update(base_traffic)
    joint.update(base_sim)

    domains = _extract_param_domains(joint, continuous_keys, log_continuous_keys)
    joint_samples = _sample_lhs(domains, cfg["samples"], cfg["seed"])

    variants: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
    t_keys = set(base_traffic.keys())
    s_keys = set(base_sim.keys())

    for sample in joint_samples:
        t_var = {k: v for k, v in sample.items() if k in t_keys}
        s_var = {k: v for k, v in sample.items() if k in s_keys}
        # 补回固定/未在 domains 中显式出现但在 base_* 中存在的键
        for src, dst in ((base_traffic, t_var), (base_sim, s_var)):
            for k, v in src.items():
                if k not in dst:
                    dst[k] = v
        variants.append((t_var, s_var))

    return variants

