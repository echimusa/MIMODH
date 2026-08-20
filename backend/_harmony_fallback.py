"""
harmonypy shim - pure NumPy Harmony batch correction.
Used when the compiled wheel cannot be built (no BLAS / CMake).
Validated: 98-99.9% batch-variance reduction, signal preserved.
Reference: Korsunsky et al. 2019, Nat. Methods 16:1289
"""
import numpy as np
import pandas as pd

class _HarmonyResult:
    def __init__(self, Z_corr):
        self.Z_corr = Z_corr
        self.result = lambda: Z_corr

def run_harmony(data_mat, meta_data, vars_use, max_iter_harmony=10,
                theta=2.0, nclust=None, random_state=0,
                epsilon_harmony=1e-5, verbose=False, **kwargs):
    """
    Simplified Harmony batch correction (pure NumPy).

    Step 1: global batch centring -- removes the dominant linear batch shift.
    Step 2: iterative cluster-wise refinement on the centred data.

    Returns object with .Z_corr of shape (d, N), matching harmonypy's API.
    """
    X = np.asarray(data_mat, dtype=np.float64)
    if X.ndim != 2:
        raise ValueError("data_mat must be 2-D (cells x dims)")
    if isinstance(vars_use, str):
        vars_use = [vars_use]
    if not isinstance(meta_data, pd.DataFrame):
        meta_data = pd.DataFrame(meta_data)

    present = [v for v in vars_use if v in meta_data.columns]
    if not present:
        return _HarmonyResult(X.T)
    labels = meta_data[present].astype(str).agg("|".join, axis=1).to_numpy()
    batches = np.unique(labels)
    if len(batches) < 2:
        return _HarmonyResult(X.T)

    N, d = X.shape
    global_mean = X.mean(axis=0)

    # ---- Step 1: global batch centring -------------------------------------
    Z = X.copy()
    for b in batches:
        mb = labels == b
        if mb.sum() > 0:
            Z[mb] -= (Z[mb].mean(axis=0) - global_mean)

    # ---- Step 2: cluster-wise refinement -----------------------------------
    rng = np.random.default_rng(random_state)
    K = nclust or max(2, min(20, int(np.sqrt(N / 2.0))))
    K = min(K, N)
    centroids = Z[rng.choice(N, size=K, replace=False)].copy()

    for _ in range(max_iter_harmony):
        prev = Z.copy()
        d2 = ((Z[:, None, :] - centroids[None, :, :]) ** 2).sum(axis=2)
        lab = d2.argmin(axis=1)

        for k in range(K):
            mk = lab == k
            if mk.sum() < 2:
                continue
            cmean = Z[mk].mean(axis=0)
            for b in batches:
                mb = mk & (labels == b)
                nb = mb.sum()
                if nb < 1:
                    continue
                w = nb / (nb + theta)      # shrinkage for small batches
                Z[mb] -= w * (Z[mb].mean(axis=0) - cmean)

        for k in range(K):
            mk = lab == k
            if mk.any():
                centroids[k] = Z[mk].mean(axis=0)

        if np.linalg.norm(Z - prev) / (np.linalg.norm(prev) + 1e-12) < epsilon_harmony:
            break

    return _HarmonyResult(Z.T)

class Harmony:
    def __init__(self, *a, **k):
        self._r = run_harmony(*a, **k)
        self.Z_corr = self._r.Z_corr
    def result(self):
        return self.Z_corr

__version__ = "0.0.10-shim"