import math
from random import seed, shuffle, randint
from pathlib import Path
from .. import runner
import re

PROJECT_DIR = runner.PROJECT_DIR


def convert_to_bytes(size_str: str) -> int:
    """
    将带有单位的流量大小字符串转换为字节数。
    支持：
        - 整数/浮点数：直接返回（取整）
        - 二进制单位：KiB, MiB, GiB, TiB (1024进制)
        - 十进制单位：KB, MB, GB, TB (1000进制)
        - 无单位时：视为字节
        - 大小写混合、前后空格
    示例：
        convert_to_bytes(100)       -> 100
        convert_to_bytes("1.5GB")   -> 1500000000
    """
    if isinstance(size_str, (int, float)):
        return int(size_str)
        
    s = str(size_str).strip()
    match = re.match(r"(?i)^\s*([\d.]+)\s*([KMGT]?I?B)?\s*$", s)
    if not match:
        raise ValueError(f"无法解析大小字符串: {size_str}")

    value, unit = match.groups()
    value = float(value)
    if not unit:
        return int(value)
        
    unit = unit.upper()
    binary = unit.endswith("IB")  # 判断是否为二进制单位
    base = 1024 if binary else 1000

    # 去掉 'I' 以统一单位表
    unit = unit.replace("I", "")

    units = {"B": 1, "KB": base, "MB": base**2, "GB": base**3, "TB": base**4}
    return int(value * units[unit])


def generate_serial_alltoall_traffic(
    nodes, conns, groupsize, flowsize, extrastarttime, randseed
):
    """
    生成串行全互联流量模式。
    此函数为模拟生成一个连接矩阵文件，其中包含指定节点、连接数、组大小和流大小的串行全互联流量模式。
    如果文件已存在，则跳过生成并直接返回文件路径。

    参数:
        nodes (int): 模拟中的节点总数。
        conns (int): 连接总数。
        groupsize (int): 每个通信组中的节点数量。
        flowsize (str): 流量大小，例如 "2MB"。
        extrastarttime (float): 额外启动时间，用于设置连接的起始时间。
        randseed (int): 随机种子，用于打乱节点顺序，如果为0则不使用随机种子。

    返回:
        str: 生成的连接矩阵文件的绝对路径。
    """
    file_name = f"alltoall_serial_{nodes}n_{conns}c_{groupsize}g_{flowsize}_{extrastarttime}es_{randseed}rs.cm"
    flowsize = convert_to_bytes(flowsize)
    target_dir = PROJECT_DIR / "data" / "connection_matrices"
    file_path = target_dir / file_name

    if file_path.exists():
        print(f"File {file_path} already exists. Skipping generation.")
        return str(file_path)

    output_content = []
    output_content.append(f"Nodes {nodes}")
    output_content.append(f"Connections {conns * (groupsize - 1)}")
    # output_content.append(f"Triggers {conns * (groupsize - 2)}")
    output_content.append(f"Triggers PLACEHOLDER")

    srcs = []
    groups = conns // groupsize

    for n in range(nodes):
        srcs.append(n)
    if randseed != 0:
        seed(randseed)
    shuffle(srcs)

    id = 0
    trig_id = 1
    for group in range(groups):
        groupsrcs = []
        for n in range(groupsize):
            groupsrcs.append(srcs[group * groupsize + n])

        for s in range(groupsize):
            for d in range(1, groupsize):
                id += 1
                dst = (s + d) % groupsize
                out = f"{groupsrcs[s]}->{groupsrcs[dst]} id {id}"
                if d == 1:
                    out = out + f" start {int(extrastarttime * 1000000)}"
                else:
                    out = out + f" trigger {trig_id}"
                    trig_id += 1
                out = out + f" size {flowsize}"
                if d != groupsize - 1:
                    out = out + f" send_done_trigger {trig_id}"
                output_content.append(out)
    for t in range(1, trig_id):
        out = f"trigger id {t} oneshot"
        output_content.append(out)

    output_content[2] = f"Triggers {trig_id - 1}"
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write("\n".join(output_content))
    print(f"Generated file: {file_path}")
    return str(file_path)


