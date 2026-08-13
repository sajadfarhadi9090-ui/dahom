@echo off
chcp 65001 >nul
title کلاس دهم - وب سایت (نسخه پایتون خالص)
cd /d "%~dp0"

echo ============================================
echo    وب سایت کلاس دهم - اجرا
echo ============================================
echo.

where python >nul 2>nul
if %errorlevel% neq 0 (
    echo [خطا] پایتون نصب نیست!
    echo از این آدرس نصب کنید: https://www.python.org/downloads/
    echo نکته مهم: گزینه «Add python.exe to PATH» را علامت بزنید.
    pause
    exit /b 1
)

if not exist venv (
    echo [1/3] در حال ساخت محیط مجازی...
    python -m venv venv
)
call venv\Scripts\activate.bat

echo [2/3] در حال نصب کتابخانه ها...
pip install -q -r requirements.txt

echo [3/3] در حال اجرای وب سایت...
echo.
echo وب سایت:     http://localhost:5000
echo پنل مدیریت:  http://localhost:5000/panel
echo.
start http://localhost:5000
python app.py

pause
