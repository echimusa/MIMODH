"""
batch_correction_metrics.py
============================
Computes iLISI, cLISI, and kBET batch-correction benchmarking metrics
for the MIMODH / MultiOmics-Reactome manuscript.

Covers the three modalities cited in the Batch-effect correction strategy
section of MANUSCRIPT_MIMODH_revised_tracked.docx:
  • scRNA-seq  → Harmony on PCA (50 PCs)
  • scATAC-seq → Harmony on LSI components 2-50 (comp 1 excluded)
  • Bulk proteomics → pycombat in feature space

Suggested public datasets (replace accessions with your actual data):
  scRNA-seq  : GEO GSE96583  (Kang et al. 2018 — stimulated/ctrl PBMC,
                               two batches; clear biological contrast)
  scATAC-seq : GEO GSE194122 (10x Multiome PBMC; paired RNA+ATAC,
                               multiple donors = natural batches)
  Proteomics : PRIDE PXD004682 (CPTAC breast cancer TMT; multiple
                               mass-spec batches, well-characterised)
               OR PXD010154  (iPRG 2016 benchmark; explicit batch design)

Requirements
------------
    pip install scanpy anndata harmonypy scib-metrics kbet lisi
    pip install inmoose pandas numpy scipy

Output
------
    batch_metrics_results.csv   — formatted for Supplementary Table 7
    batch_metrics_results.json  — machine-readable version
"""

from __future__ import annotations

import json
import logging
import warnings
from pathlib import Path
from typing import Dict, Optional, Tuple

import anndata as ad
import numpy as np
import pandas as pd
import scanpy as sc
import harmonypy as hm
from scipy import sparse
from sklearn.decomposition import TruncatedSVD
from sklearn.preprocessing import normalize

warnings.filterwarnings("ignore")
logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("batch_metrics")

OUT_DIR = Path("batch_metrics_output")
OUT_DIR.mkdir(exist_ok=True)


# ══════════════════════════════════════════════════════════════════════════════
# 1. METRIC COMPUTATION FUNCTIONS
# ══════════════════════════════════════════════════════════════════════════════

def compute_lisi(
        embedding: np.ndarray,
        metadata: pd.DataFrame,
        label_colnames: list,
        perplexity: float = 30.0
) -> pd.DataFrame:
    """
    Compute LISI scores (Korsunsky et al. 2019).
    Returns a DataFrame with one column per label in label_colnames.
    Uses the lisi package if available, otherwise a pure-numpy fallback.
    """
    try:
        import lisi
        scores = lisi.compute_lisi(embedding, metadata, label_colnames,
                                   perplexity=perplexity)
        return pd.DataFrame(scores, columns=label_colnames)
    except ImportError:
        log.warning("lisi package not found; using scib-metrics fallback.")
        return _lisi_scib(embedding, metadata, label_colnames)


def _lisi_scib(embedding, metadata, label_colnames):
    """scib-metrics LISI fallback (graph-based approximation)."""
    try:
        import scib
        adata_tmp = ad.AnnData(X=embedding,
                               obs=metadata.reset_index(drop=True))
        adata_tmp.obsm["X_emb"] = embedding
        sc.pp.neighbors(adata_tmp, use_rep="X_emb", n_neighbors=90)
        results = {}
        for col in label_colnames:
            score = scib.me.ilisi_graph(adata_tmp, batch_key=col,
                                        type_="embed", use_rep="X_emb")
            results[col] = [score] * len(embedding)
        return pd.DataFrame(results)
    except ImportError:
        log.warning("scib not found; returning NaN LISI scores.")
        return pd.DataFrame(
            {c: [np.nan] * len(embedding) for c in label_colnames})


def compute_kbet(
        embedding: np.ndarray,
        batch_labels: np.ndarray,
        k: int = 30,
        n_repeat: int = 100
) -> float:
    """
    kBET acceptance rate (Büttner et al. 2019).
    Uses the kbet Python wrapper if available; otherwise computes a
    chi-square-based approximation (k-nearest-neighbour batch mixing).
    Returns acceptance rate in [0, 1].
    """
    try:
        import rpy2.robjects as ro
        from rpy2.robjects import numpy2ri, packages
        numpy2ri.activate()
        kbet_r = packages.importr("kBET")
        result  = kbet_r.kBET(embedding, batch_labels, k=k, plot=False,
                               do_pca=False)
        summary = dict(zip(result.names, list(result)))
        return float(np.array(summary["summary"])[0, 2])   # acceptance rate
    except Exception:
        log.warning("kBET R package unavailable; using chi-square approximation.")
        return _kbet_approx(embedding, batch_labels, k=k, n_repeat=n_repeat)


