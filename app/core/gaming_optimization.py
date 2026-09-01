"""
Phase 49 — Gaming Session Optimization.

Intelligent optimization layer that runs during active gaming sessions.

Architecture:
  GamingStateDetector  — Classifies current gaming state
  GamingSessionManager — Manages session lifecycle and optimization decisions
  GamingOptimizationWorker — Background worker for heavy telemetry/optimization work

States:
  IDLE → GAME_DETECTED → STARTING → OPTIMIZING → GAMING → DEGRADED → STOPPING → IDLE

Rules:
  - Only apply optimizations when evidence indicates they are beneficial
  - Do NOT continuously modify settings every telemetry tick
  - Use cooldowns, hysteresis, thresholds, session state, change tracking
  - Do NOT claim optimization improves FPS unless measured evidence supports it
  - All heavy work runs in background workers
  - GUI must remain responsive
  - Never modify game files, inject input, create macros, or bypass anti-cheat
"""

import json
import os
import statistics
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("core.gaming_optimization")


# ── Enums ────────────────────────────────────────────────────────

class GamingState(Enum):
    """Current gaming session state."""
    IDLE = "IDLE"
    GAME_DETECTED = "GAME_DETECTED"
    STARTING = "STARTING"
    OPTIMIZING = "OPTIMIZING"
    GAMING = "GAMING"
    DEGRADED = "DEGRADED"
    STOPPING = "STOPPING"


class OptimizationAction(Enum):
    """Types of optimization actions the manager can take."""
    NONE = "NONE"
    APPLY_POWER_PLAN = "APPLY_POWER_PLAN"
    APPLY_GAME_MODE = "APPLY_GAME_MODE"
    APPLY_EMULATOR_PRIORITY = "APPLY_EMULATOR_PRIORITY"
    APPLY_MEMORY_ANALYSIS = "APPLY_MEMORY_ANALYSIS"
    RECOMMEND_BACKGROUND_LOAD = "RECOMMEND_BACKGROUND_LOAD"
    MONITOR_ONLY = "MONITOR_ONLY"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class TelemetrySnapshot:
    """Point-in-time telemetry reading for gaming optimization."""
    timestamp: float = 0.0

    cpu_percent: Optional[float] = None
    gpu_percent: Optional[float] = None
    gpu_temp: Optional[float] = None
    ram_percent: Optional[float] = None
    ram_available_gb: Optional[float] = None
    fps: Optional[float] = None
    frame_time_ms: Optional[float] = None
    one_percent_low: Optional[float] = None

    target_name: str = ""
    target_pid: int = 0
    target_cpu: Optional[float] = None
    target_ram_mb: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class OptimizationDecision:
    """A single optimization decision made by the manager."""
    action: OptimizationAction = OptimizationAction.NONE
    confidence: int = 0
    reason: str = ""
    evidence: Dict[str, float] = field(default_factory=dict)
    risk_level: str = "LOW"
    reversible: bool = True
    timestamp: float = 0.0
    applied: bool = False
    verified: bool = False
    error: str = ""

    def to_dict(self) -> dict:
        return {
            "action": self.action.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": self.evidence,
            "risk_level": self.risk_level,
            "reversible": self.reversible,
            "applied": self.applied,
            "verified": self.verified,
            "error": self.error,
        }


