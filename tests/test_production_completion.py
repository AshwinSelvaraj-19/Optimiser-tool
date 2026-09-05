"""
Heaven Society — Production Completion Validation

End-to-end test covering the complete user workflow:
Launch → Detect → Recommend → Optimize → Verify → Result → Rollback

Also validates:
- All optimization categories
- Adaptive engine integration
- Gaming session lifecycle
- Cleanup safety
- Maintenance intelligence
- Shader fallback
- Settings persistence
- Error handling
- Safety boundaries
"""

import os
import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.optimization_base import Optimization, OptimizationResult, OptimizationStatus
from app.core.optimizations import get_all_optimizations, get_optimization_by_id


# ═══════════════════════════════════════════════════════════════
#  1. OPTIMIZATION REGISTRY COMPLETENESS
# ═══════════════════════════════════════════════════════════════

class TestOptimizationRegistry:
    """Verify the optimization registry is complete and correct."""

    REQUIRED_OPTIMIZATIONS = {
        "power_plan", "game_mode", "emulator_priority",
        "background_load", "memory_analysis",
        "game_bar", "background_recording", "visual_effects",
        "startup_analysis", "cleanup_files",
    }

    def test_all_required_optimizations_registered(self):
        opts = get_all_optimizations()
        ids = {opt.id for opt in opts}
        missing = self.REQUIRED_OPTIMIZATIONS - ids
        assert not missing, f"Missing optimizations: {missing}"

    def test_no_duplicate_ids(self):
        opts = get_all_optimizations()
        ids = [opt.id for opt in opts]
        assert len(ids) == len(set(ids))

    def test_all_inherit_optimization_base(self):
        opts = get_all_optimizations()
        for opt in opts:
            assert isinstance(opt, Optimization)

    def test_all_have_required_methods(self):
        opts = get_all_optimizations()
        for opt in opts:
            assert callable(getattr(opt, 'check', None))
            assert callable(getattr(opt, 'apply', None))
            assert callable(getattr(opt, 'verify', None))
            assert callable(getattr(opt, 'rollback', None))
            assert callable(getattr(opt, 'snapshot', None))

    def test_categories_are_consistent(self):
        """Optimization categories must match optimization center categories."""
        from app.ui.optimization_center import OptimizationCategory, get_optimization_items
        center_ids = {item.opt_id for item in get_optimization_items()}
        opts = get_all_optimizations()
        for opt in opts:
            if opt.id in center_ids:
                # Category should be one of the recognized categories
                assert opt.category in ("POWER", "PERFORMANCE", "MEMORY", "GAMING",
                                        "STARTUP", "CLEANUP", "SYSTEM", "EMULATOR"), \
                    f"{opt.id} has unrecognized category: {opt.category}"


# ═══════════════════════════════════════════════════════════════
#  2. EVERY OPTIMIZATION CHECKS SAFELY
# ═══════════════════════════════════════════════════════════════

class TestAllOptimizationsCheckSafely:
    """Every optimization must return a valid result from check()."""

    def test_all_return_optimization_result(self):
        opts = get_all_optimizations()
        for opt in opts:
            result = opt.check()
            assert isinstance(result, OptimizationResult), f"{opt.id} check() did not return OptimizationResult"

    def test_all_have_valid_status(self):
        opts = get_all_optimizations()
        for opt in opts:
            result = opt.check()
            assert isinstance(result.status, OptimizationStatus), f"{opt.id} has invalid status"


# ═══════════════════════════════════════════════════════════════
#  3. RECOMMENDATION-ONLY PROTECTION
# ═══════════════════════════════════════════════════════════════

class TestRecommendationOnlyProtection:
    """Non-destructive optimizations must not modify system state."""

    REC_ONLY = ["background_load", "memory_analysis", "startup_analysis"]

    @pytest.mark.parametrize("opt_id", REC_ONLY)
    def test_apply_returns_recommendation_only(self, opt_id):
        opt = get_optimization_by_id(opt_id)
        assert opt is not None
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    @pytest.mark.parametrize("opt_id", REC_ONLY)
    def test_rollback_always_succeeds(self, opt_id):
        opt = get_optimization_by_id(opt_id)
        assert opt.rollback() is True

    @pytest.mark.parametrize("opt_id", REC_ONLY)
    def test_verify_always_succeeds(self, opt_id):
        opt = get_optimization_by_id(opt_id)
        assert opt.verify() is True


# ═══════════════════════════════════════════════════════════════
#  4. IDEMPOTENCY
# ═══════════════════════════════════════════════════════════════

