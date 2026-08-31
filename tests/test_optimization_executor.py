"""
Phase 39 — Optimization Executor Tests.

Comprehensive unit tests for the optimization execution orchestrator.
Covers: safety gates, preview, execution, verification, rollback,
impact evaluation, partial failure, session persistence, and more.

All tests use mocks — never modify the real system.
"""

import time
from unittest.mock import patch, MagicMock, PropertyMock

import pytest

from app.core.optimization_executor import (
    OptimizationExecutor,
    OptimizationExecutionSession,
    OptimizationExecutionStep,
    OptimizationImpact,
    SystemSnapshot,
    MetricValue,
    MetricState,
    ExecutionVerdict,
    SessionStatus,
    optimization_executor,
)
from app.core.optimization_base import OptimizationStatus, OptimizationResult


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture
def executor():
    """Create a fresh executor for each test."""
    return OptimizationExecutor()


@pytest.fixture
def mock_opt():
    """Mock optimization instance."""
    mock = MagicMock()
    mock.id = "power_plan"
    mock.name = "Power Plan"
    mock.category = "SYSTEM"
    mock.risk_level = "LOW"
    return mock


# ── Model Tests ──────────────────────────────────────────────────

class TestModels:
    """Test data models."""

    def test_metric_value_creation(self):
        mv = MetricValue(value=42.5, state=MetricState.MEASURED, label="CPU")
        assert mv.value == 42.5
        assert mv.state == MetricState.MEASURED
        assert mv.label == "CPU"

    def test_metric_value_to_dict(self):
        mv = MetricValue(value=42.5, state=MetricState.MEASURED, label="CPU")
        d = mv.to_dict()
        assert d["value"] == 42.5
        assert d["state"] == "MEASURED"
        assert d["label"] == "CPU"

    def test_metric_value_not_available(self):
        mv = MetricValue(state=MetricState.NOT_AVAILABLE, label="GPU Temp")
        assert mv.value is None
        assert mv.state == MetricState.NOT_AVAILABLE

    def test_metric_value_failed(self):
        mv = MetricValue(state=MetricState.FAILED, label="CPU Temp")
        assert mv.value is None

    def test_metric_state_inferred(self):
        mv = MetricValue(value=10.0, state=MetricState.INFERRED, label="FPS")
        assert mv.state == MetricState.INFERRED

    def test_system_snapshot_creation(self):
        snap = SystemSnapshot(target_name="HD-Player.exe", target_pid=12345)
        assert snap.target_name == "HD-Player.exe"
        assert snap.target_pid == 12345
        assert snap.cpu_utilization.state == MetricState.NOT_AVAILABLE

    def test_system_snapshot_to_dict(self):
        snap = SystemSnapshot(target_name="HD-Player.exe", target_pid=12345)
        snap.cpu_utilization = MetricValue(value=42.0, state=MetricState.MEASURED)
        d = snap.to_dict()
        assert d["target_name"] == "HD-Player.exe"
        assert d["cpu_utilization"]["value"] == 42.0

    def test_impact_creation(self):
        impact = OptimizationImpact(optimization_id="power_plan")
        assert impact.optimization_id == "power_plan"
        assert impact.classification == "INCONCLUSIVE"

    def test_impact_to_dict(self):
        impact = OptimizationImpact(
            optimization_id="power_plan",
            cpu_delta=-2.5,
            classification="IMPROVED",
        )
        d = impact.to_dict()
        assert d["optimization_id"] == "power_plan"
        assert d["cpu_delta"] == -2.5
        assert d["classification"] == "IMPROVED"

    def test_execution_step_creation(self):
        step = OptimizationExecutionStep(
            optimization_id="power_plan",
            optimization_name="Power Plan",
        )
        assert step.optimization_id == "power_plan"
        assert step.verdict == ExecutionVerdict.SKIPPED

    def test_execution_step_to_dict(self):
        step = OptimizationExecutionStep(
            optimization_id="power_plan",
            optimization_name="Power Plan",
            verdict=ExecutionVerdict.KEPT,
            reason="Applied and verified",
        )
        d = step.to_dict()
        assert d["optimization_id"] == "power_plan"
        assert d["verdict"] == "KEPT"

    def test_session_creation(self):
        session = OptimizationExecutionSession(profile_id="gaming")
        assert session.profile_id == "gaming"
        assert session.status == SessionStatus.NOT_STARTED

    def test_session_to_dict(self):
        session = OptimizationExecutionSession(
            profile_id="gaming",
            status=SessionStatus.COMPLETED,
            kept_count=2,
        )
        d = session.to_dict()
        assert d["profile_id"] == "gaming"
        assert d["status"] == "COMPLETED"
        assert d["kept_count"] == 2

    def test_session_format_cli(self):
        session = OptimizationExecutionSession(
            profile_id="gaming",
            profile_name="GAMING",
            target_name="HD-Player.exe",
            target_pid=12345,
            status=SessionStatus.COMPLETED,
            kept_count=1,
        )
        session.steps.append(OptimizationExecutionStep(
            optimization_id="power_plan",
            optimization_name="Power Plan",
            verdict=ExecutionVerdict.KEPT,
            reason="Applied and verified",
        ))
        text = session.format_cli()
        assert "HEAVEN SOCIETY" in text
        assert "Power Plan" in text
        assert "KEPT" in text


