"""
Tests for Phase 35 — Evidence-Based Optimization Recommendation Engine.

Uses mocks for hardware-dependent tests.
"""

import pytest
import time
from unittest.mock import patch, MagicMock

from app.core.recommendation_engine import (
    RecommendationEngine,
    Recommendation,
    RecommendationPriority,
    RecommendationSession,
    EvidencePoint,
    DataQuality,
    BOTTLENECK_OPTIMIZATION_MAP,
    OPTIMIZATION_META,
    recommendation_engine,
)
from app.performance.telemetry_models import (
    BottleneckType,
    TelemetrySample,
)


# ── Helper ───────────────────────────────────────────────────────

def make_sample(
    cpu=None, gpu=None, ram_used=None, ram_total=None,
    emu_cpu=None, emu_ram=None, fps=None, ft=None,
    gpu_temp=None, emu_pid=1234,
):
    """Create a TelemetrySample with specified values."""
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
    """Create N samples with the same values."""
    return [make_sample(**kwargs) for _ in range(n)]


# ── Model Tests ──────────────────────────────────────────────────

class TestEvidencePoint:
    def test_creation(self):
        ep = EvidencePoint(metric="CPU", measured_value=85.0, threshold=90.0, unit="%")
        assert ep.metric == "CPU"
        assert ep.measured_value == 85.0
        assert ep.unit == "%"

    def test_to_dict(self):
        ep = EvidencePoint(metric="GPU", measured_value=92.5, unit="%")
        d = ep.to_dict()
        assert d["metric"] == "GPU"
        assert d["measured_value"] == 92.5
        assert d["quality"] == "MEASURED"


class TestRecommendation:
    def test_creation(self):
        rec = Recommendation(
            optimization_id="emulator_priority",
            optimization_name="Emulator Priority",
            priority=RecommendationPriority.HIGH,
            confidence=82,
            reason="CPU pressure is high",
        )
        assert rec.optimization_id == "emulator_priority"
        assert rec.confidence == 82

    def test_to_dict(self):
        rec = Recommendation(
            optimization_id="power_plan",
            optimization_name="Power Plan",
            priority=RecommendationPriority.MEDIUM,
            confidence=60,
            reason="Test",
            evidence=[EvidencePoint(metric="CPU", measured_value=80.0)],
        )
        d = rec.to_dict()
        assert d["optimization_id"] == "power_plan"
        assert d["confidence"] == 60
        assert len(d["evidence"]) == 1


class TestRecommendationSession:
    def test_creation(self):
        session = RecommendationSession(target_name="HD-Player.exe", target_pid=1234)
        assert session.target_name == "HD-Player.exe"
        assert session.sample_count == 0

    def test_get_top_recommendations(self):
        session = RecommendationSession()
        session.recommendations = [
            Recommendation(optimization_id="a", confidence=90, priority=RecommendationPriority.HIGH),
            Recommendation(optimization_id="b", confidence=50, priority=RecommendationPriority.MEDIUM),
            Recommendation(optimization_id="c", confidence=100, priority=RecommendationPriority.ALREADY_OPTIMAL),
            Recommendation(optimization_id="d", confidence=30, priority=RecommendationPriority.NOT_AVAILABLE),
        ]
        top = session.get_top_recommendations(2)
        assert len(top) == 2
        # Excludes ALREADY_OPTIMAL and NOT_AVAILABLE
        assert top[0].optimization_id == "a"
        assert top[1].optimization_id == "b"

    def test_to_dict(self):
        session = RecommendationSession(target_name="test")
        d = session.to_dict()
        assert d["target_name"] == "test"
        assert "session_id" in d


# ── Engine Core Tests ────────────────────────────────────────────

