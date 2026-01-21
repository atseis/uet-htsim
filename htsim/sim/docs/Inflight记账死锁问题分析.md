# UEC Inflight 记账死锁问题分析报告

## 1. 问题背景
在 Incast 规模测试中（如 `conns64` 场景），受害流（Flow 9098）在发生大量 Physical TRIM 后，拥塞窗口 (CWND) 被压制到 **1 MSS**。
此时，`_in_flight` 计数器异常停留在 **1 MSS**，导致即使收到 ACK/NACK，发送端也无法发出任何数据或重传包，直到 700μs 后的重传计时器 (RTO) 强制破局。

## 2. 根因分析：不鲁棒的混合映射模型

通过对 `uec.cpp` 的审计，发现 `_in_flight` 的统计采用了一种“混合映射”模式，这种模式在网络出现信号丢失时极度脆弱。

### 2.1 增量逻辑 (Increment)
在发送新包或重传包时，`_in_flight` 简单累加：
```cpp
// z:/uet-htsim/htsim/sim/src/protocols/uec.cpp:2060 (sendNewPacket)
_in_flight += full_pkt_size;

// z:/uet-htsim/htsim/sim/src/protocols/uec.cpp:2109 (sendRtxPacket)
_in_flight += full_pkt_size;
```

### 2.2 减量逻辑的分歧 (Decrement Discrepancy)

问题出在**正常确认**与**丢包确认/TRIM确认**的处理逻辑不一致：

#### A. 成功包（基于全局计数器）
当收到 ACK 时，发送端根据接收端累计收到的字节数 `recvd_bytes` 批量扣减 `_in_flight`：
```cpp
// z:/uet-htsim/htsim/sim/src/protocols/uec.cpp:906 (processAck)
_in_flight -= newly_recvd_bytes;
```
*注：这里的 `newly_recvd_bytes` 是接收端 `UecSink::processData` 累加的 `pkt.size()`。*

#### B. 丢失/TRIM包（基于事件触发）
当收到 NACK（由镜像 TRIM 触发）或 RTO 超时时，发送端针对**特定序号**扣减 `_in_flight`：
```cpp
// z:/uet-htsim/htsim/sim/src/protocols/uec.cpp:1565 (processNack)
_in_flight -= pkt_size;

// z:/uet-htsim/htsim/sim/src/protocols/uec.cpp:1274 (mark_packet_for_retransmission)
_in_flight -= pktsize;
```

### 2.3 记账漂移与死锁 (Deep Cause: Feedback Loss)
当出现极度拥塞时，**NACK 包本身也会丢失**。
1. **TRIM 发生**：Switch 对数据包进行 TRIM，仅保留 Header。接收端收到 TRIM 包，通过 `processTrimmed` 发回 NACK。
2. **NACK 丢失**：如果这个 NACK 在回程中丢失，或者由于某种原因未被 Source 逻辑处理。
3. **幽灵包产生**：由于 NACK 丢失，上述 2.2-B 的减量逻辑未触发；同时，因为该包被 TRIM 过，它也不会被包含在 2.2-A 的 `newly_recvd_bytes` 中。
4. **窗口锁死**：这部分字节会“幽灵般”永久残留在 `_in_flight` 中。在 `cwnd = 1 MSS` 的极端情况下，`_in_flight` 也是 1 MSS，发送端判定 `cwnd < in_flight + next_pkt` 恒成立，流因此永久僵死（Deadlock）。

## 3. 代码证据

### 3.1 接收端行为的“不对称性”
`UecSink::processData` (正常接收) 会更新 `_recvd_bytes`：
```cpp
// z:/uet-htsim/htsim/sim/src/protocols/uec.cpp:2654
_recvd_bytes += pkt.size();
```
但 `UecSink::processTrimmed` (收到裁减包) **不会**更新 `_recvd_bytes`：
```cpp
// z:/uet-htsim/htsim/sim/src/protocols/uec.cpp:2728
void UecSink::processTrimmed(const UecDataPacket& pkt) {
    // ... 仅发送 NACK，不增加 _recvd_bytes ...
}
```
这意味着：**被 TRIM 的包，其窗口释放只能且必须依赖 NACK 信号或 RTO。** 如果 NACK 丢了，会计信息就会出现永久性的偏差。

### 3.2 发送端判断逻辑
在 `sendIfPermitted` 中：
```cpp
// z:/uet-htsim/htsim/sim/src/protocols/uec.cpp:1918
if (!can_send_NSCC(next_packet_size)) { return; }

// z:/uet-htsim/htsim/sim/src/protocols/uec.cpp:1111 (can_send_NSCC)
return (pkt_size > 0) &&
       (((!_loss_recovery_mode && _cwnd >= _in_flight + pkt_size) ||
         (_loss_recovery_mode && (!_rtx_queue.empty() || _cwnd >= _in_flight + pkt_size))));
```
一旦 `_in_flight` 出现“重影”，由于 `_cwnd` 被锁定在 1 MSS，上述条件永远无法满足，协议栈进入死锁。

## 4. 解决方案规划
目前的混合记账模型不具备容错性。应改为**基于包的精确状态机记账 (Per-Packet Accounting)**：
- 取消 `processAck` 中基于全局 `newly_recvd_bytes` 的批量扣减。
- 每一笔 `_in_flight` 的扣减都必须通过 `tx_bitmap` 找到原始包的记录。
- 无论收到该包的 ACK 还是 NACK，都根据 `tx_bitmap` 中存储的该包原始大小精准扣减。
- 这样即使 NACK 丢失，后续的 Cumulative ACK 或 SACK 遍历 `tx_bitmap` 时也能根据历史记录将该包从 `_in_flight` 中移除，从而自动纠错。
