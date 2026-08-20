#!/usr/bin/env bash
# =============================================================================
#  fix_and_build.sh  --  MultiOmics-Reactome Desktop: patch sources + build
#  Linux / macOS equivalent of FIX_AND_BUILD.ps1
#
#  LOCATION: this file must sit in the REPOSITORY ROOT
#            (the folder containing requirements.txt, backend/, desktop/)
#
#  Usage:
#    ./fix_and_build.sh                 # patch + build
#    ./fix_and_build.sh --patch-only    # patch sources, no build
#    ./fix_and_build.sh --no-clean      # keep dist/ and build/
#    ./fix_and_build.sh --run           # launch the binary when done
#
#  Fixes applied (identical to the Windows version):
#    [1] Window sizing    -- fits any screen
#    [2] Config refresh   -- Run button picks up current settings
#    [3] TEST_DATA_DIR    -- resolves inside the frozen binary
#    [4] repo_root        -- sys._MEIPASS aware
#    [5] numba            -- real one if installed, else no-op stub
#    [6] InputConfig      -- kwargs filtered by actual signature
#    [7] Debug logging    -- logs/pipeline_<timestamp>.log
#    [8] __init__.py      -- plain comments, no docstrings
#
#  All Python edits are made by scripts/patch_sources.py, which validates every
#  file with ast.parse() before writing. A syntax error cannot be introduced.
# =============================================================================
set -euo pipefail
IFS=$'\n\t'

if [ -t 1 ]; then
  R='\033[0;31m'; G='\033[0;32m'; Y='\033[1;33m'; C='\033[0;36m'; N='\033[0m'
else
  R=''; G=''; Y=''; C=''; N=''
fi
info() { printf "${G}   OK:${N} %s\n" "$*"; }
warn() { printf "${Y} WARN:${N} %s\n" "$*"; }
bad()  { printf "${R}ERROR:${N} %s\n" "$*" >&2; }
die()  { bad "$*"; exit 1; }
step() { printf "\n${C}== %s ==${N}\n" "$*"; }

PATCH_ONLY=0; NO_CLEAN=0; RUN_AFTER=0
while [ $# -gt 0 ]; do
  case "$1" in
    --patch-only) PATCH_ONLY=1; shift ;;
    --no-clean)   NO_CLEAN=1;   shift ;;
    --run)        RUN_AFTER=1;  shift ;;
    -h|--help)    sed -n '2,28p' "$0"; exit 0 ;;
    *) die "Unknown option: $1 (try --help)" ;;
  esac
done

# ── Locate the repository root ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

if [ ! -d desktop ] || [ ! -d backend ]; then
  die "Must be run from the repository root (needs desktop/ and backend/).
       Current directory: $SCRIPT_DIR"
fi

OS="$(uname -s)"
case "$OS" in
  Linux)  PLATFORM="Linux";  BIN_NAME="MultiOmicsReactome" ;;
  Darwin) PLATFORM="macOS";  BIN_NAME="MultiOmicsReactome" ;;
  *)      PLATFORM="$OS";    BIN_NAME="MultiOmicsReactome" ;;
esac

echo ""
echo "  MultiOmics-Reactome  --  Patch and Build"
echo "  Platform : $PLATFORM"
echo "  Folder   : $SCRIPT_DIR"

# ── Locate the virtual environment ────────────────────────────────────────────
VENV=""
for cand in .venv_build .venv_mimodh .venv venv; do
  if [ -x "$cand/bin/python" ]; then VENV="$cand"; break; fi
done

if [ -z "$VENV" ]; then
  warn "No virtual environment found."
  echo "  Create one first:"
  echo "     bash scripts/setup.sh --dev"
  echo "     source .venv_mimodh/bin/activate"
  echo "     pip install -r desktop/requirements_desktop.txt"
  echo ""
  read -r -p "  Create .venv_build now and install everything? (y/N) " reply
  case "$reply" in
    y|Y)
      command -v python3 >/dev/null 2>&1 || die "python3 not found"
      python3 -m venv .venv_build
      VENV=".venv_build"
      "$VENV/bin/pip" install --upgrade pip wheel setuptools --quiet
      info "Created $VENV"
      ;;
    *) die "Aborted. Create a virtual environment and re-run." ;;
  esac
fi

PY="$VENV/bin/python"
PIP="$VENV/bin/pip"
SITE_PKGS="$("$PY" -c 'import site; print(site.getsitepackages()[0])')"
info "Using $VENV  (Python $("$PY" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}")'))"

