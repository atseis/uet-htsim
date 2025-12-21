import yaml
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List
import subprocess


def get_git_commit() -> str:
    try:
        return (
            subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=Path(__file__).parent.parent.parent.parent,
            )
            .decode("ascii")
            .strip()
        )
    except:
        return "unknown"


def load_status(status_file_path: Path) -> Dict[str, Any]:
    if status_file_path.exists():
        with open(status_file_path, "r") as f:
            return yaml.safe_load(f) or {}
    return {}


def save_status(status_file_path: Path, status_data: Dict[str, Any]):
    status_file_path.parent.mkdir(parents=True, exist_ok=True)
    with open(status_file_path, "w") as f:
        yaml.safe_dump(status_data, f)


def initialize_status(
    status_file_path: Path,
    command: str,
    experiment_id: str,
    variables: Optional[List[Dict[str, Any]]] = None,
    all_params: Optional[Dict[str, Any]] = None,
    source_yaml: Optional[str] = None,
) -> Dict[str, Any]:
    """初始化 status.yaml，新增 all_params 存储全量配置"""
    status_data = {
        "id": experiment_id,
        "command": command,
        "source_yaml": source_yaml,
        "start_time": datetime.now().strftime("%Y-%m-%d_%H-%M-%S"),
        "end_time": None,
        "duration_sec": None,
        "status": "pending",
        "exit_code": None,
        "error_log": "",
        "git_commit": get_git_commit(),
        "rerun_count": 0,
        "variables": variables if variables is not None else [],
        "all_params": all_params if all_params is not None else {},  # [新增]
    }
    save_status(status_file_path, status_data)
    return status_data


def update_status(
    status_file_path: Path,
    new_status: str,
    exit_code: Optional[int] = None,
    error_log: str = "",
    start_time: Optional[str] = None,
    end_time: Optional[str] = None,
    duration_sec: Optional[float] = None,
    variables: Optional[List[Dict[str, Any]]] = None,
    all_params: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:  # [新增]
    status_data = load_status(status_file_path)
    status_data["status"] = new_status
    if exit_code is not None:
        status_data["exit_code"] = exit_code
    if error_log:
        status_data["error_log"] = error_log
    if start_time:
        status_data["start_time"] = start_time
    if end_time:
        status_data["end_time"] = end_time
    if duration_sec is not None:
        status_data["duration_sec"] = duration_sec
    if variables is not None:
        status_data["variables"] = variables
    if all_params is not None:
        status_data["all_params"] = all_params

    if new_status == "running":
        status_data["rerun_count"] = status_data.get("rerun_count", 0) + 1
        status_data["start_time"] = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        status_data["end_time"] = None
        status_data["duration_sec"] = None
        status_data["exit_code"] = None
        status_data["error_log"] = ""

    save_status(status_file_path, status_data)
    return status_data


def should_run(status_file_path: Path, force_rerun: bool) -> bool:
    if force_rerun:
        return True

    status_data = load_status(status_file_path)
    current_status = status_data.get("status", "pending")

    if current_status in ["success", "running"]:
        return False

    return True  # pending or failed
