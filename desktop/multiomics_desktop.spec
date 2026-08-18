# -*- mode: python ; coding: utf-8 -*-
# ─────────────────────────────────────────────────────────────────────────────
# multiomics_desktop.spec — PyInstaller spec for MultiOmics-Reactome Desktop
# Alternative to build_desktop.sh for advanced packaging.
# Usage: pyinstaller desktop/multiomics_desktop.spec
# ─────────────────────────────────────────────────────────────────────────────
import sys
from pathlib import Path

ROOT    = Path(SPECPATH).parent          # repo root
VERSION = "3.0.0"
APP_NAME = "MultiOmicsReactome"

datas = [
    (str(ROOT / "schemas"),             "schemas"),
    (str(ROOT / "backend"),             "backend"),
    (str(ROOT / "desktop" / "test_data"), "desktop/test_data"),
    (str(ROOT / "desktop" / "styles.py"), "desktop"),
    (str(ROOT / "desktop" / "widgets"),   "desktop/widgets"),
]

hidden_imports = [
    "PyQt6", "PyQt6.QtWidgets", "PyQt6.QtCore", "PyQt6.QtGui",
    "sklearn.utils.extmath", "sklearn.neighbors",
    "scipy.sparse", "scipy.stats",
    "anndata", "scanpy", "harmonypy",
    "inmoose", "inmoose.pycombat",
    "networkx", "statsmodels.stats.multitest",
    "lxml", "lxml.etree",
    "gseapy", "pyvis",
    "matplotlib", "matplotlib.backends.backend_qt5agg",
    "seaborn", "plotly",
    "requests", "joblib", "tqdm",
]

a = Analysis(
    [str(ROOT / "desktop" / "app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    noarchive=False,
    optimize=1,
)

pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    [],
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,      # windowed app
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    version_info={
        "FileVersion":    (3, 0, 0, 0),
        "ProductVersion": (3, 0, 0, 0),
        "FileDescription": "MultiOmics-Reactome Desktop — MIMODH v1.0",
        "ProductName":     "MultiOmicsReactome",
        "CompanyName":     "MIMODH",
        "LegalCopyright":  "MIT License 2025",
    } if sys.platform == "win32" else None,
)

# macOS: wrap in .app bundle
if sys.platform == "darwin":
    app = BUNDLE(
        exe,
        name=f"{APP_NAME}.app",
        icon=str(ROOT / "desktop" / "resources" / "icon.icns")
             if (ROOT / "desktop" / "resources" / "icon.icns").exists() else None,
        bundle_identifier="org.mimodh.multiomics-reactome",
        info_plist={
            "NSPrincipalClass":    "NSApplication",
            "NSHighResolutionCapable": True,
            "CFBundleShortVersionString": VERSION,
            "CFBundleVersion":    VERSION,
        },
    )
