"""
Phase 62 — Error Boundaries & Graceful Degradation.

Ensures that no single subsystem failure crashes the entire GUI.

Pattern:
  Subsystem call
    → try/except
    → mark NOT_AVAILABLE / FAILED
    → log technical error (at WARNING or ERROR level, never swallowed)
    → return safe default
    → continue application

Rules:
  - No broad except blocks that silently discard failures
  - Every exception boundary logs the actual error
  - Worker threads have cancellation and shutdown guarantees
  - Incomplete sessions are detected at startup
  - Corrupted config files are handled gracefully
  - Missing dependencies produce clear NOT_AVAILABLE states
  - MainWindow closeEvent stops all workers safely
"""

import json
import os
import sys
import time
import threading
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Generic

from app.utils.logger import get_logger

logger = get_logger("core.error_boundaries")

T = TypeVar("T")


# ── Enums ────────────────────────────────────────────────────────


class SubsystemStatus(Enum):
    """Status of a diagnostic/optimization subsystem."""
    AVAILABLE = "AVAILABLE"
    DEGRADED = "DEGRADED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    FAILED = "FAILED"
    NOT_APPLICABLE = "NOT_APPLICABLE"


class WorkerState(Enum):
    """Worker lifecycle state."""
    IDLE = "IDLE"
    STARTING = "STARTING"
    RUNNING = "RUNNING"
    CANCELLING = "CANCELLING"
    STOPPED = "STOPPED"
    FAILED = "FAILED"


# ── Data Models ──────────────────────────────────────────────────


@dataclass
class SubsystemHealth:
    """Tracks the health of a specific subsystem."""
    name: str = ""
    status: SubsystemStatus = SubsystemStatus.AVAILABLE
    last_error: str = ""
    last_error_time: float = 0.0
    error_count: int = 0
    last_success_time: float = 0.0
    consecutive_failures: int = 0

    def record_success(self):
        self.status = SubsystemStatus.AVAILABLE
        self.last_success_time = time.time()
        self.consecutive_failures = 0

    def record_failure(self, error: str):
        self.last_error = error
        self.last_error_time = time.time()
        self.error_count += 1
        self.consecutive_failures += 1
        if self.consecutive_failures >= 3:
            self.status = SubsystemStatus.FAILED
        else:
            self.status = SubsystemStatus.DEGRADED

    def record_not_available(self, reason: str = ""):
        self.status = SubsystemStatus.NOT_AVAILABLE
        self.last_error = reason
        self.last_error_time = time.time()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "status": self.status.value,
            "last_error": self.last_error,
            "error_count": self.error_count,
            "consecutive_failures": self.consecutive_failures,
        }


@dataclass
class IncompleteSession:
    """Represents a session that was not properly completed."""
    session_id: str = ""
    session_type: str = ""  # optimization, lifecycle, gaming, rollback
    started_at: str = ""
    state: str = ""
    details: Dict[str, Any] = field(default_factory=dict)
    has_applied_changes: bool = False
    reversible_changes: int = 0


# ── Subsystem Registry ───────────────────────────────────────────


