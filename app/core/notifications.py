"""
Phase 58 — Intelligent Notification System.

Heaven Society notifies the user only when something meaningful happens.

Notification levels:
  INFO          — neutral information
  RECOMMENDATION — actionable suggestion
  WARNING       — requires attention
  CRITICAL      — immediate action needed

Rules:
  - No notification spam
  - Cooldown per category
  - Duplicate suppression
  - Severity escalation (don't downgrade active warnings)
  - User-configurable categories via SettingsManager
  - Never steal focus from games
  - No aggressive popups during gameplay
"""

import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Tuple

from app.utils.logger import get_logger

logger = get_logger("core.notifications")


# ── Enums ────────────────────────────────────────────────────────


class NotificationLevel(Enum):
    """Notification severity levels."""
    INFO = "INFO"
    RECOMMENDATION = "RECOMMENDATION"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class NotificationCategory(Enum):
    """Notification categories for filtering and cooldown."""
    SYSTEM = "SYSTEM"
    GAMING = "GAMING"
    OPTIMIZATION = "OPTIMIZATION"
    THERMAL = "THERMAL"
    MEMORY = "MEMORY"
    DISK = "DISK"
    CLEANUP = "CLEANUP"
    PERFORMANCE = "PERFORMANCE"
    INPUT = "INPUT"
    SESSION = "SESSION"


class NotificationStatus(Enum):
    """Current status of a notification."""
    ACTIVE = "ACTIVE"
    DISMISSED = "DISMISSED"
    SUPERSEDED = "SUPERSEDED"
    EXPIRED = "EXPIRED"


# ── Data Models ────────────────────────────────────────────────────


@dataclass
class Notification:
    """A single notification."""
    id: str = ""
    timestamp: float = 0.0
    level: NotificationLevel = NotificationLevel.INFO
    category: NotificationCategory = NotificationCategory.SYSTEM
    title: str = ""
    message: str = ""
    status: NotificationStatus = NotificationStatus.ACTIVE

    # Metadata
    source: str = ""  # which module created this
    data: Dict = field(default_factory=dict)  # optional structured data
    expires_at: float = 0.0  # 0 = never expires
    priority: int = 0  # higher = more important

    def __post_init__(self):
        if not self.id:
            self.id = f"notif_{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def is_active(self) -> bool:
        return self.status == NotificationStatus.ACTIVE

    @property
    def is_expired(self) -> bool:
        if self.expires_at <= 0:
            return False
        return time.time() > self.expires_at

    @property
    def age_seconds(self) -> float:
        return time.time() - self.timestamp

    @property
    def level_icon(self) -> str:
        icons = {
            NotificationLevel.INFO: "i",
            NotificationLevel.RECOMMENDATION: "*",
            NotificationLevel.WARNING: "!",
            NotificationLevel.CRITICAL: "!!",
        }
        return icons.get(self.level, " ")

    @property
    def level_color(self) -> str:
        colors = {
            NotificationLevel.INFO: "#4CAF50",
            NotificationLevel.RECOMMENDATION: "#2196F3",
            NotificationLevel.WARNING: "#FF9800",
            NotificationLevel.CRITICAL: "#F44336",
        }
        return colors.get(self.level, "#9E9E9E")

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "timestamp": self.timestamp,
            "level": self.level.value,
            "category": self.category.value,
            "title": self.title,
            "message": self.message,
            "status": self.status.value,
            "source": self.source,
            "data": self.data,
            "expires_at": self.expires_at,
            "priority": self.priority,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Notification":
        level = NotificationLevel(data.get("level", "INFO"))
        cat = NotificationCategory(data.get("category", "SYSTEM"))
        status = NotificationStatus(data.get("status", "ACTIVE"))
        return cls(
            id=data.get("id", ""),
            timestamp=data.get("timestamp", 0.0),
            level=level,
            category=cat,
            title=data.get("title", ""),
            message=data.get("message", ""),
            status=status,
            source=data.get("source", ""),
            data=data.get("data", {}),
            expires_at=data.get("expires_at", 0.0),
            priority=data.get("priority", 0),
        )


@dataclass
class NotificationSummary:
    """Summary of notification state."""
    total_active: int = 0
    total_dismissed: int = 0
    total_all_time: int = 0
    by_level: Dict[str, int] = field(default_factory=dict)
    by_category: Dict[str, int] = field(default_factory=dict)
    last_notification_time: float = 0.0
    suppressed_count: int = 0


# ══════════════════════════════════════════════════════════════════
# Notification Manager
# ══════════════════════════════════════════════════════════════════