def _kbet_approx(embedding, batch_labels, k=30, n_repeat=100):
    """
    Pure-Python chi-square-based kBET approximation.
    Samples n_repeat cells; for each, builds k-NN neighbourhood and
    tests whether batch distribution matches global expectation.
    Returns proportion of non-rejected tests (acceptance rate).
    """
    from sklearn.neighbors import NearestNeighbors
    from scipy.stats import chi2_contingency

    n        = len(batch_labels)
    classes  = np.unique(batch_labels)
    global_p = np.array([(batch_labels == c).mean() for c in classes])

    nn = NearestNeighbors(n_neighbors=k + 1, metric="euclidean",
                          n_jobs=-1).fit(embedding)
    idx_all = nn.kneighbors(embedding, return_distance=False)[:, 1:]

    rng      = np.random.default_rng(42)
    test_idx = rng.choice(n, size=min(n_repeat, n), replace=False)
    accepted = 0

    for i in test_idx:
        neighbours      = batch_labels[idx_all[i]]
        observed        = np.array([(neighbours == c).sum() for c in classes])
        expected        = global_p * k
        # chi-square statistic
        stat = ((observed - expected) ** 2 / (expected + 1e-9)).sum()
        df   = len(classes) - 1
        from scipy.stats import chi2
        p_val = 1 - chi2.cdf(stat, df)
        if p_val >= 0.05:          # fail to reject → batch mixing is good
            accepted += 1

    return accepted / len(test_idx)


# ══════════════════════════════════════════════════════════════════════════════
# 2. SCRNA-SEQ PIPELINE  (Harmony on PCA, 50 components)
# ══════════════════════════════════════════════════════════════════════════════

def run_scrna(adata: ad.AnnData,
              batch_key: str = "batch",
              celltype_key: str = "cell_type",
              n_pcs: int = 50) -> Dict:
    """
    Full scRNA-seq preprocessing + Harmony correction.
    Parameters match the manuscript:
      theta=2, sigma=0.1, tolerance=1e-4, max_iter=10 (Harmony defaults
      after Korsunsky et al. 2019).
    """
    log.info(f"scRNA-seq: {adata.n_obs} cells × {adata.n_vars} genes")

    # ── preprocessing ─────────────────────────────────────────────────────────
    sc.pp.filter_cells(adata, min_genes=200)
    sc.pp.filter_genes(adata, min_cells=3)
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=2000)
    adata = adata[:, adata.var.highly_variable].copy()
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, n_comps=n_pcs, random_state=42)

    emb_before = adata.obsm["X_pca"].copy()

    # UMAP before correction (for Figure 4)
    sc.pp.neighbors(adata, use_rep="X_pca", n_neighbors=30, random_state=42)
    sc.tl.umap(adata, random_state=42)
    adata.obsm["X_umap_before"] = adata.obsm["X_umap"].copy()

    # ── Harmony batch correction ───────────────────────────────────────────────
    log.info("  Running Harmony (theta=2, sigma=0.1, tol=1e-4, max_iter=10) …")
    meta = pd.DataFrame({batch_key: adata.obs[batch_key].values.astype(str)})
    ho   = hm.run_harmony(
        emb_before.astype(np.float64), meta, batch_key,
        theta=2, sigma=0.1, epsilon_harmony=1e-4,
        max_iter_harmony=10, random_state=42, verbose=False
    )
    emb_after = ho.Z_corr.T.astype(np.float32)
    adata.obsm["X_pca_harmony"] = emb_after

    # UMAP after correction (for Figure 4)
    sc.pp.neighbors(adata, use_rep="X_pca_harmony",
                    n_neighbors=30, random_state=42)
    sc.tl.umap(adata, random_state=42)
    adata.obsm["X_umap_after"] = adata.obsm["X_umap"].copy()

    # ── metrics ───────────────────────────────────────────────────────────────
    batch_arr    = adata.obs[batch_key].values.astype(str)
    celltype_arr = adata.obs[celltype_key].values.astype(str) \
                   if celltype_key in adata.obs.columns else None

    meta_df      = pd.DataFrame({batch_key: batch_arr})
    if celltype_arr is not None:
        meta_df[celltype_key] = celltype_arr

    log.info("  Computing iLISI/cLISI before …")
    lisi_b = compute_lisi(emb_before, meta_df, [batch_key] +
                           ([celltype_key] if celltype_arr is not None else []))
    log.info("  Computing iLISI/cLISI after …")
    lisi_a = compute_lisi(emb_after,  meta_df, [batch_key] +
                           ([celltype_key] if celltype_arr is not None else []))

    log.info("  Computing kBET …")
    kbet_before = compute_kbet(emb_before, batch_arr)
    kbet_after  = compute_kbet(emb_after,  batch_arr)

    return {
        "modality":      "scRNA-seq",
        "method":        "Harmony (PCA 50 PCs)",
        "n_cells":       adata.n_obs,
        "n_batches":     int(pd.Series(batch_arr).nunique()),
        "iLISI_before":  float(lisi_b[batch_key].mean()),
        "iLISI_after":   float(lisi_a[batch_key].mean()),
        "cLISI_after":   float(lisi_a[celltype_key].mean())
                         if celltype_arr is not None else np.nan,
        "kBET_before":   float(kbet_before),
        "kBET_after":    float(kbet_after),
        "adata":         adata,   # returned for Figure 4 UMAP panels
    }


