# UEC 协议调试 SOP：从现象到根因 (以 Silent Packet 11 为例)

本文档复盘了 "Packet 11 Silence" (接收端静默导致死锁) 问题的排查全过程，并总结出一套针对类似协议栈死锁问题的标准排查流程 (SOP)。

## 阶段一：现象确认与定位 (Symptom Identification)
**目标**：确定是丢包、错包还是死锁。

## 1. 快速定位 (Quick Localization)
**核心工具**: `BatchResult` + `Full Stack Analysis` (with Physical Arrival Tracking)

### 1.1 视觉诊断 (Visual Diagnosis) - **最快路径**
直接查看 "Full Stack Analysis" 图表 (`report.show()`)，寻找 **"Silent Packet 指纹"**：
*   **特征**:
    *   🔵 **正常发送 (Blue Dot)**: 存在。
    *   🟣 **物理接收 (Purple Diamond)**: **存在** (说明包物理上到了网卡)。*新特性*
    *   ⭐ **求救信号 (Yellow Star/AR)**: **不存在** (这是 Sender 逻辑问题的铁证)。*新特性*
    *   ❌ **物理丢包 (Red X)**: 不存在。
    *   🟢 **ACK (Green Dot)**: **不存在** (这是结果)。
*   **结论**: 
    1.  **包到了 (紫钻)** -> 排除链路丢包。
    2.  **Sender 没求救 (无黄星)** -> 排除 Sender 认为自己发完了（预测失误）。
    3.  **Receiver 没反应 (无绿点)** -> 确认 Receiver 遵守了“不求救就不回复”的沉默规则。
    *   *此时可直接判定为：Sender AR 预测失败 + Receiver 缺保底机制。*

### 1.2 传统辅助日志分析 (Legacy Log Analysis)

1.  **对比收发日志**：
    *   查看 **Sender Log**：确认 Packet 11 发出时间 (`Sent 11`)。查看后续事件，发现 Sender 触发了 RTO (`rtx timer expired`)。
    *   查看 **Receiver Log**：确认 Packet 11 是否到达。日志显示 `recv 11`。
2.  **判定性质**：
    *   Sender 发了 && Receiver 收了 && Sender 超时了 = **ACK 缺失 (Silence)**。
    *   排除物理丢包的可能性。
3.  **定位关键状态**：
    *   Packet 11 的身份：`EPSN(11) != Expected(0)` (假设中间包还没补齐)，确认它是 **乱序包 (Out-of-Order Packet)**。

## 阶段二：接收端逻辑审计 (Receiver Logic Audit)
**目标**：查明接收端为什么“看到了”却“不说话”。

1.  **代码定位**：`UecSink::processData`。
2.  **分支追踪**：
    *   Packet 11 是乱序的 -> 进入 `else` 分支 (非 In-Order 分支)。
3.  **ACK 触发条件核查**：
    *   检查该分支下是否有 `force_ack = true`？ -> **无**。
    *   检查 `shouldSack()` (字节阈值)？ -> 此时累积字节未达标 -> **False**。
    *   检查 `pkt.ar()` (AR 标志)？ -> 显然发送端没置位（否则会进 `force_ack` 逻辑）-> **False**。
    *   检查 `ecn`？ -> 无拥塞 -> **False**。
4.  **结论**：接收端代码逻辑对于“既没 AR，又没 ECN，又没凑够字节数”的乱序包，选择了**更新状态但保持沉默**。

## 阶段三：机制与规范缺口分析 (Mechanism & Spec Gap Analysis)
**目标**：判断“沉默”是 Bug 还是 Feature 缺失。

1.  **保底机制排查 (Safety Net Check)**：
    *   **Question**: 合并确认 (Coalesced ACK) 允许暂时沉默，但一定要有保底。保底在哪？
    *   **Check Timer**: 搜索 `UecSink` 类定义。
        *   有没有 `EventList::Handle` 成员？ -> **无**。
        *   有没有 `doNextEvent` 实现？ -> **无**。
    *   **Result**: 严重缺失 **GEN_ACK_TIMER**。这意味着如果代码逻辑不主动 ACK，就没有时间机制来兜底。

2.  **规范一致性分析**：
    *   规范要求：AR Flag, Timer, Threshold 三者互补。
    *   现状：Timer 缺失。单纯依赖 AR Flag 和 Threshold。

## 阶段四：发送端逻辑深究 (Sender Logic Deep Dive)
**目标**：既然 Receiver 依赖 AR Flag 来打破沉默，为什么 Sender 没给 Packet 11 打 AR？

1.  **代码定位**：`UecSrc::sendNewPacket` -> `set_ar()`。
2.  **条件分析**：
    *   逻辑：`if (Backlog==0 || WindowFull || CreditEmpty) set_ar(true)`。
    *   本质：这是一个**预测性**判断。Sender 试图在**发包前**预测“发完这个我就没能力发下一个了”。
3.  **漏洞发现 (The Gap)**：
    *   Sender 在发 Packet 11 时，计算 `InFlight + Pkt11Size < CWND`。结论：还能发。-> **不打 AR**。
    *   Sender 发完 Packet 11 后，更新 `InFlight`。
    *   准备发 Packet 12 时，计算 `InFlight + Pkt12Size > CWND`。结论：不能发。-> **停止发送**。
    *   **Result**: Sender 停在了 Packet 11 和 12 之间，但 Packet 11 身上没有“求救信号” (AR)。

## 根因总结 (Root Cause Summary)
这是一个典型的**多重失效 (Systemic Failure)**：
1.  **Rx Bug**: 接收端对 OOO 包处理不完整（未强制 ACK）。
2.  **Arch Defect**: 接收端缺失保底定时器 (No Timer)。
3.  **Tx Logic Gap**: 发送端的 AR 预测逻辑存在盲区，导致尾部包处于“由于预测失误而未置位 AR”的尴尬状态。

## 修复策略建议 (Fix Strategy)
1.  **Immediate Fix (Rx)**: 在 `processData` 的 OOO 分支强制 `force_ack = true`。这是最快且副作用最小的方案（打破死锁链）。
2.  **Robust Fix (Tx)**: 修改 AR 逻辑，采用 **Guaranteed Tail** 策略（只要 Backlog 为 0 或窗口利用率高就打 AR，不要预测）。
3.  **Long-term Fix (Arch)**: 实现接收端 `GEN_ACK_TIMER`。