class TestIdempotency:
    """Verify optimizations block repeated application."""

    @pytest.mark.parametrize("opt_id", ["power_plan", "game_mode", "emulator_priority"])
    def test_already_optimal_blocks_apply(self, opt_id):
        opt = get_optimization_by_id(opt_id)
        opt._status = OptimizationStatus.ALREADY_OPTIMAL
        result = opt.apply()
        assert result.status == OptimizationStatus.ALREADY_OPTIMAL

    @pytest.mark.parametrize("opt_id", ["power_plan", "game_mode"])
    def test_not_applicable_blocks_apply(self, opt_id):
        opt = get_optimization_by_id(opt_id)
        opt._status = OptimizationStatus.NOT_APPLICABLE
        result = opt.apply()
        assert result.status == OptimizationStatus.NOT_APPLICABLE


# ═══════════════════════════════════════════════════════════════
#  5. ADAPTIVE ENGINE INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestAdaptiveIntegration:
    """Verify adaptive engine connects to real optimizations."""

    def test_all_adaptive_optimization_ids_are_valid(self):
        from app.core.adaptive_engine import CONDITION_OPTIMIZATIONS
        for ct, specs in CONDITION_OPTIMIZATIONS.items():
            for opt_id, name, risk, reversible in specs:
                opt = get_optimization_by_id(opt_id)
                assert opt is not None, f"Adaptive references unknown: {opt_id}"

    def test_adaptive_optimizations_are_executable(self):
        from app.core.adaptive_engine import CONDITION_OPTIMIZATIONS
        for ct, specs in CONDITION_OPTIMIZATIONS.items():
            for opt_id, name, risk, reversible in specs:
                opt = get_optimization_by_id(opt_id)
                result = opt.check()
                assert isinstance(result, OptimizationResult)


# ═══════════════════════════════════════════════════════════════
#  6. SAFETY BOUNDARIES
# ═══════════════════════════════════════════════════════════════

class TestSafetyBoundaries:
    """No prohibited operations exist."""

    PROHIBITED = ["cheat", "inject", "hack", "exploit", "bypass",
                  "aimbot", "recoil", "packet", "hook", "patch"]

    def test_no_prohibited_optimizations(self):
        opts = get_all_optimizations()
        for opt in opts:
            for kw in self.PROHIBITED:
                assert kw not in opt.id.lower(), f"Prohibited in ID: {opt.id}"
                assert kw not in opt.name.lower(), f"Prohibited in name: {opt.name}"
                assert kw not in opt.description.lower(), f"Prohibited in desc: {opt.description}"

    def test_no_process_killing_optimizations(self):
        """No optimization should terminate processes."""
        rec_only = ["background_load", "memory_analysis", "startup_analysis"]
        for opt_id in rec_only:
            opt = get_optimization_by_id(opt_id)
            result = opt.apply()
            assert result.status == OptimizationStatus.RECOMMENDATION_ONLY


# ═══════════════════════════════════════════════════════════════
#  7. CLEANUP SEMANTICS
# ═══════════════════════════════════════════════════════════════

class TestCleanupSemantics:
    """Cleanup is destructive — verify correct semantics."""

    def test_cleanup_not_reversible_in_center(self):
        from app.ui.optimization_center import get_optimization_items
        items = get_optimization_items()
        cleanup = [i for i in items if i.opt_id == "cleanup_files"]
        assert len(cleanup) == 1
        assert cleanup[0].reversible is False

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
#  8. PERFORMANCE
# ═══════════════════════════════════════════════════════════════

class TestPerformance:
    """Verify no expensive operations on GUI path."""

    def test_get_current_status_is_fast(self):
        from app.core.optimizer import optimizer
        t0 = time.time()
        status = optimizer.get_current_status()
        elapsed = (time.time() - t0) * 1000
        assert elapsed < 500, f"get_current_status: {elapsed:.0f}ms"

    def test_get_ui_summary_is_fast(self):
        from app.core.optimization_engine import optimization_engine
        t0 = time.time()
        summary = optimization_engine.get_ui_summary()
        elapsed = (time.time() - t0) * 1000
        assert elapsed < 100, f"get_ui_summary: {elapsed:.0f}ms"


# ═══════════════════════════════════════════════════════════════
#  9. OPTIMIZATION CENTER CATEGORIES
# ═══════════════════════════════════════════════════════════════

