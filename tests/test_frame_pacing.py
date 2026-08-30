"""
Tests for Heaven Society — Frame Pacing Analysis.

All tests use mock FrameSample data; never runs real PresentMon captures.
"""

import os
import sys
import math
import statistics
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.performance.frame_pacing import (
    FramePacingAnalyzer,
    FramePacingResult,
    PacingClassification,
    PacingPattern,
    PercentileFrameTimes,
    frame_pacing_analyzer,
)
from app.performance.fps_provider import FrameSample


# ══════════════════════════════════════════════════════════════
# Helpers
# ══════════════════════════════════════════════════════════════

def make_samples(
    count: int = 100,
    base_ft: float = 16.67,
    jitter: float = 2.0,
    spike_every: int = 0,
    spike_multiplier: float = 3.0,
    cpu_ms: float = 0.0,
    gpu_ms: float = 0.0,
) -> list:
    """Create mock FrameSample list with controllable characteristics."""
    samples = []
    for i in range(count):
        ft = base_ft
        if jitter > 0:
            import random
            random.seed(i)
            ft += random.uniform(-jitter, jitter)
        if spike_every > 0 and i % spike_every == 0 and i > 0:
            ft *= spike_multiplier
        ft = max(1.0, ft)

        s = FrameSample(
            timestamp=float(i) * ft / 1000.0,
            frame_time_ms=ft,
            process_name="HD-Player.exe",
            pid=1234,
            cpu_ms=cpu_ms if cpu_ms > 0 else ft * 0.4,
            gpu_ms=gpu_ms if gpu_ms > 0 else ft * 0.5,
        )
        samples.append(s)
    return samples


def make_stable_samples(count=100, fps=60):
    """Create perfectly stable frame samples."""
    ft = 1000.0 / fps
    return make_samples(count=count, base_ft=ft, jitter=0.5, spike_every=0)


def make_unstable_samples(count=100):
    """Create highly unstable frame samples."""
    return make_samples(count=count, base_ft=16.67, jitter=10.0, spike_every=5, spike_multiplier=4.0)


# ══════════════════════════════════════════════════════════════
# 1. Data Models
# ══════════════════════════════════════════════════════════════

class TestModels:
    """Test data model defaults and properties."""

    def test_pacing_result_defaults(self):
        r = FramePacingResult()
        assert r.sample_count == 0
        assert r.pacing_score == 0.0
        assert r.classification == PacingClassification.INSUFFICIENT_DATA
        assert r.is_measured is True

    def test_pacing_result_is_valid(self):
        r = FramePacingResult(sample_count=5, is_measured=True)
        assert not r.is_valid  # Need >= 10

        r2 = FramePacingResult(sample_count=100, is_measured=True)
        assert r2.is_valid

    def test_percentile_iqr(self):
        p = PercentileFrameTimes(p25=10, p75=20)
        assert p.interquartile_range == 10

    def test_classification_values(self):
        values = [c.value for c in PacingClassification]
        assert "EXCELLENT" in values
        assert "GOOD" in values
        assert "FAIR" in values
        assert "POOR" in values
        assert "CRITICAL" in values
        assert "INSUFFICIENT DATA" in values

    def test_pattern_values(self):
        values = [p.value for p in PacingPattern]
        assert "CPU Bound" in values
        assert "GPU Bound" in values
        assert "Emulator Scheduling" in values
        assert "Background Interference" in values
        assert "Thermal Throttling" in values
        assert "Inconsistent Pacing" in values
        assert "No Issue Detected" in values

    def test_to_dict(self):
        r = FramePacingResult(
            sample_count=100, avg_fps=60.0,
            pacing_score=75.0,
            classification=PacingClassification.GOOD,
        )
        d = r.to_dict()
        assert d["sample_count"] == 100
        assert d["avg_fps"] == 60.0
        assert d["classification"] == "GOOD"


# ══════════════════════════════════════════════════════════════
# 2. Basic Metrics
# ══════════════════════════════════════════════════════════════

