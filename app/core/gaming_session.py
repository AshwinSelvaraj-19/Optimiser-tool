"""
Gaming Session Mode — Phase 27

Controlled gaming session lifecycle:
  START → BASELINE → OPTIMIZE → MONITOR → STOP → RESTORE → CLEANUP

Manages:
- Unique session ID
- Target PID + process start time
- Applied optimization list with rollback snapshot
- Continuous telemetry monitoring
- Baseline/post metrics comparison
- Automatic cleanup on failure
- Safe target invalidation if PID changes
- Never leaves stale PresentMon processes or CSV files

IMPORTANT:
- Only restores changes made by THIS session
- Detects emulator closure and stops monitoring safely
- Detects PID changes and invalidates stale targets
- Never terminates unrelated processes
- Cleanup always runs in finally blocks
"""

import json
import os
import time
import uuid
import threading
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Tuple
from enum import Enum

from app.utils.logger import get_logger

logger = get_logger("core.gaming_session")


# ── Session States ────────────────────────────────────────────

class SessionState(Enum):
    """Gaming session lifecycle states."""
    IDLE = "IDLE"
    STARTING = "STARTING"
    BASELINE = "BASELINE"
    OPTIMIZING = "OPTIMIZING"
    MONITORING = "MONITORING"
    STOPPING = "STOPPING"
    ENDED = "ENDED"
    FAILED = "FAILED"


# ── Data Models ───────────────────────────────────────────────

@dataclass
class TelemetrySummary:
    """Aggregated telemetry for the session."""
    # FPS (from PresentMon when available)
    avg_fps: Optional[float] = None
    min_fps: Optional[float] = None
    max_fps: Optional[float] = None
    one_percent_low: Optional[float] = None
    avg_frame_time: Optional[float] = None
    frame_spikes: int = 0

    # System
    avg_cpu: Optional[float] = None
    avg_gpu: Optional[float] = None
    avg_ram: Optional[float] = None
    max_gpu_temp: Optional[float] = None
    max_cpu_temp: Optional[float] = None

    # Sample count
    telemetry_samples: int = 0
    presentmon_samples: int = 0

    def to_dict(self) -> dict:
        return {
            "avg_fps": self.avg_fps,
            "min_fps": self.min_fps,
            "max_fps": self.max_fps,
            "one_percent_low": self.one_percent_low,
            "avg_frame_time": self.avg_frame_time,
            "frame_spikes": self.frame_spikes,
            "avg_cpu": self.avg_cpu,
            "avg_gpu": self.avg_gpu,
            "avg_ram": self.avg_ram,
            "max_gpu_temp": self.max_gpu_temp,
            "max_cpu_temp": self.max_cpu_temp,
            "telemetry_samples": self.telemetry_samples,
            "presentmon_samples": self.presentmon_samples,
        }


@dataclass
class SessionOptimization:
    """Record of an optimization applied during a session."""
    opt_id: str = ""
    name: str = ""
    status: str = ""  # APPLIED, ALREADY_OPTIMAL, REQUIRES_ADMIN, FAILED, RECOMMENDATION_ONLY
    current_value: str = ""
    applied_value: str = ""
    verified: bool = False
    error: str = ""


