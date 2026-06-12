@echo off
title Fayda ID Bot - Clean Install
color 0E

echo [*] Removing old venv...
if exist "venv" rmdir /s /q venv

echo [*] Creating fresh virtual environment...
python -m venv venv

echo [*] Installing dependencies...
venv\Scripts\python.exe -m pip install -r requirements.txt --no-warn-script-location
echo [OK] Done!

echo.
echo ============================================
echo  Bot is RUNNING. Do NOT close this window.
echo ============================================
echo.

:loop
venv\Scripts\python.exe bot.py
echo [!] Restarting in 5 seconds... (Ctrl+C to exit)
timeout /t 5 >nul
goto loop
