import re
from pathlib import Path
from typing import Dict, Union, Optional, List, Any
from functools import cached_property
import pandas as pd
import numpy as np

from ..parser import idmap, statusyaml, flow, queue, sink, nic, traffic, cwnd

# 设置 Pandas 全局显示格式：保留 9 位小数，强制不使用科学计数法
pd.options.display.float_format = "{:.9f}".format


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

    def help(self):
        """
        [Interactive Guide] 显示单次实验 (ExperimentResult) 可用的属性和指标。
        """
        guides = [
            # --- 核心指标 ---
            {"Type": "Metric", "Name": "p99_fct", "Desc": "99th Percentile Flow Completion Time (us)"},
            {"Type": "Metric", "Name": "max_fct", "Desc": "Maximum FCT observed (us)"},
            {"Type": "Metric", "Name": "max_drop_rate", "Desc": "Peak Trim/Drop rate (from queue usage)"},
            {"Type": "Metric", "Name": "fairness_index", "Desc": "Jain's Fairness Index for FCTs"},
            {"Type": "Metric", "Name": "queue_stability", "Desc": "Coefficient of Variation (CV) of Queue Depth"},
            
            # --- 数据表 ---
            {"Type": "DataFrame", "Name": "flow_df", "Desc": "Flow-level log: [src, dst, size, fct_ns, start_time]"},
            {"Type": "DataFrame", "Name": "queue_df", "Desc": "Queue sampling: [time, queue_id, max_q, utilization]"},
            {"Type": "DataFrame", "Name": "traffic_df", "Desc": "Packet-level trace (if enabled): [time, event, size]"},
            {"Type": "DataFrame", "Name": "switch_df", "Desc": "Switch buffer metrics: [last_q, min_q, max_q]"},
            
            # --- 动作/工具 ---
            {"Type": "Action", "Name": "report", "Desc": "Object: AutoVisualizer for quick plots (res.report.show())"},
            {"Type": "Action", "Name": "export_config()", "Desc": "Generate a reproduction YAML for this specific run"},
            {"Type": "Action", "Name": "params", "Desc": "Dict: Merged parameters (cmd args + variables)"},
        ]
        df = pd.DataFrame(guides)
        pd.set_option('display.max_colwidth', None)
        return df

    def _compute_metric(self, name: str):
        """
        核心计算逻辑：区分“零值”与“不可观测”。
        """
        logs = self.enabled_logs

        # 1. FCT 相关指标 (依赖 flow_events 日志)
        fct_metrics = ["max_fct", "p99_fct", "median_fct", "max_slowdown"]
        if name in fct_metrics:
            if "flow_events" not in logs:
                return None

            if self.flow_df.empty:
                return 0

            # 统一提取 FCT 数据 (us)
            fct_us = self.flow_df["fct_ns"] / 1000.0

            if name == "max_fct":
                return float(fct_us.max())
            elif name == "p99_fct":
                return float(np.percentile(fct_us, 99))
            elif name == "median_fct":
                return float(np.median(fct_us))
                return (
                    float(self.flow_slowdown_df["slowdown"].max())
                    if not self.flow_slowdown_df.empty
                    else 0
                )

        if name == "max_drop_rate":
            # 优先使用 queue_usage (轻量级日志)
            if not self.queue_usage_df.empty:
                return float(self.queue_usage_df["trim_frac"].max())
            
            # 如果有 detailed traffic log (重量级)
            if not self.traffic_df.empty:
                 # CUM_TRAFFIC: cum_drop / cum_arr
                 # 这需要重新计算，暂时通过 queue_usage 覆盖大多数情况
                 pass
            return 0.0

        # 2. RTO 相关指标 (依赖 traffic 日志)
        if name == "rto_count":
            if "traffic" not in logs:
                return None  # 重要：未开日志时返回 None，表示数据缺失

            if not self.traffic_df.empty:
                return int(len(self.traffic_df[self.traffic_df["event"] == "RTO"]))
            return 0  # 开了日志但没搜到 RTO，这才是真正的 0
        # 1. 公平性指标 (Jain's Fairness Index)
        # 计算同一 Incast 中各流 FCT 的公平程度
        if name == "fairness_index":
            if self.flow_df.empty:
                return 1.0
            fcts = self.flow_df["fct_ns"].values
            n = len(fcts)
            return (np.sum(fcts) ** 2) / (n * np.sum(fcts**2))

        # 2. 稳定性指标 (Stability Index)
        # 计算 CWND 或 队列 的波动率 (CV = std / mean)
        if name == "queue_stability":
            df = self.active_queue_df
            if df.empty:
                return 0
            return (
                df["max_q"].std() / df["max_q"].mean() if df["max_q"].mean() != 0 else 0
            )

        raise ValueError(f"Unknown metric: {name}")

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

    @cached_property
    def command_params(self) -> Dict:
        """从模拟命令中提取的原始参数字典"""
        return statusyaml.parse_command_params(self.status_path)

    @cached_property
    def params(self) -> Dict:
        """
        [Core Fix] 整合后的实验参数中心。
        优先级：variables (波动的变量) > command (命令行参数)
        """
        # 优先从 status.yaml 的新字段 all_params 读取
        all_p = self.status_data.get("all_params", {})
        if all_p:
            return all_p
        # 1. 首先加载命令行中的所有默认参数
        merged = self.command_params.copy()

        # 2. 使用 variables 中的值进行覆盖（因为 variables 记录了该子实验的具体取值）
        # 注意：需要将 status_vars 中的值转为字符串或保持一致，以便后续统一处理
        merged.update({k: str(v) for k, v in self.status_vars.items()})

        return merged

    def get_param(self, key: str, default=None, type_func=float):
        """安全地获取参数并转换类型"""
        val = self.params.get(key)
        if val is None:
            return default
        try:
            return type_func(val)
        except (ValueError, TypeError):
            return default

    def get_param_list(self, key: str, default=None, type_func=float) -> List:
        """
        [New] 专门用于处理多值参数 (如 pfc_thresholds 或 ecn)。
        返回转换后的列表。
        """
        val = self.params.get(key)
        if val is None:
            return default if default else []

        try:
            # 将 "20 80" 拆分为 ["20", "80"] 并转换类型
            return [type_func(x) for x in val.split()]
        except (ValueError, TypeError):
            return []

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
    def cwnd_df(self) -> pd.DataFrame:
        """从 stdout.log 提取 cwnd 演变轨迹"""
        if not self.stdout_path.exists():
            return pd.DataFrame()
        return cwnd.parse_cwnd_from_file(self.stdout_path)

    @cached_property
    def flow_df(self) -> pd.DataFrame:
        if not self.log_path.exists():
            return pd.DataFrame()
        return flow.parse_flow_events_from_file(self.log_path.as_posix())

    @cached_property
    def flow_slowdown_df(self) -> pd.DataFrame:
        df = self.flow_df.copy()
        if df.empty:
            return df

        # [Fix] 使用新的 get_param 逻辑从 merged params 中提取
        linkspeed_mbps = self.get_param("linkspeed", default=100000)
        linkspeed_bps = linkspeed_mbps * 1e6

        hop_latency_us = self.get_param("hop_latency", default=1.0)

        # 获取拓扑层级 (tiers)，默认为 3
        tiers = int(self.get_param("tiers", default=3))
        # 根据层数计算传播跳数 (2层: Src->ToR->Agg->ToR->Dst=4跳; 3层: 6跳)
        hops = 6 if tiers == 3 else 4

        base_rtt_ns = (hop_latency_us * hops) * 1000

        df["ideal_fct_ns"] = (df["size_bytes"] * 8 / linkspeed_bps) * 1e9 + base_rtt_ns
        df["slowdown"] = df["fct_ns"] / df["ideal_fct_ns"]
        df["slowdown"] = df["slowdown"].clip(lower=1.0)

        return df

    @cached_property
    def traffic_df(self) -> pd.DataFrame:
        """[Traffic] 全量数据包事件轨迹 (自动注入 Location Name)"""
        if not self.log_path.exists():
            return pd.DataFrame()

        # 解析原始数据
        df = traffic.parse_traffic_events_from_file(self.log_path)
        if df.empty:
            return df

        # 注入位置名称：将 location_id 映射为物理组件名
        return self._inject_name(df, "location_id")

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
            pass
            
        # If not found, try to parse target_name as an integer flow ID
        try:
            target_id_int = int(target_name)
            return target_id_int
        except ValueError:
            return None

    def get_flow_trace_data(self, flow_name: str) -> Dict[str, List[Any]]:
        """
        [New] Get detailed trace events for a specific flow (by Name).
        Used for Plotly/Sequence diagrams.
        """
        from ..parser import flow_debug
        
        if not self.stdout_path.exists():
            print(f"[Warn] No stdout.log found at {self.stdout_path}")
            return {}
            
        try:
             # Read full log (expensive but necessary for grep-less extraction)
            with open(self.stdout_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            return flow_debug.parse_flow_trace(content, flow_name)
        except Exception as e:
            print(f"Error parsing trace: {e}")
            return {}

    def get_flowid_by_logID(self, log_id) -> Optional[int]:
        name = self.get_name_by_LogID(log_id)
        if name:
            return self.get_flowid_by_name(name)
        return None

    def get_queue_events_df(self, queue_id: int) -> pd.DataFrame:
        if not self.log_path.exists():
            return pd.DataFrame()
        return queue.parse_simple_events_from_file(self.log_path, queue_id=queue_id)

    # ==========================
    # Traffic 衍生 Insight 指标
    # ==========================

    @property
    def trim_events_df(self) -> pd.DataFrame:
        """[UEC Specific] 快速提取全网报文裁剪 (Trim) 事件"""
        df = self.traffic_df
        if df.empty:
            return df
        # UEC 协议中，Trim 会被 TrafficLoggerSimple 记录为 TRIM 事件
        return df[df["event"] == "TRIM"].reset_index(drop=True)

    @property
    def drop_events_df(self) -> pd.DataFrame:
        """快速提取全网丢包事件"""
        df = self.traffic_df
        if df.empty:
            return df
        return df[df["event"] == "DROP"].reset_index(drop=True)

    def _compute_traffic_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        [Refined] 基于累积量计算采样窗口内的性能指标。

        计算公式:
        1. Utilization % = 100 * (1 - Δcum_idle / Δtime)
        2. Load Factor = Δcum_arr / Δtime
        3. Drop Ratio % = 100 * (Δcum_drop / Δcum_arr)
        """
        required_cols = ["cum_arr_us", "cum_idle_us", "cum_drop_us", "time", "queue_id"]
        if df.empty or not all(col in df.columns for col in required_cols):
            return df

        df = df.copy().sort_values(by=["queue_id", "time"])

        # 针对每个队列独立差分
        diff_cols = ["time", "cum_arr_us", "cum_idle_us", "cum_drop_us"]
        grouped = df.groupby("queue_id")[diff_cols]
        diffs = grouped.diff()

        # [Fix] 首行补偿：处理 diff() 产生的 NaN
        # 假设 t=0 时累积量为 0，则第一行的 Delta = 当前值
        for col in diff_cols:
            diffs[col] = diffs[col].fillna(df[col])

        # 时间差转换为微秒 (dt_us)
        dt_us = diffs["time"] * 1e6
        dt_us = dt_us.replace(0, np.nan)  # 避免除零错误

        # --- A. Utilization (%) ---
        # 反映链路忙碌程度
        raw_util = 1.0 - (diffs["cum_idle_us"] / dt_us)
        # 噪声过滤与范围限制
        df["utilization"] = raw_util.clip(0, 1).where(raw_util > 1e-6, 0) * 100.0

        # --- B. Load Factor ---
        # 反映到达强度 (Demand)，可能 > 1.0
        df["load_factor"] = diffs["cum_arr_us"] / dt_us
        df["load_factor"] = df["load_factor"].where(df["load_factor"] > 1e-6, 0)

        # --- C. Drop Ratio (%) ---
        # 反映因拥塞导致的工作量损失
        d_arr = diffs["cum_arr_us"].replace(0, np.nan)
        df["drop_ratio"] = (diffs["cum_drop_us"] / d_arr).clip(0, 1).fillna(0) * 100.0

        return df

    @cached_property
    def status_data(self) -> Dict:
        """[New] 完整加载 status.yaml 字典，避免多次磁盘读取"""
        if not self.status_path.exists():
            return {}
        import yaml

        try:
            with open(self.status_path, "r") as f:
                return yaml.safe_load(f) or {}
        except Exception:
            return {}

    @property
    def is_success(self) -> bool:
        """[New] 供 BatchResult 调用，判断该子实验是否成功完成"""
        # 从 status.yaml 的顶级 key 中读取 status
        return self.status_data.get("status") == "success"

    @cached_property
    def enabled_logs(self) -> set:
        """
        [New] 识别当前实验开启了哪些日志。
        利用已有的 statusyaml 解析器。
        """
        from ..parser.statusyaml import parse_enabled_logs

        if not self.status_path.exists():
            return set()
        return set(parse_enabled_logs(self.status_path))

    def get_cached_metric(self, metric_name: str, force_recompute: bool = False):
        """
        [Lazy-Save] 获取指标。如果 summary.json 有效则直接读取，否则计算并存入。
        """
        summary_path = self.base_dir / "summary.json"

        # 1. 直接使用缓存的 status_data 获取锚点 (start_time)
        current_anchor = self.status_data.get("start_time")  #

        # 2. 检查缓存是否可用 (逻辑同你之前的代码)
        summary_data = {}
        if summary_path.exists() and not force_recompute:
            try:
                import json

                with open(summary_path, "r") as f:
                    summary_data = json.load(f)
                if (
                    summary_data.get("anchor") == current_anchor
                    and metric_name in summary_data
                ):
                    return summary_data[metric_name]
            except Exception:
                pass

        # 3. 缓存失效：计算指标 (按需触发 flow_df/traffic_df 解析)
        value = self._compute_metric(metric_name)

        # 4. 回写缓存 (Lazy-Save)
        summary_data["anchor"] = current_anchor
        summary_data[metric_name] = value
        import json

        with open(summary_path, "w") as f:
            json.dump(summary_data, f, indent=4)

        return value

    @property
    def report(self):
        """
        [Lazy Loading] 返回一个 AutoVisualizer 实例用于快速绘图。
        仅在被调用时才会 import matplotlib 等库。
        用法: res.report.show() 或 res.report.save("path")
        """
        # 局部 import，避免污染核心类的依赖
        from ..viz.autoreport import AutoVisualizer

        return AutoVisualizer(self)

    def _get_identity_string(self) -> str:
        """
        从 status.yaml 的 variables 字段生成身份标识字符串。
        例如: [{'randseed': 46}, {'paths': 64}] -> 'randseed46_paths64'
        """
        variables = self.status_data.get("variables", [])
        parts = []
        for var_dict in variables:
            for k, v in var_dict.items():
                parts.append(f"{k}{v}")
        return "_".join(parts) if parts else "default"

    def export_config(self) -> str:
        """
        [New] 在原始 YAML 同路径下生成诊断用 YAML。
        格式: D_<原始yaml名称>_<身份标识>.yaml
        """
        import yaml

        data = self.status_data
        source_yaml_str = data.get("source_yaml")
        if not source_yaml_str:
            raise ValueError(f"status.yaml 中未记录 source_yaml，无法定位原始路径。")

        source_path = Path(source_yaml_str)
        all_params = data.get("all_params", {})

        # 1. 生成身份标识与文件名
        identity = self._get_identity_string()
        new_filename = f"D_{source_path.stem}_{identity}.yaml"
        target_path = source_path.parent / new_filename

        # 2. 区分 Traffic 与 Simulation 参数 (逻辑复用 experiment.py)
        traffic_keys = {
            "type",
            "nodes",
            "conns",
            "flows",
            "groupsize",
            "flowsize",
            "extrastarttime",
            "parallel",
            "locality",
            "groups",
            "randseed",
            "conns_incast",
            "conns_outcast",
            "prefer_remote",
        }

        traffic_params = {k: v for k, v in all_params.items() if k in traffic_keys}
        sim_params = {k: v for k, v in all_params.items() if k not in traffic_keys}

        # 移除自动生成的运行期冗余参数
        sim_params.pop("o", None)
        sim_params.pop("tm", None)

        # [Auto-Inject] 强制开启 Debug 和全量日志以支持深度诊断
        sim_params["debug"] = True
        sim_params["log"] = [
            "sink",
            "flow_events",
            "tor_downqueue",
            "traffic",
            "nic",
            "queue_usage",
        ]
        sim_params["logtime"] = 0.01

        # 提取可执行程序名
        original_cmd = data.get("command", "")
        exe = original_cmd.split()[0] if original_cmd else "htsim_uec"

        # 3. 构造 YAML 结构
        repro_config = {
            "common": {"execute": True, "simulation": sim_params},
            "experiments": [
                {"name": f"diag_{identity}", "exe": exe, "traffic": traffic_params}
            ],
        }

        # 4. 写入文件
        # 4. 写入文件 (带注释注入)
        yaml_str = yaml.dump(repro_config, sort_keys=False, indent=2)

        # [Auto-Inject] 简单字符串替换注入注释
        yaml_str = yaml_str.replace("debug: true", "debug: true # [Auto] Enable CWND logging")
        yaml_str = yaml_str.replace("logtime: 0.01", "logtime: 0.01 # [Auto] High precision")

        with open(target_path, "w", encoding="utf-8") as f:
            f.write(yaml_str)

        return str(target_path.resolve())

    def diagnose_deadlock(self) -> List[Dict]:
        """
        [New] Run the specific UEC Slient Packet Deadlock diagnosis.
        Returns a list of detected issues (dicts).
        """
        from .. import diagnose_deadlock
        
        if not self.log_path.exists() or not self.stdout_path.exists():
            return []
            
        try:
            return diagnose_deadlock.check_deadlock_issues(
                self.log_path.as_posix(), 
                self.stdout_path.as_posix()
            )
        except Exception as e:
            print(f"[Diagnose Error] {self.base_dir.name}: {e}")
            return []
