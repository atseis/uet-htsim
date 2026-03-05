#!/usr/bin/env python3
"""
extract_ipynb_records.py
========================
从 Jupyter Notebook 中提取实验卡片所需信息。
供 AI agent 直接调用，也可单独运行进行诊断。

用法（诊断模式）：
    python3 extract_ipynb_records.py --ipynb <path> --atomic-dir AtomicRecords [--dry-run]
"""

import argparse
import base64
import json
import os
import re
import sys
from pathlib import Path
from typing import Optional


# ─────────────────────────────────────────────────────────────────────────────
# 1. ipynb 解析
# ─────────────────────────────────────────────────────────────────────────────

def parse_ipynb(ipynb_path: str) -> list[dict]:
    """
    解析 ipynb，返回结构化 cell 列表，每个元素：
    {
        "index": int,
        "type": "code" | "markdown",
        "source": str,           # 合并后的 cell 源码
        "images": [ bytes ],     # 从 outputs 中提取的 PNG（base64 解码后）
        "has_widget_save_btn": bool,  # 是否有 Save as PDF 按钮
    }
    """
    with open(ipynb_path, "r", encoding="utf-8") as f:
        nb = json.load(f)

    result = []
    for i, cell in enumerate(nb["cells"]):
        source = "".join(cell.get("source", []))
        images = []
        has_widget = False

        for out in cell.get("outputs", []):
            data = out.get("data", {})
            if "image/png" in data:
                raw = data["image/png"]
                # raw 可能是 list[str] 或 str
                if isinstance(raw, list):
                    raw = "".join(raw)
                images.append(base64.b64decode(raw))
            if "application/vnd.jupyter.widget-view+json" in data:
                has_widget = True

        result.append({
            "index": i,
            "type": cell["cell_type"],
            "source": source,
            "images": images,
            "has_widget_save_btn": has_widget,
        })
    return result


# ─────────────────────────────────────────────────────────────────────────────
# 2. 追溯 YAML 配置来源
# ─────────────────────────────────────────────────────────────────────────────

ADD_SOURCE_RE = re.compile(
    r'\.add_source\s*\(\s*[\'"]([^\'"]+\.yaml)[\'"]', re.DOTALL
)
BATCH_VAR_RE = re.compile(r'^(\w+)\s*=\s*BatchResult\(', re.MULTILINE)
CALL_RE = re.compile(r'^(\w+)\.', re.MULTILINE)


def extract_yaml_sources(cells: list[dict], image_cell_idx: int, ipynb_dir: str) -> list[str]:
    """
    从含图片的 code cell 向上追溯，找到对应的 .yaml 文件路径列表（绝对路径）。

    策略：
    1. 找到该 cell 中调用的 BatchResult 变量名（如 `b3.viz.plot_...`）
    2. 在该 cell 之前的 code cells 中，找到 `<var> = BatchResult()` 和 `.add_source(yaml_path)` 的声明
    3. 返回该变量对应的所有 yaml 路径
    """
    img_cell = cells[image_cell_idx]
    source = img_cell["source"]

    # 找到该 cell 用的变量名（如 b3、batch、bA 等）
    batch_var = None
    first_call = CALL_RE.search(source)
    if first_call:
        batch_var = first_call.group(1)

    if not batch_var:
        # fallback: 尝试用 'batch'
        batch_var = "batch"

    # 向上追溯
    yaml_paths = []
    for j in range(image_cell_idx - 1, -1, -1):
        cell = cells[j]
        if cell["type"] != "code":
            continue
        cell_src = cell["source"]

        # 检查此 cell 是否包含该变量的 BatchResult 初始化
        if re.search(rf'\b{re.escape(batch_var)}\s*=\s*BatchResult\b', cell_src):
            # 找到所有 add_source 调用
            for m in ADD_SOURCE_RE.finditer(cell_src):
                yaml_rel = m.group(1)
                yaml_abs = os.path.normpath(os.path.join(ipynb_dir, yaml_rel))
                yaml_paths.append(yaml_abs)
            break  # 找到初始化 cell 即停

    return yaml_paths


# ─────────────────────────────────────────────────────────────────────────────
# 3. 图片提取工具
# ─────────────────────────────────────────────────────────────────────────────

def extract_images(cell: dict) -> list[bytes]:
    """返回 cell 中所有 PNG 图片的原始字节。"""
    return cell["images"]


def save_image(img_bytes: bytes, output_path: str) -> None:
    """将 PNG 字节写入文件。"""
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    with open(output_path, "wb") as f:
        f.write(img_bytes)


# ─────────────────────────────────────────────────────────────────────────────
# 4. 已有卡片扫描与去重
# ─────────────────────────────────────────────────────────────────────────────

YAML_BLOCK_RE = re.compile(
    r'```yaml\s*\n(.*?)```', re.DOTALL | re.IGNORECASE
)


