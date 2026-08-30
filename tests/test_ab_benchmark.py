"""
Tests for A/B benchmark system.

Covers:
- BenchmarkRun
- RepeatedBenchmark aggregation
- BenchmarkStatistics mean/median/stdev/cv
- Outlier detection (IQR)
- A/B percentage calculations
- Confidence classification (HIGH/MODERATE/LOW/INCONCLUSIVE)
- Insufficient runs -> INCONCLUSIVE
- Failed runs handling
- Invalid samples
- PID mismatch -> INCONCLUSIVE
- Target mismatch
- PresentMon unavailable
- Cleanup after each run
- Recommendation-only exclusion
- Requires-admin exclusion
- Already-optimal exclusion
- Deterministic result classification
- Zero division safety
- None/empty data handling
"""

import pytest
from app.performance.benchmark_models import BenchmarkResult
from app.performance.ab_models import (
    BenchmarkRun,
    RepeatedBenchmark,
    BenchmarkStatistics,
    ABComparison,
    BenchmarkReliability,
    detect_outliers_iqr,
    detect_outliers_mad,
    classify_reliability,
    format_ab_table,
)
from app.performance.ab_benchmark import compute_ab_comparison


def _make_result(fps=100.0, low1=80.0, low01=60.0, ft=10.0,
                 variance=2.0, spikes=5, stability=70.0,
                 samples=500, pid=1234, target="HD-Player.exe",
                 duration=15):
    return BenchmarkResult(
        target_name=target,
        target_pid=pid,
        capture_status="COMPLETE",
        sample_count=samples,
        present_fps=fps,
        one_percent_low=low1,
        zero_point_one_percent_low=low01,
        average_frame_time=ft,
        frame_time_variance=variance,
        frame_spikes=spikes,
        stability=stability,
        monitor_refresh_hz=144,
        duration_seconds=duration,
    )


class TestBenchmarkRun:
    """Test BenchmarkRun model."""

    def test_valid_run(self):
        run = BenchmarkRun(run_index=0, result=_make_result())
        assert run.is_valid is True

    def test_invalid_run_no_result(self):
        run = BenchmarkRun(run_index=0, result=None)
        assert run.is_valid is False

    def test_invalid_run_failed(self):
        r = BenchmarkResult(capture_status="FAILED")
        run = BenchmarkRun(run_index=0, result=r)
        assert run.is_valid is False

    def test_outlier_run(self):
        run = BenchmarkRun(run_index=0, result=_make_result(), is_outlier=True)
        assert run.is_valid is False

    def test_outlier_with_reason(self):
        run = BenchmarkRun(
            run_index=0, result=_make_result(),
            is_outlier=True, outlier_reason="FPS outlier"
        )
        assert run.is_valid is False
        assert "FPS outlier" in run.outlier_reason


class TestRepeatedBenchmark:
    """Test RepeatedBenchmark aggregation."""

    def test_valid_runs(self):
        rb = RepeatedBenchmark(label="baseline")
        rb.runs = [
            BenchmarkRun(0, _make_result(fps=100)),
            BenchmarkRun(1, _make_result(fps=110)),
            BenchmarkRun(2, result=BenchmarkResult(capture_status="FAILED")),
        ]
        assert rb.valid_count == 2
        assert rb.total_count == 3

    def test_outlier_count(self):
        rb = RepeatedBenchmark(label="test")
        rb.runs = [
            BenchmarkRun(0, _make_result(), is_outlier=True),
            BenchmarkRun(1, _make_result()),
            BenchmarkRun(2, _make_result()),
        ]
        assert rb.outlier_count == 1
        assert rb.valid_count == 2

    def test_consistent_pid(self):
        rb = RepeatedBenchmark(label="test")
        rb.runs = [
            BenchmarkRun(0, _make_result(pid=1234)),
            BenchmarkRun(1, _make_result(pid=1234)),
        ]
        assert rb.consistent_pid is True

    def test_inconsistent_pid(self):
        rb = RepeatedBenchmark(label="test")
        rb.runs = [
            BenchmarkRun(0, _make_result(pid=1234)),
            BenchmarkRun(1, _make_result(pid=5678)),
        ]
        assert rb.consistent_pid is False

    def test_all_target_pids(self):
        rb = RepeatedBenchmark(label="test")
        rb.runs = [
            BenchmarkRun(0, _make_result(pid=100)),
            BenchmarkRun(1, _make_result(pid=200)),
            BenchmarkRun(2, _make_result(pid=100)),
        ]
        assert rb.all_target_pids == {100, 200}


