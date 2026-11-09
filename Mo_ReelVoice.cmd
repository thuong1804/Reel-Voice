@echo off
cd /d "%~dp0"
if exist "%~dp0.venv\Scripts\python.exe" (
  "%~dp0.venv\Scripts\python.exe" reel_voice.py
) else (
  python reel_voice.py
)
if errorlevel 1 pause
