@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=.venv\Scripts\pythonw.exe
set PY_SETUP=.venv\Scripts\python.exe

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

"%PY_SETUP%" -c "import importlib.util, sys; sys.exit(0 if importlib.util.find_spec('PySide6') else 1)" >nul 2>&1
if errorlevel 1 (
    echo Dang cai thu vien giao dien Qt...
    "%PY_SETUP%" -m pip install --only-binary=:all: -r requirements-ui.txt
    if errorlevel 1 (
        echo [LOI] Khong cai duoc Qt. Kiem tra ket noi mang va mo lai ung dung.
        pause
        exit /b 1
    )
)

rem pythonw.exe: mo giao dien ma khong keo theo cua so console den phia sau
start "" "%PY%" "giao-dien.py"
