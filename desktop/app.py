# -*- coding: utf-8 -*-
"""
app.py — MultiOmics-Reactome Desktop v3.0
==========================================
Standalone PyQt6 desktop application.
Supports Linux, Windows, and macOS.

Usage:
    python -m desktop.app           # from repo root
    python desktop/app.py           # direct
    multiomics_desktop              # after PyInstaller build

Requires: PyQt6 (pip install PyQt6)
"""
import sys
import os
from pathlib import Path

# Ensure repo root is on path when run as a script
_ROOT = Path(__file__).parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

# When frozen, the extraction folder must also be importable.
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    for _p in (sys._MEIPASS,
               os.path.join(sys._MEIPASS, "desktop"),
               os.path.join(sys._MEIPASS, "backend")):
        if _p not in sys.path:
            sys.path.insert(0, _p)


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


def _check_pyqt():
    try:
        import PyQt6.QtWidgets
    except ImportError:
        print("ERROR: PyQt6 is required for the desktop app.\n"
              "Install with:  pip install PyQt6\n"
              "Then re-run:   python -m desktop.app")
        sys.exit(1)


def main():
    _check_pyqt()

    from PyQt6.QtWidgets import QApplication, QSplashScreen
    from PyQt6.QtGui     import QPixmap, QColor, QPainter, QFont, QFontMetrics
    from PyQt6.QtCore    import Qt, QTimer

    app = QApplication(sys.argv)
    app.setApplicationName("MultiOmics-Reactome")
    app.setApplicationVersion("3.0.0")
    app.setOrganizationName("MIMODH")

    # ── Splash screen ─────────────────────────────────────────────────────────
    pix = QPixmap(520, 300)
    pix.fill(QColor("#0f1117"))
    painter = QPainter(pix)

    # Background gradient rectangle
    painter.setBrush(QColor("#1a1f2e"))
    painter.setPen(QColor("#2d3748"))
    painter.drawRoundedRect(20, 20, 480, 260, 12, 12)

    # Title
    painter.setPen(QColor("#60a5fa"))
    painter.setFont(QFont("Segoe UI", 22, QFont.Weight.Bold))
    painter.drawText(40, 90, "MultiOmics-Reactome")

    painter.setPen(QColor("#9ca3af"))
    painter.setFont(QFont("Segoe UI", 13))
    painter.drawText(40, 120, "Desktop v3.0.0  ·  MIMODH v1.0")

    painter.setPen(QColor("#6ee7b7"))
    painter.setFont(QFont("Segoe UI", 10))
    painter.drawText(40, 155, "MIMODH-Compliant Multi-Omics Harmonization")
    painter.drawText(40, 175, "Agamah et al. 2025  ·  Frontiers in Genetics")

    painter.setPen(QColor("#4b5563"))
    painter.setFont(QFont("Segoe UI", 9))
    painter.drawText(40, 260, "Loading pipeline modules…")

    painter.end()

    splash = QSplashScreen(pix, Qt.WindowType.WindowStaysOnTopHint)
    splash.show()
    app.processEvents()

    # ── Import (may take a moment) ────────────────────────────────────────────
    from desktop.main_window import MainWindow

    window = MainWindow()

    def _show():
        splash.finish(window)
        window.show()

    QTimer.singleShot(1800, _show)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
