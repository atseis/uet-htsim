from collections import defaultdict, deque
import re
from pathlib import Path
from typing import Dict, List, Union

import yaml

from ..parser import flow
from ..runner import load_idmap
import pandas as pd


def find_butterfly_groups(all_flows):
    graph = defaultdict(set)
    for f in all_flows:
        graph[f["src"]].add(f["dst"])
        graph[f["dst"]].add(f["src"])
    visited = set()
    groups = []
    for node in graph.keys():
        if node in visited:
            continue
        queue = deque([node])
        comp = []
        visited.add(node)
        while queue:
            u = queue.popleft()
            comp.append(u)
            for v in graph[u]:
                if v not in visited:
                    visited.add(v)
                    queue.append(v)
        groups.append(sorted(comp))
    return groups


def get_flow_id_from_src_dst(
    idmap: Dict[int, str], src: int, dst: int
) -> Union[int, None]:
    """
    根据 src 和 dst 从 idmap 中查找对应的 FlowID。
    """
    search_suffix = f"_{src}_{dst}"
    for flow_id, flow_str in idmap.items():
        if flow_str.endswith(search_suffix):
            return flow_id
    return None


def parse_collectives_from_cm(
    filename: Union[str, Path], idmap: Dict[int, str]
) -> List[List[Dict]]:
    """
    自动解析 CM 文件，识别流量模式，解析 groupsize，并按 collective 划分 flow。

    支持模式：
        - alltoall
        - serial_alltoall
        - serialn_alltoall (+ prio)
        - allreduce
        - allreduce_butterfly (每个小组视为一个 collective)
        - 其他模式 (perm, incast, outcast...) → 单 collective

    返回:
        List[List[Dict]]: 每个 collective 是一个 list，里面每个 flow 包含:
            {
                "src": int,
                "dst": int,
                "id": int,
                "size": int,
                "triggers": List[int],
                "prio": int or None,
                "flow_id": Union[int, None],
            }
    """

    # ======================
    # 1. 文件准备
    # ======================
    filename = Path(filename)
    if not filename.exists():
        raise FileNotFoundError(f"CM file not found: {filename}")
    fname = filename.name.lower()

    # ======================
    # 2. 识别模式
    # ======================
    mode = None
    if "serialn_alltoall_prio" in fname:
        mode = "serialn_alltoall_prio"
    elif "serialn_alltoall" in fname:
        mode = "serialn_alltoall"
    elif "alltoall_serial" in fname:
        mode = "alltoall_serial"
    elif "allreduce_butterfly" in fname:
        mode = "allreduce_butterfly"
    elif "allreduce" in fname:
        mode = "allreduce"
    else:
        mode = "single_collective"

    # ======================
    # 3. 解析 groupsize（仅 alltoall / allreduce 系列需要）
    # ======================
    groupsize = None
    g = re.search(r"_(\d+)g[s]?_?", fname)
    if g:
        groupsize = int(g.group(1))

    # ======================
    # 4. 计算 flows_per_collective
    # ======================
    flows_per_collective = None
    if mode in ("alltoall_serial", "serialn_alltoall", "serialn_alltoall_prio"):
        if groupsize is None:
            raise ValueError("groupsize could not be inferred from filename.")
        flows_per_collective = groupsize * (groupsize - 1)
    elif mode == "allreduce":
        if groupsize is None:
            raise ValueError("groupsize could not be inferred from filename.")
        flows_per_collective = groupsize * (2 * groupsize - 1)
    elif mode == "allreduce_butterfly":
        if groupsize is None:
            raise ValueError("groupsize could not be inferred from filename.")
        # Butterfly 的 flows_per_collective 不固定，每个 group 是一个 collective
        flows_per_collective = None
        # 尝试解析节点总数
        nodes_match = re.search(r"_(\d+)n_", fname)
        if nodes_match:
            nodes = int(nodes_match.group(1))
            groups = nodes // groupsize
        else:
            raise ValueError("Cannot infer number of nodes for Butterfly.")

    # ======================
    # 5. 解析 CM 文件，收集 flow
    # ======================
    flow_pattern = re.compile(r"(\d+)->(\d+).*id (\d+)")
    all_flows = []

    with open(filename, "r") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith(("Nodes", "Connections", "Triggers")):
                continue

            m = flow_pattern.search(line)
            if not m:
                continue

            src, dst, fid = map(int, m.groups())
            flow_id = get_flow_id_from_src_dst(idmap, src, dst)
            size_match = re.search(r"size (\d+)", line)
            size = int(size_match.group(1)) if size_match else None
            prio_match = re.search(r"prio (\d+)", line)
            prio = int(prio_match.group(1)) if prio_match else None
            triggers = [
                int(t)
                for t in re.findall(
                    r"(?:trigger|send_done_trigger|recv_done_trigger) (\d+)", line
                )
            ]

            flow_info = {
                "src": src,
                "dst": dst,
                "id": fid,
                "size": size,
                "triggers": triggers,
                "prio": prio,
                "flow_id": flow_id,
            }

            all_flows.append(flow_info)

    # ======================
    # 6. 切分 collectives
    # ======================
    collectives = []

    if mode in (
        "alltoall_serial",
        "serialn_alltoall",
        "serialn_alltoall_prio",
        "allreduce",
    ):
        current_collective = []
        flow_count = 0
        for flow_info in all_flows:
            current_collective.append(flow_info)
            flow_count += 1
            if flow_count >= flows_per_collective:
                collectives.append(current_collective)
                current_collective = []
                flow_count = 0
        if current_collective:
            collectives.append(current_collective)

    elif mode == "allreduce_butterfly":
        butterfly_groups = find_butterfly_groups(all_flows)
        collectives = []
        for comp in butterfly_groups:
            s = set(comp)
            flows = [f for f in all_flows if f["src"] in s]
            collectives.append(flows)

    else:
        # 单 collective 情况
        collectives = [all_flows]

    return collectives


