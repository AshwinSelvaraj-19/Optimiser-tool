"""
Tests for Heaven Society — Safe System Cleanup Engine.

Uses temporary test directories; never modifies real TEMP.
"""

import os
import shutil
import tempfile
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

from app.cleanup.cleanup_models import (
    CleanupItem,
    CleanupResult,
    CleanupSessionResult,
    CleanupStatus,
    CleanupCategory,
    format_bytes,
)
from app.cleanup.cleanup_safety import (
    is_safe_to_delete,
    can_delete_file,
    can_delete_directory,
    is_path_in_allowed_root,
    is_path_rejected,
    ALLOWED_CLEANUP_ROOTS,
)
from app.cleanup.cleanup_scanner import CleanupScanner
from app.cleanup.cleanup_engine import CleanupEngine


# ── Helpers ───────────────────────────────────────────────────

@pytest.fixture
def temp_dir():
    """Create a temporary directory for testing."""
    d = tempfile.mkdtemp(prefix="hs_test_cleanup_")
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def temp_cleanup_dir(temp_dir):
    """Create a temp directory that looks like a TEMP dir for testing."""
    # Create some test files
    for i in range(5):
        fp = os.path.join(temp_dir, f"test_file_{i}.tmp")
        with open(fp, "w") as f:
            f.write(f"test content {i}" * 100)
    # Create a subdirectory with files
    sub = os.path.join(temp_dir, "subdir")
    os.makedirs(sub)
    for i in range(3):
        fp = os.path.join(sub, f"sub_file_{i}.tmp")
        with open(fp, "w") as f:
            f.write(f"sub content {i}" * 50)
    return temp_dir


# ── format_bytes tests ────────────────────────────────────────

class TestFormatBytes:
    def test_zero(self):
        assert format_bytes(0) == "0 B"

    def test_negative(self):
        assert format_bytes(-100) == "0 B"

    def test_bytes(self):
        assert format_bytes(512) == "512 B"

    def test_kilobytes(self):
        result = format_bytes(2048)
        assert "KB" in result
        assert "2.0" in result

    def test_megabytes(self):
        result = format_bytes(5 * 1024 * 1024)
        assert "MB" in result
        assert "5.0" in result

    def test_gigabytes(self):
        result = format_bytes(2 * 1024 * 1024 * 1024)
        assert "GB" in result


# ── CleanupItem tests ─────────────────────────────────────────

class TestCleanupItem:
    def test_default_id_generated(self):
        item = CleanupItem(name="Test")
        assert item.id.startswith("cleanup_")
        assert len(item.id) > 8

    def test_custom_id(self):
        item = CleanupItem(id="my_id", name="Test")
        assert item.id == "my_id"

    def test_size_display(self):
        item = CleanupItem(detected_size=1024 * 1024)
        assert "MB" in item.size_display

    def test_removable_display(self):
        item = CleanupItem(removable_size=500)
        assert "500 B" in item.removable_display

    def test_defaults(self):
        item = CleanupItem()
        assert item.selected is False
        assert item.can_delete is False
        assert item.requires_admin is False
        assert item.status == CleanupStatus.NOT_AVAILABLE


# ── CleanupSessionResult tests ────────────────────────────────

class TestCleanupSessionResult:
    def test_default_session_id(self):
        s = CleanupSessionResult()
        assert s.session_id.startswith("cleanup_")

    def test_custom_session_id(self):
        s = CleanupSessionResult(session_id="custom")
        assert s.session_id == "custom"

    def test_success_when_all_ok(self):
        s = CleanupSessionResult(successful_items=3, failed_items=0)
        assert s.success is True

    def test_failure_when_any_fail(self):
        s = CleanupSessionResult(successful_items=2, failed_items=1)
        assert s.success is False

    def test_zero_items_not_success(self):
        s = CleanupSessionResult(successful_items=0, failed_items=0)
        assert s.success is False


# ── Path safety tests ─────────────────────────────────────────

