---
ctime: 2025-12-18 11:26:31
mtime: 2025-12-18 11:26:31
number headings:
  - first-level 2
---
# 📘 `AutoVisualizer` 技术报告提纲

## 1 概述与设计理念 (Overview & Design Philosophy)

`AutoVisualizer` 是位于 `autoreport.py` 中的自动可视化引擎。它的核心定位是作为 `ExperimentResult` 的**专用展示层**，旨在将复杂的仿真数据快速转化为可读性强的图形化报告。

---

### 1.1 核心定位：基于“薄视图”的可视化引擎 (Thin View Architecture)

`AutoVisualizer` 的设计核心在于**“薄”**。它与底层数据处理逻辑保持了严格的解耦：

- **数据隔离**：它本身不参与任何核心指标（如利用率、吞吐量）的计算，而是完全信任并读取 `ExperimentResult` 已经处理好的 DataFrame。
    
- **职责单一**：其唯一的职责是负责**坐标轴格式化、时间单位对齐及图表布局**。
    
- **依赖注入**：通过在初始化时传入一个 `ExperimentResult` 实例，它获得了对单次实验所有维度数据的访问权。
    

---

### 1.2 三大设计原则

#### 1.2.1 信任数据层 (Trust the Data Layer)

`AutoVisualizer` 默认 `ExperimentResult` 已经完成了最繁重的数据清洗和差分计算。

- 它直接调用 `result.rate_col`（如 `Rate_Gbps`）进行绘图，确保了展示的数据与分析逻辑中的数据完全一致。
    
- 这种设计避免了在绘图代码中重复实现计算公式，降低了维护成本。
    

#### 1.2.2 日志状态感知 (Log-Awareness)

由于仿真时开启的日志选项（`-log` 标志）决定了数据的可用性，`AutoVisualizer` 具备智能探测功能：

- **按需绘图**：它会检查 `status.yaml` 中的 `enabled_logs` 集合。
    
- **自动筛选**：通过 `_get_active_plotters` 接口，只有当实验确实记录了对应日志（如开启了 `-log nic`）时，才会激活相关的绘图函数，避免生成空图表或报错。
    

#### 1.2.3 专注表现层优化 (Presentation-Centric)

它负责处理仿真原始数据与人类直觉之间的转换细节：

- **时间转换**：将仿真中以秒（s）为单位的时间轴统一转换为**微秒（us）**展示，更符合数据中心亚毫秒级分析的需求。
    
- **智能缩放**：内置 `_fmt_bytes` 和 `_fmt_plain` 格式化器，自动根据数值大小切换字节单位（B/KB/MB/GB），并强制坐标轴拒绝科学计数法。
    
- **异常识别**：内置了特征提取逻辑（如掉速点探测），用于在“双视图”模板中自动高亮表现异常的流。
    

---

### 1.3 多模态执行策略

`AutoVisualizer` 支持两种主流的科研使用场景：

- **交互模式 (`show`)**：专门为 Jupyter Notebook 优化。利用 `IPython.display` 输出 Markdown 标题和内联图表，方便研究者在实验过程中进行快速探索。
    
- **批处理模式 (`save`)**：针对大规模批量实验。一键将所有相关图表保存为高分辨率 PNG 文件，并自动生成标准化的文件名（如 `system_total_goodput.png`）。
    
## 2 核心工作流 (Core Workflow)

`AutoVisualizer` 的工作流程是一个从数据感知到图形渲染的线性闭环。它确保了可视化输出既能反映实验的真实配置，又能符合研究者的直观分析习惯。

---

### 2.1 初始化与上下文绑定 (Initialization & Context Binding)

工作流起始于对 `ExperimentResult` 实例的注入。

- **依赖注入**：在初始化时，`AutoVisualizer` 将传入的 `ExperimentResult` 对象绑定到本地 `self.result`。
    
- **单位感知**：自动从数据层获取速率单位（如 "Gbps"），并预设对应的速率列名（如 `Rate_Gbps`），为后续绘图提供统一的轴标签依据。
    

### 2.2 日志状态探测与动态发现 (Log Sensing & Discovery)

为了避免在缺失数据的情况下尝试绘图，`AutoVisualizer` 执行一套动态发现机制：

- **解析日志配置**：通过 `ExperimentResult` 访问 `status.yaml`，解析出该实验中被激活的日志集合（`enabled_logs`）。
    
- **绘图器筛选**：在 `_get_active_plotters` 方法中，系统将预设的绘图函数（plotters）与已启用的日志进行交叉比对：
    
    - 若 `flow_events` 已启用，激活 FCT 相关图表。
        
    - 若 `sink` 已启用，激活 Goodput 相关图表。
        
    - 若 `nic` 或 `queue` 相关标志位存在，激活组件级动态图表。
        

