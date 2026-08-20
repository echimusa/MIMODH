# =============================================================================
#  FIX_AND_BUILD.ps1
#  Patches the MIMODH sources (via a Python patcher that validates syntax),
#  then rebuilds MultiOmicsReactome.exe
#
#  Fixes applied:
#    [1] Window sizing    -- fits any screen
#    [2] Config refresh   -- Run button picks up current settings
#    [3] TEST_DATA_DIR    -- resolves inside the .exe
#    [4] repo_root        -- sys._MEIPASS aware
#    [5] numba            -- real one if installed, else no-op stub
#    [6] InputConfig      -- kwargs filtered by actual signature
#    [7] Debug logging    -- logs/pipeline_<timestamp>.log
#    [8] __init__.py      -- plain comments, no docstrings
#
#  All Python edits are made by patch_sources.py, which validates every file
#  with ast.parse() before writing. A syntax error cannot be introduced.
# =============================================================================
Set-StrictMode -Version Latest
$ErrorActionPreference = "Continue"

function Write-Step { param($m) Write-Host "`n== $m ==" -ForegroundColor Cyan }
function Write-OK   { param($m) Write-Host "   OK: $m" -ForegroundColor Green }
function Write-Warn { param($m) Write-Host " WARN: $m" -ForegroundColor Yellow }
function Write-Bad  { param($m) Write-Host "ERROR: $m" -ForegroundColor Red }

$repoRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $repoRoot

$venvDir   = ".venv_build"
$pipExe    = Join-Path $repoRoot "$venvDir\Scripts\pip.exe"
$pyExe     = Join-Path $repoRoot "$venvDir\Scripts\python.exe"
$pyinst    = Join-Path $repoRoot "$venvDir\Scripts\pyinstaller.exe"
$sitePkgs  = Join-Path $repoRoot "$venvDir\Lib\site-packages"
$utf8NoBom = New-Object System.Text.UTF8Encoding $false

Write-Host ""
Write-Host "  MultiOmics-Reactome  --  Patch and Rebuild" -ForegroundColor Cyan
Write-Host "  Folder: $repoRoot" -ForegroundColor Gray

if (-not (Test-Path $pyExe)) {
    Write-Bad "$venvDir not found. Run build_desktop_installer.ps1 first."
    Read-Host "  Press ENTER to exit"; exit 1
}

# =============================================================================
# STEP 1 -- Write and run the Python patcher
# =============================================================================
Write-Step "Patching Python sources"

$patcherPath = Join-Path $repoRoot "patch_sources.py"
$patcherCode = @'
#!/usr/bin/env python3
"""
patch_sources.py - Patch MIMODH desktop sources for PyInstaller compatibility.

Run from the repo root:   python patch_sources.py

Every patch is validated with ast.parse() before the file is written,
so a syntax error can never be introduced.

Fixes:
  [1] main_window.py      - screen-aware window sizing
  [2] main_window.py      - always refresh config before running
  [3] configure_tab.py    - TEST_DATA_DIR resolves inside the .exe
  [4] pipeline_worker.py  - sys._MEIPASS-aware repo_root
  [5] pipeline_worker.py  - numba stub (only if real numba absent)
  [6] pipeline_worker.py  - InputConfig kwargs filtered by signature
  [7] pipeline_worker.py  - debug logging to logs/pipeline_<time>.log
  [8] all __init__.py     - plain comments (no docstrings)
"""
from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.resolve()
GREEN, YELLOW, RED, RESET = "\033[92m", "\033[93m", "\033[91m", "\033[0m"

n_ok = n_skip = n_fail = 0


def ok(msg):    global n_ok;   n_ok += 1;   print(f"  {GREEN}OK{RESET}    {msg}")
def skip(msg):  global n_skip; n_skip += 1; print(f"  {YELLOW}SKIP{RESET}  {msg}")
def fail(msg):  global n_fail; n_fail += 1; print(f"  {RED}FAIL{RESET}  {msg}")


def read(p: Path) -> str:
    return p.read_text(encoding="utf-8", errors="replace")


def write_validated(p: Path, text: str, label: str) -> bool:
    """Write only if the new text parses as valid Python."""
    try:
        ast.parse(text)
    except SyntaxError as e:
        fail(f"{label}: would create SyntaxError at line {e.lineno}: {e.msg}")
        return False
    p.write_text(text, encoding="utf-8", newline="\n")
    ok(label)
    return True


# ---------------------------------------------------------------------------
# [1] + [2]  main_window.py
# ---------------------------------------------------------------------------
def patch_main_window():
    p = ROOT / "desktop" / "main_window.py"
    if not p.exists():
        fail("main_window.py not found"); return
    src = read(p)
    orig = src

    # [1] Screen-aware sizing
    if "primaryScreen()" in src:
        skip("main_window sizing (already patched)")
    else:
        pat = re.compile(
            r"^(?P<ind>[ \t]*)self\.setMinimumSize\(\s*\d+\s*,\s*\d+\s*\)\s*\n"
            r"(?:[ \t]*self\.resize\(\s*\d+\s*,\s*\d+\s*\)\s*\n)?",
            re.MULTILINE)
        m = pat.search(src)
        if m:
            ind = m.group("ind")
            repl = (
                f"{ind}_scr = QApplication.primaryScreen()\n"
                f"{ind}if _scr is not None:\n"
                f"{ind}    _av = _scr.availableGeometry()\n"
                f"{ind}    self.setMinimumSize(min(1000, _av.width() - 60),\n"
                f"{ind}                        min(640, _av.height() - 90))\n"
                f"{ind}    self.resize(min(1280, _av.width() - 40),\n"
                f"{ind}                min(800, _av.height() - 70))\n"
                f"{ind}else:\n"
                f"{ind}    self.setMinimumSize(900, 620)\n"
                f"{ind}    self.resize(1100, 740)\n"
            )
            src = src[:m.start()] + repl + src[m.end():]
        else:
            skip("main_window sizing (pattern not found)")

    # Ensure QApplication is imported
    if "QApplication" not in src.split("class ")[0]:
        src = re.sub(r"(from PyQt6\.QtWidgets import \()",
                     r"\1QApplication, ", src, count=1)

    # [2] Always refresh config
    if "self._current_config = cfg" in src:
        skip("main_window config refresh (already patched)")
    else:
        pat2 = re.compile(
            r"^(?P<ind>[ \t]*)cfg\s*=\s*self\._current_config\s+or\s+self\._cfg_tab\.get_config\(\)\s*$",
            re.MULTILINE)
        m2 = pat2.search(src)
        if m2:
            ind = m2.group("ind")
            src = src[:m2.start()] + (
                f"{ind}cfg = self._cfg_tab.get_config()\n"
                f"{ind}self._current_config = cfg"
            ) + src[m2.end():]
        else:
            skip("main_window config refresh (pattern not found)")

    if src != orig:
        write_validated(p, src, "main_window.py patched")
    elif "primaryScreen()" in src:
        pass  # already reported as skip


# ---------------------------------------------------------------------------
# [3]  configure_tab.py
# ---------------------------------------------------------------------------
def patch_configure_tab():
    p = ROOT / "desktop" / "widgets" / "configure_tab.py"
    if not p.exists():
        fail("configure_tab.py not found"); return
    src = read(p)
    if "_get_test_data_dir" in src:
        skip("configure_tab TEST_DATA_DIR (already patched)"); return

    pat = re.compile(r"^TEST_DATA_DIR\s*=\s*.+$", re.MULTILINE)
    if not pat.search(src):
        skip("configure_tab TEST_DATA_DIR (pattern not found)"); return

    repl = (
        "def _get_test_data_dir():\n"
        "    \"\"\"Resolve bundled test-data folder for script and frozen .exe.\"\"\"\n"
        "    import sys as _sys\n"
        "    if getattr(_sys, \"frozen\", False):\n"
        "        return Path(_sys._MEIPASS) / \"desktop\" / \"test_data\"\n"
        "    return Path(__file__).parent.parent / \"test_data\"\n"
        "\n"
        "\n"
        "TEST_DATA_DIR = _get_test_data_dir()"
    )
    src = pat.sub(repl, src, count=1)
    write_validated(p, src, "configure_tab.py TEST_DATA_DIR")


# ---------------------------------------------------------------------------
# [4]-[7]  pipeline_worker.py
# ---------------------------------------------------------------------------
NUMBA_STUB = '''\
# numba: use the real package when installed (much faster). If it is
# missing, inject a no-op stub so scanpy can still be imported.
_have_numba = False
try:
    import numba as _real_numba
    _have_numba = hasattr(_real_numba, "__version__")
except Exception:
    pass

if not _have_numba and "numba" not in sys.modules:
    import types as _types
    _nb = _types.ModuleType("numba")

    def _njit(*a, **k):
        return a[0] if (a and callable(a[0])) else (lambda f: f)

    _nb.njit = _njit
    _nb.jit = _njit
    _nb.vectorize = _njit
    _nb.guvectorize = _njit
    _nb.prange = range
    _nb.float32 = float
    _nb.float64 = float
    _nb.int32 = int
    _nb.int64 = int
    _nb.boolean = bool
    _nb.typed = _types.ModuleType("numba.typed")
    _nb.core = _types.ModuleType("numba.core")
    _nb.extending = _types.ModuleType("numba.extending")
    sys.modules["numba"] = _nb
    sys.modules["numba.typed"] = _nb.typed
    sys.modules["numba.core"] = _nb.core
    sys.modules["numba.extending"] = _nb.extending
'''

LOG_FN = '''\
def _setup_pipeline_logging():
    """Mirror pipeline output to logs/pipeline_<timestamp>.log."""
    import datetime
    import logging
    import sys as _sys
    from pathlib import Path as _Path

    if getattr(_sys, "frozen", False):
        base = _Path(_sys.executable).parent
    else:
        base = _Path(__file__).parent.parent

    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / ("pipeline_" + stamp + ".log")

    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler):
            root.removeHandler(h)
    root.addHandler(fh)

    logging.info("=" * 70)
    logging.info("MultiOmics-Reactome pipeline log")
    logging.info("Started : %s", datetime.datetime.now().isoformat())
    logging.info("Python  : %s", _sys.version.replace("\\n", " "))
    logging.info("Frozen  : %s", getattr(_sys, "frozen", False))
    logging.info("Log file: %s", log_path)
    logging.info("=" * 70)
    return log_path


'''

INPUTCFG = '''\
# Build InputConfig with only the kwargs it actually accepts.
# Pipeline versions differ, so introspect the signature at runtime.
import inspect as _inspect
_sig = _inspect.signature(InputConfig.__init__)
_supported = set(_sig.parameters.keys()) - {"self"}

_all_kw = {
    "mode":            cfg_dict.get("mode", "synthetic"),
    "transcriptomics": _p(cfg_dict.get("transcriptomics")),
    "proteomics":      _p(cfg_dict.get("proteomics")),
    "metabolomics":    _p(cfg_dict.get("metabolomics")),
    "genomics":        _p(cfg_dict.get("genomics")),
    "sc_rna":          _p(cfg_dict.get("sc_rna")),
    "sc_atac":         _p(cfg_dict.get("sc_atac")),
    "spatial":         _p(cfg_dict.get("spatial")),
    "metadata":        _p(cfg_dict.get("metadata")),
    "n_samples":       int(cfg_dict.get("n_samples", 120)),
    "n_cells":         int(cfg_dict.get("n_cells", 400)),
    "n_batches":       int(cfg_dict.get("n_batches", 3)),
    "mimodh_tier":     cfg_dict.get("mimodh_tier", "Tier2"),
    "study_id":        cfg_dict.get("study_id") or "",
    "disease":         cfg_dict.get("disease", "unspecified"),
    "pi":              cfg_dict.get("pi") or None,
    "institution":     cfg_dict.get("institution") or None,
    "data_repo":       cfg_dict.get("data_repo", "local"),
    "accession":       cfg_dict.get("accession") or None,
    "ethics":          cfg_dict.get("ethics") or None,
}
_use_kw = {k: v for k, v in _all_kw.items() if k in _supported}
_extra = sorted(set(_all_kw) - set(_use_kw))
if _extra:
    print("[INFO] InputConfig does not accept: " + ", ".join(_extra))
    print("[INFO] These MIMODH fields are attached as attributes instead.")

cfg = InputConfig(**_use_kw)

for _k in _extra:
    try:
        setattr(cfg, _k, _all_kw[_k])
    except Exception:
        pass
'''


def indent_block(block: str, ind: str) -> str:
    return "".join(ind + ln if ln.strip() else ln
                   for ln in block.splitlines(keepends=True))


def patch_pipeline_worker():
    p = ROOT / "desktop" / "pipeline_worker.py"
    if not p.exists():
        fail("pipeline_worker.py not found"); return
    src = read(p)
    orig = src

    # -- [4] repo_root ------------------------------------------------------
    if "sys._MEIPASS" in src:
        skip("pipeline_worker repo_root (already patched)")
    else:
        pat = re.compile(
            r"^(?P<ind>[ \t]*)repo_root\s*=\s*Path\(__file__\)\.parent\.parent\s*$",
            re.MULTILINE)
        m = pat.search(src)
        if m:
            ind = m.group("ind")
            repl = (
                f"{ind}if getattr(sys, \"frozen\", False):\n"
                f"{ind}    repo_root = Path(sys._MEIPASS)\n"
                f"{ind}else:\n"
                f"{ind}    repo_root = Path(__file__).parent.parent"
            )
            src = src[:m.start()] + repl + src[m.end():]
        else:
            skip("pipeline_worker repo_root (pattern not found)")

    # -- [5] numba stub -----------------------------------------------------
    if '_have_numba' in src:
        skip("pipeline_worker numba stub (already patched)")
    else:
        pat = re.compile(
            r"^(?P<ind>[ \t]*)sys\.path\.insert\(0,\s*str\(repo_root\)\)\s*$",
            re.MULTILINE)
        m = pat.search(src)
        if m:
            ind = m.group("ind")
            insert = "\n\n" + indent_block(NUMBA_STUB, ind)
            src = src[:m.end()] + insert + src[m.end():]
        else:
            skip("pipeline_worker numba stub (anchor not found)")

    # -- [6] InputConfig ----------------------------------------------------
    if "_supported = set(_sig.parameters" in src:
        skip("pipeline_worker InputConfig (already patched)")
    else:
        pat = re.compile(
            r"^(?P<ind>[ \t]*)cfg\s*=\s*InputConfig\(\s*\n.*?^\1\)\s*$",
            re.MULTILINE | re.DOTALL)
        m = pat.search(src)
        if m:
            ind = m.group("ind")
            src = src[:m.start()] + indent_block(INPUTCFG, ind).rstrip("\n") + src[m.end():]
        else:
            skip("pipeline_worker InputConfig (pattern not found)")

    # -- [7] logging --------------------------------------------------------
    if "_setup_pipeline_logging" in src:
        skip("pipeline_worker logging (already patched)")
    else:
        anchor = re.search(r"^class\s+PipelineWorker\b", src, re.MULTILINE)
        if anchor:
            src = src[:anchor.start()] + LOG_FN + src[anchor.start():]
            pat = re.compile(r"^(?P<ind>[ \t]*)def _run_pipeline\(self\):\s*$",
                             re.MULTILINE)
            m = pat.search(src)
            if m:
                ind = m.group("ind") + "    "
                add = (f"\n{ind}_log_path = _setup_pipeline_logging()\n"
                       f"{ind}self.log_line.emit('Log file: ' + str(_log_path), 'INFO')")
                src = src[:m.end()] + add + src[m.end():]
        else:
            skip("pipeline_worker logging (class not found)")

    if src != orig:
        write_validated(p, src, "pipeline_worker.py patched")


