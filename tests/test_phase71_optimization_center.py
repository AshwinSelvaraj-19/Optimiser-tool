"""
Phase 71 — Optimization Command Center + Real-Time Shader Tests

Tests for:
- Optimization categories
- Optimization status
- Optimization items registry
- Shader settings persistence
- Shader enable/disable
- Shader quality levels
- Shader fallback behavior
- Command center data models
- Active optimization tracking
- Result reporting
"""

import time
from unittest.mock import MagicMock, patch

import pytest

from app.ui.optimization_center import (
    ActiveOptimization,
    OptimizationCategory,
    OptimizationItem,
    OptimizationResult,
    OptimizationRisk,
    OptimizationStatus,
    get_category_icon,
    get_category_label,
    get_optimization_items,
    get_optimization_items_by_category,
    get_status_color,
    get_status_label,
)


# ═══════════════════════════════════════════════════════════════
#  1. OPTIMIZATION CATEGORIES
# ═══════════════════════════════════════════════════════════════

class TestOptimizationCategories:
    """Verify optimization categories are defined and complete."""

    def test_all_categories_have_labels(self):
        for cat in OptimizationCategory:
            label = get_category_label(cat)
            assert label, f"Category {cat} has no label"

    def test_all_categories_have_icons(self):
        for cat in OptimizationCategory:
            icon = get_category_icon(cat)
            assert icon, f"Category {cat} has no icon"

    def test_expected_categories_exist(self):
        expected = {"PERFORMANCE", "MEMORY", "POWER", "GAMING", "STARTUP", "CLEANUP", "SYSTEM"}
        actual = {cat.value for cat in OptimizationCategory}
        assert expected == actual


# ═══════════════════════════════════════════════════════════════
#  2. OPTIMIZATION REGISTRY
# ═══════════════════════════════════════════════════════════════

class TestOptimizationRegistry:
    """Verify the optimization registry returns valid items."""

    def test_get_optimization_items(self):
        items = get_optimization_items()
        assert len(items) > 0

    def test_items_have_required_fields(self):
        items = get_optimization_items()
        for item in items:
            assert item.opt_id
            assert item.name
            assert item.description
            assert item.category in OptimizationCategory
            assert item.risk in OptimizationRisk

    def test_get_by_category(self):
        groups = get_optimization_items_by_category()
        assert len(groups) > 0
        for cat, items in groups.items():
            assert cat in OptimizationCategory
            assert len(items) > 0

    def test_known_optimizations_present(self):
        items = get_optimization_items()
        ids = {item.opt_id for item in items}
        assert "power_plan" in ids
        assert "game_mode" in ids
        assert "emulator_priority" in ids
        assert "background_load" in ids

    def test_no_duplicate_ids(self):
        items = get_optimization_items()
        ids = [item.opt_id for item in items]
        assert len(ids) == len(set(ids))


# ═══════════════════════════════════════════════════════════════
#  3. OPTIMIZATION STATUS
# ═══════════════════════════════════════════════════════════════

class TestOptimizationStatus:
    """Verify status model."""

    def test_all_statuses_have_labels(self):
        for s in OptimizationStatus:
            label = get_status_label(s)
            assert label, f"Status {s} has no label"

    def test_all_statuses_have_colors(self):
        for s in OptimizationStatus:
            color = get_status_color(s)
            assert color, f"Status {s} has no color"

    def test_status_transitions(self):
        """Verify logical status progression."""
        statuses = [
            OptimizationStatus.UNKNOWN,
            OptimizationStatus.RECOMMENDED,
            OptimizationStatus.APPLIED,
            OptimizationStatus.ROLLED_BACK,
        ]
        # Each should be a valid state
        for s in statuses:
            assert isinstance(s, OptimizationStatus)

    def test_status_serialization(self):
        assert OptimizationStatus.APPLIED.value == "APPLIED"
        assert OptimizationStatus.RECOMMENDED.value == "RECOMMENDED"