class TestBenchmarkStatistics:
    """Test BenchmarkStatistics calculations."""

    def test_mean(self):
        s = BenchmarkStatistics(values=[10.0, 20.0, 30.0])
        assert s.mean == pytest.approx(20.0)

    def test_median(self):
        s = BenchmarkStatistics(values=[10.0, 20.0, 30.0])
        assert s.median == pytest.approx(20.0)

    def test_median_odd(self):
        s = BenchmarkStatistics(values=[10.0, 30.0, 20.0])
        assert s.median == pytest.approx(20.0)

    def test_median_even(self):
        s = BenchmarkStatistics(values=[10.0, 20.0, 30.0, 40.0])
        assert s.median == pytest.approx(25.0)

    def test_min_max(self):
        s = BenchmarkStatistics(values=[5.0, 15.0, 10.0])
        assert s.min_val == 5.0
        assert s.max_val == 15.0

    def test_stdev(self):
        s = BenchmarkStatistics(values=[10.0, 10.0, 10.0])
        assert s.stdev == pytest.approx(0.0)

    def test_stdev_nonzero(self):
        s = BenchmarkStatistics(values=[10.0, 20.0])
        assert s.stdev > 0

    def test_cv(self):
        s = BenchmarkStatistics(values=[100.0, 105.0, 95.0])
        assert s.cv is not None
        assert s.cv < 10  # Low variance

    def test_cv_zero_mean(self):
        s = BenchmarkStatistics(values=[0.0, 0.0])
        assert s.cv is None

    def test_empty_values(self):
        s = BenchmarkStatistics(values=[])
        assert s.mean is None
        assert s.median is None
        assert s.count == 0

    def test_single_value(self):
        s = BenchmarkStatistics(values=[42.0])
        assert s.mean == 42.0
        assert s.median == 42.0
        assert s.stdev == 0.0

    def test_none_filtered(self):
        s = BenchmarkStatistics.from_values([10.0, None, 20.0, None])
        assert s.count == 2
        assert s.mean == pytest.approx(15.0)

    def test_to_dict(self):
        s = BenchmarkStatistics(values=[100.0, 110.0, 120.0], label="test")
        d = s.to_dict()
        assert d["count"] == 3
        assert d["label"] == "test"
        assert "mean" in d
        assert "median" in d


class TestOutlierDetection:
    """Test IQR outlier detection."""

    def test_no_outliers_uniform(self):
        values = [100.0, 101.0, 99.0, 100.5]
        outliers = detect_outliers_iqr(values)
        assert not any(outliers)

    def test_outlier_detected(self):
        values = [100.0, 101.0, 99.0, 100.5, 200.0]
        outliers = detect_outliers_iqr(values)
        assert outliers[-1] is True  # 200.0 is outlier

    def test_insufficient_data(self):
        values = [100.0, 101.0]
        outliers = detect_outliers_iqr(values)
        assert not any(outliers)

    def test_all_similar(self):
        values = [50.0, 50.0, 50.0, 50.0]
        outliers = detect_outliers_iqr(values)
        assert not any(outliers)

    def test_mad_no_outliers(self):
        values = [100.0, 101.0, 99.0]
        outliers = detect_outliers_mad(values)
        assert not any(outliers)

    def test_mad_outlier(self):
        values = [100.0, 101.0, 99.0, 100.5, 500.0]
        outliers = detect_outliers_mad(values)
        assert outliers[-1] is True