def generate_allreduce_traffic(nodes, conns, groupsize, flowsize, locality, randseed):
    """
    生成 Allreduce 流量模式。
    此函数为模拟生成一个连接矩阵文件，其中包含指定节点、连接数、组大小、流大小、局部性和随机种子的 Allreduce 流量模式。
    如果文件已存在，则跳过生成并直接返回文件路径。

    参数:
        nodes (int): 模拟中的节点总数。
        conns (int): 活跃连接总数。
        groupsize (int): 每个 Allreduce 组中的节点数量。
        flowsize (str): 流量大小，例如 "2MB"。
        locality (int): 局部性设置，如果为1，则对组内的源节点进行排序，使得相邻节点在拓扑中也相邻，这在 fat-tree 拓扑中可以减少跨机架流量，提高性能
        randseed (int): 随机种子，用于打乱节点顺序，如果为0则不使用随机种子。

    返回:
        str: 生成的连接矩阵文件的绝对路径。
    """
    file_name = f"allreduce_{nodes}n_{conns}c_{groupsize}g_{flowsize}_{locality}l_{randseed}rs.cm"
    flowsize = convert_to_bytes(flowsize)
    target_dir = PROJECT_DIR / "data" / "connection_matrices"
    file_path = target_dir / file_name

    if file_path.exists():
        print(f"File {file_path} already exists. Skipping generation.")
        return str(file_path)

    output_content = []
    output_content.append(f"Nodes {nodes}")
    output_content.append(f"Connections {conns * (2 * groupsize - 1)}")
    output_content.append(f"Triggers {conns * (2 * groupsize - 2)}")

    srcs = []
    groups = conns // groupsize

    for n in range(nodes):
        srcs.append(n)

    if randseed != 0:
        seed(randseed)

    shuffle(srcs)

    id = 0
    trig_id = 1
    for group in range(groups):
        groupsrcs = []
        for n in range(groupsize):
            groupsrcs.append(srcs[group * groupsize + n])

        if locality == 1:
            groupsrcs.sort()

        for s in range(groupsize):
            # Ring Allreduce 分为 2*groupsize-1 个步骤：
            # Reduce-Scatter（前 groupsize-1）：每个节点向下一个节点发送数据
            # All-gather（后 groupsize）：每个节点继续向下一个节点传播聚合结果
            for d in range(1, 2 * groupsize):
                id += 1
                # 使用环形拓扑
                src = (s + d - 1) % groupsize
                dst = (s + d) % groupsize
                out = f"{groupsrcs[src]}->{groupsrcs[dst]} id {id}"

                if d == 1:
                    out = out + " start 0"
                else:
                    out = out + f" trigger {trig_id}"
                    trig_id += 1

                out = out + f" size {flowsize}"
                if d != 2 * groupsize - 1:
                    out = out + f" send_done_trigger {trig_id}"
                output_content.append(out)

    for t in range(1, trig_id):
        out = f"trigger id {t} oneshot"
        output_content.append(out)

    # Ensure the directory exists
    target_dir.mkdir(parents=True, exist_ok=True)

    with open(file_path, "w") as f:
        f.write("\n".join(output_content))

    print(f"Generated file: {file_path}")
    return str(file_path)


