---
ctime: 2025-12-18 10:56:46
mtime: 2025-12-18 10:56:46
number headings: first-level 2, max 6, 1.1
---
# 📘 `ExperimentResult` 技术报告
这份报告提纲旨在为 `ExperimentResult` 类提供一个结构化的技术说明文档。它不仅涵盖了代码的静态结构，还详细描述了数据流转的动态逻辑，以便于 AI 伙伴快速理解上下文并精准定位问题。
## 1 📘 概述与核心定位 (Overview & Core Positioning)

`ExperimentResult` 是整个 `uet-htsim` 分析框架的**数据心脏**。它被定义为“单次子实验上下文（Single Sub-Experiment Context）”，其核心目标是将零散、复杂的二进制仿真日志抽象为结构化、具备拓扑语义的 Python 对象。

### 1.1 核心定位：全栈数据枢纽

`ExperimentResult` 扮演了仿真结果与分析逻辑之间的**中介者**角色。

- **屏蔽底层细节**：用户无需关心 `parse_output` 工具的命令行参数或正则表达式，直接通过属性访问（如 `.flow_df`）即可获得清洗后的数据。
    
- **一站式访问**：它集成了流（Flow）、网卡（NIC）、队列（Queue）、接收端（Sink）及交换机（Switch）等所有维度的仿真信息。
    
- **状态感知**：通过解析 `status.yaml`，它能感知该实验在批量测试中的变量取值（如特定的 `conns` 或 `linkspeed`）以及实验的运行状态。
    

### 1.2 设计原则：极致性能与易用性

为了平衡大规模批量实验带来的 I/O 压力与开发便捷性，该类遵循以下三大设计原则：

#### 1.2.1 延迟加载与缓存 (Lazy Loading & Caching)

- **按需解析**：利用 `@cached_property`，只有在代码显式访问某个数据帧（如 `res.queue_df`）时，才会触发磁盘 I/O 和复杂的解析计算。
    
- **持久化收益**：一旦解析完成，结果将缓存在内存中，后续重复访问几乎零延迟。
    

#### 1.2.2 拓扑感知与名称注入 (Topology Awareness)

- **语义映射**：仿真日志原始输出仅包含抽象数字 ID（Logged ID）。`ExperimentResult` 深度集成 `IdMap` 类，在构建 DataFrame 时自动将 ID 替换为具备拓扑含义的名称（如 `LS0->DST1`）。
    
- **位置敏感查询**：它支持基于网络角色的过滤，例如能自动识别哪些队列属于“最后一跳（Last Hop）”或“ToR 下行链路”。
    

#### 1.2.3 统一的数据接口规范

- **Pandas 导向**：所有核心指标均以 `pd.DataFrame` 格式导出，确保了与 `matplotlib`、`seaborn` 等数据科学工具链的无缝对接。
    
- **微分指标自动生成**：对于队列等累积量日志，它会自动计算时间窗口内的利用率、负载因子和丢包率，将“原始状态”转化为“性能指标”。
    

### 1.3 输入要求 (Input Requirements)

`ExperimentResult` 运行在特定的“黑盒”目录结构之上。要使该类功能完整，子实验目录必须包含以下核心文件：

|**文件名**|**属性映射**|**功能说明**|
|---|---|---|
|`output.log`|`log_path`|核心二进制日志，包含所有仿真事件。|
|`idmap.txt`|`idmap_path`|定义了 Logged ID 到物理拓扑名称的映射关系。|
|`status.yaml`|`status_vars`|记录实验的变量配置（变量名与取值）及成功状态。|
|`stdout.log`|`stdout_path`|模拟器的标准输出，用于补充流 ID 映射等辅助信息。|