class SubsystemRegistry:
    """
    Tracks health of all subsystems.

    Each subsystem is registered by name and its health is tracked
    independently. A failure in one subsystem does not affect others.
    """

    def __init__(self):
        self._subsystems: Dict[str, SubsystemHealth] = {}
        self._lock = threading.Lock()

    def register(self, name: str) -> SubsystemHealth:
        """Register a subsystem for health tracking."""
        with self._lock:
            if name not in self._subsystems:
                self._subsystems[name] = SubsystemHealth(name=name)
            return self._subsystems[name]

    def get(self, name: str) -> SubsystemHealth:
        """Get health of a subsystem."""
        with self._lock:
            if name not in self._subsystems:
                self._subsystems[name] = SubsystemHealth(
                    name=name, status=SubsystemStatus.NOT_AVAILABLE
                )
            return self._subsystems[name]

    def get_all(self) -> Dict[str, SubsystemHealth]:
        """Get all subsystem health statuses."""
        with self._lock:
            return dict(self._subsystems)

    def get_summary(self) -> str:
        """Format a summary of all subsystem health."""
        lines = []
        lines.append("SUBSYSTEM HEALTH")
        lines.append("-" * 50)
        with self._lock:
            for name, health in sorted(self._subsystems.items()):
                status = health.status.value
                error_info = ""
                if health.last_error:
                    error_info = f" ({health.last_error[:50]})"
                lines.append(f"  {name:<25} {status:<15}{error_info}")
        return "\n".join(lines)

    def format_status(self) -> str:
        """Format subsystem status for CLI display."""
        lines = []
        lines.append("=" * 55)
        lines.append("  SUBSYSTEM HEALTH")
        lines.append("=" * 55)
        lines.append("")
        with self._lock:
            for name, health in sorted(self._subsystems.items()):
                status = health.status.value
                icon = {
                    SubsystemStatus.AVAILABLE: "[OK]",
                    SubsystemStatus.DEGRADED: "[--]",
                    SubsystemStatus.NOT_AVAILABLE: "[NA]",
                    SubsystemStatus.FAILED: "[!!]",
                    SubsystemStatus.NOT_APPLICABLE: "[NA]",
                }.get(health.status, "[??]")
                line = f"  {icon} {name:<25} {status}"
                if health.error_count > 0:
                    line += f"  ({health.error_count} errors)"
                lines.append(line)
                if health.last_error:
                    lines.append(f"       Last error: {health.last_error[:60]}")
        lines.append("")
        lines.append("=" * 55)
        return "\n".join(lines)


# ── Global Registry ──────────────────────────────────────────────

subsystem_registry = SubsystemRegistry()


# ── Safe Subsystem Wrapper ───────────────────────────────────────


@contextmanager
def safe_subsystem(name: str, fallback: Any = None, log_level: str = "warning"):
    """
    Context manager that catches exceptions from a subsystem.

    Usage:
        with safe_subsystem("gpu_monitor", fallback=None) as ctx:
            result = gpu_monitor.detect()
            ctx.value = result

    If an exception occurs:
        - The subsystem is marked DEGRADED or FAILED
        - The error is logged at the specified level
        - The fallback value is returned
    """
    health = subsystem_registry.register(name)
    ctx = _SubsystemContext(fallback)

    try:
        yield ctx
        health.record_success()
        return ctx.value
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        health.record_failure(error_msg)

        log_fn = getattr(logger, log_level, logger.warning)
        log_fn(f"[SUBSYSTEM:{name}] {error_msg}")
        logger.debug(f"[SUBSYSTEM:{name}] Traceback: {traceback.format_exc()}")

        return fallback


class _SubsystemContext:
    """Holds the result of a safe subsystem call."""

    def __init__(self, fallback: Any = None):
        self.value = fallback
        self.error: Optional[str] = None
        self.success = False


# ── Safe Function Caller ─────────────────────────────────────────


def safe_call(
    func: Callable,
    *args,
    subsystem: str = "",
    fallback: Any = None,
    log_error: bool = True,
    **kwargs,
) -> Any:
    """
    Call a function safely, catching and logging any exception.

    Returns fallback on failure.
    Never crashes the caller.
    """
    if subsystem:
        health = subsystem_registry.register(subsystem)

    try:
        result = func(*args, **kwargs)
        if subsystem:
            health.record_success()
        return result
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        if subsystem:
            health.record_failure(error_msg)
        if log_error:
            logger.warning(f"[SAFE_CALL:{subsystem or func.__name__}] {error_msg}")
            logger.debug(f"[SAFE_CALL:{subsystem or func.__name__}] {traceback.format_exc()}")
        return fallback


# ── Worker Lifecycle Manager ─────────────────────────────────────


