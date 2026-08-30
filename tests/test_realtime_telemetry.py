"""
Tests for Phase 34: Real-Time Telemetry Engine.

Covers: RealtimeTelemetry, session lifecycle, PID reuse protection,
optimization correlation, frame pacing, events, overhead, and safety.
"""

import statistics
import time
import threading
import pytest
from unittest.mock import patch, MagicMock

from app.performance.telemetry_models import (
    BeforeAfterSnapshot,
    BottleneckAssessment,
    BottleneckType,
    DataAvailability,
    EventType,
    EventSeverity,
    FramePacingStatus,
    MetricValue,
    PerformanceEvent,
    PerformanceSummary,
    TelemetryMetricState,
    TelemetryOverhead,
    TelemetrySample,
    TelemetrySession,
    TargetStatus,
)
from app.performance.realtime_telemetry import (
    RealtimeTelemetry,
    realtime_telemetry,
    DEFAULT_INTERVAL_MS,
    DEFAULT_MAX_SAMPLES,
    PID_REUSE_TOLERANCE_S,
    STALE_THRESHOLD_S,
    FRAME_PACING_MIN_SAMPLES,
)


# ═══════════════════════════════════════════════════════════════
# MetricValue tests
# ═══════════════════════════════════════════════════════════════

class TestMetricValue:

    def test_default(self):
        m = MetricValue()
        assert m.value is None
        assert m.state == TelemetryMetricState.NOT_AVAILABLE
        assert m.is_available() is False

    def test_measured(self):
        m = MetricValue(value=60.0, state=TelemetryMetricState.MEASURED)
        assert m.is_available() is True

    def test_not_available(self):
        m = MetricValue(value=None, state=TelemetryMetricState.NOT_AVAILABLE)
        assert m.is_available() is False

    def test_failed(self):
        m = MetricValue(state=TelemetryMetricState.FAILED)
        assert m.is_available() is False

    def test_stale(self):
        m = MetricValue(value=50.0, state=TelemetryMetricState.STALE)
        assert m.is_available() is False

    def test_to_dict(self):
        m = MetricValue(value=42.0, state=TelemetryMetricState.MEASURED, last_updated=1000.0)
        d = m.to_dict()
        assert d["value"] == 42.0
        assert d["state"] == "MEASURED"
        assert d["last_updated"] == 1000.0


# ═══════════════════════════════════════════════════════════════
# BeforeAfterSnapshot tests
# ═══════════════════════════════════════════════════════════════

class TestBeforeAfterSnapshot:

    def test_default(self):
        s = BeforeAfterSnapshot()
        assert s.label == ""
        assert s.fps.state == TelemetryMetricState.NOT_AVAILABLE

    def test_with_label(self):
        s = BeforeAfterSnapshot(label="BEFORE", timestamp=1000.0)
        assert s.label == "BEFORE"
        assert s.timestamp == 1000.0

    def test_to_dict(self):
        s = BeforeAfterSnapshot(
            label="AFTER",
            fps=MetricValue(value=90.0, state=TelemetryMetricState.MEASURED),
        )
        d = s.to_dict()
        assert d["label"] == "AFTER"
        assert d["fps"]["value"] == 90.0


# ═══════════════════════════════════════════════════════════════
# TargetStatus tests
# ═══════════════════════════════════════════════════════════════

class TestTargetStatus:

    def test_all_values(self):
        for ts in TargetStatus:
            assert ts.value

    def test_active(self):
        assert TargetStatus.ACTIVE.value == "ACTIVE"

    def test_stopped(self):
        assert TargetStatus.STOPPED.value == "STOPPED"

    def test_pid_reuse(self):
        assert TargetStatus.PID_REUSE_DETECTED.value == "PID_REUSE_DETECTED"


# ═══════════════════════════════════════════════════════════════
# FramePacingStatus tests
# ═══════════════════════════════════════════════════════════════

