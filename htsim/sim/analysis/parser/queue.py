# src/parser/queue.py
import re
import pandas as pd
from typing import List, Dict, Optional, Union
from pathlib import Path
from .. import runner

# ==========================================
# 1. QueueLoggerSampling (主力/示波器)
# ==========================================


def parse_sampling_events(text: str) -> pd.DataFrame:
    """
    解析 QueueLoggerSampling 产生的 RANGE 事件 (水位信息)。
    更新: 兼容浮点数格式
    """
    data = []

    # 原始格式: ... Ev RANGE LastQ 1500 MinQ 1500 MaxQ 1500 Name ...
    # 新格式: ... Ev RANGE LastQ 1500.000000 MinQ 1500.000000 ...
    pattern = re.compile(
        r"(\d+\.\d+)\s+"  # Time
        r"Type\s+QUEUE_APPROX\s+"  # Type
        r"ID\s+(\d+)\s+"  # ID
        r"Ev\s+RANGE\s+"  # Event
        r"LastQ\s+([\d\.]+)\s+"  # LastQ (兼容浮点)
        r"MinQ\s+([\d\.]+)\s+"  # MinQ (兼容浮点)
        r"MaxQ\s+([\d\.]+)"  # MaxQ (兼容浮点)
        r"(?:\s+Name\s+(\S+))?"  # Name (可选)
    )

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = pattern.search(line)
        if match:
            try:
                data.append(
                    {
                        "time": float(match.group(1)),
                        "queue_id": int(match.group(2)),
                        "last_q": int(
                            float(match.group(3))
                        ),  # 先转float再转int，处理 .000 情况
                        "min_q": int(float(match.group(4))),
                        "max_q": int(float(match.group(5))),
                        "name": match.group(6) if match.group(6) else None,
                    }
                )
            except ValueError:
                continue

    df = pd.DataFrame(data)
    if not df.empty:
        df["queue_id"] = df["queue_id"].astype(int)
    return df


def parse_sampling_events_from_file(file_path: Union[str, Path]) -> pd.DataFrame:
    """从日志文件中提取采样数据 (RANGE)"""
    text = runner.get_queue_range(str(file_path))
    return parse_sampling_events(text)


# ==========================================
# 2. QueueLoggerEmpty (轻量/利用率)
# ==========================================


def clean_queue_name(raw_name: str) -> str:
    """
    清洗队列名称。
    原始: compqueue(100000Mb/s,1427600bytes)LS0->DST0(0)
    清洗后: LS0->DST0 (表示 LS0 发往 DST0 的队列)
    """
    # 只要名字里不含空格，直接字符串处理即可
    if ")" in raw_name and "(" in raw_name:
        try:
            # 提取两个括号中间的关键拓扑信息
            return raw_name.split(")", 1)[1].split("(")[0]
        except IndexError:
            return raw_name
    return raw_name


def parse_usage_log(content: str) -> pd.DataFrame:
    data = []

    for line in content.splitlines():
        line = line.strip()
        if not line:
            continue

        parts = line.split()

        # 严格检查：必须有 7 列
        if len(parts) >= 7:
            try:
                # [0] Time: 皮秒 -> 秒
                timestamp = float(parts[0]) / 1e12

                # [1] Name: 原始名称
                raw_name = parts[1]

                # [过滤] 剔除主机(Uec/Src)数据，只看交换机链路(->)
                # 如果你想看主机数据，把这两行注释掉即可
                if "->" not in raw_name:
                    continue

                # [2] Total Busy (累积忙碌时间, ps) - 之前被跳过
                total_busy = int(parts[2])

                # [3] Period (采样周期, ps) - 之前被跳过
                period = int(parts[3])

                # [4] Utilization (利用率 0.0-1.0)
                util = float(parts[4])

                # [5] Trim Fraction (丢包率)
                trim_frac = float(parts[5])

                # [6] Queue Usage / High Watermark (队列积压字节)
                q_len = int(parts[6])

                # 清洗名字
                clean_name = clean_queue_name(raw_name)

                data.append(
                    {
                        "time": timestamp,
                        "queue_name": clean_name,  # 清洗后的名字 (LS0->DST0)
                        "raw_name": raw_name,  # 原始名字
                        "utilization": util,
                        "trim_frac": trim_frac,
                        "queue_usage": q_len,
                        "period_ps": period,  # 新增：存下来以备检查
                        "total_busy_ps": total_busy,  # 新增：存下来以备检查
                    }
                )
            except ValueError:
                continue

    return pd.DataFrame(data)


def parse_usage_log_from_file(file_path: Union[str, Path]) -> pd.DataFrame:
    """直接读取 stdout 文件进行解析"""
    p = Path(file_path)
    if not p.exists():
        return pd.DataFrame()

    try:
        content = p.read_text(encoding="utf-8")
        return parse_usage_log(content)
    except Exception as e:
        print(f"Error parsing usage log: {e}")
        return pd.DataFrame()


# ==========================================
# 3. QueueLoggerSimple (调试/显微镜)
# ==========================================


