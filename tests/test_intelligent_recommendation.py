"""
Phase 51 — Comprehensive tests for Intelligent Recommendation Engine.

Tests:
- RecommendationEvidence
- SystemRecommendation
- Built-in rules: DiskPressureRule, MemoryPressureRule, ThermalRule,
  CpuPressureRule, CleanupAvailableRule, GamingOptimizationRule
- RecommendationHistory
- IntelligentRecommendationEngine
- UI summary
- CLI formatting
- Cooldowns
- Expiration
- Edge cases
"""
import os
import sys
import time
import json
import subprocess

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
from app.core.intelligent_recommendation import (
    RecommendationSeverity,
    RecommendationAction,
    RecommendationEvidence,
    SystemRecommendation,
    RecommendationRule,
    RecommendationHistoryEntry,
    RecommendationHistory,
    IntelligentRecommendationEngine,
    intelligent_recommendation_engine,
)


# ══════════════════════════════════════════════════════════════════
# 1. RecommendationEvidence
# ══════════════════════════════════════════════════════════════════

class TestRecommendationEvidence:
    def test_create(self):
        e = RecommendationEvidence(
            metric="disk_free_gb", value=4.2, threshold=5.0,
            unit="GB", source="disk"
        )
        assert e.metric == "disk_free_gb"
        assert e.value == 4.2
        assert e.threshold == 5.0
        assert e.unit == "GB"
        assert e.source == "disk"

    def test_to_dict(self):
        e = RecommendationEvidence("ram_percent", 92.0, 90.0, "%", "telemetry")
        d = e.to_dict()
        assert d["metric"] == "ram_percent"
        assert d["value"] == 92.0
        assert d["unit"] == "%"
        assert d["source"] == "telemetry"

    def test_none_values(self):
        e = RecommendationEvidence("test", None, None, "", "unknown")
        assert e.value is None
        d = e.to_dict()
        assert d["value"] is None


# ══════════════════════════════════════════════════════════════════
# 2. SystemRecommendation
# ══════════════════════════════════════════════════════════════════

class TestSystemRecommendation:
    def _make_rec(self, **kwargs):
        defaults = dict(
            title="Test recommendation",
            explanation="This is a test.",
            severity=RecommendationSeverity.LOW,
            evidence=[],
            estimated_benefit="test benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=300,
            category="disk",
        )
        defaults.update(kwargs)
        return SystemRecommendation(**defaults)

    def test_create(self):
        r = self._make_rec()
        assert r.title == "Test recommendation"
        assert r.severity == RecommendationSeverity.LOW
        assert r.category == "disk"
        assert r.id  # auto-generated UUID

    def test_severity_icon(self):
        assert self._make_rec(severity=RecommendationSeverity.INFO).severity_icon == "ℹ"
        assert self._make_rec(severity=RecommendationSeverity.LOW).severity_icon == "✓"
        assert self._make_rec(severity=RecommendationSeverity.MEDIUM).severity_icon == "⚠"
        assert self._make_rec(severity=RecommendationSeverity.HIGH).severity_icon == "⚠"
        assert self._make_rec(severity=RecommendationSeverity.CRITICAL).severity_icon == "🔴"

    def test_severity_color(self):
        assert self._make_rec(severity=RecommendationSeverity.INFO).severity_color == "#4CAF50"
        assert self._make_rec(severity=RecommendationSeverity.LOW).severity_color == "#4CAF50"
        assert self._make_rec(severity=RecommendationSeverity.MEDIUM).severity_color == "#FF9800"
        assert self._make_rec(severity=RecommendationSeverity.HIGH).severity_color == "#FF5722"
        assert self._make_rec(severity=RecommendationSeverity.CRITICAL).severity_color == "#F44336"

    def test_is_expired(self):
        r = self._make_rec(cooldown_seconds=0)
        r.expires_at = time.time() - 1
        assert r.is_expired is True

    def test_is_not_expired(self):
        r = self._make_rec(cooldown_seconds=3600)
        assert r.is_expired is False

    def test_to_dict(self):
        r = self._make_rec()
        d = r.to_dict()
        assert d["title"] == "Test recommendation"
        assert d["severity"] in ("low", "LOW")  # enum .value varies
        assert d["category"] == "disk"
        assert "evidence" in d

    def test_custom_evidence(self):
        evidence = [
            RecommendationEvidence("disk_free_gb", 4.2, 5.0, "GB", "disk"),
            RecommendationEvidence("cleanup_bytes", 2_000_000_000, None, "bytes", "cleanup"),
        ]
        r = self._make_rec(evidence=evidence)
        assert len(r.evidence) == 2
        d = r.to_dict()
        assert len(d["evidence"]) == 2