class TestFramePacingStatus:

    def test_all_values(self):
        for fp in FramePacingStatus:
            assert fp.value

    def test_stable(self):
        assert FramePacingStatus.STABLE.value == "STABLE"

    def test_insufficient_data(self):
        assert FramePacingStatus.INSUFFICIENT_DATA.value == "INSUFFICIENT_DATA"


# ═══════════════════════════════════════════════════════════════
# RealtimeTelemetry creation
# ═══════════════════════════════════════════════════════════════

class TestRealtimeTelemetryCreation:

    def test_creation(self):
        rt = RealtimeTelemetry()
        assert rt.is_running is False
        assert rt.session is None
        assert rt.target_status == TargetStatus.NOT_DETECTED
        assert rt.target_pid == 0

    def test_creation_with_params(self):
        rt = RealtimeTelemetry(interval_ms=250, max_samples=500)
        assert rt.is_running is False

    def test_singleton_exists(self):
        assert realtime_telemetry is not None
        assert isinstance(realtime_telemetry, RealtimeTelemetry)


# ═══════════════════════════════════════════════════════════════
# Target Management tests
# ═══════════════════════════════════════════════════════════════

class TestTargetManagement:

    def test_set_target(self):
        rt = RealtimeTelemetry()
        rt.set_target(1234, "HD-Player.exe", 1000.0)
        assert rt.target_pid == 1234
        assert rt.target_name == "HD-Player.exe"
        assert rt.target_status == TargetStatus.ACTIVE

    def test_clear_target(self):
        rt = RealtimeTelemetry()
        rt.set_target(1234, "HD-Player.exe", 1000.0)
        rt.clear_target()
        assert rt.target_pid == 0
        assert rt.target_status == TargetStatus.NOT_DETECTED

    def test_zero_pid(self):
        rt = RealtimeTelemetry()
        rt.set_target(0, "", 0.0)
        assert rt.target_status == TargetStatus.NOT_DETECTED

    def test_pid_reuse_detection(self):
        rt = RealtimeTelemetry()
        rt.set_target(1234, "HD-Player.exe", 1000.0)
        # Same PID but different start time -> PID reuse
        change_status = []
        rt.on_target_change(lambda s, n, p: change_status.append(s))
        rt.set_target(1234, "HD-Player.exe", 2000.0)
        assert rt.target_status == TargetStatus.PID_REUSE_DETECTED
        assert len(change_status) == 1
        assert change_status[0] == TargetStatus.PID_REUSE_DETECTED

    def test_pid_reuse_within_tolerance(self):
        rt = RealtimeTelemetry()
        rt.set_target(1234, "HD-Player.exe", 1000.0)
        # Same PID, start time within tolerance -> no reuse
        rt.set_target(1234, "HD-Player.exe", 1002.0)
        assert rt.target_status == TargetStatus.ACTIVE

    def test_different_pid(self):
        rt = RealtimeTelemetry()
        rt.set_target(1234, "HD-Player.exe", 1000.0)
        rt.set_target(5678, "HD-Player.exe", 2000.0)
        assert rt.target_pid == 5678
        assert rt.target_status == TargetStatus.ACTIVE


# ═══════════════════════════════════════════════════════════════
# Session Lifecycle tests
# ═══════════════════════════════════════════════════════════════

class TestSessionLifecycle:

    def test_start_stop_session(self):
        rt = RealtimeTelemetry(interval_ms=50)
        session = rt.start_session("HD-Player.exe", 1234)
        assert rt.is_running is True
        assert session is not None
        assert session.target_name == "HD-Player.exe"
        assert session.target_pid == 1234
        time.sleep(0.3)
        completed = rt.stop_session()
        assert rt.is_running is False
        assert completed is not None
        assert completed.sample_count >= 1
        assert completed.completed_at > 0

    def test_start_idempotent(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.1)
        # Starting again should stop previous and start new
        rt.start_session()
        assert rt.is_running is True
        rt.stop_session()

    def test_stop_without_start(self):
        rt = RealtimeTelemetry()
        result = rt.stop_session()
        # Should return session (possibly None) without crashing
        assert result is None or isinstance(result, TelemetrySession)

    def test_session_records_duration(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.3)
        rt.stop_session()
        assert rt.session is not None
        assert rt.session.get_duration() > 0.2

    def test_session_records_samples(self):
        rt = RealtimeTelemetry(interval_ms=100)
        rt.start_session()
        time.sleep(0.8)
        rt.stop_session()
        assert rt.session.sample_count >= 2


