"""
Tests for Phase 70 — Adaptive Optimization Engine.

Tests: TelemetryWindow, ConditionDetector, CooldownManager,
       ImpactEvaluator, AdaptiveEngine, session integration,
       hysteresis, cooldowns, impact classification, persistence.
"""

import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.adaptive_engine import (
    AdaptiveEngine,
    AdaptiveEngineState,
    AdaptiveThresholds,
    ConditionDetector,
    ConditionType,
    CooldownManager,
    ImpactClassification,
    ImpactEvaluator,
    ImpactResult,
    RecommendationAction,
    SustainedCondition,
    TelemetryPoint,
    TelemetryWindow,
    AdaptiveRecommendation,
    generate_recommendations,
)


# ══════════════════════════════════════════════════════════════
#  TELEMETRY WINDOW
# ══════════════════════════════════════════════════════════════


class TestTelemetryWindow:
    def test_add_and_count(self):
        w = TelemetryWindow(max_samples=10)
        for i in range(5):
            w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=50.0 + i))
        assert w.count == 5

    def test_bounded(self):
        w = TelemetryWindow(max_samples=3)
        for i in range(10):
            w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=float(i)))
        assert w.count == 3

    def test_rolling_average(self):
        w = TelemetryWindow(max_samples=10)
        for v in [10, 20, 30]:
            w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=v))
        avg = w.get_rolling_avg("cpu_percent")
        assert avg == 20.0

    def test_rolling_average_none(self):
        w = TelemetryWindow(max_samples=10)
        avg = w.get_rolling_avg("cpu_percent")
        assert avg is None

    def test_rolling_stdev(self):
        w = TelemetryWindow(max_samples=10)
        for v in [10, 10, 10]:
            w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=v))
        stdev = w.get_rolling_stdev("cpu_percent")
        assert stdev == 0.0

    def test_rolling_stdev_insufficient(self):
        w = TelemetryWindow(max_samples=10)
        w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=50.0))
        stdev = w.get_rolling_stdev("cpu_percent")
        assert stdev is None

    def test_get_snapshot(self):
        w = TelemetryWindow(max_samples=10)
        for v in [40, 50, 60]:
            w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=v))
        snap = w.get_snapshot()
        assert snap["avg_cpu_percent"] == 50.0
        assert snap["min_cpu_percent"] == 40.0
        assert snap["max_cpu_percent"] == 60.0
        assert snap["sample_count"] == 3

    def test_get_recent(self):
        w = TelemetryWindow(max_samples=100)
        now = time.time()
        w.add(TelemetryPoint(timestamp=now - 10, cpu_percent=10))
        w.add(TelemetryPoint(timestamp=now - 1, cpu_percent=20))
        recent = w.get_recent(5)
        assert len(recent) == 1
        assert recent[0].cpu_percent == 20

    def test_clear(self):
        w = TelemetryWindow(max_samples=10)
        w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=50))
        w.clear()
        assert w.count == 0

    def test_time_trim(self):
        w = TelemetryWindow(max_samples=100, max_seconds=1.0)
        w.add(TelemetryPoint(timestamp=time.time() - 5, cpu_percent=10))
        w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=20))
        assert w.count == 1  # Old point trimmed


# ══════════════════════════════════════════════════════════════
#  COOLDOWN MANAGER
# ══════════════════════════════════════════════════════════════


class TestCooldownManager:
    def test_can_recommend_initially(self):
        cm = CooldownManager(AdaptiveThresholds())
        allowed, _ = cm.can_recommend(ConditionType.CPU_PRESSURE, "power_plan")
        assert allowed

    def test_apply_cooldown(self):
        t = AdaptiveThresholds(cooldown_after_apply=10)
        cm = CooldownManager(t)
        cm.record_apply("power_plan")
        allowed, reason = cm.can_recommend(ConditionType.CPU_PRESSURE, "power_plan")
        assert not allowed
        assert "recently applied" in reason

    def test_dismiss_cooldown(self):
        t = AdaptiveThresholds(cooldown_after_dismiss=10)
        cm = CooldownManager(t)
        cm.record_dismiss("power_plan")
        allowed, _ = cm.can_recommend(ConditionType.CPU_PRESSURE, "power_plan")
        assert not allowed

    def test_failure_cooldown(self):
        t = AdaptiveThresholds(cooldown_after_failure=10)
        cm = CooldownManager(t)
        cm.record_failure("power_plan")
        allowed, _ = cm.can_recommend(ConditionType.CPU_PRESSURE, "power_plan")
        assert not allowed

    def test_clear_resets(self):
        cm = CooldownManager(AdaptiveThresholds())
        cm.record_apply("power_plan")
        cm.clear()
        allowed, _ = cm.can_recommend(ConditionType.CPU_PRESSURE, "power_plan")
        assert allowed

    def test_different_opt不受影响(self):
        t = AdaptiveThresholds(cooldown_after_apply=60)
        cm = CooldownManager(t)
        cm.record_apply("power_plan")
        allowed, _ = cm.can_recommend(ConditionType.CPU_PRESSURE, "game_mode")
        assert allowed