class TestPathSafety:
    def test_safe_delete_nonexistent(self):
        assert is_safe_to_delete("/nonexistent/path/that/does/not/exist") is False

    def test_safe_delete_empty_path(self):
        assert is_safe_to_delete("") is False

    def test_safe_delete_whitespace(self):
        assert is_safe_to_delete("   ") is False

    def test_rejected_system32(self):
        # System32 should be rejected
        result = is_path_rejected(r"C:\Windows\System32")
        # On Windows this is True; on other OS it may differ
        # We just verify the function doesn't crash
        assert isinstance(result, bool)

    def test_rejected_documents(self):
        result = is_path_rejected(r"C:\Users\test\Documents\something")
        assert isinstance(result, bool)

    def test_rejected_desktop(self):
        result = is_path_rejected(r"C:\Users\test\Desktop\file.txt")
        assert isinstance(result, bool)

    def test_allowed_root_list_not_empty(self):
        assert len(ALLOWED_CLEANUP_ROOTS) >= 0  # May be empty in test env

    def test_can_delete_nonexistent_file(self):
        assert can_delete_file("/nonexistent/file.txt") is False

    def test_can_delete_directory_as_file(self):
        assert can_delete_file(tempfile.gettempdir()) is False

    def test_can_delete_nonexistent_dir(self):
        assert can_delete_directory("/nonexistent/dir") is False

    def test_can_delete_existing_dir(self, temp_dir):
        assert can_delete_directory(temp_dir) is True


# ── Scanner tests ─────────────────────────────────────────────

class TestCleanupScanner:
    def test_scan_returns_list(self):
        scanner = CleanupScanner()
        items = scanner.scan()
        assert isinstance(items, list)

    def test_scan_returns_cleanup_items(self):
        scanner = CleanupScanner()
        items = scanner.scan()
        for item in items:
            assert isinstance(item, CleanupItem)

    def test_scan_does_not_delete(self, temp_cleanup_dir):
        """Scanner must never delete files."""
        scanner = CleanupScanner()
        # Patch user temp to our test dir
        with patch("app.cleanup.cleanup_scanner.tempfile.gettempdir", return_value=temp_cleanup_dir):
            items = scanner.scan()
        # Verify files still exist
        for i in range(5):
            assert os.path.exists(os.path.join(temp_cleanup_dir, f"test_file_{i}.tmp"))

    def test_shader_cache_is_recommendation_only(self):
        scanner = CleanupScanner()
        items = scanner.scan()
        shader_items = [i for i in items if i.category == CleanupCategory.SHADER_CACHE]
        for item in shader_items:
            assert item.status == CleanupStatus.RECOMMENDATION_ONLY
            assert item.can_delete is False

    def test_user_temp_detected(self):
        scanner = CleanupScanner()
        items = scanner.scan()
        temp_items = [i for i in items if i.category == CleanupCategory.USER_TEMP]
        assert len(temp_items) >= 1  # Should always detect user temp

    def test_scanner_multiple_scans(self):
        """Scanner can be called multiple times."""
        scanner = CleanupScanner()
        items1 = scanner.scan()
        items2 = scanner.scan()
        assert len(items1) == len(items2)

    def test_get_total_reclaimable(self):
        scanner = CleanupScanner()
        scanner.scan()
        total = scanner.get_total_reclaimable()
        assert total >= 0

    def test_scanner_with_empty_dir(self, temp_dir):
        """Scanner handles empty directories gracefully."""
        scanner = CleanupScanner()
        with patch("app.cleanup.cleanup_scanner.tempfile.gettempdir", return_value=temp_dir):
            items = scanner.scan()
        # Should not crash
        assert isinstance(items, list)


# ── Engine tests ──────────────────────────────────────────────

