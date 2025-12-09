# 绘图 YAML 配置规范

本文档描述当前绘图流程的使用方式。绘图由实验 YAML 顶层的 `plots` 字段驱动，执行完批量实验后，系统会调用内置的 Python 绘图模块（位于 `analysis/plot/`）生成图表；部分绘图模块会在结果目录的 `plots/` 下生成可编辑的 YAML（如 `cct-vs-algo.yaml`）用于二次定制。

## 1. 使用方式与流程

使用方式：

- 在实验配置文件顶层加入 `plots` 字段，列出要生成的图表类型，例如：

```yaml
plots:
  - CDF-FCT
  - CDF-CCT
  - AvgFCT-Nodes
  - MaxFCT-MsgSize
  - CCT-Algo
```

- 执行 `python run.py <config>.yaml` 后，系统会在 `results/<配置相对路径>/` 下的各子实验目录生成图表，并在需要时生成 `plots/` 子目录及配置文件。

## 2. 当前实现原理

1.  根据 `status.yaml` 加载每个子实验的运行命令与变量组合。
2.  从 `output.log` 或聚合结果目录解析 FCT/CCT 等数据。
3.  使用内置绘图模块生成图表；如 `CCT-Algo` 会在 `plots/` 下创建 `cct-vs-algo.yaml`，可手动编辑其中的配色与标签映射后重跑绘图函数。

## 3. 常见图表类型说明

- `CDF-FCT` 与 `CDF-CCT`：比较不同子实验的分布曲线。
- `AvgFCT-Nodes`：不同节点规模下的平均 FCT。
- `MaxFCT-MsgSize`：消息大小与最大 FCT 的关系。
- `CCT-Algo`：不同集体算法的最大 CCT 对比，并支持 `plots/cct-vs-algo.yaml` 自定义配色与标签映射。

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
