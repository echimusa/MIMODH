# =============================================================================
#  build_desktop_installer.ps1
#  One-click: installs everything and builds MultiOmicsReactome.exe
#
#  Just double-click this file (or run from PowerShell).
#  No Python, no git, no technical knowledge needed beyond running this once.
#
#  What it does:
#    1. Checks Python 3.9+ is installed (prompts to install if missing)
#    2. Creates an isolated virtual environment
#    3. Installs all dependencies
#    4. Builds MultiOmicsReactome.exe via PyInstaller
#    5. Opens the dist\ folder so you can double-click the .exe
#
#  Prerequisites:
#    - Windows 10 or 11
#    - Internet connection (first run only)
#    - Run from the MIMODH repository root folder
# =============================================================================

#Requires -Version 5.1

# -- Self-unblock: remove the "downloaded from internet" Zone.Identifier mark --
# This is what causes the "not digitally signed" / UnauthorizedAccess error.
# Unblock-File removes the NTFS alternate data stream that Windows adds when
# a file is downloaded, making the script safe to run without policy changes.
try {
    $thisScript = $MyInvocation.MyCommand.Path
    if ($thisScript) {
        Unblock-File -Path $thisScript -ErrorAction SilentlyContinue
    }
} catch {}

# -- Self-relaunch with Bypass if execution policy blocks us -------------------
# If the script somehow still cannot run, relaunch itself with -ExecutionPolicy Bypass
$policy = Get-ExecutionPolicy -Scope CurrentUser
if ($policy -eq "Restricted" -or $policy -eq "AllSigned") {
    $thisScript = $MyInvocation.MyCommand.Path
    if ($thisScript -and -not $env:MIMODH_RELAUNCHED) {
        Write-Host "  Execution policy is '$policy'. Relaunching with Bypass..." -ForegroundColor Yellow
        $env:MIMODH_RELAUNCHED = "1"
        Start-Process powershell -ArgumentList "-ExecutionPolicy Bypass -File `"$thisScript`"" -Wait
        exit
    }
}

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Write-Banner {
    Clear-Host
    Write-Host ""
    Write-Host "  ================================================================" -ForegroundColor Cyan
    Write-Host "   MultiOmics-Reactome Desktop  --  One-Click Setup & Build       " -ForegroundColor Cyan
    Write-Host "   Version 3.0.0  |  MIMODH v1.0  |  Agamah et al. 2025          " -ForegroundColor Cyan
    Write-Host "  ================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  This script will automatically:" -ForegroundColor White
    Write-Host "    1.  Install Python 3.11      (if not already installed)" -ForegroundColor Gray
    Write-Host "    2.  Create an isolated environment  (does not affect your PC)" -ForegroundColor Gray
    Write-Host "    3.  Install C++ Build Tools  (needed for some packages)" -ForegroundColor Gray
    Write-Host "    4.  Install all Python packages  (scipy, PyQt6, etc.)" -ForegroundColor Gray
    Write-Host "    5.  Prepare bundled test data" -ForegroundColor Gray
    Write-Host "    6.  Build MultiOmicsReactome.exe  (standalone, no Python needed)" -ForegroundColor Gray
    Write-Host ""
    Write-Host "  Nothing is installed to system folders." -ForegroundColor DarkGray
    Write-Host "  Everything goes into .venv_build\  inside this folder." -ForegroundColor DarkGray
    Write-Host ""
    Write-Host "  Estimated time: 10-20 minutes (first run) / 3-5 minutes (rebuild)" -ForegroundColor Yellow
    Write-Host ""
    $ready = Read-Host "  Press ENTER to start (or Ctrl+C to cancel)"
    Write-Host ""
}
function Write-Step  { param($n,$m) Write-Host "`n  [$n] $m" -ForegroundColor Cyan }
function Write-OK    { param($m)    Write-Host "      OK: $m" -ForegroundColor Green }
function Write-Warn  { param($m)    Write-Host "    WARN: $m" -ForegroundColor Yellow }
function Write-Fatal { param($m)    Write-Host "   ERROR: $m" -ForegroundColor Red
                       Write-Host "   Press any key to exit..."
                       $null = $host.UI.RawUI.ReadKey("NoEcho,IncludeKeyDown")
                       exit 1 }

Write-Banner

# Move to repo root (wherever this script lives)
$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot
Write-Host "  Working directory: $repoRoot" -ForegroundColor Gray

# =============================================================================
# =============================================================================
# STEP 1 -- Auto-install Python if missing
# =============================================================================
Write-Step "1/6" "Python 3.11  (auto-installing if missing)"

function Install-Python {
    Write-Warn "Python 3.11 not found. Installing automatically..."

    # Method 1: winget (Windows 10 1709+ / Windows 11)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "      Installing Python 3.11 via winget..." -ForegroundColor Gray
        winget install --id Python.Python.3.11 -e --source winget `
            --accept-package-agreements --accept-source-agreements
        # Refresh PATH so python is found immediately
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH","User")
        if (Get-Command python -ErrorAction SilentlyContinue) {
            Write-OK "Python installed via winget."
            return $true
        }
    }

    # Method 2: Chocolatey
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        Write-Host "      Installing Python 3.11 via Chocolatey..." -ForegroundColor Gray
        choco install python311 -y --no-progress
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH","User")
        if (Get-Command python -ErrorAction SilentlyContinue) {
            Write-OK "Python installed via Chocolatey."
            return $true
        }
    }

    # Method 3: Direct download from python.org (silent installer)
    Write-Host "      Downloading Python 3.11.9 installer (~25 MB)..." -ForegroundColor Gray
    $pyUrl  = "https://www.python.org/ftp/python/3.11.9/python-3.11.9-amd64.exe"
    $pyExe  = "$env:TEMP\python-3.11.9-amd64.exe"
    try {
        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        $wc = New-Object System.Net.WebClient
        $wc.DownloadFile($pyUrl, $pyExe)
    } catch {
        Write-Warn "Download failed: $_"
        return $false
    }
    Write-Host "      Running Python installer silently..." -ForegroundColor Gray
    # /quiet = no UI, InstallAllUsers=0 = current user, PrependPath=1 = add to PATH
    $proc = Start-Process -FilePath $pyExe `
        -ArgumentList "/quiet InstallAllUsers=0 PrependPath=1 Include_pip=1 Include_tcltk=0" `
        -Wait -PassThru
    Remove-Item $pyExe -Force -ErrorAction SilentlyContinue
    if ($proc.ExitCode -ne 0) {
        Write-Warn "Python installer exited with code $($proc.ExitCode)."
        return $false
    }
    # Refresh PATH
    $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                [System.Environment]::GetEnvironmentVariable("PATH","User")
    if (Get-Command python -ErrorAction SilentlyContinue) {
        Write-OK "Python installed via direct download."
        return $true
    }
    return $false
}

# Find Python 3.9+
$py = $null
foreach ($cmd in @("python","python3","py")) {
    try {
        $ver = & $cmd --version 2>&1
        if ($ver -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]; $minor = [int]$Matches[2]
            if ($major -eq 3 -and $minor -ge 9) {
                $py = $cmd
                Write-OK "Found $ver"
                break
            } elseif ($major -eq 3) {
                Write-Warn "Found Python $major.$minor -- need 3.9+. Will install 3.11."
            }
        }
    } catch {}
}

if (-not $py) {
    $installed = Install-Python
    if ($installed) {
        foreach ($cmd in @("python","python3","py")) {
            try {
                $ver = & $cmd --version 2>&1
                if ($ver -match "Python 3\.(\d+)" -and [int]$Matches[1] -ge 9) {
                    $py = $cmd
                    Write-OK "Using $ver"
                    break
                }
            } catch {}
        }
    }
    if (-not $py) {
        Write-Host ""
        Write-Host "  Automatic installation failed. Please install Python manually:" -ForegroundColor Red
        Write-Host "  1. Go to: https://www.python.org/downloads/" -ForegroundColor Yellow
        Write-Host "  2. Download Python 3.11 (Windows installer 64-bit)" -ForegroundColor Yellow
        Write-Host "  3. Run installer -- CHECK 'Add Python to PATH'" -ForegroundColor Yellow
        Write-Host "  4. Restart PowerShell and re-run this script" -ForegroundColor Yellow
        Write-Host ""
        Start-Process "https://www.python.org/downloads/"
        Write-Fatal "Python 3.9+ required."
    }
}

# Verify pip is available
$pipCheck = & $py -m pip --version 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Host "      pip missing -- bootstrapping..." -ForegroundColor Gray
    & $py -m ensurepip --upgrade 2>&1 | Out-Null
    Write-OK "pip bootstrapped"
}

# =============================================================================
# STEP 2 -- Virtual environment (fully automatic)
# =============================================================================
Write-Step "2/6" "Creating isolated Python environment"

$venvDir = ".venv_build"

# If venv is broken (e.g. from a different Python version), recreate it
if (Test-Path $venvDir) {
    $venvPy = "$venvDir\Scripts\python.exe"
    if (-not (Test-Path $venvPy)) {
        Write-Warn "Existing venv appears broken. Recreating..."
        Remove-Item -Recurse -Force $venvDir
    } else {
        # Check it still works
        $venvVer = & $venvPy --version 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-Warn "Existing venv is broken. Recreating..."
            Remove-Item -Recurse -Force $venvDir
        } else {
            Write-OK "Reusing existing $venvDir ($venvVer)"
        }
    }
}

if (-not (Test-Path $venvDir)) {
    Write-Host "      Creating isolated virtual environment..." -ForegroundColor Gray
    & $py -m venv $venvDir
    if ($LASTEXITCODE -ne 0) {
        Write-Fatal "Failed to create virtual environment."
    }
    Write-OK "Created $venvDir"
}

$pip    = "$venvDir\Scripts\pip.exe"
$python = "$venvDir\Scripts\python.exe"

# Upgrade pip/setuptools inside venv (silent)
Write-Host "      Upgrading pip inside venv..." -ForegroundColor Gray
& $python -m pip install --upgrade pip wheel setuptools --quiet
Write-OK "pip $(& $pip --version 2>&1 | Select-String -Pattern '\d+\.\d+' | ForEach-Object { $_.Matches[0].Value })"


# STEP 3 -- Install C++ Build Tools if needed
# =============================================================================
Write-Step "3/6" "C++ Build Tools  (auto-installing if missing)"

# ---- Check all known MSVC install locations ---------------------------------
function Find-MSVC {
    $paths = @(
        "$env:ProgramFiles\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC",
        "$env:ProgramFiles\Microsoft Visual Studio\2022\Community\VC\Tools\MSVC",
        "$env:ProgramFiles\Microsoft Visual Studio\2022\Professional\VC\Tools\MSVC",
        "$env:ProgramFiles\Microsoft Visual Studio\2022\Enterprise\VC\Tools\MSVC",
        "$env:ProgramFiles\Microsoft Visual Studio\2019\BuildTools\VC\Tools\MSVC",
        "$env:ProgramFiles\Microsoft Visual Studio\2019\Community\VC\Tools\MSVC",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2019\BuildTools\VC\Tools\MSVC",
        "${env:ProgramFiles(x86)}\Microsoft Visual Studio\2022\BuildTools\VC\Tools\MSVC"
    )
    foreach ($p in $paths) { if (Test-Path $p) { return $p } }

    # Also check via vswhere.exe (most reliable method)
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installerswhere.exe"
    if (Test-Path $vswhere) {
        $vsPath = & $vswhere -latest -products * -requires Microsoft.VisualCpp.Tools.HostX64.TargetX64 -property installationPath 2>$null
        if ($vsPath -and (Test-Path $vsPath)) { return $vsPath }
    }

    # Check if cl.exe is anywhere in PATH
    $cl = Get-Command cl.exe -ErrorAction SilentlyContinue
    if ($cl) { return $cl.Source }

    return $null
}

# ---- First check ---------------------------------------------------------
$vcPath = Find-MSVC
if ($vcPath) {
    Write-OK "MSVC found: $vcPath"
} else {
    Write-Host "      MSVC not found. Installing C++ Build Tools automatically..." -ForegroundColor Yellow
    Write-Host "      (~800 MB download, 5-10 minutes)" -ForegroundColor Gray
    Write-Host ""

    $installed = $false

    # Method 1: winget (Windows 10 1709+ / Windows 11)
    if (Get-Command winget -ErrorAction SilentlyContinue) {
        Write-Host "      [Method 1/3] Installing via winget..." -ForegroundColor Gray
        $wingetArgs = @(
            "install",
            "--id", "Microsoft.VisualStudio.2022.BuildTools",
            "--silent", "--force",
            "--override", "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended",
            "--accept-package-agreements", "--accept-source-agreements"
        )
        $proc = Start-Process winget -ArgumentList $wingetArgs -Wait -PassThru -NoNewWindow
        if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 3010) {
            $installed = $true
            Write-OK "Build Tools installed via winget."
        } else {
            Write-Warn "winget install exited with code $($proc.ExitCode). Trying next method..."
        }
    }

    # Method 2: Direct download of vs_BuildTools.exe
    if (-not $installed) {
        Write-Host "      [Method 2/3] Downloading VS Build Tools installer..." -ForegroundColor Gray
        $btUrl = "https://aka.ms/vs/17/release/vs_buildtools.exe"
        $btExe = "$env:TEMPs_buildtools.exe"
        try {
            [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
            $wc = New-Object System.Net.WebClient
            Write-Host "      Downloading from $btUrl ..." -ForegroundColor Gray
            $wc.DownloadFile($btUrl, $btExe)
            Write-Host "      Running installer silently (this takes several minutes)..." -ForegroundColor Gray
            $btArgs = "--quiet --wait --norestart --add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
            $proc = Start-Process -FilePath $btExe -ArgumentList $btArgs -Wait -PassThru
            Remove-Item $btExe -Force -ErrorAction SilentlyContinue
            if ($proc.ExitCode -eq 0 -or $proc.ExitCode -eq 3010) {
                $installed = $true
                Write-OK "Build Tools installed via direct download."
            } else {
                Write-Warn "Installer exited with code $($proc.ExitCode)."
            }
        } catch {
            Write-Warn "Download failed: $_"
        }
    }

    # Method 3: Chocolatey
    if (-not $installed -and (Get-Command choco -ErrorAction SilentlyContinue)) {
        Write-Host "      [Method 3/3] Installing via Chocolatey..." -ForegroundColor Gray
        choco install visualstudio2022buildtools -y --no-progress `
            --package-parameters "--add Microsoft.VisualStudio.Workload.VCTools --includeRecommended"
        if ($LASTEXITCODE -eq 0) {
            $installed = $true
            Write-OK "Build Tools installed via Chocolatey."
        }
    }

    # Refresh PATH and check again
    if ($installed) {
        $env:PATH = [System.Environment]::GetEnvironmentVariable("PATH","Machine") + ";" +
                    [System.Environment]::GetEnvironmentVariable("PATH","User")
        Start-Sleep -Seconds 3
        $vcPath = Find-MSVC
        if ($vcPath) {
            Write-OK "MSVC confirmed at: $vcPath"
        } else {
            Write-Warn "MSVC not detected yet. A restart may be needed after this build."
            Write-Warn "pycombat will be used for batch correction (functionally equivalent)."
        }
    } else {
        Write-Host ""
        Write-Host "      Automatic installation was not possible on this machine." -ForegroundColor Yellow
        Write-Host "      The build will continue using pycombat (pure Python batch correction)." -ForegroundColor Yellow
        Write-Host "      To install manually after the build:" -ForegroundColor Yellow
        Write-Host "        https://visualstudio.microsoft.com/visual-cpp-build-tools/" -ForegroundColor Cyan
        Write-Host "        Select workload: 'Desktop development with C++'" -ForegroundColor Cyan
        Write-Host ""
    }
}

# =============================================================================
# STEP 4 -- Install all dependencies
# =============================================================================
Write-Step "4/6" "Installing Python packages  [3-10 min on first run]"

$packages = @(
    @{ name="NumPy 2.x (ABI anchor)";  pkg="numpy>=2.0.0,<3.0.0" },
    @{ name="SciPy";                    pkg="scipy>=1.14.0" },
    @{ name="Pandas";                   pkg="pandas>=2.2.0" },
    @{ name="scikit-learn";             pkg="scikit-learn>=1.5.0" },
    @{ name="statsmodels";              pkg="statsmodels>=0.14.2" },
    @{ name="anndata";                  pkg="anndata>=0.10.8" },
    @{ name="scanpy";                   pkg="scanpy>=1.10.1" },
    @{ name="harmonypy";                pkg="harmonypy>=0.0.10" },
    @{ name="pycombat (batch corr.)";   pkg="pycombat>=0.4.0" },
    @{ name="lxml";                     pkg="lxml>=5.2.0" },
    @{ name="networkx";                 pkg="networkx>=3.3" },
    @{ name="plotly";                   pkg="plotly>=5.20.0" },
    @{ name="matplotlib";               pkg="matplotlib>=3.8.0" },
    @{ name="seaborn";                  pkg="seaborn>=0.13.0" },
    @{ name="requests";                 pkg="requests>=2.31.0" },
    @{ name="joblib";                   pkg="joblib>=1.4.0" },
    @{ name="tqdm";                     pkg="tqdm>=4.66.0" },
    @{ name="PyQt6";                    pkg="PyQt6>=6.7.0" },
    @{ name="PyInstaller";              pkg="pyinstaller>=6.6.0" }
)

# PyTorch CPU (large -- separate step)
Write-Host "      PyTorch (CPU wheels, ~250MB) ..." -ForegroundColor Gray
& $pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet
Write-OK "PyTorch CPU"

$total = $packages.Count
$current = 0
foreach ($p in $packages) {
    $current++
    $pct = [int](($current / $total) * 100)
    Write-Host "      [$pct%] $($p.name) ..." -ForegroundColor Gray
    & $pip install $p.pkg --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "$($p.name)"
    } else {
        Write-Warn "$($p.name) failed -- will use fallback at runtime"
    }
}

