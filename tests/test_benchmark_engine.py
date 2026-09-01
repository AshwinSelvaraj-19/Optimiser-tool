"""
Phase 55 — Comprehensive tests for Benchmark and Validation Engine.

Tests:
- BenchmarkMetric (create, comparison, display, serialization)
- BenchmarkSnapshot (create, serialization)
- BenchmarkSession (verdict, serialization)
- ComparisonEngine (compare two snapshots)
- BenchmarkEngine (capture, run, save, export, format)
- CLI commands
- Edge cases
"""
import os
import sys
import time
import json
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from app.performance.benchmark_engine import (
    BenchmarkType,
    MetricStatus,
    ChangeDirection,
    BenchmarkMetric,
    BenchmarkSnapshot,
    BenchmarkSession,
    ComparisonEngine,
    BenchmarkEngine,
    benchmark_engine,
)


# ══════════════════════════════════════════════════════════════════
# 1. Enums
# ══════════════════════════════════════════════════════════════════

class TestEnums:
    def test_benchmark_type(self):
        assert BenchmarkType.QUICK.value == "QUICK"
        assert BenchmarkType.GAMING.value == "GAMING"
        assert BenchmarkType.SYSTEM.value == "SYSTEM"

    def test_metric_status(self):
        assert MetricStatus.MEASURED.value == "MEASURED"
        assert MetricStatus.NOT_AVAILABLE.value == "NOT_AVAILABLE"
        assert MetricStatus.FAILED.value == "FAILED"

    def test_change_direction(self):
        assert ChangeDirection.IMPROVED.value == "IMPROVED"
        assert ChangeDirection.DEGRADED.value == "DEGRADED"
        assert ChangeDirection.UNCHANGED.value == "UNCHANGED"
        assert ChangeDirection.UNKNOWN.value == "UNKNOWN"


# ══════════════════════════════════════════════════════════════════
# 2. BenchmarkMetric
# ══════════════════════════════════════════════════════════════════

class TestBenchmarkMetric:
    def test_create(self):
        m = BenchmarkMetric(name="CPU", category="CPU", unit="%")
        assert m.name == "CPU"
        assert m.before_value is None
        assert m.after_value is None

    def test_improvement_higher_better(self):
        m = BenchmarkMetric(
            name="FPS", before_value=80.0, after_value=100.0,
            higher_is_better=True,
        )
        m.compute_comparison()
        assert m.delta == 20.0
        assert m.percent_change == pytest.approx(25.0, abs=0.1)
        assert m.direction == ChangeDirection.IMPROVED

    def test_degradation_higher_better(self):
        m = BenchmarkMetric(
            name="FPS", before_value=100.0, after_value=80.0,
            higher_is_better=True,
        )
        m.compute_comparison()
        assert m.delta == -20.0
        assert m.direction == ChangeDirection.DEGRADED

    def test_improvement_lower_better(self):
        m = BenchmarkMetric(
            name="Frame Time", before_value=16.0, after_value=12.0,
            unit="ms", higher_is_better=False,
        )
        m.compute_comparison()
        assert m.delta == -4.0
        assert m.direction == ChangeDirection.IMPROVED

    def test_degradation_lower_better(self):
        m = BenchmarkMetric(
            name="Temperature", before_value=65.0, after_value=80.0,
            unit="°C", higher_is_better=False,
        )
        m.compute_comparison()
        assert m.delta == 15.0
        assert m.direction == ChangeDirection.DEGRADED

    def test_unchanged(self):
        m = BenchmarkMetric(
            name="CPU", before_value=50.0, after_value=50.0,
        )
        m.compute_comparison()
        assert m.direction == ChangeDirection.UNCHANGED

    def test_missing_before(self):
        m = BenchmarkMetric(name="FPS", after_value=90.0)
        m.compute_comparison()
        assert m.direction == ChangeDirection.UNKNOWN
        assert m.delta is None

    def test_missing_after(self):
        m = BenchmarkMetric(name="FPS", before_value=90.0)
        m.compute_comparison()
        assert m.direction == ChangeDirection.UNKNOWN

    def test_zero_before(self):
        m = BenchmarkMetric(
            name="FPS", before_value=0.0, after_value=10.0,
        )
        m.compute_comparison()
        assert m.percent_change is None

    def test_display(self):
        m = BenchmarkMetric(name="CPU", unit="%", before_value=50.0, after_value=60.0)
        m.compute_comparison()
        assert m.before_display == "50.0%"
        assert m.after_display == "60.0%"
        assert m.delta_display == "+10.0%"
        assert m.change_display == "+20.0%"

    def test_display_none(self):
        m = BenchmarkMetric(name="FPS")
        assert m.before_display == "N/A"
        assert m.after_display == "N/A"
        assert m.delta_display == "N/A"

    def test_direction_icon(self):
        m = BenchmarkMetric(name="test")
        m.direction = ChangeDirection.IMPROVED
        assert m.direction_icon == "[+]"
        m.direction = ChangeDirection.DEGRADED
        assert m.direction_icon == "[-]"
        m.direction = ChangeDirection.UNCHANGED
        assert m.direction_icon == "[=]"

    def test_to_dict(self):
        m = BenchmarkMetric(name="CPU", unit="%", before_value=50.0, after_value=60.0)
        m.compute_comparison()
        d = m.to_dict()
        assert d["name"] == "CPU"
        assert d["before_value"] == 50.0
        assert d["after_value"] == 60.0
        assert d["direction"] == "IMPROVED"

    def test_from_dict(self):
        d = {
            "name": "FPS", "category": "FPS", "unit": "",
            "before_value": 80.0, "after_value": 100.0,
            "before_status": "MEASURED", "after_status": "MEASURED",
            "higher_is_better": True,
        }
        m = BenchmarkMetric.from_dict(d)
        assert m.name == "FPS"
        assert m.direction == ChangeDirection.IMPROVED