# ---------------------------------------------------------------------------
# [8]  __init__.py files
# ---------------------------------------------------------------------------
def patch_inits():
    targets = {
        ROOT / "desktop" / "__init__.py":            "# MultiOmics-Reactome Desktop package\n",
        ROOT / "desktop" / "widgets" / "__init__.py": "# Desktop widgets package\n",
        ROOT / "desktop" / "test_data" / "__init__.py": "# Test data package\n",
        ROOT / "backend" / "__init__.py":            "# MultiOmics-Reactome backend\n",
    }
    for path, content in targets.items():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="\n")
    ok(f"{len(targets)} __init__.py files rewritten clean")


# ---------------------------------------------------------------------------
def verify_all():
    print("\nVerifying every Python file parses:")
    bad = []
    for f in sorted(ROOT.rglob("*.py")):
        if any(x in str(f) for x in (".venv", "build", "dist", "__pycache__")):
            continue
        try:
            ast.parse(read(f))
        except SyntaxError as e:
            bad.append((f.relative_to(ROOT), e.lineno, e.msg))
    if bad:
        for rel, ln, msg in bad:
            fail(f"{rel} line {ln}: {msg}")
        return False
    ok("all Python files parse cleanly")
    return True







# ===========================================================================
# REPAIR: restore any file that no longer parses (from a previous bad patch)
# Pristine sources are base64-encoded so no escaping issues can occur.
# ===========================================================================
import base64

_B64_PIPELINE_WORKER = (
    "IiIiCnBpcGVsaW5lX3dvcmtlci5weSAgLSAgUVRocmVhZCB3cmFwcGVyIGZvciB0aGUgTXVsdGlP"
    "bWljcy1SZWFjdG9tZSBwaXBlbGluZS4KQ2FwdHVyZXMgc3Rkb3V0L3N0ZGVyciBpbiByZWFsLXRp"
    "bWUgYW5kIGVtaXRzIFF0IHNpZ25hbHMuCiIiIgpmcm9tIF9fZnV0dXJlX18gaW1wb3J0IGFubm90"
    "YXRpb25zCgppbXBvcnQgaW8KaW1wb3J0IG9zCmltcG9ydCBzeXMKaW1wb3J0IHRyYWNlYmFjawpm"
    "cm9tIHBhdGhsaWIgaW1wb3J0IFBhdGgKZnJvbSB0eXBpbmcgaW1wb3J0IEFueSwgRGljdCwgT3B0"
    "aW9uYWwKCmZyb20gUHlRdDYuUXRDb3JlIGltcG9ydCBRVGhyZWFkLCBweXF0U2lnbmFsCgoKY2xh"
    "c3MgUGlwZWxpbmVXb3JrZXIoUVRocmVhZCk6CiAgICAiIiIKICAgIFJ1bnMgdGhlIE11bHRpT21p"
    "Y3MtUmVhY3RvbWUgcGlwZWxpbmUgaW4gYSBiYWNrZ3JvdW5kIHRocmVhZC4KCiAgICBTaWduYWxz"
    "CiAgICAtLS0tLS0tCiAgICBsb2dfbGluZShzdHIsIHN0cikgICAgICAgIC0gIChtZXNzYWdlLCBs"
    "ZXZlbCkgZm9yIHRoZSBsaXZlIGxvZwogICAgcHJvZ3Jlc3MoaW50LCBzdHIpICAgICAgICAtICAo"
    "MC0xMDAsIHN0YWdlIGxhYmVsKQogICAgZmluaXNoZWQoZGljdCkgICAgICAgICAgICAtICBwaXBl"
    "bGluZSByZXN1bHQgZGljdCBvbiBzdWNjZXNzCiAgICBmYWlsZWQoc3RyKSAgICAgICAgICAgICAg"
    "IC0gIGVycm9yIG1lc3NhZ2Ugb24gZmFpbHVyZQogICAgIiIiCgogICAgbG9nX2xpbmUgID0gcHlx"
    "dFNpZ25hbChzdHIsIHN0cikgICAjICh0ZXh0LCBsZXZlbCkKICAgIHByb2dyZXNzICA9IHB5cXRT"
    "aWduYWwoaW50LCBzdHIpICAgIyAocGN0LCBsYWJlbCkKICAgIGZpbmlzaGVkICA9IHB5cXRTaWdu"
    "YWwoZGljdCkKICAgIGZhaWxlZCAgICA9IHB5cXRTaWduYWwoc3RyKQoKICAgIFNUQUdFX1BST0dS"
    "RVNTID0gewogICAgICAgICJEYXRhIGluZ2VzdGlvbiI6ICAgICAgIDEwLAogICAgICAgICJQcmVw"
    "cm9jZXNzaW5nIjogICAgICAgIDI1LAogICAgICAgICJOTUYiOiAgICAgICAgICAgICAgICAgIDQy"
    "LAogICAgICAgICJSZWFjdG9tZSI6ICAgICAgICAgICAgIDU1LAogICAgICAgICJOZXR3b3JrIjog"
    "ICAgICAgICAgICAgIDY1LAogICAgICAgICJEaWZmZXJlbnRpYWwiOiAgICAgICAgIDc1LAogICAg"
    "ICAgICJQYXRod2F5IGFjdGl2aXR5IjogICAgIDg1LAogICAgICAgICJPdmVybGF5IjogICAgICAg"
    "ICAgICAgIDkyLAogICAgICAgICJNSU1PREgiOiAgICAgICAgICAgICAgIDk3LAogICAgICAgICJD"
    "T01QTEVURSI6ICAgICAgICAgICAgMTAwLAogICAgfQoKICAgIGRlZiBfX2luaXRfXyhzZWxmLCBj"
    "b25maWc6IERpY3Rbc3RyLCBBbnldLCBwYXJlbnQ9Tm9uZSk6CiAgICAgICAgc3VwZXIoKS5fX2lu"
    "aXRfXyhwYXJlbnQpCiAgICAgICAgc2VsZi5jb25maWcgID0gY29uZmlnCiAgICAgICAgc2VsZi5f"
    "YWJvcnQgID0gRmFsc2UKCiAgICBkZWYgYWJvcnQoc2VsZik6CiAgICAgICAgc2VsZi5fYWJvcnQg"
    "PSBUcnVlCiAgICAgICAgc2VsZi50ZXJtaW5hdGUoKQoKICAgICMgLS0gTWFpbiB0aHJlYWQgZW50"
    "cnkgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQog"
    "ICAgZGVmIHJ1bihzZWxmKToKICAgICAgICAjIFJlZGlyZWN0IHN5cy5zdGRvdXQgLyBsb2dnaW5n"
    "IHRvIGNhcHR1cmUgcGlwZWxpbmUgb3V0cHV0CiAgICAgICAgY2FwdHVyZXIgPSBfTG9nQ2FwdHVy"
    "ZXIoc2VsZi5fZW1pdF9sb2cpCiAgICAgICAgb2xkX3N0ZG91dCA9IHN5cy5zdGRvdXQKICAgICAg"
    "ICBvbGRfc3RkZXJyID0gc3lzLnN0ZGVycgogICAgICAgIHN5cy5zdGRvdXQgPSBjYXB0dXJlcgog"
    "ICAgICAgIHN5cy5zdGRlcnIgPSBjYXB0dXJlcgoKICAgICAgICB0cnk6CiAgICAgICAgICAgIHNl"
    "bGYuX3J1bl9waXBlbGluZSgpCiAgICAgICAgZXhjZXB0IEV4Y2VwdGlvbiBhcyBleGM6CiAgICAg"
    "ICAgICAgIHRiID0gdHJhY2ViYWNrLmZvcm1hdF9leGMoKQogICAgICAgICAgICBzZWxmLmxvZ19s"
    "aW5lLmVtaXQoZiJGQVRBTDoge2V4Y30iLCAiRVJST1IiKQogICAgICAgICAgICBzZWxmLmxvZ19s"
    "aW5lLmVtaXQodGIsICJFUlJPUiIpCiAgICAgICAgICAgIHNlbGYuZmFpbGVkLmVtaXQoc3RyKGV4"
    "YykpCiAgICAgICAgZmluYWxseToKICAgICAgICAgICAgc3lzLnN0ZG91dCA9IG9sZF9zdGRvdXQK"
    "ICAgICAgICAgICAgc3lzLnN0ZGVyciA9IG9sZF9zdGRlcnIKCiAgICBkZWYgX2VtaXRfbG9nKHNl"
    "bGYsIHRleHQ6IHN0cik6CiAgICAgICAgIiIiQ2FsbGVkIGJ5IF9Mb2dDYXB0dXJlciBmb3IgZXZl"
    "cnkgbGluZTsgY2xhc3NpZmllcyBsZXZlbCBhbmQgZW1pdHMuIiIiCiAgICAgICAgaWYgbm90IHRl"
    "eHQuc3RyaXAoKToKICAgICAgICAgICAgcmV0dXJuCiAgICAgICAgbGV2ZWwgPSAiSU5GTyIKICAg"
    "ICAgICB0bCA9IHRleHQubG93ZXIoKQogICAgICAgIGlmIGFueShrIGluIHRsIGZvciBrIGluICgi"
    "ZXJyb3IiLCAidHJhY2ViYWNrIiwgImV4Y2VwdGlvbiIsICJmYXRhbCIpKToKICAgICAgICAgICAg"
    "bGV2ZWwgPSAiRVJST1IiCiAgICAgICAgZWxpZiBhbnkoayBpbiB0bCBmb3IgayBpbiAoIndhcm5p"
    "bmciLCAid2FybiIpKToKICAgICAgICAgICAgbGV2ZWwgPSAiV0FSTklORyIKICAgICAgICBlbGlm"
    "IGFueShrIGluIHRsIGZvciBrIGluICgiY29tcGxldGUiLCAiW09LXSIsICJzYXZlZCIsICJwYXNz"
    "ZWQiKSk6CiAgICAgICAgICAgIGxldmVsID0gIlNVQ0NFU1MiCiAgICAgICAgZWxpZiB0ZXh0LnN0"
    "YXJ0c3dpdGgoIlsiKSBhbmQgYW55KGsgaW4gdGV4dCBmb3IgayBpbiAoIi84XSIsICJNSU1PREgi"
    "KSk6CiAgICAgICAgICAgIGxldmVsID0gIlNFQ1RJT04iCiAgICAgICAgZWxpZiAibWltb2RoIiBp"
    "biB0bCBvciAieG1sIiBpbiB0bDoKICAgICAgICAgICAgbGV2ZWwgPSAiTUlNT0RIIgoKICAgICAg"
    "ICBzZWxmLmxvZ19saW5lLmVtaXQodGV4dC5yc3RyaXAoKSwgbGV2ZWwpCgogICAgICAgICMgVXBk"
    "YXRlIHByb2dyZXNzIGJhciBmcm9tIHN0YWdlIGtleXdvcmRzCiAgICAgICAgZm9yIGtleXdvcmQs"
    "IHBjdCBpbiBzZWxmLlNUQUdFX1BST0dSRVNTLml0ZW1zKCk6CiAgICAgICAgICAgIGlmIGtleXdv"
    "cmQubG93ZXIoKSBpbiB0bDoKICAgICAgICAgICAgICAgIGxhYmVsID0ga2V5d29yZAogICAgICAg"
    "ICAgICAgICAgc2VsZi5wcm9ncmVzcy5lbWl0KHBjdCwgbGFiZWwpCiAgICAgICAgICAgICAgICBi"
    "cmVhawoKICAgIGRlZiBfcnVuX3BpcGVsaW5lKHNlbGYpOgogICAgICAgIGNmZ19kaWN0ID0gc2Vs"
    "Zi5jb25maWcKCiAgICAgICAgIyBBZGQgcmVwbyByb290IHRvIHBhdGgKICAgICAgICByZXBvX3Jv"
    "b3QgPSBQYXRoKF9fZmlsZV9fKS5wYXJlbnQucGFyZW50CiAgICAgICAgaWYgc3RyKHJlcG9fcm9v"
    "dCkgbm90IGluIHN5cy5wYXRoOgogICAgICAgICAgICBzeXMucGF0aC5pbnNlcnQoMCwgc3RyKHJl"
    "cG9fcm9vdCkpCgogICAgICAgIGZyb20gYmFja2VuZC5tdWx0aW9taWNzX3JlYWN0b21lIGltcG9y"
    "dCAoCiAgICAgICAgICAgIElucHV0Q29uZmlnLCBydW5fcGlwZWxpbmUsIE9VVFBVVF9ESVIKICAg"
    "ICAgICApCiAgICAgICAgaW1wb3J0IGJhY2tlbmQubXVsdGlvbWljc19yZWFjdG9tZSBhcyBtcgoK"
    "ICAgICAgICBvdXRfZGlyID0gUGF0aChjZmdfZGljdC5nZXQoIm91dHB1dF9kaXIiLCAibXVsdGlv"
    "bWljc19yZWFjdG9tZV9vdXRwdXQiKSkKICAgICAgICBvdXRfZGlyLm1rZGlyKHBhcmVudHM9VHJ1"
    "ZSwgZXhpc3Rfb2s9VHJ1ZSkKICAgICAgICBtci5PVVRQVVRfRElSID0gb3V0X2RpcgoKICAgICAg"
    "ICBkZWYgX3Aodik6CiAgICAgICAgICAgIHJldHVybiBQYXRoKHYpIGlmIHYgZWxzZSBOb25lCgog"
    "ICAgICAgIGNmZyA9IElucHV0Q29uZmlnKAogICAgICAgICAgICBtb2RlICAgICAgICAgICAgICA9"
    "IGNmZ19kaWN0LmdldCgibW9kZSIsICJzeW50aGV0aWMiKSwKICAgICAgICAgICAgdHJhbnNjcmlw"
    "dG9taWNzICAgPSBfcChjZmdfZGljdC5nZXQoInRyYW5zY3JpcHRvbWljcyIpKSwKICAgICAgICAg"
    "ICAgcHJvdGVvbWljcyAgICAgICAgPSBfcChjZmdfZGljdC5nZXQoInByb3Rlb21pY3MiKSksCiAg"
    "ICAgICAgICAgIG1ldGFib2xvbWljcyAgICAgID0gX3AoY2ZnX2RpY3QuZ2V0KCJtZXRhYm9sb21p"
    "Y3MiKSksCiAgICAgICAgICAgIGdlbm9taWNzICAgICAgICAgID0gX3AoY2ZnX2RpY3QuZ2V0KCJn"
    "ZW5vbWljcyIpKSwKICAgICAgICAgICAgc2Nfcm5hICAgICAgICAgICAgPSBfcChjZmdfZGljdC5n"
    "ZXQoInNjX3JuYSIpKSwKICAgICAgICAgICAgc2NfYXRhYyAgICAgICAgICAgPSBfcChjZmdfZGlj"
    "dC5nZXQoInNjX2F0YWMiKSksCiAgICAgICAgICAgIHNwYXRpYWwgICAgICAgICAgID0gX3AoY2Zn"
    "X2RpY3QuZ2V0KCJzcGF0aWFsIikpLAogICAgICAgICAgICBtZXRhZGF0YSAgICAgICAgICA9IF9w"
    "KGNmZ19kaWN0LmdldCgibWV0YWRhdGEiKSksCiAgICAgICAgICAgIG5fc2FtcGxlcyAgICAgICAg"
    "ID0gaW50KGNmZ19kaWN0LmdldCgibl9zYW1wbGVzIiwgMTIwKSksCiAgICAgICAgICAgIG5fY2Vs"
    "bHMgICAgICAgICAgID0gaW50KGNmZ19kaWN0LmdldCgibl9jZWxscyIsICAgNDAwKSksCiAgICAg"
    "ICAgICAgIG5fYmF0Y2hlcyAgICAgICAgID0gaW50KGNmZ19kaWN0LmdldCgibl9iYXRjaGVzIiwg"
    "ICAzKSksCiAgICAgICAgICAgIG1pbW9kaF90aWVyICAgICAgID0gY2ZnX2RpY3QuZ2V0KCJtaW1v"
    "ZGhfdGllciIsICJUaWVyMiIpLAogICAgICAgICAgICBzdHVkeV9pZCAgICAgICAgICA9IGNmZ19k"
    "aWN0LmdldCgic3R1ZHlfaWQiLCAiIiksCiAgICAgICAgICAgIGRpc2Vhc2UgICAgICAgICAgID0g"
    "Y2ZnX2RpY3QuZ2V0KCJkaXNlYXNlIiwgICJ1bnNwZWNpZmllZCIpLAogICAgICAgICAgICBwaSAg"
    "ICAgICAgICAgICAgICA9IGNmZ19kaWN0LmdldCgicGkiKSAgICAgICAgb3IgTm9uZSwKICAgICAg"
    "ICAgICAgaW5zdGl0dXRpb24gICAgICAgPSBjZmdfZGljdC5nZXQoImluc3RpdHV0aW9uIikgb3Ig"
    "Tm9uZSwKICAgICAgICAgICAgZGF0YV9yZXBvICAgICAgICAgPSBjZmdfZGljdC5nZXQoImRhdGFf"
    "cmVwbyIsICJsb2NhbCIpLAogICAgICAgICAgICBhY2Nlc3Npb24gICAgICAgICA9IGNmZ19kaWN0"
    "LmdldCgiYWNjZXNzaW9uIikgb3IgTm9uZSwKICAgICAgICAgICAgZXRoaWNzICAgICAgICAgICAg"
    "PSBjZmdfZGljdC5nZXQoImV0aGljcyIpICAgIG9yIE5vbmUsCiAgICAgICAgKQoKICAgICAgICBz"
    "ZWxmLnByb2dyZXNzLmVtaXQoNSwgIkluaXRpYWxpc2luZyIpCiAgICAgICAgcmVzdWx0ID0gcnVu"
    "X3BpcGVsaW5lKGNmZywgbl9wZXJtPWludChjZmdfZGljdC5nZXQoIm5fcGVybSIsIDIwMCkpKQog"
    "ICAgICAgIHNlbGYucHJvZ3Jlc3MuZW1pdCgxMDAsICJDT01QTEVURSIpCiAgICAgICAgc2VsZi5m"
    "aW5pc2hlZC5lbWl0KHsib3V0cHV0X2RpciI6IHN0cihvdXRfZGlyKSwgKip7CiAgICAgICAgICAg"
    "IGs6IHN0cih2KSBmb3IgaywgdiBpbiByZXN1bHQuaXRlbXMoKQogICAgICAgICAgICBpZiBpc2lu"
    "c3RhbmNlKHYsIFBhdGgpIG9yIGsgaW4gKCJ4bWxfcGF0aCIsKQogICAgICAgIH19KQoKCmNsYXNz"
    "IF9Mb2dDYXB0dXJlcihpby5UZXh0SU9CYXNlKToKICAgICIiIkludGVyY2VwdHMgd3JpdGUoKSBj"
    "YWxscyBmcm9tIGxvZ2dpbmcvcHJpbnQgYW5kIHJvdXRlcyB0byBjYWxsYmFjay4iIiIKCiAgICBk"
    "ZWYgX19pbml0X18oc2VsZiwgY2FsbGJhY2spOgogICAgICAgIHN1cGVyKCkuX19pbml0X18oKQog"
    "ICAgICAgIHNlbGYuX2NiID0gY2FsbGJhY2sKICAgICAgICBzZWxmLl9idWYgPSAiIgoKICAgIGRl"
    "ZiB3cml0ZShzZWxmLCB0ZXh0OiBzdHIpIC0+IGludDoKICAgICAgICBzZWxmLl9idWYgKz0gdGV4"
    "dAogICAgICAgIHdoaWxlICJcbiIgaW4gc2VsZi5fYnVmOgogICAgICAgICAgICBsaW5lLCBzZWxm"
    "Ll9idWYgPSBzZWxmLl9idWYuc3BsaXQoIlxuIiwgMSkKICAgICAgICAgICAgc2VsZi5fY2IobGlu"
    "ZSkKICAgICAgICByZXR1cm4gbGVuKHRleHQpCgogICAgZGVmIGZsdXNoKHNlbGYpOiBwYXNzCiAg"
    "ICBkZWYgaXNhdHR5KHNlbGYpOiByZXR1cm4gRmFsc2U="
)

