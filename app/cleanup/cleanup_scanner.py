"""
Cleanup scanner — READ-ONLY analysis of cleanup targets.

The scanner NEVER deletes files. It only detects and measures.
"""

import os
import shutil
import tempfile
from pathlib import Path
from typing import List, Optional

from app.cleanup.cleanup_models import (
    CleanupItem,
    CleanupCategory,
    CleanupStatus,
    format_bytes,
)
from app.cleanup.cleanup_safety import (
    is_safe_to_delete,
    can_delete_file,
    ALLOWED_CLEANUP_ROOTS,
)
from app.utils.logger import get_logger

logger = get_logger("cleanup.scanner")

# Minimum file age to consider for cleanup (0 = any age)
MIN_FILE_AGE_DAYS = 0


class CleanupScanner:
    """Read-only scanner for cleanup targets."""

    def __init__(self):
        self._items: List[CleanupItem] = []

    def scan(self) -> List[CleanupItem]:
        """
        Perform a complete scan of all cleanup targets.
        Returns detected items without deleting anything.
        """
        logger.info("[CLEANUP] Starting scan...")
        self._items = []

        self._scan_user_temp()
        self._scan_system_temp()
        self._scan_shader_cache()
        self._scan_thumbnail_cache()
        self._scan_browser_cache()

        total_size = sum(i.detected_size for i in self._items)
        total_removable = sum(i.removable_size for i in self._items)
        total_files = sum(i.file_count for i in self._items)
        removable_files = sum(i.removable_file_count for i in self._items)

        logger.info(
            f"[CLEANUP] Scan complete: {len(self._items)} targets, "
            f"{format_bytes(total_size)} total, "
            f"{format_bytes(total_removable)} removable, "
            f"{removable_files}/{total_files} files removable"
        )

        return self._items

    def get_total_reclaimable(self) -> int:
        """Get total reclaimable bytes from last scan."""
        return sum(i.removable_size for i in self._items if i.selected)

    def get_total_reclaimable_files(self) -> int:
        """Get total removable files from last scan."""
        return sum(i.removable_file_count for i in self._items if i.selected)

    def _scan_user_temp(self):
        """Scan the user's TEMP directory."""
        user_temp = tempfile.gettempdir()
        if not user_temp or not os.path.isdir(user_temp):
            return

        item = CleanupItem(
            id="user_temp",
            name="User Temp",
            category=CleanupCategory.USER_TEMP,
            description="Temporary files created by applications",
            path=user_temp,
            risk="LOW",
        )

        total_size = 0
        removable_size = 0
        file_count = 0
        removable_count = 0
        skipped_count = 0

        try:
            for entry in os.scandir(user_temp):
                try:
                    if entry.is_file(follow_symlinks=False):
                        file_count += 1
                        try:
                            size = entry.stat().st_size
                        except OSError:
                            skipped_count += 1
                            continue

                        total_size += size

                        filepath = entry.path
                        if can_delete_file(filepath):
                            removable_size += size
                            removable_count += 1
                        else:
                            skipped_count += 1

                    elif entry.is_dir(follow_symlinks=False):
                        # Count directory contents
                        dir_size, dir_removable, dir_files, dir_removable_f, dir_skipped = (
                            self._measure_directory(entry.path)
                        )
                        file_count += dir_files
                        total_size += dir_size
                        removable_size += dir_removable
                        removable_count += dir_removable_f
                        skipped_count += dir_skipped
                except (OSError, PermissionError):
                    skipped_count += 1
        except (OSError, PermissionError) as e:
            logger.debug(f"[CLEANUP] Cannot scan user temp: {e}")
            item.status = CleanupStatus.NOT_AVAILABLE
            item.reason = f"Cannot access: {e}"
            self._items.append(item)
            return

        item.detected_size = total_size
        item.removable_size = removable_size
        item.file_count = file_count
        item.removable_file_count = removable_count
        item.skipped_file_count = skipped_count
        item.available = removable_count > 0
        item.can_delete = removable_count > 0
        item.status = CleanupStatus.AVAILABLE if removable_count > 0 else CleanupStatus.NOT_AVAILABLE
        item.reason = f"{removable_count} removable, {skipped_count} locked/in-use"

        if removable_count == 0 and file_count > 0:
            item.reason = f"All {file_count} files locked or in use"

        self._items.append(item)

    def _scan_system_temp(self):
        """Scan the Windows system TEMP directory."""
        system_temp = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "Temp"
        )
        if not os.path.isdir(system_temp):
            return

        from app.utils.admin import is_admin

        item = CleanupItem(
            id="system_temp",
            name="System Temp",
            category=CleanupCategory.SYSTEM_TEMP,
            description="Windows system temporary files",
            path=system_temp,
            risk="LOW",
        )

        # System temp usually requires admin
        if not is_admin():
            item.requires_admin = True
            item.status = CleanupStatus.REQUIRES_ADMIN
            item.reason = "Administrator privileges required"
            item.can_delete = False
            self._items.append(item)
            return

        total_size = 0
        removable_size = 0
        file_count = 0
        removable_count = 0
        skipped_count = 0

        try:
            for entry in os.scandir(system_temp):
                try:
                    if entry.is_file(follow_symlinks=False):
                        file_count += 1
                        try:
                            size = entry.stat().st_size
                        except OSError:
                            skipped_count += 1
                            continue
                        total_size += size
                        if can_delete_file(entry.path):
                            removable_size += size
                            removable_count += 1
                        else:
                            skipped_count += 1
                    elif entry.is_dir(follow_symlinks=False):
                        d_size, d_rem, d_files, d_rem_f, d_skip = (
                            self._measure_directory(entry.path)
                        )
                        file_count += d_files
                        total_size += d_size
                        removable_size += d_rem
                        removable_count += d_rem_f
                        skipped_count += d_skip
                except (OSError, PermissionError):
                    skipped_count += 1
        except (OSError, PermissionError) as e:
            logger.debug(f"[CLEANUP] Cannot scan system temp: {e}")
            item.status = CleanupStatus.NOT_AVAILABLE
            item.reason = f"Cannot access: {e}"
            self._items.append(item)
            return

        item.detected_size = total_size
        item.removable_size = removable_size
        item.file_count = file_count
        item.removable_file_count = removable_count
        item.skipped_file_count = skipped_count
        item.available = removable_count > 0
        item.can_delete = removable_count > 0
        item.status = CleanupStatus.AVAILABLE if removable_count > 0 else CleanupStatus.NOT_AVAILABLE
        item.reason = f"{removable_count} removable, {skipped_count} locked"

        self._items.append(item)

    def _scan_shader_cache(self):
        """Detect shader cache locations — RECOMMENDATION ONLY, no auto-deletion."""
        shader_paths = []

        # NVIDIA DXCache
        nvidia_dx = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "NVIDIA", "DXCache"
        )
        if nvidia_dx and os.path.isdir(nvidia_dx):
            shader_paths.append(("NVIDIA DXCache", nvidia_dx))

        # NVIDIA GLCache
        nvidia_gl = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "NVIDIA", "GLCache"
        )
        if nvidia_gl and os.path.isdir(nvidia_gl):
            shader_paths.append(("NVIDIA GLCache", nvidia_gl))

        # AMD DXCache
        amd_dx = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "AMD", "DXCache"
        )
        if amd_dx and os.path.isdir(amd_dx):
            shader_paths.append(("AMD DXCache", amd_dx))

        for name, path in shader_paths:
            size = 0
            file_count = 0
            try:
                for root, dirs, files in os.walk(path):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            size += os.path.getsize(fp)
                            file_count += 1
                        except OSError:
                            pass
            except (OSError, PermissionError):
                continue

            if file_count == 0:
                continue

            item = CleanupItem(
                id=f"shader_{name.lower().replace(' ', '_')}",
                name=name,
                category=CleanupCategory.SHADER_CACHE,
                description=(
                    f"GPU shader cache ({format_bytes(size)}).\n"
                    "Clearing may cause temporary shader recompilation/stutter.\n"
                    "Recommended only when troubleshooting shader issues."
                ),
                path=path,
                detected_size=size,
                removable_size=0,  # Not auto-deletable
                file_count=file_count,
                removable_file_count=0,
                risk="MEDIUM",
                available=True,
                selected=False,
                can_delete=False,
                requires_admin=False,
                reason="RECOMMENDATION ONLY — clearing may cause temporary stutter",
                status=CleanupStatus.RECOMMENDATION_ONLY,
            )
            self._items.append(item)

    def _measure_directory(self, dirpath: str) -> tuple:
        """Measure a directory recursively without deleting."""
        total_size = 0
        removable_size = 0
        file_count = 0
        removable_count = 0
        skipped_count = 0

        try:
            for root, dirs, files in os.walk(dirpath):
                for f in files:
                    fp = os.path.join(root, f)
                    file_count += 1
                    try:
                        size = os.path.getsize(fp)
                    except OSError:
                        skipped_count += 1
                        continue
                    total_size += size
                    if can_delete_file(fp):
                        removable_size += size
                        removable_count += 1
                    else:
                        skipped_count += 1
        except (OSError, PermissionError):
            pass

        return total_size, removable_size, file_count, removable_count, skipped_count

    def _scan_thumbnail_cache(self):
        """Scan Windows thumbnail cache — RECOMMENDATION ONLY."""
        thumb_path = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Microsoft", "Windows", "Explorer"
        )
        if not thumb_path or not os.path.isdir(thumb_path):
            return

        size = 0
        file_count = 0
        try:
            for entry in os.scandir(thumb_path):
                try:
                    if entry.is_file(follow_symlinks=False):
                        name_lower = entry.name.lower()
                        if name_lower.startswith("thumbcache_") and name_lower.endswith(".db"):
                            size += entry.stat().st_size
                            file_count += 1
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            return

        if file_count == 0:
            return

        item = CleanupItem(
            id="thumbnail_cache",
            name="Thumbnail Cache",
            category=CleanupCategory.APPLICATION_CACHE,
            description=(
                f"Windows thumbnail cache ({format_bytes(size)}). "
                "Regenerated automatically when browsing folders. "
                "Safe to clear but will cause brief delay on next folder open."
            ),
            path=thumb_path,
            detected_size=size,
            removable_size=0,  # RECOMMENDATION ONLY
            file_count=file_count,
            removable_file_count=0,
            risk="LOW",
            available=True,
            selected=False,
            can_delete=False,
            requires_admin=False,
            reason="RECOMMENDATION ONLY — thumbnails regenerate automatically",
            status=CleanupStatus.RECOMMENDATION_ONLY,
        )
        self._items.append(item)

    def _scan_browser_cache(self):
        """Scan browser cache directories — RECOMMENDATION ONLY."""
        local_app = os.environ.get("LOCALAPPDATA", "")
        app_data = os.environ.get("APPDATA", "")

        browser_paths = []

        # Chrome cache
        chrome_cache = os.path.join(
            local_app, "Google", "Chrome", "User Data", "Default", "Cache"
        )
        if chrome_cache and os.path.isdir(chrome_cache):
            browser_paths.append(("Chrome Cache", chrome_cache))

        # Edge cache
        edge_cache = os.path.join(
            local_app, "Microsoft", "Edge", "User Data", "Default", "Cache"
        )
        if edge_cache and os.path.isdir(edge_cache):
            browser_paths.append(("Edge Cache", edge_cache))

        for name, path in browser_paths:
            size = 0
            file_count = 0
            try:
                for root, dirs, files in os.walk(path):
                    for f in files:
                        fp = os.path.join(root, f)
                        try:
                            size += os.path.getsize(fp)
                            file_count += 1
                        except OSError:
                            continue
                        # Limit scan depth for performance
                        if file_count > 10000:
                            break
                    if file_count > 10000:
                        break
            except (OSError, PermissionError):
                continue

            if file_count == 0:
                continue

            item = CleanupItem(
                id=f"browser_{name.lower().replace(' ', '_')}",
                name=name,
                category=CleanupCategory.APPLICATION_CACHE,
                description=(
                    f"Browser disk cache ({format_bytes(size)}). "
                    "Clearing may temporarily slow page loads until cache rebuilds. "
                    "Only recommended when browser is not in use."
                ),
                path=path,
                detected_size=size,
                removable_size=0,  # RECOMMENDATION ONLY
                file_count=file_count,
                removable_file_count=0,
                risk="LOW",
                available=True,
                selected=False,
                can_delete=False,
                requires_admin=False,
                reason="RECOMMENDATION ONLY — browser cache rebuilds automatically",
                status=CleanupStatus.RECOMMENDATION_ONLY,
            )
            self._items.append(item)
