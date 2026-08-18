# Architecture

## Shared core

Every interface calls the same code in `backend/`, so results are identical for
identical inputs.

```
                    backend/multiomics_reactome.py
                    backend/multiomics_pipeline.py
                                  |
        +-------------------------+-------------------------+
        |                         |                         |
   Desktop (PyQt6)          CLI (argparse)          Cloud (FastAPI)
   desktop/app.py           python -m backend...    backend/app.py
```

## Pipeline stages

| # | Stage | Key methods / references |
|---|---|---|
| 1 | Ingest | 14 bulk checks + 6 AnnData checks |
| 2 | Preprocess | normalize, log1p, filter, impute |
| 3 | Batch correction | pycombat (bulk), Harmony (single-cell), MNN (cross-modal) |
| 4 | Integration | NMF (Lee & Seung 2001) + WNN (Hao et al. 2021) |
| 5 | Reactome mapping | ContentService v84 REST -> NetworkX multi-layer graph |
| 6 | Differential analysis | with BH-FDR |
| 7 | Pathway activity | GSEA-preranked (Subramanian et al. 2005) |
| 8 | Visualisation | matplotlib static + Plotly interactive |
| 9 | MIMODH XML | XSD-validated, SHA-256 checksums |

Batch-correction quality is measured with iLISI (≥ 2.0) and kBET (≥ 0.70) and
reported in `validation_report.html`.

## Desktop

```
desktop/app.py
  |-- sys.excepthook -> crash log + Qt error dialog
  |-- _setup_paths() -> handles sys._MEIPASS when frozen
  +-- MainWindow (main_window.py)
        |-- ConfigureTab   mode, files, MIMODH tier, metadata
        |-- RunTab         Run/Stop, live log, progress, 9 stage chips
        |-- ResultsTab     file tree, preview, open-in-viewer
        |-- AboutTab       feature cards, references
        +-- PipelineWorker (QThread)
              |-- redirects stdout/stderr -> Qt signals
              |-- injects numba stub if needed
              |-- filters InputConfig kwargs by signature
              +-- calls backend.multiomics_reactome.run_pipeline()
```

The worker runs on a `QThread` so the UI stays responsive. All pipeline output
is captured by `_LogCapturer` and emitted as Qt signals, then colour-coded in
the Run tab and mirrored to `logs/pipeline_<timestamp>.log`.

## Cloud

```
Browser --HTTPS--> CloudFront --> S3 (React SPA)
Browser --HTTPS--> API Gateway --> Lambda authorizer (Cognito JWT)
                                        |
                                   FastAPI (EC2/ECS, image from ECR)
                                     |            |
                              DynamoDB        SQS FIFO
                             (job state)     (job queue)
                                                  |
                                          Worker (EC2) --> S3 (results)
```

Job lifecycle: `QUEUED` -> `RUNNING` -> `COMPLETED` / `FAILED`, tracked in
DynamoDB. The worker polls SQS, runs the pipeline, uploads artifacts to S3, and
updates the job record.

## Platform-specific handling

| Concern | Solution |
|---|---|
| Frozen-binary imports | Runtime hook puts `sys._MEIPASS` on `sys.path` |
| Bundled test data | `sys._MEIPASS/desktop/test_data` when frozen |
| Output location | Next to the executable, never in the temp extraction dir |
| Screen size | `QApplication.primaryScreen().availableGeometry()` |
| `numba` unavailable | No-op stub injected before scanpy imports |
| No system BLAS | Pure-NumPy Harmony shim |
| Qt QML warnings | Unused plugin folders deleted before packaging |
