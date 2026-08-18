"""
styles.py — Dark theme QSS for MultiOmics-Reactome Desktop v3.0
Matches the web UI colour scheme (navy/teal/emerald palette).
"""

DARK_THEME = """
/* ── Global ─────────────────────────────────────────────────────────────── */
QMainWindow, QDialog, QWidget {
    background-color: #0f1117;
    color: #e5e7eb;
    font-family: "Segoe UI", "Inter", "Helvetica Neue", Arial, sans-serif;
    font-size: 13px;
}

/* ── Menu bar ────────────────────────────────────────────────────────────── */
QMenuBar {
    background-color: #1a1f2e;
    color: #e5e7eb;
    border-bottom: 1px solid #2d3748;
    padding: 2px;
}
QMenuBar::item:selected { background-color: #1e3a5f; border-radius: 4px; }
QMenu {
    background-color: #1a1f2e;
    color: #e5e7eb;
    border: 1px solid #2d3748;
    border-radius: 6px;
    padding: 4px;
}
QMenu::item:selected { background-color: #1e3a5f; border-radius: 4px; }

/* ── Tab widget ───────────────────────────────────────────────────────────── */
QTabWidget::pane {
    border: 1px solid #2d3748;
    background-color: #111827;
    border-radius: 8px;
    top: -1px;
}
QTabBar::tab {
    background-color: #1a1f2e;
    color: #9ca3af;
    padding: 10px 20px;
    border: 1px solid #2d3748;
    border-bottom: none;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    min-width: 100px;
    margin-right: 2px;
}
QTabBar::tab:selected {
    background-color: #111827;
    color: #60a5fa;
    border-bottom: 2px solid #3b82f6;
    font-weight: bold;
}
QTabBar::tab:hover:!selected { background-color: #1e293b; color: #93c5fd; }

/* ── GroupBox ─────────────────────────────────────────────────────────────── */
QGroupBox {
    background-color: #111827;
    border: 1px solid #1f2937;
    border-radius: 8px;
    margin-top: 14px;
    padding: 12px;
    font-weight: bold;
    color: #9ca3af;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 1px;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 6px;
    color: #9ca3af;
}

/* ── Labels ──────────────────────────────────────────────────────────────── */
QLabel { color: #e5e7eb; background: transparent; }
QLabel#title_label {
    font-size: 22px;
    font-weight: bold;
    color: #60a5fa;
}
QLabel#subtitle_label { font-size: 13px; color: #9ca3af; }
QLabel#badge_mimodh {
    background-color: #1e3a2a;
    color: #6ee7b7;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: bold;
}
QLabel#badge_version {
    background-color: #1e3a5f;
    color: #93c5fd;
    border-radius: 4px;
    padding: 2px 8px;
    font-size: 11px;
    font-weight: bold;
}
QLabel#section_label {
    font-size: 11px;
    font-weight: bold;
    color: #9ca3af;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* ── Buttons ─────────────────────────────────────────────────────────────── */
QPushButton {
    background-color: #1e3a5f;
    color: #93c5fd;
    border: 1px solid #3b82f6;
    border-radius: 6px;
    padding: 8px 16px;
    font-weight: bold;
    font-size: 13px;
}
QPushButton:hover  { background-color: #1e4976; border-color: #60a5fa; }
QPushButton:pressed { background-color: #1e2d45; }
QPushButton:disabled { background-color: #1f2937; color: #4b5563; border-color: #374151; }

QPushButton#run_button {
    background-color: #1d4ed8;
    color: #ffffff;
    border: 2px solid #3b82f6;
    border-radius: 10px;
    padding: 14px 0;
    font-size: 15px;
    font-weight: bold;
}
QPushButton#run_button:hover  { background-color: #2563eb; }
QPushButton#run_button:disabled { background-color: #1e3a5f; color: #6b7280; }

QPushButton#stop_button {
    background-color: #7f1d1d;
    color: #fca5a5;
    border: 1px solid #ef4444;
}
QPushButton#stop_button:hover { background-color: #991b1b; }

QPushButton#file_button {
    background-color: #1f2937;
    color: #9ca3af;
    border: 1px solid #374151;
    padding: 6px 12px;
    font-size: 12px;
    border-radius: 6px;
    font-weight: normal;
}
QPushButton#file_button:hover { background-color: #273344; border-color: #4b5563; color: #e5e7eb; }

QPushButton#open_button {
    background-color: #0d1f14;
    color: #6ee7b7;
    border: 1px solid #1e8449;
    padding: 6px 12px;
}
QPushButton#open_button:hover { background-color: #12291a; }

/* ── Inputs ──────────────────────────────────────────────────────────────── */
QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background-color: #111827;
    color: #e5e7eb;
    border: 1px solid #374151;
    border-radius: 6px;
    padding: 6px 10px;
    selection-background-color: #1e3a5f;
    font-size: 13px;
}
QLineEdit:focus, QSpinBox:focus, QDoubleSpinBox:focus, QComboBox:focus {
    border-color: #3b82f6;
}
QLineEdit::placeholder { color: #4b5563; }
QSpinBox::up-button, QSpinBox::down-button,
QDoubleSpinBox::up-button, QDoubleSpinBox::down-button {
    background-color: #1f2937;
    border: none;
    width: 18px;
}
QComboBox::drop-down  { border: none; padding-right: 8px; }
QComboBox::down-arrow { color: #60a5fa; }
QComboBox QAbstractItemView {
    background-color: #1a1f2e;
    color: #e5e7eb;
    border: 1px solid #2d3748;
    selection-background-color: #1e3a5f;
}

/* ── Radio / Checkbox ────────────────────────────────────────────────────── */
QRadioButton, QCheckBox { color: #e5e7eb; spacing: 8px; }
QRadioButton::indicator, QCheckBox::indicator {
    width: 16px; height: 16px;
    border: 2px solid #374151;
    border-radius: 3px;
    background-color: #111827;
}
QRadioButton::indicator { border-radius: 8px; }
QRadioButton::indicator:checked, QCheckBox::indicator:checked {
    background-color: #3b82f6;
    border-color: #3b82f6;
}

/* ── Progress bar ────────────────────────────────────────────────────────── */
QProgressBar {
    background-color: #1f2937;
    border: 1px solid #374151;
    border-radius: 6px;
    height: 14px;
    text-align: center;
    color: #e5e7eb;
    font-size: 11px;
}
QProgressBar::chunk {
    background: qlineargradient(x1:0,y1:0,x2:1,y2:0,
        stop:0 #1d4ed8, stop:1 #10b981);
    border-radius: 5px;
}

/* ── Text / Log area ─────────────────────────────────────────────────────── */
QPlainTextEdit, QTextEdit {
    background-color: #0a0e1a;
    color: #a0aec0;
    border: 1px solid #1f2937;
    border-radius: 6px;
    font-family: "Cascadia Code", "Fira Code", "Courier New", monospace;
    font-size: 12px;
    padding: 8px;
    selection-background-color: #1e3a5f;
}

/* ── Tree / List ─────────────────────────────────────────────────────────── */
QTreeWidget, QListWidget {
    background-color: #111827;
    color: #e5e7eb;
    border: 1px solid #1f2937;
    border-radius: 6px;
    font-size: 12px;
}
QTreeWidget::item, QListWidget::item { padding: 4px 8px; }
QTreeWidget::item:selected, QListWidget::item:selected {
    background-color: #1e3a5f;
    color: #93c5fd;
}
QTreeWidget::item:hover, QListWidget::item:hover {
    background-color: #1f2937;
}
QHeaderView::section {
    background-color: #1a1f2e;
    color: #9ca3af;
    border: 1px solid #2d3748;
    padding: 6px 8px;
    font-size: 11px;
    font-weight: bold;
    text-transform: uppercase;
    letter-spacing: 1px;
}

/* ── Splitter ────────────────────────────────────────────────────────────── */
QSplitter::handle {
    background-color: #2d3748;
    width: 2px; height: 2px;
}

/* ── Scroll bars ─────────────────────────────────────────────────────────── */
QScrollBar:vertical, QScrollBar:horizontal {
    background-color: #111827;
    width: 8px; height: 8px;
    border-radius: 4px;
}
QScrollBar::handle:vertical, QScrollBar::handle:horizontal {
    background-color: #374151;
    border-radius: 4px;
    min-height: 20px;
}
QScrollBar::handle:hover { background-color: #4b5563; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; width: 0; }

/* ── Status bar ──────────────────────────────────────────────────────────── */
QStatusBar {
    background-color: #1a1f2e;
    color: #6b7280;
    border-top: 1px solid #2d3748;
    font-size: 11px;
    padding: 2px 8px;
}

/* ── Tool tip ────────────────────────────────────────────────────────────── */
QToolTip {
    background-color: #1a1f2e;
    color: #e5e7eb;
    border: 1px solid #2d3748;
    border-radius: 4px;
    padding: 4px 8px;
    font-size: 12px;
}

/* ── Slider ──────────────────────────────────────────────────────────────── */
QSlider::groove:horizontal {
    background: #1f2937;
    height: 4px;
    border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #3b82f6;
    width: 14px; height: 14px;
    margin: -5px 0;
    border-radius: 7px;
}
QSlider::sub-page:horizontal { background: #3b82f6; border-radius: 2px; }
"""

# Status colour helpers
STATUS_COLORS = {
    "IDLE":      "#6b7280",
    "RUNNING":   "#3b82f6",
    "COMPLETED": "#10b981",
    "FAILED":    "#ef4444",
    "QUEUED":    "#f59e0b",
}

LOG_COLORS = {
    "INFO":    "#60a5fa",
    "WARNING": "#fbbf24",
    "ERROR":   "#f87171",
    "SUCCESS": "#34d399",
    "SECTION": "#c084fc",
    "MIMODH":  "#6ee7b7",
}
