"""
Adaptive Gaming Optimization & Profile Intelligence — Phase 36.

Determines the user's current gaming situation and selects the safest useful
optimization actions based on measured evidence.

Reuses existing: optimizer, recommendation_engine, telemetry, profiles,
emulator detection, session management, snapshot/rollback infrastructure.

STRICTLY evidence-based. Never modifies system state directly.
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

from app.performance.telemetry_models import (
    BottleneckType,
    TelemetrySample,
)
from app.core.recommendation_engine import (
    DataQuality,
    EvidencePoint,
    RecommendationEngine,
    RecommendationPriority,
    RecommendationSession,
)
from app.utils.logger import get_logger

logger = get_logger("core.adaptive_optimizer")


# ── Enums ────────────────────────────────────────────────────────

class AdaptiveState(Enum):
    """Current gaming condition classification."""
    OPTIMAL = "OPTIMAL"
    CPU_BOUND = "CPU_BOUND"
    GPU_BOUND = "GPU_BOUND"
    MEMORY_BOUND = "MEMORY_BOUND"
    THERMAL_LIMITED = "THERMAL_LIMITED"
    FRAME_TIME_UNSTABLE = "FRAME_TIME_UNSTABLE"
    RESOURCE_PRESSURE = "RESOURCE_PRESSURE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ActionStatus(Enum):
    """Result of applying an adaptive action."""
    APPLIED = "APPLIED"
    ALREADY_OPTIMAL = "ALREADY_OPTIMAL"
    REQUIRES_ADMIN = "REQUIRES_ADMIN"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    RECOMMENDATION_ONLY = "RECOMMENDATION_ONLY"
    BLOCKED_BY_SAFETY = "BLOCKED_BY_SAFETY"
    FAILED = "FAILED"
    SKIPPED_INSUFFICIENT_EVIDENCE = "SKIPPED_INSUFFICIENT_EVIDENCE"
    SKIPPED_NOT_IN_PROFILE = "SKIPPED_NOT_IN_PROFILE"


class ProfileSuitability(Enum):
    """How suitable a profile is for the current situation."""
    SUITABLE = "SUITABLE"
    MARGINAL = "MARGINAL"
    UNSUITABLE = "UNSUITABLE"
    UNKNOWN = "UNKNOWN"


class SessionResult(Enum):
    """Overall adaptive session result."""
    IMPROVED = "IMPROVED"
    DEGRADED = "DEGRADED"
    UNCHANGED = "UNCHANGED"
    INCONCLUSIVE = "INCONCLUSIVE"
    NO_EMULATOR = "NO_EMULATOR"
    CANCELLED = "CANCELLED"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class AdaptiveAction:
    """A single recommended action in the adaptive plan."""
    optimization_id: str = ""
    optimization_name: str = ""
    status: ActionStatus = ActionStatus.SKIPPED_INSUFFICIENT_EVIDENCE
    confidence: int = 0
    reason: str = ""
    evidence: List[EvidencePoint] = field(default_factory=list)
    expected_area: str = ""
    safety: str = ""
    rollback_available: bool = False

    def to_dict(self) -> dict:
        return {
            "optimization_id": self.optimization_id,
            "optimization_name": self.optimization_name,
            "status": self.status.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "expected_area": self.expected_area,
            "safety": self.safety,
            "rollback_available": self.rollback_available,
        }


@dataclass
class AdaptivePlan:
    """Structured action plan for adaptive optimization."""
    plan_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    target_name: str = ""
    target_pid: int = 0
    state: AdaptiveState = AdaptiveState.INSUFFICIENT_DATA
    confidence: int = 0
    recommended_profile: str = "gaming"
    actions: List[AdaptiveAction] = field(default_factory=list)
    sample_count: int = 0
    duration_seconds: float = 0.0

    def get_applicable_actions(self) -> List[AdaptiveAction]:
        """Get actions that can be applied (not blocked/skipped)."""
        return [
            a for a in self.actions
            if a.status in (ActionStatus.APPLIED, ActionStatus.ALREADY_OPTIMAL,
                           ActionStatus.REQUIRES_ADMIN, ActionStatus.FAILED)
        ]

    def to_dict(self) -> dict:
        return {
            "plan_id": self.plan_id,
            "timestamp": self.timestamp,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "state": self.state.value,
            "confidence": self.confidence,
            "recommended_profile": self.recommended_profile,
            "actions": [a.to_dict() for a in self.actions],
            "sample_count": self.sample_count,
        }


@dataclass
class ProfileSuitabilityResult:
    """Assessment of how suitable a profile is for the current state."""
    profile_id: str = ""
    suitability: ProfileSuitability = ProfileSuitability.UNKNOWN
    reason: str = ""
    evidence: List[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "profile_id": self.profile_id,
            "suitability": self.suitability.value,
            "reason": self.reason,
            "evidence": self.evidence,
        }


@dataclass
class AdaptiveSessionRecord:
    """Historical record of an adaptive optimization session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    target_name: str = ""
    target_pid: int = 0
    profile: str = ""
    state: str = ""
    confidence: int = 0
    actions_attempted: int = 0
    actions_applied: int = 0
    actions_optimal: int = 0
    actions_failed: int = 0
    baseline_fps: Optional[float] = None
    baseline_1low: Optional[float] = None
    baseline_frame_time: Optional[float] = None
    post_fps: Optional[float] = None
    post_1low: Optional[float] = None
    post_frame_time: Optional[float] = None
    result: str = ""
    restoration_status: str = ""

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "target_name": self.target_name,
            "profile": self.profile,
            "state": self.state,
            "confidence": self.confidence,
            "actions_attempted": self.actions_attempted,
            "actions_applied": self.actions_applied,
            "result": self.result,
            "baseline_fps": self.baseline_fps,
            "post_fps": self.post_fps,
        }


