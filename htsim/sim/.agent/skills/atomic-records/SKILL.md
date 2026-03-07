---
name: atomic-records
description: |
  基于 ipynb 自动实现实验结果原子化记录与分析。
  从 Jupyter Notebook 中提取实验结果图片、实验配置，生成对应的原子化 Markdown 卡片
  （code / config / result 类型），统一写入 AtomicRecords/New/ 目录中。
---

# Atomic Records Skill

## 概述

本 Skill 用于从 Jupyter Notebook（`.ipynb`）文件中提取实验信息，生成**原子化 Markdown 卡片**，
存放于 `AtomicRecords/New/` 目录。每张卡片对应一个完整、独立的信息单元。

---

## 原子类别与格式规范

所有卡片均具有以下 YAML frontmatter：

```yaml
---
ctime: YYYY-MM-DD HH:mm:ss   # 创建时间（本地时间，已提供）
mtime: YYYY-MM-DD HH:mm:ss   # 修改时间（同 ctime，新建时相同）
tags:
  - <type>                    # code / config / result / claim
---
```

### 1. code 卡片（#code）

- **命名格式**: `Code-<项目名>-v<版本号>-<git_hash_short>.md`
  - 例：`Code-uet-htsim-v1.0-30f3ab3.md`
- **内容**: 直接基于 `docs/versions/CodeVersion_v<N>.md` 内容，提炼出版本标识、版本日期、核心特性摘要
- **写入前检查**: 扫描 `AtomicRecords/New/` 和 `AtomicRecords/Processed/` 下所有 `.md` 文件，
  若已存在相同 git hash 的 code 卡片则**直接复用，不重新生成**

格式示例：
```markdown
---
ctime: 2026-03-05 20:07:00
mtime: 2026-03-05 20:07:00
tags:
  - code
version: v1.0
git_hash: 30f3ab3
---

# htsim 代码版本 v1.0

**版本标识**: `30f3ab3` (dev branch, commit #383)
**版本日期**: 2026-02-03

## 核心特性
- 7 种传输协议（UEC 为主力）
- FatTree 等 8 种数据中心拓扑
- Python 分析工具链（BatchResult / AutoVisualizer）
- 基于 YAML 的批量实验框架

详见 [[CodeVersion_v1.0]]
```

---

### 2. config 卡片（#config）

- **命名格式**: `Conf-<序号(3位)>-<yaml文件名简写>.md`
  - 例：`Conf-002b-rs-锁定001-conns96事故点.md`
  - 序号从现有卡片中累加（扫描 New + Processed 中最大序号 +1）
- **内容**: 完整 YAML 配置（放在代码块中）+ 描述（该配置是如何构造的、有何特征）
- **去重规则（极其重要）**:
  - 写入前，提取待写入 config 的**完整有效配置内容**（去掉注释行，标准化后比较）
  - 扫描 New + Processed 两个目录下所有 config 卡片，提取其中的 YAML 代码块，进行精确比对
  - **只要有一个字段不同，就必须创建新卡片**，不能复用
  - 相同配置才复用，并在 result 卡片 source 中引用已有的 config 卡片名

格式示例：
```markdown
---
ctime: 2026-03-05 20:07:00
mtime: 2026-03-05 20:07:00
tags:
  - config
source_yaml: "002b-randseed-锁定001中conns96处事故点.yaml"
---

## 配置描述

本配置针对 conns=96 处的事故点展开扫描，使用 50 个随机种子（randseed 1-50），
对比开启/关闭 SLEEK 两种条件，其余参数与 Conf-002 保持一致（ECN 20p 80p，nscc CC）。

## 完整 YAML 配置

\`\`\`yaml
# 配置内容...
\`\`\`
```

---

### 3. result 卡片（#result）

- **命名格式**: `Res-<序号(3位)>-<描述性简称>.md`
  - 例：`Res-001-randseed-vs-sleek-fct-stats.md`
  - 序号从现有卡片中累加
- **关联的图片**: 提取自 ipynb cell 输出，保存为 PNG 文件（`<描述性名称>_<timestamp>.png`），
  置于 `AtomicRecords/New/` 中（与卡片同目录）