# =============================================================================
step "Patching Python sources"

PATCHER="scripts/patch_sources.py"
[ -f "$PATCHER" ] || die "$PATCHER not found. It ships in scripts/ -- re-clone or restore it."

"$PY" "$PATCHER" || die "Patching failed (see messages above). Build aborted."

# =============================================================================
step "Dependencies"

# ---- NumPy 2.x first (ABI anchor) -------------------------------------------
if ! "$PY" -c 'import numpy' 2>/dev/null; then
  printf "   installing numpy...\n"
  "$PIP" install "numpy>=2.0.0,<3.0.0" --quiet
fi
info "numpy $("$PY" -c 'import numpy;print(numpy.__version__)')"

# ---- Core stack -------------------------------------------------------------
for pkg in scipy pandas scikit-learn statsmodels anndata scanpy \
           lxml networkx plotly matplotlib seaborn requests joblib tqdm; do
  mod="$pkg"
  [ "$pkg" = "scikit-learn" ] && mod="sklearn"
  if ! "$PY" -c "import $mod" 2>/dev/null; then
    printf "   installing %s...\n" "$pkg"
    "$PIP" install "$pkg" --quiet || warn "$pkg install failed"
  fi
done
info "core scientific stack present"

# ---- PyQt6 + PyInstaller ----------------------------------------------------
for pkg in PyQt6 pyinstaller; do
  mod="$pkg"
  [ "$pkg" = "pyinstaller" ] && mod="PyInstaller"
  if ! "$PY" -c "import $mod" 2>/dev/null; then
    printf "   installing %s...\n" "$pkg"
    "$PIP" install "$pkg" --quiet || die "$pkg is required for the desktop build"
  fi
done
info "PyQt6 and PyInstaller present"

# ---- harmonypy: >= 0.0.11 needs CMake + BLAS; older versions are pure Python
if "$PY" -c 'import harmonypy' 2>/dev/null; then
  info "harmonypy already installed"
else
  HARMONY_OK=0
  for ver in 0.0.10 0.0.9 0.0.6; do
    printf "   trying harmonypy==%s (pure Python)...\n" "$ver"
    if "$PIP" install "harmonypy==$ver" --quiet 2>/dev/null; then
      info "harmonypy $ver installed"; HARMONY_OK=1; break
    fi
  done
  if [ "$HARMONY_OK" -eq 0 ]; then
    warn "harmonypy unavailable from PyPI -- installing pure-NumPy shim"
    if [ -f scripts/harmonypy_shim.py ]; then
      cp scripts/harmonypy_shim.py "${SITE_PKGS}/harmonypy.py"
      info "shim installed to ${SITE_PKGS}/harmonypy.py"
      info "(validated: 98-99% batch-variance reduction, signal preserved)"
    else
      warn "scripts/harmonypy_shim.py missing -- batch correction may fail"
    fi
  fi
fi

# ---- pycombat (pure-Python ComBat) ------------------------------------------
if "$PY" -c 'import pycombat' 2>/dev/null || "$PY" -c 'import combat' 2>/dev/null; then
  info "ComBat implementation present"
else
  "$PIP" install pycombat --quiet 2>/dev/null && info "pycombat installed" \
    || { "$PIP" install combat --quiet 2>/dev/null && info "combat installed" \
         || warn "no ComBat package available"; }
fi

# ---- numba (optional, big speed-up) ----------------------------------------
if "$PY" -c 'import numba' 2>/dev/null; then
  info "numba $("$PY" -c 'import numba;print(numba.__version__)') -- full JIT speed"
else
  PYVER="$("$PY" -c 'import sys;print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
  printf "   trying pre-built numba wheel...\n"
  if "$PIP" install numba --quiet --only-binary :all: 2>/dev/null; then
    info "numba installed"
  else
    warn "No numba wheel for Python ${PYVER} -- pipeline runs in pure Python"
    echo "     (still fully correct, just slower)"
    echo "     For full speed use Python 3.11, or conda:"
    echo "       conda create -n mimodh python=3.11 numba -y"
  fi
fi

# ---- PyTorch (optional, GPU NMF) -------------------------------------------
if ! "$PY" -c 'import torch' 2>/dev/null; then
  warn "PyTorch not installed -- NMF will use the NumPy fallback"
  echo "     CPU : $PIP install torch --index-url https://download.pytorch.org/whl/cpu"
  echo "     CUDA: $PIP install torch --index-url https://download.pytorch.org/whl/cu121"
