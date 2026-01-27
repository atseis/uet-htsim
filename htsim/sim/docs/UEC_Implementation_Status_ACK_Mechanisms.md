# UEC ACK 机制实现现状分析报告 (UEC ACK Mechanisms Implementation Status)

本文档基于 `hts im` 仿真器的源代码 (`src/protocols/uec.cpp`, `uec.h`)，对照 UEC 规范要求进行逐一核查。

---

## Part I: ACK 保底机制 (ACK Coalescing Mechanisms)

### 1. GEN_ACK_TIMER (接收端生成 ACK 定时器)
*   **规范要求**：接收端每发送一个 ACK 重置定时器；超时若无新 ACK 生成，必须强制发送，防止死锁。
*   **实现现状**：❌ **未实现 (Not Implemented)**
*   **证据**：
    *   `UecSink` 类继承自 `DataReceiver`，未继承 `EventSource`。
    *   类定义中没有任何 `EventList::Handle` 类型的定时器成员变量。
    *   `processData` 函数中没有任何重置定时器的逻辑。
*   **影响**：这是导致"Silent Packet 11"死锁的**核心缺失**。当其他触发条件（如阈值、AR）都失效时，没有最后的保底机制。

### 2. AR Flag (ACK Request - Last Packet)
*   **规范要求**：发送端在 PDC 最后一个包必须置位 `ar` 标志；接收端收到必须立即 ACK。
*   **实现现状**：✅ **完全正常**
*   **证据**：
    *   **Receiver (`UecSink`)**: ✅ `processData` 中有 `if (pkt.ar()) { force_ack = true; }`。
    *   **Sender (`UecSrc`)**: ✅ AR 预测逻辑工作正常（参见 `Analysis_UEC_Deadlock_Visual_Proof.md` 中 Packet 12 的红星证据）。
*   **说明**: AR=1 时强制 ACK，AR=0 时按其他规则处理。机制本身符合规范。

### 3. ACK_On_ECN (拥塞信号强制触发)
*   **规范要求**：接收到带有 ECN 标记的包，必须忽略合并逻辑，立即发送 ACK。
*   **实现现状**：✅ **已实现 (Implemented)**
*   **证据**：
    *   `UecSink::processData`：
        ```cpp
        bool ecn = (bool)(pkt.flags() & ECN_CE);
        // ...
        if (ecn || shouldSack() || force_ack) {
            sack(...); // 立即发送
        }
        ```
    *   只要检测到 CE 标记，`if` 条件成立，立即触发 ACK。

### 4. Probe CP (显式控制包探测)
*   **规范要求**：发送端超时未收到 ACK 发送 Probe；接收端收到 Probe 必须立即回复。
*   **实现现状**：✅ **已实现 (Implemented)**
*   **证据**：
    *   **Sender**: `UecSrc::sendProbe` 发送类型为 `DATA_PROBE` 的包。
    *   **Receiver**: `UecSink::processData` 针对 Probe 有专门的处理分支：
        ```cpp
        if (pkt.packet_type() == UecBasePacket::DATA_PROBE) {
            UecAckPacket* ack_packet = sack(...);
            ack_packet->set_probe_ack(true);
            _nic.sendControlPacket(ack_packet, NULL, this);
            return; // 立即返回
        }
        ```
    *   实现正确且独立于通用数据处理逻辑。

### 5. Guaranteed Delivery (语义层强制)
*   **规范要求**：特定语义响应需立即 ACK。
*   **实现现状**：⚪ **未建模 (Not Modeled)**
*   **说明**：`htsim` 是网络层/传输层仿真，未对上层语义协议（SES）的具体消息类型（如 Guaranteed Delivery Response）进行建模。所有数据包均按通用 UEC 数据包处理。

---

## Part II: 发送端重传机制 (Sender Retransmission Mechanisms)

UEC 发送端有**三种独立的重传触发机制**：

### 机制 1: NACK-based 即时重传 (TRIM Mechanism)
*   **触发条件**：接收端发送 NACK (Negative ACK) 或 TRIM 包
*   **实现状态**：✅ **已实现**
*   **处理函数**：`UecSrc::processNack`
*   **代码证据**：
    ```cpp
    // uec.cpp line 1498-1584
    void UecSrc::processNack(const UecNackPacket& pkt) {
        auto nacked_seqno = pkt.ref_ack();
        
        // 找到被 NACK 的包
        auto i = _tx_bitmap.find(nacked_seqno);
        if (i == _tx_bitmap.end()) {
            return;  // 包已被确认
        }
        
        // 立即加入重传队列
        mem_b pkt_size = i->second.pkt_size;
        _tx_bitmap.erase(i);
        _in_flight -= pkt_size;
        
        queueForRtx(nacked_seqno, pkt_size);  // 加入重传队列
        sendIfPermitted();  // 立即发送
    }
    ```