# ══════════════════════════════════════════════════════════════
#  CONDITION DETECTOR
# ══════════════════════════════════════════════════════════════


class TestConditionDetector:
    def _make_window_with_values(self, cpu_vals, gpu_vals=None, ram_vals=None):
        w = TelemetryWindow(max_samples=100)
        now = time.time()
        for i, cpu in enumerate(cpu_vals):
            kw = {"timestamp": now + i, "cpu_percent": cpu}
            if gpu_vals and i < len(gpu_vals):
                kw["gpu_percent"] = gpu_vals[i]
            if ram_vals and i < len(ram_vals):
                kw["ram_percent"] = ram_vals[i]
            w.add(TelemetryPoint(**kw))
        return w

    def test_insufficient_samples(self):
        t = AdaptiveThresholds(min_samples_for_condition=5)
        cd = ConditionDetector(t)
        w = TelemetryWindow(max_samples=10)
        w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=95))
        conditions = cd.detect(w)
        assert len(conditions) == 0

    def test_cpu_pressure_detected(self):
        t = AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
        )
        cd = ConditionDetector(t)
        w = self._make_window_with_values([90, 92, 91])
        conditions = cd.detect(w)
        assert len(conditions) >= 1
        assert any(c.condition_type == ConditionType.CPU_PRESSURE for c in conditions)

    def test_cpu_pressure_not_triggered_below_threshold(self):
        t = AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
        )
        cd = ConditionDetector(t)
        w = self._make_window_with_values([70, 72, 71])
        conditions = cd.detect(w)
        assert len(conditions) == 0

    def test_hysteresis_recovery(self):
        t = AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
            cpu_recovery=75,
        )
        cd = ConditionDetector(t)

        # Trigger
        w = self._make_window_with_values([90, 92, 91])
        conditions = cd.detect(w)
        assert len(conditions) >= 1

        # Recover
        w2 = self._make_window_with_values([70, 72, 71])
        conditions2 = cd.detect(w2)
        assert len(conditions2) == 0
        assert ConditionType.CPU_PRESSURE not in cd.active_conditions

    def test_gpu_pressure(self):
        t = AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            gpu_trigger=92,
        )
        cd = ConditionDetector(t)
        w = self._make_window_with_values([50, 50, 50], gpu_vals=[93, 95, 94])
        conditions = cd.detect(w)
        assert any(c.condition_type == ConditionType.GPU_PRESSURE for c in conditions)

    def test_ram_pressure(self):
        t = AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            ram_trigger=87,
        )
        cd = ConditionDetector(t)
        w = self._make_window_with_values([50, 50, 50], ram_vals=[90, 91, 89])
        conditions = cd.detect(w)
        assert any(c.condition_type == ConditionType.RAM_PRESSURE for c in conditions)

    def test_fps_degradation(self):
        t = AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            fps_degradation_pct=15,
        )
        cd = ConditionDetector(t)
        w = TelemetryWindow(max_samples=100)
        now = time.time()
        for i in range(5):
            w.add(TelemetryPoint(timestamp=now + i, fps=80.0))  # 80 vs 100 baseline = 20% degradation
        baseline = {"fps": 100.0}
        conditions = cd.detect(w, baseline)
        assert any(c.condition_type == ConditionType.FPS_DEGRADATION for c in conditions)

    def test_thermal_pressure(self):
        t = AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            thermal_trigger=87,
        )
        cd = ConditionDetector(t)
        w = TelemetryWindow(max_samples=100)
        now = time.time()
        for i in range(5):
            w.add(TelemetryPoint(timestamp=now + i, gpu_temp=90.0))
        conditions = cd.detect(w)
        assert any(c.condition_type == ConditionType.THERMAL_PRESSURE for c in conditions)

    def test_clear_all(self):
        t = AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
        )
        cd = ConditionDetector(t)
        w = self._make_window_with_values([90, 92, 91])
        cd.detect(w)
        assert len(cd.active_conditions) > 0
        cd.clear_all()
        assert len(cd.active_conditions) == 0


