# UEC 发送端重传逻辑分析 (Sender Retransmission Logic Analysis)

## 问题背景

**现象**: Packet 12 带有 AR=1，先于 Packet 11 到达接收端（~50us），触发了 ACK。**注意：此时 Packet 11 还未到达**（Packet 11 在 ~100us 才到达）。

该 ACK 携带的信息是：
*   `cum_ack = 5` (期望接收包5)
*   `SACK bitmap` = `{12}` （**只有** Packet 12，不包含 11）

**疑问**: 这个 ACK 明确告知发送端"我收到了 12，但 5-11 都没到"，为什么发送端没有立即重传 5-11？

---

## 1. ACK 的处理流程

### 1.1 ACK 包含的信息
发送端收到的 ACK 包含：
```cpp
// UecAckPacket 结构
uint32_t cumulative_ack;  // 累积确认：5（期望的下一个包）
uint64_t bitmap;          // SACK 位图：标记 12 已收到
uint32_t ref_ack;         // bitmap 的基准序列号
```

**OOO 计数**: `ooo = 1` (只有 Packet 12 乱序)

### 1.2 发送端的 ACK 处理入口
```cpp
// uec.cpp: UecSrc::processAck
void UecSrc::processAck(UecAckPacket& pkt) {
    auto cum_ack = pkt.cumulative_ack();
    
    // Step 1: 处理累积确认
    handleCumulativeAck(cum_ack);  // 清理 0-4 的发送记录
    
    // Step 2: 处理 SACK bitmap
    auto ackno = pkt.ref_ack();
    uint64_t bitmap = pkt.bitmap();
    while (bitmap > 0) {
        if (bitmap & 1) {
            handleAckno(ackno);  // 处理 12
        }
        ackno++;
        bitmap >>= 1;
    }
    
    // Step 3: 【关键】检查是否需要重传
    if (_sender_based_cc && _enable_sleek) {
        runSleek(ooo, cum_ack);  // SACK-based 快速重传
    }
    // 如果 _enable_sleek = false，这段代码被跳过！
}
```

---

## 2. SLEEK 的影响分析

### 2.1 当前配置：SLEEK = False

**代码路径**:
```cpp
// uec.cpp around line 1042
if (_sender_based_cc && _enable_sleek) {
    runSleek(ooo, cum_ack);
}
// sleek=False → 条件不成立 → runSleek 被完全跳过
```

**结果**: 
*   发送端**完全不调用** `runSleek`
*   **不会**基于 SACK 信息判断是否重传
*   只能依赖 **RTO 超时** 机制

### 2.2 假设配置：SLEEK = True

如果 `_enable_sleek = true`，`runSleek` 会被调用，逻辑如下：

```cpp
// uec.cpp: UecSrc::runSleek
void UecSrc::runSleek(uint32_t ooo, UecBasePacket::seq_t cum_ack) {
    mem_b avg_size = get_avg_pktsize();  // 平均包大小
    
    // 计算重传阈值
    mem_b threshold = min((mem_b)(loss_retx_factor * _cwnd), _maxwnd);
    threshold = max(threshold, min_retx_config * avg_size);
    
    // 关键判断：OOO 计数是否达到阈值
    if (ooo < threshold / avg_size && !_loss_recovery_mode)
        return;  // 阈值未达到，不重传
    
    // 如果达到阈值，进入丢包恢复模式
    if (!_loss_recovery_mode && _rtx_queue.empty()) {
        _loss_recovery_mode = true;
        _recovery_seqno = _highest_sent;
    }
    
    // 将 cum_ack 到 _recovery_seqno 之间的未确认包加入重传队列
    for (seq_t rtx_seqno = cum_ack; rtx_seqno < _recovery_seqno; rtx_seqno++) {
        if (/* 包未被确认 */) {
            queueForRtx(rtx_seqno, pkt_size);  // 加入重传队列
        }
    }
    sendIfPermitted();  // 开始重传
}
```

#### 2.2.1 阈值计算