- **img 行内属性**: 使用双链形式 `![[filename.png]]`
- **source 属性**: 必须同时引用 code 卡片和 config 卡片，使用双链 `[[卡片名(不含.md)]]`
- **去重追踪（源信息）**: 在 frontmatter 中增加 `source_ipynb: "文件名"` 和 `source_cell: <行号>` 字段，用于后续运行提取时判定是否已为该 cell 生成过结果。
- **图表类型严格对齐机制（防止文不对题的致命红线）**: 在编写 `## 实验结果解读` 时，必须极其严格地保证所解读的内容与当前图片**真实对应的图表类型**完全匹配！
  - **强制校验步骤**：在提取 cell 内第 N 张图片时，必须同步解析该 cell 的文本输出（例如 `text/markdown` 中紧贴该图片的 `### <Plot Title>`），或者比对 `AutoVisualizer` 源码中的输出顺序，**绝对确认该图片的真实官方名称**（到底它是 `Bottleneck Correlation Analysis` 还是 `Incast Fan-in vs. Pressure`）。
  - **格式约束**：解读的第一条必须是 `- **图表类型**: <官方英文图名> (<中文翻译>)`，接下来的所有现象剖析必须严格基于该类型图表的坐标系（例如热力图、分层图、折线图），严禁凭感觉张冠李戴导致串台错乱。
- **内容结构**: 每个 result 文件的正文部分（img 之后）必须包含两个明确章节：
  1. `## 实验配置解析`：由于相同的 config 在不同的 code 版本下可能有不同含义（例如 ECN 阈值的单位变化），必须在此处解析该实验的具体背景、设置、场景定义，并明确指明具体的配置含义。
  2. `## 实验结果解读`：结合代码现实、实验配置，对图片展示的图表特征、微观现象、背后的网络机制机理进行深入分析解读。
- **引用规范（极其重要）**: 当文中需要提及或引用其他图片或其他卡片（不论是 code, config, result 还是 claim 时），**一律使用双链形式**（如 `[[Res-011-cell_8_img_3]]` 注意：**外面绝对不要套反引号 ``，直接写 `[[名称]]` 即可**）。链接务必与目标卡片的文件名（不含扩展名）完全精确匹配，一个字都不能差。

格式示例：
```markdown
---
ctime: 2026-03-05 20:07:00
mtime: 2026-03-05 20:07:00
tags:
  - result
source:
  - "[[Code-uet-htsim-v1.0-30f3ab3]]"
  - "[[Conf-002b-rs-锁定001-conns96事故点]]"
source_ipynb: "不同配置下的randseed测试.ipynb"
source_cell: 3
---

img:: ![[Res-001-randseed-vs-sleek-fct-stats_20260305_200700.png]]

## 实验配置解析

本实验运行于 `[[Conf-002b-rs-锁定001-conns96事故点]]` 配置下。该配置使用 conns=96 进行高并发测试。结合 `[[Code-uet-htsim-v1.0-30f3ab3]]` 代码版本，此时 ECN 阈值单位被处理为...

## 实验结果解读

图表显示了系统吞吐量在 300us 后出现的断崖式下跌。相比于 `[[Res-011-cell_8_img_3]]` 中的结果，我们发现...
```

---

### 4. claim 卡片（#claim）

- 格式更自由，一般**等用户主动提示**再生成
- 可引用多个 result、或直接内嵌图片，或两者皆可
- **命名格式**: `Claim-<序号(3位)>-<简述>.md`

---

## 工作流程

### 触发场景

当用户说"基于 XXX.ipynb 提取实验卡片"时，执行以下步骤：

### Step 1: 读取 ipynb 文件

使用辅助脚本 `scripts/extract_ipynb_records.py` 解析 ipynb：

```bash
python3 .agent/skills/atomic-records/scripts/extract_ipynb_records.py \
    --ipynb <ipynb文件路径> \
    --atomic-dir AtomicRecords \
    --dry-run   # 先用 dry-run 查看将生成什么，再决定是否实际写入
```

该脚本会输出：
- 找到了哪些 code cell + markdown section
- 每个图表对应的 YAML 配置来源（哪个 `.yaml` 文件）
- 将生成哪些卡片

