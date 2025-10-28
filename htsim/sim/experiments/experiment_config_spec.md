# 实验配置系统详细规范文档

本文档详细介绍了如何使用基于 YAML 的实验配置系统。该系统旨在简化流量生成和模拟执行过程，通过统一的配置文件管理实验参数，并支持参数的自动化组合与展开。

## 1. 引言

本实验配置系统将复杂的网络模拟实验分解为流量生成和模拟执行两个阶段。通过使用结构化的 YAML 配置文件，用户可以清晰地定义实验参数，系统将自动处理参数组合、连接矩阵生成以及模拟器调用，从而提高实验的可重复性和管理效率。

## 2. 配置文件结构

配置文件主要分为两个顶级部分：`common` 和 `experiments`。

-   **`common`**: 定义了流量生成和模拟的默认参数。这些参数将作为所有实验的基准。
-   **`experiments`**: 包含一个实验列表，每个实验定义了独立的 `traffic` 和 `simulation` 参数。这些参数会覆盖 `common` 中对应的设置。

### 示例配置概览

```yaml
common:
  traffic:
    type: permutation
    params:
      nodes: 8192
      conns: 8192
      flowsize: "2MB"
      extrastarttime: 0
      randseed: 13
  simulation:
    params:
      linkspeed: 100000
      strat: ecmp

experiments:
  - name: ndp_experiment_example
    exe: htsim_ndp
    protocol: ndp
    traffic:
      params:
        conns: [16, 32] # 列表参数将进行笛卡尔积组合
    simulation:
      params:
        paths: [32, 256] # 列表参数将进行笛卡尔积组合
        q: [35, 1000]
        ecn_thresh: [0.018] # 仅当 strat 支持 ECN 时有效
    plot_settings: # 绘图设置 (可选)
      cdf-fct:
        x_range_auto: true
        x_range_manual: null
```

## 3. 通用配置 (`common`)

`common` 部分定义了所有实验共享的默认参数。

### 3.1 `common.traffic`

定义了流量生成的默认参数。

-   **`type`**: (字符串) 指定流量生成类型，对应 `htsim/sim/analysis/config/traffic_patterns.py` 中的函数名。
-   **`params`**: (字典) 流量生成函数的具体参数。

### 3.2 `common.simulation`

定义了模拟器的默认运行参数。

-   **`params`**: (字典) 模拟器可执行文件的命令行参数。

## 4. 实验配置 (`experiments`)

`experiments` 是一个列表，每个元素代表一个独立的实验配置块。

### 4.1 实验块结构

每个实验块可以包含以下字段：

-   **`name`**: (字符串) 实验的名称，用于生成输出文件和目录名。
-   **`exe`**: (字符串) 指定要运行的模拟器可执行文件的名称（例如 `htsim_ndp`）。系统会在 `BUILD_DIR` 下寻找该二进制文件。
-   **`protocol`**: (字符串) 协议名称（例如 `ndp`），用于在生成输出文件名时提供一个前缀，帮助区分不同协议的实验结果。
-   **`traffic`**: (字典) 覆盖或扩展 `common.traffic` 中的设置。
    -   **`type`**: (可选，字符串) 覆盖 `common.traffic.type`。
    -   **`params`**: (可选，字典) 覆盖或扩展 `common.traffic.params`。
-   **`simulation`**: (字典) 覆盖或扩展 `common.simulation` 中的设置。
    -   **`params`**: (可选，字典) 覆盖或扩展 `common.simulation.params`。
-   **`execute`**: (可选，布尔值，默认为 `True`) 如果设置为 `True`，则会实际运行模拟器；否则，只会打印出将要执行的模拟命令。
-   **`plot_settings`**: (可选，字典) 定义该实验生成的绘图的特定设置。
    -   **`cdf-fct`**: (字典) 针对 FCT CDF 图表的设置。
        -   **`x_range_auto`**: (布尔值，默认为 `false`) 如果为 `true`，系统将自动识别数据范围并进行扩展（例如，将 CDF-FCT 图表的范围从 5-10 扩展到 4-12）。
        -   **`x_range_manual`**: (列表 `[min, max]` 或 `null`，默认为 `null`) 如果指定，则手动设置图表 X 轴的显示范围（例如 `[3, 7]`）。当 `x_range_auto` 为 `true` 时，此设置将被忽略。

