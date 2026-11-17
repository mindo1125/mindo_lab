@echo off
setlocal
cd /d "%~dp0"
py -3 -m venv .build-venv
if errorlevel 1 goto fail
.build-venv\Scripts\python.exe -m pip install pyinstaller==6.16.0
if errorlevel 1 goto fail
.build-venv\Scripts\python.exe -m unittest discover -s tests -v
if errorlevel 1 goto fail
.build-venv\Scripts\python.exe -m PyInstaller --noconfirm --clean --onefile --windowed --name HydroPaperDigest app.py
if errorlevel 1 goto fail
start "" "%~dp0dist"
pause
exit /b
:fail
echo Build failed. Check the messages above. Python 3.10 or newer is required.
pause
exit /b 1
