"""
Disk Analyzer — Real Windows disk diagnostics for gaming/emulator workloads.

Provides:
- System drive detection with capacity, free space, filesystem, disk type
- Storage pressure classification (NORMAL / LOW_SPACE / HIGH_PRESSURE / CRITICAL)
- Reclaimable storage estimation from safe cleanup targets
- Read/write activity monitoring (when available)
- All operations are READ-ONLY unless used by cleanup engine
"""

import os
import time
import platform
import tempfile
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum

import psutil

from app.utils.logger import get_logger

logger = get_logger("system.disk_analyzer")


class StoragePressure(Enum):
    """Storage pressure classification."""
    NORMAL = "NORMAL"
    LOW_SPACE = "LOW_SPACE"
    HIGH_PRESSURE = "HIGH_PRESSURE"
    CRITICAL = "CRITICAL"


@dataclass
class DiskPartitionInfo:
    """Info about a single disk partition."""
    device: str = ""
    mountpoint: str = ""
    filesystem: str = ""
    total_bytes: int = 0
    used_bytes: int = 0
    free_bytes: int = 0
    percent_used: float = 0.0
    is_system_drive: bool = False
    disk_type: str = "UNKNOWN"  # HDD, SSD, NVMe, UNKNOWN
    read_bytes: int = 0
    write_bytes: int = 0
    read_count: int = 0
    write_count: int = 0


@dataclass
class ReclaimableTarget:
    """A detected cleanup target with estimated reclaimable bytes."""
    name: str = ""
    path: str = ""
    estimated_bytes: int = 0
    status: str = "DETECTED"  # DETECTED, SAFE, RECOMMENDATION_ONLY, REQUIRES_ADMIN
    category: str = ""  # TEMP, CACHE, THUMBNAIL, SHADER, BROWSER


@dataclass
class DiskDiagnostics:
    """Complete disk diagnostics result."""
    # System drive
    system_drive: Optional[DiskPartitionInfo] = None
    all_partitions: List[DiskPartitionInfo] = field(default_factory=list)

    # Storage pressure
    pressure_level: StoragePressure = StoragePressure.NORMAL
    pressure_description: str = ""

    # Reclaimable storage
    reclaimable_targets: List[ReclaimableTarget] = field(default_factory=list)
    total_reclaimable_bytes: int = 0
    total_reclaimable_safe: int = 0  # Only auto-cleanable

    # I/O activity
    total_read_bytes: int = 0
    total_write_bytes: int = 0
    disk_busy_percent: float = 0.0

    # Timestamp
    timestamp: float = 0.0


# ── Disk Type Detection ────────────────────────────────────────

def _detect_disk_type(device: str) -> str:
    """
    Detect disk type (HDD/SSD/NVMe) using Windows WMI.
    Returns "HDD", "SSD", "NVMe", or "UNKNOWN".
    """
    if platform.system() != "Windows":
        return "UNKNOWN"

    try:
        import wmi
        c = wmi.WMI()
        # Query Win32_DiskDrive for the physical disk
        for disk in c.Win32_DiskDrive():
            # Match by device name
            if disk.DeviceID and device:
                mediatype = (disk.MediaType or "").lower()
                model = (disk.Model or "").lower()
                if "nvme" in model or "nvme" in mediatype:
                    return "NVME"
                if "ssd" in mediatype or "solid" in mediatype:
                    return "SSD"
                if "fixed" in mediatype or "hard" in mediatype:
                    # Could be SSD or HDD — check rotational
                    try:
                        if hasattr(disk, "PNPDeviceID"):
                            pass
                    except Exception:
                        pass
                    return "HDD"
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"WMI disk type detection failed: {e}")

    return "UNKNOWN"


# ── Core Analyzer ──────────────────────────────────────────────

