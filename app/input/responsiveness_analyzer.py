"""
Input-to-Frame Correlation & Responsiveness Analyzer — Phase 38.

Correlates input events, CPU scheduling, emulator process state,
frame generation, and display refresh to identify the actual
technical cause of perceived input delay or inconsistency.

STRICTLY MEASUREMENT — never modifies system state.
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
    PollingMeasurement,
)
from app.input.gameplay_diagnostics import (
    GameplayCondition,
    InputConsistencyScore,
    ConsistencyScoreLevel,
    ConsistencyComponent,
    calculate_consistency_score,
)
from app.utils.logger import get_logger

logger = get_logger("input.responsiveness")


# ── Enums ────────────────────────────────────────────────────────

class ResponsivenessState(Enum):
    """Overall responsiveness classification."""
    RESPONSIVE = "RESPONSIVE"
    INPUT_LIMITED = "INPUT_LIMITED"
    FRAME_LIMITED = "FRAME_LIMITED"
    CPU_SCHEDULING_LIMITED = "CPU_SCHEDULING_LIMITED"
    MEMORY_LIMITED = "MEMORY_LIMITED"
    GPU_LIMITED = "GPU_LIMITED"
    THERMAL_LIMITED = "THERMAL_LIMITED"
    MULTI_RESOURCE_LIMITED = "MULTI_RESOURCE_LIMITED"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class CorrelationStrength(Enum):
    """Strength of input/frame correlation."""
    CORRELATED = "CORRELATED"
    POSSIBLY_RELATED = "POSSIBLY_RELATED"
    NO_CLEAR_CORRELATION = "NO_CLEAR_CORRELATION"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class DisplayMatch(Enum):
    """Frame rate vs display refresh match."""
    GOOD_MATCH = "GOOD_MATCH"
    VARIABLE = "VARIABLE"
    FRAME_RATE_BELOW_REFRESH = "FRAME_RATE_BELOW_REFRESH"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class ConfidenceLevel(Enum):
    """Confidence in the analysis."""
    HIGH = "HIGH"
    MODERATE = "MODERATE"
    LOW = "LOW"
    INCONCLUSIVE = "INCONCLUSIVE"


class TargetStatus(Enum):
    """Emulator target status."""
    ACTIVE = "ACTIVE"
    STOPPED = "STOPPED"
    PID_REUSE_DETECTED = "PID_REUSE_DETECTED"
    NOT_DETECTED = "NOT_DETECTED"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class InputTimeline:
    """Input event timing statistics."""
    total_events: int = 0
    duration_seconds: float = 0.0
    observed_rate_hz: float = 0.0
    median_interval_ms: float = 0.0
    average_interval_ms: float = 0.0
    min_interval_ms: float = 0.0
    max_interval_ms: float = 0.0
    std_dev_ms: float = 0.0
    coefficient_of_variation: float = 0.0
    max_gap_ms: float = 0.0
    burst_count: int = 0
    consistency: str = "INSUFFICIENT_DATA"
    state: MetricState = MetricState.NOT_AVAILABLE

    def to_dict(self) -> dict:
        return {
            "total_events": self.total_events,
            "observed_rate_hz": round(self.observed_rate_hz, 1),
            "median_interval_ms": round(self.median_interval_ms, 2),
            "coefficient_of_variation": round(self.coefficient_of_variation, 3),
            "max_gap_ms": round(self.max_gap_ms, 2),
            "consistency": self.consistency,
            "state": self.state.value,
        }


@dataclass
class FrameTimeline:
    """Frame delivery timing statistics."""
    avg_fps: Optional[float] = None
    median_fps: Optional[float] = None
    avg_frame_time_ms: Optional[float] = None
    median_frame_time_ms: Optional[float] = None
    frame_time_std_dev_ms: float = 0.0
    frame_time_cv: float = 0.0
    one_percent_low: Optional[float] = None
    frame_spikes: int = 0
    total_frames: int = 0
    consistency: str = "INSUFFICIENT_DATA"
    state: MetricState = MetricState.NOT_AVAILABLE

    def to_dict(self) -> dict:
        return {
            "avg_fps": round(self.avg_fps, 1) if self.avg_fps else None,
            "avg_frame_time_ms": round(self.avg_frame_time_ms, 2) if self.avg_frame_time_ms else None,
            "frame_time_cv": round(self.frame_time_cv, 3),
            "frame_spikes": self.frame_spikes,
            "consistency": self.consistency,
            "state": self.state.value,
        }


@dataclass
class LatencyBreakdown:
    """Decomposed latency estimate."""
    input_ms: float = 0.0
    input_state: MetricState = MetricState.NOT_AVAILABLE
    scheduling_ms: float = 0.0
    scheduling_state: MetricState = MetricState.NOT_AVAILABLE
    frame_ms: float = 0.0
    frame_state: MetricState = MetricState.NOT_AVAILABLE
    presentation_ms: float = 0.0
    presentation_state: MetricState = MetricState.NOT_AVAILABLE
    display_ms: float = 0.0
    display_state: MetricState = MetricState.NOT_AVAILABLE
    estimated_total_ms: float = 0.0
    total_state: MetricState = MetricState.NOT_AVAILABLE
    note: str = ""

    def to_dict(self) -> dict:
        return {
            "input_ms": round(self.input_ms, 1),
            "input_state": self.input_state.value,
            "scheduling_ms": round(self.scheduling_ms, 1),
            "frame_ms": round(self.frame_ms, 1),
            "frame_state": self.frame_state.value,
            "display_ms": round(self.display_ms, 1),
            "estimated_total_ms": round(self.estimated_total_ms, 1),
            "total_state": self.total_state.value,
        }


@dataclass
class CorrelationResult:
    """Result of input/frame correlation analysis."""
    strength: CorrelationStrength = CorrelationStrength.INSUFFICIENT_DATA
    description: str = ""
    evidence: List[str] = field(default_factory=list)
    input_events_during_spikes: int = 0
    total_spikes: int = 0
    spike_overlap_percent: float = 0.0

    def to_dict(self) -> dict:
        return {
            "strength": self.strength.value,
            "description": self.description,
            "evidence": self.evidence,
            "spike_overlap_percent": round(self.spike_overlap_percent, 1),
        }


@dataclass
class ResponsivenessScore:
    """Evidence-based responsiveness score (0-100)."""
    overall: int = 0
    level: str = "NOT_AVAILABLE"
    components: List[Dict] = field(default_factory=list)
    state: MetricState = MetricState.NOT_AVAILABLE
    sample_count: int = 0

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "level": self.level,
            "components": self.components,
            "state": self.state.value,
        }


@dataclass
class DisplayAnalysis:
    """Display configuration and frame/refresh relationship."""
    resolution: str = ""
    refresh_hz: int = 0
    frame_interval_ms: float = 0.0
    avg_frame_time_ms: Optional[float] = None
    match: DisplayMatch = DisplayMatch.INSUFFICIENT_DATA
    state: MetricState = MetricState.NOT_AVAILABLE

    def to_dict(self) -> dict:
        return {
            "resolution": self.resolution,
            "refresh_hz": self.refresh_hz,
            "frame_interval_ms": round(self.frame_interval_ms, 2),
            "avg_frame_time_ms": round(self.avg_frame_time_ms, 2) if self.avg_frame_time_ms else None,
            "match": self.match.value,
        }


@dataclass
class ResponsivenessSession:
    """Complete responsiveness analysis session."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    timestamp: float = field(default_factory=time.time)
    duration_seconds: float = 0.0

    # Target
    target_name: str = ""
    target_pid: int = 0
    target_status: TargetStatus = TargetStatus.NOT_DETECTED

    # Timelines
    input_timeline: InputTimeline = field(default_factory=InputTimeline)
    frame_timeline: FrameTimeline = field(default_factory=FrameTimeline)

    # System
    cpu_percent: float = 0.0
    gpu_percent: float = 0.0
    ram_percent: float = 0.0
    gpu_temp_c: Optional[float] = None

    # Latency
    latency: LatencyBreakdown = field(default_factory=LatencyBreakdown)

    # Display
    display: DisplayAnalysis = field(default_factory=DisplayAnalysis)

    # Correlation
    correlation: CorrelationResult = field(default_factory=CorrelationResult)

    # Classification
    state: ResponsivenessState = ResponsivenessState.INSUFFICIENT_DATA
    confidence: ConfidenceLevel = ConfidenceLevel.INCONCLUSIVE
    confidence_percent: int = 0
    evidence: List[str] = field(default_factory=list)
    explanation: str = ""

    # Score
    score: ResponsivenessScore = field(default_factory=ResponsivenessScore)

    # Input session reference
    input_session: Optional[InputDiagnosticSession] = None

    # Recommendations
    recommendations: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "state": self.state.value,
            "confidence": self.confidence.value,
            "confidence_percent": self.confidence_percent,
            "explanation": self.explanation,
            "score": self.score.to_dict(),
            "input": self.input_timeline.to_dict(),
            "frame": self.frame_timeline.to_dict(),
            "latency": self.latency.to_dict(),
            "display": self.display.to_dict(),
            "correlation": self.correlation.to_dict(),
            "cpu_percent": round(self.cpu_percent, 1),
            "gpu_percent": round(self.gpu_percent, 1),
            "ram_percent": round(self.ram_percent, 1),
        }


