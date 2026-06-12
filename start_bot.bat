@echo off
title Fayda ID Bot
color 0A

echo ============================================
echo    Fayda ID Telegram Bot - Launcher
echo ============================================
echo.

python --version >nul 2>&1
if errorlevel 1 (
    echo [ERROR] Python not found!
    echo Install from: https://www.python.org/downloads/
    pause
    exit /b 1
)

if not exist "venv" (
    echo [*] Creating virtual environment...
    python -m venv venv
)

echo [*] Installing dependencies...
venv\Scripts\python.exe -m pip install -r requirements.txt --quiet --no-warn-script-location
echo [OK] Ready.

echo.
echo ============================================
echo  Bot is RUNNING. Do NOT close this window.
echo  Press Ctrl+C to stop.
echo ============================================
echo.

:loop
venv\Scripts\python.exe bot.py
echo.
echo [!] Restarting in 5 seconds... (Ctrl+C to exit)
timeout /t 5 >nul
goto loop