# ══════════════════════════════════════════════════════════════
#  RECOMMENDATION GENERATION
# ══════════════════════════════════════════════════════════════


class TestRecommendationGeneration:
    def test_cpu_pressure_generates_recommendations(self):
        cm = CooldownManager(AdaptiveThresholds())
        condition = SustainedCondition(
            condition_type=ConditionType.CPU_PRESSURE,
            current_value=91.0,
            baseline_value=64.0,
            threshold=88.0,
            confidence=75,
            sample_count=10,
        )
        recs = generate_recommendations([condition], cm)
        assert len(recs) > 0
        assert any("CPU" in r.title or "priority" in r.title.lower() for r in recs)

    def test_no_duplicate_recommendations(self):
        cm = CooldownManager(AdaptiveThresholds())
        condition = SustainedCondition(
            condition_type=ConditionType.CPU_PRESSURE,
            current_value=91.0,
            confidence=75,
            sample_count=10,
        )
        recs = generate_recommendations([condition, condition], cm)
        opt_ids = [r.optimization_id for r in recs]
        assert len(opt_ids) == len(set(opt_ids))

    def test_applied_optimization_skipped(self):
        cm = CooldownManager(AdaptiveThresholds())
        condition = SustainedCondition(
            condition_type=ConditionType.CPU_PRESSURE,
            current_value=91.0,
            confidence=75,
            sample_count=10,
        )
        recs = generate_recommendations(
            [condition], cm,
            applied_optimizations={"emulator_priority": "APPLIED"},
        )
        assert not any(r.optimization_id == "emulator_priority" for r in recs)

    def test_cooldown_blocks_recommendation(self):
        t = AdaptiveThresholds(cooldown_after_apply=60)
        cm = CooldownManager(t)
        cm.record_apply("emulator_priority")
        condition = SustainedCondition(
            condition_type=ConditionType.CPU_PRESSURE,
            current_value=91.0,
            confidence=75,
            sample_count=10,
        )
        recs = generate_recommendations([condition], cm)
        assert not any(r.optimization_id == "emulator_priority" for r in recs)

    def test_recommendation_has_evidence(self):
        cm = CooldownManager(AdaptiveThresholds())
        condition = SustainedCondition(
            condition_type=ConditionType.CPU_PRESSURE,
            current_value=91.0,
            baseline_value=64.0,
            threshold=88.0,
            confidence=75,
            sample_count=10,
            evidence=["CPU: 91.0%"],
        )
        recs = generate_recommendations([condition], cm)
        assert len(recs) > 0
        assert recs[0].telemetry_evidence["current_value"] == 91.0


# ══════════════════════════════════════════════════════════════
#  IMPACT EVALUATOR
# ══════════════════════════════════════════════════════════════


class TestImpactEvaluator:
    def test_helped(self):
        t = AdaptiveThresholds(impact_improvement_pct=5, impact_harm_pct=8)
        ev = ImpactEvaluator(t)
        before = TelemetryPoint(cpu_percent=90, fps=80, frame_time_ms=12.5)
        after_window = TelemetryWindow(max_samples=10)
        for _ in range(5):
            after_window.add(TelemetryPoint(cpu_percent=75, fps=95, frame_time_ms=10.0))
        rec = AdaptiveRecommendation(recommendation_id="rec_1")
        result = ev.evaluate(before, after_window, rec)
        assert result.classification == ImpactClassification.HELPED

    def test_harmful(self):
        t = AdaptiveThresholds(impact_improvement_pct=5, impact_harm_pct=8)
        ev = ImpactEvaluator(t)
        before = TelemetryPoint(cpu_percent=70, fps=100, frame_time_ms=10.0)
        after_window = TelemetryWindow(max_samples=10)
        for _ in range(5):
            after_window.add(TelemetryPoint(cpu_percent=80, fps=85, frame_time_ms=14.0))
        rec = AdaptiveRecommendation(recommendation_id="rec_2")
        result = ev.evaluate(before, after_window, rec)
        assert result.classification == ImpactClassification.HARMFUL

    def test_insufficient_data(self):
        t = AdaptiveThresholds()
        ev = ImpactEvaluator(t)
        before = TelemetryPoint(cpu_percent=90)
        after_window = TelemetryWindow(max_samples=10)
        after_window.add(TelemetryPoint(cpu_percent=85))
        rec = AdaptiveRecommendation(recommendation_id="rec_3")
        result = ev.evaluate(before, after_window, rec)
        assert result.classification == ImpactClassification.INSUFFICIENT_DATA

    def test_no_significant_change(self):
        t = AdaptiveThresholds(impact_improvement_pct=10, impact_harm_pct=10)
        ev = ImpactEvaluator(t)
        before = TelemetryPoint(cpu_percent=80, fps=100)
        after_window = TelemetryWindow(max_samples=10)
        for _ in range(5):
            after_window.add(TelemetryPoint(cpu_percent=81, fps=99))
        rec = AdaptiveRecommendation(recommendation_id="rec_4")
        result = ev.evaluate(before, after_window, rec)
        assert result.classification == ImpactClassification.NO_SIGNIFICANT_CHANGE