# ── Thresholds ───────────────────────────────────────────────────

CPU_HIGH = 85.0
CPU_ELEVATED = 70.0
GPU_SATURATED = 90.0
RAM_PRESSURE = 85.0
THERMAL_WARNING = 85.0
FRAME_CV_UNSTABLE = 0.35
FRAME_CV_MILD = 0.20
INPUT_CV_STABLE = 0.10
INPUT_CV_MILD = 0.25
MIN_SAMPLES = 5

# Score weights
SCORE_WEIGHTS = {
    "input_consistency": 0.20,
    "frame_pacing": 0.25,
    "cpu_headroom": 0.15,
    "memory_headroom": 0.15,
    "gpu_headroom": 0.10,
    "thermal": 0.05,
    "display_match": 0.05,
    "latency": 0.05,
}


# ── Input Timeline Analysis ──────────────────────────────────────

def analyze_input_timeline(
    input_session: Optional[InputDiagnosticSession] = None,
) -> InputTimeline:
    """Analyze input event timing from input diagnostic session."""
    timeline = InputTimeline()

    if not input_session:
        return timeline

    poll = input_session.polling
    if poll.state != MetricState.MEASURED:
        timeline.state = MetricState.NOT_AVAILABLE
        return timeline

    timeline.total_events = poll.total_events
    timeline.duration_seconds = poll.duration_seconds
    timeline.observed_rate_hz = poll.observed_rate_hz
    timeline.median_interval_ms = poll.median_interval_ms
    timeline.average_interval_ms = poll.average_interval_ms
    timeline.min_interval_ms = poll.min_interval_ms
    timeline.max_interval_ms = poll.max_interval_ms
    timeline.std_dev_ms = poll.interval_std_dev_ms
    timeline.coefficient_of_variation = poll.coefficient_of_variation
    timeline.state = MetricState.MEASURED

    # Max gap
    if poll.event_timestamps and len(poll.event_timestamps) >= 2:
        max_gap = 0
        for i in range(1, len(poll.event_timestamps)):
            gap = (poll.event_timestamps[i] - poll.event_timestamps[i - 1]) * 1000
            if gap > max_gap:
                max_gap = gap
        timeline.max_gap_ms = max_gap

    # Burst detection (events within 2ms of each other)
    if poll.event_timestamps:
        burst_count = 0
        for i in range(1, len(poll.event_timestamps)):
            interval = (poll.event_timestamps[i] - poll.event_timestamps[i - 1]) * 1000
            if interval < 2.0:
                burst_count += 1
        timeline.burst_count = burst_count

    # Consistency classification
    cv = timeline.coefficient_of_variation
    if cv < INPUT_CV_STABLE:
        timeline.consistency = "STABLE"
    elif cv < INPUT_CV_MILD:
        timeline.consistency = "MILDLY_UNSTABLE"
    else:
        timeline.consistency = "UNSTABLE"

    return timeline


