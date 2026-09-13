@echo off
title Item Research & Marketplace Studio
echo ======================================================================
echo   🏛️ Starting Item Research & Marketplace Studio...
echo ======================================================================
echo.
python main.py --review-ui
if %errorlevel% neq 0 (
    echo.
    echo [ERROR] Failed to launch with 'python'. Trying 'py'...
    py main.py --review-ui
)
pause
