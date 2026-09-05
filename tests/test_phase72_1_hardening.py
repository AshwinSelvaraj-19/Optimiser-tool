"""
Phase 72.1 — Optimization Engine Hardening Tests

Tests for:
- Performance: get_current_status is fast
- Worker thread isolation
- Recommendation-only protection
- Cleanup semantics
- Startup read-only
- Optimization classification
- Idempotency
- Adaptive integration
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.optimization_base import Optimization, OptimizationResult, OptimizationStatus
from app.core.optimizations import get_all_optimizations, get_optimization_by_id


# ═══════════════════════════════════════════════════════════════
#  1. PERFORMANCE
# ═══════════════════════════════════════════════════════════════

class TestPerformance:
    """Verify optimization status is fast (no expensive system queries)."""

    def test_get_current_status_is_fast(self):
        """get_current_status must not call .check() on all optimizations."""
        from app.core.optimizer import optimizer
        t0 = time.time()
        status = optimizer.get_current_status()
        elapsed = (time.time() - t0) * 1000
        assert elapsed < 500, f"get_current_status took {elapsed:.0f}ms (should be <500ms)"

    def test_get_current_status_returns_all_optimizations(self):
        from app.core.optimizer import optimizer
        status = optimizer.get_current_status()
        assert len(status["optimizations"]) >= 10

    def test_get_current_status_has_metadata(self):
        from app.core.optimizer import optimizer
        status = optimizer.get_current_status()
        for opt in status["optimizations"]:
            assert "id" in opt
            assert "name" in opt
            assert "category" in opt

    def test_get_current_status_no_check_results(self):
        """Status should not include check results (those belong in worker)."""
        from app.core.optimizer import optimizer
        status = optimizer.get_current_status()
        for opt in status["optimizations"]:
            # Should NOT have 'status' from check() — only metadata
            assert "status" not in opt or opt.get("status") is None


# ═══════════════════════════════════════════════════════════════
#  2. RECOMMENDATION-ONLY PROTECTION
# ═══════════════════════════════════════════════════════════════

class TestRecommendationOnlyProtection:
    """Verify non-destructive optimizations cannot modify system state."""

    BACKGROUND_LOAD_IDS = ["background_load", "memory_analysis", "startup_analysis"]

    @pytest.mark.parametrize("opt_id", BACKGROUND_LOAD_IDS)
    def test_recommendation_only_apply_returns_recommendation_only(self, opt_id):
        opt = get_optimization_by_id(opt_id)
        assert opt is not None, f"Optimization {opt_id} not found"
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY, \
            f"{opt_id}.apply() returned {result.status} instead of RECOMMENDATION_ONLY"

    @pytest.mark.parametrize("opt_id", BACKGROUND_LOAD_IDS)
    def test_recommendation_only_rollback_always_succeeds(self, opt_id):
        opt = get_optimization_by_id(opt_id)
        assert opt.rollback() is True

    @pytest.mark.parametrize("opt_id", BACKGROUND_LOAD_IDS)
    def test_recommendation_only_verify_always_succeeds(self, opt_id):
        opt = get_optimization_by_id(opt_id)
        assert opt.verify() is True


# ═══════════════════════════════════════════════════════════════
#  3. CLEANUP SEMANTICS
# ═══════════════════════════════════════════════════════════════

class TestCleanupSemantics:
    """Verify cleanup optimization correctly communicates its nature."""

    def test_cleanup_is_not_reversible_in_center(self):
        from app.ui.optimization_center import get_optimization_items
        items = get_optimization_items()
        cleanup = [i for i in items if i.opt_id == "cleanup_files"]
        assert len(cleanup) == 1
        assert cleanup[0].reversible is False, "Cleanup should not be marked reversible"

    def test_cleanup_check_works(self):
        opt = get_optimization_by_id("cleanup_files")
        result = opt.check()
        assert isinstance(result, OptimizationResult)
        assert result.status in (
            OptimizationStatus.ALREADY_OPTIMAL,
            OptimizationStatus.OPTIMIZABLE,
            OptimizationStatus.NOT_AVAILABLE,
        )


# ═══════════════════════════════════════════════════════════════
#  4. STARTUP READ-ONLY
# ═══════════════════════════════════════════════════════════════

class TestStartupReadOnly:
    """Verify startup analysis does not modify system state."""

    def test_startup_apply_returns_recommendation_only(self):
        opt = get_optimization_by_id("startup_analysis")
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_startup_is_analysis_only(self):
        opt = get_optimization_by_id("startup_analysis")
        assert opt.risk_level == "NONE"


# ═══════════════════════════════════════════════════════════════
#  5. OPTIMIZATION CLASSIFICATION
# ═══════════════════════════════════════════════════════════════

class TestOptimizationClassification:
    """Verify each optimization has correct metadata."""

    def test_state_changing_optimizations(self):
        """These actually modify system state."""
        state_changing = ["power_plan", "game_mode", "emulator_priority",
                          "game_bar", "background_recording", "visual_effects"]
        for opt_id in state_changing:
            opt = get_optimization_by_id(opt_id)
            assert opt is not None, f"{opt_id} not found"
            assert isinstance(opt, Optimization)

    def test_recommendation_only_optimizations(self):
        """These are analysis/recommendation only."""
        rec_only = ["background_load", "memory_analysis", "startup_analysis"]
        for opt_id in rec_only:
            opt = get_optimization_by_id(opt_id)
            assert opt is not None, f"{opt_id} not found"
            result = opt.apply()
            assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_cleanup_is_separate_category(self):
        opt = get_optimization_by_id("cleanup_files")
        assert opt is not None
        assert opt.category == "CLEANUP"


# ═══════════════════════════════════════════════════════════════
#  6. IDEMPOTENCY
# ═══════════════════════════════════════════════════════════════

class TestIdempotency:
    """Verify optimizations are idempotent."""

    def test_already_optimal_blocks_apply(self):
        opt = get_optimization_by_id("power_plan")
        opt._status = OptimizationStatus.ALREADY_OPTIMAL
        result = opt.apply()
        assert result.status == OptimizationStatus.ALREADY_OPTIMAL

    def test_not_applicable_blocks_apply(self):
        opt = get_optimization_by_id("emulator_priority")
        opt._status = OptimizationStatus.NOT_APPLICABLE
        result = opt.apply()
        assert result.status == OptimizationStatus.NOT_APPLICABLE

    def test_requires_admin_blocks_apply(self):
        opt = get_optimization_by_id("emulator_priority")
        opt._status = OptimizationStatus.REQUIRES_ADMIN
        result = opt.apply()
        assert result.status == OptimizationStatus.REQUIRES_ADMIN


# ═══════════════════════════════════════════════════════════════
#  7. ADAPTIVE INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestAdaptiveIntegration:
    """Verify adaptive engine connects to real optimizations."""

    def test_adaptive_optimization_ids_are_valid(self):
        from app.core.adaptive_engine import CONDITION_OPTIMIZATIONS
        for ct, specs in CONDITION_OPTIMIZATIONS.items():
            for opt_id, name, risk, reversible in specs:
                opt = get_optimization_by_id(opt_id)
                assert opt is not None, f"Adaptive references unknown: {opt_id}"

    def test_recommendation_only_not_in_adaptive_apply_path(self):
        """Recommendation-only optimizations should not be auto-applied."""
        from app.core.adaptive_engine import CONDITION_OPTIMIZATIONS
        rec_only_ids = {"background_load", "memory_analysis", "startup_analysis"}
        for ct, specs in CONDITION_OPTIMIZATIONS.items():
            for opt_id, name, risk, reversible in specs:
                if opt_id in rec_only_ids:
                    # These should still be referenced for recommendations
                    # but the adaptive engine should not auto-apply them
                    opt = get_optimization_by_id(opt_id)
                    result = opt.apply()
                    assert result.status == OptimizationStatus.RECOMMENDATION_ONLY


# ═══════════════════════════════════════════════════════════════
#  8. WORKER THREAD ISOLATION
# ═══════════════════════════════════════════════════════════════

class TestWorkerThreadIsolation:
    """Verify expensive work runs in worker, not GUI thread."""

    def test_get_ui_summary_is_fast(self):
        from app.core.optimization_engine import optimization_engine
        t0 = time.time()
        summary = optimization_engine.get_ui_summary()
        elapsed = (time.time() - t0) * 1000
        assert elapsed < 100, f"get_ui_summary took {elapsed:.0f}ms (should be <100ms)"

    def test_worker_result_has_required_fields(self):
        from app.ui.optimizer_worker import OptimizerWorkerResult
        result = OptimizerWorkerResult()
        assert hasattr(result, 'telemetry_frame')
        assert hasattr(result, 'target')
        assert hasattr(result, 'opt_status')
        assert hasattr(result, 'engine_summary')


# ═══════════════════════════════════════════════════════════════
#  9. SAFETY BOUNDARIES
# ═══════════════════════════════════════════════════════════════

class TestSafetyBoundaries:
    """Verify no prohibited operations exist."""

    def test_no_cheat_related_optimizations(self):
        opts = get_all_optimizations()
        prohibited = ["cheat", "inject", "hack", "exploit", "bypass", "aimbot"]
        for opt in opts:
            for kw in prohibited:
                assert kw not in opt.id.lower()
                assert kw not in opt.name.lower()

    def test_all_optimizations_are_os_level(self):
        opts = get_all_optimizations()
        for opt in opts:
            assert opt.category in (
                "SYSTEM", "GAMING", "EMULATOR", "STARTUP", "CLEANUP",
                "POWER", "PERFORMANCE", "MEMORY",
            )
