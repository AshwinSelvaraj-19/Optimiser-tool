"""
Tests for Phase 37 — Input Device Diagnostics & Gameplay Diagnostics.

Uses mocks for hardware-dependent tests.
"""

import os
import time
import pytest
from unittest.mock import patch, MagicMock

from app.input.input_diagnostics import (
    InputDiagnosticSession,
    PointingDevice,
    PointerConfig,
    PollingMeasurement,
    LatencyEstimate,
    MetricState,
    PollingConsistency,
    ConnectionType,
    PointerAssessment,
    detect_pointer_config,
    estimate_input_latency,
    run_input_diagnostics,
    format_input_status,
)
from app.input.gameplay_diagnostics import (
    GameplayDiagnosticSession,
    GameplayCondition,
    InputConsistencyScore,
    ConsistencyScoreLevel,
    ConsistencyComponent,
    SensitivityData,
    SensitivityDataType,
    SensitivityAnalysis,
    GameplayRecommendation,
    classify_gameplay_condition,
    calculate_consistency_score,
    analyze_sensitivity,
    generate_gameplay_recommendations,
    run_gameplay_diagnostics,
    format_gameplay_diagnostics,
    MIN_SAMPLES_CLASSIFY,
    MIN_SAMPLES_SCORE,
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


# ── Input Diagnostics Model Tests ────────────────────────────────

class TestPointingDevice:
    def test_creation(self):
        d = PointingDevice(name="Logitech Mouse", connection_type=ConnectionType.USB)
        assert d.name == "Logitech Mouse"

    def test_to_dict(self):
        d = PointingDevice(name="Test")
        d2 = d.to_dict()
        assert d2["name"] == "Test"


class TestPointerConfig:
    def test_defaults(self):
        pc = PointerConfig()
        assert pc.state == MetricState.NOT_AVAILABLE
        assert pc.assessment == PointerAssessment.UNKNOWN

    def test_consistent(self):
        pc = PointerConfig(pointer_speed=6, enhance_pointer_precision=False, state=MetricState.MEASURED)
        pc.assessment = PointerAssessment.CONSISTENT
        assert pc.assessment == PointerAssessment.CONSISTENT

    def test_acceleration(self):
        pc = PointerConfig(enhance_pointer_precision=True, state=MetricState.MEASURED)
        pc.assessment = PointerAssessment.POTENTIAL_VARIABLE_ACCELERATION
        assert pc.assessment == PointerAssessment.POTENTIAL_VARIABLE_ACCELERATION


class TestPollingMeasurement:
    def test_defaults(self):
        pm = PollingMeasurement()
        assert pm.state == MetricState.NOT_AVAILABLE
        assert pm.consistency == PollingConsistency.INSUFFICIENT_DATA

    def test_high_consistency(self):
        pm = PollingMeasurement(
            observed_rate_hz=1000.0,
            coefficient_of_variation=0.05,
            consistency=PollingConsistency.HIGH,
            state=MetricState.MEASURED,
        )
        assert pm.consistency == PollingConsistency.HIGH

    def test_to_dict(self):
        pm = PollingMeasurement(observed_rate_hz=500.0, state=MetricState.MEASURED)
        d = pm.to_dict()
        assert d["observed_rate_hz"] == 500.0


class TestLatencyEstimate:
    def test_defaults(self):
        le = LatencyEstimate()
        assert le.state == MetricState.NOT_AVAILABLE

    def test_estimated(self):
        le = LatencyEstimate(display_latency_ms=8.3, estimated_total_ms=9.0, state=MetricState.INFERRED)
        assert le.estimated_total_ms == 9.0


class TestInputDiagnosticSession:
    def test_creation(self):
        s = InputDiagnosticSession(target_name="HD-Player.exe", target_pid=1234)
        assert s.target_name == "HD-Player.exe"

    def test_to_dict(self):
        s = InputDiagnosticSession()
        d = s.to_dict()
        assert "devices" in d
        assert "pointer_config" in d


# ── Pointer Config Detection ─────────────────────────────────────

class TestPointerConfigDetection:
    @patch("app.utils.registry.read_registry_value")
    def test_detect_pointer_config(self, mock_read):
        mock_read.side_effect = lambda hive, path, name: {
            ("HKCU", r"Control Panel\Mouse", "MouseSensitivity"): 6,
            ("HKCU", r"Control Panel\Mouse", "MouseSpeed"): 0,
        }.get((hive, path, name))

        config = detect_pointer_config()
        assert config.pointer_speed == 6
        assert config.enhance_pointer_precision is False
        assert config.assessment == PointerAssessment.CONSISTENT

    @patch("app.utils.registry.read_registry_value")
    def test_detect_acceleration_enabled(self, mock_read):
        mock_read.side_effect = lambda hive, path, name: {
            ("HKCU", r"Control Panel\Mouse", "MouseSensitivity"): 10,
            ("HKCU", r"Control Panel\Mouse", "MouseSpeed"): 1,
        }.get((hive, path, name))

        config = detect_pointer_config()
        assert config.enhance_pointer_precision is True
        assert config.assessment == PointerAssessment.POTENTIAL_VARIABLE_ACCELERATION


# ── Latency Estimation ───────────────────────────────────────────

class TestLatencyEstimation:
    def test_basic_estimate(self):
        est = estimate_input_latency(display_refresh_hz=144)
        assert est.display_latency_ms > 0
        assert est.estimated_total_ms > 0
        assert est.state == MetricState.INFERRED

    def test_no_display(self):
        est = estimate_input_latency(display_refresh_hz=0)
        assert est.state == MetricState.NOT_AVAILABLE

    def test_60hz(self):
        est = estimate_input_latency(display_refresh_hz=60)
        assert est.display_latency_ms == pytest.approx(16.67, abs=0.1)

    def test_high_cpu_increases_scheduling(self):
        est_low = estimate_input_latency(display_refresh_hz=144, cpu_percent=30)
        est_high = estimate_input_latency(display_refresh_hz=144, cpu_percent=90)
        assert est_high.scheduling_latency_ms > est_low.scheduling_latency_ms


# ── Run Diagnostics ──────────────────────────────────────────────

class TestRunInputDiagnostics:
    @patch("app.input.input_diagnostics.detect_pointing_devices")
    @patch("app.input.input_diagnostics.detect_pointer_config")
    def test_run_diagnostics(self, mock_ptr, mock_dev):
        mock_dev.return_value = [PointingDevice(name="Test Mouse")]
        mock_ptr.return_value = PointerConfig(pointer_speed=6, state=MetricState.MEASURED)

        session = run_input_diagnostics(target_name="HD-Player.exe", target_pid=1234)
        assert session.target_name == "HD-Player.exe"
        assert len(session.devices) == 1
        assert session.pointer_config.pointer_speed == 6


# ── Format CLI ───────────────────────────────────────────────────

class TestFormatInputStatus:
    def test_format_with_data(self):
        session = InputDiagnosticSession(
            target_name="HD-Player.exe", target_pid=1234,
            display_refresh_hz=144,
        )
        session.devices = [PointingDevice(name="Test Mouse")]
        session.pointer_config = PointerConfig(
            pointer_speed=6, enhance_pointer_precision=False,
            state=MetricState.MEASURED, assessment=PointerAssessment.CONSISTENT,
        )
        session.latency = LatencyEstimate(
            display_latency_ms=6.9, estimated_total_ms=8.0,
            state=MetricState.INFERRED,
        )
        output = format_input_status(session)
        assert "HD-Player.exe" in output
        assert "Test Mouse" in output
        assert "POINTER CONFIGURATION" in output

    def test_format_empty(self):
        session = InputDiagnosticSession()
        output = format_input_status(session)
        assert "INPUT DIAGNOSTICS" in output


# ── Gameplay Diagnostics Model Tests ─────────────────────────────

class TestGameplayModels:
    def test_condition_creation(self):
        assert GameplayCondition.INPUT_STABLE.value == "INPUT_STABLE"

    def test_consistency_score_defaults(self):
        cs = InputConsistencyScore()
        assert cs.overall_score == 0
        assert cs.level == ConsistencyScoreLevel.NOT_AVAILABLE

    def test_sensitivity_data(self):
        sd = SensitivityData(dpi=800, general_sensitivity=50)
        assert sd.has_any() is True

    def test_sensitivity_data_empty(self):
        sd = SensitivityData()
        assert sd.has_any() is False

    def test_gameplay_session(self):
        session = GameplayDiagnosticSession(target_name="test")
        assert session.target_name == "test"
        assert session.condition == GameplayCondition.INSUFFICIENT_DATA


# ── Condition Classification ─────────────────────────────────────

class TestConditionClassification:
    def test_insufficient_data(self):
        cond, conf, ev = classify_gameplay_condition([])
        assert cond == GameplayCondition.INSUFFICIENT_DATA
        assert conf == 0

    def test_stable(self):
        samples = make_samples(10, cpu=30, gpu=25, ram_used=6000, ram_total=16000)
        cond, conf, ev = classify_gameplay_condition(samples)
        assert cond == GameplayCondition.INPUT_STABLE

    def test_cpu_limited(self):
        samples = make_samples(10, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        cond, conf, ev = classify_gameplay_condition(samples)
        assert cond == GameplayCondition.CPU_SCHEDULING_LIMITED

    def test_memory_limited(self):
        samples = make_samples(10, cpu=50, gpu=40, ram_used=14800, ram_total=16000)
        cond, conf, ev = classify_gameplay_condition(samples)
        assert cond == GameplayCondition.MEMORY_LIMITED

    def test_thermal_limited(self):
        samples = make_samples(10, cpu=60, gpu=70, gpu_temp=91, ram_used=10000, ram_total=16000)
        cond, conf, ev = classify_gameplay_condition(samples)
        assert cond == GameplayCondition.THERMAL_LIMITED

    def test_frame_time_limited(self):
        samples = []
        for i in range(10):
            ft = 8.0 + (25.0 if i % 3 == 0 else 0.0)
            samples.append(make_sample(cpu=50, gpu=50, ram_used=10000, ram_total=16000, ft=ft))
        cond, conf, ev = classify_gameplay_condition(samples)
        assert cond == GameplayCondition.FRAME_TIME_LIMITED

    def test_input_inconsistent_pointer(self):
        input_session = InputDiagnosticSession()
        input_session.pointer_config = PointerConfig(
            enhance_pointer_precision=True, state=MetricState.MEASURED,
        )
        samples = make_samples(10, cpu=50, gpu=50, ram_used=10000, ram_total=16000)
        cond, conf, ev = classify_gameplay_condition(samples, input_session)
        assert cond in (GameplayCondition.INPUT_INCONSISTENT, GameplayCondition.INPUT_STABLE)

    def test_multi_resource(self):
        samples = make_samples(10, cpu=95, gpu=50, ram_used=15000, ram_total=16000, gpu_temp=91)
        cond, conf, ev = classify_gameplay_condition(samples)
        assert cond in (GameplayCondition.MULTI_RESOURCE_LIMITED, GameplayCondition.CPU_SCHEDULING_LIMITED,
                        GameplayCondition.MEMORY_LIMITED, GameplayCondition.THERMAL_LIMITED)


# ── Consistency Score ────────────────────────────────────────────

class TestConsistencyScore:
    def test_insufficient_samples(self):
        cs = calculate_consistency_score(make_samples(3, cpu=50, gpu=40, ram_used=8000, ram_total=16000))
        assert cs.state == MetricState.NOT_AVAILABLE

    def test_with_samples(self):
        cs = calculate_consistency_score(make_samples(10, cpu=50, gpu=40, ram_used=8000, ram_total=16000))
        assert cs.overall_score > 0
        assert cs.overall_score <= 100
        assert len(cs.components) == 6

    def test_score_level(self):
        cs = calculate_consistency_score(make_samples(10, cpu=30, gpu=25, ram_used=6000, ram_total=16000))
        assert cs.level in (ConsistencyScoreLevel.EXCELLENT, ConsistencyScoreLevel.GOOD,
                           ConsistencyScoreLevel.FAIR, ConsistencyScoreLevel.POOR)

    def test_high_cpu_reduces_score(self):
        good = calculate_consistency_score(make_samples(10, cpu=30, gpu=25, ram_used=6000, ram_total=16000))
        bad = calculate_consistency_score(make_samples(10, cpu=95, gpu=25, ram_used=6000, ram_total=16000))
        assert bad.overall_score <= good.overall_score

    def test_components_have_weights(self):
        cs = calculate_consistency_score(make_samples(10, cpu=50, gpu=40, ram_used=8000, ram_total=16000))
        total_weight = sum(c.weight for c in cs.components)
        assert total_weight == pytest.approx(1.0, abs=0.01)


# ── Sensitivity Analysis ─────────────────────────────────────────

class TestSensitivityAnalysis:
    def test_no_data(self):
        data = SensitivityData()
        analysis = analyze_sensitivity(data)
        assert analysis.state == SensitivityDataType.NOT_AVAILABLE

    def test_with_dpi_and_sens(self):
        data = SensitivityData(dpi=800, general_sensitivity=50)
        analysis = analyze_sensitivity(data)
        assert analysis.effective_dpi is not None
        assert analysis.cm_per_360 is not None
        assert len(analysis.recommendations) > 0

    def test_scope_scaling(self):
        data = SensitivityData(
            dpi=800, general_sensitivity=50,
            red_dot=40, scope_2x=30, scope_4x=20, sniper=15,
        )
        analysis = analyze_sensitivity(data)
        assert "Red Dot" in analysis.scope_scaling
        assert analysis.scope_scaling["Red Dot"] == pytest.approx(0.8, abs=0.01)

    def test_low_dpi_warning(self):
        data = SensitivityData(dpi=200, general_sensitivity=50)
        analysis = analyze_sensitivity(data)
        assert any("low" in r.lower() for r in analysis.recommendations)

    def test_high_dpi_warning(self):
        data = SensitivityData(dpi=6400, general_sensitivity=50)
        analysis = analyze_sensitivity(data)
        assert any("high" in r.lower() for r in analysis.recommendations)

    def test_unusual_scope(self):
        data = SensitivityData(
            dpi=800, general_sensitivity=30, red_dot=60,
        )
        analysis = analyze_sensitivity(data)
        assert len(analysis.warnings) > 0


# ── Recommendations ──────────────────────────────────────────────

class TestRecommendations:
    def test_insufficient_data(self):
        recs = generate_gameplay_recommendations(
            GameplayCondition.INSUFFICIENT_DATA, 0,
            InputConsistencyScore(),
        )
        assert len(recs) > 0
        assert recs[0].category == "INPUT"

    def test_pointer_acceleration_rec(self):
        input_session = InputDiagnosticSession()
        input_session.pointer_config = PointerConfig(
            enhance_pointer_precision=True, state=MetricState.MEASURED,
        )
        recs = generate_gameplay_recommendations(
            GameplayCondition.INPUT_STABLE, 70,
            InputConsistencyScore(), input_session,
        )
        pointer_recs = [r for r in recs if "Pointer Precision" in r.reason or "acceleration" in r.reason.lower()]
        assert len(pointer_recs) > 0

    def test_frame_pacing_rec(self):
        recs = generate_gameplay_recommendations(
            GameplayCondition.FRAME_TIME_LIMITED, 70,
            InputConsistencyScore(),
        )
        frame_recs = [r for r in recs if r.category == "FRAME_PACING"]
        assert len(frame_recs) > 0

    def test_memory_rec(self):
        recs = generate_gameplay_recommendations(
            GameplayCondition.MEMORY_LIMITED, 75,
            InputConsistencyScore(),
        )
        mem_recs = [r for r in recs if r.category == "MEMORY"]
        assert len(mem_recs) > 0

    def test_thermal_rec(self):
        recs = generate_gameplay_recommendations(
            GameplayCondition.THERMAL_LIMITED, 60,
            InputConsistencyScore(),
        )
        thermal_recs = [r for r in recs if r.category == "THERMAL"]
        assert len(thermal_recs) > 0


# ── Run Gameplay Diagnostics ─────────────────────────────────────

class TestRunGameplayDiagnostics:
    def test_basic(self):
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        session = run_gameplay_diagnostics(samples)
        assert session.condition != GameplayCondition.INSUFFICIENT_DATA
        assert session.consistency_score.overall_score > 0

    def test_with_input_session(self):
        input_session = InputDiagnosticSession()
        input_session.pointer_config = PointerConfig(
            enhance_pointer_precision=True, state=MetricState.MEASURED,
        )
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        session = run_gameplay_diagnostics(samples, input_session)
        assert session.input_session is not None


# ── Format CLI ───────────────────────────────────────────────────

class TestFormatGameplay:
    def test_format(self):
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        session = run_gameplay_diagnostics(samples, target_name="HD-Player.exe", target_pid=1234)
        output = format_gameplay_diagnostics(session)
        assert "GAMEPLAY DIAGNOSTICS" in output
        assert "HD-Player.exe" in output


# ── Safety ───────────────────────────────────────────────────────

class TestSafety:
    def test_no_system_modification(self):
        """Verify diagnostic modules do not modify system state."""
        assert hasattr(classify_gameplay_condition, '__call__')
        assert hasattr(calculate_consistency_score, '__call__')
        assert hasattr(analyze_sensitivity, '__call__')
        # No terminate, no registry write, no file delete
        import inspect
        for func in [classify_gameplay_condition, calculate_consistency_score, analyze_sensitivity]:
            source = inspect.getsource(func)
            assert "terminate" not in source.lower()
            assert "write_registry" not in source.lower()
            assert "os.remove" not in source.lower()


# ── Deterministic ────────────────────────────────────────────────

class TestDeterministic:
    def test_same_input_same_output(self):
        samples = make_samples(10, cpu=50, gpu=40, ram_used=10000, ram_total=16000)
        c1, _, _ = classify_gameplay_condition(samples)
        c2, _, _ = classify_gameplay_condition(samples)
        assert c1 == c2

    def test_empty_always_insufficient(self):
        for _ in range(5):
            cond, _, _ = classify_gameplay_condition([])
            assert cond == GameplayCondition.INSUFFICIENT_DATA
