import re
from pathlib import Path
from typing import Dict, Union, Optional
from functools import cached_property
import pandas as pd

# 假设这些是你现有的 parser 模块
from ..parser import idmap, statusyaml, flow, queue, sink, nic


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

    def __init__(self, path: Union[str, Path], rate_unit: str = "Gbps"):
        self.base_dir = self._resolve_base_dir(path)
        self.rate_unit = rate_unit
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
    def nic_df(self) -> pd.DataFrame:
        """
        [新增 Insight] NIC 级吞吐量监控 (Per NIC Throughput).

        包含指标:
        - rx_data: 有效数据接收速率 (Goodput-like)
        - rx_total: 总接收速率 (含包头/重传)
        - rx_trim: 被 Trim (截断) 的速率
        """
        if not self.log_path.exists():
            return pd.DataFrame()

        # 1. 解析原始数据
        df = nic.parse_nic_events_from_file(self.log_path.as_posix())
        if df.empty:
            return df

        # 2. 自动单位转换 (Bps -> Gbps/Mbps)
        # NIC Log 原始单位为 Bytes/sec
        factor = 8 / 1e9 if self.rate_unit == "Gbps" else 8 / 1e6
        suffix = self.rate_unit

        for col in ["rx_data_bps", "rx_total_bps", "rx_trim_bps"]:
            new_col = col.replace("_bps", f"_{suffix}")
            df[new_col] = df[col] * factor

        return df

    @cached_property
    def _raw_sink_df(self) -> pd.DataFrame:
        """
        [基础数据] 解析原始 Goodput 日志 (Per Flow)。
        虽然这只是"翻译"，但它是后续聚合的基础。
        """
        if not self.log_path.exists():
            return pd.DataFrame()
        # 获取全量数据，不进行 ID 过滤
        return sink.parse_goodputs_from_file(self.log_path.as_posix())

    @cached_property
    def flow_goodput_df(self) -> pd.DataFrame:
        """
        [别名] 访问原始流级 Goodput 数据。
        """
        return self._raw_sink_df

    def _convert_rate(self, df: pd.DataFrame) -> pd.DataFrame:
        """根据配置自动添加带单位的 Rate 列"""
        if df.empty or "Rate" not in df.columns:
            return df

        # 原始 Rate 单位为 Bps
        col_name = f"Rate_{self.rate_unit}"
        if self.rate_unit == "Gbps":
            df[col_name] = df["Rate"] * 8 / 1e9
        elif self.rate_unit == "Mbps":
            df[col_name] = df["Rate"] * 8 / 1e6
        return df

    @cached_property
    def sink_goodput_df(self) -> pd.DataFrame:
        """
        [核心 Insight] 节点级接收吞吐量 (Per Sink Node Goodput)。

        价值：
        1. 直接反映每个 Server 的接收压力。
        2. 识别 Incast 场景下的 Victim (谁的吞吐量被压垮了)。
        3. 评估负载均衡 (是不是所有节点的接收速率都均匀)。
        """
        df = self._raw_sink_df
        if df.empty:
            return pd.DataFrame()

        # 1. 获取映射: {SinkNodeID -> [FlowID1, FlowID2...]}
        # idmap 已经帮我们做好了这个映射
        node_map = self.idmap.sink_id_to_flowIDs_map

        if not node_map:
            return pd.DataFrame()

        # 2. 调用 sink.py 的聚合逻辑
        # Returns: DataFrame [time, CAck, Rate, nodeID]
        agg_df = sink.aggregate_by_node_map(df, node_map)
        return self._convert_rate(agg_df)  # 自动注入 Rate_Gbps

    @cached_property
    def src_goodput_df(self) -> pd.DataFrame:
        """
        [扩展 Insight] 源端有效发送速率 (Per Source Node Goodput)。
        注意：这是基于 Sink 端的 ACK 计算的，代表"有效"传输速率，而非网卡发送速率。
        """
        df = self._raw_sink_df
        if df.empty:
            return pd.DataFrame()

        # 1. 获取映射: {SrcNodeID -> [FlowID1, FlowID2...]}
        node_map = self.idmap.src_id_to_flowIDs_map

        if not node_map:
            return pd.DataFrame()

        agg_df = sink.aggregate_by_node_map(df, node_map)
        return self._convert_rate(agg_df)  # 自动注入 Rate_Gbps

    @cached_property
    def total_goodput_df(self) -> pd.DataFrame:
        """
        [全局 Insight] 整个系统的总吞吐量随时间变化。
        """
        df = self._raw_sink_df
        if df.empty:
            return pd.DataFrame()

        # 聚合所有流 ID
        all_ids = df["ID"].unique().tolist()

        # 复用 aggregate_by_ids
        agg_df = sink.aggregate_by_ids(df, all_ids)
        return self._convert_rate(agg_df)  # 自动注入 Rate_Gbps

    # ==========================
    # Modified: 核心数据解析 (重构 Queue/Switch 分离)
    # ==========================

    @cached_property
    def _raw_sampling_df(self) -> pd.DataFrame:
        """
        [修改] 加载 Range, Overflow, Traffic 事件并合并。
        """
        if not self.log_path.exists():
            return pd.DataFrame()

        # 1. 解析所有类型的队列日志 (Range, Overflow, Traffic)
        df_range = queue.parse_sampling_events_from_file(self.log_path)
        df_overflow = queue.parse_overflow_events_from_file(self.log_path)  # 新增
        df_traffic = queue.parse_traffic_events_from_file(self.log_path)

        if df_range.empty:
            return pd.DataFrame()

        # 2. 合并 Overflow 数据 (Left Join on time, queue_id)
        if not df_overflow.empty:
            df = pd.merge(df_range, df_overflow, on=["time", "queue_id"], how="left")
        else:
            df = df_range
            # 填充默认值防止报错
            for col in ["last_dropped_bytes", "last_idled_bytes", "queue_buf_bytes"]:
                df[col] = 0.0

        # 3. 合并 Traffic 数据
        if not df_traffic.empty:
            df = pd.merge(df, df_traffic, on=["time", "queue_id"], how="left")
        else:
            for col in ["cum_arr_us", "cum_idle_us", "cum_drop_us"]:
                df[col] = 0.0

        return df

    def _compute_metrics(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        基于 DeepWiki Q&A 指导计算高阶队列指标。
        严格遵循 htsim 的物理含义：
        - cum_* 变量在 loggers.cpp 中是 'Service Time (Seconds)'
        - queue.py 解析时转为了 'Microseconds (us)'
        - time 是 'Seconds'
        """
        if df.empty:
            return df

        if self.idmap.data:
            df["name"] = df["queue_id"].map(self.idmap.data)

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

    # ==========================
    # Modified: 智能清洗逻辑 (DRY Refactoring)
    # ==========================

    def _clean_sampling_df(
        self, df: pd.DataFrame, value_col: str = "max_q", id_col: str = "queue_id"
    ) -> pd.DataFrame:
        """
        [内部通用] 清洗采样数据 (Queue, Switch 或 NIC)。
        逻辑：
        1. 剔除全程 value_col (如 max_q 或 rx_total) 均为 0 的 ID。
        2. 裁剪掉最后一次活跃之后的时间段 (Tail Trimming)。

        Args:
            df: 原始 DataFrame
            value_col: 用于判断活跃度的数值列名
            id_col: 用于分组的 ID 列名 (queue_id, nic_id 等)
        """
        if df.empty:
            return df

        # 确保 id_col 存在
        if id_col not in df.columns:
            return df

        # 1. 剔除“死对象” (全程无值)
        peaks = df.groupby(id_col)[value_col].max()
        active_ids = peaks[peaks > 0].index

        if len(active_ids) == 0:
            return pd.DataFrame(columns=df.columns)

        # 保留活跃 ID 的所有数据 (保留原始列，包括可能存在的 Name)
        df_active = df[df[id_col].isin(active_ids)].copy()

        # 2. 尾部裁剪 (Tail Trimming)
        # 找出所有活跃时刻 (value > 0)
        active_events = df_active[df_active[value_col] > 0]

        if active_events.empty:
            return pd.DataFrame(columns=df.columns)

        # 找出每个 ID 的“最后活跃时间”
        cutoff_times = active_events.groupby(id_col)["time"].max().reset_index()
        cutoff_times.rename(columns={"time": "cutoff_time"}, inplace=True)

        # 合并并过滤
        df_merged = df_active.merge(cutoff_times, on=id_col, how="left")
        # 保留 time <= cutoff_time 的行
        df_clean = df_merged[df_merged["time"] <= df_merged["cutoff_time"]]

        return df_clean.drop(columns=["cutoff_time"]).reset_index(drop=True)

    # ==========================
    # NIC Active Data
    # ==========================

    @cached_property
    def active_nic_df(self) -> pd.DataFrame:
        """
        [智能清洗] 获取“有效”的 NIC 数据。

        注意：nic_df 中的 nic_id 是 Source Node ID (模拟器内部 ID)，
        并非全局 LogID，因此不能关联 idmap 获取名称。
        """
        df = self.nic_df
        if df.empty:
            return df

        # 确定活跃指标列名 (自适应 rate_unit)
        target_col = f"rx_total_{self.rate_unit}"

        # 调用通用清洗逻辑，指定 ID 列为 nic_id
        return self._clean_sampling_df(df, value_col=target_col, id_col="nic_id")

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

    # ==========================
    # 5. 增强的拓扑筛选接口 (Topology Filtering)
    # ==========================

    def get_queues_by_type(self, link_type_enum) -> pd.DataFrame:
        """
        [高级筛选] 根据链路类型筛选队列数据。

        Args:
            link_type_enum: idmap.LinkType 枚举值 (e.g., idmap.LinkType.TOR_DOWN)

        Returns:
            筛选后的 pd.DataFrame (格式同 active_queue_df)

        Example:
            tor_down_df = result.get_queues_by_type(idmap.LinkType.TOR_DOWN)
        """
        # 1. 获取有效数据源
        df = self.active_queue_df
        if df.empty:
            return df

        # 2. 利用 IdMap 进行 ID 筛选
        # 注意：这里调用的是 idmap 实例的 filter_queueIDs 方法
        target_ids = set(self.idmap.filter_queueIDs(link_type_enum))

        if not target_ids:
            return pd.DataFrame(columns=df.columns)

        # 3. 返回过滤结果
        return df[df["queue_id"].isin(target_ids)].reset_index(drop=True)

    @property
    def tor_downlink_queues(self) -> pd.DataFrame:
        """[快捷属性] ToR -> Server 的下行队列 (Last Hop)"""
        return self.get_queues_by_type(idmap.LinkType.TOR_DOWN)

    @property
    def agg_downlink_queues(self) -> pd.DataFrame:
        """[快捷属性] Aggregation -> ToR 的下行队列"""
        return self.get_queues_by_type(idmap.LinkType.AGG_DOWN)

    @property
    def core_downlink_queues(self) -> pd.DataFrame:
        """[快捷属性] Core -> Aggregation 的下行队列"""
        return self.get_queues_by_type(idmap.LinkType.CORE_DOWN)

    @property
    def server_uplink_queues(self) -> pd.DataFrame:
        """[快捷属性] Server -> ToR 的上行队列 (Injection)"""
        return self.get_queues_by_type(idmap.LinkType.SERVER_UP)
