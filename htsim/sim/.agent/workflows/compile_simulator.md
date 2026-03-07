---
description: How to compile the htsim simulator
---

# Compiling the Simulator

The `htsim` project and its associated simulation runners (`analysis/runner.py`, etc.) are hardcoded to expect the compiled binaries (`htsim_uec`, `parse_output`, etc.) inside the `out/Debug/` directory.

Whenever you need to recompile the C++ codebase, you **MUST** use the following steps to ensure all outputs are correctly mapped. Do not build directly in the `build/` dir.

## Standard Compilation Commands

// turbo-all
1. Configure cmake target directory to `out/Debug`:
```bash
cmake -S . -B out/Debug -DCMAKE_BUILD_TYPE=Debug
```

2. Compile the code using parallel cores:
```bash
make --directory=out/Debug -j$(nproc)
```

By following this workflow, both your manual executions and the `analysis` python toolbox will synchronize perfectly.
