"""
Gameplay Diagnostics & Input Consistency — Phase 37.

Classifies gameplay conditions, calculates input consistency scores,
and provides sensitivity analysis recommendations.

STRICTLY ANALYSIS — never modifies game or emulator state.
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
from app.input.input_diagnostics import (
    InputDiagnosticSession,
    MetricState,
    PollingConsistency,
    PointerAssessment,
)
from app.utils.logger import get_logger

logger = get_logger("input.gameplay")


# ── Enums ────────────────────────────────────────────────────────

class GameplayCondition(Enum):
    """Gameplay condition classification."""
    INPUT_STABLE = "INPUT_STABLE"
    INPUT_INCONSISTENT = "INPUT_INCONSISTENT"
    FRAME_TIME_LIMITED = "FRAME_TIME_LIMITED"
    CPU_SCHEDULING_LIMITED = "CPU_SCHEDULING_LIMITED"
    MEMORY_LIMITED = "MEMORY_LIMITED"
    THERMAL_LIMITED = "THERMAL_LIMITED"
    MULTI_RESOURCE_LIMITED = "MULTI_RESOURCE_LIMITED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ConsistencyScoreLevel(Enum):
    """Consistency score quality level."""
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class SensitivityDataType(Enum):
    """Type of sensitivity data."""
    USER_REPORTED = "USER_REPORTED"
    MEASURED = "MEASURED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class ConsistencyComponent:
    """A single component of the consistency score."""
    name: str = ""
    score: int = 0  # 0-100
    weight: float = 0.0
    state: MetricState = MetricState.NOT_AVAILABLE
    detail: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "score": self.score,
            "weight": self.weight,
            "state": self.state.value,
            "detail": self.detail,
        }


@dataclass
class InputConsistencyScore:
    """Evidence-based input consistency score (0-100)."""
    overall_score: int = 0
    level: ConsistencyScoreLevel = ConsistencyScoreLevel.NOT_AVAILABLE
    components: List[ConsistencyComponent] = field(default_factory=list)
    state: MetricState = MetricState.NOT_AVAILABLE
    sample_count: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "level": self.level.value,
            "components": [c.to_dict() for c in self.components],
            "state": self.state.value,
            "sample_count": self.sample_count,
        }


@dataclass
class SensitivityData:
    """User-provided sensitivity data (USER_REPORTED only)."""
    data_type: SensitivityDataType = SensitivityDataType.USER_REPORTED
    dpi: Optional[int] = None
    general_sensitivity: Optional[int] = None
    red_dot: Optional[int] = None
    scope_2x: Optional[int] = None
    scope_4x: Optional[int] = None
    sniper: Optional[int] = None
    free_look: Optional[int] = None
    game_resolution: str = ""
    emulator_resolution: str = ""

    def has_any(self) -> bool:
        return any([
            self.dpi, self.general_sensitivity, self.red_dot,
            self.scope_2x, self.scope_4x, self.sniper, self.free_look,
        ])

    def to_dict(self) -> dict:
        return {
            "data_type": self.data_type.value,
            "dpi": self.dpi,
            "general_sensitivity": self.general_sensitivity,
            "red_dot": self.red_dot,
            "scope_2x": self.scope_2x,
            "scope_4x": self.scope_4x,
            "sniper": self.sniper,
            "free_look": self.free_look,
        }


@dataclass
class SensitivityAnalysis:
    """Analysis of user-provided sensitivity values."""
    effective_dpi: Optional[float] = None
    cm_per_360: Optional[float] = None
    scope_scaling: Dict[str, float] = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)
    warnings: List[str] = field(default_factory=list)
    state: SensitivityDataType = SensitivityDataType.NOT_AVAILABLE

    def to_dict(self) -> dict:
        return {
            "effective_dpi": self.effective_dpi,
            "cm_per_360": self.cm_per_360,
            "scope_scaling": self.scope_scaling,
            "recommendations": self.recommendations,
            "state": self.state.value,
        }


@dataclass
class GameplayRecommendation:
    """A gameplay/input recommendation."""
    category: str = ""  # INPUT, FRAME_PACING, MEMORY, CPU, THERMAL, CONFIGURATION
    priority: str = ""  # HIGH, MEDIUM, LOW
    reason: str = ""
    evidence: str = ""
    action: str = ""  # CONFIGURE, RESOLVE, MONITOR
    safety: str = ""  # SAFE, REQUIRES_ADMIN, USER_ACTION

    def to_dict(self) -> dict:
        return {
            "category": self.category,
            "priority": self.priority,
            "reason": self.reason,
            "evidence": self.evidence,
            "action": self.action,
            "safety": self.safety,
        }


@dataclass
class GameplayDiagnosticSession:
    """Complete gameplay diagnostic session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    target_name: str = ""
    target_pid: int = 0

    # Classification
    condition: GameplayCondition = GameplayCondition.INSUFFICIENT_DATA
    condition_confidence: int = 0
    condition_evidence: List[str] = field(default_factory=list)

    # Consistency
    consistency_score: InputConsistencyScore = field(default_factory=InputConsistencyScore)

    # Input context
    input_session: Optional[InputDiagnosticSession] = None

    # System context
    cpu_percent: float = 0.0
    gpu_percent: float = 0.0
    ram_percent: float = 0.0
    gpu_temp_c: Optional[float] = None
    fps: Optional[float] = None
    frame_time_ms: Optional[float] = None
    one_percent_low: Optional[float] = None
    frame_time_cv: float = 0.0

    # Recommendations
    recommendations: List[GameplayRecommendation] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "target_name": self.target_name,
            "condition": self.condition.value,
            "condition_confidence": self.condition_confidence,
            "consistency_score": self.consistency_score.to_dict(),
            "fps": self.fps,
            "recommendations": [r.to_dict() for r in self.recommendations],
        }


