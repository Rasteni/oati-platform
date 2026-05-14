#!/usr/bin/env python3
"""
ОАТИ · Геоаналитика — запускалка.

Создаёт виртуальное окружение, ставит зависимости, запускает сервер
и открывает браузер. Работает на Windows / macOS / Linux.

Использование:
    python run.py
"""
import os
import platform
import subprocess
import sys
import time
import venv
import webbrowser
from pathlib import Path

# На Windows консоль по умолчанию cp866 — заставляем Python писать в UTF-8
if platform.system() == "Windows":
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, Exception):
        pass

ROOT = Path(__file__).resolve().parent
VENV_DIR = ROOT / ".venv"
BACKEND_DIR = ROOT / "backend"
REQUIREMENTS = BACKEND_DIR / "requirements.txt"
PORT = 8000
URL = f"http://localhost:{PORT}"

IS_WIN = platform.system() == "Windows"
PYTHON_IN_VENV = VENV_DIR / ("Scripts" if IS_WIN else "bin") / ("python.exe" if IS_WIN else "python")
PIP_IN_VENV = VENV_DIR / ("Scripts" if IS_WIN else "bin") / ("pip.exe" if IS_WIN else "pip")


def log(msg: str):
    print(f"[*] {msg}")


def err(msg: str):
    print(f"[!] {msg}", file=sys.stderr)


def check_python_version():
    if sys.version_info < (3, 10):
        err(f"Нужен Python 3.10+, у вас {sys.version_info.major}.{sys.version_info.minor}")
        sys.exit(1)


def ensure_venv():
    if VENV_DIR.exists() and PYTHON_IN_VENV.exists():
        log(f"Виртуальное окружение уже создано: {VENV_DIR}")
        return
    log("Создаю виртуальное окружение (~10 сек)...")
    venv.create(VENV_DIR, with_pip=True, clear=False)
    log("Готово.")


def install_requirements():
    # Проверяем, установлен ли uvicorn — если да, считаем что зависимости уже стоят
    check = subprocess.run(
        [str(PYTHON_IN_VENV), "-c", "import fastapi, sqlalchemy, pandas, openpyxl, numpy"],
        capture_output=True,
    )
    if check.returncode == 0:
        log("Зависимости уже установлены.")
        return

    log("Устанавливаю зависимости (это займёт 1–3 минуты при первом запуске)...")
    proc = subprocess.run(
        [str(PYTHON_IN_VENV), "-m", "pip", "install", "--upgrade", "pip"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        err("Не удалось обновить pip:")
        print(proc.stderr)

    proc = subprocess.run(
        [str(PYTHON_IN_VENV), "-m", "pip", "install", "-r", str(REQUIREMENTS)],
        text=True,
    )
    if proc.returncode != 0:
        err("Установка пакетов завершилась с ошибкой. См. вывод выше.")
        sys.exit(1)
    log("Зависимости установлены.")


def open_browser_later():
    """Открыть браузер через 2.5 сек после старта uvicorn."""
    import threading
    def _open():
        time.sleep(2.5)
        try:
            webbrowser.open(URL)
        except Exception:
            pass
    threading.Thread(target=_open, daemon=True).start()


def run_server():
    log(f"Запускаю сервер на {URL}")
    log("Для остановки нажмите Ctrl+C")
    print()
    env = os.environ.copy()
    # PYTHONPATH чтобы импорты "app.xxx" работали из backend/
    env["PYTHONPATH"] = str(BACKEND_DIR)
    open_browser_later()
    try:
        subprocess.run(
            [str(PYTHON_IN_VENV), "-m", "uvicorn", "app.main:app",
             "--host", "127.0.0.1", "--port", str(PORT)],
            cwd=str(BACKEND_DIR),
            env=env,
        )
    except KeyboardInterrupt:
        print()
        log("Сервер остановлен.")


def main():
    print()
    print("=" * 60)
    print("  ОАТИ · Геоаналитика — локальный запуск")
    print("=" * 60)
    print()
    check_python_version()
    ensure_venv()
    install_requirements()
    print()
    run_server()


if __name__ == "__main__":
    main()
