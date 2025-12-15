import re
from pathlib import Path
from typing import Dict, List, Callable, Set, Optional, Tuple
from functools import cached_property
from collections import defaultdict
from enum import Enum, unique, auto

# ====================================
# 1. 常量与正则定义
# ====================================

FLOW_PATTERN = re.compile(r"^([^_]+)_([0-9]+)_([0-9]+)$")


@unique
class LinkType(Enum):
    """
    定义拓扑链路类型。
    枚举值为 Queue 的正则表达式。
    Pipe 的正则可以通过 "Pipe-" + Queue正则 自动推导。
    """

    # --- Server <-> TOR ---
    TOR_DOWN = r"LS\d+->DST\d+\(\d+\)"  # Last Hop: ToR -> Server
    SERVER_UP = r"SRC\d+->LS\d+\(\d+\)"  # Injection: Server -> ToR

    # --- TOR <-> Aggregation ---
    AGG_DOWN = r"US\d+->LS\d+\(\d+\)"  # Agg -> ToR (无下划线)
    TOR_UP = r"LS\d+->US\d+\(\d+\)"  # ToR -> Agg

    # --- Aggregation <-> Core (3-Tier) ---
    AGG_UP = r"US\d+->CS\d+\(\d+\)"  # Agg -> Core
    CORE_DOWN = r"CS\d+->US\d+\(\d+\)"  # Core -> Agg


@unique
class AdjType(Enum):
    """
    定义节点与组件的邻接关系类型。
    使用 auto() 自动生成值，避免硬编码字符串。
    """

    # --- 接收端 (Ingress) ---
    IN_QUEUE = auto()  # 流入该节点的队列 (例如: ...->LS)
    IN_PIPE = auto()  # 流入该节点的管道

    # --- 发送端 (Egress) ---
    OUT_QUEUE = auto()  # 该节点发出的队列 (例如: LS->...)
    OUT_PIPE = auto()  # 该节点发出的管道


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
    # 1. 匹配标准 Fat-Tree 类型
    if any(re.match(t.value, name) for t in LinkType):
        return True

    # 2. 兼容旧模式
    legacy = [r"Queue-nt-ns-\d+-\d+", r"Queue-ns-nt-\d+-\d+"]
    return any(re.match(p, name) for p in legacy)