### 2.3 视图级单位对齐与格式化 (View-Level Preparation)

在正式渲染前，数据会经过一层“显示优化”处理：

- **时间轴转换**：通过 `_to_us` 辅助函数，将 DataFrame 中的时间列从秒（s）统一转换为微秒（us），以适应数据中心网络亚毫秒级的分析粒度。
    
- **智能格式化器注册**：注册 `_fmt_plain`（拒绝科学计数法）和 `_fmt_bytes`（自动转换 B/KB/MB/GB）等格式化工具，确保坐标轴刻度易于阅读。
    

### 2.4 多模态渲染与输出 (Execution & Output)

#### 2.4.1 交互式探索模式 (`show`)
- **引导式阅读**: 按照预设的 `REPORT_PLAN`（Phase 1-5）顺序展示。
- **逻辑注入**: 每一阶段自动打印“思考重点” Markdown 标题，辅助科研分析。

#### 2.4.2 自动化批处理模式 (`save`)
- **强制对齐**: 文件名采用 `0x-y_title.png` 格式（如 `04-1_congestion_control_diagnostic.png`），确保按逻辑顺序排列。
- **自动索引**: 同步生成 `README.md` 导读文件，包含所有阶段的引导问题与图表对应关系。
💡 诊断提示：

如果在生成报告时发现某些预期的图表缺失，核心工作流的第一步排查点应是 _get_active_plotters 的过滤逻辑，确认 status.yaml 中是否准确记录了对应的 enabled_logs。


## 3 可视化矩阵 (Plotting Matrix)

`AutoVisualizer` 的可视化矩阵将仿真数据划分为四个核心维度，通过多层级的图表组合，实现从全网宏观态势到单个流异常行为的深度剖析。

---

### 3.1 流级别分析 (Flow Level)

该维度主要用于评估传输协议的可靠性和整体效率。

- **Flow Completion Time (CDF)**：
    
    - **核心功能**：展示流完成时间（FCT）的累积分布函数。
        
    - **表现形式**：采用对数 X 轴，自动计算并标注 **P99 尾部延迟**，帮助识别长尾效应。
        
    - **物理意义**：反映在当前拥塞控制算法下，大部分流是否能在预期时间内完成传输。
        
- **Flow Size vs FCT (Scatter)**：
    
    - **核心功能**：展示流大小与 FCT 的相关性散点图。
        
    - **表现形式**：双对数坐标轴，X 轴为字节单位，Y 轴为纯数字微秒。
        
    - **物理意义**：用于验证短流是否受到了长流的排队干扰（即 Incast 场景下的公平性问题）。
- **Flow Slowdown CDF**：
	
	- **核心功能**：展示流受拥塞影响的真实“膨胀率”（实际 FCT / 理想 FCT）。
	    
	- **物理意义**：通过归一化消除流大小（Flow Size）对时延统计的干扰，是评估拥塞控制算法公平性的终极指标。
	    
	- **表现形式**：对数 X 轴，自动标注中位数和 P99 Slowdown 值。

---

### 3.2 吞吐量时序分析 (Goodput Level)

这是 `AutoVisualizer` 最复杂的模块，利用“双视图模板”同时展示宏观趋势与微观异常。

#### 3.2.1 基础吞吐量视图

- **System Total Goodput**：展示全网总有效吞吐量，反映核心链路的利用率。
    
- **Aggregated Goodput**：按发送节点（Src）或接收节点（Sink）聚合的吞吐量，用于定位热点节点。
    

#### 3.2.2 双视图高亮模式 (Dual-View Template)

为了在成百上千条流中快速定位问题，该模块将画布一分为二：

1. **视图 A：宏观分布 (Macro Distribution)**：
    
    - 绘制**中位数（Median）**曲线，并填充 **10% 至 90% 分位数带**。
        
    - **价值**：直观展示流量的整体波动范围和稳定性。
        
2. **视图 B：异常凸显 (Outliers & Anomalies)**：
    
    - **背景**：所有流以浅灰色细线背景展示。
        
    - **高亮**：基于智能特征提取，自动筛选并高亮三类流：
        
        - **最慢流 (Slowest)**：FCT 掉速点最晚的前 3 条流（红色）。
            
        - **不稳定流 (Unstable)**：速率标准差（波动率）最大的前 2 条流（橙色）。
            
        - **幸存流 (Survivor)**：在仿真末期仍有高活跃度的前 2 条流（蓝色）。
            

