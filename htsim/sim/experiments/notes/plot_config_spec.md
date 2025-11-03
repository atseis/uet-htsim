# 绘图 YAML 配置规范

本文档详细描述了用于生成实验结果图表的 YAML 配置文件的结构和字段。这些配置文件由 `plot_generator.py` 生成，并由 `plot_from_yaml.py` 解析和执行，以创建各种类型的图表。

## 1. 配置文件结构

绘图 YAML 配置文件通常包含以下顶级字段：

- `generated_from`: (字符串) 生成此绘图配置的原始实验 YAML 文件的路径。
- `generated_time`: (字符串) 此绘图配置文件的生成时间，格式为 ISO 8601。
- `plot_type`: (字符串) 指定要生成的图表类型。目前支持 `cdf-fct` (Flow Completion Time CDF)、`throughput` (吞吐量) 和 `MaxFCT-MsgSize` (最大流完成时间 vs. 消息大小) 等。
- `sources`: (列表) 定义了用于绘图的数据源。每个数据源是一个字典，包含 `path` 和 `name` 字段。
    - `path`: (字符串) 实验结果数据的相对路径，通常是 `results` 目录下的子路径。
    - `name`: (字符串) 在图例中显示的数据源名称。
- `title`: (字符串) 图表的标题。
- `x_label`: (字符串) X 轴的标签。
- `y_label`: (字符串) Y 轴的标签。
- `output_format`: (字符串) 输出图表的格式，例如 `png`、`pdf`、`svg` 等。支持 `matplotlib` 支持的所有格式。
- `legend_loc`: (字符串, 可选) 图例的位置，例如 `lower right`、`upper left` 等。如果未指定，系统可能会使用默认位置。
- `grid`: (布尔值, 可选) 是否在图表中显示网格。默认为 `false`。
- `x_range_auto`: (布尔值, 可选) 是否自动调整 X 轴的显示范围。如果设置为 `true`，系统将根据数据自动确定合适的 X 轴范围。默认为 `false`。
- `x_range_manual`: (列表或 `null`, 可选) 手动指定 X 轴的显示范围。如果 `x_range_auto` 为 `false`，则此字段有效。它应该是一个包含两个浮点数的列表 `[min_value, max_value]`，表示 X 轴的最小值和最大值。如果设置为 `null`，则表示不进行手动设置，系统将使用默认或自动范围（取决于 `x_range_auto` 的值）。
- `output`: (字符串) 生成图表的完整输出路径，包括文件名和扩展名。
- `lines_config`: (列表) 定义了图中每条线的配置。每个元素是一个字典，包含以下字段：
    - `data_source_name`: (字符串) 对应 `sources` 中定义的数据源的 `name` 字段。
    - `color`: (字符串, 可选) 线的颜色，例如 `red`、`blue`、`#FF0000` 等。
    - `linestyle`: (字符串, 可选) 线的样式，例如 `-` (实线)、`--` (虚线)、`-.` (点划线) 等。
    - `marker`: (字符串, 可选) 数据点的标记样式，例如 `o` (圆圈)、`x` (叉号)、`s` (正方形) 等。如果未指定，默认使用 `o`。
    - `label`: (字符串, 可选) 图例中显示的标签。如果未指定，将使用 `data_source_name`。

## 2. 绘图流程与原理

绘图系统通过 `plot_generator.py` 根据实验结果生成绘图配置文件，然后由 `plot_from_yaml.py` 解析并执行。其核心原理如下：

1.  **数据加载与预处理**：根据 `sources` 中定义的路径加载实验数据，并进行必要的预处理（如 FCT CDF 计算、吞吐量计算等）。
2.  **图表类型识别**：根据 `plot_type` 字段识别需要绘制的图表类型，并调用相应的绘图函数。
3.  **数据映射与可视化**：将处理后的数据映射到图表的 X 轴和 Y 轴，并根据 `lines_config` 中的配置（如颜色、线型、标记等）绘制每条数据线。
4.  **图表美化**：根据 `title`、`x_label`、`y_label`、`legend_loc`、`grid`、`x_range_auto` 和 `x_range_manual` 等字段设置图表的标题、轴标签、图例、网格和轴范围。
5.  **保存图表**：根据 `output` 和 `output_format` 字段将生成的图表保存到指定路径和格式。

## 3. 示例绘图 YAML 配置

以下是一个 `cdf-fct` 类型的绘图 YAML 配置示例：

```yaml
generated_from: /root/code/uet-htsim/htsim/sim/experiments/oblivious_trim_ecn.yaml
generated_time: '2025-10-28T05:40:47.462123'
plot_type: cdf-fct
sources:
  - path: oblivious_trim_ecn/paths32_q1000_stratecmp
    name: paths32_q1000_stratecmp
  - path: oblivious_trim_ecn/paths256_q1000_stratecmp
    name: paths256_q1000_stratecmp
  - path: oblivious_trim_ecn/paths32_q35_stratecmp
    name: paths32_q35_stratecmp
  - path: oblivious_trim_ecn/ecn_thresh0.018_paths32_q1000_stratecmp_host_ecn
    name: ecn_thresh0.018_paths32_q1000_stratecmp_host_ecn
  - path: oblivious_trim_ecn/paths256_q35_stratecmp
    name: paths256_q35_stratecmp
  - path: oblivious_trim_ecn/ecn_thresh0.018_paths256_q1000_stratecmp_host_ecn
    name: ecn_thresh0.018_paths256_q1000_stratecmp_host_ecn
title: Flow Completion Time CDF
x_label: FCT (ms)
y_label: CDF
output_format: png
legend_loc: lower right
grid: true
x_range_auto: false
x_range_manual: [0.15, 0.3]
output: /root/code/uet-htsim/htsim/sim/results/oblivious_trim_ecn/plots/cdf-fct.png
lines_config:
  - data_source_name: paths32_q1000_stratecmp
    color: blue
    linestyle: '--'
    marker: 'o'
  - data_source_name: paths256_q1000_stratecmp
    color: red
    linestyle: '-'
    marker: 'x'
```

## 4. `x_range_auto` 和 `x_range_manual` 的使用

这两个字段用于控制图表的 X 轴显示范围：

- 当 `x_range_auto` 设置为 `true` 时，系统将自动分析数据并确定一个合适的 X 轴范围，`x_range_manual` 的设置将被忽略。
- 当 `x_range_auto` 设置为 `false` 时，系统将尝试使用 `x_range_manual` 指定的范围。如果 `x_range_manual` 为一个 `[min, max]` 列表，则 X 轴将显示在该范围内。如果 `x_range_manual` 为 `null`，则系统将回退到默认的自动范围。

**示例：**

- **自动范围：**
  ```yaml
  x_range_auto: true
  x_range_manual: null # 或任何值，都将被忽略
  ```

- **手动范围：**
  ```yaml
  x_range_auto: false
  x_range_manual: [0.0, 1.0]
  ```

- **不指定手动范围，回退到默认自动：**
  ```yaml
  x_range_auto: false
  x_range_manual: null
  ```