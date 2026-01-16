import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns
import numpy as np
from pathlib import Path
from typing import List, Dict, Union, Optional, Any, Callable, Tuple

# 引用现有组件
from .fileinfo import ExperimentResult


class BatchResult:
    """
    科研级批量实验管理器 (Universal Loader v2.1).
    采用“扫描模式”替代“猜测模式”，解决路径不匹配导致的加载失败。
    """

    def __init__(self):
        # 存储结构: {unique_uid: {"result": ExperimentResult, "tags": {}}}
        self.experiments: Dict[str, Dict[str, Any]] = {}
        # 自动推断项目根目录
        from ..runner import PROJECT_DIR

        self.results_base_dir = PROJECT_DIR / "results"
        self.experiments_dir = PROJECT_DIR / "experiments"

    def get_all_flows_df(self, extra_cols: List[str] = None) -> pd.DataFrame:
        """
        【增加】从所有子实验中提取原始流数据 (Flow-level raw data).
        用于绘制全网范围的 CDF 叠加图。
        """
        all_dfs = []
        for uid, entry in self.experiments.items():
            res = entry["result"]
            df = res.flow_df.copy()  # 访问 ExperimentResult.flow_df
            if df.empty:
                continue

            # 注入实验变量 (如 version, randseed) 和手动标签
            for col in extra_cols or ["version", "randseed"]:
                val = res.params.get(col) or entry["tags"].get(col)
                df[col] = val

            # FCT 转换: ns -> us
            df["fct_us"] = df["fct_ns"] / 1000.0
            all_dfs.append(df)

        return pd.concat(all_dfs, ignore_index=True) if all_dfs else pd.DataFrame()

    def get_summary_df(self, metrics: List[str]) -> pd.DataFrame:
        """
        【修改】汇总大表：自动从 ExperimentResult.params 提取全量变量，
        并利用缓存机制获取性能指标。
        """
        rows = []
        for uid, entry in self.experiments.items():
            res = entry["result"]
            # 基础参数(来自 status.yaml) + 手动标签 + 元数据
            row = {
                **res.params,  # 包含 all_params 和 variables 的合并结果
                **entry["tags"],
                "_uid": uid,
                "_path": str(res.base_dir),
            }
            # 提取缓存指标
            for m in metrics:
                # [FIX]: if m is already in params (e.g. linkspeed), do not overwrite with metric fetch (which might fail/return NaN)
                if m in row:
                    continue
                try:
                    row[m] = res.get_cached_metric(m)
                except Exception:
                    import numpy as np

                    row[m] = np.nan
            rows.append(row)

        df = pd.DataFrame(rows)
        # 显式处理数值转换，修复 FutureWarning
        if not df.empty:
            for col in df.columns:
                if col.startswith("_"):
                    continue
                try:
                    df[col] = pd.to_numeric(df[col])
                except (ValueError, TypeError):
                    continue
        return df

    def filter(self, predicate: Optional[Callable] = None, **kwargs) -> "BatchResult":
        """
        【升级版】多模式链式筛选接口。
        支持：精确匹配、列表成员检查、Lambda 范围筛选、以及自定义复杂谓词。
        """
        new_batch = BatchResult()

        for uid, entry in self.experiments.items():
            res = entry["result"]
            tags = entry["tags"]
            params = res.params  # ExperimentResult 提供的合并参数字典

            # 为了方便判断，将参数和标签合并
            combined = {**params, **tags}

            # 1. 检查 kwargs 筛选逻辑
            match_kwargs = True
            for k, v in kwargs.items():
                val = combined.get(k)

                # A. 如果 v 是可调用对象 (lambda)，执行函数判断
                if callable(v):
                    if not v(val):
                        match_kwargs = False
                        break
                # B. 如果 v 是列表，执行成员检查 (in)
                elif isinstance(v, list):
                    if val not in v:
                        match_kwargs = False
                        break
                # C. 否则执行精确匹配 (==)
                else:
                    if val != v:
                        match_kwargs = False
                        break

            if not match_kwargs:
                continue

            # 2. 检查自定义谓词逻辑 (处理复杂的跨字段判断)
            # predicate 接收 (ExperimentResult, tags) 作为参数
            if predicate and not predicate(res, tags):
                continue

            new_batch.experiments[uid] = entry

        return new_batch

    def aggregate(self, groupby: List[str], metrics: List[str]) -> pd.DataFrame:
        """
        [新增] 统计聚合工具。用于量化不同算法在多组随机种子下的稳定性。
        返回包含平均值 (avg)、标准差 (std)、最大值 (max) 的统计表。
        """
        df = self.get_summary_df(metrics)
        if df.empty:
            return df

        # 定义统计量映射
        res = df.groupby(groupby)[metrics].agg(["mean", "std", "max"])
        # 展平多级索引列名，如 max_fct_avg
        res.columns = [f"{m}_{s}" for m in metrics for s in ["avg", "std", "max"]]
        return res.reset_index()

    def find_by_params(self, **params) -> List[ExperimentResult]:
        """
        [新增] 解决 KeyError 工具函数。
        根据参数组合（如 randseed=4, version='baseline'）快速查找 ExperimentResult 对象。
        用法: res = batch.find_by_params(randseed=4, version='baseline')[0]
        """
        # 获取包含元数据的 summary 表
        # 这里默认带上常见的 metrics 以便内部筛选，实际上只需要 _uid
        df = self.get_summary_df([])

        for k, v in params.items():
            if k in df.columns:
                df = df[df[k] == v]

        results = []
        for uid in df["_uid"].tolist():
            if uid in self.experiments:
                results.append(self.experiments[uid]["result"])
        return results

    def export_to_parquet(self, filename: str = "batch_summary.parquet"):
        """将汇总大表存为 Parquet 格式，供外部绘图工具（如 Origin 或 R）使用"""
        df = self.get_summary_df(["max_fct", "max_slowdown", "fairness_index"])
        df.to_parquet(filename)
        print(f"Summary exported to {filename}")

    def get_varying_params(self, min_nunique: int = 2) -> List[str]:
        """
        [新增] 自动检测实验中的变量因子。
        返回那些取值数量 >= min_nunique 的列名。
        """
        df = self.get_summary_df([])
        if df.empty:
            return []
        
        # 排除内部字段和非数值/分类字段
        candidates = [c for c in df.columns if not c.startswith("_")]
        varying = []
        for col in candidates:
            # 尝试转换为数值以排除全是字符串的常量
            try:
                # 忽略 NaN
                n_unique = df[col].dropna().nunique()
                if n_unique >= min_nunique:
                    varying.append(col)
            except Exception:
                continue
        return varying

    @property
    def viz(self):
        return BatchVisualizer(self)

    def add_source(
        self,
        source: Union[str, Path, List[Union[str, Path]]],
        tags: Optional[Dict] = None,
        filters: Optional[Dict] = None,
    ):
        """
        【修改】统一加载入口：支持 YAML、子实验目录、大实验目录或以上列表的混合输入。
        """
        if isinstance(source, list):
            for s in source:
                self.add_source(s, tags, filters)
            return

        path = Path(source).resolve()
        tags = tags or {}

        if path.is_file() and path.suffix in [".yaml", ".yml"]:
            self._load_from_yaml(path, tags, filters)
        elif (path / "status.yaml").exists():
            self._register(path, tags, filters)
        elif path.is_dir():
            self._scan_and_register(path, tags, filters)

    def _load_from_yaml(self, yaml_path: Path, tags: Dict, filters: Dict = None):
        """根据 YAML 相对位置定位 results 目录并扫描。"""
        try:
            # 获取相对 experiments 的路径，如 RICC_tests/test.yaml
            rel_path = yaml_path.relative_to(self.experiments_dir)
            # 对应 results/RICC_tests/test/
            exp_root = self.results_base_dir / rel_path.with_suffix("")
        except ValueError:
            # 如果 YAML 不在 experiments 目录下，降级使用文件名
            exp_root = self.results_base_dir / yaml_path.stem

        if not exp_root.exists():
            print(f"[!] Warning: Result directory not found: {exp_root}")
            return

        # 注入来源标签
        combined_tags = {**{"origin_yaml": yaml_path.stem}, **tags}
        self._scan_and_register(exp_root, combined_tags, filters)

    def _scan_and_register(self, root_dir: Path, tags: Dict, filters: Dict = None):
        """递归扫描目录下所有的 status.yaml，这是最稳妥的加载方式。"""
        count = 0
        for status_file in root_dir.glob("**/status.yaml"):
            if self._register(status_file.parent, tags, filters):
                count += 1
        if count == 0:
            print(f"[!] No valid experiments found in {root_dir}")

    def _register(self, path: Path, tags: Dict, filters: Dict = None) -> bool:
        """执行实际的注册。"""
        res = ExperimentResult(path)

        # 筛选逻辑：如果不成功，默认不加载（除非你在调试）
        if not res.is_success:
            return False

        # 参数过滤：只加载符合 filters 条件的（如 conns=64）
        if filters:
            if not all(res.params.get(k) == v for k, v in filters.items()):
                return False

        # 生成唯一 ID (使用相对路径)
        uid = str(path.relative_to(self.results_base_dir))
        if uid not in self.experiments:
            self.experiments[uid] = {"result": res, "tags": tags}
            return True
        return False


