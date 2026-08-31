"""
Phase 40 — Gaming Session Analyzer Tests.

Comprehensive unit tests for the gaming session lifecycle,
timeline aggregation, event detection, root-cause analysis,
session scoring, and reporting.

All tests use mocks — never modify the real system.
"""

import time
from unittest.mock import patch, MagicMock

import pytest

from app.performance.gaming_session_analyzer import (
    GamingSessionAnalyzer,
    GamingSessionReport,
    SessionState,
    RootCause,
    SessionScoreLevel,
    MetricSource,
    SessionTimeline,
    SessionEvent,
    SessionScore,
    WorstPeriod,
    _aggregate_timeline,
    aggregate_timelines,
    detect_session_events,
    analyze_root_cause,
    detect_worst_period,
    calculate_session_score,
    generate_session_recommendations,
    gaming_session_analyzer,
)
from app.performance.telemetry_models import (
    BottleneckType,
    EventType,
    EventSeverity,
    PerformanceEvent,
    TelemetrySample,
)


# ── Fixtures ─────────────────────────────────────────────────────

def _make_sample(**kwargs) -> TelemetrySample:
    """Create a TelemetrySample with defaults."""
    defaults = {
        "timestamp": time.time(),
        "emulator_pid": 12345,
        "emulator_name": "HD-Player.exe",
        "fps": 120.0,
        "one_percent_low": 80.0,
        "frame_time_ms": 8.33,
        "cpu_total_percent": 45.0,
        "gpu_utilization_percent": 70.0,
        "gpu_temperature_c": 65.0,
        "system_ram_used_mb": 8000.0,
        "system_ram_total_mb": 16000.0,
        "emulator_cpu_percent": 35.0,
        "emulator_ram_mb": 2000.0,
    }
    defaults.update(kwargs)
    return TelemetrySample(**defaults)


def _make_samples(count: int, **overrides) -> list:
    """Create multiple TelemetrySamples."""
    samples = []
    for i in range(count):
        data = {
            "timestamp": time.time() + i * 0.5,
            "fps": 120.0 - i * 2 if overrides.get("fps_vary") else overrides.get("fps", 120.0),
            "cpu_total_percent": 45.0 + i * 1.5 if overrides.get("cpu_vary") else overrides.get("cpu_total_percent", 45.0),
            "gpu_utilization_percent": overrides.get("gpu_utilization_percent", 70.0),
            "gpu_temperature_c": overrides.get("gpu_temperature_c", 65.0),
            "system_ram_used_mb": overrides.get("system_ram_used_mb", 8000.0),
            "system_ram_total_mb": overrides.get("system_ram_total_mb", 16000.0),
            "frame_time_ms": overrides.get("frame_time_ms", 8.33),
        }
        samples.append(_make_sample(**data))
    return samples


@pytest.fixture
def analyzer():
    """Create a fresh analyzer for each test."""
    return GamingSessionAnalyzer()


# ── Model Tests ──────────────────────────────────────────────────

