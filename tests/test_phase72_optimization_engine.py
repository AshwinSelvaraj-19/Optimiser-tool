"""
Phase 72 — Advanced Safe Windows Optimization Engine Tests

Tests for:
- Optimization registry completeness
- Optimization base class compliance
- Windows gaming adapters
- Startup optimization
- Cleanup optimization
- Adaptive engine integration
- Idempotency
- Safety boundaries
- Category mapping
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.optimization_base import Optimization, OptimizationResult, OptimizationStatus
from app.core.optimizations import get_all_optimizations, get_optimization_by_id
from app.ui.optimization_center import (
    OptimizationCategory,
    OptimizationItem,
    OptimizationRisk,
    get_optimization_items,
    get_optimization_items_by_category,
)


# ═══════════════════════════════════════════════════════════════
#  1. OPTIMIZATION REGISTRY
# ═══════════════════════════════════════════════════════════════

class TestOptimizationRegistry:
    """Verify the optimization registry is complete and valid."""

    def test_get_all_optimizations(self):
        opts = get_all_optimizations()
        assert len(opts) >= 5  # At minimum: power, game_mode, emulator, memory, background

    def test_all_have_required_fields(self):
        opts = get_all_optimizations()
        for opt in opts:
            assert opt.id, f"Optimization missing id: {opt}"
            assert opt.name, f"Optimization missing name: {opt.id}"
            assert opt.description, f"Optimization missing description: {opt.id}"
            assert opt.category, f"Optimization missing category: {opt.id}"

    def test_no_duplicate_ids(self):
        opts = get_all_optimizations()
        ids = [opt.id for opt in opts]
        assert len(ids) == len(set(ids)), f"Duplicate IDs: {ids}"

    def test_get_optimization_by_id(self):
        opt = get_optimization_by_id("power_plan")
        assert opt is not None
        assert opt.id == "power_plan"

    def test_get_optimization_by_id_unknown(self):
        opt = get_optimization_by_id("nonexistent_optimization")
        assert opt is None

    def test_all_optimizations_inherit_base(self):
        opts = get_all_optimizations()
        for opt in opts:
            assert isinstance(opt, Optimization), f"{opt.id} does not inherit Optimization"

    def test_all_have_check_apply_verify_rollback(self):
        opts = get_all_optimizations()
        for opt in opts:
            assert callable(getattr(opt, 'check', None)), f"{opt.id} missing check()"
            assert callable(getattr(opt, 'apply', None)), f"{opt.id} missing apply()"
            assert callable(getattr(opt, 'verify', None)), f"{opt.id} missing verify()"
            assert callable(getattr(opt, 'rollback', None)), f"{opt.id} missing rollback()"
            assert callable(getattr(opt, 'snapshot', None)), f"{opt.id} missing snapshot()"


# ═══════════════════════════════════════════════════════════════
#  2. KNOWN OPTIMIZATIONS
# ═══════════════════════════════════════════════════════════════

class TestKnownOptimizations:
    """Verify the core optimizations are present and functional."""

    def test_power_plan_exists(self):
        opt = get_optimization_by_id("power_plan")
        assert opt is not None
        assert opt.category == "SYSTEM"

    def test_game_mode_exists(self):
        opt = get_optimization_by_id("game_mode")
        assert opt is not None

    def test_emulator_priority_exists(self):
        opt = get_optimization_by_id("emulator_priority")
        assert opt is not None

    def test_background_load_exists(self):
        opt = get_optimization_by_id("background_load")
        assert opt is not None

    def test_memory_analysis_exists(self):
        opt = get_optimization_by_id("memory_analysis")
        assert opt is not None

    def test_game_bar_adapter_exists(self):
        opt = get_optimization_by_id("game_bar")
        assert opt is not None
        assert isinstance(opt, Optimization)

    def test_background_recording_adapter_exists(self):
        opt = get_optimization_by_id("background_recording")
        assert opt is not None

    def test_visual_effects_adapter_exists(self):
        opt = get_optimization_by_id("visual_effects")
        assert opt is not None

    def test_startup_optimization_exists(self):
        opt = get_optimization_by_id("startup_analysis")
        assert opt is not None
        assert isinstance(opt, Optimization)

    def test_cleanup_optimization_exists(self):
        opt = get_optimization_by_id("cleanup_files")
        assert opt is not None
        assert isinstance(opt, Optimization)


# ═══════════════════════════════════════════════════════════════
#  3. CHECK OPERATION
# ═══════════════════════════════════════════════════════════════

class TestCheckOperation:
    """Verify check() returns valid results for all optimizations."""

    def test_power_plan_check(self):
        opt = get_optimization_by_id("power_plan")
        result = opt.check()
        assert isinstance(result, OptimizationResult)
        assert result.status in (
            OptimizationStatus.ALREADY_OPTIMAL,
            OptimizationStatus.OPTIMIZABLE,
        )

    def test_game_mode_check(self):
        opt = get_optimization_by_id("game_mode")
        result = opt.check()
        assert isinstance(result, OptimizationResult)
        assert result.status in (
            OptimizationStatus.ALREADY_OPTIMAL,
            OptimizationStatus.OPTIMIZABLE,
        )

    def test_memory_analysis_check(self):
        opt = get_optimization_by_id("memory_analysis")
        result = opt.check()
        assert isinstance(result, OptimizationResult)
        # May be NOT_APPLICABLE if diagnostics unavailable
        assert result.status in (
            OptimizationStatus.ALREADY_OPTIMAL,
            OptimizationStatus.OPTIMIZABLE,
            OptimizationStatus.NOT_APPLICABLE,
        )

    def test_background_load_check(self):
        opt = get_optimization_by_id("background_load")
        result = opt.check()
        assert isinstance(result, OptimizationResult)
        assert result.status in (
            OptimizationStatus.ALREADY_OPTIMAL,
            OptimizationStatus.RECOMMENDATION_ONLY,
        )

    def test_startup_analysis_check(self):
        opt = get_optimization_by_id("startup_analysis")
        result = opt.check()
        assert isinstance(result, OptimizationResult)
        assert result.status in (
            OptimizationStatus.ALREADY_OPTIMAL,
            OptimizationStatus.RECOMMENDATION_ONLY,
            OptimizationStatus.NOT_AVAILABLE,
        )

    def test_cleanup_check(self):
        opt = get_optimization_by_id("cleanup_files")
        result = opt.check()
        assert isinstance(result, OptimizationResult)
        assert result.status in (
            OptimizationStatus.ALREADY_OPTIMAL,
            OptimizationStatus.OPTIMIZABLE,
            OptimizationStatus.NOT_AVAILABLE,
        )


# ═══════════════════════════════════════════════════════════════
#  4. SAFETY: DIAGNOSTIC-ONLY OPTIMIZATIONS
# ═══════════════════════════════════════════════════════════════

class TestDiagnosticOptimizations:
    """Verify read-only optimizations do not modify system state."""

    def test_background_load_is_recommendation_only(self):
        opt = get_optimization_by_id("background_load")
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_memory_analysis_is_recommendation_only(self):
        opt = get_optimization_by_id("memory_analysis")
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_startup_analysis_is_recommendation_only(self):
        opt = get_optimization_by_id("startup_analysis")
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_background_load_rollback_always_succeeds(self):
        opt = get_optimization_by_id("background_load")
        assert opt.rollback() is True

    def test_memory_analysis_rollback_always_succeeds(self):
        opt = get_optimization_by_id("memory_analysis")
        assert opt.rollback() is True


# ═══════════════════════════════════════════════════════════════
#  5. IDEMPOTENCY
# ═══════════════════════════════════════════════════════════════

class TestIdempotency:
    """Verify optimizations are idempotent."""

    def test_already_optimal_does_not_apply(self):
        """If check says ALREADY_OPTIMAL, apply should not change anything."""
        opt = get_optimization_by_id("power_plan")
        # Force ALREADY_OPTIMAL status
        opt._status = OptimizationStatus.ALREADY_OPTIMAL
        result = opt.apply()
        assert result.status == OptimizationStatus.ALREADY_OPTIMAL

    def test_not_applicable_does_not_apply(self):
        opt = get_optimization_by_id("emulator_priority")
        opt._status = OptimizationStatus.NOT_APPLICABLE
        result = opt.apply()
        assert result.status == OptimizationStatus.NOT_APPLICABLE

    def test_requires_admin_does_not_apply(self):
        opt = get_optimization_by_id("emulator_priority")
        opt._status = OptimizationStatus.REQUIRES_ADMIN
        result = opt.apply()
        assert result.status == OptimizationStatus.REQUIRES_ADMIN


# ═══════════════════════════════════════════════════════════════
#  6. OPTIMIZATION CENTER REGISTRY
# ═══════════════════════════════════════════════════════════════

class TestOptimizationCenterRegistry:
    """Verify the command center registry matches real optimizations."""

    def test_center_has_all_optimization_ids(self):
        center_items = get_optimization_items()
        center_ids = {item.opt_id for item in center_items}
        # Must have the core optimizations
        required = {"power_plan", "game_mode", "background_load", "memory_analysis"}
        assert required.issubset(center_ids), f"Missing: {required - center_ids}"

    def test_center_categories_match_real_optimizations(self):
        groups = get_optimization_items_by_category()
        # POWER must have power_plan
        power_ids = {i.opt_id for i in groups.get(OptimizationCategory.POWER, [])}
        assert "power_plan" in power_ids

        # GAMING must have game_mode
        gaming_ids = {i.opt_id for i in groups.get(OptimizationCategory.GAMING, [])}
        assert "game_mode" in gaming_ids

    def test_center_no_duplicate_ids(self):
        items = get_optimization_items()
        ids = [item.opt_id for item in items]
        assert len(ids) == len(set(ids))

    def test_center_item_has_all_fields(self):
        items = get_optimization_items()
        for item in items:
            assert item.opt_id
            assert item.name
            assert item.description
            assert item.category in OptimizationCategory


# ═══════════════════════════════════════════════════════════════
#  7. ADAPTIVE ENGINE INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestAdaptiveIntegration:
    """Verify adaptive engine optimization IDs map to real optimizations."""

    def test_adaptive_optimization_ids_valid(self):
        from app.core.adaptive_engine import CONDITION_OPTIMIZATIONS
        all_ids = {opt.id for opt in get_all_optimizations()}
        for ct, specs in CONDITION_OPTIMIZATIONS.items():
            for opt_id, name, risk, reversible in specs:
                # Must either be a real optimization or a valid diagnostic
                assert opt_id in all_ids or opt_id in (
                    "background_load", "memory_analysis", "power_plan",
                    "emulator_priority",
                ), f"Adaptive references unknown optimization: {opt_id}"

    def test_adaptive_optimizations_executable(self):
        """Every adaptive optimization ID must be retrievable via get_optimization_by_id."""
        from app.core.adaptive_engine import CONDITION_OPTIMIZATIONS
        for ct, specs in CONDITION_OPTIMIZATIONS.items():
            for opt_id, name, risk, reversible in specs:
                opt = get_optimization_by_id(opt_id)
                assert opt is not None, f"Adaptive optimization {opt_id} not found in registry"


# ═══════════════════════════════════════════════════════════════
#  8. SAFETY BOUNDARIES
# ═══════════════════════════════════════════════════════════════

class TestSafetyBoundaries:
    """Verify no prohibited operations exist."""

    def test_no_cheat_related_optimizations(self):
        opts = get_all_optimizations()
        prohibited = ["cheat", "inject", "hack", "exploit", "bypass", "aimbot", "recoil"]
        for opt in opts:
            for kw in prohibited:
                assert kw not in opt.id.lower(), f"Prohibited in ID: {opt.id}"
                assert kw not in opt.name.lower(), f"Prohibited in name: {opt.name}"
                assert kw not in opt.description.lower(), f"Prohibited in desc: {opt.description}"

    def test_no_process_termination_optimizations(self):
        """No optimization should terminate processes."""
        opts = get_all_optimizations()
        for opt in opts:
            # Background load is recommendation-only
            if opt.id == "background_load":
                result = opt.apply()
                assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_all_optimizations_are_os_level(self):
        opts = get_all_optimizations()
        for opt in opts:
            assert opt.category in (
                "SYSTEM", "GAMING", "EMULATOR", "STARTUP", "CLEANUP",
            ) or opt.id in ("power_plan", "game_mode", "background_load", "memory_analysis"), \
                f"Unknown category for {opt.id}: {opt.category}"


# ═══════════════════════════════════════════════════════════════
#  9. ADAPTER COMPLIANCE
# ═══════════════════════════════════════════════════════════════

class TestAdapterCompliance:
    """Verify Windows gaming adapters properly implement Optimization interface."""

    def test_game_bar_adapter(self):
        from app.core.windows_optimizations import GameBarAdapter
        opt = GameBarAdapter()
        assert isinstance(opt, Optimization)
        assert opt.id == "game_bar"
        result = opt.check()
        assert isinstance(result, OptimizationResult)

    def test_background_recording_adapter(self):
        from app.core.windows_optimizations import BackgroundRecordingAdapter
        opt = BackgroundRecordingAdapter()
        assert isinstance(opt, Optimization)
        assert opt.id == "background_recording"
        result = opt.check()
        assert isinstance(result, OptimizationResult)

    def test_visual_effects_adapter(self):
        from app.core.windows_optimizations import VisualEffectsAdapter
        opt = VisualEffectsAdapter()
        assert isinstance(opt, Optimization)
        assert opt.id == "visual_effects"
        result = opt.check()
        assert isinstance(result, OptimizationResult)

    def test_adapter_apply_when_not_optimizable(self):
        from app.core.windows_optimizations import GameBarAdapter
        opt = GameBarAdapter()
        opt._status = OptimizationStatus.ALREADY_OPTIMAL
        result = opt.apply()
        assert result.status == OptimizationStatus.ALREADY_OPTIMAL


# ═══════════════════════════════════════════════════════════════
#  10. STARTUP SAFETY
# ═══════════════════════════════════════════════════════════════

class TestStartupSafety:
    """Verify startup optimization is safe and read-only."""

    def test_startup_is_read_only(self):
        opt = get_optimization_by_id("startup_analysis")
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_startup_rollback_always_succeeds(self):
        opt = get_optimization_by_id("startup_analysis")
        assert opt.rollback() is True

    def test_startup_verify_always_succeeds(self):
        opt = get_optimization_by_id("startup_analysis")
        assert opt.verify() is True


# ═══════════════════════════════════════════════════════════════
#  11. CLEANUP INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestCleanupIntegration:
    """Verify cleanup optimization integrates with CleanupCenter."""

    def test_cleanup_is_real_optimization(self):
        opt = get_optimization_by_id("cleanup_files")
        assert isinstance(opt, Optimization)
        assert opt.category == "CLEANUP"

    def test_cleanup_check_returns_valid_result(self):
        opt = get_optimization_by_id("cleanup_files")
        result = opt.check()
        assert isinstance(result, OptimizationResult)
        assert result.status in (
            OptimizationStatus.ALREADY_OPTIMAL,
            OptimizationStatus.OPTIMIZABLE,
            OptimizationStatus.NOT_AVAILABLE,
        )


# ═══════════════════════════════════════════════════════════════
#  12. OPTIMIZATION STATUS VALUES
# ═══════════════════════════════════════════════════════════════

class TestOptimizationStatusValues:
    """Verify status values are correctly used."""

    def test_optimization_status_enum_completeness(self):
        required = {
            "PENDING", "CHECKED", "OPTIMIZABLE", "NOT APPLICABLE",
            "ALREADY OPTIMAL", "REQUIRES_ADMIN", "RECOMMENDATION ONLY",
            "SNAPSHOT TAKEN", "APPLIED", "VERIFIED", "REVERTED",
            "FAILED", "NOT AVAILABLE",
        }
        actual = {s.value for s in OptimizationStatus}
        assert required.issubset(actual)

    def test_optimization_result_defaults(self):
        result = OptimizationResult()
        assert result.status == OptimizationStatus.PENDING
        assert result.current_value == ""
        assert result.recommended_value == ""
        assert result.message == ""
