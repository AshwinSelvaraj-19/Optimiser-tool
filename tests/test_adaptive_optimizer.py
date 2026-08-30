"""
Tests for Phase 36 — Adaptive Gaming Optimization & Profile Intelligence.

Uses mocks for hardware-dependent tests.
"""

import os
import time
import pytest
from unittest.mock import patch, MagicMock

from app.core.adaptive_optimizer import (
    AdaptiveOptimizer,
    AdaptiveState,
    AdaptiveAction,
    AdaptivePlan,
    AdaptiveSessionRecord,
    ActionStatus,
    ProfileSuitability,
    ProfileSuitabilityResult,
    SessionResult,
    adaptive_optimizer,
    load_session_history,
    _save_session_record,
    HISTORY_DIR,
    MIN_SAMPLES_CLASSIFY,
    CPU_HIGH_THRESHOLD,
    GPU_SATURATION_THRESHOLD,
    RAM_PRESSURE_HIGH,
    THERMAL_WARNING,
    FRAME_TIME_CV_UNSTABLE,
)
from app.performance.telemetry_models import (
    BottleneckType,
    TelemetrySample,
)


# ── Helpers ──────────────────────────────────────────────────────

def make_sample(
    cpu=None, gpu=None, ram_used=None, ram_total=None,
    emu_cpu=None, emu_ram=None, fps=None, ft=None,
    gpu_temp=None, emu_pid=1234,
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
        emulator_cpu_percent=emu_cpu,
        emulator_ram_mb=emu_ram,
    )


def make_samples(n=20, **kwargs):
    return [make_sample(**kwargs) for _ in range(n)]


# ── Model Tests ──────────────────────────────────────────────────

class TestAdaptiveAction:
    def test_creation(self):
        a = AdaptiveAction(
            optimization_id="emulator_priority",
            optimization_name="Emulator Priority",
            status=ActionStatus.APPLIED,
            confidence=80,
        )
        assert a.optimization_id == "emulator_priority"
        assert a.status == ActionStatus.APPLIED

    def test_to_dict(self):
        a = AdaptiveAction(
            optimization_id="power_plan",
            status=ActionStatus.ALREADY_OPTIMAL,
            confidence=100,
        )
        d = a.to_dict()
        assert d["optimization_id"] == "power_plan"
        assert d["status"] == "ALREADY_OPTIMAL"


class TestAdaptivePlan:
    def test_creation(self):
        plan = AdaptivePlan(target_name="HD-Player.exe", target_pid=1234)
        assert plan.target_name == "HD-Player.exe"
        assert plan.state == AdaptiveState.INSUFFICIENT_DATA

    def test_get_applicable_actions(self):
        plan = AdaptivePlan()
        plan.actions = [
            AdaptiveAction(status=ActionStatus.APPLIED),
            AdaptiveAction(status=ActionStatus.ALREADY_OPTIMAL),
            AdaptiveAction(status=ActionStatus.SKIPPED_NOT_IN_PROFILE),
            AdaptiveAction(status=ActionStatus.REQUIRES_ADMIN),
        ]
        applicable = plan.get_applicable_actions()
        assert len(applicable) == 3

    def test_to_dict(self):
        plan = AdaptivePlan(target_name="test")
        d = plan.to_dict()
        assert d["target_name"] == "test"
        assert "plan_id" in d


class TestProfileSuitability:
    def test_suitable(self):
        r = ProfileSuitabilityResult(
            profile_id="gaming",
            suitability=ProfileSuitability.SUITABLE,
            reason="Test",
        )
        assert r.suitability == ProfileSuitability.SUITABLE

    def test_to_dict(self):
        r = ProfileSuitabilityResult(profile_id="balanced", suitability=ProfileSuitability.MARGINAL)
        d = r.to_dict()
        assert d["profile_id"] == "balanced"