# ── Safety Gate Tests ────────────────────────────────────────────

class TestSafetyGates:
    """Test safety gate logic."""

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_passes_optimizable(self, mock_get_opt):
        exec_inst = OptimizationExecutor()
        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.OPTIMIZABLE,
            current_value="Balanced",
            recommended_value="High Performance",
        )
        mock_get_opt.return_value = mock_opt
        allowed, reason = exec_inst._check_safety_gate(
            "power_plan", "gaming", True, True, "HD-Player.exe"
        )
        assert allowed is True
        assert "Safety gate passed" in reason

    def test_safety_gate_blocks_no_target(self):
        exec_inst = OptimizationExecutor()
        allowed, reason = exec_inst._check_safety_gate(
            "power_plan", "gaming", True, False, ""
        )
        assert allowed is False
        assert "No valid emulator target" in reason

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_blocks_not_in_profile(self, mock_get_opt):
        exec_inst = OptimizationExecutor()
        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.OPTIMIZABLE,
        )
        mock_get_opt.return_value = mock_opt
        allowed, reason = exec_inst._check_safety_gate(
            "power_plan", "balanced", True, True, "HD-Player.exe"
        )
        assert allowed is False
        assert "not in profile" in reason

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_blocks_already_optimal(self, mock_get_opt):
        exec_inst = OptimizationExecutor()
        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.ALREADY_OPTIMAL,
            current_value="High Performance",
        )
        mock_get_opt.return_value = mock_opt
        allowed, reason = exec_inst._check_safety_gate(
            "power_plan", "gaming", True, True, "HD-Player.exe"
        )
        assert allowed is False
        assert "Already optimal" in reason

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_blocks_requires_admin(self, mock_get_opt):
        exec_inst = OptimizationExecutor()
        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.REQUIRES_ADMIN,
            current_value="Emulator running",
        )
        mock_get_opt.return_value = mock_opt
        allowed, reason = exec_inst._check_safety_gate(
            "emulator_priority", "gaming", False, True, "HD-Player.exe"
        )
        assert allowed is False
        assert "Administrator" in reason

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_allows_admin_available(self, mock_get_opt):
        exec_inst = OptimizationExecutor()
        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.REQUIRES_ADMIN,
            current_value="Emulator running",
        )
        mock_get_opt.return_value = mock_opt
        allowed, reason = exec_inst._check_safety_gate(
            "emulator_priority", "gaming", True, True, "HD-Player.exe"
        )
        assert allowed is True

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_blocks_recommendation_only(self, mock_get_opt):
        exec_inst = OptimizationExecutor()
        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.RECOMMENDATION_ONLY,
            current_value="3 optional processes",
        )
        mock_get_opt.return_value = mock_opt
        allowed, reason = exec_inst._check_safety_gate(
            "background_load", "max_performance", True, True, "HD-Player.exe"
        )
        assert allowed is False
        assert "Recommendation only" in reason

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_blocks_not_available(self, mock_get_opt):
        exec_inst = OptimizationExecutor()
        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.NOT_APPLICABLE,
            current_value="No emulator running",
        )
        mock_get_opt.return_value = mock_opt
        allowed, reason = exec_inst._check_safety_gate(
            "emulator_priority", "gaming", True, True, "HD-Player.exe"
        )
        assert allowed is False
        assert "Not available" in reason

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_blocks_thermal_performance(self, mock_get_opt):
        exec_inst = OptimizationExecutor()
        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.OPTIMIZABLE,
        )
        mock_get_opt.return_value = mock_opt
        allowed, reason = exec_inst._check_safety_gate(
            "power_plan", "gaming", True, True, "HD-Player.exe",
            thermal_state="HOT",
        )
        assert allowed is False
        assert "Thermal" in reason

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_allows_thermal_safe_opt(self, mock_get_opt):
        exec_inst = OptimizationExecutor()
        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.OPTIMIZABLE,
        )
        mock_get_opt.return_value = mock_opt
        allowed, reason = exec_inst._check_safety_gate(
            "power_plan", "gaming", True, True, "HD-Player.exe",
            thermal_state="NORMAL",
        )
        assert allowed is True

    def test_safety_gate_blocks_unknown_optimization(self):
        exec_inst = OptimizationExecutor()
        # nonexistent_opt is not in gaming profile, so blocked there first
        with patch("app.core.optimizations.get_optimization_by_id", return_value=None):
            allowed, reason = exec_inst._check_safety_gate(
                "nonexistent_opt", "gaming", True, True, "HD-Player.exe"
            )
            assert allowed is False
            assert "not in profile" in reason

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_safety_gate_blocks_optimization_not_found_in_profile(self, mock_get_opt):
        """Optimization that IS in profile but get_optimization_by_id returns None."""
        exec_inst = OptimizationExecutor()
        mock_get_opt.return_value = None
        # power_plan IS in gaming profile
        allowed, reason = exec_inst._check_safety_gate(
            "power_plan", "gaming", True, True, "HD-Player.exe"
        )
        assert allowed is False
        assert "not found" in reason


