"""
Tests for Heaven Society — Phase 30 Final Performance Validation Engine.
"""

import os
import json
import pytest
from unittest.mock import patch, MagicMock

from app.core.validation_engine import (
    ValidationEngine,
    ValidationReport,
    ValidationVerdict,
    StepStatus,
    CaptureMetrics,
    CaptureSuite,
    SystemSnapshot,
    OptimizationRecord,
    ValidationStep,
)

# Patch targets must be in the validation_engine namespace (module-level imports)
MOD = "app.core.validation_engine"


# ── CaptureMetrics Tests ──────────────────────────────────────

class TestCaptureMetrics:
    def test_default_not_valid(self):
        assert CaptureMetrics().is_valid is False

    def test_valid_with_fps(self):
        m = CaptureMetrics(present_fps=60.0, sample_count=100, is_valid=True)
        assert m.is_valid

    def test_error_message(self):
        m = CaptureMetrics(error="Not found")
        assert not m.is_valid


# ── CaptureSuite Tests ────────────────────────────────────────

class TestCaptureSuite:
    def _v(self, fps, one_low=None, frame_time=None, stability=None, pid=1234):
        return CaptureMetrics(present_fps=fps, one_percent_low=one_low,
                              average_frame_time=frame_time, stability=stability,
                              sample_count=100, target_pid=pid, is_valid=True)

    def test_empty(self):
        s = CaptureSuite(label="t")
        assert s.valid_count == 0 and s.median_fps is None

    def test_single(self):
        s = CaptureSuite()
        s.captures.append(self._v(100.0, 50.0, 10.0, 90.0))
        assert s.median_fps == 100.0 and s.median_one_low == 50.0

    def test_multiple(self):
        s = CaptureSuite()
        s.captures.append(self._v(100.0))
        s.captures.append(self._v(110.0))
        s.captures.append(self._v(90.0))
        assert s.median_fps == 100.0

    def test_mixed(self):
        s = CaptureSuite()
        s.captures.append(self._v(100.0))
        s.captures.append(CaptureMetrics(error="x", is_valid=False))
        s.captures.append(self._v(120.0))
        assert s.valid_count == 2 and s.median_fps == 110.0

    def test_pid_consistency(self):
        s = CaptureSuite()
        s.captures.append(self._v(100.0, pid=1))
        s.captures.append(self._v(105.0, pid=1))
        assert s.consistent_pid

    def test_pid_inconsistent(self):
        s = CaptureSuite()
        s.captures.append(self._v(100.0, pid=1))
        s.captures.append(self._v(105.0, pid=2))
        assert not s.consistent_pid

    def test_cv(self):
        s = CaptureSuite()
        s.captures.append(self._v(100.0))
        s.captures.append(self._v(100.0))
        assert s.cv_fps == 0.0

    def test_cv_with_variance(self):
        s = CaptureSuite()
        s.captures.append(self._v(90.0))
        s.captures.append(self._v(110.0))
        assert s.cv_fps > 0

    def test_median_spikes(self):
        s = CaptureSuite()
        s.captures.append(CaptureMetrics(frame_spikes=5, is_valid=True, sample_count=10))
        s.captures.append(CaptureMetrics(frame_spikes=15, is_valid=True, sample_count=10))
        assert s.median_spikes == 10.0

    def test_to_dict(self):
        s = CaptureSuite(label="t")
        s.captures.append(self._v(100.0))
        assert s.to_dict()["valid_captures"] == 1


# ── Model Tests ───────────────────────────────────────────────

class TestModels:
    def test_snapshot_defaults(self):
        assert SystemSnapshot().thermal_state == "UNKNOWN"

    def test_snapshot_to_dict(self):
        s = SystemSnapshot(cpu_model="X", ram_total_gb=16.0)
        assert s.to_dict()["cpu_model"] == "X"

    def test_optimization_record_statuses(self):
        for st in ["APPLIED", "REQUIRES_ADMIN", "RECOMMENDATION_ONLY", "ALREADY_OPTIMAL", "FAILED"]:
            assert OptimizationRecord(status=st).status == st

    def test_step(self):
        assert ValidationStep(1, "T", StepStatus.PASS, "ok").status == StepStatus.PASS


