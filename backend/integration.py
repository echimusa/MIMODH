# -*- coding: utf-8 -*-
"""
integration.py - Pluggable multi-omics integration back-ends.

MultiOmics-Reactome performs harmonisation (validation, preprocessing, batch
correction) independently of the integration step. This module exposes the
integration step as a set of interchangeable back-ends so that a study can be
integrated with the method appropriate to its design, without repeating
harmonisation.

Every back-end takes the same input - a mapping of modality name to a
(n_samples x n_features) matrix, already harmonised and batch-corrected - and
returns a joint (n_samples x n_factors) latent representation.

    from backend.integration import integrate, available_methods

    factors = integrate(embeddings, method="mofa", n_factors=10)
    print(available_methods())

Back-ends
---------
nmf     Non-negative matrix factorisation (default). PyTorch multiplicative
        update with a scikit-learn fallback. No optional dependency.
mofa    MOFA+ via mofapy2 (Argelaguet et al., Genome Biology 2020;21:111).
        pip install mofapy2
snf     Similarity Network Fusion (Wang et al., Nat Methods 2014;11:333).
        Uses snfpy when present, otherwise a built-in NumPy implementation.
mcia    Multiple Co-Inertia Analysis (Meng et al., BMC Bioinformatics
        2014;15:162). Built-in NumPy implementation; no R required.
diablo  DIABLO / block sPLS-DA via mixOmics (Singh et al., Bioinformatics
        2019;35:3055). Requires R, the mixOmics package and rpy2, and a
        response vector y.

A back-end that cannot be satisfied reports itself unavailable with the reason
and the command needed to enable it. It never fails silently and never
substitutes a different method without saying so.
"""
from __future__ import annotations

import logging
import warnings
from typing import Dict, List, Optional, Tuple

import numpy as np

log = logging.getLogger(__name__)

__all__ = [
    "integrate",
    "available_methods",
    "method_status",
    "IntegrationError",
    "IntegrationUnavailable",
]


class IntegrationError(RuntimeError):
    """Raised when an integration back-end fails during execution."""


class IntegrationUnavailable(ImportError):
    """Raised when a back-end's optional dependency is not installed."""


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------
def _validate(embeddings: Dict[str, np.ndarray]) -> Tuple[List[str], int]:
    """Check that all modalities share a sample axis. Returns (names, n_samples)."""
    if not embeddings:
        raise IntegrationError("No modalities supplied for integration.")
    names = sorted(embeddings)
    shapes = {}
    for k in names:
        arr = np.asarray(embeddings[k])
        if arr.ndim != 2:
            raise IntegrationError(
                f"Modality {k!r} must be 2-D (samples x features); got shape {arr.shape}."
            )
        shapes[k] = arr.shape
    n_rows = {v[0] for v in shapes.values()}
    if len(n_rows) != 1:
        raise IntegrationError(
            "All modalities must share the same number of samples. Got "
            + ", ".join(f"{k}={v[0]}" for k, v in shapes.items())
            + ". Reconcile sample IDs before integration."
        )
    return names, n_rows.pop()


def _standardise(X: np.ndarray) -> np.ndarray:
    """Centre and scale to unit variance, leaving constant columns at zero."""
    X = np.asarray(X, dtype=np.float64)
    mu = X.mean(axis=0)
    sd = X.std(axis=0)
    sd[sd < 1e-12] = 1.0
    return (X - mu) / sd


def _spectral_factors(affinity: np.ndarray, n_factors: int) -> np.ndarray:
    """Leading eigenvectors of the normalised Laplacian of an affinity matrix."""
    A = np.asarray(affinity, dtype=np.float64)
    A = (A + A.T) / 2.0
    np.fill_diagonal(A, 0.0)
    d = A.sum(axis=1)
    d[d < 1e-12] = 1e-12
    d_inv_sqrt = 1.0 / np.sqrt(d)
    L = A * d_inv_sqrt[:, None] * d_inv_sqrt[None, :]
    vals, vecs = np.linalg.eigh(L)
    order = np.argsort(vals)[::-1][:n_factors]
    return np.asarray(vecs[:, order], dtype=np.float64)