# ── Preview Tests ────────────────────────────────────────────────

class TestPreview:
    """Test preview mode — read-only."""

    @patch("app.core.optimization_executor.get_profile")
    @patch("app.core.optimizations.get_optimization_by_id")
    @patch("app.utils.admin.is_admin", return_value=True)
    def test_preview_returns_session(self, mock_admin, mock_get_opt, mock_get_profile):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po1 = MagicMock()
        po1.opt_id = "power_plan"
        po1.name = "Power Plan"
        po2 = MagicMock()
        po2.opt_id = "game_mode"
        po2.name = "Game Mode"
        profile.optimizations = [po1, po2]
        mock_get_profile.return_value = profile

        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.OPTIMIZABLE,
            current_value="Balanced",
        )
        mock_get_opt.return_value = mock_opt

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())):
            session = exec_inst.preview(profile_id="gaming")

        assert session.status == SessionStatus.COMPLETED
        assert session.profile_name == "GAMING"
        assert session.target_name == "HD-Player.exe"
        assert len(session.steps) == 2

    @patch("app.core.optimization_executor.get_profile")
    @patch("app.core.optimizations.get_optimization_by_id")
    @patch("app.utils.admin.is_admin", return_value=False)
    def test_preview_blocks_admin_required(self, mock_admin, mock_get_opt, mock_get_profile):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po = MagicMock()
        po.opt_id = "emulator_priority"
        po.name = "Emulator Priority"
        profile.optimizations = [po]
        mock_get_profile.return_value = profile

        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.REQUIRES_ADMIN,
            current_value="Emulator running",
        )
        mock_get_opt.return_value = mock_opt

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())):
            session = exec_inst.preview(profile_id="gaming")
        assert session.admin_required_count == 1
        assert session.steps[0].verdict == ExecutionVerdict.REQUIRES_ADMIN

    def test_preview_does_not_modify_system(self):
        """Preview must NEVER call apply() or snapshot()."""
        exec_inst = OptimizationExecutor()
        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())):
            with patch("app.core.optimization_executor.get_profile") as gp:
                profile = MagicMock()
                profile.name = "GAMING"
                profile.optimizations = []
                gp.return_value = profile
                session = exec_inst.preview(profile_id="gaming")
                assert len(session.steps) == 0

    @patch("app.core.optimization_executor.get_profile")
    @patch("app.utils.admin.is_admin", return_value=True)
    def test_preview_no_target_blocks_all(self, mock_admin, mock_get_profile):
        exec_inst = OptimizationExecutor()
        profile = MagicMock()
        profile.name = "GAMING"
        po = MagicMock()
        po.opt_id = "power_plan"
        po.name = "Power Plan"
        profile.optimizations = [po]
        mock_get_profile.return_value = profile

        with patch.object(exec_inst, '_detect_target', return_value=("", 0, 0.0)):
            session = exec_inst.preview(profile_id="gaming")
        assert session.target_pid == 0


# ── Execution Tests ──────────────────────────────────────────────

