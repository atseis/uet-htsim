# src/runner.py
import datetime
import subprocess
import os
from pathlib import Path
from enum import Enum, auto
from typing import List, Dict, Optional, Union, Tuple

CURRENT_DIR = Path(__file__).parent
PROJECT_DIR = CURRENT_DIR.parent
BUILD_DIR = PROJECT_DIR / "out" / "Debug"
PARSE_OUTPUT = BUILD_DIR / "parse_output"
error_log_file = "sim_errors.log"


class AnalysisType(Enum):
    """分析类型枚举，用于指定分析的目的"""

    FLOW_INFO = auto()  # 流级信息
    COLLECTIVE_COMPLETION = auto()  # 集合通信完成时间
    QUEUE_DELAY = auto()  # 队列延迟
    GOODPUT = auto()  # 吞吐量
    INCAST_DELAY = auto()  # Incast延迟
    CONGESTION_SIGNALS = auto()  # 拥塞信号
    ARRIVAL_RATE = auto()  # 到达率
    DROP_EVENTS = auto()  # 丢包事件
    PAUSE_EVENTS = auto()  # 暂停帧事件
    FCT = auto()  # 流完成时间
    CWND = auto()  # 拥塞窗口


def get_flags_for_analysis(
    analysis_type: AnalysisType,
    protocol: Optional[str] = None,
    filter_strings: List[str] = [],
    fields: List[int] = [],
    **kwargs,
) -> List[str]:
    """
    根据分析类型生成适当的命令行参数

    Args:
        analysis_type: 分析类型
        protocol: 协议类型 (tcp, ndp, roce, eqds, hpcc, swift等)
        filter_strings: 过滤字符串列表
        fields: 要提取的字段列表
        **kwargs: 其他参数

    Returns:
        命令行参数列表
    """
    flags = []

    # 基于分析类型添加基本参数
    if analysis_type == AnalysisType.FLOW_INFO:
        flags.append("-ascii")
        if not filter_strings:
            filter_strings = ["FLOW_EVENT"]

    elif analysis_type == AnalysisType.COLLECTIVE_COMPLETION:
        flags.append("-ascii")
        if not filter_strings:
            filter_strings = ["FLOW_EVENT", "finish"]

    elif analysis_type == AnalysisType.QUEUE_DELAY:
        flags.append("-ascii")
        if not filter_strings:
            filter_strings = ["QUEUE_APPROX"]

    elif analysis_type == AnalysisType.GOODPUT:
        flags.append("-ascii")
        if protocol:
            filter_strings = [f"{protocol.upper()}_SINK", "RATE"]
        else:
            filter_strings = ["SINK", "RATE"]

    elif analysis_type == AnalysisType.INCAST_DELAY:
        flags.append("-ascii")
        if not filter_strings:
            filter_strings = ["QUEUE_APPROX"]

    # 添加过滤字符串
    for s in filter_strings:
        flags.extend(["-filter", s])

    # 添加字段
    if fields:
        flags.extend(["-fields", ",".join(map(str, fields))])

    # 其他参数
    for key, value in kwargs.items():
        if key in ["filter_strings", "fields"]:
            continue
        flags.extend([f"-{key}", str(value)])

    return flags


def analyze_by_purpose(
    logfile: str, analysis_type: AnalysisType, protocol: Optional[str] = None, **kwargs
) -> str:
    """
    根据分析目的运行parse_output并返回结果

    Args:
        logfile: 日志文件路径
        analysis_type: 分析类型
        protocol: 协议类型
        **kwargs: 其他参数，可包含:
            - filter_strings: 过滤字符串列表
            - fields: 要提取的字段列表
            - show: 是否显示统计信息
            - verbose: 是否显示详细信息
            - idmap: ID映射文件

    Returns:
        parse_output的输出结果
    """
    flags = get_flags_for_analysis(
        analysis_type=analysis_type,
        protocol=protocol,
        filter_strings=kwargs.get("filter_strings", []),
        fields=kwargs.get("fields", []),
        **kwargs,
    )

    return run_parse(logfile, flags)


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
    if not bin_full.is_file():
        return {
            "stdout": "",
            "stderr": f"binary NOT FOUND: {bin_full.as_posix()}",
            "exit_code": 1,
            "command": " ".join([bin_full.as_posix()] + flags),
        }
    cmd = [bin_full.as_posix()]
    if flags:
        cmd.extend(flags)
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
            log_entry = f"[{cur_time}] Command failed: {command_str}\nError: {bin_full.as_posix()}:\n{e.stderr}\n"
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
    """获取流完成时间信息"""
    return analyze_by_purpose(
        logfile=logfile,
        analysis_type=AnalysisType.FLOW_INFO,
        protocol=protocol,
        **kwargs,
    )


