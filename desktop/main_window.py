"""
main_window.py — MainWindow for MultiOmics-Reactome Desktop v3.0.
Coordinates ConfigureTab ↔ RunTab ↔ ResultsTab via PipelineWorker.
"""
from __future__ import annotations
import sys
from pathlib import Path
from typing import Dict, Any

from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QTabWidget, QLabel, QMessageBox, QApplication
)
from PyQt6.QtCore  import Qt, QTimer
from PyQt6.QtGui   import QFont, QAction

from desktop.styles       import DARK_THEME, STATUS_COLORS
from desktop.pipeline_worker import PipelineWorker
from desktop.widgets.configure_tab import ConfigureTab
from desktop.widgets.run_tab        import RunTab
from desktop.widgets.results_tab    import ResultsTab
from desktop.widgets.about_tab      import AboutTab


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self._worker: PipelineWorker | None = None
        self._elapsed = 0
        self._timer   = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._current_config: Dict[str, Any] = {}

        self._setup_window()
        self._build_ui()
        self._build_menu()
        self.setStyleSheet(DARK_THEME)

    # ── Window setup ─────────────────────────────────────────────────────────
    def _setup_window(self):
        self.setWindowTitle("MultiOmics-Reactome v3.0  ·  MIMODH Desktop")
        _scr = QApplication.primaryScreen()
        if _scr is not None:
            _av = _scr.availableGeometry()
            self.setMinimumSize(min(1000, _av.width() - 60),
                                min(640, _av.height() - 90))
            self.resize(min(1280, _av.width() - 40),
                        min(800, _av.height() - 70))
        else:
            self.setMinimumSize(900, 620)
            self.resize(1100, 740)
    # ── UI layout ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)

        # ── Header bar ────────────────────────────────────────────────────────
        header = QWidget()
        header.setFixedHeight(52)
        header.setStyleSheet("background:#1a1f2e; border-bottom:1px solid #2d3748;")
        h_lay = QHBoxLayout(header)
        h_lay.setContentsMargins(20, 0, 20, 0)

        icon_lbl = QLabel("🧬")
        icon_lbl.setFont(QFont("Segoe UI Emoji", 20))
        h_lay.addWidget(icon_lbl)

        title = QLabel("MultiOmics-Reactome")
        title.setObjectName("title_label")
        title.setFont(QFont("Segoe UI", 15, QFont.Weight.Bold))
        h_lay.addWidget(title)

        ver = QLabel("v3.0.0")
        ver.setObjectName("badge_version")
        h_lay.addWidget(ver)

        mimodh_badge = QLabel("MIMODH v1.0")
        mimodh_badge.setObjectName("badge_mimodh")
        h_lay.addWidget(mimodh_badge)

        h_lay.addStretch()

        self._status_bar_lbl = QLabel("IDLE")
        self._status_bar_lbl.setStyleSheet("color:#6b7280;font-size:12px;")
        h_lay.addWidget(self._status_bar_lbl)
        root.addWidget(header)

        # ── Tab widget ────────────────────────────────────────────────────────
        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._cfg_tab     = ConfigureTab()
        self._run_tab     = RunTab()
        self._results_tab = ResultsTab()
        self._about_tab   = AboutTab()

        self._tabs.addTab(self._cfg_tab,     "⚙️  Configure")
        self._tabs.addTab(self._run_tab,     "▶  Run")
        self._tabs.addTab(self._results_tab, "📊  Results")
        self._tabs.addTab(self._about_tab,   "ℹ️  About")

        root.addWidget(self._tabs, stretch=1)

        # ── Status bar ────────────────────────────────────────────────────────
        sb = self.statusBar()
        sb.showMessage("Ready  ·  MultiOmics-Reactome Desktop v3.0  ·  MIMODH v1.0")

        # ── Wire signals ──────────────────────────────────────────────────────
        self._cfg_tab.config_changed.connect(self._on_config_changed)
        self._run_tab._run_btn.clicked.connect(self._start_pipeline)
        self._run_tab._stop_btn.clicked.connect(self._stop_pipeline)

    # ── Menu bar ──────────────────────────────────────────────────────────────
    def _build_menu(self):
        file_menu = self.menuBar().addMenu("File")

        run_act = QAction("▶  Run Pipeline", self)
        run_act.setShortcut("Ctrl+R")
        run_act.triggered.connect(self._start_pipeline)
        file_menu.addAction(run_act)

        file_menu.addSeparator()

        quit_act = QAction("Quit", self)
        quit_act.setShortcut("Ctrl+Q")
        quit_act.triggered.connect(QApplication.instance().quit)
        file_menu.addAction(quit_act)

        help_menu = self.menuBar().addMenu("Help")
        about_act = QAction("About", self)
        about_act.triggered.connect(lambda: self._tabs.setCurrentIndex(3))
        help_menu.addAction(about_act)

    # ── Slots ─────────────────────────────────────────────────────────────────
    def _on_config_changed(self, cfg: Dict[str, Any]):
        self._current_config = cfg

    def _start_pipeline(self):
        if self._worker and self._worker.isRunning():
            return

        cfg = self._current_config or self._cfg_tab.get_config()

        if not self._cfg_tab.is_ready():
            QMessageBox.warning(
                self, "Missing Input",
                "Please select at least one data file (transcriptomics or scRNA-seq)\n"
                "or switch to Synthetic mode.")
            return

        # Switch to Run tab
        self._tabs.setCurrentIndex(1)
        self._run_tab.reset()
        self._run_tab.set_status("RUNNING", "Starting…")
        self._run_tab.append_log("═" * 60, "SECTION")
        self._run_tab.append_log(f"  MultiOmics-Reactome v3.0  ·  MIMODH {cfg.get('mimodh_tier','Tier2')}", "SECTION")
        self._run_tab.append_log(f"  Mode: {cfg.get('mode','synthetic').upper()}  ·  Disease: {cfg.get('disease','?')}", "INFO")
        self._run_tab.append_log("═" * 60, "SECTION")

        self._elapsed = 0
        self._timer.start(1000)
        self._status_bar_lbl.setText("● RUNNING")
        self._status_bar_lbl.setStyleSheet(f"color:{STATUS_COLORS['RUNNING']};font-size:12px;font-weight:bold;")

        self._worker = PipelineWorker(cfg, parent=self)
        self._worker.log_line.connect(self._run_tab.append_log)
        self._worker.progress.connect(self._run_tab.set_progress)
        self._worker.finished.connect(self._on_pipeline_finished)
        self._worker.failed.connect(self._on_pipeline_failed)
        self._worker.start()

    def _stop_pipeline(self):
        if self._worker and self._worker.isRunning():
            self._worker.abort()
            self._timer.stop()
            self._run_tab.set_status("IDLE", "Stopped by user")
            self._run_tab.append_log("Pipeline stopped by user.", "WARNING")
            self._status_bar_lbl.setText("IDLE")
            self._status_bar_lbl.setStyleSheet("color:#6b7280;font-size:12px;")

    def _on_pipeline_finished(self, result: Dict[str, Any]):
        self._timer.stop()
        self._run_tab.set_status("COMPLETED", "All stages complete")
        self._run_tab.append_log("", "INFO")
        self._run_tab.append_log("✓  Pipeline COMPLETE — MIMODH XML record generated.", "MIMODH")
        self._run_tab.set_progress(100, "COMPLETE")
        self._status_bar_lbl.setText("✓ COMPLETED")
        self._status_bar_lbl.setStyleSheet(f"color:{STATUS_COLORS['COMPLETED']};font-size:12px;font-weight:bold;")

        out_dir = result.get("output_dir", self._current_config.get("output_dir", "multiomics_reactome_output"))
        self._results_tab.load_results(out_dir)
        self.statusBar().showMessage(f"Complete  ·  Outputs saved to: {out_dir}")

        # Auto-switch to results after short delay
        QTimer.singleShot(1500, lambda: self._tabs.setCurrentIndex(2))

    def _on_pipeline_failed(self, error: str):
        self._timer.stop()
        self._run_tab.set_status("FAILED", "Error")
        self._run_tab.append_log(f"✗ FAILED: {error}", "ERROR")
        self._status_bar_lbl.setText("✗ FAILED")
        self._status_bar_lbl.setStyleSheet(f"color:{STATUS_COLORS['FAILED']};font-size:12px;font-weight:bold;")
        QMessageBox.critical(self, "Pipeline Failed",
                             f"The pipeline encountered an error:\n\n{error}\n\n"
                             "See the Run tab log for details.")

    def _tick(self):
        self._elapsed += 1
        self._run_tab.set_elapsed(self._elapsed)

    def closeEvent(self, event):
        if self._worker and self._worker.isRunning():
            reply = QMessageBox.question(
                self, "Pipeline Running",
                "A pipeline is still running. Stop it and quit?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
            if reply == QMessageBox.StandardButton.Yes:
                self._worker.abort()
                event.accept()
            else:
                event.ignore()
        else:
            event.accept()