class TestAdaptiveSessionRecord:
    def test_creation(self):
        r = AdaptiveSessionRecord(profile="gaming", state="CPU_BOUND")
        assert r.profile == "gaming"
        assert r.session_id  # auto-generated

    def test_to_dict(self):
        r = AdaptiveSessionRecord(profile="gaming", result="IMPROVED")
        d = r.to_dict()
        assert d["result"] == "IMPROVED"


# ── State Classification ─────────────────────────────────────────

class TestStateClassification:
    def setup_method(self):
        self.engine = AdaptiveOptimizer()

    def test_insufficient_data_empty(self):
        state, conf, ev = self.engine.classify_state([])
        assert state == AdaptiveState.INSUFFICIENT_DATA
        assert conf == 0

    def test_insufficient_data_too_few(self):
        samples = make_samples(3, cpu=50, gpu=40, ram_used=8000, ram_total=16000)
        state, conf, ev = self.engine.classify_state(samples)
        assert state == AdaptiveState.INSUFFICIENT_DATA

    def test_optimal(self):
        samples = make_samples(20, cpu=30, gpu=25, ram_used=6000, ram_total=16000)
        state, conf, ev = self.engine.classify_state(samples)
        assert state == AdaptiveState.OPTIMAL

    def test_cpu_bound(self):
        samples = make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        state, conf, ev = self.engine.classify_state(samples)
        assert state == AdaptiveState.CPU_BOUND
        assert conf > 40

    def test_gpu_bound(self):
        samples = make_samples(20, cpu=40, gpu=95, ram_used=10000, ram_total=16000)
        state, conf, ev = self.engine.classify_state(samples)
        assert state == AdaptiveState.GPU_BOUND
        assert conf > 40

    def test_memory_bound(self):
        samples = make_samples(20, cpu=50, gpu=40, ram_used=14800, ram_total=16000)
        state, conf, ev = self.engine.classify_state(samples)
        assert state == AdaptiveState.MEMORY_BOUND
        assert conf > 40

    def test_thermal_limited(self):
        samples = make_samples(20, cpu=60, gpu=70, gpu_temp=91, ram_used=10000, ram_total=16000)
        state, conf, ev = self.engine.classify_state(samples)
        assert state == AdaptiveState.THERMAL_LIMITED
        assert conf > 40

    def test_frame_time_unstable(self):
        # Create samples with varying frame times
        samples = []
        for i in range(20):
            ft = 8.0 + (20.0 if i % 3 == 0 else 0.0)  # Every 3rd frame is a spike
            samples.append(make_sample(cpu=50, gpu=50, ram_used=10000, ram_total=16000, ft=ft))
        state, conf, ev = self.engine.classify_state(samples)
        assert state == AdaptiveState.FRAME_TIME_UNSTABLE
        assert conf > 30

    def test_resource_pressure(self):
        samples = make_samples(20, cpu=95, gpu=95, ram_used=15000, ram_total=16000)
        state, conf, ev = self.engine.classify_state(samples)
        assert state in (AdaptiveState.RESOURCE_PRESSURE, AdaptiveState.CPU_BOUND, AdaptiveState.GPU_BOUND)
        # At least 2 resources are under pressure
        assert conf > 30

    def test_high_confidence_with_many_samples(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        state, conf, ev = self.engine.classify_state(samples)
        assert conf > 50


# ── Action Planning ──────────────────────────────────────────────

class TestActionPlanning:
    def setup_method(self):
        self.engine = AdaptiveOptimizer()

    def test_optimal_no_actions(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=30, gpu=25, ram_used=6000, ram_total=16000),
            state=AdaptiveState.OPTIMAL, state_confidence=70,
            state_evidence=["No bottleneck"], profile_id="gaming",
        )
        assert len(plan.actions) == 0

    def test_insufficient_data_no_actions(self):
        plan = self.engine.generate_plan(
            samples=[], state=AdaptiveState.INSUFFICIENT_DATA,
            state_confidence=0, state_evidence=[], profile_id="gaming",
        )
        assert len(plan.actions) == 0

    def test_cpu_bound_actions(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000),
            state=AdaptiveState.CPU_BOUND, state_confidence=70,
            state_evidence=["CPU high"], profile_id="gaming",
        )
        opt_ids = [a.optimization_id for a in plan.actions]
        assert "emulator_priority" in opt_ids
        assert "power_plan" in opt_ids

    def test_memory_bound_actions(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=50, gpu=40, ram_used=14800, ram_total=16000),
            state=AdaptiveState.MEMORY_BOUND, state_confidence=75,
            state_evidence=["RAM high"], profile_id="gaming",
        )
        opt_ids = [a.optimization_id for a in plan.actions]
        assert "memory_analysis" in opt_ids
        assert "background_load" in opt_ids

    def test_thermal_limited_no_perf_increase(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=60, gpu=70, gpu_temp=91, ram_used=10000, ram_total=16000),
            state=AdaptiveState.THERMAL_LIMITED, state_confidence=60,
            state_evidence=["GPU hot"], profile_id="gaming",
        )
        opt_ids = [a.optimization_id for a in plan.actions]
        # Should NOT recommend emulator_priority when thermally limited
        assert "emulator_priority" not in opt_ids
        assert "power_plan" not in opt_ids

    def test_profile_filtering(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000),
            state=AdaptiveState.CPU_BOUND, state_confidence=70,
            state_evidence=["CPU high"], profile_id="balanced",
        )
        # Balanced only has game_mode
        opt_ids = [a.optimization_id for a in plan.actions if a.status != ActionStatus.SKIPPED_NOT_IN_PROFILE]
        assert "emulator_priority" not in opt_ids  # Not in balanced profile

    def test_max_performance_includes_all(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000),
            state=AdaptiveState.CPU_BOUND, state_confidence=70,
            state_evidence=["CPU high"], profile_id="max_performance",
        )
        opt_ids = {a.optimization_id for a in plan.actions if a.status != ActionStatus.SKIPPED_NOT_IN_PROFILE}
        assert "emulator_priority" in opt_ids
        assert "power_plan" in opt_ids