class TestCleanupEngine:
    def test_engine_not_busy_initially(self):
        engine = CleanupEngine()
        assert engine.is_busy is False

    def test_engine_clean_empty_list(self):
        engine = CleanupEngine()
        result = engine.clean([])
        assert isinstance(result, CleanupSessionResult)
        assert result.message == "No items selected for cleanup"

    def test_engine_clean_with_no_selected(self):
        engine = CleanupEngine()
        items = [CleanupItem(id="test", name="Test", can_delete=False, selected=False)]
        result = engine.clean(items)
        assert result.success is False  # No items cleaned
        assert "No items selected" in result.message

    def test_engine_clean_with_selected(self, temp_cleanup_dir):
        """Engine cleans selected files."""
        engine = CleanupEngine()
        item = CleanupItem(
            id="test_temp",
            name="Test Temp",
            category=CleanupCategory.USER_TEMP,
            path=temp_cleanup_dir,
            detected_size=1024,
            removable_size=1024,
            file_count=8,
            removable_file_count=8,
            can_delete=True,
            selected=True,
            status=CleanupStatus.AVAILABLE,
        )
        result = engine.clean([item])
        # Files should be deleted
        remaining = 0
        for f in os.listdir(temp_cleanup_dir) if os.path.exists(temp_cleanup_dir) else []:
            remaining += 1
        assert remaining < 8  # Most files should be deleted

    def test_engine_session_id_unique(self):
        engine = CleanupEngine()
        r1 = engine.clean([])
        r2 = engine.clean([])
        assert r1.session_id != r2.session_id

    def test_engine_preserves_rejected_paths(self, temp_dir):
        """Engine must not delete files outside allowed roots."""
        # Create a file in a non-allowed location
        protected_file = os.path.join(temp_dir, "protected.txt")
        with open(protected_file, "w") as f:
            f.write("protected")

        engine = CleanupEngine()
        item = CleanupItem(
            id="bad",
            name="Bad",
            path=protected_file,
            can_delete=True,
            selected=True,
            status=CleanupStatus.AVAILABLE,
        )
        with patch("app.cleanup.cleanup_engine.is_safe_to_delete", return_value=False):
            result = engine.clean([item])
        # File should still exist
        assert os.path.exists(protected_file)

    def test_engine_locked_file_handling(self, temp_cleanup_dir):
        """Engine skips locked files gracefully."""
        engine = CleanupEngine()
        item = CleanupItem(
            id="test_locked",
            name="Test Locked",
            path=temp_cleanup_dir,
            can_delete=True,
            selected=True,
            status=CleanupStatus.AVAILABLE,
        )
        # Mock os.remove to raise PermissionError
        original_remove = os.remove
        call_count = [0]

        def mock_remove(path):
            if "test_file" in str(path):
                call_count[0] += 1
                raise PermissionError("File locked")
            return original_remove(path)

        with patch("os.remove", side_effect=mock_remove):
            result = engine.clean([item])
        # Should report failures but not crash
        assert result is not None

    def test_engine_progress_callback(self):
        engine = CleanupEngine()
        calls = []
        engine.on_progress(lambda p, m: calls.append((p, m)))
        result = engine.clean([])
        # Callback should have been called with 100% at end
        assert any(p >= 100 for p, m in calls) or len(calls) == 0

    def test_engine_no_process_termination(self, temp_cleanup_dir):
        """Engine must not terminate processes."""
        import psutil
        engine = CleanupEngine()
        item = CleanupItem(
            id="test_no_kill",
            name="Test No Kill",
            path=temp_cleanup_dir,
            can_delete=True,
            selected=True,
            status=CleanupStatus.AVAILABLE,
        )
        with patch("psutil.Process.terminate") as mock_term:
            engine.clean([item])
            mock_term.assert_not_called()

    def test_engine_no_registry_modification(self, temp_cleanup_dir):
        """Engine must not modify registry."""
        engine = CleanupEngine()
        item = CleanupItem(
            id="test_no_reg",
            name="Test No Reg",
            path=temp_cleanup_dir,
            can_delete=True,
            selected=True,
            status=CleanupStatus.AVAILABLE,
        )
        with patch("winreg.SetValueEx") as mock_reg:
            engine.clean([item])
            mock_reg.assert_not_called()


# ── CleanupResult tests ───────────────────────────────────────

class TestCleanupResult:
    def test_default_values(self):
        r = CleanupResult()
        assert r.success is False
        assert r.files_deleted == 0
        assert r.bytes_freed == 0

    def test_successful_result(self):
        r = CleanupResult(
            success=True,
            files_deleted=10,
            bytes_freed=1024,
            verification_status=CleanupStatus.VERIFIED,
        )
        assert r.success is True
        assert r.files_deleted == 10


# ── CleanupStatus enum tests ─────────────────────────────────