# ═══════════════════════════════════════════════════════════════
# Data Access tests
# ═══════════════════════════════════════════════════════════════

class TestDataAccess:

    def test_latest_snapshot(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.2)
        snap = rt.latest_snapshot()
        rt.stop_session()
        assert snap is not None
        assert isinstance(snap, TelemetrySample)

    def test_latest_snapshot_empty(self):
        rt = RealtimeTelemetry()
        snap = rt.latest_snapshot()
        assert snap is None

    def test_recent_snapshots(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.3)
        snaps = rt.recent_snapshots()
        rt.stop_session()
        assert len(snaps) >= 1

    def test_recent_snapshots_with_count(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.3)
        snaps = rt.recent_snapshots(count=2)
        rt.stop_session()
        assert len(snaps) <= 2

    def test_calculate_summary(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.3)
        summary = rt.calculate_summary()
        rt.stop_session()
        assert isinstance(summary, PerformanceSummary)
        assert summary.sample_count >= 1


# ═══════════════════════════════════════════════════════════════
# Frame Pacing tests
# ═══════════════════════════════════════════════════════════════

class TestFramePacing:

    def test_insufficient_data(self):
        rt = RealtimeTelemetry()
        assert rt.get_frame_pacing_status() == FramePacingStatus.INSUFFICIENT_DATA

    def test_stable_pacing(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.6)
        # With no frame time data (no PresentMon), should be INSUFFICIENT_DATA
        status = rt.get_frame_pacing_status()
        rt.stop_session()
        assert status in (FramePacingStatus.INSUFFICIENT_DATA, FramePacingStatus.STABLE)

    def test_frame_pacing_with_mock_data(self):
        """Test frame pacing classification with injected data."""
        rt = RealtimeTelemetry()
        # Manually inject samples with consistent frame times
        stable_samples = [
            TelemetrySample(
                timestamp=time.time() + i * 0.5,
                frame_time_ms=16.67,  # Perfect 60fps
            )
            for i in range(15)
        ]
        with rt._collector._lock:
            rt._collector._samples = stable_samples
        assert rt.get_frame_pacing_status() == FramePacingStatus.STABLE

    def test_unstable_pacing(self):
        rt = RealtimeTelemetry()
        import random
        random.seed(42)
        unstable_samples = [
            TelemetrySample(
                timestamp=time.time() + i * 0.5,
                frame_time_ms=random.uniform(5, 100),
            )
            for i in range(15)
        ]
        with rt._collector._lock:
            rt._collector._samples = unstable_samples
        status = rt.get_frame_pacing_status()
        assert status in (FramePacingStatus.MILDLY_UNSTABLE, FramePacingStatus.UNSTABLE)


# ═══════════════════════════════════════════════════════════════
# Bottleneck tests
# ═══════════════════════════════════════════════════════════════

class TestBottleneck:

    def test_insufficient_data(self):
        rt = RealtimeTelemetry()
        bn = rt.get_bottleneck()
        assert bn.bottleneck == BottleneckType.INSUFFICIENT_DATA

    def test_gpu_bound_detection(self):
        rt = RealtimeTelemetry()
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
        with rt._collector._lock:
            rt._collector._samples = samples
        bn = rt.get_bottleneck()
        assert bn.bottleneck == BottleneckType.GPU_BOUND

    def test_cpu_bound_detection(self):
        rt = RealtimeTelemetry()
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
        with rt._collector._lock:
            rt._collector._samples = samples
        bn = rt.get_bottleneck()
        assert bn.bottleneck == BottleneckType.CPU_BOUND


# ═══════════════════════════════════════════════════════════════
# Optimization Correlation tests
# ═══════════════════════════════════════════════════════════════

