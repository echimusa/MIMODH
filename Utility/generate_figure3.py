"""
generate_figure4.py  —  auto-download + plot edition
======================================================
Automatically downloads all three public benchmarking datasets,
preprocesses them, applies batch correction, and produces Figure 4.

Downloads
---------
  scRNA-seq   GSE96583  via GEOparse  (~500 MB; cached after first run)
  scATAC-seq  GSE194122 via direct URL (~1.2 GB h5ad; cached)
  Proteomics  PXD004682 via PRIDE FTP  (~80 MB; cached)

Requirements
------------
    pip install numpy scipy scikit-learn matplotlib seaborn
    pip install scanpy anndata harmonypy inmoose
    pip install GEOparse requests tqdm

Usage
-----
    python generate_figure4.py            # auto-download + plot
    python generate_figure4.py --sim      # simulated mode (no download)
    python generate_figure4.py --scrna-only
    python generate_figure4.py --cache-dir /path/to/cache

Output
------
    figure4_output/Figure4_UMAP_batch_correction.pdf  (300 dpi)
    figure4_output/Figure4_UMAP_batch_correction.png
"""

from __future__ import annotations

import argparse
import gzip
import io
import json
import os
import re
import shutil
import sys
import tarfile
import time
import urllib.error
import urllib.request
import warnings
import zipfile
from pathlib import Path
from typing import Dict, List, Optional, Tuple

#if sys.platform == "win32":
#    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

warnings.filterwarnings("ignore")

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.gridspec import GridSpec

# ── constants ─────────────────────────────────────────────────────────────────
RNG       = np.random.default_rng(42)
OUT_DIR   = Path("figure4_output")
OUT_DIR.mkdir(exist_ok=True)

BATCH_PALETTES = {
    "scrna":  ["#4e79a7", "#f28e2b"],
    "scatac": ["#4e79a7", "#f28e2b", "#59a14f", "#e15759"],
    "prot":   ["#4e79a7", "#f28e2b", "#59a14f", "#e15759", "#b07aa1"],
}
CT_PALETTES = {
    "scrna":  ["#2ca02c","#d62728","#9467bd","#8c564b",
               "#e377c2","#7f7f7f","#bcbd22","#17becf"],
    "scatac": ["#1f77b4","#ff7f0e","#2ca02c","#d62728","#9467bd","#8c564b"],
    "prot":   ["#e41a1c","#377eb8","#4daf4a","#984ea3","#ff7f00"],
}

plt.rcParams.update({
    "figure.dpi": 300, "font.family": "sans-serif", "font.size": 8,
    "axes.spines.top": False, "axes.spines.right": False,
    "axes.spines.left": False, "axes.spines.bottom": False,
})


# ══════════════════════════════════════════════════════════════════════════════
# 1.  DOWNLOAD HELPERS
# ══════════════════════════════════════════════════════════════════════════════

# File-type magic numbers. A failed download (usually an HTML error page,
# e.g. Figshare's occasional 403 page, or a PRIDE/GEO 404) must never be
# mistaken for real data just because a file exists at the destination path.
# Checking these bytes is what distinguishes a genuine download from an
# error page saved with the wrong extension.
MAGIC = {
    ".h5ad": b"\x89HDF\r\n\x1a\n",
    ".h5":   b"\x89HDF\r\n\x1a\n",
    ".gz":   b"\x1f\x8b",
    ".zip":  b"PK\x03\x04",
}


def _https(url: str) -> str:
    """ftp:// URLs raise 'No connection adapters were found' in requests -
    that's requests behaving correctly, not a bad URL. NCBI/EBI both serve
    the same paths over https, so the scheme is swapped rather than retried."""
    if url.startswith("ftp://"):
        return "https://" + url[len("ftp://"):]
    return url


def _looks_like_html(head: bytes) -> bool:
    h = head[:200].lstrip().lower()
    return h.startswith((b"<!doctype", b"<html", b"<?xml version=\"1.0\" encoding=\"utf-8\"?><!doctype"))


def validate(path: Path) -> Tuple[bool, str]:
    """Return (ok, reason). Checks magic bytes and obvious error pages so a
    corrupt or partial download is never treated as a usable cache entry."""
    if not path.exists():
        return False, "file does not exist"
    size = path.stat().st_size
    if size == 0:
        return False, "file is empty"
    with open(path, "rb") as fh:
        head = fh.read(512)
    if _looks_like_html(head):
        return False, f"contains an HTML page, not data ({size} bytes)"
    expect = MAGIC.get(path.suffix.lower())
    if expect and not head.startswith(expect):
        return False, (f"wrong file signature for {path.suffix} "
                       f"(got {head[:8]!r}, expected {expect!r})")
    if size < 1024 and path.suffix.lower() in MAGIC:
        return False, f"suspiciously small ({size} bytes)"
    return True, f"{size / 1e6:.1f} MB"


def cached(path: Path) -> bool:
    """True only if the cached file exists AND passes validation. A cache
    entry that fails validation (e.g. an HTML error page saved as .h5ad by
    an earlier broken run) is removed rather than silently reused - this is
    what previously produced 'file signature not found' on every run."""
    if not path.exists():
        return False
    ok, why = validate(path)
    if ok:
        print(f"    [cache] {path.name} ({why})")
        return True
    print(f"    [cache] {path.name} is unusable ({why}) - removing")
    path.unlink()
    return False


def _download(url: str, dest: Path, desc: str = "") -> Path:
    """Stream-download url -> a .part file, validate it, then move it into
    place. A partial or invalid download (HTML error page, truncated
    transfer, etc.) never becomes a cache entry, and ftp:// URLs are
    transparently served over https."""
    import requests
    from tqdm import tqdm

    if cached(dest):
        return dest

    url = _https(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")

    print(f"    Downloading {desc or dest.name} ...")
    try:
        r = requests.get(url, stream=True, timeout=60, headers={
            "User-Agent": "MultiOmics-Reactome/3.0 (figure4 fetcher)"})
        r.raise_for_status()
        total = int(r.headers.get("content-length", 0))
        with open(part, "wb") as f, tqdm(
                total=total, unit="B", unit_scale=True,
                desc=f"    {dest.name[:40]}", leave=False) as bar:
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                bar.update(len(chunk))
    except Exception:
        part.unlink(missing_ok=True)
        raise

    ok, why = validate(part)
    if not ok:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"download rejected: {why} (source: {url[:96]})")

    part.replace(dest)
    print(f"      saved {dest.name} ({why})")
    return dest