### 1.4 快速上手示例 (Quick Start)
为了快速验证子实验数据的可用性，请参考以下典型调用流：
```python
from fileinfo import ExperimentResult

# 1. 初始化（自动发现目录并准备解析）
res = ExperimentResult("results/uec_incast_c128_q35")

# 2. 检查实验状态与可用数据
if res.is_success:
    print(f"可用指标: {res.available_metrics}") # 探测日志种类
    
    # 3. 获取核心分析数据帧
    fct_df = res.flow_df  # FCT 分布
    bottleneck_q = res.last_hop_queue_df  # 自动识别的最后一跳瓶颈队列
    
    # 4. 执行拓扑语义查询
    # 获取节点 0 发出的所有队列流量时序
    node0_out = res.get_node_queues(0, direction="out")
```

## 2 环境依赖与输入规范 (Input Specifications)

`ExperimentResult` 的正常运行高度依赖于一致的目录结构和特定格式的输入文件。该类设计为“子实验目录即对象”，即通过传入一个包含完整日志的文件夹路径来初始化数据上下文。

---

### 2.1 目录结构要求 (Directory Structure)

每个 `ExperimentResult` 实例对应一个独立的**子实验目录**。在典型的批量实验流中，这些目录通常位于 `results/` 下，按主实验名称及参数组合命名的子文件夹中。

- **路径解析**：类初始化时会解析传入路径。如果传入的是文件路径，它会自动定位到其所属的父目录。
    
- **上下文独立性**：每个目录被视为一个闭环的分析单元，包含了该次模拟运行的所有证据链。
    

---

### 2.2 核心文件清单 (Required Files)

要激活 `ExperimentResult` 的完整功能，子实验目录必须包含以下四个核心文件：

|**文件名**|**规范与格式**|**在类中的作用**|
|---|---|---|
|**`output.log`**|二进制格式，由 `Logfile` 类生成。|**核心数据源**。包含所有事件记录，需通过 `parse_output` 转化为 ASCII 进行解析。|
|**`idmap.txt`**|文本格式。每行以空格分隔：`ID Name`。|**语义映射表**。将日志中的 `Logged ID` 映射为物理组件名称（如 `LS0->DST1`）。|
|**`status.yaml`**|YAML 格式。|**元数据中心**。存储实验变量（`conns`, `nodes` 等）和运行状态（`success: True`）。|
|**`stdout.log`**|文本格式（模拟器控制台输出重定向）。|**辅助映射表**。用于通过正则匹配解析 `flowid` 与具体流名称的关联。|

---

### 2.3 环境与外部依赖 (Environment & Dependencies)

该组件并非孤立运行，它依赖于底层的解析工具和 Python 数据科学栈：

- **二进制解析器 (`parse_output`)**：必须预先编译完成。Python 层通过 `runner.py` 调用该二进制文件对 `output.log` 执行 `-filter` 操作。
    
- **Python 库依赖**：
    
    - **Pandas & Numpy**：用于构建和计算数据帧（DataFrame）。
        
    - **PyYAML**：用于解析 `status.yaml` 提取变量。
        
- **内部模块联动**：高度依赖 `parser` 文件夹下的协议解析脚本（如 `flow.py`, `nic.py`, `queue.py`, `sink.py`）来处理特定的 ASCII 流。
    

---

### 2.4 数据单位与逻辑转换规范 (Logic & Unit Conventions)

为了确保分析的一致性，`ExperimentResult` 在输入处理阶段遵循以下约定：

- **速率单位 (Rate Unit)**：初始化时可指定 `rate_unit`（默认为 "Gbps"）。类会自动将原始 Bps（Bytes per second）转换为目标单位。
    
- **时间对齐 (Time Alignment)**：
    
    - 原始日志时间通常为秒（Seconds）。
        
    - 在绘图视图层（`AutoVisualizer`），时间会被统一转换为微秒（us）。
        
    - 解析 `flow_df` 时，FCT 会转换为纳秒（ns）以保证精度。
        
- **ID 辨析规范**：
    
    - **id (小写)**：指模拟运行中的逻辑 ID（如 `flowid 24`）。
        
    - **ID (大写)**：指日志记录中的 `Logged ID`，即 `idmap.txt` 中的 Key。
        