# ── Frame Timeline Analysis ──────────────────────────────────────

def analyze_frame_timeline(
    samples: List[TelemetrySample],
) -> FrameTimeline:
    """Analyze frame delivery timing from telemetry samples."""
    timeline = FrameTimeline()

    ft_vals = [s.frame_time_ms for s in samples if s.frame_time_ms is not None and s.frame_time_ms > 0]
    fps_vals = [s.fps for s in samples if s.fps is not None and s.fps > 0]

    if not ft_vals or len(ft_vals) < 3:
        timeline.state = MetricState.NOT_AVAILABLE
        return timeline

    timeline.state = MetricState.MEASURED
    timeline.total_frames = len(ft_vals)

    # Frame time stats
    timeline.avg_frame_time_ms = statistics.mean(ft_vals)
    timeline.median_frame_time_ms = statistics.median(ft_vals)

    if len(ft_vals) > 1:
        timeline.frame_time_std_dev_ms = statistics.stdev(ft_vals)
        if timeline.avg_frame_time_ms > 0:
            timeline.frame_time_cv = timeline.frame_time_std_dev_ms / timeline.avg_frame_time_ms

    # Frame spikes (> 2x average)
    if timeline.avg_frame_time_ms:
        threshold = timeline.avg_frame_time_ms * 2
        timeline.frame_spikes = sum(1 for ft in ft_vals if ft > threshold)

    # FPS stats
    if fps_vals:
        timeline.avg_fps = statistics.mean(fps_vals)
        timeline.median_fps = statistics.median(fps_vals)

    # 1% low approximation
    if len(ft_vals) >= 10:
        sorted_ft = sorted(ft_vals)
        p1_idx = max(0, int(len(sorted_ft) * 0.99))
        p1_ft = sorted_ft[p1_idx]
        if p1_ft > 0:
            timeline.one_percent_low = 1000.0 / p1_ft

    # Consistency
    cv = timeline.frame_time_cv
    if cv < 0.10:
        timeline.consistency = "STABLE"
    elif cv < FRAME_CV_MILD:
        timeline.consistency = "MILDLY_UNSTABLE"
    elif cv < FRAME_CV_UNSTABLE:
        timeline.consistency = "UNSTABLE"
    else:
        timeline.consistency = "UNSTABLE"

    return timeline


# ── Display Analysis ─────────────────────────────────────────────

def analyze_display(
    display_refresh_hz: int = 0,
    frame_timeline: Optional[FrameTimeline] = None,
) -> DisplayAnalysis:
    """Analyze display configuration and frame/refresh relationship."""
    analysis = DisplayAnalysis()

    if display_refresh_hz <= 0:
        try:
            from app.system.display import display_monitor
            display = display_monitor.detect()
            analysis.refresh_hz = display.refresh_rate_hz
            analysis.resolution = f"{display.resolution_x}x{display.resolution_y}"
        except Exception:
            analysis.state = MetricState.NOT_AVAILABLE
            return analysis
    else:
        analysis.refresh_hz = display_refresh_hz

    if analysis.refresh_hz > 0:
        analysis.frame_interval_ms = 1000.0 / analysis.refresh_hz
        analysis.state = MetricState.MEASURED

    # Compare with frame pacing
    if frame_timeline and frame_timeline.avg_frame_time_ms and analysis.refresh_hz > 0:
        analysis.avg_frame_time_ms = frame_timeline.avg_frame_time_ms
        ratio = frame_timeline.avg_frame_time_ms / analysis.frame_interval_ms
        if ratio < 1.1:
            analysis.match = DisplayMatch.GOOD_MATCH
        elif ratio < 1.5:
            analysis.match = DisplayMatch.VARIABLE
        else:
            analysis.match = DisplayMatch.FRAME_RATE_BELOW_REFRESH

    return analysis


# ── Latency Breakdown ───────────────────────────────────────────