class TestRecommendationEngine:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_analyze_empty_samples(self):
        session = self.engine.analyze(
            samples=[],
            bottleneck_type=BottleneckType.INSUFFICIENT_DATA,
        )
        assert session.sample_count == 0
        assert session.telemetry_quality == DataQuality.NOT_AVAILABLE

    def test_analyze_insufficient_data(self):
        samples = make_samples(3, cpu=50, gpu=40, ram_used=8000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.INSUFFICIENT_DATA,
        )
        assert session.telemetry_quality in (DataQuality.MEASURED, DataQuality.INFERRED)

    def test_analyze_with_samples(self):
        samples = make_samples(25, cpu=90, gpu=40, ram_used=14000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            bottleneck_confidence=80,
        )
        assert session.sample_count == 25
        assert session.telemetry_quality == DataQuality.MEASURED
        assert len(session.recommendations) > 0

    def test_last_session_tracking(self):
        samples = make_samples(15, cpu=80, gpu=50, ram_used=10000, ram_total=16000)
        self.engine.analyze(samples=samples)
        assert self.engine.last_session is not None
        assert len(self.engine.history) >= 1

    def test_history_bounded(self):
        samples = make_samples(15, cpu=50, gpu=40, ram_used=8000, ram_total=16000)
        for _ in range(55):
            self.engine.analyze(samples=samples)
        assert len(self.engine.history) <= 50


# ── Bottleneck → Optimization Mapping ────────────────────────────

class TestBottleneckMapping:
    def test_cpu_bound_has_emulator_priority(self):
        opts = BOTTLENECK_OPTIMIZATION_MAP[BottleneckType.CPU_BOUND]
        ids = [o[0] for o in opts]
        assert "emulator_priority" in ids

    def test_memory_bound_has_memory_analysis(self):
        opts = BOTTLENECK_OPTIMIZATION_MAP[BottleneckType.MEMORY_BOUND]
        ids = [o[0] for o in opts]
        assert "memory_analysis" in ids

    def test_no_clear_bottleneck_is_empty(self):
        opts = BOTTLENECK_OPTIMIZATION_MAP[BottleneckType.NO_CLEAR_BOTTLENECK]
        assert len(opts) == 0

    def test_insufficient_data_is_empty(self):
        opts = BOTTLENECK_OPTIMIZATION_MAP[BottleneckType.INSUFFICIENT_DATA]
        assert len(opts) == 0


# ── CPU-bound Recommendations ────────────────────────────────────

class TestCPUBoundRecommendations:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_cpu_bound_recommendations(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            bottleneck_confidence=80,
        )
        rec_ids = [r.optimization_id for r in session.recommendations]
        assert "emulator_priority" in rec_ids

    def test_cpu_bound_high_confidence(self):
        samples = make_samples(35, cpu=95, gpu=30, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            bottleneck_confidence=85,
        )
        ep_rec = next(
            (r for r in session.recommendations if r.optimization_id == "emulator_priority"),
            None,
        )
        assert ep_rec is not None
        assert ep_rec.confidence > 40

    def test_cpu_bound_with_headroom_evidence(self):
        samples = make_samples(25, cpu=90, gpu=30, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            bottleneck_confidence=75,
        )
        ep_rec = next(
            (r for r in session.recommendations if r.optimization_id == "emulator_priority"),
            None,
        )
        assert ep_rec is not None
        # Should have evidence about CPU vs GPU headroom
        ev_metrics = [e.metric for e in ep_rec.evidence]
        assert any("CPU" in m or "GPU" in m for m in ev_metrics)


# ── GPU-bound Recommendations ────────────────────────────────────

class TestGPUBoundRecommendations:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_gpu_bound_recommendations(self):
        samples = make_samples(25, cpu=40, gpu=95, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.GPU_BOUND,
            bottleneck_confidence=80,
        )
        # GPU-bound should not aggressively recommend CPU changes
        rec_ids = [r.optimization_id for r in session.recommendations]
        assert "emulator_priority" not in rec_ids or all(
            r.priority != RecommendationPriority.HIGH
            for r in session.recommendations
            if r.optimization_id == "emulator_priority"
        )


# ── Memory-bound Recommendations ─────────────────────────────────

