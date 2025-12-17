import re
from pathlib import Path
from typing import Dict, Union, Optional, List
from functools import cached_property
import pandas as pd
import numpy as np

# 假设 parser 模块结构如下
from ..parser import idmap, statusyaml, flow, queue, sink, nic


class ExperimentResult:
    """
    封装单个实验结果的访问接口 (Single Sub-Experiment Context).
    [Fixed]
    1. queue_df/switch_df 自动注入 Name。
    2. switch_df 瘦身：剔除无效的 Traffic/Overflow 列，仅保留 LastQ/MinQ/MaxQ。
    3. active_nic_df 移除冗余 Name。
    """

    FILES = {
        "log": "output.log",
        "idmap": "idmap.txt",
        "status": "status.yaml",
        "stdout": "stdout.log",
    }

    def __init__(self, path: Union[str, Path], rate_unit: str = "Gbps"):
        self.base_dir = self._resolve_base_dir(path)
        self.rate_unit = rate_unit
        self._validate_files()

    def _resolve_base_dir(self, path: Union[str, Path]) -> Path:
        p = Path(path)
        if p.is_dir():
            return p
        elif p.is_file():
            return p.parent
        elif not p.exists():
            raise FileNotFoundError(f"Path {path} does not exist")
        else:
            raise FileNotFoundError(f"Path {path} is invalid")

    def _validate_files(self):
        if not (self.base_dir / self.FILES["log"]).exists():
            pass

    def __repr__(self):
        return f"<ExperimentResult: {self.base_dir.name}>"

    # ==========================
    # 1. 基础组件
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

    @cached_property
    def idmap(self) -> idmap.IdMap:
        return idmap.IdMap(self.idmap_path)

    @cached_property
    def status_vars(self) -> Dict:
        if not self.status_path.exists():
            return {}
        return statusyaml.parse_variables(self.status_path)

    def get_status_vars(self, key: str, default=None):
        return self.status_vars.get(key, default)

    # ==========================
    # Helper: Name Injection
    # ==========================
    def _inject_name(self, df: pd.DataFrame, id_col: str) -> pd.DataFrame:
        """从 IdMap 注入名称到 DataFrame，优先使用 IdMap 覆盖现有 Name"""
        if df.empty or not self.idmap.data:
            return df

        # 避免 SettingWithCopyWarning
        df = df.copy()
        mapped_names = df[id_col].map(self.idmap.data)

        if "name" not in df.columns:
            df["name"] = mapped_names
        else:
            # 优先使用 idmap 映射出的名字，如果映射为 NaN，保留原值
            df["name"] = mapped_names.combine_first(df["name"])
        return df

    # ==========================
    # 2. 核心数据: Flow & NIC
    # ==========================

    @cached_property
    def flow_df(self) -> pd.DataFrame:
        if not self.log_path.exists():
            return pd.DataFrame()
        return flow.parse_flow_events_from_file(self.log_path.as_posix())

    @cached_property
    def nic_df(self) -> pd.DataFrame:
        if not self.log_path.exists():
            return pd.DataFrame()

        df = nic.parse_nic_events_from_file(self.log_path.as_posix())
        if df.empty:
            return df

        factor = 8 / 1e9 if self.rate_unit == "Gbps" else 8 / 1e6
        suffix = self.rate_unit

        for col in ["rx_data_bps", "rx_total_bps", "rx_trim_bps"]:
            if col in df.columns:
                new_col = col.replace("_bps", f"_{suffix}")
                df[new_col] = df[col] * factor

        # NIC 不需要 Name (IdMap 也没有 NIC ID)
        if "name" in df.columns:
            df = df.drop(columns=["name"])

        return df

    # ==========================
    # 3. 核心数据: Sink
    # ==========================

    @cached_property
    def _raw_sink_df(self) -> pd.DataFrame:
        if not self.log_path.exists():
            return pd.DataFrame()
        return sink.parse_goodputs_from_file(self.log_path.as_posix())

    @cached_property
    def flow_goodput_df(self) -> pd.DataFrame:
        return self._raw_sink_df

    def _convert_rate(self, df: pd.DataFrame) -> pd.DataFrame:
        if df.empty or "Rate" not in df.columns:
            return df
        col_name = f"Rate_{self.rate_unit}"
        factor = 8 / 1e9 if self.rate_unit == "Gbps" else 8 / 1e6
        df[col_name] = df["Rate"] * factor
        return df

    @cached_property
    def sink_goodput_df(self) -> pd.DataFrame:
        df = self._raw_sink_df
        if df.empty or not self.idmap.sink_id_to_flowIDs_map:
            return pd.DataFrame()
        agg_df = sink.aggregate_by_node_map(df, self.idmap.sink_id_to_flowIDs_map)
        return self._convert_rate(agg_df)

    @cached_property
    def src_goodput_df(self) -> pd.DataFrame:
        df = self._raw_sink_df
        if df.empty or not self.idmap.src_id_to_flowIDs_map:
            return pd.DataFrame()
        agg_df = sink.aggregate_by_node_map(df, self.idmap.src_id_to_flowIDs_map)
        return self._convert_rate(agg_df)

    @cached_property
    def total_goodput_df(self) -> pd.DataFrame:
        df = self._raw_sink_df
        if df.empty:
            return pd.DataFrame()
        all_ids = df["ID"].unique().tolist()
        agg_df = sink.aggregate_by_ids(df, all_ids)
        return self._convert_rate(agg_df)

    # ==========================
    # 4. 核心数据: Queue & Switch
    # ==========================

    @cached_property
    def _raw_sampling_df(self) -> pd.DataFrame:
        """Merge Range, Overflow, Traffic with High Precision Alignment."""
        if not self.log_path.exists():
            return pd.DataFrame()

        df_range = queue.parse_sampling_events_from_file(self.log_path)
        df_overflow = queue.parse_overflow_events_from_file(self.log_path)
        df_traffic = queue.parse_traffic_events_from_file(self.log_path)

        if df_range.empty:
            return pd.DataFrame()

        # 生成纳秒级整数键
        def make_time_key(df):
            if "time" in df.columns:
                df["_time_ns"] = (df["time"] * 1e9 + 0.5).astype(np.int64)

        make_time_key(df_range)

        if not df_overflow.empty:
            make_time_key(df_overflow)
            df_range = pd.merge(
                df_range,
                df_overflow.drop(columns=["time"]),
                on=["_time_ns", "queue_id"],
                how="left",
            )
        else:
            for col in ["last_dropped_bytes", "last_idled_bytes", "queue_buf_bytes"]:
                df_range[col] = 0.0

        if not df_traffic.empty:
            make_time_key(df_traffic)
            df_range = pd.merge(
                df_range,
                df_traffic.drop(columns=["time"]),
                on=["_time_ns", "queue_id"],
                how="left",
            )
        else:
            for col in ["cum_arr_us", "cum_idle_us", "cum_drop_us"]:
                df_range[col] = 0.0

        return df_range.drop(columns=["_time_ns"])

    @cached_property
    def queue_df(self) -> pd.DataFrame:
        """[Queue] 端口队列数据 (自动注入 Name + 计算高级指标)"""
        df = self._raw_sampling_df
        if df.empty:
            return df

        valid_ids = set(self.idmap.queueIDs)
        if not valid_ids:
            return df

        # 1. 筛选队列 ID
        df_filtered = df[df["queue_id"].isin(valid_ids)].copy()

        # 2. [New] 计算高级流量指标 (Utilization, Load Factor, etc.)
        df_metrics = self._compute_traffic_metrics(df_filtered)

        # 3. 注入名称
        return self._inject_name(df_metrics, "queue_id")

    @cached_property
    def switch_df(self) -> pd.DataFrame:
        """
        [Switch] 交换机整机数据 (Range Only)
        针对 Switch Log 仅包含 LastQ/MinQ/MaxQ 的特性，剔除无效列。
        """
        df = self._raw_sampling_df
        if df.empty:
            return df
        valid_ids = set(self.idmap.switchIDs)

        df_filtered = df[df["queue_id"].isin(valid_ids)].copy()

        # [Slim] 仅保留有效的 Range 数据列
        cols_to_keep = ["time", "queue_id", "last_q", "min_q", "max_q"]
        # 兼容性保护: 仅保留存在的列
        existing_cols = [c for c in cols_to_keep if c in df_filtered.columns]
        df_filtered = df_filtered[existing_cols]

        return self._inject_name(df_filtered, "queue_id")

    @cached_property
    def queue_usage_df(self) -> pd.DataFrame:
        if not self.stdout_path.exists():
            return pd.DataFrame()
        return queue.parse_usage_log_from_file(self.stdout_path)

    # ==========================
    # 5. 智能清洗与筛选
    # ==========================

    def _clean_inactive_series(
        self, df: pd.DataFrame, id_col: str, value_col: str
    ) -> pd.DataFrame:
        """
        通用清洗逻辑：
        1. 剔除死对象
        2. 尾部空闲裁剪
        3. 自动注入 Name (如果还没注入)
        """
        if df.empty or id_col not in df.columns or value_col not in df.columns:
            return df

        # 1. 剔除死对象
        peaks = df.groupby(id_col)[value_col].max()
        active_ids = peaks[peaks > 0].index
        if len(active_ids) == 0:
            return pd.DataFrame(columns=df.columns)

        df_active = df[df[id_col].isin(active_ids)].copy()

        # 2. 尾部裁剪
        last_active = df_active[df_active[value_col] > 0].groupby(id_col)["time"].max()
        df_active = df_active.merge(last_active.rename("cutoff"), on=id_col, how="left")
        df_clean = df_active[df_active["time"] <= df_active["cutoff"]].drop(
            columns=["cutoff"]
        )

        # 3. 兜底注入 Name (queue_df/switch_df 可能已经注入了，但复用该逻辑无害)
        return self._inject_name(df_clean, id_col).reset_index(drop=True)

    @cached_property
    def active_queue_df(self) -> pd.DataFrame:
        return self._clean_inactive_series(self.queue_df, "queue_id", "max_q")

    @cached_property
    def active_switch_df(self) -> pd.DataFrame:
        return self._clean_inactive_series(self.switch_df, "queue_id", "max_q")

    @cached_property
    def active_nic_df(self) -> pd.DataFrame:
        col = f"rx_total_{self.rate_unit}"
        df = self._clean_inactive_series(self.nic_df, "nic_id", col)
        if "name" in df.columns:
            df = df.drop(columns=["name"])
        return df

    @cached_property
    def last_hop_queue_df(self) -> pd.DataFrame:
        df = self.active_queue_df
        if df.empty:
            return df
        target_ids = set(self.idmap.valid_last_hop_queueIDs())
        return df[df["queue_id"].isin(target_ids)].reset_index(drop=True)

    # ==========================
    # 6. 拓扑筛选
    # ==========================

    def get_queues_by_type(self, link_type_enum) -> pd.DataFrame:
        df = self.active_queue_df
        if df.empty:
            return df
        target_ids = set(self.idmap.filter_queueIDs(link_type_enum))
        return df[df["queue_id"].isin(target_ids)].reset_index(drop=True)

    @property
    def tor_downlink_queues(self) -> pd.DataFrame:
        return self.get_queues_by_type(idmap.LinkType.TOR_DOWN)

    @property
    def agg_downlink_queues(self) -> pd.DataFrame:
        return self.get_queues_by_type(idmap.LinkType.AGG_DOWN)

    @property
    def core_downlink_queues(self) -> pd.DataFrame:
        return self.get_queues_by_type(idmap.LinkType.CORE_DOWN)

    @property
    def server_uplink_queues(self) -> pd.DataFrame:
        return self.get_queues_by_type(idmap.LinkType.SERVER_UP)

    # ==========================
    # 7. 辅助查找工具
    # ==========================

    def get_name_by_LogID(self, log_id) -> Optional[str]:
        return self.idmap.get(log_id)

    def get_flowid_by_name(self, target_name: str) -> Optional[int]:
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
        name = self.get_name_by_LogID(log_id)
        if name:
            return self.get_flowid_by_name(name)
        return None

    def get_queue_events_df(self, queue_id: int) -> pd.DataFrame:
        if not self.log_path.exists():
            return pd.DataFrame()
        return queue.parse_simple_events_from_file(self.log_path, queue_id=queue_id)

    # ==========================
    # Helper: Traffic Metrics Calculation
    # ==========================
    def _compute_traffic_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [New] 基于累积量计算微分指标 (Windowed Metrics)。

        修正点：
        1. [Fix] 第一行数据不再丢失：NaN 差分填充为原始值 (Delta = Value - 0)。
        2. [Fix] 利用率改为百分比显示 (0-100)。
        3. [Fix] 增加噪声门限，清除 1e-16 这种极小值。
        """
        # 必须包含 Traffic 相关列才能计算
        required_cols = ["cum_arr_us", "cum_idle_us", "cum_drop_us", "time", "queue_id"]
        if df.empty or not all(col in df.columns for col in required_cols):
            return df

        # 避免修改原始缓存数据
        df = df.copy()

        # 按队列分组并按时间排序
        df = df.sort_values(by=["queue_id", "time"])

        # 定义需要做差分的列
        diff_cols = ["time", "cum_arr_us", "cum_idle_us", "cum_drop_us"]

        # 1. 计算微分 (Diff)
        grouped = df.groupby("queue_id")[diff_cols]
        diffs = grouped.diff()

        # [Fix] 核心修复：处理第一行数据
        # diff() 第一行是 NaN，我们假设初始状态为 0，所以第一行的 Delta = Current - 0
        # 使用 fillna 将 NaN 替换为 df 原始列的值
        for col in diff_cols:
            diffs[col] = diffs[col].fillna(df[col])

        # 2. 计算时间窗口 (转为微秒)
        # diffs["time"] 是秒，乘以 1e6 转为 us
        dt_us = diffs["time"] * 1e6
        dt_us = dt_us.replace(0, np.nan)  # 防除零

        # 3. 计算利用率 (Utilization %)
        # 公式: 1.0 - (空闲时间 / 总时间)
        d_idle = diffs["cum_idle_us"]
        raw_util = 1.0 - (d_idle / dt_us)

        # [Fix] 数据清洗：截断范围 + 噪声过滤
        # 先 clip 到理论范围 [0, 1]
        raw_util = raw_util.clip(0.0, 1.0)
        # 过滤极小噪声 (e.g., 4.44e-16 -> 0.0)
        raw_util = raw_util.where(raw_util > 1e-6, 0.0)
        # 转为百分比
        df["utilization"] = raw_util * 100.0

        # 4. 计算到达强度 (Load Factor)
        d_arr = diffs["cum_arr_us"]
        df["load_factor"] = d_arr / dt_us

        # 5. 计算丢弃比例 (Drop Ratio %)
        d_drop = diffs["cum_drop_us"]
        safe_arr = d_arr.replace(0, np.nan)
        raw_drop = (d_drop / safe_arr).clip(0.0, 1.0)
        df["drop_ratio"] = raw_drop * 100.0  # 也转为百分比更直观

        # 6. 填充由除以零产生的 NaN (比如 load_factor)
        fill_cols = ["utilization", "load_factor", "drop_ratio"]
        df[fill_cols] = df[fill_cols].fillna(0.0)

        return df