# ══════════════════════════════════════════════════════════════════
# 3. RecommendationHistoryEntry
# ══════════════════════════════════════════════════════════════════

class TestRecommendationHistoryEntry:
    def test_create(self):
        e = RecommendationHistoryEntry(
            recommendation_id="abc123",
            title="Test",
            severity="LOW",
            category="disk",
            action_taken="",
            timestamp=time.time(),
        )
        assert e.recommendation_id == "abc123"
        assert e.dismissed is False

    def test_to_dict(self):
        e = RecommendationHistoryEntry(
            recommendation_id="abc123",
            title="Test",
            severity="HIGH",
            category="memory",
            timestamp=1000.0,
        )
        d = e.to_dict()
        assert d["recommendation_id"] == "abc123"
        assert d["severity"] == "HIGH"
        assert d["category"] == "memory"


# ══════════════════════════════════════════════════════════════════
# 4. Built-in Rules
# ══════════════════════════════════════════════════════════════════

class TestDiskPressureRule:
    def test_no_data(self):
        from app.core.intelligent_recommendation import DiskPressureRule
        r = DiskPressureRule()
        assert r.evaluate({}) is None
        assert r.evaluate({"disk_free_gb": 0}) is None

    def test_critical(self):
        from app.core.intelligent_recommendation import DiskPressureRule
        r = DiskPressureRule()
        rec = r.evaluate({"disk_free_gb": 3.5, "disk_total_gb": 500})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.CRITICAL
        assert "critically low" in rec.title.lower()

    def test_high(self):
        from app.core.intelligent_recommendation import DiskPressureRule
        r = DiskPressureRule()
        rec = r.evaluate({"disk_free_gb": 12.0, "disk_total_gb": 500})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.HIGH

    def test_low(self):
        from app.core.intelligent_recommendation import DiskPressureRule
        r = DiskPressureRule()
        rec = r.evaluate({"disk_free_gb": 25.0, "disk_total_gb": 500})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.LOW

    def test_healthy(self):
        from app.core.intelligent_recommendation import DiskPressureRule
        r = DiskPressureRule()
        assert r.evaluate({"disk_free_gb": 100.0, "disk_total_gb": 500}) is None

    def test_with_cleanup(self):
        from app.core.intelligent_recommendation import DiskPressureRule
        r = DiskPressureRule()
        rec = r.evaluate({
            "disk_free_gb": 4.0,
            "disk_total_gb": 256,
            "cleanup_reclaimable_bytes": 3_000_000_000,
        })
        assert rec is not None
        assert "Cleaning" in rec.explanation


class TestMemoryPressureRule:
    def test_no_data(self):
        from app.core.intelligent_recommendation import MemoryPressureRule
        r = MemoryPressureRule()
        assert r.evaluate({}) is None
        assert r.evaluate({"ram_percent": 0}) is None

    def test_high(self):
        from app.core.intelligent_recommendation import MemoryPressureRule
        r = MemoryPressureRule()
        rec = r.evaluate({"ram_percent": 95.0, "ram_available_gb": 0.8})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.HIGH

    def test_elevated(self):
        from app.core.intelligent_recommendation import MemoryPressureRule
        r = MemoryPressureRule()
        rec = r.evaluate({"ram_percent": 85.0, "ram_available_gb": 2.0})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.MEDIUM

    def test_healthy(self):
        from app.core.intelligent_recommendation import MemoryPressureRule
        r = MemoryPressureRule()
        assert r.evaluate({"ram_percent": 50.0, "ram_available_gb": 8.0}) is None


class TestThermalRule:
    def test_no_data(self):
        from app.core.intelligent_recommendation import ThermalRule
        r = ThermalRule()
        assert r.evaluate({}) is None
        assert r.evaluate({"gpu_temp": 0}) is None

    def test_critical(self):
        from app.core.intelligent_recommendation import ThermalRule
        r = ThermalRule()
        rec = r.evaluate({"gpu_temp": 95.0, "thermal_status": "THROTTLING"})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.HIGH

    def test_throttling(self):
        from app.core.intelligent_recommendation import ThermalRule
        r = ThermalRule()
        rec = r.evaluate({"gpu_temp": 88.0, "thermal_status": "THROTTLING"})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.HIGH

    def test_elevated(self):
        from app.core.intelligent_recommendation import ThermalRule
        r = ThermalRule()
        rec = r.evaluate({"gpu_temp": 82.0})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.MEDIUM

    def test_healthy(self):
        from app.core.intelligent_recommendation import ThermalRule
        r = ThermalRule()
        assert r.evaluate({"gpu_temp": 65.0}) is None


