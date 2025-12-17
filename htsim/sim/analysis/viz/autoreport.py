import matplotlib.pyplot as plt
import seaborn as sns
import pandas as pd
from pathlib import Path
from typing import Optional, List, Union

# 仅在需要时尝试导入 IPython，避免在非 Notebook 环境报错
try:
    from IPython.display import display, Markdown

    IPYTHON_AVAILABLE = True
except ImportError:
    IPYTHON_AVAILABLE = False

from ..data.fileinfo import ExperimentResult
from ..parser.statusyaml import parse_enabled_logs


class AutoVisualizer:
    """
    自动可视化生成器。
    支持两种模式：
    1. save(): 保存图片到磁盘 (Batch Mode)
    2. show(): 在 Jupyter Notebook 中交互式展示 (Interactive Mode)
    """

    def __init__(self, result: ExperimentResult):
        self.result = result
        self.enabled_logs = set(parse_enabled_logs(self.result.status_path))
        # 使用字典存储生成函数，实现按需计算
        self.plotters = {
            "Flow Completion Time (CDF)": self._plot_flow_fct_cdf,
            "Flow Size vs FCT": self._plot_flow_scatter,
            "System Goodput Timeline": self._plot_sink_goodput,
            "NIC Aggregate Traffic": self._plot_nic_stats,
            "Top-3 Hotspot Queues": self._plot_hotspot_queues,
            "Switch Buffer Usage": self._plot_switch_buffer,
        }

    def _get_active_plotters(self):
        """根据日志开启情况，筛选出需要执行的绘图函数"""
        active = {}

        # 1. Flow
        if "flow_events" in self.enabled_logs:
            active["Flow Completion Time (CDF)"] = self.plotters[
                "Flow Completion Time (CDF)"
            ]
            active["Flow Size vs FCT"] = self.plotters["Flow Size vs FCT"]

        # 2. Sink
        if "sink" in self.enabled_logs:
            active["System Goodput Timeline"] = self.plotters["System Goodput Timeline"]

        # 3. NIC
        if "nic" in self.enabled_logs:
            active["NIC Aggregate Traffic"] = self.plotters["NIC Aggregate Traffic"]

        # 4. Queue
        queue_flags = {"tor_downqueue", "tor_upqueue", "queue"}
        if not self.enabled_logs.isdisjoint(queue_flags):
            active["Top-3 Hotspot Queues"] = self.plotters["Top-3 Hotspot Queues"]

        # 5. Switch
        if "switch" in self.enabled_logs:
            active["Switch Buffer Usage"] = self.plotters["Switch Buffer Usage"]

        return active

    def show(self):
        """
        [Interactive Mode]
        在 Jupyter Notebook 中直接渲染图表，无需保存文件。
        """
        if not IPYTHON_AVAILABLE:
            print(
                "Error: IPython is not available. Cannot use .show() in this environment."
            )
            return

        active_plotters = self._get_active_plotters()

        if not active_plotters:
            display(
                Markdown("### ⚠️ No visualization data available (Check enabled logs)")
            )
            return

        display(Markdown(f"# 📊 Auto Report: {self.result.base_dir.name}"))

        for title, plotter_func in active_plotters.items():
            fig = plotter_func()
            if fig:
                # 1. 打印 Markdown 标题
                display(Markdown(f"### {title}"))
                # 2. 展示图片
                display(fig)
                # 3. 关闭图片释放内存 (因为已经渲染到前端了)
                plt.close(fig)
            else:
                # 也许有日志但没数据 (Empty DataFrame)
                pass

    def save(self, output_dir: Union[str, Path]):
        """
        [Batch Mode]
        将图表保存为文件。
        """
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        active_plotters = self._get_active_plotters()
        print(f"Generating report for {self.result.base_dir.name}...")

        for title, plotter_func in active_plotters.items():
            fig = plotter_func()
            if fig:
                safe_name = (
                    title.replace(" ", "_").lower().replace("(", "").replace(")", "")
                    + ".png"
                )
                save_path = output_dir / safe_name
                fig.savefig(save_path, dpi=100, bbox_inches="tight")
                print(f"  [Saved] {safe_name}")
                plt.close(fig)

    # ==========================================
    # 绘图逻辑 (返回 Figure 对象，不负责显示或保存)
    # ==========================================

    def _plot_flow_fct_cdf(self):
        df = self.result.flow_df
        if df.empty or "fct_ns" not in df.columns:
            return None
        fig, ax = plt.subplots(figsize=(8, 4))
        sns.ecdfplot(data=df, x="fct_ns", ax=ax)
        ax.set_xscale("log")
        ax.set_title("Flow Completion Time CDF")
        ax.grid(True, which="both", ls="--", alpha=0.5)
        return fig

    def _plot_flow_scatter(self):
        df = self.result.flow_df
        if df.empty:
            return None
        fig, ax = plt.subplots(figsize=(8, 4))
        sns.scatterplot(data=df, x="size_bytes", y="fct_ns", alpha=0.5, ax=ax)
        ax.set_yscale("log")
        ax.set_xscale("log")
        ax.set_title("Flow Size vs FCT")
        return fig

    def _plot_sink_goodput(self):
        df = self.result.total_goodput_df
        if df.empty:
            return None
        rate_col = f"Rate_{self.result.rate_unit}"
        fig, ax = plt.subplots(figsize=(10, 4))
        sns.lineplot(data=df, x="time", y=rate_col, ax=ax)
        ax.set_title("System Goodput Timeline")
        return fig

    def _plot_nic_stats(self):
        df = self.result.active_nic_df
        if df.empty:
            return None
        col = f"rx_total_{self.result.rate_unit}"
        agg = df.groupby("time")[col].sum().reset_index()
        fig, ax = plt.subplots(figsize=(10, 4))
        sns.lineplot(data=agg, x="time", y=col, ax=ax, label="Total RX")
        ax.set_title("NIC Aggregate Traffic")
        return fig

    def _plot_hotspot_queues(self):
        df = self.result.tor_downlink_queues
        if df.empty:
            df = self.result.active_queue_df
        if df.empty:
            return None

        # Top 3 Logic
        top = df.groupby("queue_id")["max_q"].max().nlargest(3).index
        plot_df = df[df["queue_id"].isin(top)].copy()
        if "name" not in plot_df.columns:
            plot_df["name"] = plot_df["queue_id"].astype(str)

        fig, ax = plt.subplots(figsize=(10, 4))
        sns.lineplot(data=plot_df, x="time", y="max_q", hue="name", ax=ax)
        ax.set_title("Top 3 Congested Queues")
        return fig

    def _plot_switch_buffer(self):
        df = self.result.active_switch_df
        if df.empty:
            return None
        top = df.groupby("queue_id")["max_q"].max().nlargest(3).index
        plot_df = df[df["queue_id"].isin(top)]
        fig, ax = plt.subplots(figsize=(10, 4))
        sns.lineplot(data=plot_df, x="time", y="max_q", hue="name", ax=ax)
        ax.set_title("Switch Shared Buffer Usage")
        return fig
