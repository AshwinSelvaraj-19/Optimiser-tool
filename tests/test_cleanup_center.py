"""
Phase 50 — Comprehensive tests for the Cleanup Center.

Tests cover:
  - SafetyClassification enum
  - CleanupAnalyzer classification logic
  - CleanupRecommendationEngine disk pressure
  - CleanupRecommendationEngine recommendation generation
  - CleanupCenter scan/preview/clean workflow
  - Safety gate: DO_NOT_TOUCH items never cleaned
  - Safety gate: REVIEW items require user action
  - Safety gate: SAFE items can be cleaned
  - Item selection and deselection
  - Disk pressure thresholds
  - Recommendation priority ordering
  - UI summary generation
  - CLI formatting
  - Edge cases
"""

import os
import sys
import unittest
from unittest.mock import MagicMock, patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.cleanup.cleanup_models import (
    CleanupItem,
    CleanupCategory,
    CleanupStatus,
    SafetyClassification,
    CleanupRecommendation,
    format_bytes,
)
from app.cleanup.cleanup_center import (
    CleanupAnalyzer,
    CleanupRecommendationEngine,
    CleanupCenter,
    DISK_PRESSURE_CRITICAL,
    DISK_PRESSURE_HIGH,
    DISK_PRESSURE_ELEVATED,
    MIN_CLEANUP_SIZE_MB,
)


def _make_item(
    item_id="test",
    name="Test Item",
    category=CleanupCategory.USER_TEMP,
    detected_size=100 * 1024 * 1024,  # 100 MB
    removable_size=50 * 1024 * 1024,  # 50 MB
    removable_count=10,
    available=True,
    requires_admin=False,
    last_access_days=10,
    risk="LOW",
    status=CleanupStatus.AVAILABLE,
):
    """Helper to create a CleanupItem."""
    return CleanupItem(
        id=item_id,
        name=name,
        category=category,
        detected_size=detected_size,
        removable_size=removable_size,
        removable_file_count=removable_count,
        available=available,
        requires_admin=requires_admin,
        last_access_days=last_access_days,
        risk=risk,
        status=status,
    )


class TestSafetyClassification(unittest.TestCase):
    """Tests for SafetyClassification enum."""

    def test_has_safe(self):
        self.assertEqual(SafetyClassification.SAFE.value, "SAFE")

    def test_has_review(self):
        self.assertEqual(SafetyClassification.REVIEW.value, "REVIEW")

    def test_has_do_not_touch(self):
        self.assertEqual(SafetyClassification.DO_NOT_TOUCH.value, "DO_NOT_TOUCH")


