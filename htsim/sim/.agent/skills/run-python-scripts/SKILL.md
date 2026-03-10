---
name: run-python-scripts
description: |
  Standard workflow for running Python simulation scripts inside the correct micromamba environment.
  Ensures all Python scripts (run.py, analysis scripts, etc.) execute with the proper conda environment
  and have access to all required dependencies.
---

# 🤖 htsim Python 脚本执行标准工作流 (Python Script Execution Workflow)

**核心原则**：任何时候需要在此仓库中运行 Python 脚本（如 `run.py`、`analysis/` 下的分析脚本、或 `extract_ipynb_records.py` 等），**必须**在 `sim` micromamba 环境中执行。

---

## ⚠️ 为什么不能直接运行 `python script.py`？

直接使用系统 Python 或默认环境会导致：
- ✅ 缺少项目特定的依赖包
- ✅ 版本不兼容（NumPy、Pandas、Matplotlib 等）
- ✅ 分析结果不一致
- ✅ 无法使用项目配置的科学计算工具链

---

## 🔧 标准执行命令 (Standard Execution Commands)

### 方法 1：使用 `micromamba run`（推荐 - 适用于单次命令）

**标准格式**：
```bash
micromamba run -n sim python <script_path> [arguments]
```

**范例 1**：运行模拟实验
```bash
micromamba run -n sim python run.py experiments/SimpleTests/oblivious_trim_ecn.yaml
```

**范例 2**：运行分析脚本
```bash
micromamba run -n sim python analysis/runner.py results/experiment_001/
```

**范例 3**：运行 Jupyter Notebook 记录提取
```bash
micromamba run -n sim python extract_ipynb_records.py
```

---

### 方法 2：激活环境（适用于需要执行多个命令的场景）

```bash
# 1. 激活 sim 环境
micromamba activate sim

# 2. 现在可以直接使用 python 命令
python run.py experiments/test.yaml
python analysis/some_script.py

# 3. 完成后退出环境（可选）
micromamba deactivate
```

**说明**：此方法适用于需要在同一环境中连续执行多个 Python 命令的交互式场景。

---

## 📋 完整执行流程范例

### 场景 1：运行单文件模拟实验

```bash
# 进入项目根目录
cd /home/wy/Code/uet-htsim/htsim/sim

# 运行实验配置
micromamba run -n sim python run.py experiments/SimpleTests/oblivious_trim_ecn.yaml

# 等待模拟完成，输出将保存到 results/ 目录
```

### 场景 2：运行分析流水线

```bash
# 运行分析脚本处理实验结果
micromamba run -n sim python analysis/runner.py results/experiment_001/

# 可视化结果
micromamba run -n sim python analysis/viz/autoreport.py results/experiment_001/
```

### 场景 3：交互式开发（需要多次执行）

```bash
# 1. 激活环境
micromamba activate sim

# 2. 多次执行不同命令
python script1.py arg1 arg2
python script2.py --option value
python -m IPython  # 启动交互式 Python

# 3. 完成后退出
micromamba deactivate
```

---

## 🎯 环境验证

在执行脚本前，可以验证环境是否正确：

```bash
# 验证 micromamba 是否可用
which micromamba

# 验证 sim 环境是否存在
micromamba env list | grep sim

# 验证环境中的 Python 版本
micromamba run -n sim python --version

# 验证关键依赖包
micromamba run -n sim python -c "import numpy; print(numpy.__version__)"
```

---

## ❌ 常见错误

**错误 1**: 直接运行 Python
```bash
# ❌ 错误 - 不要这样做
python run.py experiments/test.yaml
```

**错误 2**: 使用错误的 conda/mamba 命令
```bash
# ❌ 错误 - 项目使用 micromamba，不是 conda
conda activate sim
conda run -n sim python script.py
```

**错误 3**: 忘记指定环境名称
```bash
# ❌ 错误 - 必须指定 -n sim
micromamba run python script.py
```

**正确做法**: 始终使用 `micromamba run -n sim python ...` 格式。

---

## 🔗 相关 Skills

- [[compile-simulator]] - 如何编译 htsim 模拟器到正确的输出目录

---

## 版本信息

- **最后更新**: 2026-03-10
- **适用项目**: htsim UEC 协议模拟器
- **维护者**: 项目基础设施规范
