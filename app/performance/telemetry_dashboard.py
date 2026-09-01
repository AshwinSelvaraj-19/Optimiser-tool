"""
Phase 59 — Telemetry Dashboard.

Professional real-time telemetry dashboard with bounded history buffers
and lightweight sparkline rendering.

Features:
  - Bounded in-memory buffers (never grow indefinitely)
  - Configurable time ranges: 10s, 30s, 1m, 5m
  - Lightweight ASCII sparkline rendering (no heavy charts)
  - All data consumed from cached telemetry (no expensive collection)
  - History aggregation: min, max, avg, current
  - Disk and network where available

Rules:
  - GUI timer callbacks only consume already-available data
  - All collection occurs asynchronously
  - Never allow telemetry history to grow indefinitely
  - Never introduce heavy chart rendering that causes GUI lag
"""

import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("performance.telemetry_dashboard")


# ── Enums ────────────────────────────────────────────────────────


class TimeRange(Enum):
    """Configurable time ranges for history display."""
    TEN_SECONDS = 10
    THIRTY_SECONDS = 30
    ONE_MINUTE = 60
    FIVE_MINUTES = 300


# ── History Buffer ────────────────────────────────────────────────


@dataclass
class HistoryEntry:
    """A single point in the history buffer."""
    timestamp: float = 0.0
    value: Optional[float] = None


class BoundedBuffer:
    """
    Fixed-size circular buffer for telemetry history.
    Never grows beyond max_size entries.
    """

    def __init__(self, max_size: int = 300):
        self._max_size = max_size
        self._buffer: deque = deque(maxlen=max_size)

    def append(self, value: Optional[float]):
        """Append a value with current timestamp."""
        self._buffer.append(HistoryEntry(
            timestamp=time.time(),
            value=value,
        ))

    def get_range(self, seconds: float) -> List[HistoryEntry]:
        """Get entries within the last N seconds."""
        cutoff = time.time() - seconds
        return [e for e in self._buffer if e.timestamp >= cutoff]

    def get_values(self, seconds: float) -> List[float]:
        """Get numeric values within the last N seconds."""
        return [e.value for e in self.get_range(seconds) if e.value is not None]

    @property
    def latest(self) -> Optional[float]:
        """Get the most recent value."""
        if self._buffer:
            return self._buffer[-1].value
        return None

    @property
    def size(self) -> int:
        return len(self._buffer)

    def clear(self):
        self._buffer.clear()


# ── Statistics ────────────────────────────────────────────────────


@dataclass
class MetricStats:
    """Aggregated statistics for a metric over a time range."""
    name: str = ""
    current: Optional[float] = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    avg_value: Optional[float] = None
    samples: int = 0
    unit: str = ""

    @property
    def has_data(self) -> bool:
        return self.samples > 0 and self.current is not None

    @property
    def sparkline(self) -> str:
        """Generate a lightweight ASCII sparkline from recent values."""
        # This is populated externally with actual buffer data
        return getattr(self, '_sparkline', "")

    @sparkline.setter
    def sparkline(self, value: str):
        self._sparkline = value


# ── Sparkline Renderer ────────────────────────────────────────────

# Sparkline characters from low to high
SPARK_CHARS = " .:-=+*#%@"