---

### 3.3 网络组件动态 (NIC & Queue)

该维度深入物理层，揭示拥塞发生的直接诱因。

- **NIC Traffic Breakdown**：
    
    - **表现形式**：堆叠面积图（Stackplot）。
        
    - **内容**：将网卡流量分为 **Valid Data**（有效数据）与 **Trimmed/Dropped**（被裁剪或丢弃的部分）。
        
    - **价值**：量化 UEC 等协议中 Packet Trimming 机制的开销。
        
- **Last-Hop Queue Dynamics**：
    
    - **内容**：展示“最后一跳”关键队列的时序深度。
        
    - **表现形式**：绘制 **MaxQ** 曲线，并填充 **MinQ 到 MaxQ 的包络线**。
        
    - **价值**：包络线的宽度直接反映了**微突发（Micro-burst）**的剧烈程度。
        
- **Switch Shared Buffer**：
    
    - **内容**：展示交换机整机缓存的 Top 3 占用情况，用于分析共享缓存溢出风险。
        

---

### 3.4 矩阵逻辑总结

|**监控维度**|**核心图表**|**关键指标 (Metrics)**|**日志依赖**|
|---|---|---|---|
|**流 (Flow)**|CDF / Scatter|FCT, $P99$, Size|`flow_events`|
|**吞吐 (Goodput)**|Dual-View Lineplot|$Rate_{Gbps}$, Volatility|`sink`|
|**组件 (Device)**|NIC Stack / Queue Line|Utilization, $MaxQ$, Trim Rate|`nic`, `queue`|

### 3.5 高级诊断视图 (Advanced Diagnostic Views)

- **Traffic Event Spatial Distribution (Heatmap)**：
    
    - **核心功能**：结合包轨迹与队列水位，定位全网拥塞爆发点。
        
    - **表现形式**：
        
        - **顶部面板**：拥塞强度直方图（Congestion Intensity），量化单位时间内 TRIM/DROP 事件的爆发密度。
            
        - **底部面板**：空间分布散点图（带抖动处理），并在热点位置自动叠加蓝色的队列深度（MaxQ/MinQ）曲线。
            
- **Bottleneck Correlation Analysis**：
    
    - **核心功能**：通过“三位一体”对齐布局，实锤拥塞根因。
        
    - **表现形式**：三面板共享时间轴，分别展示队列微分指标（利用率/负载因子）、NIC 吞吐速率（有效速率/裁剪速率）以及原始报文事件。
        
    - **诊断价值**：用于区分“网络侧 CC 算法响应慢”与“接收端 PCIe 反压瓶颈”。

### 3.6 高级诊断视图 (RICC 核心)
- **Congestion Control Diagnostic**:
    - **核心功能**: 将 CWND、在途字节（In-flight）、瓶颈队列深度、以及报文事件（TRIM/DROP）对齐在同一微秒级时间轴上。
    - **诊断价值**: 直观观察 CC 算法对拥塞的响应速度，识别 RTO 停滞或 Pacer 恢复延迟。

💡 绘图提示：

可视化矩阵的设计确保了即使在 -log 选项不完整的情况下，AutoVisualizer 也能根据 available_metrics 自动降级展示，只呈现数据支持的维度。



## 4 智能特征提取逻辑 (Feature Extraction)

`AutoVisualizer` 并非简单地罗列所有流的数据，而是通过内置的智能特征提取逻辑（位于 `_extract_flow_features` 方法），在成百上千条并发流中精准识别出对网络性能影响最大的“异常者”。这些特征为“双视图”模板中的异常高亮提供了数学依据。

---

### 4.1 核心特征维度 (Core Feature Dimensions)

算法针对每条流的速率时序数据，计算以下三个关键物理特征：

- **FCT 掉速点 (FCT Point / Dropping Point)**：
    
    - **定义**：识别流速率实质性下降至“传输结束”状态的时间点。
        
    - **计算逻辑**：设定阈值比例（`threshold_ratio = 0.05`），寻找最后一个速率大于 `max_rate * 0.05` 的时间索引。
        
    - **物理意义**：用于识别哪些流因为严重的排队或拥塞控制抑制而延迟退出网络，即“最慢流”。
        
- **波动率 (Volatility)**：
    
    - **定义**：衡量流在传输过程中速率变化的剧烈程度。
        
    - **计算逻辑**：计算流速率序列的标准差（Standard Deviation）。
        
    - **物理意义**：识别那些在带宽竞争中极度不稳定、频繁触发拥塞控制窗口调整的流。
        
