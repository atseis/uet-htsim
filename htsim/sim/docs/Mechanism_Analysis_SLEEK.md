# UEC SLEEK 机制实现技术详解 (Technical Analysis of SLEEK Implementation)

本文档详细分析 `htsim` 中 UEC 协议的 SLEEK (SACK-based Loss Efficient retransmission and ECN-based Knobs) 机制实现。

## 1. 机制概述

SLEEK 是 UEC 协议中用于快速丢包恢复和拥塞控制增强的核心机制。其核心思想是利用 SACK (Selective ACK) 信息来精确探测丢包，并在不依赖 RTO 超时的情况下触发快速重传。

**核心组件：**
1.  **SACK 处理**: 维护数据包接收状态位图。
2.  **OOO (Out-of-Order) 追踪**: 统计乱序包数量，用于判断丢包。
3.  **快速重传触发器**: 基于阈值的重传决策逻辑。
4.  **Probe 探测机制**: 主动探测链路状态。

---

## 2. 详细实现分析

### 2.1 启动与入口

SLEEK 逻辑嵌入在 ACK 处理流程中，受 `_enable_sleek` 标志控制。

**代码入口** (`UecSrc::processAck`):
```cpp
if (_sender_based_cc && _enable_sleek) {
    // 1. Probe Timer 检查
    if (_probe_timer_when != 0) { ... }
    
    // 2. 启动 Probe Timer (如果发送窗口受限或无数据发送)
    if (cum_ack < _highest_sent || _backlog > 0) { ... }
    
    // 3. Probe ACK 处理 (触发 Loss Recovery)
    if (pkt.is_probe_ack() && delay < _target_Qdelay) { ... }
    
    // 4. 执行核心 SLEEK 逻辑
    runSleek(ooo, cum_ack);
}
```

### 2.2 核心重传决策 (`runSleek`)

`runSleek` 函数是快速重传的大脑。它决定是否基于当前的 SACK 信息触发重传。

**关键逻辑步骤**：

1.  **计算重传阈值 (Threshold Calculation)**:
    *   **公式**: `threshold = min(loss_retx_factor * cwnd, maxwnd)`
    *   **下限**: `max(threshold, min_retx_config * avg_size)`
    *   **默认行为**: 通常需要 `~31` 个 OOO 包（假设 factor=0.5, cwnd=64pkt）才能触发。这是一个相对保守的阈值，旨在避免多路径导致的伪重传。

2.  **阈值检查**:
    ```cpp
    if (ooo < threshold / avg_size && !_loss_recovery_mode)
        return; // 未达到阈值，不重传
    ```
    这是导致"Silent Packet"场景（流末尾单包乱序）无法触发快速重传的关键原因。

3.  **进入丢包恢复模式 (Loss Recovery Mode)**:
    *   如果达到阈值，且之前未在恢复模式，标记 `_loss_recovery_mode = true`。
    *   设置 `_recovery_seqno = _highest_sent` (当前最大发送序列号)。

4.  **生成重传队列**:
    *   遍历从 `cum_ack` 到 `_recovery_seqno` 的所有包。
    *   检查 `_tx_bitmap`（发送未确认位图）。
    *   如果包未被确认，将其加入 `_rtx_queue`。
    *   **状态更新**: 从 `_tx_bitmap` 移除，减少 `_in_flight`，从 `_send_times` 移除。

5.  **触发重传**:
    *   调用 `sendIfPermitted()` 立即尝试发送重传队列中的包。

### 2.3 SACK 的基础作用 (`handleAckno`)

即使 `_enable_sleek = false`，SACK 处理函数 `handleAckno` 依然发挥关键"记账"作用：

1.  **清理记录**: 从 `_tx_bitmap` 中移除已确认的包。
2.  **RTO 维护**:
    *   如果被确认的包恰好是 RTO 正在等待的最老的包 (`send_time == _rto_send_time`)，
    *   调用 `recalculateRTO()` 重新计算 RTO（指向下一个最老的未确认包）。
3.  **队列管理**: 如果包在 `_rtx_queue` 中（之前被判丢包但又收到了 ACK），将其从重传队列移除，避免伪重传。

### 2.4 Probe 探测机制

SLEEK 包含一个主动探测机制，用于在长时间无数据发送或窗口受限时维持连接活性。

*   **启动条件**:
    *   Backlog 为空（没数据发了）
    *   或者 cum_ack < highest_sent（还有包未确认）
*   **定时器**: 
    *   Backlog=0 时：`now + base_rtt + target_Qdelay`
    *   Backlog>0 时：`now + first_trial * base_rtt`
