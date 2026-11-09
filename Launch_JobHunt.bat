@echo off
title JobHunt OS Morning Triage
echo ===================================================
echo   Starting JobHunt OS... 
echo   Initializing virtual environment and Streamlit...
echo ===================================================
cd /d "%~dp0"

REM Activate virtual environment if it exists
if exist ".venv\Scripts\activate.bat" (
    echo Activating .venv virtual environment...
    call .venv\Scripts\activate.bat
) else if exist "venv\Scripts\activate.bat" (
    echo Activating venv virtual environment...
    call venv\Scripts\activate.bat
) else if exist ".venv\Scripts\activate" (
    call .venv\Scripts\activate
) else if exist "venv\Scripts\activate" (
    call venv\Scripts\activate
) else (
    echo Using system Python environment...
)

REM Launch the dashboard
echo Launching Streamlit dashboard (app.py)...
echo Press Ctrl+C in this terminal window to stop the server.
echo.

python -m streamlit run app.py

REM Keep window open if it crashes or terminates
echo.
echo ===================================================
echo [NOTICE] Streamlit server stopped.
echo ===================================================
pause
