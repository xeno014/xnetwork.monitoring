@echo off
REM Builds dist\XenoTechSpeedAgent.exe  (the small program you run on REMOTE devices)
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

echo [1/2] Installing PyInstaller...
%PY% -m pip install --upgrade pyinstaller || goto :fail

echo [2/2] Building speed agent...
%PY% -m PyInstaller --noconfirm --clean --onefile ^
  --name XenoTechSpeedAgent ^
  --icon assets\xenotech.ico ^
  --paths src ^
  src\speed_agent.py || goto :fail

echo.
echo Done: dist\XenoTechSpeedAgent.exe
echo Copy that single file to the remote device. See docs\REMOTE_SETUP.md
pause
exit /b 0

:fail
echo.
echo Build failed - see messages above.
pause
exit /b 1
