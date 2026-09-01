"""
Phase 50 — Cleanup Center.

Intelligent cleanup analysis with safety classifications, recommendations,
and controlled execution.

Components:
  CleanupAnalyzer          — Analyzes scan results, provides safety classification
  CleanupRecommendationEngine — Generates cleanup recommendations
  CleanupCenter            — Orchestrates scan → analyze → recommend → preview → clean

Rules:
  - Never blindly delete files
  - Every candidate must have: path, category, size, reason, safety, last-access
  - Safety classifications: SAFE, REVIEW, DO_NOT_TOUCH
  - Show preview before deletion
  - Never run cleanup without user permission
  - Every deletion is verified after execution
"""

import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

from app.cleanup.cleanup_models import (
    CleanupItem,
    CleanupCategory,
    CleanupStatus,
    SafetyClassification,
    CleanupResult,
    CleanupSessionResult,
    CleanupRecommendation,
    format_bytes,
)
from app.cleanup.cleanup_scanner import CleanupScanner
from app.cleanup.cleanup_engine import CleanupEngine
from app.cleanup.cleanup_safety import is_safe_to_delete
from app.utils.logger import get_logger

logger = get_logger("cleanup.center")


# ── Constants ────────────────────────────────────────────────────

# Disk pressure thresholds (GB free)
DISK_PRESSURE_CRITICAL = 5.0
DISK_PRESSURE_HIGH = 15.0
DISK_PRESSURE_ELEVATED = 30.0

# Cleanup thresholds
MIN_CLEANUP_SIZE_MB = 10  # Minimum size to recommend cleanup
OLD_FILE_DAYS = 7  # Minimum age to consider "old"
VERY_OLD_FILE_DAYS = 30  # Age for high-priority recommendation


# ── Cleanup Analyzer ─────────────────────────────────────────────