class TestCleanupAnalyzer(unittest.TestCase):
    """Tests for CleanupAnalyzer."""

    def _make_analyzer(self):
        return CleanupAnalyzer()

    def test_recycle_bin_is_do_not_touch(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.RECYCLE_BIN)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.DO_NOT_TOUCH)
        self.assertFalse(items[0].selected)

    def test_shader_cache_is_review(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.SHADER_CACHE)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.REVIEW)
        self.assertFalse(items[0].selected)

    def test_application_cache_is_review(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.APPLICATION_CACHE)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.REVIEW)

    def test_admin_required_is_review(self):
        analyzer = self._make_analyzer()
        item = _make_item(requires_admin=True)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.REVIEW)
        self.assertFalse(items[0].can_delete)

    def test_not_available_is_review(self):
        analyzer = self._make_analyzer()
        item = _make_item(available=False, removable_size=0)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.REVIEW)

    def test_user_temp_old_is_safe(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.USER_TEMP, last_access_days=10)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.SAFE)
        self.assertTrue(items[0].selected)
        self.assertTrue(items[0].can_delete)

    def test_user_temp_new_is_review(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.USER_TEMP, last_access_days=2)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.REVIEW)
        self.assertFalse(items[0].selected)

    def test_system_temp_with_removable_is_safe(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.SYSTEM_TEMP, removable_size=1000)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.SAFE)
        self.assertTrue(items[0].selected)

    def test_crash_dumps_old_is_safe(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.CRASH_DUMPS, last_access_days=10)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.SAFE)
        self.assertTrue(items[0].selected)

    def test_crash_dumps_new_is_review(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.CRASH_DUMPS, last_access_days=3)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.REVIEW)

    def test_installer_old_is_safe(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.INSTALLER_LEFTOVER, last_access_days=10)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.SAFE)

    def test_old_logs_old_is_safe(self):
        analyzer = self._make_analyzer()
        item = _make_item(category=CleanupCategory.OLD_LOGS, last_access_days=10)
        items = analyzer.analyze([item])
        self.assertEqual(items[0].safety, SafetyClassification.SAFE)

    def test_get_safe_items(self):
        analyzer = self._make_analyzer()
        items = [
            _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10),
            _make_item("b", category=CleanupCategory.RECYCLE_BIN),
            _make_item("c", category=CleanupCategory.USER_TEMP, last_access_days=2),
        ]
        analyzed = analyzer.analyze(items)
        safe = analyzer.get_safe_items(analyzed)
        self.assertEqual(len(safe), 1)
        self.assertEqual(safe[0].id, "a")

    def test_get_review_items(self):
        analyzer = self._make_analyzer()
        items = [
            _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10),
            _make_item("b", category=CleanupCategory.RECYCLE_BIN),
            _make_item("c", category=CleanupCategory.USER_TEMP, last_access_days=2),
            _make_item("d", category=CleanupCategory.SHADER_CACHE),
        ]
        analyzed = analyzer.analyze(items)
        review = analyzer.get_review_items(analyzed)
        # RECYCLE_BIN=DO_NOT_TOUCH, USER_TEMP(10d)=SAFE, USER_TEMP(2d)=REVIEW, SHADER=REVIEW
        self.assertEqual(len(review), 2)

    def test_get_do_not_touch_items(self):
        analyzer = self._make_analyzer()
        items = [
            _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10),
            _make_item("b", category=CleanupCategory.RECYCLE_BIN),
        ]
        analyzed = analyzer.analyze(items)
        blocked = analyzer.get_do_not_touch_items(analyzed)
        self.assertEqual(len(blocked), 1)
        self.assertEqual(blocked[0].id, "b")

    def test_get_total_safe_bytes(self):
        analyzer = self._make_analyzer()
        items = [
            _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10,
                       removable_size=50 * 1024 * 1024),
            _make_item("b", category=CleanupCategory.RECYCLE_BIN),
        ]
        analyzed = analyzer.analyze(items)
        total = analyzer.get_total_safe_bytes(analyzed)
        self.assertEqual(total, 50 * 1024 * 1024)