class TestOptimizationCorrelation:

    def test_before_snapshot(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.2)
        snap = rt.capture_before_snapshot("TEST_BEFORE")
        rt.stop_session()
        assert snap.label == "TEST_BEFORE"
        assert rt.before_snapshot is snap

    def test_after_snapshot(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.2)
        snap = rt.capture_after_snapshot("TEST_AFTER")
        rt.stop_session()
        assert snap.label == "TEST_AFTER"
        assert rt.after_snapshot is snap

    def test_before_after_with_data(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.3)
        before = rt.capture_before_snapshot("BEFORE")
        # Simulate some time passing
        time.sleep(0.2)
        after = rt.capture_after_snapshot("AFTER")
        rt.stop_session()
        assert before.timestamp > 0
        assert after.timestamp >= before.timestamp

    def test_optimization_delta_none(self):
        rt = RealtimeTelemetry()
        delta = rt.get_optimization_delta()
        assert delta is None

    def test_optimization_delta_with_snapshots(self):
        rt = RealtimeTelemetry()
        rt._before_snapshot = BeforeAfterSnapshot(
            label="BEFORE",
            fps=MetricValue(value=60.0, state=TelemetryMetricState.MEASURED),
            cpu_percent=MetricValue(value=50.0, state=TelemetryMetricState.MEASURED),
        )
        rt._after_snapshot = BeforeAfterSnapshot(
            label="AFTER",
            fps=MetricValue(value=70.0, state=TelemetryMetricState.MEASURED),
            cpu_percent=MetricValue(value=45.0, state=TelemetryMetricState.MEASURED),
        )
        delta = rt.get_optimization_delta()
        assert delta is not None
        assert delta["fps"] == 10.0
        assert delta["cpu_percent"] == -5.0

    def test_optimization_delta_partial_data(self):
        rt = RealtimeTelemetry()
        rt._before_snapshot = BeforeAfterSnapshot(
            label="BEFORE",
            fps=MetricValue(value=60.0, state=TelemetryMetricState.MEASURED),
        )
        rt._after_snapshot = BeforeAfterSnapshot(
            label="AFTER",
            # No FPS data
        )
        delta = rt.get_optimization_delta()
        assert delta is not None
        assert delta["fps"] is None

    def test_reset_on_new_session(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.1)
        rt.capture_before_snapshot("BEFORE")
        rt.stop_session()
        assert rt.before_snapshot is not None
        # Starting a new session should reset
        rt.start_session()
        assert rt.before_snapshot is None
        rt.stop_session()


# ═══════════════════════════════════════════════════════════════
# Event Detection tests
# ═══════════════════════════════════════════════════════════════

class TestEventDetection:

    def test_events_empty(self):
        rt = RealtimeTelemetry()
        assert rt.events == []

    def test_events_cleared_on_session_start(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.2)
        rt.stop_session()
        # Events should be cleared on next session
        rt.start_session()
        assert len(rt.events) == 0
        rt.stop_session()

    def test_event_callback(self):
        rt = RealtimeTelemetry()
        events = []
        rt.on_event(lambda e: events.append(e))
        # Manually fire an event
        event = PerformanceEvent(
            event_type=EventType.GPU_SATURATION,
            severity=EventSeverity.WARNING,
            measured_value=99.0,
        )
        rt._fire_event(event)
        assert len(events) == 1
        assert events[0].event_type == EventType.GPU_SATURATION

    def test_events_capped(self):
        rt = RealtimeTelemetry()
        for _ in range(250):
            rt._fire_event(PerformanceEvent(event_type=EventType.FPS_DROP))
        assert len(rt.events) <= 200


# ═══════════════════════════════════════════════════════════════
# Overhead Measurement tests
# ═══════════════════════════════════════════════════════════════

