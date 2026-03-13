---
name: generate-html-report
description: |
  生成模块化、可配置的交互式 HTML 实验报告。
  支持动态增减内容模块，适用于各种实验场景。
  使用 YAML 配置文件控制报告内容和布局，使用 Chart.js 实现交互式图表。
---

# Generate HTML Report Skill

## 概述

本 Skill 用于根据 YAML 配置文件自动生成模块化的 HTML 实验报告。报告包含多种可配置的内容模块（文本、代码对比、表格、图表、流程图等），使用 Chart.js 实现交互式可视化。

---

## 文件结构

```
.agent/skills/generate-html-report/
├── SKILL.md                          # 本文件
├── scripts/
│   └── generate_modular_html_report.py  # 生成器脚本
└── config-example.yaml               # 配置示例
```

---

## 使用方法

### 方式 1: 命令行

```bash
# 从项目根目录运行
python3 .agent/skills/generate-html-report/scripts/generate_modular_html_report.py \
  --config my-config.yaml \
  --output report.html
```

### 方式 2: 在 Python 脚本中使用

```python
from pathlib import Path
import sys

sys.path.insert(0, '.agent/skills/generate-html-report/scripts')
from generate_modular_html_report import ModularHTMLReportGenerator

generator = ModularHTMLReportGenerator('my-config.yaml')
generator.generate('report.html')
```

### 方式 3: AI Agent 自动调用

AI Agent 在需要生成 HTML 报告时，会自动：
1. 创建配置文件（基于实验数据）
2. 调用生成器脚本
3. 生成最终报告

---

## 配置文件格式

### 基本结构

```yaml
report:
  title: "实验名称"
  date: "2026-03-11"

modules:
  enabled:
    - text_section
    - code_comparison
    - data_table
    - chart_bar
  order:
    - text_section
    - code_comparison
    - data_table
    - chart_bar
  config:
    text_section:
      title: "📋 摘要"
      content: "..."
    chart_bar:
      chart_id: "myChart"
      labels: ["A", "B", "C"]
      datasets: [...]

data_sources:
  buggy_log: "results/buggy.log"
  fixed_log: "results/fixed.log"

config_file: "my-config.yaml"
```

### 完整示例

完整配置示例请参考 `config-example.yaml` 文件，其中包含：
- 所有 8 种模块类型的配置示例
- 详细的注释说明
- 可直接运行的 GEN_ACK_TIMER 实验报告配置

---

## 可用模块类型

### 1. text_section - 文本章节

```yaml
text_section:
  title: "📋 章节标题"
  content: "章节内容..."
```

### 2. code_comparison - 代码对比

```yaml
code_comparison:
  title: "💻 代码对比"
  buggy_title: "修复前"
  fixed_title: "修复后"
  buggy_code: "..."
  fixed_code: "..."
  buggy_issue: "问题描述"
  fixed_improvement: "改进说明"
```

### 3. data_table - 数据表格

```yaml
data_table:
  title: "📊 数据对比"
  headers: ["列 1", "列 2", "列 3"]
  rows:
    - ["值 1", "值 2", "值 3"]
```

### 4. chart_bar - 柱状图

```yaml
chart_bar:
  chart_id: "myBarChart"
  title: "性能对比"
  labels: ["P50", "P90", "P99"]
  datasets:
    - label: "修复前"
      data: [47, 85, 94]
      backgroundColor: "rgba(231, 76, 60, 0.7)"
```

### 5. chart_line - 折线图

```yaml
chart_line:
  chart_id: "myLineChart"
  title: "延迟趋势"
  labels: ["0s", "1s", "2s"]
  datasets:
    - label: "修复前"
      data: [100, 120, 90]
      borderColor: "rgba(231, 76, 60, 1)"
```

### 6. flowchart - 流程图

```yaml
flowchart:
  title: "⚙️ 工作流程"
  steps:
    - color: "#3498db"
      icon: "▶"
      text: "步骤 1"
    - color: "#27ae60"
      icon: "✅"
      text: "步骤 2"
```

### 7. experiment_config - 实验配置

```yaml
experiment_config:
  title: "🔬 实验环境"
  items:
    参数 1: "值 1"
    参数 2: "值 2"
```

### 8. custom_html - 自定义 HTML

```yaml
custom_html:
  html: |
    <div class="card">
      <h2>自定义内容</h2>
    </div>
```

---

## 示例场景

### 场景 1: 快速验证实验

```yaml
modules:
  enabled:
    - text_section
    - code_comparison
    - data_table
```

### 场景 2: 完整性能分析

```yaml
modules:
  enabled:
    - text_section
    - code_comparison
    - experiment_config
    - data_table
    - chart_bar
    - chart_line
    - flowchart
```

### 场景 3: 机制研究

```yaml
modules:
  enabled:
    - text_section
    - flowchart
    - chart_line
```

---

## 依赖

- Python 3.7+
- PyYAML
- Chart.js (通过 CDN 自动加载)

---

## 输出

生成一个独立的 HTML 文件，包含：
- 响应式设计（适配桌面和移动设备）
- 交互式图表（Chart.js）
- 代码高亮显示
- 模块化布局

---

## 故障排查

### 问题 1: YAML 解析错误

**症状**: `yaml.scanner.ScannerError`

**解决**: 检查 YAML 缩进，确保使用空格而非 Tab

### 问题 2: 图表不显示

**症状**: HTML 中图表区域空白

**解决**: 检查是否正确加载 Chart.js CDN（需要网络连接）

### 问题 3: 中文乱码

**症状**: 中文显示为乱码

**解决**: 确保配置文件使用 UTF-8 编码保存

---

## 扩展开发

添加新模块类型：

1. 在 `ModularHTMLReportGenerator` 类中添加新的 `_generate_*` 方法
2. 在 `module_generators` 字典中注册新方法
3. 在配置文件中添加对应配置

---

## 相关文件

- `docs/Experiment_GEN_ACK_Timer_Fix.md` - 详细实验报告
- `results/exp_comparison/final_modular_report.html` - 示例报告
- `.agent/skills/generate-html-report/config-example.yaml` - 配置模板

---

**版本**: 1.0  
**创建日期**: 2026-03-11  
**维护者**: Atlas  
**依赖**: Python 3.7+, PyYAML, Chart.js
