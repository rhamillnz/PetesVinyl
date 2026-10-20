@echo off
REM Update Pete's Vinyl: gets the latest version from GitHub, installs any new parts, and restarts the app.
REM Your records, photos and keys are never touched (they aren't part of the download).
REM This file copies itself to the temp folder first, because the update can replace THIS file while it runs.
if /i "%~f0"=="%TEMP%\pv_update_run.bat" goto run
copy /y "%~f0" "%TEMP%\pv_update_run.bat" >nul
call "%TEMP%\pv_update_run.bat" "%~dp0"
exit /b

:run
setlocal EnableExtensions
title Updating Pete's Vinyl
cd /d "%~1"
set "APPDIR=%CD%"
set "OLD="
set "NEW="
echo.
echo  ============  Updating Pete's Vinyl  ============
echo.

REM --- 1. Git is needed to fetch the update.
git --version >nul 2>&1
if errorlevel 1 goto nogit

REM --- 2. Is this folder linked to GitHub? A copy installed from a ZIP file isn't yet, so link it (one time only).
if not exist ".git" goto linkrepo
git status >nul 2>&1
if errorlevel 1 (
    REM Git refuses folders owned by another Windows user, so tell it this one is fine.
    set "FWD=%CD:\=/%"
    git config --global --add safe.directory "%FWD%" >nul 2>&1
)

for /f %%H in ('git rev-parse --short HEAD 2^>nul') do set "OLD=%%H"

echo Closing Pete's Vinyl if it is open...
if exist "Stop_PetesVinyl.bat" call "Stop_PetesVinyl.bat" >nul 2>&1

echo Checking GitHub for a newer version...
git fetch origin main
if errorlevel 1 goto fetchfail
git pull --ff-only origin main
if errorlevel 1 goto pullfail
goto afterpull

:linkrepo
echo This copy was installed from a ZIP file, so I'll link it to GitHub first. This only happens once.
echo Closing Pete's Vinyl if it is open...
if exist "Stop_PetesVinyl.bat" call "Stop_PetesVinyl.bat" >nul 2>&1
git init -q
git remote add origin https://github.com/rhamillnz/PetesVinyl.git
git fetch origin main
if errorlevel 1 goto fetchfail
git checkout -f -B main origin/main
if errorlevel 1 goto fetchfail
git branch --set-upstream-to=origin/main main >nul 2>&1
goto afterpull

:afterpull
for /f %%H in ('git rev-parse --short HEAD 2^>nul') do set "NEW=%%H"
echo.
if "%OLD%"=="%NEW%" (
    echo You already have the latest version. Nothing new to install.
) else (
    echo Updated! The latest changes:
    if defined OLD git log -n 12 --no-decorate --format="   - %%s" %OLD%..%NEW%
)

REM --- 3. Install anything new the update needs.
echo.
echo Checking for new parts the app needs. This can take a minute...
if not exist "venv\Scripts\python.exe" (
    echo The Python environment is missing, so running the installer.
    call "Install_PetesVinyl.bat"
) else (
    "venv\Scripts\python.exe" -m pip install --only-binary=:all: -q -r requirements.txt
    if errorlevel 1 echo   Couldn't check the extra parts. If the app doesn't start, run Install_PetesVinyl.bat.
)

REM --- 4. Make sure both desktop shortcuts exist (older installs didn't have the Update one).
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_shortcuts.ps1" -AppDir "%APPDIR%"

REM --- 5. Start the app again.
echo.
echo Starting Pete's Vinyl again...
start "" "venv\Scripts\pythonw.exe" run.py
echo.
echo  ==================================================
echo   All done!  Pete's Vinyl is opening now.
echo  ==================================================
echo.
pause
exit /b 0

:nogit
echo.
echo  The update needs a free program called Git, and it isn't installed on this computer yet.
echo    1. Go to  https://git-scm.com/download/win  and download the installer
echo    2. Run it and click Next through the screens (the default choices are fine)
echo    3. Double-click "Update Pete's Vinyl" again
echo.
pause
exit /b 1

:fetchfail
echo.
echo  I couldn't reach GitHub. Please check the internet connection and try again.
echo  (If a sign-in window opens for GitHub, sign in there and then run the update again.)
echo.
pause
exit /b 1

:pullfail
echo.
echo  The update couldn't be applied cleanly. That usually means some of the program files on this PC were
echo  changed by hand. Your records, photos and keys are NOT affected either way.
echo.
echo  Press Y to replace those program files with the latest version, or N to cancel.
choice /c YN /n /m "Replace them now (Y/N)? "
if errorlevel 2 goto cancelled
git reset --hard origin/main
if errorlevel 1 goto fetchfail
goto afterpull

:cancelled
echo.
echo  Cancelled. Nothing was changed.
echo.
pause
exit /b 1
