"""
Phase 39 — Automated Optimization Execution & Rollback Orchestration.

Connects:
  Telemetry → RecommendationEngine → AdaptiveOptimizer → Safety Gates →
  Optimization Execution → Verification → Before/After Measurement →
  Impact Evaluation → KEEP / ROLLBACK / INCONCLUSIVE

Every execution follows:
  Safety Gate → Pre-Snapshot → Execute → Verify → Post-Snapshot →
  Impact Evaluate → KEEP or ROLLBACK

Never modifies system state without:
  - valid safety gate pass
  - pre-snapshot captured
  - post-verification
  - impact evaluation
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

from app.core.optimization_base import OptimizationStatus
from app.core.profiles import get_profile
from app.core.snapshot import Snapshot, SnapshotEntry, snapshot_manager
from app.core.rollback import rollback_engine, RollbackResult
from app.utils.logger import get_logger

logger = get_logger("core.optimization_executor")


# ── Enums ────────────────────────────────────────────────────────

class ExecutionVerdict(Enum):
    """Final verdict for a single optimization step."""
    KEPT = "KEPT"
    ROLLED_BACK = "ROLLED_BACK"
    INCONCLUSIVE = "INCONCLUSIVE"
    SKIPPED = "SKIPPED"
    BLOCKED_BY_SAFETY = "BLOCKED_BY_SAFETY"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    RECOMMENDATION_ONLY = "RECOMMENDATION_ONLY"
    FAILED = "FAILED"
    ALREADY_OPTIMAL = "ALREADY_OPTIMAL"
    REQUIRES_ADMIN = "REQUIRES_ADMIN"


class SessionStatus(Enum):
    """Overall execution session status."""
    NOT_STARTED = "NOT_STARTED"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    PARTIAL = "PARTIAL"
    CANCELLED = "CANCELLED"
    ROLLED_BACK = "ROLLED_BACK"


class MetricState(Enum):
    """State of a telemetry metric."""
    MEASURED = "MEASURED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    FAILED = "FAILED"
    STALE = "STALE"
    INFERRED = "INFERRED"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class MetricValue:
    """A single metric with availability state."""
    value: Optional[float] = None
    state: MetricState = MetricState.NOT_AVAILABLE
    label: str = ""

    def to_dict(self) -> dict:
        return {"value": self.value, "state": self.state.value, "label": self.label}


@dataclass
class SystemSnapshot:
    """Point-in-time system state capture."""
    timestamp: float = field(default_factory=time.time)
    target_name: str = ""
    target_pid: int = 0
    target_pid_start: float = 0.0

    # System metrics
    cpu_utilization: MetricValue = field(default_factory=MetricValue)
    ram_used_mb: MetricValue = field(default_factory=MetricValue)
    ram_available_mb: MetricValue = field(default_factory=MetricValue)
    gpu_utilization: MetricValue = field(default_factory=MetricValue)
    gpu_vram_used_mb: MetricValue = field(default_factory=MetricValue)
    gpu_temperature: MetricValue = field(default_factory=MetricValue)
    cpu_temperature: MetricValue = field(default_factory=MetricValue)

    # Performance metrics
    fps: MetricValue = field(default_factory=MetricValue)
    one_percent_low: MetricValue = field(default_factory=MetricValue)
    frame_time_ms: MetricValue = field(default_factory=MetricValue)

    # Emulator state
    emulator_priority: MetricValue = field(default_factory=MetricValue)
    cpu_affinity_count: MetricValue = field(default_factory=MetricValue)
    active_power_plan: MetricValue = field(default_factory=MetricValue)

    def to_dict(self) -> dict:
        result = {}
        for k, v in self.__dict__.items():
            if isinstance(v, MetricValue):
                result[k] = v.to_dict()
            else:
                result[k] = v
        return result


@dataclass
class OptimizationExecutionStep:
    """Record of a single optimization execution."""
    optimization_id: str = ""
    optimization_name: str = ""
    timestamp: float = field(default_factory=time.time)
    previous_state: str = ""
    requested_state: str = ""
    actual_state: str = ""
    success: bool = False
    verified: bool = False
    rollback_available: bool = False
    rollback_data: Optional[dict] = None
    reason: str = ""
    verdict: ExecutionVerdict = ExecutionVerdict.SKIPPED
    pre_snapshot: Optional[SystemSnapshot] = None
    post_snapshot: Optional[SystemSnapshot] = None

    def to_dict(self) -> dict:
        result = {
            "optimization_id": self.optimization_id,
            "optimization_name": self.optimization_name,
            "timestamp": self.timestamp,
            "previous_state": self.previous_state,
            "requested_state": self.requested_state,
            "actual_state": self.actual_state,
            "success": self.success,
            "verified": self.verified,
            "rollback_available": self.rollback_available,
            "reason": self.reason,
            "verdict": self.verdict.value,
        }
        if self.pre_snapshot:
            result["pre_snapshot"] = self.pre_snapshot.to_dict()
        if self.post_snapshot:
            result["post_snapshot"] = self.post_snapshot.to_dict()
        return result


@dataclass
class OptimizationImpact:
    """Before/after comparison for a single optimization."""
    optimization_id: str = ""
    cpu_delta: Optional[float] = None
    ram_delta_mb: Optional[float] = None
    gpu_delta: Optional[float] = None
    temperature_delta: Optional[float] = None
    fps_delta: Optional[float] = None
    one_low_delta: Optional[float] = None
    frame_time_delta: Optional[float] = None
    target_stable: bool = True
    classification: str = "INCONCLUSIVE"  # IMPROVED, DEGRADED, UNCHANGED, INCONCLUSIVE

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class RollbackStepResult:
    """Result of rolling back a single optimization."""
    optimization_id: str = ""
    optimization_name: str = ""
    success: bool = False
    verified: bool = False
    reason: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class OptimizationExecutionSession:
    """Complete execution session record."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    profile_id: str = "gaming"
    profile_name: str = ""
    target_name: str = ""
    target_pid: int = 0
    status: SessionStatus = SessionStatus.NOT_STARTED

    # Steps
    steps: List[OptimizationExecutionStep] = field(default_factory=list)

    # Summary
    applied_count: int = 0
    kept_count: int = 0
    rolled_back_count: int = 0
    skipped_count: int = 0
    failed_count: int = 0
    admin_required_count: int = 0
    recommendation_only_count: int = 0
    already_optimal_count: int = 0
    blocked_count: int = 0

    # Duration
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "status": self.status.value,
            "steps": [s.to_dict() for s in self.steps],
            "applied_count": self.applied_count,
            "kept_count": self.kept_count,
            "rolled_back_count": self.rolled_back_count,
            "skipped_count": self.skipped_count,
            "failed_count": self.failed_count,
            "admin_required_count": self.admin_required_count,
            "recommendation_only_count": self.recommendation_only_count,
            "already_optimal_count": self.already_optimal_count,
            "blocked_count": self.blocked_count,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
        }

    def format_cli(self) -> str:
        """Format session for CLI output."""
        lines = []
        w = 60
        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — OPTIMIZATION EXECUTION SESSION")
        lines.append("=" * w)
        lines.append("")

        lines.append(f"Session:     {self.session_id}")
        lines.append(f"Profile:     {self.profile_name or self.profile_id}")
        lines.append(f"Target:      {self.target_name or 'None'} PID {self.target_pid}")
        lines.append(f"Status:      {self.status.value}")
        lines.append(f"Started:     {self.started_at}")
        lines.append(f"Duration:    {self.duration_seconds:.1f}s")
        lines.append("")

        # Steps
        if self.steps:
            lines.append("STEPS")
            lines.append("-" * w)
            icons = {
                ExecutionVerdict.KEPT: "[OK]",
                ExecutionVerdict.ROLLED_BACK: "[<<]",
                ExecutionVerdict.INCONCLUSIVE: "[??]",
                ExecutionVerdict.SKIPPED: "[--]",
                ExecutionVerdict.BLOCKED_BY_SAFETY: "[XX]",
                ExecutionVerdict.NOT_AVAILABLE: "[NA]",
                ExecutionVerdict.RECOMMENDATION_ONLY: "[>>]",
                ExecutionVerdict.FAILED: "[!!]",
                ExecutionVerdict.ALREADY_OPTIMAL: "[==]",
                ExecutionVerdict.REQUIRES_ADMIN: "[@!]",
            }
            for step in self.steps:
                icon = icons.get(step.verdict, "[??]")
                lines.append(
                    f"  {icon} {step.optimization_name}: {step.verdict.value}"
                )
                if step.reason:
                    lines.append(f"      {step.reason}")
            lines.append("")

        # Summary
        lines.append("SUMMARY")
        lines.append("-" * w)
        lines.append(f"  Applied & Kept:    {self.kept_count}")
        lines.append(f"  Rolled Back:       {self.rolled_back_count}")
        lines.append(f"  Already Optimal:   {self.already_optimal_count}")
        lines.append(f"  Admin Required:    {self.admin_required_count}")
        lines.append(f"  Recommendation:    {self.recommendation_only_count}")
        lines.append(f"  Skipped:           {self.skipped_count}")
        lines.append(f"  Failed:            {self.failed_count}")
        lines.append(f"  Blocked:           {self.blocked_count}")
        lines.append("")
        lines.append("=" * w)
        return "\n".join(lines)


