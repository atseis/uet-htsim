---
name: compile-simulator
description: |
  Standard workflow for compiling the htsim simulator with correct binary output mapping.
  Ensures all compiled binaries (htsim_uec, parse_output, etc.) are placed in out/Debug/ directory
  for compatibility with analysis/runner.py and other Python tooling.
---

# 🤖 htsim 模拟器编译标准工作流 (Simulator Compilation Workflow)

**核心原则**：htsim 项目及其模拟运行器（如 `analysis/runner.py`）硬编码期望编译后的二进制文件（`htsim_uec`、`parse_output` 等）位于 `out/Debug/` 目录中。**任何时候需要重新编译 C++ 代码库时，必须严格遵守以下步骤**，确保所有输出正确映射。

---

## ⚠️ 为什么不能直接在 build/ 目录编译？

项目中的 Python 分析工具箱和模拟运行器硬编码查找路径为 `out/Debug/`。如果直接构建在 `build/` 或其他目录，会导致：
- ✅ `analysis/runner.py` 找不到二进制文件
- ✅ 手动执行时路径混乱
- ✅ 分析工具与执行环境不同步

---

## 🔧 标准编译命令 (Standard Compilation Commands)

### 步骤 1：配置 CMake 目标目录为 `out/Debug`

```bash
cmake -S . -B out/Debug -DCMAKE_BUILD_TYPE=Debug
```

**说明**：
- `-S .`：源目录为当前目录
- `-B out/Debug`：**关键** - 构建输出目录必须是 `out/Debug`
- `-DCMAKE_BUILD_TYPE=Debug`：使用 Debug 构建类型（包含调试符号）

### 步骤 2：使用并行核心编译

```bash
make --directory=out/Debug -j$(nproc)
```

**说明**：
- `--directory=out/Debug`：在输出目录执行 make
- `-j$(nproc)`：使用所有可用 CPU 核心并行编译

---

## 📋 完整编译流程范例

```bash
# 1. 进入项目根目录
cd /home/wy/Code/uet-htsim/htsim/sim

# 2. 配置 CMake（首次或 CMakeLists.txt 变更时需要重新配置）
cmake -S . -B out/Debug -DCMAKE_BUILD_TYPE=Debug

# 3. 编译（每次代码修改后重新编译）
make --directory=out/Debug -j$(nproc)

# 4. 验证编译产物
ls -la out/Debug/htsim_uec out/Debug/parse_output
```

---

## 🔄 何时需要重新编译？

- ✅ 修改了 `src/` 目录下的任何 C++ 源文件
- ✅ 修改了 `CMakeLists.txt`
- ✅ 添加了新的协议实现或数据包结构
- ✅ 需要测试最新的 UEC 协议修复

---

## 🎯 预期输出

编译成功后，`out/Debug/` 目录应包含以下关键二进制文件：

```
out/Debug/
├── htsim_uec          # UEC 协议模拟器主程序
├── parse_output       # 输出解析器
└── ... (其他工具)
```

遵循此工作流后，您的手动执行和 Python 分析工具箱将完美同步。

---

## ❌ 常见错误

**错误 1**: 直接在 `build/` 目录编译
```bash
# ❌ 错误 - 不要这样做
cmake -S . -B build
make -C build
```

**错误 2**: 使用默认的 CMake 构建目录
```bash
# ❌ 错误 - 不要这样做
mkdir build && cd build
cmake ..
make
```

**正确做法**: 始终使用 `out/Debug` 作为构建输出目录。

---

## 🔗 相关 Skills

- [[run-python-scripts]] - 如何在正确的 micromamba 环境中运行 Python 脚本

---

## 版本信息

- **最后更新**: 2026-03-10
- **适用项目**: htsim UEC 协议模拟器
- **维护者**: 项目基础设施规范
