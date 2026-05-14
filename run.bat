@echo off
title OATI Geoanalytics

REM Check Python availability
where python >nul 2>&1
if errorlevel 1 (
    where py >nul 2>&1
    if errorlevel 1 (
        echo.
        echo [ERROR] Python not found in PATH.
        echo.
        echo Install Python 3.10+ from https://www.python.org/downloads/
        echo During installation, check "Add Python to PATH".
        echo.
        pause
        exit /b 1
    ) else (
        py "%~dp0run.py"
    )
) else (
    python "%~dp0run.py"
)

if errorlevel 1 (
    echo.
    pause
)