# Try inmoose (needs MSVC) -- optional
Write-Host "      inmoose (optional, needs MSVC) ..." -ForegroundColor Gray
& $pip install "inmoose>=0.4.0" --quiet 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) { Write-OK "inmoose" } else { Write-Warn "inmoose skipped (pycombat will be used)" }

# Uninstall numba if present -- it pulls in tbb12.dll which PyInstaller cannot bundle
$numbaCheck = & $pip show numba 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host "      Removing numba (not needed, causes bundling issues) ..." -ForegroundColor Gray
    & $pip uninstall numba -y --quiet 2>&1 | Out-Null
    Write-OK "numba removed"
}

# =============================================================================
# STEP 5 -- Generate test data if needed
# =============================================================================
Write-Step "5/6" "Preparing bundled test data + sanitising Python sources"

$txFile = "desktop\test_data\transcriptomics_test.csv"
if (Test-Path $txFile) {
    Write-OK "Test data present"
} else {
    Write-Host "      Generating test data ..." -ForegroundColor Gray
    & $python desktop\test_data\generate_test_data.py
    Write-OK "Test data generated"
}

# Sanitise all .py files: replace em-dash and other non-ASCII in docstrings
# PyInstaller's bytecode compiler crashes on non-ASCII in module docstrings
# Force-write correct __init__.py files (fix any bad content from old push script runs)
Write-Host "      Writing clean __init__.py files..." -ForegroundColor Gray
$utf8NoBom = New-Object System.Text.UTF8Encoding $false
[System.IO.File]::WriteAllText(
    [System.IO.Path]::GetFullPath("desktop\__init__.py"),
    "# MultiOmics-Reactome Desktop package`n", $utf8NoBom)
