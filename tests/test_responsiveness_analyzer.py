"""
Tests for Phase 38 — Input-to-Frame Correlation & Responsiveness Analyzer.

Uses mocks for hardware-dependent tests.
"""

import time
import pytest
from unittest.mock import patch, MagicMock

from app.input.responsiveness_analyzer import (
    ResponsivenessState,
    ResponsivenessSession,
    InputTimeline,
    FrameTimeline,
    LatencyBreakdown,
    CorrelationResult,
    DisplayAnalysis,
    ResponsivenessScore,
    TargetStatus,
    CorrelationStrength,
    DisplayMatch,
    ConfidenceLevel,
    analyze_input_timeline,
    analyze_frame_timeline,
    analyze_display,
    calculate_latency_breakdown,
    correlate_input_frame,
    classify_responsiveness,
    calculate_responsiveness_score,
    generate_responsiveness_recommendations,
    analyze_responsiveness,
    format_responsiveness,
    MIN_SAMPLES,
)
from app.input.input_diagnostics import (
    InputDiagnosticSession,
    PollingMeasurement,
    LatencyEstimate,
    MetricState,
    PollingConsistency,
    PointerConfig,
    PointerAssessment,
)
from app.performance.telemetry_models import TelemetrySample


# ── Helpers ──────────────────────────────────────────────────────

def make_sample(
    cpu=None, gpu=None, ram_used=None, ram_total=None,
    fps=None, ft=None, gpu_temp=None, emu_pid=1234,
):
    return TelemetrySample(
        timestamp=time.time(),
        emulator_pid=emu_pid,
        emulator_name="HD-Player.exe",
        fps=fps,
        frame_time_ms=ft,
        cpu_total_percent=cpu,
        gpu_utilization_percent=gpu,
        gpu_temperature_c=gpu_temp,
        system_ram_used_mb=ram_used,
        system_ram_total_mb=ram_total,
        system_ram_available_mb=(ram_total - ram_used) if ram_used and ram_total else None,
    )


def make_samples(n=10, **kwargs):
    return [make_sample(**kwargs) for _ in range(n)]


def make_input_session(polling_state=MetricState.NOT_AVAILABLE, cv=0.0, rate=0.0):
    """Create a mock input diagnostic session."""
    session = InputDiagnosticSession(target_name="HD-Player.exe", target_pid=1234)
    session.pointer_config = PointerConfig(
        pointer_speed=6, enhance_pointer_precision=False,
        state=MetricState.MEASURED, assessment=PointerAssessment.CONSISTENT,
    )
    session.latency = LatencyEstimate(
        display_latency_ms=6.9, estimated_total_ms=7.5,
        state=MetricState.INFERRED,
    )
    session.polling = PollingMeasurement(
        duration_seconds=5.0, total_events=500,
        observed_rate_hz=rate, coefficient_of_variation=cv,
        consistency=PollingConsistency.HIGH if cv < 0.10 else (
            PollingConsistency.MODERATE if cv < 0.25 else PollingConsistency.LOW
        ),
        state=polling_state,
    )
    session.display_refresh_hz = 144
    return session


# ── Model Tests ──────────────────────────────────────────────────

class TestInputTimeline:
    def test_defaults(self):
        t = InputTimeline()
        assert t.state == MetricState.NOT_AVAILABLE
        assert t.consistency == "INSUFFICIENT_DATA"

    def test_to_dict(self):
        t = InputTimeline(observed_rate_hz=1000.0, consistency="STABLE")
        d = t.to_dict()
        assert d["observed_rate_hz"] == 1000.0


class TestFrameTimeline:
    def test_defaults(self):
        t = FrameTimeline()
        assert t.state == MetricState.NOT_AVAILABLE

    def test_to_dict(self):
        t = FrameTimeline(avg_fps=120.0, frame_time_cv=0.15, consistency="STABLE")
        d = t.to_dict()
        assert d["avg_fps"] == 120.0


class TestLatencyBreakdown:
    def test_defaults(self):
        b = LatencyBreakdown()
        assert b.total_state == MetricState.NOT_AVAILABLE

    def test_to_dict(self):
        b = LatencyBreakdown(display_ms=6.9, estimated_total_ms=7.5, total_state=MetricState.INFERRED)
        d = b.to_dict()
        assert d["estimated_total_ms"] == 7.5


class TestCorrelationResult:
    def test_defaults(self):
        r = CorrelationResult()
        assert r.strength == CorrelationStrength.INSUFFICIENT_DATA


