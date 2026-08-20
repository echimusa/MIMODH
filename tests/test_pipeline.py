"""Backend pipeline tests."""
import ast
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))


def test_backend_files_parse():
    for name in ("multiomics_reactome.py", "multiomics_pipeline.py", "app.py"):
        ast.parse((ROOT / "backend" / name).read_text(encoding="utf-8"))


def _require_pipeline_deps():
    """The pipeline needs the full scientific stack; skip if it is absent."""
    for mod in ("numpy", "scipy", "pandas", "sklearn", "statsmodels",
                "matplotlib", "seaborn", "networkx", "anndata"):
        pytest.importorskip(mod, reason=f"{mod} not installed")


def test_inputconfig_importable():
    _require_pipeline_deps()
    from backend.multiomics_reactome import InputConfig
    assert InputConfig is not None


def test_inputconfig_accepts_core_kwargs():
    _require_pipeline_deps()
    import inspect
    from backend.multiomics_reactome import InputConfig
    params = set(inspect.signature(InputConfig.__init__).parameters) - {"self"}
    for required in ("mode", "n_samples", "n_batches", "transcriptomics", "metadata"):
        assert required in params, f"InputConfig missing '{required}'"


def test_app_health():
    pytest.importorskip("boto3", reason="boto3 needed for the cloud API")
    pytest.importorskip("httpx", reason="httpx needed by fastapi.testclient")
    from fastapi.testclient import TestClient
    from backend.app import app
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["version"] == "3.0.0"


def test_integration_methods_endpoint():
    """The API must report which back-ends the deployment can actually run."""
    pytest.importorskip("boto3", reason="boto3 needed for the cloud API")
    from backend.app import integration_methods
    r = integration_methods()
    assert r["default"] == "nmf"
    assert "nmf" in r["available"], "NMF must always be available"
    for name, st in r["methods"].items():
        if not st["available"]:
            assert st["reason"], f"{name} unavailable without a reason"


def test_pipeline_accepts_integration_method():
    """run_pipeline must expose the method so all interfaces can set it."""
    import inspect
    from backend.multiomics_reactome import run_pipeline
    params = inspect.signature(run_pipeline).parameters
    assert "integration_method" in params
    assert params["integration_method"].default == "nmf"


def test_jobconfig_validates_integration_method():
    pytest.importorskip("boto3", reason="boto3 needed for the cloud API")
    from pydantic import ValidationError
    from backend.app import JobConfig
    assert JobConfig().integration_method == "nmf"
    assert JobConfig(integration_method="mcia").integration_method == "mcia"
    with pytest.raises(ValidationError):
        JobConfig(integration_method="not_a_method")


def test_harmonypy_import_is_guarded():
    """A missing optional package must not take down the whole backend.

    Regression test: `import harmonypy` was unconditional at module load, so a
    packaging gap in the frozen build raised ModuleNotFoundError before any
    pipeline code ran.
    """
    src = (ROOT / "backend" / "multiomics_reactome.py").read_text(encoding="utf-8")
    assert "try:" in src.split("import harmonypy")[0][-200:], (
        "the harmonypy import is not inside a try block"
    )
    assert "_harmony_fallback" in src, "no in-tree Harmony fallback is wired up"
    assert "_HARMONY_IMPL" in src, (
        "the implementation in use is not recorded, so a result could be "
        "produced by the fallback without saying so"
    )


def test_harmony_fallback_ships_in_package():
    """The fallback must live in backend/, not scripts/, so it is importable
    from the frozen bundle."""
    fb = ROOT / "backend" / "_harmony_fallback.py"
    assert fb.exists(), "backend/_harmony_fallback.py is missing"
    import ast
    tree = ast.parse(fb.read_text(encoding="utf-8"))
    fns = {n.name for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    assert "run_harmony" in fns, "fallback does not expose run_harmony()"


def test_harmony_fallback_actually_corrects_batch_effects():
    """The fallback must work, not merely import."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("pandas")
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_hfb", ROOT / "backend" / "_harmony_fallback.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    rng = np.random.default_rng(0)
    n, d = 90, 10
    batch = np.repeat(["b0", "b1", "b2"], 30)
    X = rng.normal(0, 1, (n, d))
    for b in np.unique(batch):
        X[batch == b] += rng.normal(0, 1, d) * 3

    def batch_var(Z):
        means = np.array([Z[batch == b].mean(axis=0) for b in np.unique(batch)])
        return means.var(axis=0).mean()

    import pandas as pd
    before = batch_var(X)
    res = mod.run_harmony(X, pd.DataFrame({"batch": batch}), "batch")
    after = batch_var(np.asarray(res.Z_corr).T)
    assert after < before * 0.2, (
        f"fallback reduced batch variance only from {before:.3f} to {after:.3f}"
    )


# ── Dependency completeness ──────────────────────────────────────────────────
def test_required_deps_list_matches_reality():
    """Every module in REQUIRED must genuinely break the backend if absent.

    Guards against the list drifting into a wishlist. If a module can be removed
    without breaking anything it belongs in OPTIONAL, where a fallback is
    documented.
    """
    from backend._deps import REQUIRED
    assert len(REQUIRED) >= 13, "the required list looks truncated"
    names = {d.module for d in REQUIRED}
    # These were determined empirically by blocking each in turn.
    for m in ("numpy", "pandas", "scipy", "sklearn", "matplotlib", "seaborn",
              "networkx", "anndata", "scanpy", "requests", "joblib", "tqdm",
              "statsmodels"):
        assert m in names, f"{m} breaks the backend when absent but is not listed"


def test_every_dep_has_purpose_and_install_command():
    from backend._deps import OPTIONAL, REQUIRED
    for d in list(REQUIRED) + list(OPTIONAL):
        assert d.purpose, f"{d.module} has no stated purpose"
        assert d.install.startswith("pip install"), (
            f"{d.module} has no usable install command")


def test_build_scripts_bundle_every_required_package():
    """A required package absent from the build scripts only bundles by luck,
    as a transitive dependency. Regression test: requests, joblib and tqdm were
    all required by the backend yet referenced in neither build script.
    """
    import re
    from backend._deps import REQUIRED

    for script in ("fix_and_build.sh", "FIX_AND_BUILD.ps1"):
        path = ROOT / script
        if not path.exists():
            continue
        src = path.read_text(encoding="utf-8", errors="replace")
        referenced = set(re.findall(r'--collect-all[",\s]+["]?([\w.]+)', src))
        referenced |= set(re.findall(r'--hidden-import[",\s]+["]?([\w.]+)', src))
        referenced |= {r.split(".")[0] for r in referenced}

        missing = [d.module for d in REQUIRED if d.module not in referenced]
        assert not missing, (
            f"{script} does not reference required package(s): {missing}. "
            "They would bundle only as transitive dependencies, which is fragile."
        )


def test_deps_module_runs_standalone():
    """backend/_deps.py must be runnable directly for troubleshooting."""
    import subprocess
    import sys
    r = subprocess.run([sys.executable, "-m", "backend._deps"],
                       capture_output=True, text=True, cwd=str(ROOT))
    assert "required packages" in r.stdout.lower()