- **尾部活跃度 (Tail Activity)**：
    
    - **定义**：衡量流在仿真后期对网络资源的占用情况。
        
    - **计算逻辑**：定义“尾部”为仿真最后 10% 的时间窗口（`tail_start = t_max * 0.9`），计算该窗口内的平均速率。
        
    - **物理意义**：识别那些在大部分流已结束后仍顽固占用带宽的“幸存流”。
- **瓶颈热点识别 (Bottleneck Hotspot Identification)**：

	- **定义**：自动锁定全网发生拥塞频率最高的位置。
	    
	- **计算逻辑**：遍历 `traffic_df`，统计各 `location_id` 发生的 `DROP` 和 `TRIM` 事件总数，提取 `idmax` 作为当前实验的 Hotspot。
	    
	- **应用**：驱动 Correlation Analysis 自动加载对应位置的物理指标。

---

### 4.2 特征处理流水线

特征提取过程遵循以下步骤以确保计算的高效性：

1. **数据透视与分组**：将 `flow_goodput_df` 按流 ID（或节点 ID）进行分组迭代。
    
2. **插值平滑**：在处理特征前，对缺失速率点进行线性插值，以防止采样空隙干扰标准差计算。
    
3. **特征聚合**：为每个 ID 生成包含 `fct_point`、`volatility` 和 `tail_avg` 的特征向量，并汇总为 `feat_df`。
    

---

### 4.3 异常高亮映射 (Anomaly Mapping)

提取的特征最终被映射到可视化界面中的高亮逻辑上：

|**异常标签**|**筛选标准**|**绘图表现**|**诊断价值**|
|---|---|---|---|
|**Latest FCT**|`fct_point` 最大前 3 名|**红色高亮**|识别造成任务尾部延迟（Tail Latency）的元凶。|
|**Highest Volatility**|`volatility` 最大前 2 名|**橙色高亮**|识别 CC 算法参数设置不当或路径质量剧烈波动的流。|
|**High Tail Activity**|`tail_avg` 最大前 2 名|**蓝色高亮**|识别在 Incast 结束阶段依然导致链路饱和的残余流量。|

---

### 4.4 逻辑优势与局限

- **优势**：
    
    - **自动降噪**：通过 5% 的掉速阈值，有效排除了仿真结束前微小的残余 ACK 流量对 FCT 判定的干扰。
        
    - **自适应定位**：无论仿真时长如何变化，10% 的尾部定义确保了分析窗口的相对稳定性。
        
- **局限**：
    
    - **计算成本**：对于包含数万条流的超大规模仿真，遍历提取特征会带来额外的处理耗时。
        
    - **静态阈值**：5% 的掉速阈值对于某些速率波动极大的协议（如激进的 DCTCP）可能需要微调。
        

💡 调优提示：

如果您发现高亮的“最慢流”实际上已经传输完毕，只是因为微小的重传包被标记，可以尝试在 autoreport.py 中微调 threshold_ratio 参数。

## 5 坐标轴与格式化规范 (Formatting Standards)

`AutoVisualizer` 制定了一套严格的格式化标准，旨在消除科学计数法带来的视觉干扰，并确保仿真中的亚毫秒级事件能够以直观、符合物理直觉的方式呈现。

---

### 5.1 时间轴归一化 (Time Normalization)

由于 `uet-htsim` 仿真通常聚焦于数据中心内极短时间的拥塞行为，`AutoVisualizer` 在展示层对时间进行了统一处理：

- **单位转换 (s → us)**：通过 `_to_us` 辅助函数，所有 DataFrame 的时间列在绘图前均从秒转换为微秒（$\mu s$）。
    
- **物理考量**：微秒级刻度能更清晰地展现 RTT（往返时延）级别的速率调整和排队波动，避免了在 0.0001s 这种刻度下进行心算。
    

---

### 5.2 核心格式化器 (Core Formatters)

类中内置了两个关键的静态格式化工具，通过 `matplotlib.ticker` 动态注入坐标轴：

- **纯数字格式化 (`_fmt_plain`)**：
    
    - **逻辑**：强制使用 `f'{x:g}'` 格式化数值。
        
    - **目的**：拒绝科学计数法（例如显示 `200` 而非 `2e2`），这在对数轴（Log-scale）上尤为重要，确保 FCT 和速率读数一目了然。
        
- **自适应字节格式化 (`_fmt_bytes`)**：
    
    - **逻辑**：根据数值大小自动在 B, KB, MB, GB, TB 之间切换单位（基于 1024 进制）。
        
    - **应用**：主要用于队列深度（Queue Depth）和流大小（Flow Size）的 X/Y 轴标签。
        