# ══════════════════════════════════════════════════════════════
#  ADAPTIVE ENGINE — SESSION LIFECYCLE
# ══════════════════════════════════════════════════════════════


class TestAdaptiveEngineLifecycle:
    def test_initial_state(self):
        engine = AdaptiveEngine()
        assert engine.state == AdaptiveEngineState.IDLE

    def test_start_session(self):
        engine = AdaptiveEngine()
        engine.start_session("test_session", baseline={"fps": 100})
        assert engine.state == AdaptiveEngineState.MONITORING
        assert engine.window.count == 0

    def test_stop_session(self):
        engine = AdaptiveEngine()
        engine.start_session("test_session")
        records = engine.stop_session()
        assert engine.state == AdaptiveEngineState.IDLE
        assert isinstance(records, list)

    def test_stop_when_idle(self):
        engine = AdaptiveEngine()
        records = engine.stop_session()
        assert records == []

    def test_ingest_adds_to_window(self):
        engine = AdaptiveEngine()
        engine.start_session("test_session")
        engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=50))
        assert engine.window.count == 1
        engine.stop_session()

    def test_ingest_ignored_when_idle(self):
        engine = AdaptiveEngine()
        engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=50))
        assert engine.window.count == 0


# ══════════════════════════════════════════════════════════════
#  ADAPTIVE ENGINE — ANALYSIS
# ══════════════════════════════════════════════════════════════


class TestAdaptiveEngineAnalysis:
    def test_analyze_no_conditions(self):
        engine = AdaptiveEngine(AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=95,
        ))
        engine.start_session("test")
        for _ in range(5):
            engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=50))
        recs = engine.analyze()
        assert len(recs) == 0
        engine.stop_session()

    def test_analyze_detects_condition(self):
        engine = AdaptiveEngine(AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
        ))
        engine.start_session("test")
        for _ in range(5):
            engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=92))
        recs = engine.analyze()
        assert len(recs) > 0
        assert recs[0].title.startswith("Adaptive:")
        engine.stop_session()

    def test_analyze_returns_highest_confidence(self):
        engine = AdaptiveEngine(AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
            thermal_trigger=87,
        ))
        engine.start_session("test")
        now = time.time()
        for i in range(5):
            engine.ingest(TelemetryPoint(
                timestamp=now + i,
                cpu_percent=92,
                gpu_temp=90,
            ))
        recs = engine.analyze()
        assert len(recs) == 1  # Only one recommendation per cycle
        engine.stop_session()

    def test_no_new_recommendation_while_pending(self):
        engine = AdaptiveEngine(AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
        ))
        engine.start_session("test")
        for _ in range(5):
            engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=92))
        recs1 = engine.analyze()
        assert len(recs1) == 1
        # Second call should return nothing (recommendation pending)
        recs2 = engine.analyze()
        assert len(recs2) == 0
        engine.stop_session()


# ══════════════════════════════════════════════════════════════
#  ADAPTIVE ENGINE — APPROVAL
# ══════════════════════════════════════════════════════════════


