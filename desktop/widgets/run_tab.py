"""
run_tab.py — Run control panel with live log output and progress bar.
"""
from __future__ import annotations
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QProgressBar, QPlainTextEdit, QFrame
)
from PyQt6.QtCore  import Qt, QDateTime
from PyQt6.QtGui   import QTextCursor, QColor, QFont, QTextCharFormat

from desktop.styles import LOG_COLORS, STATUS_COLORS


class RunTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(12)

        # ── Status row ─────────────────────────────────────────────────────
        status_row = QHBoxLayout()

        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: #6b7280; font-size: 18px;")
        self._status_lbl = QLabel("IDLE")
        self._status_lbl.setStyleSheet("color: #6b7280; font-weight: bold; font-size: 14px;")
        self._stage_lbl  = QLabel("")
        self._stage_lbl.setStyleSheet("color: #4b5563; font-size: 12px;")

        status_row.addWidget(self._status_dot)
        status_row.addWidget(self._status_lbl)
        status_row.addWidget(QLabel("·"))
        status_row.addWidget(self._stage_lbl)
        status_row.addStretch()

        self._elapsed_lbl = QLabel("00:00")
        self._elapsed_lbl.setStyleSheet("color: #4b5563; font-family: monospace; font-size: 12px;")
        status_row.addWidget(self._elapsed_lbl)
        lay.addLayout(status_row)

        # ── Progress bar ────────────────────────────────────────────────────
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFormat("%v%  %p")
        self._progress.setFixedHeight(16)
        lay.addWidget(self._progress)

        # ── Pipeline stage chips ────────────────────────────────────────────
        stage_row = QHBoxLayout()
        stage_row.setSpacing(4)
        self._stage_chips: list[QLabel] = []
        stages = ["Ingest","Preprocess","Batch Corr","NMF+WNN",
                  "Reactome","Network","DE+PAS","Visualise","MIMODH XML"]
        for s in stages:
            chip = QLabel(s)
            chip.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chip.setStyleSheet("""
                background: #1f2937; color: #4b5563;
                border-radius: 4px; padding: 3px 7px; font-size: 10px;
            """)
            self._stage_chips.append(chip)
            stage_row.addWidget(chip)
        stage_row.addStretch()
        lay.addLayout(stage_row)

        # ── Separator ───────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #1f2937;")
        lay.addWidget(sep)

        # ── Log output ──────────────────────────────────────────────────────
        log_header = QHBoxLayout()
        log_lbl = QLabel("Pipeline Log")
        log_lbl.setObjectName("section_label")
        log_header.addWidget(log_lbl)
        log_header.addStretch()
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.setObjectName("file_button")
        self._clear_btn.setFixedWidth(60)
        self._clear_btn.clicked.connect(self._log_area.clear if hasattr(self,'_log_area') else lambda: None)
        log_header.addWidget(self._clear_btn)
        lay.addLayout(log_header)

        self._log_area = QPlainTextEdit()
        self._log_area.setReadOnly(True)
        self._log_area.setMaximumBlockCount(4000)
        self._log_area.setFont(QFont("Cascadia Code,Fira Code,Courier New", 11))
        lay.addWidget(self._log_area, stretch=1)

        # Re-wire clear button now that _log_area exists
        self._clear_btn.clicked.disconnect()
        self._clear_btn.clicked.connect(self._log_area.clear)

        # ── Run / Stop buttons ──────────────────────────────────────────────
        btn_row = QHBoxLayout()
        self._run_btn  = QPushButton("▶  Run Pipeline")
        self._run_btn.setObjectName("run_button")
        self._stop_btn = QPushButton("■  Stop")
        self._stop_btn.setObjectName("stop_button")
        self._stop_btn.setFixedWidth(100)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._run_btn, stretch=1)
        btn_row.addWidget(self._stop_btn)
        lay.addLayout(btn_row)

    # ── Public slots ─────────────────────────────────────────────────────────
    def set_status(self, status: str, stage: str = ""):
        color = STATUS_COLORS.get(status, "#6b7280")
        self._status_dot.setStyleSheet(f"color: {color}; font-size: 18px;")
        self._status_lbl.setStyleSheet(f"color: {color}; font-weight: bold; font-size: 14px;")
        self._status_lbl.setText(status)
        self._stage_lbl.setText(stage)

        running = status == "RUNNING"
        self._run_btn.setEnabled(not running)
        self._stop_btn.setEnabled(running)

        if status in ("COMPLETED", "FAILED", "IDLE"):
            self._progress.setValue(100 if status == "COMPLETED" else self._progress.value())

    def set_progress(self, pct: int, stage: str = ""):
        self._progress.setValue(pct)
        self._stage_lbl.setText(stage)
        # Highlight current chip
        chip_map = {
            "Ingest": 0, "Preprocessing": 1, "Batch": 2, "NMF": 3,
            "Reactome": 4, "Network": 5, "Differential": 6, "Pathway": 6,
            "Overlay": 7, "MIMODH": 8, "COMPLETE": 8,
        }
        idx = next((v for k, v in chip_map.items() if k.lower() in stage.lower()), -1)
        for i, chip in enumerate(self._stage_chips):
            if i < idx:
                chip.setStyleSheet("background:#1e3a2a;color:#34d399;border-radius:4px;padding:3px 7px;font-size:10px;")
            elif i == idx:
                chip.setStyleSheet("background:#1e3a5f;color:#93c5fd;border-radius:4px;padding:3px 7px;font-size:10px;font-weight:bold;")
            else:
                chip.setStyleSheet("background:#1f2937;color:#4b5563;border-radius:4px;padding:3px 7px;font-size:10px;")

    def append_log(self, text: str, level: str = "INFO"):
        color = LOG_COLORS.get(level, "#a0aec0")
        ts    = QDateTime.currentDateTime().toString("hh:mm:ss")

        cursor = self._log_area.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)

        # Timestamp
        fmt_ts = QTextCharFormat()
        fmt_ts.setForeground(QColor("#374151"))
        cursor.insertText(f"[{ts}] ", fmt_ts)

        # Message
        fmt_msg = QTextCharFormat()
        fmt_msg.setForeground(QColor(color))
        if level in ("ERROR", "SUCCESS", "SECTION", "MIMODH"):
            fmt_msg.setFontWeight(700)
        cursor.insertText(text + "\n", fmt_msg)

        self._log_area.setTextCursor(cursor)
        self._log_area.ensureCursorVisible()

    def set_elapsed(self, seconds: int):
        m, s = divmod(seconds, 60)
        self._elapsed_lbl.setText(f"{m:02d}:{s:02d}")

    def reset(self):
        self._progress.setValue(0)
        self._log_area.clear()
        self.set_status("IDLE")
        for chip in self._stage_chips:
            chip.setStyleSheet(
                "background:#1f2937;color:#4b5563;border-radius:4px;padding:3px 7px;font-size:10px;")
        self._elapsed_lbl.setText("00:00")