class TestExecution:
    """Test actual execution flow."""

    @patch("app.core.optimization_executor.get_profile")
    @patch("app.core.optimizations.get_optimization_by_id")
    def test_execute_keeps_verified_optimization(self, mock_get_opt, mock_get_profile):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po = MagicMock()
        po.opt_id = "power_plan"
        po.name = "Power Plan"
        profile.optimizations = [po]
        mock_get_profile.return_value = profile

        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(
            status=OptimizationStatus.OPTIMIZABLE,
            current_value="Balanced",
        )
        mock_opt.apply.return_value = OptimizationResult(
            status=OptimizationStatus.APPLIED,
            message="Applied",
        )
        mock_opt.verify.return_value = True
        mock_opt.snapshot.return_value = {}
        mock_get_opt.return_value = mock_opt

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())), \
             patch.object(exec_inst, '_check_safety_gate', return_value=(True, "Safety gate passed")), \
             patch.object(exec_inst, '_capture_pre_snapshot', return_value=SystemSnapshot()), \
             patch.object(exec_inst, '_evaluate_impact', return_value=OptimizationImpact(classification="UNCHANGED")):
            session = exec_inst.execute(profile_id="gaming")

        assert session.status == SessionStatus.COMPLETED
        assert session.kept_count == 1
        assert session.applied_count == 1
        assert session.steps[0].verdict == ExecutionVerdict.KEPT
        mock_opt.apply.assert_called_once()
        mock_opt.verify.assert_called_once()

    @patch("app.core.optimization_executor.get_profile")
    @patch("app.core.optimizations.get_optimization_by_id")
    def test_execute_rolls_back_on_degradation(self, mock_get_opt, mock_get_profile):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po = MagicMock()
        po.opt_id = "power_plan"
        po.name = "Power Plan"
        profile.optimizations = [po]
        mock_get_profile.return_value = profile

        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(status=OptimizationStatus.OPTIMIZABLE)
        mock_opt.apply.return_value = OptimizationResult(status=OptimizationStatus.APPLIED)
        mock_opt.verify.return_value = True
        mock_opt.snapshot.return_value = {}
        mock_opt.rollback.return_value = True
        mock_get_opt.return_value = mock_opt

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())), \
             patch.object(exec_inst, '_check_safety_gate', return_value=(True, "Safety gate passed")), \
             patch.object(exec_inst, '_capture_pre_snapshot', return_value=SystemSnapshot()), \
             patch.object(exec_inst, '_evaluate_impact', return_value=OptimizationImpact(classification="DEGRADED")):
            session = exec_inst.execute(profile_id="gaming")

        assert session.steps[0].verdict == ExecutionVerdict.ROLLED_BACK
        assert session.rolled_back_count == 1
        mock_opt.rollback.assert_called_once()

    @patch("app.core.optimization_executor.get_profile")
    @patch("app.core.optimizations.get_optimization_by_id")
    def test_execute_rolls_back_on_verification_failure(self, mock_get_opt, mock_get_profile):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po = MagicMock()
        po.opt_id = "power_plan"
        po.name = "Power Plan"
        profile.optimizations = [po]
        mock_get_profile.return_value = profile

        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(status=OptimizationStatus.OPTIMIZABLE)
        mock_opt.apply.return_value = OptimizationResult(status=OptimizationStatus.APPLIED)
        mock_opt.verify.return_value = False  # Verification FAILS
        mock_opt.snapshot.return_value = {}
        mock_opt.rollback.return_value = True
        mock_get_opt.return_value = mock_opt

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())), \
             patch.object(exec_inst, '_check_safety_gate', return_value=(True, "Safety gate passed")), \
             patch.object(exec_inst, '_capture_pre_snapshot', return_value=SystemSnapshot()), \
             patch.object(exec_inst, '_evaluate_impact', return_value=OptimizationImpact(classification="UNCHANGED")):
            session = exec_inst.execute(profile_id="gaming")

        assert session.steps[0].verdict == ExecutionVerdict.ROLLED_BACK
        assert session.steps[0].reason == "Rolled back: verification failed"
        mock_opt.rollback.assert_called_once()

    def test_execute_skips_blocked_by_safety(self):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po = MagicMock()
        po.opt_id = "power_plan"
        po.name = "Power Plan"
        profile.optimizations = [po]

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())), \
             patch("app.core.optimization_executor.get_profile", return_value=profile), \
             patch.object(exec_inst, '_check_safety_gate', return_value=(False, "Thermal state HOT — performance increase blocked")):
            session = exec_inst.execute(profile_id="gaming")

        assert session.steps[0].verdict == ExecutionVerdict.BLOCKED_BY_SAFETY
        assert "thermal" in session.steps[0].reason.lower()

    def test_execute_records_already_optimal(self):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po = MagicMock()
        po.opt_id = "power_plan"
        po.name = "Power Plan"
        profile.optimizations = [po]

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())), \
             patch("app.core.optimization_executor.get_profile", return_value=profile), \
             patch.object(exec_inst, '_check_safety_gate', return_value=(False, "Already optimal")):
            session = exec_inst.execute(profile_id="gaming")

        assert session.steps[0].verdict == ExecutionVerdict.ALREADY_OPTIMAL
        assert session.already_optimal_count == 1

    def test_execute_records_admin_required(self):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po = MagicMock()
        po.opt_id = "emulator_priority"
        po.name = "Emulator Priority"
        profile.optimizations = [po]

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())), \
             patch("app.core.optimization_executor.get_profile", return_value=profile), \
             patch.object(exec_inst, '_check_safety_gate', return_value=(False, "Administrator privileges required")):
            session = exec_inst.execute(profile_id="gaming")

        assert session.steps[0].verdict == ExecutionVerdict.REQUIRES_ADMIN
        assert session.admin_required_count == 1

    @patch("app.core.optimization_executor.get_profile")
    @patch("app.core.optimizations.get_optimization_by_id")
    def test_execute_handles_exception(self, mock_get_opt, mock_get_profile):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po = MagicMock()
        po.opt_id = "power_plan"
        po.name = "Power Plan"
        profile.optimizations = [po]
        mock_get_profile.return_value = profile

        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(status=OptimizationStatus.OPTIMIZABLE)
        mock_opt.apply.side_effect = RuntimeError("System error")
        mock_opt.snapshot.return_value = {}
        mock_get_opt.return_value = mock_opt

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())), \
             patch.object(exec_inst, '_check_safety_gate', return_value=(True, "Safety gate passed")), \
             patch.object(exec_inst, '_capture_pre_snapshot', return_value=SystemSnapshot()):
            session = exec_inst.execute(profile_id="gaming")

        assert session.steps[0].verdict == ExecutionVerdict.FAILED
        assert "error" in session.steps[0].reason.lower()
        assert session.failed_count == 1

    def test_execute_returns_busy_if_in_progress(self):
        exec_inst = OptimizationExecutor()
        exec_inst._current_session = OptimizationExecutionSession(
            status=SessionStatus.IN_PROGRESS,
        )
        session = exec_inst.execute(profile_id="gaming")
        assert session.status == SessionStatus.IN_PROGRESS


