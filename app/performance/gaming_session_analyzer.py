"""
Gaming Session Analyzer — Phase 40.

Provides a structured gaming session lifecycle with timeline aggregation,
event detection, root-cause analysis, session scoring, and reporting.

STRICTLY ANALYSIS — never modifies system state.
Reuses existing: RealtimeTelemetry, BottleneckAnalyzer, TelemetrySample,
TelemetrySession, PerformanceEvent, and MetricState conventions.
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
    DataAvailability,
    EventType,
    EventSeverity,
    PerformanceEvent,
    TelemetrySample,
)
from app.utils.logger import get_logger

logger = get_logger("performance.gaming_session_analyzer")


# ── Enums ────────────────────────────────────────────────────────

class SessionState(Enum):
    """Lifecycle state of a gaming session."""
    IDLE = "IDLE"
    RUNNING = "RUNNING"
    STOPPED = "STOPPED"


class RootCause(Enum):
    """Root-cause classification."""
    CPU = "CPU"
    GPU = "GPU"
    MEMORY = "MEMORY"
    THERMAL = "THERMAL"
    FRAME_TIME = "FRAME_TIME"
    INPUT = "INPUT"
    NO_CLEAR = "NO_CLEAR"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class SessionScoreLevel(Enum):
    """Session score quality levels."""
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class MetricSource(Enum):
    """How a metric was obtained."""
    MEASURED = "MEASURED"
    INFERRED = "INFERRED"
    ESTIMATED = "ESTIMATED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


# ── Models ───────────────────────────────────────────────────────

@dataclass
class SessionTimeline:
    """Aggregated timeline statistics for a session metric."""
    avg: Optional[float] = None
    median: Optional[float] = None
    peak: Optional[float] = None
    minimum: Optional[float] = None
    std_dev: Optional[float] = None
    source: MetricSource = MetricSource.NOT_AVAILABLE
    sample_count: int = 0

    def to_dict(self) -> dict:
        return {
            "avg": round(self.avg, 2) if self.avg is not None else None,
            "median": round(self.median, 2) if self.median is not None else None,
            "peak": round(self.peak, 2) if self.peak is not None else None,
            "minimum": round(self.minimum, 2) if self.minimum is not None else None,
            "std_dev": round(self.std_dev, 2) if self.std_dev is not None else None,
            "source": self.source.value,
            "sample_count": self.sample_count,
        }


@dataclass
class SessionEvent:
    """Detected event during a gaming session."""
    timestamp: float = 0.0
    event_type: str = ""
    severity: str = "INFO"
    measured_value: float = 0.0
    threshold: float = 0.0
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type,
            "severity": self.severity,
            "measured_value": round(self.measured_value, 2),
            "threshold": round(self.threshold, 2),
            "explanation": self.explanation,
        }


@dataclass
class SessionScore:
    """Gaming session quality score (0-100)."""
    overall: int = 0
    level: SessionScoreLevel = SessionScoreLevel.NOT_AVAILABLE
    performance_stability: int = 0
    frame_pacing: int = 0
    resource_headroom: int = 0
    thermal: int = 0
    confidence: int = 0
    components: List[Dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "overall": self.overall,
            "level": self.level.value,
            "performance_stability": self.performance_stability,
            "frame_pacing": self.frame_pacing,
            "resource_headroom": self.resource_headroom,
            "thermal": self.thermal,
            "confidence": self.confidence,
            "components": self.components,
        }


@dataclass
class WorstPeriod:
    """Description of the worst performance period."""
    start_index: int = 0
    end_index: int = 0
    avg_fps: Optional[float] = None
    avg_cpu: Optional[float] = None
    avg_gpu: Optional[float] = None
    event_count: int = 0
    duration_seconds: float = 0.0

    def to_dict(self) -> dict:
        return {
            "start_index": self.start_index,
            "end_index": self.end_index,
            "avg_fps": round(self.avg_fps, 1) if self.avg_fps else None,
            "avg_cpu": round(self.avg_cpu, 1) if self.avg_cpu else None,
            "avg_gpu": round(self.avg_gpu, 1) if self.avg_gpu else None,
            "event_count": self.event_count,
            "duration_seconds": round(self.duration_seconds, 1),
        }


@dataclass
class GamingSessionReport:
    """Complete gaming session report."""
    session_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0

    # Target
    target_name: str = ""
    target_pid: int = 0

    # Baseline (captured at start)
    baseline_cpu: Optional[float] = None
    baseline_gpu: Optional[float] = None
    baseline_ram_percent: Optional[float] = None
    baseline_gpu_temp: Optional[float] = None

    # Timeline aggregations
    cpu_timeline: SessionTimeline = field(default_factory=SessionTimeline)
    gpu_timeline: SessionTimeline = field(default_factory=SessionTimeline)
    ram_timeline: SessionTimeline = field(default_factory=SessionTimeline)
    gpu_temp_timeline: SessionTimeline = field(default_factory=SessionTimeline)
    fps_timeline: SessionTimeline = field(default_factory=SessionTimeline)
    frame_time_timeline: SessionTimeline = field(default_factory=SessionTimeline)

    # Events
    events: List[SessionEvent] = field(default_factory=list)
    event_summary: Dict[str, int] = field(default_factory=dict)

    # Root cause
    root_cause: RootCause = RootCause.INSUFFICIENT_DATA
    root_cause_confidence: int = 0
    root_cause_evidence: List[str] = field(default_factory=list)

    # Worst period
    worst_period: WorstPeriod = field(default_factory=WorstPeriod)

    # Score
    score: SessionScore = field(default_factory=SessionScore)

    # Recommendations
    recommendations: List[Dict] = field(default_factory=list)

    # Sample count
    sample_count: int = 0

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": round(self.duration_seconds, 1),
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "baseline": {
                "cpu": self.baseline_cpu,
                "gpu": self.baseline_gpu,
                "ram_percent": self.baseline_ram_percent,
                "gpu_temp": self.baseline_gpu_temp,
            },
            "cpu": self.cpu_timeline.to_dict(),
            "gpu": self.gpu_timeline.to_dict(),
            "ram": self.ram_timeline.to_dict(),
            "gpu_temp": self.gpu_temp_timeline.to_dict(),
            "fps": self.fps_timeline.to_dict(),
            "frame_time": self.frame_time_timeline.to_dict(),
            "event_count": len(self.events),
            "event_summary": self.event_summary,
            "root_cause": self.root_cause.value,
            "root_cause_confidence": self.root_cause_confidence,
            "worst_period": self.worst_period.to_dict(),
            "score": self.score.to_dict(),
            "recommendations": self.recommendations,
            "sample_count": self.sample_count,
        }


# ── Thresholds ───────────────────────────────────────────────────

CPU_HIGH = 85.0
GPU_SATURATED = 90.0
RAM_PRESSURE = 85.0
THERMAL_WARNING = 85.0
FRAME_CV_UNSTABLE = 0.35
FRAME_CV_MILD = 0.20
FPS_LOW = 30.0
FPS_MEDIUM = 50.0
FRAME_SPIKE_MS = 50.0
MIN_SAMPLES = 3
WORST_WINDOW = 10  # samples for worst-period detection


# ── Timeline Aggregation ─────────────────────────────────────────

def _aggregate_timeline(values: List[float]) -> SessionTimeline:
    """Aggregate a list of values into a SessionTimeline."""
    timeline = SessionTimeline()
    if not values:
        return timeline

    timeline.sample_count = len(values)
    timeline.avg = statistics.mean(values)
    timeline.median = statistics.median(values)
    timeline.peak = max(values)
    timeline.minimum = min(values)
    if len(values) > 1:
        timeline.std_dev = statistics.stdev(values)
    timeline.source = MetricSource.MEASURED
    return timeline


def aggregate_timelines(samples: List[TelemetrySample]) -> Dict[str, SessionTimeline]:
    """Aggregate all timeline metrics from a list of samples."""
    cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
    gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
    ram_vals = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
    ram_total_vals = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
    gpu_temp_vals = [s.gpu_temperature_c for s in samples if s.gpu_temperature_c is not None]
    fps_vals = [s.fps for s in samples if s.fps is not None and s.fps > 0]
    ft_vals = [s.frame_time_ms for s in samples if s.frame_time_ms is not None and s.frame_time_ms > 0]

    result = {
        "cpu": _aggregate_timeline(cpu_vals),
        "gpu": _aggregate_timeline(gpu_vals),
        "ram": _aggregate_timeline(ram_vals),
        "gpu_temp": _aggregate_timeline(gpu_temp_vals),
        "fps": _aggregate_timeline(fps_vals),
        "frame_time": _aggregate_timeline(ft_vals),
    }

    # RAM percentage timeline
    if ram_vals and ram_total_vals and ram_total_vals[0] > 0:
        ram_pct = [(u / ram_total_vals[0]) * 100 for u in ram_vals]
        result["ram_percent"] = _aggregate_timeline(ram_pct)
        result["ram_percent"].source = MetricSource.MEASURED

    return result


# ── Event Detection ──────────────────────────────────────────────

def detect_session_events(samples: List[TelemetrySample]) -> List[SessionEvent]:
    """Detect performance events from telemetry samples."""
    events = []

    for s in samples:
        # FPS drop
        if s.fps is not None and s.fps > 0:
            if s.fps < FPS_LOW:
                events.append(SessionEvent(
                    timestamp=s.timestamp,
                    event_type=EventType.FPS_DROP.value,
                    severity=EventSeverity.CRITICAL.value,
                    measured_value=s.fps,
                    threshold=FPS_LOW,
                    explanation=f"FPS dropped to {s.fps:.1f}",
                ))
            elif s.fps < FPS_MEDIUM:
                events.append(SessionEvent(
                    timestamp=s.timestamp,
                    event_type=EventType.FPS_DROP.value,
                    severity=EventSeverity.WARNING.value,
                    measured_value=s.fps,
                    threshold=FPS_MEDIUM,
                    explanation=f"FPS at {s.fps:.1f} (below expected)",
                ))

        # Frame time spike
        if s.frame_time_ms is not None and s.frame_time_ms > FRAME_SPIKE_MS:
            events.append(SessionEvent(
                timestamp=s.timestamp,
                event_type=EventType.FRAME_TIME_SPIKE.value,
                severity=EventSeverity.WARNING.value,
                measured_value=s.frame_time_ms,
                threshold=FRAME_SPIKE_MS,
                explanation=f"Frame time spike: {s.frame_time_ms:.1f}ms",
            ))

        # CPU spike
        if s.cpu_total_percent is not None and s.cpu_total_percent >= CPU_HIGH:
            events.append(SessionEvent(
                timestamp=s.timestamp,
                event_type=EventType.CPU_SPIKE.value,
                severity=EventSeverity.WARNING.value,
                measured_value=s.cpu_total_percent,
                threshold=CPU_HIGH,
                explanation=f"CPU at {s.cpu_total_percent:.1f}%",
            ))

        # GPU saturation
        if s.gpu_utilization_percent is not None and s.gpu_utilization_percent >= GPU_SATURATED:
            events.append(SessionEvent(
                timestamp=s.timestamp,
                event_type=EventType.GPU_SATURATION.value,
                severity=EventSeverity.WARNING.value,
                measured_value=s.gpu_utilization_percent,
                threshold=GPU_SATURATED,
                explanation=f"GPU utilization at {s.gpu_utilization_percent:.1f}%",
            ))

        # GPU thermal
        if s.gpu_temperature_c is not None and s.gpu_temperature_c >= THERMAL_WARNING:
            sev = EventSeverity.CRITICAL.value if s.gpu_temperature_c >= 90 else EventSeverity.WARNING.value
            events.append(SessionEvent(
                timestamp=s.timestamp,
                event_type=EventType.GPU_THERMAL_WARNING.value,
                severity=sev,
                measured_value=s.gpu_temperature_c,
                threshold=THERMAL_WARNING,
                explanation=f"GPU temperature at {s.gpu_temperature_c:.0f}C",
            ))

        # Memory pressure (RAM percentage)
        if s.system_ram_used_mb is not None and s.system_ram_total_mb is not None and s.system_ram_total_mb > 0:
            ram_pct = (s.system_ram_used_mb / s.system_ram_total_mb) * 100
            if ram_pct >= RAM_PRESSURE:
                events.append(SessionEvent(
                    timestamp=s.timestamp,
                    event_type=EventType.MEMORY_PRESSURE.value,
                    severity=EventSeverity.WARNING.value,
                    measured_value=ram_pct,
                    threshold=RAM_PRESSURE,
                    explanation=f"RAM at {ram_pct:.1f}%",
                ))

    return events


# ── Root-Cause Analysis ──────────────────────────────────────────

def analyze_root_cause(
    samples: List[TelemetrySample],
    events: List[SessionEvent],
) -> Tuple[RootCause, int, List[str]]:
    """
    Classify root cause from telemetry samples and events.
    Returns (root_cause, confidence_percent, evidence).
    """
    if not samples or len(samples) < MIN_SAMPLES:
        return RootCause.INSUFFICIENT_DATA, 0, ["Insufficient samples"]

    evidence = []
    scores = {rc: 0 for rc in RootCause if rc != RootCause.INSUFFICIENT_DATA}

    # CPU analysis
    cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
    if cpu_vals:
        avg_cpu = statistics.mean(cpu_vals)
        if avg_cpu >= CPU_HIGH:
            scores[RootCause.CPU] += 40
            evidence.append(f"CPU averaged {avg_cpu:.1f}%")
        elif avg_cpu >= 70:
            scores[RootCause.CPU] += 15
            evidence.append(f"CPU elevated at {avg_cpu:.1f}%")

    # GPU analysis
    gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
    if gpu_vals:
        avg_gpu = statistics.mean(gpu_vals)
        if avg_gpu >= GPU_SATURATED:
            scores[RootCause.GPU] += 40
            evidence.append(f"GPU averaged {avg_gpu:.1f}%")
        elif avg_gpu >= 75:
            scores[RootCause.GPU] += 15

        # CPU high + GPU low → CPU bottleneck
        if cpu_vals and statistics.mean(cpu_vals) > 80 and avg_gpu < 50:
            scores[RootCause.CPU] += 20
            evidence.append(f"CPU high ({statistics.mean(cpu_vals):.1f}%) while GPU low ({avg_gpu:.1f}%)")

    # Memory analysis
    ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
    ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
    if ram_used and ram_total and ram_total[0] > 0:
        avg_used = statistics.mean(ram_used)
        used_pct = (avg_used / ram_total[0]) * 100
        if used_pct >= RAM_PRESSURE:
            scores[RootCause.MEMORY] += 40
            evidence.append(f"RAM at {used_pct:.1f}% ({avg_used:.0f}/{ram_total[0]:.0f} MB)")

    # Thermal analysis
    gpu_temps = [s.gpu_temperature_c for s in samples if s.gpu_temperature_c is not None]
    if gpu_temps:
        max_temp = max(gpu_temps)
        if max_temp >= THERMAL_WARNING:
            scores[RootCause.THERMAL] += 40
            evidence.append(f"GPU temperature {max_temp:.0f}C")

    # Frame time analysis
    ft_vals = [s.frame_time_ms for s in samples if s.frame_time_ms is not None and s.frame_time_ms > 0]
    if ft_vals and len(ft_vals) >= 3:
        avg_ft = statistics.mean(ft_vals)
        if avg_ft > 0:
            cv = statistics.stdev(ft_vals) / avg_ft if len(ft_vals) > 1 else 0
            if cv > FRAME_CV_UNSTABLE:
                scores[RootCause.FRAME_TIME] += 40
                evidence.append(f"Frame time unstable (CV={cv:.2f})")
            elif cv > FRAME_CV_MILD:
                scores[RootCause.FRAME_TIME] += 15

    # Event-based evidence
    cpu_events = sum(1 for e in events if e.event_type == EventType.CPU_SPIKE.value)
    gpu_events = sum(1 for e in events if e.event_type == EventType.GPU_SATURATION.value)
    thermal_events = sum(1 for e in events if e.event_type == EventType.GPU_THERMAL_WARNING.value)
    fps_events = sum(1 for e in events if e.event_type == EventType.FPS_DROP.value)
    ft_events = sum(1 for e in events if e.event_type == EventType.FRAME_TIME_SPIKE.value)

    if cpu_events >= 3:
        scores[RootCause.CPU] += 10
    if gpu_events >= 3:
        scores[RootCause.GPU] += 10
    if thermal_events >= 3:
        scores[RootCause.THERMAL] += 10
    if ft_events >= 5:
        scores[RootCause.FRAME_TIME] += 10

    # Check for no bottleneck
    has_any = cpu_vals or gpu_vals or ram_used or gpu_temps
    if not has_any:
        return RootCause.INSUFFICIENT_DATA, 0, ["No telemetry data"]

    candidates = [(rc, sc) for rc, sc in scores.items() if sc > 0]
    if not candidates:
        return RootCause.NO_CLEAR, 40, ["No persistent bottleneck detected"]

    candidates.sort(key=lambda x: x[1], reverse=True)
    best, best_score = candidates[0]

    n = len(samples)
    confidence = min(best_score + (10 if n >= 20 else 5), 100)

    return best, confidence, evidence


# ── Worst Period Detection ───────────────────────────────────────

def detect_worst_period(
    samples: List[TelemetrySample],
    window: int = WORST_WINDOW,
) -> WorstPeriod:
    """Detect the worst performance window in the sample list."""
    worst = WorstPeriod()
    if len(samples) < window:
        return worst

    worst_score = float("inf")
    for i in range(len(samples) - window + 1):
        window_samples = samples[i : i + window]

        # Score: lower is worse
        fps_vals = [s.fps for s in window_samples if s.fps is not None and s.fps > 0]
        cpu_vals = [s.cpu_total_percent for s in window_samples if s.cpu_total_percent is not None]
        gpu_vals = [s.gpu_utilization_percent for s in window_samples if s.gpu_utilization_percent is not None]
        ft_vals = [s.frame_time_ms for s in window_samples if s.frame_time_ms is not None and s.frame_time_ms > 0]

        avg_fps = statistics.mean(fps_vals) if fps_vals else 50
        avg_cpu = statistics.mean(cpu_vals) if cpu_vals else 50
        frame_events = sum(1 for s in window_samples
                          if s.frame_time_ms is not None and s.frame_time_ms > FRAME_SPIKE_MS)

        # Lower score = worse
        score = avg_fps - avg_cpu * 0.5 - frame_events * 5

        if score < worst_score:
            worst_score = score
            worst.start_index = i
            worst.end_index = i + window - 1
            worst.avg_fps = statistics.mean(fps_vals) if fps_vals else None
            worst.avg_cpu = statistics.mean(cpu_vals) if cpu_vals else None
            worst.avg_gpu = statistics.mean(gpu_vals) if gpu_vals else None
            worst.event_count = frame_events

            if window_samples:
                worst.duration_seconds = window_samples[-1].timestamp - window_samples[0].timestamp

    return worst


# ── Session Scoring ──────────────────────────────────────────────

def calculate_session_score(
    timelines: Dict[str, SessionTimeline],
    root_cause: RootCause,
    root_cause_confidence: int,
    sample_count: int,
) -> SessionScore:
    """Calculate a session quality score (0-100)."""
    score = SessionScore()
    components = []

    def _add(name, value, weight):
        components.append({"name": name, "value": value, "weight": weight})

    # Performance stability (FPS consistency)
    ft = timelines.get("frame_time", SessionTimeline())
    if ft.source == MetricSource.MEASURED and ft.std_dev is not None and ft.avg is not None and ft.avg > 0:
        cv = ft.std_dev / ft.avg
        if cv < 0.10:
            val = 95
        elif cv < 0.20:
            val = 80
        elif cv < 0.35:
            val = 60
        else:
            val = 30
        _add("Performance Stability", val, 0.25)
    else:
        _add("Performance Stability", 60, 0.25)

    # Frame pacing (FPS median consistency)
    fps = timelines.get("fps", SessionTimeline())
    if fps.source == MetricSource.MEASURED and fps.std_dev is not None and fps.avg is not None and fps.avg > 0:
        cv = fps.std_dev / fps.avg
        if cv < 0.05:
            val = 95
        elif cv < 0.10:
            val = 80
        elif cv < 0.20:
            val = 60
        else:
            val = 35
        _add("Frame Pacing", val, 0.25)
    else:
        _add("Frame Pacing", 60, 0.25)

    # Resource headroom (CPU + GPU + RAM)
    cpu = timelines.get("cpu", SessionTimeline())
    gpu = timelines.get("gpu", SessionTimeline())
    ram_pct = timelines.get("ram_percent", SessionTimeline())
    headroom_vals = []
    if cpu.source == MetricSource.MEASURED and cpu.avg is not None:
        if cpu.avg < 50:
            headroom_vals.append(95)
        elif cpu.avg < 70:
            headroom_vals.append(80)
        elif cpu.avg < 85:
            headroom_vals.append(60)
        else:
            headroom_vals.append(30)
    if gpu.source == MetricSource.MEASURED and gpu.avg is not None:
        if gpu.avg < 60:
            headroom_vals.append(90)
        elif gpu.avg < 80:
            headroom_vals.append(75)
        elif gpu.avg < 90:
            headroom_vals.append(55)
        else:
            headroom_vals.append(30)
    if ram_pct and ram_pct.source == MetricSource.MEASURED and ram_pct.avg is not None:
        if ram_pct.avg < 60:
            headroom_vals.append(95)
        elif ram_pct.avg < 75:
            headroom_vals.append(80)
        elif ram_pct.avg < 85:
            headroom_vals.append(60)
        else:
            headroom_vals.append(30)

    if headroom_vals:
        _add("Resource Headroom", int(statistics.mean(headroom_vals)), 0.20)
    else:
        _add("Resource Headroom", 60, 0.20)

    # Thermal
    gpu_temp = timelines.get("gpu_temp", SessionTimeline())
    if gpu_temp.source == MetricSource.MEASURED and gpu_temp.peak is not None:
        if gpu_temp.peak < 70:
            val = 95
        elif gpu_temp.peak < 80:
            val = 80
        elif gpu_temp.peak < 85:
            val = 60
        else:
            val = 30
        _add("Thermal", val, 0.15)
    else:
        _add("Thermal", 70, 0.15)

    # Confidence
    if sample_count >= 30:
        conf = 90
    elif sample_count >= 15:
        conf = 70
    elif sample_count >= MIN_SAMPLES:
        conf = 50
    else:
        conf = 30
    _add("Data Confidence", conf, 0.15)

    # Calculate weighted score
    total_weight = sum(c["weight"] for c in components)
    if total_weight > 0:
        score.overall = int(sum(c["value"] * c["weight"] for c in components) / total_weight)

    # Level
    if score.overall >= 85:
        score.level = SessionScoreLevel.EXCELLENT
    elif score.overall >= 70:
        score.level = SessionScoreLevel.GOOD
    elif score.overall >= 50:
        score.level = SessionScoreLevel.FAIR
    else:
        score.level = SessionScoreLevel.POOR

    score.components = components
    score.performance_stability = components[0]["value"] if components else 0
    score.frame_pacing = components[1]["value"] if len(components) > 1 else 0
    score.resource_headroom = components[2]["value"] if len(components) > 2 else 0
    score.thermal = components[3]["value"] if len(components) > 3 else 0
    score.confidence = conf

    return score


# ── Recommendations ──────────────────────────────────────────────

def generate_session_recommendations(
    root_cause: RootCause,
    root_cause_confidence: int,
    timelines: Dict[str, SessionTimeline],
    events: List[SessionEvent],
) -> List[Dict]:
    """Generate evidence-based recommendations from session analysis."""
    recs = []

    if root_cause == RootCause.INSUFFICIENT_DATA:
        recs.append({
            "category": "DATA",
            "priority": "MEDIUM",
            "reason": "Insufficient telemetry for analysis",
            "action": "Collect more samples",
        })
        return recs

    if root_cause == RootCause.NO_CLEAR:
        recs.append({
            "category": "STATUS",
            "priority": "LOW",
            "reason": "No persistent bottleneck detected",
            "action": "Monitor",
        })
        return recs

    if root_cause == RootCause.CPU:
        recs.append({
            "category": "CPU",
            "priority": "HIGH",
            "reason": "CPU bottleneck detected. Consider closing background apps or adjusting emulator CPU allocation.",
            "action": "Reduce CPU load",
        })

    if root_cause == RootCause.GPU:
        recs.append({
            "category": "GPU",
            "priority": "MEDIUM",
            "reason": "GPU saturation detected. Consider reducing emulator graphics quality.",
            "action": "Reduce graphics load",
        })

    if root_cause == RootCause.MEMORY:
        recs.append({
            "category": "MEMORY",
            "priority": "HIGH",
            "reason": "Memory pressure detected. Close unnecessary applications.",
            "action": "Reduce memory pressure",
        })

    if root_cause == RootCause.THERMAL:
        recs.append({
            "category": "THERMAL",
            "priority": "HIGH",
            "reason": "Thermal throttling likely. Reduce system load or improve cooling.",
            "action": "Reduce thermal load",
        })

    if root_cause == RootCause.FRAME_TIME:
        recs.append({
            "category": "FRAME_PACING",
            "priority": "MEDIUM",
            "reason": "Frame pacing instability. Investigate background interference.",
            "action": "Investigate frame delivery",
        })

    # Additional event-based recs
    thermal_events = [e for e in events if e.event_type == EventType.GPU_THERMAL_WARNING.value]
    if thermal_events and root_cause != RootCause.THERMAL:
        recs.append({
            "category": "THERMAL",
            "priority": "LOW",
            "reason": f"Thermal events detected ({len(thermal_events)}). Monitor GPU temperature.",
            "action": "Monitor temperature",
        })

    return recs


# ── Gaming Session Analyzer ──────────────────────────────────────

class GamingSessionAnalyzer:
    """
    Gaming session lifecycle analyzer.

    Provides start/stop, baseline capture, timeline aggregation,
    event detection, root-cause analysis, scoring, and reporting.

    Strictly read-only analysis — never modifies system state.
    """

    def __init__(self):
        self._state: SessionState = SessionState.IDLE
        self._session_id: str = ""
        self._started_at: float = 0.0
        self._samples: List[TelemetrySample] = []
        self._events: List[SessionEvent] = []
        self._baseline: Dict[str, Optional[float]] = {}
        self._target_name: str = ""
        self._target_pid: int = 0
        self._lock = threading.Lock()

        # Accumulated events (from realtime telemetry if available)
        self._external_events: List[PerformanceEvent] = []

        # Session history
        self._last_report: Optional[GamingSessionReport] = None

    @property
    def state(self) -> SessionState:
        return self._state

    @property
    def session_id(self) -> str:
        return self._session_id

    @property
    def last_report(self) -> Optional[GamingSessionReport]:
        return self._last_report

    @property
    def is_running(self) -> bool:
        return self._state == SessionState.RUNNING

    # ── Lifecycle ─────────────────────────────────────────────

    def start_session(
        self,
        target_name: str = "",
        target_pid: int = 0,
    ) -> str:
        """Start a new gaming session. Returns session ID."""
        if self._state == SessionState.RUNNING:
            logger.warning("Session already running — stopping first")
            self.stop_session()

        self._session_id = str(uuid.uuid4())[:8]
        self._started_at = time.time()
        self._target_name = target_name
        self._target_pid = target_pid
        self._samples = []
        self._events = []
        self._external_events = []

        # Capture baseline
        self._capture_baseline()

        self._state = SessionState.RUNNING
        logger.info(f"Gaming session started: {self._session_id}")
        return self._session_id

    def stop_session(self) -> Optional[GamingSessionReport]:
        """Stop the session and generate a report."""
        if self._state != SessionState.RUNNING:
            return self._last_report

        self._state = SessionState.STOPPED
        report = self._generate_report()
        self._last_report = report
        self._save_report(report)
        logger.info(f"Gaming session stopped: {self._session_id}, score={report.score.overall}")
        return report

    def get_session_status(self) -> Dict:
        """Get current session status."""
        status = {
            "state": self._state.value,
            "session_id": self._session_id,
            "duration_seconds": time.time() - self._started_at if self._started_at else 0,
            "target_name": self._target_name,
            "target_pid": self._target_pid,
            "sample_count": len(self._samples),
            "event_count": len(self._events) + len(self._external_events),
            "baseline": dict(self._baseline) if self._baseline else None,
        }

        if self._last_report:
            status["last_report_score"] = self._last_report.score.overall
            status["last_report_root_cause"] = self._last_report.root_cause.value

        return status

    # ── Sample Ingestion ──────────────────────────────────────

    def ingest_sample(self, sample: TelemetrySample):
        """Add a telemetry sample to the current session."""
        if self._state != SessionState.RUNNING:
            return

        with self._lock:
            self._samples.append(sample)

        # Detect events from this sample
        new_events = detect_session_events([sample])
        with self._lock:
            self._events.extend(new_events)

    def ingest_samples(self, samples: List[TelemetrySample]):
        """Add multiple telemetry samples to the current session."""
        for s in samples:
            self.ingest_sample(s)

    def add_external_event(self, event: PerformanceEvent):
        """Add an event from the realtime telemetry system."""
        with self._lock:
            self._external_events.append(event)

    # ── Baseline ──────────────────────────────────────────────

    def _capture_baseline(self):
        """Capture baseline system state."""
        try:
            import psutil
            vm = psutil.virtual_memory()
            self._baseline["ram_percent"] = vm.percent

            cpu_pct = psutil.cpu_percent(interval=0.5)
            self._baseline["cpu_percent"] = cpu_pct
        except Exception as e:
            logger.debug(f"Baseline capture: {e}")

        try:
            from app.system.gpu import gpu_monitor
            gpus = gpu_monitor.detect()
            if gpus and gpus[0].vendor == "NVIDIA":
                g = gpu_monitor.update_nvidia(gpus[0])
                self._baseline["gpu_percent"] = g.utilization_gpu
                self._baseline["gpu_temp"] = g.temperature_celsius
        except Exception:
            pass

    # ── Report Generation ─────────────────────────────────────

    def _generate_report(self) -> GamingSessionReport:
        """Generate a complete session report."""
        report = GamingSessionReport(
            session_id=self._session_id,
            started_at=datetime.fromtimestamp(self._started_at).isoformat() if self._started_at else "",
            completed_at=datetime.now().isoformat(),
            duration_seconds=time.time() - self._started_at if self._started_at else 0,
            target_name=self._target_name,
            target_pid=self._target_pid,
        )

        # Baseline
        report.baseline_cpu = self._baseline.get("cpu_percent")
        report.baseline_gpu = self._baseline.get("gpu_percent")
        report.baseline_ram_percent = self._baseline.get("ram_percent")
        report.baseline_gpu_temp = self._baseline.get("gpu_temp")

        # Aggregate timelines
        with self._lock:
            samples = list(self._samples)

        report.sample_count = len(samples)

        if samples:
            timelines = aggregate_timelines(samples)
            report.cpu_timeline = timelines.get("cpu", SessionTimeline())
            report.gpu_timeline = timelines.get("gpu", SessionTimeline())
            report.ram_timeline = timelines.get("ram", SessionTimeline())
            report.gpu_temp_timeline = timelines.get("gpu_temp", SessionTimeline())
            report.fps_timeline = timelines.get("fps", SessionTimeline())
            report.frame_time_timeline = timelines.get("frame_time", SessionTimeline())

        # Events
        with self._lock:
            all_events = list(self._events)
        report.events = all_events
        event_summary = {}
        for e in all_events:
            event_summary[e.event_type] = event_summary.get(e.event_type, 0) + 1
        report.event_summary = event_summary

        # Root cause
        report.root_cause, report.root_cause_confidence, report.root_cause_evidence = \
            analyze_root_cause(samples, all_events)

        # Worst period
        report.worst_period = detect_worst_period(samples)

        # Score
        timelines_dict = aggregate_timelines(samples) if samples else {}
        report.score = calculate_session_score(
            timelines_dict, report.root_cause, report.root_cause_confidence, len(samples),
        )

        # Recommendations
        report.recommendations = generate_session_recommendations(
            report.root_cause, report.root_cause_confidence, timelines_dict, all_events,
        )

        return report

    # ── Persistence ───────────────────────────────────────────

    def _save_report(self, report: GamingSessionReport):
        """Save session report to disk."""
        try:
            sessions_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "gaming_sessions",
            )
            os.makedirs(sessions_dir, exist_ok=True)
            filepath = os.path.join(sessions_dir, f"{report.session_id}.json")
            with open(filepath, "w") as f:
                json.dump(report.to_dict(), f, indent=2)
            logger.info(f"Session report saved: {filepath}")
        except Exception as e:
            logger.debug(f"Failed to save session report: {e}")

    def load_history(self, count: int = 10) -> List[Dict]:
        """Load recent session reports from disk."""
        try:
            sessions_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "gaming_sessions",
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

    def format_report(self, report: GamingSessionReport) -> str:
        """Format a session report for CLI output."""
        lines = []
        w = 60
        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — GAMING SESSION REPORT")
        lines.append("=" * w)
        lines.append("")

        lines.append(f"Session:   {report.session_id}")
        lines.append(f"Duration:  {report.duration_seconds:.1f}s")
        lines.append(f"Target:    {report.target_name or 'None'} PID {report.target_pid}")
        lines.append(f"Samples:   {report.sample_count}")
        lines.append("")

        # Baseline
        lines.append("BASELINE")
        lines.append("-" * w)
        if report.baseline_cpu is not None:
            lines.append(f"  CPU:       {report.baseline_cpu:.1f}%")
        if report.baseline_gpu is not None:
            lines.append(f"  GPU:       {report.baseline_gpu:.1f}%")
        if report.baseline_ram_percent is not None:
            lines.append(f"  RAM:       {report.baseline_ram_percent:.1f}%")
        if report.baseline_gpu_temp is not None:
            lines.append(f"  GPU Temp:  {report.baseline_gpu_temp:.0f}C")
        lines.append("")

        # Timeline
        lines.append("TIMELINE")
        lines.append("-" * w)
        fmt = "  {:<18s} {:>10s} {:>10s} {:>10s}"
        lines.append(fmt.format("METRIC", "AVG", "PEAK", "MIN"))
        lines.append(fmt.format("-" * 18, "-" * 10, "-" * 10, "-" * 10))

        for name, tl in [
            ("CPU", report.cpu_timeline),
            ("GPU", report.gpu_timeline),
            ("RAM Used", report.ram_timeline),
            ("GPU Temp", report.gpu_temp_timeline),
            ("FPS", report.fps_timeline),
            ("Frame Time", report.frame_time_timeline),
        ]:
            if tl.source == MetricSource.MEASURED:
                avg_str = f"{tl.avg:.1f}" if tl.avg is not None else "N/A"
                peak_str = f"{tl.peak:.1f}" if tl.peak is not None else "N/A"
                min_str = f"{tl.minimum:.1f}" if tl.minimum is not None else "N/A"
                unit = "ms" if name == "Frame Time" else ("C" if name == "GPU Temp" else "%")
                lines.append(fmt.format(name, f"{avg_str}{unit}", f"{peak_str}{unit}", f"{min_str}{unit}"))
        lines.append("")

        # Events
        lines.append("EVENTS")
        lines.append("-" * w)
        if report.event_summary:
            for etype, count in sorted(report.event_summary.items(), key=lambda x: -x[1]):
                lines.append(f"  {etype:<25s} x{count}")
        else:
            lines.append("  No events detected")
        lines.append("")

        # Root cause
        lines.append("ROOT CAUSE")
        lines.append("-" * w)
        lines.append(f"  Type:       {report.root_cause.value}")
        lines.append(f"  Confidence: {report.root_cause_confidence}%")
        if report.root_cause_evidence:
            for ev in report.root_cause_evidence[:3]:
                lines.append(f"  Evidence:   {ev}")
        lines.append("")

        # Worst period
        wp = report.worst_period
        if wp.avg_fps is not None:
            lines.append("WORST PERIOD")
            lines.append("-" * w)
            lines.append(f"  Samples:    {wp.start_index}-{wp.end_index}")
            lines.append(f"  Duration:   {wp.duration_seconds:.1f}s")
            lines.append(f"  Avg FPS:    {wp.avg_fps:.1f}")
            if wp.avg_cpu is not None:
                lines.append(f"  Avg CPU:    {wp.avg_cpu:.1f}%")
            if wp.avg_gpu is not None:
                lines.append(f"  Avg GPU:    {wp.avg_gpu:.1f}%")
            lines.append(f"  Events:     {wp.event_count}")
            lines.append("")

        # Score
        sc = report.score
        lines.append("SESSION SCORE")
        lines.append("-" * w)
        lines.append(f"  Overall:    {sc.overall}/100 ({sc.level.value})")
        for c in sc.components:
            lines.append(f"  {c['name']:<20s} {c['value']:3d}/100")
        lines.append("")

        # Recommendations
        if report.recommendations:
            lines.append("RECOMMENDATIONS")
            lines.append("-" * w)
            for i, r in enumerate(report.recommendations, 1):
                lines.append(f"  {i}. [{r['category']}] {r['priority']}")
                lines.append(f"     {r['reason']}")
                lines.append(f"     Action: {r['action']}")
            lines.append("")

        lines.append("=" * w)
        return "\n".join(lines)

    def format_status(self, status: Dict) -> str:
        """Format session status for CLI."""
        lines = []
        lines.append("=" * 55)
        lines.append("HEAVEN SOCIETY — GAMING SESSION STATUS")
        lines.append("=" * 55)
        lines.append("")
        lines.append(f"  State:     {status['state']}")
        lines.append(f"  Session:   {status['session_id']}")
        lines.append(f"  Duration:  {status['duration_seconds']:.1f}s")
        lines.append(f"  Target:    {status['target_name'] or 'None'} PID {status['target_pid']}")
        lines.append(f"  Samples:   {status['sample_count']}")
        lines.append(f"  Events:    {status['event_count']}")
        if status.get("last_report_score") is not None:
            lines.append(f"  Last Score: {status['last_report_score']}")
            lines.append(f"  Last Root:  {status.get('last_report_root_cause', 'N/A')}")
        lines.append("")
        lines.append("=" * 55)
        return "\n".join(lines)


# Singleton
gaming_session_analyzer = GamingSessionAnalyzer()