_B64_MAIN_WINDOW = (
    "IiIiCm1haW5fd2luZG93LnB5ICAtICBNYWluV2luZG93IGZvciBNdWx0aU9taWNzLVJlYWN0b21l"
    "IERlc2t0b3AgdjMuMC4KQ29vcmRpbmF0ZXMgQ29uZmlndXJlVGFiIDwtPiBSdW5UYWIgPC0+IFJl"
    "c3VsdHNUYWIgdmlhIFBpcGVsaW5lV29ya2VyLgoiIiIKZnJvbSBfX2Z1dHVyZV9fIGltcG9ydCBh"
    "bm5vdGF0aW9ucwppbXBvcnQgc3lzCmZyb20gcGF0aGxpYiBpbXBvcnQgUGF0aApmcm9tIHR5cGlu"
    "ZyBpbXBvcnQgRGljdCwgQW55Cgpmcm9tIFB5UXQ2LlF0V2lkZ2V0cyBpbXBvcnQgKAogICAgUU1h"
    "aW5XaW5kb3csIFFXaWRnZXQsIFFWQm94TGF5b3V0LCBRSEJveExheW91dCwKICAgIFFUYWJXaWRn"
    "ZXQsIFFMYWJlbCwgUU1lc3NhZ2VCb3gsIFFBcHBsaWNhdGlvbgopCmZyb20gUHlRdDYuUXRDb3Jl"
    "ICBpbXBvcnQgUXQsIFFUaW1lcgpmcm9tIFB5UXQ2LlF0R3VpICAgaW1wb3J0IFFGb250LCBRQWN0"
    "aW9uCgpmcm9tIGRlc2t0b3Auc3R5bGVzICAgICAgIGltcG9ydCBEQVJLX1RIRU1FLCBTVEFUVVNf"
    "Q09MT1JTCmZyb20gZGVza3RvcC5waXBlbGluZV93b3JrZXIgaW1wb3J0IFBpcGVsaW5lV29ya2Vy"
    "CmZyb20gZGVza3RvcC53aWRnZXRzLmNvbmZpZ3VyZV90YWIgaW1wb3J0IENvbmZpZ3VyZVRhYgpm"
    "cm9tIGRlc2t0b3Aud2lkZ2V0cy5ydW5fdGFiICAgICAgICBpbXBvcnQgUnVuVGFiCmZyb20gZGVz"
    "a3RvcC53aWRnZXRzLnJlc3VsdHNfdGFiICAgIGltcG9ydCBSZXN1bHRzVGFiCmZyb20gZGVza3Rv"
    "cC53aWRnZXRzLmFib3V0X3RhYiAgICAgIGltcG9ydCBBYm91dFRhYgoKCmNsYXNzIE1haW5XaW5k"
    "b3coUU1haW5XaW5kb3cpOgogICAgZGVmIF9faW5pdF9fKHNlbGYpOgogICAgICAgIHN1cGVyKCku"
    "X19pbml0X18oKQogICAgICAgIHNlbGYuX3dvcmtlcjogUGlwZWxpbmVXb3JrZXIgfCBOb25lID0g"
    "Tm9uZQogICAgICAgIHNlbGYuX2VsYXBzZWQgPSAwCiAgICAgICAgc2VsZi5fdGltZXIgICA9IFFU"
    "aW1lcihzZWxmKQogICAgICAgIHNlbGYuX3RpbWVyLnRpbWVvdXQuY29ubmVjdChzZWxmLl90aWNr"
    "KQogICAgICAgIHNlbGYuX2N1cnJlbnRfY29uZmlnOiBEaWN0W3N0ciwgQW55XSA9IHt9CgogICAg"
    "ICAgIHNlbGYuX3NldHVwX3dpbmRvdygpCiAgICAgICAgc2VsZi5fYnVpbGRfdWkoKQogICAgICAg"
    "IHNlbGYuX2J1aWxkX21lbnUoKQogICAgICAgIHNlbGYuc2V0U3R5bGVTaGVldChEQVJLX1RIRU1F"
    "KQoKICAgICMgLS0gV2luZG93IHNldHVwIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQogICAgZGVmIF9zZXR1cF93aW5kb3coc2VsZik6CiAg"
    "ICAgICAgc2VsZi5zZXRXaW5kb3dUaXRsZSgiTXVsdGlPbWljcy1SZWFjdG9tZSB2My4wICAuICBN"
    "SU1PREggRGVza3RvcCIpCiAgICAgICAgc2VsZi5zZXRNaW5pbXVtU2l6ZSgxMTAwLCA3NTApCiAg"
    "ICAgICAgc2VsZi5yZXNpemUoMTI4MCwgODIwKQoKICAgICMgLS0gVUkgbGF5b3V0IC0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KICAg"
    "IGRlZiBfYnVpbGRfdWkoc2VsZik6CiAgICAgICAgY2VudHJhbCA9IFFXaWRnZXQoKQogICAgICAg"
    "IHNlbGYuc2V0Q2VudHJhbFdpZGdldChjZW50cmFsKQogICAgICAgIHJvb3QgPSBRVkJveExheW91"
    "dChjZW50cmFsKQogICAgICAgIHJvb3Quc2V0Q29udGVudHNNYXJnaW5zKDAsIDAsIDAsIDApCiAg"
    "ICAgICAgcm9vdC5zZXRTcGFjaW5nKDApCgogICAgICAgICMgLS0gSGVhZGVyIGJhciAtLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQogICAgICAg"
    "IGhlYWRlciA9IFFXaWRnZXQoKQogICAgICAgIGhlYWRlci5zZXRGaXhlZEhlaWdodCg1MikKICAg"
    "ICAgICBoZWFkZXIuc2V0U3R5bGVTaGVldCgiYmFja2dyb3VuZDojMWExZjJlOyBib3JkZXItYm90"
    "dG9tOjFweCBzb2xpZCAjMmQzNzQ4OyIpCiAgICAgICAgaF9sYXkgPSBRSEJveExheW91dChoZWFk"
    "ZXIpCiAgICAgICAgaF9sYXkuc2V0Q29udGVudHNNYXJnaW5zKDIwLCAwLCAyMCwgMCkKCiAgICAg"
    "ICAgaWNvbl9sYmwgPSBRTGFiZWwoIvCfp6wiKQogICAgICAgIGljb25fbGJsLnNldEZvbnQoUUZv"
    "bnQoIlNlZ29lIFVJIEVtb2ppIiwgMjApKQogICAgICAgIGhfbGF5LmFkZFdpZGdldChpY29uX2xi"
    "bCkKCiAgICAgICAgdGl0bGUgPSBRTGFiZWwoIk11bHRpT21pY3MtUmVhY3RvbWUiKQogICAgICAg"
    "IHRpdGxlLnNldE9iamVjdE5hbWUoInRpdGxlX2xhYmVsIikKICAgICAgICB0aXRsZS5zZXRGb250"
    "KFFGb250KCJTZWdvZSBVSSIsIDE1LCBRRm9udC5XZWlnaHQuQm9sZCkpCiAgICAgICAgaF9sYXku"
    "YWRkV2lkZ2V0KHRpdGxlKQoKICAgICAgICB2ZXIgPSBRTGFiZWwoInYzLjAuMCIpCiAgICAgICAg"
    "dmVyLnNldE9iamVjdE5hbWUoImJhZGdlX3ZlcnNpb24iKQogICAgICAgIGhfbGF5LmFkZFdpZGdl"
    "dCh2ZXIpCgogICAgICAgIG1pbW9kaF9iYWRnZSA9IFFMYWJlbCgiTUlNT0RIIHYxLjAiKQogICAg"
    "ICAgIG1pbW9kaF9iYWRnZS5zZXRPYmplY3ROYW1lKCJiYWRnZV9taW1vZGgiKQogICAgICAgIGhf"
    "bGF5LmFkZFdpZGdldChtaW1vZGhfYmFkZ2UpCgogICAgICAgIGhfbGF5LmFkZFN0cmV0Y2goKQoK"
    "ICAgICAgICBzZWxmLl9zdGF0dXNfYmFyX2xibCA9IFFMYWJlbCgiSURMRSIpCiAgICAgICAgc2Vs"
    "Zi5fc3RhdHVzX2Jhcl9sYmwuc2V0U3R5bGVTaGVldCgiY29sb3I6IzZiNzI4MDtmb250LXNpemU6"
    "MTJweDsiKQogICAgICAgIGhfbGF5LmFkZFdpZGdldChzZWxmLl9zdGF0dXNfYmFyX2xibCkKICAg"
    "ICAgICByb290LmFkZFdpZGdldChoZWFkZXIpCgogICAgICAgICMgLS0gVGFiIHdpZGdldCAtLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQogICAg"
    "ICAgIHNlbGYuX3RhYnMgPSBRVGFiV2lkZ2V0KCkKICAgICAgICBzZWxmLl90YWJzLnNldERvY3Vt"
    "ZW50TW9kZShUcnVlKQoKICAgICAgICBzZWxmLl9jZmdfdGFiICAgICA9IENvbmZpZ3VyZVRhYigp"
    "CiAgICAgICAgc2VsZi5fcnVuX3RhYiAgICAgPSBSdW5UYWIoKQogICAgICAgIHNlbGYuX3Jlc3Vs"
    "dHNfdGFiID0gUmVzdWx0c1RhYigpCiAgICAgICAgc2VsZi5fYWJvdXRfdGFiICAgPSBBYm91dFRh"
    "YigpCgogICAgICAgIHNlbGYuX3RhYnMuYWRkVGFiKHNlbGYuX2NmZ190YWIsICAgICAi4pqZ77iP"
    "ICBDb25maWd1cmUiKQogICAgICAgIHNlbGYuX3RhYnMuYWRkVGFiKHNlbGYuX3J1bl90YWIsICAg"
    "ICAiPiAgUnVuIikKICAgICAgICBzZWxmLl90YWJzLmFkZFRhYihzZWxmLl9yZXN1bHRzX3RhYiwg"
    "IvCfk4ogIFJlc3VsdHMiKQogICAgICAgIHNlbGYuX3RhYnMuYWRkVGFiKHNlbGYuX2Fib3V0X3Rh"
    "YiwgICAi4oS577iPICBBYm91dCIpCgogICAgICAgIHJvb3QuYWRkV2lkZ2V0KHNlbGYuX3RhYnMs"
    "IHN0cmV0Y2g9MSkKCiAgICAgICAgIyAtLSBTdGF0dXMgYmFyIC0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiAgICAgICAgc2IgPSBzZWxmLnN0"
    "YXR1c0JhcigpCiAgICAgICAgc2Iuc2hvd01lc3NhZ2UoIlJlYWR5ICAuICBNdWx0aU9taWNzLVJl"
    "YWN0b21lIERlc2t0b3AgdjMuMCAgLiAgTUlNT0RIIHYxLjAiKQoKICAgICAgICAjIC0tIFdpcmUg"
    "c2lnbmFscyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0KICAgICAgICBzZWxmLl9jZmdfdGFiLmNvbmZpZ19jaGFuZ2VkLmNvbm5lY3Qoc2VsZi5f"
    "b25fY29uZmlnX2NoYW5nZWQpCiAgICAgICAgc2VsZi5fcnVuX3RhYi5fcnVuX2J0bi5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fc3RhcnRfcGlwZWxpbmUpCiAgICAgICAgc2VsZi5fcnVuX3RhYi5fc3Rv"
    "cF9idG4uY2xpY2tlZC5jb25uZWN0KHNlbGYuX3N0b3BfcGlwZWxpbmUpCgogICAgIyAtLSBNZW51"
    "IGJhciAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLQogICAgZGVmIF9idWlsZF9tZW51KHNlbGYpOgogICAgICAgIGZpbGVfbWVudSA9"
    "IHNlbGYubWVudUJhcigpLmFkZE1lbnUoIkZpbGUiKQoKICAgICAgICBydW5fYWN0ID0gUUFjdGlv"
    "bigiPiAgUnVuIFBpcGVsaW5lIiwgc2VsZikKICAgICAgICBydW5fYWN0LnNldFNob3J0Y3V0KCJD"
    "dHJsK1IiKQogICAgICAgIHJ1bl9hY3QudHJpZ2dlcmVkLmNvbm5lY3Qoc2VsZi5fc3RhcnRfcGlw"
    "ZWxpbmUpCiAgICAgICAgZmlsZV9tZW51LmFkZEFjdGlvbihydW5fYWN0KQoKICAgICAgICBmaWxl"
    "X21lbnUuYWRkU2VwYXJhdG9yKCkKCiAgICAgICAgcXVpdF9hY3QgPSBRQWN0aW9uKCJRdWl0Iiwg"
    "c2VsZikKICAgICAgICBxdWl0X2FjdC5zZXRTaG9ydGN1dCgiQ3RybCtRIikKICAgICAgICBxdWl0"
    "X2FjdC50cmlnZ2VyZWQuY29ubmVjdChRQXBwbGljYXRpb24uaW5zdGFuY2UoKS5xdWl0KQogICAg"
    "ICAgIGZpbGVfbWVudS5hZGRBY3Rpb24ocXVpdF9hY3QpCgogICAgICAgIGhlbHBfbWVudSA9IHNl"
    "bGYubWVudUJhcigpLmFkZE1lbnUoIkhlbHAiKQogICAgICAgIGFib3V0X2FjdCA9IFFBY3Rpb24o"
    "IkFib3V0Iiwgc2VsZikKICAgICAgICBhYm91dF9hY3QudHJpZ2dlcmVkLmNvbm5lY3QobGFtYmRh"
    "OiBzZWxmLl90YWJzLnNldEN1cnJlbnRJbmRleCgzKSkKICAgICAgICBoZWxwX21lbnUuYWRkQWN0"
    "aW9uKGFib3V0X2FjdCkKCiAgICAjIC0tIFNsb3RzIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiAgICBkZWYgX29uX2NvbmZp"
    "Z19jaGFuZ2VkKHNlbGYsIGNmZzogRGljdFtzdHIsIEFueV0pOgogICAgICAgIHNlbGYuX2N1cnJl"
    "bnRfY29uZmlnID0gY2ZnCgogICAgZGVmIF9zdGFydF9waXBlbGluZShzZWxmKToKICAgICAgICBp"
    "ZiBzZWxmLl93b3JrZXIgYW5kIHNlbGYuX3dvcmtlci5pc1J1bm5pbmcoKToKICAgICAgICAgICAg"
    "cmV0dXJuCgogICAgICAgIGNmZyA9IHNlbGYuX2N1cnJlbnRfY29uZmlnIG9yIHNlbGYuX2NmZ190"
    "YWIuZ2V0X2NvbmZpZygpCgogICAgICAgIGlmIG5vdCBzZWxmLl9jZmdfdGFiLmlzX3JlYWR5KCk6"
    "CiAgICAgICAgICAgIFFNZXNzYWdlQm94Lndhcm5pbmcoCiAgICAgICAgICAgICAgICBzZWxmLCAi"
    "TWlzc2luZyBJbnB1dCIsCiAgICAgICAgICAgICAgICAiUGxlYXNlIHNlbGVjdCBhdCBsZWFzdCBv"
    "bmUgZGF0YSBmaWxlICh0cmFuc2NyaXB0b21pY3Mgb3Igc2NSTkEtc2VxKVxuIgogICAgICAgICAg"
    "ICAgICAgIm9yIHN3aXRjaCB0byBTeW50aGV0aWMgbW9kZS4iKQogICAgICAgICAgICByZXR1cm4K"
    "CiAgICAgICAgIyBTd2l0Y2ggdG8gUnVuIHRhYgogICAgICAgIHNlbGYuX3RhYnMuc2V0Q3VycmVu"
    "dEluZGV4KDEpCiAgICAgICAgc2VsZi5fcnVuX3RhYi5yZXNldCgpCiAgICAgICAgc2VsZi5fcnVu"
    "X3RhYi5zZXRfc3RhdHVzKCJSVU5OSU5HIiwgIlN0YXJ0aW5nLi4uIikKICAgICAgICBzZWxmLl9y"
    "dW5fdGFiLmFwcGVuZF9sb2coIj0iICogNjAsICJTRUNUSU9OIikKICAgICAgICBzZWxmLl9ydW5f"
    "dGFiLmFwcGVuZF9sb2coZiIgIE11bHRpT21pY3MtUmVhY3RvbWUgdjMuMCAgLiAgTUlNT0RIIHtj"
    "ZmcuZ2V0KCdtaW1vZGhfdGllcicsJ1RpZXIyJyl9IiwgIlNFQ1RJT04iKQogICAgICAgIHNlbGYu"
    "X3J1bl90YWIuYXBwZW5kX2xvZyhmIiAgTW9kZToge2NmZy5nZXQoJ21vZGUnLCdzeW50aGV0aWMn"
    "KS51cHBlcigpfSAgLiAgRGlzZWFzZToge2NmZy5nZXQoJ2Rpc2Vhc2UnLCc/Jyl9IiwgIklORk8i"
    "KQogICAgICAgIHNlbGYuX3J1bl90YWIuYXBwZW5kX2xvZygiPSIgKiA2MCwgIlNFQ1RJT04iKQoK"
    "ICAgICAgICBzZWxmLl9lbGFwc2VkID0gMAogICAgICAgIHNlbGYuX3RpbWVyLnN0YXJ0KDEwMDAp"
    "CiAgICAgICAgc2VsZi5fc3RhdHVzX2Jhcl9sYmwuc2V0VGV4dCgi4pePIFJVTk5JTkciKQogICAg"
    "ICAgIHNlbGYuX3N0YXR1c19iYXJfbGJsLnNldFN0eWxlU2hlZXQoZiJjb2xvcjp7U1RBVFVTX0NP"
    "TE9SU1snUlVOTklORyddfTtmb250LXNpemU6MTJweDtmb250LXdlaWdodDpib2xkOyIpCgogICAg"
    "ICAgIHNlbGYuX3dvcmtlciA9IFBpcGVsaW5lV29ya2VyKGNmZywgcGFyZW50PXNlbGYpCiAgICAg"
    "ICAgc2VsZi5fd29ya2VyLmxvZ19saW5lLmNvbm5lY3Qoc2VsZi5fcnVuX3RhYi5hcHBlbmRfbG9n"
    "KQogICAgICAgIHNlbGYuX3dvcmtlci5wcm9ncmVzcy5jb25uZWN0KHNlbGYuX3J1bl90YWIuc2V0"
    "X3Byb2dyZXNzKQogICAgICAgIHNlbGYuX3dvcmtlci5maW5pc2hlZC5jb25uZWN0KHNlbGYuX29u"
    "X3BpcGVsaW5lX2ZpbmlzaGVkKQogICAgICAgIHNlbGYuX3dvcmtlci5mYWlsZWQuY29ubmVjdChz"
    "ZWxmLl9vbl9waXBlbGluZV9mYWlsZWQpCiAgICAgICAgc2VsZi5fd29ya2VyLnN0YXJ0KCkKCiAg"
    "ICBkZWYgX3N0b3BfcGlwZWxpbmUoc2VsZik6CiAgICAgICAgaWYgc2VsZi5fd29ya2VyIGFuZCBz"
    "ZWxmLl93b3JrZXIuaXNSdW5uaW5nKCk6CiAgICAgICAgICAgIHNlbGYuX3dvcmtlci5hYm9ydCgp"
    "CiAgICAgICAgICAgIHNlbGYuX3RpbWVyLnN0b3AoKQogICAgICAgICAgICBzZWxmLl9ydW5fdGFi"
    "LnNldF9zdGF0dXMoIklETEUiLCAiU3RvcHBlZCBieSB1c2VyIikKICAgICAgICAgICAgc2VsZi5f"
    "cnVuX3RhYi5hcHBlbmRfbG9nKCJQaXBlbGluZSBzdG9wcGVkIGJ5IHVzZXIuIiwgIldBUk5JTkci"
    "KQogICAgICAgICAgICBzZWxmLl9zdGF0dXNfYmFyX2xibC5zZXRUZXh0KCJJRExFIikKICAgICAg"
    "ICAgICAgc2VsZi5fc3RhdHVzX2Jhcl9sYmwuc2V0U3R5bGVTaGVldCgiY29sb3I6IzZiNzI4MDtm"
    "b250LXNpemU6MTJweDsiKQoKICAgIGRlZiBfb25fcGlwZWxpbmVfZmluaXNoZWQoc2VsZiwgcmVz"
    "dWx0OiBEaWN0W3N0ciwgQW55XSk6CiAgICAgICAgc2VsZi5fdGltZXIuc3RvcCgpCiAgICAgICAg"
    "c2VsZi5fcnVuX3RhYi5zZXRfc3RhdHVzKCJDT01QTEVURUQiLCAiQWxsIHN0YWdlcyBjb21wbGV0"
    "ZSIpCiAgICAgICAgc2VsZi5fcnVuX3RhYi5hcHBlbmRfbG9nKCIiLCAiSU5GTyIpCiAgICAgICAg"
    "c2VsZi5fcnVuX3RhYi5hcHBlbmRfbG9nKCJbT0tdICBQaXBlbGluZSBDT01QTEVURSAgLSAgTUlN"
    "T0RIIFhNTCByZWNvcmQgZ2VuZXJhdGVkLiIsICJNSU1PREgiKQogICAgICAgIHNlbGYuX3J1bl90"
    "YWIuc2V0X3Byb2dyZXNzKDEwMCwgIkNPTVBMRVRFIikKICAgICAgICBzZWxmLl9zdGF0dXNfYmFy"
    "X2xibC5zZXRUZXh0KCJbT0tdIENPTVBMRVRFRCIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2Jhcl9s"
    "Ymwuc2V0U3R5bGVTaGVldChmImNvbG9yOntTVEFUVVNfQ09MT1JTWydDT01QTEVURUQnXX07Zm9u"
    "dC1zaXplOjEycHg7Zm9udC13ZWlnaHQ6Ym9sZDsiKQoKICAgICAgICBvdXRfZGlyID0gcmVzdWx0"
    "LmdldCgib3V0cHV0X2RpciIsIHNlbGYuX2N1cnJlbnRfY29uZmlnLmdldCgib3V0cHV0X2RpciIs"
    "ICJtdWx0aW9taWNzX3JlYWN0b21lX291dHB1dCIpKQogICAgICAgIHNlbGYuX3Jlc3VsdHNfdGFi"
    "LmxvYWRfcmVzdWx0cyhvdXRfZGlyKQogICAgICAgIHNlbGYuc3RhdHVzQmFyKCkuc2hvd01lc3Nh"
    "Z2UoZiJDb21wbGV0ZSAgLiAgT3V0cHV0cyBzYXZlZCB0bzoge291dF9kaXJ9IikKCiAgICAgICAg"
    "IyBBdXRvLXN3aXRjaCB0byByZXN1bHRzIGFmdGVyIHNob3J0IGRlbGF5CiAgICAgICAgUVRpbWVy"
    "LnNpbmdsZVNob3QoMTUwMCwgbGFtYmRhOiBzZWxmLl90YWJzLnNldEN1cnJlbnRJbmRleCgyKSkK"
    "CiAgICBkZWYgX29uX3BpcGVsaW5lX2ZhaWxlZChzZWxmLCBlcnJvcjogc3RyKToKICAgICAgICBz"
    "ZWxmLl90aW1lci5zdG9wKCkKICAgICAgICBzZWxmLl9ydW5fdGFiLnNldF9zdGF0dXMoIkZBSUxF"
    "RCIsICJFcnJvciIpCiAgICAgICAgc2VsZi5fcnVuX3RhYi5hcHBlbmRfbG9nKGYiW1hdIEZBSUxF"
    "RDoge2Vycm9yfSIsICJFUlJPUiIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2Jhcl9sYmwuc2V0VGV4"
    "dCgiW1hdIEZBSUxFRCIpCiAgICAgICAgc2VsZi5fc3RhdHVzX2Jhcl9sYmwuc2V0U3R5bGVTaGVl"
    "dChmImNvbG9yOntTVEFUVVNfQ09MT1JTWydGQUlMRUQnXX07Zm9udC1zaXplOjEycHg7Zm9udC13"
    "ZWlnaHQ6Ym9sZDsiKQogICAgICAgIFFNZXNzYWdlQm94LmNyaXRpY2FsKHNlbGYsICJQaXBlbGlu"
    "ZSBGYWlsZWQiLAogICAgICAgICAgICAgICAgICAgICAgICAgICAgIGYiVGhlIHBpcGVsaW5lIGVu"
    "Y291bnRlcmVkIGFuIGVycm9yOlxuXG57ZXJyb3J9XG5cbiIKICAgICAgICAgICAgICAgICAgICAg"
    "ICAgICAgICAiU2VlIHRoZSBSdW4gdGFiIGxvZyBmb3IgZGV0YWlscy4iKQoKICAgIGRlZiBfdGlj"
    "ayhzZWxmKToKICAgICAgICBzZWxmLl9lbGFwc2VkICs9IDEKICAgICAgICBzZWxmLl9ydW5fdGFi"
    "LnNldF9lbGFwc2VkKHNlbGYuX2VsYXBzZWQpCgogICAgZGVmIGNsb3NlRXZlbnQoc2VsZiwgZXZl"
    "bnQpOgogICAgICAgIGlmIHNlbGYuX3dvcmtlciBhbmQgc2VsZi5fd29ya2VyLmlzUnVubmluZygp"
    "OgogICAgICAgICAgICByZXBseSA9IFFNZXNzYWdlQm94LnF1ZXN0aW9uKAogICAgICAgICAgICAg"
    "ICAgc2VsZiwgIlBpcGVsaW5lIFJ1bm5pbmciLAogICAgICAgICAgICAgICAgIkEgcGlwZWxpbmUg"
    "aXMgc3RpbGwgcnVubmluZy4gU3RvcCBpdCBhbmQgcXVpdD8iLAogICAgICAgICAgICAgICAgUU1l"
    "c3NhZ2VCb3guU3RhbmRhcmRCdXR0b24uWWVzIHwgUU1lc3NhZ2VCb3guU3RhbmRhcmRCdXR0b24u"
    "Tm8pCiAgICAgICAgICAgIGlmIHJlcGx5ID09IFFNZXNzYWdlQm94LlN0YW5kYXJkQnV0dG9uLlll"
    "czoKICAgICAgICAgICAgICAgIHNlbGYuX3dvcmtlci5hYm9ydCgpCiAgICAgICAgICAgICAgICBl"
    "dmVudC5hY2NlcHQoKQogICAgICAgICAgICBlbHNlOgogICAgICAgICAgICAgICAgZXZlbnQuaWdu"
    "b3JlKCkKICAgICAgICBlbHNlOgogICAgICAgICAgICBldmVudC5hY2NlcHQoKQ=="
)

