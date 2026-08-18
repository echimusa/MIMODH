"""
Multi-Omics Integration Pipeline  ·  Reactome Network Edition  v3
=================================================================
MODE A — Synthetic  : generates realistic test data internally
MODE B — Real Input : loads user-supplied files for all modalities

Supported input formats
-----------------------
  Bulk omics (genomics / transcriptomics / proteomics / metabolomics)
      CSV / TSV / Excel / Parquet  — rows = samples, columns = features
  Single-cell (scRNA-seq, scATAC-seq)
      AnnData  .h5ad  |  10x MEX directory  |  CSV/TSV count matrix
  Spatial omics
      AnnData  .h5ad  |  10x Visium directory (filtered_feature_bc_matrix +
      spatial/ folder)
  Metadata (clinical / phenotype / lifestyle / demographic)
      CSV / TSV / Excel

Validation & standardisation
-----------------------------
  • Schema enforcement (required columns / index type)
  • Dtype coercion and range checks
  • Missing-value audit and imputation strategy selection
  • Duplicate sample / feature detection
  • Distribution diagnostics (skew, kurtosis, zero-inflation)
  • Cross-modality sample-ID reconciliation
  • Feature-name normalisation (gene symbols → HGNC, UniProt trimming,
    ChEBI prefix enforcement)
  • Batch-label cardinality and minimum-cell-count checks
  • Full HTML validation report saved to output directory
"""

from __future__ import annotations

import argparse
import json
import logging
import math
import os
import re
import time
import warnings
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
import matplotlib.patches as mpatches
import networkx as nx
import numpy as np
import pandas as pd
import requests
import seaborn as sns
from matplotlib.gridspec import GridSpec
from scipy import sparse, stats
from scipy.stats import ttest_ind
from sklearn.decomposition import TruncatedSVD
from sklearn.neighbors import NearestNeighbors
from sklearn.preprocessing import LabelEncoder, StandardScaler
from sklearn.utils.extmath import randomized_svd
from statsmodels.stats.multitest import multipletests
from joblib import Parallel, delayed
from tqdm.auto import tqdm

import anndata as ad
import scanpy as sc
import harmonypy as hm

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)

# ── optional dependencies ─────────────────────────────────────────────────────
try:
    from inmoose.pycombat import pycombat_norm
    PYCOMBAT = True
except ImportError:
    PYCOMBAT = False

try:
    import torch
    TORCH  = True
    DEVICE = ("cuda" if torch.cuda.is_available()
               else "mps" if torch.backends.mps.is_available() else "cpu")
except ImportError:
    TORCH  = False
    DEVICE = "cpu"

OUTPUT_DIR = Path("multiomics_reactome_output")
OUTPUT_DIR.mkdir(exist_ok=True)

REACTOME_BASE = "https://reactome.org/ContentService"

plt.rcParams.update({
    "figure.dpi": 150, "font.size": 9,
    "axes.spines.top": False, "axes.spines.right": False,
})

ENTITY_COLORS = {
    "gene": "#4e79a7", "protein": "#f28e2b",
    "metabolite": "#59a14f", "pathway": "#e15759",
}

# Real symbols reused across synthetic + validation
GENE_SYMBOLS = [
    "TP53","EGFR","BRCA1","BRCA2","KRAS","MYC","VEGFA","AKT1","MTOR","PIK3CA",
    "PTEN","CDK2","CDK4","CCND1","RB1","CDKN2A","MDM2","BCL2","BAX","CASP3",
    "CASP9","ATM","CHEK1","CHEK2","RAD51","PALB2","NBN","MRE11","RAD50","H2AFX",
    "IDH1","IDH2","VHL","HIF1A","ERBB2","FGFR1","MET","ALK","BRAF","RAF1",
    "MAP2K1","MAPK1","MAPK3","HRAS","NRAS","JAK1","JAK2","STAT3","IL6","TNF",
    "TGFB1","SMAD2","SMAD3","SMAD4","WNT3A","CTNNB1","APC","NOTCH1","HES1",
    "SHH","GLI1","E2F1","HDAC1","DNMT1","EZH2","SIRT1","AMPK","TSC1","TSC2",
]
PROTEIN_SYMS = [
    "P04637","P00533","P38398","P51587","P01116","P01106","P15692","P31749",
    "P42345","P42336","P60484","P24941","P11802","P24385","P06400","P42771",
    "Q00987","P10415","Q07812","P42574","P55211","P10606","Q9UKV3","Q13315",
]
CHEBI_IDS = [
    "CHEBI:15422","CHEBI:16761","CHEBI:17634","CHEBI:16015","CHEBI:16947",
    "CHEBI:30031","CHEBI:16810","CHEBI:15361","CHEBI:16908","CHEBI:57692",
    "CHEBI:15846","CHEBI:17627","CHEBI:15351","CHEBI:16240","CHEBI:25703",
    "CHEBI:17855","CHEBI:15843","CHEBI:18012","CHEBI:30616","CHEBI:15351",
]


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 1 — VALIDATION FRAMEWORK
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class ValidationIssue:
    level:    str   # "error" | "warning" | "info"
    modality: str
    check:    str
    message:  str
    detail:   str = ""

@dataclass
class ValidationReport:
    issues: List[ValidationIssue] = field(default_factory=list)

    def add(self, level, modality, check, message, detail=""):
        self.issues.append(ValidationIssue(level, modality, check, message, detail))

    @property
    def errors(self):   return [i for i in self.issues if i.level == "error"]
    @property
    def warnings(self): return [i for i in self.issues if i.level == "warning"]
    @property
    def passed(self):   return len(self.errors) == 0

    def summary(self) -> str:
        lines = [
            f"{'═'*64}",
            f"  Validation Report  —  {len(self.errors)} errors  "
            f"{len(self.warnings)} warnings  "
            f"{len([i for i in self.issues if i.level=='info'])} info",
            f"{'═'*64}",
        ]
        for lvl, sym in [("error","✗"), ("warning","⚠"), ("info","✓")]:
            items = [i for i in self.issues if i.level == lvl]
            for i in items:
                lines.append(f"  [{sym}] [{i.modality}] {i.check}: {i.message}")
                if i.detail:
                    lines.append(f"       → {i.detail}")
        lines.append(f"{'═'*64}")
        return "\n".join(lines)

    def save_html(self, path: Path):
        COLOR = {"error": "#e63946", "warning": "#f4a261", "info": "#2a9d8f"}
        rows  = "".join(
            f"<tr style='color:{COLOR[i.level]}'>"
            f"<td>{i.level.upper()}</td><td>{i.modality}</td>"
            f"<td>{i.check}</td><td>{i.message}</td>"
            f"<td style='font-size:11px'>{i.detail}</td></tr>"
            for i in self.issues
        )
        html = f"""<!DOCTYPE html><html><head>
        <meta charset='utf-8'>
        <title>Multi-Omics Validation Report</title>
        <style>
          body{{font-family:monospace;background:#0f0f1a;color:#eee;padding:24px}}
          h1{{color:#4e79a7}} table{{border-collapse:collapse;width:100%}}
          th{{background:#1e1e2e;color:#aaa;padding:8px;text-align:left}}
          td{{padding:6px 8px;border-bottom:1px solid #222}}
        </style></head><body>
        <h1>Multi-Omics Validation Report</h1>
        <p>{len(self.errors)} errors &nbsp; {len(self.warnings)} warnings</p>
        <table><tr><th>Level</th><th>Modality</th><th>Check</th>
        <th>Message</th><th>Detail</th></tr>{rows}</table>
        </body></html>"""
        path.write_text(html)
        log.info(f"  Saved validation report: {path.name}")