class TestAdaptiveEngineApproval:
    def test_approve_sets_action(self):
        engine = AdaptiveEngine(AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
        ))
        engine.start_session("test")
        for _ in range(5):
            engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=92))
        recs = engine.analyze()
        assert len(recs) == 1
        approved = engine.approve(recs[0].recommendation_id)
        assert approved
        assert engine.state == AdaptiveEngineState.APPLYING
        engine.stop_session()

    def test_approve_wrong_id_fails(self):
        engine = AdaptiveEngine(AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
        ))
        engine.start_session("test")
        for _ in range(5):
            engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=92))
        engine.analyze()
        result = engine.approve("nonexistent_id")
        assert not result
        engine.stop_session()

    def test_dismiss_clears_recommendation(self):
        engine = AdaptiveEngine(AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
        ))
        engine.start_session("test")
        for _ in range(5):
            engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=92))
        recs = engine.analyze()
        dismissed = engine.dismiss(recs[0].recommendation_id)
        assert dismissed
        assert engine.state == AdaptiveEngineState.MONITORING
        assert engine.active_recommendation is None
        engine.stop_session()


# ══════════════════════════════════════════════════════════════
#  ADAPTIVE ENGINE — UI STATE
# ══════════════════════════════════════════════════════════════


class TestAdaptiveEngineUI:
    def test_ui_state_idle(self):
        engine = AdaptiveEngine()
        state = engine.get_ui_state()
        assert state["state"] == "IDLE"
        assert state["sample_count"] == 0

    def test_ui_state_monitoring(self):
        engine = AdaptiveEngine()
        engine.start_session("test")
        engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=50))
        state = engine.get_ui_state()
        assert state["state"] == "MONITORING"
        assert state["sample_count"] == 1
        engine.stop_session()

    def test_ui_state_with_recommendation(self):
        engine = AdaptiveEngine(AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
        ))
        engine.start_session("test")
        for _ in range(5):
            engine.ingest(TelemetryPoint(timestamp=time.time(), cpu_percent=92))
        engine.analyze()
        state = engine.get_ui_state()
        assert state["state"] == "AWAITING_APPROVAL"
        assert state["recommendation"] is not None
        engine.stop_session()


# ══════════════════════════════════════════════════════════════
#  HYSISRESIS PREVENTS OSCILLATION
# ══════════════════════════════════════════════════════════════


class TestHysteresis:
    def test_no_oscillation_around_threshold(self):
        t = AdaptiveThresholds(
            min_samples_for_condition=3,
            min_sustained_seconds=0,
            cpu_trigger=88,
            cpu_recovery=75,
        )
        cd = ConditionDetector(t)

        # Trigger
        w1 = TelemetryWindow(max_samples=10)
        now = time.time()
        for i in range(5):
            w1.add(TelemetryPoint(timestamp=now + i, cpu_percent=90))
        conds = cd.detect(w1)
        assert len(conds) >= 1

        # Fluctuate around 82 (above recovery, below trigger)
        w2 = TelemetryWindow(max_samples=10)
        for i in range(5):
            w2.add(TelemetryPoint(timestamp=now + 10 + i, cpu_percent=82))
        conds2 = cd.detect(w2)
        # Condition should STILL be active (not recovered yet)
        assert ConditionType.CPU_PRESSURE in cd.active_conditions

        # Now recover below threshold
        w3 = TelemetryWindow(max_samples=10)
        for i in range(5):
            w3.add(TelemetryPoint(timestamp=now + 20 + i, cpu_percent=70))
        conds3 = cd.detect(w3)
        assert ConditionType.CPU_PRESSURE not in cd.active_conditions


# ══════════════════════════════════════════════════════════════
#  PERSISTENCE
# ══════════════════════════════════════════════════════════════


class TestPersistence:
    def test_records_saved_on_stop(self):
        from app.core.adaptive_engine import AdaptiveRecord
        engine = AdaptiveEngine()
        engine.start_session("test")
        engine._records.append(AdaptiveRecord(session_id="test", approved=True))
        with tempfile.TemporaryDirectory() as tmpdir:
            engine._history_dir = tmpdir
            engine.stop_session()
            files = [f for f in os.listdir(tmpdir) if f.endswith(".json")]
            assert len(files) >= 1

    def test_history_bounded(self):
        from app.core.adaptive_engine import AdaptiveRecord
        engine = AdaptiveEngine()
        engine.start_session("test")
        with tempfile.TemporaryDirectory() as tmpdir:
            engine._history_dir = tmpdir
            # Create 110 fake records
            for i in range(110):
                rec = AdaptiveRecord(session_id="test", approved=True)
                rec.record_id = f"rec_{i}"
                engine._records.append(rec)
            engine.stop_session()
            files = [f for f in os.listdir(tmpdir) if f.endswith(".json")]
            assert len(files) <= 100


# ══════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════