class TestDisplayAnalysis:
    def test_defaults(self):
        d = DisplayAnalysis()
        assert d.state == MetricState.NOT_AVAILABLE

    def test_to_dict(self):
        d = DisplayAnalysis(refresh_hz=144, frame_interval_ms=6.94, match=DisplayMatch.GOOD_MATCH)
        d2 = d.to_dict()
        assert d2["refresh_hz"] == 144


class TestResponsivenessScore:
    def test_defaults(self):
        s = ResponsivenessScore()
        assert s.overall == 0
        assert s.level == "NOT_AVAILABLE"

    def test_to_dict(self):
        s = ResponsivenessScore(overall=80, level="GOOD", state=MetricState.MEASURED)
        d = s.to_dict()
        assert d["overall"] == 80


class TestResponsivenessSession:
    def test_creation(self):
        s = ResponsivenessSession(target_name="HD-Player.exe", target_pid=1234)
        assert s.target_name == "HD-Player.exe"
        assert s.state == ResponsivenessState.INSUFFICIENT_DATA

    def test_to_dict(self):
        s = ResponsivenessSession()
        d = s.to_dict()
        assert "state" in d
        assert "score" in d


# ── Input Timeline Analysis ──────────────────────────────────────

class TestInputTimelineAnalysis:
    def test_no_session(self):
        t = analyze_input_timeline(None)
        assert t.state == MetricState.NOT_AVAILABLE

    def test_not_measured(self):
        session = InputDiagnosticSession()
        t = analyze_input_timeline(session)
        assert t.state == MetricState.NOT_AVAILABLE

    def test_stable_input(self):
        session = make_input_session(polling_state=MetricState.MEASURED, cv=0.05, rate=1000)
        t = analyze_input_timeline(session)
        assert t.state == MetricState.MEASURED
        assert t.consistency == "STABLE"
        assert t.observed_rate_hz == 1000.0

    def test_unstable_input(self):
        session = make_input_session(polling_state=MetricState.MEASURED, cv=0.40, rate=500)
        t = analyze_input_timeline(session)
        assert t.consistency == "UNSTABLE"

    def test_mildly_unstable(self):
        session = make_input_session(polling_state=MetricState.MEASURED, cv=0.15, rate=500)
        t = analyze_input_timeline(session)
        assert t.consistency == "MILDLY_UNSTABLE"


# ── Frame Timeline Analysis ──────────────────────────────────────

class TestFrameTimelineAnalysis:
    def test_no_data(self):
        t = analyze_frame_timeline([])
        assert t.state == MetricState.NOT_AVAILABLE

    def test_too_few_samples(self):
        t = analyze_frame_timeline(make_samples(2, ft=8.0))
        assert t.state == MetricState.NOT_AVAILABLE

    def test_stable_frames(self):
        samples = make_samples(10, ft=8.3, fps=120)
        t = analyze_frame_timeline(samples)
        assert t.state == MetricState.MEASURED
        assert t.consistency == "STABLE"
        assert t.avg_fps == 120.0

    def test_unstable_frames(self):
        samples = []
        for i in range(10):
            ft = 8.0 + (50.0 if i % 3 == 0 else 0.0)  # Large spikes > 2x avg
            samples.append(make_sample(ft=ft, fps=1000 / ft))
        t = analyze_frame_timeline(samples)
        assert t.consistency in ("UNSTABLE", "MILDLY_UNSTABLE")
        assert t.frame_spikes > 0

    def test_one_percent_low(self):
        ft_vals = [8.0] * 90 + [20.0] * 10
        samples = [make_sample(ft=ft, fps=1000 / ft) for ft in ft_vals]
        t = analyze_frame_timeline(samples)
        assert t.one_percent_low is not None
        assert t.one_percent_low > 0


# ── Display Analysis ─────────────────────────────────────────────

class TestDisplayAnalysis:
    def test_no_refresh(self):
        d = analyze_display(0)
        # May still detect via display_monitor
        assert d.refresh_hz >= 0

    def test_144hz(self):
        d = analyze_display(144)
        assert d.refresh_hz == 144
        assert d.frame_interval_ms == pytest.approx(6.94, abs=0.01)

    def test_good_match(self):
        ft = FrameTimeline(avg_frame_time_ms=7.0)
        d = analyze_display(144, ft)
        assert d.match == DisplayMatch.GOOD_MATCH

    def test_below_refresh(self):
        ft = FrameTimeline(avg_frame_time_ms=25.0)
        d = analyze_display(144, ft)
        assert d.match == DisplayMatch.FRAME_RATE_BELOW_REFRESH