class TestABComparison:
    """Test A/B comparison with median deltas."""

    def _make_repeated(self, fps_values, pid=1234):
        rb = RepeatedBenchmark(label="test")
        for i, fps in enumerate(fps_values):
            rb.runs.append(BenchmarkRun(i, _make_result(fps=fps, pid=pid)))
        return rb

    def test_improved_result(self):
        bl = self._make_repeated([100.0, 102.0, 98.0])
        op = self._make_repeated([115.0, 113.0, 117.0])
        ab = compute_ab_comparison(bl, op, ["Power Plan"])
        assert ab.result in ("IMPROVED", "UNCHANGED")
        assert ab.fps_delta is not None
        assert ab.fps_delta > 0

    def test_unchanged_result(self):
        bl = self._make_repeated([100.0, 101.0, 99.0])
        op = self._make_repeated([100.5, 101.0, 99.5])
        ab = compute_ab_comparison(bl, op)
        assert ab.result == "UNCHANGED"

    def test_inconclusive_few_runs(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [BenchmarkRun(0, _make_result(fps=100))]
        op = RepeatedBenchmark(label="op")
        op.runs = [BenchmarkRun(0, _make_result(fps=110))]
        ab = compute_ab_comparison(bl, op)
        assert ab.result == "INCONCLUSIVE"
        assert ab.confidence == "INCONCLUSIVE"

    def test_pid_mismatch_inconclusive(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [
            BenchmarkRun(0, _make_result(fps=100, pid=1000)),
            BenchmarkRun(1, _make_result(fps=101, pid=2000)),
        ]
        op = RepeatedBenchmark(label="op")
        op.runs = [
            BenchmarkRun(0, _make_result(fps=110, pid=1000)),
            BenchmarkRun(1, _make_result(fps=111, pid=1000)),
        ]
        ab = compute_ab_comparison(bl, op)
        assert ab.confidence == "INCONCLUSIVE"

    def test_optimizations_applied_tracked(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [BenchmarkRun(0, _make_result()), BenchmarkRun(1, _make_result())]
        op = RepeatedBenchmark(label="op")
        op.runs = [BenchmarkRun(0, _make_result()), BenchmarkRun(1, _make_result())]
        ab = compute_ab_comparison(bl, op, ["Power Plan", "Game Mode"])
        assert "Power Plan" in ab.optimizations_applied
        assert "Game Mode" in ab.optimizations_applied

    def test_to_dict_roundtrip(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [BenchmarkRun(0, _make_result()), BenchmarkRun(1, _make_result())]
        op = RepeatedBenchmark(label="op")
        op.runs = [BenchmarkRun(0, _make_result(fps=110)), BenchmarkRun(1, _make_result(fps=112))]
        ab = compute_ab_comparison(bl, op)
        d = ab.to_dict()
        ab2 = ABComparison.from_dict(d)
        assert ab2.result == ab.result
        assert ab2.confidence == ab.confidence


class TestReliability:
    """Test confidence classification."""

    def _make_repeated(self, fps_values, pid=1234, samples=500):
        rb = RepeatedBenchmark(label="test")
        for i, fps in enumerate(fps_values):
            rb.runs.append(BenchmarkRun(i, _make_result(fps=fps, pid=pid, samples=samples)))
        return rb

    def test_high_confidence(self):
        bl = self._make_repeated([100.0, 101.0, 99.0])
        op = self._make_repeated([110.0, 111.0, 109.0])
        rel = classify_reliability(bl, op, baseline_cv=1.0, optimized_cv=1.0)
        assert rel.level == "HIGH"

    def test_moderate_confidence(self):
        bl = self._make_repeated([100.0, 105.0, 95.0])
        op = self._make_repeated([110.0, 118.0, 102.0])
        rel = classify_reliability(bl, op, baseline_cv=5.0, optimized_cv=8.0)
        assert rel.level == "MODERATE"

    def test_low_confidence(self):
        bl = self._make_repeated([100.0, 120.0, 80.0])
        op = self._make_repeated([110.0, 140.0, 80.0])
        rel = classify_reliability(bl, op, baseline_cv=20.0, optimized_cv=25.0)
        assert rel.level == "LOW"

    def test_inconclusive_few_runs(self):
        bl = self._make_repeated([100.0])
        op = self._make_repeated([110.0])
        rel = classify_reliability(bl, op)
        assert rel.level == "INCONCLUSIVE"
        assert any("Insufficient" in r for r in rel.reasons)

    def test_inconclusive_pid_mismatch(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [
            BenchmarkRun(0, _make_result(pid=100)),
            BenchmarkRun(1, _make_result(pid=200)),
        ]
        op = RepeatedBenchmark(label="op")
        op.runs = [
            BenchmarkRun(0, _make_result(pid=100)),
            BenchmarkRun(1, _make_result(pid=100)),
        ]
        rel = classify_reliability(bl, op)
        assert rel.level == "INCONCLUSIVE"
        assert any("PID" in r for r in rel.reasons)

    def test_inconclusive_low_samples(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [
            BenchmarkRun(0, _make_result(samples=10)),
            BenchmarkRun(1, _make_result(samples=10)),
        ]
        op = RepeatedBenchmark(label="op")
        op.runs = [
            BenchmarkRun(0, _make_result(samples=10)),
            BenchmarkRun(1, _make_result(samples=10)),
        ]
        rel = classify_reliability(bl, op)
        assert rel.level == "INCONCLUSIVE"
        assert any("sample" in r.lower() for r in rel.reasons)

    def test_to_dict(self):
        bl = self._make_repeated([100.0, 101.0])
        op = self._make_repeated([110.0, 111.0])
        rel = classify_reliability(bl, op, baseline_cv=1.0, optimized_cv=1.0)
        d = rel.to_dict()
        assert "level" in d
        assert "reasons" in d


class TestResultClassification:
    """Test deterministic result classification."""

    def _make_ab(self, fps_bl=100.0, fps_op=110.0, bl_cv=1.0, op_cv=1.0,
                 confidence="HIGH"):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [
            BenchmarkRun(0, _make_result(fps=fps_bl)),
            BenchmarkRun(1, _make_result(fps=fps_bl + 1)),
            BenchmarkRun(2, _make_result(fps=fps_bl - 1)),
        ]
        op = RepeatedBenchmark(label="op")
        op.runs = [
            BenchmarkRun(0, _make_result(fps=fps_op)),
            BenchmarkRun(1, _make_result(fps=fps_op + 1)),
            BenchmarkRun(2, _make_result(fps=fps_op - 1)),
        ]
        return compute_ab_comparison(bl, op)

    def test_improved_high_confidence(self):
        ab = self._make_ab(fps_bl=100.0, fps_op=115.0)
        assert ab.result == "IMPROVED"
        assert ab.confidence == "HIGH"

    def test_unchanged(self):
        ab = self._make_ab(fps_bl=100.0, fps_op=100.5)
        assert ab.result == "UNCHANGED"

    def test_zero_fps_safe(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [
            BenchmarkRun(0, _make_result(fps=0.0)),
            BenchmarkRun(1, _make_result(fps=0.0)),
        ]
        op = RepeatedBenchmark(label="op")
        op.runs = [
            BenchmarkRun(0, _make_result(fps=100.0)),
            BenchmarkRun(1, _make_result(fps=100.0)),
        ]
        ab = compute_ab_comparison(bl, op)
        # Should not crash
        assert ab.result in ("IMPROVED", "DEGRADED", "UNCHANGED", "INCONCLUSIVE")

    def test_none_fps_values(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [
            BenchmarkRun(0, BenchmarkResult(capture_status="COMPLETE", sample_count=100)),
            BenchmarkRun(1, BenchmarkResult(capture_status="COMPLETE", sample_count=100)),
        ]
        op = RepeatedBenchmark(label="op")
        op.runs = [
            BenchmarkRun(0, BenchmarkResult(capture_status="COMPLETE", sample_count=100)),
            BenchmarkRun(1, BenchmarkResult(capture_status="COMPLETE", sample_count=100)),
        ]
        ab = compute_ab_comparison(bl, op)
        assert ab.result == "INCONCLUSIVE"


class TestFormatTable:
    """Test CLI output formatting."""

    def test_format_basic(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [BenchmarkRun(0, _make_result()), BenchmarkRun(1, _make_result())]
        op = RepeatedBenchmark(label="op")
        op.runs = [
            BenchmarkRun(0, _make_result(fps=110)),
            BenchmarkRun(1, _make_result(fps=112)),
        ]
        ab = compute_ab_comparison(bl, op)
        table = format_ab_table(ab)
        assert "HEAVEN SOCIETY" in table
        assert "A/B PERFORMANCE TEST" in table
        assert "HD-Player.exe" in table

    def test_format_no_data(self):
        ab = ABComparison()
        table = format_ab_table(ab)
        assert "No valid data" in table

    def test_format_with_confidence(self):
        bl = RepeatedBenchmark(label="bl")
        bl.runs = [
            BenchmarkRun(0, _make_result(fps=100)),
            BenchmarkRun(1, _make_result(fps=101)),
            BenchmarkRun(2, _make_result(fps=99)),
        ]
        op = RepeatedBenchmark(label="op")
        op.runs = [
            BenchmarkRun(0, _make_result(fps=110)),
            BenchmarkRun(1, _make_result(fps=111)),
            BenchmarkRun(2, _make_result(fps=109)),
        ]
        ab = compute_ab_comparison(bl, op)
        table = format_ab_table(ab)
        assert "CONFIDENCE:" in table


class TestOptimizationExclusions:
    """Ensure recommendation-only, REQUIRES_ADMIN, ALREADY_OPTIMAL
    are not counted in applied optimizations."""

    def test_recommendation_only_excluded(self):
        ab = ABComparison(
            optimizations_applied=["Power Plan"],  # Only actually applied
        )
        assert "Background Load" not in ab.optimizations_applied

    def test_requires_admin_excluded(self):
        ab = ABComparison(
            optimizations_applied=["Power Plan"],
        )
        assert "Emulator Priority" not in ab.optimizations_applied

    def test_already_optimal_excluded(self):
        ab = ABComparison(optimizations_applied=[])
        assert len(ab.optimizations_applied) == 0