class OmicsValidator:
    """
    Validates and standardises each data modality.
    All checks are non-destructive; corrected copies are returned.
    """

    # ── dtype / range specs per modality ──────────────────────────────────────
    MODALITY_SPECS = {
        "genomics": dict(
            expected_dtypes=["float32","float64","int32","int64"],
            value_range=(0, 10),
            zero_inflation_warn=0.9,
            skew_warn=5.0,
        ),
        "transcriptomics": dict(
            expected_dtypes=["float32","float64","int32","int64"],
            value_range=(0, None),
            zero_inflation_warn=0.7,
            skew_warn=10.0,
        ),
        "proteomics": dict(
            expected_dtypes=["float32","float64"],
            value_range=(0, None),
            zero_inflation_warn=0.5,
            skew_warn=8.0,
        ),
        "metabolomics": dict(
            expected_dtypes=["float32","float64"],
            value_range=(0, None),
            zero_inflation_warn=0.5,
            skew_warn=8.0,
        ),
    }

    METADATA_REQUIRED = ["condition", "batch"]
    METADATA_CONDITION_VALUES = {"Case", "Control", "case", "control",
                                  "disease", "healthy", "tumor", "normal"}

    def __init__(self, report: ValidationReport):
        self.report = report

    # ── helpers ───────────────────────────────────────────────────────────────

    def _r(self, *a, **kw): self.report.add(*a, **kw)

    @staticmethod
    def _coerce_numeric(df: pd.DataFrame) -> pd.DataFrame:
        return df.apply(pd.to_numeric, errors="coerce")

    @staticmethod
    def _normalise_index(df: pd.DataFrame) -> pd.DataFrame:
        df.index = df.index.astype(str).str.strip()
        return df

    # ── bulk omics checks ─────────────────────────────────────────────────────

    def validate_bulk(self, name: str, df: pd.DataFrame) -> pd.DataFrame:
        mod = name
        spec = self.MODALITY_SPECS.get(name, {})

        # 1. Index type
        df = self._normalise_index(df)

        # 2. Numeric coercion
        non_num = df.select_dtypes(exclude="number").columns.tolist()
        if non_num:
            self._r("warning", mod, "dtype",
                    f"{len(non_num)} non-numeric columns coerced",
                    f"Columns: {non_num[:5]}")
            df = self._coerce_numeric(df)

        # 3. Shape
        if df.shape[0] < 5:
            self._r("error", mod, "shape",
                    f"Too few samples ({df.shape[0]}); minimum 5 required.")
        else:
            self._r("info", mod, "shape",
                    f"{df.shape[0]} samples × {df.shape[1]} features")

        # 4. Duplicated sample IDs
        dup_idx = df.index[df.index.duplicated()].tolist()
        if dup_idx:
            self._r("error", mod, "duplicates",
                    f"{len(dup_idx)} duplicate sample IDs",
                    f"IDs: {dup_idx[:5]}")
            df = df[~df.index.duplicated(keep="first")]

        # 5. Duplicated feature names
        dup_feat = df.columns[df.columns.duplicated()].tolist()
        if dup_feat:
            self._r("warning", mod, "duplicates",
                    f"{len(dup_feat)} duplicate feature names removed",
                    f"Features: {dup_feat[:5]}")
            df = df.loc[:, ~df.columns.duplicated(keep="first")]

        # 6. Missing values
        miss_pct = df.isna().mean().mean()
        if miss_pct > 0.3:
            self._r("error", mod, "missing",
                    f"{miss_pct:.1%} values missing — exceeds 30% threshold")
        elif miss_pct > 0.05:
            self._r("warning", mod, "missing",
                    f"{miss_pct:.1%} values missing — median imputation applied")
        else:
            self._r("info", mod, "missing", f"{miss_pct:.1%} missing (acceptable)")
        df = df.fillna(df.median())

        # 7. Value range
        vmin, vmax = spec.get("value_range", (None, None))
        if vmin is not None and (df < vmin).any().any():
            n_neg = int((df < vmin).sum().sum())
            self._r("warning", mod, "range",
                    f"{n_neg} values below minimum ({vmin}) — clipped",
                    "Check for log-transform or normalisation errors.")
            df = df.clip(lower=vmin)

        # 8. Zero inflation
        zi_thresh = spec.get("zero_inflation_warn", 0.9)
        zi = float((df == 0).mean().mean())
        if zi > zi_thresh:
            self._r("warning", mod, "zero_inflation",
                    f"Zero inflation = {zi:.1%} (threshold {zi_thresh:.0%})",
                    "Consider filtering low-coverage features.")
        else:
            self._r("info", mod, "zero_inflation", f"Zero inflation = {zi:.1%}")

        # 9. Distribution (skew)
        skw = float(df.apply(lambda c: c.skew()).mean())
        skw_thresh = spec.get("skew_warn", 5.0)
        if abs(skw) > skw_thresh:
            self._r("warning", mod, "distribution",
                    f"Mean skew = {skw:.2f} — log-normalisation recommended")
        else:
            self._r("info", mod, "distribution", f"Mean skew = {skw:.2f} (acceptable)")

        # 10. Constant features
        const = (df.std(axis=0) == 0).sum()
        if const > 0:
            self._r("warning", mod, "constant_features",
                    f"{const} constant (zero-variance) features removed")
            df = df.loc[:, df.std(axis=0) > 0]

        # 11. Feature name normalisation
        df = self._normalise_feature_names(name, df)

        return df

    def _normalise_feature_names(self, modality: str, df: pd.DataFrame) -> pd.DataFrame:
        cols = df.columns.tolist()
        if modality == "proteomics":
            # Trim isoform suffixes from UniProt (P12345-2 → P12345)
            new_cols = [re.sub(r"-\d+$", "", c) for c in cols]
            if new_cols != cols:
                self._r("info", modality, "feature_names",
                        f"Trimmed isoform suffixes from {sum(a!=b for a,b in zip(cols,new_cols))} UniProt IDs")
                df.columns = new_cols
        elif modality == "metabolomics":
            # Enforce CHEBI: prefix
            new_cols = [f"CHEBI:{c}" if not c.startswith("CHEBI:") and c.replace(":","").isdigit()
                        else c for c in cols]
            changed = sum(a != b for a, b in zip(cols, new_cols))
            if changed:
                self._r("info", modality, "feature_names",
                        f"Added CHEBI: prefix to {changed} metabolite IDs")
                df.columns = new_cols
        elif modality in ("transcriptomics", "genomics"):
            # Upper-case gene symbols
            new_cols = [c.upper() for c in cols]
            changed = sum(a != b for a, b in zip(cols, new_cols))
            if changed:
                self._r("info", modality, "feature_names",
                        f"Upper-cased {changed} gene symbols")
                df.columns = new_cols
        return df

    # ── AnnData (single-cell / spatial) ───────────────────────────────────────

    def validate_anndata(self, name: str, adata: ad.AnnData) -> ad.AnnData:
        mod = name

        # Shape
        if adata.n_obs < 50:
            self._r("warning", mod, "shape",
                    f"Only {adata.n_obs} cells/spots — results may be unreliable")
        else:
            self._r("info", mod, "shape",
                    f"{adata.n_obs} obs × {adata.n_vars} features")

        # Sparse check
        if not sparse.issparse(adata.X):
            self._r("info", mod, "format", "Converting dense matrix to CSR sparse")
            adata.X = sparse.csr_matrix(adata.X)

        # Negative values
        mn = adata.X.min()
        if mn < 0:
            self._r("error", mod, "range",
                    f"Negative values detected (min={mn:.2f}) — check normalisation")

        # Required obs columns
        for col in ["batch"]:
            if col not in adata.obs.columns:
                self._r("warning", mod, "obs_columns",
                        f"Missing '{col}' in .obs — batch correction will be skipped",
                        "Add a 'batch' column to .obs with batch labels.")

        # Duplicated barcodes
        dup = adata.obs.index[adata.obs.index.duplicated()].tolist()
        if dup:
            self._r("error", mod, "duplicates",
                    f"{len(dup)} duplicate barcodes",
                    f"Examples: {dup[:3]}")

        # Spatial check
        if name == "spatial" and "spatial" not in adata.obsm:
            self._r("warning", mod, "spatial_coords",
                    "No 'spatial' key in .obsm — spatial plots will be unavailable")

        return adata

    # ── metadata ──────────────────────────────────────────────────────────────

    def validate_metadata(self, df: pd.DataFrame) -> pd.DataFrame:
        mod = "metadata"
        df  = self._normalise_index(df)

        # Required columns
        for col in self.METADATA_REQUIRED:
            if col not in df.columns:
                self._r("error", mod, "required_columns",
                        f"Required column '{col}' is missing")

        # Condition values
        if "condition" in df.columns:
            vals = set(df["condition"].astype(str).str.strip().unique())
            unknown = vals - self.METADATA_CONDITION_VALUES
            if unknown:
                self._r("warning", mod, "condition_values",
                        f"Unrecognised condition values: {unknown}",
                        "Expected: Case/Control, disease/healthy, tumor/normal")
            # Standardise to Case/Control
            mapping = {v: ("Case" if v.lower() in {"case","disease","tumor"}
                           else "Control")
                       for v in df["condition"].unique()}
            df["condition"] = df["condition"].map(mapping).fillna(df["condition"])

        # Batch cardinality
        if "batch" in df.columns:
            n_batches = df["batch"].nunique()
            min_per_batch = df["batch"].value_counts().min()
            if n_batches < 2:
                self._r("warning", mod, "batch",
                        "Only 1 batch detected — batch correction has no effect")
            if min_per_batch < 3:
                self._r("warning", mod, "batch",
                        f"Smallest batch has {min_per_batch} samples (<3) — "
                        "consider ComBat non-parametric mode")
            else:
                self._r("info", mod, "batch",
                        f"{n_batches} batches  min_per_batch={min_per_batch}")

        # Numeric columns: range checks
        for col in ["age", "bmi"]:
            if col in df.columns:
                try:
                    s = pd.to_numeric(df[col], errors="coerce")
                    if col == "age"  and (s.dropna() > 120).any():
                        self._r("warning", mod, col, "Age > 120 detected — possible data error")
                    if col == "bmi"  and ((s.dropna() < 10) | (s.dropna() > 80)).any():
                        self._r("warning", mod, col, "BMI outside [10,80] — check units")
                except Exception:
                    pass

        return df

    # ── cross-modality sample reconciliation ─────────────────────────────────

    def reconcile_samples(self, modalities: Dict[str, Any]) -> Dict[str, Any]:
        """
        Find the common sample set across all bulk modalities + metadata.
        Logs which samples are dropped from each modality.
        """
        log.info("  Cross-modality sample reconciliation …")
        bulk_keys = ["transcriptomics","proteomics","metabolomics",
                     "genomics","metadata"]
        indices   = {}
        for k in bulk_keys:
            obj = modalities.get(k)
            if obj is not None:
                if isinstance(obj, pd.DataFrame):
                    indices[k] = set(obj.index.tolist())

        if len(indices) < 2:
            return modalities

        common = set.intersection(*indices.values())
        self.report.add("info","cross_modality","sample_reconciliation",
                        f"Common samples across modalities: {len(common)}",
                        f"Checked: {list(indices.keys())}")

        for k in bulk_keys:
            obj = modalities.get(k)
            if obj is not None and isinstance(obj, pd.DataFrame):
                dropped = len(obj) - len(common.intersection(set(obj.index)))
                if dropped:
                    self.report.add("warning","cross_modality","sample_reconciliation",
                                    f"{dropped} samples dropped from '{k}' (not in common set)")
                modalities[k] = obj.loc[obj.index.isin(common)]

        return modalities


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 2 — DATA LOADERS
# ══════════════════════════════════════════════════════════════════════════════