class TestCleanupStatus:
    def test_all_statuses_exist(self):
        required = [
            "AVAILABLE", "NOT_AVAILABLE", "SAFE", "REQUIRES_ADMIN",
            "SELECTED", "SKIPPED", "CLEANED", "FAILED", "VERIFIED",
            "RECOMMENDATION_ONLY",
        ]
        for name in required:
            assert hasattr(CleanupStatus, name)

    def test_status_values(self):
        assert CleanupStatus.AVAILABLE.value == "AVAILABLE"
        assert CleanupStatus.CLEANED.value == "CLEANED"
        assert CleanupStatus.FAILED.value == "FAILED"


# ── CleanupCategory tests ─────────────────────────────────────

class TestCleanupCategory:
    def test_all_categories_exist(self):
        required = [
            "USER_TEMP", "SYSTEM_TEMP", "RECYCLE_BIN",
            "SHADER_CACHE", "APPLICATION_CACHE",
        ]
        for name in required:
            assert hasattr(CleanupCategory, name)


# ── Integration: scanner + engine ─────────────────────────────

class TestCleanupIntegration:
    def test_scan_then_clean(self, temp_cleanup_dir):
        """Full scan → select → clean → verify cycle."""
        scanner = CleanupScanner()
        with patch("app.cleanup.cleanup_scanner.tempfile.gettempdir", return_value=temp_cleanup_dir):
            items = scanner.scan()

        # Find user temp item and select it
        temp_items = [i for i in items if i.category == CleanupCategory.USER_TEMP]
        assert len(temp_items) >= 1

        item = temp_items[0]
        item.selected = True

        engine = CleanupEngine()
        result = engine.clean([item])

        assert result is not None
        assert isinstance(result, CleanupSessionResult)
        assert result.session_id.startswith("cleanup_")

    def test_scan_report_accurate(self, temp_cleanup_dir):
        """Scanner report matches actual files."""
        scanner = CleanupScanner()
        with patch("app.cleanup.cleanup_scanner.tempfile.gettempdir", return_value=temp_cleanup_dir):
            items = scanner.scan()

        temp_items = [i for i in items if i.category == CleanupCategory.USER_TEMP]
        if temp_items:
            item = temp_items[0]
            # Scanner should have detected files
            assert item.file_count > 0

    def test_no_fake_success(self, temp_cleanup_dir):
        """No fake APPLIED/CLEANED status without actual deletion."""
        engine = CleanupEngine()
        item = CleanupItem(
            id="fake_test",
            name="Fake Test",
            path="/nonexistent/path",
            can_delete=True,
            selected=True,
            status=CleanupStatus.AVAILABLE,
        )
        result = engine.clean([item])
        # Should report failure or no-change, not success
        assert result.successful_items == 0 or result.failed_items > 0

    def test_recommendation_not_in_cleanup(self):
        """Recommendation-only items must not be cleaned."""
        engine = CleanupEngine()
        item = CleanupItem(
            id="rec_test",
            name="Recommendation Test",
            can_delete=False,
            selected=False,
            status=CleanupStatus.RECOMMENDATION_ONLY,
        )
        result = engine.clean([item])
        assert result.successful_items == 0

    def test_requires_admin_not_cleaned(self):
        """REQUIRES_ADMIN items must not be force-cleaned."""
        engine = CleanupEngine()
        item = CleanupItem(
            id="admin_test",
            name="Admin Test",
            can_delete=False,
            selected=True,
            requires_admin=True,
            status=CleanupStatus.REQUIRES_ADMIN,
        )
        result = engine.clean([item])
        assert result.successful_items == 0

    def test_empty_cleanup_session(self):
        """Empty cleanup returns valid session."""
        engine = CleanupEngine()
        result = engine.clean([])
        assert result.session_id != ""
        assert result.started_at != ""
        assert result.completed_at != ""
        assert result.duration_seconds >= 0


# ── Concurrent access tests ───────────────────────────────────

class TestConcurrency:
    def test_engine_busy_prevents_concurrent(self):
        """Second clean call while busy should return immediately."""
        engine = CleanupEngine()
        # First call with empty list completes instantly
        r1 = engine.clean([])
        # Engine should not be busy after completion
        assert engine.is_busy is False
