"""
Tests for Heaven Society — Shader Cache Manager.

Uses temporary directories; never modifies real shader caches.
"""

import os
import sys
import time
import tempfile
import shutil
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.system.shader_cache import (
    ShaderCacheManager,
    ShaderCacheInfo,
    ShaderCacheDiagnostics,
    ShaderCacheCleanupResult,
    ShaderCacheStatus,
    ShaderCacheType,
    shader_cache_manager,
    SHADER_CACHE_PATHS,
    _format_bytes,
)


# ══════════════════════════════════════════════════════════════
# 1. Data Models
# ══════════════════════════════════════════════════════════════

class TestModels:
    """Test shader cache data models."""

    def test_cache_info_defaults(self):
        info = ShaderCacheInfo()
        assert info.exists is False
        assert info.file_count == 0
        assert info.total_size_bytes == 0
        assert info.can_cleanup is False

    def test_cache_info_display(self):
        info = ShaderCacheInfo(
            total_size_bytes=1024 * 1024 * 5,
            oldest_file_time=time.time() - 86400,
            newest_file_time=time.time(),
            last_modified_time=time.time(),
        )
        assert "MB" in info.total_size_display
        assert "N/A" not in info.oldest_file_display
        assert "N/A" not in info.newest_file_display

    def test_cache_info_zero_time(self):
        info = ShaderCacheInfo(oldest_file_time=0, newest_file_time=0)
        assert info.oldest_file_display == "N/A"
        assert info.newest_file_display == "N/A"

    def test_diagnostics_defaults(self):
        diag = ShaderCacheDiagnostics()
        assert len(diag.caches) == 0
        assert diag.detected_count == 0
        assert diag.timestamp == 0.0

    def test_cleanup_result_defaults(self):
        result = ShaderCacheCleanupResult()
        assert result.files_deleted == 0
        assert result.bytes_freed == 0
        assert result.success is False

    def test_cleanup_result_display(self):
        result = ShaderCacheCleanupResult(bytes_freed=1024 * 1024)
        assert "MB" in result.bytes_freed_display

    def test_status_values(self):
        values = [s.value for s in ShaderCacheStatus]
        assert "DETECTED" in values
        assert "NOT_FOUND" in values
        assert "EMPTY" in values
        assert "CLEANED" in values
        assert "FAILED" in values
        assert "RECOMMENDATION_ONLY" in values

    def test_cache_type_values(self):
        values = [c.value for c in ShaderCacheType]
        assert "NVIDIA DXCache" in values
        assert "NVIDIA GLCache" in values
        assert "AMD DXCache" in values
        assert "DirectX Pipeline Cache" in values


# ══════════════════════════════════════════════════════════════
# 2. Format Bytes
# ══════════════════════════════════════════════════════════════

class TestFormatBytes:
    """Test byte formatting."""

    def test_zero(self):
        assert _format_bytes(0) == "0 B"

    def test_negative(self):
        assert _format_bytes(-100) == "0 B"

    def test_bytes(self):
        assert _format_bytes(500) == "500 B"

    def test_kilobytes(self):
        assert "KB" in _format_bytes(5000)

    def test_megabytes(self):
        assert "MB" in _format_bytes(5 * 1024 * 1024)

    def test_gigabytes(self):
        assert "GB" in _format_bytes(5 * 1024 * 1024 * 1024)


# ══════════════════════════════════════════════════════════════
# 3. Detection — Real Filesystem (Temporary Dirs)
# ══════════════════════════════════════════════════════════════

class TestDetection:
    """Test shader cache detection with temporary directories."""

    def setup_method(self):
        self.manager = ShaderCacheManager()
        self.tmpdir = tempfile.mkdtemp()

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_nonexistent_path_returns_not_found(self):
        info = self.manager._inspect_cache(
            ShaderCacheType.NVIDIA_DX,
            os.path.join(self.tmpdir, "nonexistent")
        )
        assert info.status == ShaderCacheStatus.NOT_FOUND
        assert info.exists is False
        assert info.file_count == 0

    def test_empty_directory_returns_empty(self):
        cache_dir = os.path.join(self.tmpdir, "DXCache")
        os.makedirs(cache_dir)
        info = self.manager._inspect_cache(ShaderCacheType.NVIDIA_DX, cache_dir)
        assert info.status == ShaderCacheStatus.EMPTY
        assert info.exists is True
        assert info.file_count == 0

    def test_directory_with_files_returns_detected(self):
        cache_dir = os.path.join(self.tmpdir, "DXCache")
        os.makedirs(cache_dir)
        # Create some fake shader cache files
        for i in range(5):
            fp = os.path.join(cache_dir, f"shader_{i}.bin")
            with open(fp, "wb") as f:
                f.write(os.urandom(1024 * (i + 1)))

        info = self.manager._inspect_cache(ShaderCacheType.NVIDIA_DX, cache_dir)
        assert info.status == ShaderCacheStatus.DETECTED
        assert info.exists is True
        assert info.file_count == 5
        assert info.total_size_bytes > 0
        assert info.oldest_file_time > 0
        assert info.newest_file_time > 0
        assert "recompilation" in info.recompilation_warning.lower()

    def test_oldest_newest_times_correct(self):
        cache_dir = os.path.join(self.tmpdir, "GLCache")
        os.makedirs(cache_dir)
        # Create files with different timestamps
        fp1 = os.path.join(cache_dir, "old.bin")
        fp2 = os.path.join(cache_dir, "new.bin")
        with open(fp1, "wb") as f:
            f.write(b"old")
        with open(fp2, "wb") as f:
            f.write(b"new")
        # Set old timestamp
        old_time = time.time() - 86400
        os.utime(fp1, (old_time, old_time))

        info = self.manager._inspect_cache(ShaderCacheType.NVIDIA_GL, cache_dir)
        assert info.file_count == 2
        assert info.oldest_file_time <= info.newest_file_time


