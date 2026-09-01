"""
Phase 61 — Complete Automatic Gaming Lifecycle.

Orchestrates the full gaming session lifecycle:

  GAME START → DETECT → BASELINE → RECOMMEND → USER APPROVAL
  → APPLY SAFE OPTIMIZATIONS → MONITOR → VALIDATE
  → GAME END → RESTORE TEMPORARY CHANGES → SESSION REPORT

Rules:
  - Temporary changes are explicitly marked and restored on game end.
  - Permanent changes require explicit user confirmation.
  - Never restore settings belonging to another application/session.
  - When the game closes: stop workers, stop monitoring, restore, report.
  - Never modify game files, inject input, create macros, or bypass anti-cheat.
  - Every claim must be backed by measured evidence.
"""

import json
import os
import time
import uuid
import threading
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("gaming.lifecycle")


# ── Enums ────────────────────────────────────────────────────────


class LifecycleState(Enum):
    """Complete lifecycle states."""
    IDLE = "IDLE"
    DETECTING = "DETECTING"
    BASELINE = "BASELINE"
    RECOMMENDING = "RECOMMENDING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPLYING = "APPLYING"
    MONITORING = "MONITORING"
    VALIDATING = "VALIDATING"
    STOPPING = "STOPPING"
    RESTORING = "RESTORING"
    REPORTING = "REPORTING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class ChangeType(Enum):
    """Whether a change is temporary or permanent."""
    TEMPORARY = "TEMPORARY"
    PERMANENT = "PERMANENT"


class ChangeStatus(Enum):
    """Status of a tracked change."""
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    FAILED = "FAILED"
    RESTORED = "RESTORED"
    RESTORE_FAILED = "RESTORE_FAILED"
    KEPT = "KEPT"
    IRREVERSIBLE = "IRREVERSIBLE"


# ── Data Models ──────────────────────────────────────────────────


@dataclass
class LifecycleChange:
    """A single change made during the gaming lifecycle."""
    change_id: str = ""
    name: str = ""
    description: str = ""
    category: str = ""
    change_type: ChangeType = ChangeType.TEMPORARY
    status: ChangeStatus = ChangeStatus.PENDING

    # Values
    previous_value: Any = None
    new_value: Any = None

    # Rollback
    reversible: bool = True
    rollback_data: Dict[str, Any] = field(default_factory=dict)

    # Metadata
    timestamp: float = 0.0
    admin_required: bool = False
    risk_level: str = "LOW"

    def __post_init__(self):
        if not self.change_id:
            self.change_id = f"chg_{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "change_id": self.change_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "change_type": self.change_type.value,
            "status": self.status.value,
            "previous_value": self.previous_value,
            "new_value": self.new_value,
            "reversible": self.reversible,
            "timestamp": self.timestamp,
            "admin_required": self.admin_required,
            "risk_level": self.risk_level,
        }


@dataclass
class LifecycleRecommendation:
    """A recommendation presented for user approval."""
    recommendation_id: str = ""
    title: str = ""
    description: str = ""
    change_type: ChangeType = ChangeType.TEMPORARY
    category: str = ""
    expected_effect: str = ""
    risk_level: str = "LOW"
    reversible: bool = True
    approved: bool = False
    auto_apply: bool = False  # True if safe enough to auto-apply

    # Function to apply
    apply_fn_name: str = ""
    rollback_fn_name: str = ""
    rollback_data: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.recommendation_id:
            self.recommendation_id = f"rec_{uuid.uuid4().hex[:8]}"


@dataclass
class LifecycleBaseline:
    """Baseline metrics captured at session start."""
    timestamp: float = 0.0
    cpu_percent: Optional[float] = None
    gpu_percent: Optional[float] = None
    gpu_temp: Optional[float] = None
    ram_percent: Optional[float] = None
    ram_available_gb: Optional[float] = None
    fps: Optional[float] = None
    frame_time_ms: Optional[float] = None
    disk_free_gb: Optional[float] = None
    target_name: str = ""
    target_pid: int = 0
    power_plan: str = ""
    game_mode: Optional[bool] = None
    background_cpu: float = 0.0
    background_ram_mb: float = 0.0

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}

    def diff(self, other: "LifecycleBaseline") -> Dict[str, Optional[float]]:
        """Calculate differences between baseline and current state."""
        diffs = {}
        for field_name in ("cpu_percent", "gpu_percent", "gpu_temp", "ram_percent",
                           "fps", "frame_time_ms", "disk_free_gb"):
            before = getattr(self, field_name, None)
            after = getattr(other, field_name, None)
            if before is not None and after is not None:
                diffs[field_name] = after - before
            else:
                diffs[field_name] = None
        return diffs