*   **动作**: 
    *   定时器超时发送 `DATA_PROBE` 包。
    *   接收端回复 `PROBE_ACK`。
*   **反馈**: 收到 Probe ACK 后，如果延迟较低，可能会重置 Loss Recovery 状态或触发特定的拥塞控制行为。

---

## 3. 实现与规范对比分析

| 功能 | UEC 规范意图 | htsim 实现现状 | 潜在问题 |
|:---|:---|:---|:---|
| **SACK 处理** | 必须，用于状态追踪 | ✅ 完整实现 (`handleAckno`) | 无 |
| **快速重传** | 可选优化，应对非超时丢包 | ✅ 实现 (`runSleek`) | 阈值偏高，流末尾单包失效 |
| **RTO 交互** | SACK 应重置 RTO | ✅ 完整实现 (`recalculateRTO`) | 无 |
| **重传阈值** | 可配置，适应多路径 | ✅ 实现 (基于 cwnd 比例) | 流末尾场景无法累积阈值 |
| **Probe** | 活性探测 | ✅ 实现 | 依赖 SLEEK 开关，不可独立开启 |

## 4. 关键代码段 (Evidence)

*   **阈值检查 (uec.cpp:1434)**:
    ```cpp
    if (ooo < threshold / avg_size && !_loss_recovery_mode) return;
    ```
*   **重传队列填充 (uec.cpp:1447)**:
    ```cpp
    for (seq_t rtx_seqno = cum_ack; rtx_seqno < _recovery_seqno ...; rtx_seqno++) {
        if (_tx_bitmap.find(rtx_seqno) != _tx_bitmap.end()) {
            queueForRtx(rtx_seqno, pkt_size);
        }
    }
    ```
*   **SACK 记账 (uec.cpp:644)**:
    ```cpp
    mem_b UecSrc::handleAckno(ackno) { ... _tx_bitmap.erase(i); recalculateRTO(); ... }
    ```

## 5. 局限性总结

1.  **流末尾盲区**: `runSleek` 严重依赖 OOO 计数累积。在流的最后一个包乱序且无后续包的情况下 (OOO=1 < Threshold)，SLEEK 无法触发重传，系统退化为等待 RTO。
2.  **配置依赖**: Probe 机制与 Fast Retransmit 绑定在 `_enable_sleek` 开关下，无法解耦使用。
3.  **多路径敏感**: 阈值设计是为了过滤乱序，但在低重负载或短流场景下，这个阈值可能过高导致反应迟钝。

---

## 6. ACK 保底机制实现现状 (ACK Coalescing Mechanisms Status)

> 以下内容整合自原 `UEC_Implementation_Status_ACK_Mechanisms.md`（已删除）。

| 机制 | 规范要求 | 实现状态 | 说明 |
|:---|:---|:---|:---|
| **GEN_ACK_TIMER** | 接收端保底定时器，超时强制发 ACK | ❌ **未实现** | `UecSink` 未继承 `EventSource`，无定时器成员。导致死锁的**核心缺失**。 |
| **AR Flag** | 发送端在最后一个包置位 AR；接收端收到立即 ACK | ✅ 正常 | `processData` 中 `if (pkt.ar()) { force_ack = true; }` |
| **ACK_On_ECN** | 收到 ECN 标记包立即发 ACK | ✅ 已实现 | `if (ecn \|\| shouldSack() \|\| force_ack)` |
| **Probe CP** | 发送端超时发 Probe；接收端立即回复 | ✅ 已实现 | `set_probe_ack(true)` (曾有 bug，现已修复) |
| **Guaranteed Delivery** | 语义层强制 ACK | ⚪ 未建模 | `htsim` 未对上层语义协议建模 |

### 重传机制协同

| 机制 | 触发速度 | 适用场景 | 流末尾有效 | 需要配置 |
|:---|:---|:---|:---|:---|
| **NACK/TRIM** | ⚡ 即时 | 交换机拥塞、包损坏 | ✅ | 无需 |
| **SLEEK (SACK)** | 🚀 快 (需累积) | 中间大规模乱序 | ❌ | 需开启 |
| **RTO 超时** | 🐌 慢 | 所有未确认场景 | ✅ | 无需 |

---
**结论**: SLEEK 提供了有效的拥塞下快速恢复能力，但在"Silent Packet"等边界情况（流末尾、单包乱序）下存在设计盲区，必须配合接收端的 `GEN_ACK_TIMER` 作为最后保底。