这份 API 参考手册详细列出了 `ExperimentResult` 类提供的公开接口、属性及其返回的数据结构。它是开发者和 AI 助手进行数据提取与性能分析的核心指南。

---

## 3 API 参考手册 (API Reference)

### 3.1 元数据与基础属性 (Meta & Basic Attributes)

这些属性提供了实验的背景信息和可用性检查。

| **属性/方法**                                 | **类型**      | **说明**                                                   |
| ----------------------------------------- | ----------- | -------------------------------------------------------- |
| `status_vars`                             | `Dict`      | 解析 `status.yaml` 得到的变量字典（如 `conns`, `nodes` 等）。          |
| `get_status_vars(key, default)`           | `Method`    | 安全获取实验变量的值。                                              |
| `idmap`                                   | `IdMap`     | 关联的 ID 映射对象，用于 ID 与名称转换及拓扑查询。                            |
| `available_metrics`                       | `List[str]` | **(动态探测)** 返回当前日志中包含的有效数据类别（如 `flow`, `queue`, `nic` 等）。 |
| `is_success`                              | `bool`      | 根据 `status.yaml` 返回该子实验是否运行成功。                           |
| `params`                                  | `Dict`      | 整合后的实验参数中心。优先级为 `variables` (波动的变量) > `command` (命令行参数)  |
| `get_param(key, default, type_func)`      | `Method`    | 安全获取参数并执行类型转换（如将字符串转换为 `float`）的统一接口                     |
| `get_param_list(key, default, type_func)` | `Method`    | 支持解析多值参数（如 `-pfc_thresholds 20 80` 或 `-ecn`），返回转换后的列表    |

---

### 3.2 核心数据帧属性 (Core DataFrame Properties)

所有数据帧均采用延迟加载机制，且自动注入了 `name` 列（基于 `idmap.txt`）。

#### 3.2.1 流与网卡数据

- **`flow_df`**: 包含所有已完成流的统计信息。
    - **关键列**: `flow_id`, `src_id`, `start_time`, `finish_time`, `size_bytes`, `fct_ns`。
- **`nic_df`**: 记录网卡端口的吞吐量。
    - **关键列**: `time`, `nic_id`, `rx_data_Gbps`, `rx_total_Gbps`, `rx_trim_Gbps`。
- **`flow_slowdown_df`**：包含 FCT Slowdown (膨胀率) 指标的数据帧。
    - **关键列**：`ideal_fct_ns` (理论最小完成时间), `slowdown` (实际/理想比例)。
- **`traffic_df`**：全量数据包事件轨迹，自动注入位置名称。
    - **关键列**：`time`, `location_id`, `name` (拓扑位置), `event` (DEPART/ARRIVE/DROP/TRIM), `flow_id`, `pkt_id`。
- **`cwnd_df`**:  从 `stdout.log` 提取的拥塞窗口演变轨迹。 
	- **数据源**: 依赖 `-debug` 参数开启后的模拟器标准输出。 
	- **关键列**: `time` (s), `flow_name`, `cwnd` (Bytes), `in_flight` (Bytes)。

#### 3.2.2 吞吐量 (Goodput) 数据

- **`sink_goodput_df`**: 按**接收节点**聚合的有效吞吐量时序。
    
- **`src_goodput_df`**: 按**发送节点**聚合的有效吞吐量时序。
    
- **`total_goodput_df`**: 全网总有效吞吐量时序。
    
    - **共有列**: `time`, `nodeID` (如果是聚合), `Rate_Gbps`, `CAck`。
        

#### 3.2.3 队列与交换机数据

- **`queue_df`**: 包含端口队列的深度及微分性能指标。
    
    - **关键列**: `time`, `queue_id`, `name`, `last_q`, `min_q`, `max_q`, `utilization`, `load_factor`, `drop_ratio`。
        
- **`switch_df`**: 记录交换机整机的共享缓存占用情况。
    
    - **关键列**: `time`, `queue_id`, `last_q`, `min_q`, `max_q`。
        