def _normalize_yaml(yaml_str: str) -> str:
    """去掉注释行和空行，trim 每行，用于比对。"""
    lines = []
    for line in yaml_str.splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith("#"):
            lines.append(stripped)
    return "\n".join(lines)


def find_existing_configs(atomic_dir: str) -> list[dict]:
    """
    扫描 AtomicRecords/New/ 和 AtomicRecords/Processed/ 下所有 config 卡片。
    返回：[ { "path": str, "filename": str, "stem": str, "yaml_normalized": str } ]
    """
    results = []
    for subdir in ["New", "Processed"]:
        d = Path(atomic_dir) / subdir
        if not d.exists():
            continue
        for md_file in d.rglob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            # 检查 frontmatter 中是否有 tags: config
            if "- config" not in content:
                continue
            # 提取 yaml 代码块
            for m in YAML_BLOCK_RE.finditer(content):
                yaml_block = m.group(1)
                results.append({
                    "path": str(md_file),
                    "filename": md_file.name,
                    "stem": md_file.stem,
                    "yaml_normalized": _normalize_yaml(yaml_block),
                })
                break  # 每个 config 文件只取第一个 yaml 块
    return results


def config_matches(yaml_content: str, existing_yaml_normalized: str) -> bool:
    """判断两个 YAML 内容是否完全一致（去注释、去空行后比较）。"""
    return _normalize_yaml(yaml_content) == existing_yaml_normalized


def find_existing_codes(atomic_dir: str) -> list[dict]:
    """
    扫描 New/ + Processed/ 下所有 code 卡片。
    返回：[ { "path": str, "stem": str, "git_hash": str } ]
    """
    results = []
    for subdir in ["New", "Processed"]:
        d = Path(atomic_dir) / subdir
        if not d.exists():
            continue
        for md_file in d.rglob("*.md"):
            content = md_file.read_text(encoding="utf-8")
            if "- code" not in content:
                continue
            # 从 frontmatter 中提取 git_hash
            m = re.search(r'^git_hash:\s*(\S+)', content, re.MULTILINE)
            git_hash = m.group(1) if m else None
            results.append({
                "path": str(md_file),
                "stem": md_file.stem,
                "git_hash": git_hash,
            })
    return results



def find_existing_results(atomic_dir: str) -> list[dict]:
    """
    扫描 New/ + Processed/ 下所有 result 卡片。
    返回：[ { "path": str, "stem": str, "source_ipynb": str, "cell_index": int } ]
    此处我们可以通过在提取时将 cell index 等元数据写入 Result 卡片，
    或通过解析图片文件名/描述来进行去重。
    为保证完全去重，推荐在生成 Result 卡片时在 frontmatter 加入 `source_cell: <index>`
    """
    results = []
    for subdir in ["New", "Processed"]:
        d = Path(atomic_dir) / subdir
        if not d.exists():
            continue
        for md_file in d.rglob("*.md"):
            try:
                text = md_file.read_text(encoding="utf-8")
                if "- result" not in text:
                    continue
                # 尝试提取 source_cell
                m = re.search(r'^source_cell:\s*(\d+)', text, re.MULTILINE)
                cell_idx = int(m.group(1)) if m else None
                
                # 尝试提取 notebook name
                m2 = re.search(r"^source_ipynb:\s*\"?([^\"]+)\"?", text, re.MULTILINE)

                ipynb_name = m2.group(1) if m2 else None
                
                results.append({
                    "path": str(md_file),
                    "stem": md_file.stem,
                    "cell_index": cell_idx,
                    "source_ipynb": ipynb_name
                })
            except Exception:
                pass
    return results


# ─────────────────────────────────────────────────────────────────────────────
# 5. 序号生成
# ─────────────────────────────────────────────────────────────────────────────

def next_card_index(atomic_dir: str, prefix: str) -> int:
    """
    扫描 New/ + Processed/ 下所有以 prefix 开头的 .md 文件，
    提取序号，返回 max + 1（最小为 1）。

    prefix: "Conf", "Res", "Claim" 等
    匹配模式: Conf-NNN-*, Res-NNN-*, Claim-NNN-* 中的 NNN 部分
    """
    max_idx = 0
    pattern = re.compile(rf'^{re.escape(prefix)}-(\d+)-')
    for subdir in ["New", "Processed"]:
        d = Path(atomic_dir) / subdir
        if not d.exists():
            continue
        for md_file in d.rglob("*.md"):
            m = pattern.match(md_file.name)
            if m:
                max_idx = max(max_idx, int(m.group(1)))
    return max_idx + 1


# ─────────────────────────────────────────────────────────────────────────────
# 6. 卡片内容生成辅助
# ─────────────────────────────────────────────────────────────────────────────

def make_frontmatter(tags: list[str], ctime: str, extra: dict = None) -> str:
    """生成 YAML frontmatter 字符串。"""
    lines = ["---", f"ctime: {ctime}", f"mtime: {ctime}", "tags:"]
    for tag in tags:
        lines.append(f"  - {tag}")
    if extra:
        for k, v in extra.items():
            lines.append(f"{k}: {v}")
    lines.append("---")
    return "\n".join(lines)


