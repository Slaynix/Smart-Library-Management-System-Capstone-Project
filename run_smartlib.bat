@echo off
title SmartLib - Library Management System
cd /d "%~dp0"

if not exist "venv\\Scripts\\python.exe" (
    echo Creating Python virtual environment...
    py -m venv venv
)

echo Activating environment...
call venv\\Scripts\\activate.bat

echo Installing required packages...
python -m pip install --upgrade pip
pip install -r requirements.txt

echo.
echo Starting SmartLib...
echo Open http://127.0.0.1:5000 in your browser.
echo Login: use ADMIN_USERNAME and ADMIN_PASSWORD from your private .env file.
echo.
python app.py

pause