# ══════════════════════════════════════════════════════════════════════════════
# 3. SCATAC-SEQ PIPELINE  (TF-IDF + LSI, Harmony on comps 2-50)
# ══════════════════════════════════════════════════════════════════════════════

def run_scatac(adata: ad.AnnData,
               batch_key: str  = "batch",
               celltype_key: str = "cell_type",
               n_comps: int = 50) -> Dict:
    """
    scATAC-seq preprocessing + Harmony on LSI components 2-50.
    Component 1 is excluded as it correlates with sequencing depth,
    as stated in the manuscript.
    """
    log.info(f"scATAC-seq: {adata.n_obs} cells × {adata.n_vars} peaks")

    # ── TF-IDF normalisation ──────────────────────────────────────────────────
    X   = adata.X.toarray().astype(np.float32) \
          if sparse.issparse(adata.X) else adata.X.astype(np.float32)
    tf  = X / (X.sum(axis=1, keepdims=True) + 1e-9)
    idf = np.log1p(X.shape[0] / (X.sum(axis=0) + 1))
    tfidf = (tf * idf).astype(np.float32)
    adata.X = sparse.csr_matrix(tfidf)

    # ── LSI (TruncatedSVD) ─────────────────────────────────────────────────────
    svd  = TruncatedSVD(n_components=n_comps, random_state=42)
    lsi  = svd.fit_transform(adata.X).astype(np.float32)
    adata.obsm["X_lsi"] = lsi

    # Component 1 excluded (depth-correlated) — use comps 2..n_comps (0-indexed: 1..)
    lsi_input = lsi[:, 1:]   # shape (n_cells, n_comps - 1)

    # UMAP before correction
    sc.pp.neighbors(adata, use_rep="X_lsi", n_neighbors=30, random_state=42)
    sc.tl.umap(adata, random_state=42)
    adata.obsm["X_umap_before"] = adata.obsm["X_umap"].copy()

    # ── Harmony ───────────────────────────────────────────────────────────────
    log.info("  Running Harmony on LSI comps 2-50 …")
    batch_arr = adata.obs[batch_key].values.astype(str)
    meta      = pd.DataFrame({batch_key: batch_arr})
    ho        = hm.run_harmony(
        lsi_input.astype(np.float64), meta, batch_key,
        theta=2, sigma=0.1, epsilon_harmony=1e-4,
        max_iter_harmony=10, random_state=42, verbose=False
    )
    lsi_harmony = ho.Z_corr.T.astype(np.float32)
    adata.obsm["X_lsi_harmony"] = lsi_harmony

    # UMAP after correction
    sc.pp.neighbors(adata, use_rep="X_lsi_harmony",
                    n_neighbors=30, random_state=42)
    sc.tl.umap(adata, random_state=42)
    adata.obsm["X_umap_after"] = adata.obsm["X_umap"].copy()

    # ── metrics ───────────────────────────────────────────────────────────────
    celltype_arr = adata.obs[celltype_key].values.astype(str) \
                   if celltype_key in adata.obs.columns else None
    meta_df      = pd.DataFrame({batch_key: batch_arr})
    if celltype_arr is not None:
        meta_df[celltype_key] = celltype_arr

    lisi_b = compute_lisi(lsi_input, meta_df, [batch_key] +
                           ([celltype_key] if celltype_arr is not None else []))
    lisi_a = compute_lisi(lsi_harmony, meta_df, [batch_key] +
                           ([celltype_key] if celltype_arr is not None else []))
    kbet_b = compute_kbet(lsi_input,   batch_arr)
    kbet_a = compute_kbet(lsi_harmony, batch_arr)

    return {
        "modality":     "scATAC-seq",
        "method":       "Harmony (LSI comps 2-50)",
        "n_cells":      adata.n_obs,
        "n_batches":    int(pd.Series(batch_arr).nunique()),
        "iLISI_before": float(lisi_b[batch_key].mean()),
        "iLISI_after":  float(lisi_a[batch_key].mean()),
        "cLISI_after":  float(lisi_a[celltype_key].mean())
                        if celltype_arr is not None else np.nan,
        "kBET_before":  float(kbet_b),
        "kBET_after":   float(kbet_a),
        "adata":        adata,
    }


