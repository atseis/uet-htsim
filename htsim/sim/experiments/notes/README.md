# 实验配置系统使用说明

本文档介绍如何使用新的实验配置系统，该系统将流量生成和模拟执行分为两个阶段，通过统一的YAML配置文件进行管理。

## 配置文件结构

配置文件分为 **common** 和 **experiments** 两个主要部分：

1. **common** - 通用配置，包含流量生成和模拟的默认参数
2. **experiments** - 实验配置，每个实验包含独立的 `traffic` 和 `simulation` 参数

### 示例配置

```yaml
common:
  traffic:
    type: permutation # 对应 traffic_patterns.generate_permutation_traffic
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
  - name: ndp_experiment
    exe: htsim_ndp # 指定模拟器可执行文件
    protocol: ndp # 用于输出文件命名
    traffic:
      params:
        conns: [16, 32] # 流量参数也可以是列表，会与 simulation 参数进行笛卡尔积组合
    simulation:
      params:
        paths: [32, 256] # 列表参数将被展开组合
        q: [35, 1000]
        ecn_thresh: [0.018] # 仅当 strat 支持 ECN 时有效
```

## 支持的流量类型

系统支持以下流量生成函数（对应 `traffic.type`），参数需与函数定义一致：

- **permutation**：`nodes`、`conns`、`flowsize`、`extrastarttime`、`randseed`
- **allreduce**：`nodes`、`conns`、`groupsize`、`flowsize`、`locality`、`randseed`
- **allreduce_butterfly**：`nodes`、`groups`、`groupsize`、`flowsize`、`locality`、`randseed`
- **incast**：`nodes`、`conns`、`flowsize`、`extrastarttime`、`randseed`、`prefer_remote`
- **outcast_incast**：`nodes`、`conns_incast`、`conns_outcast`、`flowsize`、`randseed`
- **permutation_full_bisection**：`nodes`、`conns`、`flowsize`、`extrastarttime`、`randseed`
- **serial_alltoall**：`nodes`、`conns`、`groupsize`、`flowsize`、`extrastarttime`、`randseed`
- **serialn_alltoall**：`nodes`、`conns`、`groupsize`、`parallel`、`flowsize`、`extrastarttime`、`randseed`
- **serialn_alltoall_prio**：`nodes`、`conns`、`groupsize`、`parallel`、`flowsize`、`extrastarttime`、`randseed`

## 运行实验

使用以下命令运行实验：

```bash
python run.py <config>.yaml
```

可选参数：

- `--force` 强制重跑所有子实验，忽略已存在的 `status.yaml` 状态
- `--continue` 在某个子实验失败后继续执行其他子实验

## 工作流程

1. 系统首先展开 `experiments` 中 `traffic` 和 `simulation` 参数的列表组合
2. 对每个组合，根据 `traffic` 配置生成连接矩阵（CM）文件
3. 运行模拟器，自动传递 CM 文件路径（`-tm`）和模拟参数

## 实验展开与组合

实验配置系统通过 `expand_params_tree` 函数实现参数的笛卡尔积展开，从而灵活地定义和运行多组实验。

- **笛卡尔积处理**：在 `experiments` 列表中的每个实验块内，`traffic` 和 `simulation` 部分的参数都可以是列表。`expand_params_tree` 函数会递归地遍历这些列表，生成所有可能的参数组合。例如，如果 `paths: [32, 256]` 和 `q: [35, 1000]`，则会生成 `(paths=32, q=35)`、`(paths=32, q=1000)`、`(paths=256, q=35)`、`(paths=256, q=1000)` 四种组合。

- **实验的识别**：
    - `experiments` 列表中的每个项定义一个“主实验”。
    - 每个主实验内部，由 `traffic` 和 `simulation` 参数（尤其是列表形式的参数）展开生成的每个唯一组合，都视为一个“子实验”。
    - 每个子实验的输出文件命名会结合 `name` 字段、`protocol` 字段以及由展开参数生成的唯一后缀，确保每个子实验结果的可追溯性。

