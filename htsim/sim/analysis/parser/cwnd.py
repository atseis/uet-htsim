import re
import pandas as pd
from pathlib import Path
from typing import Union


def parse_cwnd_log(content: str) -> pd.DataFrame:
    """
    解析 stdout.log 中关于 cwnd 和 in_flight 的输出。
    兼容发送包和处理 ACK 两种输出格式。
    """
    data = []

    # 模式 A: 对应 processAck/handleAck (输出包含 'flightsize')
    # At 17.0107 Uec_304_0 ... cwnd 262926 flightsize 46682
    pattern_ack = re.compile(
        r"At\s+(?P<time>[\d\.]+)\s+(?P<flow_name>\S+)\s+.*?cwnd\s+(?P<cwnd>\d+)\s+flightsize\s+(?P<in_flight>\d+)"
    )

    # 模式 B: 对应 sending pkt (输出包含 'in_flight')
    # 0 Uec_304_0 sending pkt 0 ... cwnd 262926 ... in_flight 4150
    pattern_send = re.compile(
        r"^(?P<time>[\d\.]+)\s+(?P<flow_name>\S+)\s+.*?cwnd\s+(?P<cwnd>\d+)\s+.*?in_flight\s+(?P<in_flight>\d+)",
        re.MULTILINE,
    )

    # 提取格式 A
    for match in pattern_ack.finditer(content):
        d = match.groupdict()
        data.append(
            {
                "time": float(d["time"]) / 1e6,  # 转换为秒 (s) 以对齐其他 DF
                "flow_name": d["flow_name"],
                "cwnd": int(d["cwnd"]),
                "in_flight": int(d["in_flight"]),
            }
        )

    # 提取格式 B
    for match in pattern_send.finditer(content):
        d = match.groupdict()
        data.append(
            {
                "time": float(d["time"]) / 1e6,
                "flow_name": d["flow_name"],
                "cwnd": int(d["cwnd"]),
                "in_flight": int(d["in_flight"]),
            }
        )

    df = pd.DataFrame(data)
    if not df.empty:
        # 按流和时间排序，确保曲线连续
        df = df.sort_values(by=["flow_name", "time"]).reset_index(drop=True)
    return df


def parse_cwnd_from_file(file_path: Union[str, Path]) -> pd.DataFrame:
    p = Path(file_path)
    if not p.exists():
        return pd.DataFrame()
    try:
        content = p.read_text(encoding="utf-8")
        return parse_cwnd_log(content)
    except Exception as e:
        print(f"Error parsing cwnd log: {e}")
        return pd.DataFrame()