@dataclass
class SessionReport:
    """Complete session report after lifecycle ends."""
    session_id: str = ""
    target_name: str = ""
    target_pid: int = 0
    profile_id: str = ""

    # Timing
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: float = 0.0

    # Baseline
    baseline: Optional[LifecycleBaseline] = None
    final: Optional[LifecycleBaseline] = None

    # Changes
    changes_applied: int = 0
    changes_restored: int = 0
    changes_kept: int = 0
    changes_failed: int = 0
    changes: List[Dict] = field(default_factory=list)

    # Recommendations
    recommendations_total: int = 0
    recommendations_approved: int = 0
    recommendations_auto_applied: int = 0

    # Classification
    temporary_changes: List[Dict] = field(default_factory=list)
    permanent_changes: List[Dict] = field(default_factory=list)

    # Validation
    validation_performed: bool = False
    validation_passed: bool = False
    validation_details: str = ""

    # Summary
    summary: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "profile_id": self.profile_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "final": self.final.to_dict() if self.final else None,
            "changes_applied": self.changes_applied,
            "changes_restored": self.changes_restored,
            "changes_kept": self.changes_kept,
            "changes_failed": self.changes_failed,
            "changes": self.changes,
            "recommendations_total": self.recommendations_total,
            "recommendations_approved": self.recommendations_approved,
            "recommendations_auto_applied": self.recommendations_auto_applied,
            "temporary_changes": self.temporary_changes,
            "permanent_changes": self.permanent_changes,
            "validation_performed": self.validation_performed,
            "validation_passed": self.validation_passed,
            "validation_details": self.validation_details,
            "summary": self.summary,
        }

    def format_cli(self) -> str:
        lines = []
        w = 60
        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — GAMING SESSION REPORT")
        lines.append("=" * w)
        lines.append("")
        lines.append(f"  Session:    {self.session_id}")
        lines.append(f"  Target:     {self.target_name} (PID {self.target_pid})")
        lines.append(f"  Profile:    {self.profile_id}")
        lines.append(f"  Duration:   {self.duration_seconds:.0f}s")
        lines.append(f"  Started:    {self.started_at}")
        lines.append(f"  Ended:      {self.ended_at}")
        lines.append("")

        # Baseline vs Final
        if self.baseline and self.final:
            lines.append("BEFORE / AFTER")
            lines.append("-" * w)
            for label, attr in [("CPU", "cpu_percent"), ("GPU", "gpu_percent"),
                                ("RAM", "ram_percent"), ("GPU Temp", "gpu_temp"),
                                ("FPS", "fps"), ("Frame Time", "frame_time_ms")]:
                before = getattr(self.baseline, attr, None)
                after = getattr(self.final, attr, None)
                if before is not None and after is not None:
                    delta = after - before
                    sign = "+" if delta >= 0 else ""
                    if attr == "fps":
                        lines.append(f"  {label:<12} {before:>8.1f} → {after:>8.1f}  ({sign}{delta:.1f})")
                    elif attr in ("cpu_percent", "gpu_percent", "ram_percent"):
                        lines.append(f"  {label:<12} {before:>7.1f}% → {after:>7.1f}%  ({sign}{delta:.1f}%)")
                    elif attr == "gpu_temp":
                        lines.append(f"  {label:<12} {before:>7.0f}°C → {after:>7.0f}°C  ({sign}{delta:.0f}°C)")
                    elif attr == "frame_time_ms":
                        lines.append(f"  {label:<12} {before:>7.1f}ms → {after:>7.1f}ms  ({sign}{delta:.1f}ms)")
                else:
                    lines.append(f"  {label:<12} {'N/A':>8} → {'N/A':>8}")
            lines.append("")

        # Changes
        lines.append(f"CHANGES ({self.changes_applied} applied)")
        lines.append("-" * w)
        for change in self.changes:
            status = change.get("status", "?")
            ctype = change.get("change_type", "?")
            name = change.get("name", "?")
            lines.append(f"  [{status}] ({ctype}) {name}")
        lines.append("")

        # Temporary vs Permanent
        if self.temporary_changes:
            lines.append(f"TEMPORARY CHANGES ({len(self.temporary_changes)}):")
            for tc in self.temporary_changes:
                lines.append(f"  - {tc.get('name', '?')}: {tc.get('status', '?')}")
            lines.append("")

        if self.permanent_changes:
            lines.append(f"PERMANENT CHANGES ({len(self.permanent_changes)}):")
            for pc in self.permanent_changes:
                lines.append(f"  - {pc.get('name', '?')}: {pc.get('status', '?')}")
            lines.append("")

        # Restoration
        lines.append("RESTORATION")
        lines.append("-" * w)
        lines.append(f"  Restored:  {self.changes_restored}")
        lines.append(f"  Kept:      {self.changes_kept}")
        lines.append(f"  Failed:    {self.changes_failed}")
        lines.append("")

        # Validation
        if self.validation_performed:
            status = "PASSED" if self.validation_passed else "FAILED"
            lines.append(f"VALIDATION: {status}")
            if self.validation_details:
                lines.append(f"  {self.validation_details}")
            lines.append("")

        # Summary
        if self.summary:
            lines.append("SUMMARY")
            lines.append("-" * w)
            lines.append(f"  {self.summary}")
            lines.append("")

        lines.append("=" * w)
        return "\n".join(lines)


# ── Persisted session record ─────────────────────────────────────


