"""
Cleanup scanner — READ-ONLY analysis of cleanup targets.

The scanner NEVER deletes files. It only detects and measures.
"""

import os
import shutil
import tempfile
import time
from pathlib import Path
from typing import List, Optional

from app.cleanup.cleanup_models import (
    CleanupItem,
    CleanupCategory,
    CleanupStatus,
    SafetyClassification,
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
        self._scan_crash_dumps()
        self._scan_installer_leftovers()
        self._scan_old_logs()
        self._scan_recycle_bin()

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
                removable_size=0,
                file_count=file_count,
                removable_file_count=0,
                risk="LOW",
                safety=SafetyClassification.REVIEW,
                available=True,
                selected=False,
                can_delete=False,
                requires_admin=False,
                reason="RECOMMENDATION ONLY — browser cache rebuilds automatically",
                status=CleanupStatus.RECOMMENDATION_ONLY,
            )
            self._items.append(item)

    def _scan_crash_dumps(self):
        """Scan Windows crash dump files — SAFE when old enough."""
        local_app = os.environ.get("LOCALAPPDATA", "")
        crash_dirs = []

        # Windows crash dumps
        crashes = os.path.join(local_app, "CrashDumps")
        if crashes and os.path.isdir(crashes):
            crash_dirs.append(("Windows Crash Dumps", crashes))

        # Also check %TEMP% for .dmp files
        user_temp = tempfile.gettempdir()
        if user_temp and os.path.isdir(user_temp):
            crash_dirs.append(("Temp Crash Dumps", user_temp))

        for label, dirpath in crash_dirs:
            size = 0
            file_count = 0
            removable_size = 0
            removable_count = 0
            oldest_days = None
            now = time.time()

            try:
                for entry in os.scandir(dirpath):
                    try:
                        if entry.is_file(follow_symlinks=False):
                            name_lower = entry.name.lower()
                            is_dump = name_lower.endswith(('.dmp', '.mdmp', '.hdmp'))
                            if label == "Temp Crash Dumps" and not is_dump:
                                continue
                            if is_dump:
                                file_count += 1
                                size += entry.stat().st_size
                                age_days = int((now - entry.stat().st_mtime) / 86400)
                                if oldest_days is None or age_days < oldest_days:
                                    oldest_days = age_days
                                if can_delete_file(entry.path):
                                    removable_size += entry.stat().st_size
                                    removable_count += 1
                    except (OSError, PermissionError):
                        continue
            except (OSError, PermissionError):
                continue

            if file_count == 0:
                continue

            # Crash dumps older than 7 days are SAFE; newer are REVIEW
            safe = oldest_days is not None and oldest_days >= 7

            item = CleanupItem(
                id=f"crash_{label.lower().replace(' ', '_')}",
                name=label,
                category=CleanupCategory.CRASH_DUMPS,
                description=(f"Crash dump files ({format_bytes(size)}). " +
                    (f"Safe to remove — oldest is {oldest_days} days old." if safe else
                     "Recent dumps may be needed for debugging.")),
                path=dirpath,
                detected_size=size,
                removable_size=removable_size if safe else 0,
                file_count=file_count,
                removable_file_count=removable_count if safe else 0,
                risk="LOW" if safe else "MEDIUM",
                safety=SafetyClassification.SAFE if safe else SafetyClassification.REVIEW,
                last_access_days=oldest_days,
                available=removable_count > 0 and safe,
                selected=safe and removable_count > 0,
                can_delete=safe and removable_count > 0,
                reversible=False,
                reason=(f"{removable_count} dumps, oldest {oldest_days}d" if oldest_days is not None else
                        f"{file_count} dumps found"),
                status=CleanupStatus.AVAILABLE if safe and removable_count > 0 else CleanupStatus.RECOMMENDATION_ONLY,
            )
            self._items.append(item)

    def _scan_installer_leftovers(self):
        """Scan for orphaned installer files — SAFE when identifiable."""
        user_temp = tempfile.gettempdir()
        if not user_temp or not os.path.isdir(user_temp):
            return

        size = 0
        file_count = 0
        removable_size = 0
        removable_count = 0
        now = time.time()
        oldest_days = None

        installer_extensions = ('.msi', '.exe')
        # Known safe installer prefixes
        safe_prefixes = ()

        try:
            for entry in os.scandir(user_temp):
                try:
                    if entry.is_file(follow_symlinks=False):
                        name_lower = entry.name.lower()
                        # MSI installers in temp are typically leftovers
                        if name_lower.endswith('.msi'):
                            file_count += 1
                            size += entry.stat().st_size
                            age_days = int((now - entry.stat().st_mtime) / 86400)
                            if oldest_days is None or age_days < oldest_days:
                                oldest_days = age_days
                            if can_delete_file(entry.path) and age_days >= 3:
                                removable_size += entry.stat().st_size
                                removable_count += 1
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            return

        if file_count == 0:
            return

        safe = oldest_days is not None and oldest_days >= 7

        item = CleanupItem(
            id="installer_leftovers",
            name="Installer Leftovers",
            category=CleanupCategory.INSTALLER_LEFTOVER,
            description=(f"Orphaned MSI installer files in temp ({format_bytes(size)}). " +
                (f"Safe — oldest is {oldest_days} days old." if safe else
                 "May still be needed.")),
            path=user_temp,
            detected_size=size,
            removable_size=removable_size if safe else 0,
            file_count=file_count,
            removable_file_count=removable_count if safe else 0,
            risk="LOW" if safe else "MEDIUM",
            safety=SafetyClassification.SAFE if safe else SafetyClassification.REVIEW,
            last_access_days=oldest_days,
            available=removable_count > 0 and safe,
            selected=safe and removable_count > 0,
            can_delete=safe and removable_count > 0,
            reversible=False,
            reason=(f"{removable_count} MSI files, oldest {oldest_days}d" if oldest_days is not None else
                    f"{file_count} MSI files found"),
            status=CleanupStatus.AVAILABLE if safe and removable_count > 0 else CleanupStatus.RECOMMENDATION_ONLY,
        )
        self._items.append(item)

    def _scan_old_logs(self):
        """Scan for old log files — SAFE when old enough."""
        log_dirs = []

        # Phoenix optimizer logs
        project_logs = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "app", "logs"
        )
        if os.path.isdir(project_logs):
            log_dirs.append(("Optimizer Logs", project_logs))

        # Windows event logs are not safe to delete
        # But we can check for .log files in temp
        user_temp = tempfile.gettempdir()
        if user_temp and os.path.isdir(user_temp):
            log_dirs.append(("Temp Logs", user_temp))

        for label, dirpath in log_dirs:
            size = 0
            file_count = 0
            removable_size = 0
            removable_count = 0
            oldest_days = None
            now = time.time()

            try:
                for entry in os.scandir(dirpath):
                    try:
                        if entry.is_file(follow_symlinks=False):
                            name_lower = entry.name.lower()
                            if name_lower.endswith(('.log', '.log.old', '.txt')):
                                file_count += 1
                                size += entry.stat().st_size
                                age_days = int((now - entry.stat().st_mtime) / 86400)
                                if oldest_days is None or age_days < oldest_days:
                                    oldest_days = age_days
                                if can_delete_file(entry.path) and age_days >= 7:
                                    removable_size += entry.stat().st_size
                                    removable_count += 1
                    except (OSError, PermissionError):
                        continue
            except (OSError, PermissionError):
                continue

            if file_count == 0:
                continue

            safe = oldest_days is not None and oldest_days >= 7

            item = CleanupItem(
                id=f"logs_{label.lower().replace(' ', '_')}",
                name=label,
                category=CleanupCategory.OLD_LOGS,
                description=(f"Old log files ({format_bytes(size)}). " +
                    (f"Safe — oldest is {oldest_days} days old." if safe else
                     "Recent logs may be useful for debugging.")),
                path=dirpath,
                detected_size=size,
                removable_size=removable_size if safe else 0,
                file_count=file_count,
                removable_file_count=removable_count if safe else 0,
                risk="LOW",
                safety=SafetyClassification.SAFE if safe else SafetyClassification.REVIEW,
                last_access_days=oldest_days,
                available=removable_count > 0 and safe,
                selected=safe and removable_count > 0,
                can_delete=safe and removable_count > 0,
                reversible=False,
                reason=(f"{removable_count} logs, oldest {oldest_days}d" if oldest_days is not None else
                        f"{file_count} logs found"),
                status=CleanupStatus.AVAILABLE if safe and removable_count > 0 else CleanupStatus.RECOMMENDATION_ONLY,
            )
            self._items.append(item)

    def _scan_recycle_bin(self):
        """Scan Recycle Bin — RECOMMENDATION ONLY (requires user confirmation)."""
        try:
            import subprocess
            # Use PowerShell to query Recycle Bin size
            result = subprocess.run(
                ['powershell', '-Command',
                 '(New-Object -ComObject Shell.Application).NameSpace(0xA).Items() | '
                 'Measure-Object -Property Size -Sum | Select-Object -ExpandProperty Sum'],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                size = int(result.stdout.strip())
                if size > 0:
                    item = CleanupItem(
                        id="recycle_bin",
                        name="Recycle Bin",
                        category=CleanupCategory.RECYCLE_BIN,
                        description=(
                            f"Recycle Bin contains {format_bytes(size)} of deleted files. "
                            "Emptying permanently removes all items. "
                            "Cannot be undone."
                        ),
                        path="Recycle Bin",
                        detected_size=size,
                        removable_size=0,  # RECOMMENDATION ONLY
                        file_count=0,
                        removable_file_count=0,
                        risk="MEDIUM",
                        safety=SafetyClassification.REVIEW,
                        available=True,
                        selected=False,
                        can_delete=False,
                        reversible=False,
                        reason="RECOMMENDATION ONLY — user must confirm",
                        status=CleanupStatus.RECOMMENDATION_ONLY,
                    )
                    self._items.append(item)
        except Exception as e:
            logger.debug(f"[CLEANUP] Recycle Bin scan: {e}")
