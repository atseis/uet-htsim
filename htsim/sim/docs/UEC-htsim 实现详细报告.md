---
Resource:
  - "[[UEC@|UEC@]]"
  - "[[htsim@]]"
level: 4-🔧Mechanism
ctime: 2025-12-07 11:30:55
mtime: 2025-12-07 11:30:55
number headings:
  - first-level 2
Topics:
  - "[[UEC@]]"
  - "[[htsim@]]"
---
# UEC htsim 协议栈实现深度调研报告 (Master Reference)

> [!NOTE]
> **现状更新 (2026-03-04)**：
> - ⚠️ 本文档包含的外链图片 (`s1.vika.cn`, Excalidraw) 可能已不可访问
> - ⚠️ 文中引用的文件路径 `htsim/sim/uec.cpp` 应为 `src/protocols/uec.cpp`；`htsim/sim/uecpacket.h` 应为 `src/packets/uecpacket.h`
> - ✅ 核心协议机制描述（NSCC, Pacer, Packet Trimming, PDC, PCIe 等）仍然准确

版本： 2.0 (Stand-alone Final)

适用范围： UEC 传输层机制研究、RICC 算法开发、代码架构参考

## 1 系统宏观架构 (System Architecture)

`htsim` 的 UEC 实现构建了一个基于事件驱动的高性能网络模型。其核心架构由**端系统 (Host + NIC)** 和 **交换网络 (FatTree Switch)** 组成。与传统仿真不同，UEC 引入了物理隔离的优先级队列设计，以确保控制信令在拥塞场景下的生存能力。