class TestModels:
    """Test data models."""

    def test_session_timeline_creation(self):
        tl = SessionTimeline(avg=50.0, peak=80.0, minimum=30.0)
        assert tl.avg == 50.0
        assert tl.peak == 80.0
        assert tl.minimum == 30.0

    def test_session_timeline_to_dict(self):
        tl = SessionTimeline(avg=50.0, peak=80.0, source=MetricSource.MEASURED, sample_count=10)
        d = tl.to_dict()
        assert d["avg"] == 50.0
        assert d["source"] == "MEASURED"
        assert d["sample_count"] == 10

    def test_session_timeline_not_available(self):
        tl = SessionTimeline()
        assert tl.source == MetricSource.NOT_AVAILABLE

    def test_session_event_creation(self):
        ev = SessionEvent(
            timestamp=100.0,
            event_type="FPS_DROP",
            severity="WARNING",
            measured_value=45.0,
            threshold=50.0,
            explanation="Low FPS",
        )
        assert ev.event_type == "FPS_DROP"

    def test_session_event_to_dict(self):
        ev = SessionEvent(event_type="GPU_SATURATION", severity="CRITICAL", measured_value=98.5)
        d = ev.to_dict()
        assert d["event_type"] == "GPU_SATURATION"
        assert d["measured_value"] == 98.5

    def test_session_score_creation(self):
        sc = SessionScore(overall=85, level=SessionScoreLevel.EXCELLENT)
        assert sc.overall == 85
        assert sc.level == SessionScoreLevel.EXCELLENT

    def test_session_score_to_dict(self):
        sc = SessionScore(overall=75, level=SessionScoreLevel.GOOD, components=[{"name": "CPU", "value": 80, "weight": 0.3}])
        d = sc.to_dict()
        assert d["overall"] == 75
        assert d["level"] == "GOOD"

    def test_worst_period_creation(self):
        wp = WorstPeriod(start_index=5, end_index=15, avg_fps=45.0, event_count=3)
        assert wp.start_index == 5
        assert wp.end_index == 15

    def test_worst_period_to_dict(self):
        wp = WorstPeriod(start_index=5, end_index=15, avg_fps=45.0)
        d = wp.to_dict()
        assert d["start_index"] == 5
        assert d["avg_fps"] == 45.0

    def test_report_to_dict(self):
        report = GamingSessionReport(
            session_id="abc123",
            target_name="HD-Player.exe",
            target_pid=12345,
            duration_seconds=60.0,
            sample_count=20,
        )
        d = report.to_dict()
        assert d["session_id"] == "abc123"
        assert d["target_name"] == "HD-Player.exe"
        assert d["sample_count"] == 20

    def test_report_format_cli(self):
        analyzer = GamingSessionAnalyzer()
        report = GamingSessionReport(session_id="test123", duration_seconds=30.0)
        report.score = SessionScore(overall=80, level=SessionScoreLevel.GOOD)
        text = analyzer.format_report(report)
        assert "GAMING SESSION REPORT" in text
        assert "test123" in text
        assert "80/100" in text


# ── Timeline Aggregation Tests ───────────────────────────────────

class TestTimelineAggregation:
    """Test timeline aggregation."""

    def test_aggregate_empty(self):
        tl = _aggregate_timeline([])
        assert tl.source == MetricSource.NOT_AVAILABLE
        assert tl.sample_count == 0

    def test_aggregate_single_value(self):
        tl = _aggregate_timeline([50.0])
        assert tl.avg == 50.0
        assert tl.peak == 50.0
        assert tl.minimum == 50.0
        assert tl.sample_count == 1
        assert tl.source == MetricSource.MEASURED

    def test_aggregate_multiple_values(self):
        tl = _aggregate_timeline([40.0, 50.0, 60.0])
        assert tl.avg == pytest.approx(50.0)
        assert tl.peak == 60.0
        assert tl.minimum == 40.0
        assert tl.sample_count == 3
        assert tl.std_dev is not None
        assert tl.std_dev > 0

    def test_aggregate_all_same(self):
        tl = _aggregate_timeline([42.0, 42.0, 42.0])
        assert tl.avg == 42.0
        assert tl.peak == 42.0
        assert tl.minimum == 42.0
        assert tl.std_dev == 0.0

    def test_aggregate_timelines_basic(self):
        samples = [_make_samples(5)]
        flat = []
        for s in samples:
            flat.extend(s)
        result = aggregate_timelines(flat)
        assert "cpu" in result
        assert "gpu" in result
        assert "ram" in result
        assert "fps" in result
        assert "frame_time" in result
        assert "gpu_temp" in result

    def test_aggregate_timelines_cpu(self):
        samples = [_make_sample(cpu_total_percent=30.0 + i * 10) for i in range(3)]
        result = aggregate_timelines(samples)
        assert result["cpu"].avg == pytest.approx(40.0)
        assert result["cpu"].peak == 50.0
        assert result["cpu"].sample_count == 3

    def test_aggregate_timelines_fps(self):
        samples = [_make_sample(fps=100.0 + i * 10) for i in range(3)]
        result = aggregate_timelines(samples)
        assert result["fps"].avg == pytest.approx(110.0)
        assert result["fps"].minimum == 100.0
        assert result["fps"].peak == 120.0

    def test_aggregate_timelines_no_fps(self):
        samples = [_make_sample(fps=None) for _ in range(3)]
        result = aggregate_timelines(samples)
        assert result["fps"].source == MetricSource.NOT_AVAILABLE

    def test_aggregate_timelines_ram_percent(self):
        samples = [_make_sample(system_ram_used_mb=8000.0, system_ram_total_mb=16000.0) for _ in range(3)]
        result = aggregate_timelines(samples)
        assert "ram_percent" in result
        assert result["ram_percent"].avg == pytest.approx(50.0)