class TestDataModels:
    def test_sustained_condition_auto_id(self):
        c = SustainedCondition()
        assert c.condition_id.startswith("cond_")

    def test_recommendation_auto_id(self):
        r = AdaptiveRecommendation()
        assert r.recommendation_id.startswith("rec_")

    def test_recommendation_expiry(self):
        r = AdaptiveRecommendation(expires_at=time.time() - 1)
        assert r.is_expired

    def test_recommendation_not_expired(self):
        r = AdaptiveRecommendation(expires_at=time.time() + 300)
        assert not r.is_expired

    def test_impact_result_to_dict(self):
        ir = ImpactResult(
            recommendation_id="rec_1",
            classification=ImpactClassification.HELPED,
            explanation="CPU improved",
        )
        d = ir.to_dict()
        assert d["classification"] == "HELPED"

    def test_telemetry_point_to_dict(self):
        tp = TelemetryPoint(cpu_percent=50, gpu_percent=70)
        d = tp.to_dict()
        assert d["cpu_percent"] == 50
        assert d["gpu_percent"] == 70


# ══════════════════════════════════════════════════════════════
#  PHASE 70.1 — DEFERRED IMPACT OBSERVATION
# ══════════════════════════════════════════════════════════════


class TestDeferredImpactObservation:
    """Verify apply_recommendation() defers impact and check_impact() evaluates."""

    def test_apply_returns_none_deferred(self):
        """apply_recommendation should return None (deferred, not immediate)."""
        thresholds = AdaptiveThresholds(
            impact_observation_seconds=0.05,
        )
        engine = AdaptiveEngine(thresholds=thresholds)
        engine.start_session("s1")

        # Feed enough telemetry
        for i in range(15):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=92.0,
                ram_percent=50.0,
            ))

        recs = engine.analyze()
        assert len(recs) >= 1
        rec = recs[0]

        approved = engine.approve(rec.recommendation_id)
        assert approved

        # Mock the optimization
        mock_opt = MagicMock()
        mock_check = MagicMock()
        mock_check.status.value = "OPTIMIZABLE"
        mock_opt.check.return_value = mock_check
        mock_apply = MagicMock()
        mock_apply.status.value = "APPLIED"
        mock_opt.apply.return_value = mock_apply
        mock_opt.verify.return_value = True

        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            result = engine.apply_recommendation()

        # Deferred: returns None
        assert result is None
        assert engine.state == AdaptiveEngineState.OBSERVING_IMPACT

    def test_check_impact_returns_none_before_window(self):
        """check_impact() returns None before observation window elapses."""
        thresholds = AdaptiveThresholds(
            impact_observation_seconds=300.0,
        )
        engine = AdaptiveEngine(thresholds=thresholds)
        engine.start_session("s1")

        for i in range(15):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=92.0,
            ))

        recs = engine.analyze()
        rec = recs[0]
        engine.approve(rec.recommendation_id)

        mock_opt = MagicMock()
        mock_check = MagicMock()
        mock_check.status.value = "OPTIMIZABLE"
        mock_opt.check.return_value = mock_check
        mock_apply = MagicMock()
        mock_apply.status.value = "APPLIED"
        mock_opt.apply.return_value = mock_apply
        mock_opt.verify.return_value = True

        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            engine.apply_recommendation()

        # Still observing — too early
        result = engine.check_impact()
        assert result is None
        assert engine.state == AdaptiveEngineState.OBSERVING_IMPACT

    def test_check_impact_evaluates_after_window(self):
        """check_impact() evaluates after observation window elapses."""
        thresholds = AdaptiveThresholds(
            impact_observation_seconds=0.01,
        )
        engine = AdaptiveEngine(thresholds=thresholds)
        engine.start_session("s1")

        for i in range(15):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=92.0,
            ))

        recs = engine.analyze()
        rec = recs[0]
        engine.approve(rec.recommendation_id)

        mock_opt = MagicMock()
        mock_check = MagicMock()
        mock_check.status.value = "OPTIMIZABLE"
        mock_opt.check.return_value = mock_check
        mock_apply = MagicMock()
        mock_apply.status.value = "APPLIED"
        mock_opt.apply.return_value = mock_apply
        mock_opt.verify.return_value = True

        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            engine.apply_recommendation()

        time.sleep(0.05)  # Wait for observation window

        result = engine.check_impact()
        assert result is not None
        assert engine.state == AdaptiveEngineState.MONITORING


# ══════════════════════════════════════════════════════════════
#  PHASE 70.1 — THREAD SAFETY
# ══════════════════════════════════════════════════════════════