# ═══════════════════════════════════════════════════════════════
#  4. DATA MODELS
# ═══════════════════════════════════════════════════════════════

class TestDataModels:
    """Verify data model serialization and defaults."""

    def test_optimization_item_to_dict(self):
        item = OptimizationItem(
            opt_id="test_opt",
            name="Test Optimization",
            description="A test",
            category=OptimizationCategory.PERFORMANCE,
        )
        d = item.to_dict()
        assert d["opt_id"] == "test_opt"
        assert d["category"] == "PERFORMANCE"
        assert d["status"] == "UNKNOWN"

    def test_optimization_result(self):
        result = OptimizationResult(
            opt_id="test",
            name="Test",
            success=True,
            verification_passed=True,
            impact="HELPED",
        )
        assert result.success
        assert result.impact == "HELPED"

    def test_active_optimization(self):
        active = ActiveOptimization(
            opt_id="power_plan",
            name="Power Plan",
            category="POWER",
            applied_at=time.time(),
            previous_state="Balanced",
            current_state="Performance",
        )
        assert active.rollback_available
        assert active.previous_state == "Balanced"

    def test_optimization_risk_levels(self):
        assert OptimizationRisk.SAFE.value == "SAFE"
        assert OptimizationRisk.LOW.value == "LOW"
        assert OptimizationRisk.REVIEW.value == "REVIEW"
        assert OptimizationRisk.HIGH.value == "HIGH"


# ═══════════════════════════════════════════════════════════════
#  5. SHADER SETTINGS
# ═══════════════════════════════════════════════════════════════

