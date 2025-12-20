import json
import yaml
import pandas as pd
import matplotlib.pyplot as plt
import seaborn as sns
from pathlib import Path
from typing import Union, List, Optional, Dict

# 导入项目基础路径和核心逻辑
from ..runner import PROJECT_DIR
from ..config.experiment import expand_params_tree, identify_variable_keys, deep_merge
from .fileinfo import ExperimentResult


class BatchVisualizer:
    """
    现代化批量实验可视化器。
    集成并优化了原本分散的 plot_*.py 逻辑。
    """

    def __init__(self, batch: "BatchResult"):
        self.batch = batch
        self.default_style = {"figsize": (10, 6), "grid_alpha": 0.3, "marker": "o"}

    def plot_fct_trend(
        self,
        x: str,
        hue: str = "strat",
        y_metric: str = "max_fct",
        title: Optional[str] = None,
    ):
        """
        绘制趋势图。自动处理多随机种子的均值与置信区间阴影。
        """
        df = self.batch.get_summary_df([y_metric])
        if df.empty:
            return

        plt.figure(figsize=self.default_style["figsize"])
        # 使用 lineplot 自动聚合相同 x 的不同 Seed 数据，绘制阴影面积
        ax = sns.lineplot(
            data=df,
            x=x,
            y=y_metric,
            hue=hue,
            marker=self.default_style["marker"],
            err_style="band",
        )

        ax.set_title(title or f"{y_metric} vs {x} (Grouped by {hue})")
        ax.set_ylabel(f"{y_metric} (us)")
        plt.grid(True, alpha=self.default_style["grid_alpha"])
        plt.show()

    def plot_fct_cdf(self, hue: str = "strat", filters: dict = None):
        """
        绘制全量流的 FCT CDF 对比图。
        """
        all_flows = []
        for uid, res in self.batch.experiments.items():
            if not res.is_success:
                continue

            # 应用过滤逻辑
            if filters and not all(res.params.get(k) == v for k, v in filters.items()):
                continue

            df = res.flow_df.copy()  # 触发解析
            for k, v in res.params.items():
                df[k] = v
            df["_exp_id"] = uid
            all_flows.append(df)

        if not all_flows:
            return
        combined = pd.concat(all_flows)

        plt.figure(figsize=self.default_style["figsize"])
        sns.ecdfplot(data=combined, x="fct_ns", hue=hue)
        plt.xscale("log")  # 遵循旧脚本习惯
        plt.title(f"FCT CDF Comparison Grouped by {hue}")
        plt.xlabel("Flow Completion Time (ns)")
        plt.grid(True, alpha=self.default_style["grid_alpha"])
        plt.show()

    def plot_algo_bars(self, x: str = "strat", y: str = "max_fct"):
        """
        绘制算法对比柱状图。
        """
        df = self.batch.get_summary_df([y])
        if df.empty:
            return

        plt.figure(figsize=self.default_style["figsize"])
        sns.barplot(data=df, x=x, y=y, capsize=0.1)
        plt.title(f"{y} Comparison by Algorithm")
        plt.ylabel(f"{y} (us)")
        plt.xticks(rotation=20)
        plt.show()