# ── Thresholds ───────────────────────────────────────────────────

CPU_SCHEDULING_THRESHOLD = 85.0
MEMORY_PRESSURE_THRESHOLD = 85.0
THERMAL_WARNING_THRESHOLD = 85.0
FRAME_TIME_CV_UNSTABLE = 0.35
FRAME_TIME_CV_MILD = 0.20
MIN_SAMPLES_CLASSIFY = 3
MIN_SAMPLES_SCORE = 5

# Consistency score weights
SCORE_WEIGHTS = {
    "event_consistency": 0.25,
    "frame_pacing": 0.25,
    "cpu_headroom": 0.15,
    "memory_headroom": 0.15,
    "pointer_config": 0.10,
    "latency_estimate": 0.10,
}


# ── Condition Classification ─────────────────────────────────────

def classify_gameplay_condition(
    samples: List[TelemetrySample],
    input_session: Optional[InputDiagnosticSession] = None,
) -> Tuple[GameplayCondition, int, List[str]]:
    """
    Classify the current gameplay condition from telemetry and input data.

    Returns:
        (condition, confidence, evidence)
    """
    if not samples or len(samples) < MIN_SAMPLES_CLASSIFY:
        return (
            GameplayCondition.INSUFFICIENT_DATA,
            0,
            [f"Only {len(samples) if samples else 0} samples, need {MIN_SAMPLES_CLASSIFY} minimum"],
        )

    evidence = []
    scores = {c: 0 for c in GameplayCondition if c != GameplayCondition.INSUFFICIENT_DATA}

    # CPU analysis
    cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
    if cpu_vals:
        avg_cpu = statistics.mean(cpu_vals)
        if avg_cpu >= CPU_SCHEDULING_THRESHOLD:
            scores[GameplayCondition.CPU_SCHEDULING_LIMITED] += 40
            evidence.append(f"CPU averaged {avg_cpu:.1f}% (scheduling pressure)")

    # Memory analysis
    ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
    ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
    if ram_used and ram_total and ram_total[0] > 0:
        avg_used = statistics.mean(ram_used)
        total = ram_total[0]
        used_pct = (avg_used / total) * 100
        if used_pct >= MEMORY_PRESSURE_THRESHOLD:
            scores[GameplayCondition.MEMORY_LIMITED] += 40
            evidence.append(f"RAM at {used_pct:.1f}% ({avg_used:.0f}/{total:.0f} MB)")

    # Thermal analysis
    gpu_temps = [s.gpu_temperature_c for s in samples if s.gpu_temperature_c is not None]
    if gpu_temps:
        max_temp = max(gpu_temps)
        if max_temp >= THERMAL_WARNING_THRESHOLD:
            scores[GameplayCondition.THERMAL_LIMITED] += 40
            evidence.append(f"GPU temperature {max_temp:.0f}°C")

    # Frame time analysis
    frame_times = [s.frame_time_ms for s in samples if s.frame_time_ms is not None and s.frame_time_ms > 0]
    if frame_times and len(frame_times) >= 3:
        avg_ft = statistics.mean(frame_times)
        if avg_ft > 0:
            cv = statistics.stdev(frame_times) / avg_ft if len(frame_times) > 1 else 0
            if cv > FRAME_TIME_CV_UNSTABLE:
                scores[GameplayCondition.FRAME_TIME_LIMITED] += 40
                evidence.append(f"Frame time unstable (CV={cv:.2f})")
            elif cv > FRAME_TIME_CV_MILD:
                scores[GameplayCondition.FRAME_TIME_LIMITED] += 15

    # Input consistency from input session
    if input_session:
        pc = input_session.pointer_config
        if pc.enhance_pointer_precision:
            scores[GameplayCondition.INPUT_INCONSISTENT] += 25
            evidence.append("Enhance Pointer Precision is enabled (mouse acceleration)")

        poll = input_session.polling
        if poll.state == MetricState.MEASURED:
            if poll.consistency == PollingConsistency.LOW:
                scores[GameplayCondition.INPUT_INCONSISTENT] += 30
                evidence.append(f"Mouse event rate inconsistent (CV={poll.coefficient_of_variation:.2f})")
            elif poll.consistency == PollingConsistency.MODERATE:
                scores[GameplayCondition.INPUT_INCONSISTENT] += 10

    # Multi-resource check
    high_count = 0
    if cpu_vals and statistics.mean(cpu_vals) > CPU_SCHEDULING_THRESHOLD:
        high_count += 1
    if ram_used and ram_total and ram_total[0] > 0:
        if (statistics.mean(ram_used) / ram_total[0]) * 100 > MEMORY_PRESSURE_THRESHOLD:
            high_count += 1
    if gpu_temps and max(gpu_temps) >= THERMAL_WARNING_THRESHOLD:
        high_count += 1
    if high_count >= 2:
        scores[GameplayCondition.MULTI_RESOURCE_LIMITED] += 30
        evidence.append(f"{high_count} resources under simultaneous pressure")

    # Check for input stability (no issues detected)
    if not evidence:
        has_data = cpu_vals or ram_used or frame_times
        if has_data:
            scores[GameplayCondition.INPUT_STABLE] += 50
            evidence.append("No input or resource issues detected")
        else:
            return (
                GameplayCondition.INSUFFICIENT_DATA,
                0,
                ["No valid telemetry data"],
            )

    # Find best
    candidates = [(c, s) for c, s in scores.items() if s > 0]
    if not candidates:
        return (
            GameplayCondition.INPUT_STABLE,
            40,
            ["System appears stable"],
        )

    candidates.sort(key=lambda x: x[1], reverse=True)
    best, best_score = candidates[0]

    n = len(samples)
    data_bonus = 10 if n >= MIN_SAMPLES_SCORE else 5
    confidence = min(best_score + data_bonus, 100)

    return best, confidence, evidence


