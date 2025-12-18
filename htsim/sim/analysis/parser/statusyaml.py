import re
import yaml
from pathlib import Path
from typing import Dict, List


def get_command(status_path: Path) -> str:
    """
    读取 status.yaml，返回 command
    """
    if not status_path.is_file():
        raise FileNotFoundError(f"status.yaml 文件不存在: {status_path}")

    with status_path.open("r") as f:
        status = yaml.safe_load(f)
        command = status.get("command", "")
    return command


def parse_variables(status_path: Path) -> Dict:
    """
    读取 status.yaml，返回 {variable: value} 字典
    """
    if not status_path.is_file():
        raise FileNotFoundError(f"status.yaml 文件不存在: {status_path}")

    with status_path.open("r") as f:
        status = yaml.safe_load(f)
        variables = status.get(
            "variables", []
        )  # 修正: default should be list based on your usage logic

    # 兼容处理: 如果 variables 为空字符串或 None，返回空字典
    if not variables:
        return {}

    # 你的原有逻辑: variables 是 list of dicts
    variables = {k: v for d in variables for k, v in d.items()}
    return variables


# ==========================================
# 新增功能: 解析 Logs
# ==========================================
def parse_enabled_logs(status_path: Path) -> List[str]:
    """
    从 status.yaml 的 command 中解析出开启了哪些 log。
    例如: "... -log sink -log flow_events ..." -> ['sink', 'flow_events']
    """
    # 1. 获取原始命令字符串
    cmd = get_command(status_path)

    # 2. 使用正则查找所有匹配项
    # \s+ 兼容可能有多个空格的情况
    pattern = r"-log\s+(\S+)"
    logs = re.findall(pattern, cmd)

    return logs


def parse_command_params(status_path: Path) -> Dict:
    """
    [Robust Fix] 解析完整的命令行参数。
    支持单值 (-linkspeed 100000) 和多值 (-pfc_thresholds 20 80) 参数。
    """
    cmd = get_command(status_path)

    # 正则逻辑：
    # -([a-zA-Z_0-9]+) : 匹配以 - 开头的参数名
    # \s+ : 匹配参数名后的空格
    # (.*?) : 非贪婪匹配后续内容
    # (?=\s-|$): 直到遇到“空格+横杠”或“字符串末尾”为止（断言，不消费字符）
    pattern = r"-([a-zA-Z_0-9]+)\s+(.*?)(?=\s-|$)"
    matches = re.findall(pattern, cmd)

    # 结果清洗：strip 掉可能存在的首尾空格
    return {k: v.strip() for k, v in matches}


if __name__ == "__main__":
    # 测试代码
    # 假设这是你的 status.yaml 路径 (请确保文件存在或使用 mock 数据测试)
    p = "/root/code/uet-htsim/htsim/sim/results/RICC_tests/diag_baseline_autopsy_seed4/debug_seed4_autopsy/status.yaml"
    path_obj = Path(p)

    try:
        # 测试 Logs 解析
        logs = parse_enabled_logs(path_obj)
        print(f"Enabled Logs: {logs}")

        logs = parse_command_params(path_obj)
        print(f"Enabled Logs: {logs}")

        # 测试原有功能
        vars = parse_variables(path_obj)
        print(f"Variables: {vars}")

    except FileNotFoundError as e:
        print(e)
