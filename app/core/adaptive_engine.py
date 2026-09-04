"""
Phase 70 — Adaptive Optimization Engine.

Production-quality adaptive optimization that:
  OBSERVE → ANALYZE → DETECT SUSTAINED CONDITION → RECOMMEND
  → USER APPROVAL → APPLY → VERIFY → OBSERVE RESULT
  → KEEP OR ROLLBACK

Builds on top of the existing AdaptiveOptimizer (Phase 36) which provides
state classification and action planning. This module adds:
  - Rolling telemetry window with bounded history
  - Sustained condition detection (not reacting to single noisy samples)
  - Baseline comparison with hysteresis
  - Cooldown / anti-spam system
  - Before/after impact evaluation
  - Automatic rollback of harmful changes
  - Session lifecycle integration
  - UI state management

Rules:
  - Never blindly change settings continuously
  - Require sustained conditions across multiple observations
  - Use existing rollback/snapshot infrastructure
  - Never modify game memory, inject DLLs, bypass anti-cheat
  - Every claim backed by measured evidence
  - All heavy work runs in background workers
  - GUI must remain responsive
"""

import json
import os
import statistics
import threading
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Deque, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("core.adaptive_engine")


# ══════════════════════════════════════════════════════════════
#  ENUMS
# ══════════════════════════════════════════════════════════════


class AdaptiveEngineState(Enum):
    """High-level engine state."""
    IDLE = "IDLE"
    MONITORING = "MONITORING"
    RECOMMENDING = "RECOMMENDING"
    AWAITING_APPROVAL = "AWAITING_APPROVAL"
    APPLYING = "APPLYING"
    OBSERVING_IMPACT = "OBSERVING_IMPACT"
    ROLLING_BACK = "ROLLING_BACK"
    STOPPED = "STOPPED"


class ConditionType(Enum):
    """Types of sustained conditions the engine detects."""
    CPU_PRESSURE = "CPU_PRESSURE"
    GPU_PRESSURE = "GPU_PRESSURE"
    RAM_PRESSURE = "RAM_PRESSURE"
    FPS_DEGRADATION = "FPS_DEGRADATION"
    FRAME_TIME_INSTABILITY = "FRAME_TIME_INSTABILITY"
    THERMAL_PRESSURE = "THERMAL_PRESSURE"
    LATENCY_DEGRADATION = "LATENCY_DEGRADATION"
    BACKGROUND_PRESSURE = "BACKGROUND_PRESSURE"


class ImpactClassification(Enum):
    """Result of post-optimization observation."""
    HELPED = "HELPED"
    NO_SIGNIFICANT_CHANGE = "NO_SIGNIFICANT_CHANGE"
    HARMFUL = "HARMFUL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class RecommendationAction(Enum):
    """User action on a recommendation."""
    PENDING = "PENDING"
    APPLY = "APPLY"
    DISMISS = "DISMISS"


# ══════════════════════════════════════════════════════════════
#  THRESHOLDS (centralized, configurable)
# ══════════════════════════════════════════════════════════════


@dataclass
class AdaptiveThresholds:
    """Centralized thresholds for adaptive optimization.

    Trigger thresholds: condition must exceed to be detected.
    Recovery thresholds: condition must drop below to clear.
    Using separate trigger/recovery prevents oscillation.
    """
    # CPU
    cpu_trigger: float = 88.0
    cpu_recovery: float = 75.0

    # GPU
    gpu_trigger: float = 92.0
    gpu_recovery: float = 80.0

    # RAM
    ram_trigger: float = 87.0
    ram_recovery: float = 75.0

    # FPS degradation (% below baseline)
    fps_degradation_pct: float = 15.0
    fps_recovery_pct: float = 5.0

    # Frame time instability (coefficient of variation)
    frame_time_cv_trigger: float = 0.30
    frame_time_cv_recovery: float = 0.15

    # Thermal
    thermal_trigger: float = 87.0
    thermal_recovery: float = 78.0

    # Latency (ms above baseline)
    latency_trigger_ms: float = 15.0
    latency_recovery_ms: float = 8.0

    # Sustained condition requirements
    min_samples_for_condition: int = 5
    min_sustained_seconds: float = 10.0

    # Impact evaluation
    impact_improvement_pct: float = 5.0  # Min % improvement to call HELPED
    impact_harm_pct: float = 8.0  # Min % degradation to call HARMFUL
    impact_observation_seconds: float = 15.0

    # Cooldowns (seconds)
    cooldown_after_apply: float = 60.0
    cooldown_after_dismiss: float = 120.0
    cooldown_after_failure: float = 180.0
    cooldown_same_recommendation: float = 300.0

    # Telemetry window
    max_window_samples: int = 120
    window_seconds: float = 120.0


# ══════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════


@dataclass
class TelemetryPoint:
    """A single telemetry observation."""
    timestamp: float = 0.0
    cpu_percent: Optional[float] = None
    gpu_percent: Optional[float] = None
    ram_percent: Optional[float] = None
    fps: Optional[float] = None
    frame_time_ms: Optional[float] = None
    gpu_temp: Optional[float] = None
    latency_ms: Optional[float] = None
    target_cpu: Optional[float] = None
    background_cpu: Optional[float] = None

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class SustainedCondition:
    """A detected sustained performance condition."""
    condition_id: str = ""
    condition_type: ConditionType = ConditionType.CPU_PRESSURE
    detected_at: float = 0.0
    duration_seconds: float = 0.0
    sample_count: int = 0
    current_value: float = 0.0
    baseline_value: float = 0.0
    threshold: float = 0.0
    confidence: float = 0.0
    evidence: List[str] = field(default_factory=list)
    active: bool = True

    def __post_init__(self):
        if not self.condition_id:
            self.condition_id = f"cond_{uuid.uuid4().hex[:8]}"

    def to_dict(self) -> dict:
        return {
            "condition_id": self.condition_id,
            "condition_type": self.condition_type.value,
            "detected_at": self.detected_at,
            "duration_seconds": self.duration_seconds,
            "sample_count": self.sample_count,
            "current_value": self.current_value,
            "baseline_value": self.baseline_value,
            "threshold": self.threshold,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "active": self.active,
        }


