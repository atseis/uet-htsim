#!/usr/bin/env python3
"""
模块化 HTML 报告生成器 v1.0

根据 YAML 配置文件动态生成交互式 HTML 报告。
支持动态增减内容模块，适用于各种实验场景。

使用方法:
    python3 generate_modular_html_report.py \
        --config html-report-config.yaml \
        --output report.html
"""

import argparse
import yaml
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime


class ModularHTMLReportGenerator:
    """
    模块化 HTML 报告生成器

    支持以下模块类型:
    1. text_section - 文本章节（标题 + 内容）
    2. code_comparison - 代码对比
    3. data_table - 数据表格
    4. chart_bar - 柱状图（Chart.js）
    5. chart_line - 折线图（Chart.js）
    6. flowchart - 流程图
    7. experiment_config - 实验配置
    8. custom_html - 自定义 HTML
    """

    def __init__(self, config_path: str):
        with open(config_path, "r", encoding="utf-8") as f:
            self.config = yaml.safe_load(f)

        self.modules = self.config.get("modules", {})
        self.enabled_modules = self.modules.get("enabled", [])
        self.module_order = self.modules.get("order", self.enabled_modules)
        self.module_configs = self.modules.get("config", {})
        self.data_sources = self.config.get("data_sources", {})

    def generate(self, output_path: str):
        """生成完整的 HTML 报告"""
        html_parts = []

        # 1. HTML 头部
        html_parts.append(self._generate_header())

        # 2. 报告标题
        html_parts.append(self._generate_title_section())

        # 3. 按顺序生成各个模块
        for module_name in self.module_order:
            if module_name in self.enabled_modules:
                module_html = self._generate_module(module_name)
                if module_html:
                    html_parts.append(module_html)

        # 4. HTML 尾部
        html_parts.append(self._generate_footer())

        # 写入文件
        full_html = "\n".join(html_parts)
        with open(output_path, "w", encoding="utf-8") as f:
            f.write(full_html)

        print(f"✅ HTML 报告已生成：{output_path}")

    def _generate_header(self) -> str:
        """生成 HTML 头部（包含 Chart.js CDN）"""
        return (
            """<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>"""
            + self.config.get("report", {}).get("title", "实验报告")
            + """</title>
    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>
    <style>
        body { 
            font-family: Arial, sans-serif; 
            max-width: 1200px; 
            margin: 0 auto; 
            padding: 20px; 
            background: #f5f5f5;
        }
        h1 { color: #2c3e50; text-align: center; }
        h2 { 
            color: #34495e; 
            border-bottom: 2px solid #3498db; 
            padding-bottom: 10px;
            margin-top: 30px;
        }
        .card { 
            background: white;
            border-radius: 8px; 
            padding: 20px; 
            margin: 20px 0; 
            box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        }
        .comparison { 
            display: grid; 
            grid-template-columns: 1fr 1fr; 
            gap: 20px; 
        }
        .buggy { 
            background: #ffe6e6; 
            padding: 15px; 
            border-left: 4px solid #e74c3c; 
        }
        .fixed { 
            background: #e6ffe6; 
            padding: 15px; 
            border-left: 4px solid #27ae60; 
        }
        table { 
            width: 100%; 
            border-collapse: collapse; 
            margin: 15px 0; 
        }
        th, td { 
            padding: 10px; 
            text-align: left; 
            border-bottom: 1px solid #ddd; 
        }
        th { 
            background: #3498db; 
            color: white; 
        }
        .code { 
            font-family: monospace; 
            background: #2c3e50; 
            color: #ecf0f1; 
            padding: 15px; 
            border-radius: 5px;
            overflow-x: auto;
        }
        .highlight { 
            background: #f39c12; 
            color: #2c3e50; 
            padding: 2px 6px; 
            border-radius: 3px;
        }
        .chart-container { 
            position: relative; 
            height: 400px; 
            margin: 20px 0; 
        }
        .metric { 
            font-size: 24px; 
            font-weight: bold; 
            color: #2c3e50; 
        }
        .improvement { 
            color: #27ae60; 
            font-weight: bold; 
        }
    </style>
</head>
<body>"""
        )

    def _generate_title_section(self) -> str:
        """生成报告标题部分"""
        report_config = self.config.get("report", {})
        title = report_config.get("title", "实验报告")
        date = report_config.get("date", datetime.now().strftime("%Y-%m-%d"))

        return f"""
    <h1>🔧 {title}</h1>
    <div class="card">
        <p><strong>报告生成日期:</strong> {date}</p>
        <p><strong>配置来源:</strong> {self.config.get("config_file", "N/A")}</p>
    </div>
"""

    def _generate_module(self, module_name: str) -> Optional[str]:
        """根据模块名称生成对应的 HTML"""
        module_config = self.module_configs.get(module_name, {})

        # 模块类型映射
        module_generators = {
            "text_section": self._generate_text_section,
            "code_comparison": self._generate_code_comparison,
            "data_table": self._generate_data_table,
            "chart_bar": self._generate_chart_bar,
            "chart_line": self._generate_chart_line,
            "flowchart": self._generate_flowchart,
            "experiment_config": self._generate_experiment_config,
            "custom_html": self._generate_custom_html,
        }

        generator = module_generators.get(module_name)
        if generator:
            return generator(module_config)
        else:
            print(f"⚠️ 警告：未知的模块类型 '{module_name}'，跳过")
            return None

    def _generate_text_section(self, config: Dict) -> str:
        """生成文本章节"""
        title = config.get("title", "")
        content = config.get("content", "")

        return f"""
    <div class="card">
        <h2>{title}</h2>
        <p>{content}</p>
    </div>
"""

    def _generate_code_comparison(self, config: Dict) -> str:
        """生成代码对比模块"""
        title = config.get("title", "代码对比")
        buggy_title = config.get("buggy_title", "修复前 (BUG)")
        fixed_title = config.get("fixed_title", "修复后 (FIX)")
        buggy_code = config.get("buggy_code", "")
        fixed_code = config.get("fixed_code", "")
        buggy_issue = config.get("buggy_issue", "")
        fixed_improvement = config.get("fixed_improvement", "")

        return f"""
    <div class="card">
        <h2>💻 {title}</h2>
        <div class="comparison">
            <div class="buggy">
                <h3>❌ {buggy_title}</h3>
                <div class="code">{buggy_code}</div>
                <p><strong>问题:</strong> {buggy_issue}</p>
            </div>
            <div class="fixed">
                <h3>✅ {fixed_title}</h3>
                <div class="code">{fixed_code}</div>
                <p><strong>改进:</strong> {fixed_improvement}</p>
            </div>
        </div>
    </div>
"""

    def _generate_data_table(self, config: Dict) -> str:
        """生成数据表格"""
        title = config.get("title", "数据对比")
        headers = config.get("headers", [])
        rows = config.get("rows", [])

        if not headers or not rows:
            return ""

        # 生成表头
        html = f"""
    <div class="card">
        <h2>📊 {title}</h2>
        <table>
            <tr>"""

        for header in headers:
            html += f"<th>{header}</th>"

        html += "</tr>"

        # 生成数据行
        for row in rows:
            html += "<tr>"
            for cell in row:
                html += f"<td>{cell}</td>"
            html += "</tr>"

        html += """</table>
    </div>
"""
        return html

    def _generate_chart_bar(self, config: Dict) -> str:
        """生成柱状图（使用 Chart.js）"""
        chart_id = config.get("chart_id", "barChart")
        title = config.get("title", "柱状图")
        labels = config.get("labels", [])
        datasets = config.get("datasets", [])
        x_label = config.get("x_label", "")
        y_label = config.get("y_label", "")

        if not labels or not datasets:
            return ""

        # 生成 Chart.js 配置
        chart_config = {
            "type": "bar",
            "data": {"labels": labels, "datasets": datasets},
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "scales": {
                    "y": {
                        "beginAtZero": True,
                        "title": {"display": True, "text": y_label},
                    }
                },
                "plugins": {"title": {"display": True, "text": title}},
            },
        }

        import json

        chart_config_json = json.dumps(chart_config, ensure_ascii=False)

        return f'''
    <div class="card">
        <h2>📈 {title}</h2>
        <div class="chart-container">
            <canvas id="{chart_id}"></canvas>
        </div>
    </div>
    <script>
        new Chart(document.getElementById('{chart_id}'), {chart_config_json});
    </script>
'''

    def _generate_chart_line(self, config: Dict) -> str:
        """生成折线图（使用 Chart.js）"""
        chart_id = config.get("chart_id", "lineChart")
        title = config.get("title", "折线图")
        labels = config.get("labels", [])
        datasets = config.get("datasets", [])
        x_label = config.get("x_label", "")
        y_label = config.get("y_label", "")

        if not labels or not datasets:
            return ""

        import json

        chart_config = {
            "type": "line",
            "data": {"labels": labels, "datasets": datasets},
            "options": {
                "responsive": True,
                "maintainAspectRatio": False,
                "scales": {
                    "y": {
                        "beginAtZero": True,
                        "title": {"display": True, "text": y_label},
                    },
                    "x": {"title": {"display": True, "text": x_label}},
                },
                "plugins": {"title": {"display": True, "text": title}},
            },
        }

        chart_config_json = json.dumps(chart_config, ensure_ascii=False)

        return f'''
    <div class="card">
        <h2>📈 {title}</h2>
        <div class="chart-container">
            <canvas id="{chart_id}"></canvas>
        </div>
    </div>
    <script>
        new Chart(document.getElementById('{chart_id}'), {chart_config_json});
    </script>
'''

    def _generate_flowchart(self, config: Dict) -> str:
        """生成流程图（使用 Mermaid.js 或自定义 HTML）"""
        title = config.get("title", "流程图")
        steps = config.get("steps", [])

        if not steps:
            return ""

        # 生成简单的步骤流程图
        html = f"""
    <div class="card">
        <h2>⚙️ {title}</h2>
        <div style="display: flex; flex-direction: column; gap: 10px; align-items: center;">
"""

        for i, step in enumerate(steps):
            color = step.get("color", "#3498db")
            icon = step.get("icon", "▶")
            text = step.get("text", f"Step {i + 1}")

            html += f"""
            <div style="background: {color}; color: white; padding: 15px; 
                        border-radius: 5px; min-width: 300px; text-align: center;">
                <strong>{icon}</strong> {text}
            </div>
"""
            if i < len(steps) - 1:
                html += '<div style="font-size: 20px;">⬇️</div>'

        html += """
        </div>
    </div>
"""
        return html

    def _generate_experiment_config(self, config: Dict) -> str:
        """生成实验配置模块"""
        title = config.get("title", "实验配置")
        items = config.get("items", {})

        html = f"""
    <div class="card">
        <h2>🔬 {title}</h2>
        <table>
"""

        for key, value in items.items():
            html += f"<tr><th>{key}</th><td>{value}</td></tr>"

        html += """</table>
    </div>
"""
        return html

    def _generate_custom_html(self, config: Dict) -> str:
        """生成自定义 HTML 模块"""
        return config.get("html", "")

    def _generate_footer(self) -> str:
        """生成 HTML 尾部"""
        return """
</body>
</html>"""


def main():
    parser = argparse.ArgumentParser(description="模块化 HTML 报告生成器")
    parser.add_argument("--config", required=True, help="YAML 配置文件路径")
    parser.add_argument("--output", required=True, help="输出 HTML 文件路径")

    args = parser.parse_args()

    config_path = Path(args.config)
    if not config_path.exists():
        print(f"❌ 错误：配置文件不存在：{config_path}")
        return

    generator = ModularHTMLReportGenerator(str(config_path))
    generator.generate(args.output)


if __name__ == "__main__":
    main()