# ══════════════════════════════════════════════════════════════════
# 3. BenchmarkSnapshot
# ══════════════════════════════════════════════════════════════════

class TestBenchmarkSnapshot:
    def test_create(self):
        snap = BenchmarkSnapshot(label="BEFORE")
        assert snap.label == "BEFORE"
        assert snap.snapshot_id.startswith("snap_")
        assert snap.timestamp > 0

    def test_with_values(self):
        snap = BenchmarkSnapshot(
            cpu_percent=50.0, gpu_utilization=70.0,
            ram_percent=60.0, fps=90.0,
            gpu_temperature=65.0, disk_free_gb=200.0,
        )
        assert snap.cpu_percent == 50.0
        assert snap.fps == 90.0

    def test_to_dict(self):
        snap = BenchmarkSnapshot(label="AFTER", cpu_percent=55.0)
        d = snap.to_dict()
        assert d["label"] == "AFTER"
        assert d["cpu_percent"] == 55.0

    def test_none_values(self):
        snap = BenchmarkSnapshot()
        d = snap.to_dict()
        assert d["fps"] is None
        assert d["gpu_utilization"] is None


# ══════════════════════════════════════════════════════════════════
# 4. BenchmarkSession
# ══════════════════════════════════════════════════════════════════

class TestBenchmarkSession:
    def test_create(self):
        s = BenchmarkSession()
        assert s.session_id.startswith("bench_")
        assert s.overall_verdict == "INCONCLUSIVE"

    def test_verdict_improved(self):
        s = BenchmarkSession()
        s.metrics = [
            BenchmarkMetric(name="FPS", direction=ChangeDirection.IMPROVED),
            BenchmarkMetric(name="CPU", direction=ChangeDirection.UNCHANGED),
        ]
        s.compute_verdict()
        assert s.overall_verdict == "IMPROVED"
        assert s.total_improved == 1

    def test_verdict_degraded(self):
        s = BenchmarkSession()
        s.metrics = [
            BenchmarkMetric(name="Temp", direction=ChangeDirection.DEGRADED),
        ]
        s.compute_verdict()
        assert s.overall_verdict == "DEGRADED"

    def test_verdict_mixed_positive(self):
        s = BenchmarkSession()
        s.metrics = [
            BenchmarkMetric(name="FPS", direction=ChangeDirection.IMPROVED),
            BenchmarkMetric(name="Temp", direction=ChangeDirection.DEGRADED),
            BenchmarkMetric(name="RAM", direction=ChangeDirection.IMPROVED),
        ]
        s.compute_verdict()
        assert s.overall_verdict == "MIXED_POSITIVE"

    def test_verdict_mixed_negative(self):
        s = BenchmarkSession()
        s.metrics = [
            BenchmarkMetric(name="FPS", direction=ChangeDirection.IMPROVED),
            BenchmarkMetric(name="Temp", direction=ChangeDirection.DEGRADED),
            BenchmarkMetric(name="CPU", direction=ChangeDirection.DEGRADED),
        ]
        s.compute_verdict()
        assert s.overall_verdict == "MIXED_NEGATIVE"

    def test_verdict_unchanged(self):
        s = BenchmarkSession()
        s.metrics = [
            BenchmarkMetric(name="CPU", direction=ChangeDirection.UNCHANGED),
        ]
        s.compute_verdict()
        assert s.overall_verdict == "UNCHANGED"

    def test_to_dict(self):
        s = BenchmarkSession(benchmark_type=BenchmarkType.GAMING)
        d = s.to_dict()
        assert d["benchmark_type"] == "GAMING"
        assert "metrics" in d