# ── Consistency Score ────────────────────────────────────────────

def calculate_consistency_score(
    samples: List[TelemetrySample],
    input_session: Optional[InputDiagnosticSession] = None,
) -> InputConsistencyScore:
    """
    Calculate an evidence-based input consistency score (0-100).

    Components:
    - Event consistency (from polling measurement)
    - Frame pacing (from frame time data)
    - CPU headroom
    - Memory headroom
    - Pointer configuration
    - Latency estimate
    """
    result = InputConsistencyScore(
        sample_count=len(samples),
        state=MetricState.NOT_AVAILABLE,
    )

    n = len(samples)
    if n < MIN_SAMPLES_SCORE:
        result.state = MetricState.NOT_AVAILABLE
        return result

    components = []

    # 1. Event consistency
    event_score = ConsistencyComponent(
        name="Event Consistency",
        weight=SCORE_WEIGHTS["event_consistency"],
    )
    if input_session and input_session.polling.state == MetricState.MEASURED:
        poll = input_session.polling
        if poll.consistency == PollingConsistency.HIGH:
            event_score.score = 95
        elif poll.consistency == PollingConsistency.MODERATE:
            event_score.score = 70
        elif poll.consistency == PollingConsistency.LOW:
            event_score.score = 40
        else:
            event_score.score = 50  # Default when not measured
        event_score.state = MetricState.MEASURED
        event_score.detail = f"CV={poll.coefficient_of_variation:.3f}, rate={poll.observed_rate_hz:.0f}Hz"
    else:
        event_score.score = 60  # Neutral when not measured
        event_score.state = MetricState.NOT_AVAILABLE
        event_score.detail = "Polling not measured"
    components.append(event_score)

    # 2. Frame pacing
    frame_score = ConsistencyComponent(
        name="Frame Pacing",
        weight=SCORE_WEIGHTS["frame_pacing"],
    )
    frame_times = [s.frame_time_ms for s in samples if s.frame_time_ms is not None and s.frame_time_ms > 0]
    if frame_times and len(frame_times) >= 3:
        avg_ft = statistics.mean(frame_times)
        if avg_ft > 0:
            cv = statistics.stdev(frame_times) / avg_ft if len(frame_times) > 1 else 0
            if cv < 0.10:
                frame_score.score = 95
            elif cv < 0.20:
                frame_score.score = 80
            elif cv < 0.35:
                frame_score.score = 60
            else:
                frame_score.score = 30
            frame_score.state = MetricState.MEASURED
            frame_score.detail = f"CV={cv:.3f}, avg={avg_ft:.1f}ms"
    else:
        frame_score.score = 60
        frame_score.state = MetricState.NOT_AVAILABLE
        frame_score.detail = "Frame time data unavailable"
    components.append(frame_score)

    # 3. CPU headroom
    cpu_score = ConsistencyComponent(
        name="CPU Headroom",
        weight=SCORE_WEIGHTS["cpu_headroom"],
    )
    cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
    if cpu_vals:
        avg_cpu = statistics.mean(cpu_vals)
        if avg_cpu < 50:
            cpu_score.score = 95
        elif avg_cpu < 70:
            cpu_score.score = 80
        elif avg_cpu < 85:
            cpu_score.score = 60
        else:
            cpu_score.score = 30
        cpu_score.state = MetricState.MEASURED
        cpu_score.detail = f"CPU avg {avg_cpu:.1f}%"
    else:
        cpu_score.score = 60
        cpu_score.state = MetricState.NOT_AVAILABLE
    components.append(cpu_score)

    # 4. Memory headroom
    mem_score = ConsistencyComponent(
        name="Memory Headroom",
        weight=SCORE_WEIGHTS["memory_headroom"],
    )
    ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
    ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
    if ram_used and ram_total and ram_total[0] > 0:
        avg_used = statistics.mean(ram_used)
        total = ram_total[0]
        used_pct = (avg_used / total) * 100
        if used_pct < 60:
            mem_score.score = 95
        elif used_pct < 75:
            mem_score.score = 80
        elif used_pct < 85:
            mem_score.score = 60
        else:
            mem_score.score = 30
        mem_score.state = MetricState.MEASURED
        mem_score.detail = f"RAM {used_pct:.1f}% ({avg_used:.0f}/{total:.0f} MB)"
    else:
        mem_score.score = 60
        mem_score.state = MetricState.NOT_AVAILABLE
    components.append(mem_score)

    # 5. Pointer configuration
    ptr_score = ConsistencyComponent(
        name="Pointer Config",
        weight=SCORE_WEIGHTS["pointer_config"],
    )
    if input_session and input_session.pointer_config.state == MetricState.MEASURED:
        pc = input_session.pointer_config
        if pc.assessment == PointerAssessment.CONSISTENT:
            ptr_score.score = 95
            ptr_score.detail = "No acceleration, consistent"
        elif pc.assessment == PointerAssessment.POTENTIAL_VARIABLE_ACCELERATION:
            ptr_score.score = 50
            ptr_score.detail = "Enhance Pointer Precision enabled"
        else:
            ptr_score.score = 60
            ptr_score.detail = "Unknown configuration"
        ptr_score.state = MetricState.MEASURED
    else:
        ptr_score.score = 60
        ptr_score.state = MetricState.NOT_AVAILABLE
    components.append(ptr_score)

    # 6. Latency estimate
    lat_score = ConsistencyComponent(
        name="Latency Estimate",
        weight=SCORE_WEIGHTS["latency_estimate"],
    )
    if input_session and input_session.latency.state != MetricState.NOT_AVAILABLE:
        total_ms = input_session.latency.estimated_total_ms
        if total_ms < 10:
            lat_score.score = 90
        elif total_ms < 17:
            lat_score.score = 75
        elif total_ms < 33:
            lat_score.score = 55
        else:
            lat_score.score = 35
        lat_score.state = MetricState.INFERRED
        lat_score.detail = f"Estimated {total_ms:.1f}ms"
    else:
        lat_score.score = 60
        lat_score.state = MetricState.NOT_AVAILABLE
    components.append(lat_score)

    # Calculate weighted score
    total_weight = sum(c.weight for c in components)
    if total_weight > 0:
        weighted_sum = sum(c.score * c.weight for c in components)
        result.overall_score = int(weighted_sum / total_weight)
    else:
        result.overall_score = 50

    # Classify level
    if result.overall_score >= 85:
        result.level = ConsistencyScoreLevel.EXCELLENT
    elif result.overall_score >= 70:
        result.level = ConsistencyScoreLevel.GOOD
    elif result.overall_score >= 50:
        result.level = ConsistencyScoreLevel.FAIR
    else:
        result.level = ConsistencyScoreLevel.POOR

    result.components = components
    result.state = MetricState.MEASURED if any(c.state == MetricState.MEASURED for c in components) else MetricState.INFERRED

    return result


