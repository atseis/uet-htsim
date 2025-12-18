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
        
        # 获取速率单位后缀 (e.g., "Gbps")，默认为 Gbps
        self.unit = getattr(self.result, "rate_unit", "Gbps") 
        # 预期的列名，例如 "Rate_Gbps"
        self.rate_col = f"Rate_{self.unit}"
        
        # 注册所有绘图器
        self.plotters = {
            # --- Flow Level ---
            "Flow Completion Time (CDF)": self._plot_flow_fct_cdf,
            "Flow Size vs FCT (Scatter)": self._plot_flow_scatter,
            
            # --- Goodput Level (Simplified) ---
            "System Total Goodput": self._plot_total_goodput,
            "Goodput by Sender Host": self._plot_src_goodput,
            "Goodput by Receiver Host": self._plot_sink_goodput,
            "Top Active Flows Goodput": self._plot_flow_goodput,

            # --- NIC Level ---
            "NIC Traffic Breakdown": self._plot_nic_stack,

            # --- Queue Level ---
            "Last-Hop Queue Dynamics": self._plot_lasthop_queues,
            "Switch Shared Buffer Usage": self._plot_switch_buffer,
        }

    def _get_active_plotters(self):
        """根据日志开启情况，筛选出需要执行的绘图函数"""
        active = {}

        # 1. Flow Logs
        if "flow_events" in self.enabled_logs:
            active["Flow Completion Time (CDF)"] = self.plotters["Flow Completion Time (CDF)"]
            active["Flow Size vs FCT (Scatter)"] = self.plotters["Flow Size vs FCT (Scatter)"]

        # 2. Sink Logs (Goodput)
        if "sink" in self.enabled_logs:
            active["System Total Goodput"] = self.plotters["System Total Goodput"]
            active["Goodput by Sender Host"] = self.plotters["Goodput by Sender Host"]
            active["Goodput by Receiver Host"] = self.plotters["Goodput by Receiver Host"]
            active["Top Active Flows Goodput"] = self.plotters["Top Active Flows Goodput"]

        # 3. NIC Logs
        if "nic" in self.enabled_logs:
            active["NIC Traffic Breakdown"] = self.plotters["NIC Traffic Breakdown"]

        # 4. Queue Logs
        queue_flags = {"tor_downqueue", "tor_upqueue", "queue"}
        if not self.enabled_logs.isdisjoint(queue_flags):
            active["Last-Hop Queue Dynamics"] = self.plotters["Last-Hop Queue Dynamics"]
        
        # 5. Switch Logs
        if "switch" in self.enabled_logs:
            active["Switch Shared Buffer Usage"] = self.plotters["Switch Shared Buffer Usage"]

        return active

    # ==========================================
    # 公共交互方法 (Show & Save)
    # ==========================================

    def show(self):
        """[Interactive Mode] Jupyter Notebook 展示"""
        if not IPYTHON_AVAILABLE:
            print("Error: IPython is not available.")
            return

        active_plotters = self._get_active_plotters()
        if not active_plotters:
            display(Markdown("### ⚠️ No visualization data available (Check enabled logs)"))
            return

        display(Markdown(f"# 📊 Auto Report: {self.result.base_dir.name}"))
        
        for title, plotter_func in active_plotters.items():
            try:
                fig = plotter_func()
                if fig:
                    display(Markdown(f"### {title}"))
                    display(fig)
                    plt.close(fig)
            except Exception as e:
                display(Markdown(f"**Error plotting {title}:** {str(e)}"))

    def save(self, output_dir: Union[str, Path]):
        """[Batch Mode] 保存图片到磁盘"""
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)

        active_plotters = self._get_active_plotters()
        print(f"Generating report for {self.result.base_dir.name}...")

        for title, plotter_func in active_plotters.items():
            try:
                fig = plotter_func()
                if fig:
                    safe_name = title.replace(" ", "_").replace("(", "").replace(")", "").lower() + ".png"
                    save_path = output_dir / safe_name
                    fig.savefig(save_path, dpi=100, bbox_inches="tight")
                    print(f"  [Saved] {safe_name}")
                    plt.close(fig)
            except Exception as e:
                print(f"  [Error] Failed to plot {title}: {e}")

    # ==========================================
    # 辅助格式化工具 (Helpers)
    # ==========================================

    @staticmethod
    def _fmt_plain(x, pos=None):
        """强制显示纯数字 (如 200 而非 2e2)，用于 FCT 和 Rate 轴"""
        return f'{x:g}'

    @staticmethod
    def _fmt_bytes(x, pos=None):
        """自动字节单位 (B/KB/MB/GB)"""
        if x == 0: return "0 B"
        units = ['B', 'KB', 'MB', 'GB', 'TB']
        i = 0
        val = x
        while val >= 1024 and i < len(units) - 1:
            val /= 1024.0
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
        df = self.result.flow_df
        if df.empty or "fct_ns" not in df.columns: return None
        
        # FCT 单位: ns -> us
        data = df["fct_ns"] / 1000.0
        
        fig, ax = plt.subplots(figsize=(8, 4))
        sns.ecdfplot(data=data, ax=ax, linewidth=2)
        ax.set_xscale("log")
        
        # 强制 Log 轴显示纯数字
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(self._fmt_plain))
        
        ax.set_xlabel("Flow Completion Time (us)")
        ax.set_ylabel("CDF")
        ax.set_title(f"FCT CDF (n={len(df)})")
        ax.grid(True, which="both", ls="--", alpha=0.3)
        
        # 标注 P99
        p99 = np.percentile(data, 99)
        ax.axvline(p99, color='r', linestyle=':', alpha=0.6)
        ax.text(p99, 0.5, f" P99: {p99:.0f} us", color='r', rotation=90, va='center', backgroundcolor='white')
        return fig

    def _plot_flow_scatter(self):
        df = self.result.flow_df
        if df.empty: return None
        fig, ax = plt.subplots(figsize=(8, 4))
        
        sns.scatterplot(x=df["size_bytes"], y=df["fct_ns"]/1000.0, alpha=0.5, ax=ax, edgecolor=None)
        
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
        sns.lineplot(data=plot_df, x="time", y=self.rate_col, hue=hue, ax=ax, palette="tab10" if hue else None)
        
        ax.set_title(title)
        ax.set_xlabel("Time (us)")
        ax.set_ylabel(f"Rate ({self.unit})")
        
        # 5. 格式化坐标轴 (拒绝科学计数法 1e8)
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        
        return fig

    def _plot_total_goodput(self):
        return self._plot_generic_goodput("total_goodput_df", hue=None, title="System Total Goodput")

    def _plot_src_goodput(self):
        # nodeID 是 sink.py 聚合后的标准列名
        return self._plot_generic_goodput("src_goodput_df", hue="nodeID", title="Goodput by Sender Host")

    def _plot_sink_goodput(self):
        return self._plot_generic_goodput("sink_goodput_df", hue="nodeID", title="Goodput by Receiver Host")

    def _plot_flow_goodput(self):
        # 在没有 FlowName 注入前，使用 ID 分类
        return self._plot_generic_goodput("flow_goodput_df", hue="ID", title="Top Active Flows Goodput")

    # ==========================================
    # 3. NIC Plotters
    # ==========================================

    def _plot_nic_stack(self):
        df = self.result.active_nic_df
        if df.empty: return None
        
        # 聚合全网 NIC。注意：此时列名已由 fileinfo 转换为 rx_data_{unit}
        data_col = f"rx_data_{self.unit}"
        trim_col = f"rx_trim_{self.unit}"
        
        agg = df.groupby("time")[[data_col, trim_col]].sum().reset_index()
        plot_df = self._to_us(agg)
        
        fig, ax = plt.subplots(figsize=(10, 4))
        ax.stackplot(plot_df["time"], plot_df[data_col], plot_df[trim_col], 
                    labels=["Valid Data", "Trimmed/Dropped"],
                    colors=["#2ca02c", "#d62728"], alpha=0.8)
        
        ax.set_title("NIC Aggregate Traffic (Valid vs Trimmed)")
        ax.set_xlabel("Time (us)")
        ax.set_ylabel("Throughput (Gbps)")
        
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.legend(loc='upper right')
        return fig

    # ==========================================
    # 4. Queue Plotters
    # ==========================================

    def _plot_lasthop_queues(self):
        # 使用 fileinfo 提供的 Last Hop 专用 DF
        df = self.result.tor_downlink_queues
        if df.empty: return None

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
            ax.fill_between(sub["time"], sub["min_q"], sub["max_q"], color=color, alpha=0.2)

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
        if df.empty: return None
        
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