class ManagedWorker:
    """
    Wraps a QThread-based worker with proper lifecycle management.

    Features:
      - Cancellation via threading.Event
      - Safe shutdown with timeout
      - State tracking
      - Prevents double-start
      - Cleanup guarantee
    """

    def __init__(self, name: str = "worker"):
        self.name = name
        self._state = WorkerState.IDLE
        self._cancel_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._start_time: float = 0.0
        self._stop_time: float = 0.0

    @property
    def state(self) -> WorkerState:
        return self._state

    @property
    def is_running(self) -> bool:
        return self._state in (WorkerState.RUNNING, WorkerState.STARTING)

    @property
    def should_cancel(self) -> bool:
        """Check if cancellation has been requested."""
        return self._cancel_event.is_set()

    @property
    def uptime(self) -> float:
        """How long the worker has been running."""
        if self._state == WorkerState.RUNNING and self._start_time > 0:
            return time.time() - self._start_time
        return 0.0

    def start(self, target: Callable, *args, **kwargs) -> bool:
        """
        Start the worker with the given target function.

        Returns False if already running or if start fails.
        """
        with self._lock:
            if self._state in (WorkerState.RUNNING, WorkerState.STARTING):
                logger.warning(f"Worker '{self.name}' already running — skipping")
                return False

            self._cancel_event.clear()
            self._state = WorkerState.STARTING
            self._start_time = time.time()
            self._stop_time = 0.0

        def _wrapper():
            failed = False
            try:
                self._state = WorkerState.RUNNING
                target(*args, **kwargs)
            except Exception as e:
                failed = True
                logger.error(f"Worker '{self.name}' failed: {e}")
                logger.debug(f"Worker '{self.name}' traceback: {traceback.format_exc()}")
                self._state = WorkerState.FAILED
            finally:
                if not failed and self._state not in (WorkerState.CANCELLING, WorkerState.FAILED):
                    self._state = WorkerState.STOPPED
                self._stop_time = time.time()

        self._thread = threading.Thread(
            target=_wrapper,
            daemon=True,
            name=f"managed_{self.name}",
        )
        self._thread.start()
        return True

    def cancel(self, timeout: float = 3.0) -> bool:
        """
        Request cancellation and wait for the worker to stop.

        Returns True if the worker stopped within the timeout.
        """
        with self._lock:
            if self._state not in (WorkerState.RUNNING, WorkerState.STARTING):
                return True

            self._state = WorkerState.CANCELLING
            self._cancel_event.set()

        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=timeout)
            if self._thread.is_alive():
                logger.warning(
                    f"Worker '{self.name}' did not stop within {timeout}s"
                )
                return False

        self._state = WorkerState.STOPPED
        return True

    def force_stop(self):
        """Force stop without waiting (for emergency shutdown)."""
        self._cancel_event.set()
        self._state = WorkerState.STOPPED

    def reset(self):
        """Reset the worker to IDLE state."""
        needs_cancel = False
        with self._lock:
            if self._state in (WorkerState.RUNNING, WorkerState.STARTING):
                needs_cancel = True
        if needs_cancel:
            self.cancel(timeout=1.0)
        with self._lock:
            self._state = WorkerState.IDLE
            self._cancel_event.clear()

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "state": self._state.value,
            "uptime": self.uptime,
            "start_time": self._start_time,
            "stop_time": self._stop_time,
        }


# ── Safe Config Loader ───────────────────────────────────────────


def safe_load_json(filepath: str, default: Any = None, label: str = "") -> Any:
    """
    Load a JSON config file safely.

    If the file is missing, returns default.
    If the file is corrupted, logs the error and returns default.
    Never crashes the application.
    """
    label = label or os.path.basename(filepath)

    if not os.path.exists(filepath):
        logger.debug(f"Config '{label}' not found at {filepath} — using defaults")
        return default

    try:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except json.JSONDecodeError as e:
        logger.warning(f"Config '{label}' is corrupted: {e}")
        logger.info(f"Config '{label}' backup created and defaults used")
        # Try to backup the corrupted file
        try:
            backup_path = filepath + ".corrupted." + str(int(time.time()))
            os.rename(filepath, backup_path)
            logger.info(f"Corrupted config backed up to: {backup_path}")
        except OSError:
            pass
        return default
    except Exception as e:
        logger.warning(f"Config '{label}' load failed: {e}")
        return default


