@echo off
setlocal enabledelayedexpansion
rem podharvest launcher: creates a local virtual environment on first run,
rem installs the base requirements, then runs main.py with any arguments
rem you pass through (run.bat gui, run.bat hardware, run.bat fetch <url>, ...).

set "ROOT=%~dp0"
set "VENV=%ROOT%.venv"
set "PYEXE=%VENV%\Scripts\python.exe"

where python >nul 2>nul
if errorlevel 1 (
    echo [podharvest] Python was not found on PATH. Install Python 3.10+ from https://python.org and try again.
    exit /b 1
)

if not exist "%PYEXE%" (
    echo [podharvest] First run detected - creating a local virtual environment in .venv ...
    python -m venv "%VENV%"
    if errorlevel 1 (
        echo [podharvest] Failed to create the virtual environment.
        exit /b 1
    )
    echo [podharvest] Installing base requirements ^(this only happens once^) ...
    "%PYEXE%" -m pip install --disable-pip-version-check --quiet --upgrade pip
    "%PYEXE%" -m pip install --disable-pip-version-check --quiet -r "%ROOT%requirements.txt"
    if errorlevel 1 (
        echo [podharvest] Dependency installation failed. See the errors above.
        exit /b 1
    )
)

"%PYEXE%" "%ROOT%main.py" %*
exit /b %errorlevel%
