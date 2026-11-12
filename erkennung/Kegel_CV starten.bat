@echo off
REM ===========================================================================
REM  Kegel_CV starten -- zum Doppelklicken.
REM
REM  Wechselt ins Projektverzeichnis (auch wenn die Verknuepfung woanders
REM  liegt: %~dp0 ist der Ordner DIESER Datei) und startet die Oberflaeche
REM  mit dem Python aus der venv.
REM
REM  Das Fenster bleibt bei einem Fehler offen -- sonst waere die Meldung weg,
REM  bevor man sie lesen kann, und genau die braucht man dann.
REM ===========================================================================

cd /d "%~dp0"
title Kegel_CV

if not exist ".venv\Scripts\python.exe" (
    echo.
    echo   FEHLER: .venv\Scripts\python.exe nicht gefunden.
    echo.
    echo   Erwartet wurde die virtuelle Umgebung im Projektordner:
    echo   %CD%\.venv
    echo.
    echo   Anlegen mit:
    echo       python -m venv .venv
    echo       .venv\Scripts\python.exe -m pip install -e .
    echo.
    pause
    exit /b 1
)

echo   Kegel_CV startet ...
echo   Projektordner: %CD%
echo.

".venv\Scripts\python.exe" -m kegel_cv.main

if errorlevel 1 (
    echo.
    echo   ============================================================
    echo   Die Anwendung wurde mit einem Fehler beendet.
    echo   Einzelheiten stehen in:  debug\kegel_cv.log
    echo   ============================================================
    echo.
    pause
    exit /b 1
)