def safe_save_json(filepath: str, data: Any, label: str = "") -> bool:
    """
    Save a JSON config file safely.

    Writes to a temp file first, then renames for atomicity.
    If save fails, logs the error. Never crashes.
    """
    label = label or os.path.basename(filepath)

    try:
        dir_path = os.path.dirname(filepath)
        if dir_path:
            os.makedirs(dir_path, exist_ok=True)

        tmp_path = filepath + ".tmp"
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        # Atomic rename
        if os.path.exists(filepath):
            os.replace(tmp_path, filepath)
        else:
            os.rename(tmp_path, filepath)

        return True
    except Exception as e:
        logger.warning(f"Config '{label}' save failed: {e}")
        # Cleanup temp file
        try:
            if os.path.exists(filepath + ".tmp"):
                os.remove(filepath + ".tmp")
        except OSError:
            pass
        return False


# ── Incomplete Session Recovery ──────────────────────────────────


def detect_incomplete_sessions() -> List[IncompleteSession]:
    """
    Scan all session directories for sessions that were not properly completed.

    Called at application startup to detect crash recovery opportunities.
    """
    incomplete = []

    # Check rollback sessions
    incomplete.extend(_check_rollback_sessions())

    # Check lifecycle sessions
    incomplete.extend(_check_lifecycle_sessions())

    # Check gaming optimization sessions
    incomplete.extend(_check_gaming_opt_sessions())

    # Check optimization runs
    incomplete.extend(_check_optimization_runs())

    if incomplete:
        logger.warning(
            f"Found {len(incomplete)} incomplete session(s) — "
            f"recovery may be needed"
        )
    else:
        logger.info("No incomplete sessions detected")

    return incomplete


def _check_rollback_sessions() -> List[IncompleteSession]:
    """Check rollback_data/ for incomplete rollback sessions."""
    sessions = []
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "rollback_data",
    )
    manifest_path = os.path.join(data_dir, "manifest.json")

    manifest = safe_load_json(manifest_path, default={}, label="rollback_manifest")
    if not manifest:
        return sessions

    session_ids = manifest.get("sessions", [])
    for sid in session_ids:
        session_path = os.path.join(data_dir, f"{sid}.json")
        data = safe_load_json(session_path, label=f"rollback_{sid}")
        if data and data.get("status") == "IN_PROGRESS":
            has_applied = any(
                c.get("status") == "APPLIED"
                for c in data.get("changes", [])
            )
            sessions.append(IncompleteSession(
                session_id=sid,
                session_type="rollback",
                started_at=data.get("started_at", ""),
                state=data.get("status", ""),
                has_applied_changes=has_applied,
                reversible_changes=sum(
                    1 for c in data.get("changes", [])
                    if c.get("reversible") and c.get("status") == "APPLIED"
                ),
                details=data,
            ))

    return sessions


def _check_lifecycle_sessions() -> List[IncompleteSession]:
    """Check lifecycle_sessions/ for incomplete lifecycle sessions."""
    sessions = []
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "lifecycle_sessions",
    )
    if not os.path.exists(data_dir):
        return sessions

    for fname in os.listdir(data_dir):
        if not fname.endswith(".json"):
            continue
        filepath = os.path.join(data_dir, fname)
        data = safe_load_json(filepath, label=f"lifecycle_{fname}")
        if not data:
            continue

        state = data.get("state", "")
        if state not in ("COMPLETED", "IDLE", "FAILED"):
            changes = data.get("changes", [])
            applied = sum(
                1 for c in changes
                if c.get("status") in ("APPLIED", "VERIFIED")
            )
            sessions.append(IncompleteSession(
                session_id=data.get("session_id", fname),
                session_type="lifecycle",
                started_at=data.get("started_at", ""),
                state=state,
                has_applied_changes=applied > 0,
                reversible_changes=applied,
                details=data,
            ))

    return sessions