# ── ValidationReport Tests ────────────────────────────────────

class TestReport:
    def test_defaults(self):
        r = ValidationReport()
        assert r.verdict == ValidationVerdict.INCONCLUSIVE

    def test_step_helpers(self):
        r = ValidationReport()
        r.step_pass(1, "T", "ok")
        r.step_fail(2, "T", "err")
        r.step_skip(3, "T", "skip")
        r.step_warn(4, "T", "warn")
        assert len(r.steps) == 4
        assert r.steps[0].status == StepStatus.PASS
        assert r.steps[1].status == StepStatus.FAIL
        assert r.steps[2].status == StepStatus.SKIP
        assert r.steps[3].status == StepStatus.WARN

    def test_to_dict(self):
        r = ValidationReport(validation_id="v1")
        r.step_pass(1, "S", "ok")
        d = r.to_dict()
        assert d["validation_id"] == "v1" and d["verdict"] == "INCONCLUSIVE"

    def test_format_cli(self):
        r = ValidationReport()
        r.system.cpu_model = "CPU"
        r.step_pass(1, "S", "ok")
        r.verdict = ValidationVerdict.UNCHANGED
        r.confidence = "HIGH"
        r.cleanup_complete = True
        r.rollback_complete = True
        text = r.format_cli()
        assert "HEAVEN SOCIETY" in text and "CPU" in text

    def test_format_with_data(self):
        r = ValidationReport()
        r.baseline.captures.append(CaptureMetrics(present_fps=100.0, sample_count=10, is_valid=True))
        r.optimized.captures.append(CaptureMetrics(present_fps=105.0, sample_count=10, is_valid=True))
        r.fps_delta = 5.0
        r.fps_delta_percent = 5.0
        text = r.format_cli()
        assert "BASELINE" in text and "+5.0" in text

    def test_json_serializable(self):
        r = ValidationReport(validation_id="v1")
        r.optimizations_applied.append(OptimizationRecord(opt_id="p", name="P", status="APPLIED"))
        assert len(json.dumps(r.to_dict(), default=str)) > 0


# ── Enum Tests ────────────────────────────────────────────────

class TestEnums:
    def test_all(self):
        assert len(ValidationVerdict) == 4
        assert len(StepStatus) == 4


# ── Individual Step Tests (patch in validation_engine namespace) ──

