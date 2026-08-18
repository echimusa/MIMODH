@echo off
setlocal enabledelayedexpansion
:: ============================================================================
::  PUSH_TO_GITHUB.bat
::  Double-click to publish MIMODH to GitHub. Handles the execution policy
::  and the "downloaded from internet" mark automatically.
::  Place in the MIMODH repository root (next to the scripts\ folder).
::
::  Optional - set your token once so you are never prompted:
::     setx GITHUB_TOKEN ghp_yourTokenHere
::  then close and reopen this window.
::
::  Create a token at https://github.com/settings/tokens/new
::  Scopes: repo, workflow, admin:repo_hook
:: ============================================================================
title MIMODH - Push to GitHub
cd /d "%~dp0"

echo.
echo  ================================================================
echo   MultiOmics-Reactome  --  Publish to GitHub
echo  ================================================================
echo.

set "PS1=%~dp0scripts\push_to_github.ps1"

if not exist "%PS1%" (
    echo  ERROR: scripts\push_to_github.ps1 not found.
    echo.
    echo  This file must sit in the MIMODH repository root, next to the
    echo  scripts\ folder. Current folder:
    echo    %~dp0
    echo.
    dir /b "%~dp0"
    echo.
    pause
    exit /b 1
)

:: ---- Clear the "downloaded from internet" mark ----------------------------
powershell -NoProfile -Command "Get-ChildItem -Path '%~dp0scripts' -Include *.ps1,*.py -Recurse -ErrorAction SilentlyContinue | Unblock-File -ErrorAction SilentlyContinue" 2>nul

:: ---- Report token status ---------------------------------------------------
if defined GITHUB_TOKEN (
    echo  GITHUB_TOKEN found in environment - you will not be prompted.
) else (
    echo  No GITHUB_TOKEN set. The script will prompt you to paste one.
    echo.
    echo    Get a token : https://github.com/settings/tokens/new
    echo    Scopes      : repo, workflow, admin:repo_hook
    echo.
    echo    To avoid the prompt in future, run once:
    echo       setx GITHUB_TOKEN ghp_yourTokenHere
)
echo.

:: ---- Ask about a dry run --------------------------------------------------
echo  A dry run shows exactly what would happen without pushing anything.
echo.
set "DRY="
set /p "DRY=  Do a dry run first? [Y/n]: "

if /i "!DRY!"=="n"  goto :realpush
if /i "!DRY!"=="no" goto :realpush

:: ---- Dry run --------------------------------------------------------------
echo.
echo  ---------------- DRY RUN ----------------
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%" -DryRun
set "DRYRC=!ERRORLEVEL!"

echo.
echo  ================================================================
echo   DRY RUN COMPLETE - nothing was pushed.
echo  ================================================================
echo.

if not "!DRYRC!"=="0" (
    echo  The dry run reported a problem ^(exit code !DRYRC!^).
    echo  Fix the issue above before pushing for real.
    echo.
    pause
    exit /b !DRYRC!
)

set "GO="
set /p "GO=  Push for real now? [y/N]: "

if /i "!GO!"=="y"   goto :realpush
if /i "!GO!"=="yes" goto :realpush

echo.
echo  Cancelled - nothing was pushed.
echo  Re-run this file when you are ready.
echo.
pause
exit /b 0

:: ---- Real push ------------------------------------------------------------
:realpush
echo.
echo  ---------------- PUSHING ----------------
echo.
powershell -NoProfile -ExecutionPolicy Bypass -File "%PS1%"
set "RC=!ERRORLEVEL!"

echo.
if "!RC!"=="0" (
    echo  ================================================================
    echo   PUSH COMPLETE
    echo  ================================================================
) else (
    echo  ================================================================
    echo   PUSH FAILED  ^(exit code !RC!^)
    echo  ================================================================
    echo.
    echo  Common causes:
    echo    - Token missing the 'repo' scope
    echo    - Token expired or revoked
    echo    - Syntax errors or secrets found by the pre-push checks
    echo.
    echo  Read the messages above for the exact reason.
)
echo.
pause
exit /b !RC!
