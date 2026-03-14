---
name: goal-radar
description: |
  A strict data schema protocol for constructing, modifying, and maintaining the Goal Radar task graph in Obsidian. 
  It defines absolute rules for generating relational primitives, state machine dictionaries, and entity formats to ensure a robust and clean task management system.
---

# 🤖 Goal Radar 数据结构与实体关系绝对协议 (Data Schema Protocol)

本协议是构建、修改和维护 Goal Radar 任务图谱的唯一底层标准。**Agent 在执行任何涉及任务规划、进度管理、阻碍记录的动作时，必须 100% 严格遵守**本协议中的固定字符串拼写、大小写和唯一语法格式，**严禁使用任何同义词或替代符号**。

**关键目录强制要求：所有由此规则生成的 Task 或 Issue Markdown 节点文件，必须且只能存放在 `AtomicRecords/Radar/` 目录下。**

## 一、 核心概念定义 (Core Concepts Definition)

在构建节点关系前，必须准确理解以下四大核心架构概念：

1. **纵向拆解 (Hierarchy)**
* **定义**：将一个宏大、抽象的父级目标，拆解为多个具体、可独立执行的子级模块。这是一种“整体与部分”的从属关系。
* **系统行为**：子节点的状态会自动自底向上汇聚（如：所有子节点完成，父节点自动完成）。

2. **横向阻塞 (Dependency/Blocking)**
* **定义**：严格的时序和逻辑因果约束。表示“如果不解决 A，则绝对无法开始/推进 B”。
* **系统行为**：一旦建立阻塞关系，被阻塞方将处于冻结状态，直到阻碍项被标记为“完成”或“取消”。

3. **方案迁移 (Migration/Iteration)**
* **定义**：发生路线变更。原定方案 A 被证明不可行或有了更优解，因此彻底放弃 A，全盘转向新方案 B。
* **系统行为**：这是一种“生态位继承”关系。系统会将旧节点 A 强制废弃，并将指向 A 的所有前置阻塞、历史依赖全部转移给新节点 B。

4. **资源参考 (Context/Resource)**
* **定义**：纯粹的信息引用、灵感来源或相关背景。
* **系统行为**：这是一种弱关联，**不产生任何物理阻塞或状态冻结**，仅用于提供上下文。

### 🔥 重要法则：全局强制双链提及 (Global Double-Link Rule)
**绝对禁止使用纯文本提及其他笔记！** 无论是在 YAML 属性区之下，还是在正文的任何角落里。凡是需要提及其他的 Task、Plan、Issue 或 Memo，**必须 100% 使用双中括号包裹完整文件名（不含 .md 后缀）**。
- ❌ 错误做法："之前在 Task-001 中发现了..."
- ❌ 错误做法："参考 `Plan-004` 执行"
- ✅ 正确做法："之前在 [[Task-001-Foundation_Repair]] 中发现了..."
- ✅ 正确做法："参考 [[Plan-004-Phase1_Code_Remediation]] 执行"

---

## 二、 关系原语规范 (Relational Primitives)

在 Markdown 文件的**正文区域**（绝不能写在 YAML 属性区），必须使用 Dataview 内联语法表达实体间的关联。
**语法标准格式**：`原语字段:: [[目标笔记名称]]` (冒号必须是英文双冒号，且目标必须包裹在双中括号内)。

每个维度的正反向关系均只有**唯一固定**的原语字段，严禁篡改：

| 关系维度 | 正向原语 (唯一值) | 反向原语 (唯一值) | 语境示例 |
| --- | --- | --- | --- |
| **阻塞 (Dependency)** | `Requires:: [[目标]]` | `Blocks:: [[目标]]` | A 需要 B 才能做：在 A 中写 `Requires:: [[B]]` |
| **迁移 (Migration)** | `Migrates To:: [[目标]]` | `Migrated From:: [[目标]]` | A 作废并由 B 替代：在 A 中写 `Migrates To:: [[B]]` |
| **拆解 (Hierarchy)** | `ParentTasks:: [[目标]]` | `SubTasks:: [[目标]]` | B 是 A 的子任务：在 B 中写 `ParentTasks:: [[A]]` |
| **资源 (Context)** | `Resource:: [[目标]]` | *(无反向原语)* | A 仅引用了 B 的情报：在 A 中写 `Resource:: [[B]]` |

---

## 三、 状态机绝对字典 (State Machine Dictionary)

无论是写入 Markdown 的 YAML 属性，还是修改 Todo 列表，都必须**完全一字不差**地映射为以下 5 级状态体系。Todo 事项的状态符号是唯一的，严禁使用替代符。