class TestSteps:
    def test_step_01(self):
        engine = ValidationEngine()
        with patch(f"{MOD}.kill_stale_phoenix_sessions", return_value=0), \
             patch("glob.glob", return_value=[]):
            engine._step_01_clean_stale()
        assert engine.report.steps[0].status == StepStatus.PASS

    def test_step_02_pass(self):
        engine = ValidationEngine()
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(prerequisites=[MagicMock(status="PASS")])
        with patch(f"{MOD}.PrerequisiteChecker", return_value=mock_checker):
            engine._step_02_prerequisites()
        assert "All 1" in engine.report.steps[0].message

    def test_step_02_fail(self):
        engine = ValidationEngine()
        mock_checker = MagicMock()
        mock_checker.check_all.return_value = MagicMock(prerequisites=[MagicMock(status="FAIL", name="X")])
        with patch(f"{MOD}.PrerequisiteChecker", return_value=mock_checker):
            engine._step_02_prerequisites()
        assert engine.report.steps[0].status == StepStatus.FAIL

    def test_step_04_no_emulator(self):
        engine = ValidationEngine()
        with patch(f"{MOD}.target_process_detector") as m:
            m.select_best_target.return_value = None
            engine._step_04_emulator()
        assert engine.report.steps[0].status == StepStatus.SKIP

    def test_step_05_no_target(self):
        engine = ValidationEngine()
        engine._step_05_baseline_capture()
        assert engine.report.steps[0].status == StepStatus.SKIP

    def test_step_06_no_target(self):
        engine = ValidationEngine()
        engine._step_06_repeated_baseline()
        assert engine.report.steps[0].status == StepStatus.SKIP

    def test_step_09_no_target(self):
        engine = ValidationEngine()
        engine._step_09_repeated_optimized()
        assert engine.report.steps[0].status == StepStatus.SKIP

    def test_step_10_no_data(self):
        engine = ValidationEngine()
        engine._step_10_compare_medians()
        assert engine.report.steps[0].status == StepStatus.SKIP

    def test_step_10_with_data(self):
        engine = ValidationEngine()
        engine.report.baseline.captures.append(CaptureMetrics(present_fps=100.0, is_valid=True, sample_count=10))
        engine.report.optimized.captures.append(CaptureMetrics(present_fps=110.0, is_valid=True, sample_count=10))
        engine._step_10_compare_medians()
        assert engine.report.fps_delta == 10.0

    def test_step_11_high(self):
        engine = ValidationEngine(runs=3)
        for _ in range(3):
            engine.report.baseline.captures.append(CaptureMetrics(present_fps=100.0, is_valid=True, sample_count=10, target_pid=1))
            engine.report.optimized.captures.append(CaptureMetrics(present_fps=100.0, is_valid=True, sample_count=10, target_pid=1))
        engine._step_11_calculate_confidence()
        assert engine.report.confidence == "HIGH"

    def test_step_11_low_data(self):
        engine = ValidationEngine(runs=3)
        engine.report.baseline.captures.append(CaptureMetrics(present_fps=100.0, is_valid=True, sample_count=10))
        engine.report.optimized.captures.append(CaptureMetrics(error="x", is_valid=False))
        engine._step_11_calculate_confidence()
        assert engine.report.confidence in ("LOW", "INCONCLUSIVE")

    def test_step_12_no_data(self):
        engine = ValidationEngine()
        engine._step_12_detect_regressions()
        assert engine.report.verdict == ValidationVerdict.INCONCLUSIVE

    def test_step_12_improved(self):
        engine = ValidationEngine()
        engine.report.fps_delta = 5.0
        engine.report.fps_delta_percent = 5.0
        engine.report.one_low_delta = 3.0
        engine.report.confidence = "HIGH"
        engine._step_12_detect_regressions()
        assert engine.report.verdict == ValidationVerdict.IMPROVED

    def test_step_12_degraded(self):
        engine = ValidationEngine()
        engine.report.fps_delta = -10.0
        engine.report.fps_delta_percent = -10.0
        engine.report.confidence = "HIGH"
        engine._step_12_detect_regressions()
        assert engine.report.verdict == ValidationVerdict.DEGRADED

    def test_step_12_unchanged(self):
        engine = ValidationEngine()
        engine.report.fps_delta = 0.5
        engine.report.fps_delta_percent = 0.5
        engine.report.confidence = "HIGH"
        engine._step_12_detect_regressions()
        assert engine.report.verdict == ValidationVerdict.UNCHANGED

    def test_step_12_low_confidence(self):
        engine = ValidationEngine()
        engine.report.fps_delta = 5.0
        engine.report.fps_delta_percent = 5.0
        engine.report.confidence = "LOW"
        engine._step_12_detect_regressions()
        assert engine.report.verdict == ValidationVerdict.INCONCLUSIVE

    def test_step_13_no_snapshot(self):
        engine = ValidationEngine()
        engine._step_13_restore_changes()
        assert engine.report.steps[0].status == StepStatus.SKIP

    def test_step_15_cleanup(self):
        engine = ValidationEngine()
        with patch(f"{MOD}.kill_stale_phoenix_sessions", return_value=0), \
             patch("glob.glob", return_value=[]):
            engine._step_15_cleanup_resources()
        assert engine.report.cleanup_complete

    def test_step_16_report(self):
        engine = ValidationEngine()
        engine.report.step_pass(1, "S", "ok")
        engine.report.verdict = ValidationVerdict.UNCHANGED
        engine._step_16_generate_report()
        assert "UNCHANGED" in engine.report.steps[-1].message


