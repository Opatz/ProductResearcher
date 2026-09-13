@echo off
chcp 65001 >nul
title 🛠️ Erstinstallation & Setup - Item Researcher
cd /d "%~dp0"

echo ======================================================================
echo   🛠️ ERSTINSTALLATION & VORBEREITUNG (Item Researcher)
echo ======================================================================
echo.

:: 0. Ordner & Konfiguration sicherstellen
if not exist "input\raw" mkdir "input\raw"
if not exist "input\artikel" mkdir "input\artikel"
if not exist "output" mkdir "output"
if not exist "config\config.ini" (
    if exist "config\config.ini.example" copy "config\config.ini.example" "config\config.ini" >nul
)

:: 1. Python Check
echo [1/3] Prüfe Python-Installation...
where python >nul 2>&1
if %errorlevel% neq 0 (
    where py >nul 2>&1
    if %errorlevel% neq 0 (
        echo.
        echo ==================================================================
        echo [FEHLER] Python wurde auf diesem Computer noch nicht gefunden!
        echo ==================================================================
        echo.
        echo So installierst du Python mit 2 Klicks:
        echo 1. Öffne das Windows-Startmenü und öffne den "Microsoft Store".
        echo 2. Tippe oben in die Suche "Python 3.12" (oder "Python 3.11") ein.
        echo 3. Klicke auf "Installieren" (oder "Kostenlos / Abrufen").
        echo 4. Sobald der Download fertig ist, starte diese Datei hier einfach erneut!
        echo.
        pause
        exit /b 1
    )
)

echo [OK] Python ist einsatzbereit!
echo.

:: 2. Requirements installieren
echo [2/3] Installiere erforderliche Erweiterungen (Bibliotheken)...
echo (Dies kann beim ersten Mal 1-2 Minuten dauern...)
python -m pip install --upgrade pip >nul 2>&1
python -m pip install -r requirements.txt
if %errorlevel% neq 0 (
    py -m pip install -r requirements.txt
    if %errorlevel% neq 0 (
        echo.
        echo [FEHLER] Bei der Installation der Abhängigkeiten ist ein Fehler aufgetreten.
        pause
        exit /b 1
    )
)
echo [OK] Alle Erweiterungen erfolgreich installiert!
echo.

:: 3. Verknüpfungen auf dem Desktop anlegen
echo [3/3] Erstelle bequeme Desktop-Verknüpfungen...
powershell -NoProfile -ExecutionPolicy Bypass -Command "$ws = New-Object -ComObject WScript.Shell; $desktop = [Environment]::GetFolderPath('Desktop'); $curr = (Get-Location).Path; $s1 = $ws.CreateShortcut(\"$desktop\1_Item_Scanner_Eingang.lnk\"); $s1.TargetPath = \"$curr\input\raw\"; $s1.Description = 'Hier Rohfotos & Videos ablegen'; $s1.Save(); $s2 = $ws.CreateShortcut(\"$desktop\2_Starte_Analyse.lnk\"); $s2.TargetPath = \"$curr\2_Starte_Analyse.bat\"; $s2.WorkingDirectory = \"$curr\"; $s2.Description = 'Startet die KI-Artikelanalyse'; $s2.Save(); $s3 = $ws.CreateShortcut(\"$desktop\3_Item_Scanner_Ergebnisse.lnk\"); $s3.TargetPath = \"$curr\output\"; $s3.Description = 'Hier liegen die fertigen Excel-Dateien'; $s3.Save();"

echo [OK] Folgende 3 Verknüpfungen wurden auf deinem Desktop angelegt:
echo.
echo   📁 1_Item_Scanner_Eingang    -> Hier legst du deine Fotos & Videos rein
echo   ⚡ 2_Starte_Analyse          -> Doppelklick startet die Auswertung
echo   📊 3_Item_Scanner_Ergebnisse -> Hier findest du die fertigen Excel-Dateien
echo.
echo ======================================================================
echo   🎉 FERTIG! Die Einrichtung ist komplett abgeschlossen.
echo ======================================================================
echo.
pause