def calculate_latency_breakdown(
    display_refresh_hz: int = 60,
    cpu_percent: float = 0.0,
    frame_time_ms: Optional[float] = None,
    input_session: Optional[InputDiagnosticSession] = None,
) -> LatencyBreakdown:
    """Calculate decomposed latency estimate."""
    breakdown = LatencyBreakdown()

    # Display
    if display_refresh_hz > 0:
        breakdown.display_ms = 1000.0 / display_refresh_hz
        breakdown.display_state = MetricState.MEASURED

    # Scheduling (inferred from CPU)
    if cpu_percent > 80:
        breakdown.scheduling_ms = 2.0
    elif cpu_percent > 50:
        breakdown.scheduling_ms = 1.0
    else:
        breakdown.scheduling_ms = 0.5
    breakdown.scheduling_state = MetricState.INFERRED

    # Frame (measured from PresentMon when available)
    if frame_time_ms and frame_time_ms > 0:
        breakdown.frame_ms = frame_time_ms
        breakdown.frame_state = MetricState.MEASURED
    else:
        breakdown.frame_ms = breakdown.display_ms
        breakdown.frame_state = MetricState.INFERRED if breakdown.display_ms > 0 else MetricState.NOT_AVAILABLE

    # Presentation (same as frame time for now)
    breakdown.presentation_ms = breakdown.frame_ms
    breakdown.presentation_state = breakdown.frame_state

    # Input (from input session)
    if input_session and input_session.latency.state != MetricState.NOT_AVAILABLE:
        breakdown.input_ms = input_session.latency.estimated_total_ms
        breakdown.input_state = MetricState.INFERRED
    else:
        breakdown.input_ms = breakdown.display_ms * 0.5
        breakdown.input_state = MetricState.INFERRED

    # Total
    total = breakdown.display_ms + breakdown.scheduling_ms
    breakdown.estimated_total_ms = total
    if breakdown.display_state != MetricState.NOT_AVAILABLE:
        breakdown.total_state = MetricState.INFERRED
    else:
        breakdown.total_state = MetricState.NOT_AVAILABLE

    breakdown.note = "All values are ESTIMATED unless hardware instrumentation exists."

    return breakdown


# ── Input/Frame Correlation ─────────────────────────────────────

def correlate_input_frame(
    input_timeline: InputTimeline,
    frame_timeline: FrameTimeline,
    samples: List[TelemetrySample],
) -> CorrelationResult:
    """Correlate input activity with frame timing."""
    result = CorrelationResult()

    if (input_timeline.state != MetricState.MEASURED or
        frame_timeline.state != MetricState.MEASURED):
        result.strength = CorrelationStrength.INSUFFICIENT_DATA
        result.description = "Insufficient data for correlation analysis"
        return result

    # Simple correlation: check if input instability aligns with frame instability
    input_unstable = input_timeline.coefficient_of_variation > INPUT_CV_MILD
    frame_unstable = frame_timeline.frame_time_cv > FRAME_CV_MILD

    if input_unstable and frame_unstable:
        result.strength = CorrelationStrength.POSSIBLY_RELATED
        result.description = "Both input and frame timing show instability"
        result.evidence.append(f"Input CV={input_timeline.coefficient_of_variation:.3f}")
        result.evidence.append(f"Frame CV={frame_timeline.frame_time_cv:.3f}")
    elif not input_unstable and frame_unstable:
        result.strength = CorrelationStrength.NO_CLEAR_CORRELATION
        result.description = "Input is stable but frame timing is unstable — likely not an input issue"
        result.evidence.append("Input events are consistent")
        result.evidence.append(f"Frame timing unstable (CV={frame_timeline.frame_time_cv:.3f})")
    elif input_unstable and not frame_unstable:
        result.strength = CorrelationStrength.POSSIBLY_RELATED
        result.description = "Input timing is unstable while frames are stable — possible input-system issue"
        result.evidence.append(f"Input CV={input_timeline.coefficient_of_variation:.3f}")
        result.evidence.append("Frame pacing is stable")
    else:
        result.strength = CorrelationStrength.NO_CLEAR_CORRELATION
        result.description = "Both input and frame timing are stable"
        result.evidence.append("No correlation needed — both are stable")

    # Check for frame spikes and input events during spikes
    if frame_timeline.frame_spikes > 0 and input_timeline.total_events > 0:
        result.total_spikes = frame_timeline.frame_spikes
        # Estimate overlap (simplified)
        spike_ratio = frame_timeline.frame_spikes / max(frame_timeline.total_frames, 1)
        input_during_spikes = int(input_timeline.total_events * spike_ratio)
        result.input_events_during_spikes = input_during_spikes
        result.spike_overlap_percent = spike_ratio * 100

    return result


# ── Responsiveness Classification ────────────────────────────────

