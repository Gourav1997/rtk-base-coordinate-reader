@echo off
cd /d "%~dp0"
if exist "%~dp0dist\RTK Base Reader.exe" (
    start "" "%~dp0dist\RTK Base Reader.exe"
    exit /b
)
if exist "%~dp0.venv\Scripts\pythonw.exe" (
    start "" "%~dp0.venv\Scripts\pythonw.exe" "%~dp0base_ui.py"
) else (
    python "%~dp0base_ui.py"
    if errorlevel 1 pause
)
