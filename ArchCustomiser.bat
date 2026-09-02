@echo off
rem ---------------------------------------------------------------------
rem  ArchCustomiser -- einfach doppelklicken.
rem
rem  Diese Datei richtet beim ersten Mal alles selbst ein und startet danach
rem  nur noch. Sie setzt nichts voraus ausser Python.
rem
rem  Wichtig: JEDER Fehlerweg endet mit "pause". Frueher pruefte diese Datei
rem  nur, ob die Programmumgebung existiert -- fehlte darin das Programm
rem  selbst, startete pythonw.exe, scheiterte an einem fehlenden Modul und
rem  schrieb nirgendwohin: kein Fenster, keine Meldung, kein Protokoll.
rem  Genau dieser Fall war der wahrscheinlichste Anfaengerfehler.
rem ---------------------------------------------------------------------

setlocal
cd /d "%~dp0"

set "VENV_PY=.venv\Scripts\python.exe"
set "VENV_PYW=.venv\Scripts\pythonw.exe"

rem -- 1. Python finden -------------------------------------------------
rem  "py -3" zuerst: ein blankes "python" oeffnet unter Windows sonst den
rem  Microsoft Store, und dessen Python legt die Umgebung woanders an.
set "PYTHON="
py -3 --version >nul 2>&1
if not errorlevel 1 set "PYTHON=py -3"

if not defined PYTHON (
    python --version >nul 2>&1
    if not errorlevel 1 set "PYTHON=python"
)

if not defined PYTHON (
    echo.
    echo   Python wurde nicht gefunden.
    echo.
    echo   ArchCustomiser braucht Python 3.11 oder neuer.
    echo   Die Download-Seite wird jetzt geoeffnet.
    echo.
    echo   Bitte bei der Installation den Haken
    echo   "Add Python to PATH" setzen und danach diese Datei erneut
    echo   doppelklicken.
    echo.
    start "" "https://www.python.org/downloads/windows/"
    pause
    exit /b 1
)

rem -- 2. Version pruefen -----------------------------------------------
%PYTHON% -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Die gefundene Python-Fassung ist zu alt.
    echo.
    %PYTHON% --version
    echo   Gebraucht wird 3.11 oder neuer.
    echo.
    start "" "https://www.python.org/downloads/windows/"
    pause
    exit /b 1
)

rem -- 3. Programmumgebung anlegen, falls sie fehlt ----------------------
rem  Windows bricht bei Pfaden ueber 260 Zeichen ab, und die Programmumgebung
rem  legt tief verschachtelte Verzeichnisse an. Ein Ordner weit unten in
rem  "Dokumente\Projekte\..." reicht dafuer schon aus.
rem  Ohne Schleife: eine Zaehlschleife schiede hier aus, weil ein "goto"
rem  aus einem Klammerblock heraus in cmd sein Sprungziel nicht findet.
rem  %VAR:~120% ist leer, solange der Wert kuerzer als 120 Zeichen ist.
set "HIER=%~dp0"
if not "%HIER:~120%"=="" (
    echo.
    echo   Hinweis: Der Pfad zu diesem Ordner ist sehr lang.
    echo   Windows kann dann beim Einrichten abbrechen. Falls das
    echo   passiert: den Ordner naeher an die Wurzel verschieben,
    echo   etwa nach C:\ArchCustomiser.
    echo.
)

if not exist "%VENV_PY%" (
    echo.
    echo   Einmalige Einrichtung. Das dauert ein paar Minuten und laedt
    echo   rund 670 MB -- danach startet das Programm sofort.
    echo.
    %PYTHON% -m venv .venv
    if errorlevel 1 (
        rem  Eine halb angelegte Umgebung ist schlimmer als gar keine: der
        rem  naechste Start haelt sie fuer fertig und scheitert dann an einer
        rem  ganz anderen Stelle. Deshalb hier wieder wegraeumen.
        rmdir /s /q ".venv" 2>nul
        echo.
        echo   Die Programmumgebung liess sich nicht anlegen.
        echo   Die Meldung darueber sagt, woran es lag. Haeufig ist es:
        echo     - der Pfad zu diesem Ordner ist zu lang
        echo     - kein Schreibrecht in diesem Ordner
        echo     - die Festplatte ist voll
        echo.
        pause
        exit /b 1
    )
)

rem -- 4. Traegt die Umgebung? ------------------------------------------
rem  Das ist die eigentliche Neuerung: pruefen statt hoffen. Der Test deckt
rem  beides ab -- die erste Einrichtung und ein "git pull", das eine neue
rem  Abhaengigkeit mitgebracht hat.
"%VENV_PY%" -c "import archcustomiser, PySide6" >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Abhaengigkeiten werden installiert ...
    echo.
    "%VENV_PY%" -m pip install --upgrade pip >nul 2>&1
    "%VENV_PY%" -m pip install -e ".[dev]"
    if errorlevel 1 (
        echo.
        echo   Die Installation ist fehlgeschlagen.
        echo.
        echo   Die Meldungen darueber sagen, woran es lag.
        echo   Haeufig ist es eine fehlende Internetverbindung.
        echo.
        pause
        exit /b 1
    )

    rem  Noch einmal pruefen -- pip kann melden, fertig zu sein, ohne dass
    rem  sich das Programm danach importieren laesst.
    "%VENV_PY%" -c "import archcustomiser, PySide6" >nul 2>&1
    if errorlevel 1 (
        echo.
        echo   Die Installation lief durch, das Programm laesst sich aber
        echo   trotzdem nicht laden. Die genaue Meldung:
        echo.
        "%VENV_PY%" -c "import archcustomiser, PySide6"
        echo.
        pause
        exit /b 1
    )
    echo.
    echo   Fertig eingerichtet.
    echo.
)

rem -- 5. Starten --------------------------------------------------------
rem  pythonw statt python: kein zusaetzliches schwarzes Fenster daneben.
rem  Abstuerze bleiben trotzdem sichtbar -- __main__.py setzt dafuer einen
rem  eigenen Ausnahmehaken, der ein Fenster zeigt und ins Protokoll schreibt.
if not exist "%VENV_PYW%" (
    echo.
    echo   pythonw.exe fehlt in der Programmumgebung.
    echo   Am einfachsten: den Ordner .venv loeschen und diese Datei
    echo   erneut doppelklicken.
    echo.
    pause
    exit /b 1
)

start "" "%VENV_PYW%" -m archcustomiser
exit /b 0

