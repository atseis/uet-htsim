# UEC Deadlock Analysis: Visual Proof & Root Cause

## 1. 核心证据：全栈可视化分析 (Full Stack Visual Analysis)

下图展示了导致死锁的完整时序与逻辑链。通过引入 **AR (ACK Request) 标记 (Red Star)** 的可视化，我们可以一目了然地看到发送端与接收端的交互细节。

![Visual Proof of UEC Deadlock](uploaded_media_1769329133125.png)

### 1.1 图例解读 (Legend)
*   🔵 **Blue Dot (Normal Send)**: 发送端发出数据包。
*   ⭐ **Red Star (AR Flag)**: 发送端在发包时置位了 `AR` (ACK Request)，主动要求接收端回复确认。
*   🟣 **Purple Diamond (Physical Arrival)**: 数据包物理上传输完成，抵达接收端网卡 (NIC) 的时刻。
*   🟢 **Green Dot (Packet ACKed)**: 接收端发出 ACK，确认收到该包。
*   🔴 **Red Circle (Retransmission)**: 发送端超时重传 (RTO)。

---

## 2. 关键事实还原 (The Facts)

### 2.1 接收端状态
从图中可以清晰看到包的到达情况：
*   **Packets 0-4**: ✅ 到达（紫钻）+ ACK（绿点）
*   **Packets 5-10**: ❌ **未到达**（无紫钻） - 可能网络丢包或严重延迟
*   **Packet 11**: 🟣 到达（紫钻）但 ❌ 无 ACK（无绿点）
*   **Packet 12**: 🟣 到达（紫钻）+ ⭐ 有红星 + ✅ ACK（绿点）

**关键观察**：Packet 11 到达时，`_expected_epsn = 5`（等待包5），而不是11。这意味着 Packet 11 是**乱序包 (Out-of-Order)**。

### 2.2 Packet 11 的处理路径
*   **状态**: `pkt.epsn() (11) > _expected_epsn (5)` → 进入 **OOO 分支**
*   **AR 标记**: ❌ 无红星 (AR=0)
*   **接收端逻辑**:
    ```cpp
    else {  // OOO branch
        _epsn_rx_bitmap[pkt.epsn()] = 1;  // 只记账
        _out_of_order_count++;
        // 没有 force_ack = true; 
    }
    ```
*   **结果**: 接收端只把 Packet 11 标记在位图中，**保持沉默**。

### 2.3 Packet 12 的处理路径
*   **状态**: `pkt.epsn() (12) > _expected_epsn (5)` → 同样进入 **OOO 分支**
*   **AR 标记**: ⭐ 有红星 (AR=1)
*   **接收端逻辑**:
    ```cpp
    if (pkt.ar()) {
        force_ack = true;  // AR 触发强制 ACK
    }
    ```
*   **结果**: 发送 ACK，告知 Sender:
    *   `cum_ack = 5` (期望包5)
    *   `SACK bitmap` 包含 11, 12

---

## 3. 死锁形成机制 (Deadlock Mechanics)

### 第一道防线失效：Sender 不基于 SACK 重传
*   **Sender 收到的信息**: "我收到了 11 和 12，但还在等 5-10"
*   **Sender 的反应**: 
    ```cpp
    // uec.cpp around line 1042
    if (_sender_based_cc && _enable_sleek) {
        runSleek(ooo, cum_ack); // SACK-based 快速重传
    }
    // 但实验配置 sleek=False，这段代码被跳过
    ```
*   **结果**: Sender **不会**基于单次 SACK 立即重传 5-10，而是等待 RTO 超时。

**设计初衷**: 在多路径传输中，包可能只是轻微乱序（不同路径延迟不同），立即重传会造成不必要的网络压力。UEC 保守策略是等待更多证据（如多次 DupACK）或超时。

### 第二道防线失效：接收端无 Timer 保底
*   **Packet 11 的困境**: 
    *   它已经物理到达接收端
    *   但因为 AR=0 + OOO，接收端选择沉默
    *   **没有 GEN_ACK_TIMER** 作为最后保底机制
*   **死锁成立**:
    *   Sender: "我在等 5-10 的 ACK 或者 RTO 超时"
    *   Receiver: "我在等 5-10 到达，Packet 11 已收到但不说话"
    *   **Result**: 如果 5-10 永久丢失且 RTO 也失效，永久死锁

---

## 4. 根本原因总结 (Root Cause)

**死锁的必要条件**：
1.  ❌ **GEN_ACK_TIMER 未实现** - 缺少接收端保底机制
2.  ❌ **OOO 分支无强制 ACK** - Packet 11 (AR=0 + OOO) 保持沉默
3.  ⚠️ **Sender 保守重传策略** - 不基于单次 SACK 快速重传（这是设计选择，不是缺陷）

**正确的理解**：
*   **AR Flag 机制**: ✅ 完全正常（Packet 12 证明）
*   **真正的缺陷**: 
    *   接收端缺少 **GEN_ACK_TIMER** 保底机制
    *   OOO 场景下对 AR=0 包的处理过于"沉默"

---

## 5. 修复方案 (Fix Strategy)

**方案 A: 规范完整实现（推荐）**
*   在 `UecSink` 中实现 **GEN_ACK_TIMER**
*   每次发送 ACK 重置定时器
*   超时强制发送 ACK
*   **优点**: 符合 UEC 规范，解决所有沉默场景

**方案 B: 快速恢复优化（补充）**
*   在 OOO 分支添加 `force_ack = true`
*   **优点**: 即使没有 Timer，也能快速通知 Sender 关于乱序包的信息
*   **缺点**: 不是规范要求，可能增加 ACK 流量

**推荐**: 同时实施 A + B，既符合规范又优化性能。