# ══════════════════════════════════════════════════════════════
# 4. Full Diagnostics
# ══════════════════════════════════════════════════════════════

class TestFullDiagnostics:
    """Test complete diagnostics pipeline."""

    def setup_method(self):
        self.manager = ShaderCacheManager()

    def test_diagnose_returns_structured_result(self):
        diag = self.manager.diagnose(force=True)
        assert isinstance(diag, ShaderCacheDiagnostics)
        assert len(diag.caches) > 0  # Should have entries for known paths
        assert diag.timestamp > 0

    def test_diagnose_caches_results(self):
        r1 = self.manager.diagnose(force=False)
        r2 = self.manager.diagnose(force=False)
        assert r1 is r2

    def test_force_refresh(self):
        r1 = self.manager.diagnose(force=True)
        self.manager._cache_ttl = 0
        r2 = self.manager.diagnose(force=True)
        assert r1 is not r2

    def test_recommendation_populated(self):
        diag = self.manager.diagnose(force=True)
        assert isinstance(diag.recommendation, str)
        assert len(diag.recommendation) > 0


# ══════════════════════════════════════════════════════════════
# 5. Cleanup — Safe Deletion
# ══════════════════════════════════════════════════════════════

class TestCleanup:
    """Test shader cache cleanup with temporary directories."""

    def setup_method(self):
        self.manager = ShaderCacheManager()
        self.tmpdir = tempfile.mkdtemp()
        # Create fake cache
        self.cache_dir = os.path.join(self.tmpdir, "NVIDIA", "DXCache")
        os.makedirs(self.cache_dir)
        for i in range(3):
            fp = os.path.join(self.cache_dir, f"cache_{i}.bin")
            with open(fp, "wb") as f:
                f.write(os.urandom(1024))

    def teardown_method(self):
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_cleanup_deletes_files(self):
        import app.system.shader_cache as mod
        original = mod.SHADER_CACHE_PATHS.copy()
        mod.SHADER_CACHE_PATHS = [
            (ShaderCacheType.NVIDIA_DX, self.cache_dir),
        ]
        try:
            result = self.manager.cleanup_cache(ShaderCacheType.NVIDIA_DX)
            assert result.success is True
            assert result.files_deleted == 3
            assert result.bytes_freed > 0
            assert result.verification_passed is True
        finally:
            mod.SHADER_CACHE_PATHS = original

    def test_cleanup_nonexistent_cache(self):
        import app.system.shader_cache as mod
        original = mod.SHADER_CACHE_PATHS.copy()
        fake_path = os.path.join(self.tmpdir, "nonexistent")
        mod.SHADER_CACHE_PATHS = [
            (ShaderCacheType.NVIDIA_DX, fake_path),
        ]
        try:
            result = self.manager.cleanup_cache(ShaderCacheType.NVIDIA_DX)
            assert result.success is False
            assert "not found" in result.message.lower()
        finally:
            mod.SHADER_CACHE_PATHS = original

    def test_cleanup_invalidates_cache(self):
        # Mock the paths to use our temp dir
        original_paths = SHADER_CACHE_PATHS.copy()
        try:
            import app.system.shader_cache as mod
            mod.SHADER_CACHE_PATHS = [
                (ShaderCacheType.NVIDIA_DX, self.cache_dir),
            ]
            self.manager._cache = "something"

            self.manager.cleanup_cache(ShaderCacheType.NVIDIA_DX)
            assert self.manager._cache is None  # Cache invalidated
        finally:
            mod.SHADER_CACHE_PATHS = original_paths


# ══════════════════════════════════════════════════════════════
# 6. Safety Rules
# ══════════════════════════════════════════════════════════════