- **参数合并与优先级**：
    - `common` 部分定义的参数是全局默认值。
    - `experiments` 列表中的每个实验块可以覆盖 `common` 中的 `traffic` 和 `simulation` 参数。
    - 实验块内部的 `traffic` 和 `simulation` 参数具有最高优先级。

- **`exe` 和 `protocol` 字段**：
    - `exe` 字段（例如 `htsim_ndp`）用于指定要运行的模拟器可执行文件的名称，系统会在 `BUILD_DIR` 下寻找该二进制文件。
    - `protocol` 字段（例如 `ndp`）可用于人类可读的区分，但当前批量运行逻辑不会将该字段纳入自动命名或命令行参数。

## 注意事项

- `traffic` 和 `simulation` 中重复的参数，以 `experiments` 中的定义为准
- 实验名称由 `name` 字段和展开的参数自动生成
- `exe` 字段必须指定模拟器可执行文件的名称，例如 `htsim_ndp`
- `execute` 字段（可选，默认为 `False`）：如果设置为 `True`，则会实际运行模拟器；否则，只会打印出将要执行的模拟命令。

# 参数说明

## 🧩 参数汇总与对照表（简要版）

|协议/程序|参数名（仅列出）|参数归属|含义简述（可在后续细化）|
|---|---|---|---|
|**所有协议共享**|-o -end -nodes -tiers -tm -topo -q -linkspeed -seed -mtu -paths -hop_latency -switch_latency -queue_type -host_queue_type -log|通用参数|日志、仿真时间、拓扑、链路、队列等基础设置|
|**UEC**|-sender_cc_only -receiver_cc_only -sender_cc_algo -oversubscribed_cc -Ai -Md -alpha -load_balancing_algo -planes -conn_reuse -target_q_delay -queue_size_bdp_factor -disable_trim -trimsize -ecn -sleek|特有参数|拥塞控制、负载均衡、多平面拓扑等高级配置|
|**EQDS**|-sender_cc_only -sender_cc_algo -recv_oversub_cc -use_exp_avg_ecn -use_exp_avg_rtt -use_reps -planes|特有参数|拥塞控制与RTT/ECN平均算法配置|
|**RoCE**|-dcqcn -pfc_thresholds -nic_burst -out_of_order -ar_method|特有参数|DCQCN控制、PFC参数、自适应路由|
|**NDP**|-rts -oversubscribed_cc -path_burst -cwnd|特有参数|拥塞与突发控制|
|**Swift**|-subflows -plb -cwnd -flowsize|特有参数|多子流、包级负载均衡、流大小|
|**TCP**|（仅通用参数）|共用|多路径TCP基础测试|

---

## ⚙️ 参数意义对应关系（同义项或相同作用）

|概念|不同程序参数名|说明|
|---|---|---|
|**队列类型**|-queue_type|所有协议共享，取值略有不同（UEC 默认 composite，RoCE 默认 lossless_input）|
|**平面拓扑**|-planes|UEC 与 EQDS 共享，用于多平面 NIC 配置|
|**拥塞控制算法**|-sender_cc_algo|UEC 与 EQDS 均定义，但实现算法不同|
|**过载控制**|-oversubscribed_cc / -recv_oversub_cc|分别在 UEC、EQDS、NDP 中出现，语义相似但作用层不同|
|**路径负载均衡**|-load_balancing_algo / -ar_method / -plb|UEC (LB算法)、RoCE (自适应路由)、Swift (包级LB) 分别控制不同层面的流量调度|
|**窗口控制**|-cwnd|NDP 与 Swift 都定义拥塞窗口大小|
|**延迟控制**|-target_q_delay / -hop_latency / -switch_latency|分别对应不同层面的延迟机制|

## 🧩 通用参数说明（适用于所有模拟程序）

> 这些参数由所有主要协议（UEC、EQDS、RoCE、NDP、Swift、TCP、HPCC）共享，用于统一仿真环境配置。  
> 它们主要控制拓扑、流量、队列、链路、日志与随机性等基础行为。

---

### 📁 基础配置

