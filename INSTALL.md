# Installation & Script Locations

**Short answer: unzip the archive and everything is already in the right place.**
Nothing needs moving. This document explains why, in case you reorganise later.

---

## The two rules

1. **Root-level scripts must stay in the repository root** — the folder that
   contains `requirements.txt`, `backend/` and `desktop/`.
2. **`scripts/` contents must stay in `scripts/`** — they are called by path,
   e.g. `scripts/patch_sources.py`.

Every script verifies its own location and refuses to run from the wrong place:

```
ERROR: Must be run from the repository root (needs desktop/ and backend/).
       Current directory: /home/user/Downloads
```

---

## Where each script lives

### Repository root — build and launch

| File | Platform | Purpose |
|---|---|---|
| `BUILD_APP.bat` | Windows | **Start here.** Full setup + build the `.exe` |
| `FIX_AND_BUILD.bat` | Windows | Patch sources + rebuild (double-click) |
| `FIX_AND_BUILD.ps1` | Windows | Same, from PowerShell |
| `fix_and_build.sh` | Linux / macOS | **Linux equivalent of `FIX_AND_BUILD.ps1`** |
| `RUN_DEBUG.bat` | Windows | Launch the `.exe` with crash logging |

These are in the root because they operate on the whole repository, and because
Windows users expect to double-click something at the top level.

### `scripts/` — environment, deploy, publish

| File | Platform | Purpose |
|---|---|---|
| `setup.sh` | Linux / macOS | Create the venv, install dependencies |
| `setup.ps1` | Windows | Same |
| `deploy_aws.sh` | Linux / macOS / WSL | Interactive AWS deployment |
| `push_to_github.sh` | Linux / macOS | Push to GitHub |
| `push_to_github.ps1` | Windows | Push to GitHub |
| `patch_sources.py` | All | Applies the 8 platform fixes (called by the build scripts) |
| `harmonypy_shim.py` | All | Pure-NumPy Harmony fallback (copied into site-packages if needed) |
| `deploy_legacy.sh` | Linux | Original non-interactive deploy, kept for reference |

### `desktop/` — desktop app only

| File | Platform | Purpose |
|---|---|---|
| `build_desktop.sh` | Linux / macOS | Lower-level PyInstaller build |
| `multiomics_desktop.spec` | All | PyInstaller spec file |
| `requirements_desktop.txt` | All | PyQt6 + PyInstaller |

---

## Full directory tree

```
MIMODH/                             <- repository root, run scripts from here
├── BUILD_APP.bat                   Windows: one-click build
├── FIX_AND_BUILD.bat               Windows: patch + rebuild (double-click)
├── FIX_AND_BUILD.ps1               Windows: patch + rebuild
├── fix_and_build.sh                Linux/macOS: patch + rebuild
├── RUN_DEBUG.bat                   Windows: run with crash logging
├── README.md
├── INSTALL.md                      this file
├── LICENSE
├── CITATION.cff
├── requirements.txt
├── docker-compose.yml
├── .env.example
├── .gitignore
│
├── backend/                        pipeline core, platform-independent
│   ├── __init__.py
│   ├── multiomics_reactome.py
│   ├── multiomics_pipeline.py
│   └── app.py
│
├── desktop/                        PyQt6 desktop application
│   ├── __init__.py
│   ├── app.py
│   ├── main_window.py
│   ├── pipeline_worker.py
│   ├── styles.py
│   ├── README.md
│   ├── build_desktop.sh
│   ├── multiomics_desktop.spec
│   ├── requirements_desktop.txt
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── configure_tab.py
│   │   ├── run_tab.py
│   │   ├── results_tab.py
│   │   └── about_tab.py
│   ├── test_data/
│   │   ├── __init__.py
│   │   ├── generate_test_data.py
│   │   ├── transcriptomics_test.csv
│   │   ├── proteomics_test.csv
│   │   ├── metabolomics_test.csv
│   │   └── metadata_test.csv
│   └── resources/                  put icon.ico / icon.icns / icon.png here
│
├── frontend/                       React 18 SPA
│   ├── README.md
│   ├── index.html
│   ├── package.json
│   ├── vite.config.js
│   └── src/
│       ├── main.jsx
│       └── App.jsx
│
├── infra/
│   └── lambda_authorizer.py
│
├── schemas/
│   └── mimodh_v1.xsd
│
├── scripts/                        keep these here, they are called by path
│   ├── setup.sh
│   ├── setup.ps1
│   ├── deploy_aws.sh
│   ├── deploy_legacy.sh
│   ├── push_to_github.sh
│   ├── push_to_github.ps1
│   ├── patch_sources.py
│   └── harmonypy_shim.py
│
├── docker/
│   └── Dockerfile
│
├── tests/
│   ├── __init__.py
│   ├── test_pipeline.py
│   ├── test_mimodh_xml.py
│   ├── test_data_validation.py
│   ├── test_desktop.py
│   ├── unit/
│   └── integration/
│
├── docs/
│   ├── ARCHITECTURE.md
│   ├── DEPLOYMENT.md
│   ├── CONTRIBUTING.md
│   └── VALIDATION_REPORT.md
│
├── notebooks/
│   └── 01_exploration.ipynb
│
└── .github/workflows/
    ├── ci.yml
    └── deploy.yml
```