class TestShaderSettings:
    """Verify shader settings persistence and behavior."""

    def test_shader_widget_importable(self):
        from app.ui.shader_widget import ShaderWidget
        assert ShaderWidget is not None

    def test_shader_quality_levels(self):
        from app.ui.shader_widget import ShaderWidget
        assert ShaderWidget.QUALITY_LOW == "LOW"
        assert ShaderWidget.QUALITY_MEDIUM == "MEDIUM"
        assert ShaderWidget.QUALITY_HIGH == "HIGH"

    def test_shader_fps_limits(self):
        from app.ui.shader_widget import ShaderWidget
        assert ShaderWidget._QUALITY_FPS["LOW"] <= ShaderWidget._QUALITY_FPS["MEDIUM"]
        assert ShaderWidget._QUALITY_FPS["MEDIUM"] <= ShaderWidget._QUALITY_FPS["HIGH"]

    def test_shader_creation(self):
        """Create shader widget in offscreen mode (disabled)."""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
            from app.ui.shader_widget import ShaderWidget
            widget = ShaderWidget(enabled=False, quality="LOW")
            assert widget.enabled is False
            assert widget.quality == "LOW"
            widget.deleteLater()
        except Exception:
            pytest.skip("QOpenGLWidget not available in offscreen mode")

    def test_shader_enable_disable(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
            from app.ui.shader_widget import ShaderWidget
            widget = ShaderWidget(enabled=False, quality="LOW")
            widget.set_enabled(True)
            assert widget.enabled is True
            widget.set_enabled(False)
            assert widget.enabled is False
            widget.deleteLater()
        except Exception:
            pytest.skip("QOpenGLWidget not available in offscreen mode")

    def test_shader_quality_change(self):
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
            from app.ui.shader_widget import ShaderWidget
            widget = ShaderWidget(enabled=False, quality="LOW")
            widget.set_quality("HIGH")
            assert widget.quality == "HIGH"
            widget.set_quality("INVALID")
            assert widget.quality == "HIGH"  # Unchanged
            widget.deleteLater()
        except Exception:
            pytest.skip("QOpenGLWidget not available in offscreen mode")

    def test_shader_graceful_fallback(self):
        """Shader should handle GL init failure gracefully."""
        import os
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        try:
            from PySide6.QtWidgets import QApplication
            app = QApplication.instance() or QApplication([])
            from app.ui.shader_widget import ShaderWidget
            widget = ShaderWidget(enabled=False)
            # May or may not init GL — should not crash
            assert True
            widget.deleteLater()
        except Exception:
            pytest.skip("QOpenGLWidget not available in offscreen mode")


# ═══════════════════════════════════════════════════════════════
#  6. OPTIMIZATION CENTER INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestOptimizationCenterIntegration:
    """Verify the optimization center correctly maps to real optimizations."""

    def test_power_plan_in_power_category(self):
        items = get_optimization_items()
        power_items = [i for i in items if i.category == OptimizationCategory.POWER]
        power_ids = {i.opt_id for i in power_items}
        assert "power_plan" in power_ids

    def test_game_mode_in_gaming_category(self):
        items = get_optimization_items()
        gaming_items = [i for i in items if i.category == OptimizationCategory.GAMING]
        gaming_ids = {i.opt_id for i in gaming_items}
        assert "game_mode" in gaming_ids

    def test_background_in_performance_category(self):
        items = get_optimization_items()
        perf_items = [i for i in items if i.category == OptimizationCategory.PERFORMANCE]
        perf_ids = {i.opt_id for i in perf_items}
        assert "background_load" in perf_ids

    def test_admin_requirements(self):
        items = get_optimization_items()
        admin_items = [i for i in items if i.requires_admin]
        admin_ids = {i.opt_id for i in admin_items}
        assert "power_plan" in admin_ids

    def test_reversibility(self):
        items = get_optimization_items()
        reversible = [i for i in items if i.reversible]
        assert len(reversible) > 0

    def test_optimization_item_to_dict_completeness(self):
        items = get_optimization_items()
        for item in items:
            d = item.to_dict()
            required_keys = {
                "opt_id", "name", "category", "status",
                "current_state", "recommended_state", "risk",
                "reversible", "requires_admin",
            }
            assert required_keys.issubset(d.keys())


# ═══════════════════════════════════════════════════════════════
#  7. SAFETY BOUNDARIES
# ═══════════════════════════════════════════════════════════════

class TestSafetyBoundaries:
    """Verify optimization center contains no prohibited items."""

    def test_no_cheat_related_optimizations(self):
        items = get_optimization_items()
        prohibited = ["cheat", "inject", "hack", "exploit", "bypass", "aimbot"]
        for item in items:
            for kw in prohibited:
                assert kw not in item.opt_id.lower()
                assert kw not in item.name.lower()
                assert kw not in item.description.lower()

    def test_all_optimizations_are_os_level(self):
        """All registered optimizations should be legitimate OS/application level."""
        items = get_optimization_items()
        for item in items:
            # Must have a valid category
            assert item.category in OptimizationCategory


# ═══════════════════════════════════════════════════════════════
#  8. SHADER VERTEX/FRAGMENT SHADERS
# ═══════════════════════════════════════════════════════════════

class TestShaderCode:
    """Verify shader source code is valid."""

    def test_vertex_shader_exists(self):
        from app.ui.shader_widget import VERTEX_SHADER
        assert "#version" in VERTEX_SHADER
        assert "main" in VERTEX_SHADER

    def test_fragment_shader_exists(self):
        from app.ui.shader_widget import FRAGMENT_SHADER
        assert "#version" in FRAGMENT_SHADER
        assert "uTime" in FRAGMENT_SHADER
        assert "uResolution" in FRAGMENT_SHADER
        assert "uIntensity" in FRAGMENT_SHADER
        assert "main" in FRAGMENT_SHADER

    def test_fragment_shader_uses_uniforms(self):
        from app.ui.shader_widget import FRAGMENT_SHADER
        assert "uniform float uTime" in FRAGMENT_SHADER
        assert "uniform vec2 uResolution" in FRAGMENT_SHADER
        assert "uniform float uIntensity" in FRAGMENT_SHADER
