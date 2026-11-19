@echo off
rem One-click launcher for the QA tool. First run installs everything (needs internet, a few minutes).
cd /d "%~dp0"

rem A second copy can't take port 8000, and the browser would quietly open the old one with old code.
netstat -ano | findstr /r /c:":8000 .*LISTENING" >nul && goto :running

if not exist ".venv\Scripts\python.exe" (
    rem An older Python would still make .venv, then pip refuses the project and every later run fails.
    python -c "import sys; sys.exit(sys.version_info < (3, 12))" || goto :nopython
    echo Setting up the QA tool for the first time...
    python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
)

rem Install only when pyproject.toml changed (first run, or an update added packages); the copy records what is installed.
fc /b pyproject.toml .venv\installed-pyproject.toml >nul 2>&1 || (
    echo Installing packages...
    ".venv\Scripts\python.exe" -m pip install --quiet -e . || goto :failed
    ".venv\Scripts\python.exe" -m playwright install chromium || goto :failed
    copy /y pyproject.toml .venv\installed-pyproject.toml >nul
)

echo Starting the QA tool at http://127.0.0.1:8000  (close this window to stop it)
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:running
echo The QA tool is already running (or another program is using port 8000).
echo Close the other QA tool window first, then run start.bat again.
pause
goto :eof

:nopython
echo Python 3.12 or newer is needed. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
pause
goto :eof

:failed
echo Setup failed. Check your internet connection and run start.bat again.
pause