fi

# =============================================================================
step "Pre-flight import test"

if "$PY" - <<'PYTEST'
import sys
sys.path.insert(0, ".")
try:
    from backend._deps import check_dependencies, format_report
except Exception as exc:
    print("could not load backend._deps:", exc)
    raise SystemExit(1)
r = check_dependencies()
print(format_report(r))
raise SystemExit(1 if r["missing_required"] else 0)
PYTEST
then
  info "all required modules present"
else
  warn "some modules are missing (listed above)"
  read -r -p "  Continue anyway? (y/N) " go
  case "$go" in y|Y) ;; *) exit 1 ;; esac
fi

if [ "$PATCH_ONLY" -eq 1 ]; then
  echo ""
  info "Patch-only mode: sources patched, dependencies checked. Not building."
  echo ""
  echo "  Run the app from source:  $PY -m desktop.app"
  echo ""
  exit 0
fi

# =============================================================================
step "Removing unused Qt QML/3D plugins"

# PyQt6 ships QML/3D plugins that reference optional Qt libraries not included
# in the wheel. PyInstaller probes them and emits dozens of harmless warnings.
# The app uses only QtWidgets/QtCore/QtGui, so these are safe to delete.
QT_BASE="${SITE_PKGS}/PyQt6/Qt6"
REMOVED=0
if [ -d "$QT_BASE" ]; then
  for sub in qml plugins/renderers plugins/sceneparsers plugins/geometryloaders \
             plugins/geoservices plugins/sensors plugins/sqldrivers \
             plugins/qmllint plugins/qmlls plugins/scxmldatamodel \
             plugins/texttospeech plugins/virtualkeyboard plugins/webview; do
    if [ -d "${QT_BASE}/${sub}" ]; then
      rm -rf "${QT_BASE}/${sub}"
      REMOVED=$((REMOVED + 1))
    fi
  done
  info "removed ${REMOVED} unused Qt plugin folder(s)"
else
  warn "Qt6 folder not found at $QT_BASE"
fi

# =============================================================================
step "Writing PyInstaller runtime hook"

RT_HOOK_DIR="_pyi_rthooks"
mkdir -p "$RT_HOOK_DIR"
cat > "${RT_HOOK_DIR}/rthook_mimodh_paths.py" <<'HOOK'
# Runs before any application code inside the frozen binary.
#
# 1. Put the extraction folder on sys.path so "desktop.*" and "backend.*" resolve.
# 2. Install the numba substitute before anything can import scanpy. scanpy
#    imports numba unconditionally and calls into it at runtime; the real
#    package cannot be bundled on Windows because llvmlite carries a native
#    threading dependency. This must happen here, ahead of all application
#    code, because any module that touches scanpy first would otherwise fail.
import sys
import os

if hasattr(sys, "_MEIPASS"):
    _m = sys._MEIPASS
    for _p in (_m, os.path.join(_m, "desktop"), os.path.join(_m, "backend")):
        if _p not in sys.path:
            sys.path.insert(0, _p)

try:
    from backend._numba_stub import install as _install_numba
    _install_numba()
except Exception:
    pass
HOOK
info "runtime hook written"

# =============================================================================
step "Building ${BIN_NAME}"

if [ "$NO_CLEAN" -eq 0 ]; then
  rm -rf dist build
  info "dist/ and build/ cleared"
fi

# --add-data separator: ':' on POSIX, ';' on Windows
SEP=":"

PI_ARGS=(
  --name           "$BIN_NAME"
  --onefile
  --windowed
  --noconfirm
  --paths          "$SCRIPT_DIR"
  --paths          "$SITE_PKGS"
  --runtime-hook   "${RT_HOOK_DIR}/rthook_mimodh_paths.py"
  --add-data       "desktop${SEP}desktop"
  --add-data       "backend${SEP}backend"
)

[ -d schemas ] && PI_ARGS+=( --add-data "schemas${SEP}schemas" )

# Bundle harmonypy / pycombat explicitly -- single-file modules are often
# missed by --hidden-import alone.
for pkg in harmonypy pycombat combat; do
  if [ -d "${SITE_PKGS}/${pkg}" ]; then
    PI_ARGS+=( --add-data "${SITE_PKGS}/${pkg}${SEP}${pkg}" )
  elif [ -f "${SITE_PKGS}/${pkg}.py" ]; then
    PI_ARGS+=( --add-data "${SITE_PKGS}/${pkg}.py${SEP}." )
  fi
