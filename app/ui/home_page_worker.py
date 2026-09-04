"""
Background worker for HomePage.

Moves expensive target detection, hardware profiling, and
PresentMon discovery off the GUI thread.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Any

from PySide6.QtCore import QObject, Signal, QThread


# ── Short-lived caches for slow-changing data ─────────────────────

_hardware_profile_cache = None
_hardware_profile_ts = 0.0
_presentmon_cache = None
_presentmon_cache_ts = 0.0

HARDWARE_PROFILE_TTL = 30.0   # seconds
PRESENTMON_TTL = 60.0         # seconds


def _get_hardware_profile():
    global _hardware_profile_cache, _hardware_profile_ts
    now = time.time()
    if _hardware_profile_cache and (now - _hardware_profile_ts) < HARDWARE_PROFILE_TTL:
        return _hardware_profile_cache
    from app.core.hardware_profile import analyze_hardware_profile
    _hardware_profile_cache = analyze_hardware_profile()
    _hardware_profile_ts = now
    return _hardware_profile_cache


def _get_presentmon():
    global _presentmon_cache, _presentmon_cache_ts
    now = time.time()
    if _presentmon_cache is not None and (now - _presentmon_cache_ts) < PRESENTMON_TTL:
        return _presentmon_cache
    from app.performance.presentmon_provider import find_presentmon
    _presentmon_cache = find_presentmon()
    _presentmon_cache_ts = now
    return _presentmon_cache


# ── result container ───────────────────────────────────────────────

@dataclass
class HomePageResult:
    """All data the HomePage needs, computed off-thread."""
    elapsed_ms: float = 0.0

    # target detection
    target_emulator: str = ""
    target_process: str = ""
    target_pid: int = 0
    target_gpu: str = "--"

    # hardware profile
    hw_tier: str = ""
    hw_recommended: str = ""

    # presentmon
    pm_available: bool = False

    # gaming analysis (cheap, but still uses telemetry)
    decision: Optional[Any] = None

    # gaming session
    session_active: bool = False
    session_state: str = "IDLE"
    session_target: str = ""
    session_pid: int = 0
    session_duration: float = 0.0
    session_applied: int = 0
    session_cpu: Optional[float] = None
    session_gpu: Optional[float] = None
    session_ram: Optional[float] = None
    session_fps: Optional[float] = None
    session_recent: list = field(default_factory=list)  # recent session summaries


# ── worker ─────────────────────────────────────────────────────────

class _HomePageWorker(QObject):
    """Performs expensive HomePage diagnostics in a background thread."""

    finished = Signal(object)
    error = Signal(str)

    def do_work(self):
        t0 = time.perf_counter()
        result = HomePageResult()
        try:
            self._collect(result)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        self.finished.emit(result)

    def _collect(self, r: HomePageResult):
        # Target detection (slow — process enumeration)
        try:
            from app.performance.target_process import target_process_detector
            candidates = target_process_detector.get_candidates()
            if candidates:
                best = target_process_detector.select_best_target()
                if best:
                    r.target_emulator = best.emulator
                    r.target_process = best.process_name
                    r.target_pid = best.pid
                    # GPU association
                    try:
                        from app.performance.gpu_association import gpu_association_detector
                        assoc = gpu_association_detector.detect_for_process(
                            best.process_name, best.pid,
                        )
                        if assoc.gpu_name:
                            r.target_gpu = assoc.gpu_name
                    except Exception:
                        pass
        except Exception:
            pass

        # Hardware profile (slow — hardware scan, cached 30s)
        try:
            prof = _get_hardware_profile()
            r.hw_tier = prof.system_tier.value.upper()
            r.hw_recommended = prof.recommended_profile.value.upper()
        except Exception:
            pass

        # PresentMon (slow — filesystem search, cached 60s)
        try:
            pm_path = _get_presentmon()
            r.pm_available = pm_path is not None
        except Exception:
            pass

        # Gaming analysis
        try:
            from app.core.adaptive_optimizer import adaptive_optimizer
            r.decision = adaptive_optimizer.analyze()
        except Exception:
            pass

        # Gaming session status (lightweight — reads singleton state)
        try:
            from app.gaming.gaming_lifecycle import gaming_lifecycle, LifecycleState
            mgr = gaming_lifecycle
            if mgr.is_active and mgr.session:
                s = mgr.session
                r.session_active = True
                r.session_state = s.state
                r.session_target = s.target_name
                r.session_pid = s.target_pid
                # Duration
                if s.started_at:
                    try:
                        from datetime import datetime
                        start = datetime.fromisoformat(s.started_at)
                        r.session_duration = (datetime.now() - start).total_seconds()
                    except Exception:
                        pass
                r.session_applied = sum(
                    1 for c in s.changes
                    if c.status.value in ("APPLIED", "VERIFIED")
                )
                # Read cached telemetry for live session metrics
                try:
                    from app.core.telemetry import telemetry_engine
                    frame = telemetry_engine.current
                    if frame.cpu_utilization > 0:
                        r.session_cpu = frame.cpu_utilization
                    if frame.gpu_utilization > 0:
                        r.session_gpu = frame.gpu_utilization
                    if frame.ram_percent > 0:
                        r.session_ram = frame.ram_percent
                except Exception:
                    pass
                # FPS
                try:
                    from app.performance.fps_provider import fps_registry
                    if fps_registry.active and hasattr(fps_registry.active, 'get_metrics'):
                        metrics = fps_registry.active.get_metrics()
                        if metrics and metrics.available and metrics.sample_count > 0:
                            fps_val = metrics.median_fps if metrics.median_fps > 0 else metrics.avg_fps
                            if fps_val > 0:
                                r.session_fps = fps_val
                except Exception:
                    pass
            else:
                r.session_active = False
        except Exception:
            pass

        # Recent session history (bounded, cheap)
        try:
            from app.gaming.gaming_lifecycle import gaming_lifecycle
            history = gaming_lifecycle.load_history(count=5)
            for h in history:
                r.session_recent.append({
                    "target": h.get("target_name", "Unknown"),
                    "duration": h.get("duration_seconds", 0),
                    "applied": h.get("changes_applied", 0),
                    "state": h.get("state", "?"),
                    "ended": h.get("ended_at", ""),
                })
        except Exception:
            pass
class HomePageWorkerThread(QThread):
    """Manages the HomePage worker lifecycle."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = _HomePageWorker()
        self._worker.moveToThread(self)
        self._worker.finished.connect(self.finished)
        self._worker.error.connect(self.error)
        self.started.connect(self._worker.do_work)
        self.setObjectName("home_page_worker")
