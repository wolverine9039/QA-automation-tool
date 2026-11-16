@echo off
rem One-click launcher for the QA tool. First run installs everything (needs internet, a few minutes).
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
    echo Setting up the QA tool for the first time...
    python -m venv .venv || goto :nopython
    ".venv\Scripts\python.exe" -m pip install --quiet --upgrade pip
    ".venv\Scripts\python.exe" -m pip install --quiet -e . || goto :failed
    ".venv\Scripts\python.exe" -m playwright install chromium || goto :failed
)

echo Starting the QA tool at http://127.0.0.1:8000  (close this window to stop it)
start "" http://127.0.0.1:8000
".venv\Scripts\python.exe" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
goto :eof

:nopython
echo Python 3.12 or newer is needed. Install it from https://www.python.org/downloads/ and tick "Add python.exe to PATH".
pause
goto :eof

:failed
echo Setup failed. Check your internet connection, delete the .venv folder and run start.bat again.
pause