# ── Sensitivity Analysis ─────────────────────────────────────────

def analyze_sensitivity(data: SensitivityData) -> SensitivityAnalysis:
    """
    Analyze user-provided sensitivity data.

    All data is USER_REPORTED — not measured.
    """
    analysis = SensitivityAnalysis()

    if not data.has_any():
        analysis.state = SensitivityDataType.NOT_AVAILABLE
        analysis.recommendations.append("No sensitivity data provided")
        return analysis

    analysis.state = SensitivityDataType.USER_REPORTED

    # Effective DPI
    if data.dpi and data.general_sensitivity:
        analysis.effective_dpi = data.dpi * (data.general_sensitivity / 50.0)
        analysis.recommendations.append(
            f"Effective DPI: {analysis.effective_dpi:.0f} (DPI {data.dpi} × sens {data.general_sensitivity}/50)"
        )

    # cm/360 estimate (if DPI available)
    if data.dpi and data.dpi > 0:
        # Approximate: cm/360 ≈ (2.54 * 25.4 * 360) / (DPI * 400/340)
        # Simplified: cm/360 ≈ 36.73 / (DPI / 400)
        analysis.cm_per_360 = 36.73 / (data.dpi / 400.0)
        analysis.recommendations.append(
            f"Estimated cm/360: {analysis.cm_per_360:.1f} cm (at 400 DPI equivalent)"
        )

    # Scope scaling analysis
    if data.general_sensitivity and data.general_sensitivity > 0:
        scopes = {
            "Red Dot": data.red_dot,
            "2x": data.scope_2x,
            "4x": data.scope_4x,
            "Sniper": data.sniper,
        }
        base = data.general_sensitivity
        for name, val in scopes.items():
            if val is not None and val > 0:
                scale = val / base
                analysis.scope_scaling[name] = round(scale, 3)

        # Check for unusual scaling
        if data.red_dot and data.red_dot > base * 1.2:
            analysis.warnings.append(
                f"Red Dot sensitivity ({data.red_dot}) is higher than general ({base}) — unusual"
            )
        if data.sniper and data.sniper > base * 0.8:
            analysis.warnings.append(
                f"Sniper sensitivity ({data.sniper}) may be high relative to general ({base})"
            )

    # DPI recommendations
    if data.dpi:
        if data.dpi < 400:
            analysis.recommendations.append(
                f"DPI {data.dpi} is low; ensure mouse sensor tracks reliably at this DPI"
            )
        elif data.dpi > 3200:
            analysis.recommendations.append(
                f"DPI {data.dpi} is high; lower DPI with higher in-game sensitivity "
                "can improve pixel-level precision"
            )

    if not analysis.recommendations:
        analysis.recommendations.append("Sensitivity data recorded — no specific concerns")

    return analysis