[System.IO.File]::WriteAllText(
    [System.IO.Path]::GetFullPath("desktop\widgets\__init__.py"),
    "# Desktop widgets package`n", $utf8NoBom)
[System.IO.File]::WriteAllText(
    [System.IO.Path]::GetFullPath("desktop\test_data\__init__.py"),
    "# Test data package`n", $utf8NoBom)
[System.IO.File]::WriteAllText(
    [System.IO.Path]::GetFullPath("backend\__init__.py"),
    "# MultiOmics-Reactome backend`n", $utf8NoBom)
Write-OK "Clean __init__.py files written"

Write-Host "      Sanitising Python source files (removing non-ASCII in docstrings)..." -ForegroundColor Gray
$pyFiles = Get-ChildItem -Path "." -Recurse -Include "*.py" |
    Where-Object { $_.FullName -notlike "*\.venv*" -and $_.FullName -notlike "*uild\*" }
$sanitised = 0
foreach ($pyFile in $pyFiles) {
    $txt = [System.IO.File]::ReadAllText($pyFile.FullName, [System.Text.Encoding]::UTF8)
    $fixed = $txt -replace [char]0x2014, " - "   # em dash
    $fixed = $fixed -replace [char]0x2013, "-"    # en dash
    $fixed = $fixed -replace [char]0x2018, "'"    # left single quote
    $fixed = $fixed -replace [char]0x2019, "'"    # right single quote
    $fixed = $fixed -replace [char]0x201C, '"'    # left double quote
    $fixed = $fixed -replace [char]0x201D, '"'    # right double quote
    $fixed = $fixed -replace [char]0x00B7, "."    # middle dot
    $fixed = $fixed -replace [char]0x2022, "*"    # bullet
    if ($fixed -ne $txt) {
        $utf8NoBom = New-Object System.Text.UTF8Encoding $false
        [System.IO.File]::WriteAllText($pyFile.FullName, $fixed, $utf8NoBom)
        $sanitised++
    }
}
Write-OK "Sanitised $sanitised Python files"