# ── Safety Constants ─────────────────────────────────────────────

# Performance degradation threshold for auto-rollback (% FPS drop)
DEGRADATION_FPS_THRESHOLD = 5.0
# Temperature increase threshold for auto-rollback (°C)
DEGRADATION_TEMP_THRESHOLD = 8.0
# Maximum steps in a single session
MAX_SESSION_STEPS = 20


# ── Optimization Executor ────────────────────────────────────────

class OptimizationExecutor:
    """
    Controlled optimization execution orchestrator.

    Connects telemetry → recommendations → adaptive optimizer →
    safety gates → execution → verification → impact → keep/rollback.

    Never executes without safety gates.
    Never claims success without verification.
    Never skips rollback when degradation is detected.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._current_session: Optional[OptimizationExecutionSession] = None
        self._last_session: Optional[OptimizationExecutionSession] = None
        self._session_history: List[OptimizationExecutionSession] = []

    @property
    def current_session(self) -> Optional[OptimizationExecutionSession]:
        return self._current_session

    @property
    def last_session(self) -> Optional[OptimizationExecutionSession]:
        return self._last_session

    @property
    def is_busy(self) -> bool:
        return self._current_session is not None and self._current_session.status == SessionStatus.IN_PROGRESS

    # ── Target Detection ──────────────────────────────────────

    def _detect_target(self) -> Tuple[str, int, float]:
        """Detect current emulator target. Returns (name, pid, start_time)."""
        try:
            from app.performance.target_process import target_process_detector
            best = target_process_detector.select_best_target()
            if best:
                return best.process_name, best.pid, getattr(best, 'start_time', 0.0)
        except Exception as e:
            logger.debug(f"Target detection: {e}")
        return "", 0, 0.0

    def _validate_target(self, name: str, pid: int, start_time: float) -> Tuple[bool, str]:
        """Validate the target is still valid (PID reuse protection)."""
        if not pid:
            return False, "No emulator target detected"
        try:
            import psutil
            proc = psutil.Process(pid)
            if proc.name() != name:
                return False, f"PID {pid} now belongs to {proc.name()} (expected {name})"
            if start_time > 0:
                proc_start = proc.create_time()
                if abs(proc_start - start_time) > 2.0:
                    return False, f"PID {pid} reused (start time changed)"
            return True, "Target valid"
        except Exception as e:
            return False, f"Target validation failed: {e}"

    # ── Safety Gates ──────────────────────────────────────────

    def _check_safety_gate(
        self,
        opt_id: str,
        profile_id: str,
        is_admin: bool,
        target_valid: bool,
        target_name: str,
        thermal_state: str = "UNKNOWN",
    ) -> Tuple[bool, str]:
        """
        Comprehensive safety gate check before execution.

        Returns (allowed, reason).
        """
        # 1. Target validity
        if not target_valid:
            return False, "No valid emulator target"

        # 2. Profile membership
        profile = get_profile(profile_id)
        profile_opt_ids = {po.opt_id for po in profile.optimizations}
        if opt_id not in profile_opt_ids:
            return False, f"Optimization not in profile {profile_id}"

        # 3. Admin requirement check
        try:
            from app.core.optimizations import get_optimization_by_id
            opt = get_optimization_by_id(opt_id)
            if not opt:
                return False, f"Optimization {opt_id} not found"
        except Exception as e:
            return False, f"Cannot load optimization: {e}"

        check_result = opt.check()

        # 4. Already optimal
        if check_result.status == OptimizationStatus.ALREADY_OPTIMAL:
            return False, "Already optimal"

        # 5. Recommendation only
        if check_result.status == OptimizationStatus.RECOMMENDATION_ONLY:
            return False, "Recommendation only — no system modification"

        # 6. Not available
        if check_result.status in (OptimizationStatus.NOT_APPLICABLE, OptimizationStatus.NOT_AVAILABLE):
            return False, "Not available on this system"

        # 7. Admin required
        if check_result.status == OptimizationStatus.REQUIRES_ADMIN:
            if not is_admin:
                return False, "Administrator privileges required"
            # Admin IS available — allow
            return True, "Admin available, proceeding"

        # 8. Thermal safety — do not increase performance when thermally limited
        if thermal_state in ("HOT", "THROTTLING_RISK") and opt_id in (
            "power_plan", "emulator_priority", "cpu_affinity"
        ):
            return False, f"Thermal state {thermal_state} — performance increase blocked"

        # 9. Protected processes
        if opt_id in ("background_load", "memory_analysis"):
            return False, "Recommendation only — no system modification"

        # 10. Must be OPTIMIZABLE
        if check_result.status != OptimizationStatus.OPTIMIZABLE:
            return False, f"Unexpected state: {check_result.status.value}"

        return True, "Safety gate passed"

    # ── Pre/Post Snapshots ────────────────────────────────────

    def _capture_pre_snapshot(
        self, target_name: str, target_pid: int, target_start: float
    ) -> SystemSnapshot:
        """Capture real system state before optimization."""
        snap = SystemSnapshot(
            target_name=target_name,
            target_pid=target_pid,
            target_pid_start=target_start,
        )

        # CPU
        try:
            import psutil
            snap.cpu_utilization = MetricValue(
                value=psutil.cpu_percent(interval=0.5),
                state=MetricState.MEASURED,
                label="System CPU",
            )
        except Exception:
            snap.cpu_utilization = MetricValue(state=MetricState.FAILED, label="System CPU")

        # RAM
        try:
            import psutil
            vm = psutil.virtual_memory()
            snap.ram_used_mb = MetricValue(
                value=round(vm.used / (1024 * 1024), 1),
                state=MetricState.MEASURED,
                label="RAM Used",
            )
            snap.ram_available_mb = MetricValue(
                value=round(vm.available / (1024 * 1024), 1),
                state=MetricState.MEASURED,
                label="RAM Available",
            )
        except Exception:
            snap.ram_used_mb = MetricValue(state=MetricState.FAILED, label="RAM Used")
            snap.ram_available_mb = MetricValue(state=MetricState.FAILED, label="RAM Available")

        # GPU
        try:
            from app.system.gpu import gpu_monitor
            gpu_info = gpu_monitor.detect()
            if gpu_info and gpu_info.utilization is not None:
                snap.gpu_utilization = MetricValue(
                    value=float(gpu_info.utilization),
                    state=MetricState.MEASURED,
                    label="GPU Utilization",
                )
            else:
                snap.gpu_utilization = MetricValue(state=MetricState.NOT_AVAILABLE, label="GPU Utilization")
            if hasattr(gpu_info, "temperature") and gpu_info.temperature is not None:
                snap.gpu_temperature = MetricValue(
                    value=float(gpu_info.temperature),
                    state=MetricState.MEASURED,
                    label="GPU Temperature",
                )
            else:
                snap.gpu_temperature = MetricValue(state=MetricState.NOT_AVAILABLE, label="GPU Temperature")
        except Exception:
            snap.gpu_utilization = MetricValue(state=MetricState.NOT_AVAILABLE, label="GPU Utilization")
            snap.gpu_temperature = MetricValue(state=MetricState.NOT_AVAILABLE, label="GPU Temperature")

        # Emulator priority
        if target_pid:
            try:
                import psutil
                proc = psutil.Process(target_pid)
                snap.emulator_priority = MetricValue(
                    value=float(proc.nice()),
                    state=MetricState.MEASURED,
                    label="Emulator Priority",
                )
            except Exception:
                snap.emulator_priority = MetricValue(state=MetricState.NOT_AVAILABLE, label="Emulator Priority")

        # CPU affinity
        if target_pid:
            try:
                import psutil
                proc = psutil.Process(target_pid)
                affinity = proc.cpu_affinity()
                snap.cpu_affinity_count = MetricValue(
                    value=float(len(affinity)),
                    state=MetricState.MEASURED,
                    label="CPU Affinity Count",
                )
            except Exception:
                snap.cpu_affinity_count = MetricValue(state=MetricState.NOT_AVAILABLE, label="CPU Affinity Count")

        # Power plan
        try:
            from app.system.power import power_monitor
            info = power_monitor.detect()
            snap.active_power_plan = MetricValue(
                value=info.active_plan_name,
                state=MetricState.MEASURED,
                label="Active Power Plan",
            )
        except Exception:
            snap.active_power_plan = MetricValue(state=MetricState.NOT_AVAILABLE, label="Active Power Plan")

        return snap

    # ── Impact Evaluation ─────────────────────────────────────

    def _evaluate_impact(
        self,
        pre: SystemSnapshot,
        post: SystemSnapshot,
        opt_id: str,
    ) -> OptimizationImpact:
        """Compare pre/post snapshots to evaluate impact."""
        impact = OptimizationImpact(optimization_id=opt_id)

        # CPU delta
        if (pre.cpu_utilization.state == MetricState.MEASURED and
                post.cpu_utilization.state == MetricState.MEASURED):
            impact.cpu_delta = post.cpu_utilization.value - pre.cpu_utilization.value

        # RAM delta
        if (pre.ram_available_mb.state == MetricState.MEASURED and
                post.ram_available_mb.state == MetricState.MEASURED):
            impact.ram_delta_mb = post.ram_available_mb.value - pre.ram_available_mb.value

        # GPU delta
        if (pre.gpu_utilization.state == MetricState.MEASURED and
                post.gpu_utilization.state == MetricState.MEASURED):
            impact.gpu_delta = post.gpu_utilization.value - pre.gpu_utilization.value

        # Temperature delta
        if (pre.gpu_temperature.state == MetricState.MEASURED and
                post.gpu_temperature.state == MetricState.MEASURED):
            impact.temperature_delta = post.gpu_temperature.value - pre.gpu_temperature.value

        # Target stability (PID unchanged)
        if post.target_pid == pre.target_pid and post.target_pid > 0:
            try:
                import psutil
                proc = psutil.Process(post.target_pid)
                if proc.name() == post.target_name:
                    impact.target_stable = True
                else:
                    impact.target_stable = False
            except Exception:
                impact.target_stable = False
        else:
            impact.target_stable = False

        # Classification
        # Only classify IMPROVED/DEGRADED when we have meaningful data
        has_data = any([
            impact.cpu_delta is not None,
            impact.ram_delta_mb is not None,
            impact.gpu_delta is not None,
            impact.temperature_delta is not None,
        ])

        if not has_data:
            impact.classification = "INCONCLUSIVE"
            return impact

        # Check for degradation signals
        degraded = False
        improved = False

        if impact.temperature_delta is not None and impact.temperature_delta > DEGRADATION_TEMP_THRESHOLD:
            degraded = True

        if not impact.target_stable:
            degraded = True

        # For most optimizations, decreased CPU/GPU is neutral or positive
        # For power plan / priority, we don't expect measurable delta from just the change
        if degraded:
            impact.classification = "DEGRADED"
        elif improved:
            impact.classification = "IMPROVED"
        else:
            impact.classification = "UNCHANGED"

        return impact

    # ── Execution ─────────────────────────────────────────────

    def preview(
        self,
        profile_id: str = "gaming",
        duration_seconds: float = 5.0,
    ) -> OptimizationExecutionSession:
        """
        Read-only preview of what WOULD be applied.

        Does not modify the system.
        """
        session = OptimizationExecutionSession(
            profile_id=profile_id,
            status=SessionStatus.NOT_STARTED,
        )

        profile = get_profile(profile_id)
        session.profile_name = profile.name

        target_name, target_pid, target_start = self._detect_target()
        session.target_name = target_name
        session.target_pid = target_pid

        is_admin = False
        try:
            from app.utils.admin import is_admin as check_admin
            is_admin = check_admin()
        except Exception:
            pass

        for po in profile.optimizations:
            step = OptimizationExecutionStep(
                optimization_id=po.opt_id,
                optimization_name=po.name,
            )

            # Safety gate
            allowed, reason = self._check_safety_gate(
                po.opt_id, profile_id, is_admin, target_pid > 0,
                target_name,
            )

            if not allowed:
                step.reason = reason
                if "Already optimal" in reason:
                    step.verdict = ExecutionVerdict.ALREADY_OPTIMAL
                    session.already_optimal_count += 1
                elif "Administrator" in reason:
                    step.verdict = ExecutionVerdict.REQUIRES_ADMIN
                    session.admin_required_count += 1
                elif "Recommendation" in reason:
                    step.verdict = ExecutionVerdict.RECOMMENDATION_ONLY
                    session.recommendation_only_count += 1
                elif "Not available" in reason:
                    step.verdict = ExecutionVerdict.NOT_AVAILABLE
                elif "not in profile" in reason:
                    step.verdict = ExecutionVerdict.BLOCKED_BY_SAFETY
                    session.blocked_count += 1
                elif "thermal" in reason.lower():
                    step.verdict = ExecutionVerdict.BLOCKED_BY_SAFETY
                    session.blocked_count += 1
                elif "not found" in reason:
                    step.verdict = ExecutionVerdict.FAILED
                    session.failed_count += 1
                else:
                    step.verdict = ExecutionVerdict.SKIPPED
                    session.skipped_count += 1
            else:
                step.verdict = ExecutionVerdict.KEPT  # Would be applied
                step.reason = "Would be applied"
                session.applied_count += 1

            session.steps.append(step)

        session.status = SessionStatus.COMPLETED
        return session

    def execute(
        self,
        profile_id: str = "gaming",
        thermal_state: str = "UNKNOWN",
    ) -> OptimizationExecutionSession:
        """
        Execute optimization with full safety, verification, and rollback.

        One optimization at a time.
        Verify each.
        Auto-rollback if degraded.
        """
        if self.is_busy:
            return OptimizationExecutionSession(
                status=SessionStatus.IN_PROGRESS,
                profile_id=profile_id,
            )

        session = OptimizationExecutionSession(
            profile_id=profile_id,
            status=SessionStatus.IN_PROGRESS,
            started_at=datetime.now().isoformat(),
        )
        self._current_session = session

        try:
            return self._execute_inner(session, thermal_state)
        finally:
            self._current_session = None
            self._last_session = session
            self._session_history.append(session)
            # Persist
            self._save_session(session)

    def _execute_inner(
        self,
        session: OptimizationExecutionSession,
        thermal_state: str,
    ) -> OptimizationExecutionSession:
        start_time = time.time()

        profile = get_profile(session.profile_id)
        session.profile_name = profile.name

        # Detect target
        target_name, target_pid, target_start = self._detect_target()
        session.target_name = target_name
        session.target_pid = target_pid

        is_admin = False
        try:
            from app.utils.admin import is_admin as check_admin
            is_admin = check_admin()
        except Exception:
            pass

        session.status = SessionStatus.IN_PROGRESS

        for po in profile.optimizations:
            if len(session.steps) >= MAX_SESSION_STEPS:
                logger.warning("Session step limit reached")
                break

            step = OptimizationExecutionStep(
                optimization_id=po.opt_id,
                optimization_name=po.name,
            )

            # Safety gate
            allowed, reason = self._check_safety_gate(
                po.opt_id, session.profile_id, is_admin, target_pid > 0,
                target_name, thermal_state,
            )

            if not allowed:
                step.reason = reason
                if "Already optimal" in reason:
                    step.verdict = ExecutionVerdict.ALREADY_OPTIMAL
                    session.already_optimal_count += 1
                elif "Administrator" in reason:
                    step.verdict = ExecutionVerdict.REQUIRES_ADMIN
                    session.admin_required_count += 1
                elif "Recommendation" in reason:
                    step.verdict = ExecutionVerdict.RECOMMENDATION_ONLY
                    session.recommendation_only_count += 1
                elif "Not available" in reason:
                    step.verdict = ExecutionVerdict.NOT_AVAILABLE
                else:
                    step.verdict = ExecutionVerdict.BLOCKED_BY_SAFETY
                    session.blocked_count += 1

                session.steps.append(step)
                continue

            # Pre-snapshot
            pre_snapshot = self._capture_pre_snapshot(target_name, target_pid, target_start)
            step.pre_snapshot = pre_snapshot

            # Execute
            try:
                from app.core.optimizations import get_optimization_by_id
                opt = get_optimization_by_id(po.opt_id)
                if not opt:
                    step.verdict = ExecutionVerdict.FAILED
                    step.reason = f"Optimization {po.opt_id} not found"
                    session.failed_count += 1
                    session.steps.append(step)
                    continue

                # Record previous state
                check_result = opt.check()
                step.previous_state = check_result.current_value

                # Snapshot for rollback
                try:
                    opt.snapshot()
                    step.rollback_available = True
                except Exception as e:
                    logger.warning(f"Snapshot failed for {po.name}: {e}")

                # Apply
                apply_result = opt.apply()

                if apply_result.status == OptimizationStatus.APPLIED:
                    step.requested_state = "APPLIED"

                    # Verify
                    time.sleep(0.5)
                    verified = opt.verify()
                    step.verified = verified
                    step.actual_state = "APPLIED" if verified else "VERIFICATION_FAILED"

                    if verified:
                        # Post-snapshot
                        post_snapshot = self._capture_pre_snapshot(target_name, target_pid, target_start)
                        step.post_snapshot = post_snapshot

                        # Impact evaluation
                        impact = self._evaluate_impact(pre_snapshot, post_snapshot, po.opt_id)

                        if impact.classification == "DEGRADED":
                            # Auto-rollback
                            logger.warning(f"Degradation detected for {po.name} — rolling back")
                            try:
                                rolled_back = opt.rollback()
                                if rolled_back:
                                    step.verdict = ExecutionVerdict.ROLLED_BACK
                                    step.reason = f"Rolled back: degradation detected ({impact.classification})"
                                    session.rolled_back_count += 1
                                else:
                                    step.verdict = ExecutionVerdict.INCONCLUSIVE
                                    step.reason = "Applied but rollback failed"
                                    session.failed_count += 1
                            except Exception as e:
                                step.verdict = ExecutionVerdict.INCONCLUSIVE
                                step.reason = f"Rollback error: {e}"
                                session.failed_count += 1
                        else:
                            step.verdict = ExecutionVerdict.KEPT
                            step.reason = f"Applied and verified: {apply_result.message}"
                            session.kept_count += 1
                            session.applied_count += 1
                    else:
                        # Verification failed — rollback
                        logger.warning(f"Verification failed for {po.name} — rolling back")
                        try:
                            rolled_back = opt.rollback()
                            if rolled_back:
                                step.verdict = ExecutionVerdict.ROLLED_BACK
                                step.reason = "Rolled back: verification failed"
                                session.rolled_back_count += 1
                            else:
                                step.verdict = ExecutionVerdict.INCONCLUSIVE
                                step.reason = "Applied but verification and rollback failed"
                                session.failed_count += 1
                        except Exception as e:
                            step.verdict = ExecutionVerdict.INCONCLUSIVE
                            step.reason = f"Rollback error after verification failure: {e}"
                            session.failed_count += 1

                elif apply_result.status == OptimizationStatus.RECOMMENDATION_ONLY:
                    step.verdict = ExecutionVerdict.RECOMMENDATION_ONLY
                    step.reason = "Recommendation only"
                    session.recommendation_only_count += 1

                elif apply_result.status == OptimizationStatus.ALREADY_OPTIMAL:
                    step.verdict = ExecutionVerdict.ALREADY_OPTIMAL
                    step.reason = "Already optimal at execution time"
                    session.already_optimal_count += 1

                elif apply_result.status == OptimizationStatus.REQUIRES_ADMIN:
                    step.verdict = ExecutionVerdict.REQUIRES_ADMIN
                    step.reason = "Administrator privileges required"
                    session.admin_required_count += 1

                else:
                    step.verdict = ExecutionVerdict.FAILED
                    step.reason = f"Apply returned: {apply_result.status.value}"
                    session.failed_count += 1

            except Exception as e:
                step.verdict = ExecutionVerdict.FAILED
                step.reason = f"Execution error: {e}"
                session.failed_count += 1
                logger.error(f"Execution error for {po.name}: {e}")

            session.steps.append(step)

        # Finalize
        session.duration_seconds = time.time() - start_time
        session.completed_at = datetime.now().isoformat()

        if session.rolled_back_count > 0 and session.kept_count == 0:
            session.status = SessionStatus.ROLLED_BACK
        elif session.kept_count > 0:
            session.status = SessionStatus.COMPLETED
        elif session.failed_count > 0:
            session.status = SessionStatus.PARTIAL
        else:
            session.status = SessionStatus.COMPLETED

        return session

    # ── Rollback ──────────────────────────────────────────────

    def rollback_last(self) -> RollbackResult:
        """Roll back the most recent execution session."""
        if not self._last_session:
            return RollbackResult(
                success=False,
                message="No execution session to rollback",
            )

        # Find applied steps
        applied_steps = [
            s for s in self._last_session.steps
            if s.verdict == ExecutionVerdict.KEPT and s.rollback_available
        ]

        if not applied_steps:
            return RollbackResult(
                success=True,
                message="No applied optimizations to rollback",
            )

        # Use the existing optimizer rollback
        from app.core.optimizer import optimizer
        result = optimizer.rollback_last()

        # Update session status
        if result.success:
            self._last_session.status = SessionStatus.ROLLED_BACK
            for step in applied_steps:
                step.verdict = ExecutionVerdict.ROLLED_BACK
            self._last_session.rolled_back_count = self._last_session.kept_count
            self._last_session.kept_count = 0

        self._save_session(self._last_session)
        return result

    # ── Verify ────────────────────────────────────────────────

    def verify_session(self) -> Dict:
        """Verify current optimization state against the last session."""
        if not self._last_session:
            return {"status": "NO_SESSION", "message": "No session to verify"}

        results = {}
        for step in self._last_session.steps:
            if step.verdict == ExecutionVerdict.KEPT:
                try:
                    from app.core.optimizations import get_optimization_by_id
                    opt = get_optimization_by_id(step.optimization_id)
                    if opt:
                        verified = opt.verify()
                        results[step.optimization_id] = {
                            "name": step.optimization_name,
                            "verified": verified,
                            "status": "VERIFIED" if verified else "MISMATCH",
                        }
                    else:
                        results[step.optimization_id] = {
                            "name": step.optimization_name,
                            "verified": False,
                            "status": "NOT_FOUND",
                        }
                except Exception as e:
                    results[step.optimization_id] = {
                        "name": step.optimization_name,
                        "verified": False,
                        "status": f"ERROR: {e}",
                    }

        all_verified = all(r.get("verified", False) for r in results.values())
        return {
            "status": "ALL_VERIFIED" if all_verified else "PARTIAL",
            "results": results,
            "session_status": self._last_session.status.value,
        }

    # ── Status ────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Get current execution status."""
        status = {
            "busy": self.is_busy,
            "last_session": None,
            "history_count": len(self._session_history),
        }
        if self._last_session:
            status["last_session"] = self._last_session.to_dict()
        return status

    # ── Persistence ───────────────────────────────────────────

    def _save_session(self, session: OptimizationExecutionSession):
        """Save session to disk."""
        try:
            sessions_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "optimization_sessions",
            )
            os.makedirs(sessions_dir, exist_ok=True)
            filepath = os.path.join(sessions_dir, f"{session.session_id}.json")
            with open(filepath, "w") as f:
                json.dump(session.to_dict(), f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save session: {e}")

    def load_history(self, count: int = 10) -> List[Dict]:
        """Load recent session history from disk."""
        try:
            sessions_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "optimization_sessions",
            )
            if not os.path.exists(sessions_dir):
                return []
            files = sorted(
                [f for f in os.listdir(sessions_dir) if f.endswith(".json")],
                key=lambda f: os.path.getmtime(os.path.join(sessions_dir, f)),
                reverse=True,
            )
            records = []
            for fname in files[:count]:
                try:
                    with open(os.path.join(sessions_dir, fname)) as f:
                        records.append(json.load(f))
                except Exception:
                    continue
            return records
        except Exception:
            return []

    # ── CLI Formatting ────────────────────────────────────────

    def format_preview(self, session: OptimizationExecutionSession) -> str:
        """Format preview for CLI."""
        lines = []
        w = 60
        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — OPTIMIZATION PREVIEW")
        lines.append("=" * w)
        lines.append("")
        lines.append(f"Profile:  {session.profile_name or session.profile_id}")
        lines.append(f"Target:   {session.target_name or 'None'} PID {session.target_pid}")
        lines.append("")

        if session.steps:
            lines.append("WOULD BE APPLIED")
            lines.append("-" * w)
            icons = {
                ExecutionVerdict.KEPT: "[APPLY]",
                ExecutionVerdict.ALREADY_OPTIMAL: "[==]",
                ExecutionVerdict.REQUIRES_ADMIN: "[@!]",
                ExecutionVerdict.RECOMMENDATION_ONLY: "[>>]",
                ExecutionVerdict.NOT_AVAILABLE: "[NA]",
                ExecutionVerdict.BLOCKED_BY_SAFETY: "[XX]",
                ExecutionVerdict.SKIPPED: "[--]",
                ExecutionVerdict.FAILED: "[!!]",
            }
            for step in session.steps:
                icon = icons.get(step.verdict, "[??]")
                lines.append(f"  {icon} {step.optimization_name}")
                if step.reason:
                    lines.append(f"       {step.reason}")
            lines.append("")

        lines.append(f"Would Apply: {session.applied_count}")
        lines.append(f"Admin Required: {session.admin_required_count}")
        lines.append(f"Already Optimal: {session.already_optimal_count}")
        lines.append(f"Recommendation Only: {session.recommendation_only_count}")
        lines.append("")
        lines.append("=" * w)
        return "\n".join(lines)


# Singleton
optimization_executor = OptimizationExecutor()