@dataclass
class SessionBaseline:
    """Baseline metrics captured at session start."""
    timestamp: float = 0.0
    cpu_percent: Optional[float] = None
    gpu_percent: Optional[float] = None
    gpu_temp: Optional[float] = None
    ram_percent: Optional[float] = None
    fps: Optional[float] = None
    frame_time_ms: Optional[float] = None
    target_name: str = ""
    target_pid: int = 0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class GamingSessionRecord:
    """Complete record of a gaming optimization session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: float = 0.0

    state: str = "IDLE"

    # Target
    target_name: str = ""
    target_pid: int = 0

    # Baseline
    baseline: Optional[SessionBaseline] = None

    # Current state
    current_cpu: Optional[float] = None
    current_gpu: Optional[float] = None
    current_gpu_temp: Optional[float] = None
    current_ram: Optional[float] = None
    current_fps: Optional[float] = None
    current_frame_time: Optional[float] = None

    # Telemetry history (last N snapshots)
    telemetry_history: List[Dict] = field(default_factory=list)

    # Optimization decisions
    decisions: List[Dict] = field(default_factory=list)

    # Summary
    total_ticks: int = 0
    optimizations_applied: int = 0
    optimizations_skipped: int = 0
    cooldown_events: int = 0
    degraded_events: int = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "state": self.state,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "current_cpu": self.current_cpu,
            "current_gpu": self.current_gpu,
            "current_gpu_temp": self.current_gpu_temp,
            "current_ram": self.current_ram,
            "current_fps": self.current_fps,
            "current_frame_time": self.current_frame_time,
            "total_ticks": self.total_ticks,
            "optimizations_applied": self.optimizations_applied,
            "optimizations_skipped": self.optimizations_skipped,
            "cooldown_events": self.cooldown_events,
            "degraded_events": self.degraded_events,
            "decisions": self.decisions[-20:],  # Last 20 decisions
        }

    def format_cli(self) -> str:
        lines = []
        w = 60
        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — GAMING SESSION")
        lines.append("=" * w)
        lines.append("")
        lines.append(f"  Session:  {self.session_id}")
        lines.append(f"  State:    {self.state}")
        lines.append(f"  Target:   {self.target_name or 'None'} PID {self.target_pid}")
        lines.append(f"  Duration: {self.duration_seconds:.0f}s")
        lines.append("")

        if self.baseline:
            b = self.baseline
            lines.append("BASELINE")
            lines.append("-" * w)
            if b.cpu_percent is not None:
                lines.append(f"  CPU:      {b.cpu_percent:.1f}%")
            if b.gpu_percent is not None:
                lines.append(f"  GPU:      {b.gpu_percent:.1f}%")
            if b.gpu_temp is not None:
                lines.append(f"  GPU Temp: {b.gpu_temp:.0f}°C")
            if b.ram_percent is not None:
                lines.append(f"  RAM:      {b.ram_percent:.1f}%")
            if b.fps is not None:
                lines.append(f"  FPS:      {b.fps:.1f}")
            lines.append("")

        lines.append("CURRENT")
        lines.append("-" * w)
        if self.current_cpu is not None:
            lines.append(f"  CPU:      {self.current_cpu:.1f}%")
        if self.current_gpu is not None:
            lines.append(f"  GPU:      {self.current_gpu:.1f}%")
        if self.current_gpu_temp is not None:
            lines.append(f"  GPU Temp: {self.current_gpu_temp:.0f}°C")
        if self.current_ram is not None:
            lines.append(f"  RAM:      {self.current_ram:.1f}%")
        if self.current_fps is not None:
            lines.append(f"  FPS:      {self.current_fps:.1f}")
        if self.current_frame_time is not None:
            lines.append(f"  Frame:    {self.current_frame_time:.1f}ms")
        lines.append("")

        lines.append("SUMMARY")
        lines.append("-" * w)
        lines.append(f"  Ticks:        {self.total_ticks}")
        lines.append(f"  Applied:      {self.optimizations_applied}")
        lines.append(f"  Skipped:      {self.optimizations_skipped}")
        lines.append(f"  Cooldowns:    {self.cooldown_events}")
        lines.append(f"  Degraded:     {self.degraded_events}")

        if self.decisions:
            lines.append("")
            lines.append("RECENT DECISIONS")
            lines.append("-" * w)
            for d in self.decisions[-5:]:
                action = d.get("action", "NONE")
                reason = d.get("reason", "")
                applied = "✓" if d.get("applied") else "✗"
                lines.append(f"  [{applied}] {action}: {reason}")

        lines.append("")
        lines.append("=" * w)
        return "\n".join(lines)


# ── Constants ────────────────────────────────────────────────────

# Cooldown: minimum seconds between optimization applications
OPTIMIZATION_COOLDOWN_SECONDS = 30.0

# Hysteresis: threshold must be exceeded for N consecutive ticks before action
CONSECUTIVE_TICKS_THRESHOLD = 3

# Telemetry history length
MAX_TELEMETRY_HISTORY = 300  # ~5 min at 1s intervals

# Decision history length
MAX_DECISION_HISTORY = 50

# Degradation thresholds
GPU_TEMP_HIGH = 85.0
GPU_TEMP_CRITICAL = 90.0
RAM_PRESSURE_HIGH = 90.0
CPU_SATURATION = 90.0
FPS_INSTABILITY_CV = 0.25  # Coefficient of variation

# Session persistence directory
SESSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "gaming_opt_sessions",
)


# ── Gaming State Detector ────────────────────────────────────────

class GamingStateDetector:
    """
    Detects the current gaming state from system telemetry.

    Rules:
      - Requires sufficient samples before declaring a state
      - Uses hysteresis to prevent oscillation
      - Never claims improvement without measured evidence
    """

    def __init__(self):
        self._consecutive_counts: Dict[str, int] = {}
        self._last_state = GamingState.IDLE
        self._state_changed_at = time.time()

    @property
    def last_state(self) -> GamingState:
        return self._last_state

    def detect_state(
        self,
        target_name: str,
        target_pid: int,
        snapshots: List[TelemetrySnapshot],
        applied_optimizations: int = 0,
        last_optimization_time: float = 0.0,
    ) -> GamingState:
        """
        Determine the current gaming state from telemetry snapshots.

        Uses hysteresis: requires CONSECUTIVE_TICKS_THRESHOLD consecutive
        readings before changing state.
        """
        now = time.time()

        # No target → IDLE
        if not target_name or not target_pid:
            return self._transition_to(GamingState.IDLE, "no_target")

        # Check if target process is still alive
        if not self._check_target_alive(target_pid):
            return self._transition_to(GamingState.IDLE, "target_lost")

        # Not enough data → GAME_DETECTED
        if len(snapshots) < 3:
            return self._transition_to(GamingState.GAME_DETECTED, "insufficient_data")

        # Check for degradation conditions
        recent = snapshots[-5:] if len(snapshots) >= 5 else snapshots

        degradation_reason = self._check_degradation(recent)
        if degradation_reason:
            # Cooldown check — don't re-enter DEGRADED if we just applied
            if now - last_optimization_time < OPTIMIZATION_COOLDOWN_SECONDS:
                return self._transition_to(GamingState.GAMING, "cooldown_after_optimization")
            return self._transition_to(GamingState.DEGRADED, degradation_reason)

        # If optimizations were recently applied and verified → GAMING
        if applied_optimizations > 0:
            return self._transition_to(GamingState.GAMING, "optimizations_active")

        # Steady telemetry → GAMING
        return self._transition_to(GamingState.GAMING, "steady_telemetry")

    def _transition_to(self, new_state: GamingState, reason: str) -> GamingState:
        """Apply hysteresis before transitioning state."""
        key = new_state.value
        self._consecutive_counts[key] = self._consecutive_counts.get(key, 0) + 1

        # Reset other counters
        for k in list(self._consecutive_counts.keys()):
            if k != key:
                self._consecutive_counts[k] = 0

        # Require consecutive ticks for state change
        if new_state != self._last_state:
            # Allow immediate transition from IDLE (no game → game detected)
            if self._last_state == GamingState.IDLE:
                logger.info(f"State: {self._last_state.value} → {new_state.value} ({reason})")
                self._last_state = new_state
                self._state_changed_at = time.time()
            elif self._consecutive_counts[key] < CONSECUTIVE_TICKS_THRESHOLD:
                return self._last_state  # Stay in current state
            else:
                # State change confirmed
                logger.info(f"State: {self._last_state.value} → {new_state.value} ({reason})")
                self._last_state = new_state
                self._state_changed_at = time.time()

        return self._last_state

    def _check_degradation(self, snapshots: List[TelemetrySnapshot]) -> Optional[str]:
        """Check if recent snapshots indicate degradation."""
        if not snapshots:
            return None

        # GPU thermal degradation
        gpu_temps = [s.gpu_temp for s in snapshots if s.gpu_temp is not None]
        if gpu_temps:
            max_temp = max(gpu_temps)
            if max_temp >= GPU_TEMP_CRITICAL:
                return f"gpu_thermal_critical_{max_temp:.0f}c"
            if max_temp >= GPU_TEMP_HIGH:
                # Only degrade if temp is rising
                if len(gpu_temps) >= 3 and gpu_temps[-1] > gpu_temps[0] + 2:
                    return f"gpu_thermal_rising_{max_temp:.0f}c"

        # RAM pressure
        ram_vals = [s.ram_percent for s in snapshots if s.ram_percent is not None]
        if ram_vals:
            avg_ram = statistics.mean(ram_vals)
            if avg_ram >= RAM_PRESSURE_HIGH:
                return f"ram_pressure_{avg_ram:.0f}%"

        # CPU saturation
        cpu_vals = [s.cpu_percent for s in snapshots if s.cpu_percent is not None]
        if cpu_vals:
            avg_cpu = statistics.mean(cpu_vals)
            if avg_cpu >= CPU_SATURATION:
                return f"cpu_saturation_{avg_cpu:.0f}%"

        # Frame time instability (if FPS data available)
        fps_vals = [s.fps for s in snapshots if s.fps is not None and s.fps > 0]
        if len(fps_vals) >= 3:
            mean_fps = statistics.mean(fps_vals)
            if mean_fps > 0:
                stdev = statistics.stdev(fps_vals) if len(fps_vals) > 1 else 0
                cv = stdev / mean_fps
                if cv > FPS_INSTABILITY_CV:
                    return f"fps_instability_cv_{cv:.2f}"

        return None

    def _check_target_alive(self, pid: int) -> bool:
        """Check if target process is still running."""
        try:
            import psutil
            proc = psutil.Process(pid)
            return proc.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False


# ── Gaming Session Manager ───────────────────────────────────────

class GamingSessionManager:
    """
    Manages gaming optimization sessions.

    Lifecycle:
      1. Detect game/emulator target
      2. Capture baseline telemetry
      3. Apply initial safe optimizations
      4. Monitor with cooldowns and hysteresis
      5. Apply reactive optimizations only when evidence warrants
      6. Capture final telemetry on stop
      7. Compare baseline vs final
      8. Persist session record

    Never applies optimizations blindly.
    Never claims improvement without measured evidence.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._state_detector = GamingStateDetector()
        self._session: Optional[GamingSessionRecord] = None
        self._snapshots: List[TelemetrySnapshot] = []
        self._last_optimization_time: float = 0.0
        self._applied_optimizations: int = 0
        self._consecutive_no_action: int = 0
        self._callback = None

    @property
    def session(self) -> Optional[GamingSessionRecord]:
        return self._session

    @property
    def state(self) -> GamingState:
        if not self._session:
            return GamingState.IDLE
        return GamingState(self._session.state)

    @property
    def is_active(self) -> bool:
        return self._session is not None and self._session.state not in ("IDLE", "STOPPING")

    def on_update(self, callback):
        """Register callback for session state updates."""
        self._callback = callback

    def _notify(self):
        if self._callback and self._session:
            try:
                self._callback(self._session)
            except Exception:
                pass

    # ── Lifecycle ─────────────────────────────────────────────

    def start_session(self, profile_id: str = "gaming") -> GamingSessionRecord:
        """Start a new gaming optimization session."""
        with self._lock:
            if self._session and self.is_active:
                logger.warning("Session already active")
                return self._session

            session = GamingSessionRecord()
            session.started_at = datetime.now().isoformat()
            session.state = GamingState.STARTING.value
            self._session = session
            self._snapshots = []
            self._last_optimization_time = 0.0
            self._applied_optimizations = 0
            self._consecutive_no_action = 0

        # Detect target
        target_name, target_pid = self._detect_target()
        session.target_name = target_name
        session.target_pid = target_pid

        if not target_name or not target_pid:
            session.state = GamingState.IDLE.value
            logger.info("No emulator target detected")
            self._notify()
            return session

        # Capture baseline
        baseline = self._capture_baseline(target_name, target_pid)
        session.baseline = baseline

        # Apply initial safe optimizations
        self._apply_initial_optimizations(session, profile_id)

        session.state = GamingState.GAMING.value
        logger.info(f"Session started: {session.session_id} target={target_name} pid={target_pid}")
        self._notify()
        return session

    def stop_session(self) -> GamingSessionRecord:
        """Stop the current gaming optimization session."""
        with self._lock:
            if not self._session:
                return GamingSessionRecord()

            session = self._session
            session.state = GamingState.STOPPING.value
            self._notify()

        # Capture final state
        if session.target_pid:
            self._capture_current_state(session)

        session.ended_at = datetime.now().isoformat()
        session.state = GamingState.IDLE.value

        try:
            start = datetime.fromisoformat(session.started_at)
            end = datetime.fromisoformat(session.ended_at)
            session.duration_seconds = (end - start).total_seconds()
        except Exception:
            pass

        # Persist
        self._save_session(session)

        with self._lock:
            self._session = None
            self._snapshots = []

        logger.info(f"Session stopped: {session.session_id} duration={session.duration_seconds:.0f}s")
        self._notify()
        return session

    # ── Monitoring Tick ───────────────────────────────────────

    def tick(self) -> Optional[OptimizationDecision]:
        """
        Process a single monitoring tick.

        Called periodically by the background worker.
        Returns the optimization decision made (or NONE).
        """
        with self._lock:
            if not self._session or not self.is_active:
                return None

            session = self._session

        # Capture current telemetry
        snapshot = self._capture_snapshot()
        if snapshot:
            self._snapshots.append(snapshot)
            if len(self._snapshots) > MAX_TELEMETRY_HISTORY:
                self._snapshots = self._snapshots[-MAX_TELEMETRY_HISTORY:]

            # Update session current values
            session.current_cpu = snapshot.cpu_percent
            session.current_gpu = snapshot.gpu_percent
            session.current_gpu_temp = snapshot.gpu_temp
            session.current_ram = snapshot.ram_percent
            session.current_fps = snapshot.fps
            session.current_frame_time = snapshot.frame_time_ms
            session.total_ticks += 1

            # Store in telemetry history (limited)
            session.telemetry_history.append(snapshot.to_dict())
            if len(session.telemetry_history) > 50:
                session.telemetry_history = session.telemetry_history[-50:]

        # Detect state
        new_state = self._state_detector.detect_state(
            session.target_name,
            session.target_pid,
            self._snapshots,
            self._applied_optimizations,
            self._last_optimization_time,
        )

        old_state = session.state
        session.state = new_state.value

        if new_state.value != old_state:
            logger.info(f"State: {old_state} → {new_state.value}")

        # Make optimization decision
        decision = self._make_decision(session, new_state, snapshot)

        if decision and decision.action != OptimizationAction.NONE:
            session.decisions.append(decision.to_dict())
            if len(session.decisions) > MAX_DECISION_HISTORY:
                session.decisions = session.decisions[-MAX_DECISION_HISTORY:]

            if decision.applied:
                session.optimizations_applied += 1
                self._applied_optimizations += 1
                self._last_optimization_time = time.time()
            else:
                session.optimizations_skipped += 1

        self._notify()
        return decision

    # ── Decision Making ───────────────────────────────────────

    def _make_decision(
        self,
        session: GamingSessionRecord,
        state: GamingState,
        snapshot: Optional[TelemetrySnapshot],
    ) -> Optional[OptimizationDecision]:
        """
        Make an optimization decision based on current state.

        Rules:
          - Only act when state is DEGRADED
          - Check cooldown before applying
          - Verify each optimization before claiming success
          - Never apply RECOMMENDATION_ONLY actions automatically
        """
        now = time.time()

        # IDLE or GAME_DETECTED → no action
        if state in (GamingState.IDLE, GamingState.GAME_DETECTED, GamingState.STARTING):
            return OptimizationDecision(
                action=OptimizationAction.NONE,
                reason=f"State is {state.value}",
            )

        # GAMING → monitor only (no action needed)
        if state == GamingState.GAMING:
            self._consecutive_no_action += 1
            return OptimizationDecision(
                action=OptimizationAction.MONITOR_ONLY,
                reason="System stable — monitoring",
            )

        # DEGRADED → evaluate what action to take
        if state == GamingState.DEGRADED:
            # Cooldown check
            elapsed = now - self._last_optimization_time
            if elapsed < OPTIMIZATION_COOLDOWN_SECONDS:
                remaining = OPTIMIZATION_COOLDOWN_SECONDS - elapsed
                session.cooldown_events += 1
                return OptimizationDecision(
                    action=OptimizationAction.NONE,
                    reason=f"Cooldown active ({remaining:.0f}s remaining)",
                )

            # Determine the best action based on degradation reason
            return self._determine_degraded_action(session, snapshot)

        return OptimizationDecision(
            action=OptimizationAction.NONE,
            reason=f"Unhandled state: {state.value}",
        )

    def _determine_degraded_action(
        self,
        session: GamingSessionRecord,
        snapshot: Optional[TelemetrySnapshot],
    ) -> OptimizationDecision:
        """Determine the best optimization action for a DEGRADED state."""
        if not snapshot:
            return OptimizationDecision(
                action=OptimizationAction.NONE,
                reason="No telemetry data for degraded action",
            )

        # GPU thermal → do NOT increase performance settings
        if snapshot.gpu_temp is not None and snapshot.gpu_temp >= GPU_TEMP_HIGH:
            return OptimizationDecision(
                action=OptimizationAction.RECOMMEND_BACKGROUND_LOAD,
                confidence=70,
                reason=f"GPU temperature elevated ({snapshot.gpu_temp:.0f}°C) — reducing background load",
                evidence={"gpu_temp": snapshot.gpu_temp},
                risk_level="LOW",
                applied=False,
            )

        # RAM pressure → memory analysis (diagnostic only)
        if snapshot.ram_percent is not None and snapshot.ram_percent >= RAM_PRESSURE_HIGH:
            return OptimizationDecision(
                action=OptimizationAction.APPLY_MEMORY_ANALYSIS,
                confidence=75,
                reason=f"RAM pressure high ({snapshot.ram_percent:.1f}%) — analyzing memory",
                evidence={"ram_percent": snapshot.ram_percent},
                risk_level="NONE",
                applied=self._try_apply_optimization("memory_analysis"),
            )

        # CPU saturation → emulator priority (if admin)
        if snapshot.cpu_percent is not None and snapshot.cpu_percent >= CPU_SATURATION:
            return OptimizationDecision(
                action=OptimizationAction.APPLY_EMULATOR_PRIORITY,
                confidence=65,
                reason=f"CPU saturated ({snapshot.cpu_percent:.1f}%) — boosting emulator priority",
                evidence={"cpu_percent": snapshot.cpu_percent},
                risk_level="LOW",
                reversible=True,
                applied=self._try_apply_optimization("emulator_priority"),
            )

        # Frame instability → power plan + priority
        if snapshot.fps is not None and snapshot.fps > 0:
            fps_vals = [s.fps for s in self._snapshots[-10:] if s.fps is not None and s.fps > 0]
            if len(fps_vals) >= 3:
                mean_fps = statistics.mean(fps_vals)
                stdev = statistics.stdev(fps_vals) if len(fps_vals) > 1 else 0
                cv = stdev / mean_fps if mean_fps > 0 else 0
                if cv > FPS_INSTABILITY_CV:
                    return OptimizationDecision(
                        action=OptimizationAction.APPLY_POWER_PLAN,
                        confidence=55,
                        reason=f"Frame instability detected (CV={cv:.2f}) — power plan may help consistency",
                        evidence={"fps_cv": cv, "fps_mean": mean_fps},
                        risk_level="LOW",
                        reversible=True,
                        applied=self._try_apply_optimization("power_plan"),
                    )

        # Default: monitor only
        return OptimizationDecision(
            action=OptimizationAction.MONITOR_ONLY,
            reason="Degradation detected but no clear actionable cause",
        )

    def _try_apply_optimization(self, opt_id: str) -> bool:
        """
        Try to apply a single optimization.

        Returns True if successfully applied and verified.
        Never claims success without verification.
        """
        try:
            from app.core.optimizations import get_optimization_by_id
            from app.core.optimization_base import OptimizationStatus

            opt = get_optimization_by_id(opt_id)
            if not opt:
                return False

            # Check current state
            check = opt.check()
            if check.status in (
                OptimizationStatus.ALREADY_OPTIMAL,
                OptimizationStatus.RECOMMENDATION_ONLY,
                OptimizationStatus.NOT_APPLICABLE,
                OptimizationStatus.NOT_AVAILABLE,
            ):
                return False

            if check.status == OptimizationStatus.REQUIRES_ADMIN:
                try:
                    from app.utils.admin import is_admin
                    if not is_admin():
                        return False
                except Exception:
                    return False

            if check.status != OptimizationStatus.OPTIMIZABLE:
                return False

            # Snapshot for rollback
            try:
                opt.snapshot()
            except Exception:
                pass

            # Apply
            result = opt.apply()
            if result.status != OptimizationStatus.APPLIED:
                return False

            # Verify
            time.sleep(0.3)
            verified = opt.verify()
            if verified:
                logger.info(f"[GAMING] Applied: {opt_id}")
                return True
            else:
                logger.warning(f"[GAMING] Applied but verification failed: {opt_id}")
                # Rollback
                try:
                    opt.rollback()
                except Exception:
                    pass
                return False

        except Exception as e:
            logger.debug(f"Optimization {opt_id} failed: {e}")
            return False

    # ── Telemetry Capture ─────────────────────────────────────

    def _detect_target(self) -> Tuple[str, int]:
        """Detect current emulator target."""
        try:
            from app.performance.target_process import target_process_detector
            best = target_process_detector.select_best_target()
            if best:
                return best.process_name, best.pid
        except Exception as e:
            logger.debug(f"Target detection: {e}")
        return "", 0

    def _capture_baseline(self, target_name: str, target_pid: int) -> SessionBaseline:
        """Capture baseline metrics at session start."""
        baseline = SessionBaseline(
            timestamp=time.time(),
            target_name=target_name,
            target_pid=target_pid,
        )

        try:
            import psutil
            baseline.cpu_percent = psutil.cpu_percent(interval=0.5)
            vm = psutil.virtual_memory()
            baseline.ram_percent = vm.percent
        except Exception:
            pass

        try:
            from app.system.gpu import gpu_monitor
            gpu = gpu_monitor.detect()
            if gpu and gpu.utilization is not None:
                baseline.gpu_percent = float(gpu.utilization)
            if hasattr(gpu, "temperature") and gpu.temperature is not None:
                baseline.gpu_temp = float(gpu.temperature)
        except Exception:
            pass

        # Try to get FPS from PresentMon
        try:
            from app.performance.presentmon_provider import PresentMonProvider
            provider = PresentMonProvider()
            if provider and provider.is_running:
                sample = provider.get_latest_sample()
                if sample:
                    baseline.fps = getattr(sample, "present_fps", None)
                    baseline.frame_time_ms = getattr(sample, "average_frame_time_ms", None)
        except Exception:
            pass

        # Emulator process metrics
        if target_pid:
            try:
                import psutil
                proc = psutil.Process(target_pid)
                baseline.cpu_percent = proc.cpu_percent(interval=0.3)
            except Exception:
                pass

        return baseline

    def _capture_snapshot(self) -> Optional[TelemetrySnapshot]:
        """Capture current telemetry as a snapshot."""
        snapshot = TelemetrySnapshot(timestamp=time.time())

        try:
            import psutil
            snapshot.cpu_percent = psutil.cpu_percent(interval=0.1)
            vm = psutil.virtual_memory()
            snapshot.ram_percent = vm.percent
            snapshot.ram_available_gb = vm.available / (1024 ** 3)
        except Exception:
            pass

        try:
            from app.system.gpu import gpu_monitor
            gpu = gpu_monitor.detect()
            if gpu and gpu.utilization is not None:
                snapshot.gpu_percent = float(gpu.utilization)
            if hasattr(gpu, "temperature") and gpu.temperature is not None:
                snapshot.gpu_temp = float(gpu.temperature)
        except Exception:
            pass

        # FPS from PresentMon
        try:
            from app.performance.presentmon_provider import PresentMonProvider
            provider = PresentMonProvider()
            if provider and provider.is_running:
                sample = provider.get_latest_sample()
                if sample:
                    snapshot.fps = getattr(sample, "present_fps", None)
                    snapshot.frame_time_ms = getattr(sample, "average_frame_time_ms", None)
                    snapshot.one_percent_low = getattr(sample, "one_percent_low", None)
        except Exception:
            pass

        # Emulator process metrics
        session = self._session
        if session and session.target_pid:
            snapshot.target_name = session.target_name
            snapshot.target_pid = session.target_pid
            try:
                import psutil
                proc = psutil.Process(session.target_pid)
                snapshot.target_cpu = proc.cpu_percent(interval=None)
                mem = proc.memory_info()
                snapshot.target_ram_mb = mem.rss / (1024 * 1024)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return snapshot

    def _capture_current_state(self, session: GamingSessionRecord):
        """Capture final state for the session."""
        snapshot = self._capture_snapshot()
        if snapshot:
            session.current_cpu = snapshot.cpu_percent
            session.current_gpu = snapshot.gpu_percent
            session.current_gpu_temp = snapshot.gpu_temp
            session.current_ram = snapshot.ram_percent
            session.current_fps = snapshot.fps
            session.current_frame_time = snapshot.frame_time_ms

    # ── Initial Optimizations ─────────────────────────────────

    def _apply_initial_optimizations(self, session: GamingSessionRecord, profile_id: str):
        """Apply safe initial optimizations at session start."""
        from app.core.profiles import get_profile

        profile = get_profile(profile_id)
        if not profile:
            return

        for po in profile.optimizations:
            # Only apply safe, non-admin optimizations initially
            if po.opt_id in ("memory_analysis", "background_load"):
                continue  # Skip recommendation-only

            try:
                applied = self._try_apply_optimization(po.opt_id)
                decision = OptimizationDecision(
                    action=OptimizationAction(f"APPLY_{po.opt_id.upper()}"),
                    confidence=80 if applied else 0,
                    reason=f"Initial optimization: {po.name}",
                    applied=applied,
                    timestamp=time.time(),
                )
                session.decisions.append(decision.to_dict())
                if applied:
                    session.optimizations_applied += 1
                    self._applied_optimizations += 1
            except Exception as e:
                logger.debug(f"Initial optimization {po.opt_id} failed: {e}")

        self._last_optimization_time = time.time()

    # ── Persistence ───────────────────────────────────────────

    def _save_session(self, session: GamingSessionRecord):
        """Save session to disk."""
        try:
            os.makedirs(SESSIONS_DIR, exist_ok=True)
            filepath = os.path.join(SESSIONS_DIR, f"{session.session_id}.json")
            with open(filepath, "w") as f:
                json.dump(session.to_dict(), f, indent=2, default=str)
        except Exception as e:
            logger.debug(f"Failed to save session: {e}")

    def load_history(self, count: int = 10) -> List[Dict]:
        """Load recent session history from disk."""
        try:
            if not os.path.exists(SESSIONS_DIR):
                return []
            files = sorted(
                [f for f in os.listdir(SESSIONS_DIR) if f.endswith(".json")],
                key=lambda f: os.path.getmtime(os.path.join(SESSIONS_DIR, f)),
                reverse=True,
            )
            records = []
            for fname in files[:count]:
                try:
                    with open(os.path.join(SESSIONS_DIR, fname)) as f:
                        records.append(json.load(f))
                except Exception:
                    continue
            return records
        except Exception:
            return []

    # ── UI Summary ────────────────────────────────────────────

    def get_ui_summary(self) -> Dict:
        """Get structured summary for UI consumption."""
        summary = {
            "state": "IDLE",
            "target_name": "",
            "target_pid": 0,
            "duration_seconds": 0,
            "cpu": None,
            "gpu": None,
            "gpu_temp": None,
            "ram": None,
            "fps": None,
            "frame_time": None,
            "baseline_cpu": None,
            "baseline_gpu": None,
            "baseline_ram": None,
            "baseline_fps": None,
            "optimizations_applied": 0,
            "total_ticks": 0,
            "last_action": "NONE",
            "last_reason": "",
        }

        if not self._session:
            return summary

        s = self._session
        summary["state"] = s.state
        summary["target_name"] = s.target_name
        summary["target_pid"] = s.target_pid
        summary["duration_seconds"] = s.duration_seconds
        summary["cpu"] = s.current_cpu
        summary["gpu"] = s.current_gpu
        summary["gpu_temp"] = s.current_gpu_temp
        summary["ram"] = s.current_ram
        summary["fps"] = s.current_fps
        summary["frame_time"] = s.current_frame_time
        summary["optimizations_applied"] = s.optimizations_applied
        summary["total_ticks"] = s.total_ticks

        if s.baseline:
            summary["baseline_cpu"] = s.baseline.cpu_percent
            summary["baseline_gpu"] = s.baseline.gpu_percent
            summary["baseline_ram"] = s.baseline.ram_percent
            summary["baseline_fps"] = s.baseline.fps

        if s.decisions:
            last = s.decisions[-1]
            summary["last_action"] = last.get("action", "NONE")
            summary["last_reason"] = last.get("reason", "")

        return summary