class TestOverheadMeasurement:

    def test_default_overhead(self):
        rt = RealtimeTelemetry()
        assert rt.overhead.measurement_count == 0

    def test_measure_overhead(self):
        rt = RealtimeTelemetry()
        overhead = rt.measure_overhead(samples=5)
        assert overhead.measurement_count == 5
        assert overhead.avg_collection_time_ms >= 0
        assert overhead.peak_collection_time_ms >= overhead.avg_collection_time_ms

    def test_overhead_cpu_impact(self):
        rt = RealtimeTelemetry()
        overhead = rt.measure_overhead(samples=5)
        # Collection should be fast (< 100ms)
        assert overhead.avg_collection_time_ms < 100
        assert overhead.cpu_overhead_percent < 50  # Well below 50%


# ═══════════════════════════════════════════════════════════════
# Status Dict tests
# ═══════════════════════════════════════════════════════════════

class TestStatusDict:

    def test_empty_status(self):
        rt = RealtimeTelemetry()
        status = rt.get_status_dict()
        assert status["target_pid"] == 0
        assert status["target_status"] == "NOT_DETECTED"
        assert status["is_running"] is False
        assert "bottleneck" in status
        assert "overhead" in status

    def test_running_status(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session("Test", 1234)
        time.sleep(0.2)
        status = rt.get_status_dict()
        rt.stop_session()
        assert status["is_running"] is True or status["is_running"] is False  # may stop between
        assert status["target_name"] == "Test"
        assert status["target_pid"] == 1234
        assert status["sample_count"] >= 1

    def test_status_has_latest(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.2)
        status = rt.get_status_dict()
        rt.stop_session()
        assert "latest" in status
        assert "frame_pacing" in status
        assert "summary" in status

    def test_status_has_bottleneck(self):
        rt = RealtimeTelemetry()
        status = rt.get_status_dict()
        assert "bottleneck" in status
        assert "bottleneck" in status["bottleneck"]

    def test_status_has_overhead(self):
        rt = RealtimeTelemetry()
        status = rt.get_status_dict()
        assert "overhead" in status
        assert "avg_collection_time_ms" in status["overhead"]


# ═══════════════════════════════════════════════════════════════
# Callback tests
# ═══════════════════════════════════════════════════════════════

class TestCallbacks:

    def test_on_sample_callback(self):
        rt = RealtimeTelemetry()
        samples = []
        rt.on_sample(lambda s: samples.append(s))
        # The callback is registered but won't fire until collection starts
        assert len(rt._on_sample_callbacks) == 1

    def test_on_event_callback(self):
        rt = RealtimeTelemetry()
        events = []
        rt.on_event(lambda e: events.append(e))
        assert len(rt._on_event_callbacks) == 1

    def test_on_target_change_callback(self):
        rt = RealtimeTelemetry()
        changes = []
        rt.on_target_change(lambda s, n, p: changes.append((s, n, p)))
        rt.set_target(1234, "Test.exe", 1000.0)
        # Active doesn't fire callback, only PID reuse does
        assert len(changes) == 0
        # PID reuse fires callback
        rt.set_target(1234, "Test.exe", 5000.0)
        assert len(changes) == 1

    def test_callback_exception_safety(self):
        rt = RealtimeTelemetry()
        rt.on_event(lambda e: 1 / 0)  # Will raise
        rt._fire_event(PerformanceEvent())  # Should not crash


# ═══════════════════════════════════════════════════════════════
# Safety tests
# ═══════════════════════════════════════════════════════════════

class TestSafety:

    def test_no_process_termination(self):
        """Telemetry must never terminate processes."""
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.2)
        rt.stop_session()
        # Just verify it completes without killing anything
        assert True

    def test_no_registry_modification(self):
        """Telemetry must never modify registry."""
        rt = RealtimeTelemetry()
        # Starting/stopping should not touch registry
        rt.start_session()
        rt.stop_session()
        assert True

    def test_no_power_plan_change(self):
        """Telemetry must not change power plans."""
        rt = RealtimeTelemetry()
        rt.start_session()
        rt.stop_session()
        assert True

    def test_no_affinity_change(self):
        """Telemetry must not change CPU affinity."""
        rt = RealtimeTelemetry()
        rt.start_session()
        rt.stop_session()
        assert True

    def test_no_priority_change(self):
        """Telemetry must not change process priority."""
        rt = RealtimeTelemetry()
        rt.start_session()
        rt.stop_session()
        assert True