def classify_responsiveness(
    input_timeline: InputTimeline,
    frame_timeline: FrameTimeline,
    cpu_percent: float,
    gpu_percent: float,
    ram_percent: float,
    gpu_temp_c: Optional[float],
    correlation: CorrelationResult,
) -> Tuple[ResponsivenessState, int, List[str], str]:
    """
    Classify overall responsiveness from all evidence.

    Returns:
        (state, confidence_percent, evidence, explanation)
    """
    evidence = []
    scores = {s: 0 for s in ResponsivenessState if s != ResponsivenessState.INSUFFICIENT_DATA}

    n = 0  # evidence count

    # Input analysis
    if input_timeline.state == MetricState.MEASURED:
        n += 1
        if input_timeline.consistency == "UNSTABLE":
            scores[ResponsivenessState.INPUT_LIMITED] += 35
            evidence.append(f"Input events inconsistent (CV={input_timeline.coefficient_of_variation:.3f})")
        elif input_timeline.consistency == "MILDLY_UNSTABLE":
            scores[ResponsivenessState.INPUT_LIMITED] += 15

    # Frame analysis
    if frame_timeline.state == MetricState.MEASURED:
        n += 1
        if frame_timeline.consistency in ("UNSTABLE",):
            scores[ResponsivenessState.FRAME_LIMITED] += 35
            evidence.append(f"Frame timing unstable (CV={frame_timeline.frame_time_cv:.3f})")
        elif frame_timeline.consistency == "MILDLY_UNSTABLE":
            scores[ResponsivenessState.FRAME_LIMITED] += 15

    # CPU
    n += 1
    if cpu_percent >= CPU_HIGH:
        scores[ResponsivenessState.CPU_SCHEDULING_LIMITED] += 35
        evidence.append(f"CPU at {cpu_percent:.1f}% (scheduling pressure)")
    elif cpu_percent >= CPU_ELEVATED:
        scores[ResponsivenessState.CPU_SCHEDULING_LIMITED] += 10

    # Memory
    if ram_percent >= RAM_PRESSURE:
        scores[ResponsivenessState.MEMORY_LIMITED] += 35
        evidence.append(f"RAM at {ram_percent:.1f}% (memory pressure)")
        n += 1
    elif ram_percent > 0:
        n += 1

    # GPU
    if gpu_percent >= GPU_SATURATED:
        scores[ResponsivenessState.GPU_LIMITED] += 35
        evidence.append(f"GPU at {gpu_percent:.1f}% (saturated)")
        n += 1
    elif gpu_percent > 0:
        n += 1

    # Thermal
    if gpu_temp_c and gpu_temp_c >= THERMAL_WARNING:
        scores[ResponsivenessState.THERMAL_LIMITED] += 30
        evidence.append(f"GPU temperature {gpu_temp_c:.0f}°C")
        n += 1

    # Multi-resource
    high_count = sum(1 for s, v in scores.items() if v >= 30 and s not in (
        ResponsivenessState.INPUT_LIMITED, ResponsivenessState.INSUFFICIENT_DATA,
    ))
    if high_count >= 2:
        scores[ResponsivenessState.MULTI_RESOURCE_LIMITED] += 25
        evidence.append(f"{high_count} resources under pressure simultaneously")

    # Check if we have any real measured data
    has_measured_data = (
        input_timeline.state == MetricState.MEASURED or
        frame_timeline.state == MetricState.MEASURED or
        cpu_percent > 0 or gpu_percent > 0 or ram_percent > 0
    )

    if not has_measured_data:
        return (
            ResponsivenessState.INSUFFICIENT_DATA, 0,
            ["No measured telemetry data available"],
            "Not enough telemetry to assess responsiveness.",
        )

    # Check for responsive case
    if not any(v >= 20 for k, v in scores.items() if k != ResponsivenessState.INSUFFICIENT_DATA):
        scores[ResponsivenessState.RESPONSIVE] += 50
        evidence.append("No significant input or resource issues detected")

    # Find best
    candidates = [(s, v) for s, v in scores.items() if v > 0 and s != ResponsivenessState.INSUFFICIENT_DATA]
    if not candidates:
        return (
            ResponsivenessState.RESPONSIVE, 40,
            ["System appears responsive"],
            "No significant issues detected with available data.",
        )

    candidates.sort(key=lambda x: x[1], reverse=True)
    best, best_score = candidates[0]

    # Confidence from sample count and evidence
    confidence = min(best_score + (10 if n >= 5 else 5), 100)

    # Generate explanation
    explanations = {
        ResponsivenessState.RESPONSIVE: "System appears responsive. No significant input or resource bottlenecks detected.",
        ResponsivenessState.INPUT_LIMITED: "Input event timing is inconsistent. This may indicate a mouse, USB, or input-pipeline issue. Changing sensitivity is unlikely to fix this.",
        ResponsivenessState.FRAME_LIMITED: "Frame delivery is unstable. This is likely NOT an input configuration issue. Investigate background interference, thermal throttling, or emulator scheduling.",
        ResponsivenessState.CPU_SCHEDULING_LIMITED: "CPU scheduling pressure is causing frame and input timing inconsistencies. The emulator may not be receiving sufficient CPU time.",
        ResponsivenessState.MEMORY_LIMITED: "High memory pressure may be causing system paging and scheduling delays that affect both frame delivery and input timing.",
        ResponsivenessState.GPU_LIMITED: "GPU is saturated. Frame delivery is limited by GPU rendering capacity. Reducing graphics quality may help.",
        ResponsivenessState.THERMAL_LIMITED: "Thermal conditions are limiting performance. Reducing background load may help lower temperatures.",
        ResponsivenessState.MULTI_RESOURCE_LIMITED: "Multiple system resources are under simultaneous pressure. Address the most critical resource first.",
    }

    return best, confidence, evidence, explanations.get(best, "Analysis complete.")


# ── Responsiveness Score ─────────────────────────────────────────

