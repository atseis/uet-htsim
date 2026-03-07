---
description: How to run python scripts for htsim inside the correct environment
---

# Running Python Simulation Scripts

Whenever you need to run a Python script in this repository (e.g., `run.py` or `extract_ipynb_records.py`), you **MUST** execute it inside the `sim` micromamba environment.

## Execution Command

Do not run python directly as `python script.py`. Instead, use the `micromamba run` command:

```bash
micromamba run -n sim python <script_path> [arguments]
```

Example:

```bash
micromamba run -n sim python run.py experiments/SimpleTests/oblivious_trim_ecn.yaml
```

If you need to run a shell where the environment is activated (e.g., for invoking multiple python commands natively):
```bash
micromamba activate sim
```
(Note: when running single commands via the agent, `micromamba run -n sim ...` is highly preferred).
