@echo off
REM Builds dist\XenoTechIPMonitor.exe  (run from the project folder)
setlocal
cd /d "%~dp0"

set PY=
py --version >nul 2>&1 && set PY=py
if not defined PY (
  python --version >nul 2>&1 && set PY=python
)
if not defined PY (
  echo Python was not found. Install it from python.org and tick "Add python.exe to PATH".
  goto :fail
)

echo [1/3] Installing dependencies...
%PY% -m pip install --upgrade pip || goto :fail
%PY% -m pip install -r requirements.txt pyinstaller || goto :fail

echo [2/3] Building executable (close the running app first)...
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed ^
  --name XenoTechIPMonitor ^
  --icon assets\xenotech.ico ^
  --paths src ^
  --add-data "assets;assets" ^
  --add-data "config\devices.json;config" ^
  --hidden-import pystray._win32 ^
  src\main.py || goto :fail

echo [3/3] Done: dist\XenoTechIPMonitor.exe
pause
exit /b 0

:fail
echo.
echo Build failed - see messages above.
pause
exit /b 1