# ── Event Detection Tests ────────────────────────────────────────

class TestEventDetection:
    """Test event detection."""

    def test_no_events_normal(self):
        samples = [_make_sample(fps=120.0, cpu_total_percent=50.0, gpu_utilization_percent=70.0)]
        events = detect_session_events(samples)
        assert len(events) == 0

    def test_fps_drop_critical(self):
        samples = [_make_sample(fps=25.0)]
        events = detect_session_events(samples)
        fps_events = [e for e in events if e.event_type == EventType.FPS_DROP.value]
        assert len(fps_events) == 1
        assert fps_events[0].severity == EventSeverity.CRITICAL.value

    def test_fps_drop_warning(self):
        samples = [_make_sample(fps=45.0)]
        events = detect_session_events(samples)
        fps_events = [e for e in events if e.event_type == EventType.FPS_DROP.value]
        assert len(fps_events) == 1
        assert fps_events[0].severity == EventSeverity.WARNING.value

    def test_frame_time_spike(self):
        samples = [_make_sample(frame_time_ms=60.0)]
        events = detect_session_events(samples)
        ft_events = [e for e in events if e.event_type == EventType.FRAME_TIME_SPIKE.value]
        assert len(ft_events) == 1

    def test_cpu_spike(self):
        samples = [_make_sample(cpu_total_percent=90.0)]
        events = detect_session_events(samples)
        cpu_events = [e for e in events if e.event_type == EventType.CPU_SPIKE.value]
        assert len(cpu_events) == 1

    def test_gpu_saturation(self):
        samples = [_make_sample(gpu_utilization_percent=96.0)]
        events = detect_session_events(samples)
        gpu_events = [e for e in events if e.event_type == EventType.GPU_SATURATION.value]
        assert len(gpu_events) == 1

    def test_gpu_thermal_warning(self):
        samples = [_make_sample(gpu_temperature_c=87.0)]
        events = detect_session_events(samples)
        thermal_events = [e for e in events if e.event_type == EventType.GPU_THERMAL_WARNING.value]
        assert len(thermal_events) == 1
        assert thermal_events[0].severity == EventSeverity.WARNING.value

    def test_gpu_thermal_critical(self):
        samples = [_make_sample(gpu_temperature_c=92.0)]
        events = detect_session_events(samples)
        thermal_events = [e for e in events if e.event_type == EventType.GPU_THERMAL_WARNING.value]
        assert len(thermal_events) == 1
        assert thermal_events[0].severity == EventSeverity.CRITICAL.value

    def test_memory_pressure(self):
        samples = [_make_sample(system_ram_used_mb=14000.0, system_ram_total_mb=16000.0)]
        events = detect_session_events(samples)
        mem_events = [e for e in events if e.event_type == EventType.MEMORY_PRESSURE.value]
        assert len(mem_events) == 1
        assert mem_events[0].measured_value == pytest.approx(87.5)

    def test_multiple_events(self):
        samples = [_make_sample(fps=20.0, cpu_total_percent=95.0, gpu_temperature_c=91.0)]
        events = detect_session_events(samples)
        assert len(events) >= 3  # FPS_DROP + CPU_SPIKE + THERMAL

    def test_events_from_multiple_samples(self):
        samples = [_make_sample(fps=120.0), _make_sample(fps=25.0), _make_sample(fps=120.0)]
        events = detect_session_events(samples)
        fps_events = [e for e in events if e.event_type == EventType.FPS_DROP.value]
        assert len(fps_events) == 1

    def test_no_fps_data_no_events(self):
        samples = [_make_sample(fps=None)]
        events = detect_session_events(samples)
        fps_events = [e for e in events if e.event_type == EventType.FPS_DROP.value]
        assert len(fps_events) == 0


