"""about_tab.py — About / help panel."""
from PyQt6.QtWidgets import QWidget, QVBoxLayout, QLabel, QScrollArea, QFrame
from PyQt6.QtCore import Qt

CARDS = [
    ("🧬 MIMODH v1.0",
     "#1e3a5f","#60a5fa",
     "Minimum Information for Multi-Omics Data Harmonization. Tier 1 (minimum recoverable) → Tier 2 (recommended) → Tier 3 (full FAIR). Every run exports a validated mimodh_record.xml.",
     "Agamah et al. 2025 · Frontiers in Genetics"),

    ("7 Omics Modalities",
     "#1e3a2a","#6ee7b7",
     "Genomics · Transcriptomics · Proteomics · Metabolomics · scRNA-seq · scATAC-seq · Spatial (10x Visium). Bulk: CSV/TSV/Parquet. Single-cell: .h5ad / 10x MEX. Spatial: Visium directory.",
     "OmicsValidator: 14 bulk checks + 6 AnnData checks"),

    ("3-Stage Batch Correction",
     "#3a2000","#fb923c",
     "pycombat (bulk: Johnson et al. 2007) → Harmony (scRNA/scATAC: Korsunsky et al. 2019) → Chunked MNN (cross-modal: Haghverdi et al. 2018). iLISI ≥ 2.0 · kBET ≥ 0.70 benchmarked.",
     "All 6 modality–method combinations PASS"),

    ("GPU-Accelerated NMF + WNN",
     "#2a1040","#c084fc",
     "Multiplicative-update NMF: CUDA → MPS → Apple Silicon → CPU fallback. WNN affinity fusion (Hao et al. 2021 / Seurat v4). Analogous to MOFA+ (Argelaguet et al. 2020). Lee & Seung 2001.",
     "8–20× speedup on NVIDIA GPU"),

    ("Reactome Pathway Mapping",
     "#3a1010","#fca5a5",
     "REST API (ContentService v84) maps genes, proteins, and metabolites to Reactome pathways. Multi-layer NetworkX graph. GSEA-preranked (Subramanian et al. 2005) with BH-FDR correction.",
     "Gillespie et al. 2022 · Reactome v84"),

    ("MIMODH XML Export",
     "#1e3a1e","#86efac",
     "Full XSD-validated XML record: study metadata, sample manifest, preprocessing provenance, batch-correction benchmarks, integration details, DE results, PAS, quality report, SHA-256 checksums.",
     "Schema: schemas/mimodh_v1.xsd · Namespace: https://mimodh.org/schema/v1"),
]

REFS = [
    ("Agamah et al. 2025",          "MIMODH framework",                   "Frontiers in Genetics"),
    ("Johnson et al. 2007",         "pycombat / ComBat",                  "Biostatistics 8:118"),
    ("Korsunsky et al. 2019",       "Harmony",                            "Nat. Methods 16:1289"),
    ("Haghverdi et al. 2018",       "MNN",                                "Nat. Biotechnol. 36:421"),
    ("Lee & Seung 2001",            "NMF update rules",                   "NeurIPS"),
    ("Hao et al. 2021",             "WNN / Seurat v4",                    "Cell 184:3573"),
    ("Argelaguet et al. 2020",      "MOFA+",                              "Nat. Biotechnol. 38:1251"),
    ("Subramanian et al. 2005",     "GSEA-preranked",                     "PNAS 102:15545"),
    ("Gillespie et al. 2022",       "Reactome v84",                       "NAR 50:D687"),
    ("Büttner et al. 2019",         "kBET",                               "Nat. Methods 16:43"),
    ("Benjamini & Hochberg 1995",   "BH-FDR",                             "J. R. Stat. Soc."),
]


class AboutTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._build_ui()

    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(16, 16, 16, 16)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setSpacing(12)
        lay.setContentsMargins(0, 0, 8, 0)

        # Title
        title = QLabel("MultiOmics-Reactome v3.0")
        title.setObjectName("title_label")
        sub   = QLabel("MIMODH-Compliant Multi-Omics Harmonization Pipeline  ·  Desktop Edition")
        sub.setObjectName("subtitle_label")
        lay.addWidget(title)
        lay.addWidget(sub)

        sep = QFrame(); sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#1f2937;"); lay.addWidget(sep)

        # Feature cards
        for title_txt, bg, col, desc, ref in CARDS:
            card = QLabel()
            card.setWordWrap(True)
            card.setText(
                f"<span style='color:{col};font-weight:bold;font-size:13px'>{title_txt}</span><br>"
                f"<span style='color:#9ca3af;font-size:12px'>{desc}</span><br>"
                f"<span style='color:{col};font-size:10px;opacity:0.7'>{ref}</span>"
            )
            card.setStyleSheet(
                f"background:{bg};border:1px solid {col}40;border-radius:8px;padding:10px 14px;")
            lay.addWidget(card)

        sep2 = QFrame(); sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet("color:#1f2937;"); lay.addWidget(sep2)

        # References
        ref_hdr = QLabel("References")
        ref_hdr.setObjectName("section_label")
        lay.addWidget(ref_hdr)
        for authors, role, journal in REFS:
            ref_lbl = QLabel(
                f"<span style='color:#60a5fa'>{authors}</span>"
                f"<span style='color:#4b5563'> — </span>"
                f"<span style='color:#9ca3af'>{role}</span>"
                f"<span style='color:#4b5563'> · {journal}</span>")
            lay.addWidget(ref_lbl)

        sep3 = QFrame(); sep3.setFrameShape(QFrame.Shape.HLine)
        sep3.setStyleSheet("color:#1f2937;"); lay.addWidget(sep3)

        repo_lbl = QLabel(
            "Repository: <a href='https://github.com/YOUR_USER/multiomics-reactome-pipeline' "
            "style='color:#60a5fa'>github.com/YOUR_USER/multiomics-reactome-pipeline</a><br>"
            "License: MIT  ·  Pipeline: v3.0.0  ·  MIMODH schema: v1.0")
        repo_lbl.setOpenExternalLinks(True)
        repo_lbl.setStyleSheet("color:#6b7280;font-size:11px;")
        lay.addWidget(repo_lbl)
        lay.addStretch()

        scroll.setWidget(inner)
        outer.addWidget(scroll)
