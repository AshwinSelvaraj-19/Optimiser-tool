"""
A/B Benchmark models — repeated measurement, aggregation, reliability.

Every value originates from real PresentMon frame data.
Outlier detection uses IQR method.
Confidence is deterministic based on run quality and variance.
"""

import statistics
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List


# ── Single run ────────────────────────────────────────────────

@dataclass
class BenchmarkRun:
    """A single benchmark capture run."""
    run_index: int = 0
    result: Optional["BenchmarkResult"] = None
    is_outlier: bool = False
    outlier_reason: str = ""

    @property
    def is_valid(self) -> bool:
        return self.result is not None and self.result.is_valid and not self.is_outlier


# ── Repeated benchmark ────────────────────────────────────────

@dataclass
class RepeatedBenchmark:
    """Multiple benchmark runs for one condition (baseline or optimized)."""
    runs: List[BenchmarkRun] = field(default_factory=list)
    label: str = ""  # "baseline" or "optimized"

    @property
    def valid_runs(self) -> List[BenchmarkRun]:
        return [r for r in self.runs if r.is_valid]

    @property
    def valid_count(self) -> int:
        return len(self.valid_runs)

    @property
    def total_count(self) -> int:
        return len(self.runs)

    @property
    def outlier_count(self) -> int:
        return sum(1 for r in self.runs if r.is_outlier)

    @property
    def all_target_pids(self) -> set:
        pids = set()
        for r in self.runs:
            if r.result:
                pids.add(r.result.target_pid)
        return pids

    @property
    def consistent_pid(self) -> bool:
        return len(self.all_target_pids) <= 1


# ── Statistics ────────────────────────────────────────────────

@dataclass
class BenchmarkStatistics:
    """Aggregated statistics from valid benchmark runs."""
    values: List[float] = field(default_factory=list)
    label: str = ""

    @property
    def count(self) -> int:
        return len(self.values)

    @property
    def mean(self) -> Optional[float]:
        return statistics.mean(self.values) if self.values else None

    @property
    def median(self) -> Optional[float]:
        return statistics.median(self.values) if self.values else None

    @property
    def min_val(self) -> Optional[float]:
        return min(self.values) if self.values else None

    @property
    def max_val(self) -> Optional[float]:
        return max(self.values) if self.values else None

    @property
    def stdev(self) -> Optional[float]:
        if len(self.values) < 2:
            return 0.0
        return statistics.stdev(self.values)

    @property
    def cv(self) -> Optional[float]:
        """Coefficient of variation (%). None if mean is zero."""
        m = self.mean
        s = self.stdev
        if m is None or s is None or m == 0:
            return None
        return (s / abs(m)) * 100.0

    @classmethod
    def from_values(cls, values: List[float], label: str = "") -> "BenchmarkStatistics":
        return cls(values=[v for v in values if v is not None], label=label)

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "count": self.count,
            "mean": round(self.mean, 2) if self.mean is not None else None,
            "median": round(self.median, 2) if self.median is not None else None,
            "min": round(self.min_val, 2) if self.min_val is not None else None,
            "max": round(self.max_val, 2) if self.max_val is not None else None,
            "stdev": round(self.stdev, 2) if self.stdev is not None else None,
            "cv": round(self.cv, 2) if self.cv is not None else None,
        }


# ── Outlier detection ─────────────────────────────────────────

def detect_outliers_iqr(values: List[float], factor: float = 1.5) -> List[bool]:
    """
    Detect outliers using the IQR method.
    Returns a boolean list of the same length, True = outlier.
    """
    if len(values) < 4:
        return [False] * len(values)

    sorted_vals = sorted(values)
    n = len(sorted_vals)
    q1_idx = n // 4
    q3_idx = (3 * n) // 4
    q1 = sorted_vals[q1_idx]
    q3 = sorted_vals[q3_idx]
    iqr = q3 - q1

    lower = q1 - factor * iqr
    upper = q3 + factor * iqr

    return [v < lower or v > upper for v in values]


def detect_outliers_mad(values: List[float], threshold: float = 3.0) -> List[bool]:
    """
    Detect outliers using Median Absolute Deviation.
    More robust than IQR for small sample sizes.
    """
    if len(values) < 3:
        return [False] * len(values)

    med = statistics.median(values)
    abs_devs = [abs(v - med) for v in values]
    mad = statistics.median(abs_devs)

    if mad == 0:
        return [False] * len(values)

    return [abs(v - med) / (mad * 1.4826) > threshold for v in values]


# ── A/B Comparison ────────────────────────────────────────────