@dataclass
class LifecycleSession:
    """Persisted lifecycle session record."""
    session_id: str = ""
    state: str = LifecycleState.IDLE.value
    target_name: str = ""
    target_pid: int = 0
    profile_id: str = ""
    started_at: str = ""
    ended_at: str = ""
    duration_seconds: float = 0.0

    baseline: Optional[LifecycleBaseline] = None
    changes: List[LifecycleChange] = field(default_factory=list)
    recommendations: List[LifecycleRecommendation] = field(default_factory=list)
    report: Optional[SessionReport] = None

    # Change tracking counters
    changes_applied: int = 0
    changes_restored: int = 0
    changes_kept: int = 0
    changes_failed: int = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "state": self.state,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "profile_id": self.profile_id,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_seconds": self.duration_seconds,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "changes": [c.to_dict() for c in self.changes],
            "recommendations": [
                {k: v for k, v in r.__dict__.items() if not k.startswith("_")}
                for r in self.recommendations
            ],
            "changes_applied": self.changes_applied,
            "changes_restored": self.changes_restored,
            "changes_kept": self.changes_kept,
            "changes_failed": self.changes_failed,
        }


# ── Constants ────────────────────────────────────────────────────

SESSIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "lifecycle_sessions",
)


# ── Gaming Lifecycle Manager ─────────────────────────────────────


