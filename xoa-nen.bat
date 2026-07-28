@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PY=.venv\Scripts\python.exe

rem Che do co dinh: model u2net + cat sat chua le deu.
rem CHON MODEL quan trong hon chinh cac nguong mau:
rem   u2net            - nhin ra do thuy tinh trong suot (dia, ly, chai), nhanh nhat
rem   birefnet-general - giu chi tiet bay (tim, tia nuoc, lap lanh) tot hon nhieu,
rem                      NHUNG khong nhin ra do thuy tinh trong suot
rem Anh co chi tiet bay thi doi dong OPT thanh:
rem   set OPT=-m birefnet-general --keep-bright --bright-above auto
rem Muon doi thi sua 2 dong duoi, hoac truyen them co:  xoa-nen.bat --pad 10
set OPT=-m u2net
set CROP=--crop

echo ============================================
echo    TOOL XOA NEN ANH
echo ============================================
echo    Che do: do thuy tinh / vat the trong suot + cat sat chua le
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
