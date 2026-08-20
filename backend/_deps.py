# -*- coding: utf-8 -*-
"""
_deps.py - Single source of truth for the pipeline's runtime dependencies.

Two categories, treated differently on purpose:

REQUIRED
    The pipeline cannot run without these. If one is missing the correct
    behaviour is to say so clearly and stop, not to degrade silently. Guarding
    them with try/except would hide a broken installation and produce results
    that are wrong in ways nobody can see.

OPTIONAL
    Each has a working fallback. The pipeline runs without them; what changes
    is speed, or which implementation performs a step. Every fallback announces
    itself in the log so a result is never attributed to the wrong method.

The desktop application calls check_dependencies() before the first run, so a
packaging gap surfaces as a readable dialog at startup rather than a traceback
part-way through an analysis.
"""
from __future__ import annotations

import importlib.util
from typing import Dict, List, NamedTuple, Tuple


class Dep(NamedTuple):
    module: str
    purpose: str
    install: str


# Determined empirically: blocking any one of these prevents
# backend.multiomics_reactome from importing at all.
REQUIRED: Tuple[Dep, ...] = (
    Dep("numpy",       "numerical core",                    "pip install 'numpy>=2.0.0,<3.0.0'"),
    Dep("pandas",      "data frames",                       "pip install pandas"),
    Dep("scipy",       "statistics, sparse matrices",       "pip install scipy"),
    Dep("sklearn",     "PCA, clustering, neighbours",       "pip install scikit-learn"),
    Dep("statsmodels", "multiple-testing correction",       "pip install statsmodels"),
    Dep("matplotlib",  "figures",                           "pip install matplotlib"),
    Dep("seaborn",     "figures",                           "pip install seaborn"),
    Dep("networkx",    "Reactome pathway graph",            "pip install networkx"),
    Dep("anndata",     "single-cell containers",            "pip install anndata"),
    Dep("scanpy",      "single-cell preprocessing",         "pip install scanpy"),
    Dep("requests",    "Reactome REST queries",             "pip install requests"),
    Dep("joblib",      "parallel execution",                "pip install joblib"),
    Dep("tqdm",        "progress reporting",                "pip install tqdm"),
    Dep("lxml",        "MIMODH XML validation",             "pip install lxml"),
)

OPTIONAL: Tuple[Dep, ...] = (
    Dep("harmonypy",  "single-cell batch correction (falls back to the in-tree "
                      "NumPy implementation)",              "pip install 'harmonypy<=0.0.10'"),
    Dep("numba",      "JIT acceleration inside scanpy (falls back to pure Python)",
                                                            "pip install numba"),
    Dep("pycombat",   "bulk batch correction (ComBat)",     "pip install pycombat"),
    Dep("torch",      "GPU-accelerated NMF (falls back to scikit-learn)",
                                                            "pip install torch --index-url https://download.pytorch.org/whl/cpu"),
    Dep("mofapy2",    "MOFA+ integration back-end",         "pip install mofapy2"),
    Dep("leidenalg",  "Leiden clustering (falls back to Louvain)",
                                                            "pip install leidenalg igraph"),
    Dep("plotly",     "interactive HTML network",           "pip install plotly"),
)


def _present(module: str) -> bool:
    try:
        return importlib.util.find_spec(module) is not None
    except (ImportError, ValueError):
        return False


def check_dependencies() -> Dict[str, List[Dep]]:
    """Return {'missing_required': [...], 'missing_optional': [...]}."""
    return {
        "missing_required": [d for d in REQUIRED if not _present(d.module)],
        "missing_optional": [d for d in OPTIONAL if not _present(d.module)],
    }


def format_report(result: Dict[str, List[Dep]] | None = None) -> str:
    """Human-readable summary suitable for a log or a dialog."""
    r = result or check_dependencies()
    lines: List[str] = []

    if r["missing_required"]:
        lines.append("MISSING REQUIRED PACKAGES - the pipeline cannot run:")
        for d in r["missing_required"]:
            lines.append(f"  {d.module:<12} {d.purpose}")
            lines.append(f"  {'':<12} {d.install}")
        lines.append("")
        lines.append("If you are running the packaged application, this indicates a")
        lines.append("build problem rather than anything you can fix locally. Please")
        lines.append("rebuild, or report the list above.")
    else:
        lines.append("All required packages present.")

    if r["missing_optional"]:
        lines.append("")
        lines.append("Optional packages not installed (the pipeline still runs):")
        for d in r["missing_optional"]:
            lines.append(f"  {d.module:<12} {d.purpose}")

    return "\n".join(lines)


def assert_ready() -> None:
    """Raise ImportError listing everything missing, rather than one at a time."""
    r = check_dependencies()
    if r["missing_required"]:
        names = ", ".join(d.module for d in r["missing_required"])
        raise ImportError(
            f"Cannot start: required package(s) missing: {names}\n\n"
            + format_report(r)
        )


if __name__ == "__main__":
    import sys
    r = check_dependencies()
    print(format_report(r))
    sys.exit(1 if r["missing_required"] else 0)
