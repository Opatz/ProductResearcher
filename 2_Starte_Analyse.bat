@echo off
chcp 65001 >nul
title 🤖 Item Researcher - Analyse & Bewertung
cd /d "%~dp0"

echo ======================================================================
echo   🤖 ITEM RESEARCHER - ANALYSE WIRD GESTARTET
echo ======================================================================
echo.
echo Verarbeite abgelegte Fotos und Videos aus dem Eingangsordner...
echo Bitte warte, bis die KI-Analyse abgeschlossen ist.
echo.

python main.py
set EXIT_CODE=%errorlevel%

if %EXIT_CODE% neq 0 (
    echo.
    echo [HINWEIS] Versuche Start mit 'py'...
    py main.py
    set EXIT_CODE=%errorlevel%
)

echo.
echo ======================================================================
if %EXIT_CODE% equ 0 (
    echo   🎉 ANALYSE ERFOLGREICH BEENDET!
    echo   Öffne den Ergebnis-Ordner mit den fertigen Excel-Dateien...
    echo ======================================================================
    start "" "%~dp0output"
) else (
    echo   ❌ Es ist ein Fehler während der Ausführung aufgetreten.
    echo ======================================================================
)
echo.
pause