# ---------------------------------------------------------------------------
# NMF (default; always available)
# ---------------------------------------------------------------------------
def _integrate_nmf(embeddings, n_factors, random_state=0, **kw) -> np.ndarray:
    names, n = _validate(embeddings)
    blocks = []
    for k in names:
        X = np.asarray(embeddings[k], dtype=np.float64)
        # NMF requires non-negativity; shift each block by its own minimum.
        m = X.min()
        blocks.append(X - m if m < 0 else X)
    X_cat = np.hstack(blocks)

    try:
        import torch  # noqa: F401
        from .torch_nmf import TorchNMF  # pragma: no cover - project-local
        return TorchNMF(n_components=n_factors).fit_transform(X_cat)
    except Exception:
        pass

    from sklearn.decomposition import NMF
    k = min(n_factors, min(X_cat.shape))
    model = NMF(n_components=k, init="nndsvda", max_iter=500,
                random_state=random_state)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return model.fit_transform(X_cat)


# ---------------------------------------------------------------------------
# MOFA+ (mofapy2)
# ---------------------------------------------------------------------------
def _check_mofa() -> Optional[str]:
    try:
        import mofapy2  # noqa: F401
        return None
    except ImportError:
        return "mofapy2 not installed. Enable with: pip install mofapy2"


def _integrate_mofa(embeddings, n_factors, random_state=0,
                    convergence_mode="fast", **kw) -> np.ndarray:
    err = _check_mofa()
    if err:
        raise IntegrationUnavailable(err)

    from mofapy2.run.entry_point import entry_point

    names, n = _validate(embeddings)
    # mofapy2 expects data[view][group] with samples in rows.
    data = [[_standardise(embeddings[k])] for k in names]

    ent = entry_point()
    ent.set_data_options(scale_views=True, scale_groups=False)
    ent.set_data_matrix(data, views_names=list(names), groups_names=["group0"])
    ent.set_model_options(factors=int(n_factors), spikeslab_weights=True,
                          ard_weights=True, ard_factors=True)
    ent.set_train_options(iter=int(kw.get("iter", 200)),
                          convergence_mode=convergence_mode,
                          startELBO=1, freqELBO=10, dropR2=None,
                          gpu_mode=False, verbose=False, seed=random_state)
    ent.build()
    ent.run()

    Z = ent.model.nodes["Z"].getExpectation()
    Z = np.asarray(Z, dtype=np.float64)
    if Z.shape[0] != n:                      # some versions return (factors, samples)
        Z = Z.T
    return Z


# ---------------------------------------------------------------------------
# Similarity Network Fusion
# ---------------------------------------------------------------------------
def _affinity(X: np.ndarray, k: int = 20, mu: float = 0.5) -> np.ndarray:
    """Scaled exponential similarity kernel (Wang et al. 2014, eq. 1-2)."""
    from scipy.spatial.distance import squareform, pdist
    D = squareform(pdist(_standardise(X), metric="euclidean"))
    n = D.shape[0]
    k = int(max(1, min(k, n - 1)))
    # mean distance to each point's k nearest neighbours
    srt = np.sort(D, axis=1)[:, 1:k + 1]
    eps = srt.mean(axis=1)
    eps[eps < 1e-12] = 1e-12
    scale = mu * (eps[:, None] + eps[None, :]) / 2.0 + D / 3.0
    scale[scale < 1e-12] = 1e-12
    W = np.exp(-(D ** 2) / (2.0 * scale ** 2))
    np.fill_diagonal(W, 1.0)
    return W


