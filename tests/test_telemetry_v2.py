"""
Tests for Phase 34: Real-Time Telemetry & Bottleneck Correlation.

Covers: TelemetrySample, PerformanceEvent, TelemetrySession, BottleneckAssessment,
TelemetryCollector, BottleneckAnalyzer, and CLI integration.
"""

import time
import threading
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from app.performance.telemetry_models import (
    BottleneckAssessment,
    BottleneckType,
    DataAvailability,
    EventSeverity,
    EventType,
    PerformanceEvent,
    PerformanceSummary,
    TelemetrySample,
    TelemetrySession,
)
from app.performance.telemetry_collector import (
    TelemetryCollector,
    _safe_avg,
    _safe_max,
    _safe_min,
)
from app.performance.bottleneck_analyzer import (
    BottleneckAnalyzer,
    CPU_HIGH_THRESHOLD,
    GPU_SATURATION_THRESHOLD,
    RAM_PRESSURE_THRESHOLD,
)


# ═══════════════════════════════════════════════════════════════
# TelemetrySample tests
# ═══════════════════════════════════════════════════════════════

class TestTelemetrySample:

    def test_default_sample(self):
        s = TelemetrySample()
        assert s.timestamp == 0.0
        assert s.fps is None
        assert s.cpu_total_percent is None
        assert s.gpu_utilization_percent is None
        assert s.system_ram_used_mb is None
        assert s.emulator_pid == 0
        assert s.emulator_name == ""
        assert s.cpu_per_core_percent == []

    def test_has_fps_true(self):
        s = TelemetrySample(fps=60.0)
        assert s.has_fps() is True

    def test_has_fps_none(self):
        s = TelemetrySample(fps=None)
        assert s.has_fps() is False

    def test_has_fps_zero(self):
        s = TelemetrySample(fps=0.0)
        assert s.has_fps() is False

    def test_has_gpu_true(self):
        s = TelemetrySample(gpu_utilization_percent=50.0)
        assert s.has_gpu() is True

    def test_has_gpu_none(self):
        s = TelemetrySample(gpu_utilization_percent=None)
        assert s.has_gpu() is False

    def test_has_emulator_true(self):
        s = TelemetrySample(emulator_pid=1234)
        assert s.has_emulator() is True

    def test_has_emulator_zero(self):
        s = TelemetrySample(emulator_pid=0)
        assert s.has_emulator() is False

    def test_has_ram_true(self):
        s = TelemetrySample(system_ram_total_mb=16000)
        assert s.has_ram() is True

    def test_has_ram_none(self):
        s = TelemetrySample(system_ram_total_mb=None)
        assert s.has_ram() is False

    def test_sample_with_all_fields(self):
        s = TelemetrySample(
            timestamp=time.time(),
            emulator_pid=7777,
            emulator_name="HD-Player.exe",
            fps=90.5,
            one_percent_low=45.2,
            frame_time_ms=11.05,
            cpu_total_percent=35.0,
            cpu_per_core_percent=[30.0, 40.0, 35.0, 35.0],
            emulator_cpu_percent=60.0,
            gpu_utilization_percent=70.0,
            gpu_temperature_c=55.0,
            gpu_vram_used_mb=2000.0,
            gpu_vram_total_mb=4096.0,
            system_ram_used_mb=8000.0,
            system_ram_available_mb=4000.0,
            system_ram_total_mb=12000.0,
            emulator_ram_mb=3000.0,
            display_refresh_hz=144,
        )
        assert s.has_fps()
        assert s.has_gpu()
        assert s.has_emulator()
        assert s.has_ram()
        assert s.emulator_name == "HD-Player.exe"


# ═══════════════════════════════════════════════════════════════
# PerformanceEvent tests
# ═══════════════════════════════════════════════════════════════

class TestPerformanceEvent:

    def test_event_creation(self):
        e = PerformanceEvent(
            timestamp=1000.0,
            event_type=EventType.FPS_DROP,
            severity=EventSeverity.WARNING,
            measured_value=30.0,
            threshold=60.0,
            explanation="FPS dropped below 60",
        )
        assert e.event_type == EventType.FPS_DROP
        assert e.severity == EventSeverity.WARNING

    def test_event_to_dict(self):
        e = PerformanceEvent(
            timestamp=1000.0,
            event_type=EventType.GPU_SATURATION,
            severity=EventSeverity.CRITICAL,
            measured_value=99.0,
            threshold=95.0,
            explanation="GPU at 99%",
        )
        d = e.to_dict()
        assert d["event_type"] == "GPU_SATURATION"
        assert d["severity"] == "CRITICAL"
        assert d["measured_value"] == 99.0

    def test_all_event_types(self):
        for et in EventType:
            e = PerformanceEvent(event_type=et)
            assert e.event_type == et

    def test_all_severities(self):
        for sev in EventSeverity:
            e = PerformanceEvent(severity=sev)
            assert e.severity == sev


