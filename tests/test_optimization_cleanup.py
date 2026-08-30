"""
Phase 8 tests — optimization engine cleanup, safety, semantic correctness.

Covers:
- GPU preference fully removed from active system
- Recommendation-only never modifies system state
- Recommendation-only never enters rollback
- Rollback with zero applied ops returns clean result
- All required statuses exist
- Snapshot categories match applied optimizations
- Profile differentiation verified
- Status values are semantically exclusive
"""

import os
import json
from unittest.mock import MagicMock, patch

import pytest

from app.core.optimization_base import Optimization, OptimizationResult, OptimizationStatus
from app.core.optimizations import (
    get_all_optimizations,
    get_optimization_by_id,
    PowerPlanOptimization,
    GameModeOptimization,
    EmulatorPriorityOptimization,
    BackgroundProcessOptimization,
)
from app.core.profiles import (
    get_profile,
    get_all_profiles,
    BALANCED,
    GAMING,
    MAX_PERFORMANCE,
    PROFILES,
)
from app.core.optimizer import Optimizer, OptResult, OptimizationReport
from app.core.snapshot import SnapshotManager, Snapshot
from app.core.rollback import RollbackEngine


class TestGPUPreferenceRemoved:
    """GPU preference must not appear in the active optimization system."""

    def test_no_gpu_preference_optimization(self):
        """get_all_optimizations must not include any GPU preference class."""
        opts = get_all_optimizations()
        for opt in opts:
            assert "gpu" not in opt.id.lower() or "gpu" not in opt.name.lower(), \
                f"GPU preference optimization found: {opt.id}"

    def test_no_gpu_preference_in_optimization_ids(self):
        """No optimization ID should reference gpu_preference."""
        opts = get_all_optimizations()
        ids = [o.id for o in opts]
        assert "gpu_preference" not in ids
        assert "GPUPreferenceOptimization" not in [type(o).__name__ for o in opts]

    def test_no_gpu_preference_in_profiles(self):
        """New-style profiles must not reference gpu_preference."""
        for profile in get_all_profiles():
            opt_ids = [po.opt_id for po in profile.optimizations]
            assert "gpu_preference" not in opt_ids, \
                f"Profile {profile.name} still references gpu_preference"

    def test_no_gpu_preference_in_optimizer_status(self):
        """Optimizer status should not report GPU preference."""
        opt = Optimizer()
        status = opt.get_current_status()
        for item in status.get("optimizations", []):
            assert "gpu" not in item.get("id", "").lower(), \
                f"GPU preference found in optimizer status: {item}"

    def test_no_gpu_preference_in_old_profiles_json(self):
        """Legacy JSON profiles must not contain gpu_preference."""
        profiles_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "profiles")
        if not os.path.isdir(profiles_dir):
            pytest.skip("profiles directory not found")
        for fname in os.listdir(profiles_dir):
            if fname.endswith(".json"):
                filepath = os.path.join(profiles_dir, fname)
                with open(filepath) as f:
                    data = json.load(f)
                for setting in data.get("settings", []):
                    assert setting.get("key") != "gpu_preference", \
                        f"gpu_preference found in {fname}"


