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

    格式规定：
    1. 区别两种 id: 小写 id 表示模拟运行中的各种 id; 大写 ID 表示 Logged 分配的、日志中查看到的 ID
        id: 比如 flowid 24, Uec_304_0 中的 304 和 0 就是 id
        ID: 使用 parse_output 从日志中读取到的就是 ID，idmap 中的 key 都是 ID
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

    # ==========================
    # Modified: 核心数据解析 (重构 Queue/Switch 分离)
    # ==========================

    @cached_property
    def _raw_sampling_df(self) -> pd.DataFrame:
        """
        [内部方法] 加载所有 Sampling 类型 (Type 5) 的原始数据。
        包含 Queue 和 Switch 的混合数据。
        """
        if not self.log_path.exists():
            return pd.DataFrame()

        # 1. 解析原始数据
        df_range = queue.parse_sampling_events_from_file(self.log_path)
        df_traffic = queue.parse_traffic_events_from_file(self.log_path)

        if df_range.empty:
            return pd.DataFrame()

        # 2. 合并 Range 和 Traffic
        if not df_traffic.empty:
            # 确保按 time, queue_id 合并 (注意: 这里 queue_id 实质是 object_id)
            df = pd.merge(df_range, df_traffic, on=["time", "queue_id"], how="left")
        else:
            df = df_range
            df["cum_arr_us"] = 0.0
            df["cum_drop_us"] = 0.0

        return df

    @cached_property
    def queue_df(self) -> pd.DataFrame:
        """
        [修正后] 仅返回【队列】相关的采样数据。
        自动剔除 Switch 级日志，并计算微分指标。
        """
        df = self._raw_sampling_df
        if df.empty:
            return df

        # 1. 利用 IdMap 过滤：只保留 Queue ID
        # 注意：需确保 self.idmap 已加载
        valid_ids = set(self.idmap.queueIDs)
        df = df[df["queue_id"].isin(valid_ids)].copy()

        if df.empty:
            return df

        # 2. 调用通用计算逻辑 (计算 Utilization/Drop)
        return self._compute_metrics(df)

    @cached_property
    def switch_df(self) -> pd.DataFrame:
        """
        [新增] 仅返回【交换机】级聚合数据 (Shared Buffer Usage)。
        """
        df = self._raw_sampling_df
        if df.empty:
            return df

        # 1. 利用 IdMap 过滤：只保留 Switch ID
        valid_ids = set(self.idmap.switchIDs)
        df = df[df["queue_id"].isin(valid_ids)].copy()

        if df.empty:
            return df

        # 2. Switch 通常关注 Buffer 占用，利用率计算可能不同，
        # 但基础的 Traffic 统计逻辑是通用的。
        # Switch Log 的核心价值是 Shared Buffer (last_q/max_q)

        # 注入名称
        if self.idmap.data:
            df["name"] = df["queue_id"].map(self.idmap.data)

        return df

    def _compute_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [内部通用] 计算 Utilization 和 Drop Ratio。
        抽离出来供 queue_df 复用 (switch_df 视需求也可复用)
        """
        # 排序确保差分正确
        df = df.sort_values(by=["queue_id", "time"])

        # 计算时间窗口 dt
        df["dt_us"] = df.groupby("queue_id")["time"].diff().fillna(0) * 1e6
        df["d_arr"] = df.groupby("queue_id")["cum_arr_us"].diff().fillna(0)
        df["d_drop"] = df.groupby("queue_id")["cum_drop_us"].diff().fillna(0)

        mask = df["dt_us"] > 0.001

        # Utilization
        df.loc[mask, "utilization"] = (
            df.loc[mask, "d_arr"] - df.loc[mask, "d_drop"]
        ) / df.loc[mask, "dt_us"]

        # Drop Ratio
        valid_load = (df["d_arr"] > 0.001) & mask
        df.loc[valid_load, "drop_ratio"] = (
            df.loc[valid_load, "d_drop"] / df.loc[valid_load, "d_arr"]
        )

        # 清洗
        df["utilization"] = df["utilization"].fillna(0).clip(0, 1.0)
        df["drop_ratio"] = df["drop_ratio"].fillna(0).clip(0, 1.0)

        # 注入元数据
        if self.idmap.data:
            df["name"] = df["queue_id"].map(self.idmap.data)

            # Category 逻辑仅对 Queue 有效，Switch 不需要 LinkType 分类
            # 可以在此处判断，或仅在 queue_df 中处理 category
            if "category" not in df.columns:
                # ... (原有 category 注入逻辑) ...
                pass  # 为了代码简洁，这里略过，建议保留在 queue_df 专属逻辑中

        # 清理中间列
        return df.drop(columns=["dt_us", "d_arr", "d_drop"], errors="ignore")

    # ==========================
    # Modified: 智能清洗逻辑 (DRY Refactoring)
    # ==========================

    def _clean_sampling_df(
        self, df: pd.DataFrame, value_col: str = "max_q"
    ) -> pd.DataFrame:
        """
        [内部通用] 清洗采样数据 (Queue 或 Switch)。
        逻辑：
        1. 剔除全程 value_col (如 max_q) 均为 0 的 ID。
        2. 裁剪掉最后一次活跃之后的时间段 (Tail Trimming)。
        """
        if df.empty:
            return df

        # 1. 剔除“死对象”
        # 这里的 queue_id 是泛指 (Queue ID 或 Switch ID)
        peaks = df.groupby("queue_id")[value_col].max()
        active_ids = peaks[peaks > 0].index

        if len(active_ids) == 0:
            return pd.DataFrame(columns=df.columns)

        df_active = df[df["queue_id"].isin(active_ids)].copy()

        # 2. 尾部裁剪
        # 找出所有活跃时刻
        active_events = df_active[df_active[value_col] > 0]

        # 找出每个 ID 的“最后活跃时间”
        cutoff_times = active_events.groupby("queue_id")["time"].max().reset_index()
        cutoff_times.rename(columns={"time": "cutoff_time"}, inplace=True)

        # 合并并过滤
        df_merged = df_active.merge(cutoff_times, on="queue_id", how="left")
        df_clean = df_merged[df_merged["time"] <= df_merged["cutoff_time"]]

        return df_clean.drop(columns=["cutoff_time"]).reset_index(drop=True)

    @cached_property
    def active_queue_df(self) -> pd.DataFrame:
        """
        [智能清洗] 获取“有效”的队列数据。
        (Refactored to use _clean_sampling_df)
        """
        # 依赖于前一步定义的 self.queue_df
        return self._clean_sampling_df(self.queue_df, value_col="max_q")

    @cached_property
    def active_switch_df(self) -> pd.DataFrame:
        """
        [新增] 获取“有效”的交换机聚合数据。

        逻辑：
        仅保留 Shared Buffer 曾经被使用过 (max_q > 0) 的交换机，
        并裁剪掉实验末尾空闲的数据。
        """
        # 依赖于前一步定义的 self.switch_df
        return self._clean_sampling_df(self.switch_df, value_col="max_q")

    @cached_property
    def last_hop_queue_df(self) -> pd.DataFrame:
        """
        [聚焦筛选] 仅获取“有效的 Last Hop”活跃队列。

        逻辑：
        1. 基于 active_queue_df (已清洗死数据)。
        2. 利用 idmap.valid_last_hop_queueIDs() 过滤出真正参与通信的 Last Hop 队列。
           (即: 仅保留目的节点是真实 Sink 节点的边缘队列)

        这在 Incast 场景下非常有用，能直接锁定瓶颈位置。
        """
        df = self.active_queue_df
        if df.empty:
            return df

        # 1. 获取有效的 Last Hop ID 列表
        # valid_last_hop_queueIDs() 会根据 flow 信息动态判断哪些节点是 Sink，
        # 进而筛选出连接这些 Sink 的 Last Hop 队列。
        target_ids = set(self.idmap.valid_last_hop_queueIDs())

        # 2. 筛选
        return df[df["queue_id"].isin(target_ids)].reset_index(drop=True)

    @cached_property
    def queue_usage_df(self) -> pd.DataFrame:
        """
        [轻量] 解析 stdout.log 中的 QueueLoggerEmpty 数据。
        常用于大规模拓扑的利用率概览。

        Returns columns:
            [time, name, utilization, trim_frac, high_watermark]
        """
        if not self.stdout_path.exists():
            return pd.DataFrame()
        return queue.parse_usage_log_from_file(self.stdout_path)

    def get_queue_events_df(self, queue_id: Optional[int] = None) -> pd.DataFrame:
        """
        [调试] 解析 QueueLoggerSimple 的详细事件 (QUEUE_EVENT)。

        注意：
        - 这是一个**方法**而不是 cached_property，因为数据量可能非常大且通常只需按需查询。
        - 强烈建议传入 queue_id 进行过滤，否则可能导致内存压力。

        Args:
            queue_id: 指定要抓取的队列 ID。

        Returns columns:
            [time, queue_id, event, q_size, flow_id, pkt_id]
        """
        if not self.log_path.exists():
            return pd.DataFrame()

        # 调用 queue.py -> runner.py (get_queue_events)
        return queue.parse_simple_events_from_file(self.log_path, queue_id=queue_id)

    @cached_property
    def idmap(self) -> idmap.IdMap:
        return idmap.IdMap(self.idmap_path)

    # ==========================
    # 3. 业务辅助方法
    # ==========================

    def get_status_vars(self, key: str, default=None):
        """便捷获取 status.yaml 中的配置项"""
        return self.status_vars.get(key, default)

    def get_name_by_LogID(self, log_id) -> Optional[str]:
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
        """根据 LogID 查找 flowid (级联查找)"""
        name = self.get_name_by_LogID(log_id)
        if name:
            return self.get_flowid_by_name(name)
        return None
