"""
Phase 53 — Background Resource Intelligence.

Extends the existing ProcessMonitor (app/system/processes.py) with:
  - ProcessIntelligence: higher-level resource analysis
  - ResourceTracker: track process resource history over time
  - ProcessClassifier: extended classification with GAME/EMULATOR/BACKGROUND
  - ProcessRecommendationEngine: evidence-based recommendations for safe actions
  - Safe actions: close app (user confirmation), ignore, add to exclusion list

Rules:
  - Never terminate processes automatically
  - Never kill critical Windows processes
  - Provide safe candidates only when evidence supports it
  - All operations are READ-ONLY unless user explicitly confirms action
  - Every value is MEASURED or NOT_AVAILABLE
"""

import os
import time
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Set, Tuple

import psutil

from app.system.processes import (
    ProcessMonitor,
    ProcessInfo,
    CRITICAL_PROCESSES,
    SECURITY_PROCESSES,
    EMULATOR_PROCESSES,
    OPTIONAL_PROCESSES,
    process_monitor,
)
from app.utils.logger import get_logger

logger = get_logger("system.process_intelligence")


# ── Enums ────────────────────────────────────────────────────────


class ProcessCategory(Enum):
    """Extended process classification."""
    SYSTEM = "SYSTEM"
    GAME = "GAME"
    EMULATOR = "EMULATOR"
    USER_APPLICATION = "USER APPLICATION"
    BACKGROUND = "BACKGROUND"
    UNKNOWN = "UNKNOWN"


class ProcessState(Enum):
    """Current foreground/background state."""
    FOREGROUND = "FOREGROUND"
    BACKGROUND = "BACKGROUND"
    UNKNOWN = "UNKNOWN"


class ResourcePressure(Enum):
    """Overall resource pressure from background processes."""
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RecommendedAction(Enum):
    """Safe recommended action for a process."""
    IGNORE = "IGNORE"
    CLOSE = "CLOSE"
    REVIEW = "REVIEW"
    ADD_TO_EXCLUSION = "ADD_TO_EXCLUSION"
    MONITOR = "MONITOR"


# ── Data Models ────────────────────────────────────────────────────


@dataclass
class ProcessResourceSnapshot:
    """A point-in-time resource measurement for a process."""
    pid: int = 0
    name: str = ""
    timestamp: float = 0.0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    gpu_percent: float = 0.0  # when available
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    net_connections: int = 0
    status: str = ""
    category: ProcessCategory = ProcessCategory.UNKNOWN
    process_state: ProcessState = ProcessState.UNKNOWN


@dataclass
class ProcessResourceHistory:
    """Aggregated resource history for a process."""
    pid: int = 0
    name: str = ""
    category: ProcessCategory = ProcessCategory.UNKNOWN
    snapshots: List[ProcessResourceSnapshot] = field(default_factory=list)
    first_seen: float = 0.0
    last_seen: float = 0.0
    lifetime_seconds: float = 0.0

    @property
    def avg_cpu(self) -> float:
        if not self.snapshots:
            return 0.0
        return sum(s.cpu_percent for s in self.snapshots) / len(self.snapshots)

    @property
    def max_cpu(self) -> float:
        if not self.snapshots:
            return 0.0
        return max(s.cpu_percent for s in self.snapshots)

    @property
    def avg_memory_mb(self) -> float:
        if not self.snapshots:
            return 0.0
        return sum(s.memory_mb for s in self.snapshots) / len(self.snapshots)

    @property
    def max_memory_mb(self) -> float:
        if not self.snapshots:
            return 0.0
        return max(s.memory_mb for s in self.snapshots)

    @property
    def current_memory_mb(self) -> float:
        if not self.snapshots:
            return 0.0
        return self.snapshots[-1].memory_mb

    @property
    def is_high_resource(self) -> bool:
        return self.avg_cpu > 20 or self.current_memory_mb > 500