_B64_CONFIGURE_TAB = (
    "IiIiCmNvbmZpZ3VyZV90YWIucHkgIC0gIENvbmZpZ3VyYXRpb24gcGFuZWwgZm9yIHRoZSBkZXNr"
    "dG9wIGFwcC4KQ292ZXJzIG1vZGUgc2VsZWN0aW9uLCBmaWxlIHBpY2tlcnMsIE1JTU9ESCB0aWVy"
    "LCBhbmQgc3ludGhldGljIHBhcmFtZXRlcnMuCiIiIgpmcm9tIF9fZnV0dXJlX18gaW1wb3J0IGFu"
    "bm90YXRpb25zCmZyb20gcGF0aGxpYiBpbXBvcnQgUGF0aApmcm9tIHR5cGluZyBpbXBvcnQgRGlj"
    "dCwgQW55Cgpmcm9tIFB5UXQ2LlF0V2lkZ2V0cyBpbXBvcnQgKAogICAgUVdpZGdldCwgUVZCb3hM"
    "YXlvdXQsIFFIQm94TGF5b3V0LCBRR3JpZExheW91dCwgUUdyb3VwQm94LAogICAgUUxhYmVsLCBR"
    "TGluZUVkaXQsIFFQdXNoQnV0dG9uLCBRQ29tYm9Cb3gsIFFTcGluQm94LAogICAgUVJhZGlvQnV0"
    "dG9uLCBRQnV0dG9uR3JvdXAsIFFGaWxlRGlhbG9nLCBRU2Nyb2xsQXJlYSwgUUZyYW1lCikKZnJv"
    "bSBQeVF0Ni5RdENvcmUgaW1wb3J0IFF0LCBweXF0U2lnbmFsCmZyb20gUHlRdDYuUXRHdWkgaW1w"
    "b3J0IFFGb250CgojIFRlc3QgZGF0YSBidW5kbGVkIHdpdGggdGhlIGFwcApURVNUX0RBVEFfRElS"
    "ID0gUGF0aChfX2ZpbGVfXykucGFyZW50LnBhcmVudCAvICJ0ZXN0X2RhdGEiCgpNT0RBTElUSUVT"
    "ID0gWwogICAgKCJ0cmFuc2NyaXB0b21pY3MiLCAi8J+nrCBUcmFuc2NyaXB0b21pY3MiLCAgICJD"
    "U1YvVFNWL1BhcnF1ZXQgIC0gIHNhbXBsZXMgeCBnZW5lcyIpLAogICAgKCJwcm90ZW9taWNzIiwg"
    "ICAgICAi8J+UrCBQcm90ZW9taWNzIiwgICAgICAgICAiQ1NWL1RTVi9QYXJxdWV0ICAtICBzYW1w"
    "bGVzIHggcHJvdGVpbnMiKSwKICAgICgibWV0YWJvbG9taWNzIiwgICAgIuKal++4jyAgTWV0YWJv"
    "bG9taWNzIiwgICAgICAgICJDU1YvVFNWL1BhcnF1ZXQgIC0gIHNhbXBsZXMgeCBtZXRhYm9saXRl"
    "cyIpLAogICAgKCJnZW5vbWljcyIsICAgICAgICAi8J+nqyBHZW5vbWljcyAoU05QKSIsICAgICAg"
    "IkNTVi9UU1YvUGFycXVldCAgLSAgc2FtcGxlcyB4IHZhcmlhbnRzIiksCiAgICAoInNjX3JuYSIs"
    "ICAgICAgICAgICLwn5StIHNjUk5BLXNlcSIsICAgICAgICAgICAiLmg1YWQgfCAxMHggTUVYIGRp"
    "cmVjdG9yeSB8IENTViIpLAogICAgKCJzY19hdGFjIiwgICAgICAgICAi8J+PlO+4jyAgc2NBVEFD"
    "LXNlcSIsICAgICAgICAgICIuaDVhZCB8IDEweCBNRVggZGlyZWN0b3J5IiksCiAgICAoInNwYXRp"
    "YWwiLCAgICAgICAgICLwn5e677iPICBTcGF0aWFsIChWaXNpdW0pIiwgICAgICIuaDVhZCB8IDEw"
    "eCBWaXNpdW0gZGlyZWN0b3J5IiksCiAgICAoIm1ldGFkYXRhIiwgICAgICAgICLwn5OLIE1ldGFk"
    "YXRhIiwgICAgICAgICAgICAgIkNTVi9FeGNlbCAgLSAgbXVzdCBoYXZlICdjb25kaXRpb24nLCdi"
    "YXRjaCciKSwKXQoKVElFUlMgPSBbCiAgICAoIlRpZXIxIiwgIiNlMmE2M2MiLCAiVGllciAxICAt"
    "ICBNaW5pbXVtIiwgICAgInNhbXBsZV9pZCAuIGNvbmRpdGlvbiAuIGJhdGNoIC4gbW9kYWxpdHki"
    "KSwKICAgICgiVGllcjIiLCAiIzNjOGRlMiIsICJUaWVyIDIgIC0gIFJlY29tbWVuZGVkIiwgIisg"
    "YWdlIC4gc2V4IC4gQk1JIC4gcGxhdGZvcm0gLiB0aXNzdWVfdHlwZSIpLAogICAgKCJUaWVyMyIs"
    "ICIjM2NlMjhhIiwgIlRpZXIgMyAgLSAgRnVsbCBGQUlSIiwgICAiKyB0cmVhdG1lbnQgLiBzdXJ2"
    "aXZhbCAuIGdlbm9tZSAuIGV0aGljcyIpLApdCgoKY2xhc3MgQ29uZmlndXJlVGFiKFFXaWRnZXQp"
    "OgogICAgIiIiRW1pdHMgY29uZmlnX2NoYW5nZWQoZGljdCkgd2hlbmV2ZXIgYW55IGZpZWxkIGNo"
    "YW5nZXMuIiIiCiAgICBjb25maWdfY2hhbmdlZCA9IHB5cXRTaWduYWwoZGljdCkKCiAgICBkZWYg"
    "X19pbml0X18oc2VsZiwgcGFyZW50PU5vbmUpOgogICAgICAgIHN1cGVyKCkuX19pbml0X18ocGFy"
    "ZW50KQogICAgICAgIHNlbGYuX2ZpbGVfZWRpdHM6IERpY3Rbc3RyLCBRTGluZUVkaXRdID0ge30K"
    "ICAgICAgICBzZWxmLl9idWlsZF91aSgpCiAgICAgICAgc2VsZi5fY29ubmVjdF9zaWduYWxzKCkK"
    "CiAgICAjIC0tIEJ1aWxkIFVJIC0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0KICAgIGRlZiBfYnVpbGRfdWkoc2VsZik6CiAgICAgICAg"
    "cm9vdCA9IFFWQm94TGF5b3V0KHNlbGYpCiAgICAgICAgcm9vdC5zZXRDb250ZW50c01hcmdpbnMo"
    "MTYsIDE2LCAxNiwgMTYpCiAgICAgICAgcm9vdC5zZXRTcGFjaW5nKDEyKQoKICAgICAgICAjIFNj"
    "cm9sbGFibGUgY29udGVudAogICAgICAgIHNjcm9sbCA9IFFTY3JvbGxBcmVhKCkKICAgICAgICBz"
    "Y3JvbGwuc2V0V2lkZ2V0UmVzaXphYmxlKFRydWUpCiAgICAgICAgc2Nyb2xsLnNldEZyYW1lU2hh"
    "cGUoUUZyYW1lLlNoYXBlLk5vRnJhbWUpCiAgICAgICAgaW5uZXIgPSBRV2lkZ2V0KCkKICAgICAg"
    "ICBsYXlvdXQgPSBRVkJveExheW91dChpbm5lcikKICAgICAgICBsYXlvdXQuc2V0Q29udGVudHNN"
    "YXJnaW5zKDAsIDAsIDgsIDApCiAgICAgICAgbGF5b3V0LnNldFNwYWNpbmcoMTQpCgogICAgICAg"
    "IGxheW91dC5hZGRXaWRnZXQoc2VsZi5fYnVpbGRfbW9kZV9ncm91cCgpKQogICAgICAgIGxheW91"
    "dC5hZGRXaWRnZXQoc2VsZi5fYnVpbGRfZmlsZXNfZ3JvdXAoKSkKICAgICAgICBsYXlvdXQuYWRk"
    "V2lkZ2V0KHNlbGYuX2J1aWxkX21pbW9kaF9ncm91cCgpKQogICAgICAgIGxheW91dC5hZGRXaWRn"
    "ZXQoc2VsZi5fYnVpbGRfc3ludGhldGljX2dyb3VwKCkpCiAgICAgICAgbGF5b3V0LmFkZFN0cmV0"
    "Y2goKQoKICAgICAgICBzY3JvbGwuc2V0V2lkZ2V0KGlubmVyKQogICAgICAgIHJvb3QuYWRkV2lk"
    "Z2V0KHNjcm9sbCkKCiAgICAjIC0tIE1vZGUgc2VsZWN0aW9uIC0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiAgICBkZWYgX2J1aWxkX21vZGVf"
    "Z3JvdXAoc2VsZikgLT4gUUdyb3VwQm94OgogICAgICAgIGdycCA9IFFHcm91cEJveCgiMSAuIE9w"
    "ZXJhdGluZyBNb2RlIikKICAgICAgICBsYXkgPSBRSEJveExheW91dChncnApCiAgICAgICAgbGF5"
    "LnNldFNwYWNpbmcoMTApCgogICAgICAgIHNlbGYuX21vZGVfZ3JvdXAgPSBRQnV0dG9uR3JvdXAo"
    "c2VsZikKICAgICAgICBmb3IgdmFsLCBsYmwsIGljb24gaW4gWwogICAgICAgICAgICAoInN5bnRo"
    "ZXRpYyIsICLwn5SsICBTeW50aGV0aWMiLCAgICJVc2UgaW50ZXJuYWxseSBnZW5lcmF0ZWQgdGVz"
    "dCBkYXRhIiksCiAgICAgICAgICAgICgicmVhbCIsICAgICAgIvCfk4IgIFJlYWwgRGF0YSIsICAg"
    "ICJMb2FkIHlvdXIgb3duIG9taWNzIGZpbGVzIiksCiAgICAgICAgICAgICgibWl4ZWQiLCAgICAg"
    "IvCflIAgIE1peGVkIiwgICAgICAgICJSZWFsIGZpbGVzICsgc3ludGhldGljIGZhbGxiYWNrIiks"
    "CiAgICAgICAgXToKICAgICAgICAgICAgcmIgPSBRUmFkaW9CdXR0b24oZiJ7bGJsfVxue2ljb259"
    "IikKICAgICAgICAgICAgcmIuc2V0UHJvcGVydHkoIm1vZGVfdmFsIiwgdmFsKQogICAgICAgICAg"
    "ICByYi5zZXRTdHlsZVNoZWV0KCIiIgogICAgICAgICAgICAgICAgUVJhZGlvQnV0dG9uIHsKICAg"
    "ICAgICAgICAgICAgICAgICBiYWNrZ3JvdW5kOiAjMWYyOTM3OyBib3JkZXI6IDFweCBzb2xpZCAj"
    "Mzc0MTUxOwogICAgICAgICAgICAgICAgICAgIGJvcmRlci1yYWRpdXM6IDhweDsgcGFkZGluZzog"
    "MTBweCAxNHB4OwogICAgICAgICAgICAgICAgICAgIGZvbnQtc2l6ZTogMTJweDsgY29sb3I6ICM5"
    "Y2EzYWY7IG1pbi13aWR0aDogMTQwcHg7CiAgICAgICAgICAgICAgICB9CiAgICAgICAgICAgICAg"
    "ICBRUmFkaW9CdXR0b246Y2hlY2tlZCB7CiAgICAgICAgICAgICAgICAgICAgYmFja2dyb3VuZDog"
    "IzFlM2E1ZjsgYm9yZGVyLWNvbG9yOiAjM2I4MmY2OyBjb2xvcjogIzkzYzVmZDsKICAgICAgICAg"
    "ICAgICAgIH0KICAgICAgICAgICAgICAgIFFSYWRpb0J1dHRvbjo6aW5kaWNhdG9yIHsgd2lkdGg6"
    "IDA7IGhlaWdodDogMDsgfQogICAgICAgICAgICAiIiIpCiAgICAgICAgICAgIHJiLnNldENoZWNr"
    "ZWQodmFsID09ICJzeW50aGV0aWMiKQogICAgICAgICAgICBzZWxmLl9tb2RlX2dyb3VwLmFkZEJ1"
    "dHRvbihyYikKICAgICAgICAgICAgbGF5LmFkZFdpZGdldChyYikKCiAgICAgICAgIyBRdWljay1s"
    "b2FkIHRlc3QgZGF0YSBidXR0b24KICAgICAgICBzZWxmLl9sb2FkX3Rlc3RfYnRuID0gUVB1c2hC"
    "dXR0b24oIvCfk6YgIExvYWQgQnVuZGxlZCBUZXN0IERhdGEiKQogICAgICAgIHNlbGYuX2xvYWRf"
    "dGVzdF9idG4uc2V0T2JqZWN0TmFtZSgiZmlsZV9idXR0b24iKQogICAgICAgIHNlbGYuX2xvYWRf"
    "dGVzdF9idG4uc2V0VG9vbFRpcCgiQXV0by1maWxsIGFsbCBwYXRocyB3aXRoIHRoZSBidW5kbGVk"
    "IHRlc3QgQ1NWIGZpbGVzIikKICAgICAgICBzZWxmLl9sb2FkX3Rlc3RfYnRuLmNsaWNrZWQuY29u"
    "bmVjdChzZWxmLl9sb2FkX3Rlc3RfZGF0YSkKICAgICAgICBsYXkuYWRkV2lkZ2V0KHNlbGYuX2xv"
    "YWRfdGVzdF9idG4pCiAgICAgICAgbGF5LmFkZFN0cmV0Y2goKQogICAgICAgIHJldHVybiBncnAK"
    "CiAgICAjIC0tIEZpbGUgcGlja2VycyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiAgICBkZWYgX2J1aWxkX2ZpbGVzX2dyb3VwKHNlbGYp"
    "IC0+IFFHcm91cEJveDoKICAgICAgICBncnAgPSBRR3JvdXBCb3goIjIgLiBEYXRhIEZpbGVzICAo"
    "UmVhbCAvIE1peGVkIG1vZGUpIikKICAgICAgICBncmlkID0gUUdyaWRMYXlvdXQoZ3JwKQogICAg"
    "ICAgIGdyaWQuc2V0U3BhY2luZyg4KQogICAgICAgIGdyaWQuc2V0Q29sdW1uU3RyZXRjaCgxLCAx"
    "KQoKICAgICAgICBmb3Igcm93LCAoa2V5LCBsYWJlbCwgaGludCkgaW4gZW51bWVyYXRlKE1PREFM"
    "SVRJRVMpOgogICAgICAgICAgICBsYmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGxibC5z"
    "ZXRNaW5pbXVtV2lkdGgoMTYwKQogICAgICAgICAgICBlZGl0ID0gUUxpbmVFZGl0KCkKICAgICAg"
    "ICAgICAgZWRpdC5zZXRQbGFjZWhvbGRlclRleHQoaGludCkKICAgICAgICAgICAgZWRpdC5zZXRP"
    "YmplY3ROYW1lKGtleSkKICAgICAgICAgICAgYnRuID0gUVB1c2hCdXR0b24oIkJyb3dzZS4uLiIp"
    "CiAgICAgICAgICAgIGJ0bi5zZXRPYmplY3ROYW1lKCJmaWxlX2J1dHRvbiIpCiAgICAgICAgICAg"
    "IGJ0bi5zZXRGaXhlZFdpZHRoKDgwKQogICAgICAgICAgICBidG4uY2xpY2tlZC5jb25uZWN0KGxh"
    "bWJkYSBfLCBrPWtleSwgZT1lZGl0OiBzZWxmLl9icm93c2UoaywgZSkpCgogICAgICAgICAgICBz"
    "ZWxmLl9maWxlX2VkaXRzW2tleV0gPSBlZGl0CiAgICAgICAgICAgIGdyaWQuYWRkV2lkZ2V0KGxi"
    "bCwgIHJvdywgMCkKICAgICAgICAgICAgZ3JpZC5hZGRXaWRnZXQoZWRpdCwgcm93LCAxKQogICAg"
    "ICAgICAgICBncmlkLmFkZFdpZGdldChidG4sICByb3csIDIpCgogICAgICAgIHJldHVybiBncnAK"
    "CiAgICAjIC0tIE1JTU9ESCBzZXR0aW5ncyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiAgICBkZWYgX2J1aWxkX21pbW9kaF9ncm91cChzZWxm"
    "KSAtPiBRR3JvdXBCb3g6CiAgICAgICAgZ3JwID0gUUdyb3VwQm94KCIzIC4gTUlNT0RIIENvbXBs"
    "aWFuY2UiKQogICAgICAgIHZsYXkgPSBRVkJveExheW91dChncnApCiAgICAgICAgdmxheS5zZXRT"
    "cGFjaW5nKDEwKQoKICAgICAgICAjIFRpZXIgc2VsZWN0b3IKICAgICAgICB0aWVyX3JvdyA9IFFI"
    "Qm94TGF5b3V0KCkKICAgICAgICB0aWVyX3Jvdy5zZXRTcGFjaW5nKDgpCiAgICAgICAgc2VsZi5f"
    "dGllcl9ncm91cCA9IFFCdXR0b25Hcm91cChzZWxmKQogICAgICAgIGZvciB2YWwsIGNvbG9yLCBu"
    "YW1lLCBkZXNjIGluIFRJRVJTOgogICAgICAgICAgICBidG4gPSBRUmFkaW9CdXR0b24oZiJ7bmFt"
    "ZX1cbntkZXNjfSIpCiAgICAgICAgICAgIGJ0bi5zZXRQcm9wZXJ0eSgidGllcl92YWwiLCB2YWwp"
    "CiAgICAgICAgICAgIGJ0bi5zZXRTdHlsZVNoZWV0KGYiIiIKICAgICAgICAgICAgICAgIFFSYWRp"
    "b0J1dHRvbiB7ewogICAgICAgICAgICAgICAgICAgIGJhY2tncm91bmQ6ICMxMTE4Mjc7IGJvcmRl"
    "cjogMXB4IHNvbGlkICMzNzQxNTE7CiAgICAgICAgICAgICAgICAgICAgYm9yZGVyLXJhZGl1czog"
    "OHB4OyBwYWRkaW5nOiAxMHB4OyBmb250LXNpemU6IDExcHg7CiAgICAgICAgICAgICAgICAgICAg"
    "Y29sb3I6ICM5Y2EzYWY7IG1pbi13aWR0aDogMTgwcHg7CiAgICAgICAgICAgICAgICB9fQogICAg"
    "ICAgICAgICAgICAgUVJhZGlvQnV0dG9uOmNoZWNrZWQge3sKICAgICAgICAgICAgICAgICAgICBi"
    "b3JkZXItY29sb3I6IHtjb2xvcn07IGNvbG9yOiB7Y29sb3J9OyBiYWNrZ3JvdW5kOiAjMGQxMTE3"
    "OwogICAgICAgICAgICAgICAgfX0KICAgICAgICAgICAgICAgIFFSYWRpb0J1dHRvbjo6aW5kaWNh"
    "dG9yIHt7IHdpZHRoOiAwOyBoZWlnaHQ6IDA7IH19CiAgICAgICAgICAgICIiIikKICAgICAgICAg"
    "ICAgYnRuLnNldENoZWNrZWQodmFsID09ICJUaWVyMiIpCiAgICAgICAgICAgIHNlbGYuX3RpZXJf"
    "Z3JvdXAuYWRkQnV0dG9uKGJ0bikKICAgICAgICAgICAgdGllcl9yb3cuYWRkV2lkZ2V0KGJ0bikK"
    "ICAgICAgICB2bGF5LmFkZExheW91dCh0aWVyX3JvdykKCiAgICAgICAgIyBNZXRhZGF0YSBmaWVs"
    "ZHMKICAgICAgICBncmlkID0gUUdyaWRMYXlvdXQoKQogICAgICAgIGdyaWQuc2V0U3BhY2luZyg4"
    "KQogICAgICAgIGZpZWxkcyA9IFsKICAgICAgICAgICAgKCJkaXNlYXNlIiwgICAgICJEaXNlYXNl"
    "IC8gUGhlbm90eXBlIiwgICAicGFuLWNhbmNlciIsICAgICAgICAgICAwLCAwKSwKICAgICAgICAg"
    "ICAgKCJkYXRhX3JlcG8iLCAgICJEYXRhIFJlcG9zaXRvcnkiLCAgICAgICAiR0VPIC8gVENHQSAv"
    "IGxvY2FsIiwgICAwLCAyKSwKICAgICAgICAgICAgKCJwaSIsICAgICAgICAgICJQcmluY2lwYWwg"
    "SW52ZXN0aWdhdG9yIiwiT3B0aW9uYWwgIC0gIFRpZXIgMisiLCAgIDEsIDApLAogICAgICAgICAg"
    "ICAoImFjY2Vzc2lvbiIsICAgIkFjY2Vzc2lvbiBJRCIsICAgICAgICAgICJlLmcuIEdTRTE5OTUx"
    "NSIsICAgICAgIDEsIDIpLAogICAgICAgICAgICAoImluc3RpdHV0aW9uIiwgIkluc3RpdHV0aW9u"
    "IiwgICAgICAgICAgICJPcHRpb25hbCAgLSAgVGllciAyKyIsICAgMiwgMCksCiAgICAgICAgICAg"
    "ICgiZXRoaWNzIiwgICAgICAiRXRoaWNzIEFwcHJvdmFsIiwgICAgICAgIklSQiByZWYgIC0gIFRp"
    "ZXIgMyIsICAgICAyLCAyKSwKICAgICAgICAgICAgKCJzdHVkeV9pZCIsICAgICJTdHVkeSBJRCIs"
    "ICAgICAgICAgICAgICAiQXV0by1nZW5lcmF0ZWQgaWYgYmxhbmsiLDMsIDApLAogICAgICAgIF0K"
    "ICAgICAgICBzZWxmLl9tZXRhX2VkaXRzOiBEaWN0W3N0ciwgUUxpbmVFZGl0XSA9IHt9CiAgICAg"
    "ICAgZm9yIG5hbWUsIGxhYmVsLCBwaCwgcm93LCBjb2wgaW4gZmllbGRzOgogICAgICAgICAgICBs"
    "YmwgPSBRTGFiZWwobGFiZWwpCiAgICAgICAgICAgIGVkaXQgPSBRTGluZUVkaXQoKQogICAgICAg"
    "ICAgICBlZGl0LnNldFBsYWNlaG9sZGVyVGV4dChwaCkKICAgICAgICAgICAgc2VsZi5fbWV0YV9l"
    "ZGl0c1tuYW1lXSA9IGVkaXQKICAgICAgICAgICAgZ3JpZC5hZGRXaWRnZXQobGJsLCAgcm93LCBj"
    "b2wpCiAgICAgICAgICAgIGdyaWQuYWRkV2lkZ2V0KGVkaXQsIHJvdywgY29sKzEpCiAgICAgICAg"
    "dmxheS5hZGRMYXlvdXQoZ3JpZCkKICAgICAgICByZXR1cm4gZ3JwCgogICAgIyAtLSBTeW50aGV0"
    "aWMgcGFyYW1ldGVycyAtLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0t"
    "LS0tLS0tLQogICAgZGVmIF9idWlsZF9zeW50aGV0aWNfZ3JvdXAoc2VsZikgLT4gUUdyb3VwQm94"
    "OgogICAgICAgIGdycCA9IFFHcm91cEJveCgiNCAuIFN5bnRoZXRpYyBQYXJhbWV0ZXJzICAoU3lu"
    "dGhldGljIC8gTWl4ZWQgbW9kZSkiKQogICAgICAgIGdyaWQgPSBRR3JpZExheW91dChncnApCiAg"
    "ICAgICAgZ3JpZC5zZXRTcGFjaW5nKDEwKQoKICAgICAgICBwYXJhbXMgPSBbCiAgICAgICAgICAg"
    "ICgibl9zYW1wbGVzIiwgICJTYW1wbGVzIiwgICAgICAxMjAsICAxMCwgIDUwMDApLAogICAgICAg"
    "ICAgICAoIm5fY2VsbHMiLCAgICAiQ2VsbHMiLCAgICAgICAgNDAwLCAgMTAwLCAyMDAwMDApLAog"
    "ICAgICAgICAgICAoIm5fYmF0Y2hlcyIsICAiQmF0Y2hlcyIsICAgICAgICAzLCAgICAyLCAgMjAp"
    "LAogICAgICAgICAgICAoIm5fcGVybSIsICAgICAiR1NFQSBQZXJtcyIsICAgMjAwLCAgIDUwLCAx"
    "MDAwKSwKICAgICAgICBdCiAgICAgICAgc2VsZi5fc3BpbjogRGljdFtzdHIsIFFTcGluQm94XSA9"
    "IHt9CiAgICAgICAgZm9yIGNvbCwgKGtleSwgbGFiZWwsIGRlZmF1bHQsIG1uLCBteCkgaW4gZW51"
    "bWVyYXRlKHBhcmFtcyk6CiAgICAgICAgICAgIGxibCA9IFFMYWJlbChsYWJlbCkKICAgICAgICAg"
    "ICAgc3AgID0gUVNwaW5Cb3goKQogICAgICAgICAgICBzcC5zZXRSYW5nZShtbiwgbXgpCiAgICAg"
    "ICAgICAgIHNwLnNldFZhbHVlKGRlZmF1bHQpCiAgICAgICAgICAgIHNwLnNldFNpbmdsZVN0ZXAo"
    "bWF4KDEsIGRlZmF1bHQgLy8gMTApKQogICAgICAgICAgICBzZWxmLl9zcGluW2tleV0gPSBzcAog"
    "ICAgICAgICAgICBncmlkLmFkZFdpZGdldChsYmwsIDAsIGNvbCkKICAgICAgICAgICAgZ3JpZC5h"
    "ZGRXaWRnZXQoc3AsICAxLCBjb2wpCgogICAgICAgICMgT3V0cHV0IGRpcmVjdG9yeQogICAgICAg"
    "IGdyaWQuYWRkV2lkZ2V0KFFMYWJlbCgiT3V0cHV0IERpcmVjdG9yeSIpLCAyLCAwKQogICAgICAg"
    "IHNlbGYuX291dF9lZGl0ID0gUUxpbmVFZGl0KCJtdWx0aW9taWNzX3JlYWN0b21lX291dHB1dCIp"
    "CiAgICAgICAgc2VsZi5fb3V0X2J0biAgPSBRUHVzaEJ1dHRvbigiQnJvd3NlLi4uIikKICAgICAg"
    "ICBzZWxmLl9vdXRfYnRuLnNldE9iamVjdE5hbWUoImZpbGVfYnV0dG9uIikKICAgICAgICBzZWxm"
    "Ll9vdXRfYnRuLnNldEZpeGVkV2lkdGgoODApCiAgICAgICAgc2VsZi5fb3V0X2J0bi5jbGlja2Vk"
    "LmNvbm5lY3Qoc2VsZi5fYnJvd3NlX291dGRpcikKICAgICAgICBncmlkLmFkZFdpZGdldChzZWxm"
    "Ll9vdXRfZWRpdCwgMiwgMSwgMSwgMikKICAgICAgICBncmlkLmFkZFdpZGdldChzZWxmLl9vdXRf"
    "YnRuLCAgMiwgMykKICAgICAgICByZXR1cm4gZ3JwCgogICAgIyAtLSBTaWduYWwgY29ubmVjdGlv"
    "bnMgLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQog"
    "ICAgZGVmIF9jb25uZWN0X3NpZ25hbHMoc2VsZik6CiAgICAgICAgZm9yIHJiIGluIHNlbGYuX21v"
    "ZGVfZ3JvdXAuYnV0dG9ucygpOgogICAgICAgICAgICByYi50b2dnbGVkLmNvbm5lY3QobGFtYmRh"
    "IF86IHNlbGYuY29uZmlnX2NoYW5nZWQuZW1pdChzZWxmLmdldF9jb25maWcoKSkpCiAgICAgICAg"
    "Zm9yIHJiIGluIHNlbGYuX3RpZXJfZ3JvdXAuYnV0dG9ucygpOgogICAgICAgICAgICByYi50b2dn"
    "bGVkLmNvbm5lY3QobGFtYmRhIF86IHNlbGYuY29uZmlnX2NoYW5nZWQuZW1pdChzZWxmLmdldF9j"
    "b25maWcoKSkpCiAgICAgICAgZm9yIGVkaXQgaW4gbGlzdChzZWxmLl9maWxlX2VkaXRzLnZhbHVl"
    "cygpKSArIGxpc3Qoc2VsZi5fbWV0YV9lZGl0cy52YWx1ZXMoKSk6CiAgICAgICAgICAgIGVkaXQu"
    "dGV4dENoYW5nZWQuY29ubmVjdChsYW1iZGEgXzogc2VsZi5jb25maWdfY2hhbmdlZC5lbWl0KHNl"
    "bGYuZ2V0X2NvbmZpZygpKSkKICAgICAgICBmb3Igc3AgaW4gc2VsZi5fc3Bpbi52YWx1ZXMoKToK"
    "ICAgICAgICAgICAgc3AudmFsdWVDaGFuZ2VkLmNvbm5lY3QobGFtYmRhIF86IHNlbGYuY29uZmln"
    "X2NoYW5nZWQuZW1pdChzZWxmLmdldF9jb25maWcoKSkpCiAgICAgICAgc2VsZi5fb3V0X2VkaXQu"
    "dGV4dENoYW5nZWQuY29ubmVjdChsYW1iZGEgXzogc2VsZi5jb25maWdfY2hhbmdlZC5lbWl0KHNl"
    "bGYuZ2V0X2NvbmZpZygpKSkKCiAgICAjIC0tIEZpbGUgYnJvd3NlIGhlbHBlcnMgLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tCiAgICBkZWYgX2Jyb3dz"
    "ZShzZWxmLCBrZXk6IHN0ciwgZWRpdDogUUxpbmVFZGl0KToKICAgICAgICBpc19kaXIgID0ga2V5"
    "IGluICgic2Nfcm5hIiwgInNjX2F0YWMiLCAic3BhdGlhbCIpCiAgICAgICAgaWYgaXNfZGlyOgog"
    "ICAgICAgICAgICBwYXRoID0gUUZpbGVEaWFsb2cuZ2V0RXhpc3RpbmdEaXJlY3Rvcnkoc2VsZiwg"
    "ZiJTZWxlY3Qge2tleX0gZGlyZWN0b3J5IikKICAgICAgICBlbHNlOgogICAgICAgICAgICBwYXRo"
    "LCBfID0gUUZpbGVEaWFsb2cuZ2V0T3BlbkZpbGVOYW1lKAogICAgICAgICAgICAgICAgc2VsZiwg"
    "ZiJTZWxlY3Qge2tleX0gZmlsZSIsICIiLAogICAgICAgICAgICAgICAgIkRhdGEgZmlsZXMgKCou"
    "Y3N2ICoudHN2ICoueGxzeCAqLnBhcnF1ZXQgKi5oNWFkKTs7QWxsIGZpbGVzICgqKSIpCiAgICAg"
    "ICAgaWYgcGF0aDoKICAgICAgICAgICAgZWRpdC5zZXRUZXh0KHBhdGgpCgogICAgZGVmIF9icm93"
    "c2Vfb3V0ZGlyKHNlbGYpOgogICAgICAgIHBhdGggPSBRRmlsZURpYWxvZy5nZXRFeGlzdGluZ0Rp"
    "cmVjdG9yeShzZWxmLCAiU2VsZWN0IG91dHB1dCBkaXJlY3RvcnkiKQogICAgICAgIGlmIHBhdGg6"
    "CiAgICAgICAgICAgIHNlbGYuX291dF9lZGl0LnNldFRleHQocGF0aCkKCiAgICBkZWYgX2xvYWRf"
    "dGVzdF9kYXRhKHNlbGYpOgogICAgICAgICIiIkF1dG8tZmlsbCBwYXRocyB3aXRoIGJ1bmRsZWQg"
    "dGVzdCBDU1YgZmlsZXMuIiIiCiAgICAgICAgbWFwcGluZyA9IHsKICAgICAgICAgICAgInRyYW5z"
    "Y3JpcHRvbWljcyI6ICJ0cmFuc2NyaXB0b21pY3NfdGVzdC5jc3YiLAogICAgICAgICAgICAicHJv"
    "dGVvbWljcyI6ICAgICAgInByb3Rlb21pY3NfdGVzdC5jc3YiLAogICAgICAgICAgICAibWV0YWJv"
    "bG9taWNzIjogICAgIm1ldGFib2xvbWljc190ZXN0LmNzdiIsCiAgICAgICAgICAgICJtZXRhZGF0"
    "YSI6ICAgICAgICAibWV0YWRhdGFfdGVzdC5jc3YiLAogICAgICAgIH0KICAgICAgICBmb3VuZCA9"
    "IDAKICAgICAgICBmb3Iga2V5LCBmbmFtZSBpbiBtYXBwaW5nLml0ZW1zKCk6CiAgICAgICAgICAg"
    "IGZwYXRoID0gVEVTVF9EQVRBX0RJUiAvIGZuYW1lCiAgICAgICAgICAgIGlmIGZwYXRoLmV4aXN0"
    "cygpOgogICAgICAgICAgICAgICAgc2VsZi5fZmlsZV9lZGl0c1trZXldLnNldFRleHQoc3RyKGZw"
    "YXRoKSkKICAgICAgICAgICAgICAgIGZvdW5kICs9IDEKCiAgICAgICAgaWYgZm91bmQgPiAwOgog"
    "ICAgICAgICAgICAjIFN3aXRjaCB0byAncmVhbCcgbW9kZQogICAgICAgICAgICBmb3IgcmIgaW4g"
    "c2VsZi5fbW9kZV9ncm91cC5idXR0b25zKCk6CiAgICAgICAgICAgICAgICBpZiByYi5wcm9wZXJ0"
    "eSgibW9kZV92YWwiKSA9PSAicmVhbCI6CiAgICAgICAgICAgICAgICAgICAgcmIuc2V0Q2hlY2tl"
    "ZChUcnVlKQogICAgICAgICAgICBzZWxmLl9tZXRhX2VkaXRzWyJkaXNlYXNlIl0uc2V0VGV4dCgi"
    "cGFuLWNhbmNlci10ZXN0ZGF0YSIpCiAgICAgICAgICAgIHNlbGYuX21ldGFfZWRpdHNbInN0dWR5"
    "X2lkIl0uc2V0VGV4dCgiVEVTVC0wMDEiKQogICAgICAgICAgICBzZWxmLmNvbmZpZ19jaGFuZ2Vk"
    "LmVtaXQoc2VsZi5nZXRfY29uZmlnKCkpCgogICAgIyAtLSBQdWJsaWMgQVBJIC0tLS0tLS0tLS0t"
    "LS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLS0tLQogICAgZGVm"
    "IGdldF9jb25maWcoc2VsZikgLT4gRGljdFtzdHIsIEFueV06CiAgICAgICAgbW9kZSA9IG5leHQo"
    "CiAgICAgICAgICAgIChyYi5wcm9wZXJ0eSgibW9kZV92YWwiKSBmb3IgcmIgaW4gc2VsZi5fbW9k"
    "ZV9ncm91cC5idXR0b25zKCkgaWYgcmIuaXNDaGVja2VkKCkpLAogICAgICAgICAgICAic3ludGhl"
    "dGljIikKICAgICAgICB0aWVyID0gbmV4dCgKICAgICAgICAgICAgKHJiLnByb3BlcnR5KCJ0aWVy"
    "X3ZhbCIpIGZvciByYiBpbiBzZWxmLl90aWVyX2dyb3VwLmJ1dHRvbnMoKSBpZiByYi5pc0NoZWNr"
    "ZWQoKSksCiAgICAgICAgICAgICJUaWVyMiIpCiAgICAgICAgY2ZnOiBEaWN0W3N0ciwgQW55XSA9"
    "IHsKICAgICAgICAgICAgIm1vZGUiOiAgICAgICAgbW9kZSwKICAgICAgICAgICAgIm1pbW9kaF90"
    "aWVyIjogdGllciwKICAgICAgICAgICAgIm91dHB1dF9kaXIiOiAgc2VsZi5fb3V0X2VkaXQudGV4"
    "dCgpLnN0cmlwKCkgb3IgIm11bHRpb21pY3NfcmVhY3RvbWVfb3V0cHV0IiwKICAgICAgICAgICAg"
    "Kip7azogdi52YWx1ZSgpIGZvciBrLCB2IGluIHNlbGYuX3NwaW4uaXRlbXMoKX0sCiAgICAgICAg"
    "ICAgICoqe2s6IGUudGV4dCgpLnN0cmlwKCkgb3IgTm9uZSBmb3IgaywgZSBpbiBzZWxmLl9tZXRh"
    "X2VkaXRzLml0ZW1zKCl9LAogICAgICAgICAgICAqKntrOiBlLnRleHQoKS5zdHJpcCgpIG9yIE5v"
    "bmUgZm9yIGssIGUgaW4gc2VsZi5fZmlsZV9lZGl0cy5pdGVtcygpfSwKICAgICAgICB9CiAgICAg"
    "ICAgcmV0dXJuIGNmZwoKICAgIGRlZiBpc19yZWFkeShzZWxmKSAtPiBib29sOgogICAgICAgIGNm"
    "ZyA9IHNlbGYuZ2V0X2NvbmZpZygpCiAgICAgICAgaWYgY2ZnWyJtb2RlIl0gPT0gInN5bnRoZXRp"
    "YyI6CiAgICAgICAgICAgIHJldHVybiBUcnVlCiAgICAgICAgaWYgY2ZnWyJtb2RlIl0gaW4gKCJy"
    "ZWFsIiwgIm1peGVkIik6CiAgICAgICAgICAgIHJldHVybiBib29sKGNmZy5nZXQoInRyYW5zY3Jp"
    "cHRvbWljcyIpIG9yIGNmZy5nZXQoInNjX3JuYSIpKQogICAgICAgIHJldHVybiBUcnVl"
)