---

### 5.3 坐标系与标度选择 (Coordinate Systems & Scaling)

针对不同的数据特征，`AutoVisualizer` 预设了最佳的标度策略：

| **图表类型**                 | **X 轴标度**   | **Y 轴标度**           | **格式化规范**                          |
| ------------------------ | ----------- | ------------------- | ---------------------------------- |
| **FCT CDF**              | 对数 (Log)    | 线性 (Linear)         | X 轴使用 `_fmt_plain`。                |
| **Size vs FCT**          | 对数 (Log)    | 对数 (Log)            | X 轴 `_fmt_bytes`，Y 轴 `_fmt_plain`。 |
| **Goodput 时序**           | 线性 (Linear) | 线性 (Linear)         | Y 轴速率标签根据 `self.unit` 动态生成。        |
| **队列深度**                 | 线性 (Linear) | 线性 (Linear)         | Y 轴使用 `_fmt_bytes` 展示 Buffer 占用。   |
| **Flow Slowdown CDF**    | 对数 (Log)    | 线性 (Linear)         | X 轴使用 `_fmt_plain`                 |
| **Congestion Heatmap**   | 线性 (Linear) | 拓扑位置 (Categorical)  | 自动注入 `idmap` 名称                    |
| **Correlation Analysis** | 线性 (Linear) | 混合 (%, Gbps, Event) | Y 轴根据面板自动切换百分比与速率                  |


### 5.4 视觉美学与辨识度 (Visual Aesthetics)

- **透明度管理 (Alpha Blending)**：
    
    - 分位数带（Percentile Band）使用 `alpha=0.3`。
        
    - 异常流背景灰色细线使用 `alpha=0.2` 且 `linewidth=0.5`。
        
    - 这种设计确保了“背景噪声”不会遮盖核心趋势线或高亮的异常流。
        
- **配色方案 (Color Palettes)**：
    
    - 多流对比和队列对比默认使用 `tab10` 调色板。
        
    - 异常高亮视图采用固定的强调色：红色（慢速）、橙色（波动）、蓝色（长尾），形成视觉上的告警提示。
        
- **网格与标签**：
    
    - 统一开启主网格线（Major Grid），并设置 `ls="--", alpha=0.3` 以辅助读数。
        
    - 图例（Legend）位置通常固定在 `upper right`，以避免遮挡时序起始阶段的剧烈波动。
        

## 6 “漏斗式”分析方法论 (Methodology)

报告建议按照以下逻辑链进行深度阅读：
1. **Phase 1 (The Result)**: 观察 CDF，确认是否存在性能长尾。
2. **Phase 2 (The Stability)**: 观察吞吐波动，识别震荡或不稳定的流。
3. **Phase 3 (The Hotspot)**: 定位物理位置，确定拥塞发生在哪个交换层级。
4. **Phase 4 (The Causality)**: **(RICC 重点)** 联动诊断 CWND 与队列，实锤算法逻辑缺陷。
5. **Phase 5 (The Anatomy)**: 针对极端受害流进行全路径时序解剖。

## 7 可视化方案反思

目前有3种图形包含队列长度随时间的变化情况：
1. Last-Hop Queue Dynamics：可以展示多个队列（限定 **Last-Hop**）的变化情况（目前会筛选出 Top-3 队列：`top_queues = df.groupby("queue_id")["max_q"].max().nlargest(3).index`）
2. Incast Fan-in vs. Pressure 和 Traffic Event Spatial Distribution：都聚焦于**单队列**的变化情况，找出发生 `DROP` 或 `TRIM` 事件频率最高的那个位置（Global Hotspot）
	1. **队列范围**：不受层级限制，可能是 Core 交换机，也可能是 ToR 交换机
	2. **目的**：两者都是“综合图”，尽管选择的队列点是相同的，但图片作为一个整体所要呈现的目的不同
		1. **`Incast Fan-in vs. Pressure`**：选中这个点，是为了通过右轴叠加 **“流的数量”**，解释为什么这个点会成为“丢包王——**目的**：判断拥塞是由**流的数量（Fan-in）** 引起的，还是单纯的**单流突发**
		2. **`Traffic Event Spatial Distribution`**：选中这个点，是为了将它的 **“水位波动线”** 作为基准，观察它在剧烈排队时，全网其他位置是否也同步出现了散点状的拥塞——**目的**：看这个最严重的点出事时，全网其他地方是不是也同步在“冒烟”（左侧 Y轴可能列出不同名字——如 `LS0->DST0`、`US2->LS0`、`CS1->US2` 等）