def generate_result_description(cell_source: str, preceding_markdown: str) -> str:
    """
    根据 cell 代码和前面的 markdown 标题，生成 result 卡片的描述文本。
    这是一个辅助函数，AI agent 在调用时会结合自身理解补充描述。
    """
    hints = []
    if preceding_markdown:
        hints.append(f"**实验场景**: {preceding_markdown.strip()}")

    # 提取关键参数
    params = {}
    for param in ["x", "y", "hue", "metrics", "col", "row", "title"]:
        m = re.search(rf"{param}\s*=\s*['\"]?([^'\")\s,]+)", cell_source)
        if m:
            params[param] = m.group(1)
    # metrics 特殊处理（可能是 list）
    m_metrics = re.search(r"metrics\s*=\s*\[([^\]]+)\]", cell_source)
    if m_metrics:
        params["metrics"] = m_metrics.group(1).replace("'", "").replace('"', '')

    if params:
        param_str = ", ".join(f"`{k}={v}`" for k, v in params.items())
        hints.append(f"**图表参数**: {param_str}")

    # 识别图表类型
    if "plot_statistical_summary" in cell_source:
        hints.append("**图表类型**: Statistical Summary（含 P50/P99/Max FCT 对比）")
    elif "plot_cdf" in cell_source:
        hints.append("**图表类型**: CDF 分布图")
    elif "plot_pivot" in cell_source:
        hints.append("**图表类型**: Pivot 参数对比图")
    elif "plot_facet" in cell_source:
        hints.append("**图表类型**: Facet 分面图")

    return "\n".join(hints) if hints else "（请手动补充图表描述）"


# ─────────────────────────────────────────────────────────────────────────────
# 7. 主分析入口（诊断模式）
# ─────────────────────────────────────────────────────────────────────────────

def analyze_ipynb(ipynb_path: str, atomic_dir: str) -> dict:
    """
    分析 ipynb，返回提取计划：
    {
        "image_cells": [
            {
                "cell_index": int,
                "preceding_markdown": str,   # 最近的 markdown cell
                "yaml_files": [str],          # 绝对路径
                "image_count": int,
                "description_hint": str,
            }
        ]
    }
    """
    ipynb_dir = os.path.dirname(os.path.abspath(ipynb_path))
    cells = parse_ipynb(ipynb_path)

    image_cells = []
    last_markdown = ""

    for i, cell in enumerate(cells):
        if cell["type"] == "markdown":
            last_markdown = cell["source"]
            continue
        if cell["type"] == "code" and cell["images"]:
            yaml_files = extract_yaml_sources(cells, i, ipynb_dir)
            desc = generate_result_description(cell["source"], last_markdown)
            image_cells.append({
                "cell_index": i,
                "preceding_markdown": last_markdown,
                "yaml_files": yaml_files,
                "image_count": len(cell["images"]),
                "description_hint": desc,
                "source": cell["source"],
            })

    return {
        "ipynb_path": ipynb_path,
        "total_cells": len(cells),
        "image_cells": image_cells,
    }


# ─────────────────────────────────────────────────────────────────────────────
# 8. CLI
# ─────────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="从 ipynb 提取实验卡片信息")
    parser.add_argument("--ipynb", required=True, help="ipynb 文件路径")
    parser.add_argument(
        "--atomic-dir", default="AtomicRecords",
        help="AtomicRecords 目录路径（默认: AtomicRecords）"
    )
    parser.add_argument("--dry-run", action="store_true", help="仅显示分析结果，不写入文件")
    args = parser.parse_args()

    print(f"📓 分析 ipynb: {args.ipynb}")
    print(f"📁 AtomicRecords 目录: {args.atomic_dir}\n")

    plan = analyze_ipynb(args.ipynb, args.atomic_dir)
    image_cells = plan["image_cells"]

    print(f"✅ 共找到 {len(image_cells)} 个含图片的 code cell：\n")

    for ic in image_cells:
        print(f"  Cell #{ic['cell_index']}")
        md_preview = ic['preceding_markdown'][:80].replace('\n', ' ')
        print(f"    前置 Markdown: {md_preview}")
        print(f"    关联 YAML 文件:")
        for yf in ic['yaml_files']:
            exists = "✅" if os.path.exists(yf) else "❌(不存在)"
            print(f"      {yf} {exists}")
        print(f"    图片数量: {ic['image_count']}")
        print(f"    描述提示:\n      {ic['description_hint'].replace(chr(10), chr(10)+'      ')}")
        print()

    if args.dry_run:
        print("🔍 Dry-run 模式：仅显示分析结果，未写入任何文件。")
        return

    # 实际写入逻辑（供 AI agent 参考，一般由 agent 直接调用各函数）
    print("💡 提示：实际卡片生成由 AI agent 根据上述信息完成，请参考 SKILL.md 中的工作流程。")


if __name__ == "__main__":
    main()
