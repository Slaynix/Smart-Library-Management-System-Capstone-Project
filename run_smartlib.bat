@echo off
title SmartLib - Library Management System
cd /d "%~dp0"

echo ============================================================
echo   SMARTLIB - Starting Server...
echo   Open http://127.0.0.1:5000 or http://localhost:5000
echo ============================================================
echo.

python app.py
if errorlevel 1 (
    echo.
    echo [!] Trying py launcher...
    py app.py
)

pause
