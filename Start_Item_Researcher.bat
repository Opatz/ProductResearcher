@echo off
title Item Research and Marketplace Studio
cd /d "%~dp0"

echo ======================================================================
echo   Starting Item Research and Marketplace Studio...
echo ======================================================================
echo.
python main.py --review-ui
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to launch with 'python'. Trying 'py'...
    py main.py --review-ui
)
pause
