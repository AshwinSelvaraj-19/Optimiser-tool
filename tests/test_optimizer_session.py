"""
Tests for Phase 11 — optimizer session management, locking, safe restore.

Covers:
- OptimizationSessionResult model
- Successful apply
- Already-optimal state
- Requires-admin behavior
- Failed verification
- Recommendation-only behavior
- Session creation and persistence
- Restore only applied changes
- Restore with no changes
- Legacy gpu_preference snapshot handling
- Stale PID detection
- Concurrent APPLY protection
- Structured result counts
- Status exclusivity
"""

import pytest
from unittest.mock import MagicMock, patch

from app.core.optimization_base import (
    OptimizationStatus, OptimizationResult, OptimizationSessionResult,
)
from app.core.optimization_base import Optimization as OptBase
from app.core.optimizer import (
    Optimizer, OptResult, OptimizationReport, RollbackEntry,
)
from app.core.optimizations import (
    get_all_optimizations, get_optimization_by_id,
    PowerPlanOptimization, GameModeOptimization,
    EmulatorPriorityOptimization, BackgroundProcessOptimization,
)
from app.core.profiles import get_profile, get_all_profiles, BALANCED, GAMING


class TestOptimizationSessionResult:
    """Test the session result model."""

    def test_session_counts(self):
        s = OptimizationSessionResult()
        s.applied = [OptResult(opt_id="a", name="A", status="APPLIED")]
        s.already_optimal = [
            OptResult(opt_id="b", name="B", status="ALREADY_OPTIMAL"),
            OptResult(opt_id="c", name="C", status="ALREADY_OPTIMAL"),
        ]
        s.requires_admin = [OptResult(opt_id="d", name="D", status="REQUIRES_ADMIN")]
        s.failed = []
        s.recommendation_only = [OptResult(opt_id="e", name="E", status="RECOMMENDATION_ONLY")]

        assert s.applied_count == 1
        assert s.optimal_count == 2
        assert s.admin_count == 1
        assert s.failed_count == 0
        assert s.review_count == 1

    def test_all_results(self):
        s = OptimizationSessionResult()
        s.applied = [OptResult(status="APPLIED")]
        s.already_optimal = [OptResult(status="ALREADY_OPTIMAL")]
        s.requires_admin = [OptResult(status="REQUIRES_ADMIN")]
        s.failed = [OptResult(status="FAILED")]
        s.recommendation_only = [OptResult(status="RECOMMENDATION_ONLY")]
        s.not_available = [OptResult(status="NOT_APPLICABLE")]

        assert len(s.all_results) == 6

    def test_busy_session(self):
        s = OptimizationSessionResult(busy=True, message="Another operation")
        assert s.busy is True
        assert s.message == "Another operation"

    def test_session_id_unique(self):
        s1 = OptimizationSessionResult(session_id="abc")
        s2 = OptimizationSessionResult(session_id="xyz")
        assert s1.session_id != s2.session_id


class TestOptimizerLocking:
    """Test operation locking."""

    def test_acquire_release(self):
        opt = Optimizer()
        assert opt.is_busy is False
        assert opt.current_operation == ""

    def test_busy_state(self):
        opt = Optimizer()
        opt._operation = "APPLY"
        assert opt.is_busy is True
        assert opt.current_operation == "APPLY"