### Step 2: 识别代码版本

1. 读取 `docs/versions/` 下最新的 `CodeVersion_v*.md`，提取 git hash
2. 在 `AtomicRecords/New/` 和 `AtomicRecords/Processed/` 中查找对应 code 卡片
3. 如已存在 → 记录卡片名备用；如不存在 → 生成新 code 卡片

### Step 3: 识别实验配置

对 ipynb 中每个含图片的 code cell：
1. 向上追溯，找到 `BatchResult()` 初始化和 `.add_source(yaml_path)` 调用
2. 读取对应 YAML 文件全部内容
3. 对 YAML 内容进行去重比对（与 New + Processed 中所有已有 config 卡片比对）
4. 若完全相同 → 复用已有 config 卡片；若有任何差异 → 创建新 config 卡片

### Step 4: 提取图片并生成 result 卡片

对每个含 `image/png` 输出的 code cell：
1. 提取 base64 编码的 PNG 数据，解码后存为 `AtomicRecords/New/<filename>.png`
2. 生成对应的 result 卡片，`img::` 使用该 PNG 的双链引用
3. 去重检查：扫描已有 Result 卡片的 `source_ipynb` 和 `source_cell`，如果当前 cell 已经生成过，则跳过提取。
4. 图表描述：分析 cell 代码（`plot_statistical_summary`、`plot_facet` 等调用的参数），
   结合上方 markdown section 标题，生成简要描述

### Step 5: 验证与汇总

列出所有生成的卡片，告知用户：
- 生成了哪些新卡片（code / config / result）
- 复用了哪些已有卡片（附上卡片名）
- 各卡片的文件路径

---

## 辅助脚本说明

详见 `scripts/extract_ipynb_records.py`，该脚本提供：
- `parse_ipynb(path)`: 解析 ipynb，返回结构化的 cell 信息
- `extract_yaml_source(cells, image_cell_idx)`: 向上追溯找到对应 YAML 配置
- `extract_image(cell)`: 从 cell 输出中提取 base64 PNG 并解码
- `find_existing_configs(atomic_dir)`: 扫描 New + Processed 目录读取所有 config 卡片的 YAML 块
- `config_matches(yaml_content, existing_yaml_block)`: 精确比对配置是否完全相同
- `next_card_index(atomic_dir, prefix)`: 扫描现有卡片，返回下一个可用序号

---

## 重要约束

1. **写入路径**: 新卡片和新图片**一律写入 `AtomicRecords/New/`**，不写 Processed
2. **读取路径**: 查重时同时扫描 `AtomicRecords/New/` 和 `AtomicRecords/Processed/`
3. **双链引用**: 卡片间引用、图片引用一律使用 `[[名称]]`（不含路径前缀，不含 `.md` 扩展名）
4. **图片引用**: 在 result 卡片的 img:: 中必须使用 `![[filename.png]]` 格式
5. **config 去重**: 宁可多创建一个 config 卡片，也绝不错误复用——只有 100% 一致才能复用
6. **时间戳**: ctime 和 mtime 使用系统提供的当前本地时间（已在 ADDITIONAL_METADATA 中提供）
7. **claim 卡片**: 一般仅在用户明确提示时才生成，不在常规 ipynb 提取流程中自动生成

---

## 文件命名快速参考

| 类型   | 命名格式                                                    | 示例                                           |
|--------|-------------------------------------------------------------|------------------------------------------------|
| code   | `Code-<项目名>-v<版本>-<hash>.md`                          | `Code-uet-htsim-v1.0-30f3ab3.md`             |
| config | `Conf-<NNN>-<yaml简称>.md`                                 | `Conf-002b-rs-锁定001-conns96事故点.md`        |
| result | `Res-<NNN>-<描述性简称>.md`                                | `Res-001-randseed-vs-sleek-fct-stats.md`       |
| claim  | `Claim-<NNN>-<简述>.md`                                    | `Claim-001-增大conns触发FCT崩溃.md`            |
| 图片   | `<描述>_<YYYYMMDD_HHmmss>.png`                             | `randseed_vs_sleek_fct_stats_20260305_200700.png` |