def generate_allreduce_butterfly_traffic(
    nodes, groups, groupsize, flowsize, locality, randseed
):
    """
    生成 Allreduce Butterfly 流量模式。
    此函数为模拟生成一个连接矩阵文件，其中包含指定节点、组数、组大小、流大小、局部性和随机种子的 Allreduce Butterfly 流量模式。
    如果文件已存在，则跳过生成并直接返回文件路径。

    参数:
        nodes (int): 模拟中的节点总数。
        groups (int): Allreduce 组的数量。
        groupsize (int): 每个 Allreduce 组中的节点数量。
        flowsize (str): 流量大小，例如 "2MB"。
        locality (int): 局部性设置，如果为1，则对组内的源节点进行排序。
        randseed (int): 随机种子，用于打乱节点顺序，如果为0则不使用随机种子。

    返回:
        str: 生成的连接矩阵文件的绝对路径。
    """
    file_name = f"allreduce_butterfly_{nodes}n_{groups}g_{groupsize}gs_{flowsize}_{locality}l_{randseed}rs.cm"
    flowsize = convert_to_bytes(flowsize)
    target_dir = PROJECT_DIR / "data" / "connection_matrices"
    file_path = target_dir / file_name

    if file_path.exists():
        print(f"File {file_path} already exists. Skipping generation.")
        return str(file_path)

    output_content = []
    conns = groups * groupsize * int(math.log(groupsize, 2))

    output_content.append(f"Nodes {nodes}")
    output_content.append(f"Connections {conns}")
    output_content.append(f"Triggers {conns - groupsize * groups}")

    srcs = []
    trigger_ids = []

    for n in range(nodes):
        srcs.append(n)

    if randseed != 0:
        seed(randseed)

    shuffle(srcs)

    id = 0
    trig_id = 0
    for group in range(groups):
        groupsrcs = []
        for n in range(groupsize):
            groupsrcs.append(srcs[group * groupsize + n])

        if locality == 1:
            groupsrcs.sort()

        for d in range(0, int(math.log(groupsize, 2))):
            step = pow(2, d)
            trigger_ids.append([])
            rng = pow(2, d + 1)
            direction = 1
            left_direction = step

            for n in range(nodes):
                trigger_ids[d].append(-1)

            last_step = d == int(math.log(groupsize, 2) - 1)

            for src in range(0, groupsize):
                if int(src / step) % 2 == 0:
                    dst = src + step

                    id += 1

                    if not last_step:
                        trig_id += 1
                        trigger_ids[d][dst] = trig_id

                    out = f"{groupsrcs[src]}->{groupsrcs[dst]} id {id}"

                    if d == 0:
                        rest = " start 0"
                    else:
                        rest = f" trigger {trigger_ids[d - 1][src]}"

                    rest = rest + f" size {flowsize}"

                    if not last_step:
                        rest = rest + f" recv_done_trigger {trig_id}"

                    out = out + rest
                    output_content.append(out)

                    id += 1

                    if not last_step:
                        trig_id += 1
                        trigger_ids[d][src] = trig_id

                    if d == 0:
                        rest = " start 0"
                    else:
                        rest = f" trigger {trigger_ids[d - 1][dst]}"

                    rest = rest + f" size {flowsize}"

                    if not last_step:
                        rest = rest + f" recv_done_trigger {trig_id}"

                    out = f"{groupsrcs[dst]}->{groupsrcs[src]} id {id}"
                    out = out + rest

                    output_content.append(out)
                else:
                    continue

    for t in range(1, trig_id + 1):
        out = f"trigger id {t} oneshot"
        output_content.append(out)

    target_dir.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write("\n".join(output_content))
    print(f"Generated file: {file_path}")
    return str(file_path)


