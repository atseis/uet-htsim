> [!IMPORTANT]
> **现状更新 (2026-03-04)**：
> - ✅ §1 僵尸 Probe 死循环修复 — 已实施（`uec.cpp` L1661 检查 `_done_sending`）
> - ❌ §2 指令式 Probe (`_probe_payload_psn`) — **未实施**，代码中未找到该字段
> - ❌ §3 Probe 触发快速重传 — **未实施**
> - ⚠️ §4 Autoreport 降噪 — 待确认

# UEC Probe 机制修复与改进文档

本文档详细记录了近期针对 UEC 协议 Probe 机制进行的修复与改进。这些更改解决了模拟性能极差、协议行为不符合规范以及死锁导致吞吐量下降等核心问题。

---

## 1. 性能修复：消除“僵尸 Probe”死循环

### 为什么要改 (Why)
*   **面对的问题**：模拟速度极慢，绘图脚本处理时间过长，且生成的日志文件 (`traffic.log`) 体积异常庞大。
*   **哪里出了问题**：即便流的数据传输已经完成 (`_done_sending = true`)，`UecSrc` 中的 Probe Timer 逻辑（位于 `doNextEvent`）并没有检查停止条件。这导致发送端在流结束后，仍然无限期地自我调度并发送大量无意义的 Probe 包，严重消耗计算资源和磁盘 I/O。

### 怎么改的 (How)
*   **逻辑变更**：在 Probe 发送逻辑中增加了对流完成状态的检查。
*   **代码位置**：`src/protocols/uec.cpp` -> `UecSrc::doNextEvent`
    ```cpp
    // 修复前：无条件重置 Timer 并发送
    // 修复后：
    if (!_done_sending && _probe_timer_when != 0 && ...) {
        sendProbe(); // 只有在流未完成时才发送 Probe
    }
    ```

---

## 2. 协议正确性：实现“指令式” Probe 规范

### 为什么要改 (Why)
*   **面对的问题**：Probe 机制无法正确触发重传，且导致 Sender 收到大量“无效 NACK”报错。
*   **哪里出了问题**：
    *   **发送端**：发送的 Probe 包只包含自身的序列号（如 404），没有携带 Sender 真正关心的“数据流序列号”。
    *   **接收端**：`UecSink::sack` 使用 Probe 自身的序列号（404）作为基准来计算 SACK Bitmap。然而，Receiver 的期望序列号 (`_expected_epsn`) 是数据流的序列号（如 30,000,000）。
    *   **结果**：这种基准不匹配导致生成的 Bitmap 是一串毫无意义的乱码（Garbage Bitmap），Sender 收到后无法解析出有效的 ACK/NACK 信息。

### 怎么改的 (How)
*   **数据结构** (`src/packets/uecpacket.h`)：
    *   在 `UecDataPacket` 中新增字段 `seq_t _probe_payload_psn`，用于携带 Sender 的“查询指令”。
*   **发送流程** (`src/protocols/uec.cpp`: `sendProbe`)：
    *   Sender 计算 **Lowest Unacked PSN**（当前最老且未确认的包，即潜在的“空洞”）。
    *   将该值填入 Probe 包：`p->set_probe_payload_psn(payload_psn)`。
*   **接收流程** (`src/protocols/uec.cpp`: `processData`)：
    *   Receiver 识别 Probe 包，并提取 `payload_psn`。
    *   将此值强制作为 `sack()` 函数的 **SACK Base**。
    *   **效果**：生成的 Bitmap 精确描述了 Sender 所关心的那个序列号范围的接收状态。

---

## 3. 逻辑修复：Probe 触发的快速重传 (Fast Retransmit)

### 为什么要改 (Why)
*   **面对的问题**：在发生尾部丢包 (Tail Loss) 时，流会陷入停滞 (Deadlock)，必须等待漫长的 RTO 超时才能恢复，严重影响完成时间 (FCT)。
*   **哪里出了问题**：
    *   UEC 原有的快速重传依赖于 Receiver 主动发送的 **Explicit NACK**。但在尾部丢包场景下，Receiver 收不到乱序包，因此不会发 NACK。
    *   虽然 Probe 机制被设计用来探测这种情况，但 Sender 的 `processAck` 处理逻辑存在缺陷：它只处理 Bitmap 中“为 1”（已接收）的位，却完全忽略了“为 0”（未接收/丢失）的位。
    *   结果：Sender 通过 Probe 即使确认了丢包（Bit 0 = 0），也无动于衷，没有触发重传。

### 怎么改的 (How)
*   **逻辑变更**：在处理 ACK 时，专门增加针对 Probe ACK 的空洞检查逻辑。
*   **代码位置**：`src/protocols/uec.cpp` -> `UecSrc::processAck`
    ```cpp
    // 如果是 Probe ACK，且 Bitmap 的第 0 位是 0（表示基准包未收到）
    if (pkt.is_probe_ack() && (bitmap & 1) == 0) {
        // 立即触发快速重传
        mark_packet_for_retransmission(ackno, ...);
    }
    ```
    *   **闭环形成**：Sender 怀疑丢包 (发 Probe) -> Receiver 确认状态 (回 Bitmap) -> Sender 发现空洞 (查 Bit 0) -> **Sender 立即重传**。

---

## 4. 可视化修复：Autoreport 降噪

### 为什么要改 (Why)
*   **面对的问题**：序列号时序图 (Sequence Plot) 的底部充满了大量噪点，导致图表难以阅读，且绘图速度慢。
*   **哪里出了问题**：绘图脚本 (`autoreport.py`) 将 Probe 包（序列号极小）误认为是普通数据包，与正常数据流（序列号极大）绘制在同一个坐标系中。

### 怎么改的 (How)
*   **逻辑变更**：
    1.  **过滤**：在绘制 "Normal Send" 主数据流时，增加过滤条件 `is_probe != 1`。
    2.  **分层**：将 Probe 事件提取出来，作为独立的图层（Events Channel）绘制在图表顶部。
*   **代码位置**：`analysis/viz/autoreport.py`

---

## 总结

本次修复通过消除死循环解决了**性能问题**，通过重构 Probe 交互协议解决了**正确性问题**，并通过补全重传触发逻辑解决了**活性 (Liveness) 问题**。现在的 Probe 机制已完全符合设计预期，能够高效、准确地处理 Incast 场景下的尾部丢包。