@dataclass
class ProcessRecommendation:
    """A safe recommendation for a specific process."""
    id: str = ""
    pid: int = 0
    name: str = ""
    category: ProcessCategory = ProcessCategory.UNKNOWN
    action: RecommendedAction = RecommendedAction.IGNORE
    title: str = ""
    explanation: str = ""
    evidence: Dict = field(default_factory=dict)
    estimated_benefit: str = ""
    risk: str = "NONE"
    safe_to_auto_suggest: bool = False

    def __post_init__(self):
        if not self.id:
            self.id = f"prec_{uuid.uuid4().hex[:8]}"


@dataclass
class ProcessScanResult:
    """Result of a resource intelligence scan."""
    scan_id: str = ""
    timestamp: float = 0.0
    duration_seconds: float = 0.0
    total_processes: int = 0
    classified_processes: Dict[str, int] = field(default_factory=dict)
    top_cpu: List[ProcessResourceSnapshot] = field(default_factory=list)
    top_memory: List[ProcessResourceSnapshot] = field(default_factory=list)
    recommendations: List[ProcessRecommendation] = field(default_factory=list)
    resource_pressure: ResourcePressure = ResourcePressure.NONE
    total_background_cpu: float = 0.0
    total_background_memory_mb: float = 0.0
    errors: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.scan_id:
            self.scan_id = f"pscan_{uuid.uuid4().hex[:8]}"


# ── Extended Classification ────────────────────────────────────────

# Extended game process names (beyond emulator processes)
KNOWN_GAME_PROCESSES = {
    "steam.exe", "epicgameslauncher.exe", "uplay.exe", "gog galaxy.exe",
    "origin.exe", "battle.net.exe", "riot client.exe", "valorant.exe",
    "fortnite.exe", "minecraft.exe", "csgo.exe", "cs2.exe",
}

# Known background services that are safe to recommend closing
SAFE_TO_CLOSE_PROCESSES = {
    "onedrive.exe", "dropbox.exe", "skype.exe", "teams.exe", "slack.exe",
    "zoom.exe", "spotify.exe", "discord.exe",
    "chrome.exe", "firefox.exe", "msedge.exe", "opera.exe",
    "obs64.exe", "obs32.exe",
    "rtknguil.exe", "razer synapse.exe", "ghub.exe", "logitech g hub.exe",
    "icue.exe", "armorycrate.exe",
}


def _classify_extended(name: str) -> ProcessCategory:
    """Classify process into extended categories."""
    name_lower = name.lower()

    # Critical / security → SYSTEM
    if name_lower in CRITICAL_PROCESSES or name_lower in SECURITY_PROCESSES:
        return ProcessCategory.SYSTEM

    # Emulator → EMULATOR
    for emulator_name, procs in EMULATOR_PROCESSES.items():
        if name_lower in [p.lower() for p in procs]:
            return ProcessCategory.EMULATOR

    # Game → GAME
    if name_lower in {g.lower() for g in KNOWN_GAME_PROCESSES}:
        return ProcessCategory.GAME

    # Optional background → BACKGROUND
    if name_lower in {o.lower() for o in OPTIONAL_PROCESSES}:
        return ProcessCategory.BACKGROUND

    # User application patterns
    user_app_keywords = [
        "office", "word", "excel", "powerpoint", "outlook",
        "photoshop", "illustrator", "premiere", "vscode", "code",
        "notepad", "calculator", "paint", "explorer",
    ]
    if any(kw in name_lower for kw in user_app_keywords):
        return ProcessCategory.USER_APPLICATION

    return ProcessCategory.UNKNOWN


# ── ResourceTracker ────────────────────────────────────────────────


