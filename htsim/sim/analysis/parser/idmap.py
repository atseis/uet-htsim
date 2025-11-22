import re
from typing import Dict, List, Callable, Union
from pathlib import Path

FLOW_PATTERN = re.compile(r"^([^_]+)_([0-9]+)_([0-9]+)$")


def get_idmap_path(path: Union[str, Path]) -> Path:
    p = Path(path)

    if p.is_dir():
        candidate = p / "idmap.txt"
        if candidate.is_file():
            return candidate
    elif p.is_file():
        candidate = p.parent / "idmap.txt"
        if candidate.is_file():
            return candidate
    else:
        raise FileNotFoundError(f"Path {path} 不存在")

    raise FileNotFoundError(f"idmap.txt 未在路径 {p} 中找到")


def read_idmap(idmap_path: Path) -> Dict[int, str]:
    """
    读取 idmap.txt 文件，返回 {id: name} 字典
    """
    if not idmap_path.is_file():
        raise FileNotFoundError(f"idmap.txt 文件不存在: {idmap_path}")

    idmap: Dict[int, str] = {}
    with idmap_path.open("r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            try:
                id_str, name = line.split(maxsplit=1)
                idmap[int(id_str)] = name
            except ValueError:
                raise ValueError(f"idmap.txt 格式错误，无法解析行: {line}")

    return idmap


def parse_flow_id(value: str):
    m = FLOW_PATTERN.match(value)
    if not m:
        return None
    proto, src, sink = m.groups()
    return proto, src, sink


def build_from_index(mapping: dict[int, str]):
    flows_by_src = {}
    flows_by_sink = {}
    for id, value in mapping.items():
        parsed = parse_flow_id(value)
        if not parsed:
            continue
        proto, src, sink = parsed
        flows_by_src.setdefault(int(src), []).append(id)
        flows_by_sink.setdefault(int(sink), []).append(id)
    return flows_by_src, flows_by_sink


# ====================================
# Matcher registry
# 粗粒度 matcher: protocol-agnostic
matcher_registry: Dict[str, Callable[[str], bool]] = {}


def matcher(name: str):
    """Decorator to register a matcher"""

    def decorator(func):
        matcher_registry[name] = func
        return func

    return decorator


# ------------------------------------
# 1. 粗粒度 matcher 定义
@matcher("src")
def match_src(name: str) -> bool:
    # matches all protocol sources: *_<src>_<dest>
    return bool(re.match(r"^[A-Za-z]+_\d+_\d+$", name))


@matcher("sink")
def match_sink(name: str) -> bool:
    # matches all protocol sinks: *_sink_<src>_<dest>
    return bool(re.match(r"[A-Za-z]+_sink_\d+_\d+$", name))


@matcher("queue")
def match_queue(name: str) -> bool:
    # queues include LS->DST, SRC->LS, Queue-nt-ns, Queue-ns-nt
    patterns = [
        r"LS\d+->DST\d+\(\d+\)",
        r"SRC\d+->LS\d+\(\d+\)",
        r"Queue-nt-ns-\d+-\d+",
        r"Queue-ns-nt-\d+-\d+",
    ]
    return any(re.match(p, name) for p in patterns)


@matcher("pipe")
def match_pipe(name: str) -> bool:
    # pipes include Pipe-LS->DST, Pipe-SRC->SW, Pipe-nt-ns, Pipe-ns-nt
    patterns = [
        r"Pipe-LS\d+->DST\d+\(\d+\)",
        r"Pipe-SRC\d+->SW\d+",
        r"Pipe-nt-ns-\d+-\d+",
        r"Pipe-ns-nt-\d+-\d+",
    ]
    return any(re.match(p, name) for p in patterns)


@matcher("switch")
def match_switch(name: str) -> bool:
    # ToR, Aggregation, Core, or general Switch
    return bool(
        re.match(
            r"(Switch_.*|Switch_LowerPod_\d+|Switch_UpperPod_\d+|Switch_Core_\d+)", name
        )
    )


@matcher("short_flow")
def match_short_flow(name: str) -> bool:
    # short flows
    return bool(re.match(r"sf_\d+_\d+\(\d+\)", name))


# ====================================
# 2. 粗粒度筛选函数
# 当前可用 categories: src, sink, queue, pipe, switch, short_flow
def extract_ids(idmap: Dict[int, str], categories: List[str]) -> List[int]:
    """
    Extract IDs from idmap based on coarse category names
    Usage:
        all_src_ids = extract_ids(idmap, ["src"])
        all_queue_ids = extract_ids(idmap, ["queue"])
    """
    result = set()
    for cat in categories:
        if cat not in matcher_registry:
            continue
        matcher_func = matcher_registry[cat]
        for _id, name in idmap.items():
            if matcher_func(name):
                result.add(_id)
    return sorted(result)


# ====================================
# 3. 细粒度筛选函数
# 基于粗粒度结果进一步过滤
# 这里的 ids 是通过粗粒度过滤得到
# RAW functions (based on input id list)
# src 也从 SINK 事件当中获取
def raw_src_from(idmap: Dict[int, str], ids: List[int], src_id: int) -> List[int]:
    return [i for i in ids if int(idmap[i].split("_")[-2]) == src_id]


def raw_sink_to(idmap: Dict[int, str], ids: List[int], dest_id: int) -> List[int]:
    return [i for i in ids if int(idmap[i].split("_")[-1]) == dest_id]


def raw_last_hop_queue(idmap: Dict[int, str], ids: List[int]) -> List[int]:
    pattern = re.compile(r"LS\d+->DST\d+\(\d+\)")
    return [i for i in ids if pattern.match(idmap[i])]


def raw_queue_by_tor(idmap: Dict[int, str], ids: List[int], tor_id: int) -> List[int]:
    pattern = re.compile(rf"LS{tor_id}->DST\d+\(\d+\)")
    return [i for i in ids if pattern.match(idmap[i])]


# ---------------------
# Direct filter functions (one-step)
def filter_src_from(idmap: Dict[int, str], src_id: int) -> List[int]:
    return raw_src_from(idmap, extract_ids(idmap, ["sink"]), src_id)


def filter_sink_to(idmap: Dict[int, str], dest_id: int) -> List[int]:
    return raw_sink_to(idmap, extract_ids(idmap, ["sink"]), dest_id)


def filter_last_hop_queue(idmap: Dict[int, str]) -> List[int]:
    return raw_last_hop_queue(idmap, extract_ids(idmap, ["queue"]))


def filter_queue_by_tor(idmap: Dict[int, str], tor_id: int) -> List[int]:
    return raw_queue_by_tor(idmap, extract_ids(idmap, ["queue"]), tor_id)


# -----
def extract_all_src_sink_ids(idmap: Dict[int, str]):
    keys = extract_ids(idmap, ["sink"])
    srcs, sinks = set(), set()
    for i in keys:
        src, sink = idmap[i].split("_")[-2], idmap[i].split("_")[-1]
        srcs.add(int(src))
        sinks.add(int(sink))
    return list(srcs), list(sinks)


# map: 对于每个节点，在哪些 flow 当中作为 sink
def get_sink_IDlist_maps(idmap: Dict[int, str]):
    _, sinks = extract_all_src_sink_ids(idmap)
    sink_map = {}
    for sink in sinks:
        sink_map[sink] = filter_sink_to(idmap, sink)
    return sink_map


# map: 对于每个节点，在哪些 flow 当中作为 src
def get_src_IDlist_maps(idmap: Dict[int, str]):
    srcs, _ = extract_all_src_sink_ids(idmap)
    src_map = {}
    for src in srcs:
        src_map[src] = filter_src_from(idmap, src)
    return src_map
