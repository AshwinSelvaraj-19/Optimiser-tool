"""
Phase 57 — Comprehensive tests for Production Settings.

Tests:
- SettingDefinition (create, validate, serialization)
- SettingsManager (get, set, reset, export, import, listeners)
- All 8 categories
- Type validation
- CLI commands
- Edge cases
"""
import os
import sys
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock
from app.core.settings import (
    SettingCategory,
    SettingType,
    SettingDefinition,
    SettingsManager,
    DEFAULT_SETTINGS,
    settings,
)


# ══════════════════════════════════════════════════════════════════
# 1. Enums
# ══════════════════════════════════════════════════════════════════

class TestEnums:
    def test_categories(self):
        assert SettingCategory.GENERAL.value == "GENERAL"
        assert SettingCategory.GAMING.value == "GAMING"
        assert SettingCategory.OPTIMIZATION.value == "OPTIMIZATION"
        assert SettingCategory.MONITORING.value == "MONITORING"
        assert SettingCategory.CLEANUP.value == "CLEANUP"
        assert SettingCategory.NOTIFICATIONS.value == "NOTIFICATIONS"
        assert SettingCategory.PRIVACY.value == "PRIVACY"
        assert SettingCategory.ADVANCED.value == "ADVANCED"

    def test_all_8_categories_present(self):
        assert len(SettingCategory) == 8

    def test_setting_types(self):
        assert SettingType.BOOL.value == "BOOL"
        assert SettingType.INT.value == "INT"
        assert SettingType.FLOAT.value == "FLOAT"
        assert SettingType.STRING.value == "STRING"
        assert SettingType.LIST.value == "LIST"


# ══════════════════════════════════════════════════════════════════
# 2. SettingDefinition
# ══════════════════════════════════════════════════════════════════

class TestSettingDefinition:
    def test_create(self):
        d = SettingDefinition(
            key="test.bool", name="Test", category=SettingCategory.GENERAL,
            setting_type=SettingType.BOOL, default_value=True,
        )
        assert d.key == "test.bool"
        assert d.default_value is True

    def test_validate_bool(self):
        d = SettingDefinition(setting_type=SettingType.BOOL)
        assert d.validate(True)[0] is True
        assert d.validate(False)[0] is True
        assert d.validate("yes")[0] is False

    def test_validate_int(self):
        d = SettingDefinition(setting_type=SettingType.INT, min_value=0, max_value=100)
        assert d.validate(50)[0] is True
        assert d.validate(-1)[0] is False
        assert d.validate(101)[0] is False
        assert d.validate("50")[0] is False

    def test_validate_float(self):
        d = SettingDefinition(setting_type=SettingType.FLOAT, min_value=0.0, max_value=1.0)
        assert d.validate(0.5)[0] is True
        assert d.validate(1.5)[0] is False

    def test_validate_string(self):
        d = SettingDefinition(
            setting_type=SettingType.STRING, options=["a", "b", "c"]
        )
        assert d.validate("a")[0] is True
        assert d.validate("d")[0] is False

    def test_validate_string_no_options(self):
        d = SettingDefinition(setting_type=SettingType.STRING)
        assert d.validate("anything")[0] is True

    def test_validate_list(self):
        d = SettingDefinition(setting_type=SettingType.LIST)
        assert d.validate([1, 2, 3])[0] is True
        assert d.validate("not a list")[0] is False

    def test_to_dict(self):
        d = SettingDefinition(
            key="test", name="Test", category=SettingCategory.GAMING,
            setting_type=SettingType.BOOL, default_value=True,
        )
        result = d.to_dict()
        assert result["key"] == "test"
        assert result["category"] == "GAMING"
        assert result["setting_type"] == "BOOL"

    def test_from_dict(self):
        d = SettingDefinition.from_dict({
            "key": "test", "name": "Test", "category": "MONITORING",
            "setting_type": "INT", "default_value": 5, "min_value": 1, "max_value": 10,
        })
        assert d.key == "test"
        assert d.category == SettingCategory.MONITORING
        assert d.min_value == 1


# ══════════════════════════════════════════════════════════════════
# 3. Default Settings
# ══════════════════════════════════════════════════════════════════

class TestDefaultSettings:
    def test_count(self):
        assert len(DEFAULT_SETTINGS) >= 30

    def test_all_categories_covered(self):
        cats = {s.category for s in DEFAULT_SETTINGS}
        for cat in SettingCategory:
            assert cat in cats

    def test_all_keys_unique(self):
        keys = [s.key for s in DEFAULT_SETTINGS]
        assert len(keys) == len(set(keys))

    def test_boolean_defaults(self):
        bools = [s for s in DEFAULT_SETTINGS if s.setting_type == SettingType.BOOL]
        for s in bools:
            assert isinstance(s.default_value, bool)

    def test_int_defaults(self):
        ints = [s for s in DEFAULT_SETTINGS if s.setting_type == SettingType.INT]
        for s in ints:
            assert isinstance(s.default_value, int)

    def test_string_defaults(self):
        strings = [s for s in DEFAULT_SETTINGS if s.setting_type == SettingType.STRING]
        for s in strings:
            assert isinstance(s.default_value, str)