# ── Gameplay Recommendations ─────────────────────────────────────

def generate_gameplay_recommendations(
    condition: GameplayCondition,
    condition_confidence: int,
    consistency: InputConsistencyScore,
    input_session: Optional[InputDiagnosticSession] = None,
    samples: List[TelemetrySample] = None,
) -> List[GameplayRecommendation]:
    """
    Generate evidence-based gameplay recommendations.

    Recommendations explain WHY based on measured evidence.
    """
    recs = []

    if condition == GameplayCondition.INSUFFICIENT_DATA:
        recs.append(GameplayRecommendation(
            category="INPUT",
            priority="MEDIUM",
            reason="Insufficient telemetry data for gameplay analysis",
            evidence="Fewer than 3 samples collected",
            action="MONITOR",
            safety="SAFE",
        ))
        return recs

    # Input-specific recommendations
    if condition in (GameplayCondition.INPUT_INCONSISTENT, GameplayCondition.INPUT_STABLE):
        if input_session:
            pc = input_session.pointer_config
            if pc.enhance_pointer_precision:
                recs.append(GameplayRecommendation(
                    category="INPUT",
                    priority="MEDIUM",
                    reason="Enhance Pointer Precision is enabled. "
                           "If you want consistent physical mouse-to-pointer behavior, "
                           "consider disabling it.",
                    evidence="Pointer acceleration: ENABLED",
                    action="CONFIGURE",
                    safety="SAFE",
                ))

            poll = input_session.polling
            if poll.state == MetricState.MEASURED and poll.consistency == PollingConsistency.LOW:
                recs.append(GameplayRecommendation(
                    category="INPUT",
                    priority="HIGH",
                    reason="Observed mouse event rate is inconsistent. "
                           "Check USB connection, device software, or polling configuration.",
                    evidence=f"Event CV={poll.coefficient_of_variation:.3f}, rate={poll.observed_rate_hz:.0f}Hz",
                    action="MONITOR",
                    safety="SAFE",
                ))

    # Frame pacing recommendations
    if condition == GameplayCondition.FRAME_TIME_LIMITED:
        recs.append(GameplayRecommendation(
            category="FRAME_PACING",
            priority="HIGH",
            reason="Frame delivery is unstable. "
                   "This is likely NOT an input configuration issue. "
                   "Investigate background interference, thermal throttling, or emulator scheduling.",
            evidence="Frame time coefficient of variation indicates unstable delivery",
            action="RESOLVE",
            safety="SAFE",
        ))

    # Memory recommendations
    if condition in (GameplayCondition.MEMORY_LIMITED, GameplayCondition.MULTI_RESOURCE_LIMITED):
        recs.append(GameplayRecommendation(
            category="MEMORY",
            priority="HIGH",
            reason="RAM utilization is high, which may increase emulator scheduling pressure. "
                   "Resolve resource pressure before tuning sensitivity.",
            evidence=f"Memory pressure detected with {condition_confidence}% confidence",
            action="RESOLVE",
            safety="SAFE",
        ))

    # CPU recommendations
    if condition == GameplayCondition.CPU_SCHEDULING_LIMITED:
        recs.append(GameplayRecommendation(
            category="CPU",
            priority="HIGH",
            reason="CPU scheduling pressure detected. "
                   "This can cause input timing inconsistencies.",
            evidence=f"CPU pressure with {condition_confidence}% confidence",
            action="RESOLVE",
            safety="SAFE",
        ))

    # Thermal recommendations
    if condition == GameplayCondition.THERMAL_LIMITED:
        recs.append(GameplayRecommendation(
            category="THERMAL",
            priority="HIGH",
            reason="Thermal conditions may be limiting performance. "
                   "Reducing background load may lower thermal pressure.",
            evidence="GPU/CPU temperature approaching limits",
            action="RESOLVE",
            safety="SAFE",
        ))

    # Generic: if input is stable and no other issues, note it
    if condition == GameplayCondition.INPUT_STABLE and not recs:
        recs.append(GameplayRecommendation(
            category="INPUT",
            priority="LOW",
            reason="Input conditions appear stable. "
                   "If you experience inconsistency, investigate frame pacing or resource pressure.",
            evidence="No input or resource issues detected",
            action="MONITOR",
            safety="SAFE",
        ))

    return recs


