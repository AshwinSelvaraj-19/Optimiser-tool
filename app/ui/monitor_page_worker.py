"""
Background worker for MonitorPage.

Moves expensive input latency analysis and thermal diagnostics
off the GUI thread.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Any

from PySide6.QtCore import QObject, Signal, QThread


# ── result container ───────────────────────────────────────────────

@dataclass
class MonitorWorkerResult:
    """Results computed off the GUI thread."""
    elapsed_ms: float = 0.0

    # input latency
    input_latency_report: Optional[Any] = None

    # thermal
    thermal_diag: Optional[Any] = None


# ── worker ─────────────────────────────────────────────────────────

class _MonitorWorker(QObject):
    """Performs expensive MonitorPage diagnostics in a background thread."""

    finished = Signal(object)
    error = Signal(str)

    def do_work(self):
        t0 = time.perf_counter()
        result = MonitorWorkerResult()
        try:
            self._collect(result)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        self.finished.emit(result)

    def _collect(self, r: MonitorWorkerResult):
        # Input latency analysis (~4.4s)
        try:
            from app.performance.input_latency import input_latency_analyzer
            r.input_latency_report = input_latency_analyzer.analyze()
        except Exception:
            pass

        # Thermal diagnostics (~1.7s)
        try:
            from app.system.thermal_monitor import thermal_diagnostics
            r.thermal_diag = thermal_diagnostics.diagnose()
        except Exception:
            pass


class MonitorWorkerThread(QThread):
    """Manages the MonitorPage worker lifecycle."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = _MonitorWorker()
        self._worker.moveToThread(self)
        self._worker.finished.connect(self.finished)
        self._worker.error.connect(self.error)
        self.started.connect(self._worker.do_work)
        self.setObjectName("monitor_page_worker")
