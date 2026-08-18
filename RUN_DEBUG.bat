@echo off
:: =============================================================================
::  RUN_DEBUG.bat  --  Launch MultiOmicsReactome.exe with full crash logging
::  Place in the same folder as dist\MultiOmicsReactome.exe
::  Double-click to run. A log file will appear with the full error.
:: =============================================================================
title MultiOmics-Reactome Debug Launcher
cd /d "%~dp0"

set "EXE=dist\MultiOmicsReactome.exe"
set "LOG=%~dp0crash_log.txt"

if not exist "%EXE%" (
    echo ERROR: %EXE% not found.
    echo Run BUILD_APP.bat first to build the executable.
    pause
    exit /b 1
)

echo.
echo  Launching %EXE% ...
echo  Crash log will be saved to: %LOG%
echo.

:: Run the exe and capture all output
"%EXE%" > "%LOG%" 2>&1

echo.
echo  App exited with code: %ERRORLEVEL%
echo.

if exist "%LOG%" (
    echo  ---- crash_log.txt ----
    type "%LOG%"
    echo  -----------------------
)

echo.
echo  If the app crashed, share crash_log.txt for diagnosis.
pause
