# Contributing

## Setup

```bash
git clone https://github.com/echimusa/MIMODH.git
cd MIMODH
bash scripts/setup.sh --dev
source .venv_mimodh/bin/activate
pip install -r desktop/requirements_desktop.txt
```

## Before opening a pull request

```bash
ruff check backend/ desktop/ tests/ --select E,F,W,I --ignore E501
black backend/ desktop/ tests/
pytest tests/ -v --cov=backend
QT_QPA_PLATFORM=offscreen pytest tests/test_desktop.py -v
for s in scripts/*.sh fix_and_build.sh; do bash -n "$s"; done
```

## Conventions

- **Branches** — `feat/…`, `fix/…`, `docs/…`, `chore/…`; PRs target `dev`
- **Commits** — [Conventional Commits](https://www.conventionalcommits.org)
- **Style** — PEP 8, `black` defaults, `pathlib` over `os.path`
- **Encoding** — ASCII-only in module docstrings, or add `# -*- coding: utf-8 -*-`.
  PyInstaller's bytecode compiler fails on non-ASCII docstrings without it.
- **Cross-platform** — no hardcoded path separators; guard `sys.platform` branches

## Adding a new modality

1. Add a loader in `backend/multiomics_reactome.py`
2. Add validation rules to `OmicsValidator`
3. Add a file picker entry in `desktop/widgets/configure_tab.py` (`MODALITIES`)
4. Extend `schemas/mimodh_v1.xsd` under `ModalityRegistry`
5. Add a fixture and test in `tests/`
6. Update the modality table in `README.md`

## Editing desktop sources

`scripts/patch_sources.py` applies the eight platform fixes and validates every
file with `ast.parse()` before writing. If you change `pipeline_worker.py`,
`main_window.py` or `configure_tab.py`, refresh the embedded pristine copies:

```bash
python - <<'PY'
import base64, pathlib
for rel in ("desktop/pipeline_worker.py", "desktop/main_window.py",
            "desktop/widgets/configure_tab.py"):
    src = pathlib.Path(rel).read_text()
    print(rel, "->", base64.b64encode(src.encode()).decode()[:60], "...")
PY
```

Then update the `_B64_*` constants in `scripts/patch_sources.py`.

## Dependency policy

Anything requiring a C/C++ compiler must have a pure-Python fallback, because
Windows users frequently lack MSVC and Linux users lack a system BLAS.

| Dependency | Fallback |
|---|---|
| `numba` | no-op stub injected into `sys.modules` |
| `harmonypy` ≥ 0.0.11 | pure-NumPy shim (`scripts/harmonypy_shim.py`) |
| `inmoose` | `pycombat` |

Fallbacks must be numerically validated. The harmonypy shim is tested at
98–99% batch-variance reduction with biological signal preserved.