class DataLoader:
    """Load bulk and single-cell/spatial data from user-supplied files."""

    TABULAR_EXTS = {".csv": ",", ".tsv": "\t", ".txt": "\t"}

    @staticmethod
    def _read_table(path: Path) -> pd.DataFrame:
        ext = path.suffix.lower()
        if ext in (".csv", ".tsv", ".txt"):
            sep = DataLoader.TABULAR_EXTS.get(ext, ",")
            df  = pd.read_csv(path, sep=sep, index_col=0)
        elif ext in (".xlsx", ".xls"):
            df  = pd.read_excel(path, index_col=0)
        elif ext == ".parquet":
            df  = pd.read_parquet(path)
        else:
            raise ValueError(f"Unsupported tabular format: {ext}. "
                             "Use CSV/TSV/Excel/Parquet.")
        return df

    def load_bulk(self, path: Path, modality: str) -> pd.DataFrame:
        log.info(f"  Loading {modality} from {path.name} …")
        df = self._read_table(path)
        log.info(f"    Raw shape: {df.shape}")
        return df

    def load_anndata(self, path: Path, modality: str) -> ad.AnnData:
        log.info(f"  Loading {modality} from {path} …")
        if path.suffix == ".h5ad":
            adata = ad.read_h5ad(path)
        elif path.is_dir():
            # 10x MEX or Visium directory
            try:
                adata = sc.read_10x_mtx(path, var_names="gene_symbols",
                                         cache=False)
                # Try to load spatial coordinates for Visium
                spatial_csv = path / "spatial" / "tissue_positions_list.csv"
                if spatial_csv.exists():
                    coords = pd.read_csv(spatial_csv, header=None,
                                         index_col=0)[[4, 5]]
                    coords.columns = ["x", "y"]
                    coords.index   = coords.index.astype(str)
                    shared = adata.obs.index.intersection(coords.index)
                    adata  = adata[shared].copy()
                    adata.obsm["spatial"] = coords.loc[shared].values.astype(float)
            except Exception as e:
                raise ValueError(f"Could not read 10x directory {path}: {e}")
        elif path.suffix in (".csv", ".tsv", ".txt"):
            df    = self._read_table(path)
            adata = ad.AnnData(X=sparse.csr_matrix(df.values.astype(np.float32)),
                               obs=pd.DataFrame(index=df.index),
                               var=pd.DataFrame(index=df.columns))
        else:
            raise ValueError(f"Unsupported AnnData format: {path.suffix}")
        log.info(f"    Shape: {adata.n_obs} × {adata.n_vars}")
        return adata

    def load_metadata(self, path: Path) -> pd.DataFrame:
        log.info(f"  Loading metadata from {path.name} …")
        df = self._read_table(path)
        log.info(f"    {df.shape[0]} samples × {df.shape[1]} columns")
        return df


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 3 — SYNTHETIC DATA GENERATOR
# ══════════════════════════════════════════════════════════════════════════════