class GamingLifecycleManager:
    """
    Orchestrates the complete gaming session lifecycle.

    Flow:
      GAME START
        → DETECT (find emulator/game process)
        → BASELINE (capture before-state)
        → RECOMMEND (generate optimization proposals)
        → USER APPROVAL (user reviews recommendations)
        → APPLY SAFE OPTIMIZATIONS (only approved/temporary)
        → MONITOR (continuous telemetry)
        → VALIDATE (verify improvements or degradation)
        → GAME END (process lost or user stops)
        → RESTORE TEMPORARY CHANGES (undo temporary)
        → SESSION REPORT (generate summary)

    Rules:
      - Temporary changes are automatically restored on game end.
      - Permanent changes require explicit confirmation and are NEVER auto-restored.
      - Never restore changes belonging to another session.
      - Every change has a unique ID bound to the creating session.
      - Workers stop when the lifecycle ends.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._session: Optional[LifecycleSession] = None
        self._state = LifecycleState.IDLE
        self._worker_running = False
        self._worker_thread: Optional[threading.Thread] = None
        self._monitoring_active = False
        self._callbacks: List[Callable] = []
        self._pending_approval: Optional[List[LifecycleRecommendation]] = None

    @property
    def state(self) -> LifecycleState:
        return self._state

    @property
    def is_active(self) -> bool:
        return self._state not in (
            LifecycleState.IDLE,
            LifecycleState.COMPLETED,
            LifecycleState.FAILED,
        )

    @property
    def session(self) -> Optional[LifecycleSession]:
        return self._session

    @property
    def pending_approval(self) -> Optional[List[LifecycleRecommendation]]:
        return self._pending_approval

    def on_state_change(self, callback: Callable):
        """Register callback for lifecycle state changes."""
        self._callbacks.append(callback)

    def _notify(self, state: Optional[LifecycleState] = None):
        if state:
            self._state = state
        for cb in self._callbacks:
            try:
                cb(self._session, self._state)
            except Exception:
                pass

    # ══════════════════════════════════════════════════════════════
    #  LIFECYCLE: START
    # ══════════════════════════════════════════════════════════════

    def start(self, profile_id: str = "gaming") -> Optional[LifecycleSession]:
        """
        Begin the complete gaming lifecycle.

        Returns the session if target detected, None otherwise.
        """
        with self._lock:
            if self.is_active:
                logger.warning("Lifecycle already active")
                return self._session

        session = LifecycleSession(
            session_id=f"lc_{uuid.uuid4().hex[:8]}",
            profile_id=profile_id,
            started_at=datetime.now().isoformat(),
        )
        self._session = session

        try:
            self._detect_target(session)
            if not session.target_name or not session.target_pid:
                self._set_state(session, LifecycleState.IDLE)
                logger.info("No gaming target detected — lifecycle not started")
                return None

            self._capture_baseline(session)
            self._generate_recommendations(session)
        except Exception as e:
            session.state = LifecycleState.FAILED.value
            self._state = LifecycleState.FAILED
            logger.error(f"Lifecycle start failed: {e}")
            return None

        self._save_session(session)
        return session

    def _set_state(self, session: LifecycleSession, state: LifecycleState):
        session.state = state.value
        self._state = state
        self._notify(state)

    # ══════════════════════════════════════════════════════════════
    #  STEP 1: DETECT
    # ══════════════════════════════════════════════════════════════

    def _detect_target(self, session: LifecycleSession):
        """Detect the current game/emulator target."""
        self._set_state(session, LifecycleState.DETECTING)

        try:
            from app.performance.target_process import target_process_detector
            best = target_process_detector.select_best_target()
            if best:
                session.target_name = best.process_name
                session.target_pid = best.pid
                logger.info(f"Target detected: {best.process_name} PID={best.pid}")
                return
        except Exception as e:
            logger.debug(f"Target detection failed: {e}")

        # Fallback: check emulator controller
        try:
            from app.core.emulator_controller import emulator_controller
            target = emulator_controller.detect_target()
            if target:
                session.target_name = target.name
                session.target_pid = target.pid
                logger.info(f"Target (emulator controller): {target.name} PID={target.pid}")
                return
        except Exception as e:
            logger.debug(f"Emulator controller detection failed: {e}")

        logger.info("No gaming target detected")

    # ══════════════════════════════════════════════════════════════
    #  STEP 2: BASELINE
    # ══════════════════════════════════════════════════════════════

    def _capture_baseline(self, session: LifecycleSession):
        """Capture system baseline before any optimizations."""
        self._set_state(session, LifecycleState.BASELINE)
        baseline = LifecycleBaseline(
            timestamp=time.time(),
            target_name=session.target_name,
            target_pid=session.target_pid,
        )

        # CPU / RAM
        try:
            import psutil
            baseline.cpu_percent = psutil.cpu_percent(interval=0.5)
            vm = psutil.virtual_memory()
            baseline.ram_percent = vm.percent
            baseline.ram_available_gb = vm.available / (1024 ** 3)
        except Exception:
            pass

        # Disk
        try:
            import psutil
            disk = psutil.disk_usage("C:\\")
            baseline.disk_free_gb = disk.free / (1024 ** 3)
        except Exception:
            pass

        # GPU
        try:
            from app.system.gpu import gpu_monitor
            gpu = gpu_monitor.detect()
            if gpu and gpu.utilization is not None:
                baseline.gpu_percent = float(gpu.utilization)
            if hasattr(gpu, "temperature") and gpu.temperature is not None:
                baseline.gpu_temp = float(gpu.temperature)
        except Exception:
            pass

        # FPS
        try:
            from app.performance.presentmon_provider import PresentMonProvider
            pm = PresentMonProvider()
            if pm and pm.is_running:
                sample = pm.get_latest_sample()
                if sample:
                    baseline.fps = getattr(sample, "present_fps", None)
                    baseline.frame_time_ms = getattr(sample, "average_frame_time_ms", None)
        except Exception:
            pass

        # Power plan
        try:
            from app.system.power import power_monitor
            values = power_monitor.get_current_values()
            baseline.power_plan = values.get("active_plan_name", "")
        except Exception:
            pass

        # Background load
        try:
            from app.system.process_intelligence import process_intelligence
            scan = process_intelligence.last_scan
            if scan:
                baseline.background_cpu = scan.total_background_cpu
                baseline.background_ram_mb = scan.total_background_memory_mb
        except Exception:
            pass

        session.baseline = baseline
        logger.info(
            f"Baseline: CPU={baseline.cpu_percent}% GPU={baseline.gpu_percent}% "
            f"RAM={baseline.ram_percent}% FPS={baseline.fps}"
        )

    # ══════════════════════════════════════════════════════════════
    #  STEP 3: RECOMMEND
    # ══════════════════════════════════════════════════════════════

    def _generate_recommendations(self, session: LifecycleSession):
        """Generate optimization recommendations based on baseline and profile."""
        self._set_state(session, LifecycleState.RECOMMENDING)
        recommendations = []

        # Load profile to determine applicable optimizations
        try:
            from app.core.optimization_profiles import OptimizationProfileManager
            pm = OptimizationProfileManager()
            profile = pm.get_profile(session.profile_id)
        except Exception:
            profile = None

        # Power plan recommendation
        if session.baseline and session.baseline.power_plan:
            current_plan = session.baseline.power_plan.lower()
            # High performance plans that don't need switching
            good_plans = ("high", "ultimate", "turbo", "performance", "best")
            if not any(gp in current_plan for gp in good_plans):
                recommendations.append(LifecycleRecommendation(
                    title="Switch to High Performance power plan",
                    description=f"Current power plan '{session.baseline.power_plan}' may limit CPU performance.",
                    change_type=ChangeType.TEMPORARY,
                    category="power",
                    expected_effect="Consistent CPU clock speeds during gaming",
                    risk_level="LOW",
                    reversible=True,
                    auto_apply=True,
                    apply_fn_name="apply_power_plan_high",
                    rollback_fn_name="restore_power_plan",
                    rollback_data={"previous_plan": session.baseline.power_plan},
                ))

        # Game Mode recommendation
        if session.baseline and session.baseline.game_mode is False:
            recommendations.append(LifecycleRecommendation(
                title="Enable Windows Game Mode",
                description="Game Mode is currently disabled. Enabling it may reduce background interference.",
                change_type=ChangeType.TEMPORARY,
                category="game_mode",
                expected_effect="Reduce background task scheduling during gaming",
                risk_level="LOW",
                reversible=True,
                auto_apply=True,
                apply_fn_name="enable_game_mode",
                rollback_fn_name="restore_game_mode",
                rollback_data={"previous_enabled": False},
            ))

        # Memory pressure recommendation
        if session.baseline and session.baseline.ram_percent is not None:
            if session.baseline.ram_percent >= 85:
                recommendations.append(LifecycleRecommendation(
                    title="Analyze memory usage",
                    description=f"RAM is at {session.baseline.ram_percent:.0f}%. "
                                "High memory pressure may affect frame consistency.",
                    change_type=ChangeType.TEMPORARY,
                    category="memory",
                    expected_effect="Identify memory-heavy background processes",
                    risk_level="NONE",
                    reversible=True,
                    auto_apply=False,
                    apply_fn_name="analyze_memory",
                    rollback_fn_name="",
                ))

        # Background CPU recommendation
        if session.baseline and session.baseline.background_cpu > 30:
            recommendations.append(LifecycleRecommendation(
                title="Reduce background CPU usage",
                description=f"Background processes are using {session.baseline.background_cpu:.0f}% CPU.",
                change_type=ChangeType.TEMPORARY,
                category="background",
                expected_effect="More CPU headroom for the game/emulator",
                risk_level="LOW",
                reversible=True,
                auto_apply=False,
                apply_fn_name="reduce_background_cpu",
                rollback_fn_name="restore_background_cpu",
                rollback_data={"previous_background_cpu": session.baseline.background_cpu},
            ))

        # FPS-based recommendations
        if session.baseline and session.baseline.fps is not None:
            if session.baseline.fps < 30:
                recommendations.append(LifecycleRecommendation(
                    title="Low frame rate detected at baseline",
                    description=f"FPS is {session.baseline.fps:.0f}. "
                                "Consider reducing graphics settings in the emulator.",
                    change_type=ChangeType.PERMANENT,
                    category="performance",
                    expected_effect="Improve frame rate through settings change",
                    risk_level="MEDIUM",
                    reversible=False,
                    auto_apply=False,
                    apply_fn_name="reduce_graphics_settings",
                ))

        session.recommendations = recommendations
        logger.info(f"Generated {len(recommendations)} recommendations")

        if recommendations:
            # Check for auto-applyable recommendations
            auto_apply = [r for r in recommendations if r.auto_apply]
            manual = [r for r in recommendations if not r.auto_apply]

            if auto_apply:
                logger.info(f"Auto-applying {len(auto_apply)} safe recommendations")
                for rec in auto_apply:
                    rec.approved = True

            if manual:
                self._pending_approval = manual
                self._set_state(session, LifecycleState.AWAITING_APPROVAL)
                logger.info(f"Awaiting user approval for {len(manual)} recommendations")
                return

        # All recommendations are auto-apply or none need approval
        self._pending_approval = None
        session.recommendations_total = len(recommendations)
        session.recommendations_approved = len([r for r in recommendations if r.approved])
        session.recommendations_auto_applied = len(auto_apply) if recommendations else 0

    # ══════════════════════════════════════════════════════════════
    #  STEP 4: USER APPROVAL
    # ══════════════════════════════════════════════════════════════

    def approve_recommendations(self, approved_ids: List[str]):
        """
        User approves specific recommendations.

        Only called when state is AWAITING_APPROVAL.
        """
        with self._lock:
            if self._state != LifecycleState.AWAITING_APPROVAL:
                logger.warning("Not awaiting approval")
                return

            if not self._pending_approval:
                return

            for rec in self._pending_approval:
                if rec.recommendation_id in approved_ids:
                    rec.approved = True

            # Update session
            if self._session:
                self._session.recommendations = self._pending_approval
                self._session.recommendations_total = len(self._pending_approval)
                self._session.recommendations_approved = len(
                    [r for r in self._pending_approval if r.approved]
                )
                auto = [r for r in self._pending_approval if r.auto_apply]
                self._session.recommendations_auto_applied = len(auto)

            self._pending_approval = None

            # Proceed to apply
            self._apply_approved()

    def approve_all(self):
        """Approve all pending recommendations."""
        if self._pending_approval:
            ids = [r.recommendation_id for r in self._pending_approval]
            self.approve_recommendations(ids)

    def reject_all(self):
        """Reject all pending recommendations and proceed to monitoring."""
        with self._lock:
            self._pending_approval = None
            if self._session:
                self._set_state(self._session, LifecycleState.MONITORING)
                self._start_monitoring()

    # ══════════════════════════════════════════════════════════════
    #  STEP 5: APPLY
    # ══════════════════════════════════════════════════════════════

    def _apply_approved(self):
        """Apply all approved recommendations."""
        session = self._session
        if not session:
            return

        self._set_state(session, LifecycleState.APPLYING)

        approved = [r for r in session.recommendations if r.approved]
        for rec in approved:
            change = LifecycleChange(
                name=rec.title,
                description=rec.description,
                category=rec.category,
                change_type=rec.change_type,
                reversible=rec.reversible,
                rollback_data=rec.rollback_data,
            )

            try:
                success = self._apply_single(rec)
                if success:
                    change.status = ChangeStatus.APPLIED
                    change.new_value = f"Applied: {rec.title}"
                    session.changes.append(change)
                else:
                    change.status = ChangeStatus.FAILED
                    change.description = f"Failed to apply: {rec.title}"
                    session.changes.append(change)
            except Exception as e:
                change.status = ChangeStatus.FAILED
                change.description = f"Error: {e}"
                session.changes.append(change)
                logger.error(f"Failed to apply recommendation {rec.title}: {e}")

        self._save_session(session)

        # Start monitoring
        self._set_state(session, LifecycleState.MONITORING)
        self._start_monitoring()

    def _apply_single(self, rec: LifecycleRecommendation) -> bool:
        """Apply a single recommendation."""
        fn_name = rec.apply_fn_name

        if fn_name == "apply_power_plan_high":
            return self._apply_power_plan("high_performance")
        elif fn_name == "enable_game_mode":
            return self._apply_game_mode(True)
        elif fn_name == "analyze_memory":
            return self._apply_memory_analysis()
        elif fn_name == "reduce_background_cpu":
            return self._reduce_background_cpu()
        elif fn_name == "reduce_graphics_settings":
            # Permanent change — only if explicitly approved
            return False  # Not auto-applied

        logger.debug(f"Unknown apply function: {fn_name}")
        return False

    def _apply_power_plan(self, plan_name: str) -> bool:
        """Apply a power plan change."""
        try:
            from app.system.power import power_monitor
            result = power_monitor.set_power_plan(plan_name)
            return result is not None and result.get("success", False)
        except Exception as e:
            logger.debug(f"Power plan change failed: {e}")
            return False

    def _apply_game_mode(self, enabled: bool) -> bool:
        """Toggle Windows Game Mode."""
        try:
            from app.utils.registry import write_registry_value
            write_registry_value(
                "HKCU",
                r"Software\Microsoft\GameBar",
                "AutoGameModeEnabled",
                1 if enabled else 0,
            )
            return True
        except Exception as e:
            logger.debug(f"Game mode change failed: {e}")
            return False

    def _apply_memory_analysis(self) -> bool:
        """Run memory analysis (diagnostic only, no modification)."""
        try:
            from app.system.process_intelligence import process_intelligence
            process_intelligence.scan()
            return True
        except Exception as e:
            logger.debug(f"Memory analysis failed: {e}")
            return False

    def _reduce_background_cpu(self) -> bool:
        """Recommend reducing background CPU (diagnostic only)."""
        # This is a recommendation-only action — report findings
        try:
            from app.system.process_intelligence import process_intelligence
            scan = process_intelligence.scan()
            if scan and scan.total_background_cpu > 30:
                logger.info(
                    f"Background CPU: {scan.total_background_cpu:.0f}% — "
                    f"review recommended"
                )
            return True
        except Exception as e:
            logger.debug(f"Background CPU analysis failed: {e}")
            return False

    # ══════════════════════════════════════════════════════════════
    #  STEP 6: MONITOR
    # ══════════════════════════════════════════════════════════════

    def _start_monitoring(self):
        """Start background monitoring worker."""
        if self._worker_running:
            return

        self._worker_running = True
        self._monitoring_active = True
        self._worker_thread = threading.Thread(
            target=self._monitor_loop,
            daemon=True,
            name="lifecycle_monitor",
        )
        self._worker_thread.start()
        logger.info("Monitoring worker started")

    def _monitor_loop(self):
        """Background monitoring loop."""
        session = self._session
        if not session:
            return

        tick_count = 0
        while self._monitoring_active and self._worker_running:
            try:
                # Check if target is still alive
                if session.target_pid and not self._check_target_alive(session.target_pid):
                    logger.info(f"Target PID {session.target_pid} no longer running")
                    self._on_target_lost()
                    return

                # Periodic validation
                if tick_count > 0 and tick_count % 30 == 0:
                    self._validate(session)

                tick_count += 1
            except Exception as e:
                logger.debug(f"Monitor tick error: {e}")

            time.sleep(1.0)

    def _check_target_alive(self, pid: int) -> bool:
        """Check if target process is still running."""
        try:
            import psutil
            proc = psutil.Process(pid)
            return proc.is_running()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    def _on_target_lost(self):
        """Handle target process ending."""
        self._monitoring_active = False
        self._worker_running = False

        session = self._session
        if session:
            logger.info("Target lost — initiating graceful shutdown")
            self._stop_lifecycle()

    # ══════════════════════════════════════════════════════════════
    #  STEP 7: VALIDATE
    # ══════════════════════════════════════════════════════════════

    def _validate(self, session: LifecycleSession):
        """Validate current state against baseline."""
        if not session.baseline:
            return

        try:
            import psutil
            current_cpu = psutil.cpu_percent(interval=0.1)
            current_vm = psutil.virtual_memory()

            # Simple validation: check for degradation
            issues = []
            if session.baseline.cpu_percent and current_cpu:
                delta = current_cpu - session.baseline.cpu_percent
                if delta > 20:
                    issues.append(f"CPU increased by {delta:.0f}%")

            if session.baseline.ram_percent and current_vm.percent:
                delta = current_vm.percent - session.baseline.ram_percent
                if delta > 10:
                    issues.append(f"RAM increased by {delta:.0f}%")

            if issues:
                logger.warning(f"Validation issues: {', '.join(issues)}")
                if session.report:
                    session.report.validation_passed = False
                    session.report.validation_details = "; ".join(issues)
            else:
                if session.report:
                    session.report.validation_passed = True
                    session.report.validation_details = "No degradation detected"

        except Exception as e:
            logger.debug(f"Validation error: {e}")

    # ══════════════════════════════════════════════════════════════
    #  STEP 8: STOP
    # ══════════════════════════════════════════════════════════════

    def stop(self) -> Optional[SessionReport]:
        """Stop the gaming lifecycle and generate a report."""
        return self._stop_lifecycle()

    def _stop_lifecycle(self) -> Optional[SessionReport]:
        """Internal stop logic."""
        session = self._session
        if not session:
            return None

        # Stop monitoring
        self._monitoring_active = False
        self._worker_running = False
        if self._worker_thread and self._worker_thread.is_alive():
            self._worker_thread.join(timeout=5.0)

        self._set_state(session, LifecycleState.STOPPING)

        # Capture final state
        final = self._capture_final_state(session)

        # Restore temporary changes
        self._restore_temporary(session)

        # Generate report
        self._set_state(session, LifecycleState.REPORTING)
        report = self._generate_report(session, final)
        session.report = report

        # Save
        self._set_state(session, LifecycleState.COMPLETED)
        session.ended_at = datetime.now().isoformat()
        try:
            start = datetime.fromisoformat(session.started_at)
            end = datetime.fromisoformat(session.ended_at)
            session.duration_seconds = (end - start).total_seconds()
        except Exception:
            pass

        self._save_session(session)
        self._session = None
        logger.info(f"Lifecycle completed: {report.session_id}")

        return report

    # ══════════════════════════════════════════════════════════════
    #  STEP 9: RESTORE
    # ══════════════════════════════════════════════════════════════

    def _restore_temporary(self, session: LifecycleSession):
        """Restore only TEMPORARY changes from this session."""
        self._set_state(session, LifecycleState.RESTORING)

        for change in session.changes:
            if change.change_type != ChangeType.TEMPORARY:
                # Permanent changes are NOT restored
                change.status = ChangeStatus.KEPT
                logger.info(f"Keeping permanent change: {change.name}")
                continue

            if change.status not in (ChangeStatus.APPLIED, ChangeStatus.VERIFIED):
                continue

            if not change.reversible:
                change.status = ChangeStatus.IRREVERSIBLE
                logger.warning(f"Irreversible change: {change.name}")
                continue

            try:
                success = self._restore_single(change)
                if success:
                    change.status = ChangeStatus.RESTORED
                    session.changes_restored += 1
                    logger.info(f"Restored: {change.name}")
                else:
                    change.status = ChangeStatus.RESTORE_FAILED
                    session.changes_failed += 1
                    logger.warning(f"Restore failed: {change.name}")
            except Exception as e:
                change.status = ChangeStatus.RESTORE_FAILED
                session.changes_failed += 1
                logger.error(f"Restore error for {change.name}: {e}")

        # Count stats
        session.changes_applied = sum(
            1 for c in session.changes
            if c.status in (ChangeStatus.APPLIED, ChangeStatus.VERIFIED,
                            ChangeStatus.RESTORED, ChangeStatus.KEPT)
        )
        session.changes_kept = sum(
            1 for c in session.changes if c.status == ChangeStatus.KEPT
        )

    def _restore_single(self, change: LifecycleChange) -> bool:
        """Restore a single change."""
        rollback_data = change.rollback_data
        category = change.category

        if category == "power":
            plan = rollback_data.get("previous_plan", "")
            if plan:
                return self._apply_power_plan(plan.lower().replace(" ", "_"))

        elif category == "game_mode":
            previous = rollback_data.get("previous_enabled", True)
            return self._apply_game_mode(previous)

        elif category == "background":
            # Background CPU restoration is not directly possible
            # Just mark as restored (the processes may have ended)
            return True

        logger.debug(f"No restore handler for category: {category}")
        return False

    # ══════════════════════════════════════════════════════════════
    #  STEP 10: FINAL STATE & REPORT
    # ══════════════════════════════════════════════════════════════

    def _capture_final_state(self, session: LifecycleSession) -> LifecycleBaseline:
        """Capture final system state for comparison."""
        final = LifecycleBaseline(
            timestamp=time.time(),
            target_name=session.target_name,
            target_pid=session.target_pid,
        )

        try:
            import psutil
            final.cpu_percent = psutil.cpu_percent(interval=0.5)
            vm = psutil.virtual_memory()
            final.ram_percent = vm.percent
            final.ram_available_gb = vm.available / (1024 ** 3)
        except Exception:
            pass

        try:
            import psutil
            disk = psutil.disk_usage("C:\\")
            final.disk_free_gb = disk.free / (1024 ** 3)
        except Exception:
            pass

        try:
            from app.system.gpu import gpu_monitor
            gpu = gpu_monitor.detect()
            if gpu and gpu.utilization is not None:
                final.gpu_percent = float(gpu.utilization)
            if hasattr(gpu, "temperature") and gpu.temperature is not None:
                final.gpu_temp = float(gpu.temperature)
        except Exception:
            pass

        return final

    def _generate_report(
        self,
        session: LifecycleSession,
        final: LifecycleBaseline,
    ) -> SessionReport:
        """Generate the complete session report."""
        report = SessionReport(
            session_id=session.session_id,
            target_name=session.target_name,
            target_pid=session.target_pid,
            profile_id=session.profile_id,
            started_at=session.started_at,
            ended_at=datetime.now().isoformat(),
            baseline=session.baseline,
            final=final,
        )

        # Count changes by type
        for change in session.changes:
            change_dict = change.to_dict()
            report.changes.append(change_dict)

            if change.change_type == ChangeType.TEMPORARY:
                report.temporary_changes.append(change_dict)
            else:
                report.permanent_changes.append(change_dict)

            if change.status in (ChangeStatus.APPLIED, ChangeStatus.VERIFIED):
                report.changes_applied += 1
            elif change.status == ChangeStatus.RESTORED:
                report.changes_restored += 1
            elif change.status == ChangeStatus.KEPT:
                report.changes_kept += 1
            elif change.status in (ChangeStatus.FAILED, ChangeStatus.RESTORE_FAILED):
                report.changes_failed += 1

        # Recommendations
        report.recommendations_total = len(session.recommendations)
        report.recommendations_approved = len(
            [r for r in session.recommendations if r.approved]
        )
        report.recommendations_auto_applied = len(
            [r for r in session.recommendations if r.auto_apply]
        )

        # Validation
        report.validation_performed = True
        if session.baseline and final:
            diffs = session.baseline.diff(final)
            # Determine if changes were beneficial
            improvements = []
            degradations = []
            for key, delta in diffs.items():
                if delta is None:
                    continue
                if key == "fps" and delta > 0:
                    improvements.append(f"FPS +{delta:.0f}")
                elif key == "fps" and delta < 0:
                    degradations.append(f"FPS {delta:.0f}")
                elif key == "cpu_percent" and delta < -5:
                    improvements.append(f"CPU {delta:.0f}%")
                elif key == "cpu_percent" and delta > 10:
                    degradations.append(f"CPU +{delta:.0f}%")
                elif key == "ram_percent" and delta < -5:
                    improvements.append(f"RAM {delta:.0f}%")
                elif key == "ram_percent" and delta > 10:
                    degradations.append(f"RAM +{delta:.0f}%")

            if improvements:
                report.validation_passed = True
                report.validation_details = f"Improvements: {', '.join(improvements)}"
            elif degradations:
                report.validation_passed = False
                report.validation_details = f"Degradations: {', '.join(degradations)}"
            else:
                report.validation_passed = True
                report.validation_details = "No significant changes detected"

        # Summary
        parts = []
        if report.changes_applied:
            parts.append(f"{report.changes_applied} changes applied")
        if report.changes_restored:
            parts.append(f"{report.changes_restored} temporary changes restored")
        if report.changes_kept:
            parts.append(f"{report.changes_kept} permanent changes kept")
        if report.changes_failed:
            parts.append(f"{report.changes_failed} changes failed")
        if report.validation_passed:
            parts.append("Validation: PASSED")
        else:
            parts.append("Validation: ISSUES DETECTED")

        report.summary = "; ".join(parts) if parts else "Session completed with no changes"

        return report

    # ══════════════════════════════════════════════════════════════
    #  PERSISTENCE
    # ══════════════════════════════════════════════════════════════

    def _save_session(self, session: LifecycleSession):
        """Persist session to disk."""
        try:
            os.makedirs(SESSIONS_DIR, exist_ok=True)
            filepath = os.path.join(SESSIONS_DIR, f"{session.session_id}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(session.to_dict(), f, indent=2, default=str)
        except Exception as e:
            logger.debug(f"Failed to save session: {e}")

    def load_history(self, count: int = 10) -> List[Dict]:
        """Load recent session history."""
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

    # ══════════════════════════════════════════════════════════════
    #  CLI FORMAT
    # ══════════════════════════════════════════════════════════════

    def format_status(self) -> str:
        """Format current lifecycle status for CLI."""
        lines = []
        w = 60
        lines.append("=" * w)
        lines.append("  GAMING LIFECYCLE STATUS")
        lines.append("=" * w)
        lines.append("")

        if not self._session:
            lines.append("  State: IDLE")
            lines.append("  No active lifecycle.")
            lines.append("")
            lines.append("=" * w)
            return "\n".join(lines)

        s = self._session
        lines.append(f"  Session:  {s.session_id}")
        lines.append(f"  State:    {s.state}")
        lines.append(f"  Target:   {s.target_name} (PID {s.target_pid})")
        lines.append(f"  Profile:  {s.profile_id}")
        lines.append(f"  Started:  {s.started_at}")

        if s.baseline:
            lines.append("")
            lines.append("  BASELINE")
            lines.append("  " + "-" * (w - 4))
            b = s.baseline
            if b.cpu_percent is not None:
                lines.append(f"    CPU:      {b.cpu_percent:.1f}%")
            if b.gpu_percent is not None:
                lines.append(f"    GPU:      {b.gpu_percent:.1f}%")
            if b.gpu_temp is not None:
                lines.append(f"    GPU Temp: {b.gpu_temp:.0f}°C")
            if b.ram_percent is not None:
                lines.append(f"    RAM:      {b.ram_percent:.1f}%")
            if b.fps is not None:
                lines.append(f"    FPS:      {b.fps:.1f}")

        # Changes
        applied = sum(1 for c in s.changes if c.status in (ChangeStatus.APPLIED, ChangeStatus.VERIFIED))
        temp = sum(1 for c in s.changes if c.change_type == ChangeType.TEMPORARY)
        perm = sum(1 for c in s.changes if c.change_type == ChangeType.PERMANENT)
        lines.append("")
        lines.append(f"  CHANGES:  {applied} applied ({temp} temporary, {perm} permanent)")

        # Pending approval
        if self._pending_approval:
            lines.append("")
            lines.append(f"  AWAITING APPROVAL: {len(self._pending_approval)} recommendations")
            for rec in self._pending_approval:
                lines.append(f"    - [{rec.change_type.value}] {rec.title}")

        lines.append("")
        lines.append("=" * w)
        return "\n".join(lines)


# ── Singleton ────────────────────────────────────────────────────

gaming_lifecycle = GamingLifecycleManager()