class ResourceTracker:
    """
    Track resource usage history for processes over time.
    Maintains a short rolling window of snapshots.
    """

    MAX_HISTORY = 30  # Keep last 30 snapshots per process
    MAX_TRACKED_PROCESSES = 200

    def __init__(self):
        self._history: Dict[int, ProcessResourceHistory] = {}
        self._pid_names: Dict[int, str] = {}
        self._lock = threading.Lock()

    def snapshot(self, processes: Optional[List[ProcessResourceSnapshot]] = None):
        """
        Take a snapshot of current process resources.
        If processes not provided, collects from psutil.
        """
        now = time.time()

        if processes is None:
            processes = self._collect_processes()

        with self._lock:
            for snap in processes:
                pid = snap.pid
                if pid not in self._history:
                    # Limit tracked processes
                    if len(self._history) >= self.MAX_TRACKED_PROCESSES:
                        # Remove oldest by first_seen
                        oldest_pid = min(
                            self._history.keys(),
                            key=lambda p: self._history[p].first_seen,
                        )
                        del self._history[oldest_pid]

                    self._history[pid] = ProcessResourceHistory(
                        pid=pid,
                        name=snap.name,
                        category=snap.category,
                        first_seen=now,
                    )

                hist = self._history[pid]
                hist.last_seen = now
                hist.lifetime_seconds = now - hist.first_seen
                hist.snapshots.append(snap)

                # Keep rolling window
                if len(hist.snapshots) > self.MAX_HISTORY:
                    hist.snapshots = hist.snapshots[-self.MAX_HISTORY:]

    def get_history(self, pid: int) -> Optional[ProcessResourceHistory]:
        """Get resource history for a specific process."""
        with self._lock:
            return self._history.get(pid)

    def get_all_histories(self) -> List[ProcessResourceHistory]:
        """Get all tracked process histories."""
        with self._lock:
            return list(self._history.values())

    def get_top_consumers(
        self, metric: str = "memory", limit: int = 10
    ) -> List[ProcessResourceHistory]:
        """Get top resource consumers by metric."""
        histories = self.get_all_histories()

        if metric == "memory":
            histories.sort(key=lambda h: h.current_memory_mb, reverse=True)
        elif metric == "cpu":
            histories.sort(key=lambda h: h.avg_cpu, reverse=True)
        else:
            histories.sort(key=lambda h: h.current_memory_mb, reverse=True)

        return histories[:limit]

    def cleanup_stale(self, max_age_seconds: float = 300.0):
        """Remove entries for processes that haven't been seen recently."""
        now = time.time()
        with self._lock:
            stale_pids = [
                pid for pid, hist in self._history.items()
                if (now - hist.last_seen) > max_age_seconds
            ]
            for pid in stale_pids:
                del self._history[pid]

    def _collect_processes(self) -> List[ProcessResourceSnapshot]:
        """Collect current process snapshots from psutil."""
        snapshots = []
        try:
            for proc in psutil.process_iter([
                "pid", "name", "cpu_percent", "memory_info", "status",
            ]):
                try:
                    info = proc.info
                    pid = info["pid"]
                    name = info.get("name", "unknown")
                    cpu = info.get("cpu_percent", 0.0) or 0.0
                    mem = info.get("memory_info")
                    mem_mb = (mem.rss / (1024 * 1024)) if mem else 0.0
                    mem_pct = 0.0
                    try:
                        mem_pct = proc.memory_percent()
                    except Exception:
                        pass

                    category = _classify_extended(name)

                    # Disk I/O (if available)
                    disk_read = 0
                    disk_write = 0
                    try:
                        io = proc.io_counters()
                        disk_read = io.read_bytes
                        disk_write = io.write_bytes
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass

                    # Network connections
                    net_conns = 0
                    try:
                        net_conns = len(proc.net_connections())
                    except (psutil.AccessDenied, psutil.NoSuchProcess):
                        pass

                    snap = ProcessResourceSnapshot(
                        pid=pid,
                        name=name,
                        timestamp=time.time(),
                        cpu_percent=cpu,
                        memory_mb=mem_mb,
                        memory_percent=mem_pct,
                        disk_read_bytes=disk_read,
                        disk_write_bytes=disk_write,
                        net_connections=net_conns,
                        status=info.get("status", "unknown"),
                        category=category,
                    )
                    snapshots.append(snap)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
                except Exception:
                    continue
        except Exception as e:
            logger.debug(f"Process collection error: {e}")

        return snapshots


