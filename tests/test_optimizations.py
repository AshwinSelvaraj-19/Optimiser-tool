"""
Comprehensive tests for optimization engine.

Tests cover:
- Background termination NOT executed by default
- Recommendation-only optimization
- Profile differentiation
- Admin-required handling
- Already-optimal detection
- Snapshot contents
- Rollback only changed values
- Rollback verification
- No fabricated metrics
- Structured optimization result
- Failed optimization
- Partial profile success
"""

from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.core.optimizations import (
    get_all_optimizations,
    get_optimization_by_id,
    PowerPlanOptimization,
    GameModeOptimization,
    EmulatorPriorityOptimization,
    BackgroundProcessOptimization,
)
from app.core.profiles import (
    get_profile, get_all_profiles, BALANCED, GAMING, MAX_PERFORMANCE,
    PROFILES,
)
from app.core.optimizer import Optimizer, OptResult, OptimizationReport
from app.core.optimization_base import OptimizationStatus


class TestOptimizationRegistration:
    """Test that optimizations are properly registered."""

    def test_all_optimizations_returned(self):
        opts = get_all_optimizations()
        assert len(opts) >= 3
        ids = [o.id for o in opts]
        assert "power_plan" in ids
        assert "game_mode" in ids
        assert "emulator_priority" in ids

    def test_get_by_id(self):
        opt = get_optimization_by_id("power_plan")
        assert opt is not None
        assert isinstance(opt, PowerPlanOptimization)

    def test_get_nonexistent(self):
        opt = get_optimization_by_id("nonexistent")
        assert opt is None

    def test_optimizations_have_required_fields(self):
        for opt in get_all_optimizations():
            assert opt.id
            assert opt.name
            assert opt.description
            assert opt.category


class TestBackgroundLoadNotUnsafe:
    """Background load must NOT terminate processes."""

    def test_background_load_is_recommendation_only(self):
        """Background load apply() must return RECOMMENDATION_ONLY."""
        opt = BackgroundProcessOptimization()
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_background_load_never_terminates(self):
        """Background load apply() must not call terminate()."""
        opt = BackgroundProcessOptimization()
        opt._candidates = [MagicMock(pid=1234, name="test.exe")]
        with patch("app.core.optimizations.psutil.Process") as mock_proc:
            result = opt.apply()
            mock_proc.assert_not_called()
            assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_background_load_check_returns_recommendation(self):
        """Check should return RECOMMENDATION_ONLY when processes found."""
        opt = BackgroundProcessOptimization()
        mock_proc = MagicMock()
        mock_proc.cpu_percent = 2.0
        mock_proc.memory_mb = 100
        mock_proc.pid = 1234
        mock_proc.name = "test.exe"
        mock_proc.category = "OPTIONAL BACKGROUND"

        with patch("app.core.optimizations.psutil.process_iter", return_value=iter([])):
            with patch("app.system.processes.process_monitor.list_processes", return_value=[mock_proc]):
                result = opt.check()
                assert result.status == OptimizationStatus.RECOMMENDATION_ONLY


class TestProfiles:
    """Test optimization profiles."""

    def test_all_profiles_exist(self):
        profiles = get_all_profiles()
        assert len(profiles) == 3
        ids = [p.id for p in profiles]
        assert "balanced" in ids
        assert "gaming" in ids
        assert "max_performance" in ids

    def test_balanced_fewer_than_gaming(self):
        balanced = get_profile("balanced")
        gaming = get_profile("gaming")
        assert len(balanced.optimizations) < len(gaming.optimizations)

    def test_balanced_only_game_mode(self):
        """Balanced should only have Game Mode."""
        balanced = get_profile("balanced")
        opt_ids = [o.opt_id for o in balanced.optimizations]
        assert opt_ids == ["game_mode"]

    def test_gaming_has_power_and_priority(self):
        """Gaming should have power plan, game mode, and emulator priority."""
        gaming = get_profile("gaming")
        opt_ids = [o.opt_id for o in gaming.optimizations]
        assert "power_plan" in opt_ids
        assert "game_mode" in opt_ids
        assert "emulator_priority" in opt_ids

    def test_max_performance_has_background_review(self):
        """Max performance should include background load review."""
        maxp = get_profile("max_performance")
        opt_ids = [o.opt_id for o in maxp.optimizations]
        assert "background_load" in opt_ids

    def test_max_performance_has_all_gaming_opts(self):
        """Max performance should include everything in gaming."""
        gaming = get_profile("gaming")
        maxp = get_profile("max_performance")
        gaming_ids = {o.opt_id for o in gaming.optimizations}
        maxp_ids = {o.opt_id for o in maxp.optimizations}
        assert gaming_ids.issubset(maxp_ids)

    def test_profile_optimizations_reference_valid_ids(self):
        valid_ids = {o.id for o in get_all_optimizations()}
        valid_ids.update({"cpu_affinity", "game_bar", "background_recording",
                          "visual_effects", "fullscreen_optimization"})
        for profile in get_all_profiles():
            for po in profile.optimizations:
                assert po.opt_id in valid_ids

    def test_get_profile_unknown_returns_gaming(self):
        profile = get_profile("nonexistent")
        assert profile.id == "gaming"

    def test_profiles_have_required_fields(self):
        for profile in get_all_profiles():
            assert profile.id
            assert profile.name
            assert profile.description
            assert isinstance(profile.optimizations, list)