---

### 3.3 拓扑语义与筛选接口 (Topological Query Interfaces)

这些接口基于网络拓扑角色直接返回特定的数据集，简化了分析流程。

|**属性/方法**|**返回类型**|**说明**|
|---|---|---|
|`active_queue_df`|`DataFrame`|剔除流量为 0 的静默队列，并裁剪掉仿真结束后的空白期。|
|`tor_downlink_queues`|`DataFrame`|仅返回 ToR 交换机到服务器（下行链路）方向的队列数据。|
|`last_hop_queue_df`|`DataFrame`|根据流量矩阵自动识别并返回“最后一跳”活跃队列的数据。|
|`get_node_queues(id, dir)`|`DataFrame`|**(语义增强)** 获取指定节点（如 `node_id=0`）发出 (`out`) 或进入 (`in`) 的所有队列数据。|
|`get_queues_by_type(type)`|`DataFrame`|按链路类型（如 `LinkType.AGG_DOWN`）筛选队列。|

---

### 3.4 辅助工具方法 (Helper Methods)

| **方法**                        | **说明**                                |
| ----------------------------- | ------------------------------------- |
| `get_name_by_LogID(ID)`       | 将日志中的大写 `ID` 转换为 `idmap.txt` 中的名称。    |
| `get_flowid_by_name(name)`    | 从 `stdout.log` 中检索特定名称对应的逻辑 `flowid`。 |
| `get_queue_events_df(id)`     | 获取特定队列的原始事件流（入队、出队、丢包等）。              |
| `get_flowid_by_logid(log_id)` | 级联查询：先由 LogID 获名，再由名获 flowid。         |



### 3.5 核心列定义与指标计算公式

为了确保数据解读的准确性，以下是关键衍生指标的计算逻辑：

1. utilization (利用率 %):
    
    $$100.0 \times \left(1.0 - \frac{\text{diff}(\text{cum\_idle\_us})}{\text{diff}(\text{time\_us})}\right)$$
    
    反映链路在采样窗口内的忙碌程度。
    
2. load_factor (负载因子):
    
    $$\frac{\text{diff}(\text{cum\_arr\_us})}{\text{diff}(\text{time\_us})}$$
    
    反映单位时间内到达队列的工作量强度。
    
3. drop_ratio (丢包率 %):
    
    $$100.0 \times \left(\frac{\text{diff}(\text{cum\_drop\_us})}{\text{diff}(\text{cum\_arr\_us})}\right)$$
    
    反映该时段内因拥塞导致的工作量损失比例。
    


### 3.6 性能诊断指标组合 (Diagnosis Patterns)
利用 `ExperimentResult` 计算出的微分指标组合，可以快速定位网络中的物理现象：

| **指标组合表现**                            | **物理场景诊断**                       | **调优方向**                      |
| ------------------------------------- | -------------------------------- | ----------------------------- |
| **高 $Load Factor$ + 低 $Utilization$** | **微突发 (Micro-burst)**            | 增加 BDP 容忍度或调整队列阈值。            |
| **高 $Utilization$ + $MinQ > 0$**      | **持续拥塞 (Persistent Congestion)** | 检查路由负载均衡（ECMP）或降低源端速率。        |
| **高 $Drop Ratio$ + $LastQ$ 剧烈波动**     | **拥塞控制 (CC) 振荡**                 | 调整 CC 算法的增益系数（如 Swift 的 $g$）。 |
| **高 $rx\_trim\_Gbps$ (仅限 UEC)**       | **Packet Trimming 频繁触发**         | 优化接收端 Pacer 速率或检查 PCIe 反压。    |

**💡 使用提示**: 在 AI 交互中，您可以直接引用这些列名进行分析。例如：“请基于 `res.queue_df` 找出 `utilization` 长期处于 100% 且 `drop_ratio` 最高的 `queue_id`。”



## 4 数据处理逻辑深度解析 (Data Processing Internals)

