@echo off
title Pete's Vinyl
REM Double-click this to start Pete's Vinyl. It opens in the browser at http://localhost:8000
cd /d "%~dp0"

if not exist "venv\Scripts\activate.bat" (
    echo Pete's Vinyl isn't installed yet. Running the installer first...
    call "%~dp0Install_PetesVinyl.bat"
)

call venv\Scripts\activate.bat

REM Start the server quietly in the background (no window to close by accident),
REM then open the browser once it's ready. If it's already running, this just opens the browser.
start "" venv\Scripts\pythonw.exe run.py

REM Fallback in case pythonw isn't available: start uvicorn directly and open the browser after 3s.
if errorlevel 1 (
    start /B uvicorn main:app --port 8000
    timeout /t 3 /nobreak >nul
    start "" http://localhost:8000
)
exit