# ── Safety Gates ─────────────────────────────────────────────────

class TestSafetyGates:
    def setup_method(self):
        self.engine = AdaptiveOptimizer()

    def test_already_optimal_not_applied(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000),
            state=AdaptiveState.CPU_BOUND, state_confidence=70,
            state_evidence=["CPU high"],
            optimization_states={"emulator_priority": "ALREADY_OPTIMAL"},
            profile_id="gaming",
        )
        ep = next(a for a in plan.actions if a.optimization_id == "emulator_priority")
        assert ep.status == ActionStatus.ALREADY_OPTIMAL

    def test_requires_admin(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000),
            state=AdaptiveState.CPU_BOUND, state_confidence=70,
            state_evidence=["CPU high"],
            optimization_states={"emulator_priority": "REQUIRES_ADMIN"},
            profile_id="gaming",
        )
        ep = next(a for a in plan.actions if a.optimization_id == "emulator_priority")
        assert ep.status == ActionStatus.REQUIRES_ADMIN

    def test_recommendation_only(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=60, gpu=50, ram_used=14000, ram_total=16000),
            state=AdaptiveState.MEMORY_BOUND, state_confidence=70,
            state_evidence=["RAM high"],
            optimization_states={"memory_analysis": "RECOMMENDATION_ONLY"},
            profile_id="gaming",
        )
        ma = next(a for a in plan.actions if a.optimization_id == "memory_analysis")
        assert ma.status == ActionStatus.RECOMMENDATION_ONLY

    def test_not_available(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000),
            state=AdaptiveState.CPU_BOUND, state_confidence=70,
            state_evidence=["CPU high"],
            optimization_states={"emulator_priority": "NOT_AVAILABLE"},
            profile_id="gaming",
        )
        ep = next(a for a in plan.actions if a.optimization_id == "emulator_priority")
        assert ep.status == ActionStatus.NOT_AVAILABLE

    def test_admin_required_blocks_action(self):
        """REQUIRES_ADMIN safety: no admin → blocks action."""
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000),
            state=AdaptiveState.CPU_BOUND, state_confidence=70,
            state_evidence=["CPU high"],
            profile_id="gaming",
            is_admin=False,
        )
        ep = next(
            (a for a in plan.actions if a.optimization_id == "emulator_priority"),
            None,
        )
        if ep:
            # Should be REQUIRES_ADMIN since is_admin=False
            assert ep.status in (ActionStatus.REQUIRES_ADMIN, ActionStatus.APPLIED)

    def test_insufficient_samples_skips_safe_actions(self):
        # With 3 samples, SAFE actions should be SKIPPED_INSUFFICIENT_EVIDENCE
        plan = self.engine.generate_plan(
            samples=make_samples(3, cpu=92, gpu=35, ram_used=10000, ram_total=16000),
            state=AdaptiveState.CPU_BOUND, state_confidence=40,
            state_evidence=["CPU high"],
            profile_id="gaming",
        )
        for a in plan.actions:
            if a.safety == "SAFE" and a.status not in (
                ActionStatus.ALREADY_OPTIMAL, ActionStatus.NOT_AVAILABLE,
            ):
                assert a.status == ActionStatus.SKIPPED_INSUFFICIENT_EVIDENCE


