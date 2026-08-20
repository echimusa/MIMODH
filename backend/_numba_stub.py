# -*- coding: utf-8 -*-
"""
_numba_stub.py - A no-op numba substitute.

scanpy imports numba unconditionally and calls into it at runtime. The real
package cannot be bundled into a frozen Windows application because llvmlite
carries a native threading-library dependency (tbb12.dll) that PyInstaller
cannot resolve, and no llvmlite wheel exists for the newest Python releases.

Rather than let that take the pipeline down, this module supplies the exact
surface scanpy uses. The attribute list is not guesswork: it was derived by
scanning the installed scanpy source, which uses

    numba.njit  numba.prange  numba.pndindex
    numba.get_num_threads  numba.set_num_threads  numba.config

Decorated functions run as ordinary Python. Results are identical; only speed
differs. install() reports whether the stub was used so the run log can say so.
"""
from __future__ import annotations

import sys
import types


def _make_module() -> types.ModuleType:
    nb = types.ModuleType("numba")

    def njit(*args, **kwargs):
        """Return the target function unchanged, whatever the call form.

        numba's decorators are called in several shapes, and all of them must
        work here:

            @njit                                   -> njit(fn)
            @njit(parallel=True)                    -> njit(**kw)(fn)
            @njit("f8(f8)", nogil=True)             -> njit(sig, **kw)(fn)
            njit(fn, cache=True, parallel=False)    -> njit(fn, **kw)

        The last form is used by fast_array_utils, a scanpy dependency, which
        builds serial and parallel variants of the same function. An earlier
        version of this stub required kwargs to be empty before unwrapping,
        so that call returned a decorator where a function was expected and
        failed later with an unexpected-keyword TypeError.
        """
        if args and callable(args[0]) and not isinstance(args[0], str):
            return args[0]
        return lambda fn: fn

    # Compilation decorators
    nb.njit = njit
    nb.jit = njit
    nb.generated_jit = njit
    nb.vectorize = njit
    nb.guvectorize = njit
    nb.stencil = njit
    nb.cfunc = njit
    nb.jitclass = njit

    # Parallel range helpers
    nb.prange = range

    def pndindex(*shape):
        import itertools
        if len(shape) == 1 and isinstance(shape[0], (tuple, list)):
            shape = tuple(shape[0])
        return itertools.product(*(range(int(s)) for s in shape))

    nb.pndindex = pndindex

    # Threading controls. scanpy queries and sets these; single-threaded is
    # the honest answer because nothing is being JIT-compiled or parallelised.
    _threads = [1]
    nb.get_num_threads = lambda: _threads[0]

    def set_num_threads(n):
        _threads[0] = max(1, int(n))

    nb.set_num_threads = set_num_threads
    nb.get_thread_id = lambda: 0

    # numba.config is read for attributes such as NUMBA_NUM_THREADS and
    # DISABLE_JIT. Return benign defaults for anything asked for.
    class _Config(types.ModuleType):
        NUMBA_NUM_THREADS = 1
        NUMBA_DEFAULT_NUM_THREADS = 1
        DISABLE_JIT = True
        THREADING_LAYER = "workqueue"

        def __getattr__(self, name):
            return None

    nb.config = _Config("numba.config")

    # Type aliases used in signatures
    nb.float32 = float
    nb.float64 = float
    nb.int8 = nb.int16 = nb.int32 = nb.int64 = int
    nb.uint8 = nb.uint16 = nb.uint32 = nb.uint64 = int
    nb.boolean = bool
    nb.void = None

    # Submodules some call sites import from
    nb.typed = types.ModuleType("numba.typed")
    nb.typed.List = list
    nb.typed.Dict = dict
    nb.core = types.ModuleType("numba.core")
    nb.core.types = types.ModuleType("numba.core.types")
    nb.extending = types.ModuleType("numba.extending")
    nb.extending.overload = njit
    nb.extending.register_jitable = njit
    nb.types = types.ModuleType("numba.types")

    class _NumbaError(Exception):
        pass

    nb.NumbaError = _NumbaError
    nb.TypingError = _NumbaError
    nb.__version__ = "0.0.0-stub"
    nb.__is_mimodh_stub__ = True
    return nb