def calculate_collective_ccts(
    collectives: List[List[Dict]],
    flow_completion_times: Dict[int, float],
    flow_start_times: Dict[int, float],
) -> List[float]:
    """
    计算每个 collective 的 CCT (Collective Completion Time)。
    CCT = collective 中最晚结束时间 - collective 中最早开始时间。
    """
    ccts = []
    for collective in collectives:
        min_start_time = float("inf")
        max_completion_time = float("-inf")

        for flow in collective:
            flow_id = flow.get("flow_id")
            if flow_id is None:
                # 如果 flow_id 不存在，则跳过此流或根据需要处理错误
                continue

            completion_time = flow_completion_times.get(flow_id)
            start_time = flow_start_times.get(flow_id)

            if completion_time is None or start_time is None:
                # 如果找不到完成时间或开始时间，则跳过此流或根据需要处理错误
                continue

            min_start_time = min(min_start_time, start_time)
            max_completion_time = max(max_completion_time, completion_time)

        if min_start_time != float("inf") and max_completion_time != float("-inf"):
            ccts.append(max_completion_time - min_start_time)
    return ccts


def get_collective_ccts_from_directory(directory_path: Union[str, Path]) -> List[float]:
    """
    从指定的实验结果目录中读取 output.log, idmap.txt, status.yaml 文件，
    并从 status.yaml 中解析出 CM 文件路径，然后调用 get_collective_ccts_from_files
    函数来获取 collective 的 CCT 列表。

    Args:
        directory_path: 实验结果目录的路径。

    Returns:
        一个浮点数列表，表示 collective 的 CCTs。
    """
    directory_path = Path(directory_path)

    log_file = directory_path / "output.log"
    idmap_file = directory_path / "idmap.txt"
    status_file = directory_path / "status.yaml"

    if not log_file.exists():
        print(f"错误: 日志文件 {log_file} 不存在。")
        return []
    if not idmap_file.exists():
        print(f"错误: ID Map 文件 {idmap_file} 不存在。")
        return []
    if not status_file.exists():
        print(f"错误: Status 文件 {status_file} 不存在。")
        return []

    # 从 status.yaml 中解析 CM 文件路径
    cm_file = None
    try:
        with open(status_file, "r") as f:
            status_data = yaml.safe_load(f)
            command_str = status_data.get("command", "")
            # 使用正则表达式从 command 字符串中提取 -tm 后面的路径
            match = re.search(r"-tm\s+(\S+)", command_str)
            if match:
                cm_file = Path(match.group(1))
            else:
                print(f"错误: 未能在 {status_file} 的 command 字段中找到 CM 文件路径。")
                return []
    except Exception as e:
        print(f"错误: 读取或解析 {status_file} 失败: {e}")
        return []

    if not cm_file or not cm_file.exists():
        print(f"错误: CM 文件 {cm_file} 不存在或未找到。")
        return []

    # print(f"成功解析文件路径：")
    # print(f"  日志文件: {log_file}")
    # print(f"  ID Map 文件: {idmap_file}")
    # print(f"  CM 文件: {cm_file}")

    return get_collective_ccts_from_files(log_file, cm_file, idmap_file)


