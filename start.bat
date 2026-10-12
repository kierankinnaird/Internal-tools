@echo off
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo First run: setting up...
    py -3 -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :error
)
".venv\Scripts\python.exe" run.py
goto :eof
:error
echo Setup failed. Check python is installed and you are online for this first run.
pause