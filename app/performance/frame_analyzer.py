"""
Frame pacing analyzer — calculates real metrics from actual frame timestamps.
Uses measurement windows for stable analysis.
"""

import statistics
from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("performance.frame_analyzer")


@dataclass
class PacingResult:
    """Frame pacing analysis result."""
    avg_frame_time_ms: float = 0.0
    median_frame_time_ms: float = 0.0
    min_frame_time_ms: float = 0.0
    max_frame_time_ms: float = 0.0
    std_dev_ms: float = 0.0
    variance_ms: float = 0.0

    avg_fps: float = 0.0
    median_fps: float = 0.0
    min_fps: float = 0.0
    max_fps: float = 0.0
    one_percent_low: float = 0.0
    point_one_percent_low: float = 0.0

    spike_count: int = 0
    long_frame_count: int = 0
    total_frames: int = 0
    duration_seconds: float = 0.0

    stability: str = "UNKNOWN"  # EXCELLENT, GOOD, FAIR, POOR, BAD
    stability_score: float = 0.0  # 0-100


class FramePacingAnalyzer:
    """Analyzes frame pacing from real frame timestamps."""

    def __init__(self, spike_threshold_ms: float = 33.33):
        """
        spike_threshold_ms: frames longer than this are considered spikes.
        Default 33.33ms = anything below 30 FPS.
        """
        self._spike_threshold = spike_threshold_ms

    def analyze(self, frame_times_ms: list) -> PacingResult:
        """
        Analyze frame times from real frame presentation timestamps.
        Input: list of frame times in milliseconds.
        """
        result = PacingResult()

        if not frame_times_ms or len(frame_times_ms) < 2:
            return result

        # Filter out invalid values
        valid = [ft for ft in frame_times_ms if ft > 0 and ft < 10000]
        if len(valid) < 2:
            return result

        result.total_frames = len(valid)
        result.duration_seconds = sum(valid) / 1000.0

        # Frame time statistics
        result.avg_frame_time_ms = statistics.mean(valid)
        result.median_frame_time_ms = statistics.median(valid)
        result.min_frame_time_ms = min(valid)
        result.max_frame_time_ms = max(valid)
        result.variance_ms = statistics.variance(valid) if len(valid) > 1 else 0
        result.std_dev_ms = result.variance_ms ** 0.5

        # FPS statistics (from frame times)
        fps_values = [1000.0 / ft for ft in valid if ft > 0]
        if fps_values:
            result.avg_fps = statistics.mean(fps_values)
            result.median_fps = statistics.median(fps_values)
            result.min_fps = min(fps_values)
            result.max_fps = max(fps_values)

        # Percentile lows (from sorted FPS values)
        sorted_fps = sorted(fps_values)
        n = len(sorted_fps)
        if n >= 10:
            p1_idx = max(0, int(n * 0.99))
            result.one_percent_low = sorted_fps[p1_idx]
            p01_idx = max(0, int(n * 0.999))
            result.point_one_percent_low = sorted_fps[p01_idx]
        elif n > 0:
            result.one_percent_low = sorted_fps[-1]
            result.point_one_percent_low = sorted_fps[-1]

        # Spikes (frames longer than threshold)
        result.spike_count = sum(1 for ft in valid if ft > self._spike_threshold)
        result.long_frame_count = sum(1 for ft in valid if ft > self._spike_threshold * 2)

        # Stability score
        if result.avg_frame_time_ms > 0:
            cv = result.std_dev_ms / result.avg_frame_time_ms  # coefficient of variation
            result.stability_score = max(0, min(100, 100 - (cv * 200)))
        else:
            result.stability_score = 50

        # Stability rating
        if result.stability_score >= 85:
            result.stability = "EXCELLENT"
        elif result.stability_score >= 70:
            result.stability = "GOOD"
        elif result.stability_score >= 50:
            result.stability = "FAIR"
        elif result.stability_score >= 30:
            result.stability = "POOR"
        else:
            result.stability = "BAD"

        logger.debug(
            f"Frame pacing: {result.avg_fps:.1f} avg FPS, "
            f"1% low: {result.one_percent_low:.1f}, "
            f"spikes: {result.spike_count}, "
            f"stability: {result.stability}"
        )

        return result


# Singleton
frame_analyzer = FramePacingAnalyzer()
