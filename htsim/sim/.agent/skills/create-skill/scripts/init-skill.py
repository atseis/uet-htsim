#!/usr/bin/env python3
"""
init-skill.py
=============
快速创建 Skill 骨架。

用法:
    python3 init-skill.py --name <skill-name> --description "<描述>"
"""

import argparse
import os
from pathlib import Path
from datetime import datetime


SKILL_TEMPLATE = """---
name: {name}
description: |
  {description}
---

# {title} - Skill 文档

## 概述

<详细说明 skill 的用途、适用场景>

---

## 文件结构

```
.agent/skills/{name}/
├── SKILL.md
├── scripts/
│   └── <script-name>.py
└── config-example.yaml
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

---

## 配置说明

<如果有配置文件，详细说明格式>

---

## 示例场景

### 场景 1: <场景名称>

```yaml
<配置示例>
```

---

## 依赖

- Python 3.7+
- <其他依赖>

---

## 故障排查

### 问题 1: <问题描述>

**症状**: <错误信息>

**解决**: <解决方法>

---

## 相关文件

- <相关文件路径>

---

**版本**: 1.0  
**创建日期**: {date}  
**维护者**: <名称>  
**依赖**: <依赖列表>
"""

CONFIG_EXAMPLE_TEMPLATE = """# ============================================================================
# {title} 配置示例
# ============================================================================

# 基本配置
config:
  # 配置项 1
  key1: value1
  
  # 配置项 2
  key2: value2

# 数据源
data_sources:
  input: "input/file.txt"
  output: "output/file.txt"
"""

SCRIPT_TEMPLATE = """#!/usr/bin/env python3
\"\"\"
<script-name>.py
============
<功能描述>

用法:
    python3 <script-name>.py [选项]
\"\"\"

import argparse
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description="<描述>")
    parser.add_argument("--input", required=True, help="输入文件")
    parser.add_argument("--output", required=True, help="输出文件")
    args = parser.parse_args()
    
    # 实现代码
    print(f"处理 {args.input} -> {args.output}")


if __name__ == "__main__":
    main()
"""


def create_skill(name: str, description: str):
    """创建 Skill 目录结构"""
    
    # 创建目录
    skill_dir = Path(f".agent/skills/{name}")
    scripts_dir = skill_dir / "scripts"
    
    skill_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir.mkdir(parents=True, exist_ok=True)
    
    # 生成标题（将连字符转换为空格，首字母大写）
    title = " ".join(word.capitalize() for word in name.split("-"))
    
    # 创建 SKILL.md
    skill_content = SKILL_TEMPLATE.format(
        name=name,
        description=description,
        title=title,
        date=datetime.now().strftime("%Y-%m-%d")
    )
    
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(skill_content, encoding="utf-8")
    print(f"✅ 创建 {skill_file}")
    
    # 创建 config-example.yaml
    config_content = CONFIG_EXAMPLE_TEMPLATE.format(title=title)
    config_file = skill_dir / "config-example.yaml"
    config_file.write_text(config_content, encoding="utf-8")
    print(f"✅ 创建 {config_file}")
    
    # 创建脚本骨架
    script_name = name.replace("-", "_")
    script_content = SCRIPT_TEMPLATE.replace("<script-name>", script_name)
    script_file = scripts_dir / f"{script_name}.py"
    script_file.write_text(script_content, encoding="utf-8")
    script_file.chmod(0o755)
    print(f"✅ 创建 {script_file}")
    
    # 打印使用说明
    print(f"\n✅ Skill '{name}' 创建成功！")
    print(f"\n下一步:")
    print(f"  1. 编辑 {skill_file} 填写详细内容")
    print(f"  2. 编辑 {script_file} 实现功能")
    print(f"  3. 编辑 {config_file} 添加配置示例")
    print(f"  4. 测试功能：python3 {script_file} --input <input> --output <output>")
    print(f"  5. 提交：git add {skill_dir} && git commit -m 'feat(skill): add {name}'")


def main():
    parser = argparse.ArgumentParser(description="快速创建 Skill 骨架")
    parser.add_argument("--name", required=True, help="Skill 名称（如：generate-html-report）")
    parser.add_argument("--description", required=True, help="Skill 描述（2-3 句话）")
    args = parser.parse_args()
    
    # 验证名称格式
    if not all(c.islower() or c == "-" for c in args.name):
        print("❌ 错误：Skill 名称必须使用小写字母和连字符")
        print("   示例：generate-html-report, atomic-records")
        sys.exit(1)
    
    # 检查是否已存在
    skill_dir = Path(f".agent/skills/{args.name}")
    if skill_dir.exists():
        print(f"❌ 错误：Skill '{args.name}' 已存在")
        sys.exit(1)
    
    create_skill(args.name, args.description)


if __name__ == "__main__":
    main()