class BatchResult:
    def __init__(self, sources: Optional[List[Union[str, Path]]] = None):
        self.experiments: Dict[str, ExperimentResult] = {}
        self.experiments_dir = PROJECT_DIR / "experiments"
        self.results_base_dir = PROJECT_DIR / "results"

        if sources:
            for source in sources:
                self.add_source(source)

    @property
    def viz(self):
        """[Lazy Loading] 可视化组件入口"""
        return BatchVisualizer(self)

    def add_source(self, source_path: Union[str, Path], filters: dict = None):
        path = Path(source_path).resolve()
        if path.is_file() and path.suffix in [".yaml", ".yml"]:
            self._add_from_yaml(path, filters)
        elif path.is_dir():
            if (path / "status.yaml").exists():
                self._register_experiment(path, label=path.parent.name)
            else:
                self._add_from_large_dir(path)

    def _add_from_yaml(self, yaml_path: Path, filters: dict = None):
        """
        [完全补全版] 复刻 experiment.py 的命名与路径推断逻辑。
        """
        try:
            relative_path = yaml_path.relative_to(self.experiments_dir)
            output_dir_name = relative_path.with_suffix("").as_posix()
            exp_root = self.results_base_dir / output_dir_name
        except ValueError:
            print(f"[!] Error: YAML {yaml_path} must be inside {self.experiments_dir}")
            return

        if not exp_root.exists():
            return

        with open(yaml_path, "r") as f:
            config = yaml.safe_load(f)

        # 逻辑对齐 experiment.py
        common = config.get("common", {})
        common_traffic = common.get("traffic", {})
        common_sim = common.get("simulation", {})
        common_flat = {
            k: v for k, v in common.items() if k not in ("traffic", "simulation")
        }
        experiments = config.get("experiments", [])

        # 1. 预扫描识别变量键
        all_exp_variants = []
        for exp_idx, exp in enumerate(experiments):
            exp_name = exp.get("name", f"exp_{exp_idx}")
            base_traffic = deep_merge(common_traffic, exp.get("traffic", {}))
            base_sim = deep_merge(common_sim, exp.get("simulation", {}))
            for t_var in expand_params_tree(base_traffic):
                for s_var in expand_params_tree(base_sim):
                    all_exp_variants.append(
                        {**common_flat, **t_var, **s_var, "name": exp_name}
                    )

        variable_keys = identify_variable_keys(all_exp_variants)

        # 2. 精准匹配目录
        for exp_idx, exp in enumerate(experiments):
            exp_name = exp.get("name", f"exp_{exp_idx}")
            base_traffic = deep_merge(common_traffic, exp.get("traffic", {}))
            base_sim = deep_merge(common_sim, exp.get("simulation", {}))

            for t_var in expand_params_tree(base_traffic):
                for s_var in expand_params_tree(base_sim):
                    current_params = {**common_flat, **t_var, **s_var}

                    # 应用 filters 筛选
                    if filters and not all(
                        current_params.get(k) == v for k, v in filters.items()
                    ):
                        continue

                    label_parts = []
                    for key in variable_keys:
                        if key != "name":
                            val = current_params.get(key)
                            if val is not None and not isinstance(val, dict):
                                label_parts.append(f"{key}{val}")

                    label_suffix = exp_name + "_".join(label_parts) or exp_name
                    small_path = exp_root / label_suffix

                    if small_path.exists():
                        self._register_experiment(small_path, label=yaml_path.stem)

    def _add_from_large_dir(self, large_dir: Path, label_prefix: str = None):
        label = label_prefix or large_dir.name
        for status_file in large_dir.glob("**/status.yaml"):
            self._register_experiment(status_file.parent, label=label)

    def _register_experiment(self, path: Path, label: str):
        unique_id = f"{label}/{path.name}"
        self.experiments[unique_id] = ExperimentResult(path)

    def get_summary_df(self, metrics: List[str]) -> pd.DataFrame:
        """[Lazy-Save] 聚合摘要数据"""
        rows = []
        for uid, res in self.experiments.items():
            if not res.is_success:
                continue
            row = {**res.params, "_batch_id": uid, "_path": str(res.base_dir)}
            for m in metrics:
                row[m] = res.get_cached_metric(m)
            rows.append(row)
        return pd.DataFrame(rows)

    def get_stats_df(self, groupby: List[str], metrics: List[str]) -> pd.DataFrame:
        """自动计算分组统计量 (均值、P99、最大值等)"""
        df = self.get_summary_df(metrics)
        if df.empty:
            return df
        agg_map = {
            m: ["mean", "max", "std", lambda x: x.quantile(0.99)] for m in metrics
        }
        stats = df.groupby(groupby).agg(agg_map)
        stats.columns = [
            f"{m}_{suffix}" for m in metrics for suffix in ["avg", "max", "std", "p99"]
        ]
        return stats.reset_index()

    def find_bad_seeds(
        self, metric: str = "max_fct", threshold: float = 500.0
    ) -> Dict[str, ExperimentResult]:
        """快速检索异常实验"""
        return {
            uid: res
            for uid, res in self.experiments.items()
            if res.is_success and (res.get_cached_metric(metric) or 0) > threshold
        }

    def clear_cache(self):
        """清除 summary.json 缓存"""
        for res in self.experiments.values():
            p = res.base_dir / "summary.json"
            if p.exists():
                p.unlink()
