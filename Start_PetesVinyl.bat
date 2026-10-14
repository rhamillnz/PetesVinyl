@echo off
title Pete's Vinyl
REM Double-click this to start Pete's Vinyl. It opens in Chrome (or Edge) at http://localhost:8000
cd /d "%~dp0"

REM If the install is missing or broken (e.g. an install that didn't finish), repair it first.
"venv\Scripts\python.exe" -c "import fastapi, uvicorn, pydantic, httpx" >nul 2>&1
if errorlevel 1 (
    echo Pete's Vinyl needs to finish installing. Running the installer first...
    call "%~dp0Install_PetesVinyl.bat"
    "venv\Scripts\python.exe" -c "import fastapi, uvicorn, pydantic, httpx" >nul 2>&1
    if errorlevel 1 exit /b 1
)

REM Start the server quietly in the background (no window to close by accident) and open the app window.
REM If it's already running, this just opens the window (or restarts it after an update).
start "" "venv\Scripts\pythonw.exe" run.py
exit
