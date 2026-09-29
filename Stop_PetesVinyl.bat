@echo off
REM Stops Pete's Vinyl if it is running in the background. (Restarting the PC does the same.)
cd /d "%~dp0"
if exist "logs\server.pid" (
    set /p PID=<logs\server.pid
    taskkill /PID %PID% /F >nul 2>&1
    del logs\server.pid
)
REM Belt and braces: stop whatever is still listening on port 8000 (an old copy left running).
powershell -NoProfile -Command "Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue | ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }"
echo Pete's Vinyl has been stopped.
timeout /t 3 >nul