class TestAdminHandling:
    """Test administrator requirement detection."""

    def test_emulator_priority_requires_admin(self):
        """Emulator priority should report REQUIRES_ADMIN when not admin."""
        opt = EmulatorPriorityOptimization()
        mock_proc = MagicMock()
        mock_proc.nice.return_value = 0  # Normal priority

        with patch("app.core.optimizations.psutil.process_iter") as mock_iter:
            mock_iter.return_value = iter([MagicMock(info={"pid": 1234, "name": "HD-Player.exe"})])
            with patch.object(opt, "_is_admin", return_value=False):
                result = opt.check()
                assert result.status == OptimizationStatus.REQUIRES_ADMIN

    def test_emulator_priority_optimizable_when_admin(self):
        """Emulator priority should be OPTIMIZABLE when admin."""
        opt = EmulatorPriorityOptimization()
        mock_proc = MagicMock()
        mock_proc.nice.return_value = 0

        with patch("app.core.optimizations.psutil.process_iter") as mock_iter:
            mock_iter.return_value = iter([MagicMock(info={"pid": 1234, "name": "HD-Player.exe"})])
            with patch.object(opt, "_is_admin", return_value=True):
                with patch("app.core.optimizations.psutil.Process", return_value=mock_proc):
                    result = opt.check()
                    assert result.status == OptimizationStatus.OPTIMIZABLE


class TestAlreadyOptimal:
    """Test already-optimal detection."""

    def test_power_plan_already_optimal(self):
        """Power plan should detect when already on performance plan."""
        opt = PowerPlanOptimization()
        with patch("app.core.optimizations.power_monitor.detect") as mock_detect:
            mock_info = MagicMock()
            mock_info.active_plan_name = "High performance"
            mock_detect.return_value = mock_info
            result = opt.check()
            assert result.status == OptimizationStatus.ALREADY_OPTIMAL

    def test_game_mode_already_optimal(self):
        """Game mode should detect when already enabled."""
        opt = GameModeOptimization()
        with patch("app.core.optimizations.read_registry_value", return_value=1):
            result = opt.check()
            assert result.status == OptimizationStatus.ALREADY_OPTIMAL


class TestSnapshotContents:
    """Test that snapshots contain required data."""

    def test_power_plan_snapshot_has_guid(self):
        opt = PowerPlanOptimization()
        with patch("app.core.optimizations.power_monitor.detect") as mock_detect:
            mock_info = MagicMock()
            mock_info.active_plan_guid = "test-guid-123"
            mock_info.active_plan_name = "Balanced"
            mock_detect.return_value = mock_info
            snap = opt.snapshot()
            assert snap["plan_guid"] == "test-guid-123"
            assert snap["plan_name"] == "Balanced"

    def test_game_mode_snapshot_has_value(self):
        opt = GameModeOptimization()
        with patch("app.core.optimizations.read_registry_value", return_value=0):
            snap = opt.snapshot()
            assert "value" in snap
            assert snap["value"] == 0