# ── Workflow Tests ────────────────────────────────────────────

class TestWorkflow:
    def test_no_emulator(self):
        engine = ValidationEngine(runs=1, duration=5)
        engine.report.system.emulator_name = ""
        engine.report.system.emulator_pid = 0

        with patch(f"{MOD}.kill_stale_phoenix_sessions", return_value=0), \
             patch("glob.glob", return_value=[]):
            engine._step_01_clean_stale()
            engine._step_15_cleanup_resources()

        with patch(f"{MOD}.target_process_detector") as m:
            m.select_best_target.return_value = None
            engine._step_04_emulator()

        engine._step_05_baseline_capture()
        engine._step_06_repeated_baseline()
        engine._step_09_repeated_optimized()
        engine._step_10_compare_medians()
        engine._step_11_calculate_confidence()
        engine._step_12_detect_regressions()

        assert engine.report.verdict == ValidationVerdict.INCONCLUSIVE
        assert engine.report.cleanup_complete

    def test_improved(self):
        engine = ValidationEngine(runs=1, duration=5)
        engine.report.system.emulator_name = "HD-Player.exe"
        engine.report.system.emulator_pid = 1234
        engine.report.system.display_refresh = 144

        call_count = [0]
        def mock_capture():
            call_count[0] += 1
            if call_count[0] <= 1:
                return CaptureMetrics(present_fps=90.0, one_percent_low=40.0,
                                      sample_count=100, target_pid=1234, is_valid=True)
            return CaptureMetrics(present_fps=100.0, one_percent_low=50.0,
                                  sample_count=100, target_pid=1234, is_valid=True)

        engine._single_capture = mock_capture
        engine._step_06_repeated_baseline()
        engine._step_09_repeated_optimized()
        engine._step_10_compare_medians()
        engine._step_11_calculate_confidence()
        engine._step_12_detect_regressions()

        assert engine.report.verdict == ValidationVerdict.IMPROVED
        assert engine.report.fps_delta == 10.0

    def test_degraded(self):
        engine = ValidationEngine(runs=1, duration=5)
        engine.report.system.emulator_name = "HD-Player.exe"
        engine.report.system.emulator_pid = 1234

        call_count = [0]
        def mock_capture():
            call_count[0] += 1
            if call_count[0] <= 1:
                return CaptureMetrics(present_fps=120.0, one_percent_low=60.0,
                                      sample_count=100, target_pid=1234, is_valid=True)
            return CaptureMetrics(present_fps=100.0, one_percent_low=40.0,
                                  sample_count=100, target_pid=1234, is_valid=True)

        engine._single_capture = mock_capture
        engine._step_06_repeated_baseline()
        engine._step_09_repeated_optimized()
        engine._step_10_compare_medians()
        engine._step_11_calculate_confidence()
        engine._step_12_detect_regressions()

        assert engine.report.verdict == ValidationVerdict.DEGRADED
        assert engine.report.fps_delta == -20.0

    def test_unchanged(self):
        engine = ValidationEngine(runs=1, duration=5)
        engine.report.system.emulator_name = "HD-Player.exe"
        engine.report.system.emulator_pid = 1234

        def mock_capture():
            return CaptureMetrics(present_fps=100.0, one_percent_low=50.0,
                                  sample_count=100, target_pid=1234, is_valid=True)

        engine._single_capture = mock_capture
        engine._step_06_repeated_baseline()
        engine._step_09_repeated_optimized()
        engine._step_10_compare_medians()
        engine._step_11_calculate_confidence()
        engine._step_12_detect_regressions()

        assert engine.report.verdict == ValidationVerdict.UNCHANGED
        assert engine.report.fps_delta == 0.0


