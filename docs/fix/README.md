# Fix 文档目录

本目录用于存放所有功能修复、Bug 修复和 Issue 相关的技术文档。

## 目录结构

```
docs/fix/
├── README.md                     # 本文件
├── probe-payload-psn-fix.md      # Probe 机制修复文档
└── ...                           # 其他修复文档
```

## 文档命名规范

- 使用小写字母和连字符（kebab-case）
- 格式: `<issue-name>-fix.md` 或 `<feature-name>-fix.md`
- 示例: `probe-payload-psn-fix.md`, `silent-packet-drop-fix.md`

## 文档内容规范

每个修复文档应包含以下部分：

1. **背景与问题** - 修复前的状态、存在的问题
2. **修复方案** - 具体的改动内容
3. **机制流程** - 修复后的工作流程（可用图表）
4. **关键概念** - 相关的技术概念解释
5. **代码变更** - 具体的代码修改位置
6. **其他说明** - 调试信息、注意事项等

## 现有文档

| 文件 | 说明 | 相关分支/Commit |
|------|------|-----------------|
| [probe-payload-psn-fix.md](./probe-payload-psn-fix.md) | Probe 机制修复：添加 probe_payload_psn 字段实现快速重传 | `fix/prb-seq` / `e3006d0` |

## 关联文档

- [Mechanism_Analysis_SLEEK.md](../Mechanism_Analysis_SLEEK.md) - SLEEK 机制分析
- [UEC_Probe_Mechanism_Fixes_CN.md](../UEC_Probe_Mechanism_Fixes_CN.md) - Probe 机制修复（历史文档）
