# UEC Packet Priority Architecture

> **Date**: 2026-01-29
> **Component**: UEC Protocol Stack (HTSim)
> **Summary**: This document details the 3-tier packet priority system, data structures, and the dynamic priority transition mechanism ("Trim Promotion").

---

## 1. 优先级架构概览 (Priority Architecture)

UEC 协议栈采用 **3 层优先级设计 (3-Tier Priority System)**，旨在实现“控制优先、数据公平、推测让路”的调度策略。

| 优先级 (Priority) | 定义代码 (Enum) | 对应队列 (HW Queue) | 设计意图 (Design Intent) |
| :--- | :--- | :--- | :--- |
| **High** | `Packet::PRIO_HI` | **High Priority Queue** | 确保控制信令 (Control Plane) 永不丢失，维护协议状态机稳定，打破死锁。 |
| **Medium** | `Packet::PRIO_MID` | **Data Queue** | 承载正常的数据传输。如果发生拥塞，该队列的包会被标记 (ECN) 或裁剪 (Trim)。 |
| **Low** | `Packet::PRIO_LO` | **Data Queue** (Low Threshold) | 承载“推测执行”的数据 (Speculative Data)。在网络负载高时最先被丢弃。 |

---

## 2. 详细分类与数据结构 (Classification & Data Structures)

优先级判定逻辑位于 `uecpacket.h` 中的 `priority()` 虚函数。核心判据包含两个维度：**包类型 (PacketType)** 和 **头部标志位 (`_is_header`)**。

### A. High Priority (控制层)
*   **包含包类型**:
    *   `UEC_ACK` (Acknowledgments)
    *   `UEC_NACK` (Negative ACKs)
    *   `UEC_PULL` (Receiver Pull Requests) - *注意：Pull 包天生是 Header*
    *   `UEC_RTS` (Request to Send)
    *   **[动态转化] Promoted Headers**: 任何被 Trim 后的数据包 (见下文 "Trim Promotion")。
*   **代码特征**:
    *   `_is_header = true`
    *   `UecPullPacket::priority()` 直接返回 `PRIO_HI`。

### B. Medium Priority (数据层)
*   **包含包类型**:
    *   `DATA_RTX` (Retransmission): 重传数据。
    *   `DATA` (Original Data): 正常的初次传输数据。
    *   **`DATA_PROBE` (Active Probe)**: **[关键隐患]** 主动探测包目前被归类为此级，与普通数据争抢资源。
*   **代码特征**:
    *   `_packet_type != DATA_SPEC`
    *   `_is_header = false`

### C. Low Priority (推测层)
*   **包含包类型**:
    *   `DATA_SPEC` (Speculative Data): 在 Credit 不足时尝试发送的“偷跑”数据。
*   **代码特征**:
    *   `_packet_type == DATA_SPEC`
    *   `_is_header = false`

---

## 3. 动态优先级转换：TRIM Promotion 机制

UEC 的核心拥塞控制机制之一是 **Packet Trimming**。这是一个改变数据包命运的关键生命周期事件。

### 机制流程
1.  **入队 (Ingress)**: 一个普通的 4KB 数据包 (`PRIO_MID`) 进入交换机。
2.  **拥塞判决 (Congestion Decision)**: 交换机发现 Data Queue 空间不足。
3.  **执行裁剪 (Action: Trim)**:
    *   调用 `Packet::strip_payload(trim_size)`。
    *   **物理变化**: 包大小 (`_size`) 被强制修改为 64B (Header Size)。
    *   **身份变化**: 标志位 `_is_header` 被置为 **`true`**。
4.  **晋升 (Promotion)**:
    *   由于 `_is_header` 变为 true，该包的 `priority()` 返回值立即变为 **`PRIO_HI`**。
    *   该包被**移出**当前的 Data Queue (或者被丢弃后重新生成)，并**插入**到 High Priority Queue 中。
5.  **转发 (Forwarding)**: 作为一个高优先级的 NACK (Header Only) 飞向接收端，通知发生拥塞。

```mermaid
graph LR
    A[Data Packet\n(PRIO_MID)] -->|Congestion| B(Switch Trim)
    B -->|strip_payload| C{Is Header?}
    C -->|Set True| D[Trimmed Header\n(PRIO_HI)]
    D --> E[High Priority Queue]
    E --> F[Receiver (NACK)]
```

---

## 4. 关键问题分析 (Critical Issues)

### Probe Priority Anomaly (探测包优先级异常)
当前架构中，`DATA_PROBE` 被定义为普通数据包（`PRIO_MID`）。

*   **意图**: Probe 应该模拟数据路径的状况。
*   **副作用**: 在死锁 (Deadlock) 或严重拥塞 (Incast) 场景下，Data Queue 往往是满的。
    *   此时发送 Probe，不仅无法“探路”，反而会被直接 Drop 或 Trim。
    *   如果被 Trim，它虽然晋升为 High 传回去了，但告诉发送端的是 "Trimmed" (拥塞) 而非 "Acked" (通畅/丢包恢复)，这导致 SLEEK 机制误判或失效。
*   **改进建议**: 在死锁恢复场景下，应赋予 Probe **“出生即 Header” (`PRIO_HI`)** 的特权，确保其能穿透拥塞队列获取准确的链路状态。
