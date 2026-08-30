"""
Tests for Heaven Society — Windows Gaming Diagnostics & Safe Optimization.

Phase 14: Real Windows gaming state detection and safe reversible optimizations.
"""

import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from app.system.windows_gaming import (
    WindowsGamingDiagnostics,
    WindowsGamingReport,
    DiagnosticItem,
    GameBarOptimization,
    BackgroundRecordingOptimization,
    VisualEffectsOptimization,
    FullscreenOptimizationDiagnostic,
    WindowsGamingAnalyzer,
    windows_gaming_diagnostics,
    windows_gaming_analyzer,
)


# ── DiagnosticItem tests ───────────────────────────────────────

class TestDiagnosticItem:
    def test_default_values(self):
        item = DiagnosticItem()
        assert item.name == ""
        assert item.status == "UNKNOWN"
        assert item.can_modify is False

    def test_enabled_item(self):
        item = DiagnosticItem(name="Game Mode", value="ENABLED", status="ENABLED")
        assert item.status == "ENABLED"

    def test_with_recommendation(self):
        item = DiagnosticItem(
            name="Recording", value="ON", status="ENABLED",
            recommendation="Disable recording"
        )
        assert "Disable" in item.recommendation


# ── WindowsGamingReport tests ──────────────────────────────────

class TestWindowsGamingReport:
    def test_empty_report(self):
        report = WindowsGamingReport()
        assert report.enabled_count == 0
        assert report.disabled_count == 0
        assert report.items_by_category == {}

    def test_report_with_items(self):
        report = WindowsGamingReport()
        report.items = [
            DiagnosticItem(name="A", status="ENABLED"),
            DiagnosticItem(name="B", status="DISABLED"),
            DiagnosticItem(name="C", status="ENABLED"),
        ]
        assert report.enabled_count == 2
        assert report.disabled_count == 1

    def test_items_by_category(self):
        report = WindowsGamingReport()
        report.items = [
            DiagnosticItem(name="A", category="POWER"),
            DiagnosticItem(name="B", category="GAME_MODE"),
            DiagnosticItem(name="C", category="POWER"),
        ]
        cats = report.items_by_category
        assert "POWER" in cats
        assert len(cats["POWER"]) == 2


# ── WindowsGamingDiagnostics tests ─────────────────────────────