# ══════════════════════════════════════════════════════════════════
# 5. ComparisonEngine
# ══════════════════════════════════════════════════════════════════

class TestComparisonEngine:
    def test_compare_identical(self):
        before = BenchmarkSnapshot(
            cpu_percent=50.0, gpu_utilization=60.0, ram_percent=70.0, fps=90.0,
        )
        after = BenchmarkSnapshot(
            cpu_percent=50.0, gpu_utilization=60.0, ram_percent=70.0, fps=90.0,
        )
        metrics = ComparisonEngine.compare(before, after)
        assert len(metrics) > 0
        for m in metrics:
            if m.before_value is not None and m.after_value is not None:
                assert m.direction == ChangeDirection.UNCHANGED

    def test_compare_improved(self):
        before = BenchmarkSnapshot(fps=80.0, one_percent_low=50.0)
        after = BenchmarkSnapshot(fps=100.0, one_percent_low=70.0)
        metrics = ComparisonEngine.compare(before, after)
        fps_metric = next(m for m in metrics if m.name == "FPS")
        assert fps_metric.direction == ChangeDirection.IMPROVED

    def test_compare_degraded(self):
        before = BenchmarkSnapshot(cpu_percent=40.0, ram_percent=60.0)
        after = BenchmarkSnapshot(cpu_percent=80.0, ram_percent=85.0)
        metrics = ComparisonEngine.compare(before, after)
        cpu_metric = next(m for m in metrics if m.name == "CPU Utilization")
        assert cpu_metric.direction == ChangeDirection.DEGRADED

    def test_compare_with_none_values(self):
        before = BenchmarkSnapshot(fps=None, cpu_percent=50.0)
        after = BenchmarkSnapshot(fps=90.0, cpu_percent=50.0)
        metrics = ComparisonEngine.compare(before, after)
        fps_metric = next(m for m in metrics if m.name == "FPS")
        assert fps_metric.before_status == MetricStatus.NOT_AVAILABLE
        assert fps_metric.after_status == MetricStatus.MEASURED

    def test_compare_all_none(self):
        before = BenchmarkSnapshot()
        after = BenchmarkSnapshot()
        metrics = ComparisonEngine.compare(before, after)
        for m in metrics:
            assert m.direction == ChangeDirection.UNKNOWN

    def test_compare_gpu_vram(self):
        before = BenchmarkSnapshot(gpu_vram_used=4000.0)
        after = BenchmarkSnapshot(gpu_vram_used=5000.0)
        metrics = ComparisonEngine.compare(before, after)
        vram = next(m for m in metrics if m.name == "GPU VRAM Used")
        assert vram.direction == ChangeDirection.DEGRADED


# ══════════════════════════════════════════════════════════════════
# 6. BenchmarkEngine
# ══════════════════════════════════════════════════════════════════

