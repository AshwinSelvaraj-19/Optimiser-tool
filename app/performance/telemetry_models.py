"""
Structured models for real-time performance telemetry.

Every metric supports NOT_AVAILABLE (None) for unavailable hardware data.
Never substitute zero for unavailable data.
"""

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class DataAvailability(Enum):
    """Distinguishes how a value was obtained."""
    MEASURED = "MEASURED"
    DETECTED = "DETECTED"
    INFERRED = "INFERRED"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class EventType(Enum):
    """Types of performance events."""
    FPS_DROP = "FPS_DROP"
    FRAME_TIME_SPIKE = "FRAME_TIME_SPIKE"
    CPU_SPIKE = "CPU_SPIKE"
    GPU_SATURATION = "GPU_SATURATION"
    MEMORY_PRESSURE = "MEMORY_PRESSURE"
    GPU_THERMAL_WARNING = "GPU_THERMAL_WARNING"
    EMULATOR_PROCESS_CHANGE = "EMULATOR_PROCESS_CHANGE"
    EMULATOR_EXITED = "EMULATOR_EXITED"


class EventSeverity(Enum):
    """Event severity levels."""
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class BottleneckType(Enum):
    """Types of performance bottlenecks."""
    CPU_BOUND = "CPU_BOUND"
    GPU_BOUND = "GPU_BOUND"
    MEMORY_BOUND = "MEMORY_BOUND"
    THERMAL_LIMITED = "THERMAL_LIMITED"
    FRAME_TIME_INSTABILITY = "FRAME_TIME_INSTABILITY"
    NO_CLEAR_BOTTLENECK = "NO_CLEAR_BOTTLENECK"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


@dataclass
class TelemetrySample:
    """Single telemetry reading at a point in time."""
    timestamp: float = 0.0
    emulator_pid: int = 0
    emulator_name: str = ""

    # Frame timing
    fps: Optional[float] = None
    one_percent_low: Optional[float] = None
    frame_time_ms: Optional[float] = None

    # CPU
    cpu_total_percent: Optional[float] = None
    cpu_per_core_percent: List[float] = field(default_factory=list)
    emulator_cpu_percent: Optional[float] = None

    # GPU
    gpu_utilization_percent: Optional[float] = None
    gpu_temperature_c: Optional[float] = None
    gpu_vram_used_mb: Optional[float] = None
    gpu_vram_total_mb: Optional[float] = None
    gpu_clock_mhz: Optional[float] = None
    gpu_power_watts: Optional[float] = None

    # Memory
    system_ram_used_mb: Optional[float] = None
    system_ram_available_mb: Optional[float] = None
    system_ram_total_mb: Optional[float] = None
    emulator_ram_mb: Optional[float] = None

    # Display
    display_refresh_hz: Optional[int] = None

    # CPU temp if available
    cpu_temperature_c: Optional[float] = None

    def has_fps(self) -> bool:
        return self.fps is not None and self.fps > 0

    def has_gpu(self) -> bool:
        return self.gpu_utilization_percent is not None

    def has_emulator(self) -> bool:
        return self.emulator_pid > 0

    def has_ram(self) -> bool:
        return self.system_ram_total_mb is not None and self.system_ram_total_mb > 0


@dataclass
class PerformanceEvent:
    """A detected performance event."""
    timestamp: float = 0.0
    event_type: EventType = EventType.FPS_DROP
    severity: EventSeverity = EventSeverity.INFO
    measured_value: float = 0.0
    threshold: float = 0.0
    explanation: str = ""

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "event_type": self.event_type.value,
            "severity": self.severity.value,
            "measured_value": self.measured_value,
            "threshold": self.threshold,
            "explanation": self.explanation,
        }


