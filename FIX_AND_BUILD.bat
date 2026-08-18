@echo off
:: ============================================================================
::  FIX_AND_BUILD.bat
::  Double-click to patch the app files and rebuild MultiOmicsReactome.exe
::  Place in the MIMODH folder next to FIX_AND_BUILD.ps1
:: ============================================================================
title MultiOmics-Reactome - Fix and Rebuild
cd /d "%~dp0"

echo.
echo  ================================================================
echo   MultiOmics-Reactome  --  Patch and Rebuild
echo  ================================================================
echo.

if not exist "%~dp0FIX_AND_BUILD.ps1" (
    echo  ERROR: FIX_AND_BUILD.ps1 not found in this folder.
    echo  Current folder: %~dp0
    pause
    exit /b 1
)

powershell -Command "Unblock-File -LiteralPath '%~dp0FIX_AND_BUILD.ps1'" 2>nul
powershell -ExecutionPolicy Bypass -NoProfile -File "%~dp0FIX_AND_BUILD.ps1"

echo.
pause
