import re
import pandas as pd
from typing import Union, Optional
from pathlib import Path
from .. import runner


def parse_traffic_events(text: str) -> pd.DataFrame:
    """
    解析 TrafficLoggerSimple 产生的详细数据包事件。
    格式: 0.000000332 Type TRAFFIC ID 2553 Ev DEPART  FlowID 9006 PktID 0
    """
    data = []
    # 正则匹配：时间, ID, 事件类型, FlowID, PktID
    pattern = re.compile(
        r"(\d+\.\d+)\s+Type\s+TRAFFIC\s+ID\s+(\d+)\s+Ev\s+(\w+)\s+FlowID\s+(\d+)\s+PktID\s+(\d+)"
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
                        "location_id": int(match.group(2)),
                        "event": match.group(3),
                        "flow_id": int(match.group(4)),
                        "pkt_id": int(match.group(5)),
                    }
                )
            except ValueError:
                continue

    df = pd.DataFrame(data)
    if not df.empty:
        df["location_id"] = df["location_id"].astype(int)
        df["flow_id"] = df["flow_id"].astype(int)
        df["pkt_id"] = df["pkt_id"].astype(int)
    return df


def parse_traffic_events_from_file(file_path: Union[str, Path]) -> pd.DataFrame:
    """从日志文件中提取流量包事件 (TRAFFIC)"""
    # 调用 runner 执行 parse_output -ascii -filter TRAFFIC
    text = runner.run_parse(str(file_path), flags=["-ascii", "-filter", "TRAFFIC ID"])
    return parse_traffic_events(text)


# if __name__ == "__main__":
#     p = "/root/code/uet-htsim/htsim/sim/results/RICC_tests/diag_baseline_autopsy_seed4/debug_seed4_autopsy/output.log"
#     print(parse_traffic_events_from_file(p))
