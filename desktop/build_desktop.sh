#!/usr/bin/env bash
# ─────────────────────────────────────────────────────────────────────────────
# build_desktop.sh — Build MultiOmics-Reactome standalone executables
# via PyInstaller. Run from the repo root directory.
#
# Usage:
#   bash desktop/build_desktop.sh           # current platform
#   bash desktop/build_desktop.sh --clean   # remove dist/ first
#
# Produces in dist/:
#   Linux   : dist/MultiOmicsReactome (single executable)
#   Windows : dist/MultiOmicsReactome.exe
#   macOS   : dist/MultiOmicsReactome.app  (open with Finder)
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail
CLEAN=0
for arg in "$@"; do [[ "$arg" == "--clean" ]] && CLEAN=1; done

cd "$(dirname "$0")/.."     # ensure we're in the repo root

APP_NAME="MultiOmicsReactome"
VERSION="3.0.0"
ENTRY="desktop/app.py"
ICON_ICO="desktop/resources/icon.ico"
ICON_PNG="desktop/resources/icon.png"
ICON_ICNS="desktop/resources/icon.icns"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  MultiOmics-Reactome Desktop  ·  Build v${VERSION}"
echo "  Platform : $(python -c 'import sys; print(sys.platform)')"
echo "══════════════════════════════════════════════════════════"
echo ""

[[ $CLEAN -eq 1 ]] && rm -rf dist/ build/ && echo "Cleaned dist/ and build/"

# Install deps
echo "[1/3] Installing dependencies…"
pip install --upgrade "numpy>=2.0.0,<3.0.0" -q
pip install torch --index-url https://download.pytorch.org/whl/cpu -q
pip install -r requirements.txt -q
pip install -r desktop/requirements_desktop.txt -q

# Generate test data if not present
echo "[2/3] Ensuring test data exists…"
if [[ ! -f desktop/test_data/transcriptomics_test.csv ]]; then
    python desktop/test_data/generate_test_data.py
fi

# Detect icon for current platform
ICON_ARG=""
PLAT=$(python -c "import sys; print(sys.platform)")
if   [[ "$PLAT" == "win32"  && -f "$ICON_ICO"  ]]; then ICON_ARG="--icon=$ICON_ICO"
elif [[ "$PLAT" == "darwin" && -f "$ICON_ICNS" ]]; then ICON_ARG="--icon=$ICON_ICNS"
elif [[ -f "$ICON_PNG" ]]; then ICON_ARG="--icon=$ICON_PNG"; fi

echo "[3/3] Running PyInstaller…"
pyinstaller \
    --name           "$APP_NAME" \
    --onefile \
    --windowed \
    --noconfirm \
    $ICON_ARG \
    --add-data "schemas:schemas" \
    --add-data "backend:backend" \
    --add-data "desktop/test_data:desktop/test_data" \
    --hidden-import backend \
    --hidden-import backend.integration \
    --hidden-import backend.multiomics_reactome \
    --collect-submodules backend \
    --hidden-import PyQt6 \
    --hidden-import PyQt6.QtWidgets \
    --hidden-import PyQt6.QtCore \
    --hidden-import PyQt6.QtGui \
    --hidden-import sklearn \
    --hidden-import sklearn.utils.extmath \
    --hidden-import scipy.sparse \
    --hidden-import anndata \
    --hidden-import scanpy \
    --hidden-import harmonypy \
    --hidden-import inmoose.pycombat \
    --hidden-import networkx \
    --hidden-import statsmodels.stats.multitest \
    --hidden-import lxml.etree \
    --collect-all PyQt6 \
    "$ENTRY"

echo ""
echo "══════════════════════════════════════════════════════════"
echo "  Build complete ✓"
if [[ "$PLAT" == "darwin" ]]; then
    echo "  macOS app : dist/${APP_NAME}.app"
    echo "  Run with  : open dist/${APP_NAME}.app"
elif [[ "$PLAT" == "win32" ]]; then
    echo "  Windows   : dist\\${APP_NAME}.exe"
else
    echo "  Linux     : dist/${APP_NAME}"
    echo "  Run with  : ./dist/${APP_NAME}"
fi
echo "══════════════════════════════════════════════════════════"
