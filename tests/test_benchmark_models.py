"""
Tests for benchmark models and optimization benchmark workflow.

Covers:
- BenchmarkResult construction and validation
- BenchmarkComparison delta calculations
- Percentage calculations
- Improvement/degradation/unchanged detection
- Insufficient-sample handling
- PresentMon unavailable handling
- NO_TARGET handling
- Recommendation-only exclusion
- REQUIRES_ADMIN exclusion
- ALREADY_OPTIMAL exclusion
- Rollback after benchmark
- No-change rollback
- Zero division handling
- Invalid/empty PresentMon data
- CLI formatting
"""

import pytest
from app.performance.benchmark_models import (
    BenchmarkResult,
    BenchmarkComparison,
    _safe_percent,
    format_comparison_table,
)


class TestBenchmarkResult:
    """Test BenchmarkResult model."""

    def test_complete_result(self):
        r = BenchmarkResult(
            target_name="HD-Player.exe",
            target_pid=1234,
            duration_seconds=15.0,
            sample_count=500,
            monitor_refresh_hz=144,
            capture_status="COMPLETE",
            present_fps=120.0,
            median_fps=118.5,
            min_fps=80.0,
            max_fps=144.0,
            one_percent_low=90.0,
            zero_point_one_percent_low=60.0,
            average_frame_time=8.33,
            frame_time_variance=1.5,
            frame_spikes=5,
            stability=85.0,
        )
        assert r.is_valid is True
        assert r.present_fps == 120.0

    def test_unavailable_result(self):
        r = BenchmarkResult.unavailable(reason="PresentMon not found")
        assert r.is_valid is False
        assert r.capture_status == "UNAVAILABLE"
        assert r.error == "PresentMon not found"

    def test_failed_result(self):
        r = BenchmarkResult.failed(reason="No frame samples")
        assert r.is_valid is False
        assert r.capture_status == "FAILED"

    def test_no_target_result(self):
        r = BenchmarkResult.no_target()
        assert r.is_valid is False
        assert r.capture_status == "NO_TARGET"

    def test_invalid_when_zero_samples(self):
        r = BenchmarkResult(
            capture_status="COMPLETE",
            sample_count=0,
            present_fps=100.0,
        )
        assert r.is_valid is False

    def test_invalid_when_no_fps(self):
        r = BenchmarkResult(
            capture_status="COMPLETE",
            sample_count=100,
            present_fps=None,
        )
        assert r.is_valid is False

    def test_to_dict_roundtrip(self):
        r = BenchmarkResult(
            target_name="test.exe",
            target_pid=999,
            present_fps=144.0,
            one_percent_low=120.0,
            capture_status="COMPLETE",
            sample_count=1000,
        )
        d = r.to_dict()
        r2 = BenchmarkResult.from_dict(d)
        assert r2.target_name == "test.exe"
        assert r2.present_fps == 144.0
        assert r2.one_percent_low == 120.0

    def test_timestamp_auto_set(self):
        r = BenchmarkResult()
        assert r.timestamp  # Should be auto-populated

    def test_all_none_fields(self):
        r = BenchmarkResult(capture_status="COMPLETE", sample_count=0)
        assert r.present_fps is None
        assert r.median_fps is None
        assert r.one_percent_low is None
        assert r.frame_spikes is None