| 参数名    | 含义         | 说明                   |
| ------ | ---------- | -------------------- |
| -o     | 输出日志文件名    | 指定仿真输出日志文件路径。        |
| -end   | 仿真结束时间     | 仿真运行的最大时间（微秒）。       |
| -nodes | 节点数量       | 拓扑中服务器节点总数，需与流量矩阵匹配。 |
| -tiers | FatTree 层数 | 设定网络拓扑层级（2 或 3 层）。   |

---

### 🌐 流量与拓扑

|参数名|含义|说明|
|---|---|---|
|-tm|流量矩阵文件|指定流量矩阵（定义连接关系与大小）。|
|-topo|拓扑文件|指定自定义拓扑文件路径，若不提供则自动生成。|

---

### 📦 队列与主机端队列

|参数名|含义|说明|
|---|---|---|
|-q|队列大小|设置交换机队列容量（单位：包）。若未设置，将按 BDP 自动估算。|
|-queue_type|队列类型|指定交换机使用的队列机制：composite、composite_ecn、lossless、lossless_input。|
|-host_queue_type|主机队列类型|指定主机发送端的队列调度策略：swift、prio、fair_prio。|

---

### ⚙️ 网络与性能参数

|参数名|含义|说明|
|---|---|---|
|-linkspeed|链路速度|设置网络链路带宽（单位 Mbps）。|
|-hop_latency|跳延迟|单跳传播延迟（单位微秒）。|
|-switch_latency|交换延迟|交换机内部处理延迟（单位微秒）。|
|-mtu|包大小|设置最大传输单元（字节），各协议默认值不同。|
|-paths|路径熵大小|多路径选择时的路径池规模。|

---

### 🧠 随机性与可重复性

|参数名|含义|说明|
|---|---|---|
|-seed|随机种子|控制随机数生成器，确保实验可重复。|

---

### 🧾 日志与调试控制

|参数名|含义|说明|
|---|---|---|
|-log|日志选项|启用特定组件的日志输出，可重复设置。常见值：sink、nic、flow_events、tor_downqueue、tor_upqueue、switch、traffic、queue_usage。|

---

### 🧩 默认值示例（部分）

|参数|默认值|适用程序|
|---|---|---|
|-queue_type|composite|UEC|
|-queue_type|lossless_input|RoCE|
|-mtu|4150|UEC|
|-mtu|4000|RoCE|
|-mtu|9000|NDP|
|-hop_latency|1|所有协议|
|-switch_latency|0|所有协议|
|-seed|13|所有协议|

## 各协议特有参数
### 🚀 UEC 参数说明（Ultra Ethernet Congestion Control）

> 本节列出 `htsim_uec` 的特有参数，用于控制 UEC 协议的拥塞控制、负载均衡、多平面拓扑及高级机制。

---

#### 🧠 拥塞控制参数

|参数名|含义|说明|
|---|---|---|
|-sender_cc_only|仅启用发送端拥塞控制|启用发送端（NSCC）控制逻辑，禁用接收端与过载控制。|
|-receiver_cc_only|仅启用接收端拥塞控制|启用接收端（RCCC）控制逻辑，禁用发送端控制。|
|-sender_cc|启用发送端拥塞控制|可与 -receiver_cc 同时启用，形成双向控制。|
|-receiver_cc|启用接收端拥塞控制|与 -sender_cc 结合使用可实现联合调节。|
|-sender_cc_algo|发送端拥塞控制算法|可选 dctcp、nscc、constant，用于指定算法类型。|
|-target_q_delay|目标队列延迟|设置拥塞控制的目标排队时延（单位微秒）。|
|-queue_size_bdp_factor|队列大小 BDP 因子|将队列大小设为带宽延迟积的倍数，用于调节缓冲大小。|
|-qa_gate|Quick Adapt 门限|设置快速窗口调整触发门限（2 的幂）。|

---

#### ⚡ 过载拥塞控制参数