**参数** (典型值):
*   `loss_retx_factor`: 配置参数，例如 `0.5` (CWND 的 50%)
*   `_cwnd`: 当前拥塞窗口，例如 `262926 bytes`
*   `min_retx_config`: 最小重传阈值，例如 `3 packets`
*   `avg_size`: 平均包大小，例如 `4150 bytes`

**计算**:
```
threshold = min(0.5 * 262926, maxwnd) = 131463 bytes
threshold = max(131463, 3 * 4150) = 131463 bytes
threshold_in_pkts = 131463 / 4150 ≈ 31 packets
```

#### 2.2.2 判断逻辑

```cpp
if (ooo < threshold / avg_size && !_loss_recovery_mode)
    return;  // 不重传
```

**本案例**:
*   `ooo = 1` (只有 Packet 12 乱序)
*   `threshold_in_pkts ≈ 31`
*   `1 < 31` → **条件成立**
*   **结果**: `runSleek` **直接返回**，不触发重传

#### 2.2.3 结论

**即使 SLEEK = True，本案例依然不会触发快速重传**！

原因：
*   单个 OOO 包 (Packet 12) 不足以判定大规模丢包
*   需要累积更多 OOO 证据（如收到多个后续包的 ACK）
*   或者等待 RTO 超时

---

## 3. 为什么需要阈值？

### 3.1 多路径传输的挑战

**正常场景**（非丢包）:
```
Packets 5-11: 走路径 A (延迟 100us)
Packet 12:    走路径 B (延迟  50us)

T=50us:  Packet 12 到达 → 触发 ACK (ooo=1)
T=100us: Packets 5-11 到达 → 填补空缺
```

**如果立即重传的后果**:
```
T=50us:  Packet 12 ACK → 【错误】立即重传 5-11
T=51us:  重传包开始发送
T=100us: 原始 5-11 包到达
T=150us: 重传 5-11 包也到达 → 重复传输！
```

### 3.2 阈值设计

**阈值的意义**:
*   **小规模乱序** (ooo < threshold): 可能只是路径延迟差异，等待
*   **大规模乱序** (ooo >= threshold): 很可能是丢包，重传

**typical 配置**:
*   阈值 = CWND 的 50% ≈ 30 packets
*   意味着需要看到 30+ 个乱序包才触发快速重传
*   本案例只有 1 个乱序包，远未达到阈值

---

## 4. 本案例的完整时间线

### 4.1 实际发生的事件

```
T=0:       发送端发送 Packets 0-12
T=10us:    Packets 0-4 到达，正常 ACK
T=50us:    Packet 12 到达接收端
           - AR=1 → 触发 ACK
           - ACK 内容: cum_ack=5, SACK={12}, ooo=1
           - 此时 Packet 11 还未到达
T=50.5us:  发送端收到 ACK
           - handleCumulativeAck(5): 确认 0-4
           - handleAckno(12): 确认 12
           - _enable_sleek = false → 跳过 runSleek
           - 决策: 等待 RTO
T=100us:   Packet 11 到达接收端
           - AR=0, OOO → 只记账，不回复
           - 没有 Timer 保底
T=??? :    【死锁】发送端等 RTO，接收端等 5-10，双方沉默
```

### 4.2 假设 SLEEK = True 会如何？

```
T=50.5us:  发送端收到 ACK
           - handleCumulativeAck(5)
           - handleAckno(12)
           - _enable_sleek = true → 调用 runSleek(ooo=1, cum_ack=5)
           - runSleek 内部判断:
             * ooo=1 < threshold=31
             * return; // 不重传
           - 决策: 仍然等待 RTO
T=100us:   Packet 11 到达，同样沉默
T=??? :    【死锁依然发生】
```

**结论**: **SLEEK = True 在本案例中也无法避免死锁**！

---

## 5. 如何才能触发快速重传？

### 5.1 需要的条件 (SLEEK = True)

**方式 1: 累积 OOO 计数**
*   收到更多后续包的 ACK
*   例如 Packet 13, 14, 15... 也陆续到达并触发 ACK
*   OOO 计数逐渐增加: 2, 3, 4, ...
*   当 OOO >= 31 时，触发 `runSleek` 重传