@dataclass
class AdaptiveRecommendation:
    """A recommendation presented to the user for approval."""
    recommendation_id: str = ""
    title: str = ""
    reason: str = ""
    condition: Optional[SustainedCondition] = None
    optimization_id: str = ""
    optimization_name: str = ""
    confidence: float = 0.0
    expected_benefit: str = ""
    risk: str = "LOW"
    reversible: bool = True
    requires_admin: bool = False
    action: RecommendationAction = RecommendationAction.PENDING
    created_at: float = 0.0
    expires_at: float = 0.0
    telemetry_evidence: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self):
        if not self.recommendation_id:
            self.recommendation_id = f"rec_{uuid.uuid4().hex[:8]}"
        if self.created_at == 0.0:
            self.created_at = time.time()

    @property
    def is_expired(self) -> bool:
        return self.expires_at > 0 and time.time() > self.expires_at

    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "title": self.title,
            "reason": self.reason,
            "condition": self.condition.to_dict() if self.condition else None,
            "optimization_id": self.optimization_id,
            "optimization_name": self.optimization_name,
            "confidence": self.confidence,
            "expected_benefit": self.expected_benefit,
            "risk": self.risk,
            "reversible": self.reversible,
            "requires_admin": self.requires_admin,
            "action": self.action.value,
            "created_at": self.created_at,
            "telemetry_evidence": self.telemetry_evidence,
        }


@dataclass
class ImpactResult:
    """Result of post-optimization impact evaluation."""
    recommendation_id: str = ""
    classification: ImpactClassification = ImpactClassification.INSUFFICIENT_DATA
    before_metrics: Dict[str, Optional[float]] = field(default_factory=dict)
    after_metrics: Dict[str, Optional[float]] = field(default_factory=dict)
    deltas: Dict[str, Optional[float]] = field(default_factory=dict)
    explanation: str = ""
    rolled_back: bool = False
    rollback_reason: str = ""

    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "classification": self.classification.value,
            "before_metrics": self.before_metrics,
            "after_metrics": self.after_metrics,
            "deltas": self.deltas,
            "explanation": self.explanation,
            "rolled_back": self.rolled_back,
            "rollback_reason": self.rollback_reason,
        }


@dataclass
class AdaptiveRecord:
    """A complete record of one adaptive optimization cycle."""
    record_id: str = ""
    session_id: str = ""
    timestamp: float = 0.0
    condition: Optional[SustainedCondition] = None
    recommendation: Optional[AdaptiveRecommendation] = None
    impact: Optional[ImpactResult] = None
    approved: bool = False
    applied: bool = False

    def __post_init__(self):
        if not self.record_id:
            self.record_id = f"arec_{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "record_id": self.record_id,
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "condition": self.condition.to_dict() if self.condition else None,
            "recommendation": self.recommendation.to_dict() if self.recommendation else None,
            "impact": self.impact.to_dict() if self.impact else None,
            "approved": self.approved,
            "applied": self.applied,
        }


# ══════════════════════════════════════════════════════════════
#  TELEMETRY WINDOW
# ══════════════════════════════════════════════════════════════


class TelemetryWindow:
    """Bounded rolling window of telemetry observations.

    Maintains a fixed-size deque of TelemetryPoint objects.
    Provides rolling averages, variance, and baseline comparison.
    """

    def __init__(self, max_samples: int = 120, max_seconds: float = 120.0):
        self._max_samples = max_samples
        self._max_seconds = max_seconds
        self._window: Deque[TelemetryPoint] = deque(maxlen=max_samples)
        self._lock = threading.Lock()

    def add(self, point: TelemetryPoint):
        """Add a telemetry point to the window."""
        if point.timestamp == 0.0:
            point.timestamp = time.time()
        with self._lock:
            self._window.append(point)
            self._trim_by_time()

    def _trim_by_time(self):
        """Remove points older than max_seconds."""
        if not self._window:
            return
        cutoff = time.time() - self._max_seconds
        while self._window and self._window[0].timestamp < cutoff:
            self._window.popleft()

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._window)

    def get_samples(self) -> List[TelemetryPoint]:
        """Get a snapshot of current window contents."""
        with self._lock:
            return list(self._window)

    def get_rolling_avg(self, metric: str, last_n: int = 0) -> Optional[float]:
        """Calculate rolling average for a metric."""
        with self._lock:
            samples = list(self._window)
        if last_n > 0:
            samples = samples[-last_n:]
        values = [
            getattr(s, metric) for s in samples
            if getattr(s, metric) is not None
        ]
        if not values:
            return None
        return statistics.mean(values)

    def get_rolling_stdev(self, metric: str, last_n: int = 0) -> Optional[float]:
        """Calculate rolling standard deviation for a metric."""
        with self._lock:
            samples = list(self._window)
        if last_n > 0:
            samples = samples[-last_n:]
        values = [
            getattr(s, metric) for s in samples
            if getattr(s, metric) is not None
        ]
        if len(values) < 2:
            return None
        return statistics.stdev(values)

    def get_recent(self, seconds: float) -> List[TelemetryPoint]:
        """Get points from the last N seconds."""
        cutoff = time.time() - seconds
        with self._lock:
            return [p for p in self._window if p.timestamp >= cutoff]

    def clear(self):
        with self._lock:
            self._window.clear()

    def get_snapshot(self) -> Dict[str, Optional[float]]:
        """Get a summary snapshot of current window state."""
        with self._lock:
            samples = list(self._window)
        if not samples:
            return {}

        snapshot = {}
        for metric in ("cpu_percent", "gpu_percent", "ram_percent", "fps",
                        "frame_time_ms", "gpu_temp", "latency_ms"):
            values = [
                getattr(s, metric) for s in samples
                if getattr(s, metric) is not None
            ]
            if values:
                snapshot[f"avg_{metric}"] = statistics.mean(values)
                snapshot[f"min_{metric}"] = min(values)
                snapshot[f"max_{metric}"] = max(values)
                if len(values) >= 2:
                    snapshot[f"stdev_{metric}"] = statistics.stdev(values)
            else:
                snapshot[f"avg_{metric}"] = None
                snapshot[f"min_{metric}"] = None
                snapshot[f"max_{metric}"] = None
                snapshot[f"stdev_{metric}"] = None

        snapshot["sample_count"] = len(samples)
        return snapshot