`ExperimentResult` 的核心价值在于其内部复杂的数据处理流水线。它将原本离散、累积且难以阅读的二进制事件日志，转化为具有高时延精度和物理语义的性能指标。以下是该处理逻辑的深度解构：

---

### 4.1 原始日志解析流水线 (The Parsing Pipeline)

数据从产生到进入 DataFrame 经历四个阶段：

1. **二进制提取**：模拟器生成的 `output.log` 采用紧凑的二进制格式以节省磁盘 I/O，每条记录固定占用 44 字节。
    
2. **ASCII 转换与过滤**：通过 `runner.run_parse` 调用编译好的 `parse_output` 二进制工具。该工具通过 `-filter` 参数（如 `QUEUE_RECORD` 或 `NIC_EVENT`）筛选出特定类型的事件并转化为 ASCII 文本流。
    
3. **正则结构化**：Python 层的解析模块（如 `nic.py`, `flow.py`）利用正则表达式从文本流中提取时间戳、ID 和负载值（Val1/2/3）。
    
4. **高精度对齐合并**：在 `_raw_sampling_df` 过程中，系统将 Range（队列极值）、Overflow（丢包信息）和 Traffic（流量统计）三类数据通过纳秒级整数键（`_time_ns`）进行强制对齐合并，确保多维指标在同一时间轴上。
	1. **对齐机制更新**：在合并 Range, Overflow 和 Traffic 数据时，系统采用纳秒级整数键 `_time_ns`（计算方式为 `(time * 1e9 + 0.5).astype(np.int64)`），有效解决了浮点数精度差值导致的对齐失败问题
	    

---

### 4.2 名称注入与拓扑关联 (Name Injection)

为了让数据具备可读性，系统执行 `_inject_name` 逻辑：

- **IdMap 覆盖**：解析器首先从 `idmap.txt` 加载 ID 映射字典。
    
- **优先映射**：在构建 DataFrame 时，通过映射表将 `queue_id` 或 `traffic_id` 转换为易读名称（如 `LS0->DST1`）。
    
- **语义补全**：如果原始日志中已包含名称，系统会使用 `idmap` 中的官方映射执行 `combine_first`，确保拓扑命名的一致性。
    

---

### 4.3 高级微分指标计算 (Advanced Metric Computation)

`ExperimentResult` 并不直接展示原始累积量，而是通过 `_compute_traffic_metrics` 计算采样窗口内的微分指标：

- **链路利用率 (Utilization %)**：
    
    - **原理**：基于 `_cum_idle_us`（从仿真开始到现在的总空闲时间）。
        
    - **公式**：$100.0 \times (1.0 - (\Delta \text{cum\_idle\_us} / \Delta \text{time\_us}))$。
        
- **到达强度 (Load Factor)**：
    
    - **原理**：衡量单位时间内到达队列的工作量（Demand），无论最终是否被丢弃。
        
    - **公式**：$\Delta \text{cum\_arr\_us} / \Delta \text{time\_us}$。
        
- **丢包比例 (Drop Ratio %)**：
    
    - **公式**：$100.0 \times (\Delta \text{cum\_drop\_us} / \Delta \text{cum\_arr\_us})$。
- **Slowdown (FCT 膨胀率)**：
	
	- **计算公式**：$Slowdown = \frac{实际 FCT}{理想传输时间}$。
	    
	- **理想时间逻辑**：由“串行化延迟”与“传播时延”组成，其中传播时延会根据 `params` 中的 `tiers` 自动识别拓扑跳数（3 层为 6 跳，2 层为 4 跳）。
	    
	- **物理意义**：消除流大小差异，直接量化网络拥塞导致的延迟惩罚，Slowdown 越接近 1.0 代表网络性能越接近理想无损状态。

---

### 4.4 智能清洗与边缘处理 (Intelligent Cleaning)

为了保证绘图和分析的质量，数据在暴露前会经过 `_clean_inactive_series` 环节：

- **剔除死对象**：自动识别最大值始终为 0 的队列或网卡，并将其从 DataFrame 中完全移除。
    