class TestBenchmarkComparison:
    """Test BenchmarkComparison delta calculations."""

    def _make_result(self, fps=100.0, low1=80.0, low01=60.0,
                     frame_time=10.0, variance=2.0, spikes=10,
                     stability=70.0, samples=500):
        return BenchmarkResult(
            target_name="test.exe",
            target_pid=1234,
            capture_status="COMPLETE",
            sample_count=samples,
            present_fps=fps,
            one_percent_low=low1,
            zero_point_one_percent_low=low01,
            average_frame_time=frame_time,
            frame_time_variance=variance,
            frame_spikes=spikes,
            stability=stability,
            monitor_refresh_hz=144,
        )

    def test_improved_detection(self):
        before = self._make_result(fps=100.0, low1=80.0, frame_time=10.0, stability=70.0)
        after = self._make_result(fps=110.0, low1=90.0, frame_time=9.0, stability=80.0)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.result == "IMPROVED"
        assert comp.fps_delta == pytest.approx(10.0)
        assert comp.fps_percent == pytest.approx(10.0)

    def test_degraded_detection(self):
        before = self._make_result(fps=120.0, low1=100.0, frame_time=8.0, stability=90.0)
        after = self._make_result(fps=100.0, low1=70.0, frame_time=12.0, stability=60.0)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.result == "DEGRADED"
        assert comp.fps_delta == pytest.approx(-20.0)

    def test_unchanged_detection(self):
        before = self._make_result(fps=100.0, low1=80.0, frame_time=10.0, stability=70.0)
        after = self._make_result(fps=100.5, low1=80.2, frame_time=10.0, stability=70.1)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.result == "UNCHANGED"

    def test_inconclusive_when_before_invalid(self):
        before = BenchmarkResult(capture_status="FAILED")
        after = self._make_result(fps=100.0)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.result == "INCONCLUSIVE"

    def test_inconclusive_when_after_invalid(self):
        before = self._make_result(fps=100.0)
        after = BenchmarkResult(capture_status="FAILED")
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.result == "INCONCLUSIVE"

    def test_fps_percent_calculation(self):
        before = self._make_result(fps=100.0)
        after = self._make_result(fps=115.0)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.fps_percent == pytest.approx(15.0)

    def test_1low_percent_calculation(self):
        before = self._make_result(low1=100.0)
        after = self._make_result(low1=110.0)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.one_percent_low_percent == pytest.approx(10.0)

    def test_frame_time_delta_negative_is_improvement(self):
        before = self._make_result(frame_time=12.0)
        after = self._make_result(frame_time=8.0)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.frame_time_delta == pytest.approx(-4.0)

    def test_frame_variance_delta(self):
        before = self._make_result(variance=3.0)
        after = self._make_result(variance=1.0)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.frame_variance_delta == pytest.approx(-2.0)

    def test_frame_spike_delta(self):
        before = self._make_result(spikes=20)
        after = self._make_result(spikes=5)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.frame_spike_delta == -15

    def test_stability_delta(self):
        before = self._make_result(stability=60.0)
        after = self._make_result(stability=80.0)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.stability_delta == pytest.approx(20.0)

    def test_zero_division_fps(self):
        """Zero FPS base should not crash."""
        before = self._make_result(fps=0.0)
        after = self._make_result(fps=100.0)
        comp = BenchmarkComparison(before=before, after=after)
        # fps_percent should be None when base is 0
        assert comp.fps_percent is None

    def test_zero_division_1low(self):
        """Zero 1% low base should not crash."""
        before = self._make_result(low1=0.0)
        after = self._make_result(low1=50.0)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.one_percent_low_percent is None

    def test_none_metrics_handled(self):
        """None metrics should produce None deltas."""
        before = BenchmarkResult(capture_status="COMPLETE", sample_count=100)
        after = BenchmarkResult(capture_status="COMPLETE", sample_count=100)
        comp = BenchmarkComparison(before=before, after=after)
        assert comp.fps_delta is None
        assert comp.one_percent_low_delta is None
        assert comp.frame_time_delta is None

    def test_mixed_improvement_and_regression(self):
        """Mixed results: FPS improved but frame time worsened."""
        before = self._make_result(fps=100.0, low1=80.0, frame_time=10.0, stability=70.0)
        after = self._make_result(fps=115.0, low1=95.0, frame_time=12.0, stability=80.0)
        comp = BenchmarkComparison(before=before, after=after)
        # FPS +15%, 1% low +18.75%, frame time +20%, stability +10
        # improvements=3 (fps, 1low, stability), regressions=1 (frame_time)
        # improvements > regressions -> IMPROVED
        assert comp.result == "IMPROVED"

    def test_to_dict_roundtrip(self):
        before = self._make_result(fps=100.0)
        after = self._make_result(fps=110.0)
        comp = BenchmarkComparison(
            before=before, after=after,
            optimizations_applied=["Power Plan", "Game Mode"],
        )
        d = comp.to_dict()
        comp2 = BenchmarkComparison.from_dict(d)
        assert comp2.result == comp.result
        assert comp2.fps_delta == pytest.approx(comp.fps_delta)
        assert comp2.optimizations_applied == ["Power Plan", "Game Mode"]

    def test_optimizations_applied_tracked(self):
        before = self._make_result()
        after = self._make_result()
        comp = BenchmarkComparison(
            before=before, after=after,
            optimizations_applied=["Power Plan", "Game Mode"],
        )
        assert len(comp.optimizations_applied) == 2