def _integrate_snf(embeddings, n_factors, K=20, t=20, mu=0.5, **kw) -> np.ndarray:
    names, n = _validate(embeddings)

    fused = None
    try:                                    # prefer the reference implementation
        import snf as _snf
        affinities = [_snf.make_affinity(_standardise(embeddings[k]),
                                         metric="euclidean", K=K, mu=mu)
                      for k in names]
        fused = _snf.snf(affinities, K=K, t=t)
        log.info("  SNF via snfpy")
    except ImportError:
        log.debug("snfpy not installed; using built-in implementation")
    except Exception as exc:
        # snfpy releases up to 0.2.2 call sklearn's check_array with the
        # force_all_finite argument, removed in scikit-learn 1.6. Fall back
        # rather than fail, and say so.
        log.warning("  snfpy unusable (%s: %s); using built-in SNF",
                    type(exc).__name__, exc)
        fused = None

    if fused is None:
        log.info("  SNF via built-in NumPy implementation")
        Ws = [_affinity(embeddings[k], k=K, mu=mu) for k in names]
        m = len(Ws)
        # full and sparse (KNN) normalisations
        P, S = [], []
        for W in Ws:
            row = W.sum(axis=1) - np.diag(W)
            row[row < 1e-12] = 1e-12
            Pi = W / (2.0 * row[:, None])
            np.fill_diagonal(Pi, 0.5)
            P.append(Pi)
            kk = int(max(1, min(K, W.shape[0] - 1)))
            idx = np.argsort(W, axis=1)[:, ::-1][:, :kk]
            Si = np.zeros_like(W)
            for i in range(W.shape[0]):
                v = W[i, idx[i]]
                s = v.sum()
                Si[i, idx[i]] = v / (s if s > 1e-12 else 1.0)
            S.append(Si)
        if m == 1:
            fused = P[0]
        else:
            for _ in range(int(t)):
                Pn = []
                for i in range(m):
                    others = sum(P[j] for j in range(m) if j != i) / (m - 1)
                    Pn.append(S[i] @ others @ S[i].T)
                P = Pn
            fused = sum(P) / m

    fused = np.asarray(fused, dtype=np.float64)
    fused = (fused + fused.T) / 2.0
    return _spectral_factors(fused, n_factors)


# ---------------------------------------------------------------------------
# Multiple Co-Inertia Analysis
# ---------------------------------------------------------------------------
def _integrate_mcia(embeddings, n_factors, **kw) -> np.ndarray:
    """
    Multiple Co-Inertia Analysis (Meng et al., BMC Bioinformatics 2014;15:162).

    Each table is centred and given equal weight by dividing by its first
    singular value, so that no modality dominates through sheer scale or
    feature count. The weighted tables are concatenated and decomposed by SVD;
    the left singular vectors are the global (synthetic-centre) scores that
    maximise the sum of squared covariances with the individual table
    projections.

    Implemented in NumPy so that no R installation is required. This reproduces
    the global scores of ade4::mcoa / omicade4::mcia for the equal-weight,
    centred case; per-table row weighting and the non-symmetric correspondence
    variant of omicade4 are not implemented.
    """
    names, n = _validate(embeddings)
    blocks = []
    for k in names:
        X = np.asarray(embeddings[k], dtype=np.float64)
        X = X - X.mean(axis=0)                       # centre
        s1 = np.linalg.svd(X, compute_uv=False)
        s1 = s1[0] if s1.size and s1[0] > 1e-12 else 1.0
        blocks.append(X / s1)                        # equal table weight
    X_cat = np.hstack(blocks)

    k = int(min(n_factors, min(X_cat.shape)))
    U, S, _ = np.linalg.svd(X_cat, full_matrices=False)
    return np.asarray(U[:, :k] * S[:k], dtype=np.float64)


# ---------------------------------------------------------------------------
# DIABLO (mixOmics via rpy2)
# ---------------------------------------------------------------------------
def _check_diablo() -> Optional[str]:
    try:
        import rpy2.robjects  # noqa: F401
    except ImportError:
        return ("rpy2 not installed. DIABLO requires R and the mixOmics "
                "package. Enable with: pip install rpy2  and, in R: "
                "BiocManager::install('mixOmics')")
    try:
        from rpy2.robjects.packages import importr
        importr("mixOmics")
        return None
    except Exception:
        return ("The R package mixOmics is not available. In R run: "
                "install.packages('BiocManager'); "
                "BiocManager::install('mixOmics')")