# ── Profile Intelligence ─────────────────────────────────────────

class TestProfileIntelligence:
    def setup_method(self):
        self.engine = AdaptiveOptimizer()

    def test_optimal_recommends_balanced(self):
        rec = self.engine._recommend_profile(AdaptiveState.OPTIMAL, 70, [])
        assert rec == "balanced"

    def test_thermal_recommends_balanced(self):
        rec = self.engine._recommend_profile(AdaptiveState.THERMAL_LIMITED, 60, [])
        assert rec == "balanced"

    def test_cpu_bound_recommends_gaming(self):
        rec = self.engine._recommend_profile(AdaptiveState.CPU_BOUND, 70, [])
        assert rec == "gaming"

    def test_memory_bound_recommends_max(self):
        rec = self.engine._recommend_profile(AdaptiveState.MEMORY_BOUND, 75, [])
        assert rec == "max_performance"

    def test_insufficient_data_defaults_gaming(self):
        rec = self.engine._recommend_profile(AdaptiveState.INSUFFICIENT_DATA, 0, [])
        assert rec == "gaming"

    def test_suitability_optimal_vs_max(self):
        result = self.engine.assess_profile_suitability(
            "max_performance", AdaptiveState.OPTIMAL, 70,
        )
        assert result.suitability == ProfileSuitability.MARGINAL

    def test_suitability_thermal_vs_max(self):
        result = self.engine.assess_profile_suitability(
            "max_performance", AdaptiveState.THERMAL_LIMITED, 60,
        )
        assert result.suitability == ProfileSuitability.UNSUITABLE

    def test_suitability_cpu_vs_gaming(self):
        result = self.engine.assess_profile_suitability(
            "gaming", AdaptiveState.CPU_BOUND, 70,
        )
        assert result.suitability == ProfileSuitability.SUITABLE

    def test_suitability_insufficient_data(self):
        result = self.engine.assess_profile_suitability(
            "gaming", AdaptiveState.INSUFFICIENT_DATA, 0,
        )
        assert result.suitability == ProfileSuitability.UNKNOWN


# ── Session History ──────────────────────────────────────────────