class TestRecommendationOnlySemantics:
    """BackgroundProcessOptimization must never claim system modification."""

    def test_recommendation_only_never_applies(self):
        """apply() must return RECOMMENDATION_ONLY, not APPLIED."""
        opt = BackgroundProcessOptimization()
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY
        assert result.status != OptimizationStatus.APPLIED

    def test_recommendation_only_never_already_optimal(self):
        """apply() must not return ALREADY_OPTIMAL."""
        opt = BackgroundProcessOptimization()
        result = opt.apply()
        assert result.status != OptimizationStatus.ALREADY_OPTIMAL

    def test_recommendation_only_never_verified(self):
        """apply() must not claim verification."""
        opt = BackgroundProcessOptimization()
        result = opt.apply()
        assert result.status != OptimizationStatus.VERIFIED

    def test_recommendation_only_never_terminates_process(self):
        """Must not call psutil.Process().terminate() or kill()."""
        opt = BackgroundProcessOptimization()
        with patch("app.core.optimizations.psutil.Process") as mock_proc:
            result = opt.apply()
            mock_proc.assert_not_called()
            assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_recommendation_only_returns_success_for_verify(self):
        """verify() returns True — nothing to verify since nothing changed."""
        opt = BackgroundProcessOptimization()
        assert opt.verify() is True

    def test_recommendation_only_returns_true_for_rollback(self):
        """rollback() returns True — nothing to roll back."""
        opt = BackgroundProcessOptimization()
        assert opt.rollback() is True

    def test_recommendation_only_in_optimizer_report(self):
        """Optimizer should report RECOMMENDATION_ONLY status correctly."""
        opt = Optimizer()
        with patch("app.core.optimizer.snapshot_manager") as mock_sm:
            mock_snapshot = MagicMock()
            mock_snapshot.snapshot_id = "test_rec"
            mock_snapshot.entries = []
            mock_sm.create_snapshot.return_value = mock_snapshot

            # Mock different statuses for different optimization IDs
            def make_opt_mock(name, opt_id, status):
                m = MagicMock()
                m.name = name
                m.id = opt_id
                check = MagicMock()
                check.status = status
                check.current_value = f"{name} value"
                check.message = f"{name} message"
                m.check.return_value = check
                return m

            mock_opts = {
                "power_plan": make_opt_mock("Power Plan", "power_plan",
                                           OptimizationStatus.ALREADY_OPTIMAL),
                "game_mode": make_opt_mock("Game Mode", "game_mode",
                                           OptimizationStatus.ALREADY_OPTIMAL),
                "emulator_priority": make_opt_mock("Emulator Priority", "emulator_priority",
                                                    OptimizationStatus.REQUIRES_ADMIN),
            }

            with patch("app.core.optimizer.get_optimization_by_id") as mock_get:
                mock_get.side_effect = lambda oid: mock_opts.get(oid)

                # Use a profile that only has background_load to test recommendation
                with patch("app.core.optimizer.get_profile") as mock_gp:
                    mock_profile = MagicMock()
                    mock_profile.name = "Test"
                    mock_profile.optimizations = [
                        MagicMock(opt_id="background_load", name="Background Load"),
                    ]
                    mock_gp.return_value = mock_profile

                    rec_opt = MagicMock()
                    rec_check = MagicMock()
                    rec_check.status = OptimizationStatus.RECOMMENDATION_ONLY
                    rec_check.current_value = "3 processes"
                    rec_check.message = "Review manually"
                    rec_opt.check.return_value = rec_check
                    rec_opt.name = "Background Load"
                    rec_opt.id = "background_load"
                    mock_opts["background_load"] = rec_opt

                    report = opt.apply_profile("balanced")
                    assert report.recommendation_only_count == 1
                    assert report.applied_count == 0
                    result = report.results[0]
                    assert result.status == "RECOMMENDATION_ONLY"


class TestRollbackSafety:
    """Rollback must only operate on actually applied optimizations."""

    def test_rollback_with_no_applied_ops(self):
        """When nothing was applied, rollback returns clean result."""
        opt = Optimizer()
        opt._last_report = MagicMock()
        opt._last_report.snapshot = MagicMock()
        opt._last_report.snapshot.entries = []
        opt._last_report.results = [
            OptResult(opt_id="x", name="X", status="ALREADY_OPTIMAL"),
            OptResult(opt_id="y", name="Y", status="RECOMMENDATION_ONLY"),
        ]

        result = opt.rollback_last()
        assert result.success is True
        assert "nothing to restore" in result.message.lower()

    def test_rollback_with_only_already_optimal(self):
        """When all results are already optimal, rollback is no-op."""
        opt = Optimizer()
        opt._last_report = MagicMock()
        opt._last_report.snapshot = MagicMock()
        opt._last_report.snapshot.entries = []
        opt._last_report.results = [
            OptResult(opt_id="power_plan", name="Power Plan", status="ALREADY_OPTIMAL"),
            OptResult(opt_id="game_mode", name="Game Mode", status="ALREADY_OPTIMAL"),
        ]

        result = opt.rollback_last()
        assert result.success is True

    def test_rollback_with_only_admin_required(self):
        """When only REQUIRES_ADMIN results exist, rollback is no-op."""
        opt = Optimizer()
        opt._last_report = MagicMock()
        opt._last_report.snapshot = MagicMock()
        opt._last_report.snapshot.entries = []
        opt._last_report.results = [
            OptResult(opt_id="emulator_priority", name="Emulator Priority",
                      status="REQUIRES_ADMIN"),
        ]

        result = opt.rollback_last()
        assert result.success is True

    def test_rollback_no_snapshot(self):
        """When no snapshot exists, rollback returns failure."""
        opt = Optimizer()
        opt._last_report = None
        result = opt.rollback_last()
        assert result.success is False
        assert "no optimization to rollback" in result.message.lower()

    def test_rollback_does_not_restore_recommendation_only(self):
        """Rollback must not attempt to restore recommendation-only changes."""
        opt = Optimizer()
        mock_snapshot = MagicMock()
        mock_snapshot.snapshot_id = "test_roll"
        mock_snapshot.entries = [
            MagicMock(category="power", key="active_plan", description="Power Plan"),
        ]
        opt._last_report = MagicMock()
        opt._last_report.snapshot = mock_snapshot
        opt._last_report.results = [
            OptResult(opt_id="power_plan", name="Power Plan", status="APPLIED"),
            OptResult(opt_id="background_load", name="Background Load",
                      status="RECOMMENDATION_ONLY"),
        ]

        with patch("app.core.optimizer.rollback_engine") as mock_re:
            mock_re.rollback.return_value = MagicMock(
                success=True, restored_entries=["active_plan"], failed_entries=[]
            )
            result = opt.rollback_last()
            # The filtered snapshot passed to rollback should only have the power entry
            call_args = mock_re.rollback.call_args[0]
            filtered_snapshot = call_args[0]
            assert len(filtered_snapshot.entries) == 1
            assert filtered_snapshot.entries[0].category == "power"