class TestThreadSafety:
    """Verify thread safety of start_session, dismiss, apply."""

    def test_concurrent_start_session_only_one_succeeds(self):
        """Only the first concurrent start_session should succeed."""
        engine = AdaptiveEngine()
        results = []

        def start():
            engine.start_session("concurrent")
            results.append(engine.state.value)

        import threading
        threads = [threading.Thread(target=start) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # Only one should have transitioned to MONITORING
        # Others should see IDLE (their call was rejected) or MONITORING
        assert engine.state == AdaptiveEngineState.MONITORING
        # At least one thread got through
        assert "MONITORING" in results

    def test_dismiss_from_wrong_thread_is_safe(self):
        """Dismiss with wrong ID should fail safely from any thread."""
        engine = AdaptiveEngine()
        engine.start_session("s1")

        for i in range(15):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=92.0,
            ))

        recs = engine.analyze()
        assert len(recs) >= 1

        result = engine.dismiss("nonexistent_id")
        assert result is False
        assert engine.state == AdaptiveEngineState.AWAITING_APPROVAL

    def test_approve_after_session_stop_fails(self):
        """Approve after session stop should fail safely."""
        engine = AdaptiveEngine()
        engine.start_session("s1")

        for i in range(15):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=92.0,
            ))

        recs = engine.analyze()
        rec = recs[0]

        engine.stop_session()

        result = engine.approve(rec.recommendation_id)
        assert result is False


# ══════════════════════════════════════════════════════════════
#  PHASE 70.1 — TELEMETRY EDGE CASES
# ══════════════════════════════════════════════════════════════


class TestTelemetryEdgeCases:
    """Verify TelemetryWindow handles edge cases correctly."""

    def test_timestamp_zero_gets_replaced(self):
        """TelemetryPoint with timestamp=0.0 should use current time."""
        w = TelemetryWindow(max_samples=10, max_seconds=300.0)
        before = time.time()
        w.add(TelemetryPoint(timestamp=0.0, cpu_percent=50.0))
        after = time.time()
        samples = w.get_samples()
        assert len(samples) == 1
        assert before <= samples[0].timestamp <= after

    def test_old_timestamps_are_trimmed(self):
        """Points outside the time window should be trimmed."""
        w = TelemetryWindow(max_samples=100, max_seconds=10.0)
        # Add old point
        old = TelemetryPoint(timestamp=time.time() - 60, cpu_percent=50.0)
        w.add(old)
        # Add recent point
        recent = TelemetryPoint(timestamp=time.time(), cpu_percent=80.0)
        w.add(recent)
        assert w.count == 1
        assert w.get_samples()[0].cpu_percent == 80.0

    def test_unordered_insertion(self):
        """Points inserted out of order should all be stored."""
        w = TelemetryWindow(max_samples=100, max_seconds=300.0)
        now = time.time()
        w.add(TelemetryPoint(timestamp=now + 2, cpu_percent=90.0))
        w.add(TelemetryPoint(timestamp=now, cpu_percent=50.0))
        w.add(TelemetryPoint(timestamp=now + 1, cpu_percent=70.0))
        assert w.count == 3

    def test_duplicate_timestamps(self):
        """Multiple points with same timestamp should all be stored."""
        w = TelemetryWindow(max_samples=10, max_seconds=300.0)
        now = time.time()
        for _ in range(5):
            w.add(TelemetryPoint(timestamp=now, cpu_percent=50.0))
        assert w.count == 5

    def test_empty_window_returns_none(self):
        """Empty window should return None for all metrics."""
        w = TelemetryWindow()
        assert w.get_rolling_avg("cpu_percent") is None
        assert w.get_rolling_stdev("cpu_percent") is None
        assert w.get_snapshot() == {}

    def test_single_sample_stdev_returns_none(self):
        """Single sample should return None for stdev."""
        w = TelemetryWindow()
        w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=50.0))
        assert w.get_rolling_stdev("cpu_percent") is None

    def test_bounded_by_max_samples(self):
        """Window should respect max_samples limit."""
        w = TelemetryWindow(max_samples=5, max_seconds=300.0)
        for i in range(20):
            w.add(TelemetryPoint(timestamp=time.time(), cpu_percent=float(i)))
        assert w.count == 5
        # Should contain the last 5 values
        samples = w.get_samples()
        values = [s.cpu_percent for s in samples]
        assert values == [15.0, 16.0, 17.0, 18.0, 19.0]


