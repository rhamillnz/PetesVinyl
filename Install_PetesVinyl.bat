@echo off
title Installing Pete's Vinyl
REM One-time setup. Needs Python 3.10+ installed with "Add python.exe to PATH" ticked.
cd /d "%~dp0"

where python >nul 2>&1
if errorlevel 1 (
    echo.
    echo  Python isn't installed yet.
    echo  1. Go to https://www.python.org/downloads/windows/
    echo  2. Download the latest Python 3 installer
    echo  3. IMPORTANT: tick "Add python.exe to PATH" on the first screen
    echo  4. Then double-click this file again.
    echo.
    pause
    exit /b 1
)

echo Creating the private Python environment...
if not exist "venv\Scripts\activate.bat" python -m venv venv
call venv\Scripts\activate.bat

echo Installing the parts Pete's Vinyl needs (this takes a few minutes)...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
    echo Something went wrong installing. Check the internet connection and try again.
    pause
    exit /b 1
)

echo Installing the browser helper used for Facebook / Gumtree listings...
python -m playwright install chromium

if not exist ".env" copy ".env.example" ".env" >nul

echo Putting a "Pete's Vinyl" shortcut on the desktop...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut([Environment]::GetFolderPath('Desktop')+'\Pete''s Vinyl.lnk');" ^
  "$s.TargetPath='%~dp0Start_PetesVinyl.bat';$s.WorkingDirectory='%~dp0';$s.WindowStyle=7;" ^
  "$s.IconLocation='%SystemRoot%\System32\imageres.dll,103';$s.Save()"

echo.
echo  All done! Double-click "Pete's Vinyl" on the desktop to start.
echo.
pause