@dataclass
class ABComparison:
    """Comparison between baseline and optimized repeated benchmarks."""
    baseline: Optional[RepeatedBenchmark] = None
    optimized: Optional[RepeatedBenchmark] = None

    # Aggregated stats
    baseline_stats: Optional[dict] = None  # metric -> BenchmarkStatistics
    optimized_stats: Optional[dict] = None

    # Deltas
    fps_delta: Optional[float] = None
    fps_percent: Optional[float] = None
    one_low_delta: Optional[float] = None
    one_low_percent: Optional[float] = None
    zero_low_delta: Optional[float] = None
    zero_low_percent: Optional[float] = None
    frame_time_delta: Optional[float] = None
    frame_variance_delta: Optional[float] = None
    stability_delta: Optional[float] = None

    # Overall
    result: str = "INCONCLUSIVE"
    confidence: str = "INCONCLUSIVE"
    optimizations_applied: list = field(default_factory=list)
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now().isoformat()

    def to_dict(self) -> dict:
        return {
            "baseline_stats": {k: v.to_dict() for k, v in (self.baseline_stats or {}).items()},
            "optimized_stats": {k: v.to_dict() for k, v in (self.optimized_stats or {}).items()},
            "fps_delta": self.fps_delta,
            "fps_percent": self.fps_percent,
            "one_low_delta": self.one_low_delta,
            "one_low_percent": self.one_low_percent,
            "zero_low_delta": self.zero_low_delta,
            "zero_low_percent": self.zero_low_percent,
            "frame_time_delta": self.frame_time_delta,
            "frame_variance_delta": self.frame_variance_delta,
            "stability_delta": self.stability_delta,
            "result": self.result,
            "confidence": self.confidence,
            "optimizations_applied": self.optimizations_applied,
            "baseline_valid": self.baseline.valid_count if self.baseline else 0,
            "baseline_total": self.baseline.total_count if self.baseline else 0,
            "optimized_valid": self.optimized.valid_count if self.optimized else 0,
            "optimized_total": self.optimized.total_count if self.optimized else 0,
            "timestamp": self.timestamp,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ABComparison":
        comp = cls()
        for k in [
            "fps_delta", "fps_percent", "one_low_delta", "one_low_percent",
            "zero_low_delta", "zero_low_percent", "frame_time_delta",
            "frame_variance_delta", "stability_delta", "result",
            "confidence", "optimizations_applied", "timestamp",
        ]:
            if k in data:
                setattr(comp, k, data[k])
        return comp


# ── Reliability ───────────────────────────────────────────────

@dataclass
class BenchmarkReliability:
    """Deterministic reliability assessment of A/B comparison."""
    level: str = "INCONCLUSIVE"  # HIGH, MODERATE, LOW, INCONCLUSIVE
    reasons: List[str] = field(default_factory=list)
    baseline_valid_runs: int = 0
    optimized_valid_runs: int = 0
    baseline_cv: Optional[float] = None
    optimized_cv: Optional[float] = None
    pid_consistent: bool = True
    min_sample_count: int = 0

    def to_dict(self) -> dict:
        return {
            "level": self.level,
            "reasons": self.reasons,
            "baseline_valid_runs": self.baseline_valid_runs,
            "optimized_valid_runs": self.optimized_valid_runs,
            "baseline_cv": self.baseline_cv,
            "optimized_cv": self.optimized_cv,
            "pid_consistent": self.pid_consistent,
            "min_sample_count": self.min_sample_count,
        }


def classify_reliability(
    baseline: RepeatedBenchmark,
    optimized: RepeatedBenchmark,
    baseline_cv: Optional[float] = None,
    optimized_cv: Optional[float] = None,
) -> BenchmarkReliability:
    """
    Classify benchmark reliability based on:
    - Number of valid runs
    - Run-to-run variance (CV)
    - Target PID consistency
    - Minimum sample quality
    """
    rel = BenchmarkReliability()
    rel.baseline_valid_runs = baseline.valid_count
    rel.optimized_valid_runs = optimized.valid_count
    rel.baseline_cv = baseline_cv
    rel.optimized_cv = optimized_cv
    rel.pid_consistent = baseline.consistent_pid and optimized.consistent_pid

    # Check minimum sample count from valid runs
    min_samples = float("inf")
    for r in baseline.valid_runs + optimized.valid_runs:
        if r.result and r.result.sample_count > 0:
            min_samples = min(min_samples, r.result.sample_count)
    rel.min_sample_count = min_samples if min_samples != float("inf") else 0

    # ── INCONCLUSIVE checks ──
    if baseline.valid_count < 2 or optimized.valid_count < 2:
        rel.level = "INCONCLUSIVE"
        rel.reasons.append(
            f"Insufficient valid runs: baseline={baseline.valid_count}, "
            f"optimized={optimized.valid_count} (need >= 2 each)"
        )
        return rel

    if not rel.pid_consistent:
        rel.level = "INCONCLUSIVE"
        rel.reasons.append("Target PID changed between runs")
        return rel

    if rel.min_sample_count < 50:
        rel.level = "INCONCLUSIVE"
        rel.reasons.append(
            f"Minimum sample count too low: {rel.min_sample_count} (need >= 50)"
        )
        return rel

    # ── Confidence based on CV ──
    max_cv = max(
        baseline_cv or 0,
        optimized_cv or 0,
    )

    if max_cv <= 5.0 and baseline.valid_count >= 3 and optimized.valid_count >= 3:
        rel.level = "HIGH"
        rel.reasons.append(f"Low variance (max CV: {max_cv:.1f}%)")
        rel.reasons.append(f"Full run count: {baseline.valid_count}/{optimized.valid_count}")
    elif max_cv <= 15.0:
        rel.level = "MODERATE"
        rel.reasons.append(f"Moderate variance (max CV: {max_cv:.1f}%)")
    else:
        rel.level = "LOW"
        rel.reasons.append(f"High variance (max CV: {max_cv:.1f}%)")

    return rel


# ── CLI formatting ────────────────────────────────────────────

def format_ab_table(ab: ABComparison) -> str:
    """Format A/B comparison as readable CLI output."""
    lines = []
    lines.append("=" * 50)
    lines.append("HEAVEN SOCIETY A/B PERFORMANCE TEST")
    lines.append("=" * 50)

    # Target
    if ab.baseline and ab.baseline.valid_runs:
        first = ab.baseline.valid_runs[0].result
        if first:
            lines.append("")
            lines.append("Target:")
            lines.append(f"  {first.target_name}")
            lines.append(f"  PID: {first.target_pid}")

    # Runs info
    lines.append("")
    lines.append("Runs:")
    bl_n = ab.baseline.total_count if ab.baseline else 0
    op_n = ab.optimized.total_count if ab.optimized else 0
    dur = 0
    if ab.baseline and ab.baseline.valid_runs and ab.baseline.valid_runs[0].result:
        dur = ab.baseline.valid_runs[0].result.duration_seconds
    lines.append(f"  {bl_n} baseline")
    lines.append(f"  {op_n} optimized")
    lines.append(f"  Duration: {dur}s")

    # Baseline median
    lines.append("")
    lines.append("BASELINE MEDIAN")
    _append_stats_lines(lines, ab.baseline_stats)

    # Optimized median
    lines.append("")
    lines.append("OPTIMIZED MEDIAN")
    _append_stats_lines(lines, ab.optimized_stats)

    # Change
    lines.append("")
    lines.append("CHANGE")
    _append_delta_lines(lines, ab)

    # Run quality
    lines.append("")
    lines.append("RUN QUALITY")
    bl_v = ab.baseline.valid_count if ab.baseline else 0
    bl_t = ab.baseline.total_count if ab.baseline else 0
    op_v = ab.optimized.valid_count if ab.optimized else 0
    op_t = ab.optimized.total_count if ab.optimized else 0
    lines.append(f"  Baseline:  {bl_v}/{bl_t} valid")
    lines.append(f"  Optimized: {op_v}/{op_t} valid")

    # Confidence
    lines.append("")
    lines.append("CONFIDENCE:")
    lines.append(f"  {ab.confidence}")

    # Result
    lines.append("")
    lines.append("RESULT:")
    lines.append(f"  {ab.result}")

    lines.append("")
    lines.append("=" * 50)
    return "\n".join(lines)


def _append_stats_lines(lines: list, stats: Optional[dict]):
    """Append aggregated statistics lines."""
    if not stats:
        lines.append("  No valid data")
        return

    fps = stats.get("present_fps")
    if fps:
        lines.append(f"  Present FPS:      {fps.median:.1f}")
    else:
        lines.append(f"  Present FPS:      N/A")

    low1 = stats.get("one_percent_low")
    if low1:
        lines.append(f"  1% Low:            {low1.median:.1f}")
    else:
        lines.append(f"  1% Low:            N/A")

    low01 = stats.get("zero_point_one_percent_low")
    if low01:
        lines.append(f"  0.1% Low:          {low01.median:.1f}")

    ft = stats.get("average_frame_time")
    if ft:
        lines.append(f"  Frame Time:        {ft.median:.2f} ms")


def _append_delta_lines(lines: list, ab: ABComparison):
    """Append delta comparison lines."""
    if ab.fps_percent is not None:
        sign = "+" if ab.fps_delta >= 0 else ""
        lines.append(f"  FPS:               {sign}{ab.fps_delta:.1f}  ({sign}{ab.fps_percent:.1f}%)")
    else:
        lines.append(f"  FPS:               N/A")

    if ab.one_low_percent is not None:
        sign = "+" if ab.one_low_delta >= 0 else ""
        lines.append(f"  1% Low:            {sign}{ab.one_low_delta:.1f}  ({sign}{ab.one_low_percent:.1f}%)")
    else:
        lines.append(f"  1% Low:            N/A")

    if ab.zero_low_percent is not None:
        sign = "+" if ab.zero_low_delta >= 0 else ""
        lines.append(f"  0.1% Low:          {sign}{ab.zero_low_delta:.1f}  ({sign}{ab.zero_low_percent:.1f}%)")

    if ab.frame_time_delta is not None:
        sign = "+" if ab.frame_time_delta >= 0 else ""
        lines.append(f"  Frame Time:        {sign}{ab.frame_time_delta:.2f} ms")

    if ab.stability_delta is not None:
        sign = "+" if ab.stability_delta >= 0 else ""
        lines.append(f"  Stability:         {sign}{ab.stability_delta:.1f}")