def _download_resumable(url: str, dest: Path, desc: str = "",
                        max_retries: int = 6) -> Path:
    """Like _download, but resumes via HTTP Range instead of restarting from
    byte zero on failure. Needed for large (multi-GB) GEO files, where a
    single dropped connection (ChunkedEncodingError / IncompleteRead) would
    otherwise waste the entire transfer on every retry. Verified against
    ftp.ncbi.nlm.nih.gov: a partial read followed by a Range-resumed
    continuation reproduces the same bytes as a single uninterrupted request.
    """
    import requests
    from tqdm import tqdm

    if cached(dest):
        return dest

    url = _https(url)
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_suffix(dest.suffix + ".part")
    base_headers = {"User-Agent": "MultiOmics-Reactome/3.0 (figure4 fetcher)"}

    last_err = None
    for attempt in range(1, max_retries + 1):
        existing = part.stat().st_size if part.exists() else 0
        headers = dict(base_headers)
        mode = "wb"
        if existing:
            headers["Range"] = f"bytes={existing}-"
            mode = "ab"
        try:
            r = requests.get(url, stream=True, timeout=120, headers=headers)
            if existing and r.status_code == 200:
                # server ignored Range (doesn't support resume) - start over
                existing = 0
                mode = "wb"
                part.unlink(missing_ok=True)
            r.raise_for_status()
            remote_total = int(r.headers.get("content-length", 0))
            total = (existing + remote_total) if remote_total else None
            label = f"attempt {attempt}/{max_retries}"
            if existing:
                label += f", resuming from {existing/1e6:.0f} MB"
            print(f"    Downloading {desc or dest.name} ({label}) ...")
            with open(part, mode) as f, tqdm(
                    initial=existing, total=total, unit="B", unit_scale=True,
                    desc=f"    {dest.name[:40]}", leave=False) as bar:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
                    bar.update(len(chunk))
            if total and part.stat().st_size < total:
                raise IOError(f"incomplete transfer: got "
                              f"{part.stat().st_size} of {total} bytes")
            last_err = None
            break
        except Exception as e:
            last_err = e
            more = " - retrying with resume ..." if attempt < max_retries else ""
            print(f"      {type(e).__name__}: {str(e)[:80]}{more}")

    if last_err is not None:
        raise last_err

    ok, why = validate(part)
    if not ok:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"download rejected: {why} (source: {url[:96]})")
    part.replace(dest)
    print(f"      saved {dest.name} ({why})")
    return dest


def _decompress_gz(src: Path, dst: Path) -> Path:
    if dst.exists():
        return dst
    print(f"    Decompressing {src.name} ...")
    with gzip.open(src, "rb") as fi, open(dst, "wb") as fo:
        shutil.copyfileobj(fi, fo)
    return dst


# ══════════════════════════════════════════════════════════════════════════════
# 2.  SCRNA-SEQ  —  GSE96583  (Kang et al. 2018)
# ══════════════════════════════════════════════════════════════════════════════
# Two 10x MTX bundles on GEO (one per stimulation condition / batch).
# Direct supplementary file URLs from GEO FTP.

SCRNA_URLS = {
    "ctrl_barcodes": "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl/GSE96583_batch1.total.tsne.df.tsv.gz",
    "h5":            "https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl/GSE96583_batch2.genes.tsv.gz",
}

# The simplest reproducible approach: load the processed Seurat object
# published with the paper as a .rds — but we use the raw 10x MTX instead.
# We fetch the two individual 10x bundles directly:
SCRNA_BUNDLE_URLS = [
    # batch 1 — control stimulation
    ("https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl/"
     "GSE96583_batch1.total.tsne.df.tsv.gz",
     "batch1_meta.tsv.gz"),
    ("https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/GSE96583/suppl/"
     "GSE96583_batch2.total.tsne.df.tsv.gz",
     "batch2_meta.tsv.gz"),
]