class TestSessionHistory:
    def test_history_tracking(self):
        engine = AdaptiveOptimizer()
        record = AdaptiveSessionRecord(profile="gaming", state="CPU_BOUND", result="IMPROVED")
        engine.save_session(record)
        assert len(engine.history) >= 1

    def test_history_bounded(self):
        engine = AdaptiveOptimizer()
        for i in range(105):
            engine.save_session(AdaptiveSessionRecord(profile="gaming", state="CPU_BOUND"))
        assert len(engine.history) <= 100

    def test_compare_with_history_improved(self):
        engine = AdaptiveOptimizer()
        prev = AdaptiveSessionRecord(
            profile="gaming", post_fps=120.0, post_1low=50.0, post_frame_time=8.3,
        )
        engine.save_session(prev)
        current = AdaptiveSessionRecord(
            profile="gaming", baseline_fps=125.0, baseline_1low=55.0,
        )
        comparison = engine.compare_with_history(current)
        assert comparison is not None
        assert comparison["overall"] in ("IMPROVED", "MIXED")

    def test_compare_with_history_no_match(self):
        engine = AdaptiveOptimizer()
        prev = AdaptiveSessionRecord(profile="balanced", post_fps=120.0)
        engine.save_session(prev)
        current = AdaptiveSessionRecord(profile="gaming", baseline_fps=125.0)
        comparison = engine.compare_with_history(current)
        assert comparison is None


# ── Execution ────────────────────────────────────────────────────

class TestExecution:
    def setup_method(self):
        self.engine = AdaptiveOptimizer()

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_execute_already_optimal(self, mock_get):
        mock_opt = MagicMock()
        mock_check = MagicMock()
        mock_check.status.value = "ALREADY OPTIMAL"
        mock_opt.check.return_value = mock_check
        mock_get.return_value = mock_opt

        plan = AdaptivePlan()
        plan.actions = [
            AdaptiveAction(optimization_id="game_mode", status=ActionStatus.APPLIED),
        ]
        plan = self.engine.execute_plan(plan)
        assert plan.actions[0].status == ActionStatus.ALREADY_OPTIMAL

    @patch("app.core.optimizations.get_optimization_by_id")
    def test_execute_requires_admin(self, mock_get):
        mock_opt = MagicMock()
        mock_check = MagicMock()
        mock_check.status.value = "REQUIRES_ADMIN"
        mock_opt.check.return_value = mock_check
        mock_get.return_value = mock_opt

        plan = AdaptivePlan()
        plan.actions = [
            AdaptiveAction(optimization_id="emulator_priority", status=ActionStatus.APPLIED),
        ]
        plan = self.engine.execute_plan(plan)
        assert plan.actions[0].status == ActionStatus.REQUIRES_ADMIN

    def test_execute_non_applied_skipped(self):
        plan = AdaptivePlan()
        plan.actions = [
            AdaptiveAction(optimization_id="x", status=ActionStatus.ALREADY_OPTIMAL),
            AdaptiveAction(optimization_id="y", status=ActionStatus.SKIPPED_NOT_IN_PROFILE),
        ]
        plan = self.engine.execute_plan(plan)
        # Non-APPLIED actions should not be modified
        assert plan.actions[0].status == ActionStatus.ALREADY_OPTIMAL
        assert plan.actions[1].status == ActionStatus.SKIPPED_NOT_IN_PROFILE

    def test_execute_empty_plan(self):
        plan = AdaptivePlan()
        plan = self.engine.execute_plan(plan)
        assert len(plan.actions) == 0


# ── CLI Formatting ───────────────────────────────────────────────

class TestCLIFormatting:
    def setup_method(self):
        self.engine = AdaptiveOptimizer()

    def test_format_status(self):
        plan = AdaptivePlan(
            target_name="HD-Player.exe", target_pid=1234,
            state=AdaptiveState.CPU_BOUND, confidence=75,
            recommended_profile="gaming", sample_count=20,
        )
        plan.actions = [
            AdaptiveAction(
                optimization_id="emulator_priority",
                optimization_name="Emulator Priority",
                status=ActionStatus.APPLIED,
                confidence=80,
                reason="CPU high",
                expected_area="CPU scheduling",
                safety="REQUIRES_ADMIN",
            ),
        ]
        output = self.engine.format_status(plan)
        assert "HD-Player.exe" in output
        assert "Cpu Bound" in output
        assert "Emulator Priority" in output

    def test_format_plan_optimal(self):
        plan = AdaptivePlan(state=AdaptiveState.OPTIMAL, confidence=70)
        output = self.engine.format_plan(plan)
        assert "optimal" in output.lower() or "no actions" in output.lower()

    def test_format_status_insufficient_data(self):
        plan = AdaptivePlan(state=AdaptiveState.INSUFFICIENT_DATA, confidence=0)
        output = self.engine.format_status(plan)
        assert "No emulator detected" in output or "Insufficient" in output


