from typing import Union
import re
from pathlib import Path

import pandas as pd

from .. import runner


def parse_line_auto(line):
    parts = line.split()

    result = {"time": float(parts[0])}
    i = 1
    while i < len(parts):
        key = parts[i]
        if i + 1 < len(parts) and re.match(r"^[0-9.+-]+$", parts[i + 1]):
            result[key] = (
                float(parts[i + 1]) if "." in parts[i + 1] else int(parts[i + 1])
            )
            i += 2
        else:
            i += 1
    return result


def is_valid_log_line(line: str) -> bool:
    # 时间 + Type 关键字
    parts = line.split()
    if len(parts) < 4:
        return False
    if parts[1] != "Type":
        return False
    # 时间字段必须是数字
    try:
        float(parts[0])
    except Exception:
        return False
    return True


def parse_queue_range(logs: str, ids=[]) -> pd.DataFrame:
    lines = logs.strip().split("\n")
    valid_lines = [l for l in lines if is_valid_log_line(l)]
    rows = [parse_line_auto(l) for l in valid_lines]
    df = pd.DataFrame(rows)
    if ids:
        df = df[df["ID"].isin(ids)]
    return df


def parse_queue_range_from_file(file_path: Union[str, Path], ids=[]) -> pd.DataFrame:
    file_path = str(file_path)
    logs = runner.get_queue_range(file_path)
    return parse_queue_range(logs, ids)