class TestBasicMetrics:
    """Test basic FPS and frame time metrics from real data."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_60fps_stable(self):
        samples = make_stable_samples(count=100, fps=60)
        result = self.analyzer.analyze(samples)
        assert result.sample_count == 100
        assert 55 < result.avg_fps < 65
        assert 55 < result.median_fps < 65
        assert result.avg_frame_time_ms > 14
        assert result.avg_frame_time_ms < 20

    def test_144fps_stable(self):
        samples = make_stable_samples(count=100, fps=144)
        result = self.analyzer.analyze(samples)
        assert 135 < result.avg_fps < 155

    def test_min_max_fps(self):
        samples = make_samples(count=100, base_ft=16.67, jitter=5.0)
        result = self.analyzer.analyze(samples)
        assert result.min_fps < result.avg_fps < result.max_fps

    def test_one_percent_low(self):
        samples = make_unstable_samples(count=500)
        result = self.analyzer.analyze(samples)
        assert result.one_percent_low <= result.avg_fps
        assert result.point_one_percent_low <= result.one_percent_low


# ══════════════════════════════════════════════════════════════
# 3. Distribution Metrics
# ══════════════════════════════════════════════════════════════

class TestDistributionMetrics:
    """Test standard deviation and coefficient of variation."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_stable_low_cv(self):
        samples = make_stable_samples(count=100, fps=60)
        result = self.analyzer.analyze(samples)
        assert result.frame_time_stdev < 2.0
        assert result.coefficient_of_variation < 0.1

    def test_unstable_high_cv(self):
        samples = make_unstable_samples(count=100)
        result = self.analyzer.analyze(samples)
        assert result.coefficient_of_variation > 0.15

    def test_cv_is_dimensionless(self):
        samples = make_stable_samples(count=100)
        result = self.analyzer.analyze(samples)
        # CV = stdev / mean, should be dimensionless
        assert 0 <= result.coefficient_of_variation < 10


# ══════════════════════════════════════════════════════════════
# 4. Percentiles
# ══════════════════════════════════════════════════════════════

class TestPercentiles:
    """Test frame time percentile computation."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_percentiles_ordered(self):
        samples = make_stable_samples(count=100)
        result = self.analyzer.analyze(samples)
        p = result.percentiles
        assert p.p1 >= 0
        assert p.p1 <= p.p5 <= p.p10 <= p.p25 <= p.p50 <= p.p75 <= p.p90 <= p.p95 <= p.p99

    def test_percentiles_nonzero(self):
        samples = make_stable_samples(count=100)
        result = self.analyzer.analyze(samples)
        assert result.percentiles.p50 > 0
        assert result.percentiles.p99 > 0

    def test_iqr_positive(self):
        samples = make_stable_samples(count=100)
        result = self.analyzer.analyze(samples)
        assert result.percentiles.interquartile_range >= 0


# ══════════════════════════════════════════════════════════════
# 5. Spike / Stutter Metrics
# ══════════════════════════════════════════════════════════════

class TestSpikeMetrics:
    """Test frame spike and stutter detection."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_stable_few_spikes(self):
        samples = make_stable_samples(count=100, fps=60)
        result = self.analyzer.analyze(samples)
        assert result.frame_spikes < 5
        assert result.long_frame_count == 0

    def test_unstable_many_spikes(self):
        samples = make_unstable_samples(count=100)
        result = self.analyzer.analyze(samples)
        assert result.frame_spikes > 0
        assert result.micro_stutters > 0

    def test_long_frame_percent(self):
        samples = make_unstable_samples(count=200)
        result = self.analyzer.analyze(samples)
        assert result.long_frame_percent >= 0
        assert result.long_frame_percent <= 100

    def test_consecutive_stutters(self):
        samples = make_samples(
            count=100, base_ft=16.67, jitter=0.5,
            spike_every=0, spike_multiplier=1,
        )
        # Add a burst of spikes
        for i in range(50, 55):
            samples[i].frame_time_ms = 100.0
        result = self.analyzer.analyze(samples)
        assert result.consecutive_stutters >= 4