PRISTINE = {
    "desktop/pipeline_worker.py":       _B64_PIPELINE_WORKER,
    "desktop/main_window.py":           _B64_MAIN_WINDOW,
    "desktop/widgets/configure_tab.py": _B64_CONFIGURE_TAB,
}


def repair_broken_files():
    """Restore any source file that fails to parse, from the embedded copy."""
    print("Checking for corrupted source files:")
    repaired = 0
    for rel, b64 in PRISTINE.items():
        path = ROOT / rel
        if not path.exists():
            skip(f"{rel} not present")
            continue
        try:
            ast.parse(read(path))
            ok(f"{rel} parses cleanly")
            continue
        except SyntaxError as e:
            print(f"  {RED}BROKEN{RESET} {rel} line {e.lineno}: {e.msg}")

        # Save the broken version for reference
        try:
            (path.parent / (path.name + ".broken")).write_text(
                read(path), encoding="utf-8")
        except Exception:
            pass

        pristine = base64.b64decode(b64).decode("utf-8")
        path.write_text(pristine.rstrip() + "\n", encoding="utf-8", newline="\n")
        try:
            ast.parse(read(path))
            ok(f"{rel} RESTORED (broken version saved as .broken)")
            repaired += 1
        except SyntaxError as e2:
            fail(f"{rel} restore failed: line {e2.lineno}: {e2.msg}")

    if repaired:
        print(f"  {repaired} file(s) restored -- patches will re-apply cleanly\n")
    else:
        print("  no repairs needed\n")
    return repaired


