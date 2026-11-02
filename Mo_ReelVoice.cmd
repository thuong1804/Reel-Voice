@echo off
cd /d "%~dp0"
python reel_voice.py
if errorlevel 1 pause
