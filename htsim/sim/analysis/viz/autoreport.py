import re
from matplotlib.colors import LogNorm
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns
import pandas as pd
import numpy as np
from pathlib import Path
from typing import Optional, List, Union, Dict

# 仅在需要时尝试导入 IPython
try:
    from IPython.display import display, Markdown

    IPYTHON_AVAILABLE = True
except ImportError:
    IPYTHON_AVAILABLE = False

from ..data.fileinfo import ExperimentResult
from ..parser.statusyaml import parse_enabled_logs


class AutoVisualizer:
    """
    自动可视化生成器 (v3.0 Thin View).

    设计原则:
    1. 信任数据层: 直接读取 result.*_goodput_df 中的 Rate_{unit} 列。
    2. 专注绘图: 仅负责 Time 单位转换 (s->us) 和坐标轴格式化。
    """

    def __init__(self, result: ExperimentResult):
        self.result = result
        self.enabled_logs = set(parse_enabled_logs(self.result.status_path))

        self.unit = getattr(self.result, "rate_unit", "Gbps")
        self.rate_col = f"Rate_{self.unit}"

        # 1. 注册所有基础绘图器 (保持原有 Key 不变)
        self.plotters = {
            "Flow Completion Time (CDF)": self._plot_flow_fct_cdf,
            "Flow Size vs FCT (Scatter)": self._plot_flow_scatter,
            "Flow Slowdown CDF": self._plot_flow_slowdown_cdf,
            "System Total Goodput": self._plot_total_goodput,
            "Goodput by Sender Host": self._plot_src_goodput,
            "Goodput by Receiver Host": self._plot_sink_goodput,
            "Top Active Flows Goodput": self._plot_flow_goodput,
            "NIC Traffic Breakdown": self._plot_nic_stack,
            "Last-Hop Queue Dynamics": self._plot_lasthop_queues,
            "Switch Shared Buffer Usage": self._plot_switch_buffer,
            "Traffic Event Spatial Distribution (Heatmap)": self._plot_traffic_spatial_dist,
            "Bottleneck Correlation Analysis": self._plot_bottleneck_correlation,
            "Incast Fan-in vs. Pressure": self._plot_incast_fanin_pressure,
            "Protocol Efficiency (Payload vs Control)": self._plot_protocol_efficiency,
            "Flow Path Spatio-Temporal Heatmap": self._plot_flow_path_heatmap_auto,
            "Full Stack Analysis (Trace)": self._plot_flow_trace_auto,
        }

        # 2. 定义漏斗式阅读逻辑 (REPORT_PLAN)
        self.REPORT_PLAN = [
            {
                "title": "Phase 1: 宏观指标 (The Result)",
                "question": "性能是否达标？是否有严重的长尾（Tail Latency）？",
                "items": [
                    "Flow Completion Time (CDF)",
                    "Flow Slowdown CDF",
                    "Flow Size vs FCT (Scatter)",
                ],
            },
            {
                "title": "Phase 2: 吞吐分布 (The Stability)",
                "question": "流量是否稳定？哪些流（High Volatility）在剧烈震荡？",
                "items": [
                    "System Total Goodput",
                    "Goodput by Sender Host",
                    "Goodput by Receiver Host",
                    "Top Active Flows Goodput",
                    "NIC Traffic Breakdown",
                ],
            },
            {
                "title": "Phase 3: 瓶颈定位 (The Hotspot)",
                "question": "拥塞发生在网络的哪个位置（ToR, Agg, 或 Core）？丢包（Drop）与裁剪（Trim）的比例如何？",
                "items": [
                    "Traffic Event Spatial Distribution (Heatmap)",
                    "Last-Hop Queue Dynamics",
                ],
            },
            {
                "title": "Phase 4: 因果关联 (The Causality)",
                "question": "观察 cwnd 的下降是否是对队列上升的即时响应？队列排空后 cwnd 是否恢复太慢？",
                "items": [
                    "Full Stack Analysis (Trace)",
                    "Incast Fan-in vs. Pressure",
                    "Bottleneck Correlation Analysis",
                    "Switch Shared Buffer Usage",
                    "Protocol Efficiency (Payload vs Control)",
                ],
            },
            {
                "title": "Phase 5: 微观轨迹 (The Anatomy)",
                "question": "对于那个最慢的流，它在每一跳的具体遭遇是什么？",
                "items": ["Flow Path Spatio-Temporal Heatmap"],
            },
        ]

    def _get_active_plotters(self):
        """根据日志开启情况，筛选出需要执行的绘图函数"""
        active = {}

        # 1. Flow Logs
        if "flow_events" in self.enabled_logs:
            active["Flow Completion Time (CDF)"] = self.plotters[
                "Flow Completion Time (CDF)"
            ]
            # active["Flow Size vs FCT (Scatter)"] = self.plotters[
            #     "Flow Size vs FCT (Scatter)"
            # ]
            # active["Flow Slowdown CDF"] = self.plotters["Flow Slowdown CDF"]

        # 2. Sink Logs (Goodput)
        if "sink" in self.enabled_logs:
            active["System Total Goodput"] = self.plotters["System Total Goodput"]
            active["Goodput by Sender Host"] = self.plotters["Goodput by Sender Host"]
            active["Goodput by Receiver Host"] = self.plotters[
                "Goodput by Receiver Host"
            ]
            active["Top Active Flows Goodput"] = self.plotters[
                "Top Active Flows Goodput"
            ]

        # 3. NIC Logs
        if "nic" in self.enabled_logs:
            active["NIC Traffic Breakdown"] = self.plotters["NIC Traffic Breakdown"]

        # 4. Queue Logs
        queue_flags = {"tor_downqueue", "tor_upqueue", "queue"}
        # if not self.enabled_logs.isdisjoint(queue_flags):
        #     active["Last-Hop Queue Dynamics"] = self.plotters["Last-Hop Queue Dynamics"]

        # 5. Switch Logs
        if "switch" in self.enabled_logs:
            active["Switch Shared Buffer Usage"] = self.plotters[
                "Switch Shared Buffer Usage"
            ]
        if "traffic" in self.enabled_logs:
            active["Traffic Event Spatial Distribution (Heatmap)"] = self.plotters[
                "Traffic Event Spatial Distribution (Heatmap)"
            ]
            active["Bottleneck Correlation Analysis"] = self.plotters[
                "Bottleneck Correlation Analysis"
            ]
        # 增强：如果同时有 traffic 和 queue 日志，激活扇入度压力图
        if "traffic" in self.enabled_logs and not self.enabled_logs.isdisjoint(
            {"queue", "tor_downqueue"}
        ):
            active["Incast Fan-in vs. Pressure"] = self.plotters[
                "Incast Fan-in vs. Pressure"
            ]

        # 增强：流量效能监控
        if "traffic" in self.enabled_logs:
            active["Protocol Efficiency (Payload vs Control)"] = self.plotters[
                "Protocol Efficiency (Payload vs Control)"
            ]

        if "traffic" in self.enabled_logs and "tor_downqueue" in self.enabled_logs:
            active["Flow Path Spatio-Temporal Heatmap"] = self.plotters[
                "Flow Path Spatio-Temporal Heatmap"
            ]
        # --- 新增: 基于 -debug 参数或数据存在性激活 ---
        # 逻辑：如果命令行包含 -debug，或者 cwnd_df 确实解析到了数据，则激活
        is_debug_enabled = self.result.params.get("debug") is not None
        has_cwnd_data = not self.result.cwnd_df.empty

        if (is_debug_enabled or has_cwnd_data) and "flow_events" in self.enabled_logs:
            # active["Congestion Control Diagnostic"] = self.plotters[
            #     "Congestion Control Diagnostic"
            # ]
            active["Full Stack Analysis (Trace)"] = self.plotters[
                "Full Stack Analysis (Trace)"
            ]
        return active

    # ==========================================
    # 公共交互方法 (Show & Save)
    # ==========================================

    def _attach_save_btn(self, fig, title: str = "figure"):
        """在 Jupyter 环境中，于图片下方显示「💾 Save as PDF」按钮。"""
        try:
            import datetime, re, matplotlib
            import ipywidgets as widgets
            from IPython.display import display as _display

            matplotlib.rcParams["pdf.fonttype"] = 42
            matplotlib.rcParams["ps.fonttype"] = 42

            save_dir = Path(__file__).resolve().parent.parent.parent / "figures"
            save_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r"[^\w\-]+", "_", str(title).strip()).strip("_").lower()[:60]

            def _on_save(b, _fig=fig, _dir=save_dir, _slug=slug):
                ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
                fname = _dir / f"{_slug}_{ts}.pdf"
                _fig.savefig(fname, bbox_inches="tight")
                b.description = "✅ Saved!"
                b.button_style = "success"
                b.disabled = True
                print(f"[save] → {fname}")

            btn = widgets.Button(
                description="💾 Save as PDF",
                button_style="info",
                icon="download",
                layout=widgets.Layout(width="180px", height="36px"),
            )
            btn.on_click(_on_save)
            _display(btn)
        except ImportError:
            pass  # 非 Jupyter 环境，静默跳过

    def show(self):
        """[Interactive Mode] 漏斗式逻辑引导报告"""
        if not IPYTHON_AVAILABLE:
            print("Error: IPython is not available.")
            return

        active_plotters = self._get_active_plotters()
        display(Markdown(f"# 🔍 实验全景观测报告: {self.result.base_dir.name}"))

        # 按计划顺序展示
        for stage in self.REPORT_PLAN:
            stage_active_items = [
                item for item in stage["items"] if item in active_plotters
            ]
            if not stage_active_items:
                continue

            display(Markdown(f"---"))
            display(Markdown(f"## {stage['title']}"))
            display(Markdown(f"> **思考重点**：{stage['question']}"))

            for title in stage_active_items:
                try:
                    fig = self.plotters[title]()
                    if fig:
                        display(Markdown(f"### {title}"))
                        display(fig)
                        self._attach_save_btn(fig, title)
                        plt.close(fig)
                except Exception as e:
                    display(Markdown(f"**Error plotting {title}:** {str(e)}"))

    def save(self, output_dir: Union[str, Path]):
        """[Batch Mode] 结构化保存图片并生成导读索引"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        active_plotters = self._get_active_plotters()
        readme_content = [f"# 导读报告: {self.result.base_dir.name}\n"]

        print(f"Generating structured report for {self.result.base_dir.name}...")

        stage_idx = 1
        for stage in self.REPORT_PLAN:
            stage_items = [item for item in stage["items"] if item in active_plotters]
            if not stage_items:
                continue

            readme_content.append(f"## {stage['title']}")
            readme_content.append(f"**核心问题**：{stage['question']}\n")

            for sub_idx, title in enumerate(stage_items, 1):
                try:
                    fig = self.plotters[title]()
                    if fig:
                        # 文件名示例：01-1_flow_completion_time_cdf.png
                        safe_title = (
                            title.lower()
                            .replace(" ", "_")
                            .replace("(", "")
                            .replace(")", "")
                        )
                        filename = f"{stage_idx:02d}-{sub_idx}_{safe_title}.png"

                        fig.savefig(output_dir / filename, dpi=120, bbox_inches="tight")
                        readme_content.append(f"- ![{title}]({filename})")
                        plt.close(fig)
                        print(f"  [Saved] {filename}")
                except Exception as e:
                    print(f"  [Error] {title}: {e}")

            readme_content.append("\n")
            stage_idx += 1

        # 保存 README 引导文件，方便离线查看
        (output_dir / "README.md").write_text("\n".join(readme_content))
        print(f"✅ Report indexed and saved to {output_dir}/")

    # ==========================================
    # 辅助格式化工具 (Helpers)
    # ==========================================

    @staticmethod
    def _fmt_plain(x, pos=None):
        """强制显示纯数字 (如 200 而非 2e2)，用于 FCT 和 Rate 轴"""
        return f"{x:g}"

    @staticmethod
    def _fmt_bytes(x, pos=None):
        """自动字节单位 (B/KB/MB/GB)"""
        if x == 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB", "TB"]
        i = 0
        val = x
        while val >= 1000 and i < len(units) - 1:
            val /= 1000.0
            i += 1
        return f"{val:.1f} {units[i]}"

    @staticmethod
    def _to_us(df: pd.DataFrame, time_col="time") -> pd.DataFrame:
        """View层仅负责展示单位转换: Seconds -> Microseconds (us)"""
        if df.empty or time_col not in df.columns:
            return df
        new_df = df.copy()
        new_df[time_col] = new_df[time_col] * 1e6
        return new_df

    # ==========================================
    # 1. Flow Plotters
    # ==========================================

    def _plot_flow_fct_cdf(self):
        """
        [Optimization] 增强型 FCT CDF.
        去除了理想 FCT 对比，增加了 Median, P99, Max 的显式标注。
        """
        df = self.result.flow_df
        if df.empty or "fct_ns" not in df.columns:
            return None

        # FCT 单位转换: ns -> us
        data = df["fct_ns"] / 1000.0

        fig, ax = plt.subplots(figsize=(8, 4))
        # 绘制主曲线，使用经典的对数 X 轴
        sns.ecdfplot(data=data, ax=ax, linewidth=2, color="#1f77b4")
        ax.set_xscale("log")

        # 1. 计算核心统计指标
        metrics = {
            "Median": data.median(),
            "P99": np.percentile(data, 99),
            "Max": data.max(),
        }

        # 2. 自动化标注逻辑 (避免标签重叠)
        colors = {"Median": "black", "P99": "red", "Max": "brown"}
        styles = {"Median": "--", "P99": ":", "Max": "-."}
        y_offsets = {"Median": 0.2, "P99": 0.5, "Max": 0.8}

        for label, val in metrics.items():
            ax.axvline(
                val, color=colors[label], linestyle=styles[label], alpha=0.7, lw=1.2
            )
            # 文本标注：旋转 90 度，背景白色填充以保证在网格线上清晰
            ax.text(
                val,
                y_offsets[label],
                f" {label}: {val:.1f} us",
                color=colors[label],
                rotation=90,
                va="center",
                backgroundcolor="white",
                fontsize=9,
                fontweight="bold",
                zorder=10,
            )

        # 3. 格式化
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.set_xlabel("Flow Completion Time (us)")
        ax.set_ylabel("CDF")
        ax.set_title(f"FCT Tail Latency Analysis (n={len(df)})")
        ax.grid(True, which="both", ls="--", alpha=0.3)

        return fig

    def _plot_flow_slowdown_cdf(self):
        """
        [New] 绘制 FCT Slowdown CDF。
        展示流受拥塞影响的真实“膨胀率”。
        """
        df = self.result.flow_slowdown_df
        if df.empty or "slowdown" not in df.columns:
            return None

        data = df["slowdown"]

        fig, ax = plt.subplots(figsize=(8, 4))
        sns.ecdfplot(data=data, ax=ax, linewidth=2, color="#2ca02c")

        # Slowdown 通常呈现长尾，建议使用对数 X 轴
        ax.set_xscale("log")
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(self._fmt_plain))

        ax.set_xlabel("FCT Slowdown (Actual / Ideal)")
        ax.set_ylabel("CDF")
        ax.set_title(f"FCT Slowdown CDF (n={len(df)})")
        ax.grid(True, which="both", ls="--", alpha=0.3)

        # 标注中位数和 P99
        median = data.median()
        p99 = np.percentile(data, 99)
        ax.axvline(median, color="k", linestyle="--", alpha=0.5)
        ax.axvline(p99, color="r", linestyle=":", alpha=0.6)
        ax.text(
            median, 0.1, f" Median: {median:.2f}", color="k", backgroundcolor="white"
        )
        ax.text(
            p99,
            0.5,
            f" P99: {p99:.2f}",
            color="r",
            rotation=90,
            va="center",
            backgroundcolor="white",
        )

        return fig

    def _plot_flow_scatter(self):
        df = self.result.flow_df
        if df.empty:
            return None
        fig, ax = plt.subplots(figsize=(8, 4))

        sns.scatterplot(
            x=df["size_bytes"],
            y=df["fct_ns"] / 1000.0,
            alpha=0.5,
            ax=ax,
            edgecolor=None,
        )

        ax.set_yscale("log")
        ax.set_xscale("log")

        # X轴: 字节单位, Y轴: 纯数字时间
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_bytes))
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.yaxis.set_minor_formatter(ticker.FuncFormatter(self._fmt_plain))

        ax.set_xlabel("Flow Size")
        ax.set_ylabel("FCT (us)")
        ax.set_title("Flow Size vs FCT")
        ax.grid(True, which="major", ls="-", alpha=0.2)
        return fig

    # ==========================================
    # 2. Goodput Plotters (Generic Template)
    # ==========================================

    def _plot_generic_goodput(self, df_attr: str, hue: str = None, title: str = ""):
        """
        通用的 Goodput 绘图模板。
        假设 self.result.{df_attr} 已经包含了正确的 self.rate_col (如 Rate_Gbps)。
        """
        # 1. 从 result 获取 DataFrame
        df = getattr(self.result, df_attr, pd.DataFrame())

        # 2. 检查数据和列是否存在
        if df.empty or self.rate_col not in df.columns:
            return None

        # 3. 仅做时间单位转换 (s -> us)
        plot_df = self._to_us(df)

        fig, ax = plt.subplots(figsize=(10, 4))

        # 4. 绘图 (直接使用 self.rate_col)
        # 如果 hue 存在，使用 tab10 调色板
        sns.lineplot(
            data=plot_df,
            x="time",
            y=self.rate_col,
            hue=hue,
            ax=ax,
            palette="tab10" if hue else None,
        )

        ax.set_title(title)
        ax.set_xlabel("Time (us)")
        ax.set_ylabel(f"Rate ({self.unit})")

        # 5. 格式化坐标轴 (拒绝科学计数法 1e8)
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))

        return fig

    # ==========================================
    # 核心：特征提取逻辑
    # ==========================================
    def _extract_flow_features(self, df, hue_col):
        features = []
        t_max = df["time"].max()
        tail_start = t_max * 0.9

        for name, group in df.groupby(hue_col):
            group = group.sort_values("time")
            rates = group[self.rate_col].values
            times = group["time"].values

            # --- 修改部分开始 ---
            # 1. 找到所有速率 > 0 的索引 (完全移除阈值)
            nonzero_indices = np.where(rates > 0)[0]

            if len(nonzero_indices) > 0:
                first_idx = nonzero_indices[0]
                last_idx = nonzero_indices[-1]

                # 计算活跃时间：最晚非零时刻 - 最早非零时刻
                active_lifetime = times[last_idx] - times[first_idx]
                # 记录结束时间点用于绘图标注位置
                fct_point = times[last_idx]
            else:
                active_lifetime = 0
                fct_point = times[0]
            # --- 修改部分结束 ---

            volatility = np.std(rates)
            tail_avg = group[group["time"] >= tail_start][self.rate_col].mean()

            features.append(
                {
                    hue_col: name,
                    "active_lifetime": active_lifetime,  # 增：新增生命周期字段
                    "fct_point": fct_point,
                    "volatility": volatility,
                    "tail_avg": tail_avg,
                }
            )
        return pd.DataFrame(features)

    # ==========================================
    # 核心：双视图绘图模板
    # ==========================================
    def _plot_dual_view_goodput(self, df_attr: str, hue_col: str, title_prefix: str):
        df = getattr(self.result, df_attr, pd.DataFrame())
        if df.empty or self.rate_col not in df.columns:
            return None

        # 0. 预处理：提取特征
        feat_df = self._extract_flow_features(df, hue_col)

        # 创建一个包含两个子图的画布
        fig, (ax_dist, ax_anomaly) = plt.subplots(2, 1, figsize=(12, 10), sharex=True)
        plt.subplots_adjust(hspace=0.2)

        # ------------------------------------------
        # 视图 A: 整体趋势图 (Median + 10/90 Percentile)
        # ------------------------------------------
        # 透视表：行=时间, 列=流ID, 值=速率
        pivot_df = df.pivot(
            index="time", columns=hue_col, values=self.rate_col
        ).interpolate(method="linear")
        pivot_df.index = pivot_df.index * 1e6  # 转为 us

        median_line = pivot_df.median(axis=1)
        q10 = pivot_df.quantile(0.1, axis=1)
        q90 = pivot_df.quantile(0.9, axis=1)

        ax_dist.plot(
            pivot_df.index,
            median_line,
            color="black",
            linewidth=2,
            label="Median",
            zorder=5,
        )
        ax_dist.fill_between(
            pivot_df.index,
            q10,
            q90,
            color="gray",
            alpha=0.3,
            label="10th-90th Percentile",
        )

        ax_dist.set_title(f"{title_prefix} - Macro Distribution", fontsize=14)
        ax_dist.set_ylabel(f"Rate ({self.unit})")
        ax_dist.grid(True, ls="--", alpha=0.5)
        ax_dist.legend(loc="upper right")

        # ------------------------------------------
        # 视图 B: 异常凸显图 (Grey Background + Highlight)
        # ------------------------------------------
        # 1. 绘制背景：所有流
        plot_df_us = self._to_us(df.copy())
        for name, group in plot_df_us.groupby(hue_col):
            ax_anomaly.plot(
                group["time"],
                group[self.rate_col],
                color="lightgrey",
                alpha=0.2,
                linewidth=0.5,
                zorder=1,
            )

        # 2. 计算高亮目标
        # 生命周期最晚前 3
        top_active = feat_df.nlargest(3, "active_lifetime")[hue_col].tolist()
        # 波动率最大前 2
        top_vol = feat_df.nlargest(2, "volatility")[hue_col].tolist()
        # 尾部活跃最高前 2
        top_tail = feat_df.nlargest(2, "tail_avg")[hue_col].tolist()

        highlights = {
            "Slowest (FCT)": (top_active, "#d62728"),  # 红
            "Unstable (Vol)": (top_vol, "#ff7f0e"),  # 橙
            "Survivor (Tail)": (top_tail, "#1f77b4"),  # 蓝
        }
        label_groups = {}
        plotted_ids = set()
        x_limit_max = plot_df_us["time"].max()
        for label, (ids, color) in highlights.items():
            for target_id in ids:
                if target_id in plotted_ids:
                    continue
                plotted_ids.add(target_id)

                sub = plot_df_us[plot_df_us[hue_col] == target_id].sort_values("time")
                ax_anomaly.plot(
                    sub["time"],
                    sub[self.rate_col],
                    color=color,
                    linewidth=1.5,
                    zorder=10,
                )

                last_x = x_limit_max
                last_y = round(sub[self.rate_col].iloc[-1], 2)

                # 依然按颜色聚合 ID，以便保持文字颜色一致
                key = (last_y, color)
                if key not in label_groups:
                    label_groups[key] = []
                label_groups[key].append(str(target_id))
        y_occupancy = {}

        # 为了美观，先处理 Y 值较大的标注
        sorted_keys = sorted(label_groups.keys(), key=lambda k: k[0], reverse=True)

        for y_val, color in sorted_keys:
            ids = label_groups[(y_val, color)]
            sorted_ids = sorted(ids, key=lambda x: int(x))
            label_text = f" ID:{', '.join(sorted_ids)}"

            # 计算偏移：如果 y_val 相同，则每多一组，向下移动一行的距离
            # 0.05 是 Rate 轴的单位偏移，根据你的 y 轴范围可微调
            offset_step = (ax_anomaly.get_ylim()[1] - ax_anomaly.get_ylim()[0]) * 0.04
            current_offset_count = y_occupancy.get(y_val, 0)
            adjusted_y = y_val - (current_offset_count * offset_step)

            # 标记该 Y 坐标已被占用
            y_occupancy[y_val] = current_offset_count + 1

            ax_anomaly.text(
                x_limit_max,
                adjusted_y,
                label_text,
                color=color,
                fontsize=9,
                fontweight="bold",
                va="center",
                ha="left",
                clip_on=False,
            )
        ax_anomaly.set_title(f"{title_prefix} - Outliers & Anomalies", fontsize=14)
        ax_anomaly.set_xlim(right=x_limit_max * 1.1)
        ax_anomaly.set_xlabel("Time (us)")
        ax_anomaly.set_ylabel(f"Rate ({self.unit})")
        ax_anomaly.grid(True, ls="--", alpha=0.5)

        # 这种图不需要右侧 Legend，只需下方添加一个说明
        from matplotlib.lines import Line2D

        custom_lines = [
            Line2D([0], [0], color="#d62728", lw=2),
            Line2D([0], [0], color="#ff7f0e", lw=2),
            Line2D([0], [0], color="#1f77b4", lw=2),
        ]
        ax_anomaly.legend(
            custom_lines,
            ["Longest Active", "Highest Volatility", "High Tail Activity"],
            loc="upper right",
            fontsize=9,
        )

        # 格式化
        for ax in [ax_dist, ax_anomaly]:
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))

        return fig

    def _plot_total_goodput(self):
        return self._plot_generic_goodput(
            "total_goodput_df", hue=None, title="System Total Goodput"
        )

    def _plot_src_goodput(self):
        return self._plot_dual_view_goodput(
            "src_goodput_df", "nodeID", "Sender Goodput"
        )

    def _plot_sink_goodput(self):
        return self._plot_dual_view_goodput(
            "sink_goodput_df", "nodeID", "Receiver Goodput"
        )

    def _plot_flow_goodput(self):
        # 原始 ID 级别的 Goodput
        return self._plot_dual_view_goodput("flow_goodput_df", "ID", "Flow Goodput")

    # ==========================================
    # 3. NIC Plotters
    # ==========================================

    # ==========================================
    # [Merged] Full Stack Trace (Auto Wrapper)
    # ==========================================

    def _plot_flow_trace_auto(self):
        """
        [New] 自动绘制 Full Stack Trace。
        逻辑：优先选择 Slowdown 最大的受害流（且存在于 debug log 中）。
        """
        res = self.result
        sd_df = res.flow_slowdown_df
        target_name = None
        target_iid = None

        if not sd_df.empty and not res.cwnd_df.empty:
            # 1. 优先找最惨的流
            sorted_worst = sd_df.sort_values(by="slowdown", ascending=False)
            for _, row in sorted_worst.iterrows():
                internal_id = row["flow_id"]
                name = res.idmap.get(internal_id)
                # 必须确保名字能对应到 stdout.log 里的数据
                if name and name in res.cwnd_df["flow_name"].values:
                    target_name = name
                    target_iid = internal_id
                    # print(f"ℹ️ [Trace] 自动锁定最惨流: {target_name} (LogID: {int(target_iid)})")
                    break

        if target_name is None and not res.cwnd_df.empty:
            target_name = res.cwnd_df["flow_name"].unique()[0]
            # Try to resolve ID
            if hasattr(res, "get_internal_flow_id"):
                target_iid = res.get_internal_flow_id(target_name)

            # Retrieve SrcID from parsed events if possible
            # We need to peek into the events, but we don't have them yet here?
            # Wait, plot_flow_trace calls get_flow_trace_data which uses parse_flow_trace.
            # We can't see SrcID easily here without parsing again or just plotting.
            # BUT, we can just print LogID here.
            # print(f"ℹ️ [Trace] 兜底选择: {target_name} (LogID: {int(target_iid) if target_iid is not None else 'N/A'})")

        if target_name:
            # [Optimization] Pre-fetch events to extract InternalID for logging
            events = res.get_flow_trace_data(target_name)
            internal_id_val = (
                events.get("internal_id", [None])[0]
                if events and events.get("internal_id")
                else "N/A"
            )

            print(
                f"ℹ️ [Trace] 自动锁定最惨流: {target_name} (LogID: {int(target_iid) if target_iid is not None else 'N/A'}, InternalID: {internal_id_val})"
            )

            return self.plot_flow_trace(target_name, preloaded_events=events)
        return None

    def _plot_cwnd_dynamics(self, target_flow_name: str = None):
        """
        绘制指定流的 cwnd 和 in_flight 曲线。
        如果未指定，默认选择 FCT Slowdown 最大的流。
        """
        df = self.result.cwnd_df
        if df.empty:
            return None

        # 自动选择目标流
        if target_flow_name is None:
            target_flow_name = df["flow_name"].unique()[0]

        plot_df = df[df["flow_name"] == target_flow_name].copy()
        plot_df = self._to_us(plot_df)  # s -> us

        fig, ax = plt.subplots(figsize=(12, 5))

        ax.step(
            plot_df["time"],
            plot_df["cwnd"],
            label="CWND (Limit)",
            color="#1f77b4",
            where="post",
        )
        ax.fill_between(
            plot_df["time"],
            0,
            plot_df["in_flight"],
            step="post",
            alpha=0.2,
            color="#2ca02c",
            label="In-Flight Bytes",
        )

        ax.set_title(f"Congestion Window Dynamics: {target_flow_name}")
        ax.set_xlabel("Time (us)")
        ax.set_ylabel("Bytes")

        # 使用你已有的格式化器
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_bytes))
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))

        ax.legend(loc="upper right")
        ax.grid(True, ls="--", alpha=0.3)

        return fig

    def _plot_nic_stack(self):
        df = self.result.active_nic_df
        if df.empty:
            return None

        # 聚合全网 NIC。注意：此时列名已由 fileinfo 转换为 rx_data_{unit}
        data_col = f"rx_data_{self.unit}"
        trim_col = f"rx_trim_{self.unit}"

        agg = df.groupby("time")[[data_col, trim_col]].sum().reset_index()
        plot_df = self._to_us(agg)

        fig, ax = plt.subplots(figsize=(10, 4))
        ax.stackplot(
            plot_df["time"],
            plot_df[data_col],
            plot_df[trim_col],
            labels=["Valid Data", "Trimmed"],
            colors=["#2ca02c", "#d62728"],
            alpha=0.8,
        )

        ax.set_title("NIC Aggregate Traffic (Valid vs Trimmed)")
        ax.set_xlabel("Time (us)")
        ax.set_ylabel("Throughput (Gbps)")

        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.legend(loc="upper right")
        return fig

    # ==========================================
    # 4. Queue Plotters
    # ==========================================

    def _plot_lasthop_queues(self):
        # 使用 fileinfo 提供的 Last Hop 专用 DF
        df = self.result.tor_downlink_queues
        if df.empty:
            return None

        # 筛选 Top 3
        top_queues = df.groupby("queue_id")["max_q"].max().nlargest(3).index
        plot_df = df[df["queue_id"].isin(top_queues)].copy()
        plot_df = self._to_us(plot_df)

        # 补充 Name (如果 Model 层没做)
        if "name" not in plot_df.columns:
            if self.result.idmap:
                plot_df["name"] = plot_df["queue_id"].map(self.result.idmap.data)
            else:
                plot_df["name"] = plot_df["queue_id"].astype(str)

        fig, ax = plt.subplots(figsize=(10, 4))
        queues = plot_df["queue_id"].unique()
        colors = sns.color_palette("tab10", len(queues))

        for i, qid in enumerate(queues):
            sub = plot_df[plot_df["queue_id"] == qid].sort_values("time")
            label = sub["name"].iloc[0]
            color = colors[i]

            # 绘制 MaxQ 曲线
            ax.plot(sub["time"], sub["max_q"], label=label, color=color, linewidth=1.5)
            # 绘制微突发带 (Min-Max)
            ax.fill_between(
                sub["time"], sub["min_q"], sub["max_q"], color=color, alpha=0.2
            )

        ax.set_title("Last-Hop Queue Micro-bursts")
        ax.set_xlabel("Time (us)")
        ax.set_ylabel("Queue Depth")

        # Y轴: 字节, X轴: 纯数字
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_bytes))
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.legend()
        return fig

    def _plot_switch_buffer(self):
        df = self.result.active_switch_df
        if df.empty:
            return None

        top = df.groupby("queue_id")["max_q"].max().nlargest(3).index
        plot_df = df[df["queue_id"].isin(top)].copy()
        plot_df = self._to_us(plot_df)

        fig, ax = plt.subplots(figsize=(10, 4))
        sns.lineplot(data=plot_df, x="time", y="max_q", hue="name", ax=ax)

        ax.set_title("Switch Shared Buffer Usage (Top 3)")
        ax.set_xlabel("Time (us)")
        ax.set_ylabel("Buffer Usage")

        ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_bytes))
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        return fig

    # ==========================================
    # 5. Traffic Plotters [New]
    # ==========================

    def _plot_traffic_spatial_dist(self):
        """
        [Improved] 流量拥塞诊断联动图 (Intensity + Spatial + Queue Depth).
        横轴统一使用微秒 (us)，集成频率统计与瓶颈水位叠加。
        """
        # 1. 数据准备
        res = self.result
        df = res.traffic_df  # 获取全量包轨迹
        if df.empty:
            return None

        # 筛选核心拥塞事件：DROP (丢包) 或 TRIM (裁剪)
        error_events = ["DROP", "TRIM"]
        plot_df = df[df["event"].isin(error_events)].copy()

        if plot_df.empty or "name" not in plot_df.columns:
            fig, ax = plt.subplots(figsize=(10, 2))
            ax.text(
                0.5,
                0.5,
                "No DROP/TRIM events or missing location mapping in Traffic log.",
                ha="center",
                va="center",
            )
            ax.set_axis_off()
            return fig

        # 转换单位 s -> us
        plot_df = self._to_us(plot_df)

        # 2. 识别头号瓶颈 (发生事件最多的位置)
        bottleneck_name = plot_df["name"].value_counts().idxmax()

        # 3. 创建画布布局 (2行：顶部频率强度，底部空间分布)
        fig = plt.figure(figsize=(14, 8))
        gs = fig.add_gridspec(2, 1, height_ratios=[1, 3], hspace=0.15)
        ax_freq = fig.add_subplot(gs[0])
        ax_main = fig.add_subplot(gs[1])

        # --- A. 顶部视图：事件强度直方图 (反映拥塞爆发节奏) ---
        bins = 100  # 将时间轴划分为 100 个区间
        sns.histplot(
            data=plot_df,
            x="time",
            hue="event",
            bins=bins,
            element="step",
            palette={"DROP": "#d62728", "TRIM": "#ff7f0e"},
            ax=ax_freq,
            alpha=0.3,
            legend=False,
        )
        ax_freq.set_title(
            f"Congestion Intensity & Spatial Distribution (Hotspot: {bottleneck_name})",
            fontsize=14,
        )
        ax_freq.set_ylabel("Event Count")
        ax_freq.set_xlabel("")
        ax_freq.grid(True, ls="--", alpha=0.3)

        # --- B. 底部视图：空间分布热力图 (带抖动处理) ---
        # 使用 stripplot 配合 jitter 处理点重叠
        sns.stripplot(
            data=plot_df,
            x="time",
            y="name",
            hue="event",
            palette={"DROP": "#d62728", "TRIM": "#ff7f0e"},
            alpha=0.6,
            size=4,
            jitter=0.2,
            dodge=True,
            ax=ax_main,
        )

        ax_main.set_ylabel("Topological Location")
        ax_main.set_xlabel("Time (us)")
        ax_main.grid(True, ls="--", alpha=0.2)

        # --- C. 核心增强：叠加瓶颈队列水位 (Secondary Y-axis) ---
        # 从 queue_df 获取该位置的物理水位数据
        q_df = res.active_queue_df
        if (
            not q_df.empty
            and "name" in q_df.columns
            and bottleneck_name in q_df["name"].values
        ):
            # 提取瓶颈队列的时序数据
            bq_data = q_df[q_df["name"] == bottleneck_name].copy()
            bq_data = self._to_us(bq_data)

            ax_q = ax_main.twinx()  # 创建共享 X 轴的右侧 Y 轴
            # 绘制 MaxQ 曲线
            ax_q.plot(
                bq_data["time"],
                bq_data["max_q"],
                color="#1f77b4",
                linewidth=1.5,
                alpha=0.8,
                label=f"Queue Depth ({bottleneck_name})",
            )

            # 填充 Min-Max 包络区间，识别微突发
            ax_q.fill_between(
                bq_data["time"],
                bq_data["min_q"],
                bq_data["max_q"],
                color="#1f77b4",
                alpha=0.15,
            )

            ax_q.set_ylabel("Queue Depth (Bytes)", color="#1f77b4", fontsize=10)
            ax_q.tick_params(axis="y", labelcolor="#1f77b4")
            ax_q.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_bytes))  #

            # 合并图例
            h1, l1 = ax_main.get_legend_handles_labels()
            h2, l2 = ax_q.get_legend_handles_labels()
            ax_main.legend(
                h1 + h2, l1 + l2, loc="upper right", frameon=True, shadow=True
            )
        else:
            ax_main.legend(loc="upper right")

        # 4. 统一坐标轴格式 (拒绝科学计数法)
        for ax in [ax_freq, ax_main]:
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))

        # 如果 Y 轴位置过多，自动缩小标签
        if len(plot_df["name"].unique()) > 15:
            ax_main.tick_params(axis="y", labelsize=8)

        return fig

    def _plot_bottleneck_correlation(self):
        """
        [Optimization] 瓶颈关联诊断视图 (Correlation View) - 增强版.
        同步对比：队列负载 -> NIC 吞吐/裁剪速率 -> 原始报文事件.

        优化点：
        1. 自动高亮 Load Factor > 1.0 的物理过载区域.
        2. 集成 RTS、TRIM、DROP 三类核心拥塞信号.
        """
        res = self.result

        # 1. 识别首号瓶颈热点位置 (基于 DROP/TRIM 事件数)
        traffic_df = res.traffic_df
        if traffic_df.empty:
            return None

        # 筛选核心拥塞事件用于定位
        if "name" not in traffic_df.columns:
            return None
        err_df = traffic_df[traffic_df["event"].isin(["DROP", "TRIM"])].copy()
        if err_df.empty:
            # 若无丢包，则退而求其次寻找 DEPART 最密集的点
            bottleneck_name = traffic_df["name"].value_counts().idxmax()
        else:
            bottleneck_name = err_df["name"].value_counts().idxmax()

        # 2. 准备对齐数据
        # Panel 1: 队列微分指标 (利用率、负载因子)
        q_df = res.active_queue_df
        if not q_df.empty and "name" in q_df.columns:
            bq_data = q_df[q_df["name"] == bottleneck_name].copy()
            bq_data = self._to_us(bq_data)  # s -> us
        else:
            bq_data = pd.DataFrame()

        # Panel 2: 关联目的节点的 NIC 吞吐
        target_node_id = None
        match = re.search(r"DST(\d+)", bottleneck_name)
        if match:
            target_node_id = int(match.group(1))

        nic_df = res.active_nic_df
        b_nic_data = pd.DataFrame()
        if target_node_id is not None and not nic_df.empty:
            b_nic_data = nic_df[nic_df["nic_id"] == target_node_id].copy()
            b_nic_data = self._to_us(b_nic_data)

        # Panel 3: 原始事件轨迹 (增加 RTS 监控)
        b_err_df = traffic_df[
            (traffic_df["name"] == bottleneck_name)
            & (traffic_df["event"].isin(["DROP", "TRIM", "RTS"]))
        ].copy()
        b_err_df = self._to_us(b_err_df)

        # 3. 绘图布局
        fig, (ax1, ax2, ax3) = plt.subplots(
            3, 1, figsize=(14, 12), sharex=True, gridspec_kw={"hspace": 0.15}
        )

        # --- Panel 1: Queue Logic (过载自动标注) ---
        if not bq_data.empty:
            # 绘制 Utilization 和 Load Factor
            ax1.plot(
                bq_data["time"],
                bq_data["utilization"],
                label="Utilization (%)",
                color="#1f77b4",
                lw=1.5,
            )
            ax1.plot(
                bq_data["time"],
                bq_data["load_factor"] * 100,
                label="Load Factor (%)",
                color="#ff7f0e",
                lw=1.5,
                ls="--",
            )

            # [Optimization] 自动高亮物理过载区域 (Load Factor > 1.0)
            # 填充负载超过 100% 的区域
            ax1.fill_between(
                bq_data["time"],
                0,
                100,
                where=(bq_data["load_factor"] > 1.0),
                color="red",
                alpha=0.1,
                label="Physical Overload (>100%)",
            )

            ax1.axhline(100, color="red", alpha=0.3, ls=":")
            ax1.set_ylabel("Queue Metrics (%)")
            ax1.set_title(
                f"Bottleneck Correlation Analysis: {bottleneck_name} (Auto-Diagnosed)",
                fontsize=14,
            )
            ax1.legend(loc="upper right", fontsize=9)
            ax1.grid(True, alpha=0.3)

        # --- Panel 2: Host/NIC Logic (有效吞吐 vs 裁剪损耗) ---
        if not b_nic_data.empty:
            data_col = f"rx_data_{self.unit}"
            trim_col = f"rx_trim_{self.unit}"

            ax2.fill_between(
                b_nic_data["time"],
                0,
                b_nic_data[data_col],
                color="#2ca02c",
                alpha=0.3,
                label="Valid RX Goodput",
            )
            if trim_col in b_nic_data.columns:
                ax2.plot(
                    b_nic_data["time"],
                    b_nic_data[trim_col],
                    color="#d62728",
                    lw=1.5,
                    label="Trimming Rate (Loss)",
                )

            ax2.set_ylabel(f"NIC Rate ({self.unit})")
            ax2.legend(loc="upper right", fontsize=9)
            ax2.grid(True, alpha=0.3)

        # --- Panel 3: Discrete Event Timeline (RTS/TRIM/DROP) ---
        if not b_err_df.empty:
            sns.stripplot(
                data=b_err_df,
                x="time",
                y="event",
                hue="event",
                palette={"DROP": "#d62728", "TRIM": "#ff7f0e", "RTS": "#9467bd"},
                alpha=0.6,
                jitter=0.3,
                ax=ax3,
                legend=False,
            )
        ax3.set_ylabel("Packet Events")
        ax3.set_xlabel("Time (us)")
        ax3.grid(True, alpha=0.3, ls="--")

        # 4. 统一格式化
        for ax in [ax1, ax2, ax3]:
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))

        return fig

    def _plot_incast_fanin_pressure(self):
        """
        [Insight] 1.1 Incast 扇入度与压力相关性视图.
        物理意义：识别是否因为流数量激增导致 CC 算法失效（Fan-in 飙升），还是单条流的突发量过大（Fan-in 平稳但 Queue 飙升）。
        """
        res = self.result
        # 1. 确定瓶颈位置 (Hotspot)
        traffic_df = res.traffic_df
        if traffic_df.empty or "name" not in traffic_df.columns:
            return None

        # 优先从丢包/裁剪事件找热点名
        err_events = ["DROP", "TRIM"]
        hot_df = traffic_df[traffic_df["event"].isin(err_events)]
        if hot_df.empty:
            # 若无丢包，则取流量最活跃的位置
            bottleneck_name = traffic_df["name"].value_counts().idxmax()
        else:
            bottleneck_name = hot_df["name"].value_counts().idxmax()

        # 2. 获取队列时序数据 (Pressure: max_q)
        q_df = res.active_queue_df
        if q_df.empty or "name" not in q_df.columns:
            return None

        target_q = q_df[q_df["name"] == bottleneck_name].copy()
        if target_q.empty:
            return None
        target_q = self._to_us(target_q)  # 转换为微秒

        # 3. 计算扇入度 (Fan-in): 统计该位置在采样窗口内的唯一 flow_id 数量
        t_traffic = traffic_df[traffic_df["name"] == bottleneck_name].copy()
        t_traffic = self._to_us(t_traffic)

        # 建立对齐 bins：使用 queue_df 的采样时间点作为区间边界
        q_times = target_q["time"].sort_values().values
        if len(q_times) < 2:
            return None

        # 计算采样周期 dt
        dt = q_times[1] - q_times[0]
        # 创建左开右闭的区间桶，例如 (0, 10], (10, 20]...
        bins = np.append(q_times - dt, q_times[-1])
        t_traffic["time_bin"] = pd.cut(t_traffic["time"], bins=bins, labels=q_times)

        # 计算每个时间桶内的唯一流数
        flow_counts = (
            t_traffic.groupby("time_bin", observed=False)["flow_id"]
            .nunique()
            .reset_index()
        )
        flow_counts.columns = ["time", "active_flow_count"]
        flow_counts["time"] = flow_counts["time"].astype(float)

        # 合并队列压力与流数数据
        plot_df = pd.merge(target_q, flow_counts, on="time", how="left").fillna(0)

        # 4. 绘图 (双轴时序)
        fig, ax1 = plt.subplots(figsize=(12, 5))
        ax2 = ax1.twinx()

        # --- 左轴: 队列深度 (Pressure) ---
        ax1.plot(
            plot_df["time"],
            plot_df["max_q"],
            color="#1f77b4",
            label="Max Queue Depth",
            lw=1.5,
        )
        ax1.fill_between(
            plot_df["time"],
            plot_df["min_q"],
            plot_df["max_q"],
            color="#1f77b4",
            alpha=0.1,
        )

        # --- 右轴: 活跃流数 (Fan-in) ---
        # 使用阶梯图 (step) 能够更真实反映“同一微秒内竞争流数”的变化
        ax2.step(
            plot_df["time"],
            plot_df["active_flow_count"],
            where="post",
            color="#d62728",
            label="Active Flows (Fan-in)",
            lw=1.2,
            ls="--",
        )

        # 5. 格式化规范
        ax1.set_title(
            f"Incast Fan-in vs. Pressure Correlation (Hotspot: {bottleneck_name})",
            fontsize=14,
        )
        ax1.set_xlabel("Time (us)")
        ax1.set_ylabel("Queue Depth (Bytes)", color="#1f77b4")
        ax2.set_ylabel("Active Flow Count", color="#d62728")

        # 拒绝科学计数法，使用统一单位转换器
        ax1.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_bytes))
        ax1.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax2.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))

        ax1.grid(True, ls="--", alpha=0.3)

        # 图例合并显示
        h1, l1 = ax1.get_legend_handles_labels()
        h2, l2 = ax2.get_legend_handles_labels()
        ax1.legend(h1 + h2, l1 + l2, loc="upper right")

        return fig

    def _plot_protocol_efficiency(self):
        """
        [New Insight] 流量效能监控.
        统计有效载荷 (Data) 与 协议开销 (ACK/Pull/RTS) 的占比。
        """
        df = self.result.traffic_df
        if df.empty:
            return None

        # 基于事件名进行粗粒度分类 (UEC 协议中不同包类型对应不同 Event)
        # 注意：实际中可能需要根据 pkt_type 细化，此处演示基于 Event 的分类
        df["category"] = df["event"].apply(
            lambda x: "Data" if x in ["DEPART", "ARRIVE"] else "Control/Overhead"
        )

        # 统计各时间窗口的比例
        resampled = (
            df.set_index(pd.to_timedelta(df["time"], unit="s"))
            .groupby([pd.Grouper(freq="10us"), "category"])
            .size()
            .unstack(fill_value=0)
        )
        resampled.index = resampled.index.total_seconds() * 1e6  # 转为 us

        fig, ax = plt.subplots(figsize=(10, 5))
        resampled.plot(
            kind="area", stacked=True, ax=ax, color=["#2ca02c", "#7f7f7f"], alpha=0.7
        )

        ax.set_title("Protocol Efficiency: Data vs. Control Packets")
        ax.set_xlabel("Time (us)")
        ax.set_ylabel("Event Count")
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.grid(True, ls="--", alpha=0.3)

        return fig

    def _plot_flow_path_heatmap_auto(self):
        """
        [Auto-Wrapper] 自动选择最慢的流并生成其时空路径热力图。
        """
        res = self.result
        # 1. 寻找最值得分析的流：FCT Slowdown 最高的流
        sd_df = res.flow_slowdown_df
        if sd_df.empty:
            # 备选：找 FCT 绝对值最大的流
            df = res.flow_df
            if df.empty:
                return None
            target_id = df.nlargest(1, "fct_ns")["flow_id"].iloc[0]
        else:
            target_id = sd_df.nlargest(1, "slowdown")["flow_id"].iloc[0]

        # 2. 调用原始绘图函数
        return self._plot_flow_path_heatmap(target_flow_id=target_id)

    def _plot_flow_path_heatmap(self, target_flow_id: int):
        """
        [Killer View] 修正版：流路径时空热力图。
        """
        res = self.result

        # 1. 物理拓扑层级映射逻辑 (基于 IdMap 规范)
        def get_hop_level(name):
            if name is None:
                return -1
            if "SRC" in name:
                return 0
            if "LS" in name and "DST" not in name:
                return 1  # ToR Up
            if "US" in name and "CS" not in name:
                return 2  # Agg Up
            if "CS" in name:
                return 3  # Core
            if "US" in name and "LS" in name:
                return 4  # Agg Down
            if "LS" in name and "DST" in name:
                return 5  # ToR Down (Last Hop)
            if "DST" in name:
                return 6  # Host Dest
            return -1

        # 2. 获取背景队列压力数据 (max_q)
        q_df = res.active_queue_df.copy()
        if not q_df.empty and "name" in q_df.columns:
            q_df["hop"] = q_df["name"].apply(get_hop_level)
            q_df = q_df[q_df["hop"] >= 0]
            q_df = self._to_us(q_df)  # s -> us
        else:
            q_df = pd.DataFrame(columns=["time", "hop", "max_q"])

        # 3. 获取特定流的轨迹
        t_df = res.traffic_df[res.traffic_df["flow_id"] == target_flow_id].copy()
        if t_df.empty:
            return None

        if "name" in t_df.columns:
            t_df["hop"] = t_df["name"].apply(get_hop_level)
        else:
            t_df["hop"] = -1
        t_df = self._to_us(t_df)

        fig, ax = plt.subplots(figsize=(14, 7))

        # 背景：使用散点或网格展示全网队列水位 (红色越深压力越大)
        sc = ax.scatter(
            q_df["time"],
            q_df["hop"],
            c=q_df["max_q"],
            cmap="YlOrRd",
            norm=LogNorm(
                vmin=1024, vmax=max(1024 * 10, res.active_queue_df["max_q"].max())
            ),  # 1KB以下统一深色，以上对数显示
            s=80,
            marker="s",
            alpha=0.7,
            edgecolors="none",
        )

        # 前景：绘制该流所有 Packet 的轨迹
        for pkt_id, group in t_df.groupby("pkt_id"):
            group = group.sort_values("time")
            ax.plot(
                group["time"],
                group["hop"],
                color="#1f77b4",
                alpha=0.1,
                lw=0.5,
                zorder=5,
            )

        # 标注特殊拥塞事件 (TRIM/DROP)
        err_df = t_df[t_df["event"].isin(["TRIM", "DROP"])]
        if not err_df.empty:
            ax.scatter(
                err_df["time"],
                err_df["hop"],
                marker="x",
                color="black",
                s=60,
                label="Congestion (TRIM/DROP)",
                zorder=10,
            )

        # 界面美化
        ax.set_yticks(range(7))
        ax.set_yticklabels(
            [
                "Source",
                "ToR (Up)",
                "Agg (Up)",
                "Core",
                "Agg (Down)",
                "ToR (Last Hop)",
                "Dest",
            ]
        )
        ax.set_title(
            f"Detailed Path-Time Trace: Flow {target_flow_id} (Worst Slowdown Case)",
            fontsize=14,
        )
        ax.set_xlabel("Time (us)")
        cbar = plt.colorbar(sc, label="Queue Depth")
        cbar.ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_bytes))
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.grid(True, ls=":", alpha=0.4)
        ax.legend(loc="upper right")

        return fig

    def plot_flow_trace(self, flow_name: str, preloaded_events: dict = None):
        """
        [Final Merged] Full Stack Analysis: Protocol + Network + Latency.
        融合了原有的 Sequence 视图和 Congestion Diagnostic 视图，
        在同一时间轴下展示：
        1. Protocol: SeqNo, ACK, Retransmission, CWND, InFlight
        2. Network: Bottleneck Queue Depth, Physical DROP/TRIM Events
        3. Latency: Split RTT (Prop vs Queue)
        """
        res = self.result
        if preloaded_events:
            events = preloaded_events
        else:
            events = self.result.get_flow_trace_data(flow_name)

        if not events or not events["send_t"]:
            print(f"No trace data found for {flow_name}")
            return None

        # --- Data Prep for Network Layer (Logic ported from cc_diagnostic) ---
        # 1. 尝试找到物理世界的 LoggedID
        # 逻辑：在 idmap 中寻找与 name 匹配的 ID
        candidate_ids = [k for k, v in res.idmap.items() if flow_name in v]
        active_traffic_ids = (
            set(res.traffic_df["flow_id"].unique())
            if not res.traffic_df.empty
            else set()
        )

        traffic_logged_id = next(
            (cid for cid in candidate_ids if cid in active_traffic_ids), None
        )

        traffic_data = pd.DataFrame()
        hotspot_name = None

        if traffic_logged_id:
            traffic_data = res.traffic_df[
                res.traffic_df["flow_id"] == traffic_logged_id
            ].copy()
            if not traffic_data.empty and "name" in traffic_data.columns:
                # 自动定位瓶颈：丢包/裁剪最多的位置，或者最活跃的位置
                err_df = traffic_data[traffic_data["event"].isin(["DROP", "TRIM"])]
                hotspot_name = (
                    err_df["name"].value_counts().idxmax()
                    if not err_df.empty
                    else traffic_data["name"].value_counts().idxmax()
                )

        # --- Visualization Layout ---
        # 2 Rows: Protocol (Top), Network/Latency (Bottom - Dual Axis)
        fig, (ax1, ax_net) = plt.subplots(
            2,
            1,
            figsize=(16, 10),
            sharex=True,
            gridspec_kw={"height_ratios": [3, 2], "hspace": 0.05},
        )

        # ==========================================
        # Row 1: Protocol Layer (Seq & CWND)
        # ==========================================
        ax1.set_ylabel(
            "Sequence Number", color="tab:blue", fontsize=11, fontweight="bold"
        )
        ax1.tick_params(axis="y", labelcolor="tab:blue")

        # --- [New] Separate Probe Channel Calculation ---
        max_seq = 0
        if events["send_seq"]:
            max_seq = max(max_seq, max(events["send_seq"]))
        if events["recv_seq"]:
            max_seq = max(max_seq, max(events["recv_seq"]))

        # Probe Channel Y-position (Top of graph)
        # Scaled to 1.1 as requested
        probe_y = max_seq * 1.05 if max_seq > 0 else 100

        # Define Headroom Factor (Total Axis Height relative to Data)
        # We give a bit more than 1.1 to ensure the marker fits comfortably
        Y_HEADROOM = 1.2

        # Calculate Max Bytes for Right Axis (CWND / InFlight)
        max_bytes = 0
        if events.get("cwnd_val"):
            max_bytes = max(max_bytes, max(events["cwnd_val"]))
        if events.get("inflight_val"):
            max_bytes = max(max_bytes, max(events["inflight_val"]))

        # --- Plot Probes (Top Channel) ---
        # --- Plot Probes (Top Channel) ---
        if events.get("probe_t"):
            # Plot Probe Sends
            ax1.scatter(
                events["probe_t"],
                [probe_y] * len(events["probe_t"]),
                marker="o",
                s=40,
                facecolors="none",
                edgecolors="magenta",
                label="Probe Send",
                zorder=30,
            )
            # Annotate Sends
            for t, seq in zip(events["probe_t"], events["probe_seq"]):
                ax1.text(
                    t,
                    probe_y * 1.02,
                    f"P{seq}",
                    color="magenta",
                    fontsize=8,
                    ha="center",
                )

        # Plot Probe Arrivals (From Stdout Log)
        if events.get("probe_recv_t"):
            ax1.scatter(
                events["probe_recv_t"],
                [probe_y] * len(events["probe_recv_t"]),
                marker="o",  # Hollow circle
                s=40,
                facecolors="magenta",  # Solid magenta for Arrival (or verify user pref)
                edgecolors="none",  # Let's use solid for arrival to distinguish? Or consistent?
                # User asked for: "Probe Send" (hollow/solid?) -> previous was Send=Solid Blue.
                # Let's stick to: Send=Hollow Magenta, Arrival=Solid Magenta for clear pair.
                label="Probe Arrival",
                zorder=30,
            )

            # Draw lines between Probe Send and Arrival
            # Match by Sequence Number
            if events.get("probe_t") and events.get("probe_seq"):
                send_map = dict(zip(events["probe_seq"], events["probe_t"]))

                for t_arr, seq_arr in zip(
                    events["probe_recv_t"], events["probe_recv_seq"]
                ):
                    if seq_arr in send_map:
                        t_send = send_map[seq_arr]
                        # Draw curved line (Arc)
                        ax1.annotate(
                            "",
                            xy=(t_arr, probe_y),
                            xycoords="data",
                            xytext=(t_send, probe_y),
                            textcoords="data",
                            arrowprops=dict(
                                arrowstyle="-",
                                color="magenta",
                                connectionstyle="arc3,rad=-0.5",
                                linewidth=0.5,
                                alpha=0.5,
                            ),
                            zorder=29,
                        )

        # --- Plot Normal Sends (Filtered) ---
        # Heuristic: If we have traffic_data, filter by size.
        # If not, use events["send_t"] which comes from stdout regex ("sending pkt").
        # As determined, stdout regex "sending pkt" excludes "sendProbe".
        # So events["send_seq"] should be clean.

        ax1.scatter(
            events["send_t"],
            events["send_seq"],
            c="blue",
            alpha=0.5,
            s=40,
            label="Normal Send",
            edgecolors="none",
        )

        # [New] AR Flag Visualization (Yellow Star Context)
        if "send_ar" in events and any(events["send_ar"]):
            ar_indices = [i for i, x in enumerate(events["send_ar"]) if x == 1]
            if ar_indices:
                ar_t = [events["send_t"][i] for i in ar_indices]
                ar_seq = [events["send_seq"][i] for i in ar_indices]
                ax1.scatter(
                    ar_t,
                    ar_seq,
                    c="red",  # Changed from gold to red for visibility
                    marker="*",
                    s=200,  # Increased size
                    alpha=1.0,  # Full opacity
                    label="Packet with AR Flag",
                    zorder=20,  # Verified on top of everything
                    edgecolors="black",  # Add border for contrast
                )

        # [New] Sink Reception (Physical Arrival from Traffic Log)
        # More robust: Look for DEPART from the Last-Hop Pipe (e.g. "Pipe-LS0->DST0")
        if not traffic_data.empty and "name" in traffic_data.columns:
            # Filter for DEPART events from Pipes connected to Destination
            sink_arrivals = traffic_data[
                (traffic_data["event"] == "DEPART")
                & (traffic_data["name"].str.contains("Pipe", na=False))
                & (traffic_data["name"].str.contains("DST", na=False))
            ]

            # Map time to us
            if not sink_arrivals.empty:
                sink_t = sink_arrivals["time"] * 1e6
                sink_seq = sink_arrivals["pkt_id"]

                # --- Filter out Probes ---
                if "pkt_type" in sink_arrivals.columns:
                    # [New] Precise Filtering using Logged Packet Type
                    # Exclude PROBE packets from the "Normal Data Arrival" plot
                    sink_arrivals_clean = sink_arrivals[
                        sink_arrivals["pkt_type"] != "PROBE"
                    ]
                    sink_t = sink_arrivals_clean["time"] * 1e6
                    sink_seq = sink_arrivals_clean["pkt_id"]

                elif events.get("probe_recv_t"):
                    # [Legacy] Heuristic Greedy Matching
                    probe_list = list(
                        zip(events["probe_recv_t"], events["probe_recv_seq"])
                    )

                    # Convert to easier format for searching
                    # We keep original indices to drop later
                    sink_candidates = []  # list of (time, seq, original_index)
                    t_list = sink_t.tolist()
                    s_list = sink_seq.tolist()
                    for i, (t, s) in enumerate(zip(t_list, s_list)):
                        sink_candidates.append(
                            {"t": t, "s": s, "idx": i, "matched": False}
                        )

                    indices_to_drop = set()

                    for pt, ps in probe_list:
                        # Find best match for this specific probe
                        best_match = None
                        min_diff = 5.0  # Max tolerance 5us

                        for cand in sink_candidates:
                            if cand["matched"]:
                                continue
                            if cand["s"] != ps:
                                continue

                            diff = abs(cand["t"] - pt)
                            if diff < min_diff:
                                min_diff = diff
                                best_match = cand

                        if best_match:
                            best_match["matched"] = True
                            indices_to_drop.add(best_match["idx"])

                    # Reconstruct filtered lists
                    if indices_to_drop:
                        print(
                            f"Filtered {len(indices_to_drop)} Probe physical events from Data plot."
                        )
                        sink_t = [
                            t for i, t in enumerate(t_list) if i not in indices_to_drop
                        ]
                        sink_seq = [
                            s for i, s in enumerate(s_list) if i not in indices_to_drop
                        ]
                        sink_t = pd.Series(sink_t, dtype=float)
                        sink_seq = pd.Series(sink_seq, dtype=int)
                    # If no probes were dropped, sink_t and sink_seq remain as original Series.
                    # If all were dropped, then sink_t and sink_seq should be empty Series.
                    elif (
                        not indices_to_drop and len(t_list) > 0
                    ):  # No probes dropped, but there were sink arrivals
                        # sink_t and sink_seq are already correctly assigned from sink_arrivals
                        pass
                    else:  # No sink arrivals or all were probes and dropped
                        sink_t = pd.Series([], dtype=float)
                        sink_seq = pd.Series([], dtype=int)

                ax1.scatter(
                    sink_t,
                    sink_seq,
                    c="purple",
                    marker="D",
                    s=30,
                    alpha=0.6,
                    label="Physical Arrival (Sink)",
                    zorder=12,
                    edgecolors="none",
                )

        # Fallback to log-based if traffic log missing (optional)
        elif events.get("recv_t"):
            ax1.scatter(
                events["recv_t"],
                events["recv_seq"],
                c="purple",
                marker="D",
                s=30,
                alpha=0.6,
                label="Log Recv (Sink)",
                zorder=12,
                edgecolors="none",
            )

        # Retransmissions
        if events["rtx_t"]:
            ax1.scatter(
                events["rtx_t"],
                events["rtx_seq"],
                # 重传使用空心圆圈
                marker="o",
                s=80,
                linewidth=1.5,
                label="Retransmission",
                zorder=10,
                facecolors="none",
                edgecolors="red",
            )
        # ACKs (Cumulative Line)
        if events["ack_t"]:
            sorted_acks = sorted(zip(events["ack_t"], events["ack_seq"]))
            if sorted_acks:
                a_t, a_s = zip(*sorted_acks)
                ax1.step(
                    a_t,
                    a_s,
                    c="green",
                    where="post",
                    alpha=0.5,
                    linewidth=2,
                    label="Cum ACK Line",
                )

                # [New] Generate Individual ACK Points (Green Solid Circle) - Deduplicated
                # Goal: Mark each packet as ACKed exactly once, at the *earliest* time the Sender knows it.

                confirmed_seqs = set()
                ack_events = []  # List of (time, seq, type)

                # 1. Collect SACKs (Explicit)
                if "sack_t" in events and events["sack_t"]:
                    for t, s in zip(events["sack_t"], events["sack_seq"]):
                        ack_events.append((t, s, "sack"))

                # 2. Collect Cum ACKs (Implicit Range)
                sorted_valid_acks = sorted(zip(events["ack_t"], events["ack_seq"]))
                if sorted_valid_acks:
                    prev_s = 0  # Initialize to 0 to capture the first ACK segment (including Seq 0)
                    # We can only infer new ACKs if the cum_ack increases.
                    # We don't know the initial state before the first log, so we start from the first log.

                    for t, s in sorted_valid_acks:
                        if s > prev_s:
                            # Range [prev_s, s) are newly cumulatively acked
                            for seq_k in range(prev_s, s):
                                ack_events.append((t, seq_k, "cum"))
                            prev_s = s
                        elif s < prev_s:
                            # Reordering or weird log? Ignore regression for ACK generation to be safe.
                            pass

                # 3. Sort all events by time to find the earliest confirmation
                ack_events.sort(key=lambda x: x[0])

                plot_t = []
                plot_s = []

                for t, seq, _ in ack_events:
                    if seq not in confirmed_seqs:
                        confirmed_seqs.add(seq)
                        plot_t.append(t)
                        plot_s.append(seq)

                if plot_t:
                    ax1.scatter(
                        plot_t,
                        plot_s,
                        c="green",
                        marker="o",
                        s=40,
                        alpha=0.8,
                        edgecolors="none",
                        label="Packet ACKed",
                        zorder=15,
                    )

        # RTO Lines (Show on all plots)
        unique_rto = sorted(list(set(events["rto_t"])))
        for i, t in enumerate(unique_rto):
            label = "RTO Event" if i == 0 else None
            for ax in [ax1, ax_net]:
                ax.axvline(
                    x=t, color="orange", linestyle="--", alpha=0.5, linewidth=1.5
                )

        # --- Precise TRIM/DROP Mapping ---
        # Map physical drops/trims from Traffic Log directly to Sequence Number
        t_plot = self._to_us(traffic_data)
        physical_events = t_plot[t_plot["event"].isin(["DROP", "TRIM"])]

        # [Fix] Filter out PROBE triggers for congestion events too
        if "pkt_type" in physical_events.columns:
            physical_events = physical_events[physical_events["pkt_type"] != "PROBE"]

        if not physical_events.empty:
            # Drop Events
            drops = physical_events[physical_events["event"] == "DROP"]
            if not drops.empty:
                ax1.scatter(
                    drops["time"],
                    drops["pkt_id"],
                    # 丢包使用 X
                    c="red",
                    marker="X",
                    s=100,
                    linewidth=2,
                    label="Physical DROP",
                    zorder=20,
                )

            # Trim Events
            trims = physical_events[physical_events["event"] == "TRIM"]
            if not trims.empty:
                ax1.scatter(
                    # TRIM Uses Triangle
                    trims["time"],
                    trims["pkt_id"],
                    facecolors="none",
                    edgecolors="tab:orange",
                    marker="^",
                    s=40,
                    linewidth=1.5,
                    label="Physical TRIM",
                    zorder=20,
                )

        # Twin Axis for CWND
        ax1_r = ax1.twinx()
        ax1_r.set_ylabel(
            "Bytes (CWND / In-Flight)",
            color="tab:purple",
            fontsize=11,
            fontweight="bold",
        )
        # Synchronize Axis Limits to reserve top 20% on both sides
        # Synchronize Axis Limits to reserve top 20% on both sides
        # Also limit bottom to slightly below 0 (e.g. -2%) to avoid cutting off markers at 0
        if max_seq > 0:
            top_seq = max_seq * Y_HEADROOM
            ax1.set_ylim(bottom=-top_seq * 0.02, top=top_seq)
        if max_bytes > 0:
            top_bytes = max_bytes * Y_HEADROOM
            ax1_r.set_ylim(bottom=-top_bytes * 0.02, top=top_bytes)
        ax1_r.tick_params(axis="y", labelcolor="tab:purple")

        if events["cwnd_t"]:
            sorted_cwnd = sorted(zip(events["cwnd_t"], events["cwnd_val"]))
            c_t, c_v = zip(*sorted_cwnd)
            ax1_r.plot(c_t, c_v, color="tab:purple", lw=2, alpha=0.9, label="CWND")

        if events["inflight_t"]:
            sorted_inf = sorted(zip(events["inflight_t"], events["inflight_val"]))
            i_t, i_v = zip(*sorted_inf)
            ax1_r.fill_between(
                i_t, 0, i_v, color="gray", alpha=0.15, step="post", label="In-Flight"
            )

        # Extract InternalID
        internal_id_val = (
            events.get("internal_id", [None])[0] if events.get("internal_id") else None
        )

        ax1.set_title(
            f"Full Stack Analysis: {flow_name} (LogID: {traffic_logged_id}, InternalID: {internal_id_val if internal_id_val is not None else 'N/A'})",
            fontsize=14,
            pad=10,
        )

        # === Legend Row 1 (Handles Only) ===
        lines1, labs1 = ax1.get_legend_handles_labels()
        lines1r, labs1r = ax1_r.get_legend_handles_labels()
        # Legend moved to bottom of figure

        ax1_r.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_bytes))

        # ==========================================
        # Row 2: Network (Left) + Latency (Right)
        # ==========================================
        # Left Axis: Queue Depth
        ax_net.set_ylabel(
            "Queue Depth (Bytes)", color="#d62728", fontsize=11, fontweight="bold"
        )
        ax_net.tick_params(axis="y", labelcolor="#d62728")
        ax_net.set_xlabel("Time (us)", fontsize=11, fontweight="bold")  # Shared X label

        has_net_data = False
        if hotspot_name:
            # Plot Queue Depth
            q_data = pd.DataFrame()
            if not res.active_queue_df.empty and "name" in res.active_queue_df.columns:
                q_data = self._to_us(
                    res.active_queue_df[res.active_queue_df["name"] == hotspot_name]
                )

            if not q_data.empty:
                ax_net.plot(
                    q_data["time"],
                    q_data["max_q"],
                    label=f"Hotspot Queue @ {hotspot_name}",
                    color="#d62728",
                    alpha=0.6,
                    lw=1.5,
                )
                ax_net.fill_between(
                    q_data["time"], 0, q_data["max_q"], color="#d62728", alpha=0.05
                )
                has_net_data = True

            # Plot Physical Drops/Trims
            t_plot = self._to_us(traffic_data)
            drops = t_plot[t_plot["event"].isin(["DROP", "TRIM"])]
            if not drops.empty:
                for ev_type, color in [("TRIM", "#ff7f0e"), ("DROP", "red")]:
                    sub = drops[drops["event"] == ev_type]
                    if not sub.empty:
                        ax_net.vlines(
                            sub["time"],
                            0,
                            ax_net.get_ylim()[1],
                            colors=color,
                            alpha=0.4,
                            linestyles="-",
                            lw=1,
                            label=f"Physical {ev_type}",
                        )
                has_net_data = True

            # if has_net_data:
            #     ax_net.text(0.01, 0.9, f"Hotspot: {hotspot_name}", transform=ax_net.transAxes,
            #                 bbox=dict(facecolor='white', alpha=0.7))

        if not has_net_data:
            ax_net.text(
                0.5,
                0.5,
                "No Queue Log Data",
                ha="center",
                va="center",
                transform=ax_net.transAxes,
                color="gray",
            )

        ax_net.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_bytes))

        # Right Axis: Latency (RTT & Delay)
        ax_lat = ax_net.twinx()
        ax_lat.set_ylabel(
            "Latency (us)", color="tab:brown", fontsize=11, fontweight="bold"
        )
        ax_lat.tick_params(axis="y", labelcolor="tab:brown")

        if events["rtt_t"]:
            sorted_rtt_all = sorted(
                zip(events["rtt_t"], events["delay_val"], events["raw_rtt_val"])
            )
            r_t, d_v, raw_v = zip(*sorted_rtt_all)

            ax_lat.plot(
                r_t,
                raw_v,
                color="tab:brown",
                marker=".",
                markersize=5,
                lw=1,
                alpha=0.8,
                label="Total RTT",
            )
            ax_lat.plot(
                r_t,
                d_v,
                color="orange",
                ls="--",
                lw=1,
                alpha=0.8,
                label="Queueing Delay",
            )
            # ax_lat.fill_between(r_t, 0, d_v, color="orange", alpha=0.05) # Optional: remove fill to reduce clutter overlap

            max_raw = max(raw_v)
            if max_raw > 0:
                ax_lat.text(
                    0.01,
                    0.82,
                    f"Max RTT: {max_raw:.1f}us",
                    transform=ax_lat.transAxes,
                    fontsize=9,
                    bbox=dict(facecolor="white", alpha=0.7),
                )

        # Legends Row 2 (Handles Only)
        lines2, labs2 = ax_net.get_legend_handles_labels()
        lines3, labs3 = ax_lat.get_legend_handles_labels()
        # Legend moved to bottom of figure

        ax_net.grid(True, ls=":", alpha=0.4)

        # Consistent Formatter
        for ax in [ax1, ax_net]:
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))

        # Align X-axis limits
        all_times = events["send_t"] + events["ack_t"]
        if all_times:
            t_min, t_max = min(all_times), max(all_times)
            duration = t_max - t_min
            margin = duration * 0.02 if duration > 0 else 10.0
            ax_net.set_xlim(left=t_min - margin, right=t_max + margin)

        # --- Unified Legend (Bottom, Multi-column) ---
        all_lines = lines1 + lines1r + lines2 + lines3
        all_labs = labs1 + labs1r + labs2 + labs3

        # Deduplicate
        by_label = dict(zip(all_labs, all_lines))

        fig.legend(
            by_label.values(),
            by_label.keys(),
            loc="lower center",
            bbox_to_anchor=(0.5, 0.01),
            ncol=6,  # 4-6 columns as requested
            fontsize=10,
            frameon=True,
            framealpha=0.9,
        )

        plt.subplots_adjust(bottom=0.15, right=0.95, top=0.92)
        # plt.show()
        title_tag = f"Full Stack Analysis: {flow_name} (LogID: {traffic_logged_id}, InternalID: {flow_name.split('_')[-2] if '_' in flow_name else flow_name})"
        self._attach_save_btn(fig, title=title_tag)
        return fig