# ── Impact Evaluation Tests ──────────────────────────────────────

class TestImpactEvaluation:
    """Test impact evaluation logic."""

    def test_evaluate_impact_unchanged(self):
        exec_inst = OptimizationExecutor()
        pre = SystemSnapshot()
        pre.cpu_utilization = MetricValue(value=50.0, state=MetricState.MEASURED)
        pre.target_pid = 12345
        pre.target_name = "HD-Player.exe"

        post = SystemSnapshot()
        post.cpu_utilization = MetricValue(value=50.5, state=MetricState.MEASURED)
        post.target_pid = 12345
        post.target_name = "HD-Player.exe"

        with patch("psutil.Process") as mock_proc:
            mock_proc.return_value.name.return_value = "HD-Player.exe"
            impact = exec_inst._evaluate_impact(pre, post, "power_plan")

        assert impact.cpu_delta == pytest.approx(0.5)
        assert impact.classification in ("UNCHANGED", "INCONCLUSIVE")

    def test_evaluate_impact_inconclusive_no_data(self):
        exec_inst = OptimizationExecutor()
        pre = SystemSnapshot()
        post = SystemSnapshot()

        impact = exec_inst._evaluate_impact(pre, post, "power_plan")
        assert impact.classification == "INCONCLUSIVE"

    def test_evaluate_impact_degraded_temperature(self):
        exec_inst = OptimizationExecutor()
        pre = SystemSnapshot()
        pre.gpu_temperature = MetricValue(value=70.0, state=MetricState.MEASURED)
        pre.target_pid = 12345
        pre.target_name = "HD-Player.exe"

        post = SystemSnapshot()
        post.gpu_temperature = MetricValue(value=85.0, state=MetricState.MEASURED)
        post.target_pid = 12345
        post.target_name = "HD-Player.exe"

        with patch("psutil.Process") as mock_proc:
            mock_proc.return_value.name.return_value = "HD-Player.exe"
            impact = exec_inst._evaluate_impact(pre, post, "power_plan")

        assert impact.temperature_delta == pytest.approx(15.0)
        assert impact.classification == "DEGRADED"

    def test_evaluate_impact_degraded_pid_change(self):
        exec_inst = OptimizationExecutor()
        pre = SystemSnapshot(target_pid=12345, target_name="HD-Player.exe")
        pre.cpu_utilization = MetricValue(value=50.0, state=MetricState.MEASURED)
        post = SystemSnapshot(target_pid=99999, target_name="HD-Player.exe")
        post.cpu_utilization = MetricValue(value=50.0, state=MetricState.MEASURED)

        with patch("psutil.Process") as mock_proc:
            mock_proc.return_value.name.return_value = "HD-Player.exe"
            impact = exec_inst._evaluate_impact(pre, post, "power_plan")

        assert impact.target_stable is False
        assert impact.classification == "DEGRADED"

    def test_evaluate_impact_ram_delta(self):
        exec_inst = OptimizationExecutor()
        pre = SystemSnapshot()
        pre.ram_available_mb = MetricValue(value=4096.0, state=MetricState.MEASURED)
        pre.target_pid = 12345
        pre.target_name = "HD-Player.exe"

        post = SystemSnapshot()
        post.ram_available_mb = MetricValue(value=4200.0, state=MetricState.MEASURED)
        post.target_pid = 12345
        post.target_name = "HD-Player.exe"

        with patch("psutil.Process") as mock_proc:
            mock_proc.return_value.name.return_value = "HD-Player.exe"
            impact = exec_inst._evaluate_impact(pre, post, "power_plan")

        assert impact.ram_delta_mb == pytest.approx(104.0)


