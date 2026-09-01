@echo off
cd /d "%~dp0"
set PYTHONPATH=src
set PERSONA_CHAT_HOST=127.0.0.1
if exist ".venv\Scripts\python.exe" (
    set "PYTHON_EXE=.venv\Scripts\python.exe"
) else (
    set "PYTHON_EXE=python"
)

echo Starting Persona AI Server (Web / PC only)...
echo   Browser: http://127.0.0.1:8765
echo   HP Android app uses its own backend on the phone — no PC server needed.
"%PYTHON_EXE%" -m persona_ai.web.server --port 8765
pause