class CleanupAnalyzer:
    """
    Analyzes cleanup scan results and provides safety classifications.

    Assigns each item a SafetyClassification:
      SAFE          — Safe to clean with user permission
      REVIEW        — Requires user review
      DO_NOT_TOUCH  — Never delete automatically
    """

    def __init__(self):
        self._last_analysis: List[CleanupItem] = []

    @property
    def last_analysis(self) -> List[CleanupItem]:
        return list(self._last_analysis)

    def analyze(self, items: List[CleanupItem]) -> List[CleanupItem]:
        """
        Analyze scan results and assign safety classifications.

        Returns items with updated safety, selected, and reason fields.
        """
        analyzed = []

        for item in items:
            classified = self._classify_item(item)
            analyzed.append(classified)

        self._last_analysis = analyzed
        return analyzed

    def _classify_item(self, item: CleanupItem) -> CleanupItem:
        """Classify a single cleanup item."""
        # DO_NOT_TOUCH: items that must never be auto-deleted
        if item.category in (CleanupCategory.RECYCLE_BIN,):
            item.safety = SafetyClassification.DO_NOT_TOUCH
            item.selected = False
            item.can_delete = False
            item.reason = "Recycle Bin requires explicit user confirmation"
            return item

        # Shader cache: always REVIEW (causes stutter)
        if item.category == CleanupCategory.SHADER_CACHE:
            item.safety = SafetyClassification.REVIEW
            item.selected = False
            item.can_delete = False
            item.reason = "Clearing shader cache may cause temporary stutter"
            return item

        # Application cache: REVIEW (browser/page loads affected)
        if item.category == CleanupCategory.APPLICATION_CACHE:
            item.safety = SafetyClassification.REVIEW
            item.selected = False
            item.can_delete = False
            item.reason = "Browser cache rebuilds — may slow page loads temporarily"
            return item

        # Items requiring admin
        if item.requires_admin:
            item.safety = SafetyClassification.REVIEW
            item.selected = False
            item.can_delete = False
            item.reason = "Requires administrator privileges"
            return item

        # Items not available or not removable
        if not item.available or item.removable_size == 0:
            item.safety = SafetyClassification.REVIEW
            item.selected = False
            item.reason = "Nothing removable (files locked or in use)"
            return item

        # User temp: SAFE if files are old enough
        if item.category == CleanupCategory.USER_TEMP:
            if item.last_access_days is not None and item.last_access_days >= OLD_FILE_DAYS:
                item.safety = SafetyClassification.SAFE
                item.selected = True
                item.can_delete = True
                item.reason = f"Temp files older than {item.last_access_days} days"
            else:
                item.safety = SafetyClassification.REVIEW
                item.selected = False
                item.reason = "Temp files may still be in use"
            return item

        # System temp: SAFE with admin, but REVIEW otherwise
        if item.category == CleanupCategory.SYSTEM_TEMP:
            if item.removable_size > 0:
                item.safety = SafetyClassification.SAFE
                item.selected = True
                item.can_delete = True
                item.reason = "System temp files are removable"
            return item

        # Crash dumps: SAFE if old enough
        if item.category == CleanupCategory.CRASH_DUMPS:
            if item.last_access_days is not None and item.last_access_days >= OLD_FILE_DAYS:
                item.safety = SafetyClassification.SAFE
                item.selected = True
                item.can_delete = True
            else:
                item.safety = SafetyClassification.REVIEW
                item.selected = False
            return item

        # Installer leftovers: SAFE if old enough
        if item.category == CleanupCategory.INSTALLER_LEFTOVER:
            if item.last_access_days is not None and item.last_access_days >= OLD_FILE_DAYS:
                item.safety = SafetyClassification.SAFE
                item.selected = True
                item.can_delete = True
            else:
                item.safety = SafetyClassification.REVIEW
                item.selected = False
            return item

        # Old logs: SAFE if old enough
        if item.category == CleanupCategory.OLD_LOGS:
            if item.last_access_days is not None and item.last_access_days >= OLD_FILE_DAYS:
                item.safety = SafetyClassification.SAFE
                item.selected = True
                item.can_delete = True
            else:
                item.safety = SafetyClassification.REVIEW
                item.selected = False
            return item

        # Default: REVIEW
        item.safety = SafetyClassification.REVIEW
        item.selected = False
        item.reason = "Unclassified — requires review"
        return item

    def get_safe_items(self, items: List[CleanupItem]) -> List[CleanupItem]:
        """Get only SAFE items that are selected for cleanup."""
        return [i for i in items if i.safety == SafetyClassification.SAFE and i.selected]

    def get_review_items(self, items: List[CleanupItem]) -> List[CleanupItem]:
        """Get items that need user review."""
        return [i for i in items if i.safety == SafetyClassification.REVIEW]

    def get_do_not_touch_items(self, items: List[CleanupItem]) -> List[CleanupItem]:
        """Get items that must never be auto-deleted."""
        return [i for i in items if i.safety == SafetyClassification.DO_NOT_TOUCH]

    def get_total_safe_bytes(self, items: List[CleanupItem]) -> int:
        """Get total bytes that can be safely reclaimed."""
        return sum(i.removable_size for i in items
                   if i.safety == SafetyClassification.SAFE and i.selected)


# ── Cleanup Recommendation Engine ────────────────────────────────