# ══════════════════════════════════════════════════════════════
#  COOLDOWN MANAGER
# ══════════════════════════════════════════════════════════════


class CooldownManager:
    """Prevents recommendation spam via cooldowns.

    Tracks per-recommendation-type cooldowns and dismissal history.
    """

    def __init__(self, thresholds: AdaptiveThresholds):
        self._thresholds = thresholds
        self._last_apply: Dict[str, float] = {}  # opt_id -> timestamp
        self._last_dismiss: Dict[str, float] = {}
        self._last_failure: Dict[str, float] = {}
        self._last_recommendation: Dict[str, float] = {}  # condition_type -> timestamp
        self._lock = threading.Lock()

    def can_recommend(self, condition_type: ConditionType, opt_id: str) -> Tuple[bool, str]:
        """Check if we can make a recommendation for this condition/optimization.

        Returns (allowed, reason).
        """
        now = time.time()
        with self._lock:
            # Check same-condition cooldown
            last_rec = self._last_recommendation.get(condition_type.value, 0)
            if now - last_rec < self._thresholds.cooldown_same_recommendation:
                remaining = self._thresholds.cooldown_same_recommendation - (now - last_rec)
                return False, f"Condition {condition_type.value} on cooldown ({remaining:.0f}s remaining)"

            # Check apply cooldown
            last_apply = self._last_apply.get(opt_id, 0)
            if now - last_apply < self._thresholds.cooldown_after_apply:
                remaining = self._thresholds.cooldown_after_apply - (now - last_apply)
                return False, f"Optimization {opt_id} recently applied ({remaining:.0f}s remaining)"

            # Check dismiss cooldown
            last_dismiss = self._last_dismiss.get(opt_id, 0)
            if now - last_dismiss < self._thresholds.cooldown_after_dismiss:
                remaining = self._thresholds.cooldown_after_dismiss - (now - last_dismiss)
                return False, f"Optimization {opt_id} recently dismissed ({remaining:.0f}s remaining)"

            # Check failure cooldown
            last_fail = self._last_failure.get(opt_id, 0)
            if now - last_fail < self._thresholds.cooldown_after_failure:
                remaining = self._thresholds.cooldown_after_failure - (now - last_fail)
                return False, f"Optimization {opt_id} recently failed ({remaining:.0f}s remaining)"

        return True, ""

    def record_apply(self, opt_id: str):
        with self._lock:
            self._last_apply[opt_id] = time.time()

    def record_dismiss(self, opt_id: str):
        with self._lock:
            self._last_dismiss[opt_id] = time.time()

    def record_failure(self, opt_id: str):
        with self._lock:
            self._last_failure[opt_id] = time.time()

    def record_recommendation(self, condition_type: ConditionType):
        with self._lock:
            self._last_recommendation[condition_type.value] = time.time()

    def clear(self):
        with self._lock:
            self._last_apply.clear()
            self._last_dismiss.clear()
            self._last_failure.clear()
            self._last_recommendation.clear()


# ══════════════════════════════════════════════════════════════
#  CONDITION DETECTOR
# ══════════════════════════════════════════════════════════════