### 4.2 参数展开与组合

实验配置系统通过 `expand_params_tree` 函数实现参数的笛卡尔积展开，从而灵活地定义和运行多组实验。

-   **笛卡尔积处理**: 在 `experiments` 列表中的每个实验块内，`traffic.params` 和 `simulation.params` 部分的参数都可以是列表。`expand_params_tree` 函数会递归地遍历这些列表，生成所有可能的参数组合。
    -   **示例**: 如果 `paths: [32, 256]` 和 `q: [35, 1000]`，则会生成 `(paths=32, q=35)`、`(paths=32, q=1000)`、`(paths=256, q=35)`、`(paths=256, q=1000)` 四种组合。
-   **实验的识别**:
    -   `experiments` 列表中的每个项定义一个“主实验”。
    -   每个主实验内部，由 `traffic` 和 `simulation` 参数（尤其是列表形式的参数）展开生成的每个唯一组合，都视为一个“子实验”。
    -   每个子实验的输出文件命名会结合 `name` 字段、`protocol` 字段以及由展开参数生成的唯一后缀，确保每个子实验结果的可追溯性。
-   **参数合并与优先级**:
    -   `common` 部分定义的参数是全局默认值。
    -   `experiments` 列表中的每个实验块可以覆盖 `common` 中的 `traffic` 和 `simulation` 参数。
    -   实验块内部的 `traffic` 和 `simulation` 参数具有最高优先级。

## 5. 支持的流量类型

系统支持以下流量生成函数（对应 `traffic.type`），参数需与函数定义一致：

-   **`permutation`**: `nodes`、`conns`、`flowsize`、`extrastarttime`、`randseed`
-   **`allreduce`**: `nodes`、`conns`、`groupsize`、`flowsize`、`locality`、`randseed`
-   **`allreduce_butterfly`**: `nodes`、`groups`、`groupsize`、`flowsize`、`locality`、`randseed`
-   **`incast`**: `nodes`、`conns`、`flowsize`、`extrastarttime`、`randseed`
-   **`outcast_incast`**: `nodes`、`conns_incast`、`conns_outcast`、`flowsize`、`randseed`
-   **`permutation_full_bisection`**: `nodes`、`conns`、`flowsize`、`extrastarttime`、`randseed`
-   **`serial_alltoall`**: `nodes`、`conns`、`groupsize`、`flowsize`、`extrastarttime`、`randseed`
-   **`serialn_alltoall`**: `nodes`、`conns`、`groupsize`、`parallel`、`flowsize`、`extrastarttime`、`randseed`
-   **`serialn_alltoall_prio`**: `nodes`、`conns`、`groupsize`、`parallel`、`flowsize`、`extrastarttime`、`randseed`

## 6. 模拟器参数说明

### 6.1 通用参数（适用于所有模拟程序）

这些参数由所有主要协议（UEC、EQDS、RoCE、NDP、Swift、TCP、HPCC）共享，用于统一仿真环境配置。它们主要控制拓扑、流量、队列、链路、日志与随机性等基础行为。

#### 📁 基础配置

| 参数名    | 含义         | 说明                   |
| :-------- | :----------- | :--------------------- |
| `-o`      | 输出日志文件名 | 指定仿真输出日志文件路径。 |
| `-end`    | 仿真结束时间 | 仿真运行的最大时间（微秒）。 |
| `-nodes`  | 节点数量     | 拓扑中服务器节点总数，需与流量矩阵匹配。 |
| `-tiers`  | FatTree 层数 | 设定网络拓扑层级（2 或 3 层）。 |

#### 🌐 流量与拓扑

| 参数名 | 含义         | 说明                               |
| :----- | :----------- | :--------------------------------- |
| `-tm`  | 流量矩阵文件 | 指定流量矩阵（定义连接关系与大小）。 |
| `-topo` | 拓扑文件     | 指定自定义拓扑文件路径，若不提供则自动生成。 |

#### 📦 队列与主机端队列