class TestCleanupRecommendationEngine(unittest.TestCase):
    """Tests for CleanupRecommendationEngine."""

    def _make_engine(self):
        return CleanupRecommendationEngine()

    def test_disk_pressure_normal(self):
        engine = self._make_engine()
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=100 * 1024**3, total=500 * 1024**3)
            free, total, level = engine.analyze_disk_pressure()
        self.assertAlmostEqual(free, 100.0, places=0)
        self.assertEqual(level, "NORMAL")

    def test_disk_pressure_critical(self):
        engine = self._make_engine()
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=3 * 1024**3, total=500 * 1024**3)
            free, total, level = engine.analyze_disk_pressure()
        self.assertEqual(level, "CRITICAL")

    def test_disk_pressure_high(self):
        engine = self._make_engine()
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=10 * 1024**3, total=500 * 1024**3)
            free, total, level = engine.analyze_disk_pressure()
        self.assertEqual(level, "HIGH")

    def test_disk_pressure_elevated(self):
        engine = self._make_engine()
        with patch("shutil.disk_usage") as mock_usage:
            mock_usage.return_value = MagicMock(free=25 * 1024**3, total=500 * 1024**3)
            free, total, level = engine.analyze_disk_pressure()
        self.assertEqual(level, "ELEVATED")

    def test_recommendations_with_safe_items(self):
        engine = self._make_engine()
        items = [
            _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10,
                       removable_size=100 * 1024 * 1024),
        ]
        # Manually set safety
        items[0].safety = SafetyClassification.SAFE
        items[0].selected = True

        recs = engine.generate_recommendations(items, 50.0, 500.0, "NORMAL")
        self.assertGreater(len(recs), 0)
        self.assertEqual(recs[0].title, "Safe Cleanup Available")

    def test_recommendations_disk_pressure_high(self):
        engine = self._make_engine()
        items = [
            _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10,
                       removable_size=100 * 1024 * 1024),
        ]
        items[0].safety = SafetyClassification.SAFE
        items[0].selected = True

        recs = engine.generate_recommendations(items, 10.0, 500.0, "HIGH")
        # Should have disk pressure warning as first or second recommendation
        titles = [r.title for r in recs]
        self.assertIn("Disk Space HIGH", titles)

    def test_recommendations_no_items(self):
        engine = self._make_engine()
        recs = engine.generate_recommendations([], 50.0, 500.0, "NORMAL")
        self.assertEqual(len(recs), 0)

    def test_recommendations_priority_ordering(self):
        engine = self._make_engine()
        items = [
            _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10,
                       removable_size=100 * 1024 * 1024),
        ]
        items[0].safety = SafetyClassification.SAFE
        items[0].selected = True

        recs = engine.generate_recommendations(items, 3.0, 500.0, "CRITICAL")
        # Disk pressure should be first (HIGH), safe cleanup second
        self.assertEqual(recs[0].title, "Disk Space CRITICAL")
        self.assertEqual(recs[0].priority, "HIGH")


class TestCleanupCenter(unittest.TestCase):
    """Tests for CleanupCenter."""

    def _make_center(self):
        return CleanupCenter()

    def test_initial_state(self):
        center = self._make_center()
        self.assertEqual(len(center.items), 0)
        self.assertFalse(center.is_busy)

    def test_scan_returns_items(self):
        center = self._make_center()
        with patch.object(center._scanner, "scan") as mock_scan:
            mock_scan.return_value = [
                _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10),
                _make_item("b", category=CleanupCategory.RECYCLE_BIN),
            ]
            with patch.object(center._recommendation_engine, "analyze_disk_pressure",
                            return_value=(50.0, 500.0, "NORMAL")):
                items = center.scan()
        self.assertEqual(len(items), 2)

    def test_get_preview(self):
        center = self._make_center()
        with patch.object(center._scanner, "scan") as mock_scan:
            mock_scan.return_value = [
                _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10),
                _make_item("b", category=CleanupCategory.RECYCLE_BIN),
            ]
            with patch.object(center._recommendation_engine, "analyze_disk_pressure",
                            return_value=(50.0, 500.0, "NORMAL")):
                center.scan()

        preview = center.get_preview()
        self.assertIn("safe_items", preview)
        self.assertIn("blocked_items", preview)
        self.assertIn("disk_free_gb", preview)
        self.assertIn("recommendations", preview)

    def test_clean_safe_no_items(self):
        center = self._make_center()
        result = center.clean_safe()
        self.assertEqual(result.message, "No safe items to clean")

    def test_get_ui_summary(self):
        center = self._make_center()
        summary = center.get_ui_summary()
        self.assertEqual(summary["total_items"], 0)
        self.assertEqual(summary["disk_pressure"], "UNKNOWN")

    def test_format_scan_results(self):
        center = self._make_center()
        output = center.format_scan_results()
        self.assertIn("CLEANUP CENTER SCAN", output)

    def test_format_preview(self):
        center = self._make_center()
        output = center.format_preview()
        self.assertIn("CLEANUP PREVIEW", output)
        self.assertIn("Nothing will be deleted yet", output)