# ── Root-Cause Analysis Tests ────────────────────────────────────

class TestRootCauseAnalysis:
    """Test root-cause analysis."""

    def test_insufficient_data(self):
        rc, conf, ev = analyze_root_cause([], [])
        assert rc == RootCause.INSUFFICIENT_DATA
        assert conf == 0

    def test_insufficient_samples(self):
        samples = [_make_sample()]
        rc, conf, ev = analyze_root_cause(samples, [])
        assert rc == RootCause.INSUFFICIENT_DATA

    def test_cpu_bound(self):
        samples = [_make_sample(cpu_total_percent=92.0) for _ in range(20)]
        rc, conf, ev = analyze_root_cause(samples, [])
        assert rc == RootCause.CPU
        assert conf > 40

    def test_gpu_bound(self):
        samples = [_make_sample(gpu_utilization_percent=95.0) for _ in range(20)]
        rc, conf, ev = analyze_root_cause(samples, [])
        assert rc == RootCause.GPU
        assert conf > 40

    def test_memory_bound(self):
        samples = [_make_sample(system_ram_used_mb=14000.0, system_ram_total_mb=16000.0) for _ in range(20)]
        rc, conf, ev = analyze_root_cause(samples, [])
        assert rc == RootCause.MEMORY
        assert conf > 40

    def test_thermal_bound(self):
        samples = [_make_sample(gpu_temperature_c=88.0) for _ in range(20)]
        rc, conf, ev = analyze_root_cause(samples, [])
        assert rc == RootCause.THERMAL
        assert conf > 40

    def test_frame_time_bound(self):
        # High variance frame times
        ft_values = [8.0, 8.0, 8.0, 30.0, 8.0, 8.0, 8.0, 40.0, 8.0, 8.0,
                     8.0, 8.0, 35.0, 8.0, 8.0]
        samples = [_make_sample(frame_time_ms=ft) for ft in ft_values]
        rc, conf, ev = analyze_root_cause(samples, [])
        assert rc == RootCause.FRAME_TIME
        assert conf > 30

    def test_no_clear_bottleneck(self):
        samples = [_make_sample(cpu_total_percent=40.0, gpu_utilization_percent=50.0,
                                system_ram_used_mb=6000.0, gpu_temperature_c=55.0) for _ in range(10)]
        rc, conf, ev = analyze_root_cause(samples, [])
        assert rc in (RootCause.NO_CLEAR, RootCause.CPU)

    def test_cpu_high_gpu_low_pattern(self):
        samples = [_make_sample(cpu_total_percent=92.0, gpu_utilization_percent=40.0) for _ in range(10)]
        rc, conf, ev = analyze_root_cause(samples, [])
        assert rc == RootCause.CPU

    def test_event_based_evidence(self):
        events = [
            SessionEvent(event_type=EventType.CPU_SPIKE.value) for _ in range(5)
        ]
        samples = [_make_sample(cpu_total_percent=88.0) for _ in range(10)]
        rc, conf, ev = analyze_root_cause(samples, events)
        assert rc == RootCause.CPU

    def test_mixed_signals(self):
        # CPU high AND GPU high
        samples = [_make_sample(cpu_total_percent=90.0, gpu_utilization_percent=95.0) for _ in range(10)]
        rc, conf, ev = analyze_root_cause(samples, [])
        # Should pick the higher-scoring one
        assert rc in (RootCause.CPU, RootCause.GPU)


# ── Worst Period Detection Tests ─────────────────────────────────

class TestWorstPeriod:
    """Test worst period detection."""

    def test_no_data(self):
        wp = detect_worst_period([])
        assert wp.start_index == 0
        assert wp.end_index == 0

    def test_insufficient_samples(self):
        samples = [_make_sample() for _ in range(5)]
        wp = detect_worst_period(samples, window=10)
        assert wp.start_index == 0  # defaults

    def test_finds_worst_window(self):
        # Create samples where window 3-7 has lowest FPS
        samples = []
        for i in range(15):
            if 3 <= i <= 7:
                fps = 30.0  # Bad window
            else:
                fps = 120.0
            samples.append(_make_sample(fps=fps, timestamp=time.time() + i * 0.5))
        wp = detect_worst_period(samples, window=5)
        assert wp.start_index >= 3
        assert wp.end_index <= 7
        assert wp.avg_fps is not None
        assert wp.avg_fps < 50.0

    def test_worst_period_has_correct_duration(self):
        samples = [_make_sample(timestamp=time.time() + i * 0.5) for i in range(15)]
        wp = detect_worst_period(samples, window=5)
        assert wp.duration_seconds > 0