def get_collective_ccts_from_files(
    log_file: Union[str, Path], cm_file: Union[str, Path], idmap_file: Union[str, Path]
) -> List[float]:
    # ... existing code ...
    """
    从日志文件、CM 文件和 idmap 文件中获取 collective 的 CCT 列表。

    这是主要的分析函数，整合了完整的分析流程：
    1. 解析日志文件获取流事件
    2. 提取流的完成时间和开始时间
    3. 加载 idmap 文件
    4. 解析 CM 文件获取 collective 结构
    5. 计算每个 collective 的 CCT

    参数:
        log_file: 日志文件路径
        cm_file: CM 文件路径
        idmap_file: idmap 文件路径

    返回:
        List[float]: collective 完成时间列表
    """
    print("正在解析日志文件...")

    try:
        # 1. 使用 flow.py 中的 parse_flow_events_from_file 函数解析日志文件
        flow_events_df = flow.parse_flow_events_from_file(str(log_file))
        #
        # print(f"成功解析日志文件，共找到 {len(flow_events_df)} 个流事件")
        # print(f"流事件数据框列: {flow_events_df.columns.tolist()}")

        if len(flow_events_df) > 0:
            # print("前5个流事件:")
            # print(flow_events_df.head())

            # 2. 从 flow_events_df 中提取流完成时间和开始时间
            flow_completion_times = {}
            flow_start_times = {}

            for _, row in flow_events_df.iterrows():
                flow_id = int(row["flow_id"])
                finish_time = row["finish_time"]
                start_time = row["start_time"]

                if pd.notna(finish_time):
                    flow_completion_times[flow_id] = (
                        float(finish_time) / 1e9
                    )  # 转换为秒
                if pd.notna(start_time):
                    flow_start_times[flow_id] = float(start_time) / 1e9  # 转换为秒

            # print(f"提取了 {len(flow_completion_times)} 个流的完成时间")
            # print(f"提取了 {len(flow_start_times)} 个流的开始时间")

            # 3. 加载 idmap 文件
            idmap = load_idmap(str(idmap_file))
            # print(f"成功加载 idmap，包含 {len(idmap)} 个映射")

            # 4. 解析 CM 文件
            collectives = parse_collectives_from_cm(cm_file, idmap)
            # print(f"成功解析 CM 文件，找到 {len(collectives)} 个 collective")

            if collectives:
                # print(f"第一个 collective 包含 {len(collectives[0])} 个流")

                # 5. 计算 CCT 列表
                ccts = calculate_collective_ccts(
                    collectives, flow_completion_times, flow_start_times
                )

                print(f"Collective CCTs: {ccts}")

                if ccts:
                    # print(f"成功计算了 {len(ccts)} 个 collective 的完成时间")
                    # for i, cct in enumerate(ccts):
                    #     print(f"Collective {i}: {cct:.6f} 秒")

                    # avg_cct = sum(ccts) / len(ccts)
                    # max_cct = max(ccts)
                    # min_cct = min(ccts)
                    # print("\n统计信息:")
                    # print(f"平均 CCT: {avg_cct:.6f} 秒")
                    # print(f"最大 CCT: {max_cct:.6f} 秒")
                    # print(f"最小 CCT: {min_cct:.6f} 秒")

                    return ccts
                else:
                    print("未计算出任何 collective 完成时间")
                    return []
            else:
                print("未找到任何 collective")
                return []
        else:
            print("未找到任何流事件，请检查日志文件格式")
            return []

    except Exception as e:
        print(f"测试过程中出现错误: {e}")
        import traceback

        traceback.print_exc()
        return []