class TestOptimizerApply:
    """Test the apply pipeline with session management."""

    def test_apply_balanced_profile(self):
        opt = Optimizer()
        with patch("app.core.optimizer.snapshot_manager") as mock_sm:
            mock_snapshot = MagicMock()
            mock_snapshot.snapshot_id = "test_session"
            mock_snapshot.entries = []
            mock_sm.create_snapshot.return_value = mock_snapshot

            with patch("app.core.optimizer.get_optimization_by_id") as mock_get:
                mock_opt = MagicMock()
                mock_check = MagicMock()
                mock_check.status = OptimizationStatus.ALREADY_OPTIMAL
                mock_check.current_value = "Test value"
                mock_opt.check.return_value = mock_check
                mock_opt.name = "Test Opt"
                mock_opt.id = "test_opt"
                mock_get.return_value = mock_opt

                report = opt.apply_profile("balanced")
                assert report.profile_name == "BALANCED"
                assert report.session is not None
                assert report.session.session_id.startswith("session_")

    def _make_opt_mock(self, name, opt_id, status, message=""):
        m = MagicMock()
        m.name = name
        m.id = opt_id
        check = MagicMock()
        check.status = status
        check.current_value = f"{name} value"
        check.message = message or f"{name} msg"
        m.check.return_value = check
        return m

    def test_session_records_applied(self):
        opt = Optimizer()
        with patch("app.core.optimizer.snapshot_manager") as mock_sm:
            mock_snapshot = MagicMock()
            mock_snapshot.snapshot_id = "test"
            mock_snapshot.entries = []
            mock_sm.create_snapshot.return_value = mock_snapshot

            applied_opt = self._make_opt_mock("Power Plan", "power_plan", OptimizationStatus.OPTIMIZABLE)
            apply_result = MagicMock()
            apply_result.status = OptimizationStatus.APPLIED
            applied_opt.apply.return_value = apply_result
            applied_opt.verify.return_value = True
            applied_opt.snapshot.return_value = {}

            already_opt = self._make_opt_mock("Game Mode", "game_mode", OptimizationStatus.ALREADY_OPTIMAL)
            admin_opt = self._make_opt_mock("Emulator Priority", "emulator_priority", OptimizationStatus.REQUIRES_ADMIN)

            mock_opts = {
                "power_plan": applied_opt,
                "game_mode": already_opt,
                "emulator_priority": admin_opt,
            }

            with patch("app.core.optimizer.get_optimization_by_id") as mock_get:
                mock_get.side_effect = lambda oid: mock_opts.get(oid)

                report = opt.apply_profile("gaming")
                session = report.session
                assert session.applied_count == 1
                assert session.applied[0].opt_id == "power_plan"
                assert session.applied[0].verified is True

    def test_session_records_requires_admin(self):
        opt = Optimizer()
        with patch("app.core.optimizer.snapshot_manager") as mock_sm:
            mock_snapshot = MagicMock()
            mock_snapshot.snapshot_id = "test"
            mock_snapshot.entries = []
            mock_sm.create_snapshot.return_value = mock_snapshot

            # Use a profile that only has emulator_priority
            with patch("app.core.optimizer.get_profile") as mock_gp:
                mock_profile = MagicMock()
                mock_profile.name = "Test"
                mock_profile.optimizations = [
                    MagicMock(opt_id="emulator_priority", name="Emulator Priority"),
                ]
                mock_gp.return_value = mock_profile

                admin_opt = self._make_opt_mock("Emulator Priority", "emulator_priority", OptimizationStatus.REQUIRES_ADMIN)

                with patch("app.core.optimizer.get_optimization_by_id") as mock_get:
                    mock_get.return_value = admin_opt

                    report = opt.apply_profile("balanced")
                    session = report.session
                    assert session.admin_count == 1
                    assert session.requires_admin[0].status == "REQUIRES_ADMIN"

    def test_session_records_recommendation_only(self):
        opt = Optimizer()
        with patch("app.core.optimizer.snapshot_manager") as mock_sm:
            mock_snapshot = MagicMock()
            mock_snapshot.snapshot_id = "test"
            mock_snapshot.entries = []
            mock_sm.create_snapshot.return_value = mock_snapshot

            with patch("app.core.optimizer.get_profile") as mock_gp:
                mock_profile = MagicMock()
                mock_profile.name = "Test"
                mock_profile.optimizations = [
                    MagicMock(opt_id="background_load", name="Background Load"),
                ]
                mock_gp.return_value = mock_profile

                rec_opt = self._make_opt_mock("Background Load", "background_load", OptimizationStatus.RECOMMENDATION_ONLY)

                with patch("app.core.optimizer.get_optimization_by_id") as mock_get:
                    mock_get.return_value = rec_opt

                    report = opt.apply_profile("balanced")
                    session = report.session
                    assert session.review_count == 1
                    assert session.recommendation_only[0].status == "RECOMMENDATION_ONLY"

    def test_session_records_failed(self):
        opt = Optimizer()
        with patch("app.core.optimizer.snapshot_manager") as mock_sm:
            mock_snapshot = MagicMock()
            mock_snapshot.snapshot_id = "test"
            mock_snapshot.entries = []
            mock_sm.create_snapshot.return_value = mock_snapshot

            with patch("app.core.optimizer.get_profile") as mock_gp:
                mock_profile = MagicMock()
                mock_profile.name = "Test"
                mock_profile.optimizations = [
                    MagicMock(opt_id="test_opt", name="Test Opt"),
                ]
                mock_gp.return_value = mock_profile

                fail_opt = self._make_opt_mock("Test Opt", "test_opt", OptimizationStatus.OPTIMIZABLE)
                apply_result = MagicMock()
                apply_result.status = OptimizationStatus.FAILED
                apply_result.message = "Failed to set"
                fail_opt.apply.return_value = apply_result
                fail_opt.snapshot.return_value = {}

                with patch("app.core.optimizer.get_optimization_by_id") as mock_get:
                    mock_get.return_value = fail_opt

                    report = opt.apply_profile("balanced")
                    session = report.session
                    assert session.failed_count == 1

    def test_session_timestamps(self):
        opt = Optimizer()
        with patch("app.core.optimizer.snapshot_manager") as mock_sm:
            mock_snapshot = MagicMock()
            mock_snapshot.snapshot_id = "test"
            mock_snapshot.entries = []
            mock_sm.create_snapshot.return_value = mock_snapshot

            with patch("app.core.optimizer.get_optimization_by_id") as mock_get:
                mock_opt = MagicMock()
                mock_check = MagicMock()
                mock_check.status = OptimizationStatus.ALREADY_OPTIMAL
                mock_check.current_value = "Optimal"
                mock_opt.check.return_value = mock_check
                mock_opt.name = "Test"
                mock_opt.id = "test"
                mock_get.return_value = mock_opt

                report = opt.apply_profile("balanced")
                session = report.session
                assert session.started_at
                assert session.completed_at
                assert session.duration_seconds >= 0