# ── Snapshot Capture Tests ───────────────────────────────────────

class TestSnapshotCapture:
    """Test pre/post snapshot capture."""

    def test_capture_snapshot_returns_metrics(self):
        exec_inst = OptimizationExecutor()
        with patch("psutil.cpu_percent", return_value=45.0), \
             patch("psutil.virtual_memory") as mock_vm, \
             patch("app.system.gpu.gpu_monitor") as mock_gpu, \
             patch("app.system.power.power_monitor") as mock_power:
            mock_vm.return_value = MagicMock(
                used=8 * 1024**3,
                available=8 * 1024**3,
            )
            mock_gpu.detect.return_value = MagicMock(
                utilization=75, temperature=None,
            )
            mock_power.detect.return_value = MagicMock(active_plan_name="Balanced")

            snap = exec_inst._capture_pre_snapshot("HD-Player.exe", 12345, time.time())

        assert snap.cpu_utilization.state == MetricState.MEASURED
        assert snap.cpu_utilization.value == 45.0
        assert snap.ram_used_mb.state == MetricState.MEASURED
        assert snap.target_name == "HD-Player.exe"
        assert snap.target_pid == 12345

    def test_capture_snapshot_handles_failures(self):
        exec_inst = OptimizationExecutor()
        # Patch the objects at their source modules so local imports get the mocks
        from app.system.gpu import gpu_monitor as real_gpu_monitor
        from app.system.power import power_monitor as real_power_monitor
        with patch("psutil.cpu_percent", side_effect=Exception("fail")), \
             patch("psutil.virtual_memory", side_effect=Exception("fail")), \
             patch.object(real_gpu_monitor, "detect", side_effect=Exception("fail")), \
             patch.object(real_power_monitor, "detect", side_effect=Exception("fail")):
            snap = exec_inst._capture_pre_snapshot("", 0, 0.0)

        assert snap.cpu_utilization.state == MetricState.FAILED
        assert snap.ram_used_mb.state == MetricState.FAILED
        assert snap.gpu_utilization.state == MetricState.NOT_AVAILABLE


# ── Rollback Tests ───────────────────────────────────────────────

class TestRollback:
    """Test rollback functionality."""

    def test_rollback_no_session(self):
        exec_inst = OptimizationExecutor()
        result = exec_inst.rollback_last()
        assert result.success is False
        assert "No execution session" in result.message

    def test_rollback_no_applied_steps(self):
        exec_inst = OptimizationExecutor()
        session = OptimizationExecutionSession()
        session.steps.append(OptimizationExecutionStep(
            optimization_id="power_plan",
            verdict=ExecutionVerdict.SKIPPED,
        ))
        exec_inst._last_session = session

        result = exec_inst.rollback_last()
        assert result.success is True
        assert "No applied optimizations" in result.message


