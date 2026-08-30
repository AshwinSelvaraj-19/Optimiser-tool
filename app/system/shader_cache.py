"""
Shader Cache Manager — Safe NVIDIA/DirectX shader-cache diagnostics and controlled cleanup.

Provides:
- Detection of NVIDIA DXCache, NVIDIA GLCache, AMD DXCache, DirectX pipeline cache
- Detailed metrics: file count, total size, oldest/newest file, last modified
- Explanations of recompilation/stutter impact
- DEFAULT = recommendation-only
- Optional explicit cleanup through the existing CLEANUP engine
- Re-scan after cleanup to verify state

All analysis is READ-ONLY by default.
Explicit cleanup requires user action (never automatic).
"""

import os
import time
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from enum import Enum

from app.utils.logger import get_logger

logger = get_logger("system.shader_cache")


class ShaderCacheStatus(Enum):
    """Status of a shader cache."""
    DETECTED = "DETECTED"
    NOT_FOUND = "NOT_FOUND"
    EMPTY = "EMPTY"
    CLEANED = "CLEANED"
    FAILED = "FAILED"
    RECOMMENDATION_ONLY = "RECOMMENDATION_ONLY"


class ShaderCacheType(Enum):
    """Type of shader cache."""
    NVIDIA_DX = "NVIDIA DXCache"
    NVIDIA_GL = "NVIDIA GLCache"
    AMD_DX = "AMD DXCache"
    DIRECTX_PIPELINE = "DirectX Pipeline Cache"


@dataclass
class ShaderCacheInfo:
    """Detailed info about a single shader cache."""
    cache_type: ShaderCacheType = ShaderCacheType.NVIDIA_DX
    name: str = ""
    path: str = ""
    exists: bool = False
    file_count: int = 0
    total_size_bytes: int = 0
    oldest_file_time: float = 0.0  # epoch
    newest_file_time: float = 0.0  # epoch
    last_modified_time: float = 0.0  # epoch
    status: ShaderCacheStatus = ShaderCacheStatus.NOT_FOUND
    can_cleanup: bool = False  # True only when explicitly allowed
    cleanup_safe: bool = True
    recompilation_warning: str = ""
    detection_error: str = ""

    @property
    def total_size_display(self) -> str:
        return _format_bytes(self.total_size_bytes)

    @property
    def oldest_file_display(self) -> str:
        if self.oldest_file_time <= 0:
            return "N/A"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.oldest_file_time))

    @property
    def newest_file_display(self) -> str:
        if self.newest_file_time <= 0:
            return "N/A"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.newest_file_time))

    @property
    def last_modified_display(self) -> str:
        if self.last_modified_time <= 0:
            return "N/A"
        return time.strftime("%Y-%m-%d %H:%M", time.localtime(self.last_modified_time))


@dataclass
class ShaderCacheDiagnostics:
    """Complete shader cache diagnostics."""
    caches: List[ShaderCacheInfo] = field(default_factory=list)
    total_size_bytes: int = 0
    total_files: int = 0
    detected_count: int = 0
    recommendation: str = ""
    timestamp: float = 0.0


@dataclass
class ShaderCacheCleanupResult:
    """Result of a shader cache cleanup operation."""
    cache_name: str = ""
    path: str = ""
    files_deleted: int = 0
    bytes_freed: int = 0
    files_failed: int = 0
    duration_seconds: float = 0.0
    success: bool = False
    message: str = ""
    verification_passed: bool = False

    @property
    def bytes_freed_display(self) -> str:
        return _format_bytes(self.bytes_freed)


def _format_bytes(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes < 0:
        return "0 B"
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    else:
        return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


# ── Known shader cache locations ───────────────────────────────

SHADER_CACHE_PATHS = [
    (ShaderCacheType.NVIDIA_DX, os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "NVIDIA", "DXCache"
    )),
    (ShaderCacheType.NVIDIA_GL, os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "NVIDIA", "GLCache"
    )),
    (ShaderCacheType.AMD_DX, os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "AMD", "DXCache"
    )),
    (ShaderCacheType.DIRECTX_PIPELINE, os.path.join(
        os.environ.get("LOCALAPPDATA", ""), "Microsoft", "D3DSCache"
    )),
]


# ── Core Analyzer ──────────────────────────────────────────────