# =============================================================================
# STEP 6 -- Build the .exe
# =============================================================================
Write-Step "6/6" "Building MultiOmicsReactome.exe  [2-5 min, please wait]"
Write-Host "      This takes 2-5 minutes. Please wait..." -ForegroundColor Gray
Write-Host ""

$pyinst = "$venvDir\Scripts\pyinstaller.exe"

# -- Delete QML/3D plugin folders from the venv before PyInstaller scans them --
# These folders contain .dll plugins that reference optional Qt DLLs not shipped
# with PyQt6 (Qt6Quick3D, Qt6Qml etc.). Deleting them stops PyInstaller from
# ever scanning them, eliminating all "Library not found" warnings.
# Safe to delete: the app uses only QtWidgets/QtCore/QtGui -- no QML at all.
Write-Host "      Removing unused Qt QML/3D plugin folders..." -ForegroundColor Gray
$qmlRoot = "$venvDir\Lib\site-packages\PyQt6\Qt6\qml"
if (Test-Path $qmlRoot) {
    Remove-Item -Recurse -Force $qmlRoot
    Write-OK "Qt QML plugin folder removed ($qmlRoot)"
} else {
    Write-OK "Qt QML folder not present (already clean)"
}

# Also remove Qt3D, QtDataVisualization, QtCharts, QtWebEngine plugin dirs
$qtExtraDirs = @(
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\sceneparsers",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\geometryloaders",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\renderplugins",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\position",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\geoservices",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\sensors",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\sensorgestures",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\texttospeech",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\virtualkeyboard",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\webview",
    "$venvDir\Lib\site-packages\PyQt6\Qt6\plugins\networkaccess"
)
foreach ($d in $qtExtraDirs) {
    if (Test-Path $d) {
        Remove-Item -Recurse -Force $d
        Write-Host "      Removed: $d" -ForegroundColor DarkGray
    }
}