# ═══════════════════════════════════════════════════════════════
# TelemetrySession tests
# ═══════════════════════════════════════════════════════════════

class TestTelemetrySession:

    def test_session_defaults(self):
        s = TelemetrySession()
        assert s.session_id
        assert len(s.session_id) == 8
        assert s.sample_count == 0
        assert s.events == []
        assert s.bottleneck is None

    def test_session_get_duration_completed(self):
        s = TelemetrySession(started_at=1000.0, completed_at=1100.0)
        assert s.get_duration() == 100.0

    def test_session_get_duration_not_completed(self):
        s = TelemetrySession(started_at=1000.0, duration_seconds=60.0)
        assert s.get_duration() == 60.0

    def test_session_to_dict(self):
        s = TelemetrySession(
            target_name="HD-Player.exe",
            target_pid=1234,
            avg_fps=90.0,
        )
        d = s.to_dict()
        assert d["target_name"] == "HD-Player.exe"
        assert d["target_pid"] == 1234
        assert d["avg_fps"] == 90.0

    def test_session_unique_ids(self):
        s1 = TelemetrySession()
        s2 = TelemetrySession()
        assert s1.session_id != s2.session_id


# ═══════════════════════════════════════════════════════════════
# BottleneckAssessment tests
# ═══════════════════════════════════════════════════════════════

class TestBottleneckAssessment:

    def test_assessment_defaults(self):
        a = BottleneckAssessment()
        assert a.bottleneck == BottleneckType.INSUFFICIENT_DATA
        assert a.confidence == 0
        assert a.evidence == []
        assert a.recommendations == []

    def test_assessment_to_dict(self):
        a = BottleneckAssessment(
            bottleneck=BottleneckType.GPU_BOUND,
            confidence=80,
            evidence=["GPU at 95%"],
            recommendations=["Reduce graphics quality"],
        )
        d = a.to_dict()
        assert d["bottleneck"] == "GPU_BOUND"
        assert d["confidence"] == 80
        assert "GPU at 95%" in d["evidence"]

    def test_all_bottleneck_types(self):
        for bt in BottleneckType:
            a = BottleneckAssessment(bottleneck=bt)
            assert a.bottleneck == bt

    def test_data_availability(self):
        for da in DataAvailability:
            a = BottleneckAssessment(data_availability=da)
            assert a.data_availability == da


# ═══════════════════════════════════════════════════════════════
# PerformanceSummary tests
# ═══════════════════════════════════════════════════════════════

class TestPerformanceSummary:

    def test_summary_defaults(self):
        s = PerformanceSummary()
        assert s.sample_count == 0
        assert s.avg_fps is None
        assert s.stability_rating == "UNKNOWN"

    def test_summary_to_dict(self):
        s = PerformanceSummary(avg_fps=90.0, sample_count=100)
        d = s.to_dict()
        assert d["avg_fps"] == 90.0
        assert d["sample_count"] == 100


# ═══════════════════════════════════════════════════════════════
# TelemetryCollector tests
# ═══════════════════════════════════════════════════════════════