def get_collective_details_from_directory(
    directory_path: Union[str, Path],
) -> List[Dict]:
    """
    从指定的实验结果目录中读取 output.log, idmap.txt, status.yaml 文件，
    并从 status.yaml 中解析出 CM 文件路径，然后解析 collective 的详细信息。

    Args:
        directory_path: 实验结果目录的路径。

    Returns:
        一个列表，其中每个元素是一个字典，包含一个 collective 的所有节点和流。
        例如：
        [
            {
                "collective_id": 0,
                "nodes": [0, 1, 2, 3],
                "flows": [
                    {"src": 0, "dst": 1, "id": 100, "flow_id": 1000},
                    {"src": 1, "dst": 0, "id": 101, "flow_id": 1001},
                    # ... 更多流
                ]
            },
            # ... 更多 collective
        ]
    """
    directory_path = Path(directory_path)

    log_file = directory_path / "output.log"
    idmap_file = directory_path / "idmap.txt"
    status_file = directory_path / "status.yaml"

    if not log_file.exists():
        print(f"错误: 日志文件 {log_file} 不存在。")
        return []
    if not idmap_file.exists():
        print(f"错误: ID Map 文件 {idmap_file} 不存在。")
        return []
    if not status_file.exists():
        print(f"错误: Status 文件 {status_file} 不存在。")
        return []

    # 从 status.yaml 中解析 CM 文件路径
    cm_file = None
    try:
        with open(status_file, "r") as f:
            status_data = yaml.safe_load(f)
            command_str = status_data.get("command", "")
            # 使用正则表达式从 command 字符串中提取 -tm 后面的路径
            match = re.search(r"-tm\s+(\S+)", command_str)
            if match:
                cm_file = Path(match.group(1))
            else:
                print(f"错误: 未能在 {status_file} 的 command 字段中找到 CM 文件路径。")
                return []
    except Exception as e:
        print(f"错误: 读取或解析 {status_file} 失败: {e}")
        return []

    if not cm_file or not cm_file.exists():
        print(f"错误: CM 文件 {cm_file} 不存在或未找到。")
        return []

    # 加载 idmap 文件
    idmap = load_idmap(str(idmap_file))

    # 解析 CM 文件
    collectives = parse_collectives_from_cm(cm_file, idmap)

    collective_details = []
    for i, collective in enumerate(collectives):
        nodes = set()
        flows_info = []
        for flow_data in collective:
            nodes.add(flow_data["src"])
            nodes.add(flow_data["dst"])
            flows_info.append(
                {
                    "src": flow_data["src"],
                    "dst": flow_data["dst"],
                    "id": flow_data["id"],
                    "flow_id": flow_data["flow_id"],
                }
            )
        collective_details.append(
            {
                "collective_id": i,
                "nodes": sorted(list(nodes)),
                "flows": flows_info,
            }
        )
    return collective_details