class TestMemoryBoundRecommendations:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_memory_bound_recommendations(self):
        samples = make_samples(25, cpu=60, gpu=50, ram_used=14500, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.MEMORY_BOUND,
            bottleneck_confidence=75,
        )
        rec_ids = [r.optimization_id for r in session.recommendations]
        assert "memory_analysis" in rec_ids

    def test_memory_pressure_high(self):
        samples = make_samples(25, cpu=50, gpu=40, ram_used=15200, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.MEMORY_BOUND,
            bottleneck_confidence=85,
        )
        mem_rec = next(
            (r for r in session.recommendations if r.optimization_id == "memory_analysis"),
            None,
        )
        assert mem_rec is not None
        assert mem_rec.confidence > 50

    def test_memory_pressure_normal(self):
        samples = make_samples(25, cpu=40, gpu=30, ram_used=6000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.NO_CLEAR_BOTTLENECK,
            bottleneck_confidence=50,
        )
        mem_recs = [r for r in session.recommendations if r.optimization_id == "memory_analysis"]
        # With normal memory, memory_analysis should not appear or should be low priority
        if mem_recs:
            assert mem_recs[0].priority in (
                RecommendationPriority.NOT_AVAILABLE,
                RecommendationPriority.ALREADY_OPTIMAL,
            )


# ── Thermal-bound Recommendations ────────────────────────────────

class TestThermalBoundRecommendations:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_thermal_bound_recommendations(self):
        samples = make_samples(25, cpu=75, gpu=80, gpu_temp=88, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.THERMAL_LIMITED,
            bottleneck_confidence=70,
        )
        assert len(session.recommendations) > 0


# ── No Bottleneck ────────────────────────────────────────────────

class TestNoBottleneck:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_no_bottleneck_few_recommendations(self):
        samples = make_samples(25, cpu=40, gpu=50, ram_used=8000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.NO_CLEAR_BOTTLENECK,
            bottleneck_confidence=60,
        )
        # Should have few or no HIGH priority recommendations
        high_recs = [r for r in session.recommendations if r.priority == RecommendationPriority.HIGH]
        assert len(high_recs) == 0


# ── Insufficient Data ────────────────────────────────────────────

class TestInsufficientData:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_insufficient_data_no_recommendations(self):
        session = self.engine.analyze(
            samples=[],
            bottleneck_type=BottleneckType.INSUFFICIENT_DATA,
        )
        # Should not produce actionable recommendations
        actionable = [r for r in session.recommendations if r.action == "APPLY"]
        assert len(actionable) == 0


# ── Conflict Detection ───────────────────────────────────────────

class TestConflictDetection:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_multi_resource_pressure(self):
        samples = make_samples(25, cpu=95, gpu=95, ram_used=15000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            bottleneck_confidence=60,
        )
        assert session.conflict_detected is True
        assert len(session.conflict_description) > 0

    def test_no_conflict(self):
        samples = make_samples(25, cpu=40, gpu=50, ram_used=8000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.NO_CLEAR_BOTTLENECK,
            bottleneck_confidence=50,
        )
        assert session.conflict_detected is False


# ── Confidence Calculation ───────────────────────────────────────

class TestConfidence:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_high_sample_confidence(self):
        samples = make_samples(35, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            bottleneck_confidence=80,
        )
        for rec in session.recommendations:
            if rec.action == "APPLY":
                assert rec.confidence > 0

    def test_low_sample_confidence(self):
        samples = make_samples(3, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            bottleneck_confidence=80,
        )
        for rec in session.recommendations:
            if rec.action == "APPLY":
                # Low samples → confidence capped at 50
                assert rec.confidence <= 50


# ── Current State Awareness ──────────────────────────────────────