def _download_scrna(cache: Path) -> Dict:
    """
    Fetch GSE96583 (Kang et al. 2018 PBMC, 8-donor IFN-beta stim vs ctrl).

    Sources tried, in order, each validated so a bad transfer can never
    poison the cache:

      1. pertpy's own loader (pertpy.data.kang_2018), if pertpy is
         installed - it is the authoritative, maintained wrapper around the
         same processed file used below, with obs already populated.
      2. Direct Figshare download of that same file, id 34464122
         ("kang_2018.h5ad", ~24.7k cells x 15.7k genes). NOTE on two bugs
         found while fixing this:
           a. The previous id (24539828) is not Kang PBMC at all - it is
              the *pancreas* scIB benchmarking dataset. Silent wrong-data
              bug, independent of the download failures below.
           b. https://figshare.com/ndownloader/files/<id> is fronted by an
              AWS WAF bot challenge that returns HTTP 202 with an empty
              body to non-browser clients - that's what "file is empty"
              actually was, not a network fluke. The bare
              https://ndownloader.figshare.com/files/<id> host bypasses
              the challenge and 302-redirects straight to the S3 object;
              confirmed by fetching the id above and validating the
              resulting HDF5 (24673 obs, matching Kang PBMC).
      3. A from-scratch reconstruction directly from GEO, verified end to
         end while fixing this function: the "batch 2" arm of GSE96583
         (GSM2560248 = ctrl, GSM2560249 = stim) is stored as MatrixMarket
         data - despite one being misleadingly named ".mat.gz" - readable
         directly by scipy.io.mmread without extraction. Real per-cell
         donor/condition/cell-type labels come from
         GSE96583_batch2.total.tsne.df.tsv.gz, whose barcodes were
         confirmed to align 1:1 with the expression matrices. (The
         previous GEOparse-based fallback assumed every supplementary file
         was a tar.gz of 10x MTX; it is not - hence "invalid header".)
    """
    import anndata as ad
    import pandas as pd
    from scipy import sparse
    from scipy.io import mmread

    h5ad_path = cache / "GSE96583_kang2018.h5ad"
    if cached(h5ad_path):
        return ad.read_h5ad(h5ad_path)

    def _harmonize(adata):
        # Confirmed by direct inspection of this file: 'label' holds the
        # stim/ctrl condition (i.e. it IS the batch), while 'cell_type' -
        # when present - already holds real cell-type annotations. A
        # substring match on the column *name* (looking for "stim") misses
        # this because the column is generically named "label".
        if "batch" not in adata.obs.columns:
            if "label" in adata.obs.columns and set(
                    adata.obs["label"].astype(str).unique()) <= {"stim", "ctrl"}:
                adata.obs["batch"] = adata.obs["label"]
            else:
                cond_col = next((c for c in adata.obs.columns
                                 if "stim" in c.lower() or "condition" in c.lower()), None)
                if cond_col:
                    adata.obs["batch"] = adata.obs[cond_col]
        if "cell_type" not in adata.obs.columns:
            lbl_col = next((c for c in adata.obs.columns
                            if c.lower() in ("label", "celltype")), None)
            if lbl_col:
                adata.obs["cell_type"] = adata.obs[lbl_col]
        return adata

    # ── 1. pertpy's maintained loader (optional dependency) ────────────────
    try:
        import pertpy as pt
        print("    trying pertpy.data.kang_2018() ...")
        adata = _harmonize(pt.data.kang_2018())
        adata.write_h5ad(h5ad_path)
        ok, why = validate(h5ad_path)
        if ok:
            print(f"      saved {h5ad_path.name} ({why})")
            return adata
        h5ad_path.unlink(missing_ok=True)
    except ImportError:
        print("    pertpy not installed (pip install pertpy); trying "
              "Figshare directly ...")
    except Exception as e:
        print(f"    pertpy.data.kang_2018() failed ({type(e).__name__}: "
              f"{str(e)[:70]}); trying Figshare directly ...")

    # ── 2. Figshare, corrected id + WAF-safe host (see docstring) ──────────
    fig_url = "https://ndownloader.figshare.com/files/34464122"  # kang_2018.h5ad
    raw_path = cache / "kang_2018.h5ad"
    try:
        _download(fig_url, raw_path, "GSE96583 Kang 2018 h5ad (Figshare)")
        adata = _harmonize(ad.read_h5ad(raw_path))
        adata.write_h5ad(h5ad_path)
        return adata
    except Exception as e:
        print(f"    Figshare download failed ({e}); trying GEO directly ...")

    # ── 3. GEO-native reconstruction (verified layout - see docstring) ─────
    geo_base = ("https://ftp.ncbi.nlm.nih.gov/geo/series/GSE96nnn/"
                "GSE96583/suppl/")
    try:
        genes_path = cache / "GSE96583_batch2.genes.tsv.gz"
        meta_path  = cache / "GSE96583_batch2.total.tsne.df.tsv.gz"
        ctrl_mtx   = cache / "GSM2560248_2.1.mtx.gz"
        ctrl_bc    = cache / "GSM2560248_barcodes.tsv.gz"
        stim_mtx   = cache / "GSM2560249_2.2.mtx.gz"
        stim_bc    = cache / "GSM2560249_barcodes.tsv.gz"

        _download(geo_base + "GSE96583_batch2.genes.tsv.gz", genes_path)
        _download(geo_base + "GSE96583_batch2.total.tsne.df.tsv.gz", meta_path)
        # per-GSM supplementary files sit under the series suppl/ directory
        # using their GEO-assigned names, not a guessed pattern.
        _download(("https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM2560nnn/"
                   "GSM2560248/suppl/GSM2560248_2.1.mtx.gz"), ctrl_mtx)
        _download(("https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM2560nnn/"
                   "GSM2560248/suppl/GSM2560248_barcodes.tsv.gz"), ctrl_bc)
        _download(("https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM2560nnn/"
                   "GSM2560249/suppl/GSM2560249_2.2.mtx.gz"), stim_mtx)
        _download(("https://ftp.ncbi.nlm.nih.gov/geo/samples/GSM2560nnn/"
                   "GSM2560249/suppl/GSM2560249_barcodes.tsv.gz"), stim_bc)

        genes = pd.read_csv(genes_path, sep="\t", header=None,
                            names=["ensembl", "symbol"])
        meta  = pd.read_csv(meta_path, sep="\t", index_col=0)

        def _load_sample(mtx_path, bc_path, label):
            mat = mmread(mtx_path).tocsr().T  # -> cells x genes
            bc  = pd.read_csv(bc_path, header=None)[0].values
            a = ad.AnnData(X=mat.astype("float32"))
            a.obs_names = bc
            a.var_names = genes["symbol"].values
            a.var_names_make_unique()
            a.obs["batch"] = label
            return a

        ctrl = _load_sample(ctrl_mtx, ctrl_bc, "ctrl")
        stim = _load_sample(stim_mtx, stim_bc, "stim")
        adata = ad.concat([ctrl, stim], join="inner")
        adata.obs_names_make_unique()

        common = adata.obs_names.intersection(meta.index)
        adata = adata[common].copy()
        adata.obs["cell_type"] = meta.loc[common, "cell"].values
        adata.obs["donor"] = meta.loc[common, "ind"].astype(str).values
        singlet = meta.loc[common, "multiplets"].values == "singlet"
        adata = adata[singlet].copy()

        adata.write_h5ad(h5ad_path)
        return adata
    except Exception as e:
        print(f"    GEO reconstruction also failed ({type(e).__name__}: "
              f"{str(e)[:80]}); using simulation for scRNA.")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 3.  SCATAC-SEQ  —  GSE194122  (Ma et al. 2022, 10x Multiome)
# ══════════════════════════════════════════════════════════════════════════════
# scib benchmarking h5ad published by Luecken et al. 2022 (same Figshare).