# ── Confidence Tests ──────────────────────────────────────────

class TestConfidence:
    def _engine(self, base_n, opt_n, base_pids, opt_pids, base_fps=None, opt_fps=None):
        e = ValidationEngine(runs=3)
        for i in range(3):
            if i < base_n:
                pid = base_pids[i % len(base_pids)] if base_pids else 1234
                fps = base_fps[i] if base_fps else 100.0
                e.report.baseline.captures.append(CaptureMetrics(
                    present_fps=fps, sample_count=10, target_pid=pid, is_valid=True))
            else:
                e.report.baseline.captures.append(CaptureMetrics(error="x", is_valid=False))
            if i < opt_n:
                pid = opt_pids[i % len(opt_pids)] if opt_pids else 1234
                fps = opt_fps[i] if opt_fps else 100.0
                e.report.optimized.captures.append(CaptureMetrics(
                    present_fps=fps, sample_count=10, target_pid=pid, is_valid=True))
            else:
                e.report.optimized.captures.append(CaptureMetrics(error="x", is_valid=False))
        return e

    def test_high(self):
        e = self._engine(3, 3, [1]*3, [1]*3, [99, 100, 101], [100, 101, 102])
        e._step_11_calculate_confidence()
        assert e.report.confidence == "HIGH"

    def test_inconclusive(self):
        e = self._engine(0, 0, [], [])
        e._step_11_calculate_confidence()
        assert e.report.confidence == "INCONCLUSIVE"


# ── Threshold Tests ───────────────────────────────────────────

class TestThresholds:
    def _e(self, fps_d, fps_p, one_d, conf="HIGH"):
        e = ValidationEngine()
        e.report.fps_delta = fps_d
        e.report.fps_delta_percent = fps_p
        e.report.one_low_delta = one_d
        e.report.confidence = conf
        return e

    def test_improve_fps(self):
        e = self._e(3.0, 3.0, 0)
        e._step_12_detect_regressions()
        assert e.report.verdict == ValidationVerdict.IMPROVED

    def test_improve_one_low(self):
        e = self._e(0.5, 0.5, 3.0)
        e._step_12_detect_regressions()
        assert e.report.verdict == ValidationVerdict.IMPROVED

    def test_degrade(self):
        e = self._e(-5.0, -5.0, 0)
        e._step_12_detect_regressions()
        assert e.report.verdict == ValidationVerdict.DEGRADED

    def test_unchanged_small(self):
        e = self._e(0.3, 0.3, 0)
        e._step_12_detect_regressions()
        assert e.report.verdict == ValidationVerdict.UNCHANGED

    def test_unchanged_below_pct(self):
        e = self._e(3.0, 1.0, 0)
        e._step_12_detect_regressions()
        assert e.report.verdict == ValidationVerdict.UNCHANGED

    def test_low_confidence(self):
        e = self._e(5.0, 5.0, 0, conf="LOW")
        e._step_12_detect_regressions()
        assert e.report.verdict == ValidationVerdict.INCONCLUSIVE


# ── Edge Cases ────────────────────────────────────────────────

class TestEdgeCases:
    def test_no_target_capture(self):
        e = ValidationEngine()
        e.report.system.emulator_name = ""
        e.report.system.emulator_pid = 0
        m = e._single_capture()
        assert m.error == "No target process"

    def test_params(self):
        e = ValidationEngine(runs=0, duration=0)
        assert e.runs == 1 and e.duration == 5
        e2 = ValidationEngine(profile_id="balanced", runs=5, duration=30)
        assert e2.profile_id == "balanced" and e2.runs == 5

    def test_none_values(self):
        s = CaptureSuite()
        s.captures.append(CaptureMetrics(is_valid=True, sample_count=10))
        assert s.median_one_low is None and s.median_frame_time is None
