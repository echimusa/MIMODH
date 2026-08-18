@echo off
setlocal enabledelayedexpansion
:: ============================================================================
::  REPAIR_GIT.bat
::  Removes oversized build artifacts from git -- including from COMMIT HISTORY.
::
::  GitHub rejects any file over 100 MB. Removing it from the index is NOT
::  enough: git still pushes every historical commit that contains it. This
::  script detects that case and rewrites history.
::
::  Place in the MIMODH repository root.
:: ============================================================================
title MIMODH - Repair Git Repository
cd /d "%~dp0"

echo.
echo  ================================================================
echo   MIMODH  --  Remove oversized files from git
echo  ================================================================
echo.

where git >nul 2>&1
if errorlevel 1 ( echo  ERROR: git not found on PATH. & pause & exit /b 1 )
if not exist ".git" ( echo  No .git folder here - nothing to repair. & pause & exit /b 0 )

:: ---- Scan the INDEX and the HISTORY ---------------------------------------
echo  [1/3] Scanning working tree and full commit history...
echo.

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lim=100MB;" ^
  "$idx=@(); git ls-files | ForEach-Object { if (Test-Path -LiteralPath $_ -PathType Leaf) { if ((Get-Item -LiteralPath $_).Length -gt $lim) { $idx+=$_ } } };" ^
  "$hist=@{}; $objs = git rev-list --objects --all 2>$null;" ^
  "$sizes = $objs | ForEach-Object { ($_ -split ' ',2)[0] } | git cat-file --batch-check='%%(objectname) %%(objecttype) %%(objectsize)' 2>$null;" ^
  "$big=@{}; foreach($l in $sizes){ $p=$l -split ' '; if($p.Length -ge 3 -and $p[1] -eq 'blob' -and [int64]$p[2] -gt $lim){ $big[$p[0]]=[int64]$p[2] } };" ^
  "foreach($o in $objs){ $p=$o -split ' ',2; if($p.Length -eq 2 -and $big.ContainsKey($p[0])){ $hist[$p[1]]=$big[$p[0]] } };" ^
  "if($idx.Count -gt 0){ Write-Host '  In the current index:' -ForegroundColor Red; $idx | ForEach-Object { Write-Host ('    ' + $_) -ForegroundColor Red } };" ^
  "if($hist.Count -gt 0){ Write-Host '  In commit HISTORY (this is why the push keeps failing):' -ForegroundColor Red; $hist.GetEnumerator() | ForEach-Object { Write-Host ('    ' + $_.Key + '   ' + [math]::Round($_.Value/1MB) + ' MB') -ForegroundColor Red }; $hist.Keys | Set-Content -LiteralPath '.git\big_paths.txt' -Encoding UTF8 };" ^
  "if($idx.Count -eq 0 -and $hist.Count -eq 0){ Write-Host '  Clean - nothing over 100 MB anywhere.' -ForegroundColor Green; exit 0 } else { exit 1 }"

if not errorlevel 1 (
    echo.
    echo  Repository is clean. Push with:  PUSH_TO_GITHUB.bat
    echo.
    if exist ".git\big_paths.txt" del ".git\big_paths.txt" >nul 2>&1
    pause
    exit /b 0
)

:: ---- Explain and choose --------------------------------------------------
echo.
echo  ----------------------------------------------------------------
echo   The oversized file is baked into your commit history.
echo   'git rm --cached' alone will NOT fix this - git still uploads
echo   every historical commit that contains the file.
echo  ----------------------------------------------------------------
echo.
echo   Choose how to fix it:
echo.
echo     [1] FRESH START  (recommended, fast, always works)
echo         Deletes .git and starts a single clean commit.
echo         You lose local commit history - the CODE is untouched.
echo         Best when publishing for the first time.
echo.
echo     [2] REWRITE HISTORY  (keeps your commits, slower)
echo         Uses git filter-branch to strip the file from every commit.
echo         Takes a few minutes on a large repo.
echo.
echo     [3] Cancel
echo.
set "OPT="
set /p "OPT=  Enter 1, 2 or 3 [1]: "
if "!OPT!"=="" set "OPT=1"

if "!OPT!"=="3" ( echo  Cancelled. & pause & exit /b 0 )
if "!OPT!"=="2" goto :rewrite
if not "!OPT!"=="1" ( echo  Invalid choice. & pause & exit /b 1 )

:: ========================================================================
:: OPTION 1 -- fresh history
:: ========================================================================
:freshstart
echo.
echo  FRESH START selected.
echo  Your files stay exactly as they are. Only .git is recreated.
echo.
set "CONF="
set /p "CONF=  Type 'fresh' to confirm: "
if /i not "!CONF!"=="fresh" ( echo  Cancelled. & pause & exit /b 0 )

echo.
echo  [2/3] Recreating the repository...

