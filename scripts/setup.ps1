# =============================================================================
#  setup.ps1  --  Environment bootstrap for Windows (NumPy 2.x ABI-safe)
#  LOCATION: scripts\setup.ps1  (run from the repository root)
#
#  Usage:
#    .\scripts\setup.ps1                    pipeline only
#    .\scripts\setup.ps1 -Desktop           + PyQt6 desktop app
#    .\scripts\setup.ps1 -Desktop -Gpu      + CUDA PyTorch
#    .\scripts\setup.ps1 -Dev               + pytest, ruff, black
# =============================================================================
param([switch]$Dev, [switch]$Gpu, [switch]$Desktop)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Write-Step { param($m) Write-Host "`n=== $m ===" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "   OK: $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host " WARN: $m" -ForegroundColor Yellow }

# Run from the repository root regardless of where the script is invoked
$repoRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $repoRoot
Write-Host "  Repository: $repoRoot" -ForegroundColor Gray

Write-Step "Virtual environment"
if (Test-Path ".venv_mimodh") {
    Write-Warn ".venv_mimodh exists, reusing it"
} else {
    python -m venv .venv_mimodh
    if ($LASTEXITCODE -ne 0) { Write-Host "venv creation failed" -ForegroundColor Red; exit 1 }
}
. .\.venv_mimodh\Scripts\Activate.ps1
pip install --upgrade pip wheel setuptools --quiet
Write-OK "environment ready"

Write-Step "NumPy 2.x (ABI anchor, must be first)"
pip install "numpy>=2.0.0,<3.0.0" --quiet
Write-OK "numpy $(python -c 'import numpy; print(numpy.__version__)')"

Write-Step "Core scientific stack"
pip install "scipy>=1.14.0" "pandas>=2.2.0" "scikit-learn>=1.5.0" "statsmodels>=0.14.2" --quiet
Write-OK "scipy, pandas, scikit-learn, statsmodels"

Write-Step "Omics tools"
pip install "anndata>=0.10.8" "scanpy>=1.10.1" --quiet
Write-OK "anndata, scanpy"

# harmonypy >= 0.0.11 needs CMake + BLAS; older releases are pure Python
$harmonyOK = $false
pip show harmonypy 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { $harmonyOK = $true; Write-OK "harmonypy already installed" }
else {
    foreach ($v in @("0.0.10", "0.0.9", "0.0.6")) {
        pip install "harmonypy==$v" --quiet 2>$null | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-OK "harmonypy $v (pure Python)"; $harmonyOK = $true; break }
    }
}
if (-not $harmonyOK) {
    Write-Warn "harmonypy unavailable, installing pure-NumPy shim"
    $site = python -c "import site; print(site.getsitepackages()[0])"
    if (Test-Path "scripts\harmonypy_shim.py") {
        Copy-Item "scripts\harmonypy_shim.py" (Join-Path $site "harmonypy.py") -Force
        Write-OK "shim installed"
    }
}

pip install "pycombat>=0.4.0" --quiet 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) { Write-OK "pycombat" } else { Write-Warn "pycombat failed" }

Write-Step "PyTorch"
if ($Gpu) {
    pip install torch --index-url https://download.pytorch.org/whl/cu121 --quiet
    Write-OK "PyTorch (CUDA 12.1)"
} else {
    pip install torch --index-url https://download.pytorch.org/whl/cpu --quiet
    Write-OK "PyTorch (CPU)"
}

Write-Step "Remaining requirements"
pip install -r requirements.txt --quiet
Write-OK "requirements.txt"

Write-Step "numba (optional, big speed-up)"
pip show numba 2>$null | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-OK "numba installed, JIT enabled"
} else {
    pip install numba --quiet --only-binary :all: 2>$null | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-OK "numba installed" }
    else {
        $pv = python -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"
        Write-Warn "no numba wheel for Python $pv -- pure Python mode (still correct)"
        Write-Host "   For full speed: conda create -n mimodh python=3.11 numba -y" -ForegroundColor Gray
    }
}

if ($Desktop) {
    Write-Step "Desktop app (PyQt6)"
    pip install -r desktop\requirements_desktop.txt --quiet
    python desktop\test_data\generate_test_data.py
    Write-OK "PyQt6 + test data. Run: python -m desktop.app"
}

if ($Dev) {
    Write-Step "Dev tools"
    pip install pytest pytest-cov httpx ruff black --quiet
    Write-OK "pytest, ruff, black"
}

Write-Host ""
Write-Host "  =========================================" -ForegroundColor Green
Write-Host "   Setup complete" -ForegroundColor Green
Write-Host "  =========================================" -ForegroundColor Green
Write-Host ""
Write-Host "   Activate : .\.venv_mimodh\Scripts\Activate.ps1"
Write-Host "   CLI      : python -m backend.multiomics_reactome --mode synthetic"
if ($Desktop) { Write-Host "   Desktop  : python -m desktop.app" }
Write-Host "   Build exe: .\BUILD_APP.bat"
Write-Host ""