@dataclass
class TelemetrySession:
    """A complete telemetry session with metadata."""
    session_id: str = field(default_factory=lambda: str(uuid.uuid4())[:8])
    started_at: float = 0.0
    completed_at: float = 0.0
    duration_seconds: float = 0.0
    sample_count: int = 0

    # Target
    target_name: str = ""
    target_pid: int = 0

    # Hardware
    cpu_model: str = ""
    gpu_model: str = ""
    total_ram_mb: float = 0.0
    display_refresh_hz: Optional[int] = None

    # Aggregated metrics (calculated from samples)
    avg_fps: Optional[float] = None
    median_fps: Optional[float] = None
    min_fps: Optional[float] = None
    max_fps: Optional[float] = None
    one_percent_low: Optional[float] = None
    point_one_percent_low: Optional[float] = None

    avg_frame_time_ms: Optional[float] = None
    frame_time_variance: Optional[float] = None
    frame_spikes: int = 0

    avg_cpu_percent: Optional[float] = None
    peak_cpu_percent: Optional[float] = None

    avg_gpu_percent: Optional[float] = None
    peak_gpu_percent: Optional[float] = None
    max_gpu_temp: Optional[float] = None

    avg_ram_used_mb: Optional[float] = None
    peak_ram_used_mb: Optional[float] = None
    min_ram_available_mb: Optional[float] = None

    avg_emulator_cpu: Optional[float] = None
    avg_emulator_ram_mb: Optional[float] = None

    # Events
    events: List[PerformanceEvent] = field(default_factory=list)
    event_summary: dict = field(default_factory=dict)

    # Bottleneck
    bottleneck: Optional["BottleneckAssessment"] = None

    def get_duration(self) -> float:
        if self.completed_at > 0:
            return self.completed_at - self.started_at
        return self.duration_seconds

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "sample_count": self.sample_count,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "avg_fps": self.avg_fps,
            "median_fps": self.median_fps,
            "one_percent_low": self.one_percent_low,
            "avg_frame_time_ms": self.avg_frame_time_ms,
            "frame_spikes": self.frame_spikes,
            "avg_cpu_percent": self.avg_cpu_percent,
            "avg_gpu_percent": self.avg_gpu_percent,
            "max_gpu_temp": self.max_gpu_temp,
            "avg_ram_used_mb": self.avg_ram_used_mb,
            "event_count": len(self.events),
            "bottleneck": self.bottleneck.to_dict() if self.bottleneck else None,
        }


@dataclass
class BottleneckAssessment:
    """Result of bottleneck correlation analysis."""
    bottleneck: BottleneckType = BottleneckType.INSUFFICIENT_DATA
    confidence: int = 0  # 0-100
    evidence: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)
    data_availability: DataAvailability = DataAvailability.NOT_AVAILABLE

    def to_dict(self) -> dict:
        return {
            "bottleneck": self.bottleneck.value,
            "confidence": self.confidence,
            "evidence": self.evidence,
            "recommendations": self.recommendations,
            "data_availability": self.data_availability.value,
        }


@dataclass
class PerformanceSummary:
    """Aggregated performance summary from multiple samples."""
    sample_count: int = 0
    valid_sample_count: int = 0
    duration_seconds: float = 0.0

    # FPS
    avg_fps: Optional[float] = None
    median_fps: Optional[float] = None
    min_fps: Optional[float] = None
    max_fps: Optional[float] = None
    one_percent_low: Optional[float] = None
    point_one_percent_low: Optional[float] = None

    # Frame time
    avg_frame_time_ms: Optional[float] = None
    median_frame_time_ms: Optional[float] = None
    frame_time_variance: Optional[float] = None
    frame_time_std_dev: Optional[float] = None
    frame_spikes: int = 0
    long_frame_count: int = 0

    # CPU
    avg_cpu_percent: Optional[float] = None
    peak_cpu_percent: Optional[float] = None
    cpu_per_core_avg: List[float] = field(default_factory=list)

    # GPU
    avg_gpu_percent: Optional[float] = None
    peak_gpu_percent: Optional[float] = None
    max_gpu_temp: Optional[float] = None
    avg_gpu_temp: Optional[float] = None
    gpu_vram_used_avg: Optional[float] = None
    gpu_vram_total: Optional[float] = None

    # RAM
    avg_ram_used_mb: Optional[float] = None
    peak_ram_used_mb: Optional[float] = None
    min_ram_available_mb: Optional[float] = None
    avg_ram_available_mb: Optional[float] = None
    ram_total_mb: Optional[float] = None

    # Emulator
    avg_emulator_cpu: Optional[float] = None
    peak_emulator_cpu: Optional[float] = None
    avg_emulator_ram_mb: Optional[float] = None
    peak_emulator_ram_mb: Optional[float] = None

    # Stability
    stability_score: float = 0.0  # 0-100
    stability_rating: str = "UNKNOWN"

    def to_dict(self) -> dict:
        return {
            "sample_count": self.sample_count,
            "valid_sample_count": self.valid_sample_count,
            "duration_seconds": self.duration_seconds,
            "avg_fps": self.avg_fps,
            "median_fps": self.median_fps,
            "one_percent_low": self.one_percent_low,
            "point_one_percent_low": self.point_one_percent_low,
            "avg_frame_time_ms": self.avg_frame_time_ms,
            "frame_spikes": self.frame_spikes,
            "stability_score": self.stability_score,
            "stability_rating": self.stability_rating,
        }