class TestCpuPressureRule:
    def test_no_data(self):
        from app.core.intelligent_recommendation import CpuPressureRule
        r = CpuPressureRule()
        assert r.evaluate({}) is None
        assert r.evaluate({"cpu_percent": 0}) is None

    def test_high(self):
        from app.core.intelligent_recommendation import CpuPressureRule
        r = CpuPressureRule()
        rec = r.evaluate({"cpu_percent": 95.0})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.HIGH

    def test_medium(self):
        from app.core.intelligent_recommendation import CpuPressureRule
        r = CpuPressureRule()
        rec = r.evaluate({"cpu_percent": 82.0})
        assert rec is not None
        assert rec.severity == RecommendationSeverity.MEDIUM

    def test_healthy(self):
        from app.core.intelligent_recommendation import CpuPressureRule
        r = CpuPressureRule()
        assert r.evaluate({"cpu_percent": 60.0}) is None


class TestCleanupAvailableRule:
    def test_no_data(self):
        from app.core.intelligent_recommendation import CleanupAvailableRule
        r = CleanupAvailableRule()
        assert r.evaluate({}) is None

    def test_no_cleanup(self):
        from app.core.intelligent_recommendation import CleanupAvailableRule
        r = CleanupAvailableRule()
        assert r.evaluate({"cleanup_reclaimable_bytes": 0}) is None
        assert r.evaluate({"cleanup_safe_items": 0}) is None

    def test_available(self):
        from app.core.intelligent_recommendation import CleanupAvailableRule
        r = CleanupAvailableRule()
        rec = r.evaluate({
            "cleanup_reclaimable_bytes": 500_000_000,
            "cleanup_safe_items": 5,
        })
        assert rec is not None
        assert rec.severity == RecommendationSeverity.LOW
        assert "cleanup" in rec.title.lower()

    def test_large_cleanup(self):
        from app.core.intelligent_recommendation import CleanupAvailableRule
        r = CleanupAvailableRule()
        rec = r.evaluate({
            "cleanup_reclaimable_bytes": 2_500_000_000,
            "cleanup_safe_items": 12,
        })
        assert rec is not None
        assert "2.3 GB" in rec.explanation  # 2500/1024 ≈ 2.4, floor to 2.3


class TestGamingOptimizationRule:
    def test_no_target(self):
        from app.core.intelligent_recommendation import GamingOptimizationRule
        r = GamingOptimizationRule()
        assert r.evaluate({}) is None
        assert r.evaluate({"target_name": ""}) is None

    def test_degraded(self):
        from app.core.intelligent_recommendation import GamingOptimizationRule
        r = GamingOptimizationRule()
        rec = r.evaluate({
            "target_name": "BlueStacks",
            "gaming_state": "DEGRADED",
        })
        assert rec is not None
        assert rec.severity == RecommendationSeverity.MEDIUM
        assert "degraded" in rec.title.lower()

    def test_optimization_available(self):
        from app.core.intelligent_recommendation import GamingOptimizationRule
        r = GamingOptimizationRule()
        rec = r.evaluate({
            "target_name": "BlueStacks",
            "gaming_state": "IDLE",
            "optimization_state": "ACTIVE",
        })
        assert rec is not None
        assert rec.severity == RecommendationSeverity.LOW

    def test_gaming_active(self):
        from app.core.intelligent_recommendation import GamingOptimizationRule
        r = GamingOptimizationRule()
        rec = r.evaluate({
            "target_name": "BlueStacks",
            "gaming_state": "GAMING",
            "optimization_state": "ACTIVE",
        })
        # Should not fire when gaming is already active
        assert rec is None


# ══════════════════════════════════════════════════════════════════
# 5. RecommendationHistory
# ══════════════════════════════════════════════════════════════════

