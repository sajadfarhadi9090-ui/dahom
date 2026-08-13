#!/usr/bin/env bash
# اجرای وب‌سایت در مک / لینوکس (نسخه پایتون خالص)
cd "$(dirname "$0")"

echo "وب سایت کلاس دهم - اجرا"
if ! command -v python3 &>/dev/null; then
  echo "[خطا] پایتون نصب نیست."
  exit 1
fi

if [ ! -d "venv" ]; then
  echo "[1/3] ساخت محیط مجازی..."
  python3 -m venv venv
fi
source venv/bin/activate

echo "[2/3] نصب کتابخانه‌ها..."
pip install -q -r requirements.txt

echo "[3/3] اجرا... سایت: http://localhost:5000  |  پنل: http://localhost:5000/panel"
python app.py
