
import os
import sys
import shutil
import datetime
import subprocess
import yaml
import glob
from pathlib import Path

def get_git_info():
    """获取当前的 git 信息"""
    info = {
        "commit": "unknown",
        "author": "unknown",
        "date": "unknown",
        "message": "unknown",
        "branch": "unknown",
        "status": "unknown"
    }
    try:
        # Commit Hash
        info["commit"] = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
        
        # Detailed Log
        log_format = "%an|%ad|%s"
        log_output = subprocess.check_output(["git", "log", "-1", f"--pretty=format:{log_format}"], text=True).strip()
        parts = log_output.split("|", 2)
        if len(parts) == 3:
            info["author"] = parts[0]
            info["date"] = parts[1]
            info["message"] = parts[2]
            
        # Branch
        info["branch"] = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
        
        # Status (Changed files)
        info["status"] = subprocess.check_output(["git", "status", "--porcelain"], text=True).strip()
        
    except Exception as e:
        print(f"[Warn] Failed to get git info: {e}")
        
    return info

def main():
    # 1. 基础配置
    ROOT_DIR = Path(__file__).parent.absolute()
    ARCHIVE_ROOT = ROOT_DIR / "archive"
    EXPERIMENTS_DIR = ROOT_DIR / "experiments"
    RESULTS_DIR = ROOT_DIR / "results"
    
    # 2. 生成归档目录名 (YYMMDD-HHMMSS)
    timestamp = datetime.datetime.now().strftime("%y%m%d-%H%M%S")
    target_dir = ARCHIVE_ROOT / timestamp
    
    print(f"[Info] Starting archive process...")
    print(f"[Info] Target Directory: {target_dir}")
    
    if target_dir.exists():
        print(f"[Error] Target directory {target_dir} already exists!")
        sys.exit(1)
        
    target_dir.mkdir(parents=True)
    
    # 3. 复制目录 (experiments, results)
    # Ignore compiled/temp files if needed, but current requirement is "all content"
    # We might want to use ignore_patterns to skip __pycache__ etc.
    ignore_func = shutil.ignore_patterns("__pycache__", ".git", ".vscode", "*.pyc")
    
    tasks = [
        ("experiments", EXPERIMENTS_DIR),
        ("results", RESULTS_DIR)
    ]
    
    for name, src_path in tasks:
        if src_path.exists():
            print(f"[Copy] {name} -> {target_dir / name}")
            shutil.copytree(src_path, target_dir / name, ignore=ignore_func)
        else:
            print(f"[Warn] {name} directory not found at {src_path}")

    # 4. 复制 *.ipynb 文件
    notebooks = list(ROOT_DIR.glob("*.ipynb"))
    if notebooks:
        print(f"[Copy] Found {len(notebooks)} notebooks")
        for nb in notebooks:
            print(f"  - {nb.name}")
            shutil.copy2(nb, target_dir / nb.name)
            
    # 5. 生成 manifest.yaml
    manifest = {
        "timestamp": datetime.datetime.now().isoformat(),
        "archived_timestamp_id": timestamp,
        "git": get_git_info(),
        "contents": {
            "experiments": EXPERIMENTS_DIR.exists(),
            "results": RESULTS_DIR.exists(),
            "notebooks": [nb.name for nb in notebooks]
        }
    }
    
    manifest_path = target_dir / "manifest.yaml"
    with open(manifest_path, "w", encoding="utf-8") as f:
        yaml.dump(manifest, f, allow_unicode=True, sort_keys=False)
        
    print(f"[Info] Archive completed successfully!")
    print(f"[Info] Saved to: {target_dir}")

if __name__ == "__main__":
    main()