def render_sparkline(values: List[float], width: int = 20) -> str:
    """
    Render a lightweight ASCII sparkline from a list of values.
    No heavy chart rendering — just characters.
    """
    if not values or len(values) < 2:
        return ""

    # Downsample to width
    if len(values) > width:
        step = len(values) / width
        sampled = [values[int(i * step)] for i in range(width)]
    else:
        sampled = values

    mn = min(sampled)
    mx = max(sampled)
    rng = mx - mn

    if rng < 0.001:
        # All same value — show middle character
        return SPARK_CHARS[len(SPARK_CHARS) // 2] * len(sampled)

    chars = []
    for v in sampled:
        normalized = (v - mn) / rng
        idx = int(normalized * (len(SPARK_CHARS) - 1))
        idx = max(0, min(len(SPARK_CHARS) - 1, idx))
        chars.append(SPARK_CHARS[idx])

    return "".join(chars)


# ── Telemetry Dashboard ──────────────────────────────────────────


class TelemetryDashboard:
    """
    Manages telemetry history buffers and provides dashboard data.
    All data comes from cached telemetry — no expensive collection.
    """

    # Max samples per metric (5 minutes at 1 sample/sec = 300)
    MAX_BUFFER_SIZE = 300

    def __init__(self, time_range: TimeRange = TimeRange.THIRTY_SECONDS):
        self._time_range = time_range
        self._buffers: Dict[str, BoundedBuffer] = {}
        self._init_buffers()

    @property
    def time_range(self) -> TimeRange:
        return self._time_range

    @time_range.setter
    def time_range(self, value: TimeRange):
        self._time_range = value

    def _init_buffers(self):
        """Initialize bounded buffers for all tracked metrics."""
        metric_names = [
            "cpu", "gpu", "ram", "vram",
            "gpu_temp", "gpu_clock",
            "fps", "one_low", "point_one_low",
            "frame_time", "frame_variance",
            "disk_free",
        ]
        for name in metric_names:
            self._buffers[name] = BoundedBuffer(max_size=self.MAX_BUFFER_SIZE)

    def record_snapshot(self, snapshot) -> None:
        """
        Record a telemetry snapshot into the history buffers.
        snapshot should be a TelemetrySample or similar cached frame.
        """
        try:
            self._buffers["cpu"].append(
                snapshot.cpu_utilization if snapshot.cpu_utilization > 0 else None
            )
            self._buffers["gpu"].append(
                snapshot.gpu_utilization if snapshot.gpu_utilization > 0 else None
            )
            self._buffers["ram"].append(
                snapshot.ram_percent if snapshot.ram_percent > 0 else None
            )

            # VRAM
            if snapshot.gpu_memory_total_mb and snapshot.gpu_memory_total_mb > 0:
                vram_pct = (snapshot.gpu_memory_used_mb / snapshot.gpu_memory_total_mb) * 100
                self._buffers["vram"].append(vram_pct)
            else:
                self._buffers["vram"].append(None)

            # GPU temp
            self._buffers["gpu_temp"].append(
                snapshot.gpu_temp if snapshot.gpu_temp and snapshot.gpu_temp > 0 else None
            )

            # GPU clock
            self._buffers["gpu_clock"].append(
                snapshot.gpu_clock_mhz if snapshot.gpu_clock_mhz and snapshot.gpu_clock_mhz > 0 else None
            )

            # FPS from snapshot if available
            self._buffers["fps"].append(
                snapshot.fps if hasattr(snapshot, 'fps') and snapshot.fps and snapshot.fps > 0 else None
            )

        except Exception as e:
            logger.debug(f"Dashboard record error: {e}")

    def record_fps(self, fps: Optional[float], one_low: Optional[float] = None,
                   point_one_low: Optional[float] = None,
                   frame_time: Optional[float] = None,
                   frame_variance: Optional[float] = None):
        """Record FPS data from PresentMon or FPS provider."""
        self._buffers["fps"].append(fps if fps and fps > 0 else None)
        self._buffers["one_low"].append(one_low if one_low and one_low > 0 else None)
        self._buffers["point_one_low"].append(
            point_one_low if point_one_low and point_one_low > 0 else None
        )
        self._buffers["frame_time"].append(
            frame_time if frame_time and frame_time > 0 else None
        )
        self._buffers["frame_variance"].append(
            frame_variance if frame_variance and frame_variance > 0 else None
        )

    def record_disk(self, free_gb: Optional[float]):
        """Record disk free space."""
        self._buffers["disk_free"].append(free_gb)

    # ── Query ────────────────────────────────────────────────

    def get_stats(self, metric: str) -> MetricStats:
        """Get aggregated statistics for a metric over the current time range."""
        buf = self._buffers.get(metric)
        if not buf:
            return MetricStats(name=metric)

        seconds = self._time_range.value
        values = buf.get_values(seconds)

        stats = MetricStats(name=metric, samples=len(values))
        if values:
            stats.current = buf.latest
            stats.min_value = min(values)
            stats.max_value = max(values)
            stats.avg_value = sum(values) / len(values)

        return stats

    def get_sparkline(self, metric: str, width: int = 20) -> str:
        """Get an ASCII sparkline for a metric."""
        buf = self._buffers.get(metric)
        if not buf:
            return ""

        seconds = self._time_range.value
        values = buf.get_values(seconds)
        return render_sparkline(values, width)

    def get_all_stats(self) -> Dict[str, MetricStats]:
        """Get statistics for all metrics."""
        result = {}
        for name in self._buffers:
            stats = self.get_stats(name)
            # Attach sparkline
            stats.sparkline = self.get_sparkline(name)
            result[name] = stats
        return result

    def get_snapshot(self) -> Dict[str, Optional[float]]:
        """Get the latest value for each metric."""
        return {
            name: buf.latest
            for name, buf in self._buffers.items()
        }

    # ── Format ───────────────────────────────────────────────

    def format_dashboard(self) -> str:
        """Format the dashboard for CLI display."""
        all_stats = self.get_all_stats()
        seconds = self._time_range.value

        lines = []
        lines.append("=" * 60)
        lines.append(f"  TELEMETRY DASHBOARD ({self._time_range.value}s window)")
        lines.append("=" * 60)

        def _fmt(val, unit=""):
            if val is None:
                return "N/A"
            return f"{val:.1f}{unit}"

        sections = [
            ("SYSTEM", [
                ("cpu", "CPU", "%"),
                ("gpu", "GPU", "%"),
                ("ram", "RAM", "%"),
                ("vram", "VRAM", "%"),
            ]),
            ("GPU", [
                ("gpu_temp", "Temperature", "°C"),
                ("gpu_clock", "Clock", "MHz"),
            ]),
            ("FRAME", [
                ("fps", "FPS", ""),
                ("one_low", "1% Low", ""),
                ("point_one_low", "0.1% Low", ""),
                ("frame_time", "Frame Time", "ms"),
                ("frame_variance", "Variance", "ms²"),
            ]),
            ("STORAGE", [
                ("disk_free", "Disk Free", "GB"),
            ]),
        ]

        for section_name, metrics in sections:
            lines.append(f"\n  {section_name}")
            lines.append("  " + "-" * 56)
            for key, label, unit in metrics:
                stats = all_stats.get(key, MetricStats())
                current = _fmt(stats.current, unit)
                avg = _fmt(stats.avg_value, unit)
                mn = _fmt(stats.min_value, unit)
                mx = _fmt(stats.max_value, unit)
                spark = stats.sparkline if hasattr(stats, 'sparkline') else ""
                samples = stats.samples

                lines.append(
                    f"    {label:<14} {current:>8}  avg {avg:>8}  "
                    f"min {mn:>8}  max {mx:>8}  [{samples} samples]"
                )
                if spark:
                    lines.append(f"    {'':14} {spark}")

        lines.append("\n" + "=" * 60)
        return "\n".join(lines)

    def clear(self):
        """Clear all history buffers."""
        for buf in self._buffers.values():
            buf.clear()


# ── Singleton ────────────────────────────────────────────────────

telemetry_dashboard = TelemetryDashboard()