# ── ProcessRecommendationEngine ────────────────────────────────────


class ProcessRecommendationEngine:
    """
    Generate safe, evidence-based recommendations for resource-consuming processes.
    Never recommends killing critical/system processes.
    """

    def __init__(self):
        self._exclusions: Set[str] = set()

    def add_exclusion(self, process_name: str):
        """Add a process to the exclusion list (never recommend closing)."""
        self._exclusions.add(process_name.lower())

    def remove_exclusion(self, process_name: str):
        """Remove a process from the exclusion list."""
        self._exclusions.discard(process_name.lower())

    def is_excluded(self, process_name: str) -> bool:
        """Check if a process is excluded from recommendations."""
        return process_name.lower() in self._exclusions

    @property
    def exclusions(self) -> List[str]:
        return sorted(self._exclusions)

    def generate_recommendations(
        self, histories: List[ProcessResourceHistory]
    ) -> List[ProcessRecommendation]:
        """
        Generate safe recommendations based on resource history.
        Never recommends killing system/critical/emulator processes.
        """
        recs = []

        for hist in histories:
            rec = self._evaluate_process(hist)
            if rec:
                recs.append(rec)

        # Sort by estimated impact (memory first, then CPU)
        recs.sort(key=lambda r: (
            r.evidence.get("memory_mb", 0) + r.evidence.get("cpu_avg", 0) * 10
        ), reverse=True)

        return recs

    def _evaluate_process(
        self, hist: ProcessResourceHistory
    ) -> Optional[ProcessRecommendation]:
        """Evaluate a single process and generate a recommendation if warranted."""
        name = hist.name
        name_lower = name.lower()

        # Never recommend actions on critical/system/emulator processes
        if hist.category in (ProcessCategory.SYSTEM, ProcessCategory.EMULATOR):
            return None

        # Check exclusions
        if self.is_excluded(name):
            return None

        current_mem = hist.current_memory_mb
        avg_cpu = hist.avg_cpu
        lifetime = hist.lifetime_seconds

        # Only generate recommendations for processes using significant resources
        if current_mem < 100 and avg_cpu < 5:
            return None

        # Determine action and severity
        if hist.category == ProcessCategory.BACKGROUND:
            if current_mem > 500 or avg_cpu > 30:
                return ProcessRecommendation(
                    pid=hist.pid,
                    name=name,
                    category=hist.category,
                    action=RecommendedAction.CLOSE,
                    title=f"{name} — {current_mem:.0f} MB RAM",
                    explanation=(
                        f"{name} is consuming {current_mem:.0f} MB RAM "
                        f"with {avg_cpu:.1f}% CPU. Consider closing if not needed."
                    ),
                    evidence={
                        "memory_mb": current_mem,
                        "cpu_avg": avg_cpu,
                        "lifetime_seconds": lifetime,
                    },
                    estimated_benefit=f"Reclaim {current_mem:.0f} MB RAM",
                    risk="LOW",
                    safe_to_auto_suggest=True,
                )
            elif current_mem > 200 or avg_cpu > 10:
                return ProcessRecommendation(
                    pid=hist.pid,
                    name=name,
                    category=hist.category,
                    action=RecommendedAction.REVIEW,
                    title=f"{name} — {current_mem:.0f} MB RAM",
                    explanation=(
                        f"{name} is using {current_mem:.0f} MB RAM. "
                        "Close if not actively used."
                    ),
                    evidence={
                        "memory_mb": current_mem,
                        "cpu_avg": avg_cpu,
                    },
                    estimated_benefit=f"Free {current_mem:.0f} MB",
                    risk="NONE",
                    safe_to_auto_suggest=False,
                )

        elif hist.category == ProcessCategory.USER_APPLICATION:
            if current_mem > 1000 or avg_cpu > 50:
                return ProcessRecommendation(
                    pid=hist.pid,
                    name=name,
                    category=hist.category,
                    action=RecommendedAction.REVIEW,
                    title=f"{name} — {current_mem:.0f} MB RAM",
                    explanation=(
                        f"{name} is using {current_mem:.0f} MB RAM "
                        f"with {avg_cpu:.1f}% CPU. High usage for a user application."
                    ),
                    evidence={
                        "memory_mb": current_mem,
                        "cpu_avg": avg_cpu,
                    },
                    estimated_benefit=f"Free {current_mem:.0f} MB",
                    risk="LOW",
                    safe_to_auto_suggest=False,
                )

        elif hist.category == ProcessCategory.UNKNOWN:
            if current_mem > 300 or avg_cpu > 20:
                return ProcessRecommendation(
                    pid=hist.pid,
                    name=name,
                    category=hist.category,
                    action=RecommendedAction.REVIEW,
                    title=f"Unknown: {name} — {current_mem:.0f} MB RAM",
                    explanation=(
                        f"Unknown process {name} using {current_mem:.0f} MB RAM. "
                        "Review recommended."
                    ),
                    evidence={
                        "memory_mb": current_mem,
                        "cpu_avg": avg_cpu,
                    },
                    estimated_benefit="Identify and possibly free resources",
                    risk="NONE",
                    safe_to_auto_suggest=False,
                )

        return None