class ConditionDetector:
    """Detects sustained performance conditions from telemetry windows.

    Uses hysteresis: separate trigger/recovery thresholds to prevent
    oscillation around a single threshold.
    """

    def __init__(self, thresholds: AdaptiveThresholds):
        self._thresholds = thresholds
        self._active_conditions: Dict[ConditionType, SustainedCondition] = {}

    def detect(self, window: TelemetryWindow, baseline: Optional[Dict[str, float]] = None) -> List[SustainedCondition]:
        """Analyze the telemetry window and return newly detected or updated conditions.

        Uses hysteresis: a condition triggers at one threshold and clears at a
        lower threshold, preventing oscillation.
        """
        now = time.time()
        snapshot = window.get_snapshot()
        sample_count = snapshot.get("sample_count", 0)

        if sample_count < self._thresholds.min_samples_for_condition:
            return []

        detected = []

        # CPU pressure
        avg_cpu = snapshot.get("avg_cpu_percent")
        if avg_cpu is not None:
            cond = self._check_condition(
                ConditionType.CPU_PRESSURE,
                avg_cpu,
                self._thresholds.cpu_trigger,
                self._thresholds.cpu_recovery,
                now, sample_count, snapshot,
                baseline, "cpu_percent", "%",
                "CPU utilization",
            )
            if cond:
                detected.append(cond)

        # GPU pressure
        avg_gpu = snapshot.get("avg_gpu_percent")
        if avg_gpu is not None:
            cond = self._check_condition(
                ConditionType.GPU_PRESSURE,
                avg_gpu,
                self._thresholds.gpu_trigger,
                self._thresholds.gpu_recovery,
                now, sample_count, snapshot,
                baseline, "gpu_percent", "%",
                "GPU utilization",
            )
            if cond:
                detected.append(cond)

        # RAM pressure
        avg_ram = snapshot.get("avg_ram_percent")
        if avg_ram is not None:
            cond = self._check_condition(
                ConditionType.RAM_PRESSURE,
                avg_ram,
                self._thresholds.ram_trigger,
                self._thresholds.ram_recovery,
                now, sample_count, snapshot,
                baseline, "ram_percent", "%",
                "RAM usage",
            )
            if cond:
                detected.append(cond)

        # FPS degradation (compare against baseline)
        avg_fps = snapshot.get("avg_fps")
        if avg_fps is not None and baseline and baseline.get("fps") is not None:
            baseline_fps = baseline["fps"]
            if baseline_fps > 0:
                degradation_pct = ((baseline_fps - avg_fps) / baseline_fps) * 100
                if degradation_pct >= self._thresholds.fps_degradation_pct:
                    cond = self._check_fps_degradation(
                        degradation_pct, avg_fps, baseline_fps,
                        now, sample_count,
                    )
                    if cond:
                        detected.append(cond)
                elif degradation_pct <= self._thresholds.fps_recovery_pct:
                    # FPS recovered — clear condition
                    self._clear_condition(ConditionType.FPS_DEGRADATION)

        # Frame time instability
        avg_ft = snapshot.get("avg_frame_time_ms")
        stdev_ft = snapshot.get("stdev_frame_time_ms")
        if avg_ft is not None and stdev_ft is not None and avg_ft > 0:
            cv = stdev_ft / avg_ft
            if cv >= self._thresholds.frame_time_cv_trigger:
                cond = self._check_frame_time_instability(
                    cv, avg_ft, stdev_ft, now, sample_count,
                )
                if cond:
                    detected.append(cond)
            elif cv <= self._thresholds.frame_time_cv_recovery:
                self._clear_condition(ConditionType.FRAME_TIME_INSTABILITY)

        # Thermal pressure
        avg_temp = snapshot.get("avg_gpu_temp")
        if avg_temp is not None:
            cond = self._check_condition(
                ConditionType.THERMAL_PRESSURE,
                avg_temp,
                self._thresholds.thermal_trigger,
                self._thresholds.thermal_recovery,
                now, sample_count, snapshot,
                baseline, "gpu_temp", "°C",
                "GPU temperature",
            )
            if cond:
                detected.append(cond)

        # Update durations for active conditions
        for ct, cond in list(self._active_conditions.items()):
            if cond.active:
                cond.duration_seconds = now - cond.detected_at

        # Return only conditions that have been sustained long enough
        sustained = [
            c for c in detected
            if c.duration_seconds >= self._thresholds.min_sustained_seconds
            or c.sample_count >= self._thresholds.min_samples_for_condition * 2
        ]

        return sustained

    def _check_condition(
        self,
        condition_type: ConditionType,
        current_value: float,
        trigger: float,
        recovery: float,
        now: float,
        sample_count: int,
        snapshot: Dict,
        baseline: Optional[Dict],
        metric_key: str,
        unit: str,
        metric_name: str,
    ) -> Optional[SustainedCondition]:
        """Check a single metric against trigger/recovery thresholds."""
        baseline_val = baseline.get(metric_key) if baseline else None

        if condition_type in self._active_conditions:
            # Condition already active — check if it recovered
            existing = self._active_conditions[condition_type]
            if current_value <= recovery:
                # Recovered
                existing.active = False
                del self._active_conditions[condition_type]
                return None
            # Still active — update values
            existing.current_value = current_value
            existing.duration_seconds = now - existing.detected_at
            existing.sample_count = sample_count
            existing.evidence = [f"{metric_name}: {current_value:.1f}{unit} (trigger: {trigger}{unit})"]
            return existing

        # New condition
        if current_value >= trigger:
            evidence = [f"{metric_name}: {current_value:.1f}{unit} (trigger: {trigger}{unit})"]
            if baseline_val is not None:
                deviation = current_value - baseline_val
                evidence.append(f"Baseline: {baseline_val:.1f}{unit} (deviation: +{deviation:.1f}{unit})")

            cond = SustainedCondition(
                condition_type=condition_type,
                detected_at=now,
                duration_seconds=0.0,
                sample_count=sample_count,
                current_value=current_value,
                baseline_value=baseline_val or 0.0,
                threshold=trigger,
                confidence=min(50 + sample_count, 100),
                evidence=evidence,
            )
            self._active_conditions[condition_type] = cond
            return cond

        return None

    def _check_fps_degradation(
        self, degradation_pct: float, current_fps: float,
        baseline_fps: float, now: float, sample_count: int,
    ) -> Optional[SustainedCondition]:
        """Check FPS degradation against baseline."""
        ct = ConditionType.FPS_DEGRADATION
        if ct in self._active_conditions:
            existing = self._active_conditions[ct]
            if degradation_pct <= self._thresholds.fps_recovery_pct:
                existing.active = False
                del self._active_conditions[ct]
                return None
            existing.current_value = current_fps
            existing.baseline_value = baseline_fps
            existing.duration_seconds = now - existing.detected_at
            existing.sample_count = sample_count
            existing.evidence = [
                f"FPS: {current_fps:.0f} (baseline: {baseline_fps:.0f}, degradation: {degradation_pct:.1f}%)"
            ]
            return existing

        evidence = [
            f"FPS: {current_fps:.0f} (baseline: {baseline_fps:.0f}, degradation: {degradation_pct:.1f}%)"
        ]
        cond = SustainedCondition(
            condition_type=ct,
            detected_at=now,
            duration_seconds=0.0,
            sample_count=sample_count,
            current_value=current_fps,
            baseline_value=baseline_fps,
            threshold=self._thresholds.fps_degradation_pct,
            confidence=min(50 + sample_count, 100),
            evidence=evidence,
        )
        self._active_conditions[ct] = cond
        return cond

    def _check_frame_time_instability(
        self, cv: float, avg_ft: float, stdev_ft: float,
        now: float, sample_count: int,
    ) -> Optional[SustainedCondition]:
        """Check frame time instability."""
        ct = ConditionType.FRAME_TIME_INSTABILITY
        if ct in self._active_conditions:
            existing = self._active_conditions[ct]
            if cv <= self._thresholds.frame_time_cv_recovery:
                existing.active = False
                del self._active_conditions[ct]
                return None
            existing.current_value = cv
            existing.duration_seconds = now - existing.detected_at
            existing.sample_count = sample_count
            existing.evidence = [f"Frame time CV: {cv:.2f} (avg: {avg_ft:.1f}ms, stdev: {stdev_ft:.1f}ms)"]
            return existing

        evidence = [f"Frame time CV: {cv:.2f} (avg: {avg_ft:.1f}ms, stdev: {stdev_ft:.1f}ms)"]
        cond = SustainedCondition(
            condition_type=ct,
            detected_at=now,
            duration_seconds=0.0,
            sample_count=sample_count,
            current_value=cv,
            baseline_value=0.0,
            threshold=self._thresholds.frame_time_cv_trigger,
            confidence=min(50 + sample_count, 100),
            evidence=evidence,
        )
        self._active_conditions[ct] = cond
        return cond

    def _clear_condition(self, condition_type: ConditionType):
        if condition_type in self._active_conditions:
            self._active_conditions[condition_type].active = False
            del self._active_conditions[condition_type]

    def clear_all(self):
        for cond in self._active_conditions.values():
            cond.active = False
        self._active_conditions.clear()

    @property
    def active_conditions(self) -> Dict[ConditionType, SustainedCondition]:
        return dict(self._active_conditions)