| 参数名          | 含义         | 说明                                       |
| :-------------- | :----------- | :----------------------------------------- |
| `-q`            | 队列大小     | 设置交换机队列容量（单位：包）。若未设置，将按 BDP 自动估算。 |
| `-queue_type`   | 队列类型     | 指定交换机使用的队列机制：`composite`、`composite_ecn`、`lossless`、`lossless_input`。 |
| `-host_queue_type` | 主机队列类型 | 指定主机发送端的队列调度策略：`swift`、`prio`、`fair_prio`。 |

#### ⚙️ 网络与性能参数

| 参数名         | 含义         | 说明                               |
| :------------- | :----------- | :--------------------------------- |
| `-linkspeed`   | 链路速度     | 设置网络链路带宽（单位 Mbps）。    |
| `-hop_latency` | 跳延迟       | 单跳传播延迟（单位微秒）。         |
| `-switch_latency` | 交换延迟     | 交换机内部处理延迟（单位微秒）。   |
| `-mtu`         | 包大小       | 设置最大传输单元（字节），各协议默认值不同。 |
| `-paths`       | 路径熵大小   | 多路径选择时的路径池规模。         |

#### 🧠 随机性与可重复性

| 参数名 | 含义     | 说明                         |
| :----- | :------- | :--------------------------- |
| `-seed` | 随机种子 | 控制随机数生成器，确保实验可重复。 |

#### 🧾 日志与调试控制

| 参数名 | 含义     | 说明                                       |
| :----- | :------- | :----------------------------------------- |
| `-log`  | 日志选项 | 启用特定组件的日志输出，可重复设置。常见值：`sink`、`nic`、`flow_events`、`tor_downqueue`、`tor_upqueue`、`switch`、`traffic`、`queue_usage`。 |

#### 🧩 默认值示例（部分）

| 参数            | 默认值       | 适用程序 |
| :-------------- | :----------- | :------- |
| `-queue_type`   | `composite`  | UEC      |
| `-queue_type`   | `lossless_input` | RoCE     |
| `-mtu`          | `4150`       | UEC      |
| `-mtu`          | `4000`       | RoCE     |
| `-mtu`          | `9000`       | NDP      |
| `-hop_latency`  | `1`          | 所有协议 |
| `-switch_latency` | `0`          | 所有协议 |
| `-seed`         | `13`         | 所有协议 |

### 6.2 各协议特有参数

#### 🚀 UEC 参数说明（Ultra Ethernet Congestion Control）

| 参数名                  | 含义             | 说明                                       |
| :---------------------- | :--------------- | :----------------------------------------- |
| `-sender_cc_only`       | 仅启用发送端拥塞控制 | 启用发送端（NSCC）控制逻辑，禁用接收端与过载控制。 |
| `-receiver_cc_only`     | 仅启用接收端拥塞控制 | 启用接收端（RCCC）控制逻辑，禁用发送端控制。 |
| `-sender_cc`            | 启用发送端拥塞控制 | 可与 `-receiver_cc` 同时启用，形成双向控制。 |
| `-receiver_cc`          | 启用接收端拥塞控制 | 与 `-sender_cc` 结合使用可实现联合调节。 |
| `-sender_cc_algo`       | 发送端拥塞控制算法 | 可选 `dctcp`、`nscc`、`constant`，用于指定算法类型。 |
| `-target_q_delay`       | 目标队列延迟     | 设置拥塞控制的目标排队时延（单位微秒）。 |
| `-queue_size_bdp_factor` | 队列大小 BDP 因子 | 将队列大小设为带宽延迟积的倍数，用于调节缓冲大小。 |
| `-qa_gate`              | Quick Adapt 门限 | 设置快速窗口调整触发门限（2 的幂）。 |
| `-oversubscribed_cc`    | 启用过载拥塞控制 | 在链路过载时启用接收端限速机制。         |
| `-Ai`                   | 加性增参数       | OversubscribedCC 的 Additive Increase 系数。 |
| `-Md`                   | 乘性减参数       | OversubscribedCC 的 Multiplicative Decrease 系数。 |
| `-alpha`                | 平滑因子         | OversubscribedCC 的加权平均平滑系数。 |
| `-force_disable_oversubscribed_cc` | 强制禁用过载控制 | 即使拓扑存在过载也禁用过载控制。         |
| `-load_balancing_algo`  | 负载均衡算法     | 可选 `bitmap`、`reps`、`reps_legacy`、`oblivious`、`mixed`。 |
| `-sack_threshold`       | SACK 阈值        | 接收端生成 SACK 的字节阈值，用于多路径反馈间隔控制。 |
| `-disable_trim`         | 禁用包裁剪       | 关闭 trimming 机制，改为直接丢弃超长包。 |
| `-trimsize`             | 裁剪包大小       | 设置被裁剪后的包大小（字节）。默认 64。 |
| `-ecn`                  | ECN 标记阈值     | 设置 ECN 低阈值与高阈值（单位：包数）。 |
| `-sleek`                | 启用 SLEEK       | 开启发送端快速丢包恢复启发式算法。         |
| `-planes`               | 多平面拓扑       | 设置网络平面数量（1–8），并自动匹配 NIC 端口数。 |
| `-conn_reuse`           | 启用连接重用     | 允许同一连接多次复用以发送多个消息。     |