*   **触发源**：
    *   交换机队列满时发送 TRIM/NACK
    *   接收端检测到包损坏时发送 NACK
*   **特点**：
    *   ✅ **无条件立即重传**（不需要阈值）
    *   ✅ 适用于所有场景（包括流末尾）
    *   ⚠️ 依赖网络设备主动通知

### 机制 2: SACK-based 快速重传 (SLEEK Mechanism)
*   **触发条件**：收到 ACK 且 `_enable_sleek = true` 且 OOO 计数超过阈值
*   **实现状态**：✅ **已实现**（但默认关闭）
*   **处理函数**：`UecSrc::runSleek`
*   **代码证据**：
    ```cpp
    // uec.cpp line 1042
    if (_sender_based_cc && _enable_sleek) {
        runSleek(ooo, cum_ack);
    }
    
    // uec.cpp line 1413-1496
    void UecSrc::runSleek(uint32_t ooo, UecBasePacket::seq_t cum_ack) {
        mem_b threshold = min((mem_b)(loss_retx_factor * _cwnd), _maxwnd);
        threshold = max(threshold, min_retx_config * avg_size);
        
        // 关键判断：OOO 是否达到阈值
        if (ooo < threshold / avg_size && !_loss_recovery_mode)
            return;  // 不重传
        
        // 进入丢包恢复模式
        if (!_loss_recovery_mode && _rtx_queue.empty()) {
            _loss_recovery_mode = true;
            _recovery_seqno = _highest_sent;
        }
        
        // 将未确认包加入重传队列
        for (seq_t rtx_seqno = cum_ack; rtx_seqno < _recovery_seqno; rtx_seqno++) {
            if (/* 未确认 */) {
                queueForRtx(rtx_seqno, pkt_size);
            }
        }
        sendIfPermitted();
    }
    ```
*   **触发条件详解**：
    *   典型阈值：`threshold ≈ 0.5 * cwnd ≈ 31 packets`
    *   需要累积 OOO 计数 >= 31 才触发
*   **特点**：
    *   ⚠️ 需要配置开启 (`sleek=True`)
    *   ⚠️ 需要累积足够的 OOO 证据
    *   ❌ **流末尾场景无效**（无法累积）
    *   ✅ 中间大规模乱序场景有效

### 机制 3: RTO 超时重传 (Timeout-based Retransmission)
*   **触发条件**：长时间未收到 ACK，RTO 定时器超时
*   **实现状态**：✅ **已实现**
*   **代码证据**：
    *   **Timer 设置** (`startRTO`, line 1982):
        ```cpp
        void UecSrc::startRTO(simtime_picosec send_time) {
            _rtx_timeout_pending = true;
            _rtx_timeout = send_time + _min_rto;  // 默认 164.7us
            _rto_send_time = send_time;
            
            // 注册定时器事件
            _rto_timer_handle = eventlist().sourceIsPendingGetHandle(*this, _rtx_timeout);
        }
        ```
    *   **超时回调** (`rtxTimerExpired`, line 2304):
        ```cpp
        void UecSrc::rtxTimerExpired() {
            // 找到最早发送的未确认包
            auto seqno = _send_times.begin()->second;
            auto send_record = _tx_bitmap.find(seqno);
            mem_b pkt_size = send_record->second.pkt_size;
            
            // 从发送记录中删除
            _tx_bitmap.erase(send_record);
            
            // 标记为需要重传
            mark_packet_for_retransmission(seqno, pkt_size);
            queueForRtx(seqno, pkt_size);  // 加入重传队列
            
            recalculateRTO();  // 重新计算下一个 RTO
        }
        ```
*   **特点**：
    *   ✅ 最后保障机制
    *   ✅ 适用于所有场景
    *   ❌ 恢复时间较长（**RTO动态计算**，本实验中 ≈ **700.248us**）
        ```cpp
        // uec.h line 23 (默认值，会被 main_uec.cpp 覆盖)
        #define DEFAULT_UEC_RTO_MIN 100  // microseconds
        
        // main_uec.cpp line 702 (实际使用的动态计算)
        UecSrc::_min_rto = timeFromUs(15 + queuesize * 6.0 * 8 * 1000000 / linkspeed);
        // 计算：15 + 1427600 * 6.0 * 8 * 1000000 / 100000000000 = 700.248us
        ```
        **日志证据**：
        ```
        > Setting min RTO to 700.248
        Start timer at 0 expires at 700.248
        rtx timer expired for seqno 11 packet sent at 3.652 now time is 703.9
        ```
    *   ⚠️ **依赖接收端后续 ACK** （重传包到达后需要接收端响应）