# ── ProcessIntelligence (Main Interface) ────────────────────────────


class ProcessIntelligence:
    """
    High-level process resource intelligence.
    Combines ProcessMonitor, ResourceTracker, and ProcessRecommendationEngine.
    """

    def __init__(
        self,
        monitor: Optional[ProcessMonitor] = None,
        tracker: Optional[ResourceTracker] = None,
        rec_engine: Optional[ProcessRecommendationEngine] = None,
    ):
        self._monitor = monitor or process_monitor
        self._tracker = tracker or ResourceTracker()
        self._rec_engine = rec_engine or ProcessRecommendationEngine()
        self._last_scan: Optional[ProcessScanResult] = None

    @property
    def tracker(self) -> ResourceTracker:
        return self._tracker

    @property
    def rec_engine(self) -> ProcessRecommendationEngine:
        return self._rec_engine

    @property
    def last_scan(self) -> Optional[ProcessScanResult]:
        return self._last_scan

    def scan(self) -> ProcessScanResult:
        """
        Perform a full process resource scan.
        Collects current state, updates tracker, generates recommendations.
        """
        start = time.time()
        result = ProcessScanResult(timestamp=start)

        try:
            # Take a snapshot
            self._tracker.snapshot()
            histories = self._tracker.get_all_histories()

            # Count by category
            category_counts: Dict[str, int] = {}
            top_cpu: List[ProcessResourceSnapshot] = []
            top_memory: List[ProcessResourceSnapshot] = []

            # Use fresh snapshot data for top lists
            fresh_snaps = self._tracker._collect_processes()
            result.total_processes = len(fresh_snaps)

            for snap in fresh_snaps:
                cat_name = snap.category.value
                category_counts[cat_name] = category_counts.get(cat_name, 0) + 1

            # Sort for top consumers
            fresh_snaps.sort(key=lambda s: s.cpu_percent, reverse=True)
            top_cpu = fresh_snaps[:10]

            fresh_snaps.sort(key=lambda s: s.memory_mb, reverse=True)
            top_memory = fresh_snaps[:10]

            # Background resource totals
            bg_cpu = 0.0
            bg_memory = 0.0
            for snap in fresh_snaps:
                if snap.category in (
                    ProcessCategory.BACKGROUND,
                    ProcessCategory.USER_APPLICATION,
                    ProcessCategory.UNKNOWN,
                ):
                    bg_cpu += snap.cpu_percent
                    bg_memory += snap.memory_mb

            result.classified_processes = category_counts
            result.top_cpu = top_cpu
            result.top_memory = top_memory
            result.total_background_cpu = bg_cpu
            result.total_background_memory_mb = bg_memory

            # Resource pressure
            result.resource_pressure = self._classify_pressure(
                bg_cpu, bg_memory, len(fresh_snaps)
            )

            # Generate recommendations
            result.recommendations = self._rec_engine.generate_recommendations(
                histories
            )

        except Exception as e:
            logger.error(f"Process scan error: {e}")
            result.errors.append(str(e))

        result.duration_seconds = time.time() - start
        self._last_scan = result
        return result

    def _classify_pressure(
        self, bg_cpu: float, bg_memory_mb: float, process_count: int
    ) -> ResourcePressure:
        """Classify overall background resource pressure."""
        score = 0.0

        # CPU contribution
        if bg_cpu > 80:
            score += 40
        elif bg_cpu > 50:
            score += 25
        elif bg_cpu > 20:
            score += 10

        # Memory contribution (MB)
        if bg_memory_mb > 4000:
            score += 40
        elif bg_memory_mb > 2000:
            score += 25
        elif bg_memory_mb > 1000:
            score += 10

        # Process count contribution
        if process_count > 200:
            score += 20
        elif process_count > 100:
            score += 10

        if score >= 70:
            return ResourcePressure.CRITICAL
        if score >= 45:
            return ResourcePressure.HIGH
        if score >= 25:
            return ResourcePressure.MODERATE
        if score >= 10:
            return ResourcePressure.LOW
        return ResourcePressure.NONE

    def format_status(self) -> str:
        """Format current process intelligence for CLI."""
        scan = self._last_scan
        if not scan:
            scan = self.scan()

        lines = []
        w = 55
        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — PROCESS RESOURCE INTELLIGENCE")
        lines.append("=" * w)

        lines.append(f"\n  TOTAL PROCESSES: {scan.total_processes}")
        lines.append(f"  PRESSURE: {scan.resource_pressure.value}")
        lines.append(
            f"  BACKGROUND CPU: {scan.total_background_cpu:.1f}%"
        )
        lines.append(
            f"  BACKGROUND RAM: {scan.total_background_memory_mb:.0f} MB"
        )

        # Category breakdown
        lines.append(f"\n  CLASSIFICATION")
        lines.append("  " + "-" * (w - 4))
        for cat, count in sorted(
            scan.classified_processes.items(), key=lambda x: x[1], reverse=True
        ):
            lines.append(f"    {cat:<20} {count:>5}")

        # Top memory consumers
        if scan.top_memory:
            lines.append(f"\n  TOP MEMORY CONSUMERS")
            lines.append("  " + "-" * (w - 4))
            for snap in scan.top_memory[:8]:
                cat = snap.category.value
                lines.append(
                    f"    {snap.name:<25} {snap.memory_mb:>8.0f} MB  "
                    f"CPU {snap.cpu_percent:>5.1f}%  [{cat}]"
                )

        # Top CPU consumers
        if scan.top_cpu:
            lines.append(f"\n  TOP CPU CONSUMERS")
            lines.append("  " + "-" * (w - 4))
            for snap in scan.top_cpu[:5]:
                cat = snap.category.value
                lines.append(
                    f"    {snap.name:<25} {snap.cpu_percent:>5.1f}%  "
                    f"RAM {snap.memory_mb:>7.0f} MB  [{cat}]"
                )

        # Recommendations
        if scan.recommendations:
            lines.append(f"\n  RECOMMENDATIONS")
            lines.append("  " + "-" * (w - 4))
            for rec in scan.recommendations[:8]:
                action = rec.action.value
                lines.append(f"    [{action}] {rec.title}")
                lines.append(f"      {rec.explanation}")
        else:
            lines.append(f"\n  No resource concerns identified.")

        if scan.errors:
            lines.append(f"\n  ERRORS")
            for e in scan.errors:
                lines.append(f"    {e}")

        lines.append("\n" + "=" * w)
        return "\n".join(lines)


# ── Singleton ────────────────────────────────────────────────────

process_intelligence = ProcessIntelligence()
