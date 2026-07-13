@echo off
cd /d "%~dp0"

if not exist "main.py" (
    echo [ERROR] main.py not found.
    echo Put this bat file inside the BSE folder where main.py is.
    pause
    exit /b 1
)

rem Prefer the specific Python 3.10 install BSEK's dependencies (PySide6 etc.)
rem were installed into, instead of the bare "python" command -- whichever
rem interpreter that resolves to depends on PATH order, which can silently
rem change (e.g. installing/reinstalling Miniconda for an unrelated project
rem puts its own python.exe earlier in PATH, and "python" quietly starts
rem pointing at an environment that's never had BSEK's packages installed).
set "BSEK_PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"

if exist "%BSEK_PYTHON%" (
    set "PYTHON_CMD=%BSEK_PYTHON%"
) else (
    echo [WARNING] Expected Python not found at:
    echo   %BSEK_PYTHON%
    echo Falling back to whatever "python" resolves to on PATH -- if BSEK
    echo fails to start with "ModuleNotFoundError", this is very likely why:
    echo run "where python" and check which one comes first.
    set "PYTHON_CMD=python"
)

echo Starting BSEK...
"%PYTHON_CMD%" main.py

if errorlevel 1 (
    echo.
    echo [BSEK exited with an error]
    echo Using interpreter: %PYTHON_CMD%
    echo If this says ModuleNotFoundError, reinstall dependencies with:
    echo   "%PYTHON_CMD%" -m pip install -r requirements.txt
    pause
)
