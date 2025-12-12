from typing import Union, List, Optional, Dict
import re
from pathlib import Path
import pandas as pd
from .. import runner


# ==========================================
# 1. 核心解析逻辑 (保持不变，稳健解析 Key-Value)
# ==========================================
def parse_line_auto(line: str) -> Optional[Dict]:
    parts = line.split()
    if len(parts) < 3:
        return None
    try:
        result = {"time": float(parts[0])}
    except ValueError:
        return None

    i = 1
    while i < len(parts):
        if i + 1 >= len(parts):
            break
        key = parts[i]
        val_str = parts[i + 1]

        # 尝试转数字，否则存字符串
        if re.match(r"^[0-9.+-]+$", val_str):
            try:
                val = float(val_str) if "." in val_str else int(val_str)
                result[key] = val
            except ValueError:
                result[key] = val_str
        else:
            result[key] = val_str
        i += 2
    return result


def is_valid_log_line(line: str) -> bool:
    parts = line.split()
    # 只要包含 Time 和 Type 就算有效日志
    if len(parts) < 3:
        return False
    try:
        float(parts[0])
    except ValueError:
        return False
    return parts[1] == "Type"


# ==========================================
# 2. 增强的筛选逻辑 (替代原来的 "RANGE" 搜索)
# ==========================================
def parse_queue_range(
    logs: str, ids: Optional[List[int]] = None, only_sampling: bool = True
) -> pd.DataFrame:
    """
    解析队列日志。

    Args:
        logs: 日志文本内容
        ids: 需要筛选的 Queue ID 列表
        only_sampling:
            True  -> 只返回原来的 "RANGE" 数据 (Type=QUEUE_APPROX)
            False -> 返回所有队列数据 (包含逐包事件 Type=QUEUE_EVENT)
    """
    lines = logs.strip().split("\n")
    rows = []
    for l in lines:
        if is_valid_log_line(l):
            row = parse_line_auto(l)
            if row:
                rows.append(row)

    df = pd.DataFrame(rows)
    if df.empty:
        return df
    # print(ids)
    # print(df)
    # print("=============================================================")

    # 1. ID 筛选
    if ids is not None and "ID" in df.columns:
        if not isinstance(ids, list):
            ids = [ids]
        df = df[df["ID"].isin(ids)]
    # print(df)

    # 2. Type 筛选 (核心变化：用 Type 替代 RANGE)
    if only_sampling and "Type" in df.columns:
        # 只保留采样数据 (对应原来的 RANGE 事件)
        # 注意：C++ 输出的字符串可能是 "QUEUE_APPROX"
        df = df[df["Type"] == "QUEUE_APPROX"]

    # 3. 列整理
    desired_order = ["time", "Type", "ID", "Ev", "Qsize", "LastQ", "MinQ", "MaxQ"]
    cols = [c for c in desired_order if c in df.columns] + [
        c for c in df.columns if c not in desired_order
    ]
    return df[cols]


def parse_queue_range_from_file(
    file_path: Union[str, Path], ids: Optional[List[int]] = None
) -> pd.DataFrame:
    file_path = str(file_path)
    logs = runner.get_queue_range(file_path)
    # 默认只返回 Sampling (RANGE) 数据，保持和旧函数行为一致
    return parse_queue_range(logs, ids, only_sampling=True)