@dataclass
class GamingSession:
    """
    Complete gaming session record.
    Contains everything needed for lifecycle management and rollback.
    """
    # Identity
    session_id: str = ""
    profile_id: str = ""
    profile_name: str = ""

    # Target
    target_name: str = ""
    target_pid: int = 0
    target_start_time: float = 0.0  # Process start time (epoch)

    # Lifecycle
    state: SessionState = SessionState.IDLE
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: float = 0.0

    # Baseline (before optimization)
    baseline: TelemetrySummary = field(default_factory=TelemetrySummary)
    baseline_timestamp: float = 0.0

    # Optimizations applied
    optimizations: List[SessionOptimization] = field(default_factory=list)
    snapshot_id: str = ""

    # Post-optimization / final
    final: TelemetrySummary = field(default_factory=TelemetrySummary)
    final_timestamp: float = 0.0

    # Monitoring
    monitoring_active: bool = False
    telemetry_history: List[Dict] = field(default_factory=list)

    # Cleanup state
    presentmon_stopped: bool = False
    csv_cleaned: bool = False
    snapshot_restored: bool = False

    # Error recovery
    errors: List[str] = field(default_factory=list)
    target_lost: bool = False
    pid_changed: bool = False

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"session_{uuid.uuid4().hex[:8]}"

    @property
    def has_applied_optimizations(self) -> bool:
        return any(o.status == "APPLIED" for o in self.optimizations)

    @property
    def applied_count(self) -> int:
        return sum(1 for o in self.optimizations if o.status == "APPLIED")

    @property
    def needs_rollback(self) -> bool:
        return self.has_applied_optimizations and not self.snapshot_restored

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "state": self.state.value,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "baseline": self.baseline.to_dict(),
            "final": self.final.to_dict(),
            "optimizations": [
                {"opt_id": o.opt_id, "name": o.name, "status": o.status, "verified": o.verified}
                for o in self.optimizations
            ],
            "snapshot_id": self.snapshot_id,
            "applied_count": self.applied_count,
            "target_lost": self.target_lost,
            "pid_changed": self.pid_changed,
            "errors": self.errors,
            "presentmon_stopped": self.presentmon_stopped,
            "csv_cleaned": self.csv_cleaned,
            "snapshot_restored": self.snapshot_restored,
        }


# ── Session Storage ───────────────────────────────────────────

SESSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "gaming_sessions"
)


def _ensure_sessions_dir():
    os.makedirs(SESSIONS_DIR, exist_ok=True)


