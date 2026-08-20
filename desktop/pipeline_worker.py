"""
pipeline_worker.py — QThread wrapper for the MultiOmics-Reactome pipeline.
Captures stdout/stderr in real-time and emits Qt signals.
"""
from __future__ import annotations

import io
import os
import sys
import traceback
from pathlib import Path
from typing import Any, Dict, Optional

from PyQt6.QtCore import QThread, pyqtSignal


def _setup_pipeline_logging():
    """Mirror pipeline output to logs/pipeline_<timestamp>.log."""
    import datetime
    import logging
    import sys as _sys
    from pathlib import Path as _Path

    if getattr(_sys, "frozen", False):
        base = _Path(_sys.executable).parent
    else:
        base = _Path(__file__).parent.parent

    log_dir = base / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = log_dir / ("pipeline_" + stamp + ".log")

    fh = logging.FileHandler(log_path, mode="w", encoding="utf-8")
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"))

    root = logging.getLogger()
    root.setLevel(logging.DEBUG)
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler):
            root.removeHandler(h)
    root.addHandler(fh)

    logging.info("=" * 70)
    logging.info("MultiOmics-Reactome pipeline log")
    logging.info("Started : %s", datetime.datetime.now().isoformat())
    logging.info("Python  : %s", _sys.version.replace("\n", " "))
    logging.info("Frozen  : %s", getattr(_sys, "frozen", False))
    logging.info("Log file: %s", log_path)
    logging.info("=" * 70)
    return log_path