def get_collective_completion_times(logfile: str, **kwargs) -> str:
    """获取集合通信完成时间信息"""
    return analyze_by_purpose(
        logfile=logfile, analysis_type=AnalysisType.COLLECTIVE_COMPLETION, **kwargs
    )


def get_queue_delay_timeseries(
    logfile: str, queue_id: Optional[str] = None, **kwargs
) -> str:
    """获取队列延迟时间序列"""
    filter_strings = kwargs.get("filter_strings", ["QUEUE_APPROX"])
    if queue_id:
        filter_strings.append(f"ID {queue_id}")

    kwargs["filter_strings"] = filter_strings
    return analyze_by_purpose(
        logfile=logfile, analysis_type=AnalysisType.QUEUE_DELAY, **kwargs
    )


def get_goodput_timeseries(
    logfile: str, protocol: str, flow_ids: List[str] = [], **kwargs
) -> str:
    """获取吞吐量时间序列"""
    filter_strings = kwargs.get("filter_strings", [])
    if flow_ids:
        for flow_id in flow_ids:
            filter_strings.append(f"ID {flow_id}")

    kwargs["filter_strings"] = filter_strings
    return analyze_by_purpose(
        logfile=logfile, analysis_type=AnalysisType.GOODPUT, protocol=protocol, **kwargs
    )


def get_incast_delay(logfile: str, switch_id: Optional[str] = None, **kwargs) -> str:
    """获取Incast延迟信息"""
    filter_strings = kwargs.get("filter_strings", ["QUEUE_APPROX"])
    if switch_id:
        filter_strings.append(f"ID {switch_id}")

    kwargs["filter_strings"] = filter_strings
    return analyze_by_purpose(
        logfile=logfile, analysis_type=AnalysisType.INCAST_DELAY, **kwargs
    )


def get_congestion_signals(logfile: str, protocol: str, **kwargs) -> str:
    """获取拥塞信号信息"""
    return analyze_by_purpose(
        logfile=logfile,
        analysis_type=AnalysisType.CONGESTION_SIGNALS,
        protocol=protocol,
        **kwargs,
    )


def get_arrival_rate(logfile: str, queue_id: Optional[str] = None, **kwargs) -> str:
    """获取到达率信息"""
    filter_strings = kwargs.get("filter_strings", ["QUEUE_APPROX", "ARRIVAL"])
    if queue_id:
        filter_strings.append(f"ID {queue_id}")

    kwargs["filter_strings"] = filter_strings
    return analyze_by_purpose(
        logfile=logfile, analysis_type=AnalysisType.ARRIVAL_RATE, **kwargs
    )


def get_drop_events(logfile: str, queue_id: Optional[str] = None, **kwargs) -> str:
    """获取丢包事件信息"""
    filter_strings = kwargs.get("filter_strings", ["QUEUE_EVENT", "DROP"])
    if queue_id:
        filter_strings.append(f"ID {queue_id}")

    kwargs["filter_strings"] = filter_strings
    return analyze_by_purpose(
        logfile=logfile, analysis_type=AnalysisType.DROP_EVENTS, **kwargs
    )


def get_pause_events(logfile: str, queue_id: Optional[str] = None, **kwargs) -> str:
    """获取暂停帧事件信息"""
    filter_strings = kwargs.get("filter_strings", ["QUEUE_EVENT", "PAUSE"])
    if queue_id:
        filter_strings.append(f"ID {queue_id}")

    kwargs["filter_strings"] = filter_strings
    return analyze_by_purpose(
        logfile=logfile, analysis_type=AnalysisType.PAUSE_EVENTS, **kwargs
    )


def get_cwnd_timeseries(
    logfile: str, protocol: str, flow_ids: List[str] = [], **kwargs
) -> str:
    """获取拥塞窗口时间序列"""
    filter_strings = kwargs.get("filter_strings", ["CWND"])
    if flow_ids:
        for flow_id in flow_ids:
            filter_strings.append(f"ID {flow_id}")

    kwargs["filter_strings"] = filter_strings
    return analyze_by_purpose(
        logfile=logfile, analysis_type=AnalysisType.CWND, protocol=protocol, **kwargs
    )


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
