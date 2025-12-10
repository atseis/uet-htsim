import re, yaml
from uuid import main
from typing import Dict, List, Callable, Union
from pathlib import Path


def parse_variables(status_path: Path):
    """
    读取 status.yaml，返回 {variable: value} 字典
    """
    if not status_path.is_file():
        raise FileNotFoundError(f"status.yaml 文件不存在: {status_path}")

    with status_path.open("r") as f:
        status = yaml.safe_load(f)
        variables = status.get("variables", "")
    variables = {k: v for d in variables for k, v in d.items()}
    return variables


if __name__ == "__main__":
    p = "/root/code/uet-htsim/htsim/sim/results/RICC_tests/config_baseline/uec_baseline_incastconns16/status.yaml"
    vars = parse_variables(Path(p))

    print(vars)