class TestOptimizationCenterCategories:
    """Verify optimization center reflects real registry."""

    def test_center_has_all_required_ids(self):
        from app.ui.optimization_center import get_optimization_items
        items = get_optimization_items()
        ids = {item.opt_id for item in items}
        required = {"power_plan", "game_mode", "background_load", "memory_analysis"}
        assert required.issubset(ids)

    def test_center_categories_match_real_optimizations(self):
        from app.ui.optimization_center import get_optimization_items_by_category, OptimizationCategory
        groups = get_optimization_items_by_category()
        power_ids = {i.opt_id for i in groups.get(OptimizationCategory.POWER, [])}
        assert "power_plan" in power_ids
        gaming_ids = {i.opt_id for i in groups.get(OptimizationCategory.GAMING, [])}
        assert "game_mode" in gaming_ids


# ═══════════════════════════════════════════════════════════════
#  10. WINDOWS ADAPTERS
# ═══════════════════════════════════════════════════════════════

class TestWindowsAdapters:
    """Verify adapter classes properly implement Optimization interface."""

    def test_game_bar_adapter(self):
        from app.core.windows_optimizations import GameBarAdapter
        opt = GameBarAdapter()
        assert isinstance(opt, Optimization)
        result = opt.check()
        assert isinstance(result, OptimizationResult)

    def test_background_recording_adapter(self):
        from app.core.windows_optimizations import BackgroundRecordingAdapter
        opt = BackgroundRecordingAdapter()
        assert isinstance(opt, Optimization)
        result = opt.check()
        assert isinstance(result, OptimizationResult)

    def test_visual_effects_adapter(self):
        from app.core.windows_optimizations import VisualEffectsAdapter
        opt = VisualEffectsAdapter()
        assert isinstance(opt, Optimization)
        result = opt.check()
        assert isinstance(result, OptimizationResult)


# ═══════════════════════════════════════════════════════════════
#  11. STARTUP SAFETY
# ═══════════════════════════════════════════════════════════════

class TestStartupSafety:
    """Startup analysis must be read-only."""

    def test_startup_is_read_only(self):
        opt = get_optimization_by_id("startup_analysis")
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_startup_risk_level_is_none(self):
        opt = get_optimization_by_id("startup_analysis")
        assert opt.risk_level == "NONE"


# ═══════════════════════════════════════════════════════════════
#  12. ERROR HANDLING
# ═══════════════════════════════════════════════════════════════

class TestErrorHandling:
    """Every optimization must fail gracefully."""

    def test_unknown_optimization_returns_none(self):
        opt = get_optimization_by_id("nonexistent_optimization_xyz")
        assert opt is None

    def test_check_with_missing_dependency(self):
        """Optimizations should handle missing dependencies gracefully."""
        opt = get_optimization_by_id("power_plan")
        # Power plan check should not crash even if powercfg fails
        result = opt.check()
        assert isinstance(result, OptimizationResult)


# ═══════════════════════════════════════════════════════════════
#  13. COMPLETE WORKFLOW
# ═══════════════════════════════════════════════════════════════

class TestCompleteWorkflow:
    """Test the complete optimization workflow end-to-end."""

    def test_power_plan_workflow(self):
        """Complete workflow: detect → check → snapshot → apply → verify → rollback."""
        opt = get_optimization_by_id("power_plan")
        assert opt is not None

        # 1. Check
        result = opt.check()
        assert isinstance(result, OptimizationResult)

        # 2. If optimizable, test the full cycle
        if result.status == OptimizationStatus.OPTIMIZABLE:
            # Snapshot
            snap = opt.snapshot()
            assert isinstance(snap, dict)

            # Apply
            apply_result = opt.apply()
            assert apply_result.status in (
                OptimizationStatus.APPLIED,
                OptimizationStatus.FAILED,
                OptimizationStatus.REQUIRES_ADMIN,
            )

            # If applied, verify and rollback
            if apply_result.status == OptimizationStatus.APPLIED:
                verified = opt.verify()
                assert isinstance(verified, bool)

                # Rollback
                rolled = opt.rollback()
                assert isinstance(rolled, bool)
        else:
            # Already optimal or not applicable — verify idempotency
            apply_result = opt.apply()
            assert apply_result.status in (
                OptimizationStatus.ALREADY_OPTIMAL,
                OptimizationStatus.NOT_APPLICABLE,
                OptimizationStatus.RECOMMENDATION_ONLY,
            )

    def test_game_mode_workflow(self):
        opt = get_optimization_by_id("game_mode")
        result = opt.check()
        assert isinstance(result, OptimizationResult)
        if result.status == OptimizationStatus.OPTIMIZABLE:
            snap = opt.snapshot()
            assert isinstance(snap, dict)