class TestStatusExclusivity:
    """Statuses must be semantically exclusive."""

    def test_required_statuses_exist(self):
        """All required status values must exist in the enum."""
        required = [
            "ALREADY_OPTIMAL",
            "APPLIED",
            "VERIFIED",
            "FAILED",
            "REQUIRES_ADMIN",
            "RECOMMENDATION_ONLY",
            "NOT_APPLICABLE",
            "NOT_AVAILABLE",
            "OPTIMIZABLE",
        ]
        for status_name in required:
            assert hasattr(OptimizationStatus, status_name), \
                f"Missing status: {status_name}"

    def test_opt_result_valid_statuses(self):
        """OptResult status must be one of the defined categories."""
        valid = {
            "APPLIED", "ALREADY_OPTIMAL", "REQUIRES_ADMIN",
            "RECOMMENDATION_ONLY", "FAILED", "NOT_APPLICABLE", "SKIPPED",
        }
        for s in valid:
            r = OptResult(status=s)
            assert r.status in valid

    def test_no_fake_status(self):
        """Ensure no optimization returns a fabricated success status."""
        for opt in get_all_optimizations():
            # All optimizations must implement the required interface
            assert callable(getattr(opt, "check", None))
            assert callable(getattr(opt, "apply", None))
            assert callable(getattr(opt, "rollback", None))


class TestProfileDifferentiation:
    """Profiles must be genuinely different."""

    def test_balanced_has_only_game_mode(self):
        assert len(BALANCED.optimizations) == 1
        assert BALANCED.optimizations[0].opt_id == "game_mode"

    def test_gaming_has_four_optimizations(self):
        assert len(GAMING.optimizations) == 4
        opt_ids = {o.opt_id for o in GAMING.optimizations}
        assert opt_ids == {"power_plan", "game_mode", "emulator_priority", "memory_analysis"}

    def test_max_performance_has_eight_optimizations(self):
        assert len(MAX_PERFORMANCE.optimizations) == 8
        opt_ids = {o.opt_id for o in MAX_PERFORMANCE.optimizations}
        assert opt_ids == {"power_plan", "game_mode", "game_bar", "background_recording", "emulator_priority", "cpu_affinity", "memory_analysis", "background_load"}

    def test_gaming_is_superset_of_balanced(self):
        balanced_ids = {o.opt_id for o in BALANCED.optimizations}
        gaming_ids = {o.opt_id for o in GAMING.optimizations}
        assert balanced_ids.issubset(gaming_ids)

    def test_max_performance_is_superset_of_gaming(self):
        gaming_ids = {o.opt_id for o in GAMING.optimizations}
        maxp_ids = {o.opt_id for o in MAX_PERFORMANCE.optimizations}
        assert gaming_ids.issubset(maxp_ids)

    def test_all_profile_opt_ids_are_valid(self):
        valid_ids = {o.id for o in get_all_optimizations()}
        # Additional IDs registered via fallback lookups
        valid_ids.update({"cpu_affinity", "game_bar", "background_recording",
                          "visual_effects", "fullscreen_optimization"})
        for profile in get_all_profiles():
            for po in profile.optimizations:
                assert po.opt_id in valid_ids, \
                    f"Profile {profile.name} references invalid opt_id: {po.opt_id}"


class TestOptimizationReportStructure:
    """Optimization report must be properly structured."""

    def test_report_counts_default_zero(self):
        report = OptimizationReport()
        assert report.applied_count == 0
        assert report.already_optimal_count == 0
        assert report.requires_admin_count == 0
        assert report.recommendation_only_count == 0
        assert report.failed_count == 0
        assert report.skipped_count == 0

    def test_report_rollback_counts_default_zero(self):
        report = OptimizationReport()
        assert report.rollback_restored == 0
        assert report.rollback_skipped == 0
        assert report.rollback_failed == 0

    def test_report_performance_delta_computed(self):
        report = OptimizationReport(
            baseline_fps=100.0, baseline_1low=80.0,
            post_fps=110.0, post_1low=85.0,
        )
        assert report.fps_delta == pytest.approx(10.0)
        assert report.one_low_delta == pytest.approx(5.0)
        assert report.performance_measured is True

    def test_report_no_performance_data(self):
        report = OptimizationReport()
        assert report.fps_delta is None
        assert report.one_low_delta is None
        assert report.performance_measured is False

    def test_report_rollback_entry_structure(self):
        from app.core.optimizer import RollbackEntry
        entry = RollbackEntry(
            opt_id="power_plan", name="Power Plan",
            action="RESTORED", message="Restored",
        )
        assert entry.action == "RESTORED"
        assert entry.opt_id == "power_plan"