|参数名|含义|说明|
|---|---|---|
|-oversubscribed_cc|启用过载拥塞控制|在链路过载时启用接收端限速机制。|
|-Ai|加性增参数|OversubscribedCC 的 Additive Increase 系数。|
|-Md|乘性减参数|OversubscribedCC 的 Multiplicative Decrease 系数。|
|-alpha|平滑因子|OversubscribedCC 的加权平均平滑系数。|
|-force_disable_oversubscribed_cc|强制禁用过载控制|即使拓扑存在过载也禁用过载控制。|

---

#### ⚖️ 负载均衡参数

|参数名|含义|说明|
|---|---|---|
|-load_balancing_algo|负载均衡算法|可选 bitmap、reps、reps_legacy、oblivious、mixed。|
|-sack_threshold|SACK 阈值|接收端生成 SACK 的字节阈值，用于多路径反馈间隔控制。|

---

#### 🧩 包与队列行为

|参数名|含义|说明|
|---|---|---|
|-disable_trim|禁用包裁剪|关闭 trimming 机制，改为直接丢弃超长包。|
|-trimsize|裁剪包大小|设置被裁剪后的包大小（字节）。默认 64。|
|-ecn|ECN 标记阈值|设置 ECN 低阈值与高阈值（单位：包数）。|
|-sleek|启用 SLEEK|开启发送端快速丢包恢复启发式算法。|

---

#### 🧭 拓扑与结构参数

|参数名|含义|说明|
|---|---|---|
|-planes|多平面拓扑|设置网络平面数量（1–8），并自动匹配 NIC 端口数。|
|-conn_reuse|启用连接重用|允许同一连接多次复用以发送多个消息。|

---

#### 🧰 示例配置片段

```bash
# 发送端控制测试
./htsim_uec -tm connection_matrices/one.cm -sender_cc_only -end 1000

# 接收端过载控制测试
./htsim_uec -tm connection_matrices/incast_128.cm -receiver_cc -oversubscribed_cc -Ai 0.5 -Md 0.5 -alpha 0.8

# 启用 REPS 负载均衡与多路径
./htsim_uec -tm connection_matrices/perm_1024n_1024c_2MB.cm -load_balancing_algo reps -paths 128

# 禁用包裁剪，使用多平面拓扑
./htsim_uec -tm connection_matrices/one.cm -disable_trim -planes 4 -conn_reuse
```

---

#### 🧩 默认值与典型配置

|参数|默认值|说明|
|---|---|---|
|-load_balancing_algo|mixed|默认混合负载均衡|
|-trimsize|64|裁剪包默认大小|
|-queue_size_bdp_factor|0|若未指定，将由 trimming 策略决定|
|-target_q_delay|未定义|可显式设置|
|-planes|1|单平面拓扑|
|-sender_cc_algo|nscc|默认发送端算法|
|-queue_type|composite|默认队列类型|
|-mtu|4150|默认包大小|


### ⚙️ EQDS 参数说明（Enhanced Queue Delay Sensing）

> EQDS 是一种轻量级、基于接收端反馈的拥塞控制算法，  
> 其参数集中在发送端控制、RTT/ECN 平滑、REPS 多路径机制与多平面拓扑上。

---
#### 🧠 拥塞控制参数

|参数名|含义|说明|
|---|---|---|
|-sender_cc_only|仅启用发送端拥塞控制|仅启用发送端控制逻辑（DCTCP 模式），禁用接收端控制。|
|-sender_cc_algo|发送端算法|指定发送端使用的拥塞控制算法，目前仅支持 dctcp。|
|-recv_oversub_cc|启用接收端过载控制|允许接收端根据网络过载状态调整反馈频率。|

---

#### 📊 平滑与加权平均机制

|参数名|含义|说明|
|---|---|---|
|-use_exp_avg_ecn|启用 ECN 指数平均|对 ECN 标记进行指数加权平均，提高反馈稳定性。|
|-use_exp_avg_rtt|启用 RTT 指数平均|对 RTT 采样值进行指数加权平滑，避免瞬态波动影响。|

---

#### ⚖️ 多路径与负载均衡

|参数名|含义|说明|
|---|---|---|
|-use_reps|启用 REPS 多路径|启动 REPS（Receiver-based Explicit Path Selection）多路径机制。|

---

#### 🧭 拓扑与结构参数