def calculate_responsiveness_score(
    input_timeline: InputTimeline,
    frame_timeline: FrameTimeline,
    cpu_percent: float,
    gpu_percent: float,
    ram_percent: float,
    gpu_temp_c: Optional[float],
    display: DisplayAnalysis,
    latency: LatencyBreakdown,
) -> ResponsivenessScore:
    """Calculate evidence-based responsiveness score (0-100)."""
    score = ResponsivenessScore(state=MetricState.NOT_AVAILABLE)
    components = []

    def _add(name, value, weight, source, confidence):
        components.append({
            "name": name, "value": value, "weight": weight,
            "source": source, "confidence": confidence,
        })

    # 1. Input consistency
    if input_timeline.state == MetricState.MEASURED:
        if input_timeline.consistency == "STABLE":
            val = 95
        elif input_timeline.consistency == "MILDLY_UNSTABLE":
            val = 70
        else:
            val = 40
        _add("Input Consistency", val, SCORE_WEIGHTS["input_consistency"], "MEASURED", "HIGH")
    else:
        _add("Input Consistency", 60, SCORE_WEIGHTS["input_consistency"], "NOT_AVAILABLE", "LOW")

    # 2. Frame pacing
    if frame_timeline.state == MetricState.MEASURED:
        cv = frame_timeline.frame_time_cv
        if cv < 0.10:
            val = 95
        elif cv < 0.20:
            val = 80
        elif cv < 0.35:
            val = 60
        else:
            val = 30
        _add("Frame Pacing", val, SCORE_WEIGHTS["frame_pacing"], "MEASURED", "HIGH")
    else:
        _add("Frame Pacing", 60, SCORE_WEIGHTS["frame_pacing"], "NOT_AVAILABLE", "LOW")

    # 3. CPU headroom
    if cpu_percent > 0:
        if cpu_percent < 50:
            val = 95
        elif cpu_percent < 70:
            val = 80
        elif cpu_percent < 85:
            val = 60
        else:
            val = 30
        _add("CPU Headroom", val, SCORE_WEIGHTS["cpu_headroom"], "MEASURED", "HIGH")
    else:
        _add("CPU Headroom", 60, SCORE_WEIGHTS["cpu_headroom"], "NOT_AVAILABLE", "LOW")

    # 4. Memory headroom
    if ram_percent > 0:
        if ram_percent < 60:
            val = 95
        elif ram_percent < 75:
            val = 80
        elif ram_percent < 85:
            val = 60
        else:
            val = 30
        _add("Memory Headroom", val, SCORE_WEIGHTS["memory_headroom"], "MEASURED", "HIGH")
    else:
        _add("Memory Headroom", 60, SCORE_WEIGHTS["memory_headroom"], "NOT_AVAILABLE", "LOW")

    # 5. GPU headroom
    if gpu_percent > 0:
        if gpu_percent < 60:
            val = 90
        elif gpu_percent < 80:
            val = 75
        elif gpu_percent < 90:
            val = 55
        else:
            val = 30
        _add("GPU Headroom", val, SCORE_WEIGHTS["gpu_headroom"], "MEASURED", "HIGH")
    else:
        _add("GPU Headroom", 60, SCORE_WEIGHTS["gpu_headroom"], "NOT_AVAILABLE", "LOW")

    # 6. Thermal
    if gpu_temp_c is not None:
        if gpu_temp_c < 70:
            val = 95
        elif gpu_temp_c < 80:
            val = 80
        elif gpu_temp_c < 85:
            val = 60
        else:
            val = 30
        _add("Thermal", val, SCORE_WEIGHTS["thermal"], "MEASURED", "HIGH")
    else:
        _add("Thermal", 70, SCORE_WEIGHTS["thermal"], "NOT_AVAILABLE", "LOW")

    # 7. Display match
    if display.match == DisplayMatch.GOOD_MATCH:
        val = 90
    elif display.match == DisplayMatch.VARIABLE:
        val = 65
    elif display.match == DisplayMatch.FRAME_RATE_BELOW_REFRESH:
        val = 40
    else:
        val = 60
    _add("Display Match", val, SCORE_WEIGHTS["display_match"],
         display.state.value if display.state else "NOT_AVAILABLE",
         "HIGH" if display.state == MetricState.MEASURED else "LOW")

    # 8. Latency
    if latency.total_state != MetricState.NOT_AVAILABLE:
        total = latency.estimated_total_ms
        if total < 10:
            val = 90
        elif total < 17:
            val = 75
        elif total < 33:
            val = 55
        else:
            val = 35
        _add("Latency", val, SCORE_WEIGHTS["latency"], "ESTIMATED", "MODERATE")
    else:
        _add("Latency", 60, SCORE_WEIGHTS["latency"], "NOT_AVAILABLE", "LOW")

    # Calculate weighted score
    total_weight = sum(c["weight"] for c in components)
    if total_weight > 0:
        weighted = sum(c["value"] * c["weight"] for c in components)
        score.overall = int(weighted / total_weight)

    # Level
    if score.overall >= 85:
        score.level = "EXCELLENT"
    elif score.overall >= 70:
        score.level = "GOOD"
    elif score.overall >= 50:
        score.level = "FAIR"
    else:
        score.level = "POOR"

    score.components = components
    score.state = MetricState.MEASURED if any(c["source"] == "MEASURED" for c in components) else MetricState.INFERRED

    return score


# ── Recommendations ──────────────────────────────────────────────

