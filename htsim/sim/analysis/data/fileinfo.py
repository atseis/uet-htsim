import re
from pathlib import Path
from typing import Dict, Union, Optional
from functools import cached_property
import pandas as pd

# 假设这些是你现有的 parser 模块
from ..parser import idmap, statusyaml, flow, queue


class ExperimentResult:
    """
    封装单个实验结果的访问接口。

    特点：
    1. 自动定位关键文件路径。
    2. 惰性加载：只有在访问数据属性（如 .flow_df, .status_vars）时才读取文件。
    3. 自动缓存：读取一次后存储在内存中，多次访问不消耗 IO。
    """

    # 关键文件名定义
    FILES = {
        "log": "output.log",
        "idmap": "idmap.txt",
        "status": "status.yaml",
        "stdout": "stdout.log",
    }

    def __init__(self, path: Union[str, Path]):
        self.base_dir = self._resolve_base_dir(path)
        self._validate_files()

    def _resolve_base_dir(self, path: Union[str, Path]) -> Path:
        """解析路径，支持传入目录或目录下的任意文件"""
        p = Path(path)
        if p.is_dir():
            return p
        elif p.is_file():
            return p.parent
        elif not p.exists():
            raise FileNotFoundError(f"Path {path} 不存在")
        else:
            raise FileNotFoundError(f"Path {path} 无效")

    def _validate_files(self):
        """快速检查关键文件是否存在"""
        # 这里只检查必须存在的文件，status/idmap 等如果是可选的，可以把检查逻辑放宽
        for name, filename in self.FILES.items():
            if not (self.base_dir / filename).exists():
                # 你可以选择 warning 而不是 raise error，视业务严格程度而定
                # print(f"Warning: {filename} missing in {self.base_dir}")
                pass

    def __repr__(self):
        return f"<ExperimentResult: {self.base_dir.name}>"

    # ==========================
    # 1. 基础文件路径属性
    # ==========================

    @property
    def log_path(self) -> Path:
        return self.base_dir / self.FILES["log"]

    @property
    def idmap_path(self) -> Path:
        return self.base_dir / self.FILES["idmap"]

    @property
    def status_path(self) -> Path:
        return self.base_dir / self.FILES["status"]

    @property
    def stdout_path(self) -> Path:
        return self.base_dir / self.FILES["stdout"]

    # ==========================
    # 2. 核心数据解析 (惰性加载 + 缓存)
    # ==========================

    @cached_property
    def status_vars(self) -> Dict:
        """解析 status.yaml，返回字典"""
        if not self.status_path.exists():
            return {}
        return statusyaml.parse_variables(self.status_path)

    # @cached_property
    # def idmap_data(self) -> Dict:
    #     """解析 idmap.txt，返回 {id: name} 映射"""
    #     if not self.idmap_path.exists():
    #         return {}
    #     return idmap.read_idmap(self.idmap_path)

    @cached_property
    def flow_df(self) -> pd.DataFrame:
        """
        解析 output.log，返回 Pandas DataFrame。
        注意：这是重操作，只会执行一次。
        """
        if not self.log_path.exists():
            return pd.DataFrame()
        return flow.parse_flow_events_from_file(self.log_path.as_posix())

    @cached_property
    def idmap(self) -> idmap.IdMap:
        return idmap.IdMap(self.idmap_path)

    # ==========================
    # 3. 业务辅助方法
    # ==========================

    def get_config(self, key: str, default=None):
        """便捷获取 status.yaml 中的配置项"""
        return self.status_vars.get(key, default)

    def get_name_by_logid(self, log_id) -> Optional[str]:
        """根据 Log ID 获取名称"""
        return self.idmap.get(log_id)

    def get_flowid_by_name(self, target_name: str) -> Optional[int]:
        """
        从 stdout.log 中查找 flowid。
        如果此操作并不频繁，可以保持流式读取不缓存；
        如果频繁，建议也改成 @cached_property。
        """
        if not self.stdout_path.exists():
            return None

        pattern = re.compile(r"flowid\s+(\d+)\s+" + re.escape(target_name))
        try:
            with open(self.stdout_path, "r", encoding="utf-8") as f:
                for line in f:
                    match = pattern.search(line)
                    if match:
                        return int(match.group(1))
        except Exception:
            return None
        return None

    def get_flowid_by_logid(self, log_id) -> Optional[int]:
        """根据 log_id 查找 flowid (级联查找)"""
        name = self.get_name_by_logid(log_id)
        if name:
            return self.get_flowid_by_name(name)
        return None