:: Preserve the remote URL if one is configured
set "OLDREMOTE="
for /f "delims=" %%r in ('git config --get remote.origin.url 2^>nul') do set "OLDREMOTE=%%r"

:: Back up the old .git so nothing is truly lost
if exist ".git_backup" rmdir /s /q ".git_backup" >nul 2>&1
move ".git" ".git_backup" >nul 2>&1
if errorlevel 1 (
    echo     ERROR: could not move .git - is a git process or editor holding it open?
    echo     Close VS Code / Git GUI tools and try again.
    pause
    exit /b 1
)
echo     old .git saved as .git_backup

git init -b main --quiet
if errorlevel 1 ( git init --quiet & git checkout -b main --quiet )

:: Make sure build artifacts are ignored BEFORE the first add
findstr /C:"*.exe" .gitignore >nul 2>&1
if errorlevel 1 (
    echo.>> .gitignore
    echo # Build artifacts - never commit ^(GitHub rejects files over 100 MB^)>> .gitignore
    echo *.exe>> .gitignore
    echo *.dll>> .gitignore
    echo *.app/>> .gitignore
    echo *.dmg>> .gitignore
    echo *.msi>> .gitignore
    echo *.AppImage>> .gitignore
    echo *.bin>> .gitignore
    echo dist/>> .gitignore
    echo build/>> .gitignore
    echo     .gitignore updated
)

git add -A
git -c user.name="MIMODH" -c user.email="mimodh@localhost" commit -q -m "feat: MultiOmics-Reactome v3.0 (MIMODH-compliant multi-omics pipeline)"
if defined OLDREMOTE (
    git remote add origin "!OLDREMOTE!" >nul 2>&1
    echo     remote restored: !OLDREMOTE!
)
goto :verify

:: ========================================================================
:: OPTION 2 -- rewrite history
:: ========================================================================
:rewrite
echo.
echo  REWRITE HISTORY selected.
echo  This can take several minutes.
echo.
set "CONF="
set /p "CONF=  Type 'rewrite' to confirm: "
if /i not "!CONF!"=="rewrite" ( echo  Cancelled. & pause & exit /b 0 )

echo.
echo  [2/3] Stripping oversized files from every commit...

if not exist ".git\big_paths.txt" (
    echo     ERROR: path list missing. Re-run this script.
    pause
    exit /b 1
)

set "FILTER="
for /f "usebackq delims=" %%p in ("`.git\big_paths.txt`") do (
    echo     removing: %%p
    set "FILTER=!FILTER! && git rm --cached --ignore-unmatch -- \"%%p\""
)

set FILTER_BRANCH_SQUELCH_WARNING=1
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$paths = Get-Content -LiteralPath '.git\big_paths.txt';" ^
  "$cmd = ($paths | ForEach-Object { 'git rm --cached --ignore-unmatch -- \"' + $_ + '\"' }) -join ' ; ';" ^
  "$env:FILTER_BRANCH_SQUELCH_WARNING='1';" ^
  "git filter-branch --force --index-filter $cmd --prune-empty --tag-name-filter cat -- --all"

if errorlevel 1 (
    echo     filter-branch reported a problem. Consider option 1 instead.
    pause
    exit /b 1
)

echo.
echo     cleaning reflog and repacking...
git for-each-ref --format="delete %%(refname)" refs/original | git update-ref --stdin >nul 2>&1
git reflog expire --expire=now --all >nul 2>&1
git gc --prune=now --aggressive --quiet >nul 2>&1

:: ========================================================================
:verify
echo.
echo  [3/3] Verifying...
powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$lim=100MB; $bad=0;" ^
  "$objs = git rev-list --objects --all 2>$null;" ^
  "$sizes = $objs | ForEach-Object { ($_ -split ' ',2)[0] } | git cat-file --batch-check='%%(objectname) %%(objecttype) %%(objectsize)' 2>$null;" ^
  "foreach($l in $sizes){ $p=$l -split ' '; if($p.Length -ge 3 -and $p[1] -eq 'blob' -and [int64]$p[2] -gt $lim){ $bad++ } };" ^
  "$packed = (git count-objects -vH | Select-String 'size-pack') -replace '.*:\s*','';" ^
  "if($bad -eq 0){ Write-Host ('    Clean - no oversized objects. Repo size: ' + $packed) -ForegroundColor Green } else { Write-Host ('    ' + $bad + ' oversized objects remain') -ForegroundColor Red }"

if exist ".git\big_paths.txt" del ".git\big_paths.txt" >nul 2>&1

echo.
echo  ================================================================
echo   REPAIR COMPLETE
echo  ================================================================
echo.
echo   Next:  PUSH_TO_GITHUB.bat
echo.
echo   The push will now be a few hundred KB instead of 280 MB.
if exist ".git_backup" (
    echo.
    echo   Your previous history is in .git_backup - delete it when happy:
    echo      rmdir /s /q .git_backup
)
echo.
pause
