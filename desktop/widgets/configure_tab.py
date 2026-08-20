"""
configure_tab.py — Configuration panel for the desktop app.
Covers mode selection, file pickers, MIMODH tier, and synthetic parameters.
"""
from __future__ import annotations
from pathlib import Path
from typing import Dict, Any

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QGroupBox,
    QLabel, QLineEdit, QPushButton, QComboBox, QSpinBox,
    QRadioButton, QButtonGroup, QFileDialog, QScrollArea, QFrame
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QFont

# Test data bundled with the app
def _get_test_data_dir():
    """Resolve bundled test-data folder for script and frozen .exe."""
    import sys as _sys
    if getattr(_sys, "frozen", False):
        return Path(_sys._MEIPASS) / "desktop" / "test_data"
    return Path(__file__).parent.parent / "test_data"


TEST_DATA_DIR = _get_test_data_dir()

# Integration back-ends. Availability is probed at runtime; unavailable methods
# are shown greyed out with the reason, never silently hidden.
INTEGRATION_METHODS = [
    ("nmf",    "NMF",    "Non-negative Matrix Factorisation - default, no extra dependency"),
    ("mofa",   "MOFA+",  "Argelaguet et al. 2020 - requires mofapy2"),
    ("snf",    "SNF",    "Similarity Network Fusion, Wang et al. 2014 - built in"),
    ("mcia",   "MCIA",   "Multiple Co-Inertia Analysis, Meng et al. 2014 - built in"),
    ("diablo", "DIABLO", "Supervised block sPLS-DA - requires R, mixOmics, rpy2"),
]


def _probe_integration_methods():
    """Ask the backend which back-ends are usable here. Never raises."""
    try:
        import sys as _sys
        from pathlib import Path as _P
        if getattr(_sys, "frozen", False):
            root = _P(_sys._MEIPASS)
        else:
            root = _P(__file__).parent.parent.parent
        if str(root) not in _sys.path:
            _sys.path.insert(0, str(root))
        from backend.integration import method_status
        return method_status()
    except Exception:
        # Backend not importable (e.g. during isolated widget tests):
        # assume the dependency-free back-ends work.
        return {k: {"available": k in ("nmf", "snf", "mcia"),
                    "reason": None if k in ("nmf", "snf", "mcia")
                              else "availability could not be determined",
                    "supervised": k == "diablo"}
                for k, _, _ in INTEGRATION_METHODS}


MODALITIES = [
    ("transcriptomics", "🧬 Transcriptomics",   "CSV/TSV/Parquet — samples × genes"),
    ("proteomics",      "🔬 Proteomics",         "CSV/TSV/Parquet — samples × proteins"),
    ("metabolomics",    "⚗️  Metabolomics",        "CSV/TSV/Parquet — samples × metabolites"),
    ("genomics",        "🧫 Genomics (SNP)",      "CSV/TSV/Parquet — samples × variants"),
    ("sc_rna",          "🔭 scRNA-seq",           ".h5ad | 10x MEX directory | CSV"),
    ("sc_atac",         "🏔️  scATAC-seq",          ".h5ad | 10x MEX directory"),
    ("spatial",         "🗺️  Spatial (Visium)",     ".h5ad | 10x Visium directory"),
    ("metadata",        "📋 Metadata",             "CSV/Excel — must have 'condition','batch'"),
]

TIERS = [
    ("Tier1", "#e2a63c", "Tier 1 — Minimum",    "sample_id · condition · batch · modality"),
    ("Tier2", "#3c8de2", "Tier 2 — Recommended", "+ age · sex · BMI · platform · tissue_type"),
    ("Tier3", "#3ce28a", "Tier 3 — Full FAIR",   "+ treatment · survival · genome · ethics"),
]