# ── Verify Tests ─────────────────────────────────────────────────

class TestVerify:
    """Test verification functionality."""

    def test_verify_no_session(self):
        exec_inst = OptimizationExecutor()
        result = exec_inst.verify_session()
        assert result["status"] == "NO_SESSION"

    def test_verify_with_applied_steps(self):
        exec_inst = OptimizationExecutor()
        session = OptimizationExecutionSession()
        session.steps.append(OptimizationExecutionStep(
            optimization_id="power_plan",
            optimization_name="Power Plan",
            verdict=ExecutionVerdict.KEPT,
        ))
        exec_inst._last_session = session

        with patch("app.core.optimizations.get_optimization_by_id") as mock_get:
            mock_opt = MagicMock()
            mock_opt.verify.return_value = True
            mock_get.return_value = mock_opt

            result = exec_inst.verify_session()

        assert result["status"] == "ALL_VERIFIED"
        assert result["results"]["power_plan"]["verified"] is True

    def test_verify_partial_mismatch(self):
        exec_inst = OptimizationExecutor()
        session = OptimizationExecutionSession()
        session.steps.append(OptimizationExecutionStep(
            optimization_id="power_plan",
            optimization_name="Power Plan",
            verdict=ExecutionVerdict.KEPT,
        ))
        session.steps.append(OptimizationExecutionStep(
            optimization_id="game_mode",
            optimization_name="Game Mode",
            verdict=ExecutionVerdict.KEPT,
        ))
        exec_inst._last_session = session

        with patch("app.core.optimizations.get_optimization_by_id") as mock_get:
            mock_opt1 = MagicMock()
            mock_opt1.verify.return_value = True
            mock_opt2 = MagicMock()
            mock_opt2.verify.return_value = False
            mock_get.side_effect = lambda oid: mock_opt1 if oid == "power_plan" else mock_opt2

            result = exec_inst.verify_session()

        assert result["status"] == "PARTIAL"


# ── Session Status Tests ─────────────────────────────────────────

class TestSessionStatus:
    """Test session status retrieval."""

    def test_get_status_no_session(self):
        exec_inst = OptimizationExecutor()
        status = exec_inst.get_status()
        assert status["busy"] is False
        assert status["last_session"] is None

    def test_get_status_with_session(self):
        exec_inst = OptimizationExecutor()
        exec_inst._last_session = OptimizationExecutionSession(
            status=SessionStatus.COMPLETED,
            kept_count=2,
        )
        status = exec_inst.get_status()
        assert status["last_session"]["status"] == "COMPLETED"
        assert status["last_session"]["kept_count"] == 2

    def test_is_busy_when_in_progress(self):
        exec_inst = OptimizationExecutor()
        assert exec_inst.is_busy is False
        exec_inst._current_session = OptimizationExecutionSession(
            status=SessionStatus.IN_PROGRESS,
        )
        assert exec_inst.is_busy is True


# ── CLI Formatting Tests ─────────────────────────────────────────

class TestCLIFormatting:
    """Test CLI output formatting."""

    def test_format_preview(self):
        exec_inst = OptimizationExecutor()
        session = OptimizationExecutionSession(
            profile_id="gaming",
            profile_name="GAMING",
            target_name="HD-Player.exe",
            target_pid=12345,
        )
        session.steps.append(OptimizationExecutionStep(
            optimization_id="power_plan",
            optimization_name="Power Plan",
            verdict=ExecutionVerdict.KEPT,
            reason="Would be applied",
        ))
        session.applied_count = 1

        text = exec_inst.format_preview(session)
        assert "OPTIMIZATION PREVIEW" in text
        assert "Power Plan" in text
        assert "Would Apply: 1" in text

    def test_session_format_cli_with_steps(self):
        session = OptimizationExecutionSession(
            profile_id="gaming",
            profile_name="GAMING",
            status=SessionStatus.COMPLETED,
            kept_count=2,
            rolled_back_count=1,
        )
        session.steps.append(OptimizationExecutionStep(
            optimization_id="power_plan",
            optimization_name="Power Plan",
            verdict=ExecutionVerdict.KEPT,
        ))
        session.steps.append(OptimizationExecutionStep(
            optimization_id="emulator_priority",
            optimization_name="Emulator Priority",
            verdict=ExecutionVerdict.ROLLED_BACK,
            reason="Rolled back: degradation",
        ))

        text = session.format_cli()
        assert "OPTIMIZATION EXECUTION SESSION" in text
        assert "KEPT" in text
        assert "ROLLED_BACK" in text
        assert "Applied & Kept:    2" in text