def _check_gaming_opt_sessions() -> List[IncompleteSession]:
    """Check gaming_opt_sessions/ for incomplete gaming sessions."""
    sessions = []
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "gaming_opt_sessions",
    )
    if not os.path.exists(data_dir):
        return sessions

    for fname in os.listdir(data_dir):
        if not fname.endswith(".json"):
            continue
        filepath = os.path.join(data_dir, fname)
        data = safe_load_json(filepath, label=f"gaming_opt_{fname}")
        if not data:
            continue

        state = data.get("state", "")
        if state not in ("IDLE",):
            applied = data.get("optimizations_applied", 0)
            sessions.append(IncompleteSession(
                session_id=data.get("session_id", fname),
                session_type="gaming_optimization",
                started_at=data.get("started_at", ""),
                state=state,
                has_applied_changes=applied > 0,
                reversible_changes=applied,
                details=data,
            ))

    return sessions


def _check_optimization_runs() -> List[IncompleteSession]:
    """Check optimization_runs/ for incomplete optimization runs."""
    sessions = []
    data_dir = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "optimization_runs",
    )
    if not os.path.exists(data_dir):
        return sessions

    for fname in os.listdir(data_dir):
        if not fname.endswith(".json"):
            continue
        filepath = os.path.join(data_dir, fname)
        data = safe_load_json(filepath, label=f"opt_run_{fname}")
        if not data:
            continue

        status = data.get("status", "")
        if status == "IN_PROGRESS":
            sessions.append(IncompleteSession(
                session_id=data.get("session_id", fname),
                session_type="optimization",
                started_at=data.get("started_at", ""),
                state=status,
                has_applied_changes=data.get("applied_count", 0) > 0,
                reversible_changes=data.get("applied_count", 0),
                details=data,
            ))

    return sessions


def format_incomplete_sessions(sessions: List[IncompleteSession]) -> str:
    """Format incomplete sessions for CLI display."""
    if not sessions:
        return "No incomplete sessions detected."

    lines = []
    lines.append("=" * 55)
    lines.append("  INCOMPLETE SESSIONS DETECTED")
    lines.append("=" * 55)
    lines.append("")
    lines.append(
        "  An optimization session did not complete properly."
    )
    lines.append("  This may have happened if the application crashed")
    lines.append("  or was force-closed during an optimization.")
    lines.append("")

    for s in sessions:
        lines.append(f"  Session: {s.session_id}")
        lines.append(f"  Type:    {s.session_type}")
        lines.append(f"  State:   {s.state}")
        lines.append(f"  Started: {s.started_at}")
        if s.has_applied_changes:
            lines.append(
                f"  Changes: {s.reversible_changes} applied (may need rollback)"
            )
        lines.append("")

    lines.append("  OPTIONS:")
    lines.append("    1. RESTORE — Roll back all applied changes")
    lines.append("    2. KEEP    — Keep current changes, mark complete")
    lines.append("    3. VIEW    — Show detailed session info")
    lines.append("")
    lines.append("=" * 55)
    return "\n".join(lines)


# ── Missing Dependency Handler ────────────────────────────────────


def check_dependencies() -> Dict[str, bool]:
    """
    Check which optional dependencies are available.

    Returns a dict of dependency_name -> available.
    Never crashes — returns False for any dependency that can't be checked.
    """
    deps = {}

    # psutil
    try:
        import psutil
        deps["psutil"] = True
    except ImportError:
        deps["psutil"] = False
        logger.warning("psutil not available — CPU/memory monitoring disabled")

    # pynvml
    try:
        import pynvml
        deps["pynvml"] = True
    except ImportError:
        deps["pynvml"] = False

    # PySide6
    try:
        from PySide6 import QtWidgets
        deps["PySide6"] = True
    except ImportError:
        deps["PySide6"] = False
        logger.error("PySide6 not available — GUI cannot start")

    # WMI
    try:
        import wmi
        deps["wmi"] = True
    except ImportError:
        deps["wmi"] = False

    # pythoncom
    try:
        import pythoncom
        deps["pythoncom"] = True
    except ImportError:
        deps["pythoncom"] = False

    return deps


# ── Permission Handler ───────────────────────────────────────────


