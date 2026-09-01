"""
Phase 59 — Comprehensive tests for Telemetry Dashboard.

Tests:
- BoundedBuffer (append, get_range, get_values, clear, max size)
- render_sparkline
- TelemetryDashboard (record, stats, sparkline, time ranges)
- MetricStats
- TimeRange enum
- Edge cases
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock
from app.performance.telemetry_dashboard import (
    TimeRange,
    HistoryEntry,
    BoundedBuffer,
    MetricStats,
    render_sparkline,
    TelemetryDashboard,
    telemetry_dashboard,
)


# ══════════════════════════════════════════════════════════════════
# 1. Enums
# ══════════════════════════════════════════════════════════════════

class TestTimeRange:
    def test_values(self):
        assert TimeRange.TEN_SECONDS.value == 10
        assert TimeRange.THIRTY_SECONDS.value == 30
        assert TimeRange.ONE_MINUTE.value == 60
        assert TimeRange.FIVE_MINUTES.value == 300

    def test_count(self):
        assert len(TimeRange) == 4


# ══════════════════════════════════════════════════════════════════
# 2. BoundedBuffer
# ══════════════════════════════════════════════════════════════════

class TestBoundedBuffer:
    def test_create(self):
        buf = BoundedBuffer(max_size=100)
        assert buf.size == 0
        assert buf.latest is None

    def test_append(self):
        buf = BoundedBuffer(max_size=100)
        buf.append(50.0)
        assert buf.size == 1
        assert buf.latest == 50.0

    def test_append_none(self):
        buf = BoundedBuffer(max_size=100)
        buf.append(None)
        assert buf.size == 1
        assert buf.latest is None

    def test_max_size_enforced(self):
        buf = BoundedBuffer(max_size=5)
        for i in range(10):
            buf.append(float(i))
        assert buf.size == 5
        # Should have the last 5 values
        assert buf.latest == 9.0

    def test_get_values(self):
        buf = BoundedBuffer(max_size=100)
        for i in range(5):
            buf.append(float(i * 10))
        values = buf.get_values(seconds=300)
        assert len(values) == 5
        assert values[0] == 0.0
        assert values[-1] == 40.0

    def test_get_values_filters_none(self):
        buf = BoundedBuffer(max_size=100)
        buf.append(10.0)
        buf.append(None)
        buf.append(30.0)
        values = buf.get_values(seconds=300)
        assert len(values) == 2
        assert values[0] == 10.0

    def test_get_range_time_filter(self):
        buf = BoundedBuffer(max_size=100)
        # Add old entry
        buf._buffer.append(HistoryEntry(timestamp=time.time() - 60, value=1.0))
        # Add recent entry
        buf.append(2.0)
        recent = buf.get_range(seconds=10)
        assert len(recent) == 1
        assert recent[0].value == 2.0

    def test_clear(self):
        buf = BoundedBuffer(max_size=100)
        buf.append(1.0)
        buf.append(2.0)
        buf.clear()
        assert buf.size == 0
        assert buf.latest is None

    def test_empty_get_values(self):
        buf = BoundedBuffer(max_size=100)
        assert buf.get_values(seconds=10) == []


# ══════════════════════════════════════════════════════════════════
# 3. render_sparkline
# ══════════════════════════════════════════════════════════════════

class TestRenderSparkline:
    def test_empty(self):
        assert render_sparkline([]) == ""

    def test_single_value(self):
        assert render_sparkline([50.0]) == ""

    def test_constant_values(self):
        result = render_sparkline([50.0, 50.0, 50.0])
        assert len(result) == 3
        # All same char
        assert len(set(result)) == 1

    def test_increasing(self):
        result = render_sparkline([0.0, 25.0, 50.0, 75.0, 100.0])
        assert len(result) == 5
        # Should generally increase
        chars = [c for c in result]
        # At least not all the same
        assert len(set(chars)) > 1

    def test_downsample(self):
        values = list(range(100))
        result = render_sparkline(values, width=10)
        assert len(result) == 10

    def test_width_20_default(self):
        values = list(range(50))
        result = render_sparkline(values)
        assert len(result) == 20

    def test_small_range(self):
        result = render_sparkline([1.0, 1.001, 1.002])
        assert len(result) == 3


# ══════════════════════════════════════════════════════════════════
# 4. MetricStats
# ══════════════════════════════════════════════════════════════════

class TestMetricStats:
    def test_create(self):
        s = MetricStats(name="cpu")
        assert s.name == "cpu"
        assert s.has_data is False

    def test_has_data(self):
        s = MetricStats(name="cpu", current=50.0, samples=10)
        assert s.has_data is True

    def test_has_data_no_samples(self):
        s = MetricStats(name="cpu", current=50.0, samples=0)
        assert s.has_data is False

    def test_sparkline(self):
        s = MetricStats()
        s.sparkline = ":-=+*"
        assert s.sparkline == ":-=+*"


# ══════════════════════════════════════════════════════════════════
# 5. TelemetryDashboard
# ══════════════════════════════════════════════════════════════════

class TestTelemetryDashboard:
    def _make_snapshot(self, **kwargs):
        """Create a mock telemetry snapshot."""
        snap = MagicMock()
        snap.cpu_utilization = kwargs.get("cpu", 0.0)
        snap.gpu_utilization = kwargs.get("gpu", 0.0)
        snap.ram_percent = kwargs.get("ram", 0.0)
        snap.gpu_memory_used_mb = kwargs.get("vram_used", 0.0)
        snap.gpu_memory_total_mb = kwargs.get("vram_total", 0.0)
        snap.gpu_temp = kwargs.get("gpu_temp", None)
        snap.gpu_clock_mhz = kwargs.get("gpu_clock", None)
        return snap

    def test_singleton_exists(self):
        assert isinstance(telemetry_dashboard, TelemetryDashboard)

    def test_create(self):
        d = TelemetryDashboard()
        assert d.time_range == TimeRange.THIRTY_SECONDS

    def test_time_range_change(self):
        d = TelemetryDashboard()
        d.time_range = TimeRange.ONE_MINUTE
        assert d.time_range == TimeRange.ONE_MINUTE

    def test_record_snapshot(self):
        d = TelemetryDashboard()
        snap = self._make_snapshot(cpu=50.0, gpu=70.0, ram=60.0)
        d.record_snapshot(snap)
        # Buffers should have data
        assert d._buffers["cpu"].size == 1
        assert d._buffers["gpu"].size == 1

    def test_record_snapshot_vram(self):
        d = TelemetryDashboard()
        snap = self._make_snapshot(vram_used=4000, vram_total=8000)
        d.record_snapshot(snap)
        assert d._buffers["vram"].size == 1

    def test_record_snapshot_vram_zero(self):
        d = TelemetryDashboard()
        snap = self._make_snapshot(vram_used=0, vram_total=0)
        d.record_snapshot(snap)
        assert d._buffers["vram"].latest is None

    def test_record_snapshot_gpu_temp(self):
        d = TelemetryDashboard()
        snap = self._make_snapshot(gpu_temp=65.0)
        d.record_snapshot(snap)
        assert d._buffers["gpu_temp"].latest == 65.0

    def test_record_fps(self):
        d = TelemetryDashboard()
        d.record_fps(fps=90.0, one_low=60.0, frame_time=11.1)
        assert d._buffers["fps"].latest == 90.0
        assert d._buffers["one_low"].latest == 60.0
        assert d._buffers["frame_time"].latest == 11.1

    def test_record_fps_none(self):
        d = TelemetryDashboard()
        d.record_fps(fps=None)
        assert d._buffers["fps"].latest is None

    def test_record_disk(self):
        d = TelemetryDashboard()
        d.record_disk(200.5)
        assert d._buffers["disk_free"].latest == 200.5

    def test_get_stats(self):
        d = TelemetryDashboard()
        d.record_fps(fps=80.0)
        d.record_fps(fps=90.0)
        d.record_fps(fps=100.0)
        stats = d.get_stats("fps")
        assert stats.current == 100.0
        assert stats.min_value == 80.0
        assert stats.max_value == 100.0
        assert stats.avg_value == 90.0
        assert stats.samples == 3

    def test_get_stats_empty(self):
        d = TelemetryDashboard()
        stats = d.get_stats("nonexistent")
        assert stats.samples == 0

    def test_get_sparkline(self):
        d = TelemetryDashboard()
        for i in range(20):
            d.record_fps(fps=float(i * 5))
        spark = d.get_sparkline("fps")
        assert len(spark) > 0

    def test_get_sparkline_empty(self):
        d = TelemetryDashboard()
        spark = d.get_sparkline("fps")
        assert spark == ""

    def test_get_all_stats(self):
        d = TelemetryDashboard()
        d.record_fps(fps=90.0)
        snap = self._make_snapshot(cpu=50.0)
        d.record_snapshot(snap)
        all_stats = d.get_all_stats()
        assert "fps" in all_stats
        assert "cpu" in all_stats

    def test_get_snapshot(self):
        d = TelemetryDashboard()
        d.record_disk(200.0)
        snap = d.get_snapshot()
        assert snap["disk_free"] == 200.0

    def test_format_dashboard(self):
        d = TelemetryDashboard()
        d.record_fps(fps=90.0)
        snap = self._make_snapshot(cpu=50.0, gpu=70.0, ram=60.0, gpu_temp=65.0)
        d.record_snapshot(snap)
        output = d.format_dashboard()
        assert "TELEMETRY DASHBOARD" in output
        assert "SYSTEM" in output
        assert "FRAME" in output

    def test_format_dashboard_empty(self):
        d = TelemetryDashboard()
        output = d.format_dashboard()
        assert "TELEMETRY DASHBOARD" in output

    def test_clear(self):
        d = TelemetryDashboard()
        d.record_fps(fps=90.0)
        d.record_disk(200.0)
        d.clear()
        assert d._buffers["fps"].size == 0
        assert d._buffers["disk_free"].size == 0

    def test_bounded_buffer_max_size(self):
        d = TelemetryDashboard()
        for i in range(400):
            d.record_fps(fps=float(i))
        assert d._buffers["fps"].size <= TelemetryDashboard.MAX_BUFFER_SIZE

    def test_time_range_filtering(self):
        d = TelemetryDashboard(time_range=TimeRange.TEN_SECONDS)
        # Record some data
        d.record_fps(fps=90.0)
        stats = d.get_stats("fps")
        assert stats.samples >= 1

    def test_multiple_metrics(self):
        d = TelemetryDashboard()
        snap = self._make_snapshot(
            cpu=50.0, gpu=70.0, ram=60.0,
            vram_used=4000, vram_total=8000,
            gpu_temp=65.0, gpu_clock=1800.0,
        )
        d.record_snapshot(snap)
        d.record_fps(fps=90.0, one_low=60.0, frame_time=11.1)
        d.record_disk(200.0)

        all_stats = d.get_all_stats()
        assert all_stats["cpu"].current == 50.0
        assert all_stats["gpu"].current == 70.0
        assert all_stats["ram"].current == 60.0
        assert all_stats["vram"].current == 50.0  # 4000/8000*100
        assert all_stats["gpu_temp"].current == 65.0
        assert all_stats["fps"].current == 90.0
        assert all_stats["disk_free"].current == 200.0


# ══════════════════════════════════════════════════════════════════
# 6. Edge Cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_negative_values(self):
        buf = BoundedBuffer(max_size=100)
        buf.append(-10.0)
        buf.append(-5.0)
        values = buf.get_values(seconds=300)
        assert values == [-10.0, -5.0]

    def test_very_large_values(self):
        buf = BoundedBuffer(max_size=100)
        buf.append(999999.0)
        assert buf.latest == 999999.0

    def test_sparkline_single_value(self):
        result = render_sparkline([50.0])
        assert result == ""

    def test_sparkline_two_values(self):
        result = render_sparkline([0.0, 100.0])
        assert len(result) == 2

    def test_dashboard_error_handling(self):
        d = TelemetryDashboard()
        # Record with bad snapshot
        bad_snap = MagicMock()
        bad_snap.cpu_utilization = "not_a_number"
        d.record_snapshot(bad_snap)  # Should not raise

    def test_concurrent_access(self):
        """Verify buffers handle rapid appends."""
        d = TelemetryDashboard()
        for _ in range(1000):
            d.record_fps(fps=90.0)
        assert d._buffers["fps"].size <= TelemetryDashboard.MAX_BUFFER_SIZE