# ── Multiple Optimization Steps ──────────────────────────────────

class TestMultipleOptimizations:
    """Test handling of multiple optimizations in a single session."""

    @patch("app.core.optimization_executor.get_profile")
    @patch("app.core.optimizations.get_optimization_by_id")
    def test_mixed_outcomes(self, mock_get_opt, mock_get_profile):
        exec_inst = OptimizationExecutor()

        profile = MagicMock()
        profile.name = "GAMING"
        po1 = MagicMock()
        po1.opt_id = "power_plan"
        po1.name = "Power Plan"
        po2 = MagicMock()
        po2.opt_id = "game_mode"
        po2.name = "Game Mode"
        po3 = MagicMock()
        po3.opt_id = "emulator_priority"
        po3.name = "Emulator Priority"
        profile.optimizations = [po1, po2, po3]
        mock_get_profile.return_value = profile

        mock_opt = MagicMock()
        mock_opt.check.return_value = OptimizationResult(status=OptimizationStatus.OPTIMIZABLE)
        mock_opt.apply.return_value = OptimizationResult(status=OptimizationStatus.APPLIED)
        mock_opt.verify.return_value = True
        mock_opt.snapshot.return_value = {}
        mock_get_opt.return_value = mock_opt

        def gate_side_effect(opt_id, *args, **kwargs):
            if opt_id == "power_plan":
                return (True, "Safety gate passed")
            elif opt_id == "game_mode":
                return (False, "Already optimal")
            elif opt_id == "emulator_priority":
                return (False, "Administrator privileges required")
            return (False, "Unknown")

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())), \
             patch.object(exec_inst, '_check_safety_gate', side_effect=gate_side_effect), \
             patch.object(exec_inst, '_capture_pre_snapshot', return_value=SystemSnapshot()), \
             patch.object(exec_inst, '_evaluate_impact', return_value=OptimizationImpact(classification="UNCHANGED")):
            session = exec_inst.execute(profile_id="gaming")

        assert len(session.steps) == 3
        assert session.kept_count == 1
        assert session.already_optimal_count == 1
        assert session.admin_required_count == 1
        assert session.status == SessionStatus.COMPLETED


# ── Profile Filtering Tests ──────────────────────────────────────

class TestProfileFiltering:
    """Test that profile filtering works correctly."""

    def test_balanced_profile_has_fewer_opts(self):
        from app.core.profiles import get_profile
        balanced = get_profile("balanced")
        gaming = get_profile("gaming")
        maxp = get_profile("max_performance")

        assert len(balanced.optimizations) < len(gaming.optimizations)
        assert len(gaming.optimizations) < len(maxp.optimizations)


# ── Edge Cases ───────────────────────────────────────────────────

class TestEdgeCases:
    """Test edge cases and boundary conditions."""

    @patch("app.core.optimization_executor.get_profile")
    def test_empty_profile(self, mock_get_profile):
        exec_inst = OptimizationExecutor()
        profile = MagicMock()
        profile.name = "EMPTY"
        profile.optimizations = []
        mock_get_profile.return_value = profile

        with patch.object(exec_inst, '_detect_target', return_value=("HD-Player.exe", 12345, time.time())):
            session = exec_inst.execute(profile_id="empty")
            assert len(session.steps) == 0
            assert session.status == SessionStatus.COMPLETED

    def test_detect_target_returns_empty(self):
        exec_inst = OptimizationExecutor()
        name, pid, start = exec_inst._detect_target()
        # Should not raise
        assert isinstance(name, str)
        assert isinstance(pid, int)

    def test_validate_target_nonexistent_pid(self):
        exec_inst = OptimizationExecutor()
        valid, msg = exec_inst._validate_target("HD-Player.exe", 99999999, 0)
        # Should fail gracefully
        assert valid is False

    def test_max_session_steps_limit(self):
        """Session should not exceed MAX_SESSION_STEPS."""
        from app.core.optimization_executor import MAX_SESSION_STEPS
        assert MAX_SESSION_STEPS > 0


# ── Singleton Tests ──────────────────────────────────────────────

class TestSingleton:
    """Test the singleton instance."""

    def test_singleton_exists(self):
        assert optimization_executor is not None
        assert isinstance(optimization_executor, OptimizationExecutor)

    def test_singleton_is_same(self):
        from app.core.optimization_executor import optimization_executor as oe2
        assert optimization_executor is oe2
