#!/usr/bin/env python3
"""
validate-skill.py
=================
验证 Skill 格式是否正确。

用法:
    python3 validate-skill.py <skill-directory>
"""

import argparse
import sys
from pathlib import Path
import yaml


def validate_skill(skill_dir: str) -> bool:
    """验证 Skill 格式"""
    
    skill_path = Path(skill_dir)
    
    if not skill_path.exists():
        print(f"❌ 错误：目录不存在：{skill_path}")
        return False
    
    if not skill_path.is_dir():
        print(f"❌ 错误：不是目录：{skill_path}")
        return False
    
    errors = []
    warnings = []
    
    # 检查 SKILL.md
    skill_file = skill_path / "SKILL.md"
    if not skill_file.exists():
        errors.append("缺少 SKILL.md 文件")
    else:
        # 验证 YAML frontmatter
        try:
            content = skill_file.read_text(encoding="utf-8")
            if content.startswith("---"):
                # 提取 YAML frontmatter
                end = content.find("---", 3)
                if end > 0:
                    yaml_content = content[4:end]
                    data = yaml.safe_load(yaml_content)
                    
                    # 检查必需字段
                    if "name" not in data:
                        errors.append("SKILL.md 缺少 name 字段")
                    elif data["name"] != skill_path.name:
                        errors.append(f"SKILL.md 的 name ({data['name']}) 与目录名 ({skill_path.name}) 不一致")
                    
                    if "description" not in data:
                        errors.append("SKILL.md 缺少 description 字段")
                else:
                    errors.append("SKILL.md YAML frontmatter 格式错误")
            else:
                errors.append("SKILL.md 缺少 YAML frontmatter（应以 --- 开头）")
        except Exception as e:
            errors.append(f"解析 SKILL.md 失败：{e}")
    
    # 检查 scripts 目录
    scripts_dir = skill_path / "scripts"
    if scripts_dir.exists():
        if not scripts_dir.is_dir():
            errors.append("scripts 不是目录")
        else:
            scripts = list(scripts_dir.glob("*.py"))
            if not scripts:
                warnings.append("scripts 目录为空")
            else:
                # 检查脚本格式
                for script in scripts:
                    content = script.read_text(encoding="utf-8")
                    if not content.startswith("#!/usr/bin/env python3"):
                        warnings.append(f"{script.name} 缺少 shebang")
    else:
        warnings.append("缺少 scripts 目录（可选）")
    
    # 检查 config-example.yaml
    config_file = skill_path / "config-example.yaml"
    if config_file.exists():
        try:
            yaml.safe_load(config_file.read_text(encoding="utf-8"))
        except Exception as e:
            errors.append(f"config-example.yaml 格式错误：{e}")
    
    # 打印结果
    print(f"\n验证 Skill: {skill_path.name}")
    print("=" * 50)
    
    if errors:
        print("\n❌ 错误:")
        for error in errors:
            print(f"  - {error}")
    
    if warnings:
        print("\n⚠️ 警告:")
        for warning in warnings:
            print(f"  - {warning}")
    
    if not errors and not warnings:
        print("\n✅ 验证通过！Skill 格式正确")
        return True
    elif not errors:
        print("\n✅ 验证通过（有警告）")
        return True
    else:
        print("\n❌ 验证失败")
        return False


def main():
    parser = argparse.ArgumentParser(description="验证 Skill 格式")
    parser.add_argument("skill_dir", help="Skill 目录路径")
    args = parser.parse_args()
    
    success = validate_skill(args.skill_dir)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
