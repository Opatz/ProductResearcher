@echo off
title Erstinstallation und Setup - Item Researcher
cd /d "%~dp0"

echo ======================================================================
echo   ERSTINSTALLATION UND VORBEREITUNG (Item Researcher)
echo ======================================================================
echo.

:: 0. Ordner und Konfiguration sicherstellen
if not exist "input\raw" mkdir "input\raw"
if not exist "input\artikel" mkdir "input\artikel"
if not exist "output" mkdir "output"
if not exist "config\config.ini" (
    if exist "config\config.ini.example" copy "config\config.ini.example" "config\config.ini" >nul
)

:: 1. Python Check
echo [1/3] Pruefe Python-Installation...
where python >nul 2>&1
if %errorlevel% equ 0 goto :PYTHON_FOUND

where py >nul 2>&1
if %errorlevel% equ 0 goto :PYTHON_FOUND

echo.
echo ==================================================================
echo [FEHLER] Python wurde auf diesem Computer noch nicht gefunden!
echo ==================================================================
echo.
echo So installierst du Python mit 2 Klicks:
echo 1. Oeffne das Windows-Startmenue und suche nach "Microsoft Store".
echo 2. Tippe oben in die Suche "Python 3.12" ein.
echo 3. Klicke auf "Installieren" bzw. "Abrufen".
echo 4. Sobald die Installation fertig ist, starte dieses Setup erneut.
echo.
pause
exit /b 1

:PYTHON_FOUND
echo [OK] Python ist einsatzbereit!
echo.

:: 2. Requirements installieren
echo [2/3] Installiere erforderliche Erweiterungen...
echo Bitte kurz warten...
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if %errorlevel% equ 0 goto :REQ_OK

py -m pip install -r requirements.txt
if %errorlevel% equ 0 goto :REQ_OK

echo.
echo [FEHLER] Bei der Installation der Bibliotheken ist ein Fehler aufgetreten.
pause
exit /b 1

:REQ_OK
echo [OK] Alle Erweiterungen erfolgreich installiert!
echo.

:: 3. Verknuepfungen auf dem Desktop anlegen
echo [3/3] Erstelle bequeme Desktop-Verknuepfungen...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $d = [Environment]::GetFolderPath('Desktop'); $c = (Get-Location).Path; $s1 = $ws.CreateShortcut((Join-Path $d '1_Item_Scanner_Eingang.lnk')); $s1.TargetPath = (Join-Path $c 'input\raw'); $s1.Description = 'Hier Rohfotos und Videos ablegen'; $s1.Save(); $s2 = $ws.CreateShortcut((Join-Path $d '2_Starte_Analyse.lnk')); $s2.TargetPath = (Join-Path $c '2_Starte_Analyse.bat'); $s2.WorkingDirectory = $c; $s2.Description = 'Startet die KI-Artikelanalyse'; $s2.Save(); $s3 = $ws.CreateShortcut((Join-Path $d '3_Item_Scanner_Ergebnisse.lnk')); $s3.TargetPath = (Join-Path $c 'output'); $s3.Description = 'Hier liegen die fertigen Excel-Dateien'; $s3.Save();"

echo [OK] Folgende 3 Verknuepfungen wurden auf deinem Desktop angelegt:
echo.
echo   * 1_Item_Scanner_Eingang    - Hier legst du deine Fotos und Videos rein
echo   * 2_Starte_Analyse          - Doppelklick startet die Auswertung
echo   * 3_Item_Scanner_Ergebnisse - Hier findest du die fertigen Excel-Dateien
echo.
echo ======================================================================
echo   FERTIG! Die Einrichtung ist komplett abgeschlossen.
echo ======================================================================
echo.
pause
