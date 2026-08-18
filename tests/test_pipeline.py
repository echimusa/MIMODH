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
    from fastapi.testclient import TestClient
    from backend.app import app
    r = TestClient(app).get("/health")
    assert r.status_code == 200
    assert r.json()["version"] == "3.0.0"