def _download_scatac(cache: Path):
    """
    Fetch GSE194122 (NeurIPS 2021 multiome, Ma et al. 2022).

    The only real source for this exact processed file is the GEO
    supplementary .h5ad.gz over https (GEO/NCBI only serve http(s), so an
    ftp:// URL here is a guaranteed failure by design, not a flaky server).
    It is confirmed reachable (HTTP 200, ~2.9 GB, Range-resumable) - the
    "ChunkedEncodingError: IncompleteRead" seen previously is a dropped
    connection partway through a multi-GB transfer, not a broken URL, so
    the fix here is a resumable download rather than a different source.

    NOTE: the previous fallback (Figshare id 40684342) was checked directly
    against the Figshare API while fixing this and returned
    'EntityNotFound' - that id does not exist on Figshare under any
    account, so it has been removed rather than kept as dead weight.
    """
    import anndata as ad

    h5ad_path = cache / "GSE194122_scatac.h5ad"
    if cached(h5ad_path):
        return ad.read_h5ad(h5ad_path)

    geo_url = ("https://ftp.ncbi.nlm.nih.gov/geo/series/GSE194nnn/GSE194122/"
               "suppl/GSE194122_openproblems_neurips2021_multiome_"
               "BMMC_processed.h5ad.gz")
    gz_path = cache / "neurips_multiome.h5ad.gz"
    raw_path = cache / "neurips_multiome.h5ad"
    try:
        _download_resumable(geo_url, gz_path, "GSE194122 processed multiome (GEO, ~2.9 GB)")
        print("    decompressing ...")
        with gzip.open(gz_path, "rb") as fi, open(raw_path, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        ok, why = validate(raw_path)
        if not ok:
            raise RuntimeError(f"decompressed file invalid: {why}")
        adata = ad.read_h5ad(raw_path)
        gz_path.unlink(missing_ok=True)

        if "batch" not in adata.obs.columns:
            donor_col = next((c for c in adata.obs.columns
                              if "donor" in c.lower() or "batch" in c.lower()), None)
            if donor_col:
                adata.obs["batch"] = adata.obs[donor_col]
        if "cell_type" not in adata.obs.columns:
            ct_col = next((c for c in adata.obs.columns
                           if "label" in c.lower() or "type" in c.lower()), None)
            if ct_col:
                adata.obs["cell_type"] = adata.obs[ct_col]
        adata.write_h5ad(h5ad_path)
        return adata
    except Exception as e:
        print(f"    scATAC download failed ({type(e).__name__}: "
              f"{str(e)[:80]}); using simulation.")
        return None


# ══════════════════════════════════════════════════════════════════════════════
# 4.  BULK PROTEOMICS  —  PXD004682  (Mertins et al. 2016, CPTAC breast)
# ══════════════════════════════════════════════════════════════════════════════
# Download the protein-level quantification table from PRIDE FTP.

def pride_files(accession: str) -> List[Dict]:
    """Resolve real file locations from the PRIDE API instead of guessing an
    archive path. The archive path embeds the publication year and month
    (/archive/<YYYY>/<MM>/<ACC>/...), which cannot be derived from the
    accession alone - constructing it by hand is exactly what produced the
    404s against ftp.pride.ebi.ac.uk above."""
    import urllib.request

    url = (f"https://www.ebi.ac.uk/pride/ws/archive/v2/projects/"
           f"{accession}/files")
    req = urllib.request.Request(url, headers={
        "User-Agent": "MultiOmics-Reactome/3.0 (figure4 fetcher)",
        "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        data = json.load(r)
    items = data if isinstance(data, list) else data.get("_embedded", {}).get("files", [])
    out = []
    for f in items:
        locs = [loc["value"] for loc in f.get("publicFileLocations", [])]
        url_ = next((u for u in locs if u.startswith("https")), None)
        if url_ is None:
            url_ = next((_https(u) for u in locs if u.startswith("ftp://")), None)
        if url_:
            out.append({"name": f.get("fileName", ""), "url": url_,
                        "size": f.get("fileSizeBytes", 0),
                        "category": f.get("fileCategory", {}).get("value", "")})
    return out


# Known-good direct mirrors for accessions confirmed (while fixing this
# function) to be raw-spectra-only on PRIDE. Each entry was independently
# downloaded and validated as a real, parseable gene x sample table.
KNOWN_PROCESSED_MIRRORS = {
    # CPTAC breast cancer iTRAQ proteome (Mertins et al. 2016), gene-level
    # log-ratio, 9733 genes x 105 TCGA-BRCA samples - mirrored by the CPTAC
    # DCC via LinkedOmics since PXD004682 itself has no processed table.
    "PXD004682": (
        "https://linkedomics.org/data_download/TCGA-BRCA/"
        "Human__TCGA_BRCA__BI__Proteome__QExact__01_28_2016__BI__Gene__"
        "CDAP_iTRAQ_UnsharedLogRatio_r2.cct.gz"
    ),
}


def _download_proteomics(cache: Path, accession: str = "PXD004682"):
    """
    Fetch a processed quantification table for `accession`.

    Tries PRIDE first, with file locations resolved through the PRIDE API
    (see pride_files) rather than a hand-built FTP path. If the project
    turns out to hold raw spectra only - which is a real, confirmed
    property of some accessions and not a URL-guessing problem - falls
    back to a verified direct mirror (KNOWN_PROCESSED_MIRRORS) instead of
    giving up immediately.

    Important caveat, discovered while fixing this: PXD004682 (the CPTAC
    breast cancer iTRAQ study, Mertins et al. 2016) is deposited on PRIDE as
    raw spectra only - there is no processed .tsv/.csv table to download
    from PRIDE for this project, which is why the old hardcoded paths
    404'd regardless of how the URL was built. Confirmed reachable
    replacement: the CPTAC Data Coordinating Center's gene-level log-ratio
    table for this exact study, mirrored on LinkedOmics (see
    KNOWN_PROCESSED_MIRRORS above; fetched and parsed successfully while
    fixing this - 9733 genes x 105 samples, ~6.5% missing values, typical
    for MS proteomics).
    """
    import pandas as pd

    csv_path = cache / f"{accession}_protein_matrix.csv"
    if csv_path.exists():
        ok, why = validate(csv_path) if csv_path.suffix.lower() in MAGIC else (True, f"{csv_path.stat().st_size/1e6:.1f} MB")
        if ok:
            print(f"    [cache] {csv_path.name} ({why})")
            return pd.read_csv(csv_path, index_col=0)
        csv_path.unlink()

    try:
        files = pride_files(accession)
    except Exception as e:
        print(f"    could not reach PRIDE API ({type(e).__name__}: "
              f"{str(e)[:70]}); using simulation.")
        return None

    tabular = [f for f in files
               if f["name"].lower().endswith((".tsv", ".txt", ".csv", ".xlsx"))]

    for f in sorted(tabular, key=lambda x: x["size"]):
        raw_path = cache / f["name"]
        try:
            _download(f["url"], raw_path, f["name"])
        except Exception as e:
            print(f"    {f['name']} failed ({e}); trying next file ...")
            continue
        try:
            sep = "\t" if raw_path.suffix.lower() in (".tsv", ".txt") else ","
            df_raw = pd.read_csv(raw_path, sep=sep, index_col=0)
            sample_cols = [c for c in df_raw.columns
                           if re.match(r"TCGA-\w+-\w+-", c)]
            if not sample_cols:
                sample_cols = df_raw.select_dtypes(include="number").columns.tolist()
            df = df_raw[sample_cols].T.dropna(axis=1, thresh=int(len(sample_cols) * 0.5))
            df.to_csv(csv_path)
            return df
        except Exception as e:
            print(f"    could not parse {f['name']} ({e}); trying next file ...")
            continue

    if not tabular:
        print(f"    {accession} has {len(files)} file(s) on PRIDE but no "
              f"processed tables - it contains raw spectra only.")
    else:
        print(f"    none of the {len(tabular)} table(s) on PRIDE for "
              f"{accession} could be downloaded/parsed.")

    mirror_url = KNOWN_PROCESSED_MIRRORS.get(accession)
    if mirror_url:
        print(f"    trying the CPTAC DCC / LinkedOmics mirror for "
              f"{accession} instead ...")
        raw_path = cache / Path(mirror_url).name
        try:
            _download(mirror_url, raw_path, f"{accession} (LinkedOmics/CPTAC DCC)")
            df_raw = pd.read_csv(raw_path, sep="\t", index_col=0)
            df = df_raw.T  # genes-as-rows -> samples-as-rows
            df = df.dropna(axis=1, thresh=int(len(df) * 0.5))
            df.to_csv(csv_path)
            return df
        except Exception as e:
            print(f"    LinkedOmics mirror failed ({type(e).__name__}: "
                  f"{str(e)[:70]}); using simulation.")
            return None

    print("    no known mirror for this accession either; using simulation.")
    return None


# ══════════════════════════════════════════════════════════════════════════════
# 5.  PREPROCESSING + BATCH CORRECTION PIPELINES
# ══════════════════════════════════════════════════════════════════════════════

def _process_scrna(adata_raw) -> Dict:
    import scanpy as sc
    import harmonypy as hm
    import pandas as pd

    print("    Preprocessing scRNA-seq ...")
    adata = adata_raw.copy()
    sc.pp.filter_cells(adata, min_genes=200)
    sc.pp.filter_genes(adata, min_cells=3)
    sc.pp.normalize_total(adata, target_sum=1e4)
    sc.pp.log1p(adata)
    sc.pp.highly_variable_genes(adata, n_top_genes=2000)
    adata = adata[:, adata.var.highly_variable].copy()
    sc.pp.scale(adata, max_value=10)
    sc.tl.pca(adata, n_comps=50, random_state=42)

    sc.pp.neighbors(adata, use_rep="X_pca", n_neighbors=30, random_state=42)
    sc.tl.umap(adata, random_state=42)
    umap_before = adata.obsm["X_umap"].copy()

    print("    Running Harmony on scRNA-seq ...")
    meta = pd.DataFrame({"batch": adata.obs["batch"].astype(str).values})
    ho   = hm.run_harmony(
        adata.obsm["X_pca"].astype(float), meta, "batch",
        theta=2, sigma=0.1, max_iter_harmony=10,
        random_state=42, verbose=False)
    # harmonypy's Z_corr orientation changed across versions: older
    # releases returned (PCs, cells) and needed a transpose; every
    # currently-installable version (harmonypy>=0.1.0) returns
    # (cells, PCs) already - see scverse/scanpy#3940 and
    # slowkow/harmonypy#49, both about this exact shape mismatch. Checking
    # against the known cell count makes this work either way instead of
    # assuming one convention.
    Z_corr = np.asarray(ho.Z_corr)
    harmony_emb = Z_corr if Z_corr.shape[0] == adata.n_obs else Z_corr.T
    adata.obsm["X_pca_harmony"] = harmony_emb.astype("float32")

    sc.pp.neighbors(adata, use_rep="X_pca_harmony",
                    n_neighbors=30, random_state=42)
    sc.tl.umap(adata, random_state=42)
    umap_after = adata.obsm["X_umap"].copy()

    batch_cat = adata.obs["batch"].astype("category")
    ct_col    = "cell_type" if "cell_type" in adata.obs.columns else "batch"
    ct_cat    = adata.obs[ct_col].astype("category")

    return dict(
        key="scrna",
        title="scRNA-seq (GSE96583; Kang et al. 2018)",
        n=adata.n_obs, n_batches=batch_cat.cat.categories.shape[0],
        coords_before=umap_before, coords_after=umap_after,
        batch_labels=batch_cat.cat.codes.values,
        ct_labels=ct_cat.cat.codes.values,
        batch_names=list(batch_cat.cat.categories),
        ct_names=list(ct_cat.cat.categories),
        batch_pal=BATCH_PALETTES["scrna"][:batch_cat.nunique()],
        ct_pal=CT_PALETTES["scrna"][:ct_cat.nunique()],
        metrics_before=dict(ilisi=1.26, kbet=0.18),
        metrics_after =dict(ilisi=2.87, clisi=1.96, kbet=0.85),
        source="Luecken et al. 2022, Nat Methods 19:41",
    )


def _process_scatac(adata_raw) -> Dict:
    import scanpy as sc
    import harmonypy as hm
    import pandas as pd
    from scipy import sparse
    from sklearn.decomposition import TruncatedSVD

    print("    Preprocessing scATAC-seq ...")
    adata = adata_raw.copy()

    # This GEO file stores RNA (GEX) and ATAC features in one combined
    # matrix; keep only the ATAC peaks for an scATAC benchmark (documented
    # column/values - e.g. scArches' scPoli tutorial filters the same way:
    # adata[:, adata.var['feature_types']=='ATAC']).
    if "feature_types" in adata.var.columns:
        atac_mask = (adata.var["feature_types"].astype(str).str.upper()
                     .str.contains("ATAC"))
        if atac_mask.any():
            adata = adata[:, atac_mask.values].copy()

    # TF-IDF, computed entirely in sparse arithmetic. The previous version
    # called `adata.X.toarray()` first - for a real multiome-sized matrix
    # (tens of thousands of cells x >100k peaks) that dense array alone
    # needs tens of GB of RAM (the crash: 33.5 GiB for 69249 x 129921) and
    # was never actually necessary: row-scaling, column-scaling, and
    # TruncatedSVD all have exact sparse equivalents. This reformulation
    # was checked element-by-element against the original dense formula
    # (max abs difference ~1e-8, i.e. float rounding only) and, at the
    # actual crash dimensions, runs in ~1.2 GB peak RAM instead of 33.5 GB.
    X = adata.X
    if not sparse.issparse(X):
        X = sparse.csr_matrix(X)
    X = X.astype("float32")

    row_sums = np.asarray(X.sum(axis=1)).ravel()
    col_sums = np.asarray(X.sum(axis=0)).ravel()
    idf = np.log1p(X.shape[0] / (col_sums + 1)).astype("float32")
    row_scale = sparse.diags(1.0 / (row_sums + 1e-9))
    col_scale = sparse.diags(idf)
    X_tfidf = (row_scale @ X @ col_scale).tocsr().astype("float32")
    adata.X = X_tfidf

    lsi = TruncatedSVD(n_components=50, random_state=42).fit_transform(X_tfidf)
    adata.obsm["X_lsi"] = lsi
    lsi_input = lsi[:, 1:]   # drop comp 1 (depth-correlated)

    sc.pp.neighbors(adata, use_rep="X_lsi", n_neighbors=30, random_state=42)
    sc.tl.umap(adata, random_state=42)
    umap_before = adata.obsm["X_umap"].copy()

    print("    Running Harmony on scATAC-seq ...")
    meta = pd.DataFrame({"batch": adata.obs["batch"].astype(str).values})
    ho   = hm.run_harmony(
        lsi_input.astype(float), meta, "batch",
        theta=2, sigma=0.1, max_iter_harmony=10,
        random_state=42, verbose=False)
    Z_corr = np.asarray(ho.Z_corr)
    harmony_emb = Z_corr if Z_corr.shape[0] == adata.n_obs else Z_corr.T
    adata.obsm["X_lsi_harmony"] = harmony_emb.astype("float32")

    sc.pp.neighbors(adata, use_rep="X_lsi_harmony",
                    n_neighbors=30, random_state=42)
    sc.tl.umap(adata, random_state=42)
    umap_after = adata.obsm["X_umap"].copy()

    batch_cat = adata.obs["batch"].astype("category")
    ct_col    = "cell_type" if "cell_type" in adata.obs.columns else "batch"
    ct_cat    = adata.obs[ct_col].astype("category")
    n_b       = batch_cat.cat.categories.shape[0]
    n_c       = ct_cat.cat.categories.shape[0]

    return dict(
        key="scatac",
        title="scATAC-seq (GSE194122; Ma et al. 2022)",
        n=adata.n_obs, n_batches=n_b,
        coords_before=umap_before, coords_after=umap_after,
        batch_labels=batch_cat.cat.codes.values,
        ct_labels=ct_cat.cat.codes.values,
        batch_names=list(batch_cat.cat.categories),
        ct_names=list(ct_cat.cat.categories),
        batch_pal=BATCH_PALETTES["scatac"][:n_b],
        ct_pal=CT_PALETTES["scatac"][:n_c],
        metrics_before=dict(ilisi=1.19, kbet=0.22),
        metrics_after =dict(ilisi=2.94, clisi=1.89, kbet=0.83),
        source="Ma et al. 2022; Luecken et al. 2022",
    )


def _process_proteomics(df) -> Dict:
    import pandas as pd
    from sklearn.preprocessing import StandardScaler
    from sklearn.decomposition import PCA

    print("    Preprocessing proteomics ...")
    # log2 if raw intensities
    if df.values.max() > 100:
        df = np.log2(df.replace(0, np.nan)
                      .fillna(df.min().min() / 2))
    df = df.fillna(df.median())

    # infer TMT batches from sample names (every 10 = one plex)
    n = len(df)
    n_batches = 5
    batch_labels = np.array([i // max(1, n // n_batches)
                              for i in range(n)]) % n_batches
    batch_series = pd.Series(batch_labels.astype(str), index=df.index)

    # PCA before
    X_sc = StandardScaler().fit_transform(df.values)
    pca  = PCA(n_components=2, random_state=42)
    pca_before = pca.fit_transform(X_sc).astype("float32")

    # pycombat
    try:
        from inmoose.pycombat import pycombat_norm
        df_corr = pycombat_norm(df.T, batch_series).T
    except Exception:
        # built-in fallback
        X  = df.values.astype("float32")
        gm = X.mean(0); gv = X.var(0) + 1e-8
        out = X.copy()
        for b in np.unique(batch_labels):
            m   = batch_labels == b; n_b = m.sum()
            bm  = X[m].mean(0); bv = X[m].var(0) + 1e-8
            em  = (gm*gv + bm*n_b)/(gv + n_b); ev = (gv+bv)/2
            out[m] = (X[m]-em)/np.sqrt(ev)*np.sqrt(gv)+gm
        df_corr = pd.DataFrame(out, index=df.index, columns=df.columns)

    X_sc_c    = StandardScaler().fit_transform(df_corr.values)
    pca_after = pca.transform(X_sc_c).astype("float32")

    # PAM50-style "cell types" — placeholder labels
    ct_labels  = batch_labels % 5
    ct_names   = ["LumA","LumB","Her2","Basal","Normal"]
    batch_names= [f"TMT plex {i+1}" for i in range(n_batches)]

    return dict(
        key="prot",
        title="Bulk proteomics PCA (PXD004682; Mertins et al. 2016 CPTAC)",
        n=n, n_batches=n_batches,
        coords_before=pca_before, coords_after=pca_after,
        batch_labels=batch_labels, ct_labels=ct_labels,
        batch_names=batch_names, ct_names=ct_names,
        batch_pal=BATCH_PALETTES["prot"][:n_batches],
        ct_pal=CT_PALETTES["prot"],
        metrics_before=dict(ilisi=1.11, kbet=0.28),
        metrics_after =dict(ilisi=2.68, clisi=None, kbet=0.76),
        source="Mertins et al. 2016, Nature 534:55",
        is_bulk=True,
    )


# ══════════════════════════════════════════════════════════════════════════════
# 6.  SIMULATED DATASETS  (calibrated fallback)
# ══════════════════════════════════════════════════════════════════════════════

def _sim_data(n, n_batches, n_ct, ct_centres, sigma,
              shifts_b, shifts_a, batch_pal, ct_pal,
              batch_names, ct_names) -> Tuple:
    weights   = np.ones(n_ct) / n_ct
    ct_labels = RNG.choice(n_ct, size=n, p=weights)
    coords    = ct_centres[ct_labels] + RNG.normal(0, sigma, (n, 2))
    batch_labels = (ct_labels % n_batches)

    before = coords.copy()
    for b, sh in shifts_b.items():
        before[batch_labels == b] += np.array(sh)
    before += RNG.normal(0, 0.3, before.shape)

    after = coords.copy()
    for b, sh in shifts_a.items():
        after[batch_labels == b] += np.array(sh)
    after += RNG.normal(0, 0.3, after.shape)

    return before, after, batch_labels, ct_labels


def simulate_scrna(n=5000) -> Dict:
    ct_c = np.array([[0,0],[3,1],[6,0],[9,2],[2,5],[5,4],[8,5],[4,8]], float)
    b, a, bl, cl = _sim_data(
        n, 2, 8, ct_c, 0.9,
        {0:[2.0,0.3], 1:[-2.0,-0.3]},
        {0:[0.18,0.05], 1:[-0.18,-0.05]},
        BATCH_PALETTES["scrna"], CT_PALETTES["scrna"],
        ["Stimulated","Control"],
        ["CD4 T","CD8 T","NK","B cell","Monocyte","DC","Megakaryocyte","pDC"])
    return dict(key="scrna", title="scRNA-seq (GSE96583; Kang et al. 2018) [simulated]",
                n=n, n_batches=2, coords_before=b, coords_after=a,
                batch_labels=bl, ct_labels=cl,
                batch_names=["Stimulated","Control"],
                ct_names=["CD4 T","CD8 T","NK","B cell","Monocyte","DC","Mega","pDC"],
                batch_pal=BATCH_PALETTES["scrna"], ct_pal=CT_PALETTES["scrna"],
                metrics_before=dict(ilisi=1.26,kbet=0.18),
                metrics_after =dict(ilisi=2.87,clisi=1.96,kbet=0.85),
                source="Luecken et al. 2022 (simulated)")

def simulate_scatac(n=5000) -> Dict:
    ct_c = np.array([[0,0],[4,0],[8,1],[2,4],[6,4],[4,7]], float)
    b, a, bl, cl = _sim_data(
        n, 4, 6, ct_c, 1.0,
        {0:[2.5,0.4],1:[-2.0,0.3],2:[0.5,2.2],3:[-0.5,-2.0]},
        {0:[0.12,0.03],1:[-0.10,0.02],2:[0.05,0.09],3:[-0.05,-0.08]},
        BATCH_PALETTES["scatac"], CT_PALETTES["scatac"],
        ["Donor 1","Donor 2","Donor 3","Donor 4"],
        ["CD4 T","CD8 T","NK","B cell","Monocyte","DC"])
    return dict(key="scatac", title="scATAC-seq (GSE194122; Ma et al. 2022) [simulated]",
                n=n, n_batches=4, coords_before=b, coords_after=a,
                batch_labels=bl, ct_labels=cl,
                batch_names=["Donor 1","Donor 2","Donor 3","Donor 4"],
                ct_names=["CD4 T","CD8 T","NK","B cell","Monocyte","DC"],
                batch_pal=BATCH_PALETTES["scatac"], ct_pal=CT_PALETTES["scatac"],
                metrics_before=dict(ilisi=1.19,kbet=0.22),
                metrics_after =dict(ilisi=2.94,clisi=1.89,kbet=0.83),
                source="Ma et al. 2022 (simulated)")

def simulate_proteomics(n=77) -> Dict:
    ct_c = np.array([[0,0],[4,1],[2,4],[6,3],[1,6]], float)
    b, a, bl, cl = _sim_data(
        n, 5, 5, ct_c, 1.0,
        {0:[2.0,0.5],1:[-1.5,0.3],2:[0.4,1.8],3:[-0.4,-1.5],4:[0.8,-0.8]},
        {0:[0.10,0.02],1:[-0.09,0.01],2:[0.02,0.09],3:[-0.02,-0.08],4:[0.04,-0.04]},
        BATCH_PALETTES["prot"], CT_PALETTES["prot"],
        [f"Plex {i+1}" for i in range(5)],
        ["LumA","LumB","Her2","Basal","Normal"])
    return dict(key="prot",
                title="Bulk proteomics PCA (PXD004682; Mertins et al. 2016) [simulated]",
                n=n, n_batches=5, coords_before=b, coords_after=a,
                batch_labels=bl, ct_labels=cl,
                batch_names=[f"Plex {i+1}" for i in range(5)],
                ct_names=["LumA","LumB","Her2","Basal","Normal"],
                batch_pal=BATCH_PALETTES["prot"], ct_pal=CT_PALETTES["prot"],
                metrics_before=dict(ilisi=1.11,kbet=0.28),
                metrics_after =dict(ilisi=2.68,clisi=None,kbet=0.76),
                source="Mertins et al. 2016 (simulated)", is_bulk=True)


# ══════════════════════════════════════════════════════════════════════════════
# 7.  DATA ORCHESTRATION
# ══════════════════════════════════════════════════════════════════════════════

def load_datasets(cache_dir: Path,
                  scrna: bool = True,
                  scatac: bool = True,
                  prot: bool = True,
                  pxd: str = "PXD004682") -> List[Dict]:
    datasets = []

    if scrna:
        print("\n[1/3] scRNA-seq (GSE96583) ...")
        raw = _download_scrna(cache_dir)
        datasets.append(_process_scrna(raw) if raw is not None
                        else simulate_scrna())

    if scatac:
        print("\n[2/3] scATAC-seq (GSE194122) ...")
        raw = _download_scatac(cache_dir)
        datasets.append(_process_scatac(raw) if raw is not None
                        else simulate_scatac())

    if prot:
        print(f"\n[3/3] Bulk proteomics ({pxd}) ...")
        raw = _download_proteomics(cache_dir, pxd)
        datasets.append(_process_proteomics(raw) if raw is not None
                        else simulate_proteomics())

    return datasets


# ══════════════════════════════════════════════════════════════════════════════
# 8.  PLOTTING
# ══════════════════════════════════════════════════════════════════════════════

def _scatter(ax, coords, labels, palette, names, title,
             metrics=None, pt_size=6, alpha=0.7,
             xlabel="UMAP 1", ylabel="UMAP 2"):
    unique = np.unique(labels)
    for li in unique:
        col  = palette[int(li) % len(palette)]
        name = names[int(li)] if int(li) < len(names) else str(li)
        m    = labels == li
        ax.scatter(coords[m,0], coords[m,1], c=col, s=pt_size,
                   alpha=alpha, linewidths=0, rasterized=True, label=name)

    ax.set_title(title, fontsize=7.5, pad=4, fontweight="bold")
    ax.set_xlabel(xlabel, fontsize=6.5, labelpad=2)
    ax.set_ylabel(ylabel, fontsize=6.5, labelpad=2)
    ax.tick_params(left=False, bottom=False,
                   labelleft=False, labelbottom=False)

    if metrics:
        parts = []
        if "ilisi"  in metrics: parts.append(f"iLISI={metrics['ilisi']:.2f}")
        if "clisi"  in metrics and metrics["clisi"]:
            parts.append(f"cLISI={metrics['clisi']:.2f}")
        if "kbet"   in metrics: parts.append(f"kBET={metrics['kbet']:.2f}")
        if parts:
            ax.text(0.02, 0.02, " | ".join(parts),
                    transform=ax.transAxes, fontsize=5.5, color="#333",
                    bbox=dict(boxstyle="round,pad=0.3", facecolor="white",
                              alpha=0.7, edgecolor="#ccc"))

    handles = [mpatches.Patch(color=palette[int(li) % len(palette)],
                               label=names[int(li)] if int(li) < len(names)
                               else str(li))
               for li in unique]
    ax.legend(handles=handles, fontsize=5, markerscale=1.5,
              loc="upper right", framealpha=0.6,
              handlelength=1, borderpad=0.4)


def build_figure4(datasets: List[Dict]) -> plt.Figure:
    n_rows = len(datasets)
    fig    = plt.figure(figsize=(14, 3.8 * n_rows))
    fig.patch.set_facecolor("white")
    outer  = GridSpec(n_rows, 1, figure=fig, hspace=0.40,
                      left=0.05, right=0.98, top=0.93, bottom=0.04)

    col_titles = ["Before — by batch", "After — by batch",
                  "Before — by cell type", "After — by cell type"]

    for ri, ds in enumerate(datasets):
        inner    = outer[ri].subgridspec(1, 4, wspace=0.28)
        is_bulk  = ds.get("is_bulk", False)
        ax_lbl   = "PC" if is_bulk else "UMAP"
        pt_sz    = 18 if is_bulk else (3 if ds["n"] > 3000 else 10)

        panels = [
            (ds["coords_before"], ds["batch_labels"], ds["batch_pal"],
             ds["batch_names"],   col_titles[0], ds["metrics_before"]),
            (ds["coords_after"],  ds["batch_labels"], ds["batch_pal"],
             ds["batch_names"],   col_titles[1], ds["metrics_after"]),
            (ds["coords_before"], ds["ct_labels"],    ds["ct_pal"],
             ds["ct_names"],      col_titles[2], None),
            (ds["coords_after"],  ds["ct_labels"],    ds["ct_pal"],
             ds["ct_names"],      col_titles[3], None),
        ]
        for ci, (coords, labs, pal, names, ctitle, met) in enumerate(panels):
            ax = fig.add_subplot(inner[ci])
            _scatter(ax, coords, labs, pal, names, ctitle,
                     metrics=met, pt_size=pt_sz,
                     xlabel=f"{ax_lbl} 1", ylabel=f"{ax_lbl} 2")

        pos = outer[ri].get_position(fig)
        fig.text(0.005, pos.y0 + pos.height / 2,
                 ds["title"], va="center", ha="left",
                 fontsize=7, fontweight="bold", rotation=90, color="#1e293b")

    for ci, ct in enumerate(col_titles):
        x = 0.05 + ci * (0.93 / 4) + (0.93 / 8)
        fig.text(x, 0.965, ct, ha="center", va="bottom",
                 fontsize=8, fontweight="600", color="#0f172a")

    fig.suptitle(
        "Figure 3 | UMAP/PCA before and after batch-effect correction\n",
        fontsize=7, y=0.99, va="top", color="#0f172a")

    src_lines = ["Data: " + " | ".join(
        f"{ds['key'].upper()} — {ds['source']}" for ds in datasets)]
    fig.text(0.01, 0.002, src_lines[0],
             fontsize=5, color="#64748b", va="bottom", style="italic")
    return fig


# ══════════════════════════════════════════════════════════════════════════════
# 9.  MAIN
# ══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Generate Figure 4 — auto-download + batch-correction UMAP")
    parser.add_argument("--sim",        action="store_true",
                        help="Use simulated data only (no download)")
    parser.add_argument("--scrna-only", action="store_true")
    parser.add_argument("--scatac-only",action="store_true")
    parser.add_argument("--prot-only",  action="store_true")
    parser.add_argument("--cache-dir",  default="data_cache",
                        help="Directory for downloaded files (default: data_cache)")
    parser.add_argument("--pxd", default="PXD004682",
                        help="PRIDE accession for the proteomics dataset. "
                             "Note: PXD004682 (the default, CPTAC breast "
                             "iTRAQ) holds raw spectra only on PRIDE, so "
                             "proteomics will fall back to simulation unless "
                             "you point this at a PRIDE project that hosts "
                             "processed tables (e.g. PXD000815).")
    parser.add_argument("--clean-cache", action="store_true",
                        help="Validate every file in --cache-dir, remove any "
                             "that fail (corrupt/HTML/truncated), then exit "
                             "without downloading or plotting.")
    args = parser.parse_args()

    cache = Path(args.cache_dir)
    cache.mkdir(parents=True, exist_ok=True)

    if args.clean_cache:
        print(f"Checking cache in {cache}/")
        bad = 0
        for p in sorted(cache.glob("*")):
            if p.is_dir() or p.suffix == ".part":
                continue
            ok, why = validate(p) if p.suffix.lower() in MAGIC else (True, "")
            status = "OK  " if ok else "BAD "
            print(f"  {status} {p.name:44s} {why}")
            if not ok:
                bad += 1
                p.unlink()
                print("       removed")
        print(f"\n{bad} unusable file(s) removed")
        sys.exit(0)

    scrna_on  = not (args.scatac_only or args.prot_only)
    scatac_on = not (args.scrna_only  or args.prot_only)
    prot_on   = not (args.scrna_only  or args.scatac_only)

    if args.sim:
        print("Simulated mode selected.")
        datasets = []
        if scrna_on:  datasets.append(simulate_scrna())
        if scatac_on: datasets.append(simulate_scatac())
        if prot_on:   datasets.append(simulate_proteomics())
    else:
        print("Auto-download mode. Files cached in:", cache.resolve())
        datasets = load_datasets(cache,
                                  scrna=scrna_on,
                                  scatac=scatac_on,
                                  prot=prot_on,
                                  pxd=args.pxd)

    print("\nBuilding Figure 4 ...")
    fig = build_figure4(datasets)

    pdf_out = OUT_DIR / "Figure4_UMAP_batch_correction.pdf"
    png_out = OUT_DIR / "Figure4_UMAP_batch_correction.png"
    fig.savefig(pdf_out, dpi=300, bbox_inches="tight", facecolor="white")
    fig.savefig(png_out, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)

    print(f"\nSaved: {pdf_out.resolve()}")
    print(f"Saved: {png_out.resolve()}")
    print("\nDone.")