---

## Getting started

### Windows

**Step 0 is not optional.** Windows marks every file extracted from a
downloaded zip as untrusted, and PowerShell then refuses to run it with
*"is not digitally signed"*.

```
0. Double-click UNBLOCK_ALL.bat          <-- run this ONCE, first
1. Install Python 3.11 from python.org   (tick "Add Python to PATH")
2. Double-click SETUP_ENVIRONMENT.bat    (choose option 2)
3. Double-click BUILD_APP.bat            (10-20 min, first run only)
4. Double-click dist\MultiOmicsReactome.exe
```

`UNBLOCK_ALL.bat` clears the mark from every `.ps1`, `.bat`, `.sh` and `.py`
file in the folder. Without it, each script fails individually with the
signature error.

If you prefer PowerShell:

```powershell
cd C:\path\to\MIMODH
Get-ChildItem -Recurse -Include *.ps1,*.bat,*.sh,*.py | Unblock-File
```

**Double-click launchers** (all handle unblocking and execution policy):

| File | Purpose |
|---|---|
| `UNBLOCK_ALL.bat` | Run once after extracting |
| `SETUP_ENVIRONMENT.bat` | Create the venv, install dependencies |
| `BUILD_APP.bat` | Build the standalone `.exe` |
| `FIX_AND_BUILD.bat` | Patch sources + rebuild |
| `PUSH_TO_GITHUB.bat` | Publish to GitHub (offers a dry run first) |
| `RUN_DEBUG.bat` | Launch the `.exe` with crash logging |
| `REPAIR_GIT.bat` | Remove oversized files from git if a push was rejected |

Later, to apply fixes and rebuild quickly:

```powershell
# Double-click FIX_AND_BUILD.bat, or:
.\FIX_AND_BUILD.ps1
```

### Ubuntu / Debian

```bash
# System libraries Qt needs
sudo apt update
sudo apt install -y python3 python3-venv python3-pip \
                    libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 \
                    libegl1 libgl1-mesa-glx

unzip MIMODH.zip && cd MIMODH
chmod +x fix_and_build.sh scripts/*.sh desktop/*.sh

bash scripts/setup.sh --dev
source .venv_mimodh/bin/activate
pip install -r desktop/requirements_desktop.txt

# Run from source
python -m desktop.app

# Or build a standalone binary
./fix_and_build.sh
./dist/MultiOmicsReactome
```

### macOS

```bash
xcode-select --install          # if not already present

unzip MIMODH.zip && cd MIMODH
chmod +x fix_and_build.sh scripts/*.sh desktop/*.sh

bash scripts/setup.sh --dev
source .venv_mimodh/bin/activate
pip install -r desktop/requirements_desktop.txt

python -m desktop.app

# Or build an .app bundle
./fix_and_build.sh
open dist/MultiOmicsReactome.app
```

If Gatekeeper blocks it:
```bash
xattr -rd com.apple.quarantine dist/MultiOmicsReactome.app
```

---

## `fix_and_build.sh` vs `FIX_AND_BUILD.ps1`

