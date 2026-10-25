@echo off
title SmartLib - Library Management System
cd /d "%~dp0"

echo ============================================================
echo   SMARTLIB - Library Management System
echo   Server URL: http://127.0.0.1:5000
echo ============================================================
echo.

if exist "venv\Scripts\python.exe" (
    echo [*] Using virtual environment Python...
    venv\Scripts\python.exe app.py
) else if exist ".venv\Scripts\python.exe" (
    echo [*] Using virtual environment Python...
    .venv\Scripts\python.exe app.py
) else (
    echo [*] Using system Python...
    python app.py
    if errorlevel 1 (
        echo [!] Trying py launcher...
        py app.py
    )
)

pause