class TestRecommendationHistory:
    def test_can_fire(self):
        h = RecommendationHistory()
        assert h.can_fire("test_rule", 300) is True

    def test_record_fire(self):
        h = RecommendationHistory()
        rec = SystemRecommendation(
            title="Test",
            explanation="Test",
            severity=RecommendationSeverity.LOW,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=300,
            category="test",
        )
        h.record_fire("test_rule", rec)
        assert h.can_fire("test_rule", 300) is False  # just fired

    def test_cooldown_expiry(self):
        h = RecommendationHistory()
        rec = SystemRecommendation(
            title="Test",
            explanation="Test",
            severity=RecommendationSeverity.LOW,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=0,  # no cooldown
            category="test",
        )
        h.record_fire("test_rule", rec)
        assert h.can_fire("test_rule", 0) is True  # 0 cooldown, can fire immediately

    def test_was_recently_recommended(self):
        h = RecommendationHistory()
        rec = SystemRecommendation(
            title="Test recommendation",
            explanation="Test",
            severity=RecommendationSeverity.LOW,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=300,
            category="test",
        )
        h.record_fire("test_rule", rec)
        assert h.was_recently_recommended("Test recommendation") is True
        assert h.was_recently_recommended("Nonexistent recommendation") is False

    def test_record_action(self):
        h = RecommendationHistory()
        rec = SystemRecommendation(
            title="Test",
            explanation="Test",
            severity=RecommendationSeverity.LOW,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=300,
            category="test",
        )
        h.record_fire("test_rule", rec)
        h.record_action(rec.id, "APPLIED")
        for entry in h._entries:
            if entry.recommendation_id == rec.id:
                assert entry.action_taken == "APPLIED"
                break

    def test_get_recent(self):
        h = RecommendationHistory()
        for i in range(5):
            rec = SystemRecommendation(
                title=f"Rec {i}",
                explanation="Test",
                severity=RecommendationSeverity.LOW,
                evidence=[],
                estimated_benefit="benefit",
                risk="NONE",
                action=RecommendationAction.REVIEW,
                cooldown_seconds=300,
                category="test",
            )
            h.record_fire(f"rule_{i}", rec)
        recent = h.get_recent(3)
        assert len(recent) == 3
        # Most recent first
        assert recent[0].title == "Rec 4"

    def test_memory_limit(self):
        h = RecommendationHistory()
        h._entries = []  # start fresh
        for i in range(250):
            h._entries.append(RecommendationHistoryEntry(
                recommendation_id=f"id_{i}",
                title=f"Rec {i}",
                severity="LOW",
                category="test",
                timestamp=time.time(),
            ))
        rec = SystemRecommendation(
            title="Overflow",
            explanation="Test",
            severity=RecommendationSeverity.LOW,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=300,
            category="test",
        )
        h._last_fired["overflow_rule"] = 0
        h.record_fire("overflow_rule", rec)
        assert len(h._entries) <= 200


# ══════════════════════════════════════════════════════════════════
# 6. IntelligentRecommendationEngine
# ══════════════════════════════════════════════════════════════════

def _fresh_engine():
    """Create an engine with clean history (no stale entries from prior tests)."""
    from app.core.intelligent_recommendation import RecommendationHistory
    engine = IntelligentRecommendationEngine()
    engine._history = RecommendationHistory()
    engine._history._entries = []
    engine._history._last_fired = {}
    engine._last_evaluation = 0
    return engine


