from collections import defaultdict, deque
import re
from pathlib import Path
from typing import Dict, List, Optional, Union

from pandas.errors import OptionError
import yaml

from ..parser import flow
from .. import runner
import pandas as pd


import re


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


def parse_sink_goodputs(logs: str, flow_ids=[]) -> pd.DataFrame:
    lines = logs.strip().split("\n")
    valid_lines = [l for l in lines if is_valid_log_line(l)]
    rows = [parse_line_auto(l) for l in valid_lines]
    df = pd.DataFrame(rows)
    if flow_ids:
        df = df[df["ID"].isin(flow_ids)]
    return df


def parse_sink_goodputs_from_file(
    file_path: str, protocol: Optional[str] = None, flow_ids=[]
) -> pd.DataFrame:
    logs = runner.get_sink_goodputs(file_path, protocol, flow_ids)
    return parse_sink_goodputs(logs, flow_ids)