@matcher("pipe")
def match_pipe(name: str) -> bool:
    # 1. 匹配标准 Fat-Tree Pipe (前缀 "Pipe-")
    # 注意：这里动态拼接 "Pipe-" + 枚举值
    if any(re.match(r"Pipe-" + t.value, name) for t in LinkType):
        return True

    # 2. 兼容旧模式
    legacy = [r"Pipe-SRC\d+->SW\d+", r"Pipe-nt-ns-\d+-\d+", r"Pipe-ns-nt-\d+-\d+"]
    return any(re.match(p, name) for p in legacy)


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
    格式规定：
    1. 区别两种 id: 小写 id 表示模拟运行中的各种 id; 大写 ID 表示 Logged 分配的、日志中查看到的 ID
        id: 比如 flowid 24, Uec_304_0 中的 304 和 0 就是 id
        ID: 使用 parse_output 从日志中读取到的就是 ID，idmap 中的 key 都是 ID
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

    def _extract_IDs_by_category(self, categories: List[str]) -> List[int]:
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

    # @cached_property
    # def sources(self) -> List[int]:
    #     """
    #     对应 matcher: src
    #     辨析：返回的是流 ID(Logged)，并非节点 ID
    #     """
    #     return self._extract_IDs_by_category(["src"])

    # @cached_property
    # def sinks(self) -> List[int]:
    #     """
    #     (之后尽量使用 flowIDs, 因为命名更直接，保留 sinks 主要是出于兼容)
    #     对应 matcher: sink
    #     辨析：返回的是流 ID(Logged)，并非节点 ID
    #     """
    #     return self._extract_IDs_by_category(["sink"])
    #
    @cached_property
    def flowIDs(self) -> List[int]:
        """
        对应 matcher: sink
        辨析：返回的是流 ID(Logged)，并非节点 ID
        """
        return self._extract_IDs_by_category(["sink"])

    @cached_property
    def queueIDs(self) -> List[int]:
        """对应 matcher: queue"""
        return self._extract_IDs_by_category(["queue"])

    @cached_property
    def pipeIDs(self) -> List[int]:
        """对应 matcher: pipe"""
        return self._extract_IDs_by_category(["pipe"])

    @cached_property
    def switchIDs(self) -> List[int]:
        """对应 matcher: switch"""
        return self._extract_IDs_by_category(["switch"])

    @cached_property
    def short_flowIDs(self) -> List[int]:
        """对应 matcher: short_flow"""
        return self._extract_IDs_by_category(["short_flow"])

    # ----------------------------------------------------
    # 细粒度筛选逻辑 (Business Logic)
    # ----------------------------------------------------

    def get_flowIDs_from_src_id(self, src_id: int) -> List[int]:
        """
        找出源自 src_id 的所有流 ID。
        注意：根据原有逻辑，这里是从 'sink' 集合中筛选，
        这通常意味着我们查找的是在该源发出的、并在某处汇聚的完整流记录。
        """
        # 格式: *_sink_<src>_<dest> -> split('_') -> [-2] is src
        return [i for i in self.flowIDs if int(self.data[i].split("_")[-2]) == src_id]

    def get_flowIDs_to_dest_id(self, dest_id: int) -> List[int]:
        """找出汇聚到 dest_id 的所有流 ID"""
        # 格式: *_sink_<src>_<dest> -> split('_') -> [-1] is dest
        return [i for i in self.flowIDs if int(self.data[i].split("_")[-1]) == dest_id]

    def get_last_hop_queueIDs(self) -> List[int]:
        """
        筛选 Last Hop Queues (LS->DST)
        实质上就是 tor_down, 可以直接 filter_queueIDs
        """
        pattern = re.compile(r"LS\d+->DST\d+\(\d+\)")
        return [i for i in self.queueIDs if pattern.match(self.data[i])]

    def get_queueIDs_by_tor_id(self, tor_id: int) -> List[int]:
        """筛选特定 ToR 下的 Queues"""
        pattern = re.compile(rf"LS{tor_id}->DST\d+\(\d+\)")
        return [i for i in self.queueIDs if pattern.match(self.data[i])]

    def valid_last_hop_queueIDs(self) -> List[int]:
        """
        只获得有效的 last hop queueIDs
        因为根据 CM 的不同，不一定每个节点都参与通信，不一定每个队列都会有流量经过
        """
        sinks = self.all_sink_node_ids

        return [
            item
            for sink in sinks
            for item in self.get_adjID(sink, AdjType.IN_QUEUE, "DST")
        ]

    # ----------------------------------------------------
    # 功能 A: 基于枚举的类型筛选
    # ----------------------------------------------------
    def filter_queueIDs(self, link_type: LinkType) -> List[int]:
        """
        根据链路类型筛选 Queue ID。

        :param link_type: 枚举类型，例如 LinkType.TOR_DOWN
        """
        # 直接使用枚举的值作为正则
        pattern = re.compile(link_type.value)
        return [gid for gid in self.queueIDs if pattern.match(self.data[gid])]

    def filter_pipeIDs(self, link_type: LinkType) -> List[int]:
        """
        根据链路类型筛选 Pipe ID。

        :param link_type: 枚举类型，例如 LinkType.TOR_DOWN
        """
        # 自动添加前缀
        pattern = re.compile(r"Pipe-" + link_type.value)
        return [gid for gid in self.pipeIDs if pattern.match(self.data[gid])]

    # ----------------------------------------------------
    # 功能 B: 基于拓扑关系的邻接查询
    # ----------------------------------------------------
    @cached_property
    def _adjacency_index(self):
        """
        构建拓扑索引 (Lazy Loading)。
        索引结构: index[node_id][role][AdjType] = [id1, id2...]
        """

        # 定义最内层的数据结构：包含所有枚举类型的空列表
        def node_struct():
            return {
                AdjType.IN_QUEUE: [],
                AdjType.OUT_QUEUE: [],
                AdjType.IN_PIPE: [],
                AdjType.OUT_PIPE: [],
            }

        # 结构: logical_id -> role_str -> AdjType -> List[int]
        # 例如: index[44]['SRC'][AdjType.OUT_QUEUE] -> [102, 103]
        index = defaultdict(lambda: defaultdict(node_struct))

        # 节点名称解析正则: 匹配 "SRC44", "LS_10", "US2" 等
        # Group 1: Role (SRC, LS, US...), Group 2: ID
        node_pattern = re.compile(r"^([A-Za-z]+)_?(\d+)$")

        def parse_node(node_str):
            m = node_pattern.match(node_str)
            if m:
                return m.group(1), int(m.group(2))
            return None, None

        def process_items(id_list, is_pipe):
            """通用处理函数：根据 is_pipe 决定映射到哪个枚举 Key"""
            # 确定当前处理的是 Pipe 还是 Queue 对应的 Enum
            in_type = AdjType.IN_PIPE if is_pipe else AdjType.IN_QUEUE
            out_type = AdjType.OUT_PIPE if is_pipe else AdjType.OUT_QUEUE

            # Pipe 的名字通常以 "Pipe-" 开头，长度为 5
            prefix_len = 5 if is_pipe else 0

            for gid in id_list:
                name = self.data[gid]

                # 1. 清理名称
                # 去除 "Pipe-" 前缀 和 "(bundle_id)" 后缀
                # 原名示例: "Pipe-LS0->DST1(0)" -> 清理后: "LS0->DST1"
                clean_name = name[prefix_len:].split("(")[0]

                if "->" not in clean_name:
                    continue

                u_str, v_str = clean_name.split("->")

                # 2. 映射上游 (Source Node) -> OUT 类型
                u_role, u_id = parse_node(u_str)
                if u_role is not None:
                    index[u_id][u_role][out_type].append(gid)

                # 3. 映射下游 (Dest Node) -> IN 类型
                v_role, v_id = parse_node(v_str)
                if v_role is not None:
                    index[v_id][v_role][in_type].append(gid)

        # 执行构建
        process_items(self.queueIDs, is_pipe=False)
        process_items(self.pipeIDs, is_pipe=True)

        return index

    def get_adjID(
        self,
        node_id: int,
        adj_type: Optional[AdjType] = None,
        role: Optional[str] = None,
    ):
        """
        获取节点的邻接组件 ID 列表。

        :param node_id: 节点逻辑 ID (如 44)
        :param adj_type: (可选) 指定 AdjType.OUT_QUEUE 等。
                         如果为 None，返回包含所有类型的字典。
        :param role: (可选) 节点角色 'SRC', 'DST', 'LS', 'US', 'CS'。
                     如果不填，会合并该 ID 下所有角色的数据。
        :return: List[int] 或 Dict[AdjType, List[int]]
        """
        # 如果 ID 不存在，返回空结构
        if node_id not in self._adjacency_index:
            return [] if adj_type else {}

        node_roles_map = self._adjacency_index[node_id]

        # 1. 确定要查找的数据源 (特定角色 或 合并所有角色)
        if role:
            # 如果指定了角色，直接获取
            target_data = node_roles_map.get(role, {})
        else:
            # 如果没指定角色，合并该 ID 下所有角色的数据
            # 初始化一个空的合并容器
            target_data = {
                AdjType.IN_QUEUE: [],
                AdjType.OUT_QUEUE: [],
                AdjType.IN_PIPE: [],
                AdjType.OUT_PIPE: [],
            }
            # 遍历所有角色进行合并 (例如同时是 Switch 和 Server，虽然罕见)
            for r in node_roles_map:
                for k in target_data:
                    # 注意：这里需要确保 key 存在于源数据中
                    if k in node_roles_map[r]:
                        target_data[k].extend(node_roles_map[r][k])

        # 2. 如果请求了特定类型 (如只看 OUT_QUEUE)，直接返回 ID 列表
        if adj_type:
            return target_data.get(adj_type, [])

        # 3. 否则返回完整字典
        return target_data

    def get_flow_endpoints_adjID(self, src_id: int, dest_id: int):
        """
        [辅助方法] 快速获取流两端（源端注入、目的端LastHop）的组件信息。
        常用于 FCT 分析。
        """
        return {
            "src_uplink_queues": self.get_adjID(src_id, AdjType.OUT_QUEUE, role="SRC"),
            "src_uplink_pipes": self.get_adjID(src_id, AdjType.OUT_PIPE, role="SRC"),
            # 下行 Last Hop (Incast 瓶颈常发处)
            "dst_downlink_queues": self.get_adjID(
                dest_id, AdjType.IN_QUEUE, role="DST"
            ),
            "dst_downlink_pipes": self.get_adjID(dest_id, AdjType.IN_PIPE, role="DST"),
        }

    # ----------------------------------------------------
    # 聚合分析 (Aggregators)
    # ----------------------------------------------------

    @cached_property
    def _src_sink_pairs(self) -> Tuple[Set[int], Set[int]]:
        """辅助方法：解析所有流名中的 (src, sink) 节点 ID 集合"""
        srcs, sinks = set(), set()
        for i in self.flowIDs:
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
    def all_src_node_ids(self) -> List[int]:
        """所有作为 Source 出现过的节点 id"""
        return sorted(list(self._src_sink_pairs[0]))

    @property
    def all_sink_node_ids(self) -> List[int]:
        """所有作为 Sink 出现过的节点 id"""
        return sorted(list(self._src_sink_pairs[1]))

    @cached_property
    def sink_id_to_flowIDs_map(self) -> Dict[int, List[int]]:
        """
        返回 {dest_node_id: [flow_ID_1, flow_ID_2...]}
        用于快速查找某个节点接收了哪些流
        """
        mapping = defaultdict(list)
        for i in self.flowIDs:
            try:
                dest = int(self.data[i].split("_")[-1])
                mapping[dest].append(i)
            except (IndexError, ValueError):
                continue
        return dict(mapping)

    @cached_property
    def src_id_to_flowIDs_map(self) -> Dict[int, List[int]]:
        """
        返回 {src_node_id: [flow_ID_1, flow_ID_2...]}
        用于快速查找某个节点发出了哪些流
        """
        mapping = defaultdict(list)
        for i in self.flowIDs:  # 注意：原逻辑是基于 sink 列表分析 source
            try:
                src = int(self.data[i].split("_")[-2])
                mapping[src].append(i)
            except (IndexError, ValueError):
                continue
        return dict(mapping)
