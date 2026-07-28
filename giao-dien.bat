@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=.venv\Scripts\pythonw.exe

if not exist "%PY%" (
    echo [LOI] Chua co moi truong Python tai .venv
    echo       Tao bang lenh:
    echo           python -m venv .venv
    echo           .venv\Scripts\python.exe -m pip install -r requirements.txt
    echo.
    pause
    exit /b 1
)

if not exist "input" mkdir "input"
if not exist "output" mkdir "output"

rem pythonw.exe: mo giao dien ma khong keo theo cua so console den phia sau
start "" "%PY%" "giao-dien.py"
