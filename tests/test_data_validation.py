"""Bundled test-data format checks.

These enforce the invariants the pipeline relies on. They caught two real
defects during development: integer batch labels and NaN treatment values.
"""
from pathlib import Path

import pytest

pd = pytest.importorskip("pandas")

TD = Path(__file__).parent.parent / "desktop" / "test_data"
OMICS = ("transcriptomics_test.csv", "proteomics_test.csv", "metabolomics_test.csv")


@pytest.fixture(scope="module")
def meta():
    return pd.read_csv(TD / "metadata_test.csv", index_col=0)


def test_all_files_present(meta):
    for f in OMICS + ("metadata_test.csv",):
        assert (TD / f).exists(), f"missing {f}"


def test_batch_is_string(meta):
    """batch must be textual, not numeric.

    pandas 2.x reports 'object' for strings; pandas 3.x reports 'str'.
    Accept either, and reject any numeric dtype.
    """
    import pandas.api.types as ptypes
    dt = meta["batch"].dtype
    assert not ptypes.is_numeric_dtype(dt), (
        f"batch must be string, got numeric dtype {dt}. "
        "Convert with: meta['batch'] = meta['batch'].apply(lambda x: f'batch_{x}')"
    )
    assert all(isinstance(v, str) for v in meta["batch"]), (
        "batch column contains non-string values"
    )


def test_batch_values_prefixed(meta):
    for b in meta["batch"].unique():
        assert str(b).startswith("batch_"), f"unexpected batch label: {b!r}"


def test_no_treatment_nan(meta):
    assert meta["treatment"].isnull().sum() == 0, "treatment column has NaN"


def test_required_metadata_columns(meta):
    for col in ("condition", "batch", "age", "sex"):
        assert col in meta.columns, f"missing required column: {col}"


def test_condition_balanced(meta):
    counts = meta["condition"].value_counts().to_dict()
    assert set(counts) == {"Case", "Control"}, f"unexpected conditions: {counts}"


@pytest.mark.parametrize("fname", OMICS)
def test_omics_clean(fname):
    df = pd.read_csv(TD / fname, index_col=0)
    assert df.isnull().sum().sum() == 0, f"{fname} contains NaN"
    assert (df >= 0).all().all(), f"{fname} contains negative values"


@pytest.mark.parametrize("fname", OMICS)
def test_sample_ids_aligned(fname, meta):
    df = pd.read_csv(TD / fname, index_col=0)
    assert set(df.index) == set(meta.index), f"{fname} sample IDs differ from metadata"