# ══════════════════════════════════════════════════════════════
#  RECOMMENDATION GENERATOR
# ══════════════════════════════════════════════════════════════


# Condition → recommended optimization mapping
CONDITION_OPTIMIZATIONS = {
    ConditionType.CPU_PRESSURE: [
        ("emulator_priority", "Raise emulator process priority", "LOW", True),
        ("background_load", "Reduce background CPU consumption", "LOW", True),
        ("power_plan", "Switch to high-performance power plan", "LOW", True),
    ],
    ConditionType.GPU_PRESSURE: [
        ("background_load", "Reduce background GPU/resource contention", "LOW", True),
    ],
    ConditionType.RAM_PRESSURE: [
        ("memory_analysis", "Analyze and identify memory-heavy processes", "LOW", True),
        ("background_load", "Reduce background memory consumption", "LOW", True),
    ],
    ConditionType.FPS_DEGRADATION: [
        ("emulator_priority", "Raise emulator priority for better frame delivery", "LOW", True),
        ("power_plan", "Ensure high-performance power plan", "LOW", True),
        ("background_load", "Reduce background interference", "LOW", True),
    ],
    ConditionType.FRAME_TIME_INSTABILITY: [
        ("emulator_priority", "Raise emulator priority for consistent frame timing", "LOW", True),
        ("background_load", "Reduce background scheduling interference", "LOW", True),
    ],
    ConditionType.THERMAL_PRESSURE: [
        ("background_load", "Reduce background load to lower thermal pressure", "LOW", True),
    ],
    ConditionType.BACKGROUND_PRESSURE: [
        ("background_load", "Reduce unnecessary background activity", "LOW", True),
    ],
}


def generate_recommendations(
    conditions: List[SustainedCondition],
    cooldown_manager: CooldownManager,
    baseline: Optional[Dict[str, float]] = None,
    applied_optimizations: Optional[Dict[str, str]] = None,
) -> List[AdaptiveRecommendation]:
    """Generate adaptive recommendations from detected conditions.

    Each recommendation includes:
    - title and reason (explainable)
    - telemetry evidence
    - confidence
    - expected benefit
    - risk level
    - cooldown check
    """
    if applied_optimizations is None:
        applied_optimizations = {}

    recommendations = []
    seen_opts = set()  # Prevent duplicate recommendations per cycle

    for condition in conditions:
        ct = condition.condition_type
        opt_specs = CONDITION_OPTIMIZATIONS.get(ct, [])

        for opt_id, benefit, risk, reversible in opt_specs:
            # Skip if already applied
            if opt_id in applied_optimizations and applied_optimizations[opt_id] in (
                "APPLIED", "VERIFIED", "ALREADY_OPTIMAL",
            ):
                continue

            # Skip duplicates in this cycle
            if opt_id in seen_opts:
                continue

            # Check cooldown
            allowed, reason = cooldown_manager.can_recommend(ct, opt_id)
            if not allowed:
                logger.debug(f"Cooldown blocked {opt_id}: {reason}")
                continue

            seen_opts.add(opt_id)

            # Build recommendation
            title = f"Adaptive: {benefit}"
            reason_text = (
                f"Sustained {ct.value.replace('_', ' ').lower()} detected "
                f"({condition.duration_seconds:.0f}s, "
                f"{condition.sample_count} samples). "
                f"Current: {condition.current_value:.1f}, "
                f"threshold: {condition.threshold:.1f}."
            )
            if condition.baseline_value:
                reason_text += f" Baseline: {condition.baseline_value:.1f}."

            telemetry_evidence = {
                "condition_type": ct.value,
                "current_value": condition.current_value,
                "baseline_value": condition.baseline_value,
                "threshold": condition.threshold,
                "duration_seconds": condition.duration_seconds,
                "sample_count": condition.sample_count,
            }

            rec = AdaptiveRecommendation(
                title=title,
                reason=reason_text,
                condition=condition,
                optimization_id=opt_id,
                optimization_name=benefit,
                confidence=condition.confidence,
                expected_benefit=benefit,
                risk=risk,
                reversible=reversible,
                requires_admin=opt_id in ("emulator_priority", "cpu_affinity"),
                telemetry_evidence=telemetry_evidence,
                expires_at=time.time() + 300,  # 5 minute validity
            )
            recommendations.append(rec)

    return recommendations


# ══════════════════════════════════════════════════════════════
#  IMPACT EVALUATOR
# ══════════════════════════════════════════════════════════════