# ══════════════════════════════════════════════════════════════════
# 4. SettingsManager
# ══════════════════════════════════════════════════════════════════

class TestSettingsManager:
    @pytest.fixture
    def tmp_mgr(self, tmp_path):
        filepath = str(tmp_path / "settings.json")
        return SettingsManager(settings_file=filepath)

    def test_singleton_exists(self):
        assert isinstance(settings, SettingsManager)

    def test_get_default(self, tmp_mgr):
        assert tmp_mgr.get("general.always_on_top") is False
        assert tmp_mgr.get("general.panel_mode") is True
        assert tmp_mgr.get("nonexistent.key") is None

    def test_get_bool(self, tmp_mgr):
        assert tmp_mgr.get_bool("general.always_on_top") is False
        assert tmp_mgr.get_bool("nonexistent", default=True) is True

    def test_get_int(self, tmp_mgr):
        val = tmp_mgr.get_int("monitoring.telemetry_interval_ms")
        assert val == 2000

    def test_get_string(self, tmp_mgr):
        val = tmp_mgr.get_string("general.theme")
        assert val == "dark"

    def test_get_list(self, tmp_mgr):
        val = tmp_mgr.get_list("advanced.excluded_processes")
        assert isinstance(val, list)

    def test_set_bool(self, tmp_mgr):
        success, msg = tmp_mgr.set("general.always_on_top", True)
        assert success is True
        assert tmp_mgr.get_bool("general.always_on_top") is True

    def test_set_int(self, tmp_mgr):
        success, _ = tmp_mgr.set("monitoring.telemetry_interval_ms", 5000)
        assert success is True
        assert tmp_mgr.get_int("monitoring.telemetry_interval_ms") == 5000

    def test_set_invalid_type(self, tmp_mgr):
        success, msg = tmp_mgr.set("general.always_on_top", "not_bool")
        assert success is False

    def test_set_out_of_range(self, tmp_mgr):
        success, msg = tmp_mgr.set("monitoring.telemetry_interval_ms", 99999)
        assert success is False

    def test_set_unknown_key(self, tmp_mgr):
        success, msg = tmp_mgr.set("nonexistent.key", "value")
        assert success is False

    def test_set_many(self, tmp_mgr):
        results = tmp_mgr.set_many({
            "general.always_on_top": True,
            "general.theme": "light",
        })
        assert results["general.always_on_top"][0] is True
        assert results["general.theme"][0] is True

    def test_reset_specific(self, tmp_mgr):
        tmp_mgr.set("general.always_on_top", True)
        tmp_mgr.reset("general.always_on_top")
        assert tmp_mgr.get_bool("general.always_on_top") is False

    def test_reset_all(self, tmp_mgr):
        tmp_mgr.set("general.always_on_top", True)
        tmp_mgr.set("general.theme", "light")
        tmp_mgr.reset()
        assert tmp_mgr.get_bool("general.always_on_top") is False
        assert tmp_mgr.get_string("general.theme") == "dark"

    def test_reset_category(self, tmp_mgr):
        tmp_mgr.set("general.always_on_top", True)
        tmp_mgr.set("general.theme", "light")
        count = tmp_mgr.reset_category(SettingCategory.GENERAL)
        assert count >= 2
        assert tmp_mgr.get_bool("general.always_on_top") is False

    def test_list_settings(self, tmp_mgr):
        all_settings = tmp_mgr.list_settings()
        assert len(all_settings) >= 30

    def test_list_settings_by_category(self, tmp_mgr):
        gaming = tmp_mgr.list_settings(category=SettingCategory.GAMING)
        for s in gaming:
            assert s.category == SettingCategory.GAMING

    def test_get_categories(self, tmp_mgr):
        cats = tmp_mgr.get_categories()
        assert len(cats) == 8

    def test_export_import(self, tmp_mgr):
        tmp_mgr.set("general.always_on_top", True)
        data = tmp_mgr.export_settings()
        assert data["settings"]["general.always_on_top"] is True

        tmp_mgr2 = SettingsManager(settings_file=str(tmp_mgr._file + ".2"))
        imported, failed = tmp_mgr2.import_settings(data)
        assert imported >= 1

    def test_persistence(self, tmp_path):
        filepath = str(tmp_path / "settings.json")
        m1 = SettingsManager(settings_file=filepath)
        m1.set("general.always_on_top", True)

        m2 = SettingsManager(settings_file=filepath)
        assert m2.get_bool("general.always_on_top") is True

    def test_listener(self, tmp_mgr):
        callback = MagicMock()
        tmp_mgr.on_change("general.always_on_top", callback)
        tmp_mgr.set("general.always_on_top", True)
        callback.assert_called_once()

    def test_listener_error_handling(self, tmp_mgr):
        def bad_callback(key, old, new):
            raise RuntimeError("test")

        tmp_mgr.on_change("general.always_on_top", bad_callback)
        # Should not raise
        tmp_mgr.set("general.always_on_top", True)

    def test_format_category(self, tmp_mgr):
        output = tmp_mgr.format_category(SettingCategory.GENERAL)
        assert "GENERAL" in output
        assert "Panel Mode" in output

    def test_format_all(self, tmp_mgr):
        output = tmp_mgr.format_all()
        assert "SETTINGS" in output
        assert "GENERAL" in output
        assert "GAMING" in output

    def test_export_to_file(self, tmp_mgr, tmp_path):
        filepath = str(tmp_path / "export.json")
        result = tmp_mgr.export_to_file(filepath)
        assert result is True
        assert os.path.exists(filepath)

    def test_import_from_file(self, tmp_mgr, tmp_path):
        filepath = str(tmp_path / "import.json")
        data = {"settings": {"general.always_on_top": True}}
        with open(filepath, "w") as f:
            json.dump(data, f)
        imported, failed = tmp_mgr.import_from_file(filepath)
        assert imported >= 1