class SyntheticGenerator:
    def __init__(self, n_samples=120, n_cells=400, n_batches=3, seed=42):
        self.n  = n_samples; self.nc = n_cells
        self.nb = n_batches; self.rng = np.random.default_rng(seed)

    def _batch(self, n):
        sz = self.rng.multinomial(n, [1/self.nb]*self.nb)
        return np.repeat(np.arange(self.nb), sz)

    def _inject(self, X, batch, s=1.5):
        X = X.copy().astype(np.float32)
        for b in np.unique(batch):
            m = batch == b
            X[m] += self.rng.normal(0, s, X.shape[1]).astype(np.float32)
            X[m] *= self.rng.lognormal(0,.3,X.shape[1]).astype(np.float32)
        return X

    def generate(self) -> Dict:
        log.info(f"[Synthetic] n_samples={self.n} n_cells={self.nc} n_batches={self.nb}")
        batch = self._batch(self.n)
        idx   = [f"S{i:03d}" for i in range(self.n)]
        cond  = np.array(["Case"]*(self.n//2)+["Control"]*(self.n-self.n//2))
        self.rng.shuffle(cond)
        cm    = cond == "Case"

        ng, np_, nm = len(GENE_SYMBOLS), len(PROTEIN_SYMS), len(CHEBI_IDS)

        mu  = np.abs(self.rng.normal(5,3,(self.n,ng)).astype(np.float32))
        tx  = self.rng.negative_binomial(5,np.clip(5/(5+mu),.01,.99)).astype(np.float32)
        tx[cm,:20] *= 3.0
        tx  = self._inject(tx, batch, 1.5)

        pr  = self.rng.lognormal(10,2,(self.n,np_)).astype(np.float32)
        pr[cm,:8] *= 2.5
        pr  = self._inject(pr, batch, 2.0)

        me  = self.rng.lognormal(8,1.5,(self.n,nm)).astype(np.float32)
        me[cm,:6] *= 2.0
        me  = self._inject(me, batch, 2.5)

        # scRNA
        mu_sc = self.rng.lognormal(1.5,1.2,(self.nc,2000)).astype(np.float32)
        rna_X = self.rng.negative_binomial(
            2,np.clip(2/(2+mu_sc),.01,.99)).astype(np.float32)
        sc_batch = self._batch(self.nc).astype(str)
        rna = ad.AnnData(X=sparse.csr_matrix(rna_X),
                         obs=pd.DataFrame({"batch":sc_batch},
                             index=[f"C{i:05d}" for i in range(self.nc)]),
                         var=pd.DataFrame(index=GENE_SYMBOLS[:2000] if len(GENE_SYMBOLS)>=2000
                                           else [f"G{i}" for i in range(2000)]))

        # scATAC
        atac_X = self.rng.negative_binomial(1,.85,(self.nc,1500)).astype(np.float32)
        atac = ad.AnnData(X=sparse.csr_matrix(atac_X),
                          obs=pd.DataFrame({"batch":sc_batch},
                              index=[f"C{i:05d}" for i in range(self.nc)]),
                          var=pd.DataFrame(index=[f"PEAK_{i}" for i in range(1500)]))

        # Spatial
        n_sp = 300; n_sg = 1000
        sp_X = self.rng.negative_binomial(3,.4,(n_sp,n_sg)).astype(np.float32)
        side = math.ceil(math.sqrt(n_sp))
        grid = np.array([(x,y) for x in range(side) for y in range(side)])[:n_sp]
        spatial = ad.AnnData(X=sparse.csr_matrix(sp_X),
                             obs=pd.DataFrame({
                                 "x":grid[:,0],"y":grid[:,1],
                                 "batch": self.rng.choice(["A","B"],n_sp),
                                 "region":self.rng.choice(["Core","Margin","Normal"],n_sp)},
                                 index=[f"SPOT_{i:04d}" for i in range(n_sp)]),
                             var=pd.DataFrame(index=[f"GENE_{i}" for i in range(n_sg)]))
        spatial.obsm["spatial"] = grid.astype(float)

        meta = pd.DataFrame({
            "condition": cond, "batch": batch,
            "age":  self.rng.integers(20,80,self.n),
            "sex":  self.rng.choice(["M","F"],self.n),
            "bmi":  self.rng.normal(26,4,self.n).round(1),
            "smoking": self.rng.choice(["Never","Former","Current"],self.n),
            "treatment": self.rng.choice(["Chemo","Immuno","None"],self.n),
            "stage": self.rng.choice(["I","II","III","NA"],self.n),
        }, index=idx)

        return dict(
            transcriptomics = pd.DataFrame(tx, index=idx, columns=GENE_SYMBOLS[:ng]),
            proteomics      = pd.DataFrame(pr, index=idx, columns=PROTEIN_SYMS),
            metabolomics    = pd.DataFrame(me, index=idx, columns=CHEBI_IDS),
            sc_rna=rna, sc_atac=atac, spatial=spatial, metadata=meta,
            bulk_batch=batch,
        )


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 4 — DATA INGESTION ROUTER
# ══════════════════════════════════════════════════════════════════════════════

@dataclass
class InputConfig:
    """Paths to real data files. None = use synthetic for that modality."""
    mode:            str   = "synthetic"   # "synthetic" | "real" | "mixed"
    transcriptomics: Optional[Path] = None
    proteomics:      Optional[Path] = None
    metabolomics:    Optional[Path] = None
    genomics:        Optional[Path] = None
    sc_rna:          Optional[Path] = None
    sc_atac:         Optional[Path] = None
    spatial:         Optional[Path] = None
    metadata:        Optional[Path] = None
    # synthetic fallback sizes
    n_samples:  int = 120
    n_cells:    int = 400
    n_batches:  int = 3


def ingest_data(cfg: InputConfig) -> Tuple[Dict, ValidationReport]:
    """
    Route to synthetic generator or real file loaders based on InputConfig.
    Runs the full validation suite on every modality.
    Returns (data_dict, report).
    """
    report  = ValidationReport()
    loader  = DataLoader()
    val     = OmicsValidator(report)
    data: Dict[str, Any] = {}

    # ── synthetic base (used for any modality whose path is None) ─────────────
    synth = None
    if cfg.mode in ("synthetic", "mixed"):
        synth = SyntheticGenerator(cfg.n_samples, cfg.n_cells, cfg.n_batches).generate()

    def _get(key: str, path: Optional[Path], is_anndata: bool = False):
        if path is not None:
            if is_anndata:
                return loader.load_anndata(path, key)
            return loader.load_bulk(path, key)
        if synth is not None:
            log.info(f"  [{key}] using synthetic data")
            return synth.get(key)
        return None

    # ── bulk modalities ───────────────────────────────────────────────────────
    for name, path in [
        ("transcriptomics", cfg.transcriptomics),
        ("proteomics",      cfg.proteomics),
        ("metabolomics",    cfg.metabolomics),
        ("genomics",        cfg.genomics),
    ]:
        raw = _get(name, path, False)
        if raw is not None:
            data[name] = val.validate_bulk(name, raw)

    # ── single-cell ───────────────────────────────────────────────────────────
    for name, path in [("sc_rna", cfg.sc_rna), ("sc_atac", cfg.sc_atac)]:
        raw = _get(name, path, True)
        if raw is not None:
            data[name] = val.validate_anndata(name, raw)

    # ── spatial ───────────────────────────────────────────────────────────────
    raw = _get("spatial", cfg.spatial, True)
    if raw is not None:
        data["spatial"] = val.validate_anndata("spatial", raw)

    # ── metadata ──────────────────────────────────────────────────────────────
    raw_meta = _get("metadata", cfg.metadata, False)
    if raw_meta is not None:
        data["metadata"] = val.validate_metadata(raw_meta)

    # ── batch label array (for downstream functions) ──────────────────────────
    if "metadata" in data and "batch" in data["metadata"].columns:
        data["bulk_batch"] = LabelEncoder().fit_transform(
            data["metadata"]["batch"].astype(str))
    elif synth is not None:
        data["bulk_batch"] = synth["bulk_batch"]
    else:
        data["bulk_batch"] = np.zeros(
            len(data.get("transcriptomics",
                pd.DataFrame(index=range(cfg.n_samples)))), dtype=int)

    # ── cross-modality reconciliation ─────────────────────────────────────────
    data = val.reconcile_samples(data)

    # ── print & save report ───────────────────────────────────────────────────
    print(report.summary())
    report.save_html(OUTPUT_DIR / "validation_report.html")

    if not report.passed:
        log.warning("Validation errors detected — review report before proceeding.")

    return data, report


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 5 — PREPROCESSING + BATCH CORRECTION
# ══════════════════════════════════════════════════════════════════════════════

def log_norm_zscore(df: pd.DataFrame) -> pd.DataFrame:
    df = np.log1p(df.clip(lower=0))
    return pd.DataFrame(StandardScaler().fit_transform(df),
                        index=df.index, columns=df.columns)

def fast_pca(X: np.ndarray, k: int = 30) -> np.ndarray:
    k   = min(k, X.shape[0]-1, X.shape[1]-1)
    Xc  = X - X.mean(axis=0)
    U,S,_ = randomized_svd(Xc, n_components=k, n_iter=4, random_state=42)
    return (U*S).astype(np.float32)

def _combat_fb(df: pd.DataFrame, batch: np.ndarray) -> pd.DataFrame:
    X = df.values.astype(np.float32)
    gm,gv = X.mean(0), X.var(0)+1e-8
    out = X.copy()
    for b in np.unique(batch):
        m=batch==b; n_b=m.sum()
        bm=X[m].mean(0); bv=X[m].var(0)+1e-8
        em=(gm*gv+bm*n_b)/(gv+n_b); ev=(gv+bv)/2
        out[m]=(X[m]-em)/np.sqrt(ev)*np.sqrt(gv)+gm
    return pd.DataFrame(out, index=df.index, columns=df.columns)

def batch_correct_bulk(df, batch, covar=None):
    if PYCOMBAT:
        bs = pd.Series(batch.astype(str), index=df.index)
        kw = {"covar_mod": covar.values} if covar is not None else {}
        return pycombat_norm(df.T, bs, **kw).T
    return _combat_fb(df, batch)

def harmony_correct(emb: np.ndarray, batch: np.ndarray) -> np.ndarray:
    """
    Run Harmony on (n_cells, n_components) and return (n_cells, n_components).

    harmonypy.run_harmony expects rows=cells, cols=components and stores the
    result in Z_corr shaped (n_components, n_cells).  We always derive the
    canonical orientation from the batch length so the function is correct
    regardless of what shape the caller accidentally passes in.
    """
    if emb.ndim != 2:
        raise ValueError(f"harmony_correct: need 2-D array, got {emb.shape}")

    n_batch = len(batch)
    r, c    = emb.shape

    # Orient so that rows == cells (== len(batch))
    if r == n_batch and c == n_batch:
        pass                        # square — trust as-is
    elif r == n_batch:
        pass                        # already (n_cells, n_comps)
    elif c == n_batch:
        log.warning(f"harmony_correct: transposing input {emb.shape} → ({c}, {r})")
        emb  = emb.T
        r, c = emb.shape
    else:
        raise ValueError(
            f"harmony_correct: neither dimension of {emb.shape} "
            f"matches batch length {n_batch}"
        )

    n_cells, n_comps = r, c
    meta = pd.DataFrame({"batch": np.asarray(batch).astype(str)},
                        index=np.arange(n_cells))

    ho  = hm.run_harmony(emb.astype(np.float64), meta, "batch",
                         max_iter_harmony=15, random_state=42, verbose=False)

    # Z_corr is (n_comps, n_cells) — transpose unconditionally
    out = np.asarray(ho.Z_corr, dtype=np.float32).T   # → (n_cells, n_comps)

    if out.shape != (n_cells, n_comps):
        # Last-resort: try the other orientation
        alt = out.T
        if alt.shape == (n_cells, n_comps):
            log.warning("harmony_correct: applied extra transpose to fix shape.")
            out = alt
        else:
            raise ValueError(
                f"harmony_correct: cannot recover expected shape "
                f"({n_cells}, {n_comps}) from Z_corr {np.asarray(ho.Z_corr).shape}"
            )
    return out

def preprocess_scrna(adata):
    sc.pp.filter_cells(adata, min_genes=10)
    sc.pp.filter_genes(adata, min_cells=3)
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=min(2000, adata.n_vars))
    adata = adata[:, adata.var.highly_variable].copy()
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, n_comps=min(50, adata.n_obs-1, adata.n_vars-1), random_state=42)
    return adata