# ── Comprehensive Diagnostic ─────────────────────────────────────

def run_gameplay_diagnostics(
    samples: List[TelemetrySample],
    input_session: Optional[InputDiagnosticSession] = None,
    target_name: str = "",
    target_pid: int = 0,
) -> GameplayDiagnosticSession:
    """
    Run comprehensive gameplay diagnostics.

    Combines input, telemetry, and system data to classify
    gameplay conditions and provide recommendations.
    """
    session = GameplayDiagnosticSession(
        target_name=target_name,
        target_pid=target_pid,
    )

    # System context from samples
    cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
    gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
    ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
    ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
    gpu_temps = [s.gpu_temperature_c for s in samples if s.gpu_temperature_c is not None]
    fps_vals = [s.fps for s in samples if s.fps is not None and s.fps > 0]
    ft_vals = [s.frame_time_ms for s in samples if s.frame_time_ms is not None and s.frame_time_ms > 0]

    if cpu_vals:
        session.cpu_percent = statistics.mean(cpu_vals)
    if gpu_vals:
        session.gpu_percent = statistics.mean(gpu_vals)
    if ram_used and ram_total and ram_total[0] > 0:
        session.ram_percent = (statistics.mean(ram_used) / ram_total[0]) * 100
    if gpu_temps:
        session.gpu_temp_c = max(gpu_temps)
    if fps_vals:
        session.fps = statistics.mean(fps_vals)
    if ft_vals:
        session.frame_time_ms = statistics.mean(ft_vals)
        if len(ft_vals) > 1:
            avg_ft = statistics.mean(ft_vals)
            if avg_ft > 0:
                session.frame_time_cv = statistics.stdev(ft_vals) / avg_ft

    # Classify condition
    session.condition, session.condition_confidence, session.condition_evidence = \
        classify_gameplay_condition(samples, input_session)

    # Calculate consistency score
    session.consistency_score = calculate_consistency_score(samples, input_session)

    # Store input session
    session.input_session = input_session

    # Generate recommendations
    session.recommendations = generate_gameplay_recommendations(
        session.condition, session.condition_confidence,
        session.consistency_score, input_session, samples,
    )

    return session