class PipelineWorker(QThread):
    """
    Runs the MultiOmics-Reactome pipeline in a background thread.

    Signals
    -------
    log_line(str, str)       — (message, level) for the live log
    progress(int, str)       — (0-100, stage label)
    finished(dict)           — pipeline result dict on success
    failed(str)              — error message on failure
    """

    log_line  = pyqtSignal(str, str)   # (text, level)
    progress  = pyqtSignal(int, str)   # (pct, label)
    finished  = pyqtSignal(dict)
    failed    = pyqtSignal(str)

    STAGE_PROGRESS = {
        "Data ingestion":       10,
        "Preprocessing":        25,
        "NMF":                  42,
        "Reactome":             55,
        "Network":              65,
        "Differential":         75,
        "Pathway activity":     85,
        "Overlay":              92,
        "MIMODH":               97,
        "COMPLETE":            100,
    }

    def __init__(self, config: Dict[str, Any], parent=None):
        super().__init__(parent)
        self.config  = config
        self._abort  = False

    def abort(self):
        self._abort = True
        self.terminate()

    # ── Main thread entry ────────────────────────────────────────────────────
    def run(self):
        # Redirect sys.stdout / logging to capture pipeline output
        capturer = _LogCapturer(self._emit_log)
        old_stdout = sys.stdout
        old_stderr = sys.stderr
        sys.stdout = capturer
        sys.stderr = capturer

        try:
            self._run_pipeline()
        except Exception as exc:
            tb = traceback.format_exc()
            self.log_line.emit(f"FATAL: {exc}", "ERROR")
            self.log_line.emit(tb, "ERROR")
            self.failed.emit(str(exc))
        finally:
            sys.stdout = old_stdout
            sys.stderr = old_stderr

    def _emit_log(self, text: str):
        """Called by _LogCapturer for every line; classifies level and emits."""
        if not text.strip():
            return
        level = "INFO"
        tl = text.lower()
        if any(k in tl for k in ("error", "traceback", "exception", "fatal")):
            level = "ERROR"
        elif any(k in tl for k in ("warning", "warn")):
            level = "WARNING"
        elif any(k in tl for k in ("complete", "✓", "saved", "passed")):
            level = "SUCCESS"
        elif text.startswith("[") and any(k in text for k in ("/8]", "MIMODH")):
            level = "SECTION"
        elif "mimodh" in tl or "xml" in tl:
            level = "MIMODH"

        self.log_line.emit(text.rstrip(), level)

        # Update progress bar from stage keywords
        for keyword, pct in self.STAGE_PROGRESS.items():
            if keyword.lower() in tl:
                label = keyword
                self.progress.emit(pct, label)
                break

    def _run_pipeline(self):
        _log_path = _setup_pipeline_logging()
        self.log_line.emit('Log file: ' + str(_log_path), 'INFO')
        cfg_dict = self.config

        # Add repo root to path
        if getattr(sys, "frozen", False):
            repo_root = Path(sys._MEIPASS)
        else:
            repo_root = Path(__file__).parent.parent
        if str(repo_root) not in sys.path:
            sys.path.insert(0, str(repo_root))

        # numba: scanpy imports it unconditionally and calls into it at runtime.
        # The real package cannot be bundled on Windows (native threading dependency),
        # so install a complete no-op substitute when it is unavailable.
        try:
            from backend._numba_stub import install as _install_numba
        except ImportError:
            try:
                from _numba_stub import install as _install_numba
            except ImportError:
                _install_numba = lambda: False
        _NUMBA_STUBBED = _install_numba()

        # Dependency preflight. A packaging gap should be reported as a
        # complete, actionable list before any analysis begins, not as a
        # traceback from whichever import happens to fail first.
        try:
            from backend._deps import check_dependencies, format_report
            _dep = check_dependencies()
            if _dep["missing_required"]:
                self.log_line.emit(format_report(_dep), "ERROR")
                raise ImportError(
                    "Required package(s) missing: "
                    + ", ".join(d.module for d in _dep["missing_required"])
                    + ". See the log above for what each one is for.")
            if _dep["missing_optional"]:
                for d in _dep["missing_optional"]:
                    self.log_line.emit(
                        f"Optional package '{d.module}' not installed - "
                        f"{d.purpose}", "WARNING")
        except ImportError as exc:
            if "Required package" in str(exc):
                raise
            # backend._deps itself unavailable; continue and let the real
            # import below produce the error.
            pass

        from backend.multiomics_reactome import (
            InputConfig, run_pipeline, OUTPUT_DIR
        )
        import backend.multiomics_reactome as mr

        out_dir = Path(cfg_dict.get("output_dir", "multiomics_reactome_output"))
        out_dir.mkdir(parents=True, exist_ok=True)
        mr.OUTPUT_DIR = out_dir

        def _p(v):
            return Path(v) if v else None

        # Build InputConfig with only the kwargs it actually accepts.
        # Pipeline versions differ, so introspect the signature at runtime.
        import inspect as _inspect
        _sig = _inspect.signature(InputConfig.__init__)
        _supported = set(_sig.parameters.keys()) - {"self"}

        _all_kw = {
            "mode":            cfg_dict.get("mode", "synthetic"),
            "transcriptomics": _p(cfg_dict.get("transcriptomics")),
            "proteomics":      _p(cfg_dict.get("proteomics")),
            "metabolomics":    _p(cfg_dict.get("metabolomics")),
            "genomics":        _p(cfg_dict.get("genomics")),
            "sc_rna":          _p(cfg_dict.get("sc_rna")),
            "sc_atac":         _p(cfg_dict.get("sc_atac")),
            "spatial":         _p(cfg_dict.get("spatial")),
            "metadata":        _p(cfg_dict.get("metadata")),
            "n_samples":       int(cfg_dict.get("n_samples", 120)),
            "n_cells":         int(cfg_dict.get("n_cells", 400)),
            "n_batches":       int(cfg_dict.get("n_batches", 3)),
            "mimodh_tier":     cfg_dict.get("mimodh_tier", "Tier2"),
            "study_id":        cfg_dict.get("study_id") or "",
            "disease":         cfg_dict.get("disease", "unspecified"),
            "pi":              cfg_dict.get("pi") or None,
            "institution":     cfg_dict.get("institution") or None,
            "data_repo":       cfg_dict.get("data_repo", "local"),
            "accession":       cfg_dict.get("accession") or None,
            "ethics":          cfg_dict.get("ethics") or None,
            "integration_method": cfg_dict.get("integration_method", "nmf"),
        }
        _use_kw = {k: v for k, v in _all_kw.items() if k in _supported}
        _extra = sorted(set(_all_kw) - set(_use_kw))
        if _extra:
            print("[INFO] InputConfig does not accept: " + ", ".join(_extra))
            print("[INFO] These MIMODH fields are attached as attributes instead.")

        cfg = InputConfig(**_use_kw)

        for _k in _extra:
            try:
                setattr(cfg, _k, _all_kw[_k])
            except Exception:
                pass
        _method = cfg_dict.get("integration_method", "nmf")
        self.log_line.emit(f"Integration back-end: {_method}", "INFO")
        self.progress.emit(5, "Initialising")

        # Forward the integration method only if this backend accepts it,
        # so an older backend/multiomics_reactome.py still runs.
        _run_kw = {"n_perm": int(cfg_dict.get("n_perm", 200))}
        if "integration_method" in _inspect.signature(run_pipeline).parameters:
            _run_kw["integration_method"] = _method
        else:
            self.log_line.emit(
                "This backend does not expose integration_method; "
                "using its default (NMF).", "WARNING")
        result = run_pipeline(cfg, **_run_kw)
        self.progress.emit(100, "COMPLETE")
        self.finished.emit({"output_dir": str(out_dir), **{
            k: str(v) for k, v in result.items()
            if isinstance(v, Path) or k in ("xml_path",)
        }})


class _LogCapturer(io.TextIOBase):
    """Intercepts write() calls from logging/print and routes to callback."""

    def __init__(self, callback):
        super().__init__()
        self._cb = callback
        self._buf = ""

    def write(self, text: str) -> int:
        self._buf += text
        while "\n" in self._buf:
            line, self._buf = self._buf.split("\n", 1)
            self._cb(line)
        return len(text)

    def flush(self): pass
    def isatty(self): return False