class CleanupRecommendationEngine:
    """
    Generates cleanup recommendations based on:
      - Disk free space
      - Cleanup size potential
      - File age
      - Historical cleanup patterns
      - System pressure
    """

    def __init__(self):
        self._history: List[Dict] = []

    def analyze_disk_pressure(self) -> Tuple[float, float, str]:
        """
        Analyze disk pressure.
        Returns (free_gb, total_gb, pressure_level).
        """
        try:
            import shutil
            usage = shutil.disk_usage("/")
            free_gb = usage.free / (1024 ** 3)
            total_gb = usage.total / (1024 ** 3)

            if free_gb < DISK_PRESSURE_CRITICAL:
                level = "CRITICAL"
            elif free_gb < DISK_PRESSURE_HIGH:
                level = "HIGH"
            elif free_gb < DISK_PRESSURE_ELEVATED:
                level = "ELEVATED"
            else:
                level = "NORMAL"

            return free_gb, total_gb, level
        except Exception:
            return 0.0, 0.0, "UNKNOWN"

    def generate_recommendations(
        self,
        items: List[CleanupItem],
        disk_free_gb: float = 0.0,
        disk_total_gb: float = 0.0,
        pressure_level: str = "NORMAL",
    ) -> List[CleanupRecommendation]:
        """
        Generate cleanup recommendations from analyzed items.

        Recommendations are prioritized by:
          1. Disk pressure (higher pressure → higher priority)
          2. Cleanup size potential
          3. Safety (SAFE items get higher priority)
          4. Age (older files get higher priority)
        """
        recommendations = []

        # Group items by safety and category
        safe_items = [i for i in items if i.safety == SafetyClassification.SAFE and i.selected]
        review_items = [i for i in items if i.safety == SafetyClassification.REVIEW]

        # Recommendation 1: Safe cleanup
        if safe_items:
            total_safe = sum(i.removable_size for i in safe_items)
            total_files = sum(i.removable_file_count for i in safe_items)

            if total_safe >= MIN_CLEANUP_SIZE_MB * 1024 * 1024:
                # Determine priority based on disk pressure
                if pressure_level == "CRITICAL":
                    priority = "HIGH"
                elif pressure_level == "HIGH":
                    priority = "HIGH"
                elif pressure_level == "ELEVATED":
                    priority = "MEDIUM"
                else:
                    priority = "LOW"

                recommendations.append(CleanupRecommendation(
                    title="Safe Cleanup Available",
                    description=(
                        f"{len(safe_items)} categories with {format_bytes(total_safe)} "
                        f"({total_files} files) can be safely cleaned."
                    ),
                    category="SAFE_CLEANUP",
                    priority=priority,
                    estimated_freed_bytes=total_safe,
                    item_ids=[i.id for i in safe_items],
                    reason=self._generate_reason(safe_items, pressure_level),
                    disk_free_gb=disk_free_gb,
                    pressure_level=pressure_level,
                ))

        # Recommendation 2: Review items
        if review_items:
            total_review = sum(i.removable_size for i in review_items)
            if total_review >= MIN_CLEANUP_SIZE_MB * 1024 * 1024:
                recommendations.append(CleanupRecommendation(
                    title="Additional Cleanup Available (Review Required)",
                    description=(
                        f"{len(review_items)} categories with {format_bytes(total_review)} "
                        "require manual review before cleanup."
                    ),
                    category="REVIEW_CLEANUP",
                    priority="LOW",
                    estimated_freed_bytes=total_review,
                    item_ids=[i.id for i in review_items],
                    reason="Items may affect system behavior — review recommended",
                    disk_free_gb=disk_free_gb,
                    pressure_level=pressure_level,
                ))

        # Recommendation 3: Disk pressure warning
        if pressure_level in ("CRITICAL", "HIGH"):
            recommendations.insert(0, CleanupRecommendation(
                title=f"Disk Space {pressure_level}",
                description=(
                    f"Only {disk_free_gb:.1f} GB free on system drive. "
                    "Cleaning safe temporary files can help free space."
                ),
                category="DISK_PRESSURE",
                priority="HIGH" if pressure_level == "CRITICAL" else "MEDIUM",
                estimated_freed_bytes=sum(i.removable_size for i in safe_items) if safe_items else 0,
                item_ids=[i.id for i in safe_items] if safe_items else [],
                reason=f"Disk free: {disk_free_gb:.1f} GB / {disk_total_gb:.1f} GB",
                disk_free_gb=disk_free_gb,
                pressure_level=pressure_level,
            ))

        # Sort by priority
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        recommendations.sort(key=lambda r: priority_order.get(r.priority, 3))

        return recommendations

    def _generate_reason(self, items: List[CleanupItem], pressure_level: str) -> str:
        """Generate a human-readable reason for the recommendation."""
        categories = [i.name for i in items[:3]]
        total = sum(i.removable_size for i in items)

        reason = f"Clean {', '.join(categories)}"
        if len(items) > 3:
            reason += f" and {len(items) - 3} more"
        reason += f" — reclaim {format_bytes(total)}"

        if pressure_level in ("CRITICAL", "HIGH"):
            reason += f" (disk pressure: {pressure_level})"

        return reason


# ── Cleanup Center ───────────────────────────────────────────────

