@echo off
:: ============================================================================
::  UNBLOCK_ALL.bat
::  Removes the Windows "downloaded from internet" mark from every script.
::  Run this ONCE after extracting the zip, then all scripts work normally.
::  Place in the MIMODH repository root.
:: ============================================================================
title MIMODH - Unblock Scripts
cd /d "%~dp0"

echo.
echo  ================================================================
echo   MIMODH  --  Unblocking downloaded scripts
echo  ================================================================
echo.
echo  Folder: %~dp0
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$n=0; Get-ChildItem -Path '%~dp0' -Recurse -Include *.ps1,*.bat,*.sh,*.py -ErrorAction SilentlyContinue | ForEach-Object { Unblock-File -LiteralPath $_.FullName -ErrorAction SilentlyContinue; $n++ }; Write-Host \"  Unblocked $n files\" -ForegroundColor Green"

echo.
echo  Done. All scripts can now be run normally:
echo.
echo     BUILD_APP.bat                     build the desktop .exe
echo     FIX_AND_BUILD.bat                 patch sources + rebuild
echo     PUSH_TO_GITHUB.bat                publish to GitHub
echo     .\scripts\setup.ps1               set up the Python environment
echo.
pause