# ══════════════════════════════════════════════════════════════
# 6. Pacing Score
# ══════════════════════════════════════════════════════════════

class TestPacingScore:
    """Test pacing score calculation."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_stable_high_score(self):
        samples = make_stable_samples(count=200, fps=60)
        result = self.analyzer.analyze(samples)
        assert result.pacing_score >= 70

    def test_unstable_low_score(self):
        samples = make_unstable_samples(count=200)
        result = self.analyzer.analyze(samples)
        assert result.pacing_score < 60

    def test_score_bounded(self):
        samples = make_stable_samples(count=100)
        result = self.analyzer.analyze(samples)
        assert 0 <= result.pacing_score <= 100

    def test_insufficient_data_zero_score(self):
        result = self.analyzer.analyze([])
        assert result.pacing_score == 0.0
        assert result.classification == PacingClassification.INSUFFICIENT_DATA


# ══════════════════════════════════════════════════════════════
# 7. Classification
# ══════════════════════════════════════════════════════════════

class TestClassification:
    """Test pacing classification."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_excellent(self):
        assert self.analyzer._classify_pacing(90) == PacingClassification.EXCELLENT

    def test_good(self):
        assert self.analyzer._classify_pacing(75) == PacingClassification.GOOD

    def test_fair(self):
        assert self.analyzer._classify_pacing(55) == PacingClassification.FAIR

    def test_poor(self):
        assert self.analyzer._classify_pacing(35) == PacingClassification.POOR

    def test_critical(self):
        assert self.analyzer._classify_pacing(15) == PacingClassification.CRITICAL

    def test_insufficient(self):
        assert self.analyzer._classify_pacing(0) == PacingClassification.INSUFFICIENT_DATA


# ══════════════════════════════════════════════════════════════
# 8. Pattern Detection
# ══════════════════════════════════════════════════════════════

class TestPatternDetection:
    """Test frame pacing pattern detection."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_cpu_bound_detection(self):
        samples = make_samples(
            count=100, base_ft=16.67, jitter=1.0,
            cpu_ms=15.0, gpu_ms=3.0,
        )
        result = self.analyzer.analyze(samples)
        # CPU busy 15ms / frame 16.67ms = 90% → CPU bound
        assert PacingPattern.CPU_BOUND in result.detected_patterns

    def test_gpu_bound_detection(self):
        samples = make_samples(
            count=100, base_ft=16.67, jitter=1.0,
            cpu_ms=3.0, gpu_ms=15.0,
        )
        result = self.analyzer.analyze(samples)
        assert PacingPattern.GPU_BOUND in result.detected_patterns

    def test_no_issue_stable(self):
        samples = make_stable_samples(count=200, fps=60)
        result = self.analyzer.analyze(samples)
        # Stable samples should have no major issues
        assert PacingPattern.NO_ISSUE in result.detected_patterns or \
               len(result.detected_patterns) <= 1

    def test_inconsistent_pacing(self):
        samples = make_unstable_samples(count=200)
        result = self.analyzer.analyze(samples)
        # High CV should trigger inconsistent pacing
        assert PacingPattern.INCONSISTENT_PACING in result.detected_patterns or \
               result.coefficient_of_variation > 0.2

    def test_patterns_have_descriptions(self):
        samples = make_samples(
            count=100, base_ft=16.67, jitter=1.0,
            cpu_ms=15.0, gpu_ms=3.0,
        )
        result = self.analyzer.analyze(samples)
        for pat in result.detected_patterns:
            if pat != PacingPattern.NO_ISSUE:
                assert pat.value in result.pattern_descriptions

    def test_confidence_bounded(self):
        samples = make_unstable_samples(count=200)
        result = self.analyzer.analyze(samples)
        for pat, conf in result.pattern_confidences.items():
            assert 0 <= conf <= 1.0


# ══════════════════════════════════════════════════════════════
# 9. Recommendations
# ══════════════════════════════════════════════════════════════

class TestRecommendations:
    """Test recommendation generation."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_cpu_bound_recommendation(self):
        samples = make_samples(
            count=100, base_ft=16.67, jitter=1.0,
            cpu_ms=15.0, gpu_ms=3.0,
        )
        result = self.analyzer.analyze(samples)
        if PacingPattern.CPU_BOUND in result.detected_patterns:
            assert any("cpu" in r.lower() for r in result.recommendations)

    def test_no_recommendations_stable(self):
        samples = make_stable_samples(count=200, fps=60)
        result = self.analyzer.analyze(samples)
        # Stable samples should have few/no recommendations
        assert len(result.recommendations) <= 2

    def test_invalid_no_recommendations(self):
        result = self.analyzer.analyze([])
        assert len(result.recommendations) == 0


