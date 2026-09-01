"""
Phase 52 — Advanced Storage Intelligence.

Extends the existing DiskAnalyzer with:
  - StorageOverview: consolidated storage summary across all drives
  - StorageAnalyzer: deep directory analysis, largest directories, drive health
  - StorageRecommendations: evidence-based storage recommendations
  - Quick Scan vs Deep Scan (deep scan runs in a worker)

Rules:
  - Never delete files automatically
  - Never scan entire filesystem synchronously from GUI thread
  - Inaccessible directories are reported, not crashed
  - Deep scans run in a background thread
  - All operations are READ-ONLY
  - Every value is MEASURED or NOT_AVAILABLE
"""

import os
import fnmatch
import shutil
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

from app.system.disk_analyzer import (
    DiskAnalyzer,
    DiskDiagnostics,
    DiskPartitionInfo,
    ReclaimableTarget,
    StoragePressure,
    disk_analyzer,
)
from app.utils.logger import get_logger

logger = get_logger("storage.intelligence")


# ── Enums ────────────────────────────────────────────────────────


class ScanDepth(Enum):
    """Scan depth level."""
    QUICK = "QUICK"
    DEEP = "DEEP"


class DriveHealth(Enum):
    """Drive health classification based on available data."""
    HEALTHY = "HEALTHY"
    ATTENTION = "ATTENTION"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"


class StorageRecommendationSeverity(Enum):
    """Severity for storage-specific recommendations."""
    INFO = "INFO"
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ── Models ────────────────────────────────────────────────────────


@dataclass
class DirectoryAnalysis:
    """Result of analyzing a single directory."""
    path: str = ""
    name: str = ""
    total_size_bytes: int = 0
    file_count: int = 0
    subdirectory_count: int = 0
    largest_files: List[Tuple[str, int]] = field(default_factory=list)  # (name, size)
    last_modified: float = 0.0
    accessible: bool = True
    error: str = ""

    @property
    def size_display(self) -> str:
        return _format_bytes(self.total_size_bytes)


@dataclass
class StorageOverview:
    """Consolidated storage overview across all drives."""
    timestamp: float = 0.0
    drives: List[DiskPartitionInfo] = field(default_factory=list)
    system_drive: Optional[DiskPartitionInfo] = None
    total_storage_bytes: int = 0
    total_used_bytes: int = 0
    total_free_bytes: int = 0
    overall_percent_used: float = 0.0
    system_pressure: StoragePressure = StoragePressure.NORMAL
    pressure_description: str = ""
    disk_type: str = "UNKNOWN"  # SSD / HDD / NVMe / UNKNOWN
    disk_health: DriveHealth = DriveHealth.UNKNOWN
    scan_depth: ScanDepth = ScanDepth.QUICK

    @property
    def total_display(self) -> str:
        return _format_bytes(self.total_storage_bytes)

    @property
    def used_display(self) -> str:
        return _format_bytes(self.total_used_bytes)

    @property
    def free_display(self) -> str:
        return _format_bytes(self.total_free_bytes)


@dataclass
class StorageScanResult:
    """Result of a storage scan (quick or deep)."""
    scan_id: str = ""
    scan_depth: ScanDepth = ScanDepth.QUICK
    timestamp: float = 0.0
    duration_seconds: float = 0.0
    overview: Optional[StorageOverview] = None
    largest_directories: List[DirectoryAnalysis] = field(default_factory=list)
    cleanup_candidates: List[ReclaimableTarget] = field(default_factory=list)
    total_reclaimable_bytes: int = 0
    recommendations: List[Dict] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.scan_id:
            self.scan_id = f"scan_{uuid.uuid4().hex[:8]}"


@dataclass
class StorageRecommendation:
    """A single storage recommendation."""
    id: str = ""
    title: str = ""
    explanation: str = ""
    severity: StorageRecommendationSeverity = StorageRecommendationSeverity.INFO
    evidence: Dict = field(default_factory=dict)
    estimated_benefit: str = ""
    risk: str = "NONE"
    category: str = ""

    def __post_init__(self):
        if not self.id:
            self.id = f"srec_{uuid.uuid4().hex[:8]}"