def preprocess_scatac(adata):
    X = adata.X.toarray().astype(np.float32) if sparse.issparse(adata.X) else adata.X.copy()
    tf  = X / (X.sum(axis=1, keepdims=True) + 1e-9)
    idf = np.log1p(X.shape[0] / (X.sum(axis=0) + 1))
    adata.X = sparse.csr_matrix((tf*idf).astype(np.float32))
    k = min(50, adata.n_obs-1, adata.n_vars-1)
    adata.obsm["X_lsi"] = TruncatedSVD(n_components=k, random_state=42).fit_transform(adata.X).astype(np.float32)
    return adata

def preprocess_spatial(adata):
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=min(1000, adata.n_vars))
    adata = adata[:, adata.var.highly_variable].copy()
    sc.pp.scale(adata)
    sc.tl.pca(adata, n_comps=min(30, adata.n_obs-1, adata.n_vars-1), random_state=42)
    return adata


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 6 — REACTOME MAPPING
# ══════════════════════════════════════════════════════════════════════════════

class ReactomeMapper:
    CACHE = OUTPUT_DIR / "reactome_cache.json"

    def __init__(self, use_cache=True):
        self._c: Dict = {}
        if use_cache and self.CACHE.exists():
            self._c = json.loads(self.CACHE.read_text())
            log.info(f"Loaded {len(self._c)} cached Reactome entries.")

    def _get(self, url, params=None):
        try:
            r = requests.get(url, params=params, timeout=12)
            r.raise_for_status(); return r.json()
        except Exception: return None

    def _pathways(self, eid: str, etype: str) -> List[Dict]:
        key = f"{etype}:{eid}"
        if key in self._c: return self._c[key]
        data = self._get(
            f"{REACTOME_BASE}/data/pathways/low/entity/{eid}/allForms",
            params={"species":"Homo sapiens"})
        result = []
        if data and isinstance(data, list):
            for pw in data:
                result.append(dict(
                    entity=eid, entity_type=etype,
                    pathway_id=pw.get("stId",""),
                    pathway_name=pw.get("displayName","")))
        self._c[key] = result
        return result

    def _save(self):
        self.CACHE.write_text(json.dumps(self._c))

    @staticmethod
    def _simulate(genes, proteins, metabolites):
        rng = np.random.default_rng(0)
        PW = {"R-HSA-1640170":"Cell Cycle","R-HSA-109581":"Apoptosis",
              "R-HSA-1430728":"Metabolism","R-HSA-162582":"Signal Transduction",
              "R-HSA-913531":"DNA Repair","R-HSA-74160":"Gene Expression",
              "R-HSA-556833":"Lipid Metabolism","R-HSA-5633007":"Regulation of TP53",
              "R-HSA-194315":"Rho GTPase Signalling","R-HSA-392499":"PI3K/AKT Signalling"}
        pids = list(PW.keys()); pnames = list(PW.values())
        rows = []
        for g in genes:
            for pid,pn in zip(rng.choice(pids,rng.integers(1,4),replace=False),
                              rng.choice(pnames,rng.integers(1,4),replace=False)):
                rows.append(dict(entity=g,entity_type="gene",pathway_id=pid,pathway_name=pn))
        for p in proteins:
            rows.append(dict(entity=p,entity_type="protein",
                             pathway_id=rng.choice(pids),pathway_name=rng.choice(pnames)))
        for m in metabolites:
            rows.append(dict(entity=m,entity_type="metabolite",
                             pathway_id=rng.choice(pids),pathway_name=rng.choice(pnames)))
        return pd.DataFrame(rows)

    def map_all(self, genes, proteins, metabolites) -> pd.DataFrame:
        log.info(f"Reactome mapping: {len(genes)}G + {len(proteins)}P + {len(metabolites)}M")
        rows = []
        for etype, items in [("gene",genes),("protein",proteins),("metabolite",metabolites)]:
            res = Parallel(n_jobs=8, prefer="threads")(
                delayed(self._pathways)(e, etype)
                for e in tqdm(items, desc=f"  Reactome {etype}s", leave=False))
            for r in res: rows.extend(r)
        self._save()
        df = pd.DataFrame(rows) if rows else pd.DataFrame()
        if df.empty or (df["pathway_id"] == "").all():
            log.warning("Reactome API unreachable — using simulated pathway assignments.")
            return self._simulate(genes, proteins, metabolites)
        log.info(f"  {len(df)} entity-pathway pairs  {df['pathway_id'].nunique()} pathways")
        return df


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 7 — NETWORK + ANALYSIS + PLOTS  (unchanged from v2, kept concise)
# ══════════════════════════════════════════════════════════════════════════════

def build_network(mapping_df: pd.DataFrame) -> nx.Graph:
    G = nx.Graph()
    for _, row in mapping_df.iterrows():
        e = row["entity"]
        if not G.has_node(e):
            G.add_node(e, node_type=row["entity_type"],
                       color=ENTITY_COLORS[row["entity_type"]], size=12)
    for pid, grp in mapping_df.groupby("pathway_id"):
        pname = grp["pathway_name"].iloc[0]
        if not G.has_node(pid):
            G.add_node(pid, node_type="pathway", label=pname,
                       color=ENTITY_COLORS["pathway"], size=20)
    for _, row in mapping_df.iterrows():
        G.add_edge(row["entity"], row["pathway_id"],
                   edge_type="member_of", weight=1.0)
    co: Dict = defaultdict(int)
    for entities in mapping_df.groupby("pathway_id")["entity"].apply(list):
        for i in range(len(entities)):
            for j in range(i+1, len(entities)):
                co[tuple(sorted([entities[i], entities[j]]))] += 1
    for (a,b), cnt in co.items():
        if cnt >= 2:
            if G.has_edge(a,b): G[a][b]["weight"] += cnt
            else: G.add_edge(a, b, edge_type="co_pathway", weight=float(cnt))
    log.info(f"Network: {G.number_of_nodes()} nodes  {G.number_of_edges()} edges")
    return G