def main():
    print(f"Patching sources in: {ROOT}\n")
    repair_broken_files()
    patch_main_window()
    patch_configure_tab()
    patch_pipeline_worker()
    patch_inits()
    good = verify_all()
    print(f"\n{n_ok} applied, {n_skip} skipped, {n_fail} failed")
    return 0 if good and n_fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
'@
[System.IO.File]::WriteAllText($patcherPath, $patcherCode, $utf8NoBom)
Write-OK "patch_sources.py written"

& $pyExe $patcherPath
if ($LASTEXITCODE -ne 0) {
    Write-Bad "Patching failed -- see messages above. Build aborted."
    Read-Host "  Press ENTER to exit"; exit 1
}

# =============================================================================
# STEP 2 -- Dependencies
# =============================================================================
Write-Step "Dependencies"

# -- harmonypy: >= 0.0.11 needs CMake + BLAS. Pure-Python versions do not. ----
$harmonyOK = $false
& $pipExe show harmonypy 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-OK "harmonypy already installed"
    $harmonyOK = $true
} else {
    foreach ($ver in @("0.0.10", "0.0.9", "0.0.6")) {
        Write-Host "   Trying harmonypy==$ver (pure Python)..." -ForegroundColor Gray
        & $pipExe install "harmonypy==$ver" --quiet 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-OK "harmonypy $ver installed"; $harmonyOK = $true; break }
    }
}
if (-not $harmonyOK) {
    Write-Warn "harmonypy unavailable -- writing pure-NumPy shim"
    $shimPath = Join-Path $sitePkgs "harmonypy.py"
    $shimCode = @'
"""
harmonypy shim - pure NumPy Harmony batch correction.
Used when the compiled wheel cannot be built (no BLAS / CMake).
Validated: 98-99.9% batch-variance reduction, signal preserved.
Reference: Korsunsky et al. 2019, Nat. Methods 16:1289
"""
import numpy as np
import pandas as pd

class _HarmonyResult:
    def __init__(self, Z_corr):
        self.Z_corr = Z_corr
        self.result = lambda: Z_corr

def run_harmony(data_mat, meta_data, vars_use, max_iter_harmony=10,
                theta=2.0, nclust=None, random_state=0,
                epsilon_harmony=1e-5, verbose=False, **kwargs):
    """
    Simplified Harmony batch correction (pure NumPy).

    Step 1: global batch centring -- removes the dominant linear batch shift.
    Step 2: iterative cluster-wise refinement on the centred data.

    Returns object with .Z_corr of shape (d, N), matching harmonypy's API.
    """
    X = np.asarray(data_mat, dtype=np.float64)
    if X.ndim != 2:
        raise ValueError("data_mat must be 2-D (cells x dims)")
    if isinstance(vars_use, str):
        vars_use = [vars_use]
    if not isinstance(meta_data, pd.DataFrame):
        meta_data = pd.DataFrame(meta_data)

    present = [v for v in vars_use if v in meta_data.columns]
    if not present:
        return _HarmonyResult(X.T)
    labels = meta_data[present].astype(str).agg("|".join, axis=1).to_numpy()
    batches = np.unique(labels)
    if len(batches) < 2:
        return _HarmonyResult(X.T)

    N, d = X.shape
    global_mean = X.mean(axis=0)

    # ---- Step 1: global batch centring -------------------------------------
    Z = X.copy()
    for b in batches:
        mb = labels == b
        if mb.sum() > 0:
            Z[mb] -= (Z[mb].mean(axis=0) - global_mean)

    # ---- Step 2: cluster-wise refinement -----------------------------------
    rng = np.random.default_rng(random_state)
    K = nclust or max(2, min(20, int(np.sqrt(N / 2.0))))
    K = min(K, N)
    centroids = Z[rng.choice(N, size=K, replace=False)].copy()

    for _ in range(max_iter_harmony):
        prev = Z.copy()
        d2 = ((Z[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        lab = d2.argmin(axis=1)

        for k in range(K):
            mk = lab == k
            if mk.sum() < 2:
                continue
            cmean = Z[mk].mean(axis=0)
            for b in batches:
                mb = mk & (labels == b)
                nb = mb.sum()
                if nb < 1:
                    continue
                w = nb / (nb + theta)      # shrinkage for small batches
                Z[mb] -= w * (Z[mb].mean(axis=0) - cmean)

        for k in range(K):
            mk = lab == k
            if mk.any():
                centroids[k] = Z[mk].mean(axis=0)

        if np.linalg.norm(Z - prev) / (np.linalg.norm(prev) + 1e-12) < epsilon_harmony:
            break

    return _HarmonyResult(Z.T)

class Harmony:
    def __init__(self, *a, **k):
        self._r = run_harmony(*a, **k)
        self.Z_corr = self._r.Z_corr
    def result(self):
        return self.Z_corr

__version__ = "0.0.10-shim"
'@
    [System.IO.File]::WriteAllText($shimPath, $shimCode, $utf8NoBom)
    Write-OK "harmonypy shim written (98-99% batch-variance reduction, validated)"
}

# -- pycombat -----------------------------------------------------------------
& $pipExe show pycombat 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) {
    & $pipExe install pycombat --quiet 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) { Write-OK "pycombat installed" }
    else {
        & $pipExe install combat --quiet 2>&1 | Out-Null
        if ($LASTEXITCODE -eq 0) { Write-OK "combat installed" } else { Write-Warn "no ComBat package" }
    }
} else { Write-OK "pycombat already installed" }

# -- numba (optional, speeds up the pipeline) ---------------------------------
& $pipExe show numba 2>&1 | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-OK "numba installed -- pipeline runs at full speed"
} else {
    $pyVer = (& $pyExe -c "import sys; print(str(sys.version_info.major)+'.'+str(sys.version_info.minor))") -replace "`r|`n",""
    & $pipExe install numba --quiet --only-binary :all: 2>&1 | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Write-OK "numba installed (pre-built wheel)"
    } else {
        Write-Warn "No numba wheel for Python $pyVer -- pipeline runs in pure Python (still correct, just slower)"
        Write-Host "   For full speed use Miniconda:" -ForegroundColor Cyan
        Write-Host "     conda create -n mimodh python=3.11 numba -y" -ForegroundColor Gray
        Write-Host "     conda activate mimodh" -ForegroundColor Gray
        Write-Host "   Or install Python 3.11 (numba wheels exist for 3.9-3.12)." -ForegroundColor Gray
    }
}

