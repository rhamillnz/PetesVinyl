@echo off
setlocal EnableExtensions
title Installing Pete's Vinyl
REM One-time setup. Safe to run again: it repairs a broken or half-finished install.
REM Needs Python 3.12 (3.10 - 3.13 also work). Python 3.14 and newer do NOT work yet.
cd /d "%~dp0"

echo.
echo  ============  Installing Pete's Vinyl  ============
echo.

REM --- 1. Are we in the right folder? Windows' "Extract All" often makes PetesVinyl-main\PetesVinyl-main.
if not exist "main.py" (
    for /d %%D in (*) do if exist "%%D\main.py" cd /d "%%D"
)
if not exist "main.py" goto wrongfolder
echo %CD% | findstr /i /c:"Program Files" >nul && goto badlocation
set "APPDIR=%CD%"
echo App folder: %APPDIR%

REM --- 2. Find a Python that works. The "py" launcher finds 3.12 even if a newer Python is also installed.
REM        A plain "python" can be a fake Microsoft Store shortcut, so it is only a last resort.
set "PY="
for %%V in (3.12 3.13 3.11 3.10) do (
    if not defined PY (
        py -%%V -c "import sys" >nul 2>&1 && set "PY=py -%%V"
    )
)
if not defined PY (
    python -c "import sys; sys.exit(0 if (3,10) <= sys.version_info[:2] <= (3,13) else 1)" >nul 2>&1 && set "PY=python"
)
if not defined PY goto nopython
echo Using Python:
%PY% --version

REM --- 3. If the app is running, stop it first (it would lock the files we're about to repair).
if exist "Stop_PetesVinyl.bat" call "Stop_PetesVinyl.bat" >nul 2>&1

REM --- 4. Create the private Python environment (venv) and install the parts the app needs.
set "NEEDVENV=1"
if exist "venv\Scripts\python.exe" (
    "venv\Scripts\python.exe" -c "import fastapi, uvicorn, pydantic, httpx, playwright" >nul 2>&1
    if not errorlevel 1 set "NEEDVENV=0"
)
if "%NEEDVENV%"=="1" (
    echo.
    echo Setting up a fresh private Python environment...
    %PY% -m venv --clear venv
    if errorlevel 1 goto venvfail
    "venv\Scripts\python.exe" -m pip install --upgrade pip
    echo.
    echo Installing the parts Pete's Vinyl needs. This takes a few minutes, so please wait...
    "venv\Scripts\python.exe" -m pip install --only-binary=:all: -r requirements.txt
    if errorlevel 1 goto pipfail
) else (
    echo The Python environment is already set up and healthy.
)

REM --- 5. Optional backup browser for the Facebook / Gumtree helper (Chrome is used if it's installed).
echo.
echo Installing the backup browser for the Facebook / Gumtree helper (optional, about 150 MB)...
"venv\Scripts\python.exe" -m playwright install chromium
if errorlevel 1 echo   (That part is optional. Pete's Vinyl works without it as long as Google Chrome is installed.)

if not exist ".env" copy ".env.example" ".env" >nul

REM --- 6. Desktop shortcuts: "Pete's Vinyl" (record icon) and "Update Pete's Vinyl" (record icon with a green arrow).
echo.
echo Putting the "Pete's Vinyl" and "Update Pete's Vinyl" shortcuts on the desktop...
powershell -NoProfile -ExecutionPolicy Bypass -File "tools\make_shortcuts.ps1" -AppDir "%APPDIR%" -Force
if errorlevel 1 echo   (Couldn't make the desktop shortcuts. You can still start the app with Start_PetesVinyl.bat.)

REM --- 7. The Update icon needs Git (free). Not needed for anything else, so just mention it.
git --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo   Note: to use the "Update Pete's Vinyl" icon later, install Git for Windows from https://git-scm.com/download/win
)

echo.
echo  ==================================================
echo   All done!  Double-click "Pete's Vinyl" on the desktop to start.
echo   Later, double-click "Update Pete's Vinyl" to get the latest version.
echo   To keep it on the taskbar: right-click the desktop shortcut,
echo   choose "Show more options", then "Pin to taskbar".
echo  ==================================================
echo.
pause
exit /b 0

:wrongfolder
echo.
echo  I can't find the app files (main.py) here.
echo  Open the folder that contains Install_PetesVinyl.bat, main.py and the "static" folder,
echo  and run this file from there. See the README, "Get the app onto the PC".
echo.
pause
exit /b 1

:badlocation
echo.
echo  Please don't put Pete's Vinyl inside "Program Files". Windows won't let it save its records there.
echo  Move the whole folder to somewhere simple like  C:\PetesVinyl  and run this again.
echo.
pause
exit /b 1

:nopython
echo.
echo  Pete's Vinyl needs Python 3.12. I couldn't find a suitable Python on this computer.
echo  (It does NOT work with Python 3.14 or newer yet, so don't pick the newest one on the python.org front page.)
echo.
echo    1. Go to  https://www.python.org/downloads/release/python-3128/
echo    2. Scroll down and download "Windows installer (64-bit)"
echo    3. Run it. On the FIRST screen tick "Add python.exe to PATH", then click "Install Now"
echo    4. Double-click Install_PetesVinyl.bat again
echo.
echo  If a newer Python is already installed, that's fine: keep it. This installer finds 3.12 by itself.
echo.
pause
exit /b 1

:venvfail
echo.
echo  Couldn't create the private Python environment.
echo  Try: close any open Pete's Vinyl window, delete the "venv" folder, then run this file again.
echo.
pause
exit /b 1

:pipfail
echo.
echo  The parts Pete's Vinyl needs could not be installed.
echo  The most common causes are no internet connection, or a Python that is too new.
echo  Python used:
%PY% --version
echo  Fix: check the internet connection, install Python 3.12 (see the README), delete the "venv" folder,
echo  then run this file again.
echo.
pause
exit /b 1