def differential_analysis(omics_dict, condition):
    log.info("Differential analysis …")
    cm = (condition=="Case").values; ctrl = ~cm; rows = []
    for mod, df in omics_dict.items():
        X = df.values.astype(np.float32)
        muc = X[cm].mean(0); mut = X[ctrl].mean(0)
        lfc = np.log2((muc+1e-6)/(mut+1e-6))
        t,p = ttest_ind(X[cm], X[ctrl], axis=0, equal_var=False)
        p   = np.nan_to_num(p, nan=1.0)
        _,padj,_,_ = multipletests(p, method="fdr_bh")
        for i,feat in enumerate(df.columns):
            rows.append(dict(entity=feat,modality=mod,log2FC=float(lfc[i]),
                             pval=float(p[i]),padj=float(padj[i]),
                             significant=bool(padj[i]<0.05 and abs(lfc[i])>0.5)))
    de = pd.DataFrame(rows)
    log.info(f"  {de['significant'].sum()} / {len(de)} significant")
    return de

def _ks_es(stats_, idx, p=1.0):
    N=len(stats_); Nh=len(idx)
    if Nh<2 or Nh==N: return 0.0
    ab = np.abs(stats_[idx])**p
    Nr = ab.sum()+1e-10
    inc = np.zeros(N); inc[idx] = ab/Nr
    exc = np.where(np.isin(np.arange(N),idx),0.,1./(N-Nh+1e-10))
    run = np.cumsum(inc-exc)
    return float(run[np.argmax(np.abs(run))])

def pathway_activity_scoring(de_df, mapping_df, n_perm=200):
    log.info(f"PAS ({n_perm} permutations) …")
    rng = np.random.default_rng(42)
    ds  = de_df.sort_values("log2FC", ascending=False).reset_index(drop=True)
    all_e = ds["entity"].tolist(); rs = ds["log2FC"].values.astype(np.float32)
    e2r   = {e:i for i,e in enumerate(all_e)}
    rows  = []
    for pid, grp in tqdm(mapping_df.groupby("pathway_id"), desc="  PAS", leave=False):
        idx = np.array([e2r[e] for e in grp["entity"] if e in e2r],dtype=int)
        if len(idx)<3: continue
        es  = _ks_es(rs,idx)
        null= np.array([_ks_es(rs,rng.choice(len(rs),len(idx),replace=False))
                        for _ in range(n_perm)])
        pos = null[null>=0]; neg = null[null<0]
        nes = es/(pos.mean()+1e-10) if es>=0 else -es/(np.abs(neg).mean()+1e-10)
        pv  = ((pos>=es).mean() if es>=0 else (neg<=es).mean())
        rows.append(dict(pathway_id=pid,pathway_name=grp["pathway_name"].iloc[0],
                         n_entities=len(idx),ES=float(es),NES=float(nes),
                         pval=float(max(pv,1/n_perm))))
    if not rows: return pd.DataFrame()
    pas = pd.DataFrame(rows)
    _,pas["padj"],_,_ = multipletests(pas["pval"],method="fdr_bh")
    pas["significant"] = (pas["padj"]<0.05)&(pas["NES"].abs()>1.0)
    return pas.sort_values("NES",ascending=False)

def overlay_results(G, de_df, pas_df):
    de_m = de_df.set_index("entity")[["log2FC","padj","significant"]].to_dict("index")
    pm   = pas_df.set_index("pathway_id")[["NES","padj","significant"]].to_dict("index") \
           if not pas_df.empty else {}
    for n in G.nodes():
        nt = G.nodes[n].get("node_type","")
        if nt in ("gene","protein","metabolite") and n in de_m:
            G.nodes[n].update({"log2FC":de_m[n]["log2FC"],"de_padj":de_m[n]["padj"],
                                "de_sig":de_m[n]["significant"]})
        elif nt=="pathway" and n in pm:
            G.nodes[n].update({"NES":pm[n]["NES"],"pas_padj":pm[n]["padj"],
                                "pas_sig":pm[n]["significant"]})
    return G

def _layout(G): return nx.spring_layout(G, seed=42, weight="weight", k=0.5)

def _draw_base(G, pos, ax, pw_alpha=0.6):
    for nt, col in ENTITY_COLORS.items():
        nodes = [n for n,d in G.nodes(data=True) if d.get("node_type")==nt]
        sizes = [G.nodes[n].get("size",10)*8 for n in nodes]
        nx.draw_networkx_nodes(G,pos,nodelist=nodes,node_color=col,
                               node_size=sizes,ax=ax,alpha=pw_alpha if nt=="pathway" else 0.85)
    nx.draw_networkx_edges(G,pos,ax=ax,alpha=0.15,edge_color="#aaaaaa",width=0.5)

def _two_slope_norm(values: list, cmap_default):
    """
    Safely build a TwoSlopeNorm from a list of floats.
    Falls back to plain Normalize when all values are identical or the
    range would violate the vmin < vcenter < vmax constraint.
    """
    arr  = np.asarray(values, dtype=float)
    arr  = arr[np.isfinite(arr)]
    if len(arr) == 0:
        return mcolors.Normalize(vmin=-1, vmax=1)
    vmin, vmax = float(arr.min()), float(arr.max())
    if vmin == vmax:                          # all identical
        delta = max(abs(vmin) * 0.1, 1e-6)
        vmin -= delta; vmax += delta
    if vmin >= 0:                             # all non-negative → shift vmin
        vmin = -1e-6
    if vmax <= 0:                             # all non-positive → shift vmax
        vmax = 1e-6
    return mcolors.TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax)

