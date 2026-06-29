@echo off
cd /d "%~dp0"

if not exist "main.py" (
    echo [ERROR] main.py not found.
    echo Put this bat file inside the BSE folder where main.py is.
    pause
    exit /b 1
)

echo Starting BSEK...
python main.py

if errorlevel 1 (
    echo.
    echo [BSEK exited with an error]
    pause
)
