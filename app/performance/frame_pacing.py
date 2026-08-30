"""
Frame Pacing Analysis — Heaven Society.

Analyzes frame delivery consistency rather than just average FPS.
Measures: frame-time distribution, stutter patterns, pacing quality.

All values originate from real PresentMon frame presentation timestamps.
No fabricated values. No simulated data.

Classification:
  EXCELLENT — consistent, smooth frame delivery
  GOOD      — mostly consistent, minor variations
  FAIR      — noticeable inconsistencies
  POOR      — frequent stutters and frame drops
  CRITICAL  — severe frame delivery problems

Pattern detection:
  CPU_BOUND — frame times cluster around CPU render time
  GPU_BOUND — frame times cluster around GPU render time
  SCHEDULING — periodic micro-stutters from emulator scheduling
  BACKGROUND_INTERFERENCE — irregular spikes from background processes
  THERMAL_THROTTLING — frame times increase over capture duration
  INCONSISTENT_PACING — high variance without clear pattern
"""

import statistics
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from enum import Enum

from app.performance.fps_provider import FrameSample
from app.utils.logger import get_logger

logger = get_logger("performance.frame_pacing")


# ── Classification ─────────────────────────────────────────────

class PacingClassification(Enum):
    """Frame pacing quality classification."""
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    FAIR = "FAIR"
    POOR = "POOR"
    CRITICAL = "CRITICAL"
    INSUFFICIENT_DATA = "INSUFFICIENT DATA"


class PacingPattern(Enum):
    """Detected frame pacing patterns."""
    CPU_BOUND = "CPU Bound"
    GPU_BOUND = "GPU Bound"
    SCHEDULING = "Emulator Scheduling"
    BACKGROUND_INTERFERENCE = "Background Interference"
    THERMAL_THROTTLING = "Thermal Throttling"
    INCONSISTENT_PACING = "Inconsistent Pacing"
    NO_ISSUE = "No Issue Detected"


# ── Data Models ────────────────────────────────────────────────

@dataclass
class PercentileFrameTimes:
    """Frame time percentiles in milliseconds."""
    p1: float = 0.0    # 1st percentile (worst frames)
    p5: float = 0.0
    p10: float = 0.0
    p25: float = 0.0
    p50: float = 0.0   # median
    p75: float = 0.0
    p90: float = 0.0
    p95: float = 0.0
    p99: float = 0.0   # best frames

    @property
    def interquartile_range(self) -> float:
        """IQR — measure of frame time spread."""
        return self.p75 - self.p25


@dataclass
class FramePacingResult:
    """
    Comprehensive frame pacing analysis result.
    All values originate from real PresentMon frame data.
    """

    # Basic metrics (from real measurements)
    sample_count: int = 0
    duration_seconds: float = 0.0

    # FPS metrics
    avg_fps: float = 0.0
    median_fps: float = 0.0
    min_fps: float = 0.0
    max_fps: float = 0.0
    one_percent_low: float = 0.0
    point_one_percent_low: float = 0.0

    # Frame time metrics (ms)
    avg_frame_time_ms: float = 0.0
    median_frame_time_ms: float = 0.0
    min_frame_time_ms: float = 0.0
    max_frame_time_ms: float = 0.0

    # Distribution metrics (from real measurements)
    frame_time_stdev: float = 0.0        # standard deviation
    coefficient_of_variation: float = 0.0 # stdev / mean (dimensionless)
    percentiles: PercentileFrameTimes = field(default_factory=PercentileFrameTimes)

    # Spike / stutter metrics
    frame_spikes: int = 0                 # frames > 2x average
    long_frame_count: int = 0             # frames > 3x median
    long_frame_percent: float = 0.0       # percentage of long frames
    consecutive_stutters: int = 0         # max consecutive spikes

    # Stutter breakdown
    micro_stutters: int = 0               # 2-3x median
    severe_stutters: int = 0              # > 3x median
    huge_spikes: int = 0                  # > 5x median

    # Pacing score (0-100) — from real measurements
    pacing_score: float = 0.0
    classification: PacingClassification = PacingClassification.INSUFFICIENT_DATA

    # Pattern detection (HEURISTIC based on measured values)
    detected_patterns: List[PacingPattern] = field(default_factory=list)
    pattern_confidences: dict = field(default_factory=dict)
    pattern_descriptions: dict = field(default_factory=dict)

    # GPU/CPU timing (from PresentMon when available)
    avg_gpu_busy_ms: float = 0.0
    avg_cpu_busy_ms: float = 0.0
    gpu_utilization: float = 0.0

    # Data source
    provider: str = ""
    is_measured: bool = True

    # Recommendations
    recommendations: List[str] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        return self.sample_count >= 10 and self.is_measured

    def to_dict(self) -> dict:
        """Serialize to dict for JSON storage."""
        return {
            "sample_count": self.sample_count,
            "duration_seconds": self.duration_seconds,
            "avg_fps": self.avg_fps,
            "median_fps": self.median_fps,
            "min_fps": self.min_fps,
            "max_fps": self.max_fps,
            "one_percent_low": self.one_percent_low,
            "point_one_percent_low": self.point_one_percent_low,
            "avg_frame_time_ms": self.avg_frame_time_ms,
            "median_frame_time_ms": self.median_frame_time_ms,
            "frame_time_stdev": self.frame_time_stdev,
            "coefficient_of_variation": self.coefficient_of_variation,
            "frame_spikes": self.frame_spikes,
            "long_frame_count": self.long_frame_count,
            "long_frame_percent": self.long_frame_percent,
            "pacing_score": self.pacing_score,
            "classification": self.classification.value,
            "detected_patterns": [p.value for p in self.detected_patterns],
            "recommendations": self.recommendations,
            "provider": self.provider,
        }


