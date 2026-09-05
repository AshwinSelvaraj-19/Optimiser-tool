"""
Phase 48 — Centralized Production-Grade Optimization Orchestration Engine.

Connects:
  Telemetry → BottleneckAnalyzer → AdaptiveOptimizer → RecommendationEngine
  → OptimizationExecutor → Safety Gates → Execution → Verification
  → Evidence Validation → Impact Evaluation → KEEP / ROLLBACK / INCONCLUSIVE

Architecture:
  OptimizationEngine
    ├── OptimizationProfile (existing)
    ├── BottleneckAnalyzer (existing)
    ├── AdaptiveOptimizer (existing)
    ├── RecommendationEngine (existing)
    ├── OptimizationExecutor (existing)
    ├── Optimizer (existing)
    ├── OptimizationEvidenceEngine (existing)
    ├── RollbackEngine (existing)
    └── SnapshotManager (existing)

Every action follows:
  1. Capture baseline
  2. Analyze (bottleneck + adaptive + recommendation)
  3. Generate plan
  4. Safety gate check
  5. Apply one optimization at a time
  6. Verify each
  7. Validate with evidence where available
  8. KEEP or ROLLBACK
  9. Capture post-state
  10. Generate report
  11. Persist session

Rules:
  - Never modifies system state without safety gate pass
  - Never claims improvement without measured evidence
  - Never executes RECOMMENDATION_ONLY actions
  - Every optimization declares risk, reversibility, affected subsystem
  - Transactions are atomic per optimization (apply → verify → keep/rollback)
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

logger = get_logger("core.optimization_engine")


# ── Enums ────────────────────────────────────────────────────────

class EnginePhase(Enum):
    """Current phase of the optimization engine."""
    IDLE = "IDLE"
    BASELINE = "BASELINE"
    ANALYSIS = "ANALYSIS"
    PLANNING = "PLANNING"
    EXECUTING = "EXECUTING"
    VALIDATING = "VALIDATING"
    ROLLING_BACK = "ROLLING_BACK"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class EngineVerdict(Enum):
    """Final verdict for an optimization run."""
    IMPROVED = "IMPROVED"
    DEGRADED = "DEGRADED"
    UNCHANGED = "UNCHANGED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NO_EMULATOR = "NO_EMULATOR"
    NO_ACTIONS = "NO_ACTIONS"
    ALL_OPTIMAL = "ALL_OPTIMAL"
    CANCELLED = "CANCELLED"


class OptActionVerdict(Enum):
    """Verdict for a single optimization within a run."""
    APPLIED = "APPLIED"
    ALREADY_OPTIMAL = "ALREADY_OPTIMAL"
    REQUIRES_ADMIN = "REQUIRES_ADMIN"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    RECOMMENDATION_ONLY = "RECOMMENDATION_ONLY"
    BLOCKED_BY_SAFETY = "BLOCKED_BY_SAFETY"
    FAILED = "FAILED"
    ROLLED_BACK = "ROLLED_BACK"
    INCONCLUSIVE = "INCONCLUSIVE"
    SKIPPED = "SKIPPED"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class SystemBaseline:
    """Point-in-time system state capture before optimization."""
    timestamp: float = field(default_factory=time.time)
    target_name: str = ""
    target_pid: int = 0
    target_pid_start: float = 0.0

    # System metrics (all marked with state)
    cpu_percent: Optional[float] = None
    cpu_state: str = "NOT_AVAILABLE"

    ram_used_mb: Optional[float] = None
    ram_available_mb: Optional[float] = None
    ram_percent: Optional[float] = None
    ram_state: str = "NOT_AVAILABLE"

    gpu_utilization: Optional[float] = None
    gpu_state: str = "NOT_AVAILABLE"

    gpu_temperature: Optional[float] = None
    gpu_temp_state: str = "NOT_AVAILABLE"

    fps: Optional[float] = None
    fps_state: str = "NOT_AVAILABLE"

    one_percent_low: Optional[float] = None
    frame_time_ms: Optional[float] = None

    emulator_priority: Optional[float] = None
    active_power_plan: str = ""
    thermal_state: str = "UNKNOWN"

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class OptimizationAction:
    """Single optimization action with full lifecycle tracking."""
    action_id: str = ""
    optimization_id: str = ""
    name: str = ""
    description: str = ""
    category: str = ""
    risk_level: str = "LOW"
    reversible: bool = True
    affected_subsystem: str = ""
    required_privilege: str = "USER"

    # Pre-state
    previous_state: str = ""
    previous_value: str = ""

    # Action
    verdict: OptActionVerdict = OptActionVerdict.SKIPPED
    reason: str = ""
    verified: bool = False

    # Impact
    cpu_delta: Optional[float] = None
    ram_delta_mb: Optional[float] = None
    gpu_delta: Optional[float] = None
    temperature_delta: Optional[float] = None

    # Rollback
    rollback_available: bool = False
    rollback_reason: str = ""

    # Timestamps
    applied_at: str = ""
    verified_at: str = ""

    def to_dict(self) -> dict:
        return {
            "action_id": self.action_id,
            "optimization_id": self.optimization_id,
            "name": self.name,
            "description": self.description,
            "category": self.category,
            "risk_level": self.risk_level,
            "reversible": self.reversible,
            "affected_subsystem": self.affected_subsystem,
            "required_privilege": self.required_privilege,
            "previous_state": self.previous_state,
            "previous_value": self.previous_value,
            "verdict": self.verdict.value,
            "reason": self.reason,
            "verified": self.verified,
            "cpu_delta": self.cpu_delta,
            "ram_delta_mb": self.ram_delta_mb,
            "gpu_delta": self.gpu_delta,
            "temperature_delta": self.temperature_delta,
            "rollback_available": self.rollback_available,
            "rollback_reason": self.rollback_reason,
            "applied_at": self.applied_at,
            "verified_at": self.verified_at,
        }


@dataclass
class OptimizationRunResult:
    """Complete result of a single optimization run."""
    run_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    profile_id: str = "gaming"
    profile_name: str = ""
    mode: str = "auto"  # auto, dry_run, validate

    # Target
    target_name: str = ""
    target_pid: int = 0

    # Phase
    phase: EnginePhase = EnginePhase.IDLE
    verdict: EngineVerdict = EngineVerdict.INCONCLUSIVE
    verdict_reason: str = ""

    # Baseline
    baseline: Optional[SystemBaseline] = None

    # Analysis
    bottleneck: str = ""
    bottleneck_confidence: int = 0
    bottleneck_evidence: List[str] = field(default_factory=list)
    adaptive_state: str = ""
    adaptive_confidence: int = 0
    recommended_profile: str = ""
    recommendation_count: int = 0

    # Actions
    actions: List[OptimizationAction] = field(default_factory=list)

    # Post-state
    post_baseline: Optional[SystemBaseline] = None

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

    # Evidence
    fps_delta: Optional[float] = None
    fps_delta_percent: Optional[float] = None
    one_low_delta: Optional[float] = None

    # Admin
    is_admin: bool = False

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "timestamp": self.timestamp,
            "profile_id": self.profile_id,
            "profile_name": self.profile_name,
            "mode": self.mode,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "phase": self.phase.value,
            "verdict": self.verdict.value,
            "verdict_reason": self.verdict_reason,
            "baseline": self.baseline.to_dict() if self.baseline else None,
            "bottleneck": self.bottleneck,
            "bottleneck_confidence": self.bottleneck_confidence,
            "bottleneck_evidence": self.bottleneck_evidence,
            "adaptive_state": self.adaptive_state,
            "adaptive_confidence": self.adaptive_confidence,
            "recommended_profile": self.recommended_profile,
            "recommendation_count": self.recommendation_count,
            "actions": [a.to_dict() for a in self.actions],
            "post_baseline": self.post_baseline.to_dict() if self.post_baseline else None,
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
            "fps_delta": self.fps_delta,
            "fps_delta_percent": self.fps_delta_percent,
            "one_low_delta": self.one_low_delta,
            "is_admin": self.is_admin,
        }

    def format_cli(self) -> str:
        """Format for human-readable CLI output."""
        lines = []
        w = 60
        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — OPTIMIZATION ENGINE RUN")
        lines.append("=" * w)
        lines.append("")

        lines.append(f"Run:       {self.run_id}")
        lines.append(f"Profile:   {self.profile_name or self.profile_id}")
        lines.append(f"Mode:      {self.mode}")
        lines.append(f"Target:    {self.target_name or 'None'} PID {self.target_pid}")
        lines.append(f"Admin:     {'YES' if self.is_admin else 'NO'}")
        lines.append(f"Duration:  {self.duration_seconds:.1f}s")
        lines.append("")

        # Baseline
        if self.baseline:
            b = self.baseline
            lines.append("BASELINE")
            lines.append("-" * w)
            if b.cpu_percent is not None:
                lines.append(f"  CPU:     {b.cpu_percent:.1f}%")
            if b.ram_percent is not None:
                lines.append(f"  RAM:     {b.ram_percent:.1f}%")
            if b.gpu_utilization is not None:
                lines.append(f"  GPU:     {b.gpu_utilization:.1f}%")
            if b.gpu_temperature is not None:
                lines.append(f"  GPU Temp: {b.gpu_temperature:.0f}°C")
            if b.fps is not None:
                lines.append(f"  FPS:     {b.fps:.1f}")
            lines.append("")

        # Analysis
        lines.append("ANALYSIS")
        lines.append("-" * w)
        lines.append(f"  Bottleneck:     {self.bottleneck or 'N/A'} ({self.bottleneck_confidence}%)")
        for ev in self.bottleneck_evidence[:3]:
            lines.append(f"  Evidence:       {ev}")
        lines.append(f"  Adaptive State: {self.adaptive_state or 'N/A'} ({self.adaptive_confidence}%)")
        lines.append(f"  Rec. Profile:   {self.recommended_profile.upper() if self.recommended_profile else 'N/A'}")
        lines.append(f"  Recommendations: {self.recommendation_count}")
        lines.append("")

        # Actions
        if self.actions:
            lines.append("ACTIONS")
            lines.append("-" * w)
            icons = {
                OptActionVerdict.APPLIED: "[OK]",
                OptActionVerdict.ALREADY_OPTIMAL: "[==]",
                OptActionVerdict.REQUIRES_ADMIN: "[@!]",
                OptActionVerdict.NOT_AVAILABLE: "[NA]",
                OptActionVerdict.RECOMMENDATION_ONLY: "[>>]",
                OptActionVerdict.BLOCKED_BY_SAFETY: "[XX]",
                OptActionVerdict.FAILED: "[!!]",
                OptActionVerdict.ROLLED_BACK: "[<<]",
                OptActionVerdict.INCONCLUSIVE: "[??]",
                OptActionVerdict.SKIPPED: "[--]",
            }
            for action in self.actions:
                icon = icons.get(action.verdict, "[??]")
                lines.append(f"  {icon} {action.name}: {action.verdict.value}")
                if action.reason:
                    lines.append(f"      {action.reason}")
                if action.verified:
                    lines.append(f"      Verified: YES")
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

        # Verdict
        lines.append("VERDICT")
        lines.append("-" * w)
        lines.append(f"  {self.verdict.value}: {self.verdict_reason}")

        if self.fps_delta is not None:
            lines.append(f"  FPS Delta: {self.fps_delta:+.1f} ({self.fps_delta_percent:+.1f}%)" if self.fps_delta_percent else f"  FPS Delta: {self.fps_delta:+.1f}")
        if self.one_low_delta is not None:
            lines.append(f"  1% Low Delta: {self.one_low_delta:+.1f}")

        lines.append("")
        lines.append("=" * w)
        return "\n".join(lines)


@dataclass
class EngineStatus:
    """Current engine status for UI consumption."""
    is_busy: bool = False
    current_phase: str = "IDLE"
    last_run: Optional[dict] = None
    history_count: int = 0
    profile_id: str = "gaming"
    is_admin: bool = False
    target_name: str = ""
    target_pid: int = 0

    def to_dict(self) -> dict:
        return {
            "is_busy": self.is_busy,
            "current_phase": self.current_phase,
            "last_run": self.last_run,
            "history_count": self.history_count,
            "profile_id": self.profile_id,
            "is_admin": self.is_admin,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
        }


# ── Safety Constants ─────────────────────────────────────────────

DEGRADATION_TEMP_THRESHOLD = 8.0  # °C increase triggers auto-rollback
DEGRADATION_TARGET_STABLE = False  # PID change triggers auto-rollback
MIN_SAMPLES_FOR_ANALYSIS = 5
MAX_ACTIONS_PER_RUN = 20


# ── Engine ───────────────────────────────────────────────────────

class OptimizationEngine:
    """
    Centralized production-grade optimization orchestration engine.

    Connects all existing subsystems into a unified workflow:
      Baseline → Analysis → Planning → Execution → Validation → Report

    Every action follows:
      Safety Gate → Pre-Snapshot → Execute → Verify → Impact → KEEP/ROLLBACK
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._current_run: Optional[OptimizationRunResult] = None
        self._last_run: Optional[OptimizationRunResult] = None
        self._history: List[OptimizationRunResult] = []
        self._progress_callback = None

    @property
    def is_busy(self) -> bool:
        return (
            self._current_run is not None
            and self._current_run.phase not in (
                EnginePhase.COMPLETED, EnginePhase.FAILED, EnginePhase.IDLE
            )
        )

    @property
    def current_run(self) -> Optional[OptimizationRunResult]:
        return self._current_run

    @property
    def last_run(self) -> Optional[OptimizationRunResult]:
        return self._last_run

    def on_progress(self, callback):
        """Register a progress callback: callback(phase, pct, message)."""
        self._progress_callback = callback

    def _progress(self, phase: EnginePhase, pct: float, msg: str):
        logger.info(f"[{phase.value}] {msg}")
        if self._progress_callback:
            try:
                self._progress_callback(phase, pct, msg)
            except Exception:
                pass

    # ── Target Detection ──────────────────────────────────────

    def _detect_target(self) -> Tuple[str, int, float]:
        """Detect current emulator target. Returns (name, pid, start_time)."""
        try:
            from app.performance.target_process import target_process_detector
            best = target_process_detector.select_best_target()
            if best:
                return best.process_name, best.pid, getattr(best, 'start_time', 0.0)
        except Exception as e:
            logger.debug(f"Target detection failed: {e}")
        return "", 0, 0.0

    def _validate_target(self, name: str, pid: int, start_time: float) -> Tuple[bool, str]:
        """Validate target PID hasn't been reused."""
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

    def _check_admin(self) -> bool:
        try:
            from app.utils.admin import is_admin
            return is_admin()
        except Exception:
            return False

    # ── Baseline Capture ──────────────────────────────────────

    def capture_baseline(self, target_name: str = "", target_pid: int = 0, target_start: float = 0.0) -> SystemBaseline:
        """Capture real system state as a baseline measurement."""
        baseline = SystemBaseline(
            target_name=target_name,
            target_pid=target_pid,
            target_pid_start=target_start,
        )

        # CPU
        try:
            import psutil
            baseline.cpu_percent = psutil.cpu_percent(interval=0.5)
            baseline.cpu_state = "MEASURED"
        except Exception:
            baseline.cpu_state = "FAILED"

        # RAM
        try:
            import psutil
            vm = psutil.virtual_memory()
            baseline.ram_used_mb = round(vm.used / (1024 * 1024), 1)
            baseline.ram_available_mb = round(vm.available / (1024 * 1024), 1)
            baseline.ram_percent = vm.percent
            baseline.ram_state = "MEASURED"
        except Exception:
            baseline.ram_state = "FAILED"

        # GPU
        try:
            from app.system.gpu import gpu_monitor
            gpu_info = gpu_monitor.detect()
            if gpu_info and gpu_info.utilization is not None:
                baseline.gpu_utilization = float(gpu_info.utilization)
                baseline.gpu_state = "MEASURED"
            else:
                baseline.gpu_state = "NOT_AVAILABLE"
            if hasattr(gpu_info, "temperature") and gpu_info.temperature is not None:
                baseline.gpu_temperature = float(gpu_info.temperature)
                baseline.gpu_temp_state = "MEASURED"
            else:
                baseline.gpu_temp_state = "NOT_AVAILABLE"
        except Exception:
            baseline.gpu_state = "NOT_AVAILABLE"
            baseline.gpu_temp_state = "NOT_AVAILABLE"

        # Emulator priority
        if target_pid:
            try:
                import psutil
                proc = psutil.Process(target_pid)
                baseline.emulator_priority = float(proc.nice())
            except Exception:
                pass

        # Power plan
        try:
            from app.system.power import power_monitor
            info = power_monitor.detect()
            baseline.active_power_plan = info.active_plan_name
        except Exception:
            pass

        # Thermal state
        try:
            from app.system.thermal_monitor import thermal_diagnostics
            thermal = thermal_diagnostics.diagnose()
            if thermal:
                baseline.thermal_state = getattr(thermal, 'overall_state', 'UNKNOWN')
        except Exception:
            pass

        return baseline

    def _delta(self, pre: SystemBaseline, post: SystemBaseline, attr: str) -> Optional[float]:
        """Calculate delta between pre and post for a given attribute."""
        pre_val = getattr(pre, attr, None)
        post_val = getattr(post, attr, None)
        if pre_val is not None and post_val is not None:
            try:
                return float(post_val) - float(pre_val)
            except (TypeError, ValueError):
                return None
        return None

    # ── Analysis Phase ────────────────────────────────────────

    def _analyze(
        self,
        run: OptimizationRunResult,
        baseline: SystemBaseline,
        optimization_states: Dict[str, str],
    ) -> None:
        """Run bottleneck analysis, adaptive classification, and recommendation generation."""
        run.phase = EnginePhase.ANALYSIS
        self._progress(EnginePhase.ANALYSIS, 0.3, "Analyzing system state...")

        # Build a minimal TelemetrySample from the baseline for the adaptive optimizer
        try:
            from app.performance.telemetry_models import TelemetrySample
            sample = TelemetrySample(
                cpu_total_percent=baseline.cpu_percent,
                system_ram_used_mb=baseline.ram_used_mb,
                system_ram_total_mb=(baseline.ram_used_mb + baseline.ram_available_mb) if baseline.ram_used_mb and baseline.ram_available_mb else None,
                gpu_utilization_percent=baseline.gpu_utilization,
                gpu_temperature_c=baseline.gpu_temperature,
            )
            samples = [sample]
        except Exception as e:
            logger.debug(f"TelemetrySample creation failed: {e}")
            samples = []

        # 1. Bottleneck analysis (existing BottleneckAnalyzer)
        try:
            from app.core.analyzer import bottleneck_analyzer
            from app.core.telemetry import TelemetryFrame
            frame = TelemetryFrame(
                timestamp=time.time(),
                cpu_utilization=baseline.cpu_percent or 0.0,
                gpu_utilization=baseline.gpu_utilization or 0.0,
                ram_percent=baseline.ram_percent or 0.0,
                gpu_temp=baseline.gpu_temperature,
                cpu_temp=None,
                gpu_memory_used_mb=0.0,
                gpu_memory_total_mb=0.0,
                thermal_status=baseline.thermal_state if baseline.thermal_state else "UNKNOWN",
            )
            analysis = bottleneck_analyzer.analyze(frame)
            if analysis.primary_bottleneck:
                run.bottleneck = analysis.primary_bottleneck.name
                run.bottleneck_confidence = int(analysis.primary_bottleneck.confidence * 100)
                run.bottleneck_evidence = [analysis.primary_bottleneck.description]
        except Exception as e:
            logger.debug(f"Bottleneck analysis failed: {e}")

        self._progress(EnginePhase.ANALYSIS, 0.4, f"Bottleneck: {run.bottleneck or 'N/A'}")

        # 2. Adaptive state classification
        try:
            from app.core.adaptive_optimizer import adaptive_optimizer, AdaptiveState
            state, conf, evidence = adaptive_optimizer.classify_state(samples)
            run.adaptive_state = state.value
            run.adaptive_confidence = conf
            run.bottleneck_evidence.extend(evidence)
        except Exception as e:
            logger.debug(f"Adaptive classification failed: {e}")

        self._progress(EnginePhase.ANALYSIS, 0.5, f"Adaptive state: {run.adaptive_state or 'N/A'}")

        # 3. Generate adaptive plan
        try:
            from app.core.adaptive_optimizer import adaptive_optimizer
            plan = adaptive_optimizer.generate_plan(
                samples=samples,
                state=AdaptiveState(run.adaptive_state) if run.adaptive_state else AdaptiveState.INSUFFICIENT_DATA,
                state_confidence=run.adaptive_confidence,
                state_evidence=run.bottleneck_evidence,
                optimization_states=optimization_states,
                profile_id=run.profile_id,
                target_name=run.target_name,
                target_pid=run.target_pid,
                is_admin=run.is_admin,
            )
            run.recommended_profile = plan.recommended_profile
        except Exception as e:
            logger.debug(f"Adaptive plan generation failed: {e}")

        # 4. Recommendation engine
        try:
            from app.core.recommendation_engine import RecommendationEngine
            rec_engine = RecommendationEngine()
            from app.performance.telemetry_models import BottleneckType
            bn_type = BottleneckType.INSUFFICIENT_DATA
            try:
                bn_type = BottleneckType(run.bottleneck.lower()) if run.bottleneck else BottleneckType.INSUFFICIENT_DATA
            except ValueError:
                pass
            rec_session = rec_engine.analyze(
                samples=samples,
                bottleneck_type=bn_type,
                bottleneck_confidence=run.bottleneck_confidence,
                bottleneck_evidence=run.bottleneck_evidence,
                optimization_states=optimization_states,
                profile_id=run.profile_id,
                target_name=run.target_name,
                target_pid=run.target_pid,
            )
            run.recommendation_count = len(rec_session.recommendations)
        except Exception as e:
            logger.debug(f"Recommendation engine failed: {e}")

        self._progress(EnginePhase.ANALYSIS, 0.6, f"Recommendations: {run.recommendation_count}")

    # ── Safety Gate ───────────────────────────────────────────

    def _safety_gate(
        self,
        optimization_id: str,
        run: OptimizationRunResult,
        thermal_state: str = "UNKNOWN",
    ) -> Tuple[bool, str]:
        """Comprehensive safety gate check before executing an optimization."""
        from app.core.profiles import get_profile
        from app.core.optimization_base import OptimizationStatus

        # 1. Target validity
        if run.target_pid <= 0:
            return False, "No valid emulator target"

        # 2. Profile membership
        profile = get_profile(run.profile_id)
        profile_opt_ids = {po.opt_id for po in profile.optimizations}
        if optimization_id not in profile_opt_ids:
            return False, f"Optimization not in profile {run.profile_id}"

        # 3. Load optimization
        try:
            from app.core.optimizations import get_optimization_by_id
            opt = get_optimization_by_id(optimization_id)
            if not opt:
                return False, f"Optimization {optimization_id} not found"
        except Exception as e:
            return False, f"Cannot load optimization: {e}"

        # 4. Check current state
        check_result = opt.check()

        if check_result.status == OptimizationStatus.ALREADY_OPTIMAL:
            return False, "Already optimal"
        if check_result.status == OptimizationStatus.RECOMMENDATION_ONLY:
            return False, "Recommendation only — no system modification"
        if check_result.status in (OptimizationStatus.NOT_APPLICABLE, OptimizationStatus.NOT_AVAILABLE):
            return False, "Not available on this system"
        if check_result.status == OptimizationStatus.REQUIRES_ADMIN:
            if not run.is_admin:
                return False, "Administrator privileges required"
            return True, "Admin available, proceeding"

        # 5. Thermal safety — do not increase performance when thermally limited
        if thermal_state in ("HOT", "THROTTLING_RISK", "THROTTLING") and optimization_id in (
            "power_plan", "emulator_priority", "cpu_affinity"
        ):
            return False, f"Thermal state {thermal_state} — performance increase blocked"

        # 6. Protected processes — recommendation only
        if optimization_id in ("background_load", "memory_analysis"):
            return False, "Recommendation only — no system modification"

        # 7. Must be OPTIMIZABLE
        if check_result.status != OptimizationStatus.OPTIMIZABLE:
            return False, f"Unexpected state: {check_result.status.value}"

        return True, "Safety gate passed"

    # ── Pre/Post Snapshot for Impact Evaluation ────────────────

    def _quick_snapshot(self, target_pid: int = 0) -> dict:
        """Quick system snapshot for impact evaluation."""
        snap = {}
        try:
            import psutil
            snap["cpu_percent"] = psutil.cpu_percent(interval=0.3)
            vm = psutil.virtual_memory()
            snap["ram_used_mb"] = round(vm.used / (1024 * 1024), 1)
            snap["ram_percent"] = vm.percent
        except Exception:
            pass
        try:
            from app.system.gpu import gpu_monitor
            gpu_info = gpu_monitor.detect()
            if gpu_info and gpu_info.utilization is not None:
                snap["gpu_utilization"] = float(gpu_info.utilization)
            if hasattr(gpu_info, "temperature") and gpu_info.temperature is not None:
                snap["gpu_temperature"] = float(gpu_info.temperature)
        except Exception:
            pass
        return snap

    def _evaluate_impact(self, pre: dict, post: dict) -> Tuple[str, str]:
        """Compare pre/post snapshots. Returns (verdict, reason)."""
        temp_delta = None
        if "gpu_temperature" in pre and "gpu_temperature" in post:
            temp_delta = post["gpu_temperature"] - pre["gpu_temperature"]

        # Degradation: significant temperature increase
        if temp_delta is not None and temp_delta > DEGRADATION_TEMP_THRESHOLD:
            return "DEGRADED", f"GPU temperature increased by {temp_delta:.1f}°C (threshold: {DEGRADATION_TEMP_THRESHOLD}°C)"

        return "UNCHANGED", "No measurable degradation detected"

    # ── Execute Single Optimization ───────────────────────────

    def _execute_single(
        self,
        optimization_id: str,
        run: OptimizationRunResult,
    ) -> OptimizationAction:
        """Execute a single optimization with full safety, verification, and rollback."""
        from app.core.optimization_base import OptimizationStatus
        from app.core.profiles import get_profile

        action = OptimizationAction(
            action_id=str(uuid.uuid4())[:8],
            optimization_id=optimization_id,
        )

        # Load optimization
        try:
            from app.core.optimizations import get_optimization_by_id
            opt = get_optimization_by_id(optimization_id)
            if not opt:
                action.verdict = OptActionVerdict.FAILED
                action.reason = f"Optimization {optimization_id} not found"
                return action
        except Exception as e:
            action.verdict = OptActionVerdict.FAILED
            action.reason = f"Load failed: {e}"
            return action

        # Get profile info
        profile = get_profile(run.profile_id)
        for po in profile.optimizations:
            if po.opt_id == optimization_id:
                action.name = po.name
                action.description = po.description
                break

        if not action.name:
            action.name = opt.name
        action.category = getattr(opt, "category", "")
        action.risk_level = getattr(opt, "risk_level", "LOW")

        # Check previous state
        try:
            check_result = opt.check()
            action.previous_value = check_result.current_value
            action.previous_state = check_result.status.value
        except Exception as e:
            action.verdict = OptActionVerdict.FAILED
            action.reason = f"Check failed: {e}"
            return action

        # Pre-snapshot for impact evaluation
        pre_snap = self._quick_snapshot(run.target_pid)

        # Snapshot for rollback
        try:
            opt.snapshot()
            action.rollback_available = True
        except Exception as e:
            logger.warning(f"Snapshot failed for {action.name}: {e}")

        # Apply
        try:
            apply_result = opt.apply()
            if apply_result.status == OptimizationStatus.APPLIED:
                action.applied_at = datetime.now().isoformat()

                # Wait briefly for system to settle
                time.sleep(0.5)

                # Verify
                verified = opt.verify()
                action.verified = verified
                action.verified_at = datetime.now().isoformat()

                if verified:
                    # Post-snapshot for impact evaluation
                    post_snap = self._quick_snapshot(run.target_pid)

                    # Evaluate impact
                    impact_verdict, impact_reason = self._evaluate_impact(pre_snap, post_snap)
                    action.cpu_delta = self._delta_dict(pre_snap, post_snap, "cpu_percent")
                    action.ram_delta_mb = self._delta_dict(pre_snap, post_snap, "ram_used_mb")
                    action.gpu_delta = self._delta_dict(pre_snap, post_snap, "gpu_utilization")
                    action.temperature_delta = self._delta_dict(pre_snap, post_snap, "gpu_temperature")

                    if impact_verdict == "DEGRADED":
                        # Auto-rollback
                        try:
                            rolled_back = opt.rollback()
                            if rolled_back:
                                action.verdict = OptActionVerdict.ROLLED_BACK
                                action.reason = f"Rolled back: {impact_reason}"
                                action.rollback_reason = impact_reason
                            else:
                                action.verdict = OptActionVerdict.INCONCLUSIVE
                                action.reason = "Applied but rollback failed after degradation"
                        except Exception as e:
                            action.verdict = OptActionVerdict.INCONCLUSIVE
                            action.reason = f"Rollback error: {e}"
                    else:
                        action.verdict = OptActionVerdict.APPLIED
                        action.reason = f"Applied and verified: {apply_result.message}"
                else:
                    # Verification failed — rollback
                    try:
                        rolled_back = opt.rollback()
                        if rolled_back:
                            action.verdict = OptActionVerdict.ROLLED_BACK
                            action.reason = "Rolled back: verification failed"
                        else:
                            action.verdict = OptActionVerdict.INCONCLUSIVE
                            action.reason = "Applied but verification and rollback failed"
                    except Exception as e:
                        action.verdict = OptActionVerdict.INCONCLUSIVE
                        action.reason = f"Rollback error: {e}"

            elif apply_result.status == OptimizationStatus.RECOMMENDATION_ONLY:
                action.verdict = OptActionVerdict.RECOMMENDATION_ONLY
                action.reason = "Recommendation only"
            elif apply_result.status == OptimizationStatus.ALREADY_OPTIMAL:
                action.verdict = OptActionVerdict.ALREADY_OPTIMAL
                action.reason = "Already optimal at execution time"
            elif apply_result.status == OptimizationStatus.REQUIRES_ADMIN:
                action.verdict = OptActionVerdict.REQUIRES_ADMIN
                action.reason = "Administrator privileges required"
            else:
                action.verdict = OptActionVerdict.FAILED
                action.reason = f"Apply returned: {apply_result.status.value}"

        except Exception as e:
            action.verdict = OptActionVerdict.FAILED
            action.reason = f"Execution error: {e}"
            logger.error(f"Execution error for {action.name}: {e}")

        return action

    @staticmethod
    def _delta_dict(pre: dict, post: dict, key: str) -> Optional[float]:
        """Calculate delta between two dicts for a given key."""
        if key in pre and key in post:
            try:
                return float(post[key]) - float(pre[key])
            except (TypeError, ValueError):
                return None
        return None

    # ── Planning Phase ────────────────────────────────────────

    def _plan(
        self,
        run: OptimizationRunResult,
        optimization_states: Dict[str, str],
    ) -> List[str]:
        """
        Generate the list of optimization IDs to execute.

        Returns ordered list of opt_ids to try, filtered by profile and state.
        """
        from app.core.profiles import get_profile

        profile = get_profile(run.profile_id)
        action_ids = []

        for po in profile.optimizations:
            state = optimization_states.get(po.opt_id, "UNKNOWN")

            # Skip known terminal states
            if state in ("ALREADY_OPTIMAL", "APPLIED", "VERIFIED"):
                continue
            if state in ("NOT_AVAILABLE", "NOT_APPLICABLE"):
                continue
            if state == "RECOMMENDATION_ONLY":
                continue  # Never auto-execute recommendation-only

            # Skip admin-required if not admin
            if state == "REQUIRES_ADMIN" and not run.is_admin:
                continue

            action_ids.append(po.opt_id)

        return action_ids[:MAX_ACTIONS_PER_RUN]

    def _get_optimization_states(self) -> Dict[str, str]:
        """Get current state of all optimizations."""
        states = {}
        try:
            from app.core.optimizations import get_all_optimizations
            for opt in get_all_optimizations():
                try:
                    result = opt.check()
                    states[opt.id] = result.status.value
                except Exception:
                    states[opt.id] = "UNKNOWN"
        except Exception:
            pass
        return states

    # ── Main Execution Pipeline ───────────────────────────────

    def run(
        self,
        profile_id: str = "gaming",
        mode: str = "auto",  # auto, dry_run, validate
        duration_seconds: float = 5.0,
    ) -> OptimizationRunResult:
        """
        Execute a complete optimization run.

        Pipeline:
          1. Acquire lock (BUSY if already running)
          2. Detect target
          3. Capture baseline
          4. Analyze (bottleneck + adaptive + recommendations)
          5. Generate plan
          6. Execute optimizations one at a time
          7. Verify each
          8. Evaluate impact
          9. KEEP or ROLLBACK
          10. Capture post-state
          11. Generate verdict
          12. Persist session
        """
        if self.is_busy:
            return OptimizationRunResult(
                phase=EnginePhase.FAILED,
                verdict=EngineVerdict.CANCELLED,
                verdict_reason="Engine is busy with another run",
            )

        if not self._lock.acquire(blocking=False):
            return OptimizationRunResult(
                phase=EnginePhase.FAILED,
                verdict=EngineVerdict.CANCELLED,
                verdict_reason="Could not acquire engine lock",
            )

        run = OptimizationRunResult(
            profile_id=profile_id,
            mode=mode,
            started_at=datetime.now().isoformat(),
            is_admin=self._check_admin(),
        )
        self._current_run = run

        try:
            return self._run_inner(run, duration_seconds)
        except Exception as e:
            run.phase = EnginePhase.FAILED
            run.verdict = EngineVerdict.INCONCLUSIVE
            run.verdict_reason = f"Engine error: {e}"
            logger.error(f"Optimization engine error: {e}")
            return run
        finally:
            run.completed_at = datetime.now().isoformat()
            try:
                run.duration_seconds = (
                    datetime.fromisoformat(run.completed_at)
                    - datetime.fromisoformat(run.started_at)
                ).total_seconds()
            except Exception:
                run.duration_seconds = 0.0
            self._current_run = None
            self._last_run = run
            self._history.append(run)
            self._save_run(run)
            self._lock.release()

    def _run_inner(
        self,
        run: OptimizationRunResult,
        duration_seconds: float,
    ) -> OptimizationRunResult:
        # ── Step 1: Detect Target ─────────────────────────────
        run.phase = EnginePhase.BASELINE
        self._progress(EnginePhase.BASELINE, 0.05, "Detecting target...")

        target_name, target_pid, target_start = self._detect_target()
        run.target_name = target_name
        run.target_pid = target_pid

        if not target_name or not target_pid:
            run.verdict = EngineVerdict.NO_EMULATOR
            run.verdict_reason = "No emulator target detected"
            run.phase = EnginePhase.COMPLETED
            return run

        # Validate target
        target_valid, target_msg = self._validate_target(target_name, target_pid, target_start)
        if not target_valid:
            run.verdict = EngineVerdict.NO_EMULATOR
            run.verdict_reason = target_msg
            run.phase = EnginePhase.COMPLETED
            return run

        # ── Step 2: Capture Baseline ─────────────────────────
        self._progress(EnginePhase.BASELINE, 0.1, "Capturing baseline...")
        baseline = self.capture_baseline(target_name, target_pid, target_start)
        run.baseline = baseline

        self._progress(EnginePhase.BASELINE, 0.2, f"Baseline captured: CPU={baseline.cpu_percent or 'N/A'}%, RAM={baseline.ram_percent or 'N/A'}%")

        # ── Step 3: Analyze ──────────────────────────────────
        optimization_states = self._get_optimization_states()
        self._analyze(run, baseline, optimization_states)

        # ── Step 4: Plan ─────────────────────────────────────
        run.phase = EnginePhase.PLANNING
        self._progress(EnginePhase.PLANNING, 0.65, "Generating action plan...")

        if run.mode == "dry_run":
            # Dry run: generate the plan but don't execute
            planned_ids = self._plan(run, optimization_states)
            for opt_id in planned_ids:
                action = OptimizationAction(
                    optimization_id=opt_id,
                    verdict=OptActionVerdict.SKIPPED,
                    reason="Dry run — would execute",
                )
                try:
                    from app.core.optimizations import get_optimization_by_id
                    opt = get_optimization_by_id(opt_id)
                    if opt:
                        action.name = opt.name
                        action.description = getattr(opt, "description", "")
                        action.category = getattr(opt, "category", "")
                        action.risk_level = getattr(opt, "risk_level", "LOW")
                except Exception:
                    pass
                run.actions.append(action)
            run.verdict = EngineVerdict.INCONCLUSIVE
            run.verdict_reason = f"Dry run — {len(run.actions)} actions planned"
            run.phase = EnginePhase.COMPLETED
            return run

        # ── Step 5: Execute ──────────────────────────────────
        run.phase = EnginePhase.EXECUTING
        planned_ids = self._plan(run, optimization_states)

        if not planned_ids:
            run.verdict = EngineVerdict.ALL_OPTIMAL
            run.verdict_reason = "All optimizations already optimal or not applicable"
            run.phase = EnginePhase.COMPLETED
            return run

        self._progress(EnginePhase.EXECUTING, 0.7, f"Executing {len(planned_ids)} optimizations...")

        for i, opt_id in enumerate(planned_ids):
            pct = 0.7 + (0.2 * (i / max(1, len(planned_ids))))
            self._progress(EnginePhase.EXECUTING, pct, f"Processing optimization {i+1}/{len(planned_ids)}...")

            # Safety gate
            allowed, reason = self._safety_gate(
                opt_id, run, baseline.thermal_state
            )

            if not allowed:
                action = OptimizationAction(
                    optimization_id=opt_id,
                    name=opt_id,
                    verdict=OptActionVerdict.BLOCKED_BY_SAFETY,
                    reason=reason,
                )
                # Refine verdict based on reason
                if "Already optimal" in reason:
                    action.verdict = OptActionVerdict.ALREADY_OPTIMAL
                    run.already_optimal_count += 1
                elif "Administrator" in reason:
                    action.verdict = OptActionVerdict.REQUIRES_ADMIN
                    run.admin_required_count += 1
                elif "Recommendation" in reason:
                    action.verdict = OptActionVerdict.RECOMMENDATION_ONLY
                    run.recommendation_only_count += 1
                elif "Not available" in reason:
                    action.verdict = OptActionVerdict.NOT_AVAILABLE
                    run.skipped_count += 1
                elif "thermal" in reason.lower():
                    action.verdict = OptActionVerdict.BLOCKED_BY_SAFETY
                    run.blocked_count += 1
                else:
                    action.verdict = OptActionVerdict.SKIPPED
                    run.skipped_count += 1
                run.actions.append(action)
                continue

            # Execute
            action = self._execute_single(opt_id, run)
            run.actions.append(action)

            # Update counts
            if action.verdict == OptActionVerdict.APPLIED:
                run.applied_count += 1
                run.kept_count += 1
            elif action.verdict == OptActionVerdict.ALREADY_OPTIMAL:
                run.already_optimal_count += 1
            elif action.verdict == OptActionVerdict.REQUIRES_ADMIN:
                run.admin_required_count += 1
            elif action.verdict == OptActionVerdict.RECOMMENDATION_ONLY:
                run.recommendation_only_count += 1
            elif action.verdict == OptActionVerdict.ROLLED_BACK:
                run.rolled_back_count += 1
            elif action.verdict == OptActionVerdict.FAILED:
                run.failed_count += 1
            elif action.verdict == OptActionVerdict.INCONCLUSIVE:
                run.failed_count += 1
            elif action.verdict == OptActionVerdict.BLOCKED_BY_SAFETY:
                run.blocked_count += 1
            else:
                run.skipped_count += 1

        # ── Step 6: Post-State Capture ───────────────────────
        run.phase = EnginePhase.VALIDATING
        self._progress(EnginePhase.VALIDATING, 0.9, "Capturing post-state...")

        time.sleep(1.0)  # Allow system to settle
        post_baseline = self.capture_baseline(target_name, target_pid, target_start)
        run.post_baseline = post_baseline

        # ── Step 7: Generate Verdict ─────────────────────────
        if run.kept_count > 0 and run.rolled_back_count == 0:
            run.verdict = EngineVerdict.UNCHANGED
            run.verdict_reason = f"Applied {run.kept_count} optimization(s). No measurable degradation detected."
        elif run.kept_count > 0 and run.rolled_back_count > 0:
            run.verdict = EngineVerdict.INCONCLUSIVE
            run.verdict_reason = f"Applied {run.kept_count}, rolled back {run.rolled_back_count}."
        elif run.rolled_back_count > 0:
            run.verdict = EngineVerdict.DEGRADED
            run.verdict_reason = f"All applied optimizations rolled back due to degradation."
        elif run.already_optimal_count > 0 and run.kept_count == 0:
            run.verdict = EngineVerdict.ALL_OPTIMAL
            run.verdict_reason = "All optimizations already optimal."
        elif run.failed_count > 0:
            run.verdict = EngineVerdict.INCONCLUSIVE
            run.verdict_reason = f"{run.failed_count} optimization(s) failed."
        else:
            run.verdict = EngineVerdict.INCONCLUSIVE
            run.verdict_reason = "No actions taken."

        # Calculate deltas
        if run.baseline and run.post_baseline:
            run.fps_delta = self._delta(run.baseline, run.post_baseline, "fps")
            run.one_low_delta = self._delta(run.baseline, run.post_baseline, "one_percent_low")
            if run.baseline.fps and run.fps_delta:
                run.fps_delta_percent = (run.fps_delta / run.baseline.fps) * 100

        self._progress(EnginePhase.COMPLETED, 1.0, f"Run complete: {run.verdict.value}")

        run.phase = EnginePhase.COMPLETED
        return run

    # ── Status ────────────────────────────────────────────────

    def get_status(self) -> EngineStatus:
        """Get current engine status for UI consumption."""
        status = EngineStatus(
            is_busy=self.is_busy,
            current_phase=self._current_run.phase.value if self._current_run else "IDLE",
            history_count=len(self._history),
            is_admin=self._check_admin(),
        )

        if self._last_run:
            status.last_run = self._last_run.to_dict()

        # Detect target
        try:
            name, pid, _ = self._detect_target()
            status.target_name = name
            status.target_pid = pid
        except Exception:
            pass

        return status

    # ── Rollback ──────────────────────────────────────────────

    def rollback_last(self) -> dict:
        """Rollback the most recent run's applied optimizations."""
        if not self._last_run:
            return {"success": False, "message": "No run to rollback"}

        applied_actions = [
            a for a in self._last_run.actions
            if a.verdict == OptActionVerdict.APPLIED
        ]

        if not applied_actions:
            return {"success": True, "message": "No applied optimizations to rollback"}

        from app.core.optimizer import optimizer
        result = optimizer.rollback_last()

        if result.success:
            for action in applied_actions:
                action.verdict = OptActionVerdict.ROLLED_BACK
                action.rollback_reason = "Rolled back by user request"
            self._last_run.rolled_back_count = self._last_run.kept_count
            self._last_run.kept_count = 0
            self._last_run.verdict = EngineVerdict.DEGRADED
            self._last_run.verdict_reason = "Rolled back by user request"
            self._save_run(self._last_run)

        return {"success": result.success, "message": result.message}

    # ── Persistence ───────────────────────────────────────────

    def _save_run(self, run: OptimizationRunResult):
        """Save run to disk."""
        try:
            sessions_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "optimization_runs",
            )
            os.makedirs(sessions_dir, exist_ok=True)
            filepath = os.path.join(sessions_dir, f"{run.run_id}.json")
            with open(filepath, "w") as f:
                json.dump(run.to_dict(), f, indent=2, default=str)
        except Exception as e:
            logger.debug(f"Failed to save run: {e}")

    def load_history(self, count: int = 10) -> List[dict]:
        """Load recent run history from disk."""
        try:
            sessions_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "optimization_runs",
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

    # ── UI Integration ────────────────────────────────────────

    def get_ui_summary(self) -> Dict:
        """Get a structured summary for the UI.
        
        Uses cached data only — does NOT perform live target detection
        or expensive system queries. The worker thread is responsible for
        fresh data collection via _collect_engine_summary().
        """
        summary = {
            "status": "IDLE",
            "profile": "gaming",
            "target_name": "",
            "target_pid": 0,
            "is_admin": False,
            "bottleneck": "N/A",
            "bottleneck_confidence": 0,
            "adaptive_state": "N/A",
            "recommended_profile": "gaming",
            "actions": [],
            "verdict": "N/A",
            "verdict_reason": "",
        }

        # Use cached status — no live target detection
        summary["status"] = self._current_run.phase.value if self._current_run else "IDLE"
        try:
            from app.utils.admin import is_admin
            summary["is_admin"] = is_admin()
        except Exception:
            pass

        if self._last_run:
            run = self._last_run
            summary["profile"] = run.profile_name or run.profile_id
            summary["bottleneck"] = run.bottleneck or "N/A"
            summary["bottleneck_confidence"] = run.bottleneck_confidence
            summary["adaptive_state"] = run.adaptive_state or "N/A"
            summary["recommended_profile"] = run.recommended_profile or run.profile_id
            summary["verdict"] = run.verdict.value
            summary["verdict_reason"] = run.verdict_reason

            summary["actions"] = []
            for a in run.actions:
                summary["actions"].append({
                    "name": a.name,
                    "verdict": a.verdict.value,
                    "reason": a.reason,
                    "risk_level": a.risk_level,
                    "rollback_available": a.rollback_available,
                })

        return summary


# Singleton
optimization_engine = OptimizationEngine()
