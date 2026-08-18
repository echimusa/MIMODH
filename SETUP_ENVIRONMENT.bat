@echo off
:: ============================================================================
::  SETUP_ENVIRONMENT.bat
::  Creates the Python virtual environment and installs all dependencies.
::  Double-click to run. Place in the MIMODH repository root.
:: ============================================================================
title MIMODH - Environment Setup
cd /d "%~dp0"

echo.
echo  ================================================================
echo   MultiOmics-Reactome  --  Environment Setup
echo  ================================================================
echo.

set "PS1=%~dp0scripts\setup.ps1"

if not exist "%PS1%" (
    echo  ERROR: scripts\setup.ps1 not found in %~dp0
    pause
    exit /b 1
)

powershell -NoProfile -Command "Get-ChildItem -Path '%~dp0scripts' -Include *.ps1 -Recurse -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" 2>nul

echo  Choose what to install:
echo.
echo    [1] Pipeline only            (command-line use)
echo    [2] Pipeline + Desktop app   (recommended)
echo    [3] Pipeline + Desktop + GPU (CUDA PyTorch)
echo    [4] Everything + dev tools   (pytest, ruff, black)
echo.
set /p CHOICE="  Enter 1-4 [2]: "
if "%CHOICE%"=="" set CHOICE=2

if "%CHOICE%"=="1" set "ARGS="
if "%CHOICE%"=="2" set "ARGS=-Desktop"
if "%CHOICE%"=="3" set "ARGS=-Desktop -Gpu"
if "%CHOICE%"=="4" set "ARGS=-Desktop -Dev"

echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" %ARGS%

echo.
pause