Functionally identical. Both apply the same 8 fixes via
`scripts/patch_sources.py`, resolve the same dependency fallbacks, strip the
same Qt plugin folders, and build with the same PyInstaller flags.

| | `fix_and_build.sh` | `FIX_AND_BUILD.ps1` |
|---|---|---|
| Platform | Linux, macOS | Windows |
| Location | repository root | repository root |
| Invoke | `./fix_and_build.sh` | `.\FIX_AND_BUILD.ps1` or `FIX_AND_BUILD.bat` |
| Venv detected | `.venv_build`, `.venv_mimodh`, `.venv`, `venv` | `.venv_build` |
| `--add-data` separator | `:` | `;` |
| Output | `dist/MultiOmicsReactome` or `.app` | `dist\MultiOmicsReactome.exe` |
| Options | `--patch-only`, `--no-clean`, `--run` | (same behaviour, always builds) |

Extra flags on the shell version:

```bash
./fix_and_build.sh --patch-only   # fix sources and check deps, do not build
./fix_and_build.sh --no-clean     # keep dist/ and build/ for a faster rebuild
./fix_and_build.sh --run          # launch the binary when the build finishes
```

---

## Cloud deployment

```bash
# From the repository root
./scripts/deploy_aws.sh --dry-run   # preview the plan, changes nothing
./scripts/deploy_aws.sh             # deploy, prompts for region/domain/etc.
```

On Windows, run it through WSL or Git Bash:

```bash
wsl bash scripts/deploy_aws.sh
# or
& "C:\Program Files\Git\bin\bash.exe" scripts/deploy_aws.sh
```

See `docs/DEPLOYMENT.md` for domain setup, TLS, DNS records and costs.

---

## Publishing to GitHub

> **Never commit the built executable.** `dist/MultiOmicsReactome.exe` is
> ~280 MB and GitHub hard-rejects any file over 100 MB. `.gitignore` blocks
> `*.exe`, `dist/` and `build/`, and the push scripts check sizes before
> uploading. If a large file has already been committed, run
> **`REPAIR_GIT.bat`** (Windows) or the commands it prints.


```bash
# Linux / macOS
export GITHUB_TOKEN=ghp_yourToken
./scripts/push_to_github.sh --dry-run
./scripts/push_to_github.sh -u yourname -r MIMODH --secrets
```

```powershell
# Windows
$env:GITHUB_TOKEN = "ghp_yourToken"
.\scripts\push_to_github.ps1 -DryRun
.\scripts\push_to_github.ps1 -User yourname -Repo MIMODH -Secrets
```

Token scopes: `repo`, `workflow`, `admin:repo_hook` —
create one at https://github.com/settings/tokens/new

Both scripts run blocking pre-push checks: Python syntax on every file, and a
scan for AWS keys, GitHub tokens and private keys.

---

## Verifying the installation

```bash
# All Python parses
python3 -c "import ast,pathlib; \
  [ast.parse(p.read_text()) for p in pathlib.Path('.').rglob('*.py') \
   if not any(x in str(p) for x in ('.venv','build','dist','__pycache__'))]; \
  print('OK')"

# Shell scripts
for s in scripts/*.sh desktop/*.sh fix_and_build.sh; do bash -n "$s" && echo "OK $s"; done

# Test suite
pytest tests/ -v

# Bundled data
pytest tests/test_data_validation.py -v

# Pipeline smoke test
python -m backend.multiomics_reactome --mode synthetic --n-samples 40
```

---

## Troubleshooting locations

| Error | Cause | Fix |
|---|---|---|
| `Must be run from the repository root` | Wrong working directory | `cd` into the MIMODH folder |
| `scripts/patch_sources.py not found` | `scripts/` moved or incomplete | Restore it from the archive |
| `FIX_AND_BUILD.ps1 not found` | `.bat` and `.ps1` separated | Keep both in the repository root |
| `No virtual environment found` | Setup not run yet | `bash scripts/setup.sh --dev` |
| `Permission denied` (Linux/macOS) | Lost execute bit after unzip | `chmod +x fix_and_build.sh scripts/*.sh desktop/*.sh` |
| `not digitally signed` (Windows) | Zone.Identifier from download | `Unblock-File -Path .\script.ps1`, or use the `.bat` |
