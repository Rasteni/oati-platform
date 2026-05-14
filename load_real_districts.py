#!/usr/bin/env python3
"""
Загружает реальные границы округов Москвы из OSM.
Использует тот же venv, что и run.py.
"""
import platform
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
IS_WIN = platform.system() == "Windows"
PYTHON_IN_VENV = VENV_DIR / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")

if not PYTHON_IN_VENV.exists():
    print("[!] Сначала запустите run.py / run.bat / run.sh, чтобы создать виртуальное окружение.")
    sys.exit(1)

env = {"PYTHONPATH": str(ROOT / "backend")}
import os
env.update(os.environ)

result = subprocess.run(
    [str(PYTHON_IN_VENV), "-m", "app.scripts.load_real_districts"],
    cwd=str(ROOT / "backend"),
    env=env,
)
sys.exit(result.returncode)