#### ⚙️ EQDS 参数说明（Enhanced Queue Delay Sensing）

| 参数名             | 含义             | 说明                                       |
| :----------------- | :--------------- | :----------------------------------------- |
| `-sender_cc_only`  | 仅启用发送端拥塞控制 | 仅启用发送端控制逻辑（DCTCP 模式），禁用接收端控制。 |
| `-sender_cc_algo`  | 发送端算法       | 指定发送端使用的拥塞控制算法，目前仅支持 `dctcp`。 |
| `-recv_oversub_cc` | 启用接收端过载控制 | 允许接收端根据网络过载状态调整反馈频率。 |
| `-use_exp_avg_ecn` | 启用 ECN 指数平均 | 对 ECN 标记进行指数加权平均，提高反馈稳定性。 |
| `-use_exp_avg_rtt` | 启用 RTT 指数平均 | 对 RTT 采样值进行指数加权平滑，避免瞬态波动影响。 |
| `-use_reps`        | 启用 REPS 多路径 | 启动 REPS（Receiver-based Explicit Path Selection）多路径机制。 |
| `-planes`          | 多平面拓扑       | 设置拓扑平面数量（1–8），同时决定 NIC 端口数。 |

#### 🧩 RoCE 参数说明（RDMA over Converged Ethernet）

| 参数名          | 含义             | 说明                                       |
| :-------------- | :--------------- | :----------------------------------------- |
| `-dcqcn`        | 启用 DCQCN 拥塞控制 | 激活 DCQCN 模块，并设置 ECN 阈值（包数）。 |
| `-pfc_thresholds` | PFC 阈值         | 设置优先级流控的低、高阈值，用于无损队列触发与恢复。 |
| `-nic_burst`    | NIC 突发包数     | 限制每次突发发送的包数，控制发送速率平滑度。 |
| `-out_of_order` | 启用乱序接收     | 允许接收端按乱序接收包，测试可靠性与重排机制。 |
| `-ar_method`    | 自适应路由方法   | 选择路径评估依据。支持 `pause`、`queue`、`bandwidth`、`flowcount`、`pqb`、`pq`、`pb`、`qb`。 |

#### ⚡ NDP 参数说明（Network Datagram Protocol）

| 参数名             | 含义             | 说明                                       |
| :----------------- | :--------------- | :----------------------------------------- |
| `-oversubscribed_cc` | 启用过载拥塞控制 | 启用接收端基于过载检测的反馈控制，用于高负载场景。 |
| `-rts`             | 启用请求发送机制 | 启用 RTS (Request To Send) 模式，使发送端先发送请求包再启动数据传输。 |
| `-path_burst`      | 路径突发包数     | 限制单条路径连续可发送的数据包数量，用于路径间速率平衡。 |
| `-cwnd`            | 拥塞窗口大小     | 设置初始拥塞窗口，控制并发传输速率。     |

#### 🌀 Swift 参数说明（Swift Congestion Control）