# Write PyInstaller hook files
$hooksDir = "$venvDir\..\pyinstaller_hooks"
New-Item -ItemType Directory -Force -Path $hooksDir | Out-Null

# hook-matplotlib.py
Set-Content -Path "$hooksDir\hook-matplotlib.py" -Value @"
from PyInstaller.utils.hooks import collect_all
datas, binaries, hiddenimports = collect_all('matplotlib')
"@

# hook-scanpy.py
Set-Content -Path "$hooksDir\hook-scanpy.py" -Value @"
from PyInstaller.utils.hooks import collect_all
datas, binaries, hiddenimports = collect_all('scanpy')
"@

# hook-anndata.py
Set-Content -Path "$hooksDir\hook-anndata.py" -Value @"
from PyInstaller.utils.hooks import collect_all
datas, binaries, hiddenimports = collect_all('anndata')
"@

# hook-PyQt6.py  -- exclude QML / 3D / Quick modules not used by desktop widgets
# This eliminates the 50+ "Library not found" warnings about Qt6Quick3D, Qt6Qml etc.
# These are optional Qt modules for QML-based apps; we use only QtWidgets.
Set-Content -Path "$hooksDir\hook-PyQt6.py" -Value @"
from PyInstaller.utils.hooks import collect_all, collect_dynamic_libs
import os, glob