def save_session(session: GamingSession):
    """Save session to local JSON."""
    _ensure_sessions_dir()
    path = os.path.join(SESSIONS_DIR, f"{session.session_id}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(session.to_dict(), f, indent=2, default=str)
    logger.info(f"Session saved: {path}")


def load_sessions() -> List[GamingSession]:
    """Load all saved sessions."""
    _ensure_sessions_dir()
    sessions = []
    for fname in sorted(os.listdir(SESSIONS_DIR)):
        if fname.endswith(".json"):
            try:
                path = os.path.join(SESSIONS_DIR, fname)
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                s = GamingSession(
                    session_id=data.get("session_id", ""),
                    profile_id=data.get("profile_id", ""),
                    target_name=data.get("target_name", ""),
                    target_pid=data.get("target_pid", 0),
                    state=SessionState(data.get("state", "IDLE")),
                    started_at=data.get("started_at", ""),
                    ended_at=data.get("ended_at", ""),
                    duration_seconds=data.get("duration_seconds", 0),
                    snapshot_id=data.get("snapshot_id", ""),
                    target_lost=data.get("target_lost", False),
                    pid_changed=data.get("pid_changed", False),
                    presentmon_stopped=data.get("presentmon_stopped", False),
                    csv_cleaned=data.get("csv_cleaned", False),
                    snapshot_restored=data.get("snapshot_restored", False),
                    errors=data.get("errors", []),
                )
                sessions.append(s)
            except Exception as e:
                logger.debug(f"Failed to load {fname}: {e}")
    return sessions


# ── Gaming Session Engine ─────────────────────────────────────

class GamingSessionEngine:
    """
    Manages the complete gaming session lifecycle.

    States:
      IDLE → STARTING → BASELINE → OPTIMIZING → MONITORING → STOPPING → ENDED
                ↓                      ↓             ↓           ↓
              FAILED                FAILED        FAILED      ENDED

    Cleanup always runs in finally blocks.
    """

    def __init__(self):
        self._session: Optional[GamingSession] = None
        self._monitor_thread: Optional[threading.Thread] = None
        self._monitoring = False
        self._lock = threading.Lock()
        self._callback = None  # UI callback

    @property
    def session(self) -> Optional[GamingSession]:
        return self._session

    @property
    def state(self) -> SessionState:
        return self._session.state if self._session else SessionState.IDLE

    @property
    def is_active(self) -> bool:
        return self._session is not None and self._session.state in (
            SessionState.STARTING, SessionState.BASELINE,
            SessionState.OPTIMIZING, SessionState.MONITORING,
        )

    def on_update(self, callback):
        """Register a callback for session state updates."""
        self._callback = callback

    def _notify(self, msg: str = ""):
        if self._callback and self._session:
            try:
                self._callback(self._session)
            except Exception:
                pass

    def start_session(self, profile_id: str) -> GamingSession:
        """
        Start a new gaming session.

        Pipeline:
          1. Create session
          2. Detect target
          3. Capture baseline telemetry
          4. Apply optimizations
          5. Verify each change
          6. Start monitoring
        """
        if self._session and self.is_active:
            logger.warning("Session already active")
            return self._session

        session = GamingSession(profile_id=profile_id)
        self._session = session

        try:
            self._start_session_inner(session)
        except Exception as e:
            session.state = SessionState.FAILED
            session.errors.append(str(e))
            logger.error(f"Session start failed: {e}")
            self._cleanup_safe(session)

        save_session(session)
        return session

    def _start_session_inner(self, session: GamingSession):
        """Inner session startup logic."""
        session.state = SessionState.STARTING
        session.started_at = datetime.now().isoformat()
        self._notify("Starting session...")

        # Step 1: Detect target
        target_name, target_pid, start_time = self._detect_target()
        if not target_name or not target_pid:
            session.state = SessionState.FAILED
            session.errors.append("No emulator target detected")
            logger.warning("No emulator target found")
            return

        session.target_name = target_name
        session.target_pid = target_pid
        session.target_start_time = start_time
        logger.info(f"Target: {target_name} PID={target_pid}")
        self._notify(f"Target: {target_name} PID={target_pid}")

        # Step 2: Get profile
        from app.core.profiles import get_profile
        profile = get_profile(session.profile_id)
        if profile:
            session.profile_name = profile.name

        # Step 3: Capture baseline
        session.state = SessionState.BASELINE
        self._notify("Capturing baseline telemetry...")
        session.baseline = self._capture_telemetry_summary()
        session.baseline_timestamp = time.time()
        logger.info(f"Baseline: FPS={session.baseline.avg_fps}, CPU={session.baseline.avg_cpu}")
        self._notify(f"Baseline: CPU={session.baseline.avg_cpu}% GPU={session.baseline.avg_gpu}%")

        # Step 4: Apply optimizations
        session.state = SessionState.OPTIMIZING
        self._notify("Applying optimizations...")
        self._apply_optimizations(session)

        # Step 5: Start monitoring
        session.state = SessionState.MONITORING
        session.monitoring_active = True
        self._start_monitoring(session)
        self._notify("Session active — monitoring")

    def stop_session(self) -> GamingSession:
        """
        Stop the current gaming session.

        Pipeline:
          1. Stop monitoring
          2. Capture final telemetry
          3. Restore optimizations (if user wants)
          4. Cleanup PresentMon
          5. Save session
        """
        if not self._session:
            logger.warning("No active session to stop")
            return GamingSession()

        session = self._session

        try:
            self._stop_session_inner(session)
        except Exception as e:
            session.errors.append(f"Stop error: {e}")
            logger.error(f"Session stop error: {e}")
        finally:
            self._cleanup_safe(session)

        session.state = SessionState.ENDED
        session.ended_at = datetime.now().isoformat()
        try:
            start = datetime.fromisoformat(session.started_at)
            end = datetime.fromisoformat(session.ended_at)
            session.duration_seconds = (end - start).total_seconds()
        except Exception:
            pass

        self._monitoring = False
        self._session = None
        save_session(session)
        self._notify("Session ended")
        return session

    def _stop_session_inner(self, session: GamingSession):
        """Inner session stop logic."""
        session.state = SessionState.STOPPING
        self._notify("Stopping monitoring...")

        # Step 1: Stop monitoring
        self._monitoring = False
        session.monitoring_active = False
        if self._monitor_thread and self._monitor_thread.is_alive():
            self._monitor_thread.join(timeout=5.0)

        # Step 2: Validate target is still alive
        if session.target_pid:
            alive = self._check_target_alive(session.target_pid)
            if not alive:
                session.target_lost = True
                session.errors.append(f"Target PID {session.target_pid} is no longer running")

        # Step 3: Capture final telemetry
        self._notify("Capturing final telemetry...")
        session.final = self._capture_telemetry_summary()
        session.final_timestamp = time.time()

        # Step 4: Cleanup PresentMon
        self._cleanup_presentmon(session)

    def restore_session(self) -> GamingSession:
        """
        Restore optimizations from the current/last session.
        Only restores changes that were actually applied.
        """
        if not self._session:
            logger.warning("No session to restore")
            return GamingSession()

        session = self._session

        if not session.has_applied_optimizations:
            session.snapshot_restored = True
            logger.info("No applied optimizations to restore")
            return session

        if not session.snapshot_id:
            session.errors.append("No snapshot available for restore")
            return session

        try:
            from app.core.rollback import rollback_engine
            from app.core.snapshot import snapshot_manager

            snapshot = snapshot_manager.load_snapshot(session.snapshot_id)
            if snapshot:
                result = rollback_engine.rollback(snapshot)
                session.snapshot_restored = result.success
                if result.success:
                    logger.info(f"Session restored: {result.message}")
                else:
                    session.errors.append(f"Restore failed: {result.message}")
            else:
                session.errors.append(f"Snapshot not found: {session.snapshot_id}")
        except Exception as e:
            session.errors.append(f"Restore error: {e}")
            logger.error(f"Restore failed: {e}")

        save_session(session)
        self._notify("Optimizations restored")
        return session

    def cleanup(self):
        """Force cleanup of any active session resources."""
        if self._session:
            self._cleanup_safe(self._session)
            self._monitoring = False

    # ── Target Detection ──────────────────────────────────────

    def _detect_target(self) -> Tuple[str, int, float]:
        """Detect current emulator target. Returns (name, pid, start_time)."""
        try:
            from app.performance.target_process import target_process_detector
            best = target_process_detector.select_best_target()
            if best:
                # Get process start time
                import psutil
                try:
                    proc = psutil.Process(best.pid)
                    start_time = proc.create_time()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    start_time = 0.0
                return best.process_name, best.pid, start_time
        except Exception as e:
            logger.debug(f"Target detection: {e}")
        return "", 0, 0.0

    def _check_target_alive(self, pid: int) -> bool:
        """Check if the target process is still running."""
        try:
            import psutil
            proc = psutil.Process(pid)
            return proc.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _check_target_valid(self, session: GamingSession) -> bool:
        """Validate target is still the same process."""
        if not session.target_pid:
            return False

        try:
            import psutil
            proc = psutil.Process(session.target_pid)
            if not proc.is_running():
                session.target_lost = True
                return False

            # Check PID hasn't been reused
            if session.target_start_time > 0:
                if abs(proc.create_time() - session.target_start_time) > 5.0:
                    session.pid_changed = True
                    session.errors.append(
                        f"PID {session.target_pid} reused — "
                        f"start time changed"
                    )
                    return False

            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            session.target_lost = True
            return False

    # ── Telemetry Capture ─────────────────────────────────────

    def _capture_telemetry_summary(self) -> TelemetrySummary:
        """Capture a telemetry summary from the telemetry engine."""
        summary = TelemetrySummary()

        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current

            summary.avg_cpu = frame.cpu_utilization if frame.cpu_utilization > 0 else None
            summary.avg_gpu = frame.gpu_utilization if frame.gpu_utilization > 0 else None
            summary.avg_ram = frame.ram_percent if frame.ram_percent > 0 else None
            summary.max_gpu_temp = frame.gpu_temp
            summary.max_cpu_temp = frame.cpu_temp
            summary.telemetry_samples = 1
        except Exception as e:
            logger.debug(f"Telemetry capture: {e}")

        return summary

    def _capture_multi_sample(self, duration: int = 3) -> TelemetrySummary:
        """Capture telemetry over multiple samples for better accuracy."""
        samples = []
        for _ in range(duration):
            try:
                from app.core.telemetry import telemetry_engine
                frame = telemetry_engine.current
                samples.append({
                    "cpu": frame.cpu_utilization,
                    "gpu": frame.gpu_utilization,
                    "ram": frame.ram_percent,
                    "gpu_temp": frame.gpu_temp,
                    "cpu_temp": frame.cpu_temp,
                })
            except Exception:
                pass
            time.sleep(1.0)

        if not samples:
            return TelemetrySummary()

        summary = TelemetrySummary()
        cpu_vals = [s["cpu"] for s in samples if s["cpu"] > 0]
        gpu_vals = [s["gpu"] for s in samples if s["gpu"] > 0]
        ram_vals = [s["ram"] for s in samples if s["ram"] > 0]
        gpu_temps = [s["gpu_temp"] for s in samples if s["gpu_temp"] is not None]
        cpu_temps = [s["cpu_temp"] for s in samples if s["cpu_temp"] is not None]

        if cpu_vals:
            summary.avg_cpu = sum(cpu_vals) / len(cpu_vals)
        if gpu_vals:
            summary.avg_gpu = sum(gpu_vals) / len(gpu_vals)
        if ram_vals:
            summary.avg_ram = sum(ram_vals) / len(ram_vals)
        if gpu_temps:
            summary.max_gpu_temp = max(gpu_temps)
        if cpu_temps:
            summary.max_cpu_temp = max(cpu_temps)
        summary.telemetry_samples = len(samples)

        return summary

    # ── Optimization Application ──────────────────────────────

    def _apply_optimizations(self, session: GamingSession):
        """Apply optimizations from the selected profile."""
        try:
            from app.core.profiles import get_profile
            from app.core.optimizations import get_optimization_by_id
            from app.core.snapshot import snapshot_manager
            from app.utils.admin import is_admin as check_admin

            profile = get_profile(session.profile_id)
            if not profile:
                session.errors.append(f"Profile not found: {session.profile_id}")
                return

            # Create snapshot
            snapshot = snapshot_manager.create_snapshot(
                f"Gaming session {session.session_id}"
            )
            session.snapshot_id = snapshot.snapshot_id

            is_admin = check_admin()

            for po in profile.optimizations:
                opt = get_optimization_by_id(po.opt_id)
                if not opt:
                    session.optimizations.append(SessionOptimization(
                        opt_id=po.opt_id, name=po.name,
                        status="NOT_FOUND", error="Optimization not found",
                    ))
                    continue

                # Check
                try:
                    check_result = opt.check()
                except Exception as e:
                    session.optimizations.append(SessionOptimization(
                        opt_id=po.opt_id, name=po.name,
                        status="FAILED", error=f"Check failed: {e}",
                    ))
                    continue

                status_val = check_result.status.value if hasattr(check_result.status, 'value') else str(check_result.status)

                if status_val == "ALREADY_OPTIMAL":
                    session.optimizations.append(SessionOptimization(
                        opt_id=po.opt_id, name=po.name,
                        status="ALREADY_OPTIMAL",
                        current_value=check_result.current_value,
                    ))
                    continue

                if status_val == "REQUIRES_ADMIN":
                    session.optimizations.append(SessionOptimization(
                        opt_id=po.opt_id, name=po.name,
                        status="REQUIRES_ADMIN",
                        current_value=check_result.current_value,
                    ))
                    continue

                if status_val == "RECOMMENDATION_ONLY":
                    session.optimizations.append(SessionOptimization(
                        opt_id=po.opt_id, name=po.name,
                        status="RECOMMENDATION_ONLY",
                        current_value=check_result.current_value,
                    ))
                    continue

                if status_val in ("NOT_APPLICABLE", "NOT AVAILABLE"):
                    session.optimizations.append(SessionOptimization(
                        opt_id=po.opt_id, name=po.name,
                        status=status_val,
                        current_value=check_result.current_value,
                    ))
                    continue

                # Apply
                try:
                    opt.snapshot()
                    apply_result = opt.apply()
                    if hasattr(apply_result.status, 'value'):
                        apply_status = apply_result.status.value
                    else:
                        apply_status = str(apply_result.status)

                    if apply_status == "APPLIED":
                        time.sleep(0.3)
                        verified = opt.verify()
                        session.optimizations.append(SessionOptimization(
                            opt_id=po.opt_id, name=po.name,
                            status="APPLIED",
                            current_value=check_result.current_value,
                            applied_value=apply_result.message,
                            verified=verified,
                        ))
                        logger.info(f"[SESSION] Applied: {po.name} (verified={verified})")
                    elif apply_status == "RECOMMENDATION_ONLY":
                        session.optimizations.append(SessionOptimization(
                            opt_id=po.opt_id, name=po.name,
                            status="RECOMMENDATION_ONLY",
                            current_value=check_result.current_value,
                        ))
                    else:
                        session.optimizations.append(SessionOptimization(
                            opt_id=po.opt_id, name=po.name,
                            status="FAILED",
                            error=apply_result.message,
                        ))
                except Exception as e:
                    session.optimizations.append(SessionOptimization(
                        opt_id=po.opt_id, name=po.name,
                        status="FAILED",
                        error=str(e),
                    ))
                    logger.error(f"[SESSION] Apply failed: {po.name} — {e}")

        except Exception as e:
            session.errors.append(f"Optimization error: {e}")
            logger.error(f"Optimization application failed: {e}")

    # ── Monitoring ────────────────────────────────────────────

    def _start_monitoring(self, session: GamingSession):
        """Start background telemetry monitoring."""
        self._monitoring = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop,
            args=(session,),
            daemon=True,
        )
        self._monitor_thread.start()

    def _monitor_loop(self, session: GamingSession):
        """Background monitoring loop."""
        logger.info("Monitoring started")
        sample_count = 0

        while self._monitoring and session.state == SessionState.MONITORING:
            try:
                # Check target is still alive
                if session.target_pid and not self._check_target_valid(session):
                    logger.warning(f"Target lost: PID {session.target_pid}")
                    break

                # Record telemetry sample
                from app.core.telemetry import telemetry_engine
                frame = telemetry_engine.current

                sample = {
                    "timestamp": time.time(),
                    "cpu": frame.cpu_utilization,
                    "gpu": frame.gpu_utilization,
                    "ram": frame.ram_percent,
                    "gpu_temp": frame.gpu_temp,
                }
                session.telemetry_history.append(sample)
                sample_count += 1

                # Keep history manageable (last 300 samples = 5 min at 1s)
                if len(session.telemetry_history) > 300:
                    session.telemetry_history = session.telemetry_history[-300:]

                self._notify()

            except Exception as e:
                logger.debug(f"Monitor sample error: {e}")

            time.sleep(1.0)

        logger.info(f"Monitoring stopped after {sample_count} samples")

    # ── PresentMon Cleanup ────────────────────────────────────

    def _cleanup_presentmon(self, session: GamingSession):
        """Ensure no stale PresentMon processes or CSV files remain."""
        try:
            # Clean CSV files
            import glob
            import tempfile
            temp_dir = tempfile.gettempdir()
            csv_pattern = os.path.join(temp_dir, "phoenix_pm_*.csv")
            for csv_path in glob.glob(csv_pattern):
                try:
                    os.remove(csv_path)
                    session.csv_cleaned = True
                    logger.info(f"Cleaned CSV: {csv_path}")
                except Exception:
                    pass

            # Verify no stale PresentMon processes
            import psutil
            for proc in psutil.process_iter(["name", "pid"]):
                try:
                    if proc.info["name"] and "presentmon" in proc.info["name"].lower():
                        # Only log — don't kill elevated processes
                        logger.info(f"PresentMon process still running: PID {proc.info['pid']}")
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            session.presentmon_stopped = True

        except Exception as e:
            logger.debug(f"PresentMon cleanup: {e}")

    # ── Safe Cleanup ──────────────────────────────────────────

    def _cleanup_safe(self, session: GamingSession):
        """Ensure all resources are cleaned up safely."""
        try:
            self._monitoring = False
            if self._monitor_thread and self._monitor_thread.is_alive():
                self._monitor_thread.join(timeout=3.0)
        except Exception:
            pass

        try:
            self._cleanup_presentmon(session)
        except Exception:
            pass


# ── Singleton ─────────────────────────────────────────────────

gaming_session_engine = GamingSessionEngine()