- **尾部自动裁剪**：计算每个对象最后一次活跃（值 > 0）的时间点，裁剪掉仿真结束后的静默空档期，防止长尾数据干扰统计均值。
    
- **第一行补偿**：Pandas 的 `diff()` 会使第一行产生 NaN。系统假设初始状态为 0，将第一行的 Delta 值填充为原始当前值，确保时序完整性。
    
- **噪声过滤**：针对浮点数精度产生的极小噪声（如 $1e^{-16}$），系统设置了 $1e^{-6}$ 的门限，低于此值的部分会自动归零。
- **首行补偿 (First-Row Compensation)**：针对 `diff()` 产生的第一个 `NaN` 值，系统通过 `fillna(df[col])` 将其填充为当前累积值，确保在 FCT 爆发初期的关键数据不会丢失。
- **噪声过滤 (Noise Thresholding)**：强制将低于 $1e^{-6}$ 的微分结果归零，消除浮点数计算产生的微小伪影。

---

### 4.5 数据特征与洞察

通过上述处理逻辑，`ExperimentResult` 能够揭示深层物理现象：

|**现象**|**数据表现**|**洞察**|
|---|---|---|
|**微突发 (Micro-burst)**|`last_q` 很低，但 `max_q` 极高|存在极短时间内的突发流量冲击。|
|**持续拥塞 (Persistent)**|`min_q` 持续大于 0|链路在整个采样周期内从未排空，处于饱和瓶颈状态。|
|**Buffer 抖动**|同一周期内 `NumDrops` 和 `NumIdle` 均大于 0|缓冲区配置过小或 CC 算法发生剧烈振荡。|


## 5 常见日志组件映射 (Log Component Mapping)

在 `uet-htsim` 仿真框架中，日志功能并非默认全量开启，而是通过命令行参数（CLI Flags）进行按需激活。`ExperimentResult` 的核心逻辑是将这些命令行标志、模拟器内部的 Logger 类型以及最终生成的 DataFrame 进行一一映射。

---

### 5.1 核心映射全景表 (Core Mapping Table)

下表展示了从“开启日志”到“获取数据”的完整路径：

|**命令行参数 (Flag)**|**模拟器内部 Logger 类型**|**ExperimentResult 属性**|**数据用途与核心指标**|
|---|---|---|---|
|**`-log flow_events`**|`FlowEventLoggerSimple`|**`flow_df`**|**FCT 分析**：流启动/结束时间、完成时延（FCT）。|
|**`-log nic`**|`NicLoggerSampling`|**`nic_df`**|**网卡负载**：Data 速率、Total 速率、Trim 速率。|
|**`-log queue`** / **`-log tor_downqueue`**|`QueueLoggerSampling`|**`queue_df`**|**队列动态**：Max/Min/Last 队长、利用率、丢包率。|
|**`-log sink`**|`UecSinkLoggerSampling` (等)|**`sink_goodput_df`**|**有效吞吐**：节点级别的 Goodput 速率与确认字节数。|
|**`-log switch`**|`MultiQueueLoggerSampling`|**`switch_df`**|**交换机压力**：整机共享缓存占用情况。|
|**`-log queue_usage`**|`QueueLoggerEmpty`|**`queue_usage_df`**|**极简监控**：ASCII 格式输出的链路利用率统计。|
|**`-log traffic`**|`TrafficLoggerSimple`|**`traffic_df`** (需扩展)|**源端统计**：流量生成端的原始数据发送事件。|

---

### 5.2 队列日志组件的深度映射

由于队列是网络分析的核心，`htsim` 针对不同需求提供了四种 Logger 实现，它们在 `ExperimentResult` 中有不同的体现：

1. **`LOGGER_SAMPLING` (标准模式)**：
    
    - **触发参数**：`-log queue` 或 `-log tor_downqueue`。
        
    - **处理逻辑**：每隔固定周期（如 10μs）记录一次统计极值。
        
    - **对应 DataFrame**：`queue_df`。
        