class ConfigureTab(QWidget):
    """Emits config_changed(dict) whenever any field changes."""
    config_changed = pyqtSignal(dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._file_edits: Dict[str, QLineEdit] = {}
        self._build_ui()
        self._connect_signals()

    # ── Build UI ─────────────────────────────────────────────────────────────
    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(16, 16, 16, 16)
        root.setSpacing(12)

        # Scrollable content
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        layout = QVBoxLayout(inner)
        layout.setContentsMargins(0, 0, 8, 0)
        layout.setSpacing(14)

        layout.addWidget(self._build_mode_group())
        layout.addWidget(self._build_files_group())
        layout.addWidget(self._build_mimodh_group())
        layout.addWidget(self._build_synthetic_group())
        layout.addStretch()

        scroll.setWidget(inner)
        root.addWidget(scroll)

    # ── Mode selection ────────────────────────────────────────────────────────
    def _build_mode_group(self) -> QGroupBox:
        grp = QGroupBox("1 · Operating Mode")
        lay = QHBoxLayout(grp)
        lay.setSpacing(10)

        self._mode_group = QButtonGroup(self)
        for val, lbl, icon in [
            ("synthetic", "🔬  Synthetic",   "Use internally generated test data"),
            ("real",      "📂  Real Data",    "Load your own omics files"),
            ("mixed",     "🔀  Mixed",        "Real files + synthetic fallback"),
        ]:
            rb = QRadioButton(f"{lbl}\n{icon}")
            rb.setProperty("mode_val", val)
            rb.setStyleSheet("""
                QRadioButton {
                    background: #1f2937; border: 1px solid #374151;
                    border-radius: 8px; padding: 10px 14px;
                    font-size: 12px; color: #9ca3af; min-width: 140px;
                }
                QRadioButton:checked {
                    background: #1e3a5f; border-color: #3b82f6; color: #93c5fd;
                }
                QRadioButton::indicator { width: 0; height: 0; }
            """)
            rb.setChecked(val == "synthetic")
            self._mode_group.addButton(rb)
            lay.addWidget(rb)

        # Quick-load test data button
        self._load_test_btn = QPushButton("📦  Load Bundled Test Data")
        self._load_test_btn.setObjectName("file_button")
        self._load_test_btn.setToolTip("Auto-fill all paths with the bundled test CSV files")
        self._load_test_btn.clicked.connect(self._load_test_data)
        lay.addWidget(self._load_test_btn)
        lay.addStretch()
        return grp

    # ── File pickers ──────────────────────────────────────────────────────────
    def _build_files_group(self) -> QGroupBox:
        grp = QGroupBox("2 · Data Files  (Real / Mixed mode)")
        grid = QGridLayout(grp)
        grid.setSpacing(8)
        grid.setColumnStretch(1, 1)

        for row, (key, label, hint) in enumerate(MODALITIES):
            lbl = QLabel(label)
            lbl.setMinimumWidth(160)
            edit = QLineEdit()
            edit.setPlaceholderText(hint)
            edit.setObjectName(key)
            btn = QPushButton("Browse…")
            btn.setObjectName("file_button")
            btn.setFixedWidth(80)
            btn.clicked.connect(lambda _, k=key, e=edit: self._browse(k, e))

            self._file_edits[key] = edit
            grid.addWidget(lbl,  row, 0)
            grid.addWidget(edit, row, 1)
            grid.addWidget(btn,  row, 2)

        return grp

    # ── MIMODH settings ───────────────────────────────────────────────────────
    def _build_mimodh_group(self) -> QGroupBox:
        grp = QGroupBox("3 · MIMODH Compliance")
        vlay = QVBoxLayout(grp)
        vlay.setSpacing(10)

        # Tier selector
        tier_row = QHBoxLayout()
        tier_row.setSpacing(8)
        self._tier_group = QButtonGroup(self)
        for val, color, name, desc in TIERS:
            btn = QRadioButton(f"{name}\n{desc}")
            btn.setProperty("tier_val", val)
            btn.setStyleSheet(f"""
                QRadioButton {{
                    background: #111827; border: 1px solid #374151;
                    border-radius: 8px; padding: 10px; font-size: 11px;
                    color: #9ca3af; min-width: 180px;
                }}
                QRadioButton:checked {{
                    border-color: {color}; color: {color}; background: #0d1117;
                }}
                QRadioButton::indicator {{ width: 0; height: 0; }}
            """)
            btn.setChecked(val == "Tier2")
            self._tier_group.addButton(btn)
            tier_row.addWidget(btn)
        vlay.addLayout(tier_row)

        # Integration back-end selector
        status = _probe_integration_methods()
        method_row = QHBoxLayout()
        method_row.setSpacing(8)
        m_lbl = QLabel("Integration method")
        m_lbl.setStyleSheet("color:#9ca3af; font-size:11px;")
        method_row.addWidget(m_lbl)

        self._method_combo = QComboBox()
        self._method_combo.setMinimumWidth(320)
        first_enabled = None
        for key, name, desc in INTEGRATION_METHODS:
            st = status.get(key, {})
            ok = bool(st.get("available"))
            label = f"{name}  -  {desc}" if ok else f"{name}  (unavailable)  -  {desc}"
            self._method_combo.addItem(label, key)
            idx = self._method_combo.count() - 1
            if not ok:
                # Keep it visible but not selectable, and show why on hover.
                self._method_combo.model().item(idx).setEnabled(False)
                reason = st.get("reason") or "optional dependency not installed"
                self._method_combo.setItemData(idx, reason, Qt.ItemDataRole.ToolTipRole)
            elif first_enabled is None:
                first_enabled = idx
        # Default to NMF when it is available, else the first usable back-end.
        nmf_idx = self._method_combo.findData("nmf")
        self._method_combo.setCurrentIndex(
            nmf_idx if nmf_idx >= 0 and status.get("nmf", {}).get("available")
            else (first_enabled or 0))
        method_row.addWidget(self._method_combo, stretch=1)
        vlay.addLayout(method_row)

        self._method_hint = QLabel(
            "Harmonisation is identical for every method; only the integration "
            "step changes. Greyed-out methods need an optional dependency.")
        self._method_hint.setWordWrap(True)
        self._method_hint.setStyleSheet("color:#6b7280; font-size:10px;")
        vlay.addWidget(self._method_hint)

        # Metadata fields
        grid = QGridLayout()
        grid.setSpacing(8)
        fields = [
            ("disease",     "Disease / Phenotype",   "pan-cancer",           0, 0),
            ("data_repo",   "Data Repository",       "GEO / TCGA / local",   0, 2),
            ("pi",          "Principal Investigator","Optional — Tier 2+",   1, 0),
            ("accession",   "Accession ID",          "e.g. GSE199515",       1, 2),
            ("institution", "Institution",           "Optional — Tier 2+",   2, 0),
            ("ethics",      "Ethics Approval",       "IRB ref — Tier 3",     2, 2),
            ("study_id",    "Study ID",              "Auto-generated if blank",3, 0),
        ]
        self._meta_edits: Dict[str, QLineEdit] = {}
        for name, label, ph, row, col in fields:
            lbl = QLabel(label)
            edit = QLineEdit()
            edit.setPlaceholderText(ph)
            self._meta_edits[name] = edit
            grid.addWidget(lbl,  row, col)
            grid.addWidget(edit, row, col+1)
        vlay.addLayout(grid)
        return grp

    # ── Synthetic parameters ──────────────────────────────────────────────────
    def _build_synthetic_group(self) -> QGroupBox:
        grp = QGroupBox("4 · Synthetic Parameters  (Synthetic / Mixed mode)")
        grid = QGridLayout(grp)
        grid.setSpacing(10)

        params = [
            ("n_samples",  "Samples",      120,  10,  5000),
            ("n_cells",    "Cells",        400,  100, 200000),
            ("n_batches",  "Batches",        3,    2,  20),
            ("n_perm",     "GSEA Perms",   200,   50, 1000),
        ]
        self._spin: Dict[str, QSpinBox] = {}
        for col, (key, label, default, mn, mx) in enumerate(params):
            lbl = QLabel(label)
            sp  = QSpinBox()
            sp.setRange(mn, mx)
            sp.setValue(default)
            sp.setSingleStep(max(1, default // 10))
            self._spin[key] = sp
            grid.addWidget(lbl, 0, col)
            grid.addWidget(sp,  1, col)

        # Output directory
        grid.addWidget(QLabel("Output Directory"), 2, 0)
        self._out_edit = QLineEdit("multiomics_reactome_output")
        self._out_btn  = QPushButton("Browse…")
        self._out_btn.setObjectName("file_button")
        self._out_btn.setFixedWidth(80)
        self._out_btn.clicked.connect(self._browse_outdir)
        grid.addWidget(self._out_edit, 2, 1, 1, 2)
        grid.addWidget(self._out_btn,  2, 3)
        return grp

    # ── Signal connections ────────────────────────────────────────────────────
    def _connect_signals(self):
        for rb in self._mode_group.buttons():
            rb.toggled.connect(lambda _: self.config_changed.emit(self.get_config()))
        for rb in self._tier_group.buttons():
            rb.toggled.connect(lambda _: self.config_changed.emit(self.get_config()))
        for edit in list(self._file_edits.values()) + list(self._meta_edits.values()):
            edit.textChanged.connect(lambda _: self.config_changed.emit(self.get_config()))
        for sp in self._spin.values():
            sp.valueChanged.connect(lambda _: self.config_changed.emit(self.get_config()))
        self._out_edit.textChanged.connect(lambda _: self.config_changed.emit(self.get_config()))
        self._method_combo.currentIndexChanged.connect(
            lambda _: self.config_changed.emit(self.get_config()))

    # ── File browse helpers ───────────────────────────────────────────────────
    def _browse(self, key: str, edit: QLineEdit):
        is_dir  = key in ("sc_rna", "sc_atac", "spatial")
        if is_dir:
            path = QFileDialog.getExistingDirectory(self, f"Select {key} directory")
        else:
            path, _ = QFileDialog.getOpenFileName(
                self, f"Select {key} file", "",
                "Data files (*.csv *.tsv *.xlsx *.parquet *.h5ad);;All files (*)")
        if path:
            edit.setText(path)

    def _browse_outdir(self):
        path = QFileDialog.getExistingDirectory(self, "Select output directory")
        if path:
            self._out_edit.setText(path)

    def _load_test_data(self):
        """Auto-fill paths with bundled test CSV files."""
        mapping = {
            "transcriptomics": "transcriptomics_test.csv",
            "proteomics":      "proteomics_test.csv",
            "metabolomics":    "metabolomics_test.csv",
            "metadata":        "metadata_test.csv",
        }
        found = 0
        for key, fname in mapping.items():
            fpath = TEST_DATA_DIR / fname
            if fpath.exists():
                self._file_edits[key].setText(str(fpath))
                found += 1

        if found > 0:
            # Switch to 'real' mode
            for rb in self._mode_group.buttons():
                if rb.property("mode_val") == "real":
                    rb.setChecked(True)
            self._meta_edits["disease"].setText("pan-cancer-testdata")
            self._meta_edits["study_id"].setText("TEST-001")
            self.config_changed.emit(self.get_config())

    # ── Public API ────────────────────────────────────────────────────────────
    def get_config(self) -> Dict[str, Any]:
        mode = next(
            (rb.property("mode_val") for rb in self._mode_group.buttons() if rb.isChecked()),
            "synthetic")
        tier = next(
            (rb.property("tier_val") for rb in self._tier_group.buttons() if rb.isChecked()),
            "Tier2")
        cfg: Dict[str, Any] = {
            "mode":        mode,
            "mimodh_tier": tier,
            "integration_method": self._method_combo.currentData() or "nmf",
            "output_dir":  self._out_edit.text().strip() or "multiomics_reactome_output",
            **{k: v.value() for k, v in self._spin.items()},
            **{k: e.text().strip() or None for k, e in self._meta_edits.items()},
            **{k: e.text().strip() or None for k, e in self._file_edits.items()},
        }
        return cfg

    def is_ready(self) -> bool:
        cfg = self.get_config()
        if cfg["mode"] == "synthetic":
            return True
        if cfg["mode"] in ("real", "mixed"):
            return bool(cfg.get("transcriptomics") or cfg.get("sc_rna"))
        return True
