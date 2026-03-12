# GEN_ACK_TIMER 修复 - 快速实验指南

## 🚀 快速开始

### 1. 运行对比实验

```bash
cd /home/wy/Code/worktrees/uet-htsim/fix/probe-seq/htsim/sim
bash scripts/run_gen_ack_timer_comparison.sh
```

**预计耗时**: 约 10-20 分钟（取决于编译速度和实验规模）

### 2. 查看结果

```bash
# 查看日志
cat results/gen_ack_timer_comparison/buggy/run.log
cat results/gen_ack_timer_comparison/fixed/run.log

# 查找 GEN_ACK_TIMER 触发记录
grep "GEN_ACK_TIMER" results/gen_ack_timer_comparison/fixed/run.log
```

---

## 📊 手动分析指南

### 关键指标提取

#### RTO 次数对比

```bash
# 修复前
grep -i "rto" results/gen_ack_timer_comparison/buggy/run.log | tail -10

# 修复后
grep -i "rto" results/gen_ack_timer_comparison/fixed/run.log | tail -10
```

#### GEN_ACK_TIMER 触发

```bash
# 统计触发次数
grep -c "GEN_ACK_TIMER expired" results/gen_ack_timer_comparison/fixed/run.log

# 查看触发时间点
grep "GEN_ACK_TIMER expired" results/gen_ack_timer_comparison/fixed/run.log | head -20
```

#### 流完成时间

```bash
# 从日志中提取流完成时间（具体命令取决于日志格式）
grep "flow.*completed" results/gen_ack_timer_comparison/*/run.log
```

---

## 📈 预期结果

### 定性预期

| 指标 | 修复前 | 修复后 | 说明 |
|------|--------|--------|------|
| GEN_ACK_TIMER 触发 | 0 次 | >0 次 | 修复后才正常工作 |
| RTO 触发 | 较多 | 较少 | GEN_ACK_TIMER 提前触发 ACK |
| 长尾延迟 | 较长 | 较短 | 减少"干等 RTO"情况 |

### 定量示例（仅供参考）

```
修复前 (Buggy):
  - GEN_ACK_TIMER 触发：0 次 (完全失效)
  - RTO 触发：~150 次
  - 流完成时间 P99: ~850 us

修复后 (Fixed):
  - GEN_ACK_TIMER 触发：~45 次
  - RTO 触发：~30 次 (减少 80%)
  - 流完成时间 P99: ~450 us (减少 47%)
```

---

## 🔍 验证修复确实生效

### 方法 1: 检查代码

```bash
# 查看当前版本的定时器注册代码
git show HEAD:src/protocols/uec.cpp | grep -A5 "start_gen_ack_timer"

# 应该看到 *(EventSource*)this 而不是 *(EventSource*)_src
```

### 方法 2: 查看日志

修复后版本应该在日志中看到：
```
GEN_ACK_TIMER expired. Sending explicit cumulative ACK: <seqno>
```

如果没有看到这条日志，可能原因：
1. 编译时使用了旧代码（忘记重新编译）
2. 实验场景没有触发 GEN_ACK_TIMER（参数不合适）
3. 日志级别不够详细

---

## ⚠️ 常见问题

### Q1: 编译失败

**症状**: `cmake --build` 报错

**解决**:
```bash
# 清理构建缓存
rm -rf out/Debug
cmake --build out/Debug --target htsim_uec
```

### Q2: 切换分支后忘记重新编译

**症状**: 实验结果与预期不符

**解决**:
```bash
git checkout <branch>
cmake --build out/Debug --target htsim_uec  # 必须重新编译！
```

### Q3: GEN_ACK_TIMER 没有触发

**可能原因**:
1. 流太小，在定时器触发前就完成了
2. 其他 ACK 触发机制（ECN、AR Flag）已经触发了 ACK
3. 乱序包数量不足

**尝试调整参数**:
```bash
# 增大流大小
./bin/htsim_uec -c 96 -f 32 -n 100 ...

# 或增加并发度
./bin/htsim_uec -c 192 -f 12 -n 100 ...
```

### Q4: 实验结果波动大

**解决**: 多次运行取平均值
```bash
# 运行 3 次
for i in {1..3}; do
  ./bin/htsim_uec -c 96 -f 12 -n 100 --output "results/run_$i/"
done
```

---

## 📚 背景知识

### 问题是什么？

接收方收到乱序包后不会立即返回 ACK，而是"凑够再返"（Coalesced ACK）。但如果：
- 流的最后几个包
- 不含 AR Flag
- 不含 ECN 标记
- 不满足计数器阈值

接收方就会"干等"，明明收到了包却不返回 ACK，只能等待发送方 RTO 超时。

### GEN_ACK_TIMER 的作用

作为一个**时间兜底机制**，在其他 ACK 触发条件都失效时，定时器超时后强制返回 ACK，避免无谓的 RTO 等待。

### Bug 在哪里？

commit `68d8d09` (atseis, 2026-03-07) 实现了 GEN_ACK_TIMER，但定时器被错误地注册到发送方 (`_src`) 而不是接收方自身 (`this`)。

**后果**: 定时器到期时调用的是 `UecSrc::doNextEvent()` 而不是 `UecSink::doNextEvent()`，导致 GEN_ACK_TIMER 完全失效！

### 修复内容

让 `UecSink` 继承 `EventSource`，并将定时器注册到 `this`。

---

## 🔗 相关文档

- Plan-004-T1-Receiver-Timer-Fix.md - 修复计划
- Plan-004-T1-Experiment.md - 详细实验设计
- Plan-004-Phase1_Code_Remediation.md - Phase1 总体修复计划

---

## 📞 需要帮助？

1. 检查 `.sisyphus/plans/` 目录中的详细计划
2. 查看实验日志中的错误信息
3. 确保正确切换分支并重新编译
