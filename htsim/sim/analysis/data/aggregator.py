import os
from typing import Dict, Union
import pandas as pd
from pathlib import Path
from .filepath import get_experiment_files_typed
from ..parser import statusyaml, flow
from .metrics import compute_percentile_fct


def get_P99_conns(path: Union[str, Path]):
    files = get_experiment_files_typed(path)
    conns = statusyaml.parse_variables(files.status)["conns"]
    df = flow.parse_flow_events_from_file(files.log.as_posix())
    p99 = compute_percentile_fct(df, 99)
    return conns, p99  # 单位： ns


def collect_P99_conns(path: Union[str, Path]):
    results = []
    for entry in os.scandir(path):
        if entry.is_dir() and entry.name != "plots":
            conns, p99 = get_P99_conns(entry.path)
            results.append({"conns": conns, "P99_Latency": p99})
    df = pd.DataFrame(results)
    df = df.sort_values(by="conns")
    return df


p = "/root/code/uet-htsim/htsim/sim/results/RICC_tests/config_baseline/"

print(collect_P99_conns(p))