class TestSafety:
    """Test safety rules — no auto-cleanup, no dangerous operations."""

    def test_manager_not_auto_cleaning(self):
        """The manager should never auto-clean during diagnose()."""
        import inspect
        source = inspect.getsource(ShaderCacheManager.diagnose)
        assert "os.remove" not in source
        assert "shutil.rmtree" not in source

    def test_cleanup_requires_explicit_call(self):
        """cleanup_cache must be called explicitly, never from diagnose."""
        import inspect
        diag_source = inspect.getsource(ShaderCacheManager.diagnose)
        assert "cleanup_cache" not in diag_source

    def test_all_caches_default_recommendation_only(self):
        manager = ShaderCacheManager()
        diag = manager.diagnose(force=True)
        for info in diag.caches:
            if info.exists:
                # can_cleanup should be False by default
                assert info.can_cleanup is False

    def test_no_fake_recompilation_times(self):
        """No fabricated recompilation duration claims."""
        manager = ShaderCacheManager()
        diag = manager.diagnose(force=True)
        for info in diag.caches:
            if info.recompilation_warning:
                # Should not claim exact FPS improvements
                assert "fps" not in info.recompilation_warning.lower()
                assert "boost" not in info.recompilation_warning.lower()

    def test_no_process_termination(self):
        """Cleanup should never terminate processes."""
        import inspect
        source = inspect.getsource(ShaderCacheManager)
        assert "psutil.Process" not in source or "terminate" not in source
        assert ".kill()" not in source


# ══════════════════════════════════════════════════════════════
# 7. Singleton
# ══════════════════════════════════════════════════════════════

class TestSingleton:
    """Test shader_cache_manager singleton."""

    def test_singleton_exists(self):
        assert shader_cache_manager is not None
        assert isinstance(shader_cache_manager, ShaderCacheManager)

    def test_singleton_is_same(self):
        from app.system.shader_cache import shader_cache_manager as scm2
        assert shader_cache_manager is scm2


# ══════════════════════════════════════════════════════════════
# 8. Cache Path Configuration
# ══════════════════════════════════════════════════════════════

class TestCachePaths:
    """Test shader cache path configuration."""

    def test_known_paths_defined(self):
        assert len(SHADER_CACHE_PATHS) >= 3

    def test_nvidia_dx_in_paths(self):
        types = [ct for ct, _ in SHADER_CACHE_PATHS]
        assert ShaderCacheType.NVIDIA_DX in types

    def test_nvidia_gl_in_paths(self):
        types = [ct for ct, _ in SHADER_CACHE_PATHS]
        assert ShaderCacheType.NVIDIA_GL in types

    def test_amd_dx_in_paths(self):
        types = [ct for ct, _ in SHADER_CACHE_PATHS]
        assert ShaderCacheType.AMD_DX in types


# ══════════════════════════════════════════════════════════════
# 9. Edge Cases
# ══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self):
        self.manager = ShaderCacheManager()

    def test_empty_path(self):
        info = self.manager._inspect_cache(ShaderCacheType.NVIDIA_DX, "")
        assert info.status == ShaderCacheStatus.NOT_FOUND

    def test_none_path(self):
        info = self.manager._inspect_cache(ShaderCacheType.NVIDIA_DX, None)
        assert info.status == ShaderCacheStatus.NOT_FOUND

    def test_large_file_count(self):
        """Test with many files."""
        tmpdir = tempfile.mkdtemp()
        try:
            cache_dir = os.path.join(tmpdir, "cache")
            os.makedirs(cache_dir)
            for i in range(100):
                with open(os.path.join(cache_dir, f"f{i}.bin"), "wb") as f:
                    f.write(b"x" * 100)

            info = self.manager._inspect_cache(ShaderCacheType.NVIDIA_DX, cache_dir)
            assert info.file_count == 100
            assert info.total_size_bytes == 100 * 100
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_cleanup_empty_directory(self):
        """Cleanup of empty directory should succeed."""
        tmpdir = tempfile.mkdtemp()
        try:
            cache_dir = os.path.join(tmpdir, "empty_cache")
            os.makedirs(cache_dir)

            import app.system.shader_cache as mod
            original = mod.SHADER_CACHE_PATHS.copy()
            mod.SHADER_CACHE_PATHS = [
                (ShaderCacheType.NVIDIA_DX, cache_dir),
            ]
            try:
                result = self.manager.cleanup_cache(ShaderCacheType.NVIDIA_DX)
                # Empty directory — no files deleted but no failure
                assert result.files_deleted == 0
            finally:
                mod.SHADER_CACHE_PATHS = original
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)

    def test_top_level_files_only(self):
        """Test that detection scans top-level files only (os.scandir)."""
        tmpdir = tempfile.mkdtemp()
        try:
            cache_dir = os.path.join(tmpdir, "cache")
            sub = os.path.join(cache_dir, "sub")
            os.makedirs(sub)
            with open(os.path.join(sub, "file.bin"), "wb") as f:
                f.write(b"test")
            # Also create a top-level file
            with open(os.path.join(cache_dir, "top.bin"), "wb") as f:
                f.write(b"top")

            info = self.manager._inspect_cache(ShaderCacheType.NVIDIA_DX, cache_dir)
            # os.scandir only sees top-level files
            assert info.file_count == 1
            assert info.exists is True
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