# ══════════════════════════════════════════════════════════════════
# 5. Category Coverage
# ══════════════════════════════════════════════════════════════════

class TestCategoryCoverage:
    def test_general_settings(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.get("general.panel_mode") is True
        assert mgr.get("general.always_on_top") is False
        assert mgr.get("general.start_minimized") is False
        assert mgr.get("general.start_with_windows") is False

    def test_gaming_settings(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.get("gaming.auto_detect") is True
        assert mgr.get("gaming.detection_interval_seconds") == 5

    def test_optimization_settings(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.get("optimization.default_profile") == "gaming"
        assert mgr.get("optimization.confirm_before_apply") is True

    def test_monitoring_settings(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.get("monitoring.telemetry_interval_ms") == 2000
        assert mgr.get("monitoring.enable_fps_tracking") is True

    def test_cleanup_settings(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.get("cleanup.auto_recommend") is True
        assert mgr.get("cleanup.min_age_days") == 7

    def test_notification_settings(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.get("notifications.enabled") is True
        assert mgr.get("notifications.cooldown_seconds") == 60

    def test_privacy_settings(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.get("privacy.collect_telemetry") is False
        assert mgr.get("privacy.store_session_history") is True

    def test_advanced_settings(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.get("advanced.restore_behavior") == "auto_rollback"
        assert mgr.get("advanced.max_undo_history") == 20


# ══════════════════════════════════════════════════════════════════
# 6. CLI Integration
# ══════════════════════════════════════════════════════════════════

class TestCLIIntegration:
    def test_settings_list(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--settings-list"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "SETTINGS" in result.stdout
        assert "GENERAL" in result.stdout

    def test_settings_show_category(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--settings-show", "--category", "GAMING"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "GAMING" in result.stdout

    def test_settings_set(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--settings-set",
             "--key", "general.always_on_top", "--value", "true"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "OK" in result.stdout

    def test_settings_reset(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--settings-reset"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "reset" in result.stdout.lower()


# ══════════════════════════════════════════════════════════════════
# 7. Edge Cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_get_nonexistent(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.get("nonexistent") is None
        assert mgr.get("nonexistent", default=42) == 42

    def test_set_then_get(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        mgr.set("general.always_on_top", True)
        assert mgr.get("general.always_on_top") is True

    def test_reset_nonexistent(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        assert mgr.reset("nonexistent.key") is False

    def test_import_invalid_file(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        imported, failed = mgr.import_from_file(str(tmp_path / "nonexistent.json"))
        assert imported == 0

    def test_export_empty(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        data = mgr.export_settings()
        assert "settings" in data
        assert "version" in data

    def test_requires_restart_flag(self):
        defn = next(s for s in DEFAULT_SETTINGS if s.requires_restart)
        assert defn.requires_restart is True

    def test_options_enforced(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        success, _ = mgr.set("general.theme", "invalid_theme")
        assert success is False

    def test_list_items_setting(self, tmp_path):
        mgr = SettingsManager(settings_file=str(tmp_path / "s.json"))
        success, _ = mgr.set("advanced.excluded_processes", ["chrome.exe", "discord.exe"])
        assert success is True
        val = mgr.get_list("advanced.excluded_processes")
        assert len(val) == 2