| 参数名      | 含义             | 说明                                       |
| :---------- | :--------------- | :----------------------------------------- |
| `-cwnd`     | 拥塞窗口大小     | 设置发送端初始拥塞窗口，用于控制初始速率。 |
| `-flowsize` | 流大小           | 指定单个流的传输大小（字节）。             |
| `-target`   | 目标 RTT         | 拥塞控制目标 RTT（单位微秒），用于计算速率调整。 |
| `-g`        | 增益系数         | 控制速率调整灵敏度（增益越大，反应越快）。 |
| `-subflows` | 子流数量         | 启用多子流机制，将单一流拆分为多个并行路径。 |
| `-plb`      | 启用包级负载均衡 | Packet-Level Balancing，在多路径之间动态选择路径。 |
| `-slow_start` | 启用慢启动       | 启动阶段采用指数增长窗口（默认关闭）。     |
| `-ecn`      | ECN 阈值         | 启用 ECN 标记阈值机制，结合 RTT 控制速率。 |

#### 🌐 TCP 参数说明（Transmission Control Protocol）

| 参数名          | 含义             | 说明                                       |
| :-------------- | :--------------- | :----------------------------------------- |
| `-cwnd`         | 初始拥塞窗口     | 设置 TCP 连接的初始拥塞窗口（以包为单位）。 |
| `-min_rtt`      | 最小 RTT         | 指定估计的最小往返时延（微秒），用于延迟采样基准。 |
| `-ecn`          | 启用 ECN         | 启用 ECN（显式拥塞通知）标记机制。         |
| `-ecn_thresh`   | ECN 阈值         | 设置 ECN 标记触发的队列深度（包数）。     |
| `-flowsize`     | 流大小           | 设置单个 TCP 流的传输大小（字节）。     |
| `-flow_type`    | 流类型           | 指定流量类型，可选 `websearch`、`uniform`、`pareto`、`incast`。 |
| `-conn_reuse`   | 启用连接复用     | 允许多次使用相同连接以减少握手成本。     |
| `-queue_type`   | 队列类型         | 选择 TCP 使用的交换机队列类型：`composite`、`composite_ecn`、`lossless_input`。 |
| `-host_queue_type` | 主机队列类型     | 设定主机端调度器策略（如 `prio`、`fair`、`swift`）。 |

## 7. 运行实验

使用 `run.py` 脚本运行实验：

```bash
python run.py <config>.yaml
```

其中 `<config>.yaml` 是您的实验配置文件路径。

## 8. 注意事项

-   `traffic` 和 `simulation` 中重复的参数，以 `experiments` 中的定义为准。
-   实验名称由 `name` 字段和展开的参数自动生成。
-   `exe` 字段必须指定模拟器可执行文件的名称，例如 `htsim_ndp`。
-   `execute` 字段（可选，默认为 `True`）：如果设置为 `True`，则会实际运行模拟器；否则，只会打印出将要执行的模拟命令。
-   绘图配置 (`plot_settings`) 允许用户在实验 YAML 中直接控制图表的显示范围，提供了自动识别和手动指定两种方式。
-   `-queue_type lossless_input` 与 `-pfc_thresholds` 必须配合使用，否则无损流控无法触发。
-   `-dcqcn` 参数与 ECN 阈值密切相关，不同链路速度下需调整。
-   自适应路由 (`-ar_method`) 与传统 ECMP 可独立启用，用于评估路径动态选择性能。
-   启用 `-rts` 可显著改善大规模 incast 场景下的公平性，但会带来额外延迟。
-   `-path_burst` 与 `-cwnd` 参数共同决定速率平衡与突发性能。
-   `-oversubscribed_cc` 可与 `-rts` 配合使用，以评估接收端反馈在高并发环境中的响应能力。
-   `-target` 与 `-g` 共同决定 Swift 速率调整的平衡点；较小的 `target` 值可实现更低延迟，但易振荡。
-   启用 `-subflows` 后可结合 `-plb` 实现 Swift-MPTCP 式的多路径并行传输。
-   当开启 Swift 的 `-ecn` 时，Swift 的速率反馈会结合 RTT 与 ECN 双信号进行速率控制。
-   TCP 开启 `-ecn` 与使用 `composite_ecn` 队列搭配效果最佳，可避免过多丢包。
-   TCP 的 `-flow_type` 决定流量分布模型，对整体 RTT 和公平性影响较大。
-   当与 UEC、EQDS 对比时，可保持相同的 `-flowsize` 与 `-mtu` 参数以确保可比性。