def generate_incast_traffic(
    nodes, conns, flowsize, extrastarttime, randseed, prefer_remote
):
    """
    生成 Incast 流量模式。
    此函数为模拟生成一个连接矩阵文件，其中包含指定节点、连接数、流大小、额外启动时间和随机种子的 Incast 流量模式。
    Incast 模式通常指多个源节点向一个目的节点发送流量。
    如果文件已存在，则跳过生成并直接返回文件路径。

    参数:
        nodes (int): 模拟中的节点总数。
        conns (int): 活跃连接数（发送方数量）
        flowsize (str): 流量大小，例如 "2MB"。
        extrastarttime (float): 启动时间分散范围（微秒），用于避免所有流同时开始，模拟更真实的场景
        randseed (int): 随机种子（0表示随机）
        prefer_remote：是否优先选择远程节点，该参数的设计思想是模拟跨机架流量，这在 fat-tree 拓扑中会产生更高的网络负载

    返回:
        str: 生成的连接矩阵文件的绝对路径。
    """
    file_name = f"incast_{nodes}n_{conns}c_{flowsize}_{extrastarttime}es_{randseed}rs_{prefer_remote}pr.cm"
    flowsize = convert_to_bytes(flowsize)
    target_dir = PROJECT_DIR / "data" / "connection_matrices"
    file_path = target_dir / file_name

    if file_path.exists():
        print(f"File {file_path} already exists. Skipping generation.")
        return str(file_path)

    output_content = []
    output_content.append(f"Nodes {nodes}")
    output_content.append(f"Connections {conns}")
    # output_content.append(f"Triggers 0")

    srcs = []
    # 根据 prefer_remote 是否优先选择源节点
    # 若为零，则从 1~nodes-1 中随机选择，然后打乱顺序
    if prefer_remote == 0:
        for n in range(1, nodes):
            srcs.append(n)
        if randseed != 0:
            seed(randseed)
        shuffle(srcs)
    # 否则，只从拓扑后半部分选择源节点
    else:
        remote_cnt = nodes - int(nodes / 2)
        if conns > remote_cnt:
            for n in range(1, int(nodes / 2)):
                srcs.append(n)
            if randseed != 0:
                seed(randseed)
            remote_half = list(range(int(nodes / 2), nodes))
            shuffle(remote_half)
            shuffle(srcs)
            srcs = remote_half + srcs
        else:
            for n in range(int(nodes / 2), nodes):
                srcs.append(n)
            if randseed != 0:
                seed(randseed)
            shuffle(srcs)
    # 目标节点固定，为 0
    dst = "0"
    for n in range(conns):
        # 启动时间在 0~extrastarttime 微秒之间随机分布
        extra = randint(0, int(extrastarttime * 1000000))
        out = (
            str(srcs[n])
            + "->"
            + str(dst)
            + " id "
            + str(n + 1)
            + " start "
            + str(extra)
            + " size "
            + str(flowsize)
        )
        output_content.append(out)

    target_dir.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write("\n".join(output_content))
    print(f"Generated file: {file_path}")
    return str(file_path)


def generate_outcast_incast_traffic(
    nodes, conns_incast, conns_outcast, flowsize, randseed
):
    """
    生成 Outcast-Incast 混合流量模式。
    这种模式用于测试拥塞控制算法在复杂流量竞争场景下的公平性和性能表现
    此函数为模拟生成一个连接矩阵文件，其中包含指定节点、Incast 连接数、Outcast 连接数、流大小和随机种子的混合流量模式。
    如果文件已存在，则跳过生成并直接返回文件路径。

    参数:
        nodes (int): 模拟中的节点总数。
        conns_incast (int): Incast 目标的连接数（发送方数量）
        conns_outcast (int): Outcast 源的连接数（目标数量）
        flowsize (str): 流量大小，例如 "2MB"。
        randseed (int): 随机种子，如果为0则不使用随机种子。

    返回:
        str: 生成的连接矩阵文件的绝对路径。
    """
    file_name = (
        f"outcast_incast_{nodes}n_{conns_incast}ci_{conns_outcast}co_{flowsize}.cm"
    )
    flowsize = convert_to_bytes(flowsize)
    target_dir = PROJECT_DIR / "data" / "connection_matrices"
    file_path = target_dir / file_name

    if file_path.exists():
        print(f"File {file_path} already exists. Skipping generation.")
        return str(file_path)

    output_content = []
    output_content.append(f"Nodes {nodes}")
    output_content.append(
        f"Connections {conns_incast + (conns_incast - 1) * (conns_outcast - 1)}"
    )

    # 判断基于给定参数生成的流量模式是否超出节点总数，如果超出则报错
    if ((conns_incast - 1) * conns_outcast + 1 + conns_incast) >= nodes:
        # This should be handled as an error or by adjusting parameters
        raise ValueError("Error: Too many connections for target topology")

    crttarget = conns_incast + 1
    id = 1

    for n in range(conns_incast):
        out = f"{n + 1}->{0} id {id} start {0} size {flowsize}"
        output_content.append(out)
        id = id + 1

        if n != 0:
            for m in range(conns_outcast - 1):
                out = f"{n + 1}->{crttarget} id {id} start {0} size {flowsize}"
                crttarget = crttarget + 1
                id = id + 1
                output_content.append(out)

    target_dir.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write("\n".join(output_content))
    print(f"Generated file: {file_path}")
    return str(file_path)


