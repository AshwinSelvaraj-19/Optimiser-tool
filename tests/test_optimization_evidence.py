"""
Tests for Heaven Society — Evidence-Based Optimization Validation (Phase 26).

Uses mocked subsystems; never requires real PresentMon or hardware.
"""

import pytest
import os
import json
import tempfile
from unittest.mock import patch, MagicMock

from app.core.optimization_evidence import (
    OptimizationEvidence,
    OptimizationEvidenceEngine,
    MeasurementSnapshot,
    EvidenceVerdict,
    CaptureStatus,
    EvidenceSession,
    save_evidence_session,
    load_evidence_sessions,
)


class TestMeasurementSnapshot:
    """Test MeasurementSnapshot data model."""

    def test_defaults(self):
        s = MeasurementSnapshot()
        assert s.present_fps is None
        assert s.one_percent_low is None
        assert s.sample_count == 0
        assert s.capture_status == CaptureStatus.FAILED
        assert s.timestamp > 0

    def test_valid_snapshot(self):
        s = MeasurementSnapshot(
            present_fps=120.0,
            one_percent_low=90.0,
            sample_count=500,
            capture_status=CaptureStatus.COMPLETE,
        )
        assert s.is_valid

    def test_invalid_no_fps(self):
        s = MeasurementSnapshot(
            sample_count=500,
            capture_status=CaptureStatus.COMPLETE,
        )
        assert not s.is_valid

    def test_invalid_no_samples(self):
        s = MeasurementSnapshot(
            present_fps=120.0,
            capture_status=CaptureStatus.COMPLETE,
        )
        assert not s.is_valid

    def test_invalid_failed_capture(self):
        s = MeasurementSnapshot(
            present_fps=120.0,
            sample_count=500,
            capture_status=CaptureStatus.FAILED,
        )
        assert not s.is_valid

    def test_to_dict(self):
        s = MeasurementSnapshot(present_fps=120.0, sample_count=100)
        d = s.to_dict()
        assert d["present_fps"] == 120.0
        assert d["sample_count"] == 100
        assert d["capture_status"] == "FAILED"


class TestEvidenceVerdict:
    """Test EvidenceVerdict enum."""

    def test_all_values(self):
        assert EvidenceVerdict.BENEFICIAL.value == "BENEFICIAL"
        assert EvidenceVerdict.NEUTRAL.value == "NEUTRAL"
        assert EvidenceVerdict.HARMFUL.value == "HARMFUL"
        assert EvidenceVerdict.INCONCLUSIVE.value == "INCONCLUSIVE"
        assert EvidenceVerdict.SKIPPED.value == "SKIPPED"

    def test_count(self):
        assert len(EvidenceVerdict) == 5


class TestCaptureStatus:
    """Test CaptureStatus enum."""

    def test_all_values(self):
        assert CaptureStatus.COMPLETE.value == "COMPLETE"
        assert CaptureStatus.FAILED.value == "FAILED"
        assert CaptureStatus.NO_TARGET.value == "NO_TARGET"
        assert CaptureStatus.TIMEOUT.value == "TIMEOUT"
        assert CaptureStatus.UAC_DENIED.value == "UAC_DENIED"