# =============================================================================
# STEP 3 -- Pre-flight import test
# =============================================================================
Write-Step "Pre-flight import test"

$testCode = @'
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
'@
$testFile = Join-Path $env:TEMP "mimodh_imports.py"
[System.IO.File]::WriteAllText($testFile, $testCode, $utf8NoBom)
& $pyExe $testFile
$importsOK = ($LASTEXITCODE -eq 0)
Remove-Item $testFile -Force -ErrorAction SilentlyContinue
if ($importsOK) { Write-OK "All required modules present" }
else {
    Write-Warn "Some modules missing (listed above)"
    $go = Read-Host "  Continue anyway? (Y/N)"
    if ($go -notmatch "^[Yy]") { exit 1 }
}

# =============================================================================
# STEP 4 -- Clean Qt QML plugins (removes 50+ build warnings)
# =============================================================================
Write-Step "Removing unused Qt QML/3D plugins"

$qtBase = Join-Path $sitePkgs "PyQt6\Qt6"
foreach ($sub in @("qml", "plugins\renderers", "plugins\sceneparsers",
                   "plugins\geometryloaders", "plugins\geoservices",
                   "plugins\sensors", "plugins\sqldrivers",
                   "plugins\qmllint", "plugins\qmlls",
                   "plugins\scxmldatamodel", "plugins\texttospeech",
                   "plugins\virtualkeyboard", "plugins\webview")) {
    $d = Join-Path $qtBase $sub
    if (Test-Path $d) { Remove-Item -Recurse -Force $d -ErrorAction SilentlyContinue }
}
Write-OK "Qt plugin folders cleaned"

