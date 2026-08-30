"""
Evidence-Based Optimization Recommendation Engine — Phase 35.

Analyzes real measured telemetry and existing optimization status to produce
structured, evidence-backed recommendations.

STRICTLY ANALYSIS/RECOMMENDATION — never modifies system state.
"""

import statistics
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.performance.telemetry_models import (
    BottleneckType,
    TelemetrySample,
)
from app.utils.logger import get_logger

logger = get_logger("core.recommendation_engine")


# ── Enums ────────────────────────────────────────────────────────

class RecommendationPriority(Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"
    ALREADY_OPTIMAL = "ALREADY_OPTIMAL"
    REQUIRES_ADMIN = "REQUIRES_ADMIN"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    RECOMMENDATION_ONLY = "RECOMMENDATION_ONLY"


class DataQuality(Enum):
    MEASURED = "MEASURED"
    INFERRED = "INFERRED"
    RECOMMENDED = "RECOMMENDED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class EvidencePoint:
    """A single piece of evidence supporting a recommendation."""
    metric: str = ""
    measured_value: Optional[float] = None
    threshold: Optional[float] = None
    unit: str = ""
    quality: DataQuality = DataQuality.MEASURED

    def to_dict(self) -> dict:
        return {
            "metric": self.metric,
            "measured_value": self.measured_value,
            "threshold": self.threshold,
            "unit": self.unit,
            "quality": self.quality.value,
        }


@dataclass
class Recommendation:
    """A single evidence-based optimization recommendation."""
    recommendation_id: str = ""
    optimization_id: str = ""
    optimization_name: str = ""
    priority: RecommendationPriority = RecommendationPriority.MEDIUM
    confidence: int = 0  # 0-100
    reason: str = ""
    evidence: List[EvidencePoint] = field(default_factory=list)
    expected_area: str = ""
    safety: str = ""  # SAFE, REQUIRES_ADMIN, RECOMMENDATION_ONLY
    current_state: str = ""
    action: str = ""  # APPLY, REVIEW, MONITOR, NONE
    historical_evidence: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "recommendation_id": self.recommendation_id,
            "optimization_id": self.optimization_id,
            "optimization_name": self.optimization_name,
            "priority": self.priority.value,
            "confidence": self.confidence,
            "reason": self.reason,
            "evidence": [e.to_dict() for e in self.evidence],
            "expected_area": self.expected_area,
            "safety": self.safety,
            "current_state": self.current_state,
            "action": self.action,
            "historical_evidence": self.historical_evidence,
        }