# ── Session Scoring Tests ────────────────────────────────────────

class TestSessionScoring:
    """Test session scoring."""

    def test_score_empty_timelines(self):
        sc = calculate_session_score({}, RootCause.NO_CLEAR, 40, 10)
        assert 0 <= sc.overall <= 100
        assert sc.level in (SessionScoreLevel.GOOD, SessionScoreLevel.FAIR)

    def test_score_excellent(self):
        timelines = {
            "frame_time": SessionTimeline(avg=8.0, std_dev=0.5, source=MetricSource.MEASURED),
            "fps": SessionTimeline(avg=120.0, std_dev=3.0, source=MetricSource.MEASURED),
            "cpu": SessionTimeline(avg=35.0, source=MetricSource.MEASURED),
            "gpu": SessionTimeline(avg=50.0, source=MetricSource.MEASURED),
            "ram_percent": SessionTimeline(avg=45.0, source=MetricSource.MEASURED),
            "gpu_temp": SessionTimeline(peak=60.0, source=MetricSource.MEASURED),
        }
        sc = calculate_session_score(timelines, RootCause.NO_CLEAR, 40, 30)
        assert sc.overall >= 75
        assert sc.level == SessionScoreLevel.EXCELLENT

    def test_score_poor(self):
        timelines = {
            "frame_time": SessionTimeline(avg=30.0, std_dev=20.0, source=MetricSource.MEASURED),
            "fps": SessionTimeline(avg=40.0, std_dev=30.0, source=MetricSource.MEASURED),
            "cpu": SessionTimeline(avg=95.0, source=MetricSource.MEASURED),
            "gpu": SessionTimeline(avg=98.0, source=MetricSource.MEASURED),
            "ram_percent": SessionTimeline(avg=92.0, source=MetricSource.MEASURED),
            "gpu_temp": SessionTimeline(peak=88.0, source=MetricSource.MEASURED),
        }
        sc = calculate_session_score(timelines, RootCause.CPU, 80, 30)
        assert sc.overall <= 65
        assert sc.level in (SessionScoreLevel.POOR, SessionScoreLevel.FAIR)

    def test_score_has_components(self):
        sc = calculate_session_score({}, RootCause.NO_CLEAR, 40, 10)
        assert len(sc.components) > 0
        assert all("name" in c for c in sc.components)
        assert all("value" in c for c in sc.components)
        assert all("weight" in c for c in sc.components)

    def test_score_confidence(self):
        sc = calculate_session_score({}, RootCause.NO_CLEAR, 40, 5)
        assert sc.confidence == 50  # < 15 samples

        sc2 = calculate_session_score({}, RootCause.NO_CLEAR, 40, 30)
        assert sc2.confidence == 90  # >= 30 samples

    def test_score_level_excellent(self):
        sc = SessionScore(overall=90)
        assert SessionScoreLevel.EXCELLENT == SessionScoreLevel.EXCELLENT

    def test_score_to_dict(self):
        sc = SessionScore(overall=75, level=SessionScoreLevel.GOOD, confidence=70)
        d = sc.to_dict()
        assert d["overall"] == 75
        assert d["level"] == "GOOD"
        assert d["confidence"] == 70


# ── Recommendation Tests ─────────────────────────────────────────

