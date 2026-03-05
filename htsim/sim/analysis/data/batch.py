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

        self.results_base_dir = (PROJECT_DIR / "results").resolve()
        self.experiments_dir = (PROJECT_DIR / "experiments").resolve()

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
            if predicate:
                import inspect
                try:
                    sig = inspect.signature(predicate)
                    if len(sig.parameters) == 1:
                        if not predicate(res):
                            continue
                    else:
                        if not predicate(res, tags):
                            continue
                except ValueError: # handle cases where signature can't be inspected (e.g. some builtins), fallback to 2 args
                     if not predicate(res, tags):
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

    def get_experiment(self, index: int = 0, **params) -> Optional[ExperimentResult]:
        """
        [Convenience] 获取单个实验结果对象。
        :param index: 如果匹配到多个，返回第 index 个 (默认 0)
        :param params: 筛选条件 (如 randseed=4)
        """
        # 使用 filter 进行筛选
        subset = self.filter(**params)
        results = [entry["result"] for entry in subset.experiments.values()]
        
        if not results:
            print(f"[!] No experiment found matching {params}")
            return None
        if index >= len(results):
            print(f"[!] Index {index} out of range (found {len(results)})")
            return None
        return results[index]

    def get_best_experiment(self, metric: str = "p99_fct", maximize: bool = False) -> Optional[ExperimentResult]:
        """
        [Convenience] 获取在该指标上表现最好的实验。
        :param maximize: False (默认) 意味着越小越好 (如 latency)。True 意味着越大越好 (如 goodput)。
        """
        df = self.get_summary_df([metric])
        if df.empty: return None
        
        # Best = Head if ascending=True (Low is Good)
        # Best = Head if ascending=False (High is Good)
        # So we just sort and take head(1) based on maximize direction
        sorted_df = df.sort_values(metric, ascending=not maximize)
        if sorted_df.empty: return None
        
        best_uid = sorted_df.iloc[0]["_uid"]
        return self.experiments.get(best_uid, {}).get("result")

    def get_worst_experiment(self, metric: str = "p99_fct", maximize: bool = False) -> Optional[ExperimentResult]:
        """
        [Convenience] 获取在该指标上表现最差的实验 (通常用于故障根因分析)。
        """
        df = self.get_summary_df([metric])
        if df.empty: return None
        
        # Worst = Tail if Best is Head
        sorted_df = df.sort_values(metric, ascending=not maximize)
        if sorted_df.empty: return None
        
        worst_uid = sorted_df.iloc[-1]["_uid"]
        return self.experiments.get(worst_uid, {}).get("result")

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

    def help(self) -> Union[pd.DataFrame, "pd.io.formats.style.Styler"]:
        """
        [Interactive Guide] 显示 BatchResult 的标准工作流指南。
        """
        guides = [
            {
                "Phase": "1. 🚛 加载数据 (Load)",
                "Action": "添加实验源",
                "Method": "batch.add_source(path, tags={...})",
                "Usage": "batch.add_source('experiments/test.yaml', tags={'version': 'v1'})",
                "Tip": "支持 YAML 文件、结果目录或 glob 路径列表"
            },
            {
                "Phase": "2. 🔍 筛选 (Filter)",
                "Action": "高级筛选 (支持 Lambda)",
                "Method": "batch.filter(col=val, col=lambda x...)",
                "Usage": "subset = batch.filter(conns=[64, 128], linkspeed=lambda x: x > 400000000)",
                "Tip": "返回 BatchResult 子集，支持链式调用: batch.filter(...).suggest()"
            },
            {
                "Phase": "3. 🤖 智能分析 (Auto)",
                "Action": "获取分析建议",
                "Method": "batch.suggest()",
                "Usage": "batch.suggest()",
                "Tip": "自动检测 LHS/对比/单变量场景，生成可执行代码"
            },
            {
                "Phase": "4. ⛏️ 深度下钻 (Deep Dive)",
                "Action": "获取极值实验",
                "Method": "batch.get_worst_experiment()",
                "Usage": "exp = batch.get_worst_experiment(metric='p99_fct')",
                "Tip": "快速定位表现最差的实验 (Crash Case) 进行根因分析"
            },
            {
                "Phase": "5. 📑 导出复现 (Reproduce)",
                "Action": "生成复现配置",
                "Method": "exp.export_config()",
                "Usage": "path = exp.export_config()",
                "Tip": "生成用于复现的 YAML 文件 (包含原的所有参数)"
            }
        ]
        
        df = pd.DataFrame(guides)
        
        # 尝试使用 Styler 优化显示 (需 jinja2)，否则回退到普通 DataFrame
        try:
            return df.style.set_properties(**{
                'text-align': 'left',
                'white-space': 'pre-wrap',
                'font-family': 'monospace'
            }).hide(axis="index")
        except AttributeError:
             pd.set_option('display.max_colwidth', None)
             return df

    def suggest(self) -> Union[pd.DataFrame, "pd.io.formats.style.Styler"]:
        """
        [Smart Assistant] 智能分析建议。
        扫描当前实验数据的维度（变化参数），根据因子数量推荐最合适的绘图与分析方法。
        直接返回包含可执行代码的 DataFrame (Styler)，复制即可运行。
        """
        # 1. 扫描变量因子及其基数 (Cardinality)
        factors = self.get_varying_params()
        
        # 获取简单的 summary df 用于判断数据类型 (Cardinality)
        # 仅加载少量列以加速
        try:
            sample_df = self.get_summary_df(metrics=[])
            factor_counts = {f: sample_df[f].nunique() for f in factors if f in sample_df.columns}
        except Exception:
            factor_counts = {f: 10 for f in factors} # Fallback

        # 2. 自动检测可用指标 (基于第一个实验的 logs)
        available_metrics = []
        metrics_groups = {"FCT": [], "Drop": [], "Utilization": [], "Combined": []}
        
        if self.experiments:
            first_exp = next(iter(self.experiments.values()))["result"]
            logs = first_exp.enabled_logs
            
            # 动态构建指标组
            if "flow_events" in logs:
                metrics_groups["FCT"] = ["p99_fct", "median_fct", "max_fct"]
                available_metrics.extend(["p99_fct", "median_fct", "max_fct", "avg_fct", "max_slowdown"])
                
            if "queue_usage" in logs:
                metrics_groups["Drop"] = ["max_drop_rate"]
                metrics_groups["Utilization"] = ["avg_utilization", "max_q_depth"]
                available_metrics.extend(["max_drop_rate", "avg_utilization", "max_q_depth"])
                
            if "cwnd" in logs:
                available_metrics.extend(["cwnd_fairness"])

        # 核心指标默选 (Primary Metric)
        primary_metric = metrics_groups["FCT"][0] if metrics_groups["FCT"] else "p99_fct"
        # 丢包指标 (Secondary Metric) - 只有存在时才设置
        drop_metric = metrics_groups["Drop"][0] if metrics_groups["Drop"] else None
        
        # 组合建议 (FCT Group) - 用于展示多维数据
        fct_group_str = str(metrics_groups["FCT"]) if metrics_groups["FCT"] else "['p99_fct', 'max_fct']"
        
        suggestions = []
        
        # 基础信息：展示可用指标
        suggestions.append({
            "Scenario": "📊 可用指标检测",
            "Detected Factors": f"Logs: {list(logs) if self.experiments else 'None'}",
            "Recommended Action": "查看完整指标列表",
            "Code": f"# Available Metrics: {available_metrics}"
        })
        
        # 基础信息：展示变量
        suggestions.append({
            "Scenario": "🔍 当前实验概览",
            "Detected Factors": f"{len(factors)} 个变量: {factors}",
            "Recommended Action": "查看变量列表",
            "Code": "batch.get_varying_params()"
        })

        if len(factors) == 0:
            suggestions.append({
                "Scenario": "📉 单一场景分析",
                "Detected Factors": "无 (固定场景)",
                "Recommended Action": "查看 FCT 分布 vs SLO",
                "Code": f"batch.viz.plot_distribution(y='{primary_metric}', kind='box')\n# Ref Line (SLO): batch.viz.plot_pivot(x='version', y='{primary_metric}', ref_line=200)"
            })

        elif len(factors) == 1:
            f = factors[0]
            suggestions.append({
                "Scenario": "📈 单因子趋势分析 (Line)",
                "Detected Factors": f"1 个因子 [{f}]",
                "Recommended Action": "绘制趋势图 + SLO 参考线",
                "Code": f"batch.viz.plot_pivot(x='{f}', y='{primary_metric}', kind='line', ref_line=500)"
            })
            
            # [Optimization] 如果有 FCT 指标，使用专业的 statistical summary (Hue=None)
            if metrics_groups["FCT"]:
                suggestions.append({
                    "Scenario": "📊 综合性能画像 (Scientific)",
                    "Detected Factors": f"1 个因子 [{f}] + FCT Metrics",
                    "Recommended Action": "多指标统计趋势图 (P99/Median/Max)",
                    "Code": f"batch.viz.plot_statistical_summary(x='{f}', metrics={fct_group_str}, hue=None, title='{f} Impact on FCT')"
                })
            else:
                # Fallback for non-FCT metrics
                suggestions.append({
                    "Scenario": "📊 综合性能画像 (Generic)",
                    "Detected Factors": f"1 个因子 [{f}]",
                    "Recommended Action": "多指标透视",
                    "Code": f"batch.viz.plot_pivot(x='{f}', y={fct_group_str}, title='Performance Overview')"
                })
            if drop_metric:
                suggestions.append({
                    "Scenario": "⚖️ 权衡分析 (Dual Axis)",
                    "Detected Factors": "FCT vs Drop",
                    "Recommended Action": "绘制双轴权衡图 (Line + Drop)",
                    "Code": f"batch.viz.plot_pivot(x='{f}', y='{primary_metric}', y2='{drop_metric}')"
                })

        elif len(factors) == 2:
            f1, f2 = factors[0], factors[1]
            
            # 判断是否有类别变量 (Cardinality < 5)，适合做 Hue 对比
            cat_factor = None
            main_factor = f1
            if factor_counts.get(f2, 100) < 5:
                cat_factor = f2
                main_factor = f1
            elif factor_counts.get(f1, 100) < 5:
                cat_factor = f1
                main_factor = f2
            
            suggestions.append({
                "Scenario": "🔥 双因子交互 (Heatmap)",
                "Detected Factors": f"2 个因子 [{f1}, {f2}]",
                "Recommended Action": "绘制热力图 (Phase Space)",
                "Code": f"batch.viz.plot_pivot(x='{f1}', hue='{f2}', y='{primary_metric}', kind='heatmap')"
            })

            # [Optimization] 科研级多指标对比 (X vs Hue)
            if metrics_groups["FCT"]:
                 suggestions.append({
                    "Scenario": "📊 综合趋势对比 (Scientific)",
                    "Detected Factors": f"X=[{f1}], Hue=[{f2}]",
                    "Recommended Action": "多指标统计趋势图 (P99/Median/Max)",
                    "Code": f"batch.viz.plot_statistical_summary(x='{f1}', hue='{f2}', metrics={fct_group_str}, title='{f1} vs {f2} (FCT Stats)')"
                })
            
            if cat_factor:
                 suggestions.append({
                    "Scenario": "📊 分组对比 (Pivot Facet)",
                    "Detected Factors": f"类别变量 [{cat_factor}]",
                    "Recommended Action": "透视对比 (Facet Grid)",
                    "Code": f"batch.viz.plot_pivot(x='{main_factor}', col='{cat_factor}', y={fct_group_str})"
                })
            
            # 即使有 Hue，Trade-off 依然很有价值 (Aggregated View)
            if drop_metric:
                suggestions.append({
                    "Scenario": "⚖️ 复杂权衡 (Dual Axis Facet)",
                    "Detected Factors": "FCT vs Drop",
                    "Recommended Action": "分面双轴分析",
                    "Code": f"batch.viz.plot_pivot(x='{f1}', y='{primary_metric}', y2='{drop_metric}', col='{f2}')"
                })

        elif len(factors) >= 3:
            # 只有当 FCT 指标可用时才建议使用 FCT
            target_metric_list = fct_group_str if metrics_groups["FCT"] else f"['{primary_metric}']"
            
            # A. 优先推荐：平行坐标图 (hue 增强)
            suggestions.append({
                "Scenario": "🕸️ 高维空间总览",
                "Detected Factors": f"{len(factors)} 个因子 (高维)",
                "Recommended Action": "平行坐标图 (Parallel Coordinates)",
                "Code": f"batch.viz.plot_parallel_coordinates(metrics={target_metric_list}, factors={factors}, hue='{factors[-1] if len(factors)>0 else None}')"
            })
            
            # B. 关键特征识别
            suggestions.append({
                "Scenario": "🌲 关键特征识别",
                "Detected Factors": "LHS/随机采样",
                "Recommended Action": "随机森林特征重要性排序",
                "Code": f"batch.viz.analyze_feature_importance('{primary_metric}')"
            })

            # C. 响应曲面分析 (Top 2 Factors) - 仅当 Top 2 为数值时建议
            f1, f2 = factors[0], factors[1]
            if pd.api.types.is_numeric_dtype(sample_df[f1]) and pd.api.types.is_numeric_dtype(sample_df[f2]):
                 suggestions.append({
                    "Scenario": "🏔️ 响应曲面分析 (Top 2 Factors)",
                    "Detected Factors": "复杂非线性关系 (数值型)",
                    "Recommended Action": "绘制响应曲面 (Response Surface)",
                    "Code": f"batch.viz.plot_response_surface(x='{f1}', y='{f2}', z='{primary_metric}')"
                })
            
            # D. [新增] 分面统计分析 (针对 ECN 等分类变量)
            # 如果存在至少3个变量，且其中有适合做 col 的 (cardinality < 10)
            facet_col = None
            for f in factors:
                if factor_counts.get(f, 100) < 10:
                    facet_col = f
                    break
            
            if facet_col:
                # 剩余变量选一个做 x
                remain_factors = [x for x in factors if x != facet_col]
                x_axis = remain_factors[0] if remain_factors else "randseed"
                
                suggestions.append({
                    "Scenario": "🧩 多维分面分析 (Expert)",
                    "Detected Factors": f"含分类变量 [{facet_col}]",
                    "Recommended Action": "分面统计摘要 (Facet Grid)",
                    "Code": f"batch.viz.plot_facet(func=batch.viz.plot_statistical_summary, col='{facet_col}', x='{x_axis}', metrics={target_metric_list})"
                })

        # 通用诊断
        suggestions.append({
            "Scenario": "🩺 异常诊断 (自动)",
            "Detected Factors": "通用",
            "Recommended Action": "运行自动诊断规则",
            "Code": "batch.diagnose_failure_modes()"
        })
        
        # 通用工具箱 (General Tools) - 确保覆盖所有可用绘图函数
        suggestions.append({
            "Scenario": "🛠️ 专家模式: 分面定制绘图",
            "Detected Factors": "任意变量",
            "Recommended Action": "使用通用分面容器 (Any Seaborn Plot)",
            "Code": f"import seaborn as sns\nbatch.viz.plot_facet(func=sns.kdeplot, x='{primary_metric}', hue=None, col='{factors[0] if factors else 'None'}', fill=True)"
        })
        suggestions.append({
            "Scenario": "🛠️ 通用工具: 分布分析",
            "Detected Factors": "任意单变量",
            "Recommended Action": "绘制累积分布/概率密度 (CDF/PDF)",
            "Code": f"batch.viz.plot_distribution(y='{primary_metric}', kind='cdf')"
        })
        suggestions.append({
            "Scenario": "🛠️ 通用工具: 相关性分析",
            "Detected Factors": "任意双变量",
            "Recommended Action": "绘制散点图 (Scatter Plot)",
            "Code": f"batch.viz.plot_scatter(x='{factors[0] if factors else 'cwnd'}', y='{primary_metric}')"
        })
        suggestions.append({
            "Scenario": "🛠️ 通用工具: 深入钻取",
            "Detected Factors": "特定实验",
            "Recommended Action": "钻取单个实验详情 (Drill Down)",
            "Code": "batch.viz.drill_down(param_name='value') # Replace with actual params"
        })

        df = pd.DataFrame(suggestions)
        
        # 确保显示完整内容不被截断 (Fix: prevent truncation ...)
        pd.set_option('display.max_colwidth', None)

        # 使用 Styler 使得换行符 \n 能够被正确渲染 (Jupyter Lab/Notebook)
        # 如果缺少 jinja2，Pandas 会抛出 AttributeError
        try:
            return df.style.set_properties(**{
                'text-align': 'left',
                'white-space': 'pre-wrap',
                'font-family': 'monospace'
            }).hide(axis="index")
        except AttributeError:
            # Fallback for environments without jinja2
            return df

    def diagnose_failure_modes(self) -> pd.DataFrame:
        """
        [Auto-Diagnosis] 自动应用领域知识检测网络故障模式。
        规则来源于《LLM推理网络优化指南》:
        1. Bufferbloat (缓存肿胀): High P99 Latency + Low Drops + High Queue Usage (if available)
        2. Congestion Collapse (拥塞崩溃): High Drop Rate + Low Goodput/Util
        3. Tail Latency (长尾极差): High Max FCT / Median FCT Ratio
        
        改进：自动展开关键变量列，提升可读性。
        """
        # 1. 获取包含核心指标的汇总表
        metrics = ["p99_fct", "median_fct", "max_fct", "max_drop_rate"]
        df = self.get_summary_df(metrics)
        # ...

    def scan_for_deadlocks(self) -> pd.DataFrame:
        """
        [New] 扫描批量实验中是否存在 "Silent Packet Deadlock" 问题。
        调用 ExperimentResult.diagnose_deadlock() 并汇总。
        """
        all_issues = []
        
        print(f"Scanning {len(self.experiments)} experiments for deadlocks...")
        
        for uid, entry in self.experiments.items():
            res = entry['result']
            issues = res.diagnose_deadlock()
            
            if issues:
                for issue in issues:
                    # Flatten info for DataFrame
                    row = {
                        "_uid": uid,
                        "FlowID": issue['flow_id'],
                        "Time_us": issue['time'],
                        "Details": issue['details'],
                        "Type": issue['type'],
                        **res.params # Include experiment params for context
                    }
                    all_issues.append(row)
        
        if not all_issues:
            print("🎉 No silent deadlocks detected in this batch.")
            return pd.DataFrame()
            
        df = pd.DataFrame(all_issues)
        print(f"⚠️ Found {len(df)} deadlock events across {df['_uid'].nunique()} experiments.")
        
        # Reorder columns to put critical info first
        cols = ["_uid", "Type", "Time_us", "FlowID", "Details"] 
        # Append other param columns (excluding internal ones)
        other_cols = [c for c in df.columns if c not in cols and not c.startswith("_")]
        
        return df[cols + other_cols]
        if df.empty:
            return pd.DataFrame()

        # 2. 定义阈值
        THRESH_BLOAT_LATENCY = 500  # us
        THRESH_COLLAPSE_DROP = 0.05 # 5%
        THRESH_TAIL_RATIO = 10.0

        diagnoses = []
        
        # 自动识别需要展示的变量（变化因子）
        varying_cols = self.get_varying_params()
        # 确保不包含指标列
        varying_cols = [c for c in varying_cols if c not in metrics]

        for _, row in df.iterrows():
            failures = []
            
            # 检测逻辑
            if row.get("p99_fct", 0) > THRESH_BLOAT_LATENCY and row.get("max_drop_rate", 0) < 0.001:
                failures.append("Bufferbloat")

            if row.get("max_drop_rate", 0) > THRESH_COLLAPSE_DROP:
                failures.append(f"Collapse (Drop {row['max_drop_rate']:.1%})")

            med = row.get("median_fct", 1)
            mx = row.get("max_fct", 0)
            if med > 0 and (mx / med) > THRESH_TAIL_RATIO:
                failures.append(f"Tail (Max/Med={mx/med:.1f}x)")

            if failures:
                # 构造易读的行
                entry = {
                    "Failures": "; ".join(failures),
                    **{col: row.get(col) for col in varying_cols}, # 仅展示变化因子
                    "_uid": row.get("_uid")
                }
                diagnoses.append(entry)

        if not diagnoses:
            print("🎉 No obvious failure modes detected!")
            return pd.DataFrame()

        # 调整列顺序：Failures 第一，变量其次
        res_df = pd.DataFrame(diagnoses)
        cols = ["Failures"] + varying_cols + ["_uid"]
        # 仅保留存在的列
        cols = [c for c in cols if c in res_df.columns]
        
        return res_df[cols]


