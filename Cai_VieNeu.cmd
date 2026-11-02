@echo off
cd /d "%~dp0"
python -m venv .venv-vieneu
if errorlevel 1 goto failed
.venv-vieneu\Scripts\python.exe -m pip install "vieneu==3.8.2"
if errorlevel 1 goto failed
.venv-vieneu\Scripts\python.exe -u vieneu_runner.py --setup
if errorlevel 1 goto failed
echo Da cai VieNeu. Hay dong va mo lai Reel Voice.
pause
exit /b 0
:failed
echo Cai dat chua thanh cong. Xem loi ben tren.
pause
exit /b 1
