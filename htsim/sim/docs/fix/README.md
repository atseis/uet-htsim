# docs/fix/ - 修复与功能文档目录

本目录存放与 **Bug 修复、功能实现、Issue 解决** 相关的技术文档。

## 目录结构

```
docs/fix/
├── README.md                           # 本文件
├── BRANCH_CHANGES_SUMMARY.md           # 当前分支（fix/rcver-timer）完整修改说明
├── BugReport_SilentPacket11.md         # Silent Packet 11 Bug 分析报告
├── Experiment_GEN_ACK_Timer_Fix.md     # GEN_ACK_TIMER 修复验证实验报告
├── GEN_ACK_Timer_快速指南.md            # GEN_ACK_TIMER 快速实验指南
├── Handle与Timer有效性审查报告.md       # Event Handle 与 Timer 安全性审查
└── UEC_Probe_Mechanism_Fixes_CN.md     # UEC Probe 机制修复文档
```

## 文档分类

### Bug 修复

| 文档 | 问题描述 | 状态 |
|------|----------|------|
| `BugReport_SilentPacket11.md` | Packet 11 "诡异静默" - ACK 缺失导致死锁 | ❌ 未修复 |
| `Handle与Timer有效性审查报告.md` | Event Handle 悬空迭代器风险 | ⚠️ 部分修复 |
| `UEC_Probe_Mechanism_Fixes_CN.md` | 僵尸 Probe 死循环、Probe 机制缺陷 | ✅/❌ 部分修复 |
| `Experiment_GEN_ACK_Timer_Fix.md` | GEN_ACK_TIMER 定时器注册错误 | ✅ 已修复 |

### 实验与验证

| 文档 | 内容 |
|------|------|
| `Experiment_GEN_ACK_Timer_Fix.md` | GEN_ACK_TIMER Bug 修复对照实验 |
| `GEN_ACK_Timer_快速指南.md` | 快速验证修复效果的实验指南 |

### 分支修改汇总

| 文档 | 内容 |
|------|------|
| `BRANCH_CHANGES_SUMMARY.md` | fix/rcver-timer 分支所有修改的完整说明 |

## 使用指南

### 查找特定问题的文档

1. **GEN_ACK_TIMER 相关问题**
   - 完整说明: `BRANCH_CHANGES_SUMMARY.md` §1
   - 实验报告: `Experiment_GEN_ACK_Timer_Fix.md`
   - 快速验证: `GEN_ACK_Timer_快速指南.md`

2. **Probe 机制问题**
   - 修复文档: `UEC_Probe_Mechanism_Fixes_CN.md`

3. **Timer/Handle 安全问题**
   - 审查报告: `Handle与Timer有效性审查报告.md`

4. **ACK 缺失/静默包问题**
   - Bug 报告: `BugReport_SilentPacket11.md`

### 文档命名规范

- `BugReport_*.md` - Bug 分析报告
- `Experiment_*.md` - 实验验证报告
- `Fix_*.md` - 修复说明（如有）
- `*_快速指南.md` - 快速操作指南

## 与外部文档的关系

```
docs/
├── fix/                    # ← Bug 修复、功能实现相关
│   ├── BugReport_*.md
│   ├── Experiment_*.md
│   └── Fix_*.md
├──
├── Mechanism_Analysis_*.md # 机制分析（根目录）
├── UEC_*_Architecture.md   # 架构设计（根目录）
├── Incast微突发稳定性研究.md  # 研究文档（根目录）
└── ...                     # 其他通用文档
```

## 维护说明

- 新修复文档请放入本目录
- 文档首行添加状态标记（如 `> [!IMPORTANT]`）
- 关联 Issue/PR 请在文档中明确标注

---

**维护者**: Atlas  
**最后更新**: 2026-03-12
