#!/usr/bin/env bash
set -e

cd "$(dirname "$0")"

# Ищем python
if command -v python3 >/dev/null 2>&1; then
    PYTHON=python3
elif command -v python >/dev/null 2>&1; then
    PYTHON=python
else
    echo ""
    echo "[ERROR] Python не найден."
    echo ""
    echo "macOS:  brew install python@3.12"
    echo "Linux:  sudo apt install python3 python3-venv"
    echo ""
    exit 1
fi

exec "$PYTHON" run.py