class TestBenchmarkEngine:
    def test_singleton_exists(self):
        assert isinstance(benchmark_engine, BenchmarkEngine)

    def test_capture_snapshot(self):
        engine = BenchmarkEngine()
        snap = engine.capture_snapshot(label="TEST")
        assert isinstance(snap, BenchmarkSnapshot)
        assert snap.label == "TEST"
        # Should have real CPU data
        assert snap.cpu_percent is not None
        assert snap.ram_percent is not None

    def test_run_benchmark_single(self):
        engine = BenchmarkEngine()
        with patch.object(engine, "capture_snapshot") as mock_cap:
            mock_snap = BenchmarkSnapshot(
                cpu_percent=50.0, ram_percent=60.0,
                gpu_utilization=70.0, fps=90.0,
            )
            mock_cap.return_value = mock_snap
            session = engine.run_benchmark(
                benchmark_type=BenchmarkType.QUICK,
                duration_seconds=0,
            )
        assert isinstance(session, BenchmarkSession)
        assert session.after is not None
        assert len(session.metrics) > 0

    def test_run_benchmark_with_before(self):
        engine = BenchmarkEngine()
        before = BenchmarkSnapshot(
            cpu_percent=40.0, ram_percent=55.0, fps=80.0,
        )
        with patch.object(engine, "capture_snapshot") as mock_cap:
            mock_cap.return_value = BenchmarkSnapshot(
                cpu_percent=50.0, ram_percent=60.0, fps=100.0,
            )
            session = engine.run_benchmark(
                benchmark_type=BenchmarkType.GAMING,
                before_snapshot=before,
                duration_seconds=0,
            )
        assert session.before is not None
        assert session.after is not None
        # Should have comparison metrics
        fps_metric = next((m for m in session.metrics if m.name == "FPS"), None)
        assert fps_metric is not None
        assert fps_metric.direction == ChangeDirection.IMPROVED

    def test_save_session(self):
        engine = BenchmarkEngine()
        with patch.object(engine, "capture_snapshot") as mock_cap:
            mock_cap.return_value = BenchmarkSnapshot(cpu_percent=50.0)
            session = engine.run_benchmark(duration_seconds=0)
        result = engine.save_session(session)
        assert result is True

    def test_export_session(self):
        engine = BenchmarkEngine()
        with patch.object(engine, "capture_snapshot") as mock_cap:
            mock_cap.return_value = BenchmarkSnapshot(cpu_percent=50.0)
            session = engine.run_benchmark(duration_seconds=0)
        data = engine.export_session(session)
        assert data is not None
        assert "session_id" in data
        assert "metrics" in data

    def test_format_session(self):
        engine = BenchmarkEngine()
        with patch.object(engine, "capture_snapshot") as mock_cap:
            mock_cap.return_value = BenchmarkSnapshot(
                cpu_percent=50.0, ram_percent=60.0,
            )
            session = engine.run_benchmark(duration_seconds=0)
        output = engine.format_session(session)
        assert "BENCHMARK" in output

    def test_format_session_with_comparison(self):
        engine = BenchmarkEngine()
        before = BenchmarkSnapshot(cpu_percent=40.0, fps=80.0)
        with patch.object(engine, "capture_snapshot") as mock_cap:
            mock_cap.return_value = BenchmarkSnapshot(cpu_percent=50.0, fps=100.0)
            session = engine.run_benchmark(
                before_snapshot=before, duration_seconds=0,
            )
        output = engine.format_session(session)
        assert "BEFORE" in output
        assert "AFTER" in output
        assert "COMPARISON" in output

    def test_format_no_session(self):
        engine = BenchmarkEngine()
        output = engine.format_session(None)
        assert "No benchmark" in output

    def test_export_no_session(self):
        engine = BenchmarkEngine()
        assert engine.export_session(None) is None

    def test_history_tracking(self):
        engine = BenchmarkEngine()
        initial_count = len(engine.history)
        with patch.object(engine, "capture_snapshot") as mock_cap:
            mock_cap.return_value = BenchmarkSnapshot(cpu_percent=50.0)
            session = engine.run_benchmark(duration_seconds=0)
        engine.save_session(session)
        assert len(engine.history) > initial_count

    def test_benchmark_types(self):
        for btype in BenchmarkType:
            engine = BenchmarkEngine()
            with patch.object(engine, "capture_snapshot") as mock_cap:
                mock_cap.return_value = BenchmarkSnapshot(cpu_percent=50.0)
                session = engine.run_benchmark(
                    benchmark_type=btype, duration_seconds=0,
                )
            assert session.benchmark_type == btype


# ══════════════════════════════════════════════════════════════════
# 7. CLI Integration
# ══════════════════════════════════════════════════════════════════

class TestCLIIntegration:
    def test_benchmark_quick(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--benchmark-quick"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "QUICK BENCHMARK" in result.stdout

    def test_benchmark_history(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--benchmark-history"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "BENCHMARK HISTORY" in result.stdout

    def test_benchmark_export(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--benchmark-export"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        # May return "No benchmark session" if no session exists
        assert result.returncode == 0


# ══════════════════════════════════════════════════════════════════
# 8. Edge Cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_metric_negative_delta(self):
        m = BenchmarkMetric(
            name="FPS", before_value=100.0, after_value=90.0,
            higher_is_better=True,
        )
        m.compute_comparison()
        assert m.delta == -10.0
        assert m.direction == ChangeDirection.DEGRADED

    def test_metric_small_change(self):
        m = BenchmarkMetric(
            name="CPU", before_value=50.001, after_value=50.002,
        )
        m.compute_comparison()
        assert m.direction == ChangeDirection.UNCHANGED

    def test_snapshot_auto_id(self):
        s1 = BenchmarkSnapshot()
        s2 = BenchmarkSnapshot()
        assert s1.snapshot_id != s2.snapshot_id

    def test_session_auto_id(self):
        s1 = BenchmarkSession()
        s2 = BenchmarkSession()
        assert s1.session_id != s2.session_id

    def test_empty_session_verdict(self):
        s = BenchmarkSession()
        s.compute_verdict()
        assert s.overall_verdict == "UNCHANGED"
        assert s.total_improved == 0

    def test_roundtrip_metric(self):
        original = BenchmarkMetric(
            name="FPS", before_value=80.0, after_value=100.0,
            higher_is_better=True,
        )
        original.compute_comparison()
        d = original.to_dict()
        restored = BenchmarkMetric.from_dict(d)
        assert restored.name == original.name
        assert restored.direction == original.direction
        assert restored.delta == pytest.approx(original.delta, abs=0.01)