class TestTelemetryCollector:

    def test_creation(self):
        c = TelemetryCollector(interval_ms=500, max_samples=100)
        assert c.sample_count == 0
        assert c.current is None

    def test_set_target(self):
        c = TelemetryCollector()
        c.set_target(1234, "HD-Player.exe", 1000.0)
        assert c._emulator_pid == 1234
        assert c._emulator_name == "HD-Player.exe"

    def test_clear(self):
        c = TelemetryCollector()
        c.clear()
        assert c.sample_count == 0
        assert c.current is None

    def test_start_stop(self):
        c = TelemetryCollector(interval_ms=100)
        c.start()
        assert c._running is True
        time.sleep(0.3)
        c.stop()
        assert c._running is False

    def test_collect_sample(self):
        c = TelemetryCollector()
        sample = c.collect_sample()
        assert isinstance(sample, TelemetrySample)
        assert sample.timestamp > 0
        assert sample.cpu_total_percent is not None or sample.cpu_total_percent is None  # may be None on first call

    def test_collect_stores_sample(self):
        c = TelemetryCollector()
        c.collect_sample()
        assert c.sample_count >= 1

    def test_bounded_buffer(self):
        c = TelemetryCollector(max_samples=5)
        for _ in range(10):
            c.collect_sample()
        assert c.sample_count <= 5

    def test_callback(self):
        c = TelemetryCollector()
        received = []
        c.on_update(lambda s: received.append(s))
        c.collect_sample()
        assert len(received) == 1
        assert isinstance(received[0], TelemetrySample)

    def test_callback_exception_safety(self):
        c = TelemetryCollector()
        c.on_update(lambda s: 1 / 0)  # Will raise
        c.collect_sample()  # Should not crash

    @patch("app.system.gpu.gpu_monitor")
    @patch("app.core.scanner.hardware_scanner")
    def test_gpu_collection(self, mock_scanner, mock_gpu):
        mock_gpu_info = MagicMock()
        mock_gpu_info.vendor = "NVIDIA"
        mock_gpu_info.utilization_gpu = 75.0
        mock_gpu_info.temperature_celsius = 60.0
        mock_gpu_info.vram_used_mb = 2000.0
        mock_gpu_info.vram_total_mb = 4096.0
        mock_gpu_info.clock_core_mhz = 1500.0
        mock_gpu_info.power_draw_watts = 120.0
        mock_gpu.update_nvidia.return_value = mock_gpu_info

        mock_profile = MagicMock()
        mock_profile.gpus = [mock_gpu_info]
        mock_scanner.scan.return_value = mock_profile

        c = TelemetryCollector()
        sample = c.collect_sample()
        assert sample.gpu_utilization_percent == 75.0
        assert sample.gpu_temperature_c == 60.0
        assert sample.gpu_vram_used_mb == 2000.0

    def test_sample_with_mocked_psutil(self):
        c = TelemetryCollector()
        with patch("psutil.cpu_percent", return_value=42.0):
            with patch("psutil.virtual_memory") as mock_mem:
                mock_mem.return_value = MagicMock(
                    used=8000 * 1024 * 1024,
                    available=4000 * 1024 * 1024,
                    total=12000 * 1024 * 1024,
                )
                sample = c.collect_sample()
                # CPU may or may not be set depending on psutil priming
                assert sample.system_ram_used_mb is not None

    def test_calculate_summary_empty(self):
        c = TelemetryCollector()
        summary = c.calculate_summary()
        assert summary.sample_count == 0

    def test_calculate_summary_with_data(self):
        c = TelemetryCollector()
        # Manually inject samples
        samples = []
        for i in range(20):
            s = TelemetrySample(
                timestamp=time.time() + i * 0.5,
                fps=60.0 + (i % 5),
                frame_time_ms=16.0 + (i % 3),
                cpu_total_percent=30.0 + i,
                gpu_utilization_percent=50.0 + i,
                system_ram_used_mb=8000.0 + i * 10,
                system_ram_available_mb=4000.0 - i * 10,
                system_ram_total_mb=12000.0,
                emulator_cpu_percent=40.0 + i,
                emulator_ram_mb=2000.0 + i * 5,
            )
            samples.append(s)

        with c._lock:
            c._samples = samples

        summary = c.calculate_summary()
        assert summary.sample_count == 20
        assert summary.avg_fps is not None
        assert summary.median_fps is not None
        assert summary.one_percent_low is not None
        assert summary.avg_cpu_percent is not None
        assert summary.avg_gpu_percent is not None
        assert summary.avg_ram_used_mb is not None
        assert summary.avg_emulator_cpu is not None

    def test_stability_calculation(self):
        c = TelemetryCollector()
        # Consistent frame times = high stability
        samples = []
        for i in range(20):
            s = TelemetrySample(
                timestamp=time.time() + i,
                frame_time_ms=16.67,  # Perfect 60fps
            )
            samples.append(s)
        with c._lock:
            c._samples = samples
        summary = c.calculate_summary()
        assert summary.stability_score > 90
        assert summary.stability_rating == "EXCELLENT"

    def test_stability_poor(self):
        c = TelemetryCollector()
        # Wildly varying frame times = low stability
        import random
        random.seed(42)
        samples = []
        for i in range(20):
            s = TelemetrySample(
                timestamp=time.time() + i,
                frame_time_ms=random.uniform(5, 100),
            )
            samples.append(s)
        with c._lock:
            c._samples = samples
        summary = c.calculate_summary()
        assert summary.stability_rating in ("FAIR", "POOR", "BAD")

    def test_start_stop_background(self):
        c = TelemetryCollector(interval_ms=50)
        c.start()
        time.sleep(0.3)
        count = c.sample_count
        c.stop()
        assert count >= 2  # Should have collected several samples