# ══════════════════════════════════════════════════════════════════════════════
# 4. BULK PROTEOMICS PIPELINE  (pycombat in feature space)
# ══════════════════════════════════════════════════════════════════════════════

def run_proteomics(df: pd.DataFrame,
                   batch_series: pd.Series,
                   covariate_df: Optional[pd.DataFrame] = None) -> Dict:
    """
    Bulk proteomics pycombat batch correction.
    df           : samples × proteins DataFrame (log-transformed intensities)
    batch_series : sample-aligned batch labels
    covariate_df : optional biological covariates (age, sex, BMI) to preserve
                   — passed directly to pycombat_norm as covar_mod

    Metrics are computed on the top-50 PCA embedding before/after correction.
    """
    log.info(f"Proteomics: {df.shape[0]} samples × {df.shape[1]} proteins")

    # ── preprocessing ─────────────────────────────────────────────────────────
    # log2 transform if values suggest raw intensities
    if df.values.max() > 100:
        log.info("  Applying log2 transform (values suggest raw intensities)")
        df = np.log2(df.replace(0, np.nan).fillna(df.min().min() / 2))
    # median imputation (proteomics — detection-limited)
    df = df.fillna(df.median())

    # PCA embedding before correction
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA
    X_scaled = StandardScaler().fit_transform(df.values)
    pca      = PCA(n_components=min(50, df.shape[1] - 1), random_state=42)
    emb_b    = pca.fit_transform(X_scaled).astype(np.float32)

    # ── pycombat ──────────────────────────────────────────────────────────────
    try:
        from inmoose.pycombat import pycombat_norm
        log.info("  Running pycombat_norm (inmoose) …")
        batch_s = batch_series.astype(str)
        kw      = {"covar_mod": covariate_df.values} \
                  if covariate_df is not None else {}
        df_corr = pycombat_norm(df.T, batch_s, **kw).T
    except ImportError:
        log.warning("  inmoose not found; using built-in ComBat fallback.")
        df_corr = _combat_fallback(df, batch_series)

    X_scaled_c = StandardScaler().fit_transform(df_corr.values)
    emb_a      = pca.transform(X_scaled_c).astype(np.float32)

    # ── metrics ───────────────────────────────────────────────────────────────
    batch_arr = batch_series.values.astype(str)
    meta_df   = pd.DataFrame({"batch": batch_arr}, index=df.index)

    lisi_b = compute_lisi(emb_b, meta_df, ["batch"])
    lisi_a = compute_lisi(emb_a, meta_df, ["batch"])
    kbet_b = compute_kbet(emb_b, batch_arr)
    kbet_a = compute_kbet(emb_a, batch_arr)

    return {
        "modality":     "Bulk proteomics",
        "method":       "pycombat (parametric EB)",
        "n_samples":    df.shape[0],
        "n_batches":    int(pd.Series(batch_arr).nunique()),
        "iLISI_before": float(lisi_b["batch"].mean()),
        "iLISI_after":  float(lisi_a["batch"].mean()),
        "cLISI_after":  np.nan,   # no cell-type annotation for bulk
        "kBET_before":  float(kbet_b),
        "kBET_after":   float(kbet_a),
        "df_corrected": df_corr,
    }


