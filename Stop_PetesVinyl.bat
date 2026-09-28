@echo off
REM Stops Pete's Vinyl if it is running in the background. (Restarting the PC does the same.)
cd /d "%~dp0"
if not exist "logs\server.pid" goto notrunning
set /p PID=<logs\server.pid
taskkill /PID %PID% /F >nul 2>&1
del logs\server.pid
echo Pete's Vinyl has been stopped.
goto end
:notrunning
echo Pete's Vinyl doesn't seem to be running.
:end
timeout /t 3 >nul