class ShaderCacheManager:
    """
    Shader cache diagnostics and controlled cleanup.
    DEFAULT = recommendation-only. Never auto-cleans.
    """

    def __init__(self):
        self._cache: Optional[ShaderCacheDiagnostics] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 10.0

    def diagnose(self, force: bool = False) -> ShaderCacheDiagnostics:
        """
        Full shader cache diagnostics.
        Returns detailed info about all detected caches.
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        diag = ShaderCacheDiagnostics(timestamp=now)

        for cache_type, path in SHADER_CACHE_PATHS:
            info = self._inspect_cache(cache_type, path)
            diag.caches.append(info)
            if info.exists:
                diag.detected_count += 1
                diag.total_size_bytes += info.total_size_bytes
                diag.total_files += info.file_count

        diag.recommendation = self._build_recommendation(diag)

        self._cache = diag
        self._cache_time = now
        return diag

    def _inspect_cache(
        self, cache_type: ShaderCacheType, path: str
    ) -> ShaderCacheInfo:
        """Inspect a single shader cache location."""
        info = ShaderCacheInfo(
            cache_type=cache_type,
            name=cache_type.value,
            path=path,
        )

        if not path or not os.path.isdir(path):
            info.status = ShaderCacheStatus.NOT_FOUND
            info.recompilation_warning = (
                "Cache not found — no action needed."
            )
            return info

        info.exists = True

        # Scan files
        total_size = 0
        file_count = 0
        oldest_time = float("inf")
        newest_time = 0.0
        last_modified = 0.0

        try:
            for entry in os.scandir(path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        file_count += 1
                        stat = entry.stat()
                        total_size += stat.st_size
                        mtime = stat.st_mtime
                        oldest_time = min(oldest_time, mtime)
                        newest_time = max(newest_time, mtime)
                        last_modified = max(last_modified, mtime)
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError) as e:
            info.detection_error = str(e)
            info.status = ShaderCacheStatus.FAILED
            info.recompilation_warning = f"Cannot scan cache: {e}"
            return info

        info.file_count = file_count
        info.total_size_bytes = total_size
        info.oldest_file_time = oldest_time if oldest_time != float("inf") else 0
        info.newest_file_time = newest_time
        info.last_modified_time = last_modified

        if file_count == 0:
            info.status = ShaderCacheStatus.EMPTY
            info.recompilation_warning = "Cache directory exists but is empty."
        else:
            info.status = ShaderCacheStatus.DETECTED
            info.recompilation_warning = (
                "Clearing this cache will force shader recompilation on next game launch. "
                "This can cause 1-3 minutes of stuttering/stutter as shaders rebuild. "
                "Only recommended when experiencing shader-related visual artifacts or crashes."
            )

        return info

    def _build_recommendation(self, diag: ShaderCacheDiagnostics) -> str:
        """Build overall recommendation."""
        if diag.detected_count == 0:
            return "No shader caches detected."

        parts = []
        for info in diag.caches:
            if info.exists and info.file_count > 0:
                parts.append(
                    f"{info.name}: {_format_bytes(info.total_size_bytes)}, "
                    f"{info.file_count} files"
                )

        if not parts:
            return "Shader caches detected but empty."

        return (
            f"Found {diag.detected_count} shader cache(es) totaling "
            f"{_format_bytes(diag.total_size_bytes)}. "
            "Clearing is RECOMMENDATION ONLY — "
            "expect 1-3 minutes of shader recompilation stutter on next game launch."
        )

    def cleanup_cache(
        self, cache_type: ShaderCacheType
    ) -> ShaderCacheCleanupResult:
        """
        Clean a specific shader cache.
        This is an EXPLICIT action — never called automatically.
        Uses safe deletion with retry for locked files.
        """
        result = ShaderCacheCleanupResult()
        start_time = time.time()

        # Find the cache path
        target_path = None
        for ct, path in SHADER_CACHE_PATHS:
            if ct == cache_type:
                target_path = path
                break

        if not target_path or not os.path.isdir(target_path):
            result.message = f"Cache not found: {cache_type.value}"
            return result

        result.cache_name = cache_type.value
        result.path = target_path

        # Safety check: must be in allowed cleanup root
        from app.cleanup.cleanup_safety import is_safe_to_delete, validate_path_security
        safe, reason = validate_path_security(target_path)
        if not safe:
            result.message = f"Path not safe to delete: {reason}"
            return result

        # Delete files with retry
        files_deleted = 0
        bytes_freed = 0
        files_failed = 0

        # Walk bottom-up
        for root, dirs, files in os.walk(target_path, topdown=False):
            for f in files:
                fp = os.path.join(root, f)
                try:
                    size = os.path.getsize(fp)
                except OSError:
                    size = 0

                deleted = self._safe_delete_file(fp)
                if deleted:
                    files_deleted += 1
                    bytes_freed += size
                else:
                    files_failed += 1

            # Remove empty directories
            for d in dirs:
                dp = os.path.join(root, d)
                try:
                    if os.path.isdir(dp) and not os.listdir(dp):
                        os.rmdir(dp)
                except OSError:
                    pass

        # Try to remove top-level directory if empty
        try:
            if os.path.isdir(target_path) and not os.listdir(target_path):
                os.rmdir(target_path)
        except OSError:
            pass

        result.files_deleted = files_deleted
        result.bytes_freed = bytes_freed
        result.files_failed = files_failed
        result.duration_seconds = time.time() - start_time
        result.success = files_failed == 0 and files_deleted > 0

        if result.success:
            result.message = (
                f"Deleted {files_deleted} files ({_format_bytes(bytes_freed)}). "
                f"Expect shader recompilation on next game launch."
            )
        elif files_deleted > 0:
            result.message = (
                f"Deleted {files_deleted} files, {files_failed} failed (locked). "
                f"Some cached shaders remain."
            )
        else:
            result.message = f"All {files_failed} files locked or in use."

        # Verify
        result.verification_passed = self._verify_cleanup(target_path)

        # Invalidate cache so next diagnose() rescans
        self._cache = None

        return result

    def _safe_delete_file(self, filepath: str) -> bool:
        """Delete a single file with retry for locked files."""
        from app.cleanup.cleanup_safety import is_safe_to_delete
        if not is_safe_to_delete(filepath):
            return False

        for attempt in range(3):
            try:
                os.remove(filepath)
                return True
            except PermissionError:
                if attempt < 2:
                    time.sleep(0.3)
                else:
                    return False
            except FileNotFoundError:
                return True
            except OSError:
                return False
        return False

    def _verify_cleanup(self, path: str) -> bool:
        """Verify cleanup by checking if cache is empty or gone."""
        if not os.path.exists(path):
            return True  # Directory removed entirely
        try:
            remaining = sum(1 for _ in os.scandir(path))
            return remaining == 0
        except (OSError, PermissionError):
            return False


# Singleton
shader_cache_manager = ShaderCacheManager()