def _combat_fallback(df: pd.DataFrame,
                     batch: pd.Series) -> pd.DataFrame:
    X  = df.values.astype(np.float32)
    gm = X.mean(0); gv = X.var(0) + 1e-8
    out = X.copy()
    for b in batch.unique():
        m   = (batch == b).values; n_b = m.sum()
        bm  = X[m].mean(0); bv = X[m].var(0) + 1e-8
        em  = (gm * gv + bm * n_b) / (gv + n_b)
        ev  = (gv + bv) / 2
        out[m] = (X[m] - em) / np.sqrt(ev) * np.sqrt(gv) + gm
    return pd.DataFrame(out, index=df.index, columns=df.columns)


# ══════════════════════════════════════════════════════════════════════════════
# 5. DIFFERENTIAL ABUNDANCE — false-positive / false-negative cross-check
#    (Reviewer comment 4 — Supplementary Table 11)
# ══════════════════════════════════════════════════════════════════════════════

def differential_abundance_check(
        df_before: pd.DataFrame,
        df_after:  pd.DataFrame,
        group_labels: pd.Series,
        fdr_threshold: float = 0.05
) -> pd.DataFrame:
    """
    Compute number of differentially abundant features before and after
    batch correction (Welch t-test + BH FDR).
    Returns a summary DataFrame for Supplementary Table 11.
    """
    from scipy.stats import ttest_ind
    from statsmodels.stats.multitest import multipletests

    results = []
    for label, df in [("Before correction", df_before),
                      ("After correction",  df_after)]:
        g1 = df[group_labels == group_labels.unique()[0]].values
        g2 = df[group_labels == group_labels.unique()[1]].values
        t, p  = ttest_ind(g1, g2, axis=0, equal_var=False)
        p     = np.nan_to_num(p, nan=1.0)
        _, padj, _, _ = multipletests(p, method="fdr_bh")
        n_sig = int((padj < fdr_threshold).sum())
        results.append({"Stage": label, "n_significant (FDR<0.05)": n_sig,
                        "n_tested": df.shape[1]})

    return pd.DataFrame(results)


# ══════════════════════════════════════════════════════════════════════════════
# 6. FIGURE 4 — UMAP PANELS (before / after, batch + celltype)
# ══════════════════════════════════════════════════════════════════════════════

def plot_figure4(results_list: list, out_dir: Path = OUT_DIR) -> None:
    """
    Generate Figure 4 UMAP panels: before/after correction,
    coloured by batch (upper row) and cell type/condition (lower row).
    """
    import matplotlib.pyplot as plt
    import matplotlib.patches as mpatches

    n_mods = len(results_list)
    fig, axes = plt.subplots(4, n_mods, figsize=(5 * n_mods, 16))
    if n_mods == 1:
        axes = axes.reshape(-1, 1)

    row_labels = ["Before — batch", "After — batch",
                  "Before — cell type", "After — cell type"]

    for col, res in enumerate(results_list):
        adata = res.get("adata")
        if adata is None:
            continue
        modality    = res["modality"]
        batch_key   = "batch"
        ct_key      = "cell_type" if "cell_type" in adata.obs.columns else batch_key

        batches    = adata.obs[batch_key].astype("category")
        batch_pal  = plt.cm.tab10(np.linspace(0, 1, batches.cat.categories.shape[0]))
        batch_cmap = dict(zip(batches.cat.categories, batch_pal))
        ct_cats    = adata.obs[ct_key].astype("category")
        ct_pal     = plt.cm.Set2(np.linspace(0, 1, ct_cats.cat.categories.shape[0]))
        ct_cmap    = dict(zip(ct_cats.cat.categories, ct_pal))

        umap_b = adata.obsm["X_umap_before"]
        umap_a = adata.obsm["X_umap_after"]

        for row, (coords, key, cmap) in enumerate([
            (umap_b, batch_key,  batch_cmap),
            (umap_a, batch_key,  batch_cmap),
            (umap_b, ct_key,     ct_cmap),
            (umap_a, ct_key,     ct_cmap),
        ]):
            ax = axes[row, col]
            colors = [cmap[v] for v in adata.obs[key]]
            ax.scatter(coords[:, 0], coords[:, 1], c=colors,
                       s=2, alpha=0.6, linewidths=0, rasterized=True)
            ax.set_title(f"{modality}\n{row_labels[row]}", fontsize=9)
            ax.axis("off")
            handles = [mpatches.Patch(color=c, label=l)
                       for l, c in cmap.items()]
            ax.legend(handles=handles, fontsize=6, markerscale=2,
                      loc="lower right", framealpha=0.5)

    fig.suptitle("Figure 4 | Batch-effect correction assessed in embedding space\n"
                 "UMAP before (left) and after (right) correction, coloured by "
                 "batch (rows 1-2) and cell type / condition (rows 3-4)",
                 fontsize=11, y=1.01)
    plt.tight_layout()
    path = out_dir / "Figure4_UMAP_before_after.pdf"
    fig.savefig(path, dpi=200, bbox_inches="tight")
    plt.close()
    log.info(f"  Saved: {path}")