|参数名|含义|说明|
|---|---|---|
|-planes|多平面拓扑|设置拓扑平面数量（1–8），同时决定 NIC 端口数。|

---

#### 🧰 示例配置片段

```bash
# 启用 DCTCP 模式下的发送端拥塞控制
./htsim_eqds -tm connection_matrices/one.cm -sender_cc_only -sender_cc_algo dctcp

# 启用指数平滑与多路径
./htsim_eqds -tm connection_matrices/incast_64.cm -use_exp_avg_ecn 1 -use_exp_avg_rtt 1 -use_reps 1

# 多平面拓扑测试
./htsim_eqds -tm connection_matrices/perm_32n_32c_2MB.cm -planes 4
```

---

#### 🧩 默认值与典型配置

|参数|默认值|说明|
|---|---|---|
|-sender_cc_algo|dctcp|唯一支持的算法类型|
|-use_exp_avg_ecn|0|默认不使用平滑|
|-use_exp_avg_rtt|0|默认不使用平滑|
|-use_reps|0|默认单路径传输|
|-planes|1|默认单平面拓扑|
|-queue_type|composite_ecn|推荐搭配 ECN 启用队列|
|-mtu|4150|默认包大小（与 UEC 一致）|



### 🧩 RoCE 参数说明（RDMA over Converged Ethernet）

> RoCE 模拟以太网无损传输环境，结合 DCQCN 拥塞控制与 PFC 流控机制。  
> 其核心参数涵盖链路层流控、ECN 阈值、自适应路由与 NIC 行为配置。

---

#### 🧠 拥塞控制参数

|参数名|含义|说明|
|---|---|---|
|-dcqcn|启用 DCQCN 拥塞控制|激活 DCQCN 模块，并设置 ECN 阈值（包数）。|

---

#### 🚦 PFC（Priority Flow Control）参数

|参数名|含义|说明|
|---|---|---|
|-pfc_thresholds|PFC 阈值|设置优先级流控的低、高阈值，用于无损队列触发与恢复。|

---

#### ⚙️ NIC 与链路层行为

|参数名|含义|说明|
|---|---|---|
|-nic_burst|NIC 突发包数|限制每次突发发送的包数，控制发送速率平滑度。|
|-out_of_order|启用乱序接收|允许接收端按乱序接收包，测试可靠性与重排机制。|

---

#### 🧭 路由与负载均衡

|参数名|含义|说明|
|---|---|---|
|-ar_method|自适应路由方法|选择路径评估依据。支持 pause、queue、bandwidth、flowcount、pqb、pq、pb、qb。|

---

#### 🧰 示例配置片段

```bash
# 启用 DCQCN 拥塞控制，阈值设为 30
./htsim_roce -tm connection_matrices/one.cm -dcqcn 30

# 配置 PFC 高低阈值并启用无损输入队列
./htsim_roce -tm connection_matrices/perm_16n_16c.cm -queue_type lossless_input -pfc_thresholds 10 30

# 自适应路由实验：基于队列长度
./htsim_roce -tm connection_matrices/perm_32n_32c.cm -ar_method queue

# 测试 NIC 突发与乱序接收
./htsim_roce -tm connection_matrices/incast_128.cm -nic_burst 8 -out_of_order
```

---

#### 🧩 默认值与典型配置

|参数|默认值|说明|
|---|---|---|
|-queue_type|lossless_input|默认使用输入端无损队列|
|-dcqcn|关闭|需显式启用|
|-pfc_thresholds|未设置|必须成对使用（低阈值 高阈值）|
|-mtu|4000|默认包大小|
|-linkspeed|100000|推荐设置为 100Gbps|
|-ar_method|无|默认 ECMP 路由，不进行自适应选择|

---

#### 🧩 参数交互提示

- `-queue_type lossless_input` 与 `-pfc_thresholds` 必须配合使用，否则无损流控无法触发。
    
- `-dcqcn` 参数与 ECN 阈值密切相关，不同链路速度下需调整。
    
- 自适应路由 (`-ar_method`) 与传统 ECMP 可独立启用，用于评估路径动态选择性能。
    