**图 1 展示了宏观架构及数据/控制流的双轨运行机制：**
![图片格式转换_3769](https://s1.vika.cn/space/2025/12/29/79fe3b72203641869eb4e644e42c5852)

- 这里的 WRR 是 NIC 层的调度策略，在 `doNextEvent()` 当中实现：
	- 当有数据源和控制包都在等待发送时，系统会按照1:10的比例轮流处理
		- 1个时间片用于发送数据包（来自活跃的数据源）
		- 10个时间片用于发送控制包（ACK、NACK、Pull等）


## 2 数据包类型与协议定义 (Packet Definitions)

UEC 协议栈在 `htsim/sim/uecpacket.h` 中定义了一套完整的数据包类型谱系，涵盖了数据传输、流控和纠错。

| **包类型**  | **类名 (C++)**    | **关键字段 / 功能**                                                       | **优先级**                       |
| -------- | --------------- | ------------------------------------------------------------------- | ----------------------------- |
| **Data** | `UecDataPacket` | `_epsn` (序列号), `_pull_target` (流控请求), `_type` (DATA/RTX/PROBE/SPEC) | MID/LO (普通), HI (Header Only) |
| **Pull** | `UecPullPacket` | `_pullno` (信用额度), `_slow_pull` (推测性拉取标志)                            | **HI**                        |
| **ACK**  | `UecAckPacket`  | `_sack_bitmap` (选择性确认), `_ecn_echo`, `_rcv_wnd_pen` (窗口惩罚)          | **HI**                        |
| **NACK** | `UecNackPacket` | `_ref_epsn` (被剪包序列号), `_target_bytes` (期望字节), `_last_hop` (位置标识)    | **HI**                        |
| **RTS**  | `UecRtsPacket`  | Request To Send。当无 Credit 或超时时发送，请求接收端关注。                           | **HI**                        |

![图片格式转换_1365](https://s1.vika.cn/space/2025/12/29/8cf4b570e33243d88d3b62d044f32387)

注：
- 几种 Data(`_type`控制):
	- ![图片格式转换_8767](https://s1.vika.cn/space/2025/12/29/7426358b911c4b0aafaabe1bd3add0f0)
	- DATA_SPEC：当发送方**没有收到明确的 Pull Grant**（信用），但网络似乎空闲或刚开始启动时，发送方会 **“赌”一把**，提前发送数据
		- 优先级较低——这意味着如果网络拥塞，它会比正常数据包更容易被丢弃。这是为了利用空闲带宽而不阻塞正常流量
- Pull 流程：
	- ![图片格式转换_4009](https://s1.vika.cn/space/2025/12/29/80fb39c9241240bcb17f6f1e04389d7e)
	- Receiver 处双队列：
		- Active：有积压数据（Backlog>0）, `_slow_pull=false`，这里的 Credit 是为了传输实际数据，这里的 Credit 收 `pull_target`(实际需求)限制
		- Idle：无数据，维持连接活性， `_slow_pull=true`，提供推测性 Credit, 避免冷启动延迟，忽略 `pull_target`，固定给 Credit(因为本来就是用于维持火星的推测行 Credit)
	- `_slow_pull` 用于标记该 Pull 包是否来自“**慢速** Pull 队列”（Slow Pull Queue），与推测性发送（Speculative Sending）是不同的机制——慢速 Pull 用于处理接收端没有足够 backlog 时的流控
		- **正常 Pull**：响应实际的数据传输需求
		- **慢速 Pull**：向空闲发送端提供**推测性 Credit**，维持最多 1 BDP 的推测性传输能力
			- 收到 Pull 包后会**停止推测发送**模式（图中“开关”）
		- **目的：** 保持“**管道畅通**”。如果该流突然有数据产生，它不需要等待整整一个 RTT 去申请信用，而是可以直接利用这个“慢速拉取”积攒的信用直接发送（通常作为 `DATA_SPEC` 发送）。
- UecAckPacket 的惩罚机制：
	- `_rcv_wnd_pen` (Receive Window Penalty)：**接收端施加的窗口惩罚系数**（0-255）
		- **作用：** 这是一种**显式的反压（Backpressure）机制**。接收端根据自己的状态（比如接收 buffer 满了，或者检测到特定拥塞），告诉发送方：“虽然你没丢包，但请把发送窗口减小一点”。
		- **公式：** `window_decrease = newly_recvd_bytes * pkt.rcv_wnd_pen() / 255`
		- **理解：** 如果 `_rcv_wnd_pen` 是 255，表示没有惩罚；如果小于 255，发送方的 CWND 会按比例强制减小。这比单纯依赖丢包来降速更精细。
- UecNackPacket：NACK 不仅负责**可靠性（重传）**，还深度参与**拥塞控制（CC）**
	- `_ref_epsn`: 确实是需要重传的**序列号**
	- `_target_bytes`：捎带流控信息。在发 NACK 的同时，接收端顺便告诉发送方**当前的流控目标**（对应 `_rcv_cwnd_pen`——这样发送方在重传时，能立即调整窗口大小，避免重传包再次导致拥塞）
	- `_last_hop`: 指示丢包是否发生在**最后一跳**（即交换机到接收网卡这一段）
		- **逻辑：** `(pkt.nexthop() - pkt.trim_hop() - 2) == 0`
		- **为什么重要？** 区分**网络核心拥塞** vs **边缘拥塞**
			- 如果是中间交换机丢包，说明网络拥塞，发送方必须大幅降低 CWND
			- 如果是 Last Hop 丢包（可能是接收端处理不过来，或者 Packet Trimming 机制生效），代码逻辑是 `if (!_receiver_based_cc || !last_hop)`。意味着在某些配置下，如果是最后一跳丢包，发送方**不需要**大幅削减窗口（避免双重惩罚）。这对于保持高吞吐至关重要。
- RTS（Request To Send） 是一个**死锁恢复（Anti-Deadlock）与流重启机制**：
	- ![图片格式转换_5908](https://s1.vika.cn/space/2025/12/29/8556c67862f340a790357387935c8c5f)
	- 触发条件（主要是 RTO）：
		- ![Pasted image 20251207225141|500](https://s1.vika.cn/space/2025/12/29/575b9b5344b343468f9c2f4afa5e6d32)
		- **RTO 触发 + 有重传队列**：发送方超时了，且确实有数据在等待重传——告诉接收方“我还活着，我还有数据要发，但我卡住了（可能是之前的 ACK/Pull 丢了）。接收方收到 RTS 会补发 Pull 或 ACK
		- **RTO 触发 + 无信用 (Receiver-based)**：发送方想发数据，但 `_credit <= 0`，且长时间没收到 Pull（导致超时）
			- **目的：** 主动请求接收方：“给我发点 Credit 吧”
		- **RTO 触发 + 窗口不足 (Sender-based)**：`_cwnd` 满了，发不出去，且长时间卡住导致超时
			- **目的：** 类似于 TCP 的 Zero Window Probe，通过 RTS 探一下接收方，触发对方回 ACK 更新窗口

![[UEC-htsim 实现详细报告 2025-12-07 22.55.27.excalidraw|1000]]
一些数据：
- **MTU:** 4160 Bytes (4096 Payload + 64 Header)。
- **有效载荷效率:** ~98.46%。
    

**图 4 直观展示了协议栈结构与开销占比：**

![图片格式转换_8966](https://s1.vika.cn/space/2025/12/29/8437b3f48fa94d468b7f6c83098c5ce9)



## 3 发送端主机实现 (UecSrc)

**文件路径:** `htsim/sim/uec.cpp` & `.h`

`UecSrc` 是极其复杂的发送引擎，集成了拥塞控制、多路径选择和丢包恢复机制。

**图 5 展示了发送端处理 ACK 的完整流水线，清晰地描绘了从 RTT 测量、Bitmap 清理到算法调用的全过程：**


![图片格式转换_2933](https://s1.vika.cn/space/2025/12/29/f999a9f582ae4e5680c290a13002124a)


其架构包含 **3 种** 发送端算法与 **2 种** 控制模式（Sender-based vs Receiver-based）。

### 3.1 拥塞控制算法集 (Pluggable CC Algorithms)

UEC 并不把 RCCC 作为同级的发送算法，而是作为一种控制模式。
1. **NSCC (Network Sender Congestion Control) - 默认标准** UEC 的核心算法。代码验证显示其状态更新并非实时生效，而是基于**周期性聚合 (Periodic Aggregation)**。
    - **核心调节函数:**
        - `fair_increase()`: 累积公平增量。
        - `proportional_increase()`: 基于目标延迟累积比例增量（内部调用 `fast_increase`）。
        - `multiplicative_decrease()`: 基于 RTT 变大执行乘性减窗。
        - `quick_adapt()`: 空闲或剧烈变化后的快速重置。
    - **`fulfill_adjustment()` (关键机制):**
        - **功能:** 上述函数并不直接修改 `cwnd`，而是更新 `_inc_bytes`。只有当收到足够字节 (`_adjust_bytes_threshold`) 或时间阈值到达时，才调用此函数。
        - **逻辑:** 执行 `_cwnd += _inc_bytes / _cwnd`，并将累积量清零。这实现了类似 AIMD 的平滑效果，并处理 `eta` (常数项) 增加。
        - **步骤**：
	        - 除了 `_cwnd += _inc_bytes / _cwnd` 外，还会对统计数据进行归一化处理（除以 `_cwnd`）
			- 当时间阈值满足时，会额外添加 `_eta` 常数项：`_cwnd += _eta`
			- 最后重置 `_inc_bytes = 0` 和 `_received_bytes = 0`，并清空周期统计
	- 图 6 解构了 NSCC 的核心决策大脑，直观展示了四种增减模式如何汇聚至“累积池”以及最终的兑现逻辑：
		- ![图片格式转换_9348](https://s1.vika.cn/space/2025/12/29/08872ed758624d14a0e162a714d3e5f5)
2. **DCTCP:** 经典数据中心 TCP 实现。
3. **CONSTANT:** 固定窗口测试模式。

### 3.2 多路径路由策略 (Multipath Strategies)

`UecSrc` 负责为每个包生成 Entropy (Path ID)。代码完整实现了 **5 种** 策略：

1. **`UecMpOblivious`:** 盲轮询，带 XOR 随机化，不感知网络状态。
    
2. **`UecMpBitmap`:** 基于接收端反馈的 Bitmap，主动避开有丢包/拥塞记录的路径。
    
3. **`UecMpRepsLegacy`:** 旧版 REPS (Randomly Permuted Schedule) 实现。
    
4. **`UecMpReps`:** **现代版 REPS**。引入了 **Circular Buffer (环形缓冲区)** 来管理路径熵，支持 Trim 时的路径信息回收。
    
5. **`UecMpMixed`:** 结合 Bitmap 和 REPS Legacy 的混合策略。
    

### 3.3 SLEEK 丢包恢复 (Loss Recovery)

![图片格式转换_6154](https://s1.vika.cn/space/2025/12/29/ebb78180d2794be5b1c9eb5b62aa73f4)

- [[SLEEK 机制]]

实现了 **SLEEK (Selective Loss recovery with Explicit Ecn Knowledge)** 机制：

- **Probe Mechanism:** 当发生超时或长时间未收到 ACK 时，发送 `DATA_PROBE` 包探测路径活性。
    
- **Dynamic RTO:** 支持动态重计算重传超时（RTO），并能处理 `processEv(PATH_TIMEOUT)` 事件。
    
除了 Probe 和 Dynamic RTO，代码中固化了以下关键默认参数，这对 RICC 调优至关重要：

- **`loss_retx_factor = 1.5`**: 乱序容忍度系数。只有当 Gap > 1.5 * CWND 时才视为丢包。
    
- **`min_retx_config = 5`**: 最小重传阈值（包数）。
    
- **`probe_first_trial_time = 3`**: 首次探测等待时间 (RTT 倍数)。
---

## 4 接收端主机实现 (UecSink)

**文件路径:** `htsim/sim/uec.cpp` & `.h`

这是 **RICC 算法的主战场**。接收端通过 Pull 机制与发送端形成闭环控制。

### 4.1 乱序重组与内存模型

- **Bitmap:** 使用 `ModularVector<uint8_t, 16384>` 维护接收窗口。
    
- **严重隐患 (Crash Point):** 当前逻辑中，如果收到的包序列号 `gap > 16384 * MTU` (约 65MiB)，仿真器会直接调用 `abort()` 崩溃。
    
    - **RICC 修改要求:** 必须删除 `abort()`，改为 **Drop (丢包) + NACK (显式拒收)**。
        

### 4.2 Pacer (定速器) 与流控

- **Credit 机制:** 接收端通过发送 `Pull Packet` 授予发送端 Credit。
    
- **动态调整接口:** `UecPullPacer` 并非固定频率，它通过 `updatePullRate()` 接口根据以下因素动态调整间隔：
    
    - **PCIe 带宽:** 来自 `PCIeModel` 的反压。
        
    - **网络拥塞:** 来自 `OversubscribedCC` 的反馈。
        
    - **计算公式:** `Actual_Interval = Base_Interval / min(Rate_PCIe, Rate_Oversubscribed)`。
        

**图 3 展示了典型 Incast 场景下接收端 Pacer 介入的时序：**


![图片格式转换_0999](https://s1.vika.cn/space/2025/12/29/5ba7b85872e343d99fc6624fe03726fa)

## 5 网卡模型 (UecNIC)

**文件路径:** `htsim/sim/uec.h`

`UecNIC` 是主机与网络之间的调度器，其核心设计目标是**保护控制信令**。

- **双队列架构:**
    
    - `_active_srcs`: 包含有数据待发的源列表（轮询调度）。
        
    - `_control`: 包含待发的 ACK, NACK, Pull, RTS 等小包。
        
- **WRR 调度 (关键参数):**
    
    - **比例:** `Data : Control = 1 : 10`。
        
    - **逻辑:** NIC 每发送 1 个数据包，就有权发送 10 个控制包。
        
    - **目的:** 确保在 Incast 发送端，反向的 ACK/Pull 不会被数据流阻塞。
        

---

## 6 交换机转发与 Packet Trimming (Switching)

**文件路径:** `htsim/sim/compositequeue.cpp`

这是 UEC 区别于 RoCEv2 的物理层特性。

### 6.1 物理队列与严格优先级

交换机端口维护两个物理队列：

1. **High Priority Queue (高优):** 存放控制包、Trimmed 包。
    
2. **Low Priority Queue (低优):** 存放普通数据包。
    

**调度权重 (WRR):** **High : Low = 100,000 : 1** (此处纠正了 v1.2 的错误)。

- 这实际上实现了**严格优先级 (Strict Priority)**，只要高优队列有包，低优队列必须等待。
    

### 6.2 Packet Trimming 物理过程

当 Low Priority Queue 溢出或收到 PCIe 反压信号时：
- **Switch 动作:** 当低优队列溢出，调用 `pkt.strip_payload()`。
    - **结果:** 4160B 的完整包变身为仅含头部的 **Trimmed Packet** (Data Header，64B)。
    - **流向:** Trimmed Packet 进入高优队列，转发给**接收端**。
- **Receiver 动作:** 接收端收到 Trimmed Packet。
    - **识别:** 检测到包被截断。
    - **响应:** 调用 `processTrimmed()`，主动生成一个 **`UecNackPacket`** 发回给发送端。
- **Sender 动作:** 发送端收到 NACK，触发重传
- **延迟突变:**
    - 完整包延迟 (4160B): ~0.33 μs
    - 修剪包延迟 (64B): ~0.005 μs


**图 2 详细描述了这一 Trimming 物理过程及延迟变化：**

![图片格式转换_1063](https://s1.vika.cn/space/2025/12/29/2d83f5ad5d06402587338ce955c996b9)




## 7 高级特性详解 (Advanced Features Detailed)

`htsim` 的 UEC 实现超越了单纯的数据包转发模拟，它包含了一系列用于模拟真实数据中心行为的高级子系统。理解这些子系统对于 RICC 至关重要，因为它们是 RICC 算法运行的“物理环境”。

### 7.1 PDC 消息层抽象

**文件路径:** `htsim/sim/uec_pdcses.h`, `htsim/sim/uec_pdcses.cpp`

![图片格式转换_0006](https://s1.vika.cn/space/2025/12/29/cd9efb244dfa456c9b98c456530187ee)


PDC 层模拟了应用层如何产生流量。在 Incast 场景中，流量通常不是无限长流，而是由大量并发的 Message 组成的。

- **核心类与机制：**
    
    - **`UecMsg` (消息实体):** 每个 Message 都有独立的状态机。
        
        - 状态流转：`Init` (初始化) $\rightarrow$ `SentFirst` (首包发出) $\rightarrow$ `SentLast` (尾包发出) $\rightarrow$ `RecvdLast` (尾包收到) $\rightarrow$ `Finished` (全被 ACK)。
            
        - **RICC 关注点:** 只有当 Message 处于 `Finished` 状态时，才能计算完成时间 (FCT)。如果你的 RICC 导致死锁，Message 将永远卡在 `SentLast`。
            
    - **`UecPdcSes` (会话管理器):**
        
        - **Triggered vs. Scheduled:** 支持两种流量生成模式。“Triggered”用于模拟请求-响应（如 RPC），“Scheduled”用于重现特定的 Traffic Trace（如 Facebook Hadoop Trace）。
            
    - **连接复用 (Connection Reuse):**
        
        - `UecTransportConnection` 允许在同一个 5-tuple 连接上串行发送多个 Message。
            
        - **RICC 关注点:** RICC 的状态（如当前的 Credit 速率）在 Message 之间是否应该重置？如果不重置，上一个 Message 的拥塞状态可能会错误地抑制下一个 Message 的启动（这被称为 "Slow Start after Idle" 问题）。
            

### 7.2 PCIe 反压模型

**文件路径:** `htsim/sim/pciemodel.h`, `htsim/sim/pciemodel.cpp`

![图片格式转换_3398](https://s1.vika.cn/space/2025/12/29/d00ab267b9fb4ae3b82a7d4e4d6112fd)


这是一个被许多研究者忽视但极其实用的模块。它模拟了 Host 内存到 NIC 之间的 PCIe 总线瓶颈。

- **工作原理：**
    - **令牌桶机制：** 模型维护一个表示 PCIe 带宽的令牌桶。每当数据包从 NIC 进入 Host 内存，消耗令牌。
    - **Backlog 积压：** 当入站流量 > PCIe 带宽时，`_backlog` 增加。
    - PCIe 的反压并非简单的两级反馈，而是一个 **连续的二次函数 (Quadratic Function)** 调节过程 
		- **Rate 计算公式**
			- 当 `Backlog < _min_threshold`: `rate = 1.0` (全速)。
			- 当 `Backlog > _max_pcie_backlog * 0.95`: `rate = 0.001` (极限减速)。
			- **中间区间:** 使用二次函数平滑衰减，模拟 PCIe 缓冲区逐渐填满时的非线性压力。
		- **Hard Reject:** 当 `Backlog > _max_pcie_backlog`，直接返回 `false`，导致 NIC 入口处的 Packet Trimming 
			  - 返回 false 会导致交换机端对该数据包执行 Packet Trimming(调用 `strip_payload()`)，而非简单丢弃（这是 UEC 核心机制之一）
			
- **对 RICC 的影响:**
    
    - 如果你的 RICC 算法发现丢包（Trim）发生在**最后一跳 (Last Hop)**，这不仅可能是 Switch 拥塞，也可能是 PCIe 拥塞。你需要检查 NACK 包中的标志位来区分。
- **关于 Pacer:** PCIe 反压模型不仅限于 RCCC（Receiver Congestion Control），它可以在两种拥塞控制模式下工作——在 `UecSink` 的初始化中，PCIe 模型的设置与拥塞控制模式是分离的，关键区别在于 Pacer 的使用方式：
	- **RCCC 模式**：使用共享的 `UecPullPacer`，多个连接共享同一个 pacer
	-  **NSCC 模式**：每个连接有自己的 pacer，但 `receiver_based_cc` 被禁用

### 7.3 过载拥塞控制

**文件路径:** `htsim/sim/oversubscribed_cc.h`
![图片格式转换_6342](https://s1.vika.cn/space/2025/12/29/3b9bf736b3b84ef8ba860f8ebde81ec4)



这是 `htsim` 自带的一个简单的接收端流控算法，专门用于对抗 Incast。
- **核心逻辑:**
	- **Last Hop Trim (最后一跳修剪):** 算法**忽略**此类事件。
	    - _原因:_ 最后一跳修剪通常由接收端 PCIe 反压（见 7.2）引起，而非网络核心拥塞。
	- **Other Hop Trim (中间跳修剪):** 视为网络拥塞 $\rightarrow$ **触发减速 (Decrease)**。
	- **ECN:** 视为拥塞 $\rightarrow$ 触发减速。
- **算法公式 (AIMD):**
    - **Decrease:** 收到 Trim 时，`rate = rate * 0.5`。
    - **Increase:** 成功接收字节时，`rate += Alpha`。
- **对 RICC 的启示:** 你的 RICC 必须能区分 `Trimmed_Last_Hop` 和 `Trimmed_Other`，否则会将接收端 PCIe 瓶颈错误地当成网络带宽不足进行处理，导致吞吐量不必要地下降

## 8 辨析
### 8.1 Sender-based vs. Receiver-based 

- 具有混合模式：两种CC可以同时起作用
- Pacer 只在 RCCC 启用时控制 credit 的发放，不直接参与 NSCC 的发送决策
- **Pacer 的生命周期完全依赖于 `_receiver_based_cc` 标志**
- **只有明确启用 receiver-based CC 时（通过 `-receiver_cc` 或 `-receiver_cc_only`），Pacer 才会被创建和使用**
- NSCC 可以独立运行，不需要 Pacer
- RCCC 必须依赖 Pacer 来控制 credit 发放速率
- 混合模式下，两者协同工作，但 Pacer 仍然只服务于 RCCC 的 credit 控制
![图片格式转换_9512](https://s1.vika.cn/space/2025/12/29/4cf404b99f744e749ee7f221e13785b0)

![[UEC-htsim 实现详细报告 2025-12-08 10.06.58.excalidraw|800]]