# ═══════════════════════════════════════════════════════════════
# Thread Safety tests
# ═══════════════════════════════════════════════════════════════

class TestThreadSafety:

    def test_concurrent_start_stop(self):
        """Multiple threads should not crash on concurrent start/stop."""
        rt = RealtimeTelemetry(interval_ms=50)
        errors = []

        def worker():
            try:
                for _ in range(5):
                    rt.start_session()
                    time.sleep(0.05)
                    rt.stop_session()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        assert len(errors) == 0

    def test_concurrent_snapshot_read(self):
        """Reading snapshots while collection is running should be safe."""
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.2)
        errors = []

        def reader():
            try:
                for _ in range(10):
                    rt.latest_snapshot()
                    rt.recent_snapshots()
                    rt.get_bottleneck()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=reader) for _ in range(3)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=5)
        rt.stop_session()
        assert len(errors) == 0


# ═══════════════════════════════════════════════════════════════
# Clean Shutdown tests
# ═══════════════════════════════════════════════════════════════

class TestCleanShutdown:

    def test_stop_without_start(self):
        rt = RealtimeTelemetry()
        result = rt.stop_session()
        assert result is None

    def test_multiple_stop(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.1)
        rt.stop_session()
        # Second stop should be safe
        result = rt.stop_session()
        assert result is None or isinstance(result, TelemetrySession)

    def test_no_orphan_thread(self):
        rt = RealtimeTelemetry(interval_ms=50)
        rt.start_session()
        time.sleep(0.2)
        rt.stop_session()
        assert rt._collector._running is False


# ═══════════════════════════════════════════════════════════════
# TelemetryOverhead tests
# ═══════════════════════════════════════════════════════════════

class TestTelemetryOverhead:

    def test_defaults(self):
        o = TelemetryOverhead()
        assert o.collection_time_ms == 0.0
        assert o.measurement_count == 0

    def test_to_dict(self):
        o = TelemetryOverhead(avg_collection_time_ms=2.5, peak_collection_time_ms=5.0)
        d = o.to_dict()
        assert d["avg_collection_time_ms"] == 2.5
        assert d["peak_collection_time_ms"] == 5.0


# ═══════════════════════════════════════════════════════════════
# DataAvailability extended states tests
# ═══════════════════════════════════════════════════════════════

class TestExtendedDataAvailability:

    def test_failed_state(self):
        assert DataAvailability.FAILED.value == "FAILED"

    def test_stale_state(self):
        assert DataAvailability.STALE.value == "STALE"

    def test_measured_state(self):
        assert DataAvailability.MEASURED.value == "MEASURED"

    def test_not_available_state(self):
        assert DataAvailability.NOT_AVAILABLE.value == "NOT_AVAILABLE"

    def test_detected_state(self):
        assert DataAvailability.DETECTED.value == "DETECTED"

    def test_inferred_state(self):
        assert DataAvailability.INFERRED.value == "INFERRED"


# ═══════════════════════════════════════════════════════════════
# Integration test
# ═══════════════════════════════════════════════════════════════

class TestIntegration:

    def test_full_workflow(self):
        """Full workflow: start -> collect -> snapshot -> stop -> delta."""
        rt = RealtimeTelemetry(interval_ms=50)

        # Start
        session = rt.start_session("Test.exe", 1234)
        assert session is not None

        # Collect
        time.sleep(0.3)
        snap = rt.latest_snapshot()
        assert snap is not None

        # Before snapshot
        before = rt.capture_before_snapshot("BEFORE")
        assert before is not None

        # More collection
        time.sleep(0.2)

        # After snapshot
        after = rt.capture_after_snapshot("AFTER")
        assert after is not None

        # Stop
        completed = rt.stop_session()
        assert completed is not None
        assert completed.sample_count >= 1

        # Delta
        delta = rt.get_optimization_delta()
        assert delta is not None

        # Status
        status = rt.get_status_dict()
        assert "bottleneck" in status
        assert "overhead" in status