# ── Helpers ────────────────────────────────────────────────────────

# Well-known large directories to analyze
SCAN_DIRECTORIES = [
    ("User Temp", "TEMP"),
    ("Windows Temp", "SYSTEM_TEMP"),
    ("Downloads", "USER_PROFILE"),
    ("Recycle Bin", "RECYCLE_BIN"),
    ("NVIDIA DXCache", "LOCALAPPDATA"),
    ("NVIDIA GLCache", "LOCALAPPDATA"),
    ("Windows Update", "SYSTEM_ROOT"),
    ("Windows SoftwareDistribution", "SYSTEM_ROOT"),
    ("Crash Dumps", "LOCALAPPDATA"),
    ("Installer Cache", "WINDOWS"),
    ("Prefetch", "WINDOWS"),
    ("Windows Logs", "SYSTEM_ROOT"),
]


def _format_bytes(size_bytes: int) -> str:
    """Format bytes to human-readable string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    elif size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    elif size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 ** 2):.1f} MB"
    else:
        return f"{size_bytes / (1024 ** 3):.2f} GB"


def _resolve_scan_path(name: str, env_key: str) -> Optional[str]:
    """Resolve a scan directory path from environment."""
    if env_key == "TEMP":
        return tempfile.gettempdir() if name == "User Temp" else None
    if env_key == "SYSTEM_TEMP":
        return os.path.join(
            os.environ.get("SystemRoot", r"C:\Windows"), "Temp"
        )
    if env_key == "USER_PROFILE":
        return os.path.join(os.environ.get("USERPROFILE", ""), name)
    if env_key == "LOCALAPPDATA":
        local = os.environ.get("LOCALAPPDATA", "")
        if not local:
            return None
        if "NVIDIA" in name:
            sub = "DXCache" if "DX" in name else "GLCache"
            return os.path.join(local, "NVIDIA", sub)
        if "Crash" in name:
            return os.path.join(local, "CrashDumps")
        return None
    if env_key == "SYSTEM_ROOT":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        if "SoftwareDistribution" in name:
            return os.path.join(root, "SoftwareDistribution")
        if "Logs" in name:
            return os.path.join(root, "Logs")
        return None
    if env_key == "WINDOWS":
        root = os.environ.get("SystemRoot", r"C:\Windows")
        if "Installer" in name:
            return os.path.join(root, "Installer")
        if "Prefetch" in name:
            return os.path.join(root, "Prefetch")
        return None
    return None


import tempfile


# ── StorageAnalyzer ────────────────────────────────────────────────


class StorageAnalyzer:
    """
    Advanced storage analysis extending the existing DiskAnalyzer.

    Quick Scan:
      - System drive overview
      - Storage pressure
      - Basic reclaimable estimation
      - Disk type / health

    Deep Scan:
      - All of Quick Scan
      - Largest directory analysis
      - Drive-by-drive breakdown
      - Detailed recommendations
      - Runs in a background thread
    """

    def __init__(self, base_analyzer: Optional[DiskAnalyzer] = None):
        self._base = base_analyzer or disk_analyzer
        self._last_scan: Optional[StorageScanResult] = None
        self._scan_lock = threading.Lock()
        self._deep_scan_thread: Optional[threading.Thread] = None
        self._deep_scan_running = False

    @property
    def last_scan(self) -> Optional[StorageScanResult]:
        return self._last_scan

    @property
    def is_deep_scanning(self) -> bool:
        return self._deep_scan_running

    def quick_scan(self) -> StorageScanResult:
        """
        Perform a quick storage scan (synchronous, fast).
        Returns overview, pressure, reclaimable targets, basic recommendations.
        """
        start = time.time()
        result = StorageScanResult(
            scan_depth=ScanDepth.QUICK,
            timestamp=start,
        )

        try:
            # Get base diagnostics
            diag = self._base.diagnose(force=True)

            # Build overview
            result.overview = self._build_overview(diag, ScanDepth.QUICK)

            # Cleanup candidates from base analyzer
            result.cleanup_candidates = diag.reclaimable_targets
            result.total_reclaimable_bytes = diag.total_reclaimable_bytes

            # Generate recommendations
            result.recommendations = [
                self._rec_to_dict(r)
                for r in self._generate_recommendations(result.overview, result.cleanup_candidates)
            ]

        except Exception as e:
            logger.error(f"Quick scan error: {e}")
            result.errors.append(str(e))

        result.duration_seconds = time.time() - start
        self._last_scan = result
        return result

    def deep_scan(self, callback=None) -> StorageScanResult:
        """
        Perform a deep storage scan.
        If called from GUI, should be dispatched to a worker.
        When called directly, runs synchronously.
        Returns full analysis including largest directories.
        """
        start = time.time()
        result = StorageScanResult(
            scan_depth=ScanDepth.DEEP,
            timestamp=start,
        )

        try:
            # Get base diagnostics
            diag = self._base.diagnose(force=True)

            # Build overview
            result.overview = self._build_overview(diag, ScanDepth.DEEP)

            # Cleanup candidates
            result.cleanup_candidates = diag.reclaimable_targets
            result.total_reclaimable_bytes = diag.total_reclaimable_bytes

            # Analyze largest directories (this is the expensive part)
            result.largest_directories = self._analyze_directories()

            # Sort by size descending
            result.largest_directories.sort(key=lambda d: d.total_size_bytes, reverse=True)

            # Generate recommendations
            result.recommendations = [
                self._rec_to_dict(r)
                for r in self._generate_recommendations(
                    result.overview,
                    result.cleanup_candidates,
                    result.largest_directories,
                )
            ]

        except Exception as e:
            logger.error(f"Deep scan error: {e}")
            result.errors.append(str(e))

        result.duration_seconds = time.time() - start

        with self._scan_lock:
            self._last_scan = result
            self._deep_scan_running = False

        if callback:
            try:
                callback(result)
            except Exception:
                pass

        return result

    def start_deep_scan_async(self, callback=None) -> str:
        """
        Start a deep scan in a background thread.
        Returns the scan_id immediately.
        Use is_deep_scanning to check progress.
        """
        if self._deep_scan_running:
            return self._last_scan.scan_id if self._last_scan else ""

        self._deep_scan_running = True
        self._deep_scan_thread = threading.Thread(
            target=self.deep_scan,
            args=(callback,),
            daemon=True,
            name="storage-deep-scan",
        )
        self._deep_scan_thread.start()

        # Return the scan_id that will be populated
        return f"scan_{uuid.uuid4().hex[:8]}"

    def stop_deep_scan(self):
        """Request stop of a running deep scan (best effort)."""
        self._deep_scan_running = False
        if self._deep_scan_thread and self._deep_scan_thread.is_alive():
            # Thread checks _deep_scan_running flag in directory iteration
            self._deep_scan_thread.join(timeout=5.0)

    # ── Private Methods ─────────────────────────────────────────

    def _build_overview(self, diag: DiskDiagnostics, depth: ScanDepth) -> StorageOverview:
        """Build a StorageOverview from DiskDiagnostics."""
        overview = StorageOverview(
            timestamp=time.time(),
            drives=diag.all_partitions,
            system_drive=diag.system_drive,
            system_pressure=diag.pressure_level,
            pressure_description=diag.pressure_description,
            scan_depth=depth,
        )

        # Aggregate all drives
        for drive in diag.all_partitions:
            overview.total_storage_bytes += drive.total_bytes
            overview.total_used_bytes += drive.used_bytes
            overview.total_free_bytes += drive.free_bytes

        if overview.total_storage_bytes > 0:
            overview.overall_percent_used = (
                overview.total_used_bytes / overview.total_storage_bytes
            ) * 100

        # Disk type from system drive
        if diag.system_drive:
            overview.disk_type = diag.system_drive.disk_type

        # Drive health (simplified — based on pressure)
        overview.disk_health = self._classify_drive_health(diag)

        return overview

    def _classify_drive_health(self, diag: DiskDiagnostics) -> DriveHealth:
        """Classify drive health from available diagnostics."""
        if not diag.system_drive:
            return DriveHealth.UNKNOWN

        pressure = diag.pressure_level
        if pressure == StoragePressure.CRITICAL:
            return DriveHealth.WARNING
        if pressure == StoragePressure.HIGH_PRESSURE:
            return DriveHealth.ATTENTION
        if pressure == StoragePressure.LOW_SPACE:
            return DriveHealth.ATTENTION

        return DriveHealth.HEALTHY

    def _analyze_directories(self) -> List[DirectoryAnalysis]:
        """Analyze well-known large directories."""
        results = []

        for name, env_key in SCAN_DIRECTORIES:
            path = _resolve_scan_path(name, env_key)
            if not path or not os.path.isdir(path):
                continue

            analysis = self._analyze_single_directory(path, name)
            if analysis.total_size_bytes > 0:
                results.append(analysis)

        # Also analyze user profile root
        user_profile = os.environ.get("USERPROFILE", "")
        if user_profile and os.path.isdir(user_profile):
            analysis = self._analyze_single_directory(user_profile, "User Profile")
            if analysis.total_size_bytes > 0:
                results.append(analysis)

        # Analyze Program Files
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        if os.path.isdir(pf):
            analysis = self._analyze_single_directory(pf, "Program Files")
            if analysis.total_size_bytes > 0:
                results.append(analysis)

        # Analyze Windows
        win_dir = os.environ.get("SystemRoot", r"C:\Windows")
        if os.path.isdir(win_dir):
            analysis = self._analyze_single_directory(win_dir, "Windows")
            if analysis.total_size_bytes > 0:
                results.append(analysis)

        return results

    def _analyze_single_directory(
        self, path: str, name: str, max_depth: int = 2, max_files: int = 20000
    ) -> DirectoryAnalysis:
        """
        Analyze a single directory for size, file count, and largest files.
        Limited depth and file count to avoid long scans.
        """
        analysis = DirectoryAnalysis(path=path, name=name)

        largest_files: List[Tuple[str, int]] = []
        total_size = 0
        file_count = 0
        sub_count = 0
        last_mod = 0.0

        try:
            for entry in os.scandir(path):
                if not self._deep_scan_running and analysis.total_size_bytes > 0:
                    # Early termination requested
                    break

                try:
                    if entry.is_file(follow_symlinks=False):
                        try:
                            stat = entry.stat()
                            size = stat.st_size
                            total_size += size
                            file_count += 1

                            mod = stat.st_mtime
                            if mod > last_mod:
                                last_mod = mod

                            # Track top 10 largest files
                            if len(largest_files) < 10:
                                largest_files.append((entry.name, size))
                                largest_files.sort(key=lambda x: x[1], reverse=True)
                            elif size > largest_files[-1][1]:
                                largest_files[-1] = (entry.name, size)
                                largest_files.sort(key=lambda x: x[1], reverse=True)

                            if file_count >= max_files:
                                break
                        except (OSError, PermissionError):
                            continue

                    elif entry.is_dir(follow_symlinks=False):
                        sub_count += 1
                        if max_depth > 0:
                            sub = self._analyze_single_directory(
                                entry.path, entry.name, max_depth - 1, max_files
                            )
                            total_size += sub.total_size_bytes
                            file_count += sub.file_count
                            largest_files.extend(sub.largest_files)
                            largest_files.sort(key=lambda x: x[1], reverse=True)
                            largest_files = largest_files[:10]
                except (OSError, PermissionError):
                    continue

        except (OSError, PermissionError) as e:
            analysis.accessible = False
            analysis.error = str(e)
        except Exception as e:
            analysis.accessible = False
            analysis.error = f"Unexpected error: {e}"

        analysis.total_size_bytes = total_size
        analysis.file_count = file_count
        analysis.subdirectory_count = sub_count
        analysis.largest_files = largest_files[:10]
        analysis.last_modified = last_mod

        return analysis

    def _generate_recommendations(
        self,
        overview: StorageOverview,
        cleanup_candidates: List[ReclaimableTarget],
        largest_dirs: Optional[List[DirectoryAnalysis]] = None,
    ) -> List[StorageRecommendation]:
        """Generate evidence-based storage recommendations."""
        recs = []

        if not overview or not overview.system_drive:
            return recs

        drive = overview.system_drive
        free_gb = drive.free_bytes / (1024 ** 3)
        reclaimable_gb = sum(t.estimated_bytes for t in cleanup_candidates) / (1024 ** 3)

        # Critical disk space
        if free_gb < 5:
            recs.append(StorageRecommendation(
                title="Storage critically low",
                explanation=(
                    f"Only {free_gb:.1f} GB free on {drive.mountpoint}. "
                    "System stability may be affected."
                ),
                severity=StorageRecommendationSeverity.CRITICAL,
                evidence={"free_gb": free_gb, "threshold_gb": 5.0},
                estimated_benefit="Restore system stability",
                risk="LOW",
                category="disk_pressure",
            ))

        # High pressure
        elif free_gb < 15:
            recs.append(StorageRecommendation(
                title="Storage running low",
                explanation=(
                    f"{free_gb:.1f} GB free on {drive.mountpoint}. "
                    "Performance may be affected."
                ),
                severity=StorageRecommendationSeverity.HIGH,
                evidence={"free_gb": free_gb, "threshold_gb": 15.0},
                estimated_benefit="Improve system performance",
                risk="NONE",
                category="disk_pressure",
            ))

        # Elevated
        elif free_gb < 30:
            recs.append(StorageRecommendation(
                title="Storage approaching capacity",
                explanation=(
                    f"{free_gb:.1f} GB free on {drive.mountpoint}. "
                    "Consider cleanup when convenient."
                ),
                severity=StorageRecommendationSeverity.LOW,
                evidence={"free_gb": free_gb, "threshold_gb": 30.0},
                estimated_benefit="Maintain healthy storage",
                risk="NONE",
                category="disk_pressure",
            ))

        # Reclaimable storage available
        if reclaimable_gb > 0.5:
            severity = (
                StorageRecommendationSeverity.MEDIUM if reclaimable_gb > 2.0
                else StorageRecommendationSeverity.LOW
            )
            recs.append(StorageRecommendation(
                title="Temporary data available for cleanup",
                explanation=(
                    f"Approximately {reclaimable_gb:.1f} GB of temporary data "
                    "can be reclaimed."
                ),
                severity=severity,
                evidence={"reclaimable_gb": reclaimable_gb},
                estimated_benefit=f"Reclaim {reclaimable_gb:.1f} GB",
                risk="NONE",
                category="cleanup",
            ))

        # Largest directory analysis
        if largest_dirs:
            for da in largest_dirs[:3]:
                size_gb = da.total_size_bytes / (1024 ** 3)
                if size_gb > 5:
                    recs.append(StorageRecommendation(
                        title=f"Large directory: {da.name}",
                        explanation=(
                            f"{da.name} at {da.path} uses {size_gb:.1f} GB "
                            f"({da.file_count:,} files)."
                        ),
                        severity=StorageRecommendationSeverity.INFO,
                        evidence={
                            "path": da.path,
                            "size_gb": size_gb,
                            "file_count": da.file_count,
                        },
                        estimated_benefit="Review for potential cleanup",
                        risk="NONE",
                        category="directory_review",
                    ))

        # Disk type awareness
        if overview.disk_type == "HDD":
            recs.append(StorageRecommendation(
                title="HDD detected",
                explanation=(
                    "System drive is an HDD. SSD upgrade would significantly "
                    "improve loading times and system responsiveness."
                ),
                severity=StorageRecommendationSeverity.INFO,
                evidence={"disk_type": "HDD"},
                estimated_benefit="Faster loading and system responsiveness",
                risk="NONE",
                category="hardware",
            ))

        return recs

    @staticmethod
    def _rec_to_dict(rec: StorageRecommendation) -> Dict:
        """Convert a recommendation to a dict for serialization."""
        return {
            "id": rec.id,
            "title": rec.title,
            "explanation": rec.explanation,
            "severity": rec.severity.value,
            "evidence": rec.evidence,
            "estimated_benefit": rec.estimated_benefit,
            "risk": rec.risk,
            "category": rec.category,
        }


# ── Singleton ────────────────────────────────────────────────────

storage_analyzer = StorageAnalyzer()