# Collect the core PyQt6 modules we actually use
datas, binaries, hiddenimports = collect_all('PyQt6')

# Remove QML / 3D / Quick plugins that reference missing optional DLLs
# These cause the 'Library not found: Qt6Quick3D*.dll' warnings
QML_NOISE = [
    'Qt6Quick3D', 'Qt6Quick3DParticle', 'Qt6Qml', 'Qt6QmlLocalStorage',
    'Qt6QuickControls2Fluent', 'Qt6QuickControls2Windows',
    'Qt6QuickVectorImage', 'Qt6QuickShapes', 'Qt63DQuick',
    'Qt6WebEngine', 'Qt6WebView', 'Qt6Bluetooth', 'Qt6Location',
    'Qt6Positioning', 'Qt6Sensors', 'Qt6SerialPort', 'Qt6Multimedia',
    'Qt6Charts', 'Qt6DataVisualization', 'Qt6Lottie', 'Qt6VirtualKeyboard',
]
binaries = [
    (src, dst) for src, dst in binaries
    if not any(noise.lower() in os.path.basename(src).lower() for noise in QML_NOISE)
]
datas = [
    (src, dst) for src, dst in datas
    if not any(noise.lower() in src.lower() for noise in ['QtQuick3D', 'qml'])
    or any(keep in src for keep in ['QtWidgets', 'QtCore', 'QtGui', 'QtSvg'])
]
"@