---

## Part III: 重传机制对比与协同

| 机制 | 触发速度 | 适用场景 | 流末尾有效 | 需要配置 |
|:---|:---|:---|:---|:---|
| **NACK/TRIM** | ⚡ 即时 | 交换机拥塞、包损坏 | ✅ 有效 | 无需 |
| **SLEEK (SACK)** | 🚀 快 (需累积) | 中间大规模乱序 | ❌ 无效 | 需开启 |
| **RTO 超时** | 🐌 慢 | 所有未确认场景 | ✅ 有效 | 无需 |

### 协同工作流程

```
数据包发送
    ↓
收到 NACK？ → YES → 【机制1】立即重传 ✅
    ↓ NO
收到 ACK？
    ↓ YES
SLEEK 开启？ → YES → OOO >= 阈值？ → YES → 【机制2】快速重传 ✅
    ↓ NO                    ↓ NO
    ↓                       等待更多 ACK
    ↓
等待 RTO...
    ↓
超时 → 【机制3】RTO 重传 ✅
```

---

## Part IV: Silent Packet 死锁分析整合

### 完整时间线（整合三种机制）

```
T=0:       发送 Packets 0-12
T=10us:    Packets 0-4 到达，正常 ACK
T=50us:    Packet 12 到达，AR=1 → 触发 ACK
           ACK: cum_ack=5, SACK={12}, ooo=1
T=50.5us:  发送端收到 ACK
           - 【机制2 SLEEK】: sleek=False → 跳过
           - 【机制2 SLEEK】: 即使 sleek=True，ooo=1 < 阈值 → 不重传
           - 决策：等待 RTO
T=100us:   Packet 11 到达接收端
           - AR=0, OOO → 只记账，不 ACK
           - 【无 NACK】：包正常到达，不触发 TRIM
T=700us:   【机制3 RTO】: 可能超时，尝试重传 5-10
           但重传包到达后，接收端仍可能沉默（无 Timer）
T=∞:       【死锁】：三种重传机制都无法打破僵局
           - NACK: 包未损坏，不触发
           - SLEEK: 无法累积 OOO
           - RTO: 重传后接收端仍沉默
```

### 为什么 NACK 没有拯救 Packet 11？

**NACK 的触发条件**：
*   交换机队列溢出（TRIM）
*   包在传输中损坏
*   **不包括**：包正常到达但接收端沉默

**本案例**：
*   Packet 11 **物理上成功到达**接收端（图中有紫钻）
*   接收端成功接收并记账（`_epsn_rx_bitmap[11] = 1`）
*   **没有理由发 NACK**

---

## Part V: 总结与建议

### 机制现状总结

| 分类 | 机制 | 状态 | 关键问题 |
|:---|:---|:---|:---|
| **ACK 保底** | GEN_ACK_TIMER | ❌ 未实现 | 导致死锁的核心缺失 |
| **ACK 保底** | AR Flag | ✅ 正常 | - |
| **ACK 保底** | ACK_On_ECN | ✅ 正常 | - |
| **ACK 保底** | Probe CP | ✅ 正常 | - |
| **重传机制** | NACK/TRIM | ✅ 实现 | 不适用于"正常到达但沉默" |
| **重传机制** | SLEEK (SACK) | ⚠️ 可选 | 流末尾场景无效 |
| **重传机制** | RTO 超时 | ✅ 实现 | 恢复慢，且依赖接收端后续 ACK |

### 死锁的根本原因

**NOT** 重传机制缺失（三种机制都有）
**BUT** 接收端缺少 **GEN_ACK_TIMER** 保底

**逻辑链**：
1.  Packet 11 正常到达 → 不触发 NACK ❌
2.  流已结束 → SLEEK 无法累积 OOO ❌
3.  RTO 超时重传 → 但重传包填坑后，接收端**仍然沉默** ❌
4.  **缺少 Timer** → 接收端永不主动 ACK → 死锁 ❌

### 修复建议

**优先级 1: 实现 GEN_ACK_TIMER (治本)**
*   在 `UecSink` 中添加定时器
*   每次发送 ACK 重置定时器
*   超时强制发送 ACK
*   **优点**: 符合规范，彻底解决沉默问题

**优先级 2: 优化 OOO 处理 (辅助)**
*   在 OOO 分支添加 `force_ack = true`
*   **优点**: 即使没有 Timer，也能快速反馈
*   **缺点**: 可能增加 ACK 流量

**不推荐: 调整 SLEEK 阈值**
*   降低阈值虽可强制重传，但会导致多路径场景性能下降
*   这是应急措施，不是长期方案