class TestCurrentStateAwareness:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_already_optimal(self):
        samples = make_samples(25, cpu=90, gpu=40, ram_used=10000, ram_total=16000)
        states = {"game_mode": "ALREADY_OPTIMAL"}
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            optimization_states=states,
        )
        gm_rec = next(
            (r for r in session.recommendations if r.optimization_id == "game_mode"),
            None,
        )
        if gm_rec:
            assert gm_rec.priority == RecommendationPriority.ALREADY_OPTIMAL

    def test_requires_admin(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        states = {"emulator_priority": "REQUIRES_ADMIN"}
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            optimization_states=states,
        )
        ep_rec = next(
            (r for r in session.recommendations if r.optimization_id == "emulator_priority"),
            None,
        )
        if ep_rec:
            assert ep_rec.priority == RecommendationPriority.REQUIRES_ADMIN

    def test_recommendation_only(self):
        samples = make_samples(25, cpu=60, gpu=50, ram_used=14000, ram_total=16000)
        states = {"background_load": "RECOMMENDATION_ONLY"}
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.MEMORY_BOUND,
            optimization_states=states,
        )
        bg_rec = next(
            (r for r in session.recommendations if r.optimization_id == "background_load"),
            None,
        )
        if bg_rec:
            assert bg_rec.priority == RecommendationPriority.RECOMMENDATION_ONLY

    def test_not_available(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        states = {"emulator_priority": "NOT_AVAILABLE"}
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            optimization_states=states,
        )
        ep_rec = next(
            (r for r in session.recommendations if r.optimization_id == "emulator_priority"),
            None,
        )
        if ep_rec:
            assert ep_rec.priority == RecommendationPriority.NOT_AVAILABLE


# ── Profile Restrictions ─────────────────────────────────────────

class TestProfileFiltering:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_balanced_profile_limited_recs(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            profile_id="balanced",
        )
        # Balanced only has game_mode
        rec_ids = [r.optimization_id for r in session.recommendations]
        # Should not have emulator_priority since it's not in balanced profile
        assert "emulator_priority" not in rec_ids

    def test_gaming_profile(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            profile_id="gaming",
        )
        rec_ids = [r.optimization_id for r in session.recommendations]
        assert "emulator_priority" in rec_ids

    def test_max_performance_profile(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            profile_id="max_performance",
        )
        rec_ids = [r.optimization_id for r in session.recommendations]
        assert "emulator_priority" in rec_ids
        assert "power_plan" in rec_ids


# ── No Fabricated FPS ────────────────────────────────────────────

class TestNoFabricatedFPS:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_no_fps_predictions(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
        )
        for rec in session.recommendations:
            # No recommendation should mention FPS gains
            assert "fps" not in rec.reason.lower() or "fps" in rec.expected_area.lower()
            assert "+20 fps" not in rec.reason.lower()
            assert "+10 fps" not in rec.reason.lower()


# ── Recommendation Ordering ──────────────────────────────────────

class TestRecommendationOrdering:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_sorted_by_confidence(self):
        samples = make_samples(35, cpu=92, gpu=35, ram_used=14500, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            bottleneck_confidence=80,
        )
        actionable = [
            r for r in session.recommendations
            if r.priority not in (
                RecommendationPriority.ALREADY_OPTIMAL,
                RecommendationPriority.NOT_AVAILABLE,
            )
        ]
        for i in range(len(actionable) - 1):
            assert actionable[i].confidence >= actionable[i + 1].confidence


# ── Serialization ────────────────────────────────────────────────

