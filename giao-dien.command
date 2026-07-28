#!/usr/bin/env bash
#
# Mo giao dien do hoa cua tool xoa nen - ban cho macOS
#
# Lan dau tien phai cap quyen chay:   chmod +x giao-dien.command
# Sau do nhay doi vao file nay trong Finder.

set -e

cd "$(dirname "$0")"

PY=".venv/bin/python3"

echo "Dang mo giao dien xoa nen anh..."

# --- Dung moi truong Python neu chua co -------------------------------------
if [ ! -x "$PY" ]; then
  echo "Chua co moi truong Python rieng, dang tao..."

  if ! command -v python3 >/dev/null 2>&1; then
    echo
    echo "[LOI] Khong tim thay python3. Cai bang mot trong hai cach:"
    echo "        xcode-select --install"
    echo "        brew install python"
    echo
    read -r -n 1 -p "Nhan phim bat ky de dong..."
    exit 1
  fi

  python3 -m venv .venv
  "$PY" -m pip install --upgrade pip
  "$PY" -m pip install -r requirements.txt
  echo "Xong phan cai dat."
  echo
fi

# --- tkinter co san khong? --------------------------------------------------
# Python cai qua Homebrew thuong THIEU tkinter, phai cai them goi rieng.
if ! "$PY" -c "import tkinter" >/dev/null 2>&1; then
  echo
  echo "[LOI] Ban Python nay thieu tkinter nen khong mo duoc giao dien."
  echo "      Cach xu ly:"
  echo "        brew install python-tk"
  echo "      roi xoa thu muc .venv va chay lai file nay."
  echo
  echo "      Hoac dung ban khong giao dien:  ./xoa-nen.command"
  echo
  read -r -n 1 -p "Nhan phim bat ky de dong..."
  exit 1
fi

mkdir -p input output

"$PY" giao-dien.py