# ── Persistence ──────────────────────────────────────────────────

HISTORY_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "adaptive_sessions",
)
MAX_HISTORY = 100


def _ensure_history_dir():
    os.makedirs(HISTORY_DIR, exist_ok=True)


def _save_session_record(record: AdaptiveSessionRecord):
    """Save a session record to disk."""
    try:
        _ensure_history_dir()
        filepath = os.path.join(HISTORY_DIR, f"{record.session_id}.json")
        with open(filepath, "w") as f:
            json.dump(record.to_dict(), f, indent=2)
    except Exception as e:
        logger.debug(f"Failed to save session record: {e}")


def load_session_history(count: int = 20) -> List[AdaptiveSessionRecord]:
    """Load recent session history from disk."""
    try:
        _ensure_history_dir()
        files = sorted(
            [f for f in os.listdir(HISTORY_DIR) if f.endswith(".json")],
            key=lambda f: os.path.getmtime(os.path.join(HISTORY_DIR, f)),
            reverse=True,
        )
        records = []
        for fname in files[:count]:
            try:
                with open(os.path.join(HISTORY_DIR, fname)) as f:
                    data = json.load(f)
                records.append(AdaptiveSessionRecord(**{
                    k: v for k, v in data.items()
                    if k in AdaptiveSessionRecord.__dataclass_fields__
                }))
            except Exception:
                continue
        return records
    except Exception:
        return []


# ── Constants ────────────────────────────────────────────────────

# Persistence requirements for bottleneck classification
MIN_SAMPLES_CLASSIFY = 5
MIN_SAMPLES_HIGH_CONFIDENCE = 20

# Thresholds for state classification (from telemetry samples)
CPU_HIGH_THRESHOLD = 85.0
CPU_ELEVATED_THRESHOLD = 70.0
GPU_SATURATION_THRESHOLD = 90.0
GPU_ELEVATED_THRESHOLD = 75.0
RAM_PRESSURE_HIGH = 85.0
RAM_PRESSURE_ELEVATED = 75.0
THERMAL_WARNING = 85.0
THERMAL_CRITICAL = 90.0
FRAME_TIME_CV_UNSTABLE = 0.35
FRAME_TIME_CV_MILD = 0.20

# Profile → optimization mapping
PROFILE_OPT_IDS = {
    "balanced": {"game_mode"},
    "gaming": {"power_plan", "game_mode", "emulator_priority", "memory_analysis"},
    "max_performance": {
        "power_plan", "game_mode", "game_bar", "background_recording",
        "emulator_priority", "cpu_affinity", "memory_analysis", "background_load",
    },
}


# ── Engine ───────────────────────────────────────────────────────

