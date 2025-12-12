import re
from pathlib import Path
from typing import Dict, List, Callable, Set, Optional, Tuple
from functools import cached_property
from collections import defaultdict

# ====================================
# 1. 常量与正则定义
# ====================================

FLOW_PATTERN = re.compile(r"^([^_]+)_([0-9]+)_([0-9]+)$")

# ====================================
# 2. Matcher 注册机制 (保持全局)
# ====================================

matcher_registry: Dict[str, Callable[[str], bool]] = {}


def matcher(name: str):
    """Decorator to register a matcher"""

    def decorator(func):
        matcher_registry[name] = func
        return func

    return decorator


# ====================================
# 3. 具体的 Matcher 定义
# ====================================


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
# 4. IdMap 核心类封装
# ====================================


class IdMap:
    """
    IdMap 封装了 idmap.txt 的读取与查询逻辑。
    支持像字典一样访问 {id: name}，同时提供高性能的分类筛选方法。
    """

    def __init__(self, path: Path):
        self._path = path

    def __repr__(self):
        status = "loaded" if "data" in self.__dict__ else "lazy"
        return f"<IdMap: {self._path.name} ({status})>"

    # ----------------------------------------------------
    # 基础数据访问 (Dict-like Interface)
    # ----------------------------------------------------

    @cached_property
    def data(self) -> Dict[int, str]:
        """
        惰性读取 idmap.txt 文件。只有在第一次访问 .data 或使用字典方法时才会触发 IO。
        """
        if not self._path.is_file():
            # 视业务需求，这里可以选择抛错或者返回空字典
            # raise FileNotFoundError(f"idmap.txt 文件不存在: {self._path}")
            return {}

        _map: Dict[int, str] = {}
        with self._path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                try:
                    id_str, name = line.split(maxsplit=1)
                    _map[int(id_str)] = name
                except ValueError:
                    # 可以记录日志，这里暂且跳过
                    continue
        return _map

    def __getitem__(self, key: int) -> str:
        return self.data[key]

    def __contains__(self, key: int) -> bool:
        return key in self.data

    def get(self, key: int, default=None):
        return self.data.get(key, default)

    def items(self):
        return self.data.items()

    def keys(self):
        return self.data.keys()

    def values(self):
        return self.data.values()

    def __len__(self):
        return len(self.data)

    # ----------------------------------------------------
    # 粗粒度分类属性 (Cached Properties)
    # ----------------------------------------------------

    def _extract_ids_by_category(self, categories: List[str]) -> List[int]:
        """内部通用筛选函数"""
        result = set()
        active_matchers = [
            matcher_registry[cat] for cat in categories if cat in matcher_registry
        ]

        if not active_matchers:
            return []

        for _id, name in self.data.items():
            for func in active_matchers:
                if func(name):
                    result.add(_id)
                    break
        return sorted(result)

    @cached_property
    def sources(self) -> List[int]:
        """
        对应 matcher: src
        辨析：返回的是流 ID(Logged)，并非节点 ID
        """
        return self._extract_ids_by_category(["src"])

    @cached_property
    def sinks(self) -> List[int]:
        """
        对应 matcher: sink
        辨析：返回的是流 ID(Logged)，并非节点 ID
        """
        return self._extract_ids_by_category(["sink"])

    @cached_property
    def queues(self) -> List[int]:
        """对应 matcher: queue"""
        return self._extract_ids_by_category(["queue"])

    @cached_property
    def pipes(self) -> List[int]:
        """对应 matcher: pipe"""
        return self._extract_ids_by_category(["pipe"])

    @cached_property
    def switches(self) -> List[int]:
        """对应 matcher: switch"""
        return self._extract_ids_by_category(["switch"])

    @cached_property
    def short_flows(self) -> List[int]:
        """对应 matcher: short_flow"""
        return self._extract_ids_by_category(["short_flow"])

    # ----------------------------------------------------
    # 细粒度筛选逻辑 (Business Logic)
    # ----------------------------------------------------

    def get_flows_from_src(self, src_id: int) -> List[int]:
        """
        找出源自 src_id 的所有流 ID。
        注意：根据原有逻辑，这里是从 'sink' 集合中筛选，
        这通常意味着我们查找的是在该源发出的、并在某处汇聚的完整流记录。
        """
        # 格式: *_sink_<src>_<dest> -> split('_') -> [-2] is src
        return [i for i in self.sinks if int(self.data[i].split("_")[-2]) == src_id]

    def get_flows_to_dest(self, dest_id: int) -> List[int]:
        """找出汇聚到 dest_id 的所有流 ID"""
        # 格式: *_sink_<src>_<dest> -> split('_') -> [-1] is dest
        return [i for i in self.sinks if int(self.data[i].split("_")[-1]) == dest_id]

    def get_last_hop_queues(self) -> List[int]:
        """筛选 Last Hop Queues (LS->DST)"""
        pattern = re.compile(r"LS\d+->DST\d+\(\d+\)")
        return [i for i in self.queues if pattern.match(self.data[i])]

    def get_queues_by_tor(self, tor_id: int) -> List[int]:
        """筛选特定 ToR 下的 Queues"""
        pattern = re.compile(rf"LS{tor_id}->DST\d+\(\d+\)")
        return [i for i in self.queues if pattern.match(self.data[i])]

    # ----------------------------------------------------
    # 聚合分析 (Aggregators)
    # ----------------------------------------------------

    @cached_property
    def _src_sink_pairs(self) -> Tuple[Set[int], Set[int]]:
        """辅助方法：解析所有流名中的 (src, sink) 节点 ID 集合"""
        srcs, sinks = set(), set()
        for i in self.sinks:
            # 假设命名规范严格为 *_sink_SRC_DEST
            parts = self.data[i].split("_")
            try:
                src, sink = parts[-2], parts[-1]
                srcs.add(int(src))
                sinks.add(int(sink))
            except (IndexError, ValueError):
                continue
        return srcs, sinks

    @property
    def all_src_nodes(self) -> List[int]:
        """所有作为 Source 出现过的节点 ID"""
        return sorted(list(self._src_sink_pairs[0]))

    @property
    def all_sink_nodes(self) -> List[int]:
        """所有作为 Sink 出现过的节点 ID"""
        return sorted(list(self._src_sink_pairs[1]))

    @cached_property
    def sink_map(self) -> Dict[int, List[int]]:
        """
        返回 {dest_node_id: [flow_id_1, flow_id_2...]}
        用于快速查找某个节点接收了哪些流
        """
        mapping = defaultdict(list)
        for i in self.sinks:
            try:
                dest = int(self.data[i].split("_")[-1])
                mapping[dest].append(i)
            except (IndexError, ValueError):
                continue
        return dict(mapping)

    @cached_property
    def src_map(self) -> Dict[int, List[int]]:
        """
        返回 {src_node_id: [flow_id_1, flow_id_2...]}
        用于快速查找某个节点发出了哪些流
        """
        mapping = defaultdict(list)
        for i in self.sinks:  # 注意：原逻辑是基于 sink 列表分析 source
            try:
                src = int(self.data[i].split("_")[-2])
                mapping[src].append(i)
            except (IndexError, ValueError):
                continue
        return dict(mapping)

