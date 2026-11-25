@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>&1
if not errorlevel 1 (
    py -3 install_dependencies.py
) else (
    where python >nul 2>&1
    if errorlevel 1 (
        echo Please install Python 3.10 or newer with Tcl/Tk enabled and Python on PATH.
        pause
        exit /b 1
    )
    python install_dependencies.py
)
if errorlevel 1 (
    echo Dependency installation failed. Review the error above.
    pause
    exit /b 1
)
pause
