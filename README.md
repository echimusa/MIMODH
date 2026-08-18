# MultiOmics-Reactome v3.0

**MIMODH-compliant multi-omics harmonization pipeline** — available as a desktop
application, a cloud web app, and a command-line tool.

[![CI](https://github.com/echimusa/MIMODH/actions/workflows/ci.yml/badge.svg)](https://github.com/echimusa/MIMODH/actions/workflows/ci.yml)
[![MIMODH v1.0](https://img.shields.io/badge/MIMODH-v1.0-1e8449)](https://mimodh.org/schema/v1)
[![Python 3.10–3.13](https://img.shields.io/badge/python-3.10%E2%80%933.13-blue)](https://python.org)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

> Integrates seven omics modalities into a harmonized joint representation mapped
> to Reactome pathways, and emits a schema-validated MIMODH XML record for every run.
>
> MIMODH standard: Agamah et al. 2025, *Frontiers in Genetics*

---

## Contents

| Section | |
|---|---|
| [What it does](#what-it-does) | Modalities, pipeline stages, outputs |
| [Choose your interface](#choose-your-interface) | Desktop / CLI / Cloud |
| [Quick start — Windows](#quick-start--windows) | Double-click installer |
| [Quick start — Linux / macOS](#quick-start--linux--macos) | Shell scripts |
| [Quick start — Cloud](#quick-start--cloud-aws) | AWS deployment |
| [MIMODH compliance](#mimodh-compliance) | Tier 1 / 2 / 3 fields |
| [Repository layout](#repository-layout) | Directory map |
| [Testing](#testing) | Test suite and CI |
| [Troubleshooting](#troubleshooting) | Common issues |
| [References](#references) | Citations |

---

## What it does

**Seven modalities in, one harmonized representation out.**

| Modality | Formats accepted |
|---|---|
| Genomics (SNP) | CSV, TSV, Parquet |
| Transcriptomics | CSV, TSV, Parquet |
| Proteomics | CSV, TSV, Parquet |
| Metabolomics | CSV, TSV, Parquet |
| scRNA-seq | `.h5ad`, 10x MEX directory, CSV |
| scATAC-seq | `.h5ad`, 10x MEX directory |
| Spatial (Visium) | `.h5ad`, 10x Visium directory |

**Pipeline stages**

1. **Ingest** — load and validate all modalities (14 bulk + 6 AnnData checks)
2. **Preprocess** — normalize, log-transform, filter, impute
3. **Batch correction** — pycombat (bulk) → Harmony (single-cell) → MNN (cross-modal)
4. **Integration** — GPU-accelerated NMF + WNN affinity fusion
5. **Reactome mapping** — REST API (ContentService v84) → multi-layer NetworkX graph
6. **Differential analysis** — with Benjamini–Hochberg FDR correction
7. **Pathway activity scoring** — GSEA-preranked
8. **Visualization** — static plots + interactive HTML network
9. **MIMODH XML export** — XSD-validated record with SHA-256 checksums

**Outputs** (per run)

```
output/
├── mimodh_record.xml            MIMODH-compliant metadata record
├── differential_analysis.csv    DE results with FDR
├── pathway_activity_scores.csv  PAS per sample per pathway
├── reactome_mapping.csv         entity → pathway mappings
├── network_overview.png         pathway network
├── network_de_overlay.png       network coloured by DE
├── analysis_results.png         volcano + PCA + heatmaps
├── interactive_network.html     zoomable Plotly network
└── validation_report.html       QC and batch-correction metrics
```

---

## Choose your interface

| | Desktop app | CLI | Cloud web app |
|---|---|---|---|
| **Best for** | Single user, laptop | Scripting, HPC | Teams, large data |
| **Install effort** | One double-click | `pip install` | AWS deployment |
| **Runs offline** | Yes | Yes | No |
| **Multi-user** | No | No | Yes (Cognito auth) |
| **Max dataset** | Local RAM | Local RAM | SageMaker |
| **Bundled test data** | Yes | Yes | Manual upload |
| **MIMODH XML** | Identical | Identical | Identical |
| **Platforms** | Windows, macOS, Linux | Any | Browser |

---

## Quick start — Windows

**No Python or technical knowledge required.**

0. Double-click **`UNBLOCK_ALL.bat`** — **do this first.** Windows blocks
   scripts extracted from a downloaded zip; this clears the mark
1. Install Python 3.11 from [python.org](https://www.python.org/downloads/) —
   tick **"Add Python to PATH"** during install
2. Double-click **`BUILD_APP.bat`**
3. Wait 10–20 minutes (first run only — it downloads and installs everything)
4. Double-click **`dist\MultiOmicsReactome.exe`**

> Skipping step 0 causes `"...is not digitally signed. You cannot run this
> script on the current system."` on every PowerShell script.

The `.exe` is fully standalone — copy it to a USB stick or share it with colleagues.
No Python needed on the target machine.

**To try it immediately:** Configure tab → **Load Bundled Test Data** → **Run Pipeline**

<details>
<summary>Windows: individual scripts</summary>

```powershell
# One-time: allow scripts
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

.\build_desktop_installer.ps1   # full setup + build .exe
.\FIX_AND_BUILD.ps1             # patch sources + rebuild (faster)
.\RUN_DEBUG.bat                 # launch with crash logging
.\scripts\push_to_github.ps1    # push to GitHub
```
</details>

See **[desktop/README.md](desktop/README.md)** for the full desktop guide.

---

## Quick start — Linux / macOS

```bash
git clone https://github.com/echimusa/MIMODH.git
cd MIMODH

# Environment (NumPy 2.x ABI-safe install order)
bash scripts/setup.sh --dev            # add --gpu for CUDA PyTorch
source .venv_mimodh/bin/activate

# --- Option A: command line ---
python -m backend.multiomics_reactome \
    --mode synthetic --n-samples 120 --n-batches 3 --mimodh-tier Tier2

# --- Option B: desktop GUI ---
pip install -r desktop/requirements_desktop.txt
python -m desktop.app

# --- Option C: build a standalone binary ---
bash desktop/build_desktop.sh
./dist/MultiOmicsReactome
```

**Run with your own data**

```bash
python -m backend.multiomics_reactome \
    --mode real \
    --transcriptomics data/counts.csv \
    --proteomics      data/protein.csv \
    --metadata        data/samples.csv \
    --mimodh-tier Tier3 \
    --disease "colorectal-cancer"
```

Your metadata CSV must contain `condition` and `batch` columns.
`batch` values must be **strings** (`batch_0`, `batch_A`) — not bare integers.

---

## Quick start — Cloud (AWS)

**Interactive, idempotent, with a dry-run mode.**

```bash
# Prerequisites: aws-cli v2, docker, node 20+
aws configure                      # if not already done

./scripts/deploy_aws.sh --dry-run  # preview the plan, change nothing
./scripts/deploy_aws.sh            # deploy for real
```

You'll be prompted for:

| Prompt | Example | Notes |
|---|---|---|
| AWS region | `eu-west-2` | Defaults to your CLI region |
| Application name | `multiomics` | Used in all resource names |
| Stage | `prod` | `prod` / `staging` / `dev` |
| **Your domain** | `mimodh.example.org` | Leave blank to use the CloudFront URL |
| EC2 instance type | `t3.large` | `g4dn.xlarge` for GPU |
| Admin email | `you@example.org` | Creates the first Cognito user |

Answers are saved to `deploy_<stage>.env` so re-runs need no input:

```bash
./scripts/deploy_aws.sh --config deploy_prod.env            # re-deploy
./scripts/deploy_aws.sh --config deploy_prod.env --destroy  # tear down
```

**Local development stack** (no AWS account needed):

```bash
docker compose up --build
#   API      http://localhost:8000/docs
#   Frontend http://localhost:5173
#   AWS mock http://localhost:4566   (LocalStack)
```

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for architecture, DNS setup,
TLS certificates, cost estimates, and CI/CD.

---

## MIMODH compliance

Every run emits `mimodh_record.xml`, validated against `schemas/mimodh_v1.xsd`.

| Tier | Required fields | Use case |
|---|---|---|
| **Tier 1**<br>*minimum recoverable* | `sample_id`, `condition`, `batch`, `modality`, `data_path` | Internal / exploratory |
| **Tier 2**<br>*recommended* | Tier 1 + `age`, `sex`, `bmi`, `platform`, `tissue_type` | Publication |
| **Tier 3**<br>*full FAIR* | Tier 2 + `treatment`, `survival`, `cell_type`, `reference_genome`, `normalization_method`, `ethical_approval`, `accession` | Archiving, data sharing |

The XML record captures study metadata, sample manifest, per-modality
preprocessing provenance, batch-correction benchmarks (iLISI, kBET),
integration parameters, DE results, pathway activity scores, a quality report,
and SHA-256 checksums for every output artifact.

Validate manually:

```bash
python -c "from lxml import etree; \
  etree.XMLSchema(etree.parse('schemas/mimodh_v1.xsd')) \
  .assertValid(etree.parse('output/mimodh_record.xml')); \
  print('MIMODH XML valid')"
```

---

## Repository layout

```
MIMODH/
├── backend/                      Pipeline core (platform-independent)
│   ├── multiomics_reactome.py    Reactome network pipeline
│   ├── multiomics_pipeline.py    Integration engine
│   └── app.py                    FastAPI REST API
├── desktop/                      PyQt6 desktop application
│   ├── app.py                    Entry point + splash
│   ├── main_window.py            Main window, 4 tabs
│   ├── pipeline_worker.py        QThread pipeline runner
│   ├── styles.py                 Dark theme (QSS)
│   ├── widgets/                  Configure / Run / Results / About
│   ├── test_data/                Bundled 40-sample dataset
│   ├── build_desktop.sh          Build binary (Linux/macOS)
│   └── README.md                 Desktop guide
├── frontend/                     React 18 SPA
│   ├── src/App.jsx               Upload, run, visualise, download
│   └── package.json
├── infra/
│   ├── lambda_authorizer.py      Cognito JWT authorizer
│   └── cloudformation.yml        Full AWS stack
├── schemas/
│   └── mimodh_v1.xsd             W3C XML Schema (MIMODH v1.0)
├── scripts/
│   ├── setup.sh                  Environment bootstrap (Linux/macOS)
│   ├── setup.ps1                 Environment bootstrap (Windows)
│   ├── deploy_aws.sh             Interactive AWS deployment
│   ├── push_to_github.sh         Push to GitHub (Linux/macOS)
│   └── push_to_github.ps1        Push to GitHub (Windows)
├── docker/Dockerfile             Multi-stage API/worker image
├── docker-compose.yml            Local dev stack + LocalStack
├── tests/                        pytest suite
├── docs/
│   ├── ARCHITECTURE.md           System design
│   ├── DEPLOYMENT.md             AWS + domain setup
│   └── CONTRIBUTING.md           Development guide
├── .github/workflows/            CI (ci.yml) and CD (deploy.yml)
├── BUILD_APP.bat                 Windows one-click builder
├── FIX_AND_BUILD.ps1             Windows patch + rebuild
└── requirements.txt              Pinned dependencies
```

---

## Testing

```bash
pytest tests/ -v --cov=backend --cov-report=term-missing

# Desktop tests (headless)
QT_QPA_PLATFORM=offscreen pytest tests/test_desktop.py -v

# Validate bundled test data
pytest tests/test_data_validation.py -v

# MIMODH schema
pytest tests/test_mimodh_xml.py -v
```

CI runs on every push to `main`, `dev`, `staging`:

| Job | Checks |
|---|---|
| `lint` | ruff + black on `backend/`, `desktop/`, `tests/` |
| `test-syntax` | `ast.parse()` on every Python file |
| `test-backend` | pytest on Python 3.10 and 3.11, ≥75% coverage |
| `test-data-validation` | batch column is string, no NaN, no negatives, IDs aligned |
| `mimodh-xsd` | XSD schema parses and validates |
| `desktop-test` | headless PyQt6 import test |
| `frontend-build` | `npm ci && npm run build` |
| `docker-build` | Docker image builds |

---

## Troubleshooting

<details>
<summary><b>Windows: "script is not digitally signed"</b></summary>

```powershell
Unblock-File -Path .\script.ps1
# or run via the .bat launcher, which handles this automatically
```
</details>

<details>
<summary><b>numba won't install</b></summary>

`numba` needs `llvmlite`, which lags new Python releases by ~6 months.
It is **optional** — the pipeline injects a no-op stub and runs in pure Python.

For full speed, use Python 3.11 or conda:
```bash
conda create -n mimodh python=3.11 numba -y
conda activate mimodh
pip install -r requirements.txt
```
</details>

<details>
<summary><b>harmonypy build fails (CMake / BLAS error)</b></summary>

`harmonypy >= 0.0.11` compiles C++ and needs a system BLAS.
The setup scripts fall back to pure-Python `0.0.10`, or to a built-in
NumPy shim (validated at 98–99% batch-variance reduction).
</details>

<details>
<summary><b>Desktop app crashes on launch</b></summary>

Run `RUN_DEBUG.bat` (Windows) — it writes `crash_log.txt` with the full traceback.
The app also writes `dist/MultiOmicsReactome_crash.log` automatically.
</details>

<details>
<summary><b>Pipeline: "batch must be string dtype"</b></summary>

Your metadata `batch` column contains integers. Convert them:
```python
meta["batch"] = meta["batch"].apply(lambda x: f"batch_{x}")
meta.to_csv("metadata_fixed.csv")
```
</details>

<details>
<summary><b>AWS deploy: "credentials not configured"</b></summary>

```bash
aws configure
aws sts get-caller-identity   # should print your account and ARN
```
</details>

---

## Citation

```bibtex
@software{multiomics_reactome_2025,
  author  = {Chimusa, E.R.},
  title   = {MultiOmics-Reactome v3.0: MIMODH-Compliant Multi-Omics
             Harmonization Pipeline},
  year    = {2025},
  url     = {https://github.com/echimusa/MIMODH},
  version = {3.0.0}
}
```

## References

| | |
|---|---|
| Agamah et al. 2025 | MIMODH framework — *Frontiers in Genetics* |
| Johnson et al. 2007 | ComBat batch correction — *Biostatistics* 8:118 |
| Korsunsky et al. 2019 | Harmony — *Nat. Methods* 16:1289 |
| Haghverdi et al. 2018 | MNN — *Nat. Biotechnol.* 36:421 |
| Lee & Seung 2001 | NMF update rules — *NeurIPS* |
| Hao et al. 2021 | WNN / Seurat v4 — *Cell* 184:3573 |
| Argelaguet et al. 2020 | MOFA+ — *Nat. Biotechnol.* 38:1251 |
| Subramanian et al. 2005 | GSEA-preranked — *PNAS* 102:15545 |
| Gillespie et al. 2022 | Reactome v84 — *NAR* 50:D687 |
| Büttner et al. 2019 | kBET — *Nat. Methods* 16:43 |
| Benjamini & Hochberg 1995 | BH-FDR — *JRSS-B* 57:289 |

## License

MIT — see [LICENSE](LICENSE).
