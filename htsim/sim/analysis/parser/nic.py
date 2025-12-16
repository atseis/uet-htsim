import re
import pandas as pd
from typing import Optional
from .. import runner


def parse_nic_events(text: str) -> pd.DataFrame:
    """
    解析 parse_output 的 NIC_EVENT 输出。

    Format example:
    0.000800000 Type NIC_EVENT ID 426 Data 0 Total 0 Trim 0

    Args:
        text: 包含 NIC_EVENT 的日志文本

    Returns:
        pd.DataFrame: columns [time, nic_id, rx_data_bps, rx_total_bps, rx_trim_bps]
    """
    data = []

    # Pattern 匹配: Time, ID, Data(New), Total, Trim
    # 兼容整数和浮点数格式 ([\d\.]+)
    pattern = re.compile(
        r"(\d+\.\d+)\s+"  # Time (Group 1)
        r"Type\s+NIC_EVENT\s+"  # Type
        r"ID\s+(\d+)\s+"  # ID (Group 2)
        r"Data\s+([\d\.]+)\s+"  # Data/New Rate (Group 3)
        r"Total\s+([\d\.]+)\s+"  # Total Rate (Group 4)
        r"Trim\s+([\d\.]+)"  # Trim Rate (Group 5)
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
                        "nic_id": int(match.group(2)),
                        "rx_data_bps": float(match.group(3)),
                        "rx_total_bps": float(match.group(4)),
                        "rx_trim_bps": float(match.group(5)),
                    }
                )
            except ValueError:
                continue

    df = pd.DataFrame(data)
    if not df.empty:
        # 确保 ID 列为整数类型，方便后续 join
        df["nic_id"] = df["nic_id"].astype(int)
    return df


def parse_nic_events_from_file(file_path: str) -> pd.DataFrame:
    """
    从文件中读取并解析 NIC 事件。
    调用 runner.run_parse 并指定 NIC_EVENT 过滤器。
    """
    # 严格遵守 runner.py 接口: run_parse(logfile: str, flags: list)
    text = runner.run_parse(file_path, flags=["-ascii", "-filter", "NIC_EVENT"])
    return parse_nic_events(text)