class NotificationManager:
    """
    Intelligent notification manager with cooldown, dedup, and escalation.

    Never steals focus from games.
    No aggressive popups during gameplay.
    """

    # Default cooldowns per category (seconds)
    DEFAULT_COOLDOWNS = {
        NotificationCategory.SYSTEM: 300,
        NotificationCategory.GAMING: 60,
        NotificationCategory.OPTIMIZATION: 300,
        NotificationCategory.THERMAL: 120,
        NotificationCategory.MEMORY: 180,
        NotificationCategory.DISK: 600,
        NotificationCategory.CLEANUP: 1800,
        NotificationCategory.PERFORMANCE: 300,
        NotificationCategory.INPUT: 300,
        NotificationCategory.SESSION: 60,
    }

    # Duplicate suppression window (seconds)
    DEDUP_WINDOW = 300

    # Max active notifications
    MAX_ACTIVE = 20

    # Max history to keep
    MAX_HISTORY = 200

    def __init__(self):
        self._notifications: List[Notification] = []
        self._last_fired: Dict[str, float] = {}  # category -> timestamp
        self._last_message: Dict[str, float] = {}  # message hash -> timestamp
        self._listeners: List[Callable] = []
        self._game_mode_active: bool = False

    @property
    def game_mode_active(self) -> bool:
        return self._game_mode_active

    @game_mode_active.setter
    def game_mode_active(self, value: bool):
        self._game_mode_active = value

    # ── Core API ─────────────────────────────────────────────

    def notify(
        self,
        title: str,
        message: str = "",
        level: NotificationLevel = NotificationLevel.INFO,
        category: NotificationCategory = NotificationCategory.SYSTEM,
        source: str = "",
        data: Optional[Dict] = None,
        priority: int = 0,
        force: bool = False,
    ) -> Optional[Notification]:
        """
        Send a notification.

        Returns the Notification if sent, None if suppressed.
        """
        # Check if notifications are enabled
        if not self._is_enabled():
            return None

        # Check category-specific settings
        if not self._is_category_enabled(category):
            return None

        # Cooldown check
        if not force and not self._check_cooldown(category):
            return None

        # Duplicate suppression
        if not force and self._is_duplicate(title, message):
            return None

        # Create notification
        notif = Notification(
            level=level,
            category=category,
            title=title,
            message=message,
            source=source,
            data=data or {},
            priority=priority,
        )

        # During gameplay: only allow WARNING/CRITICAL, suppress INFO
        if self._game_mode_active and level == NotificationLevel.INFO:
            return None

        # Supersede lower-priority active notifications
        self._supersede(notif)

        # Add to history
        self._notifications.append(notif)

        # Trim history
        if len(self._notifications) > self.MAX_HISTORY:
            self._notifications = self._notifications[-self.MAX_HISTORY:]

        # Record cooldown
        self._last_fired[category.value] = time.time()
        self._last_message[self._message_key(title, message)] = time.time()

        # Notify listeners
        self._emit(notif)

        logger.debug(f"Notification: [{level.value}] {title}")
        return notif

    def info(
        self, title: str, message: str = "",
        category: NotificationCategory = NotificationCategory.SYSTEM,
        **kwargs,
    ) -> Optional[Notification]:
        """Send an INFO notification."""
        return self.notify(title, message, NotificationLevel.INFO, category, **kwargs)

    def recommend(
        self, title: str, message: str = "",
        category: NotificationCategory = NotificationCategory.OPTIMIZATION,
        **kwargs,
    ) -> Optional[Notification]:
        """Send a RECOMMENDATION notification."""
        return self.notify(title, message, NotificationLevel.RECOMMENDATION, category, **kwargs)

    def warn(
        self, title: str, message: str = "",
        category: NotificationCategory = NotificationCategory.SYSTEM,
        **kwargs,
    ) -> Optional[Notification]:
        """Send a WARNING notification."""
        return self.notify(title, message, NotificationLevel.WARNING, category, **kwargs)

    def critical(
        self, title: str, message: str = "",
        category: NotificationCategory = NotificationCategory.SYSTEM,
        **kwargs,
    ) -> Optional[Notification]:
        """Send a CRITICAL notification."""
        return self.notify(
            title, message, NotificationLevel.CRITICAL, category,
            force=True,  # Critical always goes through
            **kwargs,
        )

    # ── Query ────────────────────────────────────────────────

    def get_active(self) -> List[Notification]:
        """Get all active (non-dismissed, non-expired) notifications."""
        now = time.time()
        return [
            n for n in self._notifications
            if n.is_active and not n.is_expired
        ]

    def get_recent(self, limit: int = 20) -> List[Notification]:
        """Get recent notifications (newest first)."""
        return list(reversed(self._notifications[-limit:]))

    def get_by_level(self, level: NotificationLevel) -> List[Notification]:
        """Get active notifications by level."""
        return [n for n in self.get_active() if n.level == level]

    def get_by_category(self, category: NotificationCategory) -> List[Notification]:
        """Get active notifications by category."""
        return [n for n in self.get_active() if n.category == category]

    def get_summary(self) -> NotificationSummary:
        """Get a summary of notification state."""
        active = self.get_active()
        all_time = self._notifications
        summary = NotificationSummary(
            total_active=len(active),
            total_all_time=len(all_time),
        )

        for n in active:
            lv = n.level.value
            summary.by_level[lv] = summary.by_level.get(lv, 0) + 1
            cat = n.category.value
            summary.by_category[cat] = summary.by_category.get(cat, 0) + 1

        summary.total_dismissed = sum(
            1 for n in all_time if n.status == NotificationStatus.DISMISSED
        )

        if all_time:
            summary.last_notification_time = all_time[-1].timestamp

        return summary

    # ── Actions ──────────────────────────────────────────────

    def dismiss(self, notification_id: str) -> bool:
        """Dismiss a notification."""
        for n in self._notifications:
            if n.id == notification_id:
                n.status = NotificationStatus.DISMISSED
                return True
        return False

    def dismiss_all(self) -> int:
        """Dismiss all active notifications. Returns count dismissed."""
        count = 0
        for n in self._notifications:
            if n.is_active:
                n.status = NotificationStatus.DISMISSED
                count += 1
        return count

    def clear_history(self):
        """Clear all notification history."""
        self._notifications.clear()
        self._last_fired.clear()
        self._last_message.clear()

    # ── Listeners ────────────────────────────────────────────

    def on_notification(self, callback: Callable):
        """Register a listener for new notifications."""
        self._listeners.append(callback)

    def remove_listener(self, callback: Callable):
        """Remove a notification listener."""
        self._listeners = [l for l in self._listeners if l is not callback]

    # ── Formatting ───────────────────────────────────────────

    def format_active(self) -> str:
        """Format active notifications for CLI display."""
        active = self.get_active()
        if not active:
            return "No active notifications."

        lines = []
        lines.append("=" * 55)
        lines.append("  ACTIVE NOTIFICATIONS")
        lines.append("=" * 55)

        for n in active:
            age = int(n.age_seconds)
            if age < 60:
                age_str = f"{age}s ago"
            elif age < 3600:
                age_str = f"{age // 60}m ago"
            else:
                age_str = f"{age // 3600}h ago"

            lines.append(f"\n  [{n.level_icon}] {n.title}")
            if n.message:
                lines.append(f"    {n.message}")
            lines.append(f"    Category: {n.category.value}  |  {age_str}")

        lines.append("\n" + "=" * 55)
        return "\n".join(lines)

    def format_summary(self) -> str:
        """Format notification summary for CLI display."""
        summary = self.get_summary()
        lines = []
        lines.append("=" * 55)
        lines.append("  NOTIFICATION SYSTEM STATUS")
        lines.append("=" * 55)
        lines.append(f"\n  Active:         {summary.total_active}")
        lines.append(f"  Dismissed:      {summary.total_dismissed}")
        lines.append(f"  Total (all):    {summary.total_all_time}")
        lines.append(f"  Suppressed:     {summary.suppressed_count}")

        if summary.by_level:
            lines.append(f"\n  By Level:")
            for lv, count in sorted(summary.by_level.items()):
                lines.append(f"    {lv:<18} {count}")

        if summary.by_category:
            lines.append(f"\n  By Category:")
            for cat, count in sorted(summary.by_category.items()):
                lines.append(f"    {cat:<18} {count}")

        lines.append("\n" + "=" * 55)
        return "\n".join(lines)

    # ── Internal ─────────────────────────────────────────────

    def _is_enabled(self) -> bool:
        """Check if notifications are globally enabled."""
        try:
            from app.core.settings import settings
            return settings.get_bool("notifications.enabled", True)
        except Exception:
            return True

    def _is_category_enabled(self, category: NotificationCategory) -> bool:
        """Check if a specific category is enabled."""
        try:
            from app.core.settings import settings
            if category == NotificationCategory.THERMAL:
                return settings.get_bool("notifications.show_thermal_warnings", True)
            if category == NotificationCategory.DISK:
                return settings.get_bool("notifications.show_disk_warnings", True)
            if category == NotificationCategory.OPTIMIZATION:
                return settings.get_bool("notifications.show_optimization_results", True)
        except Exception:
            pass
        return True

    def _check_cooldown(self, category: NotificationCategory) -> bool:
        """Check if a category is on cooldown."""
        cooldown = self.DEFAULT_COOLDOWNS.get(category, 300)

        # Use custom cooldown from settings
        try:
            from app.core.settings import settings
            custom = settings.get_int("notifications.cooldown_seconds", 60)
            cooldown = max(custom, 10)  # minimum 10s
        except Exception:
            pass

        last = self._last_fired.get(category.value, 0)
        return (time.time() - last) >= cooldown

    def _is_duplicate(self, title: str, message: str) -> bool:
        """Check if this exact notification was recently sent."""
        key = self._message_key(title, message)
        last = self._last_message.get(key, 0)
        return (time.time() - last) < self.DEDUP_WINDOW

    def _supersede(self, new: Notification):
        """Supersede lower-priority active notifications of the same category."""
        for n in self._notifications:
            if (
                n.is_active
                and n.category == new.category
                and n.priority < new.priority
            ):
                n.status = NotificationStatus.SUPERSEDED

    def _emit(self, notification: Notification):
        """Emit notification to all listeners."""
        for listener in self._listeners:
            try:
                listener(notification)
            except Exception as e:
                logger.debug(f"Notification listener error: {e}")

    @staticmethod
    def _message_key(title: str, message: str) -> str:
        """Generate a dedup key from title and message."""
        return f"{title}|{message}".lower().strip()


# ── Singleton ────────────────────────────────────────────────────

notification_manager = NotificationManager()
