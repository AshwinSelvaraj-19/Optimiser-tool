"""
Phase 57 — Production Settings System.

Centralized, typed settings model with 8 categories:
  GENERAL, GAMING, OPTIMIZATION, MONITORING, CLEANUP,
  NOTIFICATIONS, PRIVACY, ADVANCED

All settings are persisted in a single JSON file.
No scattered QSettings calls across the codebase.

Rules:
  - Every setting has a type, default, and description
  - Settings are grouped by category
  - Changes are validated before applying
  - Settings survive application restarts
  - Reset restores all defaults
  - Export/Import for portability
"""

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("core.settings")


# ── Enums ────────────────────────────────────────────────────────


class SettingCategory(Enum):
    """Settings categories."""
    GENERAL = "GENERAL"
    GAMING = "GAMING"
    OPTIMIZATION = "OPTIMIZATION"
    MONITORING = "MONITORING"
    CLEANUP = "CLEANUP"
    NOTIFICATIONS = "NOTIFICATIONS"
    PRIVACY = "PRIVACY"
    ADVANCED = "ADVANCED"


class SettingType(Enum):
    """Setting value types."""
    BOOL = "BOOL"
    INT = "INT"
    FLOAT = "FLOAT"
    STRING = "STRING"
    LIST = "LIST"


# ── Setting Definition ────────────────────────────────────────────