class TestFormatBytes(unittest.TestCase):
    """Tests for format_bytes utility."""

    def test_zero(self):
        self.assertEqual(format_bytes(0), "0 B")

    def test_bytes(self):
        self.assertEqual(format_bytes(500), "500 B")

    def test_kb(self):
        self.assertEqual(format_bytes(1536), "1.5 KB")

    def test_mb(self):
        self.assertEqual(format_bytes(1024 * 1024), "1.0 MB")

    def test_gb(self):
        self.assertEqual(format_bytes(1024 * 1024 * 1024), "1.00 GB")

    def test_negative(self):
        self.assertEqual(format_bytes(-100), "0 B")


class TestCleanupRecommendation(unittest.TestCase):
    """Tests for CleanupRecommendation."""

    def test_to_dict(self):
        rec = CleanupRecommendation(
            title="Test",
            description="Desc",
            priority="HIGH",
            estimated_freed_bytes=1024 * 1024,
        )
        d = rec.to_dict()
        self.assertEqual(d["title"], "Test")
        self.assertEqual(d["priority"], "HIGH")
        self.assertEqual(d["estimated_freed_display"], "1.0 MB")

    def test_default_id(self):
        rec = CleanupRecommendation()
        self.assertTrue(rec.recommendation_id.startswith("rec_"))


class TestCleanupItemModels(unittest.TestCase):
    """Tests for CleanupItem models."""

    def test_size_display(self):
        item = _make_item(detected_size=1024 * 1024)
        self.assertEqual(item.size_display, "1.0 MB")

    def test_removable_display(self):
        item = _make_item(removable_size=512 * 1024)
        self.assertEqual(item.removable_display, "512.0 KB")

    def test_default_id(self):
        item = CleanupItem()
        self.assertTrue(item.id.startswith("cleanup_"))


class TestDiskPressureThresholds(unittest.TestCase):
    """Tests for disk pressure constants."""

    def test_critical_less_than_high(self):
        self.assertLess(DISK_PRESSURE_CRITICAL, DISK_PRESSURE_HIGH)

    def test_high_less_than_elevated(self):
        self.assertLess(DISK_PRESSURE_HIGH, DISK_PRESSURE_ELEVATED)

    def test_min_cleanup_size_positive(self):
        self.assertGreater(MIN_CLEANUP_SIZE_MB, 0)


class TestEdgeCases(unittest.TestCase):
    """Edge case tests."""

    def _make_center(self):
        return CleanupCenter()

    def test_analyzer_empty_input(self):
        analyzer = CleanupAnalyzer()
        items = analyzer.analyze([])
        self.assertEqual(len(items), 0)

    def test_center_scan_with_no_scanner_results(self):
        center = self._make_center()
        with patch.object(center._scanner, "scan", return_value=[]):
            with patch.object(center._recommendation_engine, "analyze_disk_pressure",
                            return_value=(50.0, 500.0, "NORMAL")):
                items = center.scan()
        self.assertEqual(len(items), 0)

    def test_clean_selected_empty_list(self):
        center = self._make_center()
        result = center.clean_selected([])
        self.assertIn("No valid items", result.message)

    def test_item_all_none_sizes(self):
        item = CleanupItem()
        self.assertEqual(item.size_display, "0 B")
        self.assertEqual(item.removable_display, "0 B")

    def test_recommendation_engine_disk_error(self):
        engine = CleanupRecommendationEngine()
        with patch("shutil.disk_usage", side_effect=Exception("error")):
            free, total, level = engine.analyze_disk_pressure()
        self.assertEqual(level, "UNKNOWN")

    def test_center_ui_summary_after_scan(self):
        center = self._make_center()
        with patch.object(center._scanner, "scan") as mock_scan:
            mock_scan.return_value = [
                _make_item("a", category=CleanupCategory.USER_TEMP, last_access_days=10),
            ]
            with patch.object(center._recommendation_engine, "analyze_disk_pressure",
                            return_value=(50.0, 500.0, "NORMAL")):
                center.scan()
        summary = center.get_ui_summary()
        self.assertEqual(summary["total_items"], 1)
        self.assertGreater(summary["safe_count"], 0)


if __name__ == "__main__":
    unittest.main()