def generate_permutation_traffic(nodes, conns, flowsize, extrastarttime, randseed):
    """
    生成置换流量模式。
    此函数为模拟生成一个连接矩阵文件，其中包含指定节点、连接数、流大小、额外启动时间和随机种子的置换流量模式。
    置换模式确保每个节点发送到一个唯一的目的节点，并且每个节点接收来自一个唯一的源节点的流量。
    如果文件已存在，则跳过生成并直接返回文件路径。

    参数:
        nodes (int): 模拟中的节点总数。
        conns (int): 连接总数。
        flowsize (str): 流量大小，例如 "2MB"。
        extrastarttime (float): 额外启动时间，用于设置连接的起始时间。
        randseed (int): 随机种子，用于打乱源节点和目的节点顺序，如果为0则不使用随机种子。

    返回:
        str: 生成的连接矩阵文件的绝对路径。
    """
    file_name = f"perm_{nodes}n_{conns}c_{flowsize}.cm"
    flowsize = convert_to_bytes(flowsize)
    target_dir = PROJECT_DIR / "data" / "connection_matrices"
    file_path = target_dir / file_name

    if file_path.exists():
        print(f"File {file_path} already exists. Skipping generation.")
        return str(file_path)

    output_content = []
    output_content.append(f"Nodes {nodes}")
    output_content.append(f"Connections {conns}")

    srcs = []
    dsts = []
    for n in range(nodes):
        srcs.append(n)
        dsts.append(n)
    if randseed != 0:
        seed(randseed)

    shuffle(srcs)
    shuffle(dsts)

    # eliminate any duplicates - a node should not send to itself
    for n in range(nodes):
        if srcs[n] == dsts[n]:
            i = (n + 1) % nodes
            tmp = dsts[n]
            dsts[n] = dsts[i]
            dsts[i] = tmp

    for n in range(conns):
        out = f"{srcs[n]}->{dsts[n]} id {n + 1} start {int(extrastarttime * 1000000)} size {flowsize}"
        output_content.append(out)

    target_dir.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write("\n".join(output_content))
    print(f"Generated file: {file_path}")
    return str(file_path)


def generate_permutation_full_bisection_traffic(
    nodes, conns, flowsize, extrastarttime, randseed
):
    """
    生成全二分置换流量模式。
    此函数为模拟生成一个连接矩阵文件，其中包含指定节点、连接数、流大小、额外启动时间和随机种子的全二分置换流量模式。
    全二分置换模式通常用于测试网络在最坏情况下的性能，其中流量在网络的两个对半分区之间进行。
    如果文件已存在，则跳过生成并直接返回文件路径。

    参数:
        nodes (int): 模拟中的节点总数。
        conns (int): 连接总数。
        flowsize (str): 流量大小，例如 "2MB"。
        extrastarttime (float): 额外启动时间，用于设置连接的起始时间。
        randseed (int): 随机种子，用于生成随机源节点和目的节点，如果为0则不使用随机种子。

    返回:
        str: 生成的连接矩阵文件的绝对路径。
    """
    file_name = f"perm_full_bisection_{nodes}n_{conns}c_{flowsize}_{extrastarttime}es_{randseed}rs.cm"
    flowsize = convert_to_bytes(flowsize)
    target_dir = PROJECT_DIR / "data" / "connection_matrices"
    file_path = target_dir / file_name

    if file_path.exists():
        print(f"File {file_path} already exists. Skipping generation.")
        return str(file_path)

    output_content = []
    output_content.append(f"Nodes {nodes}")
    output_content.append(f"Connections {conns}")

    srcs = []
    dsts = []
    stride = nodes // 2

    if randseed != 0:
        seed(randseed)

    for _ in range(nodes):
        source = randint(0, nodes - 1)
        while source in srcs:
            source = randint(0, nodes - 1)

        destination = (source + stride) % nodes
        srcs.append(source)
        dsts.append(destination)

    for n in range(conns):
        out = f"{srcs[n]}->{dsts[n]} id {n + 1} start {int(extrastarttime * 1000000)} size {flowsize}"
        output_content.append(out)

    target_dir.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write("\n".join(output_content))
    print(f"Generated file: {file_path}")
    return str(file_path)


