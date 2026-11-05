@echo off
setlocal
cd /d "%~dp0"
title Ecommerce Customer Service Agent

if not exist ".venv\Scripts\python.exe" (
    echo [ERROR] .venv not found.
    echo Please create the virtual environment first, then re-run this file.
    pause
    exit /b 1
)

netstat -ano | findstr /C:":8000 " | findstr /I "LISTENING" >nul
if not errorlevel 1 (
    echo Server is already running at http://127.0.0.1:8000/web/
    if /i not "%~1"=="--no-browser" start "" http://127.0.0.1:8000/web/
    timeout /t 2 >nul
    exit /b 0
)

echo Starting server...
echo Buyer:    http://127.0.0.1:8000/web/
echo Merchant: http://127.0.0.1:8000/web/#merchant
echo Press Ctrl+C in this window to stop.
echo.

if /i not "%~1"=="--no-browser" (
    start "open-browser" /min cmd /c "timeout /t 3 /nobreak >nul & start http://127.0.0.1:8000/web/"
)

".venv\Scripts\python.exe" -m uvicorn main:app --host 127.0.0.1 --port 8000
echo.
echo Server stopped. Press any key to close this window...
pause >nul