@dataclass
class RecommendationSession:
    """A complete recommendation session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    target_name: str = ""
    target_pid: int = 0

    # Bottleneck
    bottleneck: str = ""
    bottleneck_confidence: int = 0
    bottleneck_evidence: List[str] = field(default_factory=list)

    # Telemetry summary
    sample_count: int = 0
    duration_seconds: float = 0.0
    telemetry_quality: DataQuality = DataQuality.NOT_AVAILABLE

    # Recommendations
    recommendations: List[Recommendation] = field(default_factory=list)

    # Conflict
    conflict_detected: bool = False
    conflict_description: str = ""

    def get_top_recommendations(self, count: int = 5) -> List[Recommendation]:
        """Get top N recommendations sorted by confidence."""
        actionable = [
            r for r in self.recommendations
            if r.priority not in (
                RecommendationPriority.ALREADY_OPTIMAL,
                RecommendationPriority.NOT_AVAILABLE,
            )
        ]
        actionable.sort(key=lambda r: r.confidence, reverse=True)
        return actionable[:count]

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "bottleneck": self.bottleneck,
            "bottleneck_confidence": self.bottleneck_confidence,
            "sample_count": self.sample_count,
            "duration_seconds": self.duration_seconds,
            "telemetry_quality": self.telemetry_quality.value,
            "recommendation_count": len(self.recommendations),
            "conflict_detected": self.conflict_detected,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


# ── Confidence thresholds ────────────────────────────────────────

HIGH_CONFIDENCE_MIN_SAMPLES = 30
MODERATE_CONFIDENCE_MIN_SAMPLES = 10
# Below 10 = LOW


# ── Bottleneck → Optimization mapping ────────────────────────────
# Each bottleneck type maps to a list of (opt_id, priority) tuples

BOTTLENECK_OPTIMIZATION_MAP = {
    BottleneckType.CPU_BOUND: [
        ("emulator_priority", RecommendationPriority.HIGH),
        ("power_plan", RecommendationPriority.MEDIUM),
        ("background_load", RecommendationPriority.MEDIUM),
        ("cpu_affinity", RecommendationPriority.LOW),
    ],
    BottleneckType.GPU_BOUND: [
        # GPU is saturated — limited software optimization available
        ("memory_analysis", RecommendationPriority.LOW),
        ("background_load", RecommendationPriority.LOW),
    ],
    BottleneckType.MEMORY_BOUND: [
        ("memory_analysis", RecommendationPriority.HIGH),
        ("background_load", RecommendationPriority.HIGH),
    ],
    BottleneckType.THERMAL_LIMITED: [
        ("power_plan", RecommendationPriority.MEDIUM),
        ("background_load", RecommendationPriority.LOW),
    ],
    BottleneckType.FRAME_TIME_INSTABILITY: [
        ("emulator_priority", RecommendationPriority.MEDIUM),
        ("power_plan", RecommendationPriority.MEDIUM),
        ("background_load", RecommendationPriority.MEDIUM),
    ],
    BottleneckType.NO_CLEAR_BOTTLENECK: [
        # No aggressive recommendations
    ],
    BottleneckType.INSUFFICIENT_DATA: [],
}

MULTI_RESOURCE_PRESSURE_DESCRIPTION = (
    "Multiple resource constraints detected simultaneously. "
    "Recommendations are provided for each constraint."
)


# ── Recommendation rules ─────────────────────────────────────────

OPTIMIZATION_META = {
    "emulator_priority": {
        "name": "Emulator Priority",
        "expected_area": "CPU scheduling for the emulator process",
        "safety": "REQUIRES_ADMIN",
    },
    "power_plan": {
        "name": "Power Plan",
        "expected_area": "CPU/GPU power state management",
        "safety": "SAFE",
    },
    "game_mode": {
        "name": "Game Mode",
        "expected_area": "Windows gaming resource allocation",
        "safety": "SAFE",
    },
    "background_load": {
        "name": "Background Load",
        "expected_area": "Background resource contention",
        "safety": "RECOMMENDATION_ONLY",
    },
    "memory_analysis": {
        "name": "Memory Analysis",
        "expected_area": "System memory pressure",
        "safety": "RECOMMENDATION_ONLY",
    },
    "cpu_affinity": {
        "name": "CPU Affinity",
        "expected_area": "CPU core assignment for the emulator",
        "safety": "REQUIRES_ADMIN",
    },
    "game_bar": {
        "name": "Game Bar",
        "expected_area": "Overlay/background recording overhead",
        "safety": "SAFE",
    },
    "background_recording": {
        "name": "Background Recording",
        "expected_area": "Capture overhead",
        "safety": "SAFE",
    },
    "visual_effects": {
        "name": "Visual Effects",
        "expected_area": "Desktop compositor overhead",
        "safety": "RECOMMENDATION_ONLY",
    },
    "fullscreen_optimization": {
        "name": "Fullscreen Optimization",
        "expected_area": "Display presentation",
        "safety": "RECOMMENDATION_ONLY",
    },
}


# ── Engine ───────────────────────────────────────────────────────

class RecommendationEngine:
    """
    Evidence-based optimization recommendation engine.

    Analyzes real measured telemetry and existing optimization status to
    produce structured, evidence-backed recommendations.

    STRICTLY ANALYSIS/RECOMMENDATION — never modifies system state.
    """

    def __init__(self):
        self._last_session: Optional[RecommendationSession] = None
        self._history: List[RecommendationSession] = []

    @property
    def last_session(self) -> Optional[RecommendationSession]:
        return self._last_session

    @property
    def history(self) -> List[RecommendationSession]:
        return list(self._history)

    def analyze(
        self,
        samples: List[TelemetrySample],
        bottleneck_type: BottleneckType = BottleneckType.INSUFFICIENT_DATA,
        bottleneck_confidence: int = 0,
        bottleneck_evidence: List[str] = None,
        optimization_states: Dict[str, str] = None,
        profile_id: str = "gaming",
        target_name: str = "",
        target_pid: int = 0,
        duration_seconds: float = 0.0,
    ) -> RecommendationSession:
        """
        Analyze telemetry and produce evidence-based recommendations.

        Args:
            samples: Recent telemetry samples
            bottleneck_type: Current bottleneck classification
            bottleneck_confidence: Bottleneck confidence (0-100)
            bottleneck_evidence: Bottleneck evidence strings
            optimization_states: Dict of opt_id -> current status string
            profile_id: Active optimization profile
            target_name: Emulator process name
            target_pid: Emulator PID
            duration_seconds: Telemetry duration

        Returns:
            RecommendationSession with structured recommendations
        """
        if bottleneck_evidence is None:
            bottleneck_evidence = []
        if optimization_states is None:
            optimization_states = {}

        session = RecommendationSession(
            target_name=target_name,
            target_pid=target_pid,
            bottleneck=bottleneck_type.value,
            bottleneck_confidence=bottleneck_confidence,
            bottleneck_evidence=bottleneck_evidence,
            sample_count=len(samples),
            duration_seconds=duration_seconds,
        )

        # Determine telemetry quality
        session.telemetry_quality = self._assess_data_quality(samples, duration_seconds)

        # Detect multi-resource pressure
        conflicts = self._detect_conflicts(samples)
        if len(conflicts) > 1:
            session.conflict_detected = True
            session.conflict_description = MULTI_RESOURCE_PRESSURE_DESCRIPTION

        # Build recommendations based on bottleneck
        recommendations = []

        # 1. Bottleneck-specific recommendations
        bottleneck_recs = self._bottleneck_recommendations(
            bottleneck_type, samples, optimization_states, profile_id
        )
        recommendations.extend(bottleneck_recs)

        # 2. Always check game_mode
        if "game_mode" not in [r.optimization_id for r in recommendations]:
            game_mode_rec = self._evaluate_optimization(
                "game_mode", samples, optimization_states, profile_id
            )
            if game_mode_rec:
                recommendations.append(game_mode_rec)

        # 3. Check memory pressure specifically
        memory_rec = self._evaluate_memory_pressure(samples, optimization_states)
        if memory_rec and "memory_analysis" not in [r.optimization_id for r in recommendations]:
            recommendations.append(memory_rec)

        # 4. Filter by profile — only recommend optimizations in the profile
        recommendations = self._filter_by_profile(recommendations, profile_id)

        # 5. Sort by confidence
        recommendations.sort(key=lambda r: r.confidence, reverse=True)

        # 6. Add historical context if available
        self._add_historical_context(recommendations)

        session.recommendations = recommendations

        self._last_session = session
        self._history.append(session)
        # Keep last 50 sessions
        if len(self._history) > 50:
            self._history = self._history[-50:]

        return session

    # ── Data Quality ───────────────────────────────────────────

    def _assess_data_quality(
        self, samples: List[TelemetrySample], duration: float
    ) -> DataQuality:
        """Assess the quality/quantity of available telemetry data."""
        if not samples:
            return DataQuality.NOT_AVAILABLE

        n = len(samples)
        has_cpu = any(s.cpu_total_percent is not None for s in samples)
        has_ram = any(s.system_ram_used_mb is not None for s in samples)

        if n >= HIGH_CONFIDENCE_MIN_SAMPLES and has_cpu and has_ram:
            return DataQuality.MEASURED
        elif n >= MODERATE_CONFIDENCE_MIN_SAMPLES:
            return DataQuality.MEASURED
        elif n > 0:
            return DataQuality.INFERRED
        return DataQuality.NOT_AVAILABLE

    def _calculate_recommendation_confidence(
        self,
        samples: List[TelemetrySample],
        base_confidence: int,
    ) -> int:
        """Adjust confidence based on data quality."""
        n = len(samples)
        if n >= HIGH_CONFIDENCE_MIN_SAMPLES:
            return min(base_confidence, 100)
        elif n >= MODERATE_CONFIDENCE_MIN_SAMPLES:
            return min(base_confidence, 75)
        elif n > 0:
            return min(base_confidence, 50)
        return 0

    # ── Conflict Detection ────────────────────────────────────

    def _detect_conflicts(self, samples: List[TelemetrySample]) -> List[str]:
        """Detect multiple simultaneous resource constraints."""
        conflicts = []
        if not samples:
            return conflicts

        cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
        gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
        ram_vals = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
        ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]

        if cpu_vals and statistics.mean(cpu_vals) > 85:
            conflicts.append("CPU")
        if gpu_vals and statistics.mean(gpu_vals) > 90:
            conflicts.append("GPU")
        if ram_vals and ram_total:
            used_pct = (statistics.mean(ram_vals) / ram_total[0]) * 100
            if used_pct > 85:
                conflicts.append("MEMORY")

        return conflicts

    # ── Bottleneck → Recommendations ──────────────────────────

    def _bottleneck_recommendations(
        self,
        bottleneck: BottleneckType,
        samples: List[TelemetrySample],
        states: Dict[str, str],
        profile_id: str,
    ) -> List[Recommendation]:
        """Generate recommendations from bottleneck classification."""
        mapping = BOTTLENECK_OPTIMIZATION_MAP.get(bottleneck, [])
        recs = []
        for opt_id, priority in mapping:
            rec = self._evaluate_optimization(opt_id, samples, states, profile_id)
            if rec:
                # Only override priority for actionable recommendations
                # Never override terminal states (ALREADY_OPTIMAL, REQUIRES_ADMIN, etc.)
                terminal_priorities = {
                    RecommendationPriority.ALREADY_OPTIMAL,
                    RecommendationPriority.REQUIRES_ADMIN,
                    RecommendationPriority.RECOMMENDATION_ONLY,
                    RecommendationPriority.NOT_AVAILABLE,
                }
                if rec.priority not in terminal_priorities:
                    rec.priority = priority
                recs.append(rec)
        return recs

    def _evaluate_optimization(
        self,
        opt_id: str,
        samples: List[TelemetrySample],
        states: Dict[str, str],
        profile_id: str,
    ) -> Optional[Recommendation]:
        """Evaluate a single optimization for recommendation."""
        meta = OPTIMIZATION_META.get(opt_id)
        if not meta:
            return None

        current_state = states.get(opt_id, "UNKNOWN")

        # Already optimal
        if current_state in ("ALREADY_OPTIMAL", "APPLIED", "VERIFIED"):
            return Recommendation(
                optimization_id=opt_id,
                optimization_name=meta["name"],
                priority=RecommendationPriority.ALREADY_OPTIMAL,
                confidence=100,
                reason=f"{meta['name']} is already in optimal state.",
                expected_area=meta["expected_area"],
                safety=meta["safety"],
                current_state=current_state,
                action="NONE",
            )

        # Requires admin
        if current_state == "REQUIRES_ADMIN":
            return Recommendation(
                optimization_id=opt_id,
                optimization_name=meta["name"],
                priority=RecommendationPriority.REQUIRES_ADMIN,
                confidence=90,
                reason=f"{meta['name']} requires administrator privileges.",
                expected_area=meta["expected_area"],
                safety=meta["safety"],
                current_state="Requires elevation",
                action="APPLY",
            )

        # Recommendation only
        if current_state == "RECOMMENDATION_ONLY":
            return Recommendation(
                optimization_id=opt_id,
                optimization_name=meta["name"],
                priority=RecommendationPriority.RECOMMENDATION_ONLY,
                confidence=60,
                reason=f"{meta['name']} provides advisory information only.",
                expected_area=meta["expected_area"],
                safety=meta["safety"],
                current_state="Recommendation only",
                action="REVIEW",
            )

        # Not available
        if current_state in ("NOT_AVAILABLE", "NOT_APPLICABLE"):
            return Recommendation(
                optimization_id=opt_id,
                optimization_name=meta["name"],
                priority=RecommendationPriority.NOT_AVAILABLE,
                confidence=0,
                reason=f"{meta['name']} is not available on this system.",
                expected_area=meta["expected_area"],
                safety=meta["safety"],
                current_state="Not available",
                action="NONE",
            )

        # Evaluate evidence for this optimization
        evidence = self._gather_evidence(opt_id, samples)
        confidence = self._calculate_recommendation_confidence(samples, evidence[1])

        if confidence < 10:
            return None  # Insufficient evidence

        return Recommendation(
            optimization_id=opt_id,
            optimization_name=meta["name"],
            priority=RecommendationPriority.MEDIUM,
            confidence=confidence,
            reason=evidence[0],
            evidence=evidence[2],
            expected_area=meta["expected_area"],
            safety=meta["safety"],
            current_state="Applicable",
            action="APPLY",
        )

    def _gather_evidence(
        self, opt_id: str, samples: List[TelemetrySample]
    ) -> Tuple[str, int, List[EvidencePoint]]:
        """
        Gather evidence for an optimization.

        Returns:
            (reason, base_confidence, evidence_points)
        """
        if not samples:
            return "Insufficient telemetry data", 0, []

        evidence = []
        confidence = 0
        reasons = []

        cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
        gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
        emu_cpu = [s.emulator_cpu_percent for s in samples if s.emulator_cpu_percent is not None]
        ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
        ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
        emu_ram = [s.emulator_ram_mb for s in samples if s.emulator_ram_mb is not None]

        if opt_id == "emulator_priority":
            if cpu_vals:
                avg_cpu = statistics.mean(cpu_vals)
                evidence.append(EvidencePoint(
                    metric="CPU utilization",
                    measured_value=round(avg_cpu, 1),
                    threshold=85.0,
                    unit="%",
                ))
                if avg_cpu > 85:
                    confidence += 30
                    reasons.append(f"CPU pressure is elevated ({avg_cpu:.1f}% avg)")
                elif avg_cpu > 70:
                    confidence += 15
                    reasons.append(f"CPU utilization is moderate ({avg_cpu:.1f}% avg)")

            if gpu_vals and cpu_vals:
                avg_gpu = statistics.mean(gpu_vals)
                avg_cpu = statistics.mean(cpu_vals)
                evidence.append(EvidencePoint(
                    metric="GPU utilization",
                    measured_value=round(avg_gpu, 1),
                    unit="%",
                ))
                if avg_cpu > 75 and avg_gpu < 60:
                    confidence += 20
                    reasons.append(
                        f"CPU pressure ({avg_cpu:.1f}%) while GPU has headroom ({avg_gpu:.1f}%)"
                    )

            if emu_cpu:
                avg_emu = statistics.mean(emu_cpu)
                evidence.append(EvidencePoint(
                    metric="Emulator CPU",
                    measured_value=round(avg_emu, 1),
                    unit="%",
                ))

        elif opt_id == "power_plan":
            if cpu_vals:
                avg_cpu = statistics.mean(cpu_vals)
                evidence.append(EvidencePoint(
                    metric="CPU utilization",
                    measured_value=round(avg_cpu, 1),
                    unit="%",
                ))
                if avg_cpu > 85:
                    confidence += 25
                    reasons.append(f"CPU under high load ({avg_cpu:.1f}%) — power plan affects throughput")
                elif avg_cpu > 70:
                    confidence += 15
                    reasons.append(f"CPU under load ({avg_cpu:.1f}%) — power plan may affect throughput")

        elif opt_id == "background_load":
            if cpu_vals:
                avg_cpu = statistics.mean(cpu_vals)
                evidence.append(EvidencePoint(
                    metric="CPU utilization",
                    measured_value=round(avg_cpu, 1),
                    unit="%",
                ))
                if avg_cpu > 60:
                    confidence += 15
                    reasons.append(f"System CPU elevated ({avg_cpu:.1f}%) — background processes may contribute")

            if ram_used and ram_total:
                avg_used = statistics.mean(ram_used)
                total = ram_total[0]
                used_pct = (avg_used / total) * 100
                evidence.append(EvidencePoint(
                    metric="RAM usage",
                    measured_value=round(used_pct, 1),
                    unit="%",
                ))
                if used_pct > 75:
                    confidence += 15
                    reasons.append(f"RAM usage elevated ({used_pct:.1f}%) — optional processes may help")

        elif opt_id == "cpu_affinity":
            if cpu_vals and emu_cpu:
                avg_cpu = statistics.mean(cpu_vals)
                avg_emu = statistics.mean(emu_cpu)
                evidence.append(EvidencePoint(
                    metric="System CPU",
                    measured_value=round(avg_cpu, 1),
                    unit="%",
                ))
                evidence.append(EvidencePoint(
                    metric="Emulator CPU",
                    measured_value=round(avg_emu, 1),
                    unit="%",
                ))
                if avg_emu > 80:
                    confidence += 15
                    reasons.append(f"Emulator CPU high ({avg_emu:.1f}%) — affinity may help distribute load")

        if not reasons:
            return "No strong evidence for this optimization with current telemetry", 0, evidence

        reason = "; ".join(reasons)
        # Minimum evidence confidence to generate a recommendation
        MIN_EVIDENCE_CONFIDENCE = 10
        if confidence < MIN_EVIDENCE_CONFIDENCE:
            return "No strong evidence for this optimization with current telemetry", 0, evidence
        return reason, confidence, evidence

    def _evaluate_memory_pressure(
        self,
        samples: List[TelemetrySample],
        states: Dict[str, str],
    ) -> Optional[Recommendation]:
        """Evaluate memory pressure for recommendation."""
        ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
        ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]

        if not ram_used or not ram_total:
            return None

        avg_used = statistics.mean(ram_used)
        total = ram_total[0]
        if total <= 0:
            return None

        used_pct = (avg_used / total) * 100

        if used_pct < 75:
            return None  # No memory pressure

        current_state = states.get("memory_analysis", "UNKNOWN")

        confidence = 0
        if used_pct > 90:
            confidence = 80
        elif used_pct > 85:
            confidence = 60
        elif used_pct > 80:
            confidence = 40
        else:
            confidence = 25

        confidence = self._calculate_recommendation_confidence(samples, confidence)

        evidence = [
            EvidencePoint(
                metric="System RAM usage",
                measured_value=round(used_pct, 1),
                threshold=85.0,
                unit="%",
            ),
            EvidencePoint(
                metric="Available RAM",
                measured_value=round(total - avg_used, 0),
                threshold=2048.0,
                unit="MB",
            ),
        ]

        if used_pct >= 90:
            reason = f"Memory pressure is critical ({used_pct:.1f}% used, {total - avg_used:.0f} MB available)"
        elif used_pct >= 85:
            reason = f"Memory pressure is high ({used_pct:.1f}% used, {total - avg_used:.0f} MB available)"
        else:
            reason = f"Memory pressure is elevated ({used_pct:.1f}% used)"

        if current_state in ("ALREADY_OPTIMAL", "APPLIED"):
            priority = RecommendationPriority.ALREADY_OPTIMAL
            action = "NONE"
        elif current_state == "RECOMMENDATION_ONLY":
            priority = RecommendationPriority.RECOMMENDATION_ONLY
            action = "REVIEW"
        else:
            priority = RecommendationPriority.HIGH if used_pct > 85 else RecommendationPriority.MEDIUM
            action = "REVIEW"

        return Recommendation(
            optimization_id="memory_analysis",
            optimization_name="Memory Analysis",
            priority=priority,
            confidence=confidence,
            reason=reason,
            evidence=evidence,
            expected_area="System memory pressure",
            safety="RECOMMENDATION_ONLY",
            current_state=current_state,
            action=action,
        )

    # ── Profile Filtering ─────────────────────────────────────

    def _filter_by_profile(
        self, recommendations: List[Recommendation], profile_id: str
    ) -> List[Recommendation]:
        """Filter recommendations to only include optimizations in the profile."""
        from app.core.profiles import get_profile

        profile = get_profile(profile_id)
        profile_opt_ids = {po.opt_id for po in profile.optimizations}

        filtered = []
        for rec in recommendations:
            if rec.optimization_id in profile_opt_ids:
                filtered.append(rec)
            elif rec.priority in (
                RecommendationPriority.ALREADY_OPTIMAL,
                RecommendationPriority.NOT_AVAILABLE,
            ):
                # Keep status-only entries
                filtered.append(rec)

        return filtered

    # ── Historical Context ────────────────────────────────────

    def _add_historical_context(self, recommendations: List[Recommendation]):
        """Add historical benchmark evidence if available."""
        if len(self._history) < 2:
            return

        # Look at recent sessions for same bottleneck
        recent = self._history[-5:]
        for rec in recommendations:
            count = 0
            for past in recent:
                for past_rec in past.recommendations:
                    if (
                        past_rec.optimization_id == rec.optimization_id
                        and past_rec.priority == RecommendationPriority.ALREADY_OPTIMAL
                    ):
                        count += 1
            if count >= 2:
                rec.historical_evidence = (
                    f"Consistently optimal in {count} recent assessments"
                )

    # ── CLI Formatting ────────────────────────────────────────

    def format_session(self, session: RecommendationSession) -> str:
        """Format a recommendation session for CLI output."""
        lines = []
        lines.append("=" * 55)
        lines.append("HEAVEN SOCIETY — PERFORMANCE ASSESSMENT")
        lines.append("=" * 55)
        lines.append("")

        # Target
        lines.append("TARGET")
        if session.target_name:
            lines.append(f"  {session.target_name}  PID: {session.target_pid}")
        else:
            lines.append("  No emulator detected")
        lines.append("")

        # Bottleneck
        lines.append("BOTTLENECK")
        bn = session.bottleneck.replace("_", " ").title()
        lines.append(f"  {bn}")
        lines.append(f"  Confidence: {session.bottleneck_confidence}%")
        if session.bottleneck_evidence:
            for ev in session.bottleneck_evidence[:3]:
                lines.append(f"  Evidence: {ev}")
        lines.append("")

        # Data quality
        lines.append("DATA")
        lines.append(f"  Samples: {session.sample_count}")
        lines.append(f"  Duration: {session.duration_seconds:.1f}s")
        lines.append(f"  Quality: {session.telemetry_quality.value}")
        if session.conflict_detected:
            lines.append(f"  Conflict: {session.conflict_description}")
        lines.append("")

        # Recommendations
        top = session.get_top_recommendations(8)
        if top:
            lines.append("RECOMMENDATIONS")
            lines.append("-" * 55)
            for i, rec in enumerate(top, 1):
                priority_str = rec.priority.value
                lines.append(f"  {i}. {rec.optimization_name}")
                lines.append(f"     Priority: {priority_str}  |  Confidence: {rec.confidence}%")
                lines.append(f"     Why: {rec.reason}")
                lines.append(f"     Area: {rec.expected_area}")
                lines.append(f"     Safety: {rec.safety}")
                lines.append(f"     Action: {rec.action}")
                if rec.historical_evidence:
                    lines.append(f"     History: {rec.historical_evidence}")
                if rec.evidence:
                    ev_parts = []
                    for ev in rec.evidence[:3]:
                        v = f"{ev.measured_value}" if ev.measured_value is not None else "N/A"
                        u = ev.unit or ""
                        ev_parts.append(f"{ev.metric}: {v}{u}")
                    lines.append(f"     Metrics: {' | '.join(ev_parts)}")
                lines.append("")
        else:
            lines.append("RECOMMENDATIONS")
            lines.append("-" * 55)
            lines.append("  No actionable recommendations at this time.")
            lines.append("")

        lines.append("=" * 55)
        return "\n".join(lines)


# Singleton
recommendation_engine = RecommendationEngine()
