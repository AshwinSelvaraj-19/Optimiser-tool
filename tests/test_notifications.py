"""
Phase 58 — Comprehensive tests for Intelligent Notification System.

Tests:
- Notification (create, serialization, properties)
- NotificationManager (notify, cooldown, dedup, escalation, listeners)
- Game mode suppression
- Category filtering
- Dismiss, clear, summary
- CLI commands
- Edge cases
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
from app.core.notifications import (
    NotificationLevel,
    NotificationCategory,
    NotificationStatus,
    Notification,
    NotificationSummary,
    NotificationManager,
    notification_manager,
)


# ══════════════════════════════════════════════════════════════════
# 1. Enums
# ══════════════════════════════════════════════════════════════════

class TestEnums:
    def test_notification_levels(self):
        assert NotificationLevel.INFO.value == "INFO"
        assert NotificationLevel.RECOMMENDATION.value == "RECOMMENDATION"
        assert NotificationLevel.WARNING.value == "WARNING"
        assert NotificationLevel.CRITICAL.value == "CRITICAL"

    def test_categories(self):
        assert NotificationCategory.SYSTEM.value == "SYSTEM"
        assert NotificationCategory.GAMING.value == "GAMING"
        assert NotificationCategory.THERMAL.value == "THERMAL"
        assert NotificationCategory.CLEANUP.value == "CLEANUP"

    def test_status(self):
        assert NotificationStatus.ACTIVE.value == "ACTIVE"
        assert NotificationStatus.DISMISSED.value == "DISMISSED"


# ══════════════════════════════════════════════════════════════════
# 2. Notification
# ══════════════════════════════════════════════════════════════════

class TestNotification:
    def test_create(self):
        n = Notification(title="Test", message="Hello")
        assert n.id.startswith("notif_")
        assert n.level == NotificationLevel.INFO
        assert n.is_active is True

    def test_with_level(self):
        n = Notification(
            title="Warning", level=NotificationLevel.WARNING,
            category=NotificationCategory.THERMAL,
        )
        assert n.level == NotificationLevel.WARNING
        assert n.category == NotificationCategory.THERMAL

    def test_is_expired(self):
        n = Notification(title="Test", expires_at=time.time() - 1)
        assert n.is_expired is True

    def test_not_expired(self):
        n = Notification(title="Test", expires_at=time.time() + 3600)
        assert n.is_expired is False

    def test_no_expiry(self):
        n = Notification(title="Test", expires_at=0)
        assert n.is_expired is False

    def test_age_seconds(self):
        n = Notification(title="Test", timestamp=time.time() - 10)
        assert n.age_seconds >= 9

    def test_level_icon(self):
        assert Notification(level=NotificationLevel.INFO).level_icon == "i"
        assert Notification(level=NotificationLevel.WARNING).level_icon == "!"
        assert Notification(level=NotificationLevel.CRITICAL).level_icon == "!!"

    def test_level_color(self):
        assert Notification(level=NotificationLevel.CRITICAL).level_color == "#F44336"
        assert Notification(level=NotificationLevel.INFO).level_color == "#4CAF50"

    def test_to_dict(self):
        n = Notification(title="Test", message="Hello", level=NotificationLevel.WARNING)
        d = n.to_dict()
        assert d["title"] == "Test"
        assert d["level"] == "WARNING"
        assert d["message"] == "Hello"

    def test_from_dict(self):
        d = {
            "id": "notif_test",
            "title": "Test",
            "level": "CRITICAL",
            "category": "THERMAL",
            "status": "ACTIVE",
        }
        n = Notification.from_dict(d)
        assert n.id == "notif_test"
        assert n.level == NotificationLevel.CRITICAL
        assert n.category == NotificationCategory.THERMAL


# ══════════════════════════════════════════════════════════════════
# 3. NotificationManager
# ══════════════════════════════════════════════════════════════════

class TestNotificationManager:
    @pytest.fixture
    def mgr(self):
        """Create a fresh manager for each test."""
        m = NotificationManager()
        m._last_fired.clear()
        m._last_message.clear()
        m._notifications.clear()
        return m

    def test_singleton_exists(self):
        assert isinstance(notification_manager, NotificationManager)

    def test_notify_basic(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n = mgr.notify("Test", "Hello")
        assert n is not None
        assert n.title == "Test"
        assert n.is_active is True

    def test_notify_disabled(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=False):
            n = mgr.notify("Test", "Hello")
        assert n is None

    def test_cooldown_suppression(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n1 = mgr.notify("Test", level=NotificationLevel.INFO, category=NotificationCategory.SYSTEM)
            n2 = mgr.notify("Test 2", level=NotificationLevel.INFO, category=NotificationCategory.SYSTEM)
        # Second should be suppressed by cooldown
        assert n1 is not None
        assert n2 is None

    def test_cooldown_force(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n1 = mgr.notify("Test", category=NotificationCategory.SYSTEM)
            n2 = mgr.notify("Test 2", category=NotificationCategory.SYSTEM, force=True)
        assert n1 is not None
        assert n2 is not None

    def test_duplicate_suppression(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n1 = mgr.notify("Same Title", "Same Message", category=NotificationCategory.SYSTEM)
            n2 = mgr.notify("Same Title", "Same Message", category=NotificationCategory.GAMING)
        # Same title+message should be deduped regardless of category
        assert n1 is not None
        assert n2 is None

    def test_different_messages_not_deduped(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n1 = mgr.notify("Title 1", category=NotificationCategory.SYSTEM)
            # Different cooldown category
            n2 = mgr.notify("Title 2", category=NotificationCategory.GAMING)
        assert n1 is not None
        assert n2 is not None

    def test_game_mode_suppresses_info(self, mgr):
        mgr.game_mode_active = True
        with patch.object(mgr, "_is_enabled", return_value=True):
            n = mgr.notify("Test", level=NotificationLevel.INFO)
        assert n is None

    def test_game_mode_allows_warning(self, mgr):
        mgr.game_mode_active = True
        with patch.object(mgr, "_is_enabled", return_value=True):
            n = mgr.notify("Test", level=NotificationLevel.WARNING, force=True)
        assert n is not None

    def test_game_mode_allows_critical(self, mgr):
        mgr.game_mode_active = True
        with patch.object(mgr, "_is_enabled", return_value=True):
            n = mgr.notify("Test", level=NotificationLevel.CRITICAL, force=True)
        assert n is not None

    def test_shortcuts(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n_info = mgr.info("Info", category=NotificationCategory.GAMING)
            n_rec = mgr.recommend("Rec", category=NotificationCategory.THERMAL)
            n_warn = mgr.warn("Warn", category=NotificationCategory.MEMORY)
            n_crit = mgr.critical("Crit", category=NotificationCategory.CLEANUP)
        assert n_info.level == NotificationLevel.INFO
        assert n_rec.level == NotificationLevel.RECOMMENDATION
        assert n_warn.level == NotificationLevel.WARNING
        assert n_crit.level == NotificationLevel.CRITICAL

    def test_critical_always_goes_through(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n1 = mgr.critical("Crit 1")
            n2 = mgr.critical("Crit 2")
        assert n1 is not None
        assert n2 is not None

    def test_get_active(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            mgr.info("Test 1", category=NotificationCategory.GAMING)
            mgr.warn("Test 2", category=NotificationCategory.THERMAL)
        active = mgr.get_active()
        assert len(active) == 2

    def test_get_recent(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            for i in range(5):
                mgr.info(f"Test {i}", category=NotificationCategory.GAMING, force=True)
        recent = mgr.get_recent(limit=3)
        assert len(recent) == 3

    def test_get_by_level(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            mgr.info("Info 1", category=NotificationCategory.GAMING)
            mgr.warn("Warn 1", category=NotificationCategory.THERMAL)
        warnings = mgr.get_by_level(NotificationLevel.WARNING)
        assert len(warnings) == 1
        assert warnings[0].title == "Warn 1"

    def test_get_by_category(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            mgr.info("Info 1", category=NotificationCategory.GAMING)
            mgr.info("Info 2", category=NotificationCategory.THERMAL)
        gaming = mgr.get_by_category(NotificationCategory.GAMING)
        assert len(gaming) == 1

    def test_dismiss(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n = mgr.info("Test", category=NotificationCategory.GAMING)
        result = mgr.dismiss(n.id)
        assert result is True
        assert n.status == NotificationStatus.DISMISSED

    def test_dismiss_nonexistent(self, mgr):
        result = mgr.dismiss("nonexistent")
        assert result is False

    def test_dismiss_all(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            mgr.info("Test 1", category=NotificationCategory.GAMING)
            mgr.info("Test 2", category=NotificationCategory.THERMAL)
        count = mgr.dismiss_all()
        assert count == 2
        assert len(mgr.get_active()) == 0

    def test_clear_history(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            mgr.info("Test", category=NotificationCategory.GAMING)
        mgr.clear_history()
        assert len(mgr._notifications) == 0

    def test_listener(self, mgr):
        callback = MagicMock()
        mgr.on_notification(callback)
        with patch.object(mgr, "_is_enabled", return_value=True):
            mgr.info("Test", category=NotificationCategory.GAMING)
        callback.assert_called_once()

    def test_listener_error_handling(self, mgr):
        def bad_callback(n):
            raise RuntimeError("test")
        mgr.on_notification(bad_callback)
        with patch.object(mgr, "_is_enabled", return_value=True):
            # Should not raise
            mgr.info("Test", category=NotificationCategory.GAMING)

    def test_remove_listener(self, mgr):
        callback = MagicMock()
        mgr.on_notification(callback)
        mgr.remove_listener(callback)
        with patch.object(mgr, "_is_enabled", return_value=True):
            mgr.info("Test", category=NotificationCategory.GAMING)
        callback.assert_not_called()

    def test_summary(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            mgr.info("Test 1", category=NotificationCategory.GAMING)
            mgr.warn("Test 2", category=NotificationCategory.THERMAL)
        summary = mgr.get_summary()
        assert summary.total_active == 2
        assert summary.by_level.get("INFO", 0) == 1
        assert summary.by_level.get("WARNING", 0) == 1

    def test_format_active(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            mgr.info("Test", message="Hello", category=NotificationCategory.GAMING)
        output = mgr.format_active()
        assert "ACTIVE NOTIFICATIONS" in output
        assert "Test" in output

    def test_format_active_empty(self, mgr):
        output = mgr.format_active()
        assert "No active" in output

    def test_format_summary(self, mgr):
        output = mgr.format_summary()
        assert "NOTIFICATION SYSTEM STATUS" in output

    def test_supersede(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n1 = mgr.notify(
                "Low priority", level=NotificationLevel.INFO,
                category=NotificationCategory.THERMAL, priority=1, force=True,
            )
            n2 = mgr.notify(
                "High priority", level=NotificationLevel.WARNING,
                category=NotificationCategory.THERMAL, priority=5, force=True,
            )
        assert n1.status == NotificationStatus.SUPERSEDED
        assert n2.is_active

    def test_max_history(self, mgr):
        mgr.MAX_HISTORY = 5
        with patch.object(mgr, "_is_enabled", return_value=True):
            for i in range(10):
                mgr.notify(f"Test {i}", force=True)
        assert len(mgr._notifications) <= 5


# ══════════════════════════════════════════════════════════════════
# 4. CLI Integration
# ══════════════════════════════════════════════════════════════════

class TestCLIIntegration:
    def test_notifications_status(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--notifications-status"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "NOTIFICATION SYSTEM STATUS" in result.stdout

    def test_notifications_active(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--notifications-active"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0

    def test_notifications_test(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--notifications-test",
             "--level", "CRITICAL", "--message", "Test critical"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "Sent" in result.stdout

    def test_notifications_clear(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--notifications-clear"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "Dismissed" in result.stdout


# ══════════════════════════════════════════════════════════════════
# 5. Edge Cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    @pytest.fixture
    def mgr(self):
        m = NotificationManager()
        m._last_fired.clear()
        m._last_message.clear()
        m._notifications.clear()
        return m
    def test_empty_message(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n = mgr.notify("Title Only")
        assert n is not None
        assert n.message == ""

    def test_long_message(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n = mgr.notify("Title", "x" * 1000)
        assert n is not None

    def test_unicode_message(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n = mgr.notify("GPU温度警告", "温度已达到85°C")
        assert n is not None

    def test_notification_id_unique(self):
        n1 = Notification()
        n2 = Notification()
        assert n1.id != n2.id

    def test_dedup_case_insensitive(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n1 = mgr.notify("Test", "Hello", category=NotificationCategory.GAMING)
            n2 = mgr.notify("test", "hello", category=NotificationCategory.THERMAL)
        assert n1 is not None
        assert n2 is None

    def test_game_mode_toggle(self, mgr):
        mgr.game_mode_active = True
        with patch.object(mgr, "_is_enabled", return_value=True):
            n1 = mgr.info("Suppressed")
        assert n1 is None

        mgr.game_mode_active = False
        with patch.object(mgr, "_is_enabled", return_value=True):
            n2 = mgr.info("Allowed")
        assert n2 is not None

    def test_notification_data(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n = mgr.notify(
                "Test", data={"cpu": 95.0, "ram": 88.0},
                category=NotificationCategory.GAMING,
            )
        assert n.data["cpu"] == 95.0

    def test_priority_ordering(self, mgr):
        with patch.object(mgr, "_is_enabled", return_value=True):
            n1 = mgr.notify("Low", priority=1, category=NotificationCategory.GAMING, force=True)
            n2 = mgr.notify("High", priority=10, category=NotificationCategory.GAMING, force=True)
        assert n1.status == NotificationStatus.SUPERSEDED
        assert n2.is_active
