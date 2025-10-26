from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT / "results"

print(ROOT)
print(RESULTS_DIR)