def plot_all(G, pos, de_df, pas_df):
    # ── overview ──────────────────────────────────────────────────────────────
    fig,ax = plt.subplots(figsize=(13,9))
    _draw_base(G,pos,ax)
    pw_labels = {n:d.get("label",n)[:26] for n,d in G.nodes(data=True)
                 if d.get("node_type")=="pathway"}
    nx.draw_networkx_labels(G,pos,labels=pw_labels,font_size=5,ax=ax)
    ax.legend(handles=[mpatches.Patch(color=c,label=t.capitalize())
                        for t,c in ENTITY_COLORS.items()],fontsize=8,loc="upper left")
    ax.set_title("Reactome Network — Overview",fontweight="bold"); ax.axis("off")
    plt.tight_layout(); plt.savefig(OUTPUT_DIR/"network_overview.png",dpi=150); plt.close()

    # ── DE overlay ────────────────────────────────────────────────────────────
    fig,ax = plt.subplots(figsize=(13,9))
    pw_nodes = [n for n,d in G.nodes(data=True) if d.get("node_type")=="pathway"]
    nx.draw_networkx_nodes(G,pos,nodelist=pw_nodes,node_color="#cccccc",
                           node_size=120,ax=ax,alpha=0.5)
    ent = [n for n,d in G.nodes(data=True) if d.get("node_type") in ("gene","protein","metabolite")]
    fc  = [G.nodes[n].get("log2FC",0.) for n in ent]
    sig = [G.nodes[n].get("de_sig",False) for n in ent]
    norm = _two_slope_norm(fc, plt.cm.RdBu_r)
    cmap = plt.cm.RdBu_r
    nx.draw_networkx_nodes(G,pos,nodelist=ent,
                           node_color=[cmap(norm(v)) for v in fc],
                           node_size=[60 if s else 25 for s in sig],ax=ax,alpha=0.9)
    nx.draw_networkx_edges(G,pos,ax=ax,alpha=0.1,edge_color="#999",width=0.4)
    nx.draw_networkx_labels(G,pos,labels={n:n for n,s in zip(ent,sig) if s},
                            font_size=5,ax=ax)
    sm=plt.cm.ScalarMappable(cmap=cmap,norm=norm); sm.set_array([])
    plt.colorbar(sm,ax=ax,fraction=0.02,pad=0.01,label="log₂ Fold Change")
    ax.set_title("DE Overlay",fontweight="bold"); ax.axis("off")
    plt.tight_layout(); plt.savefig(OUTPUT_DIR/"network_de_overlay.png",dpi=150); plt.close()

    # ── PAS overlay ───────────────────────────────────────────────────────────
    if not pas_df.empty:
        fig,ax = plt.subplots(figsize=(13,9))
        ent_n = [n for n,d in G.nodes(data=True)
                 if d.get("node_type") in ("gene","protein","metabolite")]
        nx.draw_networkx_nodes(G,pos,nodelist=ent_n,node_color="#dddddd",
                               node_size=15,ax=ax,alpha=0.4)
        pwn  = [n for n,d in G.nodes(data=True) if d.get("node_type")=="pathway"]
        nes  = [G.nodes[n].get("NES",0.) for n in pwn]
        psig = [G.nodes[n].get("pas_sig",False) for n in pwn]
        norm2 = _two_slope_norm(nes, plt.cm.PiYG)
        cmap2 = plt.cm.PiYG
        nx.draw_networkx_nodes(G,pos,nodelist=pwn,
                               node_color=[cmap2(norm2(v)) for v in nes],
                               node_size=[400 if s else 120 for s in psig],ax=ax,alpha=0.9)
        nx.draw_networkx_edges(G,pos,ax=ax,alpha=0.08,edge_color="#aaa",width=0.3)
        nx.draw_networkx_labels(G,pos,labels={n:d.get("label",n)[:20]
                                               for n,d,s in zip(pwn,
                                               [G.nodes[x] for x in pwn],psig) if s},
                                font_size=5,ax=ax)
        sm2=plt.cm.ScalarMappable(cmap=cmap2,norm=norm2); sm2.set_array([])
        plt.colorbar(sm2,ax=ax,fraction=0.02,pad=0.01,label="NES")
        ax.set_title("Pathway Activity Score Overlay",fontweight="bold"); ax.axis("off")
        plt.tight_layout(); plt.savefig(OUTPUT_DIR/"network_pas_overlay.png",dpi=150); plt.close()

    # ── analysis multi-panel ─────────────────────────────────────────────────
    fig = plt.figure(figsize=(18,14))
    gs  = GridSpec(3,3,figure=fig,hspace=0.45,wspace=0.38)
    ax1 = fig.add_subplot(gs[0,:2])
    col = de_df["significant"].map({True:"#e63946",False:"#adb5bd"})
    ax1.scatter(de_df["log2FC"],-np.log10(de_df["pval"]+1e-300),
                c=col,s=12,alpha=0.65,linewidths=0)
    ax1.axvline(0.5,color="#333",lw=0.8,ls="--"); ax1.axvline(-0.5,color="#333",lw=0.8,ls="--")
    ax1.axhline(-np.log10(0.05),color="#555",lw=0.8,ls=":")
    for _,row in de_df[de_df["significant"]].nlargest(10,"log2FC").iterrows():
        ax1.text(row["log2FC"],-np.log10(row["pval"]+1e-300),
                 row["entity"],fontsize=5.5,ha="left",va="bottom")
    ax1.set_xlabel("log₂FC"); ax1.set_ylabel("-log₁₀(p)"); ax1.set_title("Volcano Plot",fontweight="bold")
    ax2 = fig.add_subplot(gs[0,2])
    ax2.scatter(de_df["log2FC"].abs(), de_df["log2FC"],c=col,s=8,alpha=0.5,linewidths=0)
    ax2.axhline(0,color="#333",lw=0.8); ax2.set_xlabel("Mean |log₂FC|")
    ax2.set_ylabel("log₂FC"); ax2.set_title("MA Plot",fontweight="bold")
    ax3 = fig.add_subplot(gs[1,:])
    if not pas_df.empty:
        pp = pas_df.head(20).sort_values("NES")
        bc = ["#e63946" if v>0 else "#4361ee" for v in pp["NES"]]
        ax3.barh(pp["pathway_name"],pp["NES"],color=bc,alpha=0.8,edgecolor="white",lw=0.4)
        for i,(_,row) in enumerate(pp.iterrows()):
            if row.get("significant",False):
                ax3.text(row["NES"]+(0.02 if row["NES"]>0 else -0.02),i,"★",
                         fontsize=7,va="center",ha="left" if row["NES"]>0 else "right")
        ax3.axvline(0,color="#333",lw=0.8); ax3.set_xlabel("NES")
        ax3.set_title("Pathway Activity Scores (★=sig)",fontweight="bold")
        ax3.tick_params(axis="y",labelsize=7)
    ax4 = fig.add_subplot(gs[2,:])
    top = de_df[de_df["significant"]].nlargest(30,"log2FC")[["entity","modality","log2FC"]]
    if not top.empty:
        pv = top.pivot_table(index="entity",columns="modality",values="log2FC",aggfunc="mean").fillna(0)
        sns.heatmap(pv,ax=ax4,cmap="RdBu_r",center=0,linewidths=0.3,linecolor="#eee",
                    cbar_kws={"label":"log₂FC","shrink":0.6})
        ax4.set_title("Top 30 Significant Entities Heatmap",fontweight="bold")
        ax4.tick_params(axis="y",labelsize=6); ax4.set_xlabel(""); ax4.set_ylabel("")
    fig.suptitle("Multi-Omics Reactome Analysis",fontsize=14,fontweight="bold",y=1.01)
    plt.savefig(OUTPUT_DIR/"analysis_results.png",dpi=150,bbox_inches="tight"); plt.close()

    # ── degree distribution ───────────────────────────────────────────────────
    fig,axes = plt.subplots(1,2,figsize=(12,4))
    degs = [d for _,d in G.degree()]
    axes[0].hist(degs,bins=30,color="#4e79a7",edgecolor="white",lw=0.5)
    axes[0].set(xlabel="Degree",ylabel="Count",yscale="log",title="Degree Distribution")
    hubs = sorted(G.degree(),key=lambda x:x[1],reverse=True)[:20]
    hn   = [f"{n[:18]}…" if len(n)>18 else n for n,_ in hubs]
    hd   = [d for _,d in hubs]
    hc   = [ENTITY_COLORS.get(G.nodes[n].get("node_type",""),"#888") for n,_ in hubs]
    axes[1].barh(hn[::-1],hd[::-1],color=hc[::-1],edgecolor="white",lw=0.4)
    axes[1].set(xlabel="Degree",title="Top 20 Hubs")
    axes[1].tick_params(axis="y",labelsize=7)
    plt.tight_layout()
    plt.savefig(OUTPUT_DIR/"degree_distribution.png",dpi=150); plt.close()

    # ── validation distribution QC ────────────────────────────────────────────
    log.info("  Saved all plots.")


def export_html(G, pos, de_df):
    try:
        from pyvis.network import Network
        net = Network(height="800px",width="100%",bgcolor="#1a1a2e",
                      font_color="#eee",notebook=False)
        net.set_options('{"physics":{"barnesHut":{"gravitationalConstant":-8000}}}')
        de_m = de_df.set_index("entity")["log2FC"].to_dict() if not de_df.empty else {}
        for node,data in G.nodes(data=True):
            nt=data.get("node_type",""); col=ENTITY_COLORS.get(nt,"#888")
            sz=data.get("size",10); fc=de_m.get(node,0.)
            title=f"<b>{node}</b><br>Type:{nt}<br>log2FC:{fc:.3f}<br>NES:{data.get('NES','N/A')}"
            if data.get("de_sig") or data.get("pas_sig"): col="#ff6b6b"; sz*=2
            net.add_node(str(node),label=str(data.get("label",node))[:28],
                         color=col,size=sz,title=title)
        for u,v,ed in G.edges(data=True):
            net.add_edge(str(u),str(v),
                         width=min(ed.get("weight",1.),5.),
                         color="#334455" if ed.get("edge_type")=="member_of" else "#555577")
        net.save_graph(str(OUTPUT_DIR/"interactive_network.html"))
        log.info("  Saved: interactive_network.html")
    except ImportError:
        log.warning("pyvis not installed — skipping interactive HTML export.")


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 8 — MAIN PIPELINE
# ══════════════════════════════════════════════════════════════════════════════