2. **`LOGGER_SIMPLE` (全量事件模式)**：
    
    - **触发参数**：通常需要修改代码指定为 `LOGGER_SIMPLE`。
        
    - **处理逻辑**：记录每一次入队、出队、丢包或裁剪的原子操作。
        
    - **对应方法**：`get_queue_events_df(id)`。
        
3. **`MULTIQUEUE_SAMPLING` (交换机聚合模式)**：
    
    - **触发参数**：`-log switch`。
        
    - **处理逻辑**：聚合交换机下所有端口的缓存占用。
        
    - **对应 DataFrame**：`switch_df`。
        
4. **`LOGGER_EMPTY` (ASCII 监控模式)**：
    
    - **触发参数**：`-log queue_usage`。
        
    - **处理逻辑**：直接向标准输出打印文本，不进入二进制日志。
        
    - **对应 DataFrame**：`queue_usage_df`。
        

---

### 5.3 二进制事件码映射 (Event ID Mapping)

在 `output.log` 的原始记录中，`Ev` 字段的数值决定了数据的语义含义：

| **数据类型 (Type)**        | **事件码 (Ev Code)**      | **含义**                   | **解析关联**   |
| ---------------------- | ---------------------- | ------------------------ | ---------- |
| **`QUEUE_APPROX`** (5) | `QUEUE_RANGE` (500)    | 记录周期内的 Last/Min/Max 队长。  | `queue.py` |
| **`QUEUE_APPROX`** (5) | `QUEUE_OVERFLOW` (501) | 记录丢包量、空闲量及总容量。           | `queue.py` |
| **`FLOW_EVENT`** (100) | `START` (0)            | 流传输开始。                   | `flow.py`  |
| **`FLOW_EVENT`** (100) | `FINISH` (1)           | 流传输结束并完成 FCT 计算。         | `flow.py`  |
| **`NIC_EVENT`** (101)  | `NIC_RECORD` (0)       | 记录网卡 Data/Total/Trim 速率。 | `nic.py`   |

---

### 5.4 ID 映射机制与 `idmap.txt`

`ExperimentResult` 依赖 `idmap` 模块完成从物理实体到日志 ID 的“最后一公里”映射：

- **Source/Sink ID**：对应 `*_sink_<src>_<dest>` 格式，用于聚合 Goodput。
    
- **Queue ID**：通过正则匹配（如 `LS\d+->DST\d+`）识别链路类型，从而支持 `tor_downlink_queues` 等高级属性。

**💡 诊断提示：** 如果您在 `ExperimentResult` 中发现某个 DataFrame（如 `nic_df`）为空，请首先检查模拟器的启动命令行中是否包含对应的 `-log` 标志（例如 `-log nic`）。如果没有这些标志，二进制日志中将不会包含对应的事件记录。

## 6 故障排查与已知限制 (Troubleshooting & Constraints)

在利用 `ExperimentResult` 进行深度分析时，理解其底层解析边界和仿真物理限制至关重要。本章节列出了常见的故障场景、背后的原因以及当前架构的已知局限。

---

### 6.1 数据完整性与缺失排查 (Data Integrity)

当发现 `ExperimentResult` 中的某些 DataFrame 为空或 `available_metrics` 缺少预期项时，请按以下顺序排查：

- **日志开关未开启**：最常见的原因是模拟器启动命令行中缺少对应的 `-log` 标志（例如：若无 `-log nic`，则 `nic_df` 为空）。
    
- **对象未注册 Logged**：如果二进制日志中有数据但 `name` 列全为 `NaN`，说明该组件（如某个特定 Queue）在 C++ 代码中未被添加至 `Logged` 列表，导致 `idmap.txt` 缺失该 ID 映射。
    
- **流量极小被过滤**：`ExperimentResult` 会自动剔除最大值始终为 0 的静默对象（Inactive Series）。如果一个流没有产生任何数据包，它将不会出现在 `active_nic_df` 或 `active_queue_df` 中。
    
