# src/runner.py
import datetime
import subprocess
import os
from pathlib import Path
from enum import Enum, auto
from typing import List, Dict, Optional, Union, Tuple

from numpy import printoptions

CURRENT_DIR = Path(__file__).parent
PROJECT_DIR = CURRENT_DIR.parent
BUILD_DIR = PROJECT_DIR / "out" / "Debug"
PARSE_OUTPUT = BUILD_DIR / "parse_output"
error_log_file = "sim_errors.log"


def run_parse(logfile: str, flags: list = ["-ascii"]) -> str:
    if not PARSE_OUTPUT.is_file():
        raise FileNotFoundError(f"parse_output NOT FOUND: {PARSE_OUTPUT.as_posix()}")
    if not os.path.isfile(logfile):
        raise FileNotFoundError(f"logfile NOT FOUND: {logfile}")
    cmd = [str(PARSE_OUTPUT), logfile]
    if flags:
        cmd.extend(flags)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout
    except subprocess.CalledProcessError as e:
        raise RuntimeError(f"FAILED RUNNING parse_output:\n{e.stderr}") from e


def run_sim(bin: str, flags: list = []) -> Dict[str, Union[str, int]]:
    bin_full = BUILD_DIR / bin
    expanded_flags = []
    for arg in flags:
        if isinstance(arg, str) and " " in arg:
            expanded_flags.extend(arg.split())
        else:
            expanded_flags.append(arg)
    if not bin_full.is_file():
        return {
            "stdout": "",
            "stderr": f"binary NOT FOUND: {bin_full.as_posix()}",
            "exit_code": 1,
            "command": " ".join([bin_full.as_posix()] + expanded_flags),
        }
    cmd = [bin_full.as_posix()]
    if expanded_flags:
        cmd.extend(expanded_flags)
    command_str = " ".join(cmd)
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return {
            "stdout": result.stdout,
            "stderr": "",
            "exit_code": 0,
            "command": command_str,
        }
    except subprocess.CalledProcessError as e:
        with open(error_log_file, "a") as f:
            cur_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{cur_time}] Command failed: {command_str}\nError: {bin_full.as_posix()}:\n{e.stderr}\n{e.stdout}\n"
            f.write(log_entry)
            print(f"Error written to: {error_log_file}")
        return {
            "stdout": e.stdout,
            "stderr": e.stderr,
            "exit_code": e.returncode,
            "command": command_str,
        }
    except Exception as e:
        with open(error_log_file, "a") as f:
            cur_time = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            log_entry = f"[{cur_time}] Command failed with unexpected error: {command_str}\nError: {str(e)}\n"
            f.write(log_entry)
            print(f"Error written to: {error_log_file}")
        return {
            "stdout": "",
            "stderr": str(e),
            "exit_code": 1,
            "command": command_str,
        }


# 以下是针对特定分析场景的辅助函数


def get_flow_completion_times(
    logfile: str, protocol: Optional[str] = None, **kwargs
) -> str:
    return run_parse(logfile, ["-ascii", "-filter", "FLOW_EVENT"])


def get_sink_goodputs(logfile: str, protocol: Optional[str] = None) -> str:
    if protocol:
        flags = ["-ascii", "-filter", protocol + "_SINK"]
    else:
        flags = ["-ascii", "-filter", "SINK"]
    return run_parse(logfile, flags)


def get_queue_range(logfile: str) -> str:
    # 在当前的实现当中（QueueLoggerSampling::doNextEvent()） ，type 都是 QUEUE_APPROX
    # 区别只体现在在 ev 上（目前包含 QUEUE_RANGE, QUEUE_OVERFLOW）
    # 具体数据结构可见 QueueLogger
    flags = ["-ascii", "-filter", "QUEUE_APPROX", "-filter", "RANGE"]
    return run_parse(logfile, flags)


# src/runner.py (添加在文件末尾或 get_queue_range 附近)


def get_queue_events(logfile: str, queue_id: Optional[int] = None) -> str:
    """
    获取 QueueLoggerSimple 的原始事件日志 (QUEUE_EVENT)。
    对应 parse_output -filter QUEUE_EVENT

    Args:
        logfile: 日志文件路径
        queue_id: (可选) 如果指定，则通过 grep 进一步筛选特定 ID，减少数据量
    """
    # 基础参数: 获取所有 QUEUE_EVENT
    # 注意: parse_output 的 QUEUE_EVENT 对应 id=0, ev=0
    flags = ["-ascii", "-filter", "QUEUE_EVENT"]

    # 获取原始输出
    output = run_parse(logfile, flags)

    # 如果指定了 queue_id，可以在 Python 层面做一次简单的过滤
    # (或者如果 parse_output 支持针对 ID 的 filter 更好，但目前看代码似乎只支持字符串 filter)
    if queue_id is not None:
        # 简单过滤: 只保留包含 "ID <queue_id> " 的行
        target = f"ID {queue_id} "
        filtered_lines = [line for line in output.splitlines() if target in line]
        return "\n".join(filtered_lines)

    return output


def get_queue_cum_traffic(logfile: str) -> str:
    """
    [新增] 获取 QueueLoggerSampling 的累积时间统计数据。
    对应 Ev CUM_TRAFFIC
    注意：需确认 C++ output log 中是否正确输出了浮点数，否则全为 0。
    """
    # 过滤关键字：Type QUEUE_APPROX ... Ev CUM_TRAFFIC
    flags = ["-ascii", "-filter", "QUEUE_APPROX", "-filter", "CUM_TRAFFIC"]
    return run_parse(logfile, flags)


def load_idmap(filepath: str) -> dict[int, str]:
    mapping = {}
    with open(filepath, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            id, text = line.split(maxsplit=1)
            mapping[int(id)] = text
    return mapping