**方式 2: 降低阈值**
*   修改配置: `loss_retx_factor = 0.1` (CWND 的 10%)
*   或 `min_retx_config = 1` (最少 1 包)
*   这样单个 OOO 也能触发
*   **代价**: 增加误报率（正常乱序被误判为丢包）

### 5.2 为什么本案例无法累积 OOO？

**流已结束**:
*   Packet 12 是流的最后一个包
*   没有后续 Packet 13, 14, 15...
*   OOO 计数永远停留在 1
*   **无法**通过累积达到阈值

**这就是流末尾场景的特殊性**：
*   中间丢包：后续包持续到达 → OOO 累积 → 触发重传 ✅
*   末尾丢包：无后续包 → OOO 不增长 → 无法触发 ❌

---

## 6. 两道防线的设计意图

### 第一道防线：快速重传 (Fast Retransmit via SLEEK)
*   **规范要求**: 可选优化，非强制
*   **UEC 实现**: 通过 SLEEK 功能实现
*   **触发条件**: OOO 计数 >= 阈值
*   **局限性**: 
    *   ❌ 流末尾场景无效（无法累积）
    *   ❌ 单包乱序场景无效（阈值保护）
    *   ✅ 中间大规模乱序有效

### 第二道防线：接收端 Timer (GEN_ACK_TIMER)
*   **规范要求**: **强制要求**，保底机制
*   **UEC 实现**: ❌ **未实现**
*   **触发条件**: 超时无条件发送
*   **优势**: 
    *   ✅ 覆盖所有场景（包括流末尾）
    *   ✅ 独立于发送端策略
    *   ✅ 打破任何沉默

### 当前问题
**两道防线都失效**:
1.  第一道：SLEEK 即使开启也无法处理流末尾单包乱序
2.  第二道：Timer 缺失 → 无保底机制（**这是致命缺陷**）

---

## 7. SLEEK 影响总结

| 场景 | SLEEK=False | SLEEK=True (本案例) | SLEEK=True (降低阈值) |
|:---|:---|:---|:---|
| **单包乱序 (ooo=1)** | ❌ 不重传 | ❌ 不重传 (阈值保护) | ✅ 可能重传 |
| **流末尾场景** | ❌ 无法累积 OOO | ❌ 无法累积 OOO | ✅ 如果阈值=1 |
| **中间大规模乱序** | ❌ 等 RTO | ✅ 触发重传 | ✅ 触发重传 |

**关键发现**:
*   **SLEEK 不是死锁的根因**
*   即使 SLEEK=True，本案例仍会死锁（阈值保护 + 流末尾）
*   **真正根因**: **缺少 GEN_ACK_TIMER**

---

## 8. 解决方案

### 方案 A: 调整 SLEEK 阈值 (治标不治本)
```cpp
// 配置
loss_retx_factor = 0.0;  // 禁用比例阈值
min_retx_config = 1;     // 最小阈值 = 1 包
```
*   效果：单个 OOO 即触发重传
*   代价：**大幅增加误报**，多路径场景性能下降

### 方案 B: 实现 GEN_ACK_TIMER (治本)
*   在 `UecSink` 中添加定时器
*   效果：无论何种场景，接收端定期发送 ACK
*   优点：**符合 UEC 规范**，彻底解决沉默问题

### 推荐
**优先实现方案 B (GEN_ACK_TIMER)**:
*   这是规范强制要求
*   解决根本问题
*   方案 A 只是应急措施，不应作为长期方案

---

## 9. 总结

**核心发现**:
1.  ✅ Packet 12 的 ACK 到达了发送端
2.  ✅ ACK 包含 SACK 信息（只有 Packet 12，不含 11）
3.  ✅ 发送端**选择不重传**是因为：
    *   SLEEK=False: 完全不检查
    *   SLEEK=True: OOO=1 < 阈值≈31，不满足触发条件
4.  ❌ **SLEEK 不是根本原因**
5.  ❌ **真正缺陷**: 接收端无 GEN_ACK_TIMER

**设计启示**:
*   快速重传（SLEEK）是**性能优化**，有其使用场景和限制
*   接收端 Timer 是**可靠性保障**，必须无条件实现
*   **流末尾场景**是快速重传的"盲区"，只能靠 Timer 兜底
