"""
Performance scoring engine.
Calculates a weighted composite score from benchmark metrics.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("core.scoring")


@dataclass
class BenchmarkMetrics:
    """Raw benchmark metrics for scoring."""
    avg_fps: float = 0.0
    one_percent_low: float = 0.0
    point_one_percent_low: float = 0.0
    avg_frame_time_ms: float = 0.0
    frame_time_variance: float = 0.0
    frame_spikes: int = 0
    fps_drops: int = 0
    avg_gpu_util: float = 0.0
    duration_seconds: float = 0.0


@dataclass
class ScoreWeights:
    """Configurable scoring weights."""
    avg_fps: float = 0.40
    one_percent_low: float = 0.30
    point_one_percent_low: float = 0.20
    frame_stability: float = 0.10

    def normalize(self):
        total = self.avg_fps + self.one_percent_low + self.point_one_percent_low + self.frame_stability
        if total > 0:
            self.avg_fps /= total
            self.one_percent_low /= total
            self.point_one_percent_low /= total
            self.frame_stability /= total


@dataclass
class PerformanceScore:
    """Calculated performance score."""
    total_score: float = 0.0
    component_scores: dict = field(default_factory=dict)
    grade: str = "F"
    temperature_penalty: float = 0.0
    raw_metrics: Optional[BenchmarkMetrics] = None


class PerformanceScorer:
    """Calculates weighted performance scores."""

    def __init__(self, weights: Optional[ScoreWeights] = None):
        self._weights = weights or ScoreWeights()

    def calculate(self, metrics: BenchmarkMetrics,
                  cpu_temp: Optional[float] = None,
                  gpu_temp: Optional[float] = None,
                  thermal_throttling: bool = False) -> PerformanceScore:
        """
        Calculate composite performance score.

        Formula:
        Score = 0.40 × FPS_normalized + 0.30 × 1%Low_normalized +
                0.20 × 0.1%Low_normalized + 0.10 × FrameStability
        """
        result = PerformanceScore(raw_metrics=metrics)
        w = self._weights

        # Normalize FPS score (0-100 scale, where 120 FPS = 100)
        fps_score = min(100, (metrics.avg_fps / 120.0) * 100) if metrics.avg_fps > 0 else 0

        # Normalize 1% Low (0-100 scale, where 90 FPS = 100)
        one_low_score = min(100, (metrics.one_percent_low / 90.0) * 100) if metrics.one_percent_low > 0 else 0

        # Normalize 0.1% Low (0-100 scale, where 60 FPS = 100)
        point_one_low_score = min(100, (metrics.point_one_percent_low / 60.0) * 100) if metrics.point_one_percent_low > 0 else 0

        # Frame stability score (0-100, lower variance = higher score)
        if metrics.avg_frame_time_ms > 0:
            # Ideal: 16.67ms for 60fps. Lower variance = more stable
            cv = (metrics.frame_time_variance ** 0.5) / max(0.1, metrics.avg_frame_time_ms)  # Coefficient of variation
            stability_score = max(0, 100 - (cv * 200))  # CV of 0.5 = 0, CV of 0 = 100
        else:
            stability_score = 50  # Unknown

        # Component scores
        result.component_scores = {
            "avg_fps": fps_score,
            "one_percent_low": one_low_score,
            "point_one_percent_low": point_one_low_score,
            "frame_stability": stability_score,
        }

        # Weighted total
        total = (
            fps_score * w.avg_fps +
            one_low_score * w.one_percent_low +
            point_one_low_score * w.point_one_percent_low +
            stability_score * w.frame_stability
        )

        # Temperature penalty
        penalty = 0.0
        if thermal_throttling:
            penalty = 25.0
        elif gpu_temp is not None and gpu_temp > 85:
            penalty = max(penalty, 10.0)
        elif cpu_temp is not None and cpu_temp > 85:
            penalty = max(penalty, 8.0)

        result.temperature_penalty = penalty
        result.total_score = max(0, total - penalty)
        result.grade = self._grade(result.total_score)

        logger.info(f"Score: {result.total_score:.1f}/100 ({result.grade}) — Penalty: {penalty:.1f}")

        return result

    def calculate_delta(self, before: PerformanceScore, after: PerformanceScore) -> dict:
        """Calculate improvement metrics between two scores."""
        delta = {
            "score_change": after.total_score - before.total_score,
            "score_change_percent": (
                ((after.total_score - before.total_score) / max(0.1, before.total_score)) * 100
            ),
            "grade_before": before.grade,
            "grade_after": after.grade,
            "component_changes": {},
            "temperature_penalty_change": after.temperature_penalty - before.temperature_penalty,
        }

        for key in before.component_scores:
            before_val = before.component_scores.get(key, 0)
            after_val = after.component_scores.get(key, 0)
            delta["component_changes"][key] = {
                "before": before_val,
                "after": after_val,
                "change": after_val - before_val,
                "change_percent": ((after_val - before_val) / max(0.1, before_val)) * 100,
            }

        return delta

    def should_keep_change(self, before: PerformanceScore, after: PerformanceScore,
                           min_improvement: float = 1.0) -> tuple:
        """
        Determine whether an optimization change should be kept.

        Returns:
            (should_keep: bool, reason: str)
        """
        delta = self.calculate_delta(before, after)

        # Check overall score
        if delta["score_change"] >= min_improvement:
            return True, f"Performance score improved by {delta['score_change']:.1f} points"

        # Check if 1% low improved significantly even if average didn't
        one_low_change = delta["component_changes"].get("one_percent_low", {}).get("change_percent", 0)
        if one_low_change > 15:
            return True, f"1% low improved significantly ({one_low_change:+.1f}%), improving frame consistency"

        # Check if frame stability improved
        stability_change = delta["component_changes"].get("frame_stability", {}).get("change_percent", 0)
        if stability_change > 20 and delta["score_change"] > -2:
            return True, f"Frame stability improved significantly ({stability_change:+.1f}%)"

        # Check for regression
        if delta["score_change"] < -min_improvement:
            return False, f"Performance score decreased by {abs(delta['score_change']):.1f} points"

        # Neutral
        return False, "Change had negligible impact"

    def _grade(self, score: float) -> str:
        """Convert score to letter grade."""
        if score >= 90:
            return "S"
        elif score >= 80:
            return "A"
        elif score >= 70:
            return "B"
        elif score >= 60:
            return "C"
        elif score >= 50:
            return "D"
        elif score >= 30:
            return "E"
        else:
            return "F"


# Default scorer singleton
performance_scorer = PerformanceScorer()
