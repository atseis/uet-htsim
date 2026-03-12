# Probe 机制修复文档

## 1. 背景与问题

### 1.1 SLEEK 简介

SLEEK (Swift Loss rEcovEry pacKets) 是 UEC (Ultra Ethernet Consortium) 传输协议中的一个**快速丢包恢复机制**。它的核心思想是：

- 当发送方怀疑有丢包时，主动发送**探测包 (Probe Packet)**
- 接收方收到探测包后，立即返回 ACK 并附带 SACK bitmap
- 发送方根据 SACK bitmap 判断哪些包已丢失，触发**快速重传**
- 这样可以在 RTO (Retransmission Timeout) 到期前恢复丢包，提高吞吐量

### 1.2 修复前的问题

在修复之前 (`dev` 分支)，Probe 机制存在一个关键缺陷：

**问题现象**: Probe 包返回的 SACK bitmap 无法正确反映未确认数据包的状态，导致快速重传机制无法正常工作。

**根本原因**: 

1. Probe 包使用独立的序列号空间 (`_probe_seqno`)，与数据包的序列号 (`_highest_sent`) 分开计数
2. 接收方收到 Probe 包后，使用 `sackBitmapBase(pkt.epsn())` 生成 SACK bitmap
3. 但 `pkt.epsn()` 是 Probe 包自己的序列号，不是数据包的序列号
4. 这导致 SACK bitmap 的基准是错误的，bitmap 中标记的"已接收/未接收"状态与实际情况不符

**代码示例 (dev 分支)**:
```cpp
// sendProbe() - 发送 Probe 包，使用独立的 probe_seqno
void UecSrc::sendProbe() {
    _probe_seqno++;  // 独立的序列号
    auto* p = UecDataPacket::newpkt(_flow, NULL, _probe_seqno, _hdr_size, 
                                    UecBasePacket::DATA_PROBE, 0, _dstaddr);
    // 没有携带数据包序列号信息！
    ...
}

// processData() - 接收端处理
void UecSink::processData(UecDataPacket& pkt) {
    if (pkt.packet_type() == UecBasePacket::DATA_PROBE) {
        // 使用 pkt.epsn() (即 probe_seqno) 生成 SACK bitmap
        // 但这不是数据包的序列号！
        UecAckPacket* ack_packet = sack(pkt.path_id(), 
                                         sackBitmapBase(pkt.epsn()),  // ❌ 错误！
                                         pkt.epsn(), ...);
        ...
    }
}
```

## 2. 修复方案

### 2.1 核心改动

修复添加了 `probe_payload_psn` 字段，让 Probe 包携带它所询问的数据包序列号：

**1. 新增字段 (uecpacket.h)**:
```cpp
class UecDataPacket : public UecBasePacket {
    ...
    // Probe payload PSN - the sequence number the probe is asking about
    inline seq_t probe_payload_psn() const { return _probe_payload_psn; }
    inline void set_probe_payload_psn(seq_t p) { _probe_payload_psn = p; }
    ...
protected:
    seq_t _probe_payload_psn;  // payload sequence number carried by probe packets
    ...
};
```

**2. 发送端设置 probe_payload_psn (uec.cpp)**:
```cpp
void UecSrc::sendProbe() {
    _probe_seqno++;
    auto* p = UecDataPacket::newpkt(_flow, NULL, _probe_seqno, _hdr_size, 
                                    UecBasePacket::DATA_PROBE, 0, _dstaddr);
    ...
    // Find the lowest unacked packet to probe about
    UecBasePacket::seq_t lowest_unacked =
        _tx_bitmap.empty() ? _highest_sent : _tx_bitmap.begin()->first;
    p->set_probe_payload_psn(lowest_unacked);  // ✅ 携带数据包序列号
    ...
}
```

**3. 接收端使用 probe_payload_psn (uec.cpp)**:
```cpp
void UecSink::processData(UecDataPacket& pkt) {
    if (pkt.packet_type() == UecBasePacket::DATA_PROBE) {
        ...
        // 使用 probe_payload_psn 生成 SACK bitmap
        UecAckPacket* ack_packet =
            sack(pkt.path_id(), 
                 sackBitmapBase(pkt.probe_payload_psn()),  // ✅ 正确！
                 pkt.epsn(), ...);
        ack_packet->set_probe_ack(true);
        _nic.sendControlPacket(ack_packet, NULL, this);
        return;
    }
    ...
}
```

### 2.2 修复后的机制流程

```
发送端 (UecSrc)                              接收端 (UecSink)
     |                                              |
     | 1. 检测可能丢包                               |
     |    (SLEEK 机制触发)                           |
     |                                              |
     | 2. 准备发送 Probe 包                          |
     |    - 增加 _probe_seqno                       |
     |    - 查找最低未确认包: lowest_unacked        |
     |    - 设置 probe_payload_psn = lowest_unacked |
     |                                              |
     |---------- Probe Packet --------------------->|
     |       epsn = _probe_seqno                    |
     |       probe_payload_psn = 询问的数据包序列号   |
     |                                              |
     |                                              | 3. 收到 Probe
     |                                              |    - 识别为 DATA_PROBE
     |                                              |    - 用 probe_payload_psn
     |                                              |      生成 SACK bitmap
     |                                              |    - 返回 ACK (is_probe_ack=true)
     |                                              |
     |<--------- ACK Packet ------------------------|
     |       包含正确的 SACK bitmap                  |
     |       is_probe_ack = true                    |
     |                                              |
     | 4. 处理 ACK                                   |
     |    - 识别 is_probe_ack                       |
     |    - 根据 SACK bitmap 判断丢包                |
     |    - 触发快速重传                             |
     v                                              v
```

## 3. 关键概念解释

### 3.1 两个序列号的区别