class BatchVisualizer:
    def __init__(self, batch: BatchResult):
        self.batch = batch

    def _fmt_plain(self, x, pos=None):
        return f"{x:g}"

    def plot_pivot(
        self,
        x: str,
        y: str,
        hue: Optional[str] = None,
        col: Optional[str] = None,
        row: Optional[str] = None,
        kind: str = "line",  # 支持 line, bar, box, scatter
        metrics: Optional[List[str]] = None,
        title: Optional[str] = None,
        y_log: bool = False,
        **sns_kwargs,
    ):
        """
        【增加】通用科研透视绘图 API：一键处理筛选、聚类和子图。
        :param x: X 轴变量（如 'nodes' 或 'flowsize'）
        :param y: Y 轴指标（如 'max_fct' 或 'p99_fct'）
        :param hue: 聚类变量（每种取值对应一条线/颜色，如 'strat' 或 'version'）
        :param col/row: 分面变量（用于横向或纵向对比子图，如 'conns'）
        """
        df = self.batch.get_summary_df(metrics or [y])
        if df.empty:
            return

        import matplotlib.pyplot as plt
        import seaborn as sns
        import matplotlib.ticker as ticker

        sns.set_theme(style="whitegrid", font_scale=1.1)

        # 选择绘图函数
        plot_func = sns.relplot if kind in ["line", "scatter"] else sns.catplot

        g = plot_func(
            data=df,
            x=x,
            y=y,
            hue=hue,
            col=col,
            row=row,
            kind=kind,
            marker="o" if kind == "line" else None,
            facet_kws={"sharey": False, "sharex": True},
            **sns_kwargs,
        )

        # 格式化
        for ax in g.axes.flat:
            if y_log:
                ax.set_yscale("log")
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
            ax.grid(True, ls="--", alpha=0.5)

        if title:
            g.fig.suptitle(title, y=1.02)
        plt.show()
        return g

    def drill_down(self, **params):
        """
        【增加】下钻分析：定位特定的子实验并弹出其 AutoVisualizer 报告。
        """
        results = self.batch.find_by_params(**params)
        if not results:
            print("No matching experiment found.")
            return

        # 调用 ExperimentResult 的 report 属性（AutoVisualizer）
        results[0].report.show()  # 使用 fileinfo.py 中新增的 report 属性

    def plot_distribution(
        self,
        y: str,
        x: str = "version",
        hue: Optional[str] = None,
        kind: str = "box",
        filters: Dict = None,
    ):
        """
        展示指标的分布情况。kind 支持 'box', 'violin', 'strip'。
        非常适合展示 Sleek 如何压缩了 Baseline 的长尾分布。
        """
        df = self.batch.get_summary_df([y])
        if filters:
            for k, v in filters.items():
                df = df[df[k] == v]

        plt.figure(figsize=(8, 6))
        if kind == "box":
            sns.boxplot(data=df, x=x, y=y, hue=hue, palette="muted", showmeans=True)
        elif kind == "violin":
            sns.violinplot(data=df, x=x, y=y, hue=hue, split=True, inner="quart")

        plt.title(f"Distribution of {y} across Seeds")
        plt.grid(axis="y", ls="--", alpha=0.3)
        plt.show()

    def plot_improvement(
        self,
        base_version: str,
        target_version: str,
        metric: str = "max_fct",
        groupby: str = "randseed",
    ):
        """
        计算并画出“优化比例”图。
        Y轴 = (Base - Target) / Base * 100 %
        """
        df = self.batch.get_summary_df([metric])
        # 提取两组数据并按种子对齐
        base_data = df[df["version"] == base_version].set_index(groupby)[metric]
        target_data = df[df["version"] == target_version].set_index(groupby)[metric]

        improvement = (base_data - target_data) / base_data * 100

        plt.figure(figsize=(10, 5))
        improvement.plot(kind="bar", color="skyblue", edgecolor="black")
        plt.axhline(0, color="red", lw=1)
        plt.ylabel("Improvement (%)")
        plt.title(f"{target_version} vs {base_version}: {metric} Reduction")
        plt.show()

    def plot_generic(
        self,
        x: str,
        y: str,
        hue: str = None,
        col: str = None,
        kind: str = "line",
        metrics: List[str] = None,
        filters: Dict = None,
        title: str = None,
        y_scale: str = "linear",
    ):
        """
        高阶通用绘图接口。
        支持：置信区间(CI)、分面(Facet)、多算法对比(Hue)。
        """
        df = self.batch.get_summary_df(metrics or [y])
        if df.empty:
            print("[!] Summary DataFrame is empty. Check filters or paths.")
            return

        if filters:
            for k, v in filters.items():
                df = df[df[k] == v]

        # 设置绘图风格
        sns.set_theme(style="whitegrid")

        # 使用 relplot 支持分面
        g = sns.relplot(
            data=df,
            x=x,
            y=y,
            hue=hue,
            col=col,
            kind=kind,
            marker="o" if kind == "line" else None,
            facet_kws={"sharey": False, "sharex": True},
            aspect=1.2,
            height=4,
        )

        # 轴格式化
        for ax in g.axes.flat:
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
            ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
            if y_scale == "log":
                ax.set_yscale("log")
            ax.grid(True, ls="--", alpha=0.5)

        if title:
            g.fig.suptitle(title, y=1.05, fontsize=14)

        plt.show()
        return g

    def plot_statistical_summary(
        self,
        x: str,
        hue: str = "version",
        metrics: Optional[List[str]] = None,
        title: str = "Scalability Analysis: FCT Statistics",
    ):
        """
        [新增] 科研级多指标对比图。
        维度 1 (颜色 Hue): 对应算法/配置 (如 baseline vs sleek)
        维度 2 (线型 Style): 对应统计指标 (默认 Max, P99, Median)
        """
        import matplotlib.ticker as ticker

        # 1. 自动提取核心 FCT 指标
        target_metrics = metrics or ["max_fct", "p99_fct", "median_fct"]
        df = self.batch.get_summary_df(target_metrics)
        if df.empty:
            return

        # 2. 数据长表化 (Melt)：将多列指标转为一列 'Metric' 和一列 'Value'
        id_vars = [c for c in df.columns if c not in target_metrics]
        df_long = df.melt(
            id_vars=id_vars,
            value_vars=target_metrics,
            var_name="Metric",
            value_name="FCT_us",
        )

        # 3. 映射美化名称
        name_map = {"max_fct": "Max", "p99_fct": "P99", "median_fct": "Median"}
        df_long["Metric"] = df_long["Metric"].map(name_map)

        # --- 【关键修正 A】: 执行物理逻辑排序 ---
        # 理由：磁盘 glob 加载是无序的。我们需要提取 ecn 字符串（如 "4 20"）中的第一个数字进行排序。
        def get_sort_key(val):
            try:
                # 尝试取第一个空格前的数字，如果是纯数字则直接转换
                return float(str(val).split()[0])
            except (ValueError, AttributeError, IndexError):
                return 0.0

        df_long["_sort_order"] = df_long[x].apply(get_sort_key)
        df_long = df_long.sort_values("_sort_order").drop(columns=["_sort_order"])
        # ----------------------------------------

        # 4. 绘图风格设置 (参考 image_62442b 样式)
        plt.figure(figsize=(12, 7))
        sns.set_theme(style="whitegrid", font_scale=1.1)

        # 定义指标对应的线型与标记符号
        # Max: 点线(X), P99: 实线(o), Median: 虚线(s)
        style_map = {"Max": (2, 2), "P99": "", "Median": (5, 5)}
        markers = {"Max": "X", "P99": "o", "Median": "s"}

        ax = sns.lineplot(
            data=df_long,
            x=x,
            y="FCT_us",
            hue=hue,  # 颜色区分算法
            style="Metric",  # 线型区分统计量
            markers=markers,
            dashes=style_map,
            palette="husl",  # 高对比度配色
            linewidth=2,
            markersize=8,
            sort=False,
        )

        # 5. 细节优化与格式化
        ax.set_title(title, pad=20, fontsize=14)
        ax.set_ylabel("Flow Completion Time (us)")
        ax.set_xlabel(x.replace("_", " ").capitalize())

        # --- 【关键修正 B】: 类型敏感的 X 轴格式化 ---
        # 理由：之前强制执行 _fmt_plain 会把分类标签的索引(0,1...)转为字符串。
        # 仅当 X 轴数据本身是数值类型（如 nodes）时才使用自定义格式化器。
        is_x_numeric = pd.api.types.is_numeric_dtype(df_long[x])
        if is_x_numeric:
            ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        # 如果是字符串（如 "4 20"），保持默认，Matplotlib 将显示原始标签。

        # 强制拒绝科学计数法
        # ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))

        # 优化图例布局，防止遮挡曲线
        plt.legend(bbox_to_anchor=(1.02, 1), loc="upper left", borderaxespad=0.0)
        plt.grid(True, ls="--", alpha=0.4)

        sns.despine(trim=False)
        plt.tight_layout()
        plt.show()

    def plot_fct_cdf_overlap(
        self,
        hue: str = "version",
        filters: Optional[Dict] = None,
        title: str = "Batch FCT CDF Comparison",
    ):
        """
        【增加】批量 FCT CDF 叠加图。
        每一条曲线代表一个分组（如不同算法版本）在所有种子下的流分布总和。
        """
        import matplotlib.pyplot as plt
        import seaborn as sns
        import matplotlib.ticker as ticker

        # 1. 获取全量流数据
        df = self.batch.get_all_flows_df(
            extra_cols=[hue] + list((filters or {}).keys())
        )
        if df.empty:
            print("[!] No flow data found.")
            return

        # 2. 执行筛选
        if filters:
            for k, v in filters.items():
                df = df[df[k] == v]

        # 3. 绘图
        plt.figure(figsize=(10, 5))
        sns.set_theme(style="whitegrid")

        # 使用对数轴展示长尾
        ax = sns.ecdfplot(data=df, x="fct_us", hue=hue, palette="tab10", linewidth=2)
        ax.set_xscale("log")

        # 4. 格式化规范
        ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.xaxis.set_minor_formatter(ticker.FuncFormatter(self._fmt_plain))
        ax.set_xlabel("Flow Completion Time (us)")
        ax.set_ylabel("CDF")
        ax.set_title(title)
        ax.grid(True, which="both", ls="--", alpha=0.4)

        plt.show()
        return ax

    # ==========================================
    # 6. DoE / Sampling 可视化工具
    # ==========================================


    def plot_main_effects(
        self,
        factors: List[str],
        metric: Union[str, List[str]],
        agg: str = "mean",
        filters: Dict = None,
        sharey: bool = True,
    ):
        """
        主效应图：逐个因子画 (factor -> metric) 的聚合曲线。
        支持自动分组显示：同类指标（如各类 FCT）在同一行展示，不同类指标（如 FCT 与 利用率）分行展示。
        - factors: 因子名列表，如 ['randseed', 'target_q_delay']
        - metric: 目标指标列名 (支持单个或列表)，如 'max_fct' 或 ['avg_fct', 'p99_fct']
                  支持宏 'fct' -> ["avg_fct", "median_fct", "p99_fct", "max_fct"]
        - agg: 聚合方式，'mean' | 'median' | 'max' 等
        - filters: 额外筛选条件（精确匹配）
        """
        raw_metrics = [metric] if isinstance(metric, str) else metric
        expanded_metrics = []
        
        # 1. 宏展开与预处理
        for m in raw_metrics:
            if m.lower() == "fct":
                expanded_metrics.extend(["avg_fct", "median_fct", "p99_fct", "max_fct"])
            else:
                expanded_metrics.append(m)
        
        # 2. 智能分组 (Heuristic Grouping)
        from collections import defaultdict
        groups = defaultdict(list)
        for m in expanded_metrics:
            m_lower = m.lower()
            if "fct" in m_lower or "slowdown" in m_lower or "latency" in m_lower:
                groups["Response Time"].append(m)
            elif "util" in m_lower or "load" in m_lower:
                groups["Utilization"].append(m)
            elif "drop" in m_lower or "loss" in m_lower:
                groups["Drops / Loss"].append(m)
            elif "queue" in m_lower:
                groups["Queue State"].append(m)
            else:
                groups[m].append(m) # 无法分类的单独一行

        df = self.batch.get_summary_df(expanded_metrics)
        if df.empty:
            print("[!] Summary DataFrame is empty.")
            return

        if filters:
            for k, v in filters.items():
                df = df[df[k] == v]

        import matplotlib.pyplot as plt
        import seaborn as sns
        from matplotlib.ticker import FuncFormatter

        n_cols = len(factors)
        n_rows = len(groups)
        if n_cols == 0 or n_rows == 0:
            return

        # 使用 squeeze=False 确保 axes 总是 2D 数组 [row][col]
        fig, axes = plt.subplots(
            n_rows, n_cols, 
            figsize=(min(20, 5 * n_cols), 4 * n_rows), 
            sharex='col', 
            sharey='row',
            squeeze=False 
        )

        sns.set_theme(style="whitegrid")
        
        # 定义样式循环
        markers = ["o", "s", "^", "D", "v", "<", ">"]
        linestyles = ["-", "--", "-.", ":", "-", "--", "-."]
        
        group_names = list(groups.keys())

        for row_idx, group_name in enumerate(group_names):
            current_metrics = groups[group_name]
            colors = sns.color_palette("tab10", n_colors=len(current_metrics))
            
            for col_idx, factor in enumerate(factors):
                ax = axes[row_idx][col_idx]
                
                if factor not in df.columns:
                    ax.set_visible(False)
                    continue

                for m_idx, m in enumerate(current_metrics):
                    if m not in df.columns: continue
                    
                    try:
                        grouped = df.groupby(factor, observed=False)[m].agg(agg).reset_index()
                        sns.lineplot(
                            data=grouped,
                            x=factor,
                            y=m,
                            marker=markers[m_idx % len(markers)],
                            linestyle=linestyles[m_idx % len(linestyles)],
                            color=colors[m_idx % len(colors)],
                            label=m,
                            ax=ax,
                            linewidth=2,
                            markersize=8
                        )
                    except Exception as e:
                        print(f"[Warn] Plotting failed for {m} vs {factor}: {e}")

                # 设置标题（仅第一行）和标签
                if row_idx == 0:
                    ax.set_title(f"Impact of {factor}", fontsize=12, fontweight='bold')
                
                # 设置Y轴标签（每行第一个）
                if col_idx == 0:
                    ax.set_ylabel(f"{group_name} ({agg})", fontsize=11, fontweight='bold')
                else:
                    ax.set_ylabel("")

                ax.grid(True, ls="--", alpha=0.3)
                ax.legend(fontsize=9, loc='best')
                
                # Smart Format X Axis
                if pd.api.types.is_numeric_dtype(df[factor]):
                    def fmt_func(x, pos, col=factor): 
                        return self._smart_format(col, x)
                    ax.xaxis.set_major_formatter(FuncFormatter(fmt_func))

            # Smart Format Y Axis (Row-wise using first metric in group)
            valid_metrics = [m for m in current_metrics if m in df.columns and pd.api.types.is_numeric_dtype(df[m])]
            if valid_metrics:
                base_metric = valid_metrics[0]
                def fmt_func_y(y, pos, col=base_metric):
                    return self._smart_format(col, y)
                # Apply to the first ax in row (shared y)
                axes[row_idx][0].yaxis.set_major_formatter(FuncFormatter(fmt_func_y))

        plt.tight_layout()
        plt.show()

    def plot_parallel_coordinates(
        self,
        factors: List[str],
        metrics: List[str],
        hue: str = None,
        filters: Dict = None,
        sample: Optional[int] = 200,
        normalize: bool = True,
        highlight: Dict = None,
    ):
        """
        平行坐标图：同时查看多个因子 + 指标的关系，用于 LHS/正交实验整体形状观察。
        - factors: 因子列名列表
        - metrics: 指标列名列表
        - hue: 分组列（如 'version' 或 'algorithm'），可选
        - filters: 精确筛选条件
        - sample: 随机下采样到指定行数（None 表示不过滤）
        - normalize: 是否对每列进行 Min-Max 归一化 (解决y轴跨度不一致问题)
        """
        cols = list(set(factors + metrics + ([hue] if hue else [])))
        df = self.batch.get_summary_df(list(set(metrics)))
        if df.empty:
            print("[!] Summary DataFrame is empty.")
            return

        df = df[[c for c in cols if c in df.columns]].copy()

        if filters:
            for k, v in filters.items():
                df = df[df[k] == v]

        if df.empty:
            print("[!] No data after filtering.")
            return

        if sample is not None and len(df) > sample:
            df = df.sample(sample, random_state=0)

        label_col = hue or "__group__"
        if label_col not in df.columns:
            df[label_col] = "all"

        # 核心修改：归一化处理
        plot_df = df[factors + metrics + [label_col]].copy()
        
        # 预先计算并保存原始范围用于标签
        range_labels = {}
        
        if normalize:
            for col in factors + metrics:
                if col not in plot_df.columns: 
                    continue
                # 跳过非数值列
                if not pd.api.types.is_numeric_dtype(plot_df[col]):
                    range_labels[col] = col
                    continue
                    
                min_val = plot_df[col].min()
                max_val = plot_df[col].max()
                
                # 获取格式化后的 Min/Max 字符串
                min_str = self._smart_format(col, min_val)
                max_str = self._smart_format(col, max_val)

                if max_val > min_val:
                    # 归一化到 [0, 1]
                    plot_df[col] = (plot_df[col] - min_val) / (max_val - min_val)
                    # 重命名列以包含原始范围信息
                    # 格式: Name\nMin ~ Max
                    range_label = f"{col}\n{min_str}\n↓\n{max_str}"
                    plot_df.rename(columns={col: range_label}, inplace=True)
                else:
                    # 如果只有单一值
                    range_label = f"{col}\n{min_str}"
                    plot_df.rename(columns={col: range_label}, inplace=True)

        # [Custom Implementation] Curved Parallel Coordinates
        # 丢弃 pandas.plotting.parallel_coordinates，改用自定义 Bezier 实现
        
        plot_df = plot_df.rename(columns={label_col: "class"})
        cols_to_plot = [c for c in plot_df.columns if c != "class"]
        
        # 提取数据矩阵 (N_samples, M_axes)
        data_matrix = plot_df[cols_to_plot].values
        # 提取分类标签用于着色
        class_labels = plot_df["class"].values
        
        # X 轴坐标: 0, 1, 2 ... M-1
        x_coords = np.arange(len(cols_to_plot))
        
        from matplotlib.collections import LineCollection
        
        def _make_bezier_curves(y_data, x_coords):
            """
            生成平滑曲线的坐标点。
            y_data: shape (N, M)
            return: segments list of shape (N, (M-1)*steps, 2)
            """
            N, M = y_data.shape
            steps = 20 # 每一段的插值点数
            t = np.linspace(0, 1, steps)
            
            # Bezier Basis functions (Cubic with horizontal tangents)
            # P(t) = (1-t)^3 P0 + 3(1-t)^2 t P1 + 3(1-t) t^2 P2 + t^3 P3
            # Set P1 = (x0 + 0.5, y0), P2 = (x1 - 0.5, y1) for sigmoid shape
            
            segments = []
            for i in range(N):
                points = []
                for j in range(M - 1):
                    x0, x1 = x_coords[j], x_coords[j+1]
                    y0, y1 = y_data[i, j], y_data[i, j+1]
                    
                    # Control points
                    xc1, xc2 = x0 + 0.5, x1 - 0.5
                    yc1, yc2 = y0, y1
                    
                    # Compute curve points
                    x_curve = (1-t)**3 * x0 + 3*(1-t)**2*t * xc1 + 3*(1-t)*t**2 * xc2 + t**3 * x1
                    y_curve = (1-t)**3 * y0 + 3*(1-t)**2*t * yc1 + 3*(1-t)*t**2 * yc2 + t**3 * y1
                    
                    seg_points = np.column_stack([x_curve, y_curve])
                    points.append(seg_points)
                
                # Stack all segments for this line
                full_line = np.vstack(points)
                segments.append(full_line)
            
            return segments

        with plt.style.context("seaborn-v0_8-whitegrid"):
            fig, ax = plt.subplots(figsize=(max(10, 2.0 * len(cols_to_plot)), 7))
            
            # 准备 Highlight Mask
            mask_indices = np.zeros(len(plot_df), dtype=bool)
            
            # A. 全局计算高亮 Mask (若有配置)
            if highlight:
                target_metric = highlight.get("metric")
                 # 注意：target_metric 在 df (原始数据) 中查找
                if target_metric in df.columns:
                    fraction = highlight.get("fraction", 0.1)
                    is_top = highlight.get("top", True)
                    q_val = df[target_metric].quantile(1.0 - fraction if is_top else fraction)
                    
                    if is_top:
                        mask_indices = df[target_metric].values >= q_val
                    else:
                        mask_indices = df[target_metric].values <= q_val
            
            # B. 分离数据
            if highlight and np.any(mask_indices):
                bg_data = data_matrix[~mask_indices]
                hl_data = data_matrix[mask_indices]
                hl_labels = class_labels[mask_indices]
            else:
                bg_data = None
                hl_data = data_matrix
                hl_labels = class_labels

            # C. 绘制背景层 (灰色，低透明，细线)
            if bg_data is not None and len(bg_data) > 0:
                bg_segs = _make_bezier_curves(bg_data, x_coords)
                lc_bg = LineCollection(bg_segs, colors="#d3d3d3", alpha=0.1, linewidths=1)
                ax.add_collection(lc_bg)

            # D. 绘制高亮层/主层 (彩色，高透明，粗线)
            if len(hl_data) > 0:
                hl_segs = _make_bezier_curves(hl_data, x_coords)
                
                # 颜色映射逻辑
                unique_labels = np.unique(hl_labels)
                if len(unique_labels) > 1:
                    # 使用 viridis 映射分类
                    cmap = plt.get_cmap("viridis")
                    # 简单 hash labels 到 float [0,1]
                    label_map = {l: i/(len(unique_labels)-1) if len(unique_labels)>1 else 0.5 
                                 for i, l in enumerate(sorted(unique_labels))}
                    colors = [cmap(label_map[l]) for l in hl_labels]
                else:
                    colors = "teal" # 默认单色

                lc_hl = LineCollection(hl_segs, colors=colors, alpha=0.8, linewidths=1.5)
                ax.add_collection(lc_hl)

            # E. 设置坐标轴
            ax.set_xticks(x_coords)
            ax.set_xticklabels(cols_to_plot, rotation=0, fontsize=10, fontweight='bold')
            ax.set_yticks([]) # 隐藏 Y 轴
            ax.set_xlim(-0.2, len(cols_to_plot) - 0.8)
            ax.set_ylim(-0.05, 1.05)
            
            # 标题
            if highlight:
                title_str = f"Parallel Coordinates (Highlighting Top {highlight.get('fraction',0.1):.0%} {highlight.get('metric')})"
            else:
                title_str = "Parallel Coordinates (Normalized Range)"
            ax.set_title(title_str, fontsize=16, pad=20)
            
            # 竖向网格线 (这就是坐标轴)
            for x in x_coords:
                ax.axvline(x, color='black', alpha=0.1, linewidth=1)
                
            plt.tight_layout()
            plt.show()

        return plot_df

    def _smart_format(self, col_name: str, val: float) -> str:
        """
        智能格式化数值单位
        """
        col_lower = col_name.lower()
        val = float(val)

        if "linkspeed" in col_lower or "bandwidth" in col_lower:
            if val >= 1000:
                return f"{val/1000:.0f}Gbps"
            return f"{val:.0f}Mbps"

        # 2. 流量/大小: Bytes -> MB/KB
        if any(x in col_lower for x in ["flowsize", "bytes", "limit"]):
            # 简单处理：如果是 0
            if val == 0: return "0"
            for unit in ['B', 'KB', 'MB', 'GB']:
                if val < 1000: 
                    # 如果是整数，不显示小数
                    if val.is_integer(): return f"{int(val)}{unit}"
                    return f"{val:.1f}{unit}"
                val /= 1000
            return f"{val:.1f}TB"

        # 3. 队列/Buffer相关的 BDP factor 系数 (无单位)
        if any(x in col_lower for x in ["queue", "ecn", "bdp"]):
             if val.is_integer():
                return str(int(val))
             return f"{val:.2g}"

        # 4. 时间: us (默认) -> ms
        if any(x in col_lower for x in ["fct", "latency", "rtt", "delay"]):
            if val >= 1000:
                return f"{val/1000:.1f}ms"
            return f"{val:.0f}us"
            
        # 4. 默认保留3位有效数字
        if val.is_integer():
            return str(int(val))
        return f"{val:.2g}"

    def plot_scatter_matrix(
        self,
        columns: List[str],
        filters: Dict = None,
        sample: Optional[int] = 500,
    ):
        """
        散点矩阵：快速观察若干参数/指标之间的相关性。
        - columns: 需要展示的列（因子 + 指标）
        - filters: 精确筛选条件
        - sample: 下采样行数（避免点过多），None 表示不过滤
        """
        df = self.batch.get_summary_df([])
        if df.empty:
            print("[!] Summary DataFrame is empty.")
            return

        if filters:
            for k, v in filters.items():
                df = df[df[k] == v]

        cols = [c for c in columns if c in df.columns]
        if len(cols) == 0:
            print("[!] No valid columns for scatter matrix.")
            return

        df = df[cols].dropna()
        if df.empty:
            print("[!] No data for scatter matrix after dropping NaNs.")
            return

        if sample is not None and len(df) > sample:
            df = df.sample(sample, random_state=0)

        from pandas.plotting import scatter_matrix
        import matplotlib.pyplot as plt

        axs = scatter_matrix(
            df, figsize=(3 * len(cols), 3 * len(cols)), diagonal="kde"
        )
        for ax_row in axs:
            for ax in ax_row:
                ax.grid(True, ls="--", alpha=0.2)
        plt.tight_layout()
        plt.show()
        return axs

    def plot_response_surface(
        self,
        x: str,
        y: str,
        z: str,
        filters: Dict = None,
        title: str = None,
        cmap: str = "viridis",
        levels: int = 15,
        scatter_alpha: float = 0.6,
        show_points: bool = True,
    ):
        """
        响应面图 (Response Surface): 使用三角剖分 (Triangulation) 绘制等高线填充图。
        适用于 LHS 等非网格化数据，展示两个连续因子 (x, y) 对响应 (z) 的联合影响。

        :param x: X轴因子名 (e.g. 'linkspeed')
        :param y: Y轴因子名 (e.g. 'flowsize')
        :param z: 响应指标名 (e.g. 'max_fct')
        :param filters: 筛选条件
        :param show_points: 是否叠加显示原始采样点
        """
        df = self.batch.get_summary_df([z])
        if df.empty:
            print("[!] Summary DataFrame is empty.")
            return

        if filters:
            for k, v in filters.items():
                df = df[df[k] == v]

        # 确保数据列存在且为数值型
        cols = [x, y, z]
        if not all(c in df.columns for c in cols):
            missing = [c for c in cols if c not in df.columns]
            print(f"[!] Missing columns: {missing}")
            return

        # 剔除 NaN
        plot_df = df[cols].dropna()
        if plot_df.empty:
            print("[!] No valid data for response surface.")
            return

        X = plot_df[x].values
        Y = plot_df[y].values
        Z = plot_df[z].values

        import matplotlib.pyplot as plt
        import matplotlib.tri as tri
        from matplotlib.ticker import FuncFormatter

        # 使用更现代的风格
        with plt.style.context("seaborn-v0_8-white"):
            fig, ax = plt.subplots(figsize=(10, 8))

            try:
                # 1. 创建三角剖分并绘制等高填充图
                # 如果点共线或太少，Triangulation 会抛出错误，这里进行捕获
                triang = tri.Triangulation(X, Y)
                cntr = ax.tricontourf(triang, Z, levels=levels, cmap=cmap)
            except Exception as e:
                # 降级方案：如果是共线或者维度不足，直接画散点图
                print(f"[Warn] Triangulation failed ({e}), falling back to Scatter Plot.")
                sc = ax.scatter(X, Y, c=Z, cmap=cmap, s=100, edgecolors="k")
                plt.colorbar(sc, ax=ax, label=z)
                ax.set_title(f"{title or z} (Scatter Fallback)")
                ax.set_xlabel(x)
                ax.set_ylabel(y)
                plt.close(fig) # Close the contour fig
                return None # The caller should handle this or we just show scatter

            # 使用 tricontourf 填充颜色
            # cntr 已在 try 块中定义
            
            # 添加颜色条
            cbar = fig.colorbar(cntr, ax=ax, aspect=30, pad=0.02)
            
            # Smart Format Z Axis (Colorbar)
            # 注意: colorbar 的 axis 取决于方向，默认垂直则用 yaxis
            def fmt_func_z(val, pos, col=z): return self._smart_format(col, val)
            cbar.ax.yaxis.set_major_formatter(FuncFormatter(fmt_func_z))
            
            # 既然刻度自带单位，Label 就只需变量名
            cbar.set_label(f"{z}", rotation=270, labelpad=20, fontsize=12)

            # 2. (可选) 绘制等高线线条，增强可读性
            try:
                ax.tricontour(triang, Z, levels=levels, colors='white', linewidths=0.5, alpha=0.3)
            except Exception:
                pass # 忽略轮廓线错误

            # 3. (可选) 叠加原始采样点
            if show_points:
                ax.scatter(X, Y, edgecolors="black", facecolors="none", s=20, lw=0.5, alpha=scatter_alpha)

            # 4. 格式化与标签
            
            # Smart Format X/Y Axis
            def fmt_func_x(val, pos, col=x): return self._smart_format(col, val)
            def fmt_func_y(val, pos, col=y): return self._smart_format(col, val)
            
            ax.xaxis.set_major_formatter(FuncFormatter(fmt_func_x))
            ax.yaxis.set_major_formatter(FuncFormatter(fmt_func_y))

            # 既然刻度自带单位，Label 就只需变量名，不再画蛇添足
            ax.set_xlabel(x, fontsize=12, fontweight='bold')
            ax.set_ylabel(y, fontsize=12, fontweight='bold')
            
            if title:
                ax.set_title(title, fontsize=14, pad=15)
            else:
                ax.set_title(f"Response Surface\n{z} vs ({x}, {y})", fontsize=15, fontweight='bold')

            plt.tight_layout()
            plt.show()

    def plot_auto_interactions(self, metrics: List[str] = None):
        """
        [新增] 智能交互分析：自动检测并可视化领域内已知的关键参数对。
        目前的通用扫描往往忽略了参数间的物理耦合（如 ECN 双阈值）。
        此函数会自动寻找已知的耦合参数，如果它们都在变化，则绘制响应面图。
        """
        varying = self.batch.get_varying_params()
        target_metric = metrics[0] if metrics else "p99_fct"
        
        # 1. ECN 阈值交互 (ECN Low vs High)
        if "ecn_low" in varying and "ecn_high" in varying:
            print(f"[Auto-Analysis] Detected ECN Dual-Thresholds. Plotting Interaction for {target_metric}...")
            self.plot_response_surface(
                x="ecn_low",
                y="ecn_high",
                z=target_metric,
                title=f"ECN Interaction: {target_metric} vs Thresholds",
                cmap="RdYlGn_r" # 红=差(High FCT)，绿=好
            )
            
        # 2. 负载 vs 缓冲区 (Conns vs Queue Size) - 只有当两者都变时才画
        if "conns" in varying and "queue_size_bdp_factor" in varying:
            print(f"[Auto-Analysis] Detected Load vs Buffer. Plotting Interaction for {target_metric}...")
            self.plot_response_surface(
                x="conns",
                y="queue_size_bdp_factor",
                z=target_metric,
                title=f"Buffer Efficacy: {target_metric} vs Load & Size",
                cmap="viridis"
            )

        # 3. 带宽延迟积相关 (Linkspeed vs Hop Latency)
        if "linkspeed" in varying and "hop_latency" in varying:
             print(f"[Auto-Analysis] Detected BDP Factors. Plotting Interaction for {target_metric}...")
             self.plot_response_surface(
                x="linkspeed",
                y="hop_latency",
                z=target_metric,
                title=f"BDP Impact: {target_metric} vs Bandwidth & Latency",
                cmap="viridis"
             )

    # ==========================================
    # 8. Smart Analysis Capabilities (LHS-Native)
    # ==========================================

    def analyze_feature_importance(
        self, 
        metric: str = "p99_fct", 
        factors: Optional[List[str]] = None,
        top_n: int = 10
    ):
        """
        [NEW] 使用随机森林 (Random Forest) 定量分析各因子对目标指标的影响权重。
        这是 LHS 分析的核心：在高维随机空间中找出那个"最重要"的参数。
        """
        try:
            from sklearn.ensemble import RandomForestRegressor
            from sklearn.preprocessing import LabelEncoder
        except ImportError:
            print("[Error] scikit-learn is required for feature importance analysis.")
            return

        # 1. 准备数据
        if factors is None:
            factors = self.batch.get_varying_params()
        
        df = self.batch.get_summary_df([metric])
        if df.empty:
            print("[!] No data available.")
            return

        # 清洗数据：去除无效值
        df_clean = df.dropna(subset=[metric] + factors)
        if len(df_clean) < 10:
            print("Not enough data points for Random Forest analysis.")
            return

        X = df_clean[factors].copy()
        y = df_clean[metric]

        # 2. 预处理：处理分类变量
        encoders = {}
        for col in X.columns:
            # 兼容性处理: object 类型或 categorical 类型都视为分类变量
            if X[col].dtype == 'object' or str(X[col].dtype) == 'category':
                le = LabelEncoder()
                # 转换为字符串以处理潜在的混合类型
                X[col] = le.fit_transform(X[col].astype(str))
                encoders[col] = le

        # 3. 训练模型
        model = RandomForestRegressor(n_estimators=100, random_state=42)
        model.fit(X, y)

        # 4. 提取权重
        importances = model.feature_importances_
        feature_imp = pd.DataFrame({
            'Factor': factors,
            'Importance': importances
        }).sort_values('Importance', ascending=False)

        # 5. 可视化
        import matplotlib.pyplot as plt
        import seaborn as sns
        
        plt.figure(figsize=(10, 6))
        sns.barplot(x="Importance", y="Factor", data=feature_imp.head(top_n), palette="viridis")
        plt.title(f"What Matters Most? (Impact on {metric})")
        plt.xlabel("Relative Importance (Random Forest)")
        plt.tight_layout()
        plt.show()

        # 6. 输出结论
        print("\n=== Feature Importance Ranking (Top 5) ===")
        for index, row in feature_imp.head(5).iterrows():
            print(f"{row['Factor']:<20}: {row['Importance']:.4f}")
        
        if not feature_imp.empty:
            top_factor = feature_imp.iloc[0]['Factor']
            print(f"\n[Insight] The dominant factor affecting {metric} is '{top_factor}'.")
            print(f"You should focus your analysis on '{top_factor}' (e.g. plot main effects for this).")

    def find_best_worst_configs(self, metric: str = "p99_fct", n: int = 3, maximize: bool = False):
        """
        [NEW] 极值扫描：自动全表扫描，找出表现最好和最差的配置。
        maximize=False (默认) 意味着越小越好 (如 latency)。
        """
        df = self.batch.get_summary_df([metric])
        if df.empty: return

        # 排序: ascending=True means smallest first.
        # If maximize=False (Low is Good): Smallest is Best (Head), Largest is Worst (Tail).
        # If maximize=True (High is Good): Largest is Best (Tail), Smallest is Worst (Head).
        # 让 best 始终在 head，我们需要根据 maximize 调整 ascending
        
        # maximize=True (High Good) -> use ascending=False -> Head is Large (Best)
        # maximize=False (Low Good) -> use ascending=True -> Head is Small (Best)
        
        sorted_df = df.sort_values(metric, ascending=not maximize)
        
        best = sorted_df.head(n)
        worst = sorted_df.tail(n)
        
        # 如果是 tail 取出的，顺序是反的（从小到大），倒序一下让最差的排前面
        try:
            worst = worst.iloc[::-1]
        except:
            pass

        print(f"\n=== Best {n} Configs ({metric} {'High' if maximize else 'Low'} is Better) ===")
        self._print_case_table(best, metric)

        print(f"\n=== Worst {n} Configs (Sentinel Cases) ===")
        self._print_case_table(worst, metric)

    def _print_case_table(self, df: pd.DataFrame, metric: str):
        # 挑选关键列显示
        factors = self.batch.get_varying_params()
        # 确保列存在
        valid_factors = [c for c in factors if c in df.columns]
        cols = ["_uid", metric] + valid_factors
        
        if df.empty:
            print("(No data)")
            return

        # 截断太长的 uid
        view = df[cols].copy()
        
        def truncate_uid(x):
            s = str(x)
            # 取路径最后两段作为简略 ID
            parts = s.split("/")
            return "/".join(parts[-2:]) if len(parts) > 1 else s

        view["_uid"] = view["_uid"].apply(truncate_uid)
        try:
            print(view.to_markdown(index=False))
        except ImportError:
            # Fallback if tabulate is not installed
            print(view.to_string(index=False))

    def diagnose_failure_modes(self):
        """
        [NEW] 专家诊断：基于规则匹配常见网络故障模式。
        规则来源：docs/LLM推理网络优化指南.md
        """
        # 需要的指标
        metrics = ["p99_fct", "max_fct", "median_fct", "drop_count", "util_avg"]
        df = self.batch.get_summary_df(metrics)
        if df.empty: return

        print("\n=== Domain Expert Diagnostics ===")
        
        # 预先检查列是否存在，不存在则填充 NaN 或 0
        for m in metrics:
            if m not in df.columns:
                df[m] = 0

        # 1. 缓冲区膨胀检测 (Bufferbloat)
        # 规则：P99 很高，但丢包很少 (延迟主要来自排队)
        # 阈值定义：P99 > 3 * Median (长尾显著) 且 drop_count < 10 (几乎无丢包)
        # 且 P99 绝对值要够大 (例如 > 200us) 避免噪音
        bloated = df[ 
            (df["p99_fct"] > 3 * df["median_fct"]) & 
            (df["drop_count"] < 10) & 
            (df["p99_fct"] > 100) 
        ]
        
        if not bloated.empty:
            print(f"\n[!] Bufferbloat Detected in {len(bloated)} experiments.")
            print("    Signature: High Tail Latency + Low Drops")
            print("    Diagnosis: Packets are queuing up. CC is too passive.")
            print("    Action: Reduce 'queue_size' or 'ecn_high'.")
            print("    Example Cases:")
            self._print_case_table(bloated.head(3), "p99_fct")
        else:
            print("[Pass] No obvious Bufferbloat detected.")

        # 2. 拥塞崩溃检测 (Incast Collapse)
        # 规则：丢包极多
        collapsed = df[ (df["drop_count"] > 1000) ]
        if not collapsed.empty:
            print(f"\n[!] Congestion Collapse Detected in {len(collapsed)} experiments.")
            print("    Signature: Massive Packet Drops (>1000)")
            print("    Diagnosis: Buffer overflow (Micro-burst). CC is too slow.")
            print("    Action: Increase 'queue_size', Enable PFC, or use Lower ECN.")
            print("    Example Cases:")
            self._print_case_table(collapsed.head(3), "drop_count")
        else:
            print("[Pass] No Congestion Collapse detected.")

        # 3. Hash 冲突检测 (Straggler)
        # 规则：Max 远大于 P99 (个别流极慢)，但整体 P99 正常 (P99 < 2 * Median)
        stragglers = df[ 
            (df["max_fct"] > 2 * df["p99_fct"]) & 
            (df["p99_fct"] < 2 * df["median_fct"]) 
        ]
        
        if not stragglers.empty:
            print(f"\n[!] Hash Collision / Stragglers Detected in {len(stragglers)} experiments.")
            print("    Signature: Max FCT >> P99 FCT (while P99 is normal)")
            print("    Diagnosis: ECMP Hash collision on single paths.")
            print("    Action: Use Adaptive Routing (e.g. reactive_ecn) or Packet Spraying.")
            print("    Example Cases:")
            self._print_case_table(stragglers.head(3), "max_fct")
        else:
            print("[Pass] No pure Hash Collision/Stragglers detected.")
