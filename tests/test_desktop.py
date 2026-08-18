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
