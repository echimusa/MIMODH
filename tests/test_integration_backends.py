# -*- coding: utf-8 -*-
"""Tests for the pluggable integration back-ends.

Run:  pytest tests/test_integration_backends.py -v

Back-ends whose optional dependency is absent are skipped, not failed, so the
suite is meaningful in a minimal environment.
"""
import warnings

import numpy as np
import pytest

from backend.integration import (METHODS, IntegrationError,
                                 IntegrationUnavailable, available_methods,
                                 integrate, method_status)

warnings.filterwarnings("ignore")

UNSUPERVISED = ["nmf", "mofa", "snf", "mcia"]


@pytest.fixture(scope="module")
def data():
    """Three modalities sharing a planted 3-group structure."""
    rng = np.random.default_rng(0)
    n, g = 90, 3
    labels = np.repeat(np.arange(g), n // g)
    Z = rng.normal(0, 4, (g, 6))[labels] + rng.normal(0, 0.5, (n, 6))
    emb = {
        "transcriptomics": Z @ rng.normal(0, 1, (6, 60)) + rng.normal(0, 1.0, (n, 60)),
        "proteomics":      Z @ rng.normal(0, 1, (6, 30)) + rng.normal(0, 1.3, (n, 30)),
        "metabolomics":    Z @ rng.normal(0, 1, (6, 20)) + rng.normal(0, 1.6, (n, 20)),
    }
    return emb, labels


def _skip_if_unavailable(method):
    st = method_status()[method]
    if not st["available"]:
        pytest.skip(f"{method} unavailable: {st['reason']}")


# ---------------------------------------------------------------- registry --
def test_registry_lists_all_methods():
    assert set(METHODS) == {"nmf", "mofa", "snf", "mcia", "diablo"}


def test_nmf_always_available():
    assert "nmf" in available_methods(), "NMF must not depend on optional packages"


def test_status_reports_reason_when_unavailable():
    for name, st in method_status().items():
        if not st["available"]:
            assert st["reason"], f"{name} unavailable but gives no reason"
            assert "install" in st["reason"].lower()


def test_every_method_has_a_citation():
    for name, st in method_status().items():
        assert st["citation"], f"{name} has no citation"


# ------------------------------------------------------------------ shapes --
@pytest.mark.parametrize("method", UNSUPERVISED)
def test_returns_correct_shape(method, data):
    _skip_if_unavailable(method)
    emb, _ = data
    n = next(iter(emb.values())).shape[0]
    F = integrate(emb, method=method, n_factors=5)
    assert F.shape[0] == n
    assert F.shape[1] <= 5
    assert np.isfinite(F).all(), "factors contain NaN or inf"


# --------------------------------------------------------------- behaviour --
@pytest.mark.parametrize("method", UNSUPERVISED)
def test_recovers_planted_structure(method, data):
    """Joint factors should recover the group structure shared across modalities."""
    _skip_if_unavailable(method)
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score

    emb, labels = data
    F = integrate(emb, method=method, n_factors=5)
    pred = KMeans(n_clusters=3, n_init=10, random_state=0).fit(F).labels_
    ari = adjusted_rand_score(labels, pred)
    assert ari > 0.5, f"{method} recovered structure poorly (ARI={ari:.3f})"


@pytest.mark.parametrize("method", UNSUPERVISED)
def test_deterministic(method, data):
    _skip_if_unavailable(method)
    emb, _ = data
    a = integrate(emb, method=method, n_factors=4, random_state=0)
    b = integrate(emb, method=method, n_factors=4, random_state=0)
    assert np.allclose(a, b, atol=1e-8), f"{method} is not reproducible"


def test_handles_unbalanced_feature_counts():
    """A modality with 100x more features must not swamp the others."""
    rng = np.random.default_rng(1)
    n = 60
    labels = np.repeat(np.arange(3), n // 3)
    Z = rng.normal(0, 4, (3, 6))[labels] + rng.normal(0, 0.5, (n, 6))
    emb = {"big":   Z @ rng.normal(0, 1, (6, 5000)) + rng.normal(0, 1.5, (n, 5000)),
           "small": Z @ rng.normal(0, 1, (6, 40))   + rng.normal(0, 1.5, (n, 40))}
    from sklearn.cluster import KMeans
    from sklearn.metrics import adjusted_rand_score
    F = integrate(emb, method="mcia", n_factors=5)
    ari = adjusted_rand_score(labels,
                              KMeans(3, n_init=10, random_state=0).fit(F).labels_)
    assert ari > 0.5, f"scale imbalance degraded recovery (ARI={ari:.3f})"


# ------------------------------------------------------------ error paths ---
def test_rejects_mismatched_sample_counts(data):
    emb, _ = data
    bad = dict(emb)
    bad["transcriptomics"] = bad["transcriptomics"][:50]
    with pytest.raises(IntegrationError, match="same number of samples"):
        integrate(bad, method="nmf")


def test_rejects_unknown_method(data):
    emb, _ = data
    with pytest.raises(IntegrationError, match="Unknown integration method"):
        integrate(emb, method="not_a_method")


def test_rejects_empty_input():
    with pytest.raises(IntegrationError, match="No modalities"):
        integrate({}, method="nmf")


def test_rejects_one_dimensional_modality(data):
    emb, _ = data
    bad = dict(emb)
    bad["transcriptomics"] = np.arange(90.0)
    with pytest.raises(IntegrationError, match="must be 2-D"):
        integrate(bad, method="nmf")


def test_diablo_requires_labels(data):
    """DIABLO is supervised; without y it must say so rather than guess."""
    emb, _ = data
    st = method_status()["diablo"]
    with pytest.raises((IntegrationError, IntegrationUnavailable)) as exc:
        integrate(emb, method="diablo")
    msg = str(exc.value).lower()
    assert ("response vector" in msg) or ("not available" in msg)


def test_single_modality_is_allowed(data):
    emb, _ = data
    F = integrate({"transcriptomics": emb["transcriptomics"]},
                  method="mcia", n_factors=3)
    assert F.shape == (90, 3)


# ---------------------------------------------------------------- contract --
@pytest.mark.parametrize("method", UNSUPERVISED)
def test_method_is_reported_not_silently_substituted(method, data, caplog):
    """A back-end must never quietly fall back to a different method."""
    _skip_if_unavailable(method)
    import logging
    emb, _ = data
    with caplog.at_level(logging.INFO, logger="backend.integration"):
        integrate(emb, method=method, n_factors=3)
    if method != "nmf":
        joined = " ".join(r.message for r in caplog.records).lower()
        assert method_status()[method]["label"].lower().split()[0] in joined