class AdaptiveOptimizer:
    """
    Adaptive gaming optimization engine.

    Evaluates the current gaming situation, determines what actually needs
    optimization, and generates evidence-based action plans.

    Uses existing infrastructure for actual system modifications.
    """

    def __init__(self):
        self._recommendation_engine = RecommendationEngine()
        self._lock = threading.Lock()
        self._last_plan: Optional[AdaptivePlan] = None
        self._history: List[AdaptiveSessionRecord] = []

    @property
    def last_plan(self) -> Optional[AdaptivePlan]:
        return self._last_plan

    @property
    def history(self) -> List[AdaptiveSessionRecord]:
        if not self._history:
            self._history = load_session_history()
        return list(self._history)

    # ── State Classification ──────────────────────────────────

    def classify_state(
        self, samples: List[TelemetrySample]
    ) -> Tuple[AdaptiveState, int, List[str]]:
        """
        Classify the current gaming condition from telemetry samples.

        Returns:
            (state, confidence, evidence)
        """
        if not samples or len(samples) < MIN_SAMPLES_CLASSIFY:
            return (
                AdaptiveState.INSUFFICIENT_DATA,
                0,
                [f"Only {len(samples) if samples else 0} samples, "
                 f"need {MIN_SAMPLES_CLASSIFY} minimum"],
            )

        evidence = []
        scores = {s: 0 for s in AdaptiveState}

        # Collect metric arrays
        cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
        gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
        ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
        ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
        gpu_temps = [s.gpu_temperature_c for s in samples if s.gpu_temperature_c is not None]
        emu_cpu = [s.emulator_cpu_percent for s in samples if s.emulator_cpu_percent is not None]
        frame_times = [s.frame_time_ms for s in samples if s.frame_time_ms is not None and s.frame_time_ms > 0]

        # CPU analysis
        if cpu_vals:
            avg_cpu = statistics.mean(cpu_vals)
            peak_cpu = max(cpu_vals)
            if avg_cpu >= CPU_HIGH_THRESHOLD:
                scores[AdaptiveState.CPU_BOUND] += 40
                evidence.append(f"CPU averaged {avg_cpu:.1f}% (peak {peak_cpu:.1f}%)")
            elif avg_cpu >= CPU_ELEVATED_THRESHOLD:
                scores[AdaptiveState.CPU_BOUND] += 15
                evidence.append(f"CPU elevated at {avg_cpu:.1f}%")

        # GPU analysis
        if gpu_vals:
            avg_gpu = statistics.mean(gpu_vals)
            peak_gpu = max(gpu_vals)
            if avg_gpu >= GPU_SATURATION_THRESHOLD:
                scores[AdaptiveState.GPU_BOUND] += 40
                evidence.append(f"GPU averaged {avg_gpu:.1f}% (peak {peak_gpu:.1f}%)")
            elif avg_gpu >= GPU_ELEVATED_THRESHOLD:
                scores[AdaptiveState.GPU_BOUND] += 15
                evidence.append(f"GPU elevated at {avg_gpu:.1f}%")

            # GPU-bound is stronger when CPU has headroom
            if cpu_vals and avg_gpu >= 80:
                avg_cpu = statistics.mean(cpu_vals)
                if avg_cpu < 60:
                    scores[AdaptiveState.GPU_BOUND] += 20
                    evidence.append(f"GPU saturated ({avg_gpu:.1f}%) while CPU has headroom ({avg_cpu:.1f}%)")

        # Memory analysis
        if ram_used and ram_total and ram_total[0] > 0:
            avg_used = statistics.mean(ram_used)
            total = ram_total[0]
            used_pct = (avg_used / total) * 100
            if used_pct >= RAM_PRESSURE_HIGH:
                scores[AdaptiveState.MEMORY_BOUND] += 40
                evidence.append(f"RAM at {used_pct:.1f}% ({avg_used:.0f}/{total:.0f} MB)")
            elif used_pct >= RAM_PRESSURE_ELEVATED:
                scores[AdaptiveState.MEMORY_BOUND] += 15
                evidence.append(f"RAM elevated at {used_pct:.1f}%")

        # Thermal analysis
        if gpu_temps:
            max_temp = max(gpu_temps)
            avg_temp = statistics.mean(gpu_temps)
            if max_temp >= THERMAL_CRITICAL:
                scores[AdaptiveState.THERMAL_LIMITED] += 45
                evidence.append(f"GPU temperature critical: {max_temp:.0f}°C")
            elif max_temp >= THERMAL_WARNING:
                scores[AdaptiveState.THERMAL_LIMITED] += 25
                evidence.append(f"GPU temperature elevated: {max_temp:.0f}°C (avg {avg_temp:.0f}°C)")

            # Rising temperature trend
            if len(gpu_temps) >= 10:
                first_half = statistics.mean(gpu_temps[:len(gpu_temps) // 2])
                second_half = statistics.mean(gpu_temps[len(gpu_temps) // 2:])
                if second_half - first_half > 5:
                    scores[AdaptiveState.THERMAL_LIMITED] += 10
                    evidence.append(f"GPU temperature rising ({first_half:.0f}→{second_half:.0f}°C)")

        # Frame time analysis
        if frame_times and len(frame_times) >= 3:
            avg_ft = statistics.mean(frame_times)
            if avg_ft > 0:
                cv = statistics.stdev(frame_times) / avg_ft if len(frame_times) > 1 else 0
                if cv > FRAME_TIME_CV_UNSTABLE:
                    scores[AdaptiveState.FRAME_TIME_UNSTABLE] += 40
                    evidence.append(f"Frame time unstable (CV={cv:.2f})")
                elif cv > FRAME_TIME_CV_MILD:
                    scores[AdaptiveState.FRAME_TIME_UNSTABLE] += 15
                    evidence.append(f"Frame time mildly unstable (CV={cv:.2f})")

        # Cross-metric analysis: CPU-bound pattern
        if cpu_vals and gpu_vals:
            avg_cpu = statistics.mean(cpu_vals)
            avg_gpu = statistics.mean(gpu_vals)
            if avg_cpu > CPU_HIGH_THRESHOLD and avg_gpu < 50:
                scores[AdaptiveState.CPU_BOUND] += 15
                evidence.append(f"CPU high ({avg_cpu:.1f}%) while GPU low ({avg_gpu:.1f}%)")

        # Cross-metric: multi-resource pressure
        high_resources = 0
        if cpu_vals and statistics.mean(cpu_vals) > CPU_HIGH_THRESHOLD:
            high_resources += 1
        if gpu_vals and statistics.mean(gpu_vals) > GPU_SATURATION_THRESHOLD:
            high_resources += 1
        if ram_used and ram_total and ram_total[0] > 0:
            if (statistics.mean(ram_used) / ram_total[0]) * 100 > RAM_PRESSURE_HIGH:
                high_resources += 1
        if high_resources >= 2:
            scores[AdaptiveState.RESOURCE_PRESSURE] += 30
            evidence.append(f"{high_resources} resources under simultaneous pressure")

        # Determine primary state
        n = len(samples)
        data_bonus = 0
        if n >= MIN_SAMPLES_HIGH_CONFIDENCE:
            data_bonus = 10
            evidence.append(f"{n} samples collected (high confidence)")
        elif n >= MIN_SAMPLES_CLASSIFY:
            data_bonus = 5
            evidence.append(f"{n} samples collected")

        # Find the highest-scoring non-INSUFFICIENT_DATA state
        candidates = [
            (state, score + data_bonus)
            for state, score in scores.items()
            if state != AdaptiveState.INSUFFICIENT_DATA and score > 0
        ]

        if not candidates:
            # Check if we have any data at all
            has_any = cpu_vals or gpu_vals or ram_used
            if has_any:
                return (
                    AdaptiveState.OPTIMAL,
                    50 + data_bonus,
                    ["No persistent resource bottleneck detected"],
                )
            return (
                AdaptiveState.INSUFFICIENT_DATA,
                0,
                ["No valid telemetry data collected"],
            )

        candidates.sort(key=lambda x: x[1], reverse=True)
        best_state, best_score = candidates[0]

        # Cap confidence
        confidence = min(best_score, 100)

        return best_state, confidence, evidence

    # ── Action Planning ───────────────────────────────────────

    def generate_plan(
        self,
        samples: List[TelemetrySample],
        state: AdaptiveState,
        state_confidence: int,
        state_evidence: List[str],
        optimization_states: Dict[str, str] = None,
        profile_id: str = "gaming",
        target_name: str = "",
        target_pid: int = 0,
        is_admin: bool = False,
    ) -> AdaptivePlan:
        """
        Generate an adaptive action plan based on the current state.

        Only recommends actions justified by evidence and permitted by profile.
        """
        if optimization_states is None:
            optimization_states = {}

        plan = AdaptivePlan(
            target_name=target_name,
            target_pid=target_pid,
            state=state,
            confidence=state_confidence,
            recommended_profile=self._recommend_profile(state, state_confidence, samples),
            sample_count=len(samples),
        )

        # Determine applicable actions based on state
        action_specs = self._state_to_actions(state, state_confidence, samples)

        # Filter by profile
        profile_opt_ids = PROFILE_OPT_IDS.get(profile_id, set())

        for opt_id, base_confidence, reason in action_specs:
            action = self._evaluate_action(
                opt_id, base_confidence, reason, samples,
                optimization_states, profile_opt_ids, is_admin, state,
            )
            plan.actions.append(action)

        self._last_plan = plan
        return plan

    def _state_to_actions(
        self, state: AdaptiveState, confidence: int, samples: List[TelemetrySample]
    ) -> List[Tuple[str, int, str]]:
        """
        Map state to action specifications.

        Returns list of (optimization_id, base_confidence, reason).
        """
        if state == AdaptiveState.INSUFFICIENT_DATA:
            return []

        if state == AdaptiveState.OPTIMAL:
            return []  # No actions needed

        if state == AdaptiveState.CPU_BOUND:
            return [
                ("emulator_priority", 70, "CPU scheduling may benefit from higher emulator priority"),
                ("power_plan", 50, "Power plan affects CPU throughput"),
                ("background_load", 40, "Background processes may contribute to CPU pressure"),
                ("cpu_affinity", 30, "CPU affinity may help distribute load"),
            ]

        if state == AdaptiveState.GPU_BOUND:
            return [
                # GPU-bound: limited software optimization
                ("memory_analysis", 30, "GPU saturation detected; memory analysis for overall health"),
                ("background_load", 25, "Reduce background resource contention"),
            ]

        if state == AdaptiveState.MEMORY_BOUND:
            return [
                ("memory_analysis", 75, "Memory pressure is elevated"),
                ("background_load", 65, "Background processes may be consuming significant RAM"),
            ]

        if state == AdaptiveState.THERMAL_LIMITED:
            return [
                # Do NOT increase performance settings when thermally limited
                ("background_load", 40, "Reducing background load may lower thermal pressure"),
            ]

        if state == AdaptiveState.FRAME_TIME_UNSTABLE:
            return [
                ("emulator_priority", 50, "Frame delivery is inconsistent; priority may help"),
                ("power_plan", 40, "Power management affects frame consistency"),
                ("background_load", 35, "Background interference may cause frame spikes"),
            ]

        if state == AdaptiveState.RESOURCE_PRESSURE:
            return [
                ("memory_analysis", 60, "Multiple resources under pressure"),
                ("background_load", 55, "Background processes contribute to resource pressure"),
                ("emulator_priority", 45, "Priority may help amid resource contention"),
            ]

        return []

    def _evaluate_action(
        self,
        opt_id: str,
        base_confidence: int,
        reason: str,
        samples: List[TelemetrySample],
        states: Dict[str, str],
        profile_opt_ids: set,
        is_admin: bool,
        state: AdaptiveState,
    ) -> AdaptiveAction:
        """Evaluate a single action for the plan."""
        from app.core.recommendation_engine import OPTIMIZATION_META

        meta = OPTIMIZATION_META.get(opt_id, {})
        name = meta.get("name", opt_id)
        expected_area = meta.get("expected_area", "")
        safety = meta.get("safety", "")

        # Check profile membership
        if opt_id not in profile_opt_ids:
            return AdaptiveAction(
                optimization_id=opt_id,
                optimization_name=name,
                status=ActionStatus.SKIPPED_NOT_IN_PROFILE,
                confidence=0,
                reason=f"{name} is not in the {state.value} profile",
                expected_area=expected_area,
                safety=safety,
            )

        # Check current state
        current = states.get(opt_id, "UNKNOWN")

        if current in ("ALREADY_OPTIMAL", "APPLIED", "VERIFIED"):
            return AdaptiveAction(
                optimization_id=opt_id,
                optimization_name=name,
                status=ActionStatus.ALREADY_OPTIMAL,
                confidence=100,
                reason=f"{name} is already optimal",
                expected_area=expected_area,
                safety=safety,
            )

        if current == "REQUIRES_ADMIN":
            return AdaptiveAction(
                optimization_id=opt_id,
                optimization_name=name,
                status=ActionStatus.REQUIRES_ADMIN,
                confidence=90,
                reason=f"{name} requires administrator privileges",
                expected_area=expected_area,
                safety=safety,
            )

        if current == "RECOMMENDATION_ONLY":
            return AdaptiveAction(
                optimization_id=opt_id,
                optimization_name=name,
                status=ActionStatus.RECOMMENDATION_ONLY,
                confidence=60,
                reason=f"{name} is advisory only",
                expected_area=expected_area,
                safety=safety,
            )

        if current in ("NOT_AVAILABLE", "NOT_APPLICABLE"):
            return AdaptiveAction(
                optimization_id=opt_id,
                optimization_name=name,
                status=ActionStatus.NOT_AVAILABLE,
                confidence=0,
                reason=f"{name} is not available",
                expected_area=expected_area,
                safety=safety,
            )

        # Safety gate: admin required but not available
        if safety == "REQUIRES_ADMIN" and not is_admin:
            return AdaptiveAction(
                optimization_id=opt_id,
                optimization_name=name,
                status=ActionStatus.REQUIRES_ADMIN,
                confidence=base_confidence,
                reason=f"{name} requires elevation",
                expected_area=expected_area,
                safety=safety,
            )

        # Safety gate: insufficient evidence
        n = len(samples)
        if n < MIN_SAMPLES_CLASSIFY:
            return AdaptiveAction(
                optimization_id=opt_id,
                optimization_name=name,
                status=ActionStatus.SKIPPED_INSUFFICIENT_EVIDENCE,
                confidence=0,
                reason="Insufficient telemetry samples for this action",
                expected_area=expected_area,
                safety=safety,
            )

        # Apply confidence scaling
        if n >= MIN_SAMPLES_HIGH_CONFIDENCE:
            confidence = min(base_confidence, 100)
        elif n >= MIN_SAMPLES_CLASSIFY:
            confidence = min(base_confidence, 75)
        else:
            confidence = min(base_confidence, 50)

        return AdaptiveAction(
            optimization_id=opt_id,
            optimization_name=name,
            status=ActionStatus.APPLIED,  # Will be actual APPLIED only after execute
            confidence=confidence,
            reason=reason,
            expected_area=expected_area,
            safety=safety,
        )

    # ── Profile Intelligence ──────────────────────────────────

    def _recommend_profile(
        self, state: AdaptiveState, confidence: int, samples: List[TelemetrySample]
    ) -> str:
        """Recommend the most appropriate profile for the current state."""
        if state == AdaptiveState.INSUFFICIENT_DATA:
            return "gaming"  # Default

        if state == AdaptiveState.OPTIMAL:
            return "balanced"  # No aggressive optimization needed

        if state == AdaptiveState.THERMAL_LIMITED:
            # Do NOT recommend max performance when thermally limited
            return "balanced"

        if state in (AdaptiveState.RESOURCE_PRESSURE, AdaptiveState.MEMORY_BOUND):
            return "max_performance"  # Need all available tools

        if state in (AdaptiveState.CPU_BOUND, AdaptiveState.FRAME_TIME_UNSTABLE):
            return "gaming"

        if state == AdaptiveState.GPU_BOUND:
            return "gaming"  # Limited software optimization for GPU-bound

        return "gaming"

    def assess_profile_suitability(
        self,
        profile_id: str,
        state: AdaptiveState,
        state_confidence: int,
        is_admin: bool = False,
        samples: List[TelemetrySample] = None,
    ) -> ProfileSuitabilityResult:
        """Assess how suitable a profile is for the current situation."""
        reasons = []

        if state == AdaptiveState.INSUFFICIENT_DATA:
            return ProfileSuitabilityResult(
                profile_id=profile_id,
                suitability=ProfileSuitability.UNKNOWN,
                reason="Insufficient telemetry to assess suitability",
            )

        if state == AdaptiveState.OPTIMAL and profile_id == "max_performance":
            return ProfileSuitabilityResult(
                profile_id=profile_id,
                suitability=ProfileSuitability.MARGINAL,
                reason="System is optimal; aggressive optimization may not be justified",
                evidence=["No bottleneck detected", "All resources have headroom"],
            )

        if state == AdaptiveState.THERMAL_LIMITED and profile_id == "max_performance":
            return ProfileSuitabilityResult(
                profile_id=profile_id,
                suitability=ProfileSuitability.UNSUITABLE,
                reason="Thermal state elevated; increasing performance settings may worsen thermals",
                evidence=["GPU/CPU temperature approaching limits"],
            )

        if state == AdaptiveState.THERMAL_LIMITED and profile_id == "gaming":
            return ProfileSuitabilityResult(
                profile_id=profile_id,
                suitability=ProfileSuitability.MARGINAL,
                reason="Thermal state elevated; gaming profile includes power plan which may increase thermal load",
            )

        # Check admin requirements for the profile
        profile_opts = PROFILE_OPT_IDS.get(profile_id, set())
        admin_opts = {"emulator_priority", "cpu_affinity"}
        needs_admin = profile_opts & admin_opts
        if needs_admin and not is_admin:
            reasons.append(f"Profile requires admin for: {', '.join(needs_admin)}")

        # Match profile to state
        if state == AdaptiveState.CPU_BOUND:
            if profile_id in ("gaming", "max_performance"):
                return ProfileSuitabilityResult(
                    profile_id=profile_id,
                    suitability=ProfileSuitability.SUITABLE,
                    reason="Profile includes CPU-relevant optimizations",
                    evidence=[f"CPU-bound with {state_confidence}% confidence"],
                )
            else:
                return ProfileSuitabilityResult(
                    profile_id=profile_id,
                    suitability=ProfileSuitability.MARGINAL,
                    reason="Balanced profile has limited CPU optimization",
                )

        if state == AdaptiveState.MEMORY_BOUND:
            if profile_id in ("gaming", "max_performance"):
                return ProfileSuitabilityResult(
                    profile_id=profile_id,
                    suitability=ProfileSuitability.SUITABLE,
                    reason="Profile includes memory analysis",
                )
            return ProfileSuitabilityResult(
                profile_id=profile_id,
                suitability=ProfileSuitability.MARGINAL,
                reason="Balanced profile lacks memory optimization",
            )

        if state == AdaptiveState.GPU_BOUND:
            return ProfileSuitabilityResult(
                profile_id=profile_id,
                suitability=ProfileSuitability.MARGINAL,
                reason="Limited software optimization available for GPU-bound workload",
            )

        # Default
        return ProfileSuitabilityResult(
            profile_id=profile_id,
            suitability=ProfileSuitability.SUITABLE,
            reason="Profile is compatible with current state",
        )

    # ── Execution ─────────────────────────────────────────────

    def execute_plan(self, plan: AdaptivePlan) -> AdaptivePlan:
        """
        Execute an adaptive plan using the existing optimizer.

        Only applies actions with APPLIED status.
        Verifies each application.
        Records results.
        """
        from app.core.optimizer import optimizer

        if not plan.actions:
            return plan

        for action in plan.actions:
            if action.status != ActionStatus.APPLIED:
                continue  # Only execute planned actions

            try:
                from app.core.optimizations import get_optimization_by_id
                opt = get_optimization_by_id(action.optimization_id)
                if not opt:
                    action.status = ActionStatus.FAILED
                    action.reason = f"Optimization {action.optimization_id} not found"
                    continue

                # Check
                check_result = opt.check()
                if check_result.status.value in ("ALREADY OPTIMAL",):
                    action.status = ActionStatus.ALREADY_OPTIMAL
                    action.reason = "Already optimal at execution time"
                    continue
                elif check_result.status.value == "REQUIRES_ADMIN":
                    action.status = ActionStatus.REQUIRES_ADMIN
                    action.reason = "Administrator privileges required"
                    continue
                elif check_result.status.value in ("NOT APPLICABLE", "NOT AVAILABLE"):
                    action.status = ActionStatus.NOT_AVAILABLE
                    action.reason = "Not available at execution time"
                    continue
                elif check_result.status.value == "RECOMMENDATION ONLY":
                    action.status = ActionStatus.RECOMMENDATION_ONLY
                    action.reason = "Recommendation only — no system change"
                    continue
                elif check_result.status.value != "OPTIMIZABLE":
                    action.status = ActionStatus.SKIPPED_INSUFFICIENT_EVIDENCE
                    action.reason = f"Unexpected state: {check_result.status.value}"
                    continue

                # Snapshot
                try:
                    opt.snapshot()
                except Exception as e:
                    logger.warning(f"Snapshot failed for {action.optimization_name}: {e}")

                # Apply
                apply_result = opt.apply()
                if apply_result.status.value == "APPLIED":
                    time.sleep(0.3)
                    verified = opt.verify()
                    if verified:
                        action.status = ActionStatus.APPLIED
                        action.rollback_available = True
                        action.reason = f"Applied and verified: {apply_result.message}"
                    else:
                        action.status = ActionStatus.FAILED
                        action.reason = f"Applied but verification failed"
                else:
                    action.status = ActionStatus.FAILED
                    action.reason = f"Apply returned: {apply_result.status.value}"

            except Exception as e:
                action.status = ActionStatus.FAILED
                action.reason = f"Execution error: {e}"
                logger.error(f"Adaptive action failed: {action.optimization_name}: {e}")

        return plan

    # ── Session History ───────────────────────────────────────

    def compare_with_history(
        self, current: AdaptiveSessionRecord
    ) -> Optional[Dict]:
        """Compare current session with most recent similar session."""
        history = self.history
        if not history:
            return None

        # Find most recent session with same profile
        previous = None
        for h in history:
            if h.profile == current.profile and h.session_id != current.session_id:
                previous = h
                break

        if not previous:
            return None

        comparison = {
            "previous_session": previous.to_dict(),
            "fps_change": None,
            "one_low_change": None,
            "frame_time_change": None,
            "overall": "INCONCLUSIVE",
            "confidence": "LOW",
        }

        if current.baseline_fps is not None and previous.post_fps is not None:
            comparison["fps_change"] = current.baseline_fps - previous.post_fps
        if current.baseline_1low is not None and previous.post_1low is not None:
            comparison["one_low_change"] = current.baseline_1low - previous.post_1low

        # Determine overall
        changes = [
            comparison["fps_change"],
            comparison["one_low_change"],
        ]
        valid_changes = [c for c in changes if c is not None]
        if not valid_changes:
            comparison["overall"] = "INCONCLUSIVE"
        elif all(c > 1 for c in valid_changes):
            comparison["overall"] = "IMPROVED"
            comparison["confidence"] = "MODERATE"
        elif all(c < -1 for c in valid_changes):
            comparison["overall"] = "DEGRADED"
            comparison["confidence"] = "MODERATE"
        else:
            comparison["overall"] = "MIXED"
            comparison["confidence"] = "LOW"

        return comparison

    def save_session(self, record: AdaptiveSessionRecord):
        """Save a session record and update history."""
        self._history.insert(0, record)
        if len(self._history) > MAX_HISTORY:
            self._history = self._history[:MAX_HISTORY]
        _save_session_record(record)

    # ── CLI Formatting ────────────────────────────────────────

    def format_status(self, plan: AdaptivePlan) -> str:
        """Format adaptive status for CLI."""
        lines = []
        lines.append("=" * 55)
        lines.append("HEAVEN SOCIETY — ADAPTIVE STATUS")
        lines.append("=" * 55)
        lines.append("")

        lines.append("TARGET")
        if plan.target_name:
            lines.append(f"  {plan.target_name}  PID: {plan.target_pid}")
        else:
            lines.append("  No emulator detected")
        lines.append("")

        state_str = plan.state.value.replace("_", " ").title()
        lines.append("STATE")
        lines.append(f"  {state_str}")
        lines.append(f"  Confidence: {plan.confidence}%")
        lines.append("")

        lines.append("DATA")
        lines.append(f"  Samples: {plan.sample_count}")
        lines.append("")

        lines.append(f"RECOMMENDED PROFILE: {plan.recommended_profile.upper()}")
        lines.append("")

        if plan.actions:
            lines.append("ACTIONS")
            lines.append("-" * 55)
            for a in plan.actions:
                status_str = a.status.value.replace("_", " ")
                lines.append(f"  {a.optimization_name}")
                lines.append(f"    Status: {status_str}")
                lines.append(f"    Confidence: {a.confidence}%")
                lines.append(f"    Why: {a.reason}")
                lines.append(f"    Area: {a.expected_area}")
                lines.append(f"    Safety: {a.safety}")
                lines.append("")
        else:
            lines.append("ACTIONS")
            lines.append("-" * 55)
            if plan.state == AdaptiveState.OPTIMAL:
                lines.append("  System is optimal — no actions needed.")
            elif plan.state == AdaptiveState.INSUFFICIENT_DATA:
                lines.append("  Insufficient data — collect more telemetry.")
            else:
                lines.append("  No applicable actions.")
            lines.append("")

        lines.append("=" * 55)
        return "\n".join(lines)

    def format_plan(self, plan: AdaptivePlan) -> str:
        """Format action plan for CLI."""
        lines = []
        lines.append("=" * 55)
        lines.append("HEAVEN SOCIETY — ADAPTIVE ACTION PLAN")
        lines.append("=" * 55)
        lines.append("")

        state_str = plan.state.value.replace("_", " ").title()
        lines.append(f"STATE: {state_str} ({plan.confidence}% confidence)")
        lines.append(f"PROFILE: {plan.recommended_profile.upper()}")
        lines.append(f"TARGET: {plan.target_name or 'None'} PID: {plan.target_pid}")
        lines.append("")

        applicable = [a for a in plan.actions if a.status in (
            ActionStatus.APPLIED, ActionStatus.ALREADY_OPTIMAL,
            ActionStatus.REQUIRES_ADMIN, ActionStatus.RECOMMENDATION_ONLY,
        )]

        if applicable:
            lines.append("PLANNED ACTIONS")
            lines.append("-" * 55)
            for i, a in enumerate(applicable, 1):
                status_str = a.status.value.replace("_", " ")
                lines.append(f"  {i}. {a.optimization_name}")
                lines.append(f"     Status: {status_str}")
                lines.append(f"     Confidence: {a.confidence}%")
                lines.append(f"     Why: {a.reason}")
                lines.append(f"     Area: {a.expected_area}")
                lines.append(f"     Safety: {a.safety}")
                if a.evidence:
                    ev_parts = []
                    for ev in a.evidence[:3]:
                        v = f"{ev.measured_value}" if ev.measured_value is not None else "N/A"
                        ev_parts.append(f"{ev.metric}: {v}{ev.unit}")
                    lines.append(f"     Evidence: {' | '.join(ev_parts)}")
                lines.append("")
        else:
            lines.append("No applicable actions.")
            lines.append("")

        lines.append("=" * 55)
        return "\n".join(lines)


# Singleton
adaptive_optimizer = AdaptiveOptimizer()