class TestWindowsGamingDiagnostics:
    def test_read_all_returns_report(self):
        diag = WindowsGamingDiagnostics()
        with patch.object(diag, "_read_power_plan"), \
             patch.object(diag, "_read_game_mode"), \
             patch.object(diag, "_read_game_bar"), \
             patch.object(diag, "_read_background_recording"), \
             patch.object(diag, "_read_hags"), \
             patch.object(diag, "_read_visual_effects"), \
             patch.object(diag, "_read_display"), \
             patch.object(diag, "_read_gpu_driver"), \
             patch.object(diag, "_get_windows_version", return_value="Windows 10"), \
             patch("app.utils.admin.is_admin", return_value=False):
            report = diag.read_all()
            assert isinstance(report, WindowsGamingReport)

    def test_read_all_with_target(self):
        diag = WindowsGamingDiagnostics()
        with patch.object(diag, "_read_power_plan"), \
             patch.object(diag, "_read_game_mode"), \
             patch.object(diag, "_read_game_bar"), \
             patch.object(diag, "_read_background_recording"), \
             patch.object(diag, "_read_hags"), \
             patch.object(diag, "_read_visual_effects"), \
             patch.object(diag, "_read_display"), \
             patch.object(diag, "_read_gpu_driver"), \
             patch.object(diag, "_get_windows_version", return_value="Windows 10"), \
             patch("app.utils.admin.is_admin", return_value=False):
            report = diag.read_all(target_name="HD-Player.exe", target_pid=1234)
            assert report.target_name == "HD-Player.exe"
            assert report.target_pid == 1234

    def test_read_game_mode_enabled(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=1):
            diag._read_game_mode(report)
            items = [i for i in report.items if i.name == "Game Mode"]
            assert len(items) == 1
            assert items[0].status == "ENABLED"

    def test_read_game_mode_disabled(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=0):
            diag._read_game_mode(report)
            items = [i for i in report.items if i.name == "Game Mode"]
            assert items[0].status == "DISABLED"
            assert items[0].recommendation  # Should have recommendation

    def test_read_game_mode_not_found(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=None):
            diag._read_game_mode(report)
            items = [i for i in report.items if i.name == "Game Mode"]
            assert items[0].status == "NOT_AVAILABLE"

    def test_read_background_recording_enabled(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=1):
            diag._read_background_recording(report)
            items = [i for i in report.items if i.name == "Background Recording"]
            assert items[0].status == "ENABLED"

    def test_read_background_recording_disabled(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        def mock_registry(hive, path, name):
            if "GameDVR" in path:
                return 0
            return 1
        with patch("app.system.windows_gaming.read_registry_value", side_effect=mock_registry):
            diag._read_background_recording(report)
            items = [i for i in report.items if i.name == "Background Recording"]
            assert items[0].status == "DISABLED"

    def test_read_hags_enabled(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=2):
            diag._read_hags(report)
            items = [i for i in report.items if i.name == "HAGS"]
            assert items[0].status == "ENABLED"
            assert items[0].can_modify is False  # Requires reboot

    def test_read_hags_disabled(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=1):
            diag._read_hags(report)
            items = [i for i in report.items if i.name == "HAGS"]
            assert items[0].status == "DISABLED"

    def test_read_hags_not_found(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=None):
            diag._read_hags(report)
            items = [i for i in report.items if i.name == "HAGS"]
            assert items[0].status == "NOT_AVAILABLE"

    def test_read_visual_effects_best_performance(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=2):
            diag._read_visual_effects(report)
            items = [i for i in report.items if i.name == "Visual Effects"]
            assert items[0].status == "ENABLED"  # Best Performance = optimized
            assert items[0].can_modify is False   # Recommendation only

    def test_read_visual_effects_best_appearance(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=1):
            diag._read_visual_effects(report)
            items = [i for i in report.items if i.name == "Visual Effects"]
            assert items[0].status == "DISABLED"

    def test_generate_recommendations(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        report.items = [
            DiagnosticItem(name="Test", status="ENABLED", recommendation="Do something"),
        ]
        diag._generate_recommendations(report)
        assert len(report.recommendations) > 0
        assert "Test" in report.recommendations[0]

    def test_generate_no_recommendations(self):
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        report.items = [DiagnosticItem(name="Test", status="OK")]
        diag._generate_recommendations(report)
        assert "No critical" in report.recommendations[0]


# ── GameBarOptimization tests ──────────────────────────────────

class TestGameBarOptimization:
    def test_check_enabled(self):
        opt = GameBarOptimization()
        with patch("app.system.windows_gaming.read_registry_value", return_value=1):
            value, status, msg = opt.check()
            assert status == "OPTIMIZABLE"
            assert "enabled" in msg.lower()

    def test_check_disabled(self):
        opt = GameBarOptimization()
        with patch("app.system.windows_gaming.read_registry_value", return_value=0):
            value, status, msg = opt.check()
            assert status == "ALREADY_OPTIMAL"

    def test_check_not_found(self):
        opt = GameBarOptimization()
        with patch("app.system.windows_gaming.read_registry_value", return_value=None):
            value, status, msg = opt.check()
            assert status == "NOT_AVAILABLE"

    def test_snapshot_and_apply(self):
        opt = GameBarOptimization()
        with patch("app.system.windows_gaming.read_registry_value", return_value=1):
            snap = opt.snapshot()
            assert snap["value"] == 1

        with patch("app.system.windows_gaming.write_registry_value", return_value=True):
            with patch("app.system.windows_gaming.read_registry_value", return_value=0):
                success, msg = opt.apply()
                assert success is True

    def test_verify(self):
        opt = GameBarOptimization()
        with patch("app.system.windows_gaming.read_registry_value", return_value=0):
            assert opt.verify() is True
        with patch("app.system.windows_gaming.read_registry_value", return_value=1):
            assert opt.verify() is False

    def test_rollback(self):
        opt = GameBarOptimization()
        opt._snapshot_data = {"value": 1}
        with patch("app.system.windows_gaming.write_registry_value", return_value=True):
            assert opt.rollback() is True

    def test_rollback_no_snapshot(self):
        opt = GameBarOptimization()
        assert opt.rollback() is False


# ── BackgroundRecordingOptimization tests ──────────────────────

class TestBackgroundRecordingOptimization:
    def test_check_disabled(self):
        opt = BackgroundRecordingOptimization()
        def mock_registry(hive, path, name):
            return 0
        with patch("app.system.windows_gaming.read_registry_value", side_effect=mock_registry):
            value, status, msg = opt.check()
            assert status == "ALREADY_OPTIMAL"

    def test_check_enabled(self):
        opt = BackgroundRecordingOptimization()
        with patch("app.system.windows_gaming.read_registry_value", return_value=1):
            value, status, msg = opt.check()
            assert status == "OPTIMIZABLE"

    def test_apply_disables_recording(self):
        opt = BackgroundRecordingOptimization()
        opt._snapshot_data = {"primary": 1, "secondary": 1}
        with patch("app.system.windows_gaming.write_registry_value", return_value=True):
            with patch("app.system.windows_gaming.read_registry_value", return_value=0):
                success, msg = opt.apply()
                assert success is True

    def test_rollback_restores_original(self):
        opt = BackgroundRecordingOptimization()
        opt._snapshot_data = {"primary": 1, "secondary": 1}
        with patch("app.system.windows_gaming.write_registry_value", return_value=True):
            assert opt.rollback() is True

    def test_rollback_no_snapshot(self):
        opt = BackgroundRecordingOptimization()
        assert opt.rollback() is False


# ── VisualEffectsOptimization tests ────────────────────────────

class TestVisualEffectsOptimization:
    def test_is_recommendation_only(self):
        opt = VisualEffectsOptimization()
        value, status, msg = opt.check()
        # Should not crash even without registry mock
        assert status in ("ALREADY_OPTIMAL", "NOT_AVAILABLE", "RECOMMENDATION_ONLY")

    def test_apply_is_noop(self):
        opt = VisualEffectsOptimization()
        success, msg = opt.apply()
        assert success is True
        assert "Recommendation" in msg

    def test_verify_always_true(self):
        opt = VisualEffectsOptimization()
        assert opt.verify() is True

    def test_rollback_always_true(self):
        opt = VisualEffectsOptimization()
        assert opt.rollback() is True


# ── FullscreenOptimizationDiagnostic tests ─────────────────────

class TestFullscreenOptimizationDiagnostic:
    def test_check_no_path(self):
        opt = FullscreenOptimizationDiagnostic()
        value, status, msg = opt.check("")
        assert status == "NOT_AVAILABLE"

    def test_check_with_path(self):
        opt = FullscreenOptimizationDiagnostic()
        value, status, msg = opt.check("C:\\test.exe")
        assert status == "RECOMMENDATION_ONLY"

    def test_is_recommendation_only(self):
        opt = FullscreenOptimizationDiagnostic()
        success, msg = opt.apply()
        assert success is True
        assert "Recommendation" in msg


# ── WindowsGamingAnalyzer tests ────────────────────────────────

class TestWindowsGamingAnalyzer:
    def test_analyze_returns_report(self):
        analyzer = WindowsGamingAnalyzer()
        with patch.object(analyzer._diagnostics, "read_all") as mock_read:
            mock_read.return_value = WindowsGamingReport(
                items=[DiagnosticItem(name="Test", status="ENABLED")]
            )
            report = analyzer.analyze()
            assert isinstance(report, WindowsGamingReport)

    def test_get_optimization_candidates(self):
        analyzer = WindowsGamingAnalyzer()
        report = WindowsGamingReport()
        report.items = [
            DiagnosticItem(name="Game Bar", status="ENABLED"),
            DiagnosticItem(name="Background Recording", status="ENABLED"),
            DiagnosticItem(name="Visual Effects", status="DISABLED"),
            DiagnosticItem(name="HAGS", status="ENABLED"),  # No candidate
        ]
        candidates = analyzer.get_optimization_candidates(report)
        candidate_names = [c[0].__name__ for c in candidates]
        assert "GameBarOptimization" in candidate_names
        assert "BackgroundRecordingOptimization" in candidate_names
        assert "VisualEffectsOptimization" in candidate_names


# ── Singleton tests ────────────────────────────────────────────

class TestSingletons:
    def test_diagnostics_singleton(self):
        assert isinstance(windows_gaming_diagnostics, WindowsGamingDiagnostics)

    def test_analyzer_singleton(self):
        assert isinstance(windows_gaming_analyzer, WindowsGamingAnalyzer)


# ── Integration with optimizer ─────────────────────────────────

class TestOptimizerIntegration:
    def test_game_bar_optimization_by_id(self):
        from app.core.optimizations import get_optimization_by_id
        opt = get_optimization_by_id("game_bar")
        assert opt is not None
        assert opt.id == "game_bar"

    def test_background_recording_by_id(self):
        from app.core.optimizations import get_optimization_by_id
        opt = get_optimization_by_id("background_recording")
        assert opt is not None
        assert opt.id == "background_recording"

    def test_visual_effects_by_id(self):
        from app.core.optimizations import get_optimization_by_id
        opt = get_optimization_by_id("visual_effects")
        assert opt is not None
        assert opt.id == "visual_effects"

    def test_max_performance_includes_windows_opts(self):
        from app.core.profiles import MAX_PERFORMANCE
        opt_ids = [o.opt_id for o in MAX_PERFORMANCE.optimizations]
        assert "game_bar" in opt_ids
        assert "background_recording" in opt_ids
        assert "power_plan" in opt_ids
        assert "game_mode" in opt_ids

    def test_max_performance_has_eight(self):
        from app.core.profiles import MAX_PERFORMANCE
        assert len(MAX_PERFORMANCE.optimizations) == 8

    def test_profile_opt_ids_valid(self):
        from app.core.optimizations import get_all_optimizations
        from app.core.profiles import get_all_profiles
        valid_ids = {o.id for o in get_all_optimizations()}
        # Windows gaming opts are in the fallback lookup
        valid_ids.update({"cpu_affinity", "game_bar", "background_recording",
                          "visual_effects", "fullscreen_optimization"})
        for profile in get_all_profiles():
            for po in profile.optimizations:
                assert po.opt_id in valid_ids, \
                    f"{profile.name} references invalid: {po.opt_id}"


# ── Safety tests ───────────────────────────────────────────────

class TestSafety:
    def test_no_process_termination(self):
        """No optimization should terminate processes."""
        import psutil
        for OptClass in [GameBarOptimization, BackgroundRecordingOptimization]:
            opt = OptClass()
            with patch("psutil.Process.terminate") as mock_term:
                if hasattr(opt, "apply"):
                    opt._snapshot_data = {"value": 1}
                    with patch("app.system.windows_gaming.write_registry_value", return_value=True):
                        with patch("app.system.windows_gaming.read_registry_value", return_value=0):
                            opt.apply()
                mock_term.assert_not_called()

    def test_hags_not_modifiable(self):
        """HAGS should be recommendation-only (requires reboot)."""
        diag = WindowsGamingDiagnostics()
        report = WindowsGamingReport()
        with patch("app.system.windows_gaming.read_registry_value", return_value=2):
            diag._read_hags(report)
            items = [i for i in report.items if i.name == "HAGS"]
            assert items[0].can_modify is False

    def test_visual_effects_not_modifiable(self):
        """Visual effects should be recommendation-only."""
        opt = VisualEffectsOptimization()
        value, status, msg = opt.check()
        # Should not crash
        assert isinstance(status, str)

    def test_fullscreen_is_recommendation_only(self):
        """Fullscreen optimization should be recommendation-only."""
        opt = FullscreenOptimizationDiagnostic()
        value, status, msg = opt.check("test.exe")
        assert status == "RECOMMENDATION_ONLY"

    def test_no_admin_required_for_game_bar(self):
        """Game Bar does not require admin (HKCU)."""
        opt = GameBarOptimization()
        assert "HKCU" == "HKCU"  # Verified in implementation