# ── Latency Breakdown ───────────────────────────────────────────

class TestLatencyBreakdown:
    def test_basic(self):
        b = calculate_latency_breakdown(display_refresh_hz=144, cpu_percent=40)
        assert b.display_ms > 0
        assert b.scheduling_ms > 0
        assert b.estimated_total_ms > 0
        assert b.total_state == MetricState.INFERRED

    def test_high_cpu_increases_scheduling(self):
        low = calculate_latency_breakdown(display_refresh_hz=144, cpu_percent=30)
        high = calculate_latency_breakdown(display_refresh_hz=144, cpu_percent=90)
        assert high.scheduling_ms > low.scheduling_ms

    def test_with_frame_time(self):
        b = calculate_latency_breakdown(display_refresh_hz=144, frame_time_ms=10.0)
        assert b.frame_ms == 10.0
        assert b.frame_state == MetricState.MEASURED


# ── Correlation ──────────────────────────────────────────────────

class TestCorrelation:
    def test_insufficient_data(self):
        inp = InputTimeline(state=MetricState.NOT_AVAILABLE)
        fr = FrameTimeline(state=MetricState.NOT_AVAILABLE)
        r = correlate_input_frame(inp, fr, [])
        assert r.strength == CorrelationStrength.INSUFFICIENT_DATA

    def test_both_stable(self):
        inp = InputTimeline(state=MetricState.MEASURED, coefficient_of_variation=0.05)
        fr = FrameTimeline(state=MetricState.MEASURED, frame_time_cv=0.08)
        r = correlate_input_frame(inp, fr, [])
        assert r.strength == CorrelationStrength.NO_CLEAR_CORRELATION

    def test_input_unstable_frame_stable(self):
        inp = InputTimeline(state=MetricState.MEASURED, coefficient_of_variation=0.40)
        fr = FrameTimeline(state=MetricState.MEASURED, frame_time_cv=0.08)
        r = correlate_input_frame(inp, fr, [])
        assert r.strength == CorrelationStrength.POSSIBLY_RELATED

    def test_input_stable_frame_unstable(self):
        inp = InputTimeline(state=MetricState.MEASURED, coefficient_of_variation=0.05)
        fr = FrameTimeline(state=MetricState.MEASURED, frame_time_cv=0.40)
        r = correlate_input_frame(inp, fr, [])
        assert r.strength == CorrelationStrength.NO_CLEAR_CORRELATION

    def test_both_unstable(self):
        inp = InputTimeline(state=MetricState.MEASURED, coefficient_of_variation=0.40)
        fr = FrameTimeline(state=MetricState.MEASURED, frame_time_cv=0.40)
        r = correlate_input_frame(inp, fr, [])
        assert r.strength == CorrelationStrength.POSSIBLY_RELATED


# ── Classification ───────────────────────────────────────────────

class TestClassification:
    def test_insufficient_data(self):
        s, c, ev, ex = classify_responsiveness(
            InputTimeline(), FrameTimeline(), 0, 0, 0, None,
            CorrelationResult(),
        )
        assert s == ResponsivenessState.INSUFFICIENT_DATA

    def test_responsive(self):
        s, c, ev, ex = classify_responsiveness(
            InputTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            FrameTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            30, 40, 55, 65,
            CorrelationResult(strength=CorrelationStrength.NO_CLEAR_CORRELATION),
        )
        assert s == ResponsivenessState.RESPONSIVE

    def test_cpu_limited(self):
        s, c, ev, ex = classify_responsiveness(
            InputTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            FrameTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            95, 40, 55, 65,
            CorrelationResult(),
        )
        assert s == ResponsivenessState.CPU_SCHEDULING_LIMITED

    def test_memory_limited(self):
        s, c, ev, ex = classify_responsiveness(
            InputTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            FrameTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            50, 40, 92, 65,
            CorrelationResult(),
        )
        assert s == ResponsivenessState.MEMORY_LIMITED

    def test_gpu_limited(self):
        s, c, ev, ex = classify_responsiveness(
            InputTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            FrameTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            40, 95, 55, 65,
            CorrelationResult(),
        )
        assert s == ResponsivenessState.GPU_LIMITED

    def test_thermal_limited(self):
        s, c, ev, ex = classify_responsiveness(
            InputTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            FrameTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            50, 60, 55, 90,
            CorrelationResult(),
        )
        assert s == ResponsivenessState.THERMAL_LIMITED

    def test_frame_limited(self):
        s, c, ev, ex = classify_responsiveness(
            InputTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            FrameTimeline(state=MetricState.MEASURED, consistency="UNSTABLE"),
            50, 40, 55, 65,
            CorrelationResult(),
        )
        assert s == ResponsivenessState.FRAME_LIMITED

    def test_input_limited(self):
        s, c, ev, ex = classify_responsiveness(
            InputTimeline(state=MetricState.MEASURED, consistency="UNSTABLE"),
            FrameTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            50, 40, 55, 65,
            CorrelationResult(),
        )
        assert s == ResponsivenessState.INPUT_LIMITED

    def test_multi_resource(self):
        s, c, ev, ex = classify_responsiveness(
            InputTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            FrameTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            95, 40, 92, 90,
            CorrelationResult(),
        )
        # Multiple resources are under pressure — may be classified as
        # the highest individual or as multi-resource
        assert s in (ResponsivenessState.MULTI_RESOURCE_LIMITED,
                     ResponsivenessState.CPU_SCHEDULING_LIMITED,
                     ResponsivenessState.MEMORY_LIMITED,
                     ResponsivenessState.THERMAL_LIMITED)


