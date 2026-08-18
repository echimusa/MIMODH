# MultiOmics-Reactome Desktop

Standalone PyQt6 application — **Windows, macOS, Linux**.
Runs fully offline; the Reactome API is optional.

---

## Windows — one double-click

1. Install Python 3.11 from [python.org](https://www.python.org/downloads/)
   (tick **"Add Python to PATH"**)
2. Double-click **`BUILD_APP.bat`** in the repository root
3. Wait 10–20 minutes (first run only)
4. Double-click **`dist\MultiOmicsReactome.exe`**

The builder automatically installs Python (if missing), creates an isolated
virtual environment in `.venv_build\`, installs C++ Build Tools if available,
resolves all dependencies with fallbacks, generates the test data, and
compiles the `.exe`.

Nothing is written outside the repository folder.

### Windows scripts

| Script | Purpose |
|---|---|
| `BUILD_APP.bat` | **Start here.** Full setup + build |
| `build_desktop_installer.ps1` | Same, run directly from PowerShell |
| `FIX_AND_BUILD.ps1` | Patch sources + rebuild (faster, for iterating) |
| `RUN_DEBUG.bat` | Launch the `.exe` with crash logging to `crash_log.txt` |

If PowerShell refuses to run a script:
```powershell
Unblock-File -Path .\build_desktop_installer.ps1
# or just use the .bat launcher, which handles this
```

---

## Linux / macOS

```bash
# Install
bash scripts/setup.sh --dev
source .venv_mimodh/bin/activate
pip install -r desktop/requirements_desktop.txt

# Run
python -m desktop.app

# Build a standalone binary (optional)
bash desktop/build_desktop.sh
./dist/MultiOmicsReactome              # Linux
open dist/MultiOmicsReactome.app       # macOS
```

**macOS Gatekeeper** — unsigned binaries are quarantined:
```bash
xattr -rd com.apple.quarantine dist/MultiOmicsReactome.app
```

**Linux Qt platform plugin errors** — install the X11/Wayland libs:
```bash
sudo apt install -y libxcb-cursor0 libxcb-xinerama0 libxkbcommon-x11-0 \
                    libegl1 libgl1-mesa-glx
```

---

## First run — bundled test data

1. **Configure** tab
2. Click **Load Bundled Test Data** — all four paths auto-fill
3. Leave MIMODH tier at **Tier 2**
4. Click **Run Pipeline**
5. Results appear in the **Results** tab, with `mimodh_record.xml` highlighted green

### Bundled dataset

| File | Shape | Content |
|---|---|---|
| `transcriptomics_test.csv` | 40 × 70 | Bulk RNA-seq, HGNC symbols (TP53, EGFR, BRCA1…), negative-binomial + batch effect |
| `proteomics_test.csv` | 40 × 24 | MS proteomics, UniProt accessions (P04637…), log-normal |
| `metabolomics_test.csv` | 40 × 20 | LC-MS, ChEBI IDs (CHEBI:15422…) |
| `metadata_test.csv` | 40 × 14 | condition, batch, age, sex, bmi, tissue_type, disease_stage, treatment, platform, rin_score, reference_genome |

40 samples · 20 Case / 20 Control · 3 batches (14/13/13) ·
first 15 genes upregulated 3× in cases · additive + multiplicative batch noise.
Reproducible (NumPy seed 42).

Regenerate:
```bash
python desktop/test_data/generate_test_data.py
```

---

## Interface

| Tab | Contents |
|---|---|
| **Configure** | Mode (Synthetic / Real / Mixed) · file pickers for all 7 modalities · MIMODH tier selector · study metadata (disease, PI, institution, ethics, accession) · synthetic parameters · output directory |
| **Run** | Large Run / Stop buttons · live colour-coded log with timestamps · progress bar · 9 stage chips that light up as the pipeline advances · elapsed timer |
| **Results** | Grouped file tree (MIMODH record / tables / figures / HTML) · text, CSV and XML preview · open in system viewer · green banner when the MIMODH XML is written |
| **About** | Feature cards for each subsystem · full reference list |

---

## Using your own data

### Bulk omics (CSV / TSV / Parquet)

Rows = samples, columns = features. First column is the sample ID.

```csv
sample_id,TP53,EGFR,BRCA1,...
S000,12.4,8.1,3.3,...
S001,9.8,11.2,4.1,...
```

### Metadata (required for Real mode)

Must contain `condition` and `batch`. **`batch` values must be strings**:

```csv
sample_id,condition,batch,age,sex,bmi,tissue_type,platform
S000,Case,batch_0,54,F,26.1,Primary tumour,Illumina NovaSeq 6000
S001,Control,batch_1,61,M,24.8,Primary tumour,Illumina NovaSeq 6000
```

If your batches are integers, convert them:
```python
import pandas as pd
m = pd.read_csv("metadata.csv", index_col=0)
m["batch"] = m["batch"].apply(lambda x: f"batch_{x}")
m.to_csv("metadata_fixed.csv")
```

### Single-cell and spatial

Point the picker at a `.h5ad` file or a 10x MEX / Visium **directory**.

---

## Outputs and logs

Results are written next to the `.exe` (or to the directory you chose):

```
dist/
├── MultiOmicsReactome.exe
├── output/
│   ├── mimodh_record.xml
│   ├── differential_analysis.csv
│   ├── pathway_activity_scores.csv
│   ├── network_overview.png
│   ├── interactive_network.html
│   └── validation_report.html
└── logs/
    └── pipeline_20260802_164417.log
```

Every run writes a timestamped log. The log path is shown in the Run tab.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `ModuleNotFoundError: PyQt6` | `pip install PyQt6` |
| `ModuleNotFoundError: backend` | Run from the repo root: `python -m desktop.app` |
| App exits with no window | Run `RUN_DEBUG.bat`; read `crash_log.txt` |
| Window options cut off at the bottom | Fixed in v3.0 (screen-aware sizing). Re-run `FIX_AND_BUILD.ps1` |
| Run button does nothing | Fixed in v3.0 (test-data path resolution inside the `.exe`) |
| `No module named 'numba'` | Fixed in v3.0 (no-op stub). Re-run `FIX_AND_BUILD.ps1` |
| `No module named 'harmonypy'` | Re-run `FIX_AND_BUILD.ps1` — it installs a pure-Python version or a shim |
| macOS "app can't be opened" | `xattr -rd com.apple.quarantine dist/MultiOmicsReactome.app` |
| Antivirus blocks the `.exe` | Add `dist\` to exclusions. PyInstaller binaries are often false-positived |
| Build fails on numpy | Ensure NumPy ≥ 2.0 installs **before** other packages (the setup scripts do this) |
| Reactome step hangs | The REST API can be slow. Synthetic mode has no network dependency |

### Getting a useful crash report

```powershell
.\RUN_DEBUG.bat          # Windows: writes crash_log.txt
```
```bash
python -m desktop.app 2>&1 | tee crash.log     # Linux/macOS
```

Also check `dist/MultiOmicsReactome_crash.log` — the app writes it
automatically on any unhandled exception, even when the window never appears.

---

## Build internals

```
desktop/
├── app.py                 Entry point, splash, sys.excepthook, _MEIPASS paths
├── main_window.py         MainWindow: tabs, timer, worker coordination
├── pipeline_worker.py     QThread; captures stdout/stderr; numba stub; logging
├── styles.py              Dark QSS theme (navy / teal / emerald)
├── widgets/
│   ├── configure_tab.py   Mode, file pickers, MIMODH tier, metadata
│   ├── run_tab.py         Run/Stop, live log, progress, stage chips
│   ├── results_tab.py     File tree, preview, open-in-viewer
│   └── about_tab.py       Feature cards, references
├── test_data/             Bundled dataset + generator
├── resources/             Place icon.ico / icon.icns / icon.png here
├── build_desktop.sh       PyInstaller build (Linux/macOS)
├── multiomics_desktop.spec PyInstaller spec
└── requirements_desktop.txt
```

**PyInstaller notes** (why the build scripts do what they do):

- `--collect-all` is required for matplotlib, scanpy, sklearn and scipy —
  `--hidden-import` alone misses their data files
- `numba` is excluded (needs `tbb12.dll`, which cannot be bundled) and replaced
  at runtime by a no-op stub
- Qt QML/3D plugin folders are deleted from the venv before building — they
  reference optional DLLs that PyQt6 does not ship, producing 50+ warnings
- A runtime hook puts `sys._MEIPASS` on `sys.path` so `desktop.*` and
  `backend.*` resolve inside the frozen executable
- `__init__.py` files use plain comments, not docstrings — PyInstaller's
  bytecode compiler can fail on non-ASCII module docstrings

---

## Desktop vs Web

| | Desktop (PyQt6) | Web (React + FastAPI) |
|---|---|---|
| Install needed | Python, or none for the `.exe` | Docker Compose or AWS |
| Offline / air-gapped | Yes | No |
| Multiple users | No | Yes (Cognito) |
| Large datasets | Local RAM | SageMaker |
| Test data | Bundled | Manual upload |
| MIMODH XML | Identical | Identical |

Both share the same `backend/` pipeline code, so results are byte-identical
for the same inputs and parameters.