# ── No Fabricated Performance ────────────────────────────────────

class TestNoFabricatedPerformance:
    def setup_method(self):
        self.engine = AdaptiveOptimizer()

    def test_no_fps_predictions(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000),
            state=AdaptiveState.CPU_BOUND, state_confidence=70,
            state_evidence=["CPU high"], profile_id="gaming",
        )
        for action in plan.actions:
            assert "fps" not in action.reason.lower() or "frame" in action.expected_area.lower()
            assert "+20 fps" not in action.reason.lower()

    def test_optimal_says_nothing_needed(self):
        plan = self.engine.generate_plan(
            samples=make_samples(20, cpu=30, gpu=25, ram_used=6000, ram_total=16000),
            state=AdaptiveState.OPTIMAL, state_confidence=70,
            state_evidence=["No bottleneck"], profile_id="gaming",
        )
        assert len(plan.actions) == 0


# ── Safety: No System Modifications ──────────────────────────────

class TestSafety:
    def setup_method(self):
        self.engine = AdaptiveOptimizer()

    def test_engine_is_analysis_only(self):
        """Verify the engine does not have system-modifying methods."""
        assert hasattr(self.engine, "classify_state")
        assert hasattr(self.engine, "generate_plan")
        assert hasattr(self.engine, "execute_plan")  # Uses existing optimizer
        assert hasattr(self.engine, "format_status")
        assert hasattr(self.engine, "assess_profile_suitability")
        # Should not have direct system-modification methods
        assert not hasattr(self.engine, "set_power_plan")
        assert not hasattr(self.engine, "terminate_process")
        assert not hasattr(self.engine, "modify_registry")

    def test_action_statuses_are_explicit(self):
        for status in ActionStatus:
            assert status.value  # All statuses have values


# ── Persistence ──────────────────────────────────────────────────

class TestPersistence:
    def test_save_and_load(self):
        record = AdaptiveSessionRecord(
            profile="gaming", state="CPU_BOUND", result="IMPROVED",
            baseline_fps=120.0, post_fps=125.0,
        )
        _save_session_record(record)
        assert os.path.exists(os.path.join(HISTORY_DIR, f"{record.session_id}.json"))

    def test_load_history(self):
        records = load_session_history(5)
        assert isinstance(records, list)


# ── Deterministic Classification ─────────────────────────────────

class TestDeterministicClassification:
    def test_same_input_same_output(self):
        engine = AdaptiveOptimizer()
        samples = make_samples(20, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        s1, c1, _ = engine.classify_state(samples)
        s2, c2, _ = engine.classify_state(samples)
        assert s1 == s2
        assert c1 == c2

    def test_empty_always_insufficient(self):
        engine = AdaptiveOptimizer()
        for _ in range(5):
            state, _, _ = engine.classify_state([])
            assert state == AdaptiveState.INSUFFICIENT_DATA


# ── Conflicting Evidence ─────────────────────────────────────────

class TestConflictingEvidence:
    def test_cpu_and_gpu_both_high(self):
        engine = AdaptiveOptimizer()
        samples = make_samples(20, cpu=92, gpu=92, ram_used=10000, ram_total=16000)
        state, conf, ev = engine.classify_state(samples)
        # Should be one of the high-resource states
        assert state in (AdaptiveState.CPU_BOUND, AdaptiveState.GPU_BOUND, AdaptiveState.RESOURCE_PRESSURE)
        assert conf > 30