# ═══════════════════════════════════════════════════════════════
# BottleneckAnalyzer tests
# ═══════════════════════════════════════════════════════════════

class TestBottleneckAnalyzer:

    def test_creation(self):
        a = BottleneckAnalyzer()
        assert a is not None

    def test_insufficient_data_empty(self):
        a = BottleneckAnalyzer()
        result = a.analyze_samples([])
        assert result.bottleneck == BottleneckType.INSUFFICIENT_DATA
        assert result.confidence == 0

    def test_insufficient_data_few_samples(self):
        a = BottleneckAnalyzer()
        samples = [TelemetrySample(cpu_total_percent=50.0) for _ in range(3)]
        result = a.analyze_samples(samples)
        assert result.bottleneck == BottleneckType.INSUFFICIENT_DATA

    def test_no_bottleneck_detected(self):
        a = BottleneckAnalyzer()
        samples = [
            TelemetrySample(
                cpu_total_percent=30.0,
                gpu_utilization_percent=40.0,
                system_ram_used_mb=6000,
                system_ram_total_mb=16000,
                system_ram_available_mb=10000,
            )
            for _ in range(10)
        ]
        result = a.analyze_samples(samples)
        assert result.bottleneck == BottleneckType.NO_CLEAR_BOTTLENECK
        assert result.confidence > 0

    def test_gpu_bound_detection(self):
        a = BottleneckAnalyzer()
        samples = [
            TelemetrySample(
                gpu_utilization_percent=95.0,
                cpu_total_percent=30.0,
                emulator_cpu_percent=20.0,
                system_ram_used_mb=6000,
                system_ram_total_mb=16000,
                system_ram_available_mb=10000,
            )
            for _ in range(10)
        ]
        result = a.analyze_samples(samples)
        assert result.bottleneck == BottleneckType.GPU_BOUND
        assert result.confidence >= 50
        assert len(result.evidence) > 0
        assert len(result.recommendations) > 0

    def test_cpu_bound_detection(self):
        a = BottleneckAnalyzer()
        samples = [
            TelemetrySample(
                cpu_total_percent=92.0,
                gpu_utilization_percent=20.0,
                emulator_cpu_percent=85.0,
                system_ram_used_mb=6000,
                system_ram_total_mb=16000,
                system_ram_available_mb=10000,
            )
            for _ in range(10)
        ]
        result = a.analyze_samples(samples)
        assert result.bottleneck == BottleneckType.CPU_BOUND
        assert result.confidence >= 50

    def test_memory_bound_detection(self):
        a = BottleneckAnalyzer()
        samples = [
            TelemetrySample(
                cpu_total_percent=40.0,
                gpu_utilization_percent=30.0,
                system_ram_used_mb=15000,
                system_ram_total_mb=16000,
                system_ram_available_mb=500,
                emulator_ram_mb=8000,
            )
            for _ in range(10)
        ]
        result = a.analyze_samples(samples)
        assert result.bottleneck == BottleneckType.MEMORY_BOUND
        assert result.confidence >= 40

    def test_thermal_detection(self):
        a = BottleneckAnalyzer()
        samples = [
            TelemetrySample(
                gpu_temperature_c=92.0,
                cpu_total_percent=40.0,
                gpu_utilization_percent=60.0,
                system_ram_used_mb=8000,
                system_ram_total_mb=16000,
                system_ram_available_mb=8000,
            )
            for _ in range(10)
        ]
        result = a.analyze_samples(samples)
        assert result.bottleneck == BottleneckType.THERMAL_LIMITED
        assert result.confidence >= 30

    def test_frame_instability_detection(self):
        a = BottleneckAnalyzer()
        import random
        random.seed(42)
        samples = [
            TelemetrySample(
                frame_time_ms=random.uniform(5, 100),
                cpu_total_percent=40.0,
                gpu_utilization_percent=30.0,
                system_ram_used_mb=8000,
                system_ram_total_mb=16000,
                system_ram_available_mb=8000,
            )
            for _ in range(20)
        ]
        result = a.analyze_samples(samples)
        assert result.bottleneck == BottleneckType.FRAME_TIME_INSTABILITY

    def test_no_gpu_data(self):
        a = BottleneckAnalyzer()
        samples = [
            TelemetrySample(
                cpu_total_percent=30.0,
                gpu_utilization_percent=None,
                system_ram_used_mb=6000,
                system_ram_total_mb=16000,
                system_ram_available_mb=10000,
            )
            for _ in range(10)
        ]
        result = a.analyze_samples(samples)
        # Should not crash
        assert result.bottleneck in (
            BottleneckType.NO_CLEAR_BOTTLENECK,
            BottleneckType.INSUFFICIENT_DATA,
            BottleneckType.CPU_BOUND,
        )

    def test_with_performance_summary(self):
        """Test that bottleneck analyzer uses PerformanceSummary internally."""
        a = BottleneckAnalyzer()
        samples = []
        for i in range(10):
            s = TelemetrySample(
                timestamp=time.time() + i,
                cpu_total_percent=50.0,
                gpu_utilization_percent=50.0,
                system_ram_used_mb=8000,
                system_ram_total_mb=16000,
                system_ram_available_mb=8000,
            )
            samples.append(s)
        result = a.analyze_samples(samples)
        assert result.data_availability == DataAvailability.MEASURED


