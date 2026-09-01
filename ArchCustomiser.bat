@echo off
rem ---------------------------------------------------------------------
rem  ArchCustomiser starten -- einfach doppelklicken.
rem
rem  Wechselt ins Programmverzeichnis (auch wenn die Datei von woanders
rem  aufgerufen wird) und startet die Oberflaeche mit dem Python aus dem
rem  projekteigenen .venv.
rem ---------------------------------------------------------------------

cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo.
    echo   Die Programmumgebung fehlt.
    echo   Einmalig einrichten mit:
    echo.
    echo       python -m venv .venv
    echo       .venv\Scripts\pip install -e ".[dev]"
    echo.
    pause
    exit /b 1
)

rem pythonw statt python: startet die Oberflaeche ohne zusaetzliches
rem schwarzes Konsolenfenster daneben.
start "" ".venv\Scripts\pythonw.exe" -m archcustomiser