def generate_serialn_alltoall_traffic(
    nodes, conns, groupsize, parallel, flowsize, extrastarttime, randseed
):
    """
    生成串行N对N全互联流量模式。
    此函数为模拟生成一个连接矩阵文件，其中包含指定节点、连接数、组大小、并行度、流大小、额外启动时间和随机种子的串行N对N全互联流量模式。
    如果文件已存在，则跳过生成并直接返回文件路径。

    参数:
        nodes (int): 模拟中的节点总数。
        conns (int): 连接总数。
        groupsize (int): 每个通信组中的节点数量。
        parallel (int): 并行度，表示同时进行的连接数量。
        flowsize (str): 流量大小，例如 "2MB"。
        extrastarttime (float): 额外启动时间，用于设置连接的起始时间。
        randseed (int): 随机种子，用于打乱节点顺序，如果为0则不使用随机种子。

    返回:
        str: 生成的连接矩阵文件的绝对路径。
    """
    file_name = f"serialn_alltoall_{nodes}n_{conns}c_{groupsize}g_{parallel}p_{flowsize}_{extrastarttime}es_{randseed}rs.cm"
    flowsize = convert_to_bytes(flowsize)
    target_dir = PROJECT_DIR / "data" / "connection_matrices"
    file_path = target_dir / file_name

    if file_path.exists():
        print(f"File {file_path} already exists. Skipping generation.")
        return str(file_path)

    output_content = []
    output_content.append(f"Nodes {nodes}")
    output_content.append(f"Connections {conns * (groupsize - 1)}")

    half = (groupsize - 1) // parallel
    # output_content.append(f"Triggers {(conns // groupsize) * groupsize * half}")
    output_content.append("Triggers PLACEHOLDER")

    srcs = []
    groups = conns // groupsize

    for n in range(nodes):
        srcs.append(n)
    if randseed != 0:
        seed(randseed)

    shuffle(srcs)

    id = 0
    trig_id = 0

    for group in range(groups):
        groupsrcs = []

        for n in range(groupsize):
            groupsrcs.append(srcs[group * groupsize + n])

        half = (groupsize - 1) // parallel
        left = (groupsize - 1) % parallel
        for s in range(groupsize):
            for d in range(1, half + 1):
                st_trigger = trig_id

                if d != half or left > 0:
                    trig_id += 1

                for crt in range(parallel):
                    id += 1
                    dst = (s + d + crt * half) % groupsize
                    out = f"{groupsrcs[s]}->{groupsrcs[dst]} id {id}"

                    if d == 1:
                        out = out + f" start {int(extrastarttime * 1000000)}"
                    else:
                        out = out + f" trigger {st_trigger}"

                    out = out + f" size {flowsize}"

                    if d != half or left > 0:
                        out = out + f" send_done_trigger {trig_id}"

                    output_content.append(out)

            if left > 0:
                st_trigger = trig_id

                for crt in range(left):
                    id += 1
                    dst = (s + parallel * half + crt + 1) % groupsize
                    out = f"{groupsrcs[s]}->{groupsrcs[dst]} id {id}"

                    out = out + f" trigger {st_trigger}"
                    out = out + f" size {flowsize}"
                    output_content.append(out)

    for t in range(1, trig_id + 1):
        out = f"trigger id {t} multishot"
        output_content.append(out)

    output_content[2] = f"Triggers {trig_id}"

    target_dir.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write("\n".join(output_content))
    print(f"Generated file: {file_path}")
    return str(file_path)