class ImpactEvaluator:
    """Evaluates the impact of an applied adaptive optimization.

    Compares before/after telemetry to classify as:
    HELPED / NO_SIGNIFICANT_CHANGE / HARMFUL / INSUFFICIENT_DATA
    """

    def __init__(self, thresholds: AdaptiveThresholds):
        self._thresholds = thresholds

    def evaluate(
        self,
        before_window: TelemetryPoint,
        after_window: TelemetryWindow,
        recommendation: AdaptiveRecommendation,
    ) -> ImpactResult:
        """Evaluate impact by comparing before snapshot with after window."""
        after_snapshot = after_window.get_snapshot()
        sample_count = after_snapshot.get("sample_count", 0)

        if sample_count < 3:
            return ImpactResult(
                recommendation_id=recommendation.recommendation_id,
                classification=ImpactClassification.INSUFFICIENT_DATA,
                explanation=f"Only {sample_count} post-optimization samples (need ≥3).",
            )

        before = {
            "cpu": before_window.cpu_percent,
            "gpu": before_window.gpu_percent,
            "ram": before_window.ram_percent,
            "fps": before_window.fps,
            "frame_time": before_window.frame_time_ms,
            "gpu_temp": before_window.gpu_temp,
        }
        after = {
            "cpu": after_snapshot.get("avg_cpu_percent"),
            "gpu": after_snapshot.get("avg_gpu_percent"),
            "ram": after_snapshot.get("avg_ram_percent"),
            "fps": after_snapshot.get("avg_fps"),
            "frame_time": after_snapshot.get("avg_frame_time_ms"),
            "gpu_temp": after_snapshot.get("avg_gpu_temp"),
        }

        deltas = {}
        for key in before:
            b = before[key]
            a = after[key]
            if b is not None and a is not None:
                deltas[key] = a - b
            else:
                deltas[key] = None

        # Classify impact
        improvements = 0
        degradations = 0
        total_checked = 0

        # FPS: higher is better
        if deltas.get("fps") is not None:
            total_checked += 1
            fps_delta = deltas["fps"]
            before_fps = before["fps"]
            if before_fps and before_fps > 0:
                pct_change = (fps_delta / before_fps) * 100
                if pct_change >= self._thresholds.impact_improvement_pct:
                    improvements += 1
                elif pct_change <= -self._thresholds.impact_harm_pct:
                    degradations += 1

        # CPU: lower is better (after optimization)
        if deltas.get("cpu") is not None:
            total_checked += 1
            cpu_delta = deltas["cpu"]
            if cpu_delta <= -3:
                improvements += 1
            elif cpu_delta >= 5:
                degradations += 1

        # Frame time: lower is better
        if deltas.get("frame_time") is not None:
            total_checked += 1
            ft_delta = deltas["frame_time"]
            if ft_delta <= -1.0:
                improvements += 1
            elif ft_delta >= 2.0:
                degradations += 1

        # GPU temp: lower is better
        if deltas.get("gpu_temp") is not None:
            total_checked += 1
            temp_delta = deltas["gpu_temp"]
            if temp_delta <= -2:
                improvements += 1
            elif temp_delta >= 3:
                degradations += 1

        # Classify
        if total_checked == 0:
            classification = ImpactClassification.INSUFFICIENT_DATA
            explanation = "No comparable metrics available."
        elif degradations > 0 and degradations >= improvements:
            classification = ImpactClassification.HARMFUL
            explanation = f"Degradation detected in {degradations} metric(s)."
        elif improvements > 0 and improvements > degradations:
            classification = ImpactClassification.HELPED
            explanation = f"Improvement detected in {improvements} metric(s)."
        else:
            classification = ImpactClassification.NO_SIGNIFICANT_CHANGE
            explanation = "No significant change detected."

        # Add metric details
        details = []
        for key in ("fps", "cpu", "frame_time", "gpu_temp"):
            d = deltas.get(key)
            if d is not None:
                sign = "+" if d >= 0 else ""
                details.append(f"{key}: {sign}{d:.1f}")
        if details:
            explanation += f" ({', '.join(details)})"

        return ImpactResult(
            recommendation_id=recommendation.recommendation_id,
            classification=classification,
            before_metrics=before,
            after_metrics=after,
            deltas=deltas,
            explanation=explanation,
        )


# ══════════════════════════════════════════════════════════════
#  ADAPTIVE ENGINE (main orchestrator)
# ══════════════════════════════════════════════════════════════


