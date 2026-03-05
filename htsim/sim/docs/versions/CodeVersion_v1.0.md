# htsim 代码版本说明 v1.0

> **版本标识**: `30f3ab3` (dev branch, commit #383)  
> **版本日期**: 2026-02-03  
> **文档编写日期**: 2026-03-04  
> **性质**: 首个完整版本文档（后续版本将以增量描述为主）

---

## 1 版本概述

htsim 是一个**事件驱动的高性能数据中心网络仿真器**，主要用于 UEC (Ultra Ethernet Consortium) 传输协议的研究与开发。本版本包含 7 种完整的传输协议实现、8 种数据中心拓扑、完整的 Python 分析工具链，以及基于 YAML 的批量实验框架。

### 代码规模

| 层 | 语言 | 文件数 | 代码行数 |
|:---|:---|:---|:---|
| 仿真引擎 (`src/`) | C++ | 145 | ~9,600 |
| 数据中心 (`datacenter/`) | C++ | 33 | ~1,400 |
| 入口程序 (`main/`) | C++ | 12 | — |
| 分析工具 (`analysis/`) | Python | 34 | ~11,200 |
| **合计** | — | **224** | **~22,200** |

---

## 2 项目结构

```
htsim/sim/
├── CMakeLists.txt              # 构建配置（C++17, htsim 静态库）
├── src/                        # C++ 仿真引擎源码
│   ├── core/                   #   事件系统、网络抽象、路由
│   ├── components/             #   队列、管道、交换机
│   ├── protocols/              #   传输协议实现
│   ├── packets/                #   数据包类型定义
│   ├── logging/                #   日志系统
│   ├── models/                 #   物理模型（PCIe, OversubscribedCC）
│   └── utils/                  #   工具类
├── main/                       # 各协议的 main 入口（12 个可执行文件）
├── datacenter/                 # 数据中心拓扑与流量生成
│   ├── topologies/             #   8 种拓扑（FatTree 为主力）
│   ├── traffic/                #   连接矩阵生成
│   ├── control/                #   NIC 模型
│   └── utils/                  #   拓扑工具
├── analysis/                   # Python 分析工具链
│   ├── config/                 #   实验配置、流量模式、LHS 采样
│   ├── parser/                 #   二进制日志解析器
│   ├── data/                   #   数据抽象层（ExperimentResult, BatchResult）
│   └── viz/                    #   可视化引擎（AutoVisualizer）
├── tools/                      # 辅助工具（launcher, 可视化脚本）
├── docs/                       # 文档
├── data/                       # 数据资源（流量 trace 等）
└── experiments/                # 实验 YAML 配置
```

### 构建系统

- **工具**: CMake ≥ 3.16, C++17 (GCC/Clang)
- **核心库**: `htsim` 静态库（编译 `src/` 下所有源文件）
- **可执行文件**: 自动扫描 `main/` 下所有 `main_*.cpp`，生成 `htsim_*` 可执行文件
  - **默认构建**: 仅 `htsim_uec`（其余设置 `EXCLUDE_FROM_ALL`）
  - 符号链接自动创建到 `bin/` 目录
- **测试**: 可选 GoogleTest (`-DENABLE_TESTS=ON`)
- **编译选项**: `-O3 -Wall -g`，**asserts 始终启用**（不使用 `-DNDEBUG`）

```bash
# 典型构建流程
mkdir build && cd build
cmake ..                     # 默认只构建 htsim_uec
cmake --build . -j$(nproc)

# 构建所有协议
cmake --build . --target htsim_ndp htsim_roce htsim_swift ...
```

---

## 3 C++ 仿真引擎

### 3.1 核心框架 (`src/core/`)

#### EventList — 事件驱动引擎

仿真器的心脏。基于 `std::multimap<simtime_picosec, EventSource*>` 的**单线程事件调度器**。

- **精度**: 皮秒级时间戳
- **调度**: `doNextEvent()` 从 multimap 头部取出最近事件并执行
- **Handle 机制**: 支持通过 `sourceIsPendingGetHandle()` 获取迭代器 Handle，用于 O(1) 取消定时器
- **Trigger**: 即时执行的触发器（零延迟），LIFO 顺序

```mermaid
graph LR
    A[EventSource] -->|sourceIsPending| B[multimap 队列]
    B -->|doNextEvent| C[取出最早事件]
    C -->|执行| A
```

> **已知问题**: `cancelPendingSourceByHandle` 中的 assert 顺序错误（先解引用 handle 再检查 end()），详见 [[Handle与Timer有效性审查报告]]

#### Network — 网络抽象

定义了仿真器的基础类型体系：

| 类 | 职责 |
|:---|:---|
| `Packet` | 包基类（size, type, flags, route, priority） |
| `PacketSink` | 接收包的接口（所有队列、管道、协议端点） |
| `PacketFlow` | 流标识与统计 |
| `DataSource` / `DataReceiver` | 传输层源/宿抽象 |

#### Route — 路由

`Route` 是一个 `PacketSink*` 的有序列表，表示包从源到宿经过的 hop 序列（Queue → Pipe → Queue → Pipe → ...）。

### 3.2 网络组件 (`src/components/`)

#### 队列体系

htsim 实现了 **20+ 种队列变体**，所有队列继承自 `BaseQueue`。核心层次：

```
BaseQueue (虚基类)
├── Queue (标准 FIFO, 带 drop-tail)
│   ├── CompositeQueue      ← UEC/NDP 交换机核心（High + Low 双队列 + Packet Trimming）
│   ├── ECNQueue            ← DCTCP 使用（ECN 标记）
│   ├── ECNPrioQueue        ← 多优先级 + ECN
│   ├── AeolusQueue         ← 含推测层
│   ├── LosslessQueue       ← PFC 无损（用于 RoCE）
│   ├── LosslessInputQueue  ← 入口无损队列
│   ├── LosslessOutputQueue ← 出口无损队列
│   ├── RandomQueue         ← 随机丢包
│   └── ...
├── HostQueue
│   ├── PriorityQueue       ← 主机端优先级调度
│   └── FairPriorityQueue   ← 公平优先级调度
```

**CompositeQueue**（UEC 核心）：
- 维护 High Priority Queue（控制包/Trimmed 包）和 Low Priority Queue（数据包）
- WRR 调度权重 **High : Low = 100,000 : 1**（实质为严格优先级）
- 支持 **Packet Trimming**：低优队列满时将 4KB 数据包裁剪为 64B Header，晋升至高优队列

#### Pipe — 传播延迟

模拟链路传播延迟。每个 Pipe 在包进入时注册一个未来事件，到时间后将包交给下一个 `PacketSink`。

#### Switch

交换机容器类，持有端口列表 (`vector<BaseQueue*>`)。负责端口注册和 PAUSE 帧广播。**缓冲模型**：每个端口队列各自持有独立的 `_maxsize` 缓冲，交换机级不做任何感知或共享管理。这意味着在大规模 Incast 场景下，单个队列满后立即开始 Trim，无法借用其他端口的空余缓冲。（共享缓冲架构在本版本中尚未实现，架构方案见 `共享缓冲区实现第一性原理分析.md`。）

### 3.3 协议实现 (`src/protocols/`)

#### UEC — 主力协议 (113KB)

htsim 中最完整、最复杂的协议实现，包含以下核心模块：

| 模块 | 文件 | 职责 |
|:---|:---|:---|
| **UecSrc** | `uec.cpp/h` | 发送端引擎：CC 算法、SLEEK 丢包恢复、Probe 探测、RTO |
| **UecSink** | `uec.cpp/h` | 接收端：SACK、OOO 处理、Pull/Credit 机制 |
| **UecNIC** | `uec.h` | NIC 层：WRR 调度（数据:控制 = 1:10）、双队列架构 |
| **UecPullPacer** | `uec.cpp/h` | 接收端速率控制器（Credit 发放节奏） |
| **UecPdcSes** | `uec_pdcses.cpp/h` | PDC 消息层（消息状态机、连接复用） |
| **UecMultipath** | `uec_mp.cpp/h` | 5 种多路径策略（Oblivious, Bitmap, REPS, REPSLegacy, Mixed） |

**拥塞控制算法**:
- **NSCC** (默认): 周期性聚合的 AIMD 算法（`fair_increase`, `proportional_increase`, `multiplicative_decrease`, `quick_adapt` → `fulfill_adjustment`）
- **DCTCP**: 经典 ECN 反馈算法
- **CONSTANT**: 固定窗口（测试用）

**丢包恢复（3 层机制）**:

| 层 | 机制 | 触发条件 | 速度 | 流末尾有效 |
|:---|:---|:---|:---|:---|
| 1 | **NACK/TRIM** | 交换机丢包/裁剪 | ⚡ 即时 | ✅ |
| 2 | **SLEEK** | SACK 累积 OOO 达阈值 | 🚀 快（需积累） | ❌ |
| 3 | **RTO** | 超时 | 🐌 慢 | ✅ |

**SLEEK 关键参数**（本版本默认值）：
- 重传阈值：`threshold = min(loss_retx_factor × cwnd, maxwnd)`，下限 `min_retx_config × avg_pkt_size`
- 默认需要约 **31 个 OOO 包**才触发（`factor=0.5, cwnd=64pkt`），对流末尾单包乱序**无效**
- Probe 定时器：无数据时 `now + base_rtt + target_Qdelay`；有 backlog 时 `now + first_trial × base_rtt`
- 收到 Probe ACK 且延迟 `< target_Qdelay` 时触发 `_loss_recovery_mode`

**ACK 保底机制状态**（本版本）：

| 机制 | 状态 | 说明 |
|:---|:---|:---|
| **GEN_ACK_TIMER** | ❌ 缺失 | `UecSink` 不继承 `EventSource`，无法注册定时器 |
| **AR Flag** | ✅ | 最后一包置 AR，接收端 `force_ack=true` |
| **ACK on ECN** | ✅ | ECN 标记包立即回 ACK |
| **Probe CP** | ✅ | `set_probe_ack(true)` 已修复 |

**数据包类型**: DATA, DATA_RTX, DATA_PROBE, DATA_SPEC, ACK, NACK, PULL, RTS

**Packet Trimming 流程**：
```
交换机低优队列满 → 包头 64B 保留 → 晋升高优队列
接收端 processTrimmed() → 发送 NACK → 发送端入 _rtx_queue
```

**已知问题**:
- ❌ 接收端 OOO 分支不回 ACK（`processData` L2703-2707 缺 `force_ack=true`），导致流末尾死锁
- ❌ 缺少 `GEN_ACK_TIMER` 保底定时器（根本原因）
- ❌ 指令式 Probe（`_probe_payload_psn` 字段）未实施
- ⚠️ Probe 优先级为 `PRIO_MID`，拥塞时可能被 Trim

#### 其他协议

| 协议 | 代码量 | 特点 |
|:---|:---|:---|
| **EQDS** | 77KB | Enhanced Queue Delay Sensing，DCTCP CC，REPS 多路径 |
| **NDP** | 72KB | Network Datagram Protocol，Header-based CC，Packet Trimming |
| **Swift** | 38KB | Delay-based CC，PLB 负载均衡，子流 |
| **TCP** | 23KB | 标准 TCP（含 DCTCP, Transfer 模式） |
| **HPCC** | 15KB | High Precision CC，INT 带内网络遥测 |
| **RoCE** | 14KB | RDMA over Converged Ethernet，DCQCN，PFC |
| **其他** | — | CBR, MTCP, QCN, STrack, NDPTunnel |

### 3.4 数据包定义 (`src/packets/`)

每种协议有专属的包类型文件（`*packet.h/cpp`）。所有包继承自 `Packet` 基类，定义了 3 级优先级：

| 优先级 | 枚举 | 用途 |
|:---|:---|:---|
| High | `PRIO_HI` | 控制包（ACK/NACK/PULL/RTS）+ Trimmed Header |
| Medium | `PRIO_MID` | 正常数据包 + 重传包 + Probe |
| Low | `PRIO_LO` | 推测性数据包 (DATA_SPEC) |

详见 [[UEC_Packet_Priority_Architecture]]

### 3.5 日志系统 (`src/logging/`)

#### 二进制日志底层

`Logfile` 将所有日志以**固定 44 字节/记录**的二进制格式写入磁盘：

| 字段 | 类型 | 大小 |
|:---|:---|:---|
| Time | `double` | 8B |
| Type | `uint32_t` | 4B |
| ID | `uint32_t` | 4B |
| Event | `uint32_t` | 4B |
| Val1-3 | `double × 3` | 24B |

#### QueueLogger 4 级体系

| Logger 类 | 启用参数 | 粒度 | 开销 |
|:---|:---|:---|:---|
| `QueueLoggerSimple` | (需改代码) | 逐包 | 🔴 极高 |
| `QueueLoggerSampling` | `-log tor_downqueue` | 10μs 窗口 (Min/Max/Last) | 🟢 低 |
| `MultiQueueLoggerSampling` | `-log switch` | 交换机聚合 | 🟡 中 |
| `QueueLoggerEmpty` | `-log queue_usage` | 利用率/Trim 率 | 🟢 极低 |

详见 [[队列相关日志组件梳理@htsim]]

#### 协议专用日志

- **UecTrafficLogger** (`uec_logger.cpp`): 记录 UEC 包类型（DATA/PROBE/SPEC/RX/ACK 等），使用 `UEC_TRAFFIC` 事件标识
- **EqdsLogger** / **DcqcnLogger**: 各自协议的专用日志

### 3.6 物理模型 (`src/models/`)

| 模型 | 文件 | 功能 |
|:---|:---|:---|
| **PCIeModel** | `pciemodel.cpp/h` | 模拟 Host↔NIC 的 PCIe 带宽瓶颈。令牌桶 + 二次函数反压。Backlog 超限时触发 Packet Trimming。 |
| **OversubscribedCC** | `oversubscribed_cc.cpp/h` | 接收端简易流控算法。忽略 Last Hop Trim，对 Other Hop Trim/ECN 执行 AIMD 减速。 |

### 3.7 工具类 (`src/utils/`)

| 工具 | 功能 |
|:---|:---|
| `ModularVector` | 环形缓冲区，用于接收端 SACK Bitmap (`ModularVector<uint8_t, 16384>`) |
| `Matrix` | 矩阵容器 |
| `Meter` | 速率计量 |
| `Trigger` | 异步触发器（用于流完成通知等） |

---

## 4 数据中心拓扑 (`datacenter/`)

### 4.1 拓扑类型

| 拓扑 | 文件 | 代码量 | 说明 |
|:---|:---|:---|:---|
| **FatTree** | `fat_tree_topology.cpp` | 81KB | **主力拓扑**，支持 2/3 层，自适应路由(6 种 AR 方法)，多平面 |
| OversubscribedFatTree | `oversubscribed_fat_tree_topology.cpp` | 14KB | 过载场景 |
| MulthomedFatTree | `multihomed_fat_tree_topology.cpp` | 17KB | 多归属 |
| DragonFly | `dragon_fly_topology.cpp` | 29KB | 蜻蜓拓扑 |
| BCube | `bcube_topology.cpp` | 11KB | BCube 拓扑 |
| VL2 | `vl2_topology.cpp` | 11KB | VL2 拓扑 |
| Star | `star_topology.cpp` | 3KB | 星形（测试用） |
| Generic | `generic_topology.cpp` | 15KB | 通用拓扑（自定义文件） |

### 4.2 FatTreeSwitch

`FatTreeSwitch`（20KB）实现了交换机内部的路由逻辑，支持 6 种自适应路由方法：

- `pause`: 基于 PFC PAUSE 状态
- `queue`: 基于队列深度
- `bandwidth`: 基于可用带宽
- `flowcount`: 基于活跃流数
- `pqb`, `pq`, `pb`, `qb`: 组合方法

### 4.3 流量生成

**ConnectionMatrix** (`connection_matrix.cpp`, 31KB) 生成连接矩阵文件 (`.tm`)，支持 9 种流量模式：

1. `permutation` — 随机排列
2. `incast` — Incast 收敛
3. `allreduce` — AllReduce 集合通信
4. `allreduce_butterfly` — 蝶形 AllReduce
5. `outcast_incast` — 混合 Outcast+Incast
6. `permutation_full_bisection` — 全等分排列
7. `serial_alltoall` — 串行 All-to-All
8. `serialn_alltoall` — N 并行 All-to-All
9. `serialn_alltoall_prio` — 带优先级的 N 并行 All-to-All

---

## 5 Python 分析层 (`analysis/`)

### 5.1 配置与运行 (`config/`)

| 文件 | 功能 |
|:---|:---|
| `experiment.py` (28KB) | 实验展开引擎：解析 YAML，笛卡尔积参数组合，子实验管理，模拟器调用 |
| `traffic_patterns.py` (29KB) | 9 种流量模式的 Python 生成器（输出 `.tm` 文件） |
| `sampling.py` (10KB) | LHS 拉丁超立方采样、正交采样、连续/对数连续变量 |
| `status.py` (4KB) | 实验运行状态管理 |

**运行入口**：
```bash
cd htsim/sim
python run.py experiments/my_config.yaml        # 单配置运行
python run.py experiments/my_config.yaml --lhs 50 # LHS 采样 50 组
```

**YAML 配置结构**（最小示例）：
```yaml
traffic:
  type: incast           # permutation / incast / allreduce / ...
  n_senders: 32
  load: 0.8

simulation:
  topology: fattree
  k: 8                   # FatTree 规模（k=8 → 128 主机）
  linkspeed: 100Gbps
  buffer: 200KB          # 每端口缓冲
  duration: 5ms

protocol: uec
params:
  cc_mode: [nscc, dctcp]     # 列表 → 笛卡尔积展开
  cwnd: [32, 64, 128]
  enable_sleek: [true, false]
  multipath: reps
```

**关键 UEC 参数一览**（本版本 `main_uec.cpp`）：

| 参数 | 说明 | 典型值 |
|:---|:---|:---|
| `-cc` | CC 模式 | `nscc` / `dctcp` / `constant` |
| `-cwnd` | 初始窗口 (pkts) | 32–128 |
| `-enable_sleek` | 开启 SLEEK 丢包恢复 | `1` |
| `-enable_multipath` | 多路径策略 | `reps` / `oblivious` |
| `-log` | 日志级别 | `tor_downqueue` / `switch` / `queue_usage` |
| `-debug` | 逐包调试（指定 flow ID）| 慎用，输出极大 |
| `-target_qdelay` | 目标队列延迟 | `10us` |
| `-base_rtt` | 基准 RTT | `4us`（k=8, 100G 拓扑）|

### 5.2 日志解析 (`parser/`)

二进制日志需经 `parse_output.cpp` 解码为文本格式，再由 Python 解析器读取。

| 解析器 | 数据源 | 输出 |
|:---|:---|:---|
| `idmap.py` (18KB) | `-o` 日志 + idmap | 对象 ID ↔ 名称映射，拓扑感知 |
| `queue.py` (11KB) | 队列日志 | DataFrame: QueueID, Time, Min/Max/LastQ, Dropped, Idle |
| `flow_debug.py` (10KB) | `-log traffic -debug` | 逐包追踪 DataFrame（发送/接收/ACK/NACK 时间线） |
| `collective.py` (14KB) | flow_events | 集合通信完成时间(CCT)分析 |
| `flow.py` / `sink.py` | flow_events / sink | FCT、吞吐量 |
| `nic.py` | NIC 日志 | NIC 层统计 |
| `cwnd.py` | `-debug` 输出 | CWND/InFlight 追踪 |
| `traffic.py` | traffic 日志 | 流量事件 |

### 5.3 数据抽象层 (`data/`)

| 类 | 文件 | 功能 |
|:---|:---|:---|
| **ExperimentResult** | `fileinfo.py` (38KB) | 单实验数据枢纽。懒加载 + 缓存。提供 `flow_df`, `queue_df`, `nic_df`, `switch_df` 等统一 API。自动注入拓扑名称。 |
| **BatchResult** | `batch.py` (91KB) | 批量实验分析。加载目录下所有子实验，提供 `plot_pivot`, `plot_generic`, CDF, 参数空间探索等。 |
| `metrics.py` | `metrics.py` (3KB) | 指标计算工具 |

**典型分析流程**：
```python
from analysis.data.fileinfo import ExperimentResult
from analysis.data.batch import BatchResult

# 单次实验
er = ExperimentResult("out/exp_001")
flow_df  = er.flow_df()    # FCT, 吞吐量; 列: flow_id, fct, tput, ...
queue_df = er.queue_df()   # 队列占用; 列: queue_id, time, minq, maxq, dropped
nic_df   = er.nic_df()     # NIC 层统计

# 批量实验（笛卡尔积目录）
br = BatchResult("out/sweep_cwnd/")
br.plot_pivot(x="cwnd", y="p99_fct", hue="cc_mode")   # 参数对比图
br.plot_cdf("fct", group_by="cwnd")                    # FCT CDF
```

### 5.4 可视化 (`viz/`)

| 模块 | 文件 | 功能 |
|:---|:---|:---|
| **AutoVisualizer** | `autoreport.py` (78KB) | 全自动报告生成引擎。"Thin View" 架构（不做数据处理，完全信任 ExperimentResult 输出）。 |
| CDF | `cdf.py` (6KB) | 独立 CDF 绘图工具 |

**AutoVisualizer 主要图表**：

| 图表 | 功能 | 启用条件 |
|:---|:---|:---|
| Full Stack Analysis | 逐包时序图（Src发送/Sink接收/ACK/NACK/CCT） | `-debug flowid` + `-log traffic` |
| Queue Waveform | 队列占用时序 + Trim 率 | `-log tor_downqueue` 或 `-log switch` |
| CC Diagnostics | CWND/InFlight/ECN 曲线 | `-debug flowid` |
| FCT CDF | 流完成时间分布 | 默认 |
| NIC Throughput | 发送/接收吞吐量 | 默认 |

**使用方式**：
```bash
# 自动生成单次实验报告
python -m analysis.viz.autoreport out/exp_001/
# 结果保存至 out/exp_001/report/
```

---

## 6 入口程序 (`main/`)

所有入口文件遵循统一模式：解析命令行参数 → 创建拓扑 → 创建连接 → 运行事件循环。

| 入口 | 可执行文件 | 大小 | 默认构建 |
|:---|:---|:---|:---|
| `main_uec.cpp` | `htsim_uec` | 46KB | ✅ |
| `main_ndp.cpp` | `htsim_ndp` | 32KB | ❌ |
| `main_eqds.cpp` | `htsim_eqds` | 29KB | ❌ |
| `main_roce.cpp` | `htsim_roce` | 27KB | ❌ |
| `main_hpcc.cpp` | `htsim_hpcc` | 24KB | ❌ |
| `main_tcp.cpp` | `htsim_tcp` | 16KB | ❌ |
| `main_swift.cpp` | `htsim_swift` | 16KB | ❌ |
| `main_simple.cpp` | `htsim_simple` | 9KB | ❌ |
| `main_test.cpp` | `htsim_test` | 6KB | ❌ |
| `main_003.cpp` | `htsim_003` | 10KB | ❌ |
| `main_002.cpp` | `htsim_002` | 5KB | ❌ |
| `main_001.cpp` | `htsim_001` | 1KB | ❌ |

`main_uec.cpp` 是功能最完整的入口，支持所有 UEC 参数（CC 模式、SLEEK、多路径、ECN、PDC 等）。

---

## 7 已知问题与待修复项

基于 [[BugReport_SilentPacket11|文档审计 (2026-03-04)]] 的代码交叉验证结果：

| 问题 | 严重性 | 状态 | 位置 | 相关文档 |
|:---|:---|:---|:---|:---|
| OOO 分支不回 ACK | 🔴 | 未修复 | `uec.cpp` processData L2703 | [[BugReport_SilentPacket11]] |
| 缺少 GEN_ACK_TIMER | 🔴 | 未实现 | `UecSink` 类 | 同上 |
| EventList assert 顺序错误 | 🟡 | 未修复 | `eventlist.cpp` L143-144 | [[Handle与Timer有效性审查报告]] |
| Probe 指令式协议未实施 | 🟡 | 未实施 | `uec.cpp` / `uecpacket.h` | [[UEC_Probe_Mechanism_Fixes_CN]] |
| Probe 优先级应为 HI | 🟢 | 未修改 | `uecpacket.h` priority() | [[UEC_Packet_Priority_Architecture]] |
| Bitmap 溢出直接 abort() | 🟡 | 未修改 | `uec.cpp` processData L2594 | [[UEC-htsim 实现详细报告]] |

**已修复的问题**:
- ✅ Probe ACK 标记 (`set_probe_ack(true)`)
- ✅ 僵尸 Probe 死循环（`_done_sending` 检查）
- ✅ Probe timer handle 重置为 `nullHandle()`

---

## 8 研究背景与当前关注点

> 本节记录截至 v1.0 时，研究工作的主要方向与关键发现。为 Obsidian 实验笔记提供背景语境。

### 8.1 核心研究场景：LLM 推理 Incast

**问题**：LLM 推理产生严重的 Incast 微突发（多个 GPU 同时向单一目标发送 KV Cache）。

**关键发现**：
- 增大单口缓冲对 Incast 无效（概率性 drop 时间窗口内，所有流同时到达）
- 问题根因是**规模依赖**：N 个发送方 → N 倍的瞬时速率冲击
- 交换机 Trim 产生 NACK → 引发全局重传 → 加剧拥塞（正反馈循环）
- NACK/ACK 丢失时 `_in_flight` 记账出现漂移 → CWND=1 时可能出现死锁
- **研究结论**：需要接纳控制(Admission Control)等架构级方案，而非参数调优

**当前仿真重点参数**：
```
k=8（128主机）、100Gbps、FatTree、incast 32→1
buffer: 200KB–800KB（对比组）
cc_mode: nscc / dctcp
enable_sleek: true
```

### 8.2 协议层待解决问题优先级

| 优先级 | 问题 | 影响 |
|:---|:---|:---|
| P0 | OOO 不回 ACK + 缺 GEN_ACK_TIMER | 流末尾死锁，直接影响所有仿真准确性 |
| P1 | EventList assert 顺序 | 潜在 crash（调试模式可见） |
| P2 | Probe 指令式协议 | Probe 触发快速重传能力缺失 |
| P3 | Probe 优先级 | 拥塞时 Probe 可能被 Trim，失效 |

### 8.3 分析工具链使用约定（本版本）

- 日志策略：常规实验使用 `-log switch`；调试特定流使用 `-debug <flowid> -log traffic`
- LHS 采样：高维参数空间使用 `--lhs 50`（50 组正交采样代替全笛卡尔积）
- 指标重点：P50/P99 FCT、Trim 率、CWND 稳定性、Incast 完成时间(CCT)

---

## 9 附录：模块文件统计

| 目录 | .cpp | .h | 合计 | 最大文件 |
|:---|:---|:---|:---|:---|
| `src/core/` | 5 | 7 | 14* | `network.h` (11KB) |
| `src/components/` | 20 | 20 | 40 | `queue.cpp` (17KB) |
| `src/protocols/` | 22 | 23 | 45 | `uec.cpp` (113KB) |
| `src/packets/` | 11 | 11 | 22 | `ndppacket.h` (16KB) |
| `src/logging/` | 6 | 4 | 13* | `loggers.cpp` (61KB) |
| `src/models/` | 2 | 2 | 4 | `oversubscribed_cc.cpp` (3KB) |
| `src/utils/` | 2 | 4 | 6 | `matrix.h` (4KB) |
| `datacenter/topologies/` | 9 | 10 | 19 | `fat_tree_topology.cpp` (81KB) |
| `analysis/viz/` | 2 | — | 3* | `autoreport.py` (78KB) |
| `analysis/data/` | 4 | — | 5* | `batch.py` (91KB) |

\* 含 `__init__.py` 或 `.h` only 文件