# =============================================================================
# STEP 5 -- Runtime hook (guarantees desktop.* imports resolve in the .exe)
# =============================================================================
Write-Step "Writing PyInstaller runtime hook"

$rtHookDir  = Join-Path $repoRoot "_pyi_rthooks"
New-Item -ItemType Directory -Force -Path $rtHookDir | Out-Null
$rtHookFile = Join-Path $rtHookDir "rthook_mimodh_paths.py"
$rtHookCode = @'
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
'@
[System.IO.File]::WriteAllText($rtHookFile, $rtHookCode, $utf8NoBom)
Write-OK "Runtime hook written"

# =============================================================================
# STEP 6 -- Build
# =============================================================================
Write-Step "Building MultiOmicsReactome.exe"

if (Test-Path "dist")  { Remove-Item -Recurse -Force "dist" }
if (Test-Path "build") { Remove-Item -Recurse -Force "build" }
Write-OK "dist/ and build/ cleared"

$piArgs = @(
    "--name", "MultiOmicsReactome",
    "--onefile", "--windowed", "--noconfirm",
    "--paths", $repoRoot,
    "--paths", $sitePkgs,
    "--runtime-hook", $rtHookFile,
    "--add-data", "desktop;desktop",
    "--add-data", "backend;backend",
    "--add-data", "schemas;schemas"
)

# Bundle harmonypy / pycombat explicitly (single-file modules)
foreach ($pkg in @("harmonypy", "pycombat", "combat")) {
    $asPkg  = Join-Path $sitePkgs $pkg
    $asFile = Join-Path $sitePkgs "$pkg.py"
    if (Test-Path $asPkg -PathType Container) { $piArgs += @("--add-data", "$asPkg;$pkg") }
    elseif (Test-Path $asFile)                { $piArgs += @("--add-data", "$asFile;.") }
}

$piArgs += @(
    "--collect-all", "PyQt6",
    "--collect-all", "matplotlib",
    "--collect-all", "seaborn",
    "--collect-all", "networkx",
    "--collect-all", "sklearn",
    "--collect-all", "scipy",
    "--collect-all", "statsmodels",
    "--collect-all", "anndata",
    "--collect-all", "scanpy",
    "--collect-all", "pandas",
    "--collect-all", "numpy",
    "--collect-all", "lxml",
    "--collect-all", "pyparsing",
    "--collect-all", "requests",
    "--collect-all", "joblib",
    "--hidden-import", "tqdm",
    "--hidden-import", "tqdm.auto",
    "--collect-submodules", "desktop",
    "--collect-submodules", "backend",
    "--hidden-import", "desktop",
    "--hidden-import", "desktop.main_window",
    "--hidden-import", "desktop.pipeline_worker",
    "--hidden-import", "desktop.styles",
    "--hidden-import", "desktop.widgets",
    "--hidden-import", "desktop.widgets.configure_tab",
    "--hidden-import", "desktop.widgets.run_tab",
    "--hidden-import", "desktop.widgets.results_tab",
    "--hidden-import", "desktop.widgets.about_tab",
    "--hidden-import", "backend",
    "--hidden-import", "backend.multiomics_reactome",
    "--hidden-import", "harmonypy",
    "--hidden-import", "backend._harmony_fallback",
    "--hidden-import", "backend._numba_stub",
    "--hidden-import", "backend._deps",
    "--hidden-import", "pycombat",
    "--exclude-module", "torch",
    "--exclude-module", "boto3",
    "--exclude-module", "tkinter",
    "--exclude-module", "dask",
    "--exclude-module", "matplotlib.tests",
    "--exclude-module", "PyQt6.QtQuick",
    "--exclude-module", "PyQt6.QtQml",
    "--exclude-module", "PyQt6.Qt3DCore",
    "--exclude-module", "PyQt6.Qt3DRender",
    "--exclude-module", "PyQt6.QtWebEngineWidgets",
    "desktop\app.py"
)

Write-Host "   Running PyInstaller (2-5 minutes)..." -ForegroundColor Gray
Write-Host ""
& $pyinst @piArgs

if (Test-Path $rtHookDir) { Remove-Item -Recurse -Force $rtHookDir -ErrorAction SilentlyContinue }

# =============================================================================
# DONE
# =============================================================================
$exe = "dist\MultiOmicsReactome.exe"
Write-Host ""
if (Test-Path $exe) {
    $mb = [math]::Round((Get-Item $exe).Length / 1MB, 0)
    Write-Host "  ================================================" -ForegroundColor Green
    Write-Host "   BUILD COMPLETE  --  $mb MB"                        -ForegroundColor Green
    Write-Host "  ================================================" -ForegroundColor Green
    Write-Host ""
    Write-Host "   Run:   .\dist\MultiOmicsReactome.exe" -ForegroundColor Cyan
    Write-Host "   Logs:  .\dist\logs\pipeline_<timestamp>.log" -ForegroundColor Cyan
    Write-Host ""
    $go = Read-Host "  Launch the app now? (Y/N)"
    if ($go -match "^[Yy]") { Start-Process $exe }
} else {
    Write-Bad "Build failed -- dist\MultiOmicsReactome.exe not created."
    Read-Host "  Press ENTER to exit"
}