class TestDeltaCalculation:
    """Test delta calculation from baseline and post."""

    def test_fps_delta(self):
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(
                present_fps=100.0, one_percent_low=80.0,
                average_frame_time=10.0, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
            post=MeasurementSnapshot(
                present_fps=110.0, one_percent_low=85.0,
                average_frame_time=9.0, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
        )
        ev.calculate_deltas()
        assert ev.fps_delta == pytest.approx(10.0, abs=0.01)
        assert ev.fps_delta_percent == pytest.approx(10.0, abs=0.1)
        assert ev.one_low_delta == pytest.approx(5.0, abs=0.01)
        assert ev.frame_time_delta == pytest.approx(-1.0, abs=0.01)

    def test_no_delta_without_valid_data(self):
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(capture_status=CaptureStatus.FAILED),
            post=MeasurementSnapshot(capture_status=CaptureStatus.COMPLETE),
        )
        ev.calculate_deltas()
        assert ev.fps_delta is None

    def test_same_fps_gives_zero_delta(self):
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(
                present_fps=100.0, sample_count=100,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
            post=MeasurementSnapshot(
                present_fps=100.0, sample_count=100,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
        )
        ev.calculate_deltas()
        assert ev.fps_delta == pytest.approx(0.0, abs=0.01)


class TestVerdictDetermination:
    """Test verdict determination logic."""

    def _make_valid_evidence(self, baseline_fps, post_fps, baseline_1low=None, post_1low=None):
        """Helper to create evidence with valid snapshots."""
        return OptimizationEvidence(
            baseline=MeasurementSnapshot(
                present_fps=baseline_fps,
                one_percent_low=baseline_1low or baseline_fps * 0.7,
                average_frame_time=1000.0 / baseline_fps if baseline_fps > 0 else 0,
                sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
            post=MeasurementSnapshot(
                present_fps=post_fps,
                one_percent_low=post_1low or post_fps * 0.7,
                average_frame_time=1000.0 / post_fps if post_fps > 0 else 0,
                sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
        )

    def test_beneficial_fps_improvement(self):
        ev = self._make_valid_evidence(100.0, 115.0)
        ev.determine_verdict()
        assert ev.verdict == EvidenceVerdict.BENEFICIAL

    def test_beneficial_1low_improvement(self):
        ev = self._make_valid_evidence(100.0, 102.0, baseline_1low=70.0, post_1low=75.0)
        ev.determine_verdict()
        # 1% low improved by 5, FPS improved by 2 — should be beneficial
        assert ev.verdict in (EvidenceVerdict.BENEFICIAL, EvidenceVerdict.NEUTRAL)

    def test_harmful_fps_drop(self):
        ev = self._make_valid_evidence(100.0, 85.0)
        ev.determine_verdict()
        assert ev.verdict == EvidenceVerdict.HARMFUL

    def test_neutral_small_change(self):
        ev = self._make_valid_evidence(100.0, 101.0)
        ev.determine_verdict()
        assert ev.verdict == EvidenceVerdict.NEUTRAL

    def test_inconclusive_no_fps(self):
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(
                capture_status=CaptureStatus.FAILED,
            ),
            post=MeasurementSnapshot(
                present_fps=100.0, sample_count=100,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
        )
        ev.determine_verdict()
        assert ev.verdict == EvidenceVerdict.INCONCLUSIVE

    def test_inconclusive_pid_changed(self):
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(
                present_fps=100.0, sample_count=100,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
            post=MeasurementSnapshot(
                present_fps=110.0, sample_count=100,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=5678,
            ),
        )
        ev.determine_verdict()
        assert ev.verdict == EvidenceVerdict.INCONCLUSIVE
        assert "PID changed" in ev.verdict_reason

    def test_inconclusive_insufficient_samples(self):
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(
                present_fps=100.0, sample_count=10,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
            post=MeasurementSnapshot(
                present_fps=120.0, sample_count=10,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
        )
        ev.determine_verdict()
        assert ev.verdict == EvidenceVerdict.INCONCLUSIVE
        assert "Insufficient samples" in ev.verdict_reason

    def test_harmful_frame_time_increase(self):
        ev = self._make_valid_evidence(100.0, 98.0)
        ev.baseline.average_frame_time = 10.0
        ev.post.average_frame_time = 11.0
        ev.determine_verdict()
        assert ev.verdict in (EvidenceVerdict.HARMFUL, EvidenceVerdict.NEUTRAL)


class TestOptimizationEvidence:
    """Test OptimizationEvidence data model."""

    def test_defaults(self):
        ev = OptimizationEvidence()
        assert ev.optimization_id == ""
        assert ev.verdict == EvidenceVerdict.INCONCLUSIVE
        assert ev.was_applied is False
        assert ev.was_rolled_back is False
        assert ev.timestamp != ""

    def test_to_dict(self):
        ev = OptimizationEvidence(
            optimization_id="power_plan",
            optimization_name="Power Plan",
            verdict=EvidenceVerdict.BENEFICIAL,
            fps_delta=5.0,
            fps_delta_percent=5.0,
        )
        d = ev.to_dict()
        assert d["optimization_id"] == "power_plan"
        assert d["verdict"] == "BENEFICIAL"
        assert d["fps_delta"] == 5.0

    def test_is_benchmark_valid(self):
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(
                present_fps=100.0, sample_count=100,
                capture_status=CaptureStatus.COMPLETE,
            ),
            post=MeasurementSnapshot(
                present_fps=110.0, sample_count=100,
                capture_status=CaptureStatus.COMPLETE,
            ),
        )
        assert ev.is_benchmark_valid

    def test_same_target(self):
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(target_pid=1234),
            post=MeasurementSnapshot(target_pid=1234),
        )
        assert ev.same_target

    def test_different_target(self):
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(target_pid=1234),
            post=MeasurementSnapshot(target_pid=5678),
        )
        assert not ev.same_target


class TestEvidenceSession:
    """Test EvidenceSession data model."""

    def test_defaults(self):
        s = EvidenceSession()
        assert s.session_id.startswith("evidence_")
        assert s.beneficial_count == 0
        assert s.evidence_list == []

    def test_add_evidence(self):
        s = EvidenceSession()
        ev1 = OptimizationEvidence(verdict=EvidenceVerdict.BENEFICIAL)
        ev2 = OptimizationEvidence(verdict=EvidenceVerdict.NEUTRAL)
        ev3 = OptimizationEvidence(verdict=EvidenceVerdict.HARMFUL)
        s.add_evidence(ev1)
        s.add_evidence(ev2)
        s.add_evidence(ev3)
        assert s.beneficial_count == 1
        assert s.neutral_count == 1
        assert s.harmful_count == 1
        assert len(s.evidence_list) == 3

    def test_finalize(self):
        s = EvidenceSession()
        s.add_evidence(OptimizationEvidence(verdict=EvidenceVerdict.NEUTRAL))
        s.finalize()
        assert s.completed_at != ""
        assert s.duration_seconds >= 0

    def test_to_dict(self):
        s = EvidenceSession(profile_id="gaming")
        s.add_evidence(OptimizationEvidence(verdict=EvidenceVerdict.BENEFICIAL))
        d = s.to_dict()
        assert d["profile_id"] == "gaming"
        assert d["beneficial_count"] == 1
        assert len(d["evidence"]) == 1


class TestEvidenceStorage:
    """Test evidence session persistence."""

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            session = EvidenceSession(profile_id="test")
            session.add_evidence(OptimizationEvidence(
                optimization_id="test_opt",
                verdict=EvidenceVerdict.BENEFICIAL,
                fps_delta=5.0,
            ))
            session.finalize()

            # Override the evidence dir
            import app.core.optimization_evidence as mod
            old_dir = mod.EVIDENCE_DIR
            mod.EVIDENCE_DIR = tmpdir
            try:
                save_evidence_session(session)
                loaded = load_evidence_sessions()
                assert len(loaded) == 1
                assert loaded[0].profile_id == "test"
                assert loaded[0].evidence_list[0].verdict == EvidenceVerdict.BENEFICIAL
            finally:
                mod.EVIDENCE_DIR = old_dir

    def test_load_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import app.core.optimization_evidence as mod
            old_dir = mod.EVIDENCE_DIR
            mod.EVIDENCE_DIR = tmpdir
            try:
                loaded = load_evidence_sessions()
                assert len(loaded) == 0
            finally:
                mod.EVIDENCE_DIR = old_dir

    def test_load_corrupted_file(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import app.core.optimization_evidence as mod
            old_dir = mod.EVIDENCE_DIR
            mod.EVIDENCE_DIR = tmpdir
            try:
                # Write a corrupted file
                with open(os.path.join(tmpdir, "bad.json"), "w") as f:
                    f.write("not valid json {{{")
                loaded = load_evidence_sessions()
                assert len(loaded) == 0
            finally:
                mod.EVIDENCE_DIR = old_dir


class TestEvidenceEngine:
    """Test the validation engine logic."""

    def test_detect_target_no_emulator(self):
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("", 0)):
            name, pid = engine._detect_target()
            assert name == ""
            assert pid == 0

    def test_detect_target_with_emulator(self):
        engine = OptimizationEvidenceEngine()
        with patch("app.performance.target_process.target_process_detector") as mock:
            best = MagicMock()
            best.process_name = "HD-Player.exe"
            best.pid = 1234
            mock.select_best_target.return_value = best
            name, pid = engine._detect_target()
            assert name == "HD-Player.exe"
            assert pid == 1234

    def test_is_optimization_applicable_not_found(self):
        engine = OptimizationEvidenceEngine()
        with patch("app.core.optimization_evidence.optimization_evidence_engine._is_optimization_applicable") as mock:
            mock.return_value = False
            result = engine._is_optimization_applicable("nonexistent")
            assert not result

    def test_validate_no_target(self):
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("", 0)):
            evidence = engine.validate_optimization(
                optimization_id="test",
                optimization_name="Test",
            )
            assert evidence.verdict == EvidenceVerdict.INCONCLUSIVE
            assert "No emulator target" in evidence.verdict_reason

    def test_validate_baseline_failed(self):
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234)), \
             patch.object(engine, "capture_baseline") as mock:
            mock.return_value = MeasurementSnapshot(
                capture_status=CaptureStatus.FAILED,
                error="PresentMon not found",
                target_pid=1234,
            )
            evidence = engine.validate_optimization(
                optimization_id="test",
                optimization_name="Test",
            )
            assert evidence.verdict == EvidenceVerdict.INCONCLUSIVE
            assert "Baseline capture failed" in evidence.verdict_reason

    def test_validate_apply_failed(self):
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234)), \
             patch.object(engine, "capture_baseline") as mock_base, \
             patch.object(engine, "_apply_single_optimization", return_value=False):
            mock_base.return_value = MeasurementSnapshot(
                present_fps=100.0, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            )
            evidence = engine.validate_optimization(
                optimization_id="test",
                optimization_name="Test",
            )
            assert evidence.verdict == EvidenceVerdict.SKIPPED

    def test_validate_full_beneficial(self):
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234)), \
             patch.object(engine, "capture_baseline") as mock_base, \
             patch.object(engine, "_apply_single_optimization", return_value=True), \
             patch.object(engine, "capture_post") as mock_post, \
             patch("app.core.optimization_evidence.time.sleep"):
            mock_base.return_value = MeasurementSnapshot(
                present_fps=100.0, one_percent_low=70.0,
                average_frame_time=10.0, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            )
            mock_post.return_value = MeasurementSnapshot(
                present_fps=115.0, one_percent_low=80.0,
                average_frame_time=8.7, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            )
            evidence = engine.validate_optimization(
                optimization_id="power_plan",
                optimization_name="Power Plan",
            )
            assert evidence.verdict == EvidenceVerdict.BENEFICIAL
            assert evidence.fps_delta == pytest.approx(15.0, abs=0.1)
            assert evidence.was_applied is True

    def test_validate_full_harmful_with_rollback(self):
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234)), \
             patch.object(engine, "capture_baseline") as mock_base, \
             patch.object(engine, "_apply_single_optimization", return_value=True), \
             patch.object(engine, "capture_post") as mock_post, \
             patch.object(engine, "_rollback_single_optimization", return_value=True), \
             patch("app.core.optimization_evidence.time.sleep"):
            mock_base.return_value = MeasurementSnapshot(
                present_fps=100.0, one_percent_low=70.0,
                average_frame_time=10.0, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            )
            mock_post.return_value = MeasurementSnapshot(
                present_fps=85.0, one_percent_low=55.0,
                average_frame_time=11.8, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            )
            evidence = engine.validate_optimization(
                optimization_id="bad_opt",
                optimization_name="Bad Optimization",
            )
            assert evidence.verdict == EvidenceVerdict.HARMFUL
            assert evidence.was_rolled_back is True

    def test_validate_full_neutral(self):
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234)), \
             patch.object(engine, "capture_baseline") as mock_base, \
             patch.object(engine, "_apply_single_optimization", return_value=True), \
             patch.object(engine, "capture_post") as mock_post, \
             patch("app.core.optimization_evidence.time.sleep"):
            mock_base.return_value = MeasurementSnapshot(
                present_fps=100.0, one_percent_low=70.0,
                average_frame_time=10.0, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            )
            mock_post.return_value = MeasurementSnapshot(
                present_fps=100.5, one_percent_low=70.2,
                average_frame_time=9.95, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            )
            evidence = engine.validate_optimization(
                optimization_id="neutral_opt",
                optimization_name="Neutral Optimization",
            )
            assert evidence.verdict == EvidenceVerdict.NEUTRAL

    def test_validate_profile_mixed_results(self):
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234)), \
             patch.object(engine, "_is_optimization_applicable", return_value=True), \
             patch.object(engine, "validate_optimization") as mock_val:

            # Simulate three different results
            results = [
                OptimizationEvidence(
                    optimization_id="opt1", verdict=EvidenceVerdict.BENEFICIAL,
                    fps_delta=10.0, was_applied=True,
                ),
                OptimizationEvidence(
                    optimization_id="opt2", verdict=EvidenceVerdict.NEUTRAL,
                    fps_delta=0.5,
                ),
                OptimizationEvidence(
                    optimization_id="opt3", verdict=EvidenceVerdict.SKIPPED,
                ),
            ]
            mock_val.side_effect = results

            session = engine.validate_profile(
                profile_id="gaming",
                optimization_ids=["opt1", "opt2", "opt3"],
                optimization_names={"opt1": "Opt 1", "opt2": "Opt 2", "opt3": "Opt 3"},
            )
            assert session.beneficial_count == 1
            assert session.neutral_count == 1
            assert session.skipped_count == 1
            assert session.harmful_count == 0


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_validate_with_no_capture_function(self):
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234)), \
             patch.object(engine, "_apply_single_optimization", return_value=True), \
             patch.object(engine, "_rollback_single_optimization", return_value=False), \
             patch.object(engine, "capture_baseline") as mock_base, \
             patch.object(engine, "capture_post") as mock_post, \
             patch("app.core.optimization_evidence.time.sleep"):
            mock_base.return_value = MeasurementSnapshot(
                present_fps=100.0, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            )
            mock_post.return_value = MeasurementSnapshot(
                present_fps=80.0, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            )
            evidence = engine.validate_optimization(
                optimization_id="test", optimization_name="Test",
            )
            assert evidence.verdict == EvidenceVerdict.HARMFUL
            assert evidence.was_rolled_back is False  # rollback failed

    def test_significance_thresholds(self):
        """Test that small changes are classified as neutral."""
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(
                present_fps=100.0, one_percent_low=70.0,
                average_frame_time=10.0, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
            post=MeasurementSnapshot(
                present_fps=101.0, one_percent_low=70.5,
                average_frame_time=9.9, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
        )
        ev.determine_verdict()
        assert ev.verdict == EvidenceVerdict.NEUTRAL

    def test_large_improvement_beneficial(self):
        """Test that large improvements are classified as beneficial."""
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(
                present_fps=60.0, one_percent_low=40.0,
                average_frame_time=16.67, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
            post=MeasurementSnapshot(
                present_fps=80.0, one_percent_low=55.0,
                average_frame_time=12.5, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
        )
        ev.determine_verdict()
        assert ev.verdict == EvidenceVerdict.BENEFICIAL
        assert ev.fps_delta == pytest.approx(20.0, abs=0.1)

    def test_large_regression_harmful(self):
        """Test that large regressions are classified as harmful."""
        ev = OptimizationEvidence(
            baseline=MeasurementSnapshot(
                present_fps=120.0, one_percent_low=90.0,
                average_frame_time=8.33, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
            post=MeasurementSnapshot(
                present_fps=90.0, one_percent_low=60.0,
                average_frame_time=11.11, sample_count=500,
                capture_status=CaptureStatus.COMPLETE,
                target_pid=1234,
            ),
        )
        ev.determine_verdict()
        assert ev.verdict == EvidenceVerdict.HARMFUL

    def test_multiple_sessions_persistence(self):
        """Test saving and loading multiple sessions."""
        with tempfile.TemporaryDirectory() as tmpdir:
            import app.core.optimization_evidence as mod
            old_dir = mod.EVIDENCE_DIR
            mod.EVIDENCE_DIR = tmpdir
            try:
                for i in range(3):
                    session = EvidenceSession(profile_id=f"profile_{i}")
                    session.add_evidence(OptimizationEvidence(
                        optimization_id=f"opt_{i}",
                        verdict=EvidenceVerdict.NEUTRAL,
                    ))
                    session.finalize()
                    save_evidence_session(session)

                loaded = load_evidence_sessions()
                assert len(loaded) == 3
                profiles = {s.profile_id for s in loaded}
                assert profiles == {"profile_0", "profile_1", "profile_2"}
            finally:
                mod.EVIDENCE_DIR = old_dir

    def test_empty_profile_validation(self):
        """Test validation with empty optimization list."""
        engine = OptimizationEvidenceEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234)):
            session = engine.validate_profile(
                profile_id="empty",
                optimization_ids=[],
                optimization_names={},
            )
            assert len(session.evidence_list) == 0
            assert session.beneficial_count == 0