| 状态语义 (AI 判断依据) | 写入 YAML 属性的值 (`status:`) | 写入 Todo 列表的唯一字符 |
| --- | --- | --- |
| **计划** (尚未分配资源启动) | *不写 status 属性* 或 `0-🌱Idea` | `- [ ] ` |
| **执行** (正在积极推进中) | `1-🚀Active` | `- [/] ` |
| **阻塞** (被卡住/主动挂起暂停) | `2-💤Paused` | `- [=] ` |
| **完成** (目标达成/成果交付) | `3-✅Completed` | `- [x] ` |
| **取消** (验证失败/放弃/被替代) | `4-❌Cancelled` | `- [-] ` |

*(注：在生成 Todo 事项时，务必注意中括号内的字符必须严格匹配上表，且右中括号后必须跟一个空格)*

---

## 四、 实体生成协议 (Entity Generation Protocol)

根据用户的指令粒度，Agent 必须输出以下三种正确的实体格式之一，存入 `AtomicRecords/Radar/` 目录下：

### 实体 1：文件级 Task (File Node)

* **触发条件**：建立宏大目标、需要背景解释的模块、或者独立子项目。
* **物理结构**：完整的 Markdown 文件结构，包含 YAML 区。
* **强制要求**：YAML 区必须包含 `tags: [task]`。关系原语必须写在正文顶部。

### 实体 2：文件级 Issue (File Node)

* **触发条件**：记录 Bug 报错、面临决策分歧、单纯的情报记录。
* **物理结构**：完整的 Markdown 文件结构，包含 YAML 区。
* **强制要求**：YAML 区必须包含 `tags: [ibis/issue]`。通常在正文使用 `Resource::` 关联上下文，若阻断了任务则在被阻断任务中写入 `Requires::` 指向该 Issue。

### 实体 3：动作级 Todo (List Item Node)

* **触发条件**：具体的、几个小时内能做完的物理执行动作。
* **物理结构**：**禁止创建独立文件**。必须在上级 Task 文件的正文中，使用无序列表输出。
* **强制要求**：严格遵守状态机字典的唯一字符。支持使用空格缩进表达内部拆解。

---

## ⚡ 五、 综合标准执行范例 (Execution Playbooks)

Agent 在接收到人类的任务拆解指令后，应参照以下范式在 `AtomicRecords/Radar/` 生成纯净的 Markdown 源码。

### 场景 1：项目立项与混合拆解

**人类指令**：“新建一个任务：开发 V2 版本。第一阶段先搭框架，包含搞定 API 和配置数据库；第二阶段是写核心算法，这个算法单独建个任务跟进。框架搭建现在就开始做。”
**AI 产出**：
创建 `[[开发 V2 版本.md]]`：

```markdown
---
tags:
  - task
status: 1-🚀Active
---
# 第一阶段：搭框架
- [/] 搞定 API 接口
- [ ] 配置数据库

# 第二阶段：核心算法
SubTasks:: [[编写核心算法模块]]

```

创建 `[[编写核心算法模块.md]]`：

```markdown
---
tags:
  - task
---
ParentTasks:: [[开发 V2 版本]]

# 算法设计
（待补充）

```

### 场景 2：遭遇阻断与建立阻塞

**人类指令**：“在搞 API 接口的时候，发现老版本的鉴权 token 不通用了，这问题卡住我了，必须先解决。”
**AI 产出**：
创建 `[[Issue-老版本鉴权 Token 不通用.md]]`：

```markdown
---
tags:
  - ibis/issue
---
# 报错说明
发现老版本的 Token 验证逻辑在 V2 环境下抛出异常。

```

修改 `[[开发 V2 版本.md]]` (追加阻塞原语，并把对应 Todo 设为阻塞态)：

```markdown
---
tags:
  - task
status: 2-💤Paused
---
Requires:: [[Issue-老版本鉴权 Token 不通用]]

# 第一阶段：搭框架
- [=] 搞定 API 接口
- [ ] 配置数据库

```

### 场景 3：方案迭代与状态迁移

**人类指令**：“之前那个‘编写核心算法模块’太花时间了，作废掉。我决定直接用开源库，新建个任务来做这件事，现在就开始执行。”
**AI 产出**：
修改旧文件 `[[编写核心算法模块.md]]`：

```markdown
---
tags:
  - task
status: 4-❌Cancelled
---
Migrates To:: [[接入开源算法库]]
ParentTasks:: [[开发 V2 版本]]

```

创建新文件 `[[接入开源算法库.md]]`：

```markdown
---
tags:
  - task
status: 1-🚀Active
---
ParentTasks:: [[开发 V2 版本]]

# 执行步骤
- [/] 调研主流开源库
- [ ] 完成接口对接

```