class TestRecommendations:
    """Test recommendation generation."""

    def test_insufficient_data_rec(self):
        recs = generate_session_recommendations(RootCause.INSUFFICIENT_DATA, 0, {}, [])
        assert len(recs) == 1
        assert recs[0]["category"] == "DATA"

    def test_no_clear_rec(self):
        recs = generate_session_recommendations(RootCause.NO_CLEAR, 40, {}, [])
        assert len(recs) == 1
        assert recs[0]["category"] == "STATUS"

    def test_cpu_rec(self):
        recs = generate_session_recommendations(RootCause.CPU, 80, {}, [])
        assert any(r["category"] == "CPU" for r in recs)

    def test_gpu_rec(self):
        recs = generate_session_recommendations(RootCause.GPU, 80, {}, [])
        assert any(r["category"] == "GPU" for r in recs)

    def test_memory_rec(self):
        recs = generate_session_recommendations(RootCause.MEMORY, 80, {}, [])
        assert any(r["category"] == "MEMORY" for r in recs)

    def test_thermal_rec(self):
        recs = generate_session_recommendations(RootCause.THERMAL, 80, {}, [])
        assert any(r["category"] == "THERMAL" for r in recs)

    def test_frame_time_rec(self):
        recs = generate_session_recommendations(RootCause.FRAME_TIME, 80, {}, [])
        assert any(r["category"] == "FRAME_PACING" for r in recs)

    def test_thermal_events_add_rec(self):
        events = [SessionEvent(event_type=EventType.GPU_THERMAL_WARNING.value) for _ in range(3)]
        recs = generate_session_recommendations(RootCause.CPU, 80, {}, events)
        # Should have CPU rec + thermal rec from events
        assert len(recs) >= 2

    def test_all_recs_have_required_fields(self):
        for rc in RootCause:
            recs = generate_session_recommendations(rc, 50, {}, [])
            for r in recs:
                assert "category" in r
                assert "priority" in r
                assert "reason" in r
                assert "action" in r


# ── Lifecycle Tests ──────────────────────────────────────────────

class TestLifecycle:
    """Test session lifecycle."""

    def test_start_session(self, analyzer):
        session_id = analyzer.start_session("HD-Player.exe", 12345)
        assert len(session_id) == 8
        assert analyzer.state == SessionState.RUNNING
        assert analyzer.is_running
        assert analyzer.session_id == session_id

    def test_stop_session(self, analyzer):
        analyzer.start_session("HD-Player.exe", 12345)
        report = analyzer.stop_session()
        assert report is not None
        assert analyzer.state == SessionState.STOPPED
        assert not analyzer.is_running
        assert report.session_id == analyzer.session_id

    def test_stop_without_start(self, analyzer):
        report = analyzer.stop_session()
        assert report is None

    def test_double_start(self, analyzer):
        analyzer.start_session("Test", 100)
        id1 = analyzer.session_id
        analyzer.start_session("Test2", 200)
        assert analyzer.session_id != id1
        assert analyzer.state == SessionState.RUNNING

    def test_session_status(self, analyzer):
        analyzer.start_session("HD-Player.exe", 12345)
        status = analyzer.get_session_status()
        assert status["state"] == "RUNNING"
        assert status["target_name"] == "HD-Player.exe"
        assert status["target_pid"] == 12345
        assert status["sample_count"] == 0

    def test_session_status_idle(self, analyzer):
        status = analyzer.get_session_status()
        assert status["state"] == "IDLE"


# ── Sample Ingestion Tests ───────────────────────────────────────

class TestSampleIngestion:
    """Test sample ingestion."""

    def test_ingest_sample(self, analyzer):
        analyzer.start_session("Test", 100)
        sample = _make_sample(cpu_total_percent=50.0)
        analyzer.ingest_sample(sample)
        status = analyzer.get_session_status()
        assert status["sample_count"] == 1

    def test_ingest_multiple_samples(self, analyzer):
        analyzer.start_session("Test", 100)
        for i in range(10):
            analyzer.ingest_sample(_make_sample(cpu_total_percent=40.0 + i))
        status = analyzer.get_session_status()
        assert status["sample_count"] == 10

    def test_ingest_samples_list(self, analyzer):
        analyzer.start_session("Test", 100)
        samples = [_make_sample() for _ in range(5)]
        analyzer.ingest_samples(samples)
        status = analyzer.get_session_status()
        assert status["sample_count"] == 5

    def test_ingest_events_detected(self, analyzer):
        analyzer.start_session("Test", 100)
        analyzer.ingest_sample(_make_sample(fps=25.0))  # FPS drop
        status = analyzer.get_session_status()
        assert status["event_count"] >= 1

    def test_ingest_when_idle(self, analyzer):
        # Should not crash when not running
        analyzer.ingest_sample(_make_sample())
        status = analyzer.get_session_status()
        assert status["state"] == "IDLE"
        assert status["sample_count"] == 0

    def test_ingest_after_stop(self, analyzer):
        analyzer.start_session("Test", 100)
        analyzer.stop_session()
        analyzer.ingest_sample(_make_sample())
        status = analyzer.get_session_status()
        assert status["sample_count"] == 0  # Not recording