# ── Core Analyzer ──────────────────────────────────────────────

class FramePacingAnalyzer:
    """
    Comprehensive frame pacing analysis from real PresentMon frame data.

    All values originate from actual frame presentation timestamps.
    Pattern detection uses heuristics based on measured values.
    """

    def analyze(self, samples: List[FrameSample]) -> FramePacingResult:
        """
        Analyze frame pacing from real frame samples.

        Args:
            samples: List of FrameSample from PresentMon capture

        Returns:
            FramePacingResult with all metrics computed from real data
        """
        result = FramePacingResult()

        if not samples or len(samples) < 10:
            result.is_measured = True if samples else False
            result.sample_count = len(samples) if samples else 0
            return result

        # Extract frame times (filter out invalid)
        frame_times = [s.frame_time_ms for s in samples if s.frame_time_ms > 0]
        if len(frame_times) < 10:
            result.sample_count = len(frame_times)
            result.is_measured = True
            return result

        result.sample_count = len(frame_times)
        result.duration_seconds = sum(frame_times) / 1000.0
        result.is_measured = True

        # Provider info
        if samples and samples[0].process_name:
            result.provider = f"PresentMon ({samples[0].process_name})"

        # ── 1. Basic metrics ──────────────────────────────────
        self._compute_basic_metrics(result, frame_times)

        # ── 2. Distribution metrics ───────────────────────────
        self._compute_distribution_metrics(result, frame_times)

        # ── 3. Percentiles ────────────────────────────────────
        self._compute_percentiles(result, frame_times)

        # ── 4. Spike / stutter metrics ────────────────────────
        self._compute_spike_metrics(result, frame_times)

        # ── 5. GPU/CPU timing ─────────────────────────────────
        self._compute_gpu_cpu_timing(result, samples)

        # ── 6. Pacing score ───────────────────────────────────
        result.pacing_score = self._calculate_pacing_score(result)
        result.classification = self._classify_pacing(result.pacing_score)

        # ── 7. Pattern detection ──────────────────────────────
        result.detected_patterns, result.pattern_confidences, \
            result.pattern_descriptions = self._detect_patterns(result, samples)

        # ── 8. Recommendations ────────────────────────────────
        result.recommendations = self._generate_recommendations(result)

        return result

    def _compute_basic_metrics(
        self, result: FramePacingResult, frame_times: List[float]
    ):
        """Compute basic FPS and frame time metrics from real data."""
        n = len(frame_times)

        # FPS values
        fps_values = [1000.0 / ft for ft in frame_times if ft > 0]
        if not fps_values:
            return

        sorted_fps = sorted(fps_values)
        result.avg_fps = statistics.mean(fps_values)
        result.median_fps = statistics.median(fps_values)
        result.min_fps = min(fps_values)
        result.max_fps = max(fps_values)

        # 1% low and 0.1% low
        p1_idx = max(0, int(len(sorted_fps) * 0.01))
        p01_idx = max(0, int(len(sorted_fps) * 0.001))
        result.one_percent_low = sorted_fps[p1_idx]
        result.point_one_percent_low = sorted_fps[p01_idx]

        # Frame time basics
        result.avg_frame_time_ms = statistics.mean(frame_times)
        result.median_frame_time_ms = statistics.median(frame_times)
        result.min_frame_time_ms = min(frame_times)
        result.max_frame_time_ms = max(frame_times)

    def _compute_distribution_metrics(
        self, result: FramePacingResult, frame_times: List[float]
    ):
        """Compute standard deviation and coefficient of variation."""
        n = len(frame_times)
        if n < 2:
            return

        result.frame_time_stdev = statistics.stdev(frame_times)
        mean = statistics.mean(frame_times)
        if mean > 0:
            result.coefficient_of_variation = result.frame_time_stdev / mean

    def _compute_percentiles(
        self, result: FramePacingResult, frame_times: List[float]
    ):
        """Compute frame time percentiles from real data."""
        sorted_ft = sorted(frame_times)
        n = len(sorted_ft)

        def percentile(pct: float) -> float:
            idx = int(n * pct / 100.0)
            idx = min(idx, n - 1)
            return sorted_ft[idx]

        result.percentiles = PercentileFrameTimes(
            p1=percentile(1),
            p5=percentile(5),
            p10=percentile(10),
            p25=percentile(25),
            p50=percentile(50),
            p75=percentile(75),
            p90=percentile(90),
            p95=percentile(95),
            p99=percentile(99),
        )

    def _compute_spike_metrics(
        self, result: FramePacingResult, frame_times: List[float]
    ):
        """Compute frame spike and stutter metrics from real data."""
        median_ft = result.median_frame_time_ms
        if median_ft <= 0:
            return

        spike_threshold = median_ft * 2     # >2x median = spike
        long_threshold = median_ft * 3      # >3x median = long frame
        micro_threshold = median_ft * 2     # 2-3x = micro-stutter
        severe_threshold = median_ft * 3    # >3x = severe
        huge_threshold = median_ft * 5      # >5x = huge spike

        spikes = 0
        long_frames = 0
        micro = 0
        severe = 0
        huge = 0
        consecutive = 0
        max_consecutive = 0

        for ft in frame_times:
            if ft > spike_threshold:
                spikes += 1
                consecutive += 1
                max_consecutive = max(max_consecutive, consecutive)
            else:
                consecutive = 0

            if ft > long_threshold:
                long_frames += 1

            if ft > huge_threshold:
                huge += 1
            elif ft > severe_threshold:
                severe += 1
            elif ft > micro_threshold:
                micro += 1

        result.frame_spikes = spikes
        result.long_frame_count = long_frames
        result.long_frame_percent = (long_frames / len(frame_times)) * 100
        result.consecutive_stutters = max_consecutive
        result.micro_stutters = micro
        result.severe_stutters = severe
        result.huge_spikes = huge

    def _compute_gpu_cpu_timing(
        self, result: FramePacingResult, samples: List[FrameSample]
    ):
        """Extract GPU/CPU timing from PresentMon samples."""
        gpu_times = [s.gpu_ms for s in samples if s.gpu_ms > 0]
        cpu_times = [s.cpu_ms for s in samples if s.cpu_ms > 0]
        gpu_busy = [s.gpu_busy for s in samples if s.gpu_busy > 0]

        if gpu_times:
            result.avg_gpu_busy_ms = statistics.mean(gpu_times)
        if cpu_times:
            result.avg_cpu_busy_ms = statistics.mean(cpu_times)
        if gpu_busy:
            result.gpu_utilization = statistics.mean(gpu_busy)

    def _calculate_pacing_score(self, result: FramePacingResult) -> float:
        """
        Calculate pacing score (0-100) from measured values.

        Weighting:
        - Coefficient of variation: 30% (lower = better)
        - Long frame percentage: 25% (lower = better)
        - Spike count relative to samples: 20% (lower = better)
        - Consecutive stutters: 15% (lower = better)
        - 1% low / avg ratio: 10% (higher = better)
        """
        if result.sample_count < 10:
            return 0.0

        scores = {}

        # CV score: CV=0 → 100, CV=0.5 → 50, CV=1.0 → 0
        cv = result.coefficient_of_variation
        scores["cv"] = max(0, min(100, 100 - (cv * 100)))

        # Long frame % score: 0% → 100, 5% → 50, 10% → 0
        lfp = result.long_frame_percent
        scores["long_frames"] = max(0, min(100, 100 - (lfp * 10)))

        # Spike ratio score: 0% → 100, 5% → 50, 10% → 0
        spike_ratio = (result.frame_spikes / result.sample_count) * 100
        scores["spikes"] = max(0, min(100, 100 - (spike_ratio * 10)))

        # Consecutive stutter score: 0 → 100, 5 → 50, 10 → 0
        scores["consecutive"] = max(0, min(100, 100 - (result.consecutive_stutters * 10)))

        # 1% low ratio score: ratio=1.0 → 100, ratio=0.5 → 50
        if result.avg_fps > 0:
            low_ratio = result.one_percent_low / result.avg_fps
            scores["low_ratio"] = max(0, min(100, low_ratio * 120))
        else:
            scores["low_ratio"] = 50

        # Weighted average
        weights = {
            "cv": 0.30,
            "long_frames": 0.25,
            "spikes": 0.20,
            "consecutive": 0.15,
            "low_ratio": 0.10,
        }

        total = sum(scores[k] * weights[k] for k in scores)
        return max(0, min(100, total))

    def _classify_pacing(self, score: float) -> PacingClassification:
        """Classify pacing quality from score."""
        if score >= 85:
            return PacingClassification.EXCELLENT
        if score >= 70:
            return PacingClassification.GOOD
        if score >= 50:
            return PacingClassification.FAIR
        if score >= 30:
            return PacingClassification.POOR
        if score > 0:
            return PacingClassification.CRITICAL
        return PacingClassification.INSUFFICIENT_DATA

    def _detect_patterns(
        self,
        result: FramePacingResult,
        samples: List[FrameSample],
    ) -> Tuple[List[PacingPattern], dict, dict]:
        """
        Detect frame pacing patterns from measured values.
        Uses heuristics based on real data — not fabricated.
        """
        patterns = []
        confidences = {}
        descriptions = {}

        if result.sample_count < 10:
            return patterns, confidences, descriptions

        # ── CPU-bound detection ────────────────────────────────
        # HEURISTIC: If CPU busy time is high relative to frame time
        if result.avg_cpu_busy_ms > 0 and result.avg_frame_time_ms > 0:
            cpu_ratio = result.avg_cpu_busy_ms / result.avg_frame_time_ms
            if cpu_ratio > 0.7:
                conf = min(0.9, cpu_ratio * 0.8)
                patterns.append(PacingPattern.CPU_BOUND)
                confidences[PacingPattern.CPU_BOUND.value] = conf
                descriptions[PacingPattern.CPU_BOUND.value] = (
                    f"CPU busy {result.avg_cpu_busy_ms:.1f}ms / "
                    f"frame {result.avg_frame_time_ms:.1f}ms "
                    f"({cpu_ratio * 100:.0f}%) — CPU is the primary limiter"
                )

        # ── GPU-bound detection ────────────────────────────────
        # HEURISTIC: If GPU busy time is high relative to frame time
        if result.avg_gpu_busy_ms > 0 and result.avg_frame_time_ms > 0:
            gpu_ratio = result.avg_gpu_busy_ms / result.avg_frame_time_ms
            if gpu_ratio > 0.7:
                conf = min(0.9, gpu_ratio * 0.8)
                patterns.append(PacingPattern.GPU_BOUND)
                confidences[PacingPattern.GPU_BOUND.value] = conf
                descriptions[PacingPattern.GPU_BOUND.value] = (
                    f"GPU busy {result.avg_gpu_busy_ms:.1f}ms / "
                    f"frame {result.avg_frame_time_ms:.1f}ms "
                    f"({gpu_ratio * 100:.0f}%) — GPU is the primary limiter"
                )

        # ── Scheduling detection ───────────────────────────────
        # HEURISTIC: Periodic micro-stutters (regular spike intervals)
        if result.micro_stutters > 5 and result.consecutive_stutters <= 2:
            # Check if spikes are roughly periodic
            frame_times = [s.frame_time_ms for s in samples if s.frame_time_ms > 0]
            spike_intervals = self._find_spike_intervals(frame_times)
            if spike_intervals and self._is_periodic(spike_intervals):
                conf = min(0.8, result.micro_stutters / result.sample_count * 20)
                patterns.append(PacingPattern.SCHEDULING)
                confidences[PacingPattern.SCHEDULING.value] = conf
                descriptions[PacingPattern.SCHEDULING.value] = (
                    f"Periodic micro-stutters detected ({result.micro_stutters} occurrences). "
                    "May be emulator scheduling overhead."
                )

        # ── Background interference detection ──────────────────
        # HEURISTIC: Irregular large spikes with high consecutive count
        if result.consecutive_stutters >= 3 and result.huge_spikes > 0:
            conf = min(0.7, result.huge_spikes / max(1, result.sample_count) * 50)
            patterns.append(PacingPattern.BACKGROUND_INTERFERENCE)
            confidences[PacingPattern.BACKGROUND_INTERFERENCE.value] = conf
            descriptions[PacingPattern.BACKGROUND_INTERFERENCE.value] = (
                f"Consecutive stutters ({result.consecutive_stutters}) and "
                f"large spikes ({result.huge_spikes}) suggest background interference."
            )

        # ── Thermal throttling detection ───────────────────────
        # HEURISTIC: Frame times trend upward over capture duration
        if result.sample_count > 50:
            frame_times = [s.frame_time_ms for s in samples if s.frame_time_ms > 0]
            trend = self._detect_upward_trend(frame_times)
            if trend > 0.15:  # Significant upward trend
                conf = min(0.7, trend)
                patterns.append(PacingPattern.THERMAL_THROTTLING)
                confidences[PacingPattern.THERMAL_THROTTLING.value] = conf
                descriptions[PacingPattern.THERMAL_THROTTLING.value] = (
                    f"Frame times trend upward over capture ({trend:.0%} increase). "
                    "May indicate thermal throttling."
                )

        # ── Inconsistent pacing ────────────────────────────────
        # HEURISTIC: High CV without a clear dominant pattern
        if result.coefficient_of_variation > 0.3 and len(patterns) < 2:
            conf = min(0.6, result.coefficient_of_variation)
            patterns.append(PacingPattern.INCONSISTENT_PACING)
            confidences[PacingPattern.INCONSISTENT_PACING.value] = conf
            descriptions[PacingPattern.INCONSISTENT_PACING.value] = (
                f"High frame time variation (CV={result.coefficient_of_variation:.2f}). "
                "Frame delivery is inconsistent."
            )

        if not patterns:
            patterns.append(PacingPattern.NO_ISSUE)
            confidences[PacingPattern.NO_ISSUE.value] = 0.5
            descriptions[PacingPattern.NO_ISSUE.value] = (
                "No significant frame pacing issues detected."
            )

        return patterns, confidences, descriptions

    def _find_spike_intervals(self, frame_times: List[float]) -> List[int]:
        """Find intervals between frame spikes."""
        if not frame_times:
            return []

        median = statistics.median(frame_times)
        threshold = median * 2
        intervals = []
        last_spike_idx = -1

        for i, ft in enumerate(frame_times):
            if ft > threshold:
                if last_spike_idx >= 0:
                    intervals.append(i - last_spike_idx)
                last_spike_idx = i

        return intervals

    def _is_periodic(self, intervals: List[int], tolerance: float = 0.3) -> bool:
        """Check if spike intervals are roughly periodic."""
        if len(intervals) < 3:
            return False

        mean_interval = statistics.mean(intervals)
        if mean_interval <= 0:
            return False

        # Check if most intervals are within tolerance of mean
        within = sum(
            1 for iv in intervals
            if abs(iv - mean_interval) / mean_interval < tolerance
        )
        return within / len(intervals) > 0.6

    def _detect_upward_trend(self, values: List[float]) -> float:
        """
        Detect upward trend in frame times.
        Returns trend strength (0 = no trend, 1 = strong upward).
        HEURISTIC — not a definitive thermal detection.
        """
        if len(values) < 20:
            return 0.0

        n = len(values)
        third = n // 3

        first_third = statistics.mean(values[:third])
        last_third = statistics.mean(values[-third:])

        if first_third <= 0:
            return 0.0

        increase = (last_third - first_third) / first_third
        return max(0.0, increase)

    def _generate_recommendations(self, result: FramePacingResult) -> List[str]:
        """Generate recommendations from measured pacing data."""
        recs = []

        if not result.is_valid:
            return recs

        if result.classification == PacingClassification.CRITICAL:
            recs.append(
                "Frame pacing is critical. Significant stutters detected. "
                "Close background applications and verify thermal state."
            )

        if PacingPattern.CPU_BOUND in result.detected_patterns:
            recs.append(
                "CPU-bound frame pacing detected. "
                "Consider setting emulator to HIGH priority or reducing CPU load."
            )

        if PacingPattern.GPU_BOUND in result.detected_patterns:
            recs.append(
                "GPU-bound frame pacing detected. "
                "Consider reducing emulator graphics settings."
            )

        if PacingPattern.THERMAL_THROTTLING in result.detected_patterns:
            recs.append(
                "Thermal throttling likely. Frame times increase over time. "
                "Ensure adequate cooling and ventilation."
            )

        if PacingPattern.BACKGROUND_INTERFERENCE in result.detected_patterns:
            recs.append(
                "Background process interference detected. "
                "Close unnecessary applications during gaming."
            )

        if result.long_frame_percent > 5:
            recs.append(
                f"{result.long_frame_percent:.1f}% of frames are significantly delayed. "
                "Investigate background process activity."
            )

        if result.coefficient_of_variation > 0.4:
            recs.append(
                "High frame time variation — inconsistent frame delivery. "
                "This degrades perceived smoothness even with high average FPS."
            )

        return recs


# Singleton
frame_pacing_analyzer = FramePacingAnalyzer()
