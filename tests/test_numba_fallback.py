# -*- coding: utf-8 -*-
"""The numba substitute must satisfy every call form and code path scanpy uses.

Regression tests. Two defects were found only by running the complete pipeline
with numba blocked; neither was visible from an import check:

  1. numba.get_num_threads() was missing, so the stub imported but failed later.
  2. njit(fn, cache=True, parallel=False) - the form used by fast_array_utils -
     returned a decorator where a function was expected.
"""
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


@pytest.fixture(scope="module")
def stub():
    from backend._numba_stub import _make_module
    return _make_module()


# -- API surface -------------------------------------------------------------
@pytest.mark.parametrize("attr", [
    "njit", "jit", "prange", "pndindex",
    "get_num_threads", "set_num_threads", "config",
])
def test_provides_attribute_scanpy_uses(stub, attr):
    """Derived by scanning installed scanpy for `numba.<attr>` references."""
    assert hasattr(stub, attr), f"stub is missing numba.{attr}"


def test_stub_covers_everything_scanpy_references():
    """Fail if a scanpy upgrade starts using a numba attribute we do not provide."""
    sc = pytest.importorskip("scanpy")
    import collections
    import re

    from backend._numba_stub import _make_module

    used = collections.Counter()
    for f in Path(sc.__file__).parent.rglob("*.py"):
        try:
            src = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        used.update(re.findall(r"\bnumba\.(\w+)", src))
        for m in re.finditer(r"from numba import ([\w,\s]+)", src):
            used.update(n.strip() for n in m.group(1).split(",") if n.strip())

    stub = _make_module()
    missing = sorted(a for a in used if not hasattr(stub, a))
    assert not missing, (
        f"scanpy uses numba attributes the stub does not provide: {missing}")


# -- decorator call forms ----------------------------------------------------
def test_njit_bare_decorator(stub):
    @stub.njit
    def f(x):
        return x * 2
    assert f(3) == 6


def test_njit_with_options(stub):
    @stub.njit(parallel=True, cache=True)
    def f(x):
        return x * 3
    assert f(3) == 9


def test_njit_with_signature_string(stub):
    @stub.njit("f8(f8)", nogil=True)
    def f(x):
        return x * 4
    assert f(3) == 12


def test_njit_function_plus_kwargs(stub):
    """The form used by fast_array_utils, which scanpy depends on.

    fast_array_utils builds serial and parallel variants with
    `numba.njit(fn, cache=True, parallel=p)`. An earlier stub required kwargs
    to be empty before unwrapping, so this returned a decorator and failed with
    an unexpected-keyword TypeError at call time.
    """
    def g(x, rows=None):
        return x * 5
    f = stub.njit(g, cache=True, parallel=False)
    assert f(3, rows=1) == 15


def test_thread_controls_round_trip(stub):
    assert stub.get_num_threads() >= 1
    stub.set_num_threads(4)
    assert stub.get_num_threads() == 4


def test_pndindex_matches_ndindex(stub):
    import numpy as np
    assert list(stub.pndindex((2, 3))) == list(np.ndindex(2, 3))


# -- scanpy compatibility ----------------------------------------------------
def test_normalize_total_matches_scanpy_without_numba(tmp_path):
    """The substituted normalize_total must be numerically identical.

    scanpy's _normalize_csr returns `counts_per_cols`, which is bound only
    inside `if exclude_highly_expressed:`. numba hides this by eliminating the
    dead branch at compile time; interpreted, the default path raises
    UnboundLocalError. We substitute the public entry point rather than patch
    scanpy internals, so the result must be verified equal.
    """
    pytest.importorskip("scanpy")
    pytest.importorskip("anndata")
    import numpy as np
    import scipy.sparse as sp

    ref_in = tmp_path / "in.npz"
    ref_out = tmp_path / "out.npy"

    # Reference from real scanpy in this process
    import anndata as ad
    import scanpy as sc
    rng = np.random.default_rng(0)
    X = sp.csr_matrix(rng.poisson(3, (50, 30)).astype(np.float64))
    sp.save_npz(ref_in, X)
    a = ad.AnnData(X.copy())
    sc.pp.normalize_total(a, target_sum=1e4)
    np.save(ref_out, np.asarray(a.X.todense()))

    # Same computation with numba blocked, in a clean interpreter
    code = f'''
import sys
class B:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "numba":
            raise ImportError("blocked")
        return None
sys.meta_path.insert(0, B())
sys.path.insert(0, {str(ROOT)!r})
from backend._numba_stub import install, patch_scanpy
install(); patch_scanpy()
import numpy as np, scipy.sparse as sp, anndata as ad, scanpy as sc
X = sp.load_npz({str(ref_in)!r})
a = ad.AnnData(X.copy()); sc.pp.normalize_total(a, target_sum=1e4)
ours = np.asarray(a.X.todense() if sp.issparse(a.X) else a.X)
ref = np.load({str(ref_out)!r})
assert np.allclose(ref, ours, rtol=1e-9, atol=1e-9), np.abs(ref-ours).max()
print("EQUIVALENT")
'''
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=600)
    assert "EQUIVALENT" in r.stdout, (
        f"normalize_total differs without numba:\n{r.stdout}\n{r.stderr[-600:]}")


def test_full_pipeline_runs_without_numba(tmp_path):
    """End-to-end guard. Both defects above were invisible to import checks."""
    pytest.importorskip("scanpy")
    code = f'''
import sys, warnings
warnings.filterwarnings("ignore")
class B:
    def find_spec(self, name, path=None, target=None):
        if name.split(".")[0] == "numba":
            raise ImportError("blocked")
        return None
sys.meta_path.insert(0, B())
sys.path.insert(0, {str(ROOT)!r})
from backend._numba_stub import install
install()
import backend.multiomics_reactome as mr
from pathlib import Path
mr.OUTPUT_DIR = Path({str(tmp_path)!r})
cfg = mr.InputConfig(mode="synthetic", n_samples=30, n_cells=80, n_batches=2)
mr.run_pipeline(cfg, n_perm=10, integration_method="nmf")
print("PIPELINE_OK")
'''
    r = subprocess.run([sys.executable, "-c", code], capture_output=True,
                       text=True, timeout=1200)
    assert "PIPELINE_OK" in r.stdout, (
        f"pipeline failed without numba:\n{r.stdout[-800:]}\n{r.stderr[-800:]}")
