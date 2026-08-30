"""
Benchmark models — structured result and comparison data.

Every value comes from real measurements.
No fabricated values. No fake defaults.
If a metric cannot be measured, it is None.
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional


@dataclass
class BenchmarkResult:
    """
    Result of a single PresentMon benchmark capture.

    All fields originate from real measurements or are explicitly None/UNAVAILABLE.
    """

    # Target identification
    target_name: str = ""
    target_pid: int = 0

    # Capture metadata
    duration_seconds: float = 0.0
    sample_count: int = 0
    monitor_refresh_hz: int = 0
    capture_status: str = "UNAVAILABLE"  # COMPLETE, UNAVAILABLE, FAILED, NO_TARGET
    error: str = ""

    # Frame metrics — only populated when capture_status == COMPLETE
    present_fps: Optional[float] = None
    median_fps: Optional[float] = None
    min_fps: Optional[float] = None
    max_fps: Optional[float] = None
    one_percent_low: Optional[float] = None
    zero_point_one_percent_low: Optional[float] = None
    average_frame_time: Optional[float] = None  # ms
    frame_time_variance: Optional[float] = None  # ms^2
    frame_spikes: Optional[int] = None
    stability: Optional[float] = None  # 0-100

    # Timestamp
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    @property
    def is_valid(self) -> bool:
        """True if this result contains real measured data."""
        return (
            self.capture_status == "COMPLETE"
            and self.sample_count > 0
            and self.present_fps is not None
        )

    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        return {
            "target_name": self.target_name,
            "target_pid": self.target_pid,
            "duration_seconds": self.duration_seconds,
            "sample_count": self.sample_count,
            "monitor_refresh_hz": self.monitor_refresh_hz,
            "capture_status": self.capture_status,
            "error": self.error,
            "present_fps": self.present_fps,
            "median_fps": self.median_fps,
            "min_fps": self.min_fps,
            "max_fps": self.max_fps,
            "one_percent_low": self.one_percent_low,
            "zero_point_one_percent_low": self.zero_point_one_percent_low,
            "average_frame_time": self.average_frame_time,
            "frame_time_variance": self.frame_time_variance,
            "frame_spikes": self.frame_spikes,
            "stability": self.stability,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BenchmarkResult":
        """Deserialize from dict."""
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})

    @classmethod
    def unavailable(cls, reason: str = "", target: str = "", pid: int = 0) -> "BenchmarkResult":
        """Create an explicitly unavailable result."""
        return cls(
            target_name=target,
            target_pid=pid,
            capture_status="UNAVAILABLE",
            error=reason,
        )

    @classmethod
    def failed(cls, reason: str = "", target: str = "", pid: int = 0) -> "BenchmarkResult":
        """Create a failed result."""
        return cls(
            target_name=target,
            target_pid=pid,
            capture_status="FAILED",
            error=reason,
        )

    @classmethod
    def no_target(cls) -> "BenchmarkResult":
        """Create a no-target result."""
        return cls(capture_status="NO_TARGET", error="No emulator process detected")


@dataclass
class BenchmarkComparison:
    """
    Comparison between two BenchmarkResults.

    Delta conventions:
      - Higher FPS = positive delta = improvement
      - Higher 1% low = positive delta = improvement
      - Lower frame time = negative delta = improvement
      - Lower variance = negative delta = improvement
      - Fewer spikes = negative delta = improvement
      - Higher stability = positive delta = improvement
    """

    before: BenchmarkResult = field(default_factory=BenchmarkResult)
    after: BenchmarkResult = field(default_factory=BenchmarkResult)

    # Computed deltas
    fps_delta: Optional[float] = None
    fps_percent: Optional[float] = None
    one_percent_low_delta: Optional[float] = None
    one_percent_low_percent: Optional[float] = None
    zero_point_one_percent_low_delta: Optional[float] = None
    zero_point_one_percent_low_percent: Optional[float] = None
    frame_time_delta: Optional[float] = None  # negative = improvement
    frame_variance_delta: Optional[float] = None  # negative = improvement
    frame_spike_delta: Optional[int] = None  # negative = improvement
    stability_delta: Optional[float] = None  # positive = improvement

    # Overall result
    result: str = "INCONCLUSIVE"  # IMPROVED, DEGRADED, UNCHANGED, INCONCLUSIVE

    # What was applied
    optimizations_applied: list = field(default_factory=list)

    def __post_init__(self):
        if self.before.is_valid and self.after.is_valid:
            self._compute_deltas()
            self._determine_result()

    def _compute_deltas(self):
        """Compute all deltas from real measurements."""
        b = self.before
        a = self.after

        # FPS delta (higher = better)
        if b.present_fps is not None and a.present_fps is not None:
            self.fps_delta = a.present_fps - b.present_fps
            self.fps_percent = _safe_percent(self.fps_delta, b.present_fps)

        # 1% Low delta (higher = better)
        if b.one_percent_low is not None and a.one_percent_low is not None:
            self.one_percent_low_delta = a.one_percent_low - b.one_percent_low
            self.one_percent_low_percent = _safe_percent(
                self.one_percent_low_delta, b.one_percent_low
            )

        # 0.1% Low delta (higher = better)
        if b.zero_point_one_percent_low is not None and a.zero_point_one_percent_low is not None:
            self.zero_point_one_percent_low_delta = (
                a.zero_point_one_percent_low - b.zero_point_one_percent_low
            )
            self.zero_point_one_percent_low_percent = _safe_percent(
                self.zero_point_one_percent_low_delta, b.zero_point_one_percent_low
            )

        # Frame time delta (lower = better)
        if b.average_frame_time is not None and a.average_frame_time is not None:
            self.frame_time_delta = a.average_frame_time - b.average_frame_time

        # Frame variance delta (lower = better)
        if b.frame_time_variance is not None and a.frame_time_variance is not None:
            self.frame_variance_delta = a.frame_time_variance - b.frame_time_variance

        # Frame spike delta (lower = better)
        if b.frame_spikes is not None and a.frame_spikes is not None:
            self.frame_spike_delta = a.frame_spikes - b.frame_spikes

        # Stability delta (higher = better)
        if b.stability is not None and a.stability is not None:
            self.stability_delta = a.stability - b.stability

    def _determine_result(self):
        """
        Determine overall comparison result using a significance threshold.

        A change is SIGNIFICANT if:
          - FPS changed by >= 1% AND at least one other metric improved
          - OR any metric improved by >= 3%
          - OR stability improved by >= 5 points

        Otherwise: UNCHANGED or INCONCLUSIVE.
        """
        # Need valid data in both
        if not self.before.is_valid or not self.after.is_valid:
            self.result = "INCONCLUSIVE"
            return

        # Check if there's meaningful change
        improvements = 0
        regressions = 0

        # FPS significance: >= 1%
        if self.fps_percent is not None:
            if self.fps_percent >= 1.0:
                improvements += 1
            elif self.fps_percent <= -1.0:
                regressions += 1

        # 1% Low significance: >= 3%
        if self.one_percent_low_percent is not None:
            if self.one_percent_low_percent >= 3.0:
                improvements += 1
            elif self.one_percent_low_percent <= -3.0:
                regressions += 1

        # Frame time significance: >= 3% change (negative = improvement)
        if self.frame_time_delta is not None and self.before.average_frame_time:
            ft_pct = (self.frame_time_delta / self.before.average_frame_time) * 100
            if ft_pct <= -3.0:
                improvements += 1
            elif ft_pct >= 3.0:
                regressions += 1

        # Stability significance: >= 5 points
        if self.stability_delta is not None:
            if self.stability_delta >= 5.0:
                improvements += 1
            elif self.stability_delta <= -5.0:
                regressions += 1

        # Determine result
        if improvements > 0 and regressions == 0:
            self.result = "IMPROVED"
        elif regressions > 0 and improvements == 0:
            self.result = "DEGRADED"
        elif improvements > 0 and regressions > 0:
            # Mixed — consider net effect
            if improvements > regressions:
                self.result = "IMPROVED"
            elif regressions > improvements:
                self.result = "DEGRADED"
            else:
                self.result = "UNCHANGED"
        else:
            self.result = "UNCHANGED"

    def to_dict(self) -> dict:
        """Serialize to dict."""
        return {
            "before": self.before.to_dict(),
            "after": self.after.to_dict(),
            "fps_delta": self.fps_delta,
            "fps_percent": self.fps_percent,
            "one_percent_low_delta": self.one_percent_low_delta,
            "one_percent_low_percent": self.one_percent_low_percent,
            "zero_point_one_percent_low_delta": self.zero_point_one_percent_low_delta,
            "zero_point_one_percent_low_percent": self.zero_point_one_percent_low_percent,
            "frame_time_delta": self.frame_time_delta,
            "frame_variance_delta": self.frame_variance_delta,
            "frame_spike_delta": self.frame_spike_delta,
            "stability_delta": self.stability_delta,
            "result": self.result,
            "optimizations_applied": self.optimizations_applied,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BenchmarkComparison":
        """Deserialize from dict."""
        before = BenchmarkResult.from_dict(data.get("before", {}))
        after = BenchmarkResult.from_dict(data.get("after", {}))
        comp = cls(before=before, after=after)
        # Override computed values from stored data
        for field_name in [
            "fps_delta", "fps_percent", "one_percent_low_delta",
            "one_percent_low_percent", "zero_point_one_percent_low_delta",
            "zero_point_one_percent_low_percent", "frame_time_delta",
            "frame_variance_delta", "stability_delta", "result",
        ]:
            if field_name in data:
                setattr(comp, field_name, data[field_name])
        if "frame_spike_delta" in data:
            comp.frame_spike_delta = data["frame_spike_delta"]
        if "optimizations_applied" in data:
            comp.optimizations_applied = data["optimizations_applied"]
        return comp


def _safe_percent(delta: float, base: float) -> Optional[float]:
    """Calculate percentage change safely, returning None for zero base."""
    if base == 0:
        return None
    return (delta / abs(base)) * 100.0


def format_comparison_table(comp: BenchmarkComparison) -> str:
    """Format a benchmark comparison as a readable text table."""
    lines = []
    lines.append("=" * 50)
    lines.append("HEAVEN SOCIETY PERFORMANCE BENCHMARK")
    lines.append("=" * 50)

    # Target info
    if comp.before.target_name:
        lines.append("")
        lines.append("Target:")
        lines.append(f"  {comp.before.target_name}")
        lines.append(f"  PID: {comp.before.target_pid}")

    if comp.before.monitor_refresh_hz:
        lines.append("")
        lines.append(f"Monitor: {comp.before.monitor_refresh_hz} Hz")

    # Before
    lines.append("")
    lines.append("BASELINE")
    _append_result_lines(lines, comp.before)

    # After
    lines.append("")
    lines.append("AFTER")
    _append_result_lines(lines, comp.after)

    # Comparison
    if comp.before.is_valid and comp.after.is_valid:
        lines.append("")
        lines.append("COMPARISON")
        if comp.fps_percent is not None:
            sign = "+" if comp.fps_delta >= 0 else ""
            lines.append(f"  FPS:              {sign}{comp.fps_delta:.1f}  ({sign}{comp.fps_percent:.1f}%)")
        else:
            lines.append(f"  FPS:              N/A")

        if comp.one_percent_low_delta is not None:
            sign = "+" if comp.one_percent_low_delta >= 0 else ""
            lines.append(f"  1% Low:           {sign}{comp.one_percent_low_delta:.1f}  ({sign}{comp.one_percent_low_percent:.1f}%)")
        else:
            lines.append(f"  1% Low:           N/A")

        if comp.zero_point_one_percent_low_delta is not None:
            sign = "+" if comp.zero_point_one_percent_low_delta >= 0 else ""
            lines.append(f"  0.1% Low:         {sign}{comp.zero_point_one_percent_low_delta:.1f}  ({sign}{comp.zero_point_one_percent_low_percent:.1f}%)")

        if comp.frame_time_delta is not None:
            sign = "+" if comp.frame_time_delta >= 0 else ""
            lines.append(f"  Frame Time:       {sign}{comp.frame_time_delta:.2f} ms")

        if comp.stability_delta is not None:
            sign = "+" if comp.stability_delta >= 0 else ""
            lines.append(f"  Stability:        {sign}{comp.stability_delta:.1f}")

    # Optimizations applied
    if comp.optimizations_applied:
        lines.append("")
        lines.append("OPTIMIZATIONS")
        for opt in comp.optimizations_applied:
            lines.append(f"  {opt}")

    # Result
    lines.append("")
    lines.append("RESULT:")
    lines.append(f"  {comp.result}")

    lines.append("")
    lines.append("=" * 50)
    return "\n".join(lines)


def _append_result_lines(lines: list, result: BenchmarkResult):
    """Append benchmark result lines."""
    if result.capture_status == "NO_TARGET":
        lines.append("  No emulator detected")
        return
    if result.capture_status != "COMPLETE":
        lines.append(f"  Status: {result.capture_status}")
        if result.error:
            lines.append(f"  Error: {result.error}")
        return

    if result.present_fps is not None:
        lines.append(f"  Present FPS:       {result.present_fps:.1f}")
    else:
        lines.append(f"  Present FPS:       N/A")

    if result.one_percent_low is not None:
        lines.append(f"  1% Low:            {result.one_percent_low:.1f}")
    else:
        lines.append(f"  1% Low:            N/A")

    if result.zero_point_one_percent_low is not None:
        lines.append(f"  0.1% Low:          {result.zero_point_one_percent_low:.1f}")

    if result.average_frame_time is not None:
        lines.append(f"  Frame Time:        {result.average_frame_time:.2f} ms")

    if result.frame_spikes is not None:
        lines.append(f"  Frame Spikes:      {result.frame_spikes}")

    if result.stability is not None:
        lines.append(f"  Stability:         {result.stability:.1f}/100")

    lines.append(f"  Samples:           {result.sample_count}")