- **FCT 计算失败**：只有处于 `Finished` 状态（所有消息包均被 ACK）的流才会进入 `flow_df`；如果发生死锁，Message 将卡在 `SentLast` 状态，导致该流在结果中“消失”。
    

---

### 6.2 ID 映射与语义错误 (ID Mapping & Semantics)

- **大小写 ID 混淆**：
    
    - **id (小写)**：模拟器内部逻辑 ID。
        
    - **ID (大写)**：日志记录使用的 `Logged ID`。若映射逻辑出错，请检查 `idmap.py` 中的解析规则。
        
- **拓扑角色识别失败**：`tor_downlink_queues` 等属性依赖特定的命名规范（如 `LS\d+->DST\d+`）。如果自定义了拓扑命名且未更新 `idmap.py` 中的正则表达式，这些属性将返回空值。
    

---

### 6.3 数值计算与精度限制 (Numerical Constraints)

- **微分指标的起始点偏差**：由于 `diff()` 计算会产生 `NaN`，系统假设 $t=0$ 时刻状态为 0，将第一行的差分值填充为原始值（即 $Delta = Value - 0$）。
    
- **浮点数噪声过滤**：为了防止微分计算产生极小的浮点数碎屑（如 $1e^{-16}$），系统强制将低于 $1e^{-6}$ 的结果归零。在分析极低速率流量时需注意此门限。
    
- **单位转换溢出**：解析流数据时，时间单位从秒（s）转换为纳秒（ns）以保证 FCT 精度。在极长周期的仿真中，需注意大整数溢出风险。
- **参数合并优先级限制**：在批量实验中，若某个参数未出现在 `variables` 列表中，则系统会自动退回到从 `command` 字符串中提取默认值。这要求模拟器的命令行格式必须严格遵循 `-key value` 结构，且多值参数需通过空格分隔

---

### 6.4 仿真器物理机制限制 (Simulator Physical Limits)

- **重组缓冲区崩溃点**：`ModularVector` 维护的接收窗口上限为 16384 个包（约 65MiB），如果序列号空隙（Gap）超过此限制，仿真器会触发 `abort()` 崩溃。
    
- **PCIe 反压误判**：最后一跳（Last Hop）的丢包（Trim）通常由接收端 PCIe 反压引起，而非网络核心拥塞。在分析 RICC 算法时，必须通过 `last_hop` 标志位区分这两种截然不同的物理现象。
    
- **队列日志歧义**：目前 `-log tor_downqueue` 和 `-log tor_upqueue` 在底层均映射为 `LOGGER_SAMPLING`，在 `ExperimentResult` 中主要通过 `idmap` 筛选名称来区分，而非通过日志事件类型区分。
    

---

### 6.5 性能与 I/O 警告 (Performance Warnings)

- **二进制解析开销**：对于包含数百万条记录的 `output.log`，首次访问 `queue_df` 或 `flow_df` 可能需要数秒至数十秒的解析时间。
    
- **内存占用**：由于采用 `cached_property`，所有解析后的数据都会常驻内存。在处理超大规模子实验时，请注意监控内存占用，必要时手动销毁实例以释放空间。


### 6.6 数据持久化与分析优化 (Optimization Advice)
由于 `ExperimentResult` 的初始化涉及昂贵的二进制解析过程：

- **内存管理**：解析后的数据通过 `@cached_property` 驻留在内存中。 在处理大规模批量实验时，建议分析完一个子实验后显式销毁实例，以释放内存。
    
- **缓存建议**：对于频繁访问的大型数据帧（如 `queue_df`），建议在首次加载后使用 `res.queue_df.to_parquet("cache.parquet")` 进行本地持久化。 这样在后续分析中可跳过 `parse_output` 工具的调用，提速 10-50 倍。

💡 GTD 验证建议：

若遇到无法解释的数据异常，请先调用 res.available_metrics 查看实质解析出的组件，并检查 idmap_path 指向的文件内容是否完整。

