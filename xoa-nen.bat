@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

rem Che do co dinh: [5] giu chi tiet bay o phia tren + [1] cat sat chua le deu.
rem Muon doi thi sua 2 dong duoi, hoac truyen them co:  xoa-nen.bat --pad 10
set OPT=--keep-bright --bright-above auto
set CROP=--crop

echo ============================================
echo    TOOL XOA NEN ANH
echo ============================================
echo    Che do: chi tiet bay o tren + cat sat chua le
echo.

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

echo Dang xu ly...
echo.

rem Khong dat --overwrite: anh da co ket qua se duoc bo qua, nen bi ngat giua
rem chung thi chay lai la chay tiep. Muon lam lai tu dau: xoa-nen.bat --overwrite
"%PY%" "remove_bg.py" %OPT% %CROP% %*

echo.
echo Xong! Ket qua nam trong thu muc "output".
pause