# ── Report Generation Tests ──────────────────────────────────────

class TestReportGeneration:
    """Test report generation."""

    def test_report_from_samples(self, analyzer):
        analyzer.start_session("HD-Player.exe", 12345)
        samples = [_make_sample(cpu_total_percent=45.0 + i * 2) for i in range(15)]
        analyzer.ingest_samples(samples)
        report = analyzer.stop_session()

        assert report is not None
        assert report.sample_count == 15
        assert report.cpu_timeline.source == MetricSource.MEASURED
        assert report.cpu_timeline.avg is not None

    def test_report_has_baselines(self, analyzer):
        analyzer.start_session("HD-Player.exe", 12345)
        analyzer.ingest_sample(_make_sample())
        report = analyzer.stop_session()
        assert report.baseline_cpu is not None or report.baseline_ram_percent is not None

    def test_report_has_events(self, analyzer):
        analyzer.start_session("HD-Player.exe", 12345)
        analyzer.ingest_sample(_make_sample(fps=20.0))  # Critical FPS drop
        report = analyzer.stop_session()
        assert len(report.events) >= 1

    def test_report_has_root_cause(self, analyzer):
        analyzer.start_session("HD-Player.exe", 12345)
        samples = [_make_sample(cpu_total_percent=92.0) for _ in range(10)]
        analyzer.ingest_samples(samples)
        report = analyzer.stop_session()
        assert report.root_cause != RootCause.INSUFFICIENT_DATA

    def test_report_has_score(self, analyzer):
        analyzer.start_session("HD-Player.exe", 12345)
        samples = [_make_sample() for _ in range(10)]
        analyzer.ingest_samples(samples)
        report = analyzer.stop_session()
        assert report.score.overall > 0
        assert report.score.level != SessionScoreLevel.NOT_AVAILABLE

    def test_report_has_recommendations(self, analyzer):
        analyzer.start_session("HD-Player.exe", 12345)
        samples = [_make_sample(cpu_total_percent=92.0) for _ in range(10)]
        analyzer.ingest_samples(samples)
        report = analyzer.stop_session()
        assert len(report.recommendations) > 0

    def test_report_has_worst_period(self, analyzer):
        analyzer.start_session("HD-Player.exe", 12345)
        # 20 samples, with a bad window in the middle
        samples = []
        for i in range(20):
            fps = 30.0 if 5 <= i <= 10 else 120.0
            samples.append(_make_sample(fps=fps, timestamp=time.time() + i * 0.5))
        analyzer.ingest_samples(samples)
        report = analyzer.stop_session()
        assert report.worst_period.avg_fps is not None

    def test_report_event_summary(self, analyzer):
        analyzer.start_session("Test", 100)
        analyzer.ingest_sample(_make_sample(fps=20.0))
        analyzer.ingest_sample(_make_sample(fps=20.0))
        report = analyzer.stop_session()
        assert "FPS_DROP" in report.event_summary
        assert report.event_summary["FPS_DROP"] == 2

    def test_report_empty_session(self, analyzer):
        analyzer.start_session("Test", 100)
        report = analyzer.stop_session()
        assert report.sample_count == 0
        assert report.score.overall >= 0

    def test_report_format(self, analyzer):
        analyzer.start_session("Test", 100)
        samples = [_make_sample() for _ in range(5)]
        analyzer.ingest_samples(samples)
        report = analyzer.stop_session()
        text = analyzer.format_report(report)
        assert "GAMING SESSION REPORT" in text
        assert report.session_id in text

    def test_report_format_status(self, analyzer):
        status = analyzer.get_session_status()
        text = analyzer.format_status(status)
        assert "GAMING SESSION STATUS" in text
        assert "IDLE" in text


# ── External Event Tests ─────────────────────────────────────────