def parse_simple_events(text: str) -> pd.DataFrame:
    """
    解析 QueueLoggerSimple 产生的详细事件。
    对应 C++: QueueLoggerSimple::event_to_str -> QUEUE_EVENT
    注意：数据量极大，建议仅对特定时间窗口或特定队列 ID 使用。

    Returns:
        DataFrame columns: [time, queue_id, event, qsize, flow_id, pkt_id]
    """
    data = []

    # Regex 对应 parse_output.cpp L70-96
    # 格式示例: 0.000012 ID 42 Ev ENQUEUE Qsize 1500 FlowID 7 PktID 123
    pattern = re.compile(
        r"(\d+\.\d+)\s+"  # Time
        r"ID\s+(\d+)\s+"  # ID
        r"Ev\s+(\w+)\s+"  # Event (ENQUEUE, DROP, etc.)
        r"Qsize\s+(\d+)\s+"  # Qsize
        r"FlowID\s+(\d+)\s+"  # FlowID
        r"PktID\s+(\d+)"  # PktID
    )

    for line in text.splitlines():
        # 只有包含 QUEUE_EVENT 的行才会被 parse_output 处理 (通常通过 filter 保证)
        # 但 parse_output 的输出通常不带 "Type QUEUE_EVENT" 前缀 (参考 cpp case 0)，只输出了 ID...
        # 所以这里的 regex 直接匹配 ID 开头的部分
        match = pattern.search(line)
        if match:
            data.append(
                {
                    "time": float(match.group(1)),
                    "queue_id": int(match.group(2)),
                    "event": match.group(3),
                    "q_size": int(match.group(4)),
                    "flow_id": int(match.group(5)),
                    "pkt_id": int(match.group(6)),
                }
            )

    return pd.DataFrame(data)


def parse_simple_events_from_file(
    file_path: Union[str, Path], queue_id: Optional[int] = None
) -> pd.DataFrame:
    """
    解析详细的队列事件。
    """
    # 调用 runner 中封装函数，保持接口一致性
    text = runner.get_queue_events(str(file_path), queue_id=queue_id)
    return parse_simple_events(text)


def parse_traffic_events(text: str) -> pd.DataFrame:
    """
    解析 QueueLoggerSampling 产生的 CUM_TRAFFIC 事件 (流量信息)。
    语义：CumArr/CumIdle/CumDrop 均为累积时间(秒)。
    更新: 兼容浮点数格式
    变更：将秒转化为微秒
    """
    data = []

    # 格式: ... Ev CUM_TRAFFIC CumArr 0.000256 CumIdle 0.000000 CumDrop 0.000000
    pattern = re.compile(
        r"(\d+\.\d+)\s+"  # Time
        r"Type\s+QUEUE_APPROX\s+"  # Type
        r"ID\s+(\d+)\s+"  # ID
        r"Ev\s+CUM_TRAFFIC\s+"  # Event
        r"CumArr\s+([\d\.]+)\s+"  # CumArr (Seconds)
        r"CumIdle\s+([\d\.]+)\s+"  # CumIdle (Seconds)
        r"CumDrop\s+([\d\.]+)"  # CumDrop (Seconds)
    )

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = pattern.search(line)
        if match:
            try:
                data.append(
                    {
                        "time": float(match.group(1)),
                        "queue_id": int(match.group(2)),
                        # 将下面的三个时间均转化为微秒
                        "cum_arr_us": float(match.group(3)) * 1e6,
                        "cum_idle_us": float(match.group(4)) * 1e6,
                        "cum_drop_us": float(match.group(5)) * 1e6,
                    }
                )
            except ValueError:
                continue

    df = pd.DataFrame(data)
    if not df.empty:
        df["queue_id"] = df["queue_id"].astype(int)
    return df


def parse_traffic_events_from_file(file_path: Union[str, Path]) -> pd.DataFrame:
    """从日志文件中提取累积流量数据 (CUM_TRAFFIC)"""
    text = runner.get_queue_cum_traffic(str(file_path))
    return parse_traffic_events(text)


def parse_overflow_events(text: str) -> pd.DataFrame:
    """
    [新增] 解析 QueueLoggerSampling 产生的 OVERFLOW 事件。
    兼容 htsim 日志中可能的 Typo ("OVERLOW")。
    """
    data = []

    # 匹配 ... Ev OVERFLOW LastIdled -100 LastDropped 0 QueueBuf 15000 ...
    pattern = re.compile(
        r"(\d+\.\d+)\s+"  # Time
        r"Type\s+QUEUE_APPROX\s+"  # Type
        r"ID\s+(\d+)\s+"  # ID
        r"Ev\s+(?:OVERFLOW|OVERLOW)\s+"  # Event (Handle Typo)
        r"LastIdled\s+([\d\.\-]+)\s+"  # LastIdled (Can be negative)
        r"LastDropped\s+([\d\.]+)\s+"  # LastDropped
        r"QueueBuf\s+([\d\.]+)"  # QueueBuf
    )

    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue

        match = pattern.search(line)
        if match:
            try:
                data.append(
                    {
                        "time": float(match.group(1)),
                        "queue_id": int(match.group(2)),
                        "last_idled_bytes": float(match.group(3)),
                        "last_dropped_bytes": float(match.group(4)),
                        "queue_buf_bytes": float(match.group(5)),
                    }
                )
            except ValueError:
                continue

    df = pd.DataFrame(data)
    if not df.empty:
        df["queue_id"] = df["queue_id"].astype(int)
    return df


def parse_overflow_events_from_file(file_path: Union[str, Path]) -> pd.DataFrame:
    text = runner.run_parse(str(file_path), flags=["-ascii", "-filter", "OVERLOW"])
    return parse_overflow_events(text)