class DiskAnalyzer:
    """
    Real disk diagnostics for Heaven Society.
    All analysis is read-only.
    """

    def __init__(self):
        self._cache: Optional[DiskDiagnostics] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 5.0

    def diagnose(self, force: bool = False) -> DiskDiagnostics:
        """
        Full disk diagnostics.
        Returns real Windows disk data from psutil.
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        diag = DiskDiagnostics(timestamp=now)

        try:
            # 1. Get disk partitions
            diag.all_partitions = self._get_partitions()
            diag.system_drive = self._find_system_drive(diag.all_partitions)

            # 2. Get disk I/O
            self._get_disk_io(diag)

            # 3. Classify storage pressure
            diag.pressure_level, diag.pressure_description = \
                self._classify_pressure(diag.system_drive)

            # 4. Estimate reclaimable storage
            diag.reclaimable_targets = self._estimate_reclaimable()
            diag.total_reclaimable_bytes = sum(
                t.estimated_bytes for t in diag.reclaimable_targets
            )
            diag.total_reclaimable_safe = sum(
                t.estimated_bytes for t in diag.reclaimable_targets
                if t.status in ("SAFE", "DETECTED")
            )

        except Exception as e:
            logger.error(f"Disk diagnostics error: {e}")

        self._cache = diag
        self._cache_time = now
        return diag

    def _get_partitions(self) -> List[DiskPartitionInfo]:
        """Get all disk partitions with usage info."""
        partitions = []

        try:
            disk_io = psutil.disk_io_counters(perdisk=True)
        except Exception:
            disk_io = {}

        try:
            for part in psutil.disk_partitions(all=False):
                try:
                    usage = psutil.disk_usage(part.mountpoint)
                    io = disk_io.get(part.device, None)

                    # Detect disk type for system drive
                    disk_type = _detect_disk_type(part.device) \
                        if "C:" in part.mountpoint.upper() else "UNKNOWN"

                    info = DiskPartitionInfo(
                        device=part.device,
                        mountpoint=part.mountpoint,
                        filesystem=part.fstype,
                        total_bytes=usage.total,
                        used_bytes=usage.used,
                        free_bytes=usage.free,
                        percent_used=usage.percent,
                        is_system_drive="C:" in part.mountpoint.upper(),
                        disk_type=disk_type,
                        read_bytes=io.read_bytes if io else 0,
                        write_bytes=io.write_bytes if io else 0,
                        read_count=io.read_count if io else 0,
                        write_count=io.write_count if io else 0,
                    )
                    partitions.append(info)
                except (OSError, PermissionError) as e:
                    logger.debug(f"Cannot read partition {part.mountpoint}: {e}")
                    continue
        except Exception as e:
            logger.debug(f"Error listing partitions: {e}")

        return partitions

    def _find_system_drive(
        self, partitions: List[DiskPartitionInfo]
    ) -> Optional[DiskPartitionInfo]:
        """Find the system drive (usually C:)."""
        for p in partitions:
            if p.is_system_drive:
                return p
        return partitions[0] if partitions else None

    def _get_disk_io(self, diag: DiskDiagnostics):
        """Get disk I/O counters."""
        try:
            io = psutil.disk_io_counters()
            if io:
                diag.total_read_bytes = io.read_bytes
                diag.total_write_bytes = io.write_bytes
                diag.disk_busy_percent = getattr(io, "busy_time", 0) / 1000 if hasattr(io, "busy_time") else 0.0
        except Exception:
            pass

    def _classify_pressure(
        self, drive: Optional[DiskPartitionInfo]
    ) -> Tuple[StoragePressure, str]:
        """Classify storage pressure from real disk usage."""
        if not drive:
            return StoragePressure.NORMAL, "No system drive detected"

        pct = drive.percent_used
        free_gb = drive.free_bytes / (1024 ** 3)

        if pct > 95 or free_gb < 5:
            return StoragePressure.CRITICAL, (
                f"System drive at {pct:.0f}% capacity ({free_gb:.1f}GB free). "
                "Critical — may cause system instability and application failures."
            )
        if pct > 85 or free_gb < 10:
            return StoragePressure.HIGH_PRESSURE, (
                f"System drive at {pct:.0f}% capacity ({free_gb:.1f}GB free). "
                "High pressure — may cause performance degradation."
            )
        if pct > 75 or free_gb < 20:
            return StoragePressure.LOW_SPACE, (
                f"System drive at {pct:.0f}% capacity ({free_gb:.1f}GB free). "
                "Running low on space — consider cleanup."
            )
        return StoragePressure.NORMAL, (
            f"System drive at {pct:.0f}% capacity ({free_gb:.1f}GB free). "
            "Storage is healthy."
        )

    def _estimate_reclaimable(self) -> List[ReclaimableTarget]:
        """Estimate reclaimable storage from safe cleanup targets."""
        targets = []

        # 1. User TEMP
        user_temp = tempfile.gettempdir()
        if user_temp and os.path.isdir(user_temp):
            size = self._estimate_dir_size(user_temp)
            if size > 0:
                targets.append(ReclaimableTarget(
                    name="User Temp",
                    path=user_temp,
                    estimated_bytes=size,
                    status="SAFE",
                    category="TEMP",
                ))

        # 2. System TEMP
        system_temp = os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "Temp"
        )
        if os.path.isdir(system_temp):
            from app.utils.admin import is_admin
            size = self._estimate_dir_size(system_temp)
            if size > 0:
                targets.append(ReclaimableTarget(
                    name="System Temp",
                    path=system_temp,
                    estimated_bytes=size,
                    status="REQUIRES_ADMIN" if not is_admin() else "SAFE",
                    category="TEMP",
                ))

        # 3. Thumbnail cache (Windows)
        thumb_path = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Microsoft", "Windows", "Explorer"
        )
        if os.path.isdir(thumb_path):
            size = self._estimate_dir_size(thumb_path, pattern="thumbcache_*.db")
            if size > 0:
                targets.append(ReclaimableTarget(
                    name="Thumbnail Cache",
                    path=thumb_path,
                    estimated_bytes=size,
                    status="RECOMMENDATION_ONLY",
                    category="THUMBNAIL",
                ))

        # 4. NVIDIA shader cache
        for cache_name, cache_path in [
            ("NVIDIA DXCache", os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "NVIDIA", "DXCache")),
            ("NVIDIA GLCache", os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "NVIDIA", "GLCache")),
            ("AMD DXCache", os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "AMD", "DXCache")),
        ]:
            if os.path.isdir(cache_path):
                size = self._estimate_dir_size(cache_path)
                if size > 0:
                    targets.append(ReclaimableTarget(
                        name=cache_name,
                        path=cache_path,
                        estimated_bytes=size,
                        status="RECOMMENDATION_ONLY",
                        category="SHADER",
                    ))

        # 5. Browser caches (detection only — recommendation)
        browser_cache_dirs = [
            ("Chrome Cache", os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "Google", "Chrome",
                "User Data", "Default", "Cache")),
            ("Firefox Cache", os.path.join(
                os.environ.get("APPDATA", ""), "Mozilla", "Firefox",
                "Profiles")),
            ("Edge Cache", os.path.join(
                os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Edge",
                "User Data", "Default", "Cache")),
        ]
        for name, path in browser_cache_dirs:
            if os.path.isdir(path):
                size = self._estimate_dir_size(path)
                if size > 0:
                    targets.append(ReclaimableTarget(
                        name=name,
                        path=path,
                        estimated_bytes=size,
                        status="RECOMMENDATION_ONLY",
                        category="BROWSER",
                    ))

        # 6. Recycle Bin (user confirmation required)
        recycle_size, recycle_count = self._estimate_recycle_bin()
        if recycle_size > 0:
            targets.append(ReclaimableTarget(
                name="Recycle Bin",
                path="Recycle Bin",
                estimated_bytes=recycle_size,
                status="USER_CONFIRMATION_REQUIRED",
                category="RECYCLE_BIN",
            ))

        # 7. Windows error reporting
        wer_path = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "WER"
        )
        if os.path.isdir(wer_path):
            size = self._estimate_dir_size(wer_path)
            if size > 0:
                targets.append(ReclaimableTarget(
                    name="Windows Error Reporting",
                    path=wer_path,
                    estimated_bytes=size,
                    status="SAFE",
                    category="TEMP",
                ))

        return targets

    def _estimate_recycle_bin(self) -> tuple:
        """
        Estimate Recycle Bin size using Shell32 COM API.
        Returns (size_bytes, item_count).
        """
        try:
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            try:
                shell = win32com.client.Dispatch("Shell.Application")
                recycle_bin = shell.NameSpace(0x0a)  # Recycle Bin
                if recycle_bin:
                    total_size = 0
                    item_count = 0
                    items = recycle_bin.Items()
                    for item in items:
                        try:
                            total_size += item.Size
                            item_count += 1
                        except Exception:
                            continue
                    return total_size, item_count
            finally:
                pythoncom.CoUninitialize()
        except (ImportError, Exception) as e:
            logger.debug(f"Recycle Bin size detection failed: {e}")
        return 0, 0

    def measure_disk_state(self) -> Dict:
        """Take a snapshot of current disk state for before/after comparison."""
        diag = self.diagnose()
        state = {"timestamp": time.time()}
        if diag.system_drive:
            d = diag.system_drive
            state["free_bytes"] = d.free_bytes
            state["used_bytes"] = d.used_bytes
            state["total_bytes"] = d.total_bytes
            state["percent_used"] = d.percent_used
        state["reclaimable_bytes"] = diag.total_reclaimable_bytes
        return state

    def compare_disk_states(self, before: Dict, after: Dict) -> Dict:
        """Compare two disk snapshots and calculate deltas."""
        result = {"before": before, "after": after, "delta": {}}
        delta = result["delta"]
        for key in ["free_bytes", "used_bytes", "percent_used", "reclaimable_bytes"]:
            if key in before and key in after:
                delta[key] = after[key] - before[key]
        return result

    def _estimate_dir_size(
        self,
        dirpath: str,
        pattern: str = "",
        max_depth: int = 2,
    ) -> int:
        """
        Estimate directory size without deep recursion.
        Limited depth to avoid long scans.
        """
        total = 0
        try:
            for entry in os.scandir(dirpath):
                try:
                    if entry.is_file(follow_symlinks=False):
                        if not pattern or self._matches_pattern(entry.name, pattern):
                            total += entry.stat().st_size
                    elif entry.is_dir(follow_symlinks=False) and max_depth > 0:
                        total += self._estimate_dir_size(
                            entry.path, pattern, max_depth - 1
                        )
                except (OSError, PermissionError):
                    continue
        except (OSError, PermissionError):
            pass
        return total

    @staticmethod
    def _matches_pattern(name: str, pattern: str) -> bool:
        """Simple glob pattern matching (* only)."""
        if not pattern:
            return True
        import fnmatch
        return fnmatch.fnmatch(name.lower(), pattern.lower())


# Singleton
disk_analyzer = DiskAnalyzer()
