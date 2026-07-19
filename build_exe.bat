@echo off
rem This script automatically switches to the folder it lives in before
rem doing anything else -- %~dp0 is "the drive+path this .bat file is
rem located in", so it works no matter where you launch it from (double
rem click, a cmd window opened elsewhere, etc.). This removes the need to
rem manually "cd" into the project folder every time, which is what caused
rem "Spec file not found" the last few times (the terminal was still
rem sitting in C:\Users\fngps instead of the project folder).
cd /d "%~dp0"

echo Building in: %CD%
echo.

if not exist "bethesda_strings_editor.spec" (
    echo [ERROR] bethesda_strings_editor.spec not found here.
    echo This .bat file must sit in the same folder as bethesda_strings_editor.spec.
    pause
    exit /b 1
)

set "BSEK_PYTHON=%LOCALAPPDATA%\Programs\Python\Python310\python.exe"

if not exist "%BSEK_PYTHON%" (
    echo [ERROR] Expected Python not found at:
    echo   %BSEK_PYTHON%
    pause
    exit /b 1
)

echo Using: %BSEK_PYTHON%
echo.

"%BSEK_PYTHON%" -m PyInstaller bethesda_strings_editor.spec

if errorlevel 1 (
    echo.
    echo [BUILD FAILED] See the errors above.
    pause
    exit /b 1
)

echo.
echo [BUILD OK] Output: %CD%\dist\bethesda-strings-editor\
pause
