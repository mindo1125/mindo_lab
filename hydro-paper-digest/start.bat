@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
  py -3 -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
  if not errorlevel 1 (
    py -3 app.py
    if errorlevel 1 pause
    exit /b
  )
)
where python >nul 2>&1
if not errorlevel 1 (
  python -c "import sys; assert sys.version_info >= (3, 10)" >nul 2>&1
  if not errorlevel 1 (
    python app.py
    if errorlevel 1 pause
    exit /b
  )
)
echo Install Python 3.10 or newer, then double-click start.bat again.
echo Alternatively download HydroPaperDigest.exe from GitHub Actions artifacts.
start "" https://www.python.org/downloads/windows/
pause