class TestSerialization:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_session_serializable(self):
        samples = make_samples(20, cpu=80, gpu=50, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(samples=samples)
        d = session.to_dict()
        assert isinstance(d, dict)
        assert "session_id" in d
        assert "recommendations" in d

    def test_recommendation_serializable(self):
        samples = make_samples(20, cpu=80, gpu=50, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(samples=samples)
        for rec in session.recommendations:
            d = rec.to_dict()
            assert isinstance(d, dict)
            assert "optimization_id" in d


# ── Safety: No System Modifications ──────────────────────────────

class TestSafety:
    def setup_method(self):
        self.engine = RecommendationEngine()

    @patch("app.core.recommendation_engine.recommendation_engine.analyze")
    def test_engine_does_not_modify_system(self, mock_analyze):
        """Verify the engine only recommends, never modifies."""
        # The engine is purely analytical
        assert hasattr(self.engine, "analyze")
        assert hasattr(self.engine, "format_session")
        # No methods that modify system state
        assert not hasattr(self.engine, "apply")
        assert not hasattr(self.engine, "set_power_plan")
        assert not hasattr(self.engine, "terminate_process")

    def test_recommendation_actions_are_safe(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(samples=samples)
        for rec in session.recommendations:
            assert rec.action in ("APPLY", "REVIEW", "MONITOR", "NONE")

    def test_optimization_meta_safety(self):
        for opt_id, meta in OPTIMIZATION_META.items():
            assert "safety" in meta
            assert meta["safety"] in ("SAFE", "REQUIRES_ADMIN", "RECOMMENDATION_ONLY")


# ── Historical Context ───────────────────────────────────────────

class TestHistoricalContext:
    def test_historical_evidence_after_multiple_sessions(self):
        engine = RecommendationEngine()
        samples = make_samples(25, cpu=40, gpu=50, ram_used=8000, ram_total=16000)

        # Run multiple sessions where game_mode is already optimal
        for _ in range(3):
            engine.analyze(
                samples=samples,
                optimization_states={"game_mode": "ALREADY_OPTIMAL"},
            )

        # Next session should have historical evidence
        session = engine.analyze(samples=samples)
        gm_rec = next(
            (r for r in session.recommendations if r.optimization_id == "game_mode"),
            None,
        )
        if gm_rec and gm_rec.priority == RecommendationPriority.ALREADY_OPTIMAL:
            assert gm_rec.historical_evidence is not None
            assert "recent" in gm_rec.historical_evidence.lower()


# ── CLI Formatting ───────────────────────────────────────────────

class TestCLIFormatting:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_format_session(self):
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            bottleneck_confidence=80,
            bottleneck_evidence=["CPU averaged 92.1%"],
            target_name="HD-Player.exe",
            target_pid=1234,
        )
        output = self.engine.format_session(session)
        assert "HEAVEN SOCIETY" in output
        assert "HD-Player.exe" in output
        assert "PID: 1234" in output
        assert "CPU_BOUND" in output.replace("_", " ").replace(" ", "") or "CPU" in output

    def test_format_empty_session(self):
        session = RecommendationSession()
        output = self.engine.format_session(session)
        assert "No emulator detected" in output


# ── Evidence Quality ─────────────────────────────────────────────

class TestDataQuality:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_no_samples_quality(self):
        quality = self.engine._assess_data_quality([], 0)
        assert quality == DataQuality.NOT_AVAILABLE

    def test_few_samples_quality(self):
        quality = self.engine._assess_data_quality(make_samples(3), 1.5)
        assert quality in (DataQuality.MEASURED, DataQuality.INFERRED)

    def test_many_samples_quality(self):
        quality = self.engine._assess_data_quality(make_samples(30, cpu=50, ram_used=8000, ram_total=16000), 15.0)
        assert quality == DataQuality.MEASURED


# ── Optimal State Exclusion ──────────────────────────────────────

class TestOptimalExclusion:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_already_optimal_not_applied(self):
        """Already optimal must not be counted as applied."""
        samples = make_samples(25, cpu=92, gpu=35, ram_used=10000, ram_total=16000)
        states = {"game_mode": "ALREADY_OPTIMAL", "power_plan": "ALREADY_OPTIMAL"}
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.CPU_BOUND,
            optimization_states=states,
        )
        for rec in session.recommendations:
            if rec.optimization_id in ("game_mode", "power_plan"):
                assert rec.priority == RecommendationPriority.ALREADY_OPTIMAL
                assert rec.action == "NONE"


# ── Recommended vs Applied Distinction ───────────────────────────

class TestRecommendationVsApplied:
    def setup_method(self):
        self.engine = RecommendationEngine()

    def test_recommendation_only_never_applied(self):
        samples = make_samples(25, cpu=60, gpu=50, ram_used=14000, ram_total=16000)
        states = {"memory_analysis": "RECOMMENDATION_ONLY"}
        session = self.engine.analyze(
            samples=samples,
            bottleneck_type=BottleneckType.MEMORY_BOUND,
            optimization_states=states,
        )
        mem_rec = next(
            (r for r in session.recommendations if r.optimization_id == "memory_analysis"),
            None,
        )
        if mem_rec:
            assert mem_rec.priority == RecommendationPriority.RECOMMENDATION_ONLY
            assert mem_rec.action in ("REVIEW", "NONE")