def _integrate_diablo(embeddings, n_factors, y=None, **kw) -> np.ndarray:
    err = _check_diablo()
    if err:
        raise IntegrationUnavailable(err)
    if y is None:
        raise IntegrationError(
            "DIABLO is a supervised method and requires a response vector. "
            "Pass y=<array of class labels, one per sample>, or choose an "
            "unsupervised back-end (nmf, mofa, snf, mcia)."
        )

    import rpy2.robjects as ro
    from rpy2.robjects import numpy2ri
    from rpy2.robjects.packages import importr

    names, n = _validate(embeddings)
    y = np.asarray(y)
    if y.shape[0] != n:
        raise IntegrationError(
            f"y has {y.shape[0]} entries but there are {n} samples."
        )

    mixomics = importr("mixOmics")
    numpy2ri.activate()
    try:
        blocks = ro.ListVector(
            {k: ro.r.matrix(_standardise(embeddings[k]),
                            nrow=n, ncol=embeddings[k].shape[1])
             for k in names}
        )
        yr = ro.FactorVector([str(v) for v in y])
        res = mixomics.block_splsda(X=blocks, Y=yr, ncomp=int(n_factors))
        variates = res.rx2("variates")
        mats = [np.asarray(variates.rx2(k)) for k in names]
        return np.mean(mats, axis=0)                 # consensus components
    finally:
        numpy2ri.deactivate()


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
_BACKENDS = {
    "nmf":    dict(fn=_integrate_nmf,    check=lambda: None,   supervised=False,
                   label="Non-negative Matrix Factorisation",
                   cite="Lee & Seung, NeurIPS 2001"),
    "mofa":   dict(fn=_integrate_mofa,   check=_check_mofa,    supervised=False,
                   label="MOFA+",
                   cite="Argelaguet et al., Genome Biology 2020;21:111"),
    "snf":    dict(fn=_integrate_snf,    check=lambda: None,   supervised=False,
                   label="Similarity Network Fusion",
                   cite="Wang et al., Nat Methods 2014;11:333"),
    "mcia":   dict(fn=_integrate_mcia,   check=lambda: None,   supervised=False,
                   label="Multiple Co-Inertia Analysis",
                   cite="Meng et al., BMC Bioinformatics 2014;15:162"),
    "diablo": dict(fn=_integrate_diablo, check=_check_diablo,  supervised=True,
                   label="DIABLO (block sPLS-DA)",
                   cite="Singh et al., Bioinformatics 2019;35:3055"),
}

METHODS = tuple(_BACKENDS)


def method_status() -> Dict[str, Dict[str, object]]:
    """Report every back-end, whether it is usable, and how to enable it."""
    out = {}
    for name, spec in _BACKENDS.items():
        reason = spec["check"]()
        out[name] = {
            "label":      spec["label"],
            "citation":   spec["cite"],
            "supervised": spec["supervised"],
            "available":  reason is None,
            "reason":     reason,
        }
    return out


def available_methods() -> List[str]:
    """Names of the back-ends usable in this environment."""
    return [k for k, v in method_status().items() if v["available"]]


def integrate(embeddings: Dict[str, np.ndarray],
              method: str = "nmf",
              n_factors: int = 10,
              **kwargs) -> np.ndarray:
    """
    Integrate harmonised per-modality matrices into a joint latent space.

    Parameters
    ----------
    embeddings : dict of {modality: (n_samples, n_features) array}
        Harmonised, batch-corrected matrices sharing one sample axis.
    method : {'nmf', 'mofa', 'snf', 'mcia', 'diablo'}
        Integration back-end. Default 'nmf'.
    n_factors : int
        Number of latent factors to return.
    **kwargs
        Passed to the back-end. 'diablo' requires y=<labels>.

    Returns
    -------
    (n_samples, n_factors) ndarray

    Raises
    ------
    IntegrationUnavailable
        The back-end's optional dependency is missing. The message states the
        command needed to install it.
    IntegrationError
        The inputs are inconsistent, or the back-end failed.
    """
    m = str(method).lower().strip()
    if m not in _BACKENDS:
        raise IntegrationError(
            f"Unknown integration method {method!r}. "
            f"Available: {', '.join(METHODS)}."
        )
    spec = _BACKENDS[m]
    reason = spec["check"]()
    if reason:
        raise IntegrationUnavailable(
            f"Integration method {m!r} ({spec['label']}) is not available. {reason}"
        )

    log.info("  Integration: %s (%s)", spec["label"], spec["cite"])
    factors = spec["fn"](embeddings, n_factors, **kwargs)
    factors = np.asarray(factors, dtype=np.float64)

    n = next(iter(embeddings.values())).shape[0]
    if factors.shape[0] != n:
        raise IntegrationError(
            f"Back-end {m!r} returned {factors.shape[0]} rows for {n} samples."
        )
    log.info("  Integration produced %d x %d factor matrix",
             factors.shape[0], factors.shape[1])
    return factors
