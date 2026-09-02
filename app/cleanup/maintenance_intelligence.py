"""
Maintenance Intelligence — determines whether cleanup is worthwhile.

Produces a deterministic recommendation based on measurable system state:
- reclaimable disk space
- disk free-space percentage
- age since previous maintenance
- accumulated cleanup candidates
- storage pressure

Centralized thresholds in MaintenancePolicy.
Persistent history in lightweight JSON file.
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional

from app.utils.logger import get_logger

logger = get_logger("cleanup.maintenance_intelligence")


# ── Status Model ────────────────────────────────────────────────

class MaintenanceStatus(Enum):
    """Deterministic maintenance recommendation status."""
    RECOMMENDED_NOW = "RECOMMENDED_NOW"
    RECOMMENDED_SOON = "RECOMMENDED_SOON"
    NOT_NEEDED = "NOT_NEEDED"


# ── Centralized Policy ──────────────────────────────────────────

@dataclass
class MaintenancePolicy:
    """Centralized thresholds for maintenance recommendations.
    
    All magic numbers live here instead of scattered across UI code.
    """
    # Reclaimable space thresholds (bytes)
    recommend_now_bytes: int = 500 * 1024 * 1024       # 500 MB
    recommend_soon_bytes: int = 100 * 1024 * 1024       # 100 MB

    # Disk free-space thresholds (GB)
    critical_free_gb: float = 5.0
    high_free_gb: float = 15.0
    elevated_free_gb: float = 30.0

    # Maintenance interval (days)
    recommend_interval_days: int = 30
    soon_interval_days: int = 60

    # Minimum meaningful reclaim (bytes) — below this, NOT_NEEDED
    minimum_meaningful_reclaim: int = 10 * 1024 * 1024   # 10 MB

    def __post_init__(self):
        pass


DEFAULT_POLICY = MaintenancePolicy()


# ── Recommendation Result ───────────────────────────────────────

@dataclass
class MaintenanceRecommendation:
    """Transparent recommendation with reasoning."""
    status: MaintenanceStatus = MaintenanceStatus.NOT_NEEDED
    score: int = 0                          # 0-100, higher = more needed
    reasons: List[str] = field(default_factory=list)
    estimated_reclaimable_bytes: int = 0
    estimated_reclaimable_display: str = ""
    disk_free_gb: float = 0.0
    disk_free_percent: float = 0.0
    disk_total_gb: float = 0.0
    storage_pressure: str = "NORMAL"
    last_maintenance_time: Optional[str] = None
    last_maintenance_display: str = "Never"
    next_recommended_time: Optional[str] = None
    next_recommended_display: str = ""
    cleanup_categories: int = 0
    total_cleanup_items: int = 0
    confidence: float = 0.0
    checked_at: str = ""

    def __post_init__(self):
        if not self.checked_at:
            self.checked_at = datetime.now().isoformat(timespec="seconds")


# ── Maintenance History ─────────────────────────────────────────

class MaintenanceHistory:
    """Lightweight persistent maintenance history.
    
    Stores records in a JSON file alongside the existing config.
    """

    def __init__(self):
        self._data_dir = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(__file__))),
            "maintenance_history",
        )
        self._history_file = os.path.join(self._data_dir, "maintenance_log.json")
        self._records: List[dict] = []
        self._load()

    def _load(self):
        """Load history from disk."""
        try:
            if os.path.exists(self._history_file):
                with open(self._history_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                self._records = data.get("records", []) if isinstance(data, dict) else []
        except Exception as e:
            logger.debug(f"Failed to load maintenance history: {e}")
            self._records = []

    def _save(self):
        """Save history to disk."""
        try:
            os.makedirs(self._data_dir, exist_ok=True)
            with open(self._history_file, "w", encoding="utf-8") as f:
                json.dump({"records": self._records[-50:]}, f, indent=2)
        except Exception as e:
            logger.debug(f"Failed to save maintenance history: {e}")

    def record_scan(self, reclaimable_bytes: int, categories: int, items: int):
        """Record a scan event."""
        self._records.append({
            "type": "scan",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "reclaimable_bytes": reclaimable_bytes,
            "categories": categories,
            "items": items,
        })
        self._save()

    def record_cleanup(
        self,
        bytes_cleaned: int,
        categories: List[str],
        success: bool,
        items_cleaned: int = 0,
    ):
        """Record a cleanup event."""
        self._records.append({
            "type": "cleanup",
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "bytes_cleaned": bytes_cleaned,
            "categories": categories,
            "success": success,
            "items_cleaned": items_cleaned,
        })
        self._save()

    def get_last_cleanup(self) -> Optional[dict]:
        """Get the most recent successful cleanup record."""
        for rec in reversed(self._records):
            if rec.get("type") == "cleanup" and rec.get("success"):
                return rec
        return None

    def get_last_cleanup_time(self) -> Optional[datetime]:
        """Get the timestamp of the last successful cleanup."""
        last = self.get_last_cleanup()
        if last:
            try:
                return datetime.fromisoformat(last["timestamp"])
            except (ValueError, KeyError):
                pass
        return None

    def get_last_cleanup_display(self) -> str:
        """Human-readable time since last cleanup."""
        last_time = self.get_last_cleanup_time()
        if not last_time:
            return "Never"
        delta = datetime.now() - last_time
        days = delta.days
        if days == 0:
            hours = delta.seconds // 3600
            if hours == 0:
                return "Today"
            return f"{hours}h ago"
        elif days == 1:
            return "Yesterday"
        elif days < 30:
            return f"{days} days ago"
        elif days < 365:
            months = days // 30
            return f"{months} month{'s' if months > 1 else ''} ago"
        else:
            years = days // 365
            return f"{years} year{'s' if years > 1 else ''} ago"

    def get_total_cleaned_all_time(self) -> int:
        """Total bytes cleaned across all successful cleanups."""
        total = 0
        for rec in self._records:
            if rec.get("type") == "cleanup" and rec.get("success"):
                total += rec.get("bytes_cleaned", 0)
        return total

    def get_records(self) -> List[dict]:
        """Get all history records."""
        return list(self._records)


# ── Maintenance Intelligence Engine ─────────────────────────────

class MaintenanceIntelligence:
    """
    Evaluates system state and produces a MaintenanceRecommendation.
    
    Uses real measurements only — no fake data.
    Expensive disk analysis runs in background workers, not on GUI thread.
    """

    def __init__(self, policy: Optional[MaintenancePolicy] = None):
        self._policy = policy or DEFAULT_POLICY
        self._history = MaintenanceHistory()
        self._last_recommendation: Optional[MaintenanceRecommendation] = None

    @property
    def policy(self) -> MaintenancePolicy:
        return self._policy

    @property
    def history(self) -> MaintenanceHistory:
        return self._history

    def evaluate(
        self,
        reclaimable_bytes: int = 0,
        disk_free_gb: float = 0.0,
        disk_total_gb: float = 0.0,
        cleanup_categories: int = 0,
        total_cleanup_items: int = 0,
        storage_pressure: str = "NORMAL",
    ) -> MaintenanceRecommendation:
        """
        Produce a maintenance recommendation from measured system state.
        
        All inputs come from existing scanners/analyzers — this method
        does NOT perform any filesystem scans itself.
        """
        p = self._policy
        rec = MaintenanceRecommendation()

        # Disk info
        rec.disk_free_gb = disk_free_gb
        rec.disk_total_gb = disk_total_gb
        if disk_total_gb > 0:
            rec.disk_free_percent = (disk_free_gb / disk_total_gb) * 100
        rec.storage_pressure = storage_pressure

        # Cleanup info
        rec.estimated_reclaimable_bytes = reclaimable_bytes
        rec.estimated_reclaimable_display = self._format_bytes(reclaimable_bytes)
        rec.cleanup_categories = cleanup_categories
        rec.total_cleanup_items = total_cleanup_items

        # Last maintenance
        rec.last_maintenance_display = self._history.get_last_cleanup_display()
        last_cleanup_time = self._history.get_last_cleanup_time()
        if last_cleanup_time:
            rec.last_maintenance_time = last_cleanup_time.isoformat(timespec="seconds")

        # Score and status
        score, reasons = self._compute_score(
            reclaimable_bytes=reclaimable_bytes,
            disk_free_gb=disk_free_gb,
            disk_total_gb=disk_total_gb,
            storage_pressure=storage_pressure,
            last_cleanup_time=last_cleanup_time,
            cleanup_categories=cleanup_categories,
        )

        rec.score = min(100, max(0, score))
        rec.reasons = reasons
        rec.confidence = min(1.0, score / 80.0) if score > 0 else 0.5

        # Determine status from score
        if rec.estimated_reclaimable_bytes < p.minimum_meaningful_reclaim:
            rec.status = MaintenanceStatus.NOT_NEEDED
            if not reasons:
                rec.reasons = ["Current cleanup candidates are below the maintenance threshold."]
        elif score >= 60:
            rec.status = MaintenanceStatus.RECOMMENDED_NOW
        elif score >= 30:
            rec.status = MaintenanceStatus.RECOMMENDED_SOON
        else:
            rec.status = MaintenanceStatus.NOT_NEEDED

        # Override: disk pressure always bumps to RECOMMENDED_NOW
        if storage_pressure in ("CRITICAL", "HIGH") and reclaimable_bytes > 0:
            rec.status = MaintenanceStatus.RECOMMENDED_NOW
            if score < 60:
                rec.score = max(score, 65)
                reasons.insert(0, f"Storage pressure is {storage_pressure}.")

        # Next recommended time
        if rec.status == MaintenanceStatus.RECOMMENDED_NOW:
            rec.next_recommended_display = "After cleanup"
        elif rec.status == MaintenanceStatus.RECOMMENDED_SOON:
            rec.next_recommended_display = "Within 7 days"
        else:
            rec.next_recommended_display = f"In {p.recommend_interval_days} days"

        self._last_recommendation = rec
        return rec

    def _compute_score(
        self,
        reclaimable_bytes: int,
        disk_free_gb: float,
        disk_total_gb: float,
        storage_pressure: str,
        last_cleanup_time: Optional[datetime],
        cleanup_categories: int,
    ) -> tuple:
        """Compute a 0-100 score and list of reasons.
        
        Returns (score, reasons_list).
        """
        p = self._policy
        score = 0
        reasons = []

        # Factor 1: Reclaimable space (0-40 points)
        if reclaimable_bytes >= p.recommend_now_bytes:
            score += 40
            reasons.append(
                f"{self._format_bytes(reclaimable_bytes)} of reclaimable temporary data detected."
            )
        elif reclaimable_bytes >= p.recommend_soon_bytes:
            score += 20
            reasons.append(
                f"{self._format_bytes(reclaimable_bytes)} of reclaimable data available."
            )
        elif reclaimable_bytes >= p.minimum_meaningful_reclaim:
            score += 5
            reasons.append(
                f"Small amount of reclaimable data: {self._format_bytes(reclaimable_bytes)}."
            )

        # Factor 2: Disk free space (0-30 points)
        if disk_free_gb > 0:
            if disk_free_gb < p.critical_free_gb:
                score += 30
                reasons.append(
                    f"Only {disk_free_gb:.1f} GB ({disk_free_gb/disk_total_gb*100:.0f}%) free disk space."
                )
            elif disk_free_gb < p.high_free_gb:
                score += 20
                reasons.append(
                    f"Disk free space is low: {disk_free_gb:.1f} GB."
                )
            elif disk_free_gb < p.elevated_free_gb:
                score += 10
                reasons.append(
                    f"Disk free space is moderate: {disk_free_gb:.1f} GB."
                )

        # Factor 3: Time since last maintenance (0-20 points)
        if last_cleanup_time:
            days_since = (datetime.now() - last_cleanup_time).days
            if days_since >= p.soon_interval_days:
                score += 20
                reasons.append(
                    f"Last maintenance was {days_since} days ago."
                )
            elif days_since >= p.recommend_interval_days:
                score += 10
                reasons.append(
                    f"Last maintenance was {days_since} days ago."
                )
            else:
                # Recent maintenance suppresses score
                score -= 10
                reasons.append(
                    f"Recent maintenance ({days_since} days ago) — system is maintained."
                )
        else:
            # No previous maintenance — slight boost
            score += 5
            reasons.append("No previous maintenance recorded.")

        # Factor 4: Number of categories (0-10 points)
        if cleanup_categories >= 5:
            score += 10
            reasons.append(f"{cleanup_categories} cleanup categories detected.")
        elif cleanup_categories >= 3:
            score += 5
            reasons.append(f"{cleanup_categories} cleanup categories detected.")

        return score, reasons

    @staticmethod
    def _format_bytes(size_bytes: int) -> str:
        """Human-readable byte size."""
        if size_bytes <= 0:
            return "0 B"
        for unit in ("B", "KB", "MB", "GB", "TB"):
            if abs(size_bytes) < 1024.0:
                return f"{size_bytes:.1f} {unit}"
            size_bytes /= 1024.0
        return f"{size_bytes:.1f} PB"

    def get_status_display(self, status: MaintenanceStatus) -> str:
        """Return display text for a status."""
        return {
            MaintenanceStatus.RECOMMENDED_NOW: "RECOMMENDED NOW",
            MaintenanceStatus.RECOMMENDED_SOON: "RECOMMENDED SOON",
            MaintenanceStatus.NOT_NEEDED: "NOT NEEDED",
        }.get(status, "UNKNOWN")

    def get_status_icon(self, status: MaintenanceStatus) -> str:
        """Return display icon for a status."""
        return {
            MaintenanceStatus.RECOMMENDED_NOW: "\u26a0",
            MaintenanceStatus.RECOMMENDED_SOON: "\u25cf",
            MaintenanceStatus.NOT_NEEDED: "\u2713",
        }.get(status, "?")


# Singleton
maintenance_intelligence = MaintenanceIntelligence()
