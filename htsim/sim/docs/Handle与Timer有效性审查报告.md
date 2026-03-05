> [!IMPORTANT]
> **现状更新 (2026-03-04)**：
> - ❌ `eventlist.cpp` L143-144 的 assertion 顺序 Bug **仍然存在**（先解引用 handle 再检查 end()）
> - ⚠️ `uec.cpp` L1050 的 probe handle 解引用风险：虽然有 `_probe_timer_when != 0` 前置保护，但 handle 本身与 `_probe_timer_when` 不完全同步，风险未完全消除
> - ✅ L1058 现在会将 handle 重置为 `nullHandle()`

# Event Handle 与 Timer 有效性审查报告

> 审查范围：htsim 事件系统（`EventList`）、UEC 协议（`uec.cpp/h`）、EQDS 协议（`eqds.cpp/h`）  
> 审查时间：2026-02-20

---

## 0. 背景：Handle 的本质与风险

`EventList::Handle` 的声明为：

```cpp
typedef multimap<simtime_picosec, EventSource*>::iterator Handle;
```

它就是一个 `std::multimap` 的迭代器。`std::multimap` 在插入新元素时**不会使任何已有迭代器失效**，但在**删除对应元素后**，该迭代器立即变为"悬空迭代器"（dangling iterator）——对其解引用或以任何方式使用均为**未定义行为（UB）**。

`EventList` 中的"空迭代器"用最末位置表示：

```cpp
static Handle nullHandle() { return _pendingsources.end(); }
```

`cancelPendingSourceByHandle` 中有明确的注释：

```cpp
// be careful to ensure handle is still valid (L142 of eventlist.h)
assert(handle->second == &src);          // 解引用了 handle
assert(handle != _pendingsources.end()); // 与 end() 比较（在解引用之后！）
assert(handle->first >= now());
```

> [!CAUTION]
> 注意这三个 `assert` 的**顺序**：第一行已经解引用了 `handle`，第二行才检查是否为 `end()`。这意味着如果 `handle` 是 `end()`（nullHandle），第一行就会 UB（解引用 end() 迭代器）。

---

## 1. 确认 Bug：Probe Timer Handle 的不安全访问