def check_permissions() -> Dict[str, bool]:
    """
    Check what permissions are available.

    Returns a dict of permission_name -> available.
    """
    perms = {}

    # Admin check
    try:
        import ctypes
        perms["admin"] = ctypes.windll.shell32.IsUserAnAdmin() != 0
    except Exception:
        perms["admin"] = False

    # Registry read
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion",
            0,
            winreg.KEY_READ,
        )
        winreg.CloseKey(key)
        perms["registry_read"] = True
    except Exception:
        perms["registry_read"] = False

    # Process access
    try:
        import psutil
        proc = psutil.Process()
        proc.cpu_percent()
        perms["process_access"] = True
    except Exception:
        perms["process_access"] = False

    return perms


# ── WMI Failure Handler ──────────────────────────────────────────


@contextmanager
def safe_wmi_context(label: str = "wmi"):
    """
    Safe WMI context manager that handles COM initialization and cleanup.

    Prevents:
      - COM not initialized errors
      - IUnknown release errors
      - Thread-related COM errors
    """
    health = subsystem_registry.register(f"wmi_{label}")

    try:
        import pythoncom
        pythoncom.CoInitialize()
    except Exception:
        pass  # Already initialized or not available

    try:
        yield
        health.record_success()
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        health.record_failure(error_msg)
        logger.warning(f"[WMI:{label}] {error_msg}")
        logger.debug(f"[WMI:{label}] Traceback: {traceback.format_exc()}")
    finally:
        try:
            import pythoncom
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ── GPU API Failure Handler ──────────────────────────────────────


def safe_gpu_call(func: Callable, *args, fallback: Any = None, **kwargs) -> Any:
    """
    Execute a GPU/NVML API call safely.

    Handles:
      - NVML not initialized
      - GPU not accessible
      - Driver version mismatch
      - Access denied
    """
    health = subsystem_registry.register("gpu_api")

    try:
        result = func(*args, **kwargs)
        health.record_success()
        return result
    except Exception as e:
        error_msg = f"{type(e).__name__}: {e}"
        health.record_failure(error_msg)
        logger.debug(f"[GPU_API] {error_msg}")
        return fallback


# ── Application Error Handler ────────────────────────────────────


def install_global_exception_handler():
    """
    Install a global exception handler for unhandled exceptions.

    Logs the exception but does NOT crash the application.
    GUI exceptions are caught separately via Qt's exception handling.
    """
    original_excepthook = sys.excepthook

    def _handler(exc_type, exc_value, exc_tb):
        if issubclass(exc_type, KeyboardInterrupt):
            # Allow Ctrl+C to work normally
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return

        logger.error(
            f"Unhandled exception: {exc_type.__name__}: {exc_value}"
        )
        if exc_tb:
            tb_lines = traceback.format_exception(exc_type, exc_value, exc_tb)
            for line in tb_lines:
                logger.error(line.rstrip())

    sys.excepthook = _handler


# ── MainWindow Safe Close ────────────────────────────────────────


def safe_shutdown_workers(workers: list, timeout_per_worker: float = 2.0):
    """
    Safely shut down a list of workers/threads.

    Each worker gets its own timeout.
    If a worker fails to stop, it is logged but does not block others.
    """
    for worker in workers:
        try:
            if hasattr(worker, "cancel"):
                worker.cancel(timeout=timeout_per_worker)
            elif hasattr(worker, "stop"):
                worker.stop()
            elif hasattr(worker, "quit"):
                worker.quit()
                worker.wait(int(timeout_per_worker * 1000))
            elif hasattr(worker, "isRunning") and worker.isRunning():
                worker.quit()
                worker.wait(int(timeout_per_worker * 1000))
        except Exception as e:
            logger.warning(f"Worker shutdown error: {e}")

    # Force stop anything still running
    for worker in workers:
        try:
            if hasattr(worker, "force_stop"):
                worker.force_stop()
            elif hasattr(worker, "isRunning") and worker.isRunning():
                worker.terminate()
        except Exception:
            pass


def safe_stop_timers(timers: list):
    """Safely stop a list of QTimer objects."""
    for timer in timers:
        try:
            if hasattr(timer, "isActive") and timer.isActive():
                timer.stop()
        except Exception as e:
            logger.debug(f"Timer stop error: {e}")
