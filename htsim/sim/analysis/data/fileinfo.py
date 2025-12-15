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
    @cached_property
    def queue_df(self) -> pd.DataFrame:
        """
        [主力] 解析 QueueLoggerSampling 数据，合并水位 (RANGE) 和 流量 (TRAFFIC)。

        功能：
        1. 合并两个维度的日志 (Range 提供深度, Traffic 提供时间累积)。
        2. 计算微分指标：Utilization (链路利用率) 和 Drop Ratio (丢包率)。
        3. 注入元数据：Name, Category (链路位置)。

        Returns:
            pd.DataFrame: [time, queue_id, name, category,
                           last_q, min_q, max_q, (Bytes)
                           utilization, drop_ratio, (0.0-1.0)
                           cum_arr_us, cum_drop_us] (us)
        """
        if not self.log_path.exists():
            return pd.DataFrame()

        # 1. 解析原始数据 (直接使用 queue.py 的输出，天然时序)
        df_range = queue.parse_sampling_events_from_file(self.log_path)
        df_traffic = queue.parse_traffic_events_from_file(self.log_path)

        if df_range.empty:
            return pd.DataFrame()

        # 2. 数据合并
        # Left Join: 以 Range 数据为基准
        # 注意：Sampling Logger 在同一时刻会连续输出 Range 和 Traffic，因此时间戳完全一致，可以直接 merge
        if not df_traffic.empty:
            df = pd.merge(df_range, df_traffic, on=["time", "queue_id"], how="left")
        else:
            df = df_range
            df["cum_arr_us"] = 0.0
            df["cum_drop_us"] = 0.0

        # 3. 计算微分指标 (核心逻辑)
        # 虽然日志是时序的，但为了 diff() 计算的绝对安全，我们在计算前按 (ID, Time) 显式排序。
        # 这样可以防止万一日志在某些极端多线程写入情况下出现的微小乱序（虽罕见但防御性编程更好）。
        df = df.sort_values(by=["queue_id", "time"])

        # 计算时间窗口 dt (单位: 微秒, 与 cum_xxx 统一)
        # group by queue_id 确保我们是在同一个队列的时间线上做差分
        df["dt_us"] = df.groupby("queue_id")["time"].diff().fillna(0) * 1e6

        # 计算累积量的增量 (Delta)
        df["d_arr"] = df.groupby("queue_id")["cum_arr_us"].diff().fillna(0)
        df["d_drop"] = df.groupby("queue_id")["cum_drop_us"].diff().fillna(0)

        # 仅对有效的时间窗口进行计算 (防止除零或首帧噪声)
        mask = df["dt_us"] > 0.001

        # --- 指标 A: 链路利用率 (Utilization) ---
        # 公式: (处理总时间 - 丢包浪费的时间) / 物理时间窗口
        # 解释: _cumarr 包含了被丢弃包的处理时间(drainTime)，因此有效传输时间需减去 _cumdrop
        df.loc[mask, "utilization"] = (
            df.loc[mask, "d_arr"] - df.loc[mask, "d_drop"]
        ) / df.loc[mask, "dt_us"]

        # --- 指标 B: 丢包强度 (Drop Ratio) ---
        # 公式: 丢包时间 / 到达总时间 (offered load)
        # 反映拥塞严重程度
        valid_load = (df["d_arr"] > 0.001) & mask
        df.loc[valid_load, "drop_ratio"] = (
            df.loc[valid_load, "d_drop"] / df.loc[valid_load, "d_arr"]
        )

        # 4. 数据清洗与边界处理
        # 填补 NaN 并限制在 [0, 1] 范围内
        df["utilization"] = df["utilization"].fillna(0).clip(0, 1.0)
        df["drop_ratio"] = df["drop_ratio"].fillna(0).clip(0, 1.0)

        # 5. 元数据增强 (利用 IdMap)
        if self.idmap.data:
            # 映射名称
            df["name"] = df["queue_id"].map(self.idmap.data)

            # 映射类别 (Category) - 预计算优化性能
            id_to_cat = {}
            # 遍历 LinkType 枚举 (TOR_DOWN, AGG_UP 等)
            for link_type in idmap.LinkType:
                ids = self.idmap.filter_queueIDs(link_type)
                for qid in ids:
                    id_to_cat[qid] = link_type.name

            df["category"] = df["queue_id"].map(id_to_cat)

        # 清理中间计算列，保持 DataFrame 干净
        columns_to_drop = ["dt_us", "d_arr", "d_drop"]
        df.drop(columns=columns_to_drop, inplace=True, errors='ignore')

        return df

    @cached_property
    def active_queue_df(self) -> pd.DataFrame:
        """
        [智能清洗] 获取“有效”的队列数据。

        清洗逻辑：
        1. 死队列剔除：如果某队列全程 max_q 均为 0，则完全剔除。
        2. 尾部裁剪：对于有效队列，只保留到最后一次活跃(max_q > 0)的时间点，
           之后的一直为 0 的记录将被裁剪掉。

        Returns:
            清洗后的 pd.DataFrame
        """
        # 1. 获取原始数据
        df = self.queue_df
        if df.empty:
            return df

        # -------------------------------------------------------
        # 步骤 A: 剔除“死队列” (全程无流量)
        # -------------------------------------------------------
        # 按 queue_id 分组，计算 max_q 的最大值
        queue_peaks = df.groupby("queue_id")["max_q"].max()
        # 只保留峰值 > 0 的队列 ID
        active_ids = queue_peaks[queue_peaks > 0].index

        # 如果没有活跃队列，直接返回空表
        if len(active_ids) == 0:
            return pd.DataFrame(columns=df.columns)

        # 过滤 DataFrame
        df_active = df[df["queue_id"].isin(active_ids)].copy()

        # -------------------------------------------------------
        # 步骤 B: 尾部裁剪 (Tail Trimming)
        # -------------------------------------------------------
        # 1. 找出所有活跃时刻 (max_q > 0)
        active_events = df_active[df_active["max_q"] > 0]

        # 2. 找出每个队列的“最后活跃时间” (Last Active Time)
        #    result: queue_id -> time
        cutoff_times = active_events.groupby("queue_id")["time"].max().reset_index()
        cutoff_times.rename(columns={"time": "cutoff_time"}, inplace=True)

        # 3. 将 cutoff_time 合并回原表
        #    df_merged 将多出一列 cutoff_time
        df_merged = df_active.merge(cutoff_times, on="queue_id", how="left")

        # 4. 只保留 time <= cutoff_time 的记录
        #    这样就删除了最后一次活跃之后的所有 0 值记录
        df_clean = df_merged[df_merged["time"] <= df_merged["cutoff_time"]]

        # 5. 清理辅助列并重置索引
        return df_clean.drop(columns=["cutoff_time"]).reset_index(drop=True)

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