class BatchVisualizer:
    def __init__(self, batch: BatchResult):
        self.batch = batch
        # 推断项目根路径（用于默认保存目录）
        self._root = Path(__file__).parent.parent.parent

    def _attach_save_btn(self, fig, title: str = "figure"):
        """
        在 Jupyter 环境中，于图片下方显示「💾 Save as PDF」按钮。

        使用方式（在任何绘图函数 plt.show() 之后加一行即可）:
            plt.show()
            self._attach_save_btn(plt.gcf(), title)
        """
        try:
            import datetime, re, matplotlib
            import ipywidgets as widgets
            from IPython.display import display as _display
            matplotlib.rcParams['pdf.fonttype'] = 42
            matplotlib.rcParams['ps.fonttype'] = 42

            save_dir = self._root / "figures"
            save_dir.mkdir(parents=True, exist_ok=True)
            slug = re.sub(r'[^\w\-]+', '_', str(title).strip()).strip('_').lower()[:60]

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

    def _fmt_plain(self, x, pos=None):
        return f"{x:g}"

    def plot_pivot(
        self,
        x: str,
        y: Union[str, List[str]], # Support list[str]
        hue: Optional[str] = None,
        col: Optional[str] = None,
        row: Optional[str] = None,
        kind: str = "line",  # 支持 line, bar, box, scatter, heatmap
        metrics: Optional[List[str]] = None,
        y2: Optional[str] = None, # [New] Secondary Axis Metric
        ref_line: Optional[float] = None, # [New] Reference Line
        title: Optional[str] = None,
        y_log: bool = False,
        **sns_kwargs,
    ):
        """
        【增加】通用科研透视绘图 API：一键处理筛选、聚类和子图。
        支持双轴 (y2) 和多指标 (List y) 绘图。
        :param x: X 轴变量
        :param y: Y 轴指标 (可为列表)
        :param y2: [New] 右侧 Y 轴指标 (叠加显示)
        :param hue: 聚类变量
        :param col/row: 分面变量
        """
        # Determine metrics to fetch
        targets = metrics or (y if isinstance(y, list) else [y])
        if y2:
            targets = targets + [y2]
            
        df = self.batch.get_summary_df(targets)
        if df.empty:
            return

        import matplotlib.pyplot as plt
        import seaborn as sns
        import matplotlib.ticker as ticker
        import pandas as pd 

        sns.set_theme(style="whitegrid", font_scale=1.1)
        
        # [Mode: Heatmap]
        if kind == "heatmap":
            if not hue:
                print("Error: Heatmap requires 'hue' to be set (mapped to Y-axis).")
                return
            
            def draw_heatmap(data, **kws):
                # Pivot: x=Column, hue=Index, y=Value
                # Ensure we only take the first metric if y is list (heatmap allows only 1 value dim)
                val_col = y[0] if isinstance(y, list) else y
                # Pivot and drop NaNs to avoid heatmap issues
                try:
                    pivot_data = data.pivot(index=hue, columns=x, values=val_col)
                    sns.heatmap(pivot_data, annot=True, fmt=".2g", cmap="viridis", cbar=True)
                except Exception as e:
                    print(f"Heatmap pivot failed: {e}")
            
            g = sns.FacetGrid(df, col=col, row=row, height=4, aspect=1.2, **sns_kwargs)
            g.map_dataframe(draw_heatmap)
            
        # [Mode: Standard Plots]
        else:
            # Only melt if y is list. If y2 is present, it stays as column for now (to be mapped later)
            plot_data = df
            plot_y = y
            plot_hue = hue
            plot_style = None # Style for primary plot
            
            if isinstance(y, list):
                # Melt logic for Primary Y
                # Keep y2 and other structure cols as ID vars
                id_vars = [c for c in df.columns if c not in y] 
                plot_data = df.melt(id_vars=id_vars, value_vars=y, var_name="Metric", value_name="Value")
                
                plot_y = "Value"
                if hue:
                    plot_style = "Metric" # Hue used by user, differentiate metrics by style
                else:
                    plot_hue = "Metric" # Hue free, use it for metrics
            
            # 选择绘图函数
            plot_func = sns.relplot if kind in ["line", "scatter"] else sns.catplot

            # 1. Draw Primary Plot
            g = plot_func(
                data=plot_data,
                x=x,
                y=plot_y,
                hue=plot_hue,
                style=plot_style,
                col=col,
                row=row,
                kind=kind,
                marker="o" if kind == "line" else None,
                facet_kws={"sharey": False, "sharex": True},
                **sns_kwargs,
            )
            
            # 2. [New] Draw Secondary Axis (y2) if requested
            if y2:
                def overlay_y2(data, **kws):
                    ax = plt.gca()
                    ax2 = ax.twinx()
                    # Use a distinct color/style for y2 (e.g., Red Dashed Line)
                    sns.lineplot(
                        data=data, x=x, y=y2, 
                        ax=ax2, color="tab:red", linestyle="--", marker="x", 
                        label=y2, ci=None
                    )
                    ax2.set_ylabel(y2, color="tab:red")
                    ax2.tick_params(axis='y', labelcolor="tab:red")
                    ax2.grid(False)

                # Map the overlay function to all facets
                g.map_dataframe(overlay_y2)

            # 3. set generic labels
            if isinstance(y, list):
                g.set_axis_labels(x_var=x, y_var="Metric Value")
            
            # 4. Format Axes
            for ax in g.axes.flat:
                if y_log:
                    ax.set_yscale("log")
                if not y2: # If dual axis, primary formatting might conflict visually if simple
                     ax.yaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
                # Only set x-format if NOT heatmap (heatmap usually has categorical X)
                ax.xaxis.set_major_formatter(ticker.FuncFormatter(self._fmt_plain))
                ax.grid(True, ls="--", alpha=0.5)

        # [Global Enhancements] Reference Line
        if ref_line is not None:
            for ax in g.axes.flat:
                # Use axhline directly, zorder to put it on top/bottom
                ax.axhline(y=ref_line, color='red', linestyle=':', linewidth=1.5, alpha=0.8)

        if title:
            g.fig.suptitle(title, y=1.02)
        _fig = g.fig  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, title or "plot_pivot")
        return g

    def plot_facet(
        self,
        func: Callable,
        col: Optional[str] = None,
        row: Optional[str] = None,
        metrics: Optional[List[str]] = None,
        sharex: bool = True,
        sharey: bool = False,
        **kwargs,
    ):
        """
        【新增】通用分面绘图容器 (Universal Facet Wrapper)。
        完全解耦“分面逻辑”与“绘图逻辑”。
        您提供任何绘图函数 (func) 和参数 (**kwargs)，这里只负责把画布切好 (FacetGrid)。
        
        :param func: 绘图函数，如 sns.boxplot, sns.kdeplot, sns.scatterplot 等 (必须支持 data=df 参数)
        :param col/row: 分面变量
        :param metrics: 需要加载的数据列 (如果 kwargs 里的 x/y 是指标名，会自动尝试加载，但手动指定更保险)
        """
        import matplotlib.pyplot as plt
        import seaborn as sns
        
        # 1. 自动推断需要加载的 metrics
        targets = set()
        if metrics:
            targets.update(metrics)
            
        # 尝试从 kwargs 中提取可能的指标名 (例如 x='p99_fct', y='goodput')
        for k, v in kwargs.items():
            if isinstance(v, str) and k in ["x", "y", "hue", "size", "style"]:
                targets.add(v)
        
        targets = list(targets)
        
        # 2. 获取数据
        df = self.batch.get_summary_df(targets)
        if df.empty:
            print("Error: No data found for the specified metrics.")
            return

        sns.set_theme(style="whitegrid", font_scale=1.1)

        # 3. 创建分面网格
        g = sns.FacetGrid(
            df, col=col, row=row, 
            sharex=sharex, sharey=sharey, 
            height=4, aspect=1.2
        )
        
        # 4. 映射绘图函数
        # 注意: func 必须支持 data argument。Seaborn 函数通常都支持。
        g.map_dataframe(func, **kwargs)
        
        # 5. 优化展示
        g.add_legend()
        for ax in g.axes.flat:
             ax.grid(True, ls="--", alpha=0.5)

        _fig = g.fig  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, "batch_facet")
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
        _fig = plt.gcf()  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, f"distribution_{y}")

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
        _fig = plt.gcf()  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, f"{target_version}_vs_{base_version}_{metric}")

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
        **kwargs,
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
            facet_kws={"sharey": False, "sharex": True},
            aspect=1.2,
            height=4,
            **kwargs,
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

        _fig = g.fig  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, title or "plot_generic")
        return g

    def plot_tradeoff(
        self,
        x: str,
        y1: str,
        y2: str,
        filters: Dict = None,
        title: str = None,
        labels: Tuple[str, str, str] = None,
        data: pd.DataFrame = None,
    ):
        """
        [新增] 双轴权衡图 (Dual-Axis Plot)。
        支持自定义 DataFrame 输入 (data) 以便预处理指标单位。
        """
        # 1. 准备数据
        if data is not None:
            df = data.copy()
        else:
            df = self.batch.get_summary_df([y1, y2])
        
        if df.empty:
            print("[!] No data available.")
            return

        if filters:
            for k, v in filters.items():
                df = df[df[k] == v]

        if df.empty:
            print("[!] No data after filtering.")
            return
            
        # 自动按 X 轴排序，保证线条连贯
        if x in df.columns:
            df = df.sort_values(x)
        else:
            print(f"[!] X axis variable '{x}' not found.")
            return

        # 2. 绘图
        import matplotlib.pyplot as plt
        import seaborn as sns
        
        sns.set_theme(style="whitegrid")
        fig, ax1 = plt.subplots(figsize=(10, 6))

        # 左轴 (Y1)
        color1 = 'tab:blue'
        sns.lineplot(
            data=df, x=x, y=y1, 
            ax=ax1, marker='o', color=color1, linewidth=2, label=y1, legend=False
        )
        ax1.tick_params(axis='y', labelcolor=color1)
        ax1.grid(True, linestyle='--', alpha=0.7)

        # 右轴 (Y2)
        ax2 = ax1.twinx()  
        color2 = 'tab:red'
        sns.lineplot(
            data=df, x=x, y=y2, 
            ax=ax2, marker='s', color=color2, linestyle='--', linewidth=2, label=y2, legend=False
        )
        ax2.tick_params(axis='y', labelcolor=color2)
        ax2.grid(False) # 避免网格冲突

        # 3. 标签与修饰
        if labels:
            xlabel, ylabel1, ylabel2 = labels
            ax1.set_xlabel(xlabel, fontsize=12, fontweight='bold')
            ax1.set_ylabel(ylabel1, color=color1, fontsize=12, fontweight='bold')
            ax2.set_ylabel(ylabel2, color=color2, fontsize=12, fontweight='bold')
        else:
            ax1.set_xlabel(x, fontsize=12)
            ax1.set_ylabel(y1, color=color1, fontsize=12)
            ax2.set_ylabel(y2, color=color2, fontsize=12)

        if title:
            plt.title(title, fontsize=14, pad=20)
        else:
            plt.title(f"{y1} vs {y2} over {x}", fontsize=14, pad=20)
            
        # 合并图例
        lines_1, labels_1 = ax1.get_legend_handles_labels()
        lines_2, labels_2 = ax2.get_legend_handles_labels()
        ax1.legend(lines_1 + lines_2, labels_1 + labels_2, loc='upper left')

        plt.tight_layout()
        _fig = plt.gcf()  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, title or "plot_tradeoff")

    def plot_statistical_summary(
        self,
        x: str,
        hue: str = "version",
        metrics: Optional[List[str]] = None,
        title: str = "Scalability Analysis: FCT Statistics",
        **kwargs
    ):
        """
        [新增] 科研级多指标对比图。
        支持作为独立函数调用，也支持被 plot_facet 调用 (作为 map_dataframe 的 func)。
        """
        import matplotlib.ticker as ticker
        
        # [Compatibility Fix] Handle FacetGrid injections
        # FacetGrid passes 'color', 'label' etc. We ignore them or use them if needed.
        # But crucially, it passes 'data' (the sliced dataframe for this facet).
        data = kwargs.get("data", None)
        
        # 1. 获取数据
        target_metrics = metrics or ["max_fct", "p99_fct", "median_fct"]
        
        if data is None:
            # 独立调用模式：自己去取全量数据
            df = self.batch.get_summary_df(target_metrics)
        else:
            # FacetGrid 模式：使用已经切分好的数据 (注意：这个 data 可能已经包含了 columns)
            # 但 FacetGrid 传进来的 data 可能不缺列，因为我们之前的 plot_facet 
            # 是用 get_summary_df(all_needed) 初始化的。
            df = data
            
        if df.empty:
            return

        # 2. 数据长表化 (Melt)
        # 检查 target_metrics 是否都在 df 中
        missing = [m for m in target_metrics if m not in df.columns]
        if missing and data is not None:
             # 如果是 Facet 模式且缺列，说明 plot_facet 初始化时没把指标加进去
             # 尝试补救 (不建议，因为 FacetGrid 的 data 是 disconnected 的)
             # 所以只好 filter out missing
             target_metrics = [m for m in target_metrics if m in df.columns]
        
        if not target_metrics:
             return

        id_vars = [c for c in df.columns if c not in target_metrics]
        df_long = df.melt(
            id_vars=id_vars,
            value_vars=target_metrics,
            var_name="Metric",
            value_name="FCT_us",
        )

        # 3. 映射美化名称
        name_map = {"max_fct": "Max", "p99_fct": "P99", "median_fct": "Median"}
        df_long["Metric"] = df_long["Metric"].map(name_map).fillna(df_long["Metric"])

        # --- 执行物理逻辑排序 ---
        def get_sort_key(val):
            try:
                return float(str(val).split()[0])
            except (ValueError, AttributeError, IndexError):
                return 0.0

        if x in df_long.columns:
            df_long["_sort_order"] = df_long[x].apply(get_sort_key)
            df_long = df_long.sort_values("_sort_order").drop(columns=["_sort_order"])

        # 4. 绘图 (如果是 Facet 模式，不要创建新 Figure)
        # FacetGrid 会自动使得当前的 plt.gca() 为目标子图
        is_facet_mode = (data is not None)
        
        if not is_facet_mode:
            plt.figure(figsize=(12, 7))
        
        sns.set_theme(style="whitegrid", font_scale=1.1)

        style_map = {"Max": (2, 2), "P99": "", "Median": (5, 5)}
        markers = {"Max": "X", "P99": "o", "Median": "s"}
        
        # 只要存在不同 style，hue 就需要 careful
        # 注意：如果 FacetGrid 已经分过 hue (通过 map_dataframe(..., hue='xxx'))
        # 那么 kwargs 里会有 hue。
        # 但我们这里还需要强制用 Hue 分算法，用 Style 分指标。
        # 如果 hue 参数与 plot_statistical_summary(hue=...) 冲突，以前者优先。
        
        current_hue = kwargs.get("hue", hue) 
        # 如果 FacetGrid 没传 hue (比如只用了 col)，那就用默认值
        
        # 即使是 Facet Mode，我们也画 lineplot。
        # 注意: lineplot 会自动画到当前 ax
        ax = sns.lineplot(
            data=df_long,
            x=x,
            y="FCT_us",
            hue=current_hue, 
            style="Metric",
            markers=markers,
            dashes=style_map,
            palette="husl",
            linewidth=2,
            markersize=8,
            sort=False,
            # Ax handling is automatic in seaborn usually, but to be safe:
            ax=plt.gca() if is_facet_mode else None
        )

        # 5. 细节优化
        if not is_facet_mode:
            ax.set_title(title, pad=20, fontsize=14)
            ax.set_ylabel("Flow Completion Time (us)")
            ax.set_xlabel(x.replace("_", " ").capitalize())
            
            # Independent mode extras
            plt.legend(bbox_to_anchor=(1.02, 1), loc="upper left", borderaxespad=0.0)
            plt.grid(True, ls="--", alpha=0.4)
            sns.despine(trim=False)
            plt.tight_layout()
            fig = plt.gcf()
            plt.show()
            if kwargs.get("return_fig", False):
                return fig
            self._attach_save_btn(fig, title)
        else:
            # Facet Mode cleanup
            ax.set_xlabel(x)
            ax.set_ylabel("FCT (us)")
            ax.grid(True, ls="--", alpha=0.4)

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

        _fig = plt.gcf()  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, title)
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
        _fig = plt.gcf()  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, f"main_effects_{metric if isinstance(metric,str) else metric[0]}")

    def plot_parallel_coordinates(
        self,
        factors: List[str],
        metrics: List[str],
        hue: str = None,
        filters: Dict = None,
        sample: Optional[int] = 200,
        normalize: bool = True,
        highlight: Dict = None,
        title: str = None,
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
        # [Fix] 去重，避免 hue (label_col) 在 factors 中导致列重复 (ValueError: Buffer has wrong number of dimensions)
        req_cols = list(dict.fromkeys(factors + metrics + [label_col]))
        plot_df = df[req_cols].copy()
        
        # [Fix] 显式保留分类标签列，防止被后面归一化重命名破坏 (KeyError: 'class')
        plot_df["class"] = df[label_col].values
        
        # 预先计算并保存原始范围用于标签
        range_labels = {}
        
        if normalize:
            from sklearn.preprocessing import LabelEncoder
            for col in factors + metrics:
                if col not in plot_df.columns: 
                    continue
                
                min_str, max_str = "", ""
                is_categorical = False

                # 1. 预处理：Boolean 转 Int, String 转 Int (LabelEncode)
                if pd.api.types.is_bool_dtype(plot_df[col]):
                     plot_df[col] = plot_df[col].astype(int)
                
                min_str, max_str = "", ""
                is_categorical = False

                # 检查是否为数值 (此时 Bool 已转 Int，应视为数值)
                if not pd.api.types.is_numeric_dtype(plot_df[col]):
                    is_categorical = True
                    try:
                        # [Fix] Fill NaNs to avoid encoding failure
                        safe_col = plot_df[col].fillna("NaN").astype(str)
                        le = LabelEncoder()
                        plot_df[col] = le.fit_transform(safe_col)
                        if len(le.classes_) > 0:
                            min_str = str(le.classes_[0])
                            max_str = str(le.classes_[-1])
                    except Exception as e:
                        print(f"[Warn] Failed to encode column '{col}': {e}. Dropping from plot.")
                        if col in plot_df.columns:
                            plot_df.drop(columns=[col], inplace=True)
                        continue
                else:
                    # 数值列 (含 Bool->Int)
                    min_val_raw = plot_df[col].min()
                    max_val_raw = plot_df[col].max()
                    min_str = self._smart_format(col, min_val_raw)
                    max_str = self._smart_format(col, max_val_raw)

                # [Safety Check] Skip if column was dropped
                if col not in plot_df.columns:
                    continue

                # 2. 统一归一化
                # 强制转 float 以避免 int 运算问题或潜在的 bool 残留
                plot_df[col] = plot_df[col].astype(float)
                
                min_val = plot_df[col].min()
                max_val = plot_df[col].max()

                if max_val > min_val:
                    # 归一化到 [0, 1]
                    plot_df[col] = (plot_df[col] - min_val) / (max_val - min_val)
                    
                    # 生成轴标签
                    if is_categorical:
                        # 对于分类变量，显示 First ~ Last
                        range_label = f"{col}\n{min_str}\n~\n{max_str}"
                    else:
                        range_label = f"{col}\n{min_str}\n↓\n{max_str}"
                    
                    plot_df.rename(columns={col: range_label}, inplace=True)
                else:
                    # 单一值
                    range_label = f"{col}\n{min_str}"
                    plot_df.rename(columns={col: range_label}, inplace=True)

        # [Custom Implementation] Curved Parallel Coordinates
        # 丢弃 pandas.plotting.parallel_coordinates，改用自定义 Bezier 实现
        
        # plot_df = plot_df.rename(columns={label_col: "class"})
        # [Fix] 不需要再重命名了，前面已经手动创建了 class 列
        cols_to_plot = [c for c in plot_df.columns if c != "class"]
        
        # [Safety] Final Type Coercion
        # Ensure all plotting data is strictly numeric
        valid_cols = []
        for c in cols_to_plot:
            try:
                plot_df[c] = pd.to_numeric(plot_df[c])
                valid_cols.append(c)
            except Exception:
                print(f"[Error] Column '{c}' is still non-numeric after encoding. Dropping.")
        
        cols_to_plot = valid_cols
        if not cols_to_plot:
            print("[Error] No valid numeric columns left to plot.")
            return

        # 提取数据矩阵 (N_samples, M_axes)
        data_matrix = plot_df[cols_to_plot].values.astype(float)
        
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
                # [Fix] 使用 pd.factorize 避免 numpy 标量/数组不可哈希的问题
                codes, unique_labels = pd.factorize(hl_labels, sort=True)
                
                if len(unique_labels) > 1:
                    # 使用 viridis 映射分类
                    cmap = plt.get_cmap("viridis")
                    # Normalize codes to [0, 1]
                    # codes 是整数数组，直接归一化
                    norm_vals = codes / (len(unique_labels) - 1)
                    colors = cmap(norm_vals)
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
            if title:
                title_str = title
            elif highlight:
                is_top = highlight.get('top', True)
                metric = highlight.get('metric')
                frac = highlight.get('fraction', 0.1)
                desc = "Top" if is_top else "Bottom" # Or "Highest"/"Lowest"
                title_str = f"Parallel Coordinates ({desc} {frac:.0%} {metric})"
            else:
                title_str = "Parallel Coordinates (Normalized Range)"
            ax.set_title(title_str, fontsize=16, pad=20)
            
            # 竖向网格线 (这就是坐标轴)
            for x in x_coords:
                ax.axvline(x, color='black', alpha=0.1, linewidth=1)
                
            plt.tight_layout()
            _fig = plt.gcf()  # capture before plt.show() resets state
            plt.show()
            self._attach_save_btn(_fig, title or "parallel_coordinates")

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
        _fig = plt.gcf()  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, "scatter_matrix")
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

        # [Fix] 类型检查：确保 X, Y 为数值类型
        # 尝试强制转换，如果失败则这些列可能包含无法解析的字符串 (如 "10 20")
        try:
            plot_df[x] = pd.to_numeric(plot_df[x])
            plot_df[y] = pd.to_numeric(plot_df[y])
        except (ValueError, TypeError):
             print(f"[Warn] Response Surface requires numeric X/Y axes. Function aborted.\n    Got types: {x}={plot_df[x].dtype}, {y}={plot_df[y].dtype}")
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
            _fig = plt.gcf()  # capture before plt.show() resets state
            plt.show()
            self._attach_save_btn(_fig, title or f"response_surface_{z}_vs_{x}_{y}")

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
                title=f"BDP Impact: {target_metric} vs Bandwidth & Delay",
                cmap="plasma"
            )

    def plot_distribution(
        self,
        y: str,
        kind: str = "cdf",
        filters: Dict = None,
        title: str = None,
        **sns_kwargs
    ):
        """
        [General Tool] 通用分布分析工具。
        :param y: 指标名称 (如 'p99_fct')
        :param kind: 'hist', 'kde', 'cdf', 'box', 'violin'
        """
        df = self.batch.get_summary_df([y])
        if filters:
            for k, v in filters.items():
                if k in df.columns:
                    df = df[df[k] == v]
        
        if df.empty:
            print("[!] No data to plot.")
            return

        plt.figure(figsize=(8, 6))
        
        if kind == 'cdf':
            sns.ecdfplot(data=df, x=y, **sns_kwargs)
            plt.grid(True, linestyle='--', alpha=0.3)
            plt.ylabel("CDF")
        elif kind == 'hist':
            sns.histplot(data=df, x=y, **sns_kwargs)
        elif kind == 'kde':
            sns.kdeplot(data=df, x=y, **sns_kwargs)
        elif kind == 'box':
            sns.boxplot(data=df, y=y, **sns_kwargs)
        elif kind == 'violin':
            sns.violinplot(data=df, y=y, **sns_kwargs)
            
        plt.title(title if title else f"Distribution of {y}")
        plt.tight_layout()
        _fig = plt.gcf()  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, title or f"distribution_{y}")

    def plot_scatter(
        self,
        x: str,
        y: str,
        hue: str = None,
        size: str = None,
        filters: Dict = None,
        title: str = None,
        **sns_kwargs
    ):
        """
        [General Tool] 通用散点相关性分析工具。
        """
        metrics = [y]
        if size and size not in metrics: metrics.append(size)
        
        df = self.batch.get_summary_df(metrics) # Auto-includes params
        
        if filters:
            for k, v in filters.items():
                 if k in df.columns:
                    df = df[df[k] == v]
        
        if df.empty:
             print("[!] No data.")
             return

        plt.figure(figsize=(8, 6))
        sns.scatterplot(data=df, x=x, y=y, hue=hue, size=size, **sns_kwargs)
        
        # 增加相关系数标注
        try:
            if x in df.columns and y in df.columns and pd.api.types.is_numeric_dtype(df[x]) and pd.api.types.is_numeric_dtype(df[y]):
                corr = df[[x, y]].corr().iloc[0, 1]
                plt.text(0.05, 0.95, f"Corr: {corr:.2f}", transform=plt.gca().transAxes, 
                         bbox=dict(facecolor='white', alpha=0.8))
        except:
            pass
            
        plt.grid(True, linestyle='--', alpha=0.3)
        plt.title(title if title else f"{x} vs {y}")
        plt.tight_layout()
        _fig = plt.gcf()  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, title or f"{x}_vs_{y}")

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
        _fig = plt.gcf()  # capture before plt.show() resets state
        plt.show()
        self._attach_save_btn(_fig, f"feature_importance_{metric}")

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