class CleanupCenter:
    """
    Orchestrates the complete cleanup workflow:
      Scan → Analyze → Recommend → Preview → Clean → Verify

    Never runs cleanup without user permission.
    Every deletion is verified.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._scanner = CleanupScanner()
        self._analyzer = CleanupAnalyzer()
        self._recommendation_engine = CleanupRecommendationEngine()
        self._engine = CleanupEngine()

        self._items: List[CleanupItem] = []
        self._recommendations: List[CleanupRecommendation] = []
        self._last_session: Optional[CleanupSessionResult] = None
        self._disk_info: Tuple[float, float, str] = (0.0, 0.0, "UNKNOWN")

    @property
    def items(self) -> List[CleanupItem]:
        return list(self._items)

    @property
    def recommendations(self) -> List[CleanupRecommendation]:
        return list(self._recommendations)

    @property
    def last_session(self) -> Optional[CleanupSessionResult]:
        return self._last_session

    @property
    def is_busy(self) -> bool:
        return self._engine.is_busy

    # ── Workflow Methods ───────────────────────────────────────

    def scan(self) -> List[CleanupItem]:
        """
        Perform a full scan and analysis.
        Returns analyzed items with safety classifications.
        """
        with self._lock:
            # Scan
            raw_items = self._scanner.scan()

            # Analyze
            self._items = self._analyzer.analyze(raw_items)

            # Disk info
            self._disk_info = self._recommendation_engine.analyze_disk_pressure()

            # Generate recommendations
            self._recommendations = self._recommendation_engine.generate_recommendations(
                self._items,
                self._disk_info[0],
                self._disk_info[1],
                self._disk_info[2],
            )

            return self._items

    def get_preview(self) -> Dict:
        """
        Get a preview of what would be cleaned.
        Does NOT delete anything.
        """
        safe_items = self._analyzer.get_safe_items(self._items)
        review_items = self._analyzer.get_review_items(self._items)
        blocked_items = self._analyzer.get_do_not_touch_items(self._items)

        total_safe = sum(i.removable_size for i in safe_items)
        total_review = sum(i.removable_size for i in review_items)

        return {
            "safe_items": [{"id": i.id, "name": i.name, "size": i.removable_size,
                           "size_display": i.removable_display, "files": i.removable_file_count,
                           "category": i.category.value, "reason": i.reason}
                          for i in safe_items],
            "review_items": [{"id": i.id, "name": i.name, "size": i.removable_size,
                             "size_display": i.removable_display, "files": i.removable_file_count,
                             "category": i.category.value, "reason": i.reason}
                            for i in review_items],
            "blocked_items": [{"id": i.id, "name": i.name, "size": i.detected_size,
                              "size_display": i.size_display, "category": i.category.value,
                              "reason": i.reason}
                             for i in blocked_items],
            "total_safe_bytes": total_safe,
            "total_safe_display": format_bytes(total_safe),
            "total_review_bytes": total_review,
            "total_review_display": format_bytes(total_review),
            "disk_free_gb": self._disk_info[0],
            "disk_total_gb": self._disk_info[1],
            "disk_pressure": self._disk_info[2],
            "recommendations": [r.to_dict() for r in self._recommendations],
        }

    def clean_safe(self, progress_callback=None) -> CleanupSessionResult:
        """
        Clean only SAFE items that are selected.
        Requires user permission (called by button click).
        """
        safe_items = self._analyzer.get_safe_items(self._items)

        if not safe_items:
            result = CleanupSessionResult()
            result.message = "No safe items to clean"
            self._last_session = result
            return result

        # Ensure items are marked for deletion
        for item in safe_items:
            item.selected = True
            item.can_delete = True

        result = self._engine.clean(safe_items, progress_callback)
        self._last_session = result

        # Re-scan to update state
        self.scan()

        return result

    def clean_selected(self, item_ids: List[str], progress_callback=None) -> CleanupSessionResult:
        """
        Clean specific items by ID.
        Only processes items that pass safety checks.
        """
        selected_items = [
            i for i in self._items
            if i.id in item_ids and i.can_delete
            and i.safety != SafetyClassification.DO_NOT_TOUCH
        ]

        if not selected_items:
            result = CleanupSessionResult()
            result.message = "No valid items selected for cleanup"
            self._last_session = result
            return result

        for item in selected_items:
            item.selected = True

        result = self._engine.clean(selected_items, progress_callback)
        self._last_session = result

        # Re-scan
        self.scan()

        return result

    # ── UI Summary ─────────────────────────────────────────────

    def get_ui_summary(self) -> Dict:
        """Get structured summary for UI consumption."""
        safe = self._analyzer.get_safe_items(self._items)
        review = self._analyzer.get_review_items(self._items)
        blocked = self._analyzer.get_do_not_touch_items(self._items)

        return {
            "total_items": len(self._items),
            "safe_count": len(safe),
            "review_count": len(review),
            "blocked_count": len(blocked),
            "safe_bytes": sum(i.removable_size for i in safe),
            "safe_display": format_bytes(sum(i.removable_size for i in safe)),
            "review_bytes": sum(i.removable_size for i in review),
            "review_display": format_bytes(sum(i.removable_size for i in review)),
            "blocked_bytes": sum(i.detected_size for i in blocked),
            "blocked_display": format_bytes(sum(i.detected_size for i in blocked)),
            "disk_free_gb": self._disk_info[0],
            "disk_total_gb": self._disk_info[1],
            "disk_pressure": self._disk_info[2],
            "recommendation_count": len(self._recommendations),
            "top_recommendation": self._recommendations[0].to_dict() if self._recommendations else None,
            "last_session": self._last_session.to_dict() if self._last_session else None,
        }

    # ── CLI Formatting ─────────────────────────────────────────

    def format_scan_results(self) -> str:
        """Format scan results for CLI output."""
        lines = []
        w = 60
        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — CLEANUP CENTER SCAN")
        lines.append("=" * w)
        lines.append("")

        # Disk info
        free_gb, total_gb, pressure = self._disk_info
        lines.append(f"  Disk: {free_gb:.1f} GB free / {total_gb:.1f} GB total")
        lines.append(f"  Pressure: {pressure}")
        lines.append("")

        # Items by safety
        safe = self._analyzer.get_safe_items(self._items)
        review = self._analyzer.get_review_items(self._items)
        blocked = self._analyzer.get_do_not_touch_items(self._items)

        if safe:
            total_safe = sum(i.removable_size for i in safe)
            lines.append(f"  SAFE TO CLEAN ({len(safe)} items, {format_bytes(total_safe)})")
            lines.append("  " + "-" * (w - 4))
            for item in safe:
                lines.append(f"    [{item.category.value}] {item.name}")
                lines.append(f"      Size: {item.removable_display}  Files: {item.removable_file_count}")
                lines.append(f"      Reason: {item.reason}")
            lines.append("")

        if review:
            total_review = sum(i.removable_size for i in review)
            lines.append(f"  REVIEW REQUIRED ({len(review)} items, {format_bytes(total_review)})")
            lines.append("  " + "-" * (w - 4))
            for item in review:
                lines.append(f"    [{item.category.value}] {item.name}")
                lines.append(f"      Size: {item.removable_display}  Files: {item.removable_file_count}")
                lines.append(f"      Reason: {item.reason}")
            lines.append("")

        if blocked:
            total_blocked = sum(i.detected_size for i in blocked)
            lines.append(f"  DO NOT TOUCH ({len(blocked)} items, {format_bytes(total_blocked)})")
            lines.append("  " + "-" * (w - 4))
            for item in blocked:
                lines.append(f"    [{item.category.value}] {item.name}")
                lines.append(f"      Size: {item.size_display}  Reason: {item.reason}")
            lines.append("")

        # Recommendations
        if self._recommendations:
            lines.append("  RECOMMENDATIONS")
            lines.append("  " + "-" * (w - 4))
            for rec in self._recommendations:
                lines.append(f"    [{rec.priority}] {rec.title}")
                lines.append(f"      {rec.description}")
                lines.append(f"      Estimated: {rec.estimated_freed_display}")
            lines.append("")

        lines.append("=" * w)
        return "\n".join(lines)

    def format_preview(self) -> str:
        """Format preview for CLI output."""
        preview = self.get_preview()
        lines = []
        w = 60
        lines.append("=" * w)
        lines.append("  CLEANUP PREVIEW — Nothing will be deleted yet")
        lines.append("=" * w)
        lines.append("")

        if preview["safe_items"]:
            lines.append(f"  SAFE TO CLEAN ({preview['total_safe_display']})")
            lines.append("  " + "-" * (w - 4))
            for item in preview["safe_items"]:
                lines.append(f"    {item['name']}: {item['size_display']} ({item['files']} files)")
            lines.append("")

        if preview["review_items"]:
            lines.append(f"  REVIEW REQUIRED ({preview['total_review_display']})")
            lines.append("  " + "-" * (w - 4))
            for item in preview["review_items"]:
                lines.append(f"    {item['name']}: {item['size_display']} ({item['files']} files)")
            lines.append("")

        if preview["blocked_items"]:
            lines.append(f"  DO NOT TOUCH ({len(preview['blocked_items'])} items)")
            lines.append("  " + "-" * (w - 4))
            for item in preview["blocked_items"]:
                lines.append(f"    {item['name']}: {item['size_display']}")
            lines.append("")

        lines.append("=" * w)
        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────

cleanup_center = CleanupCenter()