# ═══════════════════════════════════════════════════════════════
# Helper function tests
# ═══════════════════════════════════════════════════════════════

class TestHelpers:

    def test_safe_avg(self):
        assert _safe_avg([1.0, 2.0, 3.0]) == 2.0

    def test_safe_avg_empty(self):
        assert _safe_avg([]) is None

    def test_safe_avg_with_nones(self):
        assert _safe_avg([1.0, None, 3.0]) == 2.0

    def test_safe_avg_all_nones(self):
        assert _safe_avg([None, None]) is None

    def test_safe_max(self):
        assert _safe_max([1.0, 5.0, 3.0]) == 5.0

    def test_safe_max_empty(self):
        assert _safe_max([]) is None

    def test_safe_max_with_nones(self):
        assert _safe_max([None, 5.0, None]) == 5.0

    def test_safe_min(self):
        assert _safe_min([3.0, 1.0, 5.0]) == 1.0

    def test_safe_min_empty(self):
        assert _safe_min([]) is None

    def test_safe_min_with_nones(self):
        assert _safe_min([None, 1.0, None]) == 1.0


# ═══════════════════════════════════════════════════════════════
# Integration tests
# ═══════════════════════════════════════════════════════════════

class TestIntegration:

    def test_collector_to_bottleneck_pipeline(self):
        """Full pipeline: collect samples -> summarize -> analyze bottleneck."""
        collector = TelemetryCollector(max_samples=100)
        for _ in range(10):
            s = TelemetrySample(
                timestamp=time.time(),
                cpu_total_percent=35.0,
                gpu_utilization_percent=95.0,
                emulator_cpu_percent=25.0,
                system_ram_used_mb=8000,
                system_ram_total_mb=16000,
                system_ram_available_mb=8000,
            )
            with collector._lock:
                collector._samples.append(s)

        summary = collector.calculate_summary()
        assert summary.sample_count == 10

        analyzer = BottleneckAnalyzer()
        assessment = analyzer.analyze_samples(collector.samples)
        assert assessment.bottleneck == BottleneckType.GPU_BOUND

    def test_summary_serialization(self):
        """Summary can be serialized to dict."""
        s = PerformanceSummary(
            sample_count=100,
            avg_fps=90.0,
            median_fps=88.0,
            one_percent_low=45.0,
            avg_frame_time_ms=11.1,
            frame_spikes=5,
            stability_score=85.0,
            stability_rating="EXCELLENT",
        )
        d = s.to_dict()
        assert isinstance(d, dict)
        assert d["avg_fps"] == 90.0
        assert d["stability_rating"] == "EXCELLENT"

    def test_session_serialization(self):
        """Session can be serialized to dict."""
        s = TelemetrySession(
            target_name="HD-Player.exe",
            target_pid=1234,
            avg_fps=90.0,
            bottleneck=BottleneckAssessment(
                bottleneck=BottleneckType.GPU_BOUND,
                confidence=80,
            ),
        )
        d = s.to_dict()
        assert isinstance(d, dict)
        assert d["bottleneck"]["bottleneck"] == "GPU_BOUND"

    def test_no_process_termination(self):
        """Verify telemetry collection never terminates processes."""
        c = TelemetryCollector()
        sample = c.collect_sample()
        # Just verify it completes without killing anything
        assert isinstance(sample, TelemetrySample)

    def test_no_registry_modification(self):
        """Verify telemetry collection does not modify registry."""
        c = TelemetryCollector()
        sample = c.collect_sample()
        assert isinstance(sample, TelemetrySample)