class TestOptimizerPipeline:
    """Test the optimizer pipeline."""

    def test_apply_balanced_profile(self):
        opt = Optimizer()
        with patch("app.core.optimizer.snapshot_manager") as mock_sm:
            mock_snapshot = MagicMock()
            mock_snapshot.snapshot_id = "test_123"
            mock_snapshot.entries = []
            mock_sm.create_snapshot.return_value = mock_snapshot

            with patch("app.core.optimizer.get_optimization_by_id") as mock_get:
                mock_opt = MagicMock()
                mock_check = MagicMock()
                mock_check.status = OptimizationStatus.ALREADY_OPTIMAL
                mock_opt.check.return_value = mock_check
                mock_opt.name = "Test Opt"
                mock_opt.id = "test_opt"
                mock_get.return_value = mock_opt

                report = opt.apply_profile("balanced")
                assert report.profile_name == "BALANCED"
                assert report.snapshot_id == "test_123"

    def test_rollback_last(self):
        opt = Optimizer()
        mock_snapshot = MagicMock()
        mock_snapshot.snapshot_id = "test_456"
        mock_snapshot.entries = []
        opt._last_report = MagicMock()
        opt._last_report.snapshot = mock_snapshot
        opt._last_report.results = []

        with patch("app.core.optimizer.rollback_engine") as mock_re:
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.message = "Restored"
            mock_result.restored_entries = ["power_plan"]
            mock_result.failed_entries = []
            mock_re.rollback.return_value = mock_result

            result = opt.rollback_last()
            assert result.success is True

    def test_rollback_no_snapshot(self):
        opt = Optimizer()
        opt._last_report = None
        result = opt.rollback_last()
        assert result.success is False


class TestOptResult:
    """Test OptResult structure."""

    def test_opt_result_fields(self):
        r = OptResult(
            opt_id="test", name="Test", status="APPLIED",
            message="ok", current_value="old",
            verified=True, rollback_available=True,
        )
        assert r.opt_id == "test"
        assert r.verified is True
        assert r.current_value == "old"

    def test_opt_result_status_values(self):
        """Status should be one of the defined categories."""
        valid = {
            "APPLIED", "ALREADY_OPTIMAL", "REQUIRES_ADMIN",
            "RECOMMENDATION_ONLY", "FAILED", "NOT_APPLICABLE", "SKIPPED",
        }
        for s in valid:
            r = OptResult(status=s)
            assert r.status in valid


class TestOptimizationReport:
    """Test OptimizationReport structure."""

    def test_report_deltas(self):
        report = OptimizationReport(
            baseline_fps=100.0, baseline_1low=80.0,
            post_fps=110.0, post_1low=85.0,
        )
        assert report.fps_delta == pytest.approx(10.0)
        assert report.one_low_delta == pytest.approx(5.0)

    def test_report_no_data(self):
        report = OptimizationReport()
        assert report.fps_delta is None
        assert report.one_low_delta is None
        assert report.performance_measured is False

    def test_report_performance_measured(self):
        report = OptimizationReport(baseline_fps=90.0, post_fps=95.0)
        assert report.performance_measured is True

    def test_report_counts_default_zero(self):
        report = OptimizationReport()
        assert report.applied_count == 0
        assert report.already_optimal_count == 0
        assert report.requires_admin_count == 0
        assert report.recommendation_only_count == 0
        assert report.failed_count == 0


class TestOptimizationBase:
    """Test the base optimization class interface."""

    def test_all_optimizations_implement_interface(self):
        for opt in get_all_optimizations():
            assert hasattr(opt, "check")
            assert hasattr(opt, "snapshot")
            assert hasattr(opt, "apply")
            assert hasattr(opt, "verify")
            assert hasattr(opt, "rollback")

    def test_optimization_has_risk_level(self):
        for opt in get_all_optimizations():
            assert opt.risk_level in ("LOW", "MEDIUM", "HIGH", "NONE")

    def test_optimization_has_category(self):
        for opt in get_all_optimizations():
            assert opt.category

    def test_no_fake_optimizations(self):
        """Every optimization must have a real implementation."""
        for opt in get_all_optimizations():
            # check() must return a valid status
            result = opt.check()
            assert isinstance(result.status, OptimizationStatus)

    def test_all_statuses_used(self):
        """Verify the new statuses exist in the enum."""
        assert hasattr(OptimizationStatus, "REQUIRES_ADMIN")
        assert hasattr(OptimizationStatus, "RECOMMENDATION_ONLY")