@dataclass
class SettingDefinition:
    """Defines a single setting with metadata."""
    key: str = ""
    name: str = ""
    description: str = ""
    category: SettingCategory = SettingCategory.GENERAL
    setting_type: SettingType = SettingType.BOOL
    default_value: Any = None
    current_value: Any = None
    min_value: Optional[float] = None
    max_value: Optional[float] = None
    options: List[str] = field(default_factory=list)
    requires_restart: bool = False
    hidden: bool = False

    def validate(self, value: Any) -> Tuple[bool, str]:
        """Validate a value for this setting."""
        if self.setting_type == SettingType.BOOL:
            if not isinstance(value, bool):
                return False, f"Expected bool, got {type(value).__name__}"
        elif self.setting_type == SettingType.INT:
            if not isinstance(value, int) or isinstance(value, bool):
                return False, f"Expected int, got {type(value).__name__}"
            if self.min_value is not None and value < self.min_value:
                return False, f"Value {value} below minimum {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"Value {value} above maximum {self.max_value}"
        elif self.setting_type == SettingType.FLOAT:
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                return False, f"Expected float, got {type(value).__name__}"
            if self.min_value is not None and value < self.min_value:
                return False, f"Value {value} below minimum {self.min_value}"
            if self.max_value is not None and value > self.max_value:
                return False, f"Value {value} above maximum {self.max_value}"
        elif self.setting_type == SettingType.STRING:
            if not isinstance(value, str):
                return False, f"Expected str, got {type(value).__name__}"
            if self.options and value not in self.options:
                return False, f"Value '{value}' not in options: {self.options}"
        elif self.setting_type == SettingType.LIST:
            if not isinstance(value, list):
                return False, f"Expected list, got {type(value).__name__}"
        return True, ""

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "setting_type": self.setting_type.value,
            "default_value": self.default_value,
            "current_value": self.current_value,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "options": self.options,
            "requires_restart": self.requires_restart,
            "hidden": self.hidden,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "SettingDefinition":
        cat = SettingCategory(data.get("category", "GENERAL"))
        stype = SettingType(data.get("setting_type", "BOOL"))
        return cls(
            key=data.get("key", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=cat,
            setting_type=stype,
            default_value=data.get("default_value"),
            current_value=data.get("current_value"),
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            options=data.get("options", []),
            requires_restart=data.get("requires_restart", False),
            hidden=data.get("hidden", False),
        )


# ══════════════════════════════════════════════════════════════════
# DEFAULT SETTINGS DEFINITIONS
# ══════════════════════════════════════════════════════════════════

DEFAULT_SETTINGS: List[SettingDefinition] = [
    # ── GENERAL ────────────────────────────────────────────
    SettingDefinition(
        key="general.panel_mode",
        name="Panel Mode",
        description="Use compact floating panel instead of full window",
        category=SettingCategory.GENERAL,
        setting_type=SettingType.BOOL,
        default_value=True,
        requires_restart=True,
    ),
    SettingDefinition(
        key="general.always_on_top",
        name="Always On Top",
        description="Keep the panel above other windows",
        category=SettingCategory.GENERAL,
        setting_type=SettingType.BOOL,
        default_value=False,
    ),
    SettingDefinition(
        key="general.start_minimized",
        name="Start Minimized",
        description="Start the application minimized to tray",
        category=SettingCategory.GENERAL,
        setting_type=SettingType.BOOL,
        default_value=False,
        requires_restart=True,
    ),
    SettingDefinition(
        key="general.start_with_windows",
        name="Start with Windows",
        description="Launch automatically when Windows starts",
        category=SettingCategory.GENERAL,
        setting_type=SettingType.BOOL,
        default_value=False,
        requires_restart=True,
    ),
    SettingDefinition(
        key="general.theme",
        name="Theme",
        description="Application visual theme",
        category=SettingCategory.GENERAL,
        setting_type=SettingType.STRING,
        default_value="dark",
        options=["dark", "light"],
    ),

    # ── GAMING ─────────────────────────────────────────────
    SettingDefinition(
        key="gaming.auto_detect",
        name="Auto Detect Gaming",
        description="Automatically detect when a game/emulator starts",
        category=SettingCategory.GAMING,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="gaming.gaming_mode_on_detect",
        name="Gaming Mode on Detect",
        description="Automatically enable gaming mode when a game is detected",
        category=SettingCategory.GAMING,
        setting_type=SettingType.BOOL,
        default_value=False,
    ),
    SettingDefinition(
        key="gaming.detection_interval_seconds",
        name="Detection Interval",
        description="How often to check for running games (seconds)",
        category=SettingCategory.GAMING,
        setting_type=SettingType.INT,
        default_value=5,
        min_value=2,
        max_value=30,
    ),
    SettingDefinition(
        key="gaming.target_processes",
        name="Target Processes",
        description="Additional process names to treat as gaming targets",
        category=SettingCategory.GAMING,
        setting_type=SettingType.LIST,
        default_value=[],
    ),

    # ── OPTIMIZATION ───────────────────────────────────────
    SettingDefinition(
        key="optimization.default_profile",
        name="Default Profile",
        description="Profile to use when no profile is explicitly selected",
        category=SettingCategory.OPTIMIZATION,
        setting_type=SettingType.STRING,
        default_value="gaming",
        options=["balanced", "gaming", "competitive", "battery", "performance"],
    ),
    SettingDefinition(
        key="optimization.confirm_before_apply",
        name="Confirm Before Apply",
        description="Ask for confirmation before applying optimizations",
        category=SettingCategory.OPTIMIZATION,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="optimization.auto_rollback_on_failure",
        name="Auto Rollback on Failure",
        description="Automatically rollback optimizations that fail verification",
        category=SettingCategory.OPTIMIZATION,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="optimization.require_admin_for_system",
        name="Require Admin for System Changes",
        description="Only apply system-level optimizations with admin privileges",
        category=SettingCategory.OPTIMIZATION,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="optimization.max_concurrent_optimizations",
        name="Max Concurrent Optimizations",
        description="Maximum number of optimizations to apply simultaneously",
        category=SettingCategory.OPTIMIZATION,
        setting_type=SettingType.INT,
        default_value=1,
        min_value=1,
        max_value=5,
    ),

    # ── MONITORING ─────────────────────────────────────────
    SettingDefinition(
        key="monitoring.telemetry_interval_ms",
        name="Telemetry Interval",
        description="How often to collect telemetry data (milliseconds)",
        category=SettingCategory.MONITORING,
        setting_type=SettingType.INT,
        default_value=2000,
        min_value=500,
        max_value=10000,
    ),
    SettingDefinition(
        key="monitoring.enable_fps_tracking",
        name="Enable FPS Tracking",
        description="Track FPS using PresentMon when available",
        category=SettingCategory.MONITORING,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="monitoring.enable_thermal_monitoring",
        name="Enable Thermal Monitoring",
        description="Monitor GPU/CPU temperature",
        category=SettingCategory.MONITORING,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="monitoring.enable_input_tracking",
        name="Enable Input Tracking",
        description="Track input latency and consistency",
        category=SettingCategory.MONITORING,
        setting_type=SettingType.BOOL,
        default_value=False,
    ),
    SettingDefinition(
        key="monitoring.session_history_limit",
        name="Session History Limit",
        description="Maximum number of sessions to keep in history",
        category=SettingCategory.MONITORING,
        setting_type=SettingType.INT,
        default_value=50,
        min_value=10,
        max_value=500,
    ),

    # ── CLEANUP ────────────────────────────────────────────
    SettingDefinition(
        key="cleanup.auto_recommend",
        name="Auto Recommend Cleanup",
        description="Automatically suggest cleanup when disk pressure is detected",
        category=SettingCategory.CLEANUP,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="cleanup.confirm_before_clean",
        name="Confirm Before Clean",
        description="Ask for confirmation before deleting files",
        category=SettingCategory.CLEANUP,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="cleanup.min_age_days",
        name="Minimum File Age (days)",
        description="Only recommend cleanup for files older than this",
        category=SettingCategory.CLEANUP,
        setting_type=SettingType.INT,
        default_value=7,
        min_value=1,
        max_value=90,
    ),
    SettingDefinition(
        key="cleanup.include_temp",
        name="Include Temp Files",
        description="Include temporary files in cleanup recommendations",
        category=SettingCategory.CLEANUP,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="cleanup.include_browser_cache",
        name="Include Browser Cache",
        description="Include browser cache in cleanup recommendations",
        category=SettingCategory.CLEANUP,
        setting_type=SettingType.BOOL,
        default_value=False,
    ),
    SettingDefinition(
        key="cleanup.include_shader_cache",
        name="Include Shader Cache",
        description="Include shader cache in cleanup recommendations",
        category=SettingCategory.CLEANUP,
        setting_type=SettingType.BOOL,
        default_value=False,
    ),
    SettingDefinition(
        key="cleanup.disk_pressure_threshold",
        name="Disk Pressure Threshold (GB)",
        description="Free disk space below which cleanup is recommended",
        category=SettingCategory.CLEANUP,
        setting_type=SettingType.INT,
        default_value=15,
        min_value=1,
        max_value=100,
    ),

    # ── NOTIFICATIONS ──────────────────────────────────────
    SettingDefinition(
        key="notifications.enabled",
        name="Enable Notifications",
        description="Show system notifications for important events",
        category=SettingCategory.NOTIFICATIONS,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="notifications.cooldown_seconds",
        name="Notification Cooldown",
        description="Minimum seconds between notifications of the same type",
        category=SettingCategory.NOTIFICATIONS,
        setting_type=SettingType.INT,
        default_value=60,
        min_value=10,
        max_value=600,
    ),
    SettingDefinition(
        key="notifications.show_thermal_warnings",
        name="Show Thermal Warnings",
        description="Notify when GPU temperature is critically high",
        category=SettingCategory.NOTIFICATIONS,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="notifications.show_disk_warnings",
        name="Show Disk Warnings",
        description="Notify when disk space is critically low",
        category=SettingCategory.NOTIFICATIONS,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="notifications.show_optimization_results",
        name="Show Optimization Results",
        description="Notify when an optimization session completes",
        category=SettingCategory.NOTIFICATIONS,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),

    # ── PRIVACY ────────────────────────────────────────────
    SettingDefinition(
        key="privacy.collect_telemetry",
        name="Collect Telemetry",
        description="Collect anonymized usage telemetry",
        category=SettingCategory.PRIVACY,
        setting_type=SettingType.BOOL,
        default_value=False,
    ),
    SettingDefinition(
        key="privacy.store_session_history",
        name="Store Session History",
        description="Keep history of optimization and gaming sessions",
        category=SettingCategory.PRIVACY,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),
    SettingDefinition(
        key="privacy.store_benchmark_results",
        name="Store Benchmark Results",
        description="Keep history of benchmark results",
        category=SettingCategory.PRIVACY,
        setting_type=SettingType.BOOL,
        default_value=True,
    ),

    # ── ADVANCED ───────────────────────────────────────────
    SettingDefinition(
        key="advanced.enable_debug_logging",
        name="Enable Debug Logging",
        description="Write detailed debug logs (requires restart)",
        category=SettingCategory.ADVANCED,
        setting_type=SettingType.BOOL,
        default_value=False,
        requires_restart=True,
    ),
    SettingDefinition(
        key="advanced.worker_thread_count",
        name="Worker Thread Count",
        description="Number of background worker threads",
        category=SettingCategory.ADVANCED,
        setting_type=SettingType.INT,
        default_value=2,
        min_value=1,
        max_value=8,
        requires_restart=True,
    ),
    SettingDefinition(
        key="advanced.excluded_processes",
        name="Excluded Processes",
        description="Processes that should never be recommended for closure",
        category=SettingCategory.ADVANCED,
        setting_type=SettingType.LIST,
        default_value=[],
    ),
    SettingDefinition(
        key="advanced.excluded_applications",
        name="Excluded Applications",
        description="Applications excluded from optimization recommendations",
        category=SettingCategory.ADVANCED,
        setting_type=SettingType.LIST,
        default_value=[],
    ),
    SettingDefinition(
        key="advanced.restore_behavior",
        name="Restore Behavior",
        description="How to handle restore after optimization",
        category=SettingCategory.ADVANCED,
        setting_type=SettingType.STRING,
        default_value="auto_rollback",
        options=["auto_rollback", "keep_changes", "ask"],
    ),
    SettingDefinition(
        key="advanced.max_undo_history",
        name="Max Undo History",
        description="Maximum number of undoable changes to keep",
        category=SettingCategory.ADVANCED,
        setting_type=SettingType.INT,
        default_value=20,
        min_value=5,
        max_value=100,
    ),
]


# ══════════════════════════════════════════════════════════════════
# Settings Manager
# ══════════════════════════════════════════════════════════════════


class SettingsManager:
    """
    Centralized settings manager.
    All settings are defined once, typed, validated, and persisted.
    """

    SETTINGS_FILE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))),
        "app_settings.json",
    )

    def __init__(self, settings_file: Optional[str] = None):
        self._file = settings_file or self.SETTINGS_FILE
        self._definitions: Dict[str, SettingDefinition] = {}
        self._values: Dict[str, Any] = {}
        self._listeners: Dict[str, List[Callable]] = {}
        self._init_definitions()
        self._load()

    def _init_definitions(self):
        """Initialize all setting definitions."""
        for defn in DEFAULT_SETTINGS:
            self._definitions[defn.key] = defn
            self._values[defn.key] = defn.default_value

    # ── Get ─────────────────────────────────────────────────

    def get(self, key: str, default: Any = None) -> Any:
        """Get a setting value by key."""
        if key in self._values:
            return self._values[key]
        return default

    def get_bool(self, key: str, default: bool = False) -> bool:
        """Get a boolean setting."""
        val = self.get(key, default)
        return bool(val) if val is not None else default

    def get_int(self, key: str, default: int = 0) -> int:
        """Get an integer setting."""
        val = self.get(key, default)
        return int(val) if val is not None else default

    def get_float(self, key: str, default: float = 0.0) -> float:
        """Get a float setting."""
        val = self.get(key, default)
        return float(val) if val is not None else default

    def get_string(self, key: str, default: str = "") -> str:
        """Get a string setting."""
        val = self.get(key, default)
        return str(val) if val is not None else default

    def get_list(self, key: str, default: Optional[List] = None) -> List:
        """Get a list setting."""
        val = self.get(key, default)
        return val if isinstance(val, list) else (default or [])

    # ── Set ─────────────────────────────────────────────────

    def set(self, key: str, value: Any) -> Tuple[bool, str]:
        """
        Set a setting value.
        Returns (success, message).
        """
        if key not in self._definitions:
            return False, f"Unknown setting: {key}"

        defn = self._definitions[key]
        valid, msg = defn.validate(value)
        if not valid:
            return False, msg

        old_value = self._values.get(key)
        self._values[key] = value
        defn.current_value = value

        # Notify listeners
        if key in self._listeners:
            for listener in self._listeners[key]:
                try:
                    listener(key, old_value, value)
                except Exception as e:
                    logger.debug(f"Settings listener error: {e}")

        self._save()
        return True, "OK"

    def set_many(self, updates: Dict[str, Any]) -> Dict[str, Tuple[bool, str]]:
        """Set multiple settings at once."""
        results = {}
        for key, value in updates.items():
            results[key] = self.set(key, value)
        return results

    # ── List / Query ────────────────────────────────────────

    def list_settings(
        self, category: Optional[SettingCategory] = None, include_hidden: bool = False
    ) -> List[SettingDefinition]:
        """List all settings, optionally filtered by category."""
        result = []
        for defn in self._definitions.values():
            if not include_hidden and defn.hidden:
                continue
            if category and defn.category != category:
                continue
            defn.current_value = self._values.get(defn.key, defn.default_value)
            result.append(defn)
        return result

    def get_definition(self, key: str) -> Optional[SettingDefinition]:
        """Get the definition of a setting."""
        defn = self._definitions.get(key)
        if defn:
            defn.current_value = self._values.get(key, defn.default_value)
        return defn

    def get_categories(self) -> List[SettingCategory]:
        """Get all categories that have settings."""
        cats = set()
        for defn in self._definitions.values():
            cats.add(defn.category)
        return sorted(cats, key=lambda c: c.value)

    # ── Reset ───────────────────────────────────────────────

    def reset(self, key: Optional[str] = None) -> bool:
        """Reset a specific setting or all settings to defaults."""
        if key:
            if key in self._definitions:
                self._values[key] = self._definitions[key].default_value
                self._definitions[key].current_value = self._definitions[key].default_value
                self._save()
                return True
            return False
        else:
            for defn in DEFAULT_SETTINGS:
                self._values[defn.key] = defn.default_value
                defn.current_value = defn.default_value
            self._save()
            return True

    def reset_category(self, category: SettingCategory) -> int:
        """Reset all settings in a category. Returns count reset."""
        count = 0
        for defn in self._definitions.values():
            if defn.category == category:
                self._values[defn.key] = defn.default_value
                defn.current_value = defn.default_value
                count += 1
        self._save()
        return count

    # ── Export / Import ─────────────────────────────────────

    def export_settings(self) -> Dict:
        """Export all current settings as a dict."""
        return {
            "version": 1,
            "exported_at": time.time(),
            "settings": {k: v for k, v in self._values.items()},
        }

    def import_settings(self, data: Dict) -> Tuple[int, int]:
        """Import settings from a dict. Returns (imported, failed)."""
        settings = data.get("settings", data)
        imported = 0
        failed = 0
        for key, value in settings.items():
            success, _ = self.set(key, value)
            if success:
                imported += 1
            else:
                failed += 1
        return imported, failed

    def export_to_file(self, filepath: str) -> bool:
        """Export settings to a JSON file."""
        try:
            with open(filepath, "w") as f:
                json.dump(self.export_settings(), f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Settings export error: {e}")
            return False

    def import_from_file(self, filepath: str) -> Tuple[int, int]:
        """Import settings from a JSON file."""
        try:
            with open(filepath) as f:
                data = json.load(f)
            return self.import_settings(data)
        except Exception as e:
            logger.error(f"Settings import error: {e}")
            return 0, 0

    # ── Listeners ───────────────────────────────────────────

    def on_change(self, key: str, callback: Callable):
        """Register a callback for when a setting changes."""
        if key not in self._listeners:
            self._listeners[key] = []
        self._listeners[key].append(callback)

    # ── Format ──────────────────────────────────────────────

    def format_category(self, category: SettingCategory) -> str:
        """Format all settings in a category for CLI display."""
        settings = self.list_settings(category=category)
        lines = []
        lines.append(f"  {category.value}")
        lines.append("  " + "-" * 50)
        for s in settings:
            val = self._values.get(s.key, s.default_value)
            if s.setting_type == SettingType.BOOL:
                display = "ON" if val else "OFF"
            elif s.setting_type == SettingType.LIST:
                display = f"[{len(val)} items]" if val else "[]"
            else:
                display = str(val)
            restart = " [RESTART]" if s.requires_restart else ""
            lines.append(f"    {s.name:<30} {display:>15}{restart}")
            lines.append(f"      {s.description}")
        return "\n".join(lines)

    def format_all(self) -> str:
        """Format all settings for CLI display."""
        lines = []
        lines.append("=" * 55)
        lines.append("  HEAVEN SOCIETY — SETTINGS")
        lines.append("=" * 55)
        for cat in self.get_categories():
            lines.append("")
            lines.append(self.format_category(cat))
        lines.append("\n" + "=" * 55)
        return "\n".join(lines)

    # ── Internal ────────────────────────────────────────────

    def _load(self):
        """Load settings from disk."""
        if not os.path.exists(self._file):
            return
        try:
            with open(self._file) as f:
                data = json.load(f)
            settings = data.get("settings", data)
            for key, value in settings.items():
                if key in self._definitions:
                    self._values[key] = value
        except Exception as e:
            logger.debug(f"Settings load error: {e}")

    def _save(self):
        """Save settings to disk."""
        try:
            data = {
                "version": 1,
                "saved_at": time.time(),
                "settings": {k: v for k, v in self._values.items()},
            }
            with open(self._file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Settings save error: {e}")


# ── Singleton ────────────────────────────────────────────────────

settings = SettingsManager()