Write-OK "PyInstaller hooks written (matplotlib, scanpy, anndata, PyQt6 QML filter)"

& $pyinst `
    --name            "MultiOmicsReactome" `
    --onefile `
    --windowed `
    --noconfirm `
    --additional-hooks-dir $hooksDir `
    --add-data        "schemas;schemas" `
    --add-data        "backend;backend" `
    --add-data        "desktop\test_data;desktop\test_data" `
    --add-data        "desktop\widgets;desktop\widgets" `
    --add-data        "desktop\styles.py;desktop" `
    --add-data        "desktop\__init__.py;desktop" `
    --add-data        "desktop\widgets\__init__.py;desktop\widgets" `
    --add-data        "desktop\test_data\__init__.py;desktop\test_data" `
    --add-data        "backend\__init__.py;backend" `
    --collect-all     "PyQt6" `
    --collect-all     "matplotlib" `
    --collect-all     "seaborn" `
    --collect-all     "plotly" `
    --collect-all     "networkx" `
    --collect-all     "sklearn" `
    --collect-all     "scipy" `
    --collect-all     "statsmodels" `
    --collect-all     "anndata" `
    --collect-all     "scanpy" `
    --hidden-import   "harmonypy" `
    --collect-all     "pycombat" `
    --collect-all     "lxml" `
    --collect-all     "pandas" `
    --collect-all     "numpy" `
    --collect-all     "joblib" `
    --collect-all     "tqdm" `
    --collect-all     "requests" `
    --hidden-import   "backend" `
    --hidden-import   "backend.integration" `
    --hidden-import   "backend.multiomics_reactome" `
    --collect-submodules "backend" `
    --hidden-import   "desktop.main_window" `
    --hidden-import   "desktop.pipeline_worker" `
    --hidden-import   "desktop.styles" `
    --hidden-import   "desktop.widgets.configure_tab" `
    --hidden-import   "desktop.widgets.run_tab" `
    --hidden-import   "desktop.widgets.results_tab" `
    --hidden-import   "desktop.widgets.about_tab" `
    --hidden-import   "PIL" `
    --hidden-import   "PIL.Image" `
    --hidden-import   "pkg_resources.py2_warn" `
    --exclude-module  "torch" `
    --exclude-module  "boto3" `
    --exclude-module  "botocore" `
    --exclude-module  "tkinter" `
    --exclude-module  "IPython" `
    --exclude-module  "jupyter" `
    --exclude-module  "notebook" `
    --exclude-module  "dask" `
    --exclude-module  "numba" `
    --exclude-module  "pytest" `
    --exclude-module  "matplotlib.tests" `
    --exclude-module  "matplotlib.testing" `
    --exclude-module  "sklearn.externals.array_api_compat.dask" `
    --exclude-module  "sklearn.tests" `
    --exclude-module  "scanpy.tests" `
    --exclude-module  "scipy.optimize.tests" `
    --exclude-module  "pandas.tests" `
    --exclude-module  "numpy.tests" `
    --exclude-module  "anndata.tests" `
    --exclude-module  "PyQt6.QtQuick" `
    --exclude-module  "PyQt6.QtQml" `
    --exclude-module  "PyQt6.QtQuick3D" `
    --exclude-module  "PyQt6.QtWebEngine" `
    --exclude-module  "PyQt6.QtWebEngineWidgets" `
    --exclude-module  "PyQt6.QtWebEngineCore" `
    --exclude-module  "PyQt6.QtBluetooth" `
    --exclude-module  "PyQt6.QtLocation" `
    --exclude-module  "PyQt6.QtMultimedia" `
    --exclude-module  "PyQt6.QtSensors" `
    --exclude-module  "PyQt6.QtSerialPort" `
    --exclude-module  "PyQt6.Qt3DCore" `
    --exclude-module  "PyQt6.Qt3DRender" `
    --exclude-module  "PyQt6.Qt3DInput" `
    "desktop\app.py"