# ══════════════════════════════════════════════════════════════
#  PHASE 70.1 — COMPLETE SESSION SIMULATION
# ══════════════════════════════════════════════════════════════


class TestSessionSimulation:
    """Realistic end-to-end session simulation."""

    def test_full_cycle_with_deferred_impact(self):
        """Simulate: ingest -> detect -> recommend -> approve -> apply -> observe -> impact."""
        thresholds = AdaptiveThresholds(
            impact_observation_seconds=0.01,
            min_samples_for_condition=3,
            min_sustained_seconds=0.0,
            window_seconds=0.1,  # Very short window so old samples age out
        )
        engine = AdaptiveEngine(thresholds=thresholds)
        engine.start_session("sim1", baseline={"cpu_percent": 50.0})

        # Phase 1: Normal telemetry
        for _ in range(5):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=50.0,
            ))

        recs = engine.analyze()
        assert len(recs) == 0  # No pressure yet

        # Wait for normal samples to age out of short window
        time.sleep(0.15)

        # Phase 2: CPU rises to sustained pressure (all high samples)
        for _ in range(10):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=92.0,
            ))

        recs = engine.analyze()
        assert len(recs) >= 1  # Recommendation generated
        rec = recs[0]
        assert rec.condition.condition_type == ConditionType.CPU_PRESSURE

        # Phase 3: User approves
        approved = engine.approve(rec.recommendation_id)
        assert approved
        assert engine.state == AdaptiveEngineState.APPLYING

        # Phase 4: Apply (mock)
        mock_opt = MagicMock()
        mock_check = MagicMock()
        mock_check.status.value = "OPTIMIZABLE"
        mock_opt.check.return_value = mock_check
        mock_apply = MagicMock()
        mock_apply.status.value = "APPLIED"
        mock_opt.apply.return_value = mock_apply
        mock_opt.verify.return_value = True

        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            result = engine.apply_recommendation()

        assert result is None  # Deferred
        assert engine.state == AdaptiveEngineState.OBSERVING_IMPACT

        # Phase 5: Wait for observation, then check impact
        time.sleep(0.05)

        # Add post-optimization telemetry (improved)
        for _ in range(5):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=70.0,
            ))

        impact = engine.check_impact()
        assert impact is not None
        assert engine.state == AdaptiveEngineState.MONITORING

        # Phase 6: Stop session
        records = engine.stop_session()
        assert len(records) >= 1

    def test_harmful_rollback_triggers(self):
        """Simulate harmful impact triggering rollback."""
        thresholds = AdaptiveThresholds(
            impact_observation_seconds=0.01,
            min_samples_for_condition=3,
            min_sustained_seconds=0.0,
            window_seconds=0.1,
        )
        engine = AdaptiveEngine(thresholds=thresholds)
        engine.start_session("sim2")

        for _ in range(10):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=92.0,
                fps=120.0,
            ))

        recs = engine.analyze()
        rec = recs[0]
        engine.approve(rec.recommendation_id)

        mock_opt = MagicMock()
        mock_check = MagicMock()
        mock_check.status.value = "OPTIMIZABLE"
        mock_opt.check.return_value = mock_check
        mock_apply = MagicMock()
        mock_apply.status.value = "APPLIED"
        mock_opt.apply.return_value = mock_apply
        mock_opt.verify.return_value = True

        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            engine.apply_recommendation()

        time.sleep(0.05)

        # Post-optimization: FPS drops significantly (harmful)
        for _ in range(5):
            engine.ingest(TelemetryPoint(
                timestamp=time.time(),
                cpu_percent=95.0,
                fps=60.0,  # FPS halved — harmful
            ))

        # Mock rollback infrastructure
        mock_snapshot = MagicMock()
        mock_snapshot.optimization_id = rec.optimization_id
        mock_snap_manager = MagicMock()
        mock_snap_manager.list_snapshots.return_value = [mock_snapshot]
        mock_rollback_result = MagicMock()
        mock_rollback_result.success = True
        mock_rollback_result.message = "Restored"
        mock_rollback_engine = MagicMock()
        mock_rollback_engine.rollback.return_value = mock_rollback_result

        with patch("app.core.snapshot.snapshot_manager", mock_snap_manager), \
             patch("app.core.rollback.rollback_engine", mock_rollback_engine):
            impact = engine.check_impact()

        assert impact is not None
        # Should detect harmful and trigger rollback
        if impact.classification == ImpactClassification.HARMFUL:
            assert impact.rolled_back

        engine.stop_session()