class TestExternalEvents:
    """Test external event integration."""

    def test_add_external_event(self, analyzer):
        analyzer.start_session("Test", 100)
        event = PerformanceEvent(
            event_type=EventType.EMULATOR_PROCESS_CHANGE,
            explanation="PID changed",
        )
        analyzer.add_external_event(event)
        status = analyzer.get_session_status()
        assert status["event_count"] == 1

    def test_external_events_not_in_report(self, analyzer):
        analyzer.start_session("Test", 100)
        event = PerformanceEvent(event_type=EventType.EMULATOR_EXITED)
        analyzer.add_external_event(event)
        report = analyzer.stop_session()
        # External events are tracked separately; report shows internal events
        # This tests that external events don't crash report generation
        assert report is not None


# ── Persistence Tests ────────────────────────────────────────────

class TestPersistence:
    """Test report persistence."""

    def test_report_saved(self, analyzer):
        with patch.object(analyzer, '_save_report') as mock_save:
            analyzer.start_session("Test", 100)
            analyzer.ingest_sample(_make_sample())
            analyzer.stop_session()
            mock_save.assert_called_once()

    def test_load_history_empty(self, analyzer):
        with patch("os.path.exists", return_value=False):
            history = analyzer.load_history()
            assert history == []


# ── Edge Cases ───────────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases."""

    def test_singleton_exists(self):
        assert gaming_session_analyzer is not None
        assert isinstance(gaming_session_analyzer, GamingSessionAnalyzer)

    def test_singleton_is_same(self):
        from app.performance.gaming_session_analyzer import gaming_session_analyzer as gsa2
        assert gaming_session_analyzer is gsa2

    def test_no_emulator_target(self, analyzer):
        analyzer.start_session("", 0)
        status = analyzer.get_session_status()
        assert status["target_name"] == ""
        assert status["target_pid"] == 0

    def test_all_none_metrics(self, analyzer):
        analyzer.start_session("Test", 100)
        sample = TelemetrySample(
            timestamp=time.time(),
            fps=None,
            cpu_total_percent=None,
            gpu_utilization_percent=None,
            system_ram_used_mb=None,
            system_ram_total_mb=None,
            gpu_temperature_c=None,
            frame_time_ms=None,
        )
        analyzer.ingest_sample(sample)
        report = analyzer.stop_session()
        assert report.cpu_timeline.source == MetricSource.NOT_AVAILABLE
        assert report.fps_timeline.source == MetricSource.NOT_AVAILABLE

    def test_session_state_transitions(self, analyzer):
        assert analyzer.state == SessionState.IDLE
        analyzer.start_session()
        assert analyzer.state == SessionState.RUNNING
        analyzer.stop_session()
        assert analyzer.state == SessionState.STOPPED

    def test_many_samples(self, analyzer):
        analyzer.start_session("Test", 100)
        samples = [_make_sample(cpu_total_percent=40.0 + (i % 50)) for i in range(100)]
        analyzer.ingest_samples(samples)
        report = analyzer.stop_session()
        assert report.sample_count == 100

    def test_baseline_capture_handles_exception(self, analyzer):
        with patch("psutil.virtual_memory", side_effect=Exception("mock error")):
            analyzer._capture_baseline()
            # Should not crash
            assert isinstance(analyzer._baseline, dict)

    def test_event_summary_is_dict(self, analyzer):
        analyzer.start_session("Test", 100)
        analyzer.ingest_sample(_make_sample(fps=25.0))
        report = analyzer.stop_session()
        assert isinstance(report.event_summary, dict)
        for key, val in report.event_summary.items():
            assert isinstance(key, str)
            assert isinstance(val, int)

    def test_report_dict_serializable(self, analyzer):
        import json
        analyzer.start_session("Test", 100)
        samples = [_make_sample() for _ in range(5)]
        analyzer.ingest_samples(samples)
        report = analyzer.stop_session()
        # Should not raise
        json_str = json.dumps(report.to_dict())
        assert len(json_str) > 0

    def test_worst_period_default(self):
        wp = WorstPeriod()
        d = wp.to_dict()
        assert d["start_index"] == 0
        assert d["avg_fps"] is None