def generate_responsiveness_recommendations(
    state: ResponsivenessState,
    input_timeline: InputTimeline,
    frame_timeline: FrameTimeline,
    ram_percent: float,
    cpu_percent: float,
    correlation: CorrelationResult,
) -> List[Dict]:
    """Generate evidence-based recommendations."""
    recs = []

    if state == ResponsivenessState.INSUFFICIENT_DATA:
        recs.append({
            "category": "DATA",
            "priority": "MEDIUM",
            "reason": "Insufficient telemetry for analysis",
            "action": "Collect more samples",
        })
        return recs

    if state == ResponsivenessState.INPUT_LIMITED:
        recs.append({
            "category": "INPUT",
            "priority": "HIGH",
            "reason": "Input event timing is inconsistent. Check mouse USB connection, "
                      "device software, or polling configuration.",
            "action": "Investigate input pipeline",
        })

    if state == ResponsivenessState.FRAME_LIMITED:
        recs.append({
            "category": "FRAME_PACING",
            "priority": "HIGH",
            "reason": "Frame delivery is unstable. This is likely NOT an input configuration issue. "
                      "Investigate background interference, thermal throttling, or emulator scheduling.",
            "action": "Investigate frame delivery",
        })

    if state == ResponsivenessState.CPU_SCHEDULING_LIMITED:
        recs.append({
            "category": "CPU",
            "priority": "HIGH",
            "reason": "CPU scheduling pressure affects both frame delivery and input timing. "
                      "Close unnecessary background applications.",
            "action": "Reduce CPU load",
        })

    if state == ResponsivenessState.MEMORY_LIMITED:
        recs.append({
            "category": "MEMORY",
            "priority": "HIGH",
            "reason": "High memory pressure may cause paging delays. "
                      "Close unnecessary applications to free RAM.",
            "action": "Reduce memory pressure",
        })

    if state == ResponsivenessState.GPU_LIMITED:
        recs.append({
            "category": "GPU",
            "priority": "MEDIUM",
            "reason": "GPU is saturated. Reducing emulator graphics quality may help.",
            "action": "Reduce graphics load",
        })

    if state == ResponsivenessState.THERMAL_LIMITED:
        recs.append({
            "category": "THERMAL",
            "priority": "MEDIUM",
            "reason": "Thermal conditions limit performance. Reducing background load may help.",
            "action": "Reduce thermal load",
        })

    if state == ResponsivenessState.MULTI_RESOURCE_LIMITED:
        recs.append({
            "category": "MULTI",
            "priority": "HIGH",
            "reason": "Multiple resources under pressure. Address the most critical first.",
            "action": "Prioritize resource relief",
        })

    if state == ResponsivenessState.RESPONSIVE:
        recs.append({
            "category": "STATUS",
            "priority": "LOW",
            "reason": "System appears responsive. No action required.",
            "action": "Monitor",
        })

    return recs


# ── Main Analyzer ────────────────────────────────────────────────

def analyze_responsiveness(
    samples: List[TelemetrySample],
    input_session: Optional[InputDiagnosticSession] = None,
    target_name: str = "",
    target_pid: int = 0,
    duration_seconds: float = 0.0,
) -> ResponsivenessSession:
    """
    Run comprehensive responsiveness analysis.

    Correlates input, frame, CPU, GPU, RAM, thermal, and display data
    to identify the actual technical cause of perceived issues.
    """
    session = ResponsivenessSession(
        target_name=target_name,
        target_pid=target_pid,
        duration_seconds=duration_seconds,
        input_session=input_session,
    )

    # System metrics from samples
    cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
    gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
    ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
    ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
    gpu_temps = [s.gpu_temperature_c for s in samples if s.gpu_temperature_c is not None]

    if cpu_vals:
        session.cpu_percent = statistics.mean(cpu_vals)
    if gpu_vals:
        session.gpu_percent = statistics.mean(gpu_vals)
    if ram_used and ram_total and ram_total[0] > 0:
        session.ram_percent = (statistics.mean(ram_used) / ram_total[0]) * 100
    if gpu_temps:
        session.gpu_temp_c = max(gpu_temps)

    # Target status
    if target_pid > 0:
        session.target_status = TargetStatus.ACTIVE
    else:
        session.target_status = TargetStatus.NOT_DETECTED

    # Input timeline
    session.input_timeline = analyze_input_timeline(input_session)

    # Frame timeline
    session.frame_timeline = analyze_frame_timeline(samples)

    # Display
    display_refresh = 0
    if input_session:
        display_refresh = input_session.display_refresh_hz
    session.display = analyze_display(display_refresh, session.frame_timeline)

    # Latency breakdown
    frame_time = None
    if session.frame_timeline.avg_frame_time_ms:
        frame_time = session.frame_timeline.avg_frame_time_ms
    session.latency = calculate_latency_breakdown(
        display_refresh_hz=session.display.refresh_hz,
        cpu_percent=session.cpu_percent,
        frame_time_ms=frame_time,
        input_session=input_session,
    )

    # Correlation
    session.correlation = correlate_input_frame(
        session.input_timeline, session.frame_timeline, samples,
    )

    # Classification
    session.state, session.confidence_percent, session.evidence, session.explanation = \
        classify_responsiveness(
            session.input_timeline, session.frame_timeline,
            session.cpu_percent, session.gpu_percent,
            session.ram_percent, session.gpu_temp_c,
            session.correlation,
        )

    # Confidence level
    if session.confidence_percent >= 70:
        session.confidence = ConfidenceLevel.HIGH
    elif session.confidence_percent >= 50:
        session.confidence = ConfidenceLevel.MODERATE
    elif session.confidence_percent > 0:
        session.confidence = ConfidenceLevel.LOW
    else:
        session.confidence = ConfidenceLevel.INCONCLUSIVE

    # Score
    session.score = calculate_responsiveness_score(
        session.input_timeline, session.frame_timeline,
        session.cpu_percent, session.gpu_percent,
        session.ram_percent, session.gpu_temp_c,
        session.display, session.latency,
    )

    # Recommendations
    session.recommendations = generate_responsiveness_recommendations(
        session.state, session.input_timeline, session.frame_timeline,
        session.ram_percent, session.cpu_percent, session.correlation,
    )

    return session