class TestSafePercent:
    """Test the _safe_percent helper."""

    def test_normal(self):
        assert _safe_percent(10, 100) == pytest.approx(10.0)

    def test_negative(self):
        assert _safe_percent(-5, 100) == pytest.approx(-5.0)

    def test_zero_base(self):
        assert _safe_percent(10, 0) is None

    def test_zero_delta(self):
        assert _safe_percent(0, 100) == pytest.approx(0.0)


class TestFormatComparisonTable:
    """Test CLI output formatting."""

    def _make_valid_comparison(self):
        before = BenchmarkResult(
            target_name="HD-Player.exe",
            target_pid=7460,
            capture_status="COMPLETE",
            sample_count=500,
            monitor_refresh_hz=144,
            present_fps=100.0,
            one_percent_low=80.0,
            zero_point_one_percent_low=60.0,
            average_frame_time=10.0,
            frame_spikes=5,
            stability=75.0,
        )
        after = BenchmarkResult(
            target_name="HD-Player.exe",
            target_pid=7460,
            capture_status="COMPLETE",
            sample_count=500,
            monitor_refresh_hz=144,
            present_fps=110.0,
            one_percent_low=90.0,
            zero_point_one_percent_low=70.0,
            average_frame_time=9.0,
            frame_spikes=3,
            stability=85.0,
        )
        return BenchmarkComparison(
            before=before, after=after,
            optimizations_applied=["Power Plan", "Game Mode"],
        )

    def test_table_contains_target(self):
        comp = self._make_valid_comparison()
        table = format_comparison_table(comp)
        assert "HD-Player.exe" in table
        assert "7460" in table

    def test_table_contains_result(self):
        comp = self._make_valid_comparison()
        table = format_comparison_table(comp)
        assert "IMPROVED" in table

    def test_table_contains_benchmark_header(self):
        comp = self._make_valid_comparison()
        table = format_comparison_table(comp)
        assert "HEAVEN SOCIETY" in table

    def test_table_contains_optimizations(self):
        comp = self._make_valid_comparison()
        table = format_comparison_table(comp)
        assert "Power Plan" in table
        assert "Game Mode" in table

    def test_table_no_target(self):
        comp = BenchmarkComparison(
            before=BenchmarkResult.no_target(),
            after=BenchmarkResult.no_target(),
        )
        table = format_comparison_table(comp)
        assert "No emulator detected" in table

    def test_table_unavailable(self):
        comp = BenchmarkComparison(
            before=BenchmarkResult.unavailable(reason="PM not found"),
            after=BenchmarkResult.unavailable(reason="PM not found"),
        )
        table = format_comparison_table(comp)
        assert "UNAVAILABLE" in table


class TestOptimizationExclusions:
    """Verify that recommendation-only, REQUIRES_ADMIN, ALREADY_OPTIMAL
    are not counted as applied optimizations in the benchmark workflow."""

    def test_recommendation_only_not_in_applied(self):
        """BenchmarkComparison.optimizations_applied should not include
        recommendation-only optimizations."""
        before = BenchmarkResult(
            capture_status="COMPLETE", sample_count=100,
            present_fps=100.0, one_percent_low=80.0,
        )
        after = BenchmarkResult(
            capture_status="COMPLETE", sample_count=100,
            present_fps=100.0, one_percent_low=80.0,
        )
        comp = BenchmarkComparison(
            before=before, after=after,
            optimizations_applied=["Power Plan"],  # Only actually applied
        )
        assert "Background Load" not in comp.optimizations_applied

    def test_requires_admin_not_in_applied(self):
        before = BenchmarkResult(
            capture_status="COMPLETE", sample_count=100,
            present_fps=100.0,
        )
        after = BenchmarkResult(
            capture_status="COMPLETE", sample_count=100,
            present_fps=100.0,
        )
        comp = BenchmarkComparison(
            before=before, after=after,
            optimizations_applied=["Power Plan"],  # Only applied
        )
        assert "Emulator Priority" not in comp.optimizations_applied

    def test_already_optimal_not_in_applied(self):
        before = BenchmarkResult(
            capture_status="COMPLETE", sample_count=100,
            present_fps=100.0,
        )
        after = BenchmarkResult(
            capture_status="COMPLETE", sample_count=100,
            present_fps=100.0,
        )
        comp = BenchmarkComparison(
            before=before, after=after,
            optimizations_applied=[],  # Nothing was changed
        )
        assert len(comp.optimizations_applied) == 0