class AdaptiveEngine:
    """Main adaptive optimization engine.

    Orchestrates:
      OBSERVE → DETECT → RECOMMEND → APPROVAL → APPLY → VERIFY
      → OBSERVE → IMPACT → KEEP/ROLLBACK

    Integrates with:
      - TelemetryWindow (rolling buffer)
      - ConditionDetector (sustained conditions)
      - CooldownManager (anti-spam)
      - ImpactEvaluator (before/after)
      - AdaptiveOptimizer (existing state classification + execution)
      - GamingLifecycleManager (session integration)
    """

    def __init__(self, thresholds: Optional[AdaptiveThresholds] = None):
        self._thresholds = thresholds or AdaptiveThresholds()
        self._window = TelemetryWindow(
            max_samples=self._thresholds.max_window_samples,
            max_seconds=self._thresholds.window_seconds,
        )
        self._condition_detector = ConditionDetector(self._thresholds)
        self._cooldown_manager = CooldownManager(self._thresholds)
        self._impact_evaluator = ImpactEvaluator(self._thresholds)

        self._state = AdaptiveEngineState.IDLE
        self._lock = threading.Lock()
        self._session_id: str = ""
        self._baseline: Optional[Dict[str, float]] = None
        self._active_recommendation: Optional[AdaptiveRecommendation] = None
        self._pending_before: Optional[TelemetryPoint] = None
        self._impact_observation_start: float = 0.0
        self._applied_optimizations: Dict[str, str] = {}
        self._records: List[AdaptiveRecord] = []
        self._callbacks: List = []

        # Persistence
        self._history_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "adaptive_sessions",
        )

    @property
    def state(self) -> AdaptiveEngineState:
        return self._state

    @property
    def window(self) -> TelemetryWindow:
        return self._window

    @property
    def active_recommendation(self) -> Optional[AdaptiveRecommendation]:
        return self._active_recommendation

    @property
    def active_conditions(self) -> Dict[ConditionType, SustainedCondition]:
        return self._condition_detector.active_conditions

    @property
    def records(self) -> List[AdaptiveRecord]:
        return list(self._records)

    def on_state_change(self, callback):
        self._callbacks.append(callback)

    def _set_state(self, state: AdaptiveEngineState):
        self._state = state
        for cb in self._callbacks:
            try:
                cb(state)
            except Exception:
                pass

    # ── Session Lifecycle ──────────────────────────────────────

    def start_session(
        self,
        session_id: str,
        baseline: Optional[Dict[str, float]] = None,
    ):
        """Start adaptive optimization for a gaming session."""
        with self._lock:
            if self._state != AdaptiveEngineState.IDLE:
                logger.warning("Adaptive engine already active")
                return
            self._session_id = session_id
            self._baseline = baseline or {}
            self._active_recommendation = None
            self._pending_before = None
            self._impact_observation_start: float = 0.0
            self._applied_optimizations.clear()
            self._records.clear()
            self._window.clear()
            self._condition_detector.clear_all()
            self._cooldown_manager.clear()
            self._set_state(AdaptiveEngineState.MONITORING)
        logger.info(f"Adaptive engine started for session {session_id}")

    def stop_session(self) -> List[AdaptiveRecord]:
        """Stop adaptive optimization and return session records."""
        with self._lock:
            if self._state == AdaptiveEngineState.IDLE:
                return []
            self._set_state(AdaptiveEngineState.STOPPED)
            # Cancel pending recommendation
            if self._active_recommendation:
                self._active_recommendation.action = RecommendationAction.DISMISS
                self._active_recommendation = None

        records = list(self._records)
        self._save_history(records)

        self._set_state(AdaptiveEngineState.IDLE)
        logger.info(
            f"Adaptive engine stopped: {len(records)} records, "
            f"{len(self._applied_optimizations)} optimizations applied"
        )
        return records

    # ── Telemetry Ingestion ────────────────────────────────────

    def ingest(self, point: TelemetryPoint):
        """Ingest a telemetry point into the rolling window."""
        if self._state == AdaptiveEngineState.IDLE:
            return

        self._window.add(point)

    # ── Analysis Cycle ─────────────────────────────────────────

    def analyze(self) -> List[AdaptiveRecommendation]:
        """Run one analysis cycle.

        Must be called periodically (not from GUI timer — use a worker).
        Returns new recommendations if conditions are sustained.
        """
        if self._state in (AdaptiveEngineState.IDLE, AdaptiveEngineState.STOPPED):
            return []

        # Don't generate new recommendations while one is pending
        if self._active_recommendation and not self._active_recommendation.is_expired:
            return []

        # Detect sustained conditions
        conditions = self._condition_detector.detect(self._window, self._baseline)

        if not conditions:
            return []

        # Generate recommendations
        recs = generate_recommendations(
            conditions,
            self._cooldown_manager,
            self._baseline,
            self._applied_optimizations,
        )

        if recs:
            # Pick the highest-confidence recommendation
            best = max(recs, key=lambda r: r.confidence)
            self._active_recommendation = best
            self._set_state(AdaptiveEngineState.AWAITING_APPROVAL)
            logger.info(f"Adaptive recommendation: {best.title} (confidence={best.confidence}%)")
            return [best]

        return []

    # ── User Approval ──────────────────────────────────────────

    def approve(self, recommendation_id: str) -> bool:
        """User approves a recommendation.

        Returns True if the recommendation was found and approved.
        """
        with self._lock:
            if self._state != AdaptiveEngineState.AWAITING_APPROVAL:
                return False

            if not self._active_recommendation:
                return False

            if self._active_recommendation.recommendation_id != recommendation_id:
                return False

            self._active_recommendation.action = RecommendationAction.APPLY
            self._set_state(AdaptiveEngineState.APPLYING)
            return True

    def dismiss(self, recommendation_id: str) -> bool:
        """User dismisses a recommendation."""
        with self._lock:
            if not self._active_recommendation:
                return False

            if self._active_recommendation.recommendation_id != recommendation_id:
                return False

            self._active_recommendation.action = RecommendationAction.DISMISS
            self._cooldown_manager.record_dismiss(self._active_recommendation.optimization_id)
            self._active_recommendation = None
            self._set_state(AdaptiveEngineState.MONITORING)
            return True

    # ── Apply Optimization ─────────────────────────────────────

    def apply_recommendation(self) -> Optional[ImpactResult]:
        """Apply the approved recommendation.

        Uses the existing AdaptiveOptimizer infrastructure.
        After apply, transitions to OBSERVING_IMPACT for deferred evaluation.
        Returns None immediately; call check_impact() later for result.
        """
        with self._lock:
            rec = self._active_recommendation
            if not rec or rec.action != RecommendationAction.APPLY:
                return None

        # Capture before-state
        snapshot = self._window.get_snapshot()
        avg_cpu = snapshot.get("avg_cpu_percent")
        avg_gpu = snapshot.get("avg_gpu_percent")
        avg_ram = snapshot.get("avg_ram_percent")
        avg_fps = snapshot.get("avg_fps")
        avg_ft = snapshot.get("avg_frame_time_ms")
        avg_temp = snapshot.get("avg_gpu_temp")

        with self._lock:
            self._pending_before = TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=avg_cpu,
                gpu_percent=avg_gpu,
                ram_percent=avg_ram,
                fps=avg_fps,
                frame_time_ms=avg_ft,
                gpu_temp=avg_temp,
            )

        # Execute via existing optimizer
        try:
            from app.core.optimizations import get_optimization_by_id

            opt = get_optimization_by_id(rec.optimization_id)
            if not opt:
                self._finish_apply_failure(rec, "optimization not found")
                return None

            # Check current state
            check = opt.check()
            if check.status.value in ("ALREADY OPTIMAL",):
                self._applied_optimizations[rec.optimization_id] = "ALREADY_OPTIMAL"
                rec.action = RecommendationAction.DISMISS
                with self._lock:
                    self._active_recommendation = None
                    self._set_state(AdaptiveEngineState.MONITORING)
                return None
            elif check.status.value == "REQUIRES_ADMIN":
                self._applied_optimizations[rec.optimization_id] = "REQUIRES_ADMIN"
                rec.action = RecommendationAction.DISMISS
                with self._lock:
                    self._active_recommendation = None
                    self._set_state(AdaptiveEngineState.MONITORING)
                return None
            elif check.status.value not in ("OPTIMIZABLE",):
                rec.action = RecommendationAction.DISMISS
                with self._lock:
                    self._active_recommendation = None
                    self._set_state(AdaptiveEngineState.MONITORING)
                return None

            # Snapshot before applying
            try:
                opt.snapshot()
            except Exception as e:
                logger.debug(f"Snapshot failed: {e}")

            # Apply
            apply_result = opt.apply()
            if apply_result.status.value != "APPLIED":
                self._finish_apply_failure(rec, "apply failed")
                return None

            # Verify (no sleep — verification reads the current state)
            verified = opt.verify()
            if not verified:
                self._finish_apply_failure(rec, "verification failed")
                return None

            # Record success
            self._applied_optimizations[rec.optimization_id] = "APPLIED"
            self._cooldown_manager.record_apply(rec.optimization_id)

            # Transition to deferred impact observation
            with self._lock:
                self._impact_observation_start = time.time()
                self._set_state(AdaptiveEngineState.OBSERVING_IMPACT)

            logger.info(
                f"Adaptive optimization applied: {rec.optimization_name}. "
                f"Observing impact for {self._thresholds.impact_observation_seconds}s."
            )
            return None  # Impact evaluated later via check_impact()

        except Exception as e:
            logger.error(f"Adaptive apply failed: {e}")
            self._finish_apply_failure(rec, f"exception: {e}")
            return None

    def _finish_apply_failure(self, rec: AdaptiveRecommendation, reason: str):
        """Common failure cleanup for apply_recommendation."""
        rec.action = RecommendationAction.DISMISS
        self._cooldown_manager.record_failure(rec.optimization_id)
        with self._lock:
            self._active_recommendation = None
            self._set_state(AdaptiveEngineState.MONITORING)

    def check_impact(self) -> Optional[ImpactResult]:
        """Check if deferred impact observation is complete.

        Call this periodically from the background worker.
        Evaluates impact after the observation window has elapsed.
        """
        with self._lock:
            if self._state != AdaptiveEngineState.OBSERVING_IMPACT:
                return None
            if not self._pending_before:
                self._set_state(AdaptiveEngineState.MONITORING)
                return None
            rec = self._active_recommendation
            obs_start = self._impact_observation_start

        # Check if observation window has elapsed
        elapsed = time.time() - obs_start
        if elapsed < self._thresholds.impact_observation_seconds:
            return None  # Still observing

        # Evaluate
        impact = self._observe_impact(rec)

        # Record
        record = AdaptiveRecord(
            session_id=self._session_id,
            condition=rec.condition if rec else None,
            recommendation=rec,
            impact=impact,
            approved=True,
            applied=True,
        )
        with self._lock:
            self._records.append(record)

        # Check if harmful → rollback
        if impact and impact.classification == ImpactClassification.HARMFUL:
            self._rollback(rec, impact)

        # Done observing
        with self._lock:
            self._active_recommendation = None
            self._pending_before = None
            self._set_state(AdaptiveEngineState.MONITORING)

        return impact

    def _observe_impact(self, rec: Optional[AdaptiveRecommendation]) -> ImpactResult:
        """Evaluate post-optimization impact from the telemetry window.

        Called by check_impact() after the observation window has elapsed.
        """
        if not rec:
            return ImpactResult(
                recommendation_id="",
                classification=ImpactClassification.INSUFFICIENT_DATA,
                explanation="No recommendation to evaluate.",
            )
        if not self._pending_before:
            return ImpactResult(
                recommendation_id=rec.recommendation_id,
                classification=ImpactClassification.INSUFFICIENT_DATA,
                explanation="No before-state captured.",
            )
        return self._impact_evaluator.evaluate(
            self._pending_before,
            self._window,
            rec,
        )

    def _rollback(self, rec: AdaptiveRecommendation, impact: ImpactResult):
        """Rollback a harmful optimization."""
        with self._lock:
            self._set_state(AdaptiveEngineState.ROLLING_BACK)

        try:
            from app.core.optimizations import get_optimization_by_id
            opt = get_optimization_by_id(rec.optimization_id)
            if opt:
                # Try to restore from snapshot
                from app.core.rollback import rollback_engine
                from app.core.snapshot import snapshot_manager

                # Find the most recent snapshot for this optimization
                snapshots = snapshot_manager.list_snapshots()
                for snap in reversed(snapshots):
                    if hasattr(snap, 'optimization_id') and snap.optimization_id == rec.optimization_id:
                        result = rollback_engine.rollback(snap)
                        if result.success:
                            impact.rolled_back = True
                            impact.rollback_reason = result.message
                            self._applied_optimizations[rec.optimization_id] = "ROLLED_BACK"
                            logger.info(f"Rolled back {rec.optimization_name}: {result.message}")
                        else:
                            impact.rollback_reason = f"Rollback failed: {result.message}"
                            logger.warning(f"Rollback failed for {rec.optimization_name}")
                        break

            # Record the rollback
            record = AdaptiveRecord(
                session_id=self._session_id,
                condition=rec.condition,
                recommendation=rec,
                impact=impact,
                approved=True,
                applied=True,
            )
            with self._lock:
                self._records.append(record)

        except Exception as e:
            logger.error(f"Rollback error: {e}")
            impact.rollback_reason = f"Rollback exception: {e}"

        with self._lock:
            self._set_state(AdaptiveEngineState.MONITORING)

    # ── Persistence ────────────────────────────────────────────

    def _save_history(self, records: List[AdaptiveRecord]):
        """Persist adaptive records bounded."""
        try:
            os.makedirs(self._history_dir, exist_ok=True)
            for record in records:
                filepath = os.path.join(self._history_dir, f"{record.record_id}.json")
                with open(filepath, "w", encoding="utf-8") as f:
                    json.dump(record.to_dict(), f, indent=2, default=str)

            # Trim old records
            files = sorted(
                [f for f in os.listdir(self._history_dir) if f.endswith(".json")],
                key=lambda f: os.path.getmtime(os.path.join(self._history_dir, f)),
                reverse=True,
            )
            for old_file in files[100:]:
                try:
                    os.remove(os.path.join(self._history_dir, old_file))
                except Exception:
                    pass
        except Exception as e:
            logger.debug(f"Failed to save adaptive history: {e}")

    # ── UI State ───────────────────────────────────────────────

    def get_ui_state(self) -> Dict[str, Any]:
        """Get current engine state for UI display."""
        snapshot = self._window.get_snapshot()
        conditions = self._condition_detector.active_conditions
        rec = self._active_recommendation

        return {
            "state": self._state.value,
            "session_id": self._session_id,
            "sample_count": snapshot.get("sample_count", 0),
            "conditions": {
                ct.value: {
                    "duration": c.duration_seconds,
                    "current": c.current_value,
                    "baseline": c.baseline_value,
                    "confidence": c.confidence,
                }
                for ct, c in conditions.items()
            },
            "recommendation": rec.to_dict() if rec else None,
            "applied_count": len([
                v for v in self._applied_optimizations.values()
                if v == "APPLIED"
            ]),
            "total_records": len(self._records),
        }


# ── Singleton ────────────────────────────────────────────────

adaptive_engine = AdaptiveEngine()