# ── CLI Formatting ───────────────────────────────────────────────

def format_gameplay_diagnostics(session: GameplayDiagnosticSession) -> str:
    """Format gameplay diagnostics for CLI output."""
    lines = []
    lines.append("=" * 55)
    lines.append("HEAVEN SOCIETY — GAMEPLAY DIAGNOSTICS")
    lines.append("=" * 55)
    lines.append("")

    # Target
    lines.append("TARGET")
    if session.target_name:
        lines.append(f"  {session.target_name}  PID: {session.target_pid}")
    else:
        lines.append("  No emulator detected")
    lines.append("")

    # Condition
    cond_str = session.condition.value.replace("_", " ").title()
    lines.append("CONDITION")
    lines.append(f"  {cond_str}")
    lines.append(f"  Confidence: {session.condition_confidence}%")
    for ev in session.condition_evidence[:3]:
        lines.append(f"  Evidence: {ev}")
    lines.append("")

    # Consistency Score
    cs = session.consistency_score
    if cs.state == MetricState.MEASURED or cs.state == MetricState.INFERRED:
        lines.append("INPUT CONSISTENCY")
        lines.append(f"  Score: {cs.overall_score}/100 ({cs.level.value})")
        for comp in cs.components:
            lines.append(f"  {comp.name:20s} {comp.score:3d}/100  {comp.detail}")
    else:
        lines.append("INPUT CONSISTENCY")
        lines.append(f"  Score: NOT_AVAILABLE")
    lines.append("")

    # System
    lines.append("SYSTEM")
    if session.fps:
        lines.append(f"  FPS:          {session.fps:.0f}")
    if session.frame_time_ms:
        lines.append(f"  Frame Time:   {session.frame_time_ms:.1f} ms")
    lines.append(f"  CPU:          {session.cpu_percent:.0f}%")
    lines.append(f"  RAM:          {session.ram_percent:.0f}%")
    if session.gpu_temp_c:
        lines.append(f"  GPU Temp:     {session.gpu_temp_c:.0f}°C")
    lines.append("")

    # Input
    if session.input_session:
        isess = session.input_session
        lines.append("INPUT")
        pc = isess.pointer_config
        epp = "ON" if pc.enhance_pointer_precision else "OFF"
        lines.append(f"  Pointer Acceleration: {epp}")
        lines.append(f"  Pointer Speed:        {pc.pointer_speed}/11")
        if isess.polling.state == MetricState.MEASURED:
            lines.append(f"  Observed Rate:        {isess.polling.observed_rate_hz:.0f} Hz")
            lines.append(f"  Consistency:          {isess.polling.consistency.value}")
        lat = isess.latency
        if lat.state != MetricState.NOT_AVAILABLE:
            lines.append(f"  Input Latency:        {lat.estimated_total_ms:.1f} ms (ESTIMATED)")
        lines.append("")

    # Recommendations
    if session.recommendations:
        lines.append("RECOMMENDATIONS")
        lines.append("-" * 55)
        for r in session.recommendations:
            lines.append(f"  [{r.category}] {r.priority}")
            lines.append(f"    {r.reason}")
            lines.append(f"    Evidence: {r.evidence}")
            lines.append(f"    Action: {r.action}  |  Safety: {r.safety}")
            lines.append("")

    lines.append("=" * 55)
    return "\n".join(lines)