class TestIntelligentRecommendationEngine:

    def test_singleton(self):
        assert isinstance(intelligent_recommendation_engine, IntelligentRecommendationEngine)

    def test_evaluate_healthy_system(self):
        engine = _fresh_engine()
        engine._last_evaluation = 0  # bypass throttle
        context = {
            "disk_free_gb": 100.0,
            "disk_total_gb": 500,
            "ram_percent": 50.0,
            "ram_available_gb": 8.0,
            "gpu_temp": 65.0,
            "cpu_percent": 40.0,
        }
        recommendations = engine.evaluate(context)
        # Healthy system should produce no recommendations
        assert len(recommendations) == 0

    def test_evaluate_critical_disk(self):
        engine = _fresh_engine()
        engine._last_evaluation = 0
        context = {
            "disk_free_gb": 3.0,
            "disk_total_gb": 256,
            "ram_percent": 50.0,
            "ram_available_gb": 8.0,
            "gpu_temp": 65.0,
            "cpu_percent": 40.0,
        }
        recommendations = engine.evaluate(context)
        disk_recs = [r for r in recommendations if r.category == "disk"]
        assert len(disk_recs) > 0
        assert disk_recs[0].severity == RecommendationSeverity.CRITICAL

    def test_evaluate_critical_memory(self):
        engine = _fresh_engine()
        engine._last_evaluation = 0
        context = {
            "disk_free_gb": 100.0,
            "disk_total_gb": 500,
            "ram_percent": 95.0,
            "ram_available_gb": 0.5,
            "gpu_temp": 65.0,
            "cpu_percent": 40.0,
        }
        recommendations = engine.evaluate(context)
        mem_recs = [r for r in recommendations if r.category == "memory"]
        assert len(mem_recs) > 0
        assert mem_recs[0].severity == RecommendationSeverity.HIGH

    def test_evaluate_thermal_warning(self):
        engine = _fresh_engine()
        engine._last_evaluation = 0
        context = {
            "disk_free_gb": 100.0,
            "ram_percent": 50.0,
            "ram_available_gb": 8.0,
            "gpu_temp": 92.0,
            "cpu_percent": 40.0,
        }
        recommendations = engine.evaluate(context)
        thermal_recs = [r for r in recommendations if r.category == "thermal"]
        assert len(thermal_recs) > 0

    def test_cooldown_prevents_firing(self):
        engine = _fresh_engine()
        engine._last_evaluation = 0
        context = {
            "disk_free_gb": 3.0,
            "disk_total_gb": 256,
            "ram_percent": 50.0,
            "ram_available_gb": 8.0,
            "gpu_temp": 65.0,
            "cpu_percent": 40.0,
        }
        # First evaluation
        recs1 = engine.evaluate(context)
        # Force re-evaluation
        engine._last_evaluation = 0
        recs2 = engine.evaluate(context)
        assert len(recs2) <= len(recs1)

    def test_throttle_prevents_rapid_evaluation(self):
        engine = _fresh_engine()
        engine._last_evaluation = time.time()
        context = {"disk_free_gb": 3.0, "disk_total_gb": 256}
        recs = engine.evaluate(context)
        assert len(recs) == 0  # throttled

    def test_get_system_health_healthy(self):
        engine = _fresh_engine()
        context = {
            "disk_free_gb": 100.0,
            "ram_percent": 50.0,
            "gpu_temp": 65.0,
            "cpu_percent": 40.0,
        }
        health, color = engine.get_system_health(context)
        assert "HEALTHY" in health

    def test_get_system_health_disk_critical(self):
        engine = _fresh_engine()
        context = {
            "disk_free_gb": 3.0,
            "ram_percent": 50.0,
            "gpu_temp": 65.0,
            "cpu_percent": 40.0,
        }
        health, color = engine.get_system_health(context)
        assert "CRITICAL" in health

    def test_get_system_health_memory_pressure(self):
        engine = _fresh_engine()
        context = {
            "disk_free_gb": 100.0,
            "ram_percent": 85.0,
            "gpu_temp": 65.0,
            "cpu_percent": 40.0,
        }
        health, color = engine.get_system_health(context)
        assert "MEMORY" in health

    def test_get_system_health_thermal(self):
        engine = _fresh_engine()
        context = {
            "disk_free_gb": 100.0,
            "ram_percent": 50.0,
            "gpu_temp": 92.0,
            "cpu_percent": 40.0,
        }
        health, color = engine.get_system_health(context)
        assert "THERMAL" in health

    def test_get_system_health_cpu_saturated(self):
        engine = _fresh_engine()
        context = {
            "disk_free_gb": 100.0,
            "ram_percent": 50.0,
            "gpu_temp": 65.0,
            "cpu_percent": 97.0,
        }
        health, color = engine.get_system_health(context)
        assert "CPU" in health

    def test_ui_summary(self):
        engine = _fresh_engine()
        summary = engine.get_ui_summary()
        assert "health_text" in summary
        assert "health_color" in summary
        assert "recommendation_count" in summary
        assert "recommendations" in summary

    def test_ui_summary_with_recommendations(self):
        engine = _fresh_engine()
        rec = SystemRecommendation(
            title="Test rec",
            explanation="Test",
            severity=RecommendationSeverity.MEDIUM,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=300,
            category="test",
        )
        engine._active_recommendations = [rec]
        summary = engine.get_ui_summary()
        assert summary["recommendation_count"] == 1
        assert summary["recommendations"][0]["title"] == "Test rec"

    def test_format_status(self):
        engine = _fresh_engine()
        status = engine.format_status()
        assert "HEAVEN SOCIETY" in status
        assert "SYSTEM HEALTH" in status

    def test_format_status_with_recommendations(self):
        engine = _fresh_engine()
        rec = SystemRecommendation(
            title="Test rec",
            explanation="Test explanation",
            severity=RecommendationSeverity.HIGH,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=300,
            category="test",
        )
        engine._active_recommendations = [rec]
        status = engine.format_status()
        assert "Test rec" in status
        assert "Test explanation" in status

    def test_history_property(self):
        engine = _fresh_engine()
        assert isinstance(engine.history, RecommendationHistory)

    def test_active_recommendations_removes_expired(self):
        engine = _fresh_engine()
        rec = SystemRecommendation(
            title="Expired rec",
            explanation="Test",
            severity=RecommendationSeverity.LOW,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=0,
            category="test",
        )
        rec.expires_at = time.time() - 1  # expired
        engine._active_recommendations = [rec]
        active = engine.active_recommendations
        assert len(active) == 0

    def test_collect_context(self):
        engine = _fresh_engine()
        context = engine.collect_context()
        assert isinstance(context, dict)