def generate_serialn_alltoall_prio_traffic(
    nodes, conns, groupsize, parallel, flowsize, extrastarttime, randseed
):
    """
    生成带优先级的串行N对N全互联流量模式。
    此函数为模拟生成一个连接矩阵文件，其中包含指定节点、连接数、组大小、并行度、流大小、额外启动时间和随机种子的带优先级的串行N对N全互联流量模式。
    如果文件已存在，则跳过生成并直接返回文件路径。

    参数:
        nodes (int): 模拟中的节点总数。
        conns (int): 连接总数。
        groupsize (int): 每个通信组中的节点数量。
        parallel (int): 并行度，表示同时进行的连接数量。
        flowsize (str): 流量大小，例如 "2MB"。
        extrastarttime (float): 额外启动时间，用于设置连接的起始时间。
        randseed (int): 随机种子，用于打乱节点顺序，如果为0则不使用随机种子。

    返回:
        str: 生成的连接矩阵文件的绝对路径。
    """
    file_name = f"serialn_alltoall_prio_{nodes}n_{conns}c_{groupsize}g_{parallel}p_{flowsize}_{extrastarttime}es_{randseed}rs.cm"
    flowsize = convert_to_bytes(flowsize)
    target_dir = PROJECT_DIR / "data" / "connection_matrices"
    file_path = target_dir / file_name

    if file_path.exists():
        print(f"File {file_path} already exists. Skipping generation.")
        return str(file_path)

    if conns % groupsize != 0:
        raise ValueError("conns must be a multiple of groupsize\n")

    output_content = []
    output_content.append(f"Nodes {nodes}")
    output_content.append(f"Connections {conns * (groupsize - 1)}")

    # if (conns - 1) % parallel == 0:
    #     output_content.append(f"Triggers {groupsize * ((conns - 1) // parallel - 1)}")
    # else:
    #     output_content.append(f"Triggers {groupsize * ((conns - 1) // parallel)}")

    output_content.append("Triggers PLACEHOLDER")
    srcs = []
    groups = conns // groupsize

    for n in range(nodes):
        srcs.append(n)
    if randseed != 0:
        seed(randseed)

    shuffle(srcs)

    id = 0
    trig_id = 0

    for group in range(groups):
        groupsrcs = []

        for n in range(groupsize):
            groupsrcs.append(srcs[group * groupsize + n])

        half = (groupsize - 1) // parallel
        left = (groupsize - 1) % parallel
        for s in range(groupsize):
            prio = 0
            for d in range(1, half + 1):
                prio += 1
                st_trigger = trig_id

                if d != half or left > 0:
                    trig_id += 1

                for crt in range(parallel):
                    id += 1
                    dst = (s + d + crt * half) % groupsize
                    out = f"{groupsrcs[s]}->{groupsrcs[dst]} id {id}"

                    if d == 1:
                        out = out + f" start {int(extrastarttime * 1000000)}"
                    else:
                        out = out + f" trigger {st_trigger}"

                    out = out + f" size {flowsize}"

                    if d != half or left > 0:
                        out = out + f" send_done_trigger {trig_id}"
                    out = out + f" prio {prio}"

                    output_content.append(out)

            prio += 1
            if left > 0:
                st_trigger = trig_id

                for crt in range(left):
                    id += 1
                    dst = (s + parallel * half + crt + 1) % groupsize
                    out = f"{groupsrcs[s]}->{groupsrcs[dst]} id {id}"

                    out = out + f" trigger {st_trigger}"
                    out = out + f" size {flowsize}"
                    out = out + f" prio {prio}"
                    output_content.append(out)

    for t in range(1, trig_id + 1):
        out = f"trigger id {t} multishot"
        output_content.append(out)

    output_content[2] = f"Triggers {trig_id}"
    target_dir.mkdir(parents=True, exist_ok=True)
    with open(file_path, "w") as f:
        f.write("\n".join(output_content))
    print(f"Generated file: {file_path}")
    return str(file_path)