# ══════════════════════════════════════════════════════════════
# 10. Edge Cases
# ══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_empty_samples(self):
        result = self.analyzer.analyze([])
        assert result.sample_count == 0
        assert result.pacing_score == 0.0

    def test_too_few_samples(self):
        samples = make_samples(count=5)
        result = self.analyzer.analyze(samples)
        assert result.sample_count < 10
        assert not result.is_valid

    def test_single_sample(self):
        samples = [FrameSample(timestamp=0.0, frame_time_ms=16.67)]
        result = self.analyzer.analyze(samples)
        assert result.sample_count == 1

    def test_all_zero_frame_times(self):
        samples = [FrameSample(timestamp=0.0, frame_time_ms=0.0) for _ in range(20)]
        result = self.analyzer.analyze(samples)
        assert result.sample_count == 0 or not result.is_valid

    def test_very_high_fps(self):
        samples = make_stable_samples(count=100, fps=500)
        result = self.analyzer.analyze(samples)
        assert result.avg_fps > 400

    def test_very_low_fps(self):
        samples = make_stable_samples(count=10, fps=10)
        result = self.analyzer.analyze(samples)
        assert 8 < result.avg_fps < 12


# ══════════════════════════════════════════════════════════════
# 11. GPU/CPU Timing
# ══════════════════════════════════════════════════════════════

class TestGPUTiming:
    """Test GPU/CPU timing extraction."""

    def setup_method(self):
        self.analyzer = FramePacingAnalyzer()

    def test_gpu_cpu_timing(self):
        samples = make_samples(
            count=100, base_ft=16.67, jitter=1.0,
            cpu_ms=8.0, gpu_ms=10.0,
        )
        result = self.analyzer.analyze(samples)
        assert result.avg_gpu_busy_ms > 0
        assert result.avg_cpu_busy_ms > 0

    def test_no_gpu_data(self):
        samples = make_stable_samples(count=100)
        result = self.analyzer.analyze(samples)
        # Default cpu_ms/gpu_ms are proportional to frame time
        assert result.avg_cpu_busy_ms > 0


# ══════════════════════════════════════════════════════════════
# 12. Safety Rules
# ══════════════════════════════════════════════════════════════

class TestSafety:
    """Test safety rules."""

    def test_analyzer_is_read_only(self):
        import inspect
        source = inspect.getsource(FramePacingAnalyzer)
        assert "os.remove" not in source
        assert ".kill()" not in source
        assert "winreg" not in source

    def test_no_fake_data(self):
        """All values come from input samples."""
        samples = make_stable_samples(count=100, fps=60)
        result = frame_pacing_analyzer.analyze(samples)
        assert result.sample_count == 100
        assert 55 < result.avg_fps < 65  # Real computation from samples


# ══════════════════════════════════════════════════════════════
# 13. Singleton
# ══════════════════════════════════════════════════════════════

class TestSingleton:
    """Test singleton."""

    def test_singleton_exists(self):
        assert frame_pacing_analyzer is not None
        assert isinstance(frame_pacing_analyzer, FramePacingAnalyzer)

    def test_singleton_is_same(self):
        from app.performance.frame_pacing import frame_pacing_analyzer as fpa2
        assert frame_pacing_analyzer is fpa2