**文件**：[uec.cpp L1049–1066](file:///home/wy/Code/uet-htsim/htsim/sim/src/protocols/uec.cpp#L1049-L1066)  
**严重级别**：🔴 高（未定义行为，可能导致崩溃或静默错误）

### 问题代码

```cpp
// processAck 中，SLEEK 模式启用时：
if (_probe_timer_when != 0) {
    if (_probe_timer_handle->second != this) {   // ← L1050: 危险！
        // ...
    }
    eventlist().cancelPendingSourceByHandle(*this, _probe_timer_handle); // ← L1056
    _probe_timer_when = 0;
    _probe_timer_handle = eventlist().nullHandle();
}
```

### 触发路径

`_probe_timer_when` 在以下情况下 `!= 0`，但 `_probe_timer_handle` 可能是 nullHandle：

```
sendProbe() 被调用
  → L2160: _probe_timer_when = now() + probe_retry_time * _base_rtt  (非零)
  → L2161: _probe_timer_handle = sourceIsPendingGetHandle(...)
           如果 probe_retry_time 后的时间点 >= endtime，
           sourceIsPendingGetHandle 返回 _pendingsources.end()
           但 _probe_timer_when 已经被设为非零！
```

此时 `_probe_timer_when != 0` 为真，但 `_probe_timer_handle == nullHandle()`，
对 `_probe_timer_handle->second` 的访问会解引用 `end()` 迭代器，触发 **UB**。

### 第二个触发路径

`doNextEvent` 中探测定时器触发时：

```cpp
// doNextEvent L1630:
_probe_timer_when = 0;  // 重置时间戳（注释说"Fix"）
sendProbe();            // sendProbe 内部会设新 handle
```

但 `doNextEvent` **没有**在 `_probe_timer_when = 0` 之前设置 `_probe_timer_handle = nullHandle()`。
接着 `sendProbe()` 内部（L2161）会给 `_probe_timer_handle` 赋新值，所以在 sendProbe 期间这个问题被掩盖了。  
但如果 `sendProbe()` 中的 `sourceIsPendingGetHandle` 返回了 nullHandle（近似模拟结束时），
`_probe_timer_handle` 就持有 nullHandle，而 `_probe_timer_when` 是非零的——下次 processAck 时就会触发上面的 Bug。

### 修复

```diff
 if (_probe_timer_when != 0) {
+    if (_probe_timer_handle != eventlist().nullHandle()) {
-        if (_probe_timer_handle->second != this) {
+        if (_probe_timer_handle->second != this) {
             // ...
         }
         eventlist().cancelPendingSourceByHandle(*this, _probe_timer_handle);
+        _probe_timer_handle = eventlist().nullHandle();
+    }
     _probe_timer_when = 0;
-    _probe_timer_handle = eventlist().nullHandle();
 }
```

---

## 2. 确认 Bug：doNextEvent 中 Probe Timer Handle 未清零

**文件**：[uec.cpp L1624–1634](file:///home/wy/Code/uet-htsim/htsim/sim/src/protocols/uec.cpp#L1624-L1634)  
**严重级别**：🟠 中（stale handle 留存，可能导致后续误用）

### 问题代码

```cpp
// doNextEvent - probe timer 触发路径：
if (_probe_timer_when != 0 && _probe_timer_when == eventlist().now()) {
    _probe_timer_when = 0;   // 只清了时间戳
    // 没有清 _probe_timer_handle！              ← Bug
    sendProbe();             // sendProbe 会覆盖 _probe_timer_handle
}
```

当 probe timer 正常触发时调用 `doNextEvent`，事件系统已经**从 `_pendingsources` 中移除**了对应条目（在 `EventList::doNextEvent` 中 `_pendingsources.erase(i)` 之后才调用 `EventSource::doNextEvent`）。

这意味着此刻 `_probe_timer_handle` 是一个指向**已删除条目**的失效迭代器（dangling iterator）。

- 如果 `sendProbe()` 调用成功，它会覆盖 `_probe_timer_handle`，掩盖了风险。
- 如果 sendProbe 内部提前 return（例如 NIC 阻塞），`_probe_timer_handle` 依然持有 stale handle 且 `_probe_timer_when` 已经是 0，下次比较时因为 0 的判断不进入 cancel，看起来"没问题"，但 handle 已是悬空状态。

### 修复

```diff
 if (_probe_timer_when != 0 && _probe_timer_when == eventlist().now()) {
     _probe_timer_when = 0;
+    _probe_timer_handle = eventlist().nullHandle();  // 明确清零
     sendProbe();
 }
```

---

## 3. 潜在风险：cancelPendingSourceByHandle 的 assert 顺序问题

**文件**：[eventlist.cpp L139–151](file:///home/wy/Code/uet-htsim/htsim/sim/src/core/eventlist.cpp#L139-L151)  
**严重级别**：🟡 低（assert 防御逻辑不完整）

```cpp
void EventList::cancelPendingSourceByHandle(EventSource &src, EventList::Handle handle) {
    assert(handle->second == &src);          // 先解引用
    assert(handle != _pendingsources.end()); // 再检查是否为 end()
    assert(handle->first >= now());
    ...
}
```

三个断言中，第 2 行的检查在第 1 行**之后**执行。如果 `handle == end()`（nullHandle），第 1 行就已经对 `end()` 迭代器解引用，产生 UB，根本不会走到第 2 行的检测。

这个问题本身不是业务逻辑 Bug，但它让防御性 assert 形同虚设：传入 nullHandle 时不会给出有意义的错误，而是直接 UB。

### 修复

```diff
 void EventList::cancelPendingSourceByHandle(EventSource &src, EventList::Handle handle) {
+    assert(handle != _pendingsources.end());  // 先检查是否为 end()
-    assert(handle->second == &src);
+    assert(handle->second == &src);           // 再解引用
-    assert(handle != _pendingsources.end());
     assert(handle->first >= now());
     ...
 }
```

---

## 4. 结构性风险：双重状态跟踪潜在不一致

**文件**：[uec.cpp](file:///home/wy/Code/uet-htsim/htsim/sim/src/protocols/uec.cpp)  
**严重级别**：🟡 低（目前逻辑正确，但容易在未来的修改中引入 Bug）

RTO 定时器的状态由**两个变量**共同描述：

| 变量 | 含义 |
|------|------|
| `_rtx_timeout_pending` (bool) | 宏观：Timer 是否在运行 |
| `_rto_timer_handle` (Handle) | 微观：Timer 在事件队列中的迭代器位置 |

当 `sourceIsPendingGetHandle` 返回 nullHandle（模拟结束时间之后），代码正确处理了：

```cpp
_rto_timer_handle = sourceIsPendingGetHandle(*this, _rtx_timeout);
if (_rto_timer_handle == eventlist().nullHandle()) {
    _rtx_timeout_pending = false;  // 两个状态同步清除
}
```

UEC 的 `cancelRTO`、`clearRTO` 也都保持了两者同步：

```cpp
void UecSrc::cancelRTO() {
    if (_rtx_timeout_pending) {
        eventlist().cancelPendingSourceByHandle(*this, _rto_timer_handle);
        clearRTO();  // clearRTO 会同时清 handle 和 pending 标志
    }
}
```

**风险点**：这两个变量必须始终保持一致，但 `doNextEvent` 中依赖 `now() == _rtx_timeout` 来区分"RTO 触发"与"流开始"事件：

```cpp
void UecSrc::doNextEvent() {
    if (_rtx_timeout_pending && eventlist().now() == _rtx_timeout) {
        clearRTO();           // 先清状态
        rtxTimerExpired();    // 再处理
    } else if (_highest_sent == 0) {
        startConnection();
    }
    // ...
}
```

这里没有 `else`，意味着如果两个条件都（意外地）同时满足，两条路径都会执行。如果条件都不满足，`doNextEvent` 会**静默返回**，不做任何事。后续事件将依赖其他包触发继续，这可能导致流卡死但不报错。

---

## 5. 其他协议的 Cancel 模式对比

| 协议/文件 | Cancel 方式 | 是否记录 Handle | 风险评估 |
|-----------|------------|---------------|---------|
| UEC RTO (`uec.cpp`) | `cancelPendingSourceByHandle` | ✅ `_rto_timer_handle` | ✅ 正确（详见 §4） |
| UEC Probe (`uec.cpp`) | `cancelPendingSourceByHandle` | ⚠️ `_probe_timer_handle` | 🔴 见 §1、§2 |
| EQDS RTO (`eqds.cpp`) | `cancelPendingSourceByHandle` | ✅ `_rto_timer_handle` | ✅ 正确（设计与 UEC RTO 相同） |
| Strack (`strack.cpp`) | `cancelPendingSource`（线性扫描） | ❌ 不用 Handle | ✅ 安全，代价是 O(n) 扫描 |
| Swift (`swift.cpp`) | `cancelPendingSource`（线性扫描） | ❌ 不用 Handle | ✅ 安全 |

---

## 6. 总结

| # | 位置 | 类型 | 严重级别 | 简述 |
|---|------|------|---------|------|
| Bug 1 | [`uec.cpp:1050`](file:///home/wy/Code/uet-htsim/htsim/sim/src/protocols/uec.cpp#L1050) | 确认 Bug | 🔴 高 | 解引用 `_probe_timer_handle` 前未检查是否为 nullHandle |
| Bug 2 | [`uec.cpp:1630`](file:///home/wy/Code/uet-htsim/htsim/sim/src/protocols/uec.cpp#L1630) | 确认 Bug | 🟠 中 | probe timer 触发后未清零 `_probe_timer_handle`，留下 stale handle |
| 风险 1 | [`eventlist.cpp:143`](file:///home/wy/Code/uet-htsim/htsim/sim/src/core/eventlist.cpp#L143) | 防御缺陷 | 🟡 低 | assert 顺序错误，端点检查在解引用之后 |
| 风险 2 | [`uec.cpp:1609`](file:///home/wy/Code/uet-htsim/htsim/sim/src/protocols/uec.cpp#L1609) | 结构风险 | 🟡 低 | 双重状态机（`_rtx_timeout_pending` + handle）需保持同步，未来易引入不一致 |

**共同根因**：Probe Timer 的生命周期管理没有采用与 RTO Timer 相同的模式（"使用 bool flag 作为主要状态，handle 作为加速取消的优化"），而是依赖 `_probe_timer_when != 0` 作为状态判断，同时在不一致的地方直接操作 handle，形成了潜在 UB。