def run_pipeline(cfg: InputConfig, n_perm: int = 200):
    t0  = time.time()
    bar = "═"*65
    log.info(f"\n{bar}\n  MULTI-OMICS · REACTOME  (mode={cfg.mode})\n{bar}")

    # ── 1. Ingest + validate ──────────────────────────────────────────────────
    log.info("\n[1] Data ingestion & validation")
    data, report = ingest_data(cfg)
    if not report.passed:
        log.warning(f"  {len(report.errors)} validation error(s) — check validation_report.html")

    meta      = data.get("metadata")
    batch     = data.get("bulk_batch", np.zeros(cfg.n_samples, dtype=int))
    condition = meta["condition"] if meta is not None else pd.Series(
        ["Case"]*(cfg.n_samples//2)+["Control"]*(cfg.n_samples-cfg.n_samples//2))

    # ── 2. Preprocessing + batch correction ──────────────────────────────────
    log.info("\n[2] Preprocessing + batch correction")
    covar = None
    if meta is not None:
        enc_sex = LabelEncoder().fit_transform(meta.get("sex",
            pd.Series(["M"]*len(meta))).astype(str))
        covar = pd.DataFrame({
            "age": StandardScaler().fit_transform(
                meta[["age"]].apply(pd.to_numeric,errors="coerce").fillna(50)).ravel(),
            "sex": enc_sex,
        }, index=meta.index)

    omics_corr: Dict[str, pd.DataFrame] = {}
    for name in ("transcriptomics","proteomics","metabolomics"):
        df = data.get(name)
        if df is None: continue
        pp = log_norm_zscore(df)
        omics_corr[name] = batch_correct_bulk(pp, batch, covar)
        log.info(f"  {name}: {omics_corr[name].shape} ✓")

    if data.get("sc_rna")  is not None: data["sc_rna"]  = preprocess_scrna(data["sc_rna"])
    if data.get("sc_atac") is not None: data["sc_atac"] = preprocess_scatac(data["sc_atac"])
    if data.get("spatial") is not None: data["spatial"] = preprocess_spatial(data["spatial"])

    # Harmony for single-cell
    for key, emb_key in [("sc_rna","X_pca"),("sc_atac","X_lsi")]:
        ad_ = data.get(key)
        if ad_ is not None and emb_key in ad_.obsm and "batch" in ad_.obs.columns:
            raw_emb = np.asarray(ad_.obsm[emb_key], dtype=np.float32)
            batch_labels = ad_.obs["batch"].values
            ad_.obsm[f"{emb_key}_harmony"] = harmony_correct(raw_emb, batch_labels)

    # ── 3. Reactome mapping ───────────────────────────────────────────────────
    log.info("\n[3] Reactome mapping")
    genes  = list(omics_corr.get("transcriptomics",
                  pd.DataFrame(columns=GENE_SYMBOLS)).columns)[:len(GENE_SYMBOLS)]
    prots  = list(omics_corr.get("proteomics",
                  pd.DataFrame(columns=PROTEIN_SYMS)).columns)[:len(PROTEIN_SYMS)]
    mets   = list(omics_corr.get("metabolomics",
                  pd.DataFrame(columns=CHEBI_IDS)).columns)[:len(CHEBI_IDS)]
    mapper     = ReactomeMapper()
    mapping_df = mapper.map_all(genes, prots, mets)
    mapping_df.to_csv(OUTPUT_DIR/"reactome_mapping.csv", index=False)

    # ── 4. Network ────────────────────────────────────────────────────────────
    log.info("\n[4] Network construction")
    G = build_network(mapping_df)

    # ── 5. Differential analysis ──────────────────────────────────────────────
    log.info("\n[5] Differential analysis")
    de_df = differential_analysis(omics_corr, condition)
    de_df.to_csv(OUTPUT_DIR/"differential_analysis.csv", index=False)

    # ── 6. PAS ────────────────────────────────────────────────────────────────
    log.info("\n[6] Pathway activity scoring")
    pas_df = pathway_activity_scoring(de_df, mapping_df, n_perm=n_perm)
    if not pas_df.empty:
        pas_df.to_csv(OUTPUT_DIR/"pathway_activity_scores.csv", index=False)

    # ── 7–9. Overlay + plot ───────────────────────────────────────────────────
    log.info("\n[7] Overlay + plots")
    G = overlay_results(G, de_df, pas_df)
    pos = _layout(G)
    plot_all(G, pos, de_df, pas_df)
    export_html(G, pos, de_df)

    elapsed = time.time()-t0
    log.info(f"\n{bar}\n  COMPLETE  {elapsed:.1f}s  "
             f"outputs → {OUTPUT_DIR.resolve()}\n{bar}")
    return dict(G=G,pos=pos,mapping_df=mapping_df,
                de_df=de_df,pas_df=pas_df,data=data,report=report)


# ══════════════════════════════════════════════════════════════════════════════
# SECTION 9 — CLI
# ══════════════════════════════════════════════════════════════════════════════

def _path(s): return Path(s) if s else None

def build_cli() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="multiomics_reactome",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        description=__doc__,
        epilog="""
Examples
────────
  # Full synthetic run (default)
  python multiomics_reactome.py --mode synthetic

  # Real transcriptomics + proteomics, synthetic everything else
  python multiomics_reactome.py --mode mixed \\
      --transcriptomics data/rna.csv \\
      --proteomics data/prot.tsv \\
      --metadata data/meta.csv

  # All real inputs
  python multiomics_reactome.py --mode real \\
      --transcriptomics data/rna.csv \\
      --proteomics data/prot.tsv \\
      --metabolomics data/met.csv \\
      --sc-rna data/scrna.h5ad \\
      --sc-atac data/scatac.h5ad \\
      --spatial data/visium_dir/ \\
      --metadata data/meta.csv

  # Validation only (no analysis)
  python multiomics_reactome.py --mode real --transcriptomics data/rna.csv \\
      --metadata data/meta.csv --validate-only
""")
    p.add_argument("--mode", choices=["synthetic","real","mixed"],
                   default="synthetic",
                   help="Data source mode (default: synthetic)")
    p.add_argument("--transcriptomics", metavar="FILE",
                   help="Bulk RNA-seq  CSV/TSV/Excel/Parquet  [samples × genes]")
    p.add_argument("--proteomics",      metavar="FILE",
                   help="Proteomics    CSV/TSV/Excel/Parquet  [samples × proteins]")
    p.add_argument("--metabolomics",    metavar="FILE",
                   help="Metabolomics  CSV/TSV/Excel/Parquet  [samples × metabolites]")
    p.add_argument("--genomics",        metavar="FILE",
                   help="Genomics/SNP  CSV/TSV/Excel/Parquet  [samples × features]")
    p.add_argument("--sc-rna",          metavar="FILE/DIR",
                   help="scRNA-seq     .h5ad | 10x MEX dir | CSV")
    p.add_argument("--sc-atac",         metavar="FILE/DIR",
                   help="scATAC-seq    .h5ad | 10x MEX dir | CSV")
    p.add_argument("--spatial",         metavar="FILE/DIR",
                   help="Spatial omics .h5ad | Visium dir")
    p.add_argument("--metadata",        metavar="FILE",
                   help="Metadata      CSV/TSV/Excel  (must contain 'condition','batch')")
    p.add_argument("--n-samples",  type=int, default=120,
                   help="Synthetic sample count (default: 120)")
    p.add_argument("--n-cells",    type=int, default=400,
                   help="Synthetic cell count   (default: 400)")
    p.add_argument("--n-batches",  type=int, default=3,
                   help="Synthetic batch count  (default: 3)")
    p.add_argument("--n-perm",     type=int, default=200,
                   help="GSEA permutations      (default: 200)")
    p.add_argument("--validate-only", action="store_true",
                   help="Run validation & standardisation only; skip analysis")
    p.add_argument("--output-dir", default="multiomics_reactome_output",
                   help="Output directory (default: multiomics_reactome_output)")
    return p


def main():
    global OUTPUT_DIR
    parser = build_cli()
    args   = parser.parse_args()

    OUTPUT_DIR = Path(args.output_dir)
    OUTPUT_DIR.mkdir(exist_ok=True)

    cfg = InputConfig(
        mode            = args.mode,
        transcriptomics = _path(args.transcriptomics),
        proteomics      = _path(args.proteomics),
        metabolomics    = _path(args.metabolomics),
        genomics        = _path(args.genomics),
        sc_rna          = _path(args.sc_rna),
        sc_atac         = _path(args.sc_atac),
        spatial         = _path(args.spatial),
        metadata        = _path(args.metadata),
        n_samples       = args.n_samples,
        n_cells         = args.n_cells,
        n_batches       = args.n_batches,
    )

    if args.validate_only:
        log.info("=== Validation-only mode ===")
        _, report = ingest_data(cfg)
        print(report.summary())
        return

    run_pipeline(cfg, n_perm=args.n_perm)


if __name__ == "__main__":
    main()