### ⚡ NDP 参数说明（Network Datagram Protocol）

> NDP 模拟一种无状态的高速数据中心传输协议，  
> 特点是短 RTT、零队列积压以及“请求-数据-确认”三阶段机制。  
> 参数主要集中在拥塞控制、路径突发与窗口控制。

---

#### 🧠 拥塞与控制参数

|参数名|含义|说明|
|---|---|---|
|-oversubscribed_cc|启用过载拥塞控制|启用接收端基于过载检测的反馈控制，用于高负载场景。|

---

#### 🚀 传输机制与流控制

|参数名|含义|说明|
|---|---|---|
|-rts|启用请求发送机制|启用 RTS (Request To Send) 模式，使发送端先发送请求包再启动数据传输。|
|-path_burst|路径突发包数|限制单条路径连续可发送的数据包数量，用于路径间速率平衡。|
|-cwnd|拥塞窗口大小|设置初始拥塞窗口，控制并发传输速率。|

---

#### 🧰 示例配置片段

```bash
# 启用请求发送机制与固定突发
./htsim_ndp -tm connection_matrices/one.cm -rts -path_burst 4

# 使用过载控制与较小窗口
./htsim_ndp -tm connection_matrices/incast_128.cm -oversubscribed_cc -cwnd 8

# 高速多路径突发测试
./htsim_ndp -tm connection_matrices/perm_32n_32c_2MB.cm -path_burst 16 -cwnd 32
```

---

#### 🧩 默认值与典型配置

|参数|默认值|说明|
|---|---|---|
|-rts|关闭|默认直接发送数据，不使用 RTS。|
|-oversubscribed_cc|关闭|默认无过载控制机制。|
|-path_burst|未定义|需显式设置，典型值 4–16。|
|-cwnd|未定义|默认由算法自适应确定。|
|-mtu|9000|默认最大包大小（Jumbo Frame）。|
|-queue_type|composite|默认队列类型（有损）。|

---

#### 🧩 参数交互提示

- 启用 `-rts` 可显著改善大规模 incast 场景下的公平性，但会带来额外延迟。
    
- `-path_burst` 与 `-cwnd` 参数共同决定速率平衡与突发性能。
    
- `-oversubscribed_cc` 可与 `-rts` 配合使用，以评估接收端反馈在高并发环境中的响应能力。
    

### 🌀 Swift 参数说明（Swift Congestion Control）

> **Swift** 是一种基于速率反馈的、低延迟的拥塞控制算法，  
> 通过包级别的延迟估计实现快速调节速率。  
> 其设计与 UEC、EQDS 不同，Swift 更强调发送端自适应与多子流控制。

---

#### 🧠 拥塞与速率控制

|参数名|含义|说明|
|---|---|---|
|-cwnd|拥塞窗口大小|设置发送端初始拥塞窗口，用于控制初始速率。|
|-flowsize|流大小|指定单个流的传输大小（字节）。|
|-target|目标 RTT|拥塞控制目标 RTT（单位微秒），用于计算速率调整。|
|-g|增益系数|控制速率调整灵敏度（增益越大，反应越快）。|

---

#### 🌐 多子流与负载均衡

|参数名|含义|说明|
|---|---|---|
|-subflows|子流数量|启用多子流机制，将单一流拆分为多个并行路径。|
|-plb|启用包级负载均衡|Packet-Level Balancing，在多路径之间动态选择路径。|

---

#### ⚙️ 其他控制与实验选项

|参数名|含义|说明|
|---|---|---|
|-slow_start|启用慢启动|启动阶段采用指数增长窗口（默认关闭）。|
|-ecn|ECN 阈值|启用 ECN 标记阈值机制，结合 RTT 控制速率。|

---

#### 🧰 示例配置片段

```bash
# 基本 Swift 拥塞控制实验
./htsim_swift -tm connection_matrices/one.cm -cwnd 10 -target 50 -g 0.5

# 启用多子流与包级负载均衡
./htsim_swift -tm connection_matrices/perm_32n_32c_2MB.cm -subflows 4 -plb -target 40 -g 0.3

# 启用 ECN 并结合慢启动
./htsim_swift -tm connection_matrices/incast_128.cm -ecn 5 -slow_start -target 60
```

