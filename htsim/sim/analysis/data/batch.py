import pandas as pd
import matplotlib.pyplot as plt
import matplotlib.ticker as ticker
import seaborn as sns
import numpy as np
from pathlib import Path
from typing import List, Dict, Union, Optional, Any, Callable

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