| 字段 | 名称 | 用途 | 计数方式 |
|------|------|------|----------|
| `epsn` (在 Probe 包中) | Probe Sequence Number | Probe 包自身的序列号 | 独立计数，每次发送 Probe 增加 |
| `probe_payload_psn` | Probe Payload PSN | Probe 询问的数据包序列号 | 指向 `_tx_bitmap` 中最低未确认包 |

### 3.2 SACK Bitmap 的作用

SACK (Selective Acknowledgment) Bitmap 是一个 64 位的位图，表示从某个基准序列号开始的 64 个包中哪些已被接收：

```
序列号:    100  101  102  103  104  105  106  107  ...
状态:       ✓    ✓    ✗    ✓    ✗    ✗    ✓    ✓   ...
Bitmap:     1    1    0    1    0    0    1    1   ...
```

**修复前**: Bitmap 基准是 `probe_seqno`，与数据包序列号无关，bitmap 内容无意义。

**修复后**: Bitmap 基准是 `probe_payload_psn`，bitmap 正确反映了从该序列号开始的接收状态。

### 3.3 与快速重传的关系

修复前，Probe 机制无法正确触发快速重传，因为：
1. 发送方收到 Probe ACK，但 SACK bitmap 是基于错误基准的
2. 发送方无法从 bitmap 中准确识别哪些数据包已丢失
3. 只能等待 RTO 超时后才能重传，失去了 Probe 的意义

修复后：
1. 发送方收到 Probe ACK，SACK bitmap 正确反映了数据包接收状态
2. 发送方可以准确识别丢失的数据包
3. 立即触发快速重传，无需等待 RTO

## 4. 代码变更汇总

### 4.1 文件变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `htsim/sim/src/packets/uecpacket.h` | 新增 | 添加 `_probe_payload_psn` 字段及访问方法 |
| `htsim/sim/src/protocols/uec.cpp` | 修改 | `sendProbe()` 设置 `probe_payload_psn` |
| `htsim/sim/src/protocols/uec.cpp` | 修改 | `processData()` 使用 `probe_payload_psn` 生成 SACK |

### 4.2 详细 Diff

```cpp
// uecpacket.h
class UecDataPacket : public UecBasePacket {
public:
    ...
+   // Probe payload PSN - the sequence number the probe is asking about
+   inline seq_t probe_payload_psn() const { return _probe_payload_psn; }
+   inline void set_probe_payload_psn(seq_t p) { _probe_payload_psn = p; }
    ...
protected:
    ...
+   seq_t _probe_payload_psn;  // payload sequence number carried by probe packets
    ...
};
```

```cpp
// uec.cpp - sendProbe()
void UecSrc::sendProbe() {
    ...
    _probe_seqno++;
    auto* p = UecDataPacket::newpkt(...);
    ...
+   // Find the lowest unacked packet to probe about
+   UecBasePacket::seq_t lowest_unacked =
+       _tx_bitmap.empty() ? _highest_sent : _tx_bitmap.begin()->first;
+   p->set_probe_payload_psn(lowest_unacked);
    ...
}
```

```cpp
// uec.cpp - processData()
void UecSink::processData(UecDataPacket& pkt) {
    if (pkt.packet_type() == UecBasePacket::DATA_PROBE) {
        ...
        UecAckPacket* ack_packet =
-           sack(pkt.path_id(), sackBitmapBase(pkt.epsn()), pkt.epsn(), ...);
+           sack(pkt.path_id(), sackBitmapBase(pkt.probe_payload_psn()), 
+                pkt.epsn(), ...);
        ...
    }
}
```

## 5. 其他重要部分

### 5.1 与 SLEEK 参数的关联

Probe 机制的行为可以通过以下参数配置：

```cpp
// uec.cpp 中的 SLEEK 参数
int UecSrc::probe_first_trial_time = 3;    // 首次发送 Probe 前的等待时间 (RTT 倍数)
int UecSrc::probe_retry_time = 5;          // Probe 重试间隔 (RTT 倍数)
float UecSrc::loss_retx_factor = 1.5;      // 触发快速重传的阈值因子
int UecSrc::min_retx_config = 5;           // 最小重传包数
```

### 5.2 Probe 的发送时机

Probe 的发送由 `runSleek()` 函数控制，在以下情况触发：

1. **正常 ACK 处理后**: 当 `cum_ack < _highest_sent` 或 `_backlog > 0` 时
2. **定时器触发**: `_probe_timer_when` 到期时调用 `sendProbe()`
3. **进入丢包恢复模式**: 收到延迟很低的 Probe ACK 时 (`delay < _target_Qdelay`)

### 5.3 调试信息

代码中包含大量调试输出，可通过设置 `_debug_flowid` 或 `_debug_src` 来追踪 Probe 行为：

```cpp
if (_flow.flow_id() == _debug_flowid) {
    cout << timeAsUs(eventlist().now()) << " flowid " << _flow.flow_id()
         << " sendProbe " << " _probe_seqno " << _probe_seqno + 1 << endl;
}
```

### 5.4 注意事项

1. **Probe 包是控制包**: Probe 包通过 `_nic.sendControlPacket()` 发送，优先级较高
2. **Probe 包没有 payload**: Probe 包大小为 `_hdr_size` (64 bytes)，只有头部
3. **Probe ACK 标记**: 接收方返回的 ACK 设置 `is_probe_ack = true`，发送方据此识别
4. **与 RTO 的关系**: Probe 机制是 RTO 的补充，不能替代 RTO，但可以减少 RTO 触发

---

**总结**: 本次修复通过添加 `probe_payload_psn` 字段，解决了 Probe 包 SACK bitmap 生成基准错误的问题，使 SLEEK 快速丢包恢复机制能够正常工作，从而提高了传输协议在丢包场景下的性能。