---

#### 🧩 默认值与典型配置

|参数|默认值|说明|
|---|---|---|
|-subflows|1|默认单路径|
|-plb|关闭|默认禁用包级负载均衡|
|-cwnd|10|默认初始窗口|
|-target|50|默认目标 RTT（μs）|
|-g|0.5|默认增益系数|
|-ecn|关闭|默认不启用 ECN|
|-queue_type|composite|默认队列类型|
|-mtu|4150|默认包大小|

---

#### 🧩 参数交互提示

- `-target` 与 `-g` 共同决定速率调整的平衡点；较小的 `target` 值可实现更低延迟，但易振荡。
    
- 启用 `-subflows` 后可结合 `-plb` 实现 Swift-MPTCP 式的多路径并行传输。
    
- 当开启 `-ecn` 时，Swift 的速率反馈会结合 RTT 与 ECN 双信号进行速率控制。
    

### 🌐 TCP 参数说明（Transmission Control Protocol）

> **TCP 模拟**用于与其他协议（UEC、EQDS、RoCE、Swift、NDP）对比，  
> 评估传统基于拥塞窗口的可靠传输机制在数据中心网络下的表现。  
> 参数主要控制拥塞窗口、流量规模、RTT 与 ECN 行为。

---

#### 🧠 拥塞控制参数

|参数名|含义|说明|
|---|---|---|
|-cwnd|初始拥塞窗口|设置 TCP 连接的初始拥塞窗口（以包为单位）。|
|-min_rtt|最小 RTT|指定估计的最小往返时延（微秒），用于延迟采样基准。|
|-ecn|启用 ECN|启用 ECN（显式拥塞通知）标记机制。|
|-ecn_thresh|ECN 阈值|设置 ECN 标记触发的队列深度（包数）。|

---

#### 🚀 流与连接控制

|参数名|含义|说明|
|---|---|---|
|-flowsize|流大小|设置单个 TCP 流的传输大小（字节）。|
|-flow_type|流类型|指定流量类型，可选 websearch、uniform、pareto、incast。|
|-conn_reuse|启用连接复用|允许多次使用相同连接以减少握手成本。|

---

#### ⚙️ 性能与调度选项

|参数名|含义|说明|
|---|---|---|
|-queue_type|队列类型|选择 TCP 使用的交换机队列类型：composite、composite_ecn、lossless_input。|
|-host_queue_type|主机队列类型|设定主机端调度器策略（如 prio、fair、swift）。|

---

#### 🧰 示例配置片段

```bash
# 基础 TCP 模拟，带初始窗口设置
./htsim_tcp -tm connection_matrices/one.cm -cwnd 10 -flowsize 1MB

# 启用 ECN 并设定阈值
./htsim_tcp -tm connection_matrices/perm_32n_32c.cm -ecn -ecn_thresh 20

# 使用 composite_ecn 队列进行延迟反馈
./htsim_tcp -tm connection_matrices/incast_64.cm -queue_type composite_ecn -flow_type incast
```

---

#### 🧩 默认值与典型配置

|参数|默认值|说明|
|---|---|---|
|-cwnd|10|初始窗口大小|
|-flowsize|1MB|单流传输大小|
|-flow_type|uniform|默认均匀流量分布|
|-ecn|关闭|默认关闭 ECN|
|-ecn_thresh|20|推荐值（包数）|
|-queue_type|composite|默认队列类型|
|-mtu|4150|默认包大小|
|-host_queue_type|prio|默认主机调度类型|

---

#### 🧩 参数交互提示

- 开启 `-ecn` 与使用 `composite_ecn` 队列搭配效果最佳，可避免过多丢包。
    
- `-flow_type` 决定流量分布模型，对整体 RTT 和公平性影响较大。
    
- 当与 UEC、EQDS 对比时，可保持相同的 `-flowsize` 与 `-mtu` 参数以确保可比性。
    
