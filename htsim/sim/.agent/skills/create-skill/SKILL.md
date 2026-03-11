---
name: create-skill
description: |
  将重复性工作流程固化为可复用的 Skill。
  提供完整的 skill 创建指南、模板和自动化脚本。
  遵循项目现有 skill 格式规范（参考 atomic-records 等）。
---

# Create Skill - Skill 创建指南

## 概述

本 Skill 用于指导如何将重复性的工作流程、工具脚本、最佳实践固化为可复用的 **Skill**。每个 Skill 都是一个独立的模块，包含文档、脚本和配置示例。

---

## 何时创建 Skill

当遇到以下情况时，应考虑创建 Skill：

1. **重复性工作** - 某项任务需要多次执行，步骤相似
2. **最佳实践** - 某个流程已经验证有效，值得推广
3. **工具封装** - 有实用脚本需要标准化和文档化
4. **知识沉淀** - 某个领域的经验需要系统化记录
5. **AI 辅助** - 需要为 AI agent 提供明确的操作指南

---

## Skill 标准格式

### 文件结构

```
.agent/skills/<skill-name>/
├── SKILL.md                          # Skill 文档（YAML frontmatter 格式）
├── scripts/                          # 脚本目录（可选）
│   └── <script-name>.py              # 相关脚本
└── config-example.yaml               # 配置示例（可选）
```

### SKILL.md 格式

```markdown
---
name: <skill-name>
description: |
  <2-3 句话描述 skill 的功能和用途>
---

# <Skill Name> - <副标题>

## 概述

<详细说明 skill 的用途、适用场景>

---

## 文件结构

```
<显示 file tree>
```

---

## 使用方法

### 方式 1: 命令行

```bash
<命令示例>
```

### 方式 2: Python 调用

```python
<代码示例>
```

### 方式 3: AI Agent 自动调用

<说明 AI 如何自动使用此 skill>

---

## 配置说明

<如果有配置文件，详细说明格式>

### 基本结构

```yaml
<配置示例>
```

### 完整示例

<提供完整的配置示例>

---

## 可用模块/功能

<分章节详细介绍各个功能模块>

### 1. 模块名称

```yaml
<配置方式>
```

---

## 示例场景

### 场景 1: <场景名称>

```yaml
<配置示例>
```

---

## 依赖

- <依赖 1>
- <依赖 2>
- ...

---

## 输出

<说明生成的内容格式和特点>

---

## 故障排查

### 问题 1: <问题描述>

**症状**: <错误信息>

**解决**: <解决方法>

---

## 扩展开发

<说明如何扩展功能>

---

## 相关文件

- <相关文件路径>

---

**版本**: 1.0  
**创建日期**: YYYY-MM-DD  
**维护者**: <名称>  
**依赖**: <依赖列表>
```

---

## 创建步骤

### Step 1: 确定 Skill 名称

- 使用小写字母和连字符（如 `generate-html-report`）
- 名称应清晰反映功能（动词 + 名词）
- 避免与现有 skill 重名

### Step 2: 创建目录结构

```bash
# 创建基本结构
mkdir -p .agent/skills/<skill-name>/scripts

# 或使用脚本
python3 .agent/skills/create-skill/scripts/init-skill.py --name <skill-name>
```

### Step 3: 编写 SKILL.md

1. 复制 `SKILL_TEMPLATE.md`
2. 填写 YAML frontmatter（name, description）
3. 按照模板结构编写内容
4. 提供完整的代码示例

### Step 4: 开发脚本（如需要）

```python
# scripts/<script-name>.py
#!/usr/bin/env python3
"""
<脚本名称>
============
功能描述
"""

# 实现代码...
```

### Step 5: 创建配置示例（如需要）

```yaml
# config-example.yaml
# 提供详细注释
# 包含所有配置项
```

### Step 6: 测试验证

```bash
# 测试 skill 功能
<测试命令>

# 验证生成的内容
<验证命令>
```

### Step 7: 提交

```bash
git add .agent/skills/<skill-name>/
git commit -m "feat(skill): add <skill-name> skill"
```

---

## 设计规范

### YAML Frontmatter

```yaml
---
name: <skill-name>           # 必填：skill 名称（与目录名一致）
description: |               # 必填：2-3 句话描述
  <描述内容>
---
```

### 文档结构

1. **概述** - 说明用途和适用场景
2. **文件结构** - 展示目录布局
3. **使用方法** - 提供多种使用方式
4. **配置说明** - 详细的配置指南
5. **示例场景** - 实际应用场景
6. **故障排查** - 常见问题解答

### 代码示例

- 使用代码块标注语言类型
- 提供完整的可运行示例
- 添加必要的注释说明

### 配置示例

- 提供详细注释
- 包含所有配置项
- 可直接复制使用

---

## 质量检查清单

在提交 Skill 前，请确认：

- [ ] SKILL.md 包含 YAML frontmatter
- [ ] name 与目录名一致
- [ ] description 清晰简洁
- [ ] 提供完整的使用示例
- [ ] 配置示例可直接使用
- [ ] 脚本可正常运行
- [ ] 文档结构清晰
- [ ] 代码有适当注释
- [ ] 提供故障排查指南
- [ ] 测试通过

---

## 最佳实践

### 1. 命名规范

```
✅ generate-html-report
✅ atomic-records
❌ GenerateHTMLReport
❌ my-skill
```

### 2. 文档编写

- 使用简洁清晰的语言
- 提供多种使用场景
- 包含完整的示例
- 添加故障排查章节

### 3. 脚本开发

- 使用 `#!/usr/bin/env python3`
- 添加详细的 docstring
- 提供命令行参数
- 处理异常情况

### 4. 配置设计

- 使用 YAML 格式
- 提供详细注释
- 包含默认值
- 示例可直接使用

---

## 示例 Skill

### 示例 1: generate-html-report

**用途**: 生成模块化 HTML 实验报告

**文件结构**:
```
.agent/skills/generate-html-report/
├── SKILL.md
├── scripts/
│   └── generate_modular_html_report.py
└── config-example.yaml
```

**核心功能**:
- 模块化设计（8 种模块类型）
- YAML 配置
- Chart.js 交互图表

### 示例 2: atomic-records

**用途**: 从 Jupyter Notebook 提取实验卡片

**文件结构**:
```
.agent/skills/atomic-records/
├── SKILL.md
└── scripts/
    └── extract_ipynb_records.py
```

**核心功能**:
- 解析 ipynb 文件
- 提取图片
- 追溯 YAML 配置
- 生成原子化卡片

---

## 自动化脚本

### init-skill.py

用于快速创建 Skill 骨架：

```bash
python3 .agent/skills/create-skill/scripts/init-skill.py \
  --name <skill-name> \
  --description "<描述>"
```

### validate-skill.py

用于验证 Skill 格式：

```bash
python3 .agent/skills/create-skill/scripts/validate-skill.py \
  .agent/skills/<skill-name>/
```

---

## 相关文件

- `.agent/skills/generate-html-report/SKILL.md` - 示例 Skill
- `.agent/skills/atomic-records/SKILL.md` - 示例 Skill
- `.agent/skills/` - Skills 目录

---

## 参考资料

- [Skill 设计规范] - 项目内部规范文档
- [YAML Frontmatter] - Jekyll 文档
- [Python 脚本规范] - PEP 8

---

**版本**: 1.0  
**创建日期**: 2026-03-11  
**维护者**: Atlas  
**依赖**: Python 3.7+, PyYAML