# ── CLI Formatting ───────────────────────────────────────────────

def format_responsiveness(session: ResponsivenessSession) -> str:
    """Format responsiveness analysis for CLI output."""
    lines = []
    lines.append("=" * 55)
    lines.append("HEAVEN SOCIETY — RESPONSIVENESS ANALYSIS")
    lines.append("=" * 55)
    lines.append("")

    # Target
    lines.append("TARGET")
    if session.target_name:
        lines.append(f"  {session.target_name}  PID: {session.target_pid}")
    else:
        lines.append("  No emulator detected")
    lines.append("")

    # Input
    inp = session.input_timeline
    lines.append("INPUT")
    if inp.state == MetricState.MEASURED:
        lines.append(f"  Events:        {inp.total_events}")
        lines.append(f"  Rate:          {inp.observed_rate_hz:.0f} Hz")
        lines.append(f"  CV:            {inp.coefficient_of_variation:.3f}")
        lines.append(f"  Consistency:   {inp.consistency}")
    else:
        lines.append(f"  State:         NOT_AVAILABLE")
    lines.append("")

    # Frame
    fr = session.frame_timeline
    lines.append("FRAME PACING")
    if fr.state == MetricState.MEASURED:
        if fr.avg_fps:
            lines.append(f"  FPS:           {fr.avg_fps:.1f}")
        if fr.avg_frame_time_ms:
            lines.append(f"  Frame Time:    {fr.avg_frame_time_ms:.1f} ms")
        lines.append(f"  CV:            {fr.frame_time_cv:.3f}")
        lines.append(f"  Spikes:        {fr.frame_spikes}")
        lines.append(f"  Consistency:   {fr.consistency}")
    else:
        lines.append(f"  State:         NOT_AVAILABLE")
    lines.append("")

    # System
    lines.append("SYSTEM")
    lines.append(f"  CPU:           {session.cpu_percent:.1f}%")
    lines.append(f"  GPU:           {session.gpu_percent:.1f}%")
    lines.append(f"  RAM:           {session.ram_percent:.1f}%")
    if session.gpu_temp_c:
        lines.append(f"  GPU Temp:      {session.gpu_temp_c:.0f}°C")
    lines.append("")

    # Display
    disp = session.display
    lines.append("DISPLAY")
    if disp.state == MetricState.MEASURED:
        lines.append(f"  Refresh:       {disp.refresh_hz} Hz")
        lines.append(f"  Interval:      {disp.frame_interval_ms:.2f} ms")
        lines.append(f"  Match:         {disp.match.value}")
    else:
        lines.append(f"  State:         NOT_AVAILABLE")
    lines.append("")

    # Latency
    lat = session.latency
    lines.append("LATENCY (ALL ESTIMATED)")
    lines.append(f"  Display:       {lat.display_ms:.1f} ms  [{lat.display_state.value}]")
    lines.append(f"  Scheduling:    {lat.scheduling_ms:.1f} ms  [{lat.scheduling_state.value}]")
    lines.append(f"  Frame:         {lat.frame_ms:.1f} ms  [{lat.frame_state.value}]")
    lines.append(f"  Total:         {lat.estimated_total_ms:.1f} ms  [{lat.total_state.value}]")
    lines.append("")

    # Correlation
    corr = session.correlation
    lines.append("CORRELATION")
    lines.append(f"  Strength:      {corr.strength.value}")
    lines.append(f"  {corr.description}")
    if corr.evidence:
        for ev in corr.evidence[:3]:
            lines.append(f"  Evidence:      {ev}")
    lines.append("")

    # Score
    sc = session.score
    if sc.state != MetricState.NOT_AVAILABLE:
        lines.append("RESPONSIVENESS SCORE")
        lines.append(f"  Score:         {sc.overall}/100 ({sc.level})")
        for c in sc.components:
            lines.append(f"  {c['name']:18s} {c['value']:3d}/100  [{c['source']}]")
    else:
        lines.append("RESPONSIVENESS SCORE")
        lines.append(f"  Score:         NOT_AVAILABLE")
    lines.append("")

    # Classification
    state_str = session.state.value.replace("_", " ").title()
    lines.append("CLASSIFICATION")
    lines.append(f"  State:         {state_str}")
    lines.append(f"  Confidence:    {session.confidence.value} ({session.confidence_percent}%)")
    lines.append(f"  {session.explanation}")
    lines.append("")

    # Recommendations
    if session.recommendations:
        lines.append("RECOMMENDATIONS")
        lines.append("-" * 55)
        for r in session.recommendations:
            lines.append(f"  [{r['category']}] {r['priority']}")
            lines.append(f"    {r['reason']}")
            lines.append(f"    Action: {r['action']}")
            lines.append("")

    lines.append("=" * 55)
    return "\n".join(lines)
