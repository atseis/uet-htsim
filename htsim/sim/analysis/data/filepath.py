from pathlib import Path
from typing import NamedTuple
from typing import Dict, Union


# 定义返回结构
class ExperimentFiles(NamedTuple):
    log: Path
    idmap: Path
    status: Path


def _resolve_base_dir(path: Union[str, Path]) -> Path:
    """内部辅助函数：根据输入路径确定实验的根目录"""
    p = Path(path)
    if p.is_dir():
        return p
    elif p.is_file():
        return p.parent
    elif not p.exists():
        raise FileNotFoundError(f"Path {path} 不存在")
    else:
        # 处理其他情况（如 socket 文件等），通常视为无效
        raise FileNotFoundError(f"Path {path} 无效")


def get_experiment_files_typed(path: Union[str, Path]) -> ExperimentFiles:
    base_dir = _resolve_base_dir(path)  # 复用上面的辅助函数

    # 预定义文件路径
    log_path = base_dir / "output.log"
    idmap_path = base_dir / "idmap.txt"
    status_path = base_dir / "status.yaml"

    # 检查所有文件是否存在
    # (这里演示了一种批量检查的写法)
    check_list = [
        (log_path, "output.log"),
        (idmap_path, "idmap.txt"),
        (status_path, "status.yaml"),
    ]

    for p_obj, name in check_list:
        if not p_obj.is_file():
            raise FileNotFoundError(f"{name} 未在路径 {base_dir} 中找到")

    # 返回对象
    return ExperimentFiles(log=log_path, idmap=idmap_path, status=status_path)


# --- 使用示例 ---
# p = "/root/code/uet-htsim/htsim/sim/results/RICC_tests/config_baseline/uec_baseline_incastconns32"
# files = get_experiment_files_typed(p)
# print(files.log)  # IDE 会自动提示 .log, .status, .idmap
# print(files.status)
# print(files.idmap)