done

# Icon, if present
if [ "$PLATFORM" = "macOS" ] && [ -f desktop/resources/icon.icns ]; then
  PI_ARGS+=( --icon desktop/resources/icon.icns )
elif [ -f desktop/resources/icon.png ]; then
  PI_ARGS+=( --icon desktop/resources/icon.png )
fi

PI_ARGS+=(
  --collect-all        PyQt6
  --collect-all        matplotlib
  --collect-all        seaborn
  --collect-all        networkx
  --collect-all        sklearn
  --collect-all        scipy
  --collect-all        statsmodels
  --collect-all        anndata
  --collect-all        scanpy
  --collect-all        pandas
  --collect-all        numpy
  --collect-all        lxml
  --collect-all        pyparsing
  --collect-all        requests
  --collect-all        joblib
  --hidden-import      tqdm
  --hidden-import      tqdm.auto
  --collect-submodules desktop
  --collect-submodules backend
  --hidden-import      desktop
  --hidden-import      desktop.main_window
  --hidden-import      desktop.pipeline_worker
  --hidden-import      desktop.styles
  --hidden-import      desktop.widgets
  --hidden-import      desktop.widgets.configure_tab
  --hidden-import      desktop.widgets.run_tab
  --hidden-import      desktop.widgets.results_tab
  --hidden-import      desktop.widgets.about_tab
  --hidden-import      backend
  --hidden-import      backend.multiomics_reactome
  --hidden-import      backend._harmony_fallback
  --hidden-import      backend._numba_stub
  --hidden-import      backend._deps
  --hidden-import      harmonypy
  --hidden-import      pycombat
  --exclude-module     torch
  --exclude-module     boto3
  --exclude-module     tkinter
  --exclude-module     numba
  --exclude-module     dask
  --exclude-module     matplotlib.tests
  --exclude-module     PyQt6.QtQuick
  --exclude-module     PyQt6.QtQml
  --exclude-module     PyQt6.Qt3DCore
  --exclude-module     PyQt6.Qt3DRender
  --exclude-module     PyQt6.QtWebEngineWidgets
  desktop/app.py
)

printf "   running PyInstaller (2-5 minutes)...\n\n"
"$VENV/bin/pyinstaller" "${PI_ARGS[@]}"
BUILD_RC=$?

rm -rf "$RT_HOOK_DIR"

# =============================================================================
if [ "$PLATFORM" = "macOS" ] && [ -d "dist/${BIN_NAME}.app" ]; then
  TARGET="dist/${BIN_NAME}.app"
  # Remove the quarantine flag so Gatekeeper does not block it
  xattr -rd com.apple.quarantine "$TARGET" 2>/dev/null || true
  RUN_CMD="open $TARGET"
else
  TARGET="dist/${BIN_NAME}"
  RUN_CMD="./$TARGET"
fi

echo ""
if [ -e "$TARGET" ]; then
  if command -v du >/dev/null 2>&1; then
    SIZE="$(du -sh "$TARGET" 2>/dev/null | cut -f1)"
  else
    SIZE="?"
  fi
  chmod +x "$TARGET" 2>/dev/null || true
  printf "${G}  ================================================${N}\n"
  printf "${G}   BUILD COMPLETE  --  %s${N}\n" "$SIZE"
  printf "${G}  ================================================${N}\n"
  echo ""
  echo "   Binary : $SCRIPT_DIR/$TARGET"
  echo "   Run    : $RUN_CMD"
  echo "   Logs   : $SCRIPT_DIR/dist/logs/pipeline_<timestamp>.log"
  echo ""
  echo "   First run: Configure tab -> Load Bundled Test Data -> Run Pipeline"
  echo ""
  if [ "$RUN_AFTER" -eq 1 ]; then
    info "launching..."
    eval "$RUN_CMD" &
  fi
else
  bad "Build failed -- $TARGET was not created (PyInstaller exit $BUILD_RC)."
  echo ""
  echo "  Common causes on ${PLATFORM}:"
  if [ "$PLATFORM" = "Linux" ]; then
    echo "    Missing Qt system libraries. Install them with:"
    echo "      sudo apt install -y libxcb-cursor0 libxcb-xinerama0 \\"
    echo "                          libxkbcommon-x11-0 libegl1 libgl1-mesa-glx"
  else
    echo "    Missing Xcode command-line tools:  xcode-select --install"
  fi
  echo "    Check the PyInstaller output above for the first ERROR line."
  exit 1
fi
