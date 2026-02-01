# SLEEK Mechanism Analysis: Active Probing & Fast Retransmit

This document provides a code-level analysis of the SLEEK congestion control mechanism implemented in `UEC`, specifically verifying the logic for **Active Probing** and **RTT-based Loss Recovery**.

## 1. Mechanism Overview (The User's Model)
The user's diagram describes the following workflow:
1.  **Silence**: Window is limited or no data to send.
2.  **Probe Timer**: Fires after a timeout (`base_rtt + target_Qdelay`).
3.  **Active Probe**: Sends a `DATA_PROBE` packet to "break the silence".
4.  **Probe ACK**: Receiver forces an ACK (`PROB_ACK`).
5.  **RTT Check**: Sender checks if `RTT < Target_Qdelay`.
6.  **Loss Recovery**: If RTT is low but data is unacked, interpret as **LOSS**, not congestion -> Trigger Retransmission.

## 2. Code Evidence (Verification)

### A. Setting the Probe Timer
**Location**: `UecSrc::processAck` (Lines 1060-1067)
When an ACK is received, the sender schedules a probe if conditions are met:

```cpp
1060: if (cum_ack < _highest_sent || _backlog > 0) {
1061:     if (_backlog == 0) {
              // Standard timeout: RTT + Target Delay
1062:         _probe_timer_when = eventlist().now() + (_base_rtt + _target_Qdelay);
1063:     } else {
              // Aggressive timeout if we have backlog
1064:         _probe_timer_when = eventlist().now() + probe_first_trial_time * _base_rtt;
1065:     }
1066:     _probe_timer_handle = eventlist().sourceIsPendingGetHandle(*this, _probe_timer_when);
1067: }
```
*Evidence confirmed.*

### B. Sending the Probe
**Location**: `UecSrc::doNextEvent` -> `sendProbe`
When the timer fires, `sendProbe` creates and transmits a `DATA_PROBE` packet.
*Evidence confirmed (Verified in previous steps).*

### C. The Critical Link: RTT Check & Loss Trigger
**Location**: `UecSrc::processAck` (Lines 1068-1075)
This is the logic that was previously "hidden" by the `is_probe_ack` bug.

```cpp
// 1. Check if it is a Probe ACK (fixed by recent patch)
// 2. Check if RTT is low (Low Delay = Path is empty = Loss, not Congestion)
1068: if (pkt.is_probe_ack() && delay < _target_Qdelay) {
1069:     _loss_recovery_mode = true;         // <--- ENTER LOSS RECOVERY
1070:     _recovery_seqno = _highest_sent;    // Mark recovery point
1071:     _highest_rtx_sent = cum_ack;        // Reset retransmit pointer
1072:     if (_flow.flow_id() == _debug_flowid) {
1073:         cout << ... " enter_loss_probe " ... endl;
1074:     }
1075: }
```
*Evidence confirmed.*

### D. Why It Was "Missing" (The Paradox)
Before the fix, the Receiver sent Probe ACKs with `is_probe_ack = false`.
The Sender's check at **Line 1068** (`pkt.is_probe_ack()`) always failed.
*   **Result**: The code block lines 1069-1075 was **Dead Code**.
*   **Consequence**: The "Active Probing" happened (packets sent), but the "Fast Retransmit" trigger (the intelligence) was disabled.

## 3. Conclusion
The code **fully supports** the mechanism described in your diagram. With the fix applied:
1.  **Probe ACKs** will now pass the `is_probe_ack()` check.
2.  **RTT Measurement** (`delay`) will be valid.
3.  **Low RTT** will correctly trigger `_loss_recovery_mode`.
4.  **Retransmission** (`resendPacket`) will begin immediately from `cum_ack`.

This aligns perfectly with the design intent: distinguishing **Congestion** (High RTT -> Back off) from **Loss** (Low RTT -> Retransmit).