def install() -> bool:
    """Install the stub if the real numba is unavailable.

    Returns True if the stub was installed, False if the real package is in use.
    Safe to call more than once.
    """
    try:
        import numba as _real
        if not getattr(_real, "__is_mimodh_stub__", False):
            return False
    except Exception:
        pass

    if "numba" in sys.modules and getattr(sys.modules["numba"],
                                          "__is_mimodh_stub__", False):
        return True

    nb = _make_module()
    sys.modules["numba"] = nb
    sys.modules["numba.typed"] = nb.typed
    sys.modules["numba.core"] = nb.core
    sys.modules["numba.core.types"] = nb.core.types
    sys.modules["numba.extending"] = nb.extending
    sys.modules["numba.types"] = nb.types
    sys.modules["numba.config"] = nb.config
    return True


def is_stubbed() -> bool:
    nb = sys.modules.get("numba")
    return bool(nb is not None and getattr(nb, "__is_mimodh_stub__", False))


# ---------------------------------------------------------------------------
# scanpy compatibility
# ---------------------------------------------------------------------------
def patch_scanpy() -> bool:
    """Replace scanpy.pp.normalize_total with a pure-NumPy equivalent.

    scanpy's `_normalize_csr` is only correct when JIT-compiled::

        counts_per_cell = np.zeros(rows, ...)
        ...
        if exclude_highly_expressed:
            counts_per_cols = np.zeros(columns, ...)
            ...
        return counts_per_cell, counts_per_cols    # <- unbound when False

    `counts_per_cols` is assigned only inside the conditional, so under
    interpretation the default path raises UnboundLocalError. numba hides this
    because type inference eliminates the dead branch at compile time.

    Since the stub runs the function as ordinary Python, that latent bug becomes
    live. Rather than patch scanpy's internals - which would break on their next
    release - substitute the public entry point with a direct implementation.
    Library-size normalisation is a division; the result is identical.

    Returns True if the patch was applied.
    """
    if not is_stubbed():
        return False
    try:
        import numpy as np
        import scanpy as sc
    except Exception:
        return False

    if getattr(sc.pp.normalize_total, "__is_mimodh_patch__", False):
        return True

    def normalize_total(adata, *, target_sum=None, exclude_highly_expressed=False,
                        max_fraction=0.05, key_added=None, layer=None,
                        inplace=True, copy=False, **kwargs):
        """Library-size normalisation. Pure NumPy; matches scanpy semantics."""
        import scipy.sparse as sp

        if copy:
            adata = adata.copy()
        X = adata.layers[layer] if layer is not None else adata.X

        counts = np.asarray(X.sum(axis=1)).ravel().astype(np.float64)

        if exclude_highly_expressed:
            Xd = X.toarray() if sp.issparse(X) else np.asarray(X)
            with np.errstate(invalid="ignore", divide="ignore"):
                frac = np.divide(Xd, counts[:, None],
                                 out=np.zeros_like(Xd, dtype=np.float64),
                                 where=counts[:, None] != 0)
            keep = ~(frac > max_fraction).any(axis=0)
            counts = Xd[:, keep].sum(axis=1).astype(np.float64)

        ts = float(np.median(counts[counts > 0])) if target_sum is None \
            else float(target_sum)
        with np.errstate(invalid="ignore", divide="ignore"):
            factors = np.divide(counts, ts, out=np.ones_like(counts),
                                where=counts > 0)
        factors[factors == 0] = 1.0

        if sp.issparse(X):
            Xn = sp.diags(1.0 / factors) @ X.tocsr()
        else:
            Xn = np.asarray(X) / factors[:, None]

        if key_added is not None:
            adata.obs[key_added] = counts

        if not inplace:
            return {"X": Xn, "norm_factor": counts}
        if layer is not None:
            adata.layers[layer] = Xn
        else:
            adata.X = Xn
        return adata if copy else None

    normalize_total.__is_mimodh_patch__ = True
    sc.pp.normalize_total = normalize_total
    try:
        sc.preprocessing.normalize_total = normalize_total
    except Exception:
        pass
    return True
