"""
results_tab.py — Results browser: file tree + preview pane.
"""
from __future__ import annotations
import os, subprocess, sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QSplitter, QTreeWidget,
    QTreeWidgetItem, QLabel, QPlainTextEdit, QPushButton, QFrame
)
from PyQt6.QtCore import Qt, QSize
from PyQt6.QtGui  import QFont, QColor, QIcon

RESULT_ICONS = {
    ".png":  "🖼️",  ".jpg": "🖼️",
    ".html": "🌐",
    ".xml":  "📋",
    ".csv":  "📊",
    ".json": "🔧",
    ".txt":  "📄",
    ".log":  "📄",
}

HIGHLIGHT_FILES = {"mimodh_record.xml", "validation_report.html",
                   "interactive_network.html"}


class ResultsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._output_dir: Path | None = None
        self._build_ui()

    def _build_ui(self):
        lay = QVBoxLayout(self)
        lay.setContentsMargins(16, 16, 16, 16)
        lay.setSpacing(10)

        # Header row
        hdr = QHBoxLayout()
        lbl = QLabel("Results")
        lbl.setObjectName("section_label")
        hdr.addWidget(lbl)
        hdr.addStretch()
        self._dir_lbl = QLabel("")
        self._dir_lbl.setStyleSheet("color:#4b5563;font-size:11px;")
        hdr.addWidget(self._dir_lbl)

        self._open_dir_btn = QPushButton("📂  Open Folder")
        self._open_dir_btn.setObjectName("file_button")
        self._open_dir_btn.setEnabled(False)
        self._open_dir_btn.clicked.connect(self._open_output_dir)
        hdr.addWidget(self._open_dir_btn)

        self._refresh_btn = QPushButton("↻")
        self._refresh_btn.setObjectName("file_button")
        self._refresh_btn.setFixedWidth(36)
        self._refresh_btn.setEnabled(False)
        self._refresh_btn.clicked.connect(self._refresh)
        hdr.addWidget(self._refresh_btn)
        lay.addLayout(hdr)

        # Splitter: file tree | preview
        splitter = QSplitter(Qt.Orientation.Horizontal)

        # Left: file tree
        self._tree = QTreeWidget()
        self._tree.setHeaderLabels(["File", "Size", "Type"])
        self._tree.setColumnWidth(0, 240)
        self._tree.setColumnWidth(1, 70)
        self._tree.setColumnWidth(2, 80)
        self._tree.itemClicked.connect(self._on_item_clicked)
        self._tree.itemDoubleClicked.connect(self._on_item_dbl_clicked)
        splitter.addWidget(self._tree)

        # Right: preview + open button
        right = QWidget()
        right_lay = QVBoxLayout(right)
        right_lay.setContentsMargins(0, 0, 0, 0)
        right_lay.setSpacing(8)

        preview_hdr = QHBoxLayout()
        self._preview_lbl = QLabel("Select a file to preview")
        self._preview_lbl.setStyleSheet("color:#4b5563;font-size:11px;")
        preview_hdr.addWidget(self._preview_lbl)
        preview_hdr.addStretch()
        self._open_file_btn = QPushButton("Open ↗")
        self._open_file_btn.setObjectName("open_button")
        self._open_file_btn.setEnabled(False)
        self._open_file_btn.clicked.connect(self._open_selected_file)
        preview_hdr.addWidget(self._open_file_btn)
        right_lay.addLayout(preview_hdr)

        self._preview = QPlainTextEdit()
        self._preview.setReadOnly(True)
        self._preview.setFont(QFont("Cascadia Code,Fira Code,Courier New", 10))
        self._preview.setPlaceholderText(
            "Double-click a file to open it in your system viewer.\n"
            "Text files (.csv, .xml, .html) are previewed here.")
        right_lay.addWidget(self._preview)
        splitter.addWidget(right)

        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 2)
        lay.addWidget(splitter, stretch=1)

        # MIMODH XML highlight banner (hidden until completed)
        self._mimodh_banner = QLabel(
            "✅  MIMODH XML record generated: mimodh_record.xml  "
            "(Schema: mimodh_v1.xsd — Tier 2 FAIR-compliant)")
        self._mimodh_banner.setStyleSheet("""
            background: #0d1f14; color: #6ee7b7; border: 1px solid #1e8449;
            border-radius: 8px; padding: 8px 14px; font-size: 12px;
        """)
        self._mimodh_banner.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._mimodh_banner.hide()
        lay.addWidget(self._mimodh_banner)

    # ── Public API ────────────────────────────────────────────────────────────
    def load_results(self, output_dir: str):
        self._output_dir = Path(output_dir)
        self._dir_lbl.setText(str(self._output_dir))
        self._open_dir_btn.setEnabled(True)
        self._refresh_btn.setEnabled(True)
        self._refresh()

        # Show MIMODH banner if XML exists
        xml_path = self._output_dir / "mimodh_record.xml"
        self._mimodh_banner.setVisible(xml_path.exists())

    def _refresh(self):
        if not self._output_dir or not self._output_dir.exists():
            return
        self._tree.clear()

        # Group files by type
        groups = {
            "📋 MIMODH Record":    ["mimodh_record.xml"],
            "📊 Analysis Tables":  ["differential_analysis.csv","pathway_activity_scores.csv","reactome_mapping.csv"],
            "🖼️ Figures":          ["network_overview.png","network_de_overlay.png","network_pas_overlay.png","analysis_results.png","degree_distribution.png"],
            "🌐 HTML Reports":     ["interactive_network.html","validation_report.html"],
            "🔧 Cache / Other":    [],
        }
        grouped = set()
        for group_name, fnames in groups.items():
            items_in_group = []
            for fname in fnames:
                fpath = self._output_dir / fname
                if fpath.exists():
                    items_in_group.append((fname, fpath))
                    grouped.add(fname)
            if items_in_group:
                parent = QTreeWidgetItem(self._tree, [group_name, "", ""])
                parent.setExpanded(True)
                for fname, fpath in items_in_group:
                    self._add_file_item(parent, fname, fpath)

        # Remaining files
        other_items = []
        for fpath in sorted(self._output_dir.iterdir()):
            if fpath.name not in grouped and not fpath.name.startswith("."):
                other_items.append(fpath)
        if other_items:
            other_grp = QTreeWidgetItem(self._tree, ["🔧 Cache / Other", "", ""])
            other_grp.setExpanded(False)
            for fpath in other_items:
                self._add_file_item(other_grp, fpath.name, fpath)

    def _add_file_item(self, parent: QTreeWidgetItem, name: str, path: Path):
        icon  = RESULT_ICONS.get(path.suffix.lower(), "📄")
        size  = self._fmt_size(path.stat().st_size) if path.exists() else "?"
        ftype = path.suffix.upper().lstrip(".") or "DIR"

        item = QTreeWidgetItem(parent, [f"{icon} {name}", size, ftype])
        item.setData(0, Qt.ItemDataRole.UserRole, str(path))

        if name in HIGHLIGHT_FILES:
            for col in range(3):
                item.setForeground(col, QColor("#6ee7b7"))

    # ── Events ────────────────────────────────────────────────────────────────
    def _on_item_clicked(self, item: QTreeWidgetItem, col: int):
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if not path_str:
            return
        path = Path(path_str)
        self._preview_lbl.setText(path.name)
        self._open_file_btn.setEnabled(True)
        self._open_file_btn.setProperty("_fpath", path_str)

        # Preview text files
        if path.suffix.lower() in (".csv", ".xml", ".html", ".txt", ".json", ".log"):
            try:
                text = path.read_text(errors="replace")
                self._preview.setPlainText(text[:15000] +
                    ("\n\n... [truncated — open file for full content]" if len(text) > 15000 else ""))
            except Exception as e:
                self._preview.setPlainText(f"Cannot preview: {e}")
        else:
            self._preview.setPlainText(
                f"Binary / image file: {path.name}\n\nDouble-click or press 'Open ↗' to open in system viewer.")

    def _on_item_dbl_clicked(self, item: QTreeWidgetItem, _col: int):
        path_str = item.data(0, Qt.ItemDataRole.UserRole)
        if path_str:
            self._open_with_system(path_str)

    def _open_selected_file(self):
        path_str = self._open_file_btn.property("_fpath")
        if path_str:
            self._open_with_system(path_str)

    def _open_output_dir(self):
        if self._output_dir:
            self._open_with_system(str(self._output_dir))

    @staticmethod
    def _open_with_system(path: str):
        if sys.platform == "win32":
            os.startfile(path)
        elif sys.platform == "darwin":
            subprocess.Popen(["open", path])
        else:
            subprocess.Popen(["xdg-open", path])

    @staticmethod
    def _fmt_size(n: int) -> str:
        for unit in ("B", "KB", "MB", "GB"):
            if n < 1024:
                return f"{n:.0f} {unit}"
            n /= 1024
        return f"{n:.1f} GB"