# ── Gaming Optimization Worker (QThread) ─────────────────────────

class GamingOptimizationWorker:
    """
    Background worker for gaming optimization.

    Runs telemetry collection and optimization decisions off the GUI thread.
    Emits results via a callback mechanism.

    Usage from QThread:
      worker = GamingOptimizationWorker(session_manager)
      worker.tick()  # Called from background thread
      result = worker.get_last_result()  # Read from GUI thread
    """

    def __init__(self, manager: GamingSessionManager):
        self._manager = manager
        self._last_tick_time = 0.0
        self._tick_interval = 2.0  # seconds between ticks
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._callback = None

    @property
    def is_running(self) -> bool:
        return self._running

    def on_tick_complete(self, callback):
        """Register callback for tick completion."""
        self._callback = callback

    def start(self):
        """Start the background monitoring worker."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker_loop,
            daemon=True,
            name="gaming_opt_worker",
        )
        self._thread.start()
        logger.info("Gaming optimization worker started")

    def stop(self):
        """Stop the background monitoring worker."""
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=5.0)
        self._running = False
        logger.info("Gaming optimization worker stopped")

    def tick(self) -> Optional[OptimizationDecision]:
        """Execute a single tick (can be called synchronously)."""
        return self._manager.tick()

    def _worker_loop(self):
        """Background worker loop."""
        while self._running:
            try:
                if self._manager.is_active:
                    decision = self._manager.tick()
                    self._last_tick_time = time.time()

                    if self._callback:
                        try:
                            self._callback(decision)
                        except Exception:
                            pass
            except Exception as e:
                logger.debug(f"Gaming worker tick error: {e}")

            time.sleep(self._tick_interval)

    def get_last_tick_time(self) -> float:
        return self._last_tick_time


# ── Singleton ─────────────────────────────────────────────────

gaming_session_manager = GamingSessionManager()