# ── Responsiveness Score ─────────────────────────────────────────

class TestResponsivenessScore:
    def test_no_data(self):
        s = calculate_responsiveness_score(
            InputTimeline(), FrameTimeline(), 0, 0, 0, None, DisplayAnalysis(), LatencyBreakdown(),
        )
        assert s.overall > 0  # Should still produce a score from defaults
        assert s.level in ("EXCELLENT", "GOOD", "FAIR", "POOR")

    def test_good_system(self):
        s = calculate_responsiveness_score(
            InputTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            FrameTimeline(state=MetricState.MEASURED, frame_time_cv=0.08),
            30, 40, 55, 65,
            DisplayAnalysis(refresh_hz=144, state=MetricState.MEASURED, match=DisplayMatch.GOOD_MATCH),
            LatencyBreakdown(display_ms=6.9, scheduling_ms=0.5, estimated_total_ms=7.4, total_state=MetricState.INFERRED),
        )
        assert s.overall >= 70
        assert s.level in ("EXCELLENT", "GOOD")
        assert len(s.components) == 8

    def test_bad_system(self):
        s = calculate_responsiveness_score(
            InputTimeline(state=MetricState.MEASURED, consistency="UNSTABLE"),
            FrameTimeline(state=MetricState.MEASURED, frame_time_cv=0.50),
            95, 95, 95, 92,
            DisplayAnalysis(refresh_hz=60, state=MetricState.MEASURED, match=DisplayMatch.FRAME_RATE_BELOW_REFRESH),
            LatencyBreakdown(display_ms=16.7, scheduling_ms=2.0, estimated_total_ms=18.7, total_state=MetricState.INFERRED),
        )
        assert s.overall <= 50
        assert s.level in ("FAIR", "POOR")

    def test_components_have_weights(self):
        s = calculate_responsiveness_score(
            InputTimeline(state=MetricState.MEASURED, consistency="STABLE"),
            FrameTimeline(state=MetricState.MEASURED, frame_time_cv=0.10),
            50, 50, 60, 70,
            DisplayAnalysis(refresh_hz=144, state=MetricState.MEASURED),
            LatencyBreakdown(estimated_total_ms=8.0, total_state=MetricState.INFERRED),
        )
        total_weight = sum(c["weight"] for c in s.components)
        assert total_weight == pytest.approx(1.0, abs=0.01)


# ── Recommendations ──────────────────────────────────────────────

class TestRecommendations:
    def test_responsive(self):
        recs = generate_responsiveness_recommendations(
            ResponsivenessState.RESPONSIVE, InputTimeline(), FrameTimeline(), 50, 30,
            CorrelationResult(),
        )
        assert len(recs) > 0
        assert recs[0]["priority"] == "LOW"

    def test_input_limited(self):
        recs = generate_responsiveness_recommendations(
            ResponsivenessState.INPUT_LIMITED, InputTimeline(), FrameTimeline(), 50, 30,
            CorrelationResult(),
        )
        assert any(r["category"] == "INPUT" for r in recs)

    def test_frame_limited(self):
        recs = generate_responsiveness_recommendations(
            ResponsivenessState.FRAME_LIMITED, InputTimeline(), FrameTimeline(), 50, 30,
            CorrelationResult(),
        )
        assert any(r["category"] == "FRAME_PACING" for r in recs)

    def test_memory_limited(self):
        recs = generate_responsiveness_recommendations(
            ResponsivenessState.MEMORY_LIMITED, InputTimeline(), FrameTimeline(), 92, 30,
            CorrelationResult(),
        )
        assert any(r["category"] == "MEMORY" for r in recs)