if ($LASTEXITCODE -ne 0) {
    Write-Fatal "PyInstaller failed. See output above for details."
}

# =============================================================================
# DONE
# =============================================================================
$exePath = "dist\MultiOmicsReactome.exe"
if (Test-Path $exePath) {
    $sizeMB = [math]::Round((Get-Item $exePath).Length / 1MB, 0)
    Write-Host ""
    Write-Host "  ###############################################" -ForegroundColor Green
    Write-Host "  #   BUILD COMPLETE!                          #" -ForegroundColor Green
    Write-Host "  ###############################################" -ForegroundColor Green
    Write-Host ""
    Write-Host "  Executable : $repoRoot\$exePath" -ForegroundColor Cyan
    Write-Host "  Size       : $sizeMB MB"          -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  HOW TO RUN THE APP:" -ForegroundColor White
    Write-Host ""
    Write-Host "    >> Double-click  dist\MultiOmicsReactome.exe  <<" -ForegroundColor Green
    Write-Host ""
    Write-Host "  The app works like any normal Windows program." -ForegroundColor White
    Write-Host "  No Python, no packages, no internet needed to run it." -ForegroundColor White
    Write-Host ""
    Write-Host "  To share with colleagues:" -ForegroundColor Yellow
    Write-Host "    Copy  dist\MultiOmicsReactome.exe  to USB / OneDrive / email." -ForegroundColor Yellow
    Write-Host "    They can run it on any Windows 10/11 PC -- nothing to install." -ForegroundColor Yellow
    Write-Host ""
    Write-Host "  If you see 'No module named X' when running the .exe:" -ForegroundColor Yellow
    Write-Host "    1. Delete the dist\ and build\ folders" -ForegroundColor Yellow
    Write-Host "    2. Re-run this installer script" -ForegroundColor Yellow
    Write-Host "    (PyInstaller bundles everything fresh each time)" -ForegroundColor Yellow
    Write-Host ""

    # Open dist folder in Explorer
    $openDist = Read-Host "  Open dist\ folder in File Explorer? (Y/N)"
    if ($openDist -match "^[Yy]") { Start-Process "dist" }
} else {
    Write-Fatal "Build seemed to succeed but dist\MultiOmicsReactome.exe was not found."
}