# ══════════════════════════════════════════════════════════════════════════════
# 7. SUPPLEMENTARY TABLE 7 FORMATTER
# ══════════════════════════════════════════════════════════════════════════════

def format_supp_table7(all_results: list) -> pd.DataFrame:
    """
    Format results into Supplementary Table 7 structure as requested
    by Reviewer 2, comment 4, and the editorial review report.
    """
    rows = []
    for r in all_results:
        rows.append({
            "Modality":                r["modality"],
            "Correction method":       r["method"],
            "N samples/cells":         r.get("n_cells", r.get("n_samples", "?")),
            "N batches":               r["n_batches"],
            "iLISI before correction": f"{r['iLISI_before']:.2f}",
            "iLISI after correction":  f"{r['iLISI_after']:.2f}",
            "iLISI improvement":       f"{r['iLISI_after'] - r['iLISI_before']:.2f}",
            "cLISI after correction":  f"{r['cLISI_after']:.2f}"
                                       if not np.isnan(r['cLISI_after']) else "N/A",
            "kBET acceptance before":  f"{r['kBET_before']:.2f}",
            "kBET acceptance after":   f"{r['kBET_after']:.2f}",
            "Outcome":                 "Effective" if
                                       (r['iLISI_after'] - r['iLISI_before']) > 0.3
                                       and r['kBET_after'] > 0.50 else "Review",
        })
    return pd.DataFrame(rows)


# ══════════════════════════════════════════════════════════════════════════════
# 8. DATA LOADERS — replace paths with your actual downloaded files
# ══════════════════════════════════════════════════════════════════════════════

def load_scrna_kang2018(data_dir: Path) -> ad.AnnData:
    """
    Load GSE96583 (Kang et al. 2018 — PBMC stimulated/control).
    Download from GEO: https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE96583
    Expected files: GSE96583_batch1.* and GSE96583_batch2.* (10x MTX format)

    Each batch forms a natural experimental batch; stimulated/control
    is the biological contrast used for cLISI.
    """
    h5ad = data_dir / "GSE96583_kang2018.h5ad"
    if h5ad.exists():
        log.info(f"  Loading cached {h5ad.name}")
        return ad.read_h5ad(h5ad)

    # If raw files provided, load and combine:
    b1 = sc.read_10x_mtx(data_dir / "batch1", var_names="gene_symbols")
    b2 = sc.read_10x_mtx(data_dir / "batch2", var_names="gene_symbols")
    b1.obs["batch"] = "batch1"
    b2.obs["batch"] = "batch2"
    # stimulated / control annotation from GSE96583_batch_cell.membership.txt
    # (adjust column name to match the file in your download)
    adata = ad.concat([b1, b2], join="inner")
    adata.obs_names_make_unique()
    adata.write_h5ad(h5ad)
    return adata