# ── Main Analyzer ────────────────────────────────────────────────

class TestAnalyzeResponsiveness:
    def test_basic(self):
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        result = analyze_responsiveness(samples)
        assert result.state != ResponsivenessState.INSUFFICIENT_DATA
        assert result.score.overall > 0

    def test_with_input_session(self):
        input_session = make_input_session(polling_state=MetricState.MEASURED, cv=0.05, rate=1000)
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        result = analyze_responsiveness(samples, input_session)
        assert result.input_timeline.state == MetricState.MEASURED
        assert result.input_session is not None

    def test_with_target(self):
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        result = analyze_responsiveness(samples, target_name="HD-Player.exe", target_pid=1234)
        assert result.target_name == "HD-Player.exe"
        assert result.target_status == TargetStatus.ACTIVE

    def test_no_target(self):
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        result = analyze_responsiveness(samples)
        assert result.target_status == TargetStatus.NOT_DETECTED


# ── CLI Formatting ───────────────────────────────────────────────

class TestFormatResponsiveness:
    def test_format(self):
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        result = analyze_responsiveness(samples, target_name="HD-Player.exe", target_pid=1234)
        output = format_responsiveness(result)
        assert "RESPONSIVENESS ANALYSIS" in output
        assert "HD-Player.exe" in output

    def test_format_empty(self):
        result = ResponsivenessSession()
        output = format_responsiveness(result)
        assert "RESPONSIVENESS ANALYSIS" in output


# ── Safety ───────────────────────────────────────────────────────

class TestSafety:
    def test_no_system_modification(self):
        """Verify analyzer does not modify system state."""
        import inspect
        for func in [analyze_input_timeline, analyze_frame_timeline,
                     classify_responsiveness, calculate_responsiveness_score]:
            source = inspect.getsource(func)
            assert "terminate" not in source.lower()
            assert "write_registry" not in source.lower()
            assert "os.remove" not in source.lower()

    def test_estimated_values_labeled(self):
        result = analyze_responsiveness(
            make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000),
        )
        # Latency should be labeled as estimated
        assert result.latency.total_state in (MetricState.INFERRED, MetricState.NOT_AVAILABLE)


# ── Deterministic ────────────────────────────────────────────────

class TestDeterministic:
    def test_same_input_same_output(self):
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        r1 = analyze_responsiveness(samples)
        r2 = analyze_responsiveness(samples)
        assert r1.state == r2.state
        assert r1.score.overall == r2.score.overall

    def test_empty_always_insufficient(self):
        for _ in range(3):
            result = analyze_responsiveness([])
            assert result.state == ResponsivenessState.INSUFFICIENT_DATA


# ── Bottleneck Differentiation ───────────────────────────────────

class TestBottleneckDifferentiation:
    def test_case_a_memory_frame(self):
        """Case A: Input stable, frame unstable, RAM high."""
        samples = make_samples(10, cpu=50, gpu=40, ram_used=15000, ram_total=16000)
        result = analyze_responsiveness(samples)
        assert result.state in (ResponsivenessState.MEMORY_LIMITED, ResponsivenessState.MULTI_RESOURCE_LIMITED)

    def test_case_b_input_inconsistent(self):
        """Case B: Input inconsistent, frames stable, resources OK."""
        input_session = make_input_session(polling_state=MetricState.MEASURED, cv=0.50, rate=500)
        samples = make_samples(10, cpu=30, gpu=30, ram_used=8000, ram_total=16000)
        result = analyze_responsiveness(samples, input_session)
        assert result.state == ResponsivenessState.INPUT_LIMITED

    def test_case_c_gpu_saturated(self):
        """Case C: Input stable, frames stable, GPU saturated."""
        samples = make_samples(10, cpu=30, gpu=95, ram_used=8000, ram_total=16000)
        result = analyze_responsiveness(samples)
        assert result.state in (ResponsivenessState.GPU_LIMITED, ResponsivenessState.RESPONSIVE)

    def test_case_d_cpu_saturated(self):
        """Case D: Input stable, frame unstable, CPU high."""
        samples = make_samples(10, cpu=95, gpu=30, ram_used=10000, ram_total=16000)
        result = analyze_responsiveness(samples)
        assert result.state in (ResponsivenessState.CPU_SCHEDULING_LIMITED, ResponsivenessState.RESPONSIVE)
