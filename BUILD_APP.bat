@echo off
:: =============================================================================
::  BUILD_APP.bat  --  MultiOmics-Reactome Desktop Builder
::  Place this file in the MIMODH folder (same folder as requirements.txt)
::  Then double-click it. No PowerShell knowledge needed.
:: =============================================================================
title MultiOmics-Reactome Desktop Builder
cd /d "%~dp0"

echo.
echo  ================================================================
echo   MultiOmics-Reactome Desktop  --  One-Click Builder
echo  ================================================================
echo.

:: ---- Find build_desktop_installer.ps1 (check several locations) -------------
set "PS1="

:: Same folder as this .bat file
if exist "%~dp0build_desktop_installer.ps1" (
    set "PS1=%~dp0build_desktop_installer.ps1"
    goto :found
)

:: desktop\ subfolder
if exist "%~dp0desktop\build_desktop_installer.ps1" (
    set "PS1=%~dp0desktop\build_desktop_installer.ps1"
    goto :found
)

:: scripts\ subfolder
if exist "%~dp0scripts\build_desktop_installer.ps1" (
    set "PS1=%~dp0scripts\build_desktop_installer.ps1"
    goto :found
)

echo  ERROR: build_desktop_installer.ps1 not found.
echo.
echo  Make sure BUILD_APP.bat and build_desktop_installer.ps1
echo  are in the same folder (the MIMODH repo root).
echo.
echo  Current folder: %~dp0
echo  Contents:
dir /b "%~dp0"
echo.
pause
exit /b 1

:found
echo  Found: %PS1%
echo.

:: ---- Unblock the script (removes "downloaded from internet" mark) -----------
powershell -Command "Unblock-File -LiteralPath '%PS1%'" 2>nul

:: ---- Run with Bypass policy (no permanent system changes) -------------------
powershell -ExecutionPolicy Bypass -NoProfile -File "%PS1%"

echo.
if errorlevel 1 (
    echo  Build encountered an error. See messages above.
) else (
    echo  Done! Look for dist\MultiOmicsReactome.exe
)
echo.
pause