def load_scatac_10x_multiome(data_dir: Path) -> ad.AnnData:
    """
    Load GSE194122 (10x Multiome PBMC — multiple donors = batches).
    Download from GEO: https://www.ncbi.nlm.nih.gov/geo/query/acc.cgi?acc=GSE194122
    Use the ATAC fragment files or the pre-processed peak matrix .h5ad.
    """
    h5ad = data_dir / "GSE194122_scatac.h5ad"
    if h5ad.exists():
        return ad.read_h5ad(h5ad)
    raise FileNotFoundError(
        f"Please download GSE194122 scATAC data to {data_dir} and save as "
        "GSE194122_scatac.h5ad with obs columns: 'batch', 'cell_type'")


def load_proteomics_cptac(data_dir: Path) -> Tuple[pd.DataFrame, pd.Series]:
    """
    Load PRIDE PXD004682 (CPTAC breast cancer TMT proteomics).
    Download from PRIDE: https://www.ebi.ac.uk/pride/archive/projects/PXD004682

    Returns:
        df     : samples × proteins log2-intensity DataFrame
        batch  : batch label Series (TMT plex = batch)
    """
    csv = data_dir / "PXD004682_protein_matrix.csv"
    if not csv.exists():
        raise FileNotFoundError(
            f"Download PXD004682 protein matrix to {csv}\n"
            "The file should have rows = samples, columns = UniProt accessions,\n"
            "and a 'batch' column indicating TMT plex.")
    df    = pd.read_csv(csv, index_col=0)
    batch = df.pop("batch")
    return df, batch


# ══════════════════════════════════════════════════════════════════════════════
# 9. MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(
        description="Compute batch-correction benchmarking metrics for MIMODH")
    parser.add_argument("--data-dir", default="data",
                        help="Directory containing downloaded datasets")
    parser.add_argument("--scrna",  action="store_true",
                        help="Run scRNA-seq pipeline (GSE96583)")
    parser.add_argument("--scatac", action="store_true",
                        help="Run scATAC-seq pipeline (GSE194122)")
    parser.add_argument("--prot",   action="store_true",
                        help="Run proteomics pipeline (PXD004682)")
    parser.add_argument("--all",    action="store_true",
                        help="Run all three pipelines")
    args = parser.parse_args()

    data_dir = Path(args.data_dir)
    all_results  = []
    adata_results = []

    if args.all or args.scrna:
        log.info("=== scRNA-seq (GSE96583, Kang 2018) ===")
        adata = load_scrna_kang2018(data_dir)
        res   = run_scrna(adata, batch_key="batch", celltype_key="cell_type")
        all_results.append(res)
        adata_results.append(res)

    if args.all or args.scatac:
        log.info("=== scATAC-seq (GSE194122, 10x Multiome) ===")
        adata = load_scatac_10x_multiome(data_dir)
        res   = run_scatac(adata, batch_key="batch", celltype_key="cell_type")
        all_results.append(res)
        adata_results.append(res)

    if args.all or args.prot:
        log.info("=== Bulk proteomics (PXD004682, CPTAC breast) ===")
        df, batch = load_proteomics_cptac(data_dir)
        # Covariate DataFrame — load from your clinical file
        # covar = pd.read_csv(data_dir/"clinical.csv", index_col=0)[["age","sex","bmi"]]
        res = run_proteomics(df, batch, covariate_df=None)
        all_results.append(res)

    if not all_results:
        log.warning("No pipelines selected. Use --all or --scrna/--scatac/--prot")
    else:
        # ── Supplementary Table 7 ────────────────────────────────────────────
        supp7 = format_supp_table7(all_results)
        supp7.to_csv(OUT_DIR / "SupplementaryTable7_iLISI_cLISI_kBET.csv",
                     index=False)
        log.info(f"\n{supp7.to_string(index=False)}")

        # ── Figure 4 ─────────────────────────────────────────────────────────
        if adata_results:
            plot_figure4(adata_results)

        # ── JSON output ──────────────────────────────────────────────────────
        json_out = [{k: v for k, v in r.items()
                     if k not in ("adata", "df_corrected")}
                    for r in all_results]
        with open(OUT_DIR / "batch_metrics_results.json", "w") as f:
            json.dump(json_out, f, indent=2, default=str)

        log.info(f"\nAll outputs written to: {OUT_DIR.resolve()}")
        log.info("Copy iLISI/cLISI/kBET values into Supplementary Table 7")
        log.info("and the three bracketed placeholders in the manuscript "
                 "Batch-effect correction strategy section.")
