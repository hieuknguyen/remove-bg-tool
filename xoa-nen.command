#!/usr/bin/env bash
#
# TOOL XOA NEN ANH - ban cho macOS
#
# Cach dung: bo anh vao thu muc "input" roi nhay doi vao file nay trong Finder.
# Lan dau tien phai cap quyen chay:   chmod +x xoa-nen.command
#
# Che do co dinh: model u2net + cat sat chu the chua le.
#
# CHON MODEL quan trong hon chinh cac nguong mau:
#   u2net            - nhin ra do thuy tinh trong suot (dia, ly, chai), nhanh nhat.
#   birefnet-general - giu chi tiet bay (tim, tia nuoc, lap lanh) tot hon nhieu,
#                      NHUNG khong nhin ra do thuy tinh trong suot.
# Anh co chi tiet bay thi doi sang:
#   OPT="-m birefnet-general --keep-bright --bright-above auto"
#
# Muon doi thi sua bien OPT ben duoi, hoac truyen them co khi goi tu Terminal:
#   ./xoa-nen.command --pad 10

set -e

# Ve dung thu muc chua script (Finder mo Terminal o $HOME chu khong phai o day)
cd "$(dirname "$0")"

PY=".venv/bin/python3"

OPT="-m u2net"
CROP="--crop"

echo "============================================"
echo "   TOOL XOA NEN ANH"
echo "============================================"
echo "   Che do: do thuy tinh / vat the trong suot + cat sat chua le"
echo

# --- Dung moi truong Python neu chua co -------------------------------------
if [ ! -x "$PY" ]; then
  echo "Chua co moi truong Python rieng, dang tao..."

  if ! command -v python3 >/dev/null 2>&1; then
    echo
    echo "[LOI] Khong tim thay python3."
    echo "      Cai bang mot trong hai cach:"
    echo "        xcode-select --install"
    echo "        brew install python"
    echo
    read -r -n 1 -p "Nhan phim bat ky de dong..."
    exit 1
  fi

  python3 -m venv .venv
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r requirements.txt
  echo
  echo "Xong phan cai dat."
  echo
fi

mkdir -p input output

# --- Kiem tra co anh chua ---------------------------------------------------
count=$(find input -maxdepth 1 -type f \
  \( -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.png' -o -iname '*.webp' \
     -o -iname '*.bmp' -o -iname '*.tif' -o -iname '*.tiff' \) | wc -l | tr -d ' ')

if [ "$count" -eq 0 ]; then
  echo "[!] Thu muc \"input\" chua co anh nao."
  echo "    Bo anh vao do roi chay lai."
  echo
  read -r -n 1 -p "Nhan phim bat ky de dong..."
  exit 0
fi

echo "Tim thay $count anh. Dang xu ly (lan dau se tai model, hoi lau)..."
echo "Uoc tinh khoang 30 giay/anh."
echo

# Khong dat --overwrite: anh nao da co ket qua trong "output" se duoc bo qua,
# nen neu bi ngat giua chung thi chay lai la chay tiep, khong lam lai tu dau.
# Muon ep lam lai toan bo:  ./xoa-nen.command --overwrite
#
# "$@" cho phep truyen them co tu Terminal, vd: ./xoa-nen.command --pad 10
"$PY" remove_bg.py $OPT $CROP "$@"

echo
echo "Xong! Ket qua nam trong thu muc \"output\"."
open output 2>/dev/null || true

echo
read -r -n 1 -p "Nhan phim bat ky de dong..."