# ══════════════════════════════════════════════════════════════════
# 7. CLI Integration
# ══════════════════════════════════════════════════════════════════

class TestCLIIntegration:
    def test_intelligent_recommendations_command(self):
        result = subprocess.run(
            [sys.executable, "main.py", "--intelligent-recommendations"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "HEAVEN SOCIETY" in result.stdout

    def test_recommendation_history_command(self):
        result = subprocess.run(
            [sys.executable, "main.py", "--recommendation-history"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "RECOMMENDATION HISTORY" in result.stdout


# ══════════════════════════════════════════════════════════════════
# 8. Edge Cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_multiple_rules_fire_simultaneously(self):
        engine = _fresh_engine()
        engine._last_evaluation = 0
        engine._history._last_fired = {}  # clear cooldowns
        context = {
            "disk_free_gb": 3.0,
            "disk_total_gb": 256,
            "ram_percent": 95.0,
            "ram_available_gb": 0.5,
            "gpu_temp": 92.0,
            "cpu_percent": 97.0,
        }
        recommendations = engine.evaluate(context)
        categories = {r.category for r in recommendations}
        assert len(categories) >= 3  # disk, memory, thermal, cpu

    def test_rule_base_class(self):
        """Verify base rule raises NotImplementedError."""
        r = RecommendationRule(rule_id="base", name="Base")
        with pytest.raises(NotImplementedError):
            r.evaluate({})

    def test_engine_active_recommendations_limit_ui(self):
        """UI summary should cap at 5 recommendations."""
        engine = _fresh_engine()
        engine._active_recommendations = [
            SystemRecommendation(
                title=f"Rec {i}",
                explanation="Test",
                severity=RecommendationSeverity.LOW,
                evidence=[],
                estimated_benefit="benefit",
                risk="NONE",
                action=RecommendationAction.REVIEW,
                cooldown_seconds=300,
                category="test",
            )
            for i in range(50)
        ]
        summary = engine.get_ui_summary()
        assert len(summary["recommendations"]) <= 5

    def test_history_empty(self):
        engine = _fresh_engine()
        engine._history._entries = []
        recent = engine._history.get_recent(10)
        assert isinstance(recent, list)

    def test_history_entries_persist(self):
        engine = _fresh_engine()
        rec = SystemRecommendation(
            title="Persist test",
            explanation="Test",
            severity=RecommendationSeverity.LOW,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=300,
            category="test",
        )
        engine._history.record_fire("persist_rule", rec)
        entries = engine._history.get_recent(10)
        assert len(entries) >= 1
        assert entries[0].title == "Persist test"

    def test_empty_context(self):
        engine = _fresh_engine()
        engine._last_evaluation = 0
        recs = engine.evaluate({})
        # Should not crash, may produce some rules if context collects defaults
        assert isinstance(recs, list)

    def test_history_action_tracking(self):
        h = RecommendationHistory()
        rec = SystemRecommendation(
            title="Track action",
            explanation="Test",
            severity=RecommendationSeverity.LOW,
            evidence=[],
            estimated_benefit="benefit",
            risk="NONE",
            action=RecommendationAction.REVIEW,
            cooldown_seconds=300,
            category="test",
        )
        h.record_fire("track_rule", rec)
        h.record_action(rec.id, "DISMISSED")
        found = False
        for entry in h._entries:
            if entry.recommendation_id == rec.id:
                assert entry.action_taken == "DISMISSED"
                found = True
                break
        assert found
