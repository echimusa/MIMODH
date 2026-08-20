"""Desktop application tests (headless).

Run with:  QT_QPA_PLATFORM=offscreen pytest tests/test_desktop.py -v
"""
import ast
import os
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

DESKTOP_FILES = (
    "app.py", "main_window.py", "pipeline_worker.py", "styles.py",
    "widgets/configure_tab.py", "widgets/run_tab.py",
    "widgets/results_tab.py", "widgets/about_tab.py",
)


@pytest.mark.parametrize("rel", DESKTOP_FILES)
def test_desktop_file_parses(rel):
    path = ROOT / "desktop" / rel
    assert path.exists(), f"missing {rel}"
    ast.parse(path.read_text(encoding="utf-8"))


def test_styles_import():
    from desktop.styles import DARK_THEME, LOG_COLORS, STATUS_COLORS
    assert "QMainWindow" in DARK_THEME
    for k in ("IDLE", "RUNNING", "COMPLETED", "FAILED"):
        assert k in STATUS_COLORS
    for k in ("INFO", "WARNING", "ERROR", "SUCCESS"):
        assert k in LOG_COLORS


def test_pipeline_worker_import():
    pytest.importorskip("PyQt6.QtCore", reason="PyQt6 not installed")
    from desktop.pipeline_worker import PipelineWorker
    assert hasattr(PipelineWorker, "run")
    assert hasattr(PipelineWorker, "abort")


def test_worker_handles_frozen_paths():
    """The worker must resolve paths for both script and frozen execution."""
    src = (ROOT / "desktop" / "pipeline_worker.py").read_text(encoding="utf-8")
    assert "_MEIPASS" in src, "pipeline_worker.py is missing the frozen-path fix"


def test_configure_tab_resolves_test_data_when_frozen():
    src = (ROOT / "desktop" / "widgets" / "configure_tab.py").read_text(encoding="utf-8")
    assert "_MEIPASS" in src or "_get_test_data_dir" in src, (
        "configure_tab.py is missing the frozen test-data path fix"
    )


def test_main_window_is_screen_aware():
    src = (ROOT / "desktop" / "main_window.py").read_text(encoding="utf-8")
    assert "primaryScreen" in src, (
        "main_window.py should size itself from the available screen geometry"
    )


def test_numba_stub_installed_at_entry_point():
    """desktop/app.py must install the numba substitute before anything can
    import scanpy.

    scanpy imports numba unconditionally at module load and calls into it at
    runtime; the real package cannot be bundled on Windows.
    """
    src = (ROOT / "desktop" / "app.py").read_text(encoding="utf-8")
    assert "_numba_stub" in src, "app.py does not reference backend._numba_stub"
    assert "_NUMBA_STUBBED" in src, "the installer is imported but never called"


def test_numba_stub_install_is_unconditional():
    """The install call must not sit inside a conditional.

    Regression test: the stub was once nested inside
    `if str(repo_root) not in sys.path:`, so it was skipped whenever the
    PyInstaller runtime hook had already put the extraction folder on sys.path
    - exactly the frozen case it exists to protect.
    """
    for rel in ("desktop/app.py", "desktop/pipeline_worker.py"):
        src = (ROOT / rel).read_text(encoding="utf-8")
        for line in src.split("\n"):
            if "_NUMBA_STUBBED = " in line:
                indent = len(line) - len(line.lstrip())
                assert indent <= 8, (
                    f"{rel}: the stub installer is indented {indent} spaces, so "
                    "it sits inside a nested block and may be skipped")
                break
        else:
            raise AssertionError(f"{rel} never calls the stub installer")


def test_runtime_hook_installs_numba_stub():
    """The PyInstaller runtime hook is the earliest safe place for the stub."""
    for script in ("fix_and_build.sh", "FIX_AND_BUILD.ps1"):
        path = ROOT / script
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        assert "_numba_stub" in src, (
            f"{script} runtime hook does not install the numba substitute")


def test_stub_module_is_bundled_by_build_scripts():
    """The substitute lives in backend/, so it must be an explicit hidden-import
    or it will not be present in the frozen application."""
    for script in ("fix_and_build.sh", "FIX_AND_BUILD.ps1"):
        path = ROOT / script
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        assert "backend._numba_stub" in src, (
            f"{script} does not bundle backend._numba_stub")