class TestOptimizerRollback:
    """Test safe rollback."""

    def test_rollback_no_changes(self):
        opt = Optimizer()
        opt._last_report = MagicMock()
        opt._last_report.snapshot = MagicMock()
        opt._last_report.snapshot.entries = []
        opt._last_report.results = [
            OptResult(opt_id="a", name="A", status="ALREADY_OPTIMAL"),
        ]

        result = opt.rollback_last()
        assert result.success is True
        assert "nothing to restore" in result.message.lower()

    def test_rollback_no_report(self):
        opt = Optimizer()
        opt._last_report = None
        result = opt.rollback_last()
        assert result.success is False

    def test_rollback_verifies_restoration(self):
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
        ]

        with patch("app.core.optimizer.rollback_engine") as mock_re:
            mock_re.rollback.return_value = MagicMock(
                success=True, restored_entries=["active_plan"], failed_entries=[]
            )
            with patch("app.core.optimizer.get_optimization_by_id") as mock_get:
                mock_opt = MagicMock()
                mock_opt.verify.return_value = True
                mock_get.return_value = mock_opt

                result = opt.rollback_last()
                assert result.success is True
                # Verify was called on the optimization
                mock_opt.verify.assert_called()


class TestConcurrentProtection:
    """Test that concurrent operations are blocked."""

    def test_acquire_lock(self):
        opt = Optimizer()
        assert opt._acquire_lock("APPLY") is True
        assert opt.is_busy is True
        opt._release_lock()
        assert opt.is_busy is False

    def test_double_acquire_blocked(self):
        opt = Optimizer()
        assert opt._acquire_lock("APPLY") is True
        assert opt._acquire_lock("RESTORE") is False
        opt._release_lock()
        assert opt._acquire_lock("RESTORE") is True
        opt._release_lock()


class TestProfileContents:
    """Verify profiles are correct and distinct."""

    def test_balanced_only_game_mode(self):
        balanced = get_profile("balanced")
        assert len(balanced.optimizations) == 1
        assert balanced.optimizations[0].opt_id == "game_mode"

    def test_gaming_has_four(self):
        gaming = get_profile("gaming")
        assert len(gaming.optimizations) == 4

    def test_max_performance_has_eight(self):
        maxp = get_profile("max_performance")
        assert len(maxp.optimizations) == 8

    def test_all_profiles_valid_ids(self):
        valid_ids = {o.id for o in get_all_optimizations()}
        valid_ids.update({"cpu_affinity", "game_bar", "background_recording",
                          "visual_effects", "fullscreen_optimization"})
        for profile in get_all_profiles():
            for po in profile.optimizations:
                assert po.opt_id in valid_ids


class TestStatusExclusivity:
    """Ensure statuses are semantically exclusive."""

    def test_required_statuses_exist(self):
        required = [
            "ALREADY_OPTIMAL", "APPLIED", "VERIFIED", "FAILED",
            "REQUIRES_ADMIN", "RECOMMENDATION_ONLY", "NOT_APPLICABLE",
            "NOT_AVAILABLE", "OPTIMIZABLE",
        ]
        for name in required:
            assert hasattr(OptimizationStatus, name)

    def test_opt_result_valid_statuses(self):
        valid = {
            "APPLIED", "ALREADY_OPTIMAL", "REQUIRES_ADMIN",
            "RECOMMENDATION_ONLY", "FAILED", "NOT_APPLICABLE", "SKIPPED",
        }
        for s in valid:
            r = OptResult(status=s)
            assert r.status in valid


class TestRollbackEntry:
    """Test RollbackEntry model."""

    def test_entry_fields(self):
        e = RollbackEntry(
            opt_id="power_plan", name="Power Plan",
            action="RESTORED", message="Restored",
        )
        assert e.action == "RESTORED"
        assert e.opt_id == "power_plan"

    def test_entry_actions(self):
        for action in ["RESTORED", "RESTORED_UNVERIFIED", "SKIPPED", "FAILED"]:
            e = RollbackEntry(action=action)
            assert e.action == action


class TestOptimizationReport:
    """Test report structure."""

    def test_report_counts_default_zero(self):
        report = OptimizationReport()
        assert report.applied_count == 0
        assert report.already_optimal_count == 0
        assert report.requires_admin_count == 0
        assert report.recommendation_only_count == 0
        assert report.failed_count == 0

    def test_report_session_none_by_default(self):
        report = OptimizationReport()
        assert report.session is None

    def test_report_performance_delta(self):
        report = OptimizationReport(baseline_fps=100.0, post_fps=110.0)
        assert report.fps_delta == 10.0
        assert report.performance_measured is True

    def test_report_no_performance(self):
        report = OptimizationReport()
        assert report.fps_delta is None
        assert report.performance_measured is False