# ===========================================================================
# 模块级工具函数
# ===========================================================================

def show_with_save(
    plot_func,
    *args,
    save_dir: str = None,
    **kwargs,
):
    """
    包裹任意 BatchVisualizer 绘图函数，在图下方显示「💾 Save as PDF」按钮。
    点击后以 {title_slug}_{timestamp}.pdf 格式保存到指定目录（默认 figures/）。

    用法示例：
        from analysis.data.batch import show_with_save
        show_with_save(
            batch.viz.plot_statistical_summary,
            x='randseed', hue='sleek',
            metrics=['p99_fct', 'median_fct', 'max_fct'],
            title='randseed vs sleek (FCT Stats)',
        )
    """
    import datetime
    import re
    import matplotlib
    import matplotlib.pyplot as plt

    # 论文级字体设置：字体嵌入为 TrueType，Adobe/Inkscape 中仍可编辑
    matplotlib.rcParams['pdf.fonttype'] = 42
    matplotlib.rcParams['ps.fonttype'] = 42

    # 1. 调用绘图函数，截获 fig（通过 return_fig=True 注入）
    fig = plot_func(*args, return_fig=True, **kwargs)

    if fig is None:
        # 如果该函数不支持 return_fig，尝试 plt.gcf() 补救
        fig = plt.gcf()
        if not fig.get_axes():
            print("[show_with_save] 无法截获 figure，该绘图函数可能不支持 return_fig。")
            return

    # 2. 确定保存目录（默认：项目根/figures/）
    if save_dir is None:
        save_dir = Path(__file__).parent.parent.parent / "figures"
    save_path = Path(save_dir)
    save_path.mkdir(parents=True, exist_ok=True)

    # 3. 自动生成文件名 slug（来自 title 参数）
    title_str = kwargs.get("title", "figure")
    slug = re.sub(r'[^\w\-]+', '_', str(title_str).strip()).strip('_').lower()
    slug = slug[:60]  # 截断过长标题

    # 4. 显示保存按钮
    try:
        import ipywidgets as widgets
        from IPython.display import display

        def _on_save(b):
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = save_path / f"{slug}_{ts}.pdf"
            fig.savefig(filename, bbox_inches="tight")
            b.description = "✅ Saved!"
            b.button_style = "success"
            b.disabled = True
            print(f"[save] → {filename}")

        btn = widgets.Button(
            description="💾 Save as PDF",
            button_style="info",
            icon="download",
            layout=widgets.Layout(width="180px", height="36px"),
        )
        btn.on_click(_on_save)
        display(btn)

    except ImportError:
        # 非 Jupyter 环境：直接保存
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = save_path / f"{slug}_{ts}.pdf"
        fig.savefig(filename, bbox_inches="tight")
        print(f"[save] ipywidgets 不可用，已自动保存 → {filename}")
