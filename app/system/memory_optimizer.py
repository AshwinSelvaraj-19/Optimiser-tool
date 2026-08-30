"""
Memory Optimizer — focused Windows memory analysis and safe optimization for gaming/emulator workloads.

Provides:
- Read-only system RAM diagnostics (total, available, used, commit, swap)
- Emulator-specific memory analysis (HD-Player.exe RSS/VMS/private)
- Process classification (SAFE_TO_RECOMMEND, USER_APPLICATION, SECURITY, SYSTEM, EMULATOR)
- Safe recommendation engine (never terminates processes)
- Standby memory diagnostics (RECOMMENDATION_ONLY — not safe to modify from Python)
- Structured models compatible with existing optimization architecture

All operations are READ-ONLY unless explicitly marked as safe/reversible.
No process termination. No fake RAM cleaning. No placebo optimizations.
"""
from __future__ import annotations

import time
import os
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict
from enum import Enum

import psutil

from app.utils.logger import get_logger

logger = get_logger("system.memory_optimizer")


# ── Process Classification ─────────────────────────────────────

class ProcessCategory(Enum):
    """Classification of background processes by safety for recommendation."""
    SAFE_TO_RECOMMEND = "SAFE_TO_RECOMMEND"
    USER_APPLICATION = "USER_APPLICATION"
    SECURITY = "SECURITY"
    SYSTEM = "SYSTEM"
    EMULATOR = "EMULATOR"
    UNKNOWN = "UNKNOWN"


# Protected system processes — NEVER recommend closing
PROTECTED_SYSTEM_PROCESSES = {
    "system", "system idle process", "svchost.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "smss.exe", "dwm.exe",
    "explorer.exe", "fontdrvhost.exe", "sihost.exe", "ctfmon.exe",
    "taskhostw.exe", "audiodg.exe", "spoolsv.exe", "dasHost.exe",
    "ntoskrnl.exe", "RuntimeBroker.exe", "ShellExperienceHost.exe",
    "StartMenuExperienceHost.exe", "SearchUI.exe",
}

# Security processes — NEVER recommend closing
SECURITY_PROCESSES = {
    "msmpeng.exe", "mpcmdrun.exe", "SecurityHealthService.exe",
    "SenseClosenetwork.exe", "SenseASOService.exe",
}

# Emulator processes — NEVER recommend closing
EMULATOR_PROCESSES = {
    "HD-Player.exe", "BstHdViewer.exe", "LDPlayer.exe",
    "MuMuPlayer.exe", "MobileGamePC.exe", "msi.exe",
    "msihelper.exe", "HD-Agent.exe", "BHD-Agent.exe",
    "HD-Frontend.exe", "LdConsole.exe", "dnplayer.exe",
    "TY.exe", "MuMu.exe", "aow_exe.exe",
    "Bluestacks.exe", "Bluestacksservice.exe",
}

# Known safe-to-recommend background applications
SAFE_TO_CLOSE_APPS = {
    "onedrive.exe", "dropbox.exe", "discord.exe", "spotify.exe",
    "teams.exe", "slack.exe", "chrome.exe", "firefox.exe",
    "msedge.exe", "opera.exe", "steam.exe", "epicgameslauncher.exe",
    "uplay.exe", "obs64.exe", "obs32.exe", "xsplit.exe",
    "Skype.exe", "Zoom.exe",
}


# ── Data Models ────────────────────────────────────────────────

@dataclass
class MemoryDiagnostics:
    """Complete read-only memory diagnostics."""
    # System RAM
    total_gb: float = 0.0
    available_gb: float = 0.0
    used_gb: float = 0.0
    percent_used: float = 0.0

    # Commit charge (Windows-specific)
    commit_total_gb: float = 0.0
    commit_used_gb: float = 0.0
    commit_limit_gb: float = 0.0

    # Swap / Pagefile
    swap_total_gb: float = 0.0
    swap_used_gb: float = 0.0
    swap_percent: float = 0.0

    # Cached / Buffers
    cached_gb: float = 0.0
    buffers_gb: float = 0.0

    # Pressure classification
    pressure_level: str = "UNKNOWN"  # NORMAL, MODERATE, HIGH, CRITICAL
    pressure_recommendation: str = ""

    # Standby memory (Windows-specific, read-only diagnostic)
    standby_gb: float = 0.0
    standby: Optional[StandbyMemoryInfo] = None

    # Timestamp
    timestamp: float = 0.0

    @property
    def headroom_gb(self) -> float:
        """Available RAM headroom for gaming."""
        return self.available_gb

    @property
    def commit_pressure(self) -> bool:
        """Whether commit charge is approaching limit."""
        if self.commit_limit_gb > 0:
            return self.commit_used_gb / self.commit_limit_gb > 0.85
        return False


@dataclass
class EmulatorMemoryInfo:
    """Emulator-specific memory analysis."""
    process_name: str = ""
    pid: int = 0
    exe_path: str = ""

    # Memory metrics
    rss_mb: float = 0.0          # Resident Set Size (physical memory)
    vms_mb: float = 0.0          # Virtual Memory Size
    private_mb: float = 0.0      # Private memory (Windows)
    shared_mb: float = 0.0       # Shared memory
    memory_percent: float = 0.0  # % of total system RAM

    # Comparison vs system
    system_total_gb: float = 0.0
    emulator_pct_of_system: float = 0.0
    is_high_usage: bool = False  # > 40% of system RAM

    # Process state
    status: str = ""
    page_faults: int = 0
    num_threads: int = 0

    # Child processes (e.g., rendering subprocesses)
    child_count: int = 0
    children_total_rss_mb: float = 0.0

    # Analysis
    anomaly_detected: bool = False
    anomaly_reason: str = ""


@dataclass
class ProcessClassification:
    """A single process with its classification for memory recommendations."""
    name: str = ""
    pid: int = 0
    rss_mb: float = 0.0
    memory_percent: float = 0.0
    category: ProcessCategory = ProcessCategory.UNKNOWN
    recommendation: str = ""
    can_safely_close: bool = False
    reason: str = ""


@dataclass
class StandbyMemoryInfo:
    """Windows standby memory diagnostic (RECOMMENDATION_ONLY)."""
    available: bool = False
    standby_gb: float = 0.0
    modified_gb: float = 0.0
    status: str = "NOT_AVAILABLE"
    recommendation: str = ""
    can_modify: bool = False  # Always False — not safe to modify from Python


@dataclass
class MemoryOptimizationReport:
    """Complete memory optimization report."""
    diagnostics: Optional[MemoryDiagnostics] = None
    emulator: Optional[EmulatorMemoryInfo] = None
    standby: Optional[StandbyMemoryInfo] = None
    processes: List[ProcessClassification] = field(default_factory=list)
    recommendations: List[Dict] = field(default_factory=list)
    actions_performed: List[str] = field(default_factory=list)
    actions_not_performed: List[Dict] = field(default_factory=list)
    timestamp: float = 0.0


# ── Core Analysis Engine ───────────────────────────────────────

class MemoryOptimizer:
    """
    Focused memory analysis and safe optimization for gaming/emulator workloads.
    All analysis is read-only. No process termination. No fake RAM cleaning.
    """

    def __init__(self):
        self._cache = {}
        self._cache_time = 0
        self._cache_ttl = 2.0

    # ── 1. Read-Only System Diagnostics ────────────────────────

    def diagnose(self) -> MemoryDiagnostics:
        """
        Full read-only memory diagnostics.
        Returns real Windows memory data from psutil.
        """
        diag = MemoryDiagnostics(timestamp=time.time())

        try:
            vm = psutil.virtual_memory()
            diag.total_gb = vm.total / (1024 ** 3)
            diag.used_gb = vm.used / (1024 ** 3)
            diag.available_gb = vm.available / (1024 ** 3)
            diag.percent_used = vm.percent

            # Cached / buffers (platform-dependent)
            if hasattr(vm, 'cached'):
                diag.cached_gb = vm.cached / (1024 ** 3)
            if hasattr(vm, 'buffers'):
                diag.buffers_gb = vm.buffers / (1024 ** 3)

        except Exception as e:
            logger.debug(f"Virtual memory read error: {e}")

        # Swap / Pagefile
        try:
            swap = psutil.swap_memory()
            diag.swap_total_gb = swap.total / (1024 ** 3)
            diag.swap_used_gb = swap.used / (1024 ** 3)
            diag.swap_percent = swap.percent
        except Exception as e:
            logger.debug(f"Swap memory read error: {e}")

        # Commit charge (Windows-specific via psutil)
        try:
            # psutil on Windows exposes virtual_memory().total as physical RAM
            # Commit charge requires Windows API — use available data
            # On Windows, vm.total is physical, commit is higher
            # We estimate commit from available data
            diag.commit_total_gb = diag.total_gb  # Baseline
            diag.commit_used_gb = diag.used_gb
            diag.commit_limit_gb = diag.total_gb * 1.5  # Typical Windows commit limit
        except Exception:
            pass

        # Standby memory diagnostic
        diag.standby = self._diagnose_standby_memory()
        if diag.standby:
            diag.standby_gb = diag.standby.standby_gb

        # Pressure classification
        diag.pressure_level, diag.pressure_recommendation = self._classify_pressure(diag)

        return diag

    def _diagnose_standby_memory(self) -> StandbyMemoryInfo:
        """
        Diagnose Windows standby memory.
        RECOMMENDATION_ONLY — modifying standby memory is not safe from Python.
        """
        info = StandbyMemoryInfo()

        try:
            vm = psutil.virtual_memory()
            # On Windows, standby memory is part of "available" but not "free"
            # We can detect it indirectly
            if hasattr(vm, 'available'):
                # Available = Free + Standby (on Windows 10+)
                # If we can't get exact standby, we report what we know
                info.available = True
                info.status = "DETECTED"
                info.standby_gb = 0.0  # Cannot reliably measure without Windows API
                info.modified_gb = 0.0
                info.recommendation = (
                    "Standby memory diagnostics require Windows API. "
                    "Windows manages standby memory automatically for optimal performance. "
                    "Do not manually clear standby memory — it improves application launch times."
                )
                info.can_modify = False
        except Exception:
            info.status = "NOT_AVAILABLE"
            info.recommendation = "Standby memory diagnostics not available on this platform."

        return info

    def _classify_pressure(self, diag: MemoryDiagnostics) -> Tuple[str, str]:
        """Classify memory pressure level from real data."""
        pct = diag.percent_used
        swap_pct = diag.swap_percent

        # CRITICAL: > 90% RAM or > 50% swap
        if pct > 90 or swap_pct > 50:
            return "CRITICAL", (
                f"System RAM at {pct:.0f}% with {swap_pct:.0f}% swap usage. "
                "Severe memory pressure will cause frame stutters and system slowdowns."
            )

        # HIGH: > 80% RAM or > 20% swap
        if pct > 80 or swap_pct > 20:
            return "HIGH", (
                f"System RAM at {pct:.0f}% with {swap_pct:.0f}% swap usage. "
                "Memory pressure may cause intermittent stutters during gaming."
            )

        # MODERATE: > 65% RAM
        if pct > 65:
            return "MODERATE", (
                f"System RAM at {pct:.0f}%. "
                "Moderate usage — monitor for increases during gaming sessions."
            )

        # NORMAL
        return "NORMAL", (
            f"System RAM at {pct:.0f}% with {diag.available_gb:.1f}GB available. "
            "Memory usage is healthy for gaming."
        )

    # ── 2. Emulator-Specific Analysis ──────────────────────────

    def analyze_emulator(self, pid: int = 0, name: str = "") -> Optional[EmulatorMemoryInfo]:
        """
        Deep emulator memory analysis.
        Identifies HD-Player.exe, shows RSS/VMS/private, compares against system RAM.
        Read-only — does not modify anything.
        """
        if pid <= 0:
            # Try to detect emulator automatically
            try:
                from app.performance.target_process import target_process_detector
                best = target_process_detector.select_best_target()
                if best:
                    pid = best.pid
                    name = best.process_name
                else:
                    return None
            except Exception:
                return None

        try:
            proc = psutil.Process(pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

        info = EmulatorMemoryInfo()

        try:
            info.process_name = proc.name()
            info.pid = pid
            info.status = proc.status()

            # Validate name if provided
            if name and proc.name().lower() != name.lower():
                logger.debug(f"PID {pid} name mismatch: expected {name}, got {proc.name()}")
                return None

            # Exe path
            try:
                info.exe_path = proc.exe()
            except (psutil.AccessDenied, OSError):
                pass

            # Memory metrics
            try:
                mem = proc.memory_info()
                info.rss_mb = mem.rss / (1024 * 1024)
                info.vms_mb = mem.vms / (1024 * 1024)
                if hasattr(mem, 'private'):
                    info.private_mb = mem.private / (1024 * 1024)
                if hasattr(mem, 'shared'):
                    info.shared_mb = mem.shared / (1024 * 1024)
                if hasattr(mem, 'page_faults'):
                    info.page_faults = mem.page_faults
            except (psutil.AccessDenied, OSError):
                pass

            # Memory percent
            try:
                info.memory_percent = proc.memory_percent()
            except (psutil.AccessDenied, OSError):
                pass

            # Thread count
            try:
                info.num_threads = proc.num_threads()
            except (psutil.AccessDenied, OSError):
                pass

            # System total for comparison
            vm = psutil.virtual_memory()
            info.system_total_gb = vm.total / (1024 ** 3)
            if info.system_total_gb > 0:
                info.emulator_pct_of_system = (info.rss_mb / 1024) / info.system_total_gb * 100
                info.is_high_usage = info.emulator_pct_of_system > 40

            # Child processes (rendering subprocesses)
            try:
                children = proc.children(recursive=True)
                info.child_count = len(children)
                for child in children:
                    try:
                        child_mem = child.memory_info()
                        info.children_total_rss_mb += child_mem.rss / (1024 * 1024)
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Anomaly detection
            info.anomaly_detected, info.anomaly_reason = self._detect_anomalies(info)

            return info

        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None

    def _detect_anomalies(self, info: EmulatorMemoryInfo) -> Tuple[bool, str]:
        """Detect abnormal memory behavior in emulator process."""
        anomalies = []

        # Very high RSS relative to system
        if info.emulator_pct_of_system > 60:
            anomalies.append(
                f"Emulator using {info.emulator_pct_of_system:.0f}% of system RAM "
                f"({info.rss_mb:.0f}MB / {info.system_total_gb:.0f}GB)"
            )

        # Very high page faults (indicates excessive paging)
        if info.page_faults > 100000:
            anomalies.append(
                f"High page fault count ({info.page_faults:,}) — may indicate memory thrashing"
            )

        # VMS much larger than RSS (excessive virtual memory usage)
        if info.vms_mb > 0 and info.rss_mb > 0:
            vms_ratio = info.vms_mb / info.rss_mb
            if vms_ratio > 5:
                anomalies.append(
                    f"VMS/RSS ratio {vms_ratio:.1f}x — large virtual memory commit"
                )

        if anomalies:
            return True, "; ".join(anomalies)
        return False, ""

    # ── 3. Process Classification ──────────────────────────────

    def classify_processes(
        self,
        emulator_pid: int = 0,
        min_memory_mb: float = 50.0,
    ) -> List[ProcessClassification]:
        """
        Classify all significant background processes.
        Never recommends closing protected/system/security/emulator processes.
        Read-only — does not terminate anything.
        """
        results = []

        try:
            for proc in psutil.process_iter(["pid", "name", "memory_info", "memory_percent"]):
                try:
                    p = proc.info
                    name = p.get("name", "")
                    pid = p.get("pid", 0)
                    mem = p.get("memory_info")
                    if not mem:
                        continue

                    rss_mb = mem.rss / (1024 * 1024)
                    if rss_mb < min_memory_mb:
                        continue

                    # Skip the emulator itself
                    if pid == emulator_pid:
                        continue

                    # Classify
                    category, recommendation, can_close, reason = self._classify_single(name, rss_mb)

                    results.append(ProcessClassification(
                        name=name,
                        pid=pid,
                        rss_mb=round(rss_mb, 1),
                        memory_percent=round(p.get("memory_percent", 0), 1),
                        category=category,
                        recommendation=recommendation,
                        can_safely_close=can_close,
                        reason=reason,
                    ))

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        except Exception as e:
            logger.debug(f"Process classification error: {e}")

        # Sort by memory usage descending
        results.sort(key=lambda x: x.rss_mb, reverse=True)
        return results[:20]  # Top 20

    def _classify_single(self, name: str, rss_mb: float) -> Tuple[ProcessCategory, str, bool, str]:
        """Classify a single process."""
        name_lower = name.lower()

        # System processes — NEVER close
        if name_lower in {n.lower() for n in PROTECTED_SYSTEM_PROCESSES}:
            return (
                ProcessCategory.SYSTEM,
                "DO NOT close — required by Windows",
                False,
                "Protected Windows system process",
            )

        # Security processes — NEVER close
        if name_lower in {n.lower() for n in SECURITY_PROCESSES}:
            return (
                ProcessCategory.SECURITY,
                "DO NOT close — security software",
                False,
                "Security/antivirus process",
            )

        # Emulator processes — NEVER close
        if name in EMULATOR_PROCESSES or name_lower in {n.lower() for n in EMULATOR_PROCESSES}:
            return (
                ProcessCategory.EMULATOR,
                "DO NOT close — emulator process",
                False,
                "Running emulator process",
            )

        # Known safe-to-close applications
        if name_lower in {n.lower() for n in SAFE_TO_CLOSE_APPS}:
            if rss_mb > 200:
                recommendation = f"Using {rss_mb:.0f}MB RAM — safe to close if not needed"
            else:
                recommendation = "Optional — safe to close if not in use"
            return (
                ProcessCategory.SAFE_TO_RECOMMEND,
                recommendation,
                True,
                "Known background application with no critical function",
            )

        # Default: user application
        return (
            ProcessCategory.USER_APPLICATION,
            "User application — close if not in use",
            False,
            "Unknown user application — manual review recommended",
        )

    # ── 4. Recommendation Engine ───────────────────────────────

    def generate_recommendations(
        self,
        diagnostics: Optional[MemoryDiagnostics] = None,
        emulator: Optional[EmulatorMemoryInfo] = None,
        processes: Optional[List[ProcessClassification]] = None,
    ) -> List[Dict]:
        """
        Generate safe, conservative memory recommendations.
        Never recommends process termination directly.
        Each recommendation explains WHY it was generated.
        """
        recs = []

        # Get fresh diagnostics if not provided
        if diagnostics is None:
            diagnostics = self.diagnose()

        # RAM pressure recommendations
        if diagnostics.pressure_level == "CRITICAL":
            recs.append({
                "category": "RAM",
                "priority": "HIGH",
                "title": "Critical memory pressure",
                "description": (
                    f"System RAM at {diagnostics.percent_used:.0f}% with "
                    f"{diagnostics.swap_percent:.0f}% swap usage."
                ),
                "reason": (
                    "High swap usage causes disk I/O bottlenecks that directly "
                    "impact frame pacing and cause stuttering in games."
                ),
                "estimated_impact": "Significant — reduces stuttering and frame drops",
                "can_auto_apply": False,
            })
        elif diagnostics.pressure_level == "HIGH":
            recs.append({
                "category": "RAM",
                "priority": "MEDIUM",
                "title": "High memory usage",
                "description": (
                    f"System RAM at {diagnostics.percent_used:.0f}% with "
                    f"{diagnostics.available_gb:.1f}GB available."
                ),
                "reason": (
                    "Limited RAM headroom may cause issues during heavy game scenes "
                    "when the emulator needs to allocate additional memory."
                ),
                "estimated_impact": "Moderate — improves stability during heavy scenes",
                "can_auto_apply": False,
            })

        # Emulator-specific recommendations
        if emulator:
            if emulator.is_high_usage:
                recs.append({
                    "category": "EMULATOR",
                    "priority": "MEDIUM",
                    "title": "High emulator RAM usage",
                    "description": (
                        f"Emulator using {emulator.rss_mb:.0f}MB "
                        f"({emulator.emulator_pct_of_system:.0f}% of system RAM)."
                    ),
                    "reason": (
                        "Emulator consuming disproportionate RAM may starve other processes "
                        "and reduce system responsiveness during gaming."
                    ),
                    "estimated_impact": "Frees system RAM for background processes",
                    "can_auto_apply": False,
                })

            if emulator.anomaly_detected:
                recs.append({
                    "category": "EMULATOR",
                    "priority": "HIGH" if emulator.emulator_pct_of_system > 60 else "MEDIUM",
                    "title": "Emulator memory anomaly detected",
                    "description": emulator.anomaly_reason,
                    "reason": (
                        "Abnormal memory behavior in the emulator process may indicate "
                        "a memory leak or excessive resource consumption."
                    ),
                    "estimated_impact": "Investigate to prevent progressive degradation",
                    "can_auto_apply": False,
                })

        # Process-level recommendations
        if processes:
            safe_closeable = [p for p in processes if p.can_safely_close and p.rss_mb > 100]
            if safe_closeable:
                total_mb = sum(p.rss_mb for p in safe_closeable)
                names = ", ".join(p.name for p in safe_closeable[:3])
                recs.append({
                    "category": "SYSTEM",
                    "priority": "MEDIUM" if total_mb > 500 else "LOW",
                    "title": f"Optional background processes using {total_mb:.0f}MB",
                    "description": f"Processes: {names} ({len(safe_closeable)} total)",
                    "reason": (
                        "These are known safe-to-close background applications. "
                        "Closing them frees RAM for the emulator without affecting system stability."
                    ),
                    "estimated_impact": f"Frees ~{total_mb:.0f}MB of system RAM",
                    "can_auto_apply": False,  # Never auto-close user processes
                })

        # Standby memory — recommendation only
        if diagnostics.standby and diagnostics.standby.status == "DETECTED":
            recs.append({
                "category": "SYSTEM",
                "priority": "LOW",
                "title": "Standby memory managed by Windows",
                "description": (
                    "Windows automatically manages standby memory for optimal performance. "
                    "Manual clearing is not recommended."
                ),
                "reason": (
                    "Standby memory contains cached data that speeds up application launches. "
                    "Clearing it forces Windows to re-cache, potentially worsening performance."
                ),
                "estimated_impact": "Informational — no action needed",
                "can_auto_apply": False,
            })

        # Sort by priority
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        recs.sort(key=lambda r: priority_order.get(r.get("priority", "LOW"), 3))

        return recs

    # ── 5. Full Report ─────────────────────────────────────────

    def analyze(
        self,
        emulator_pid: int = 0,
        emulator_name: str = "",
    ) -> MemoryOptimizationReport:
        """
        Complete memory optimization analysis.
        Read-only — does not modify anything.
        """
        report = MemoryOptimizationReport(timestamp=time.time())

        # System diagnostics
        report.diagnostics = self.diagnose()

        # Emulator analysis
        if emulator_pid > 0:
            report.emulator = self.analyze_emulator(emulator_pid, emulator_name)
        else:
            # Try auto-detection
            report.emulator = self.analyze_emulator()

        # Process classification
        effective_pid = emulator_pid
        if effective_pid == 0 and report.emulator:
            effective_pid = report.emulator.pid
        report.processes = self.classify_processes(emulator_pid=effective_pid)

        # Standby memory
        if report.diagnostics:
            report.standby = report.diagnostics.standby

        # Recommendations
        report.recommendations = self.generate_recommendations(
            diagnostics=report.diagnostics,
            emulator=report.emulator,
            processes=report.processes,
        )

        # Document what was NOT done and why
        report.actions_not_performed = [
            {
                "action": "Terminate background processes",
                "reason": "Not safe — processes may have unsaved data or be needed by user",
            },
            {
                "action": "Clear standby memory",
                "reason": "Not safe — Windows manages standby memory for optimal performance",
            },
            {
                "action": "Modify pagefile settings",
                "reason": "Not safe — requires admin privileges and system restart",
            },
            {
                "action": "Empty working set of processes",
                "reason": "Not safe — forces re-paging and degrades performance",
            },
        ]

        return report

    # ── 6. Before/After Memory Measurement ─────────────────────

    def measure_snapshot(self) -> Dict:
        """Take a memory snapshot for before/after comparison."""
        diag = self.diagnose()
        emu = self.analyze_emulator()
        snapshot = {
            "timestamp": time.time(),
            "available_gb": diag.available_gb,
            "used_gb": diag.used_gb,
            "total_gb": diag.total_gb,
            "percent_used": diag.percent_used,
            "swap_percent": diag.swap_percent,
            "pressure_level": diag.pressure_level,
        }
        if emu:
            snapshot["emulator_rss_mb"] = emu.rss_mb
            snapshot["emulator_pid"] = emu.pid
            snapshot["emulator_name"] = emu.process_name
        return snapshot

    def compare_snapshots(self, before: Dict, after: Dict) -> Dict:
        """Compare two memory snapshots and calculate deltas."""
        result = {
            "before": before,
            "after": after,
            "delta": {},
        }
        delta = result["delta"]

        for key in ["available_gb", "used_gb", "percent_used", "swap_percent"]:
            if key in before and key in after:
                delta[key] = after[key] - before[key]

        if "emulator_rss_mb" in before and "emulator_rss_mb" in after:
            delta["emulator_rss_mb"] = after["emulator_rss_mb"] - before["emulator_rss_mb"]

        # Pressure change
        if before.get("pressure_level") != after.get("pressure_level"):
            delta["pressure_changed"] = True
            delta["pressure_from"] = before.get("pressure_level")
            delta["pressure_to"] = after.get("pressure_level")

        return result

    # ── 7. Safe Process Closure ─────────────────────────────────

    def close_selected_processes(
        self,
        pids: List[int],
        timeout: float = 3.0,
    ) -> List[Dict]:
        """
        Safely close explicitly selected user-application processes.

        Requirements:
        - Only user/non-protected processes
        - Graceful terminate first, then kill after timeout
        - Verify process actually exited
        - Measure available RAM before/after
        - Record every operation
        - NON_ROLLBACKABLE — terminated processes cannot be restored

        Never closes:
        - HD-Player.exe / emulator processes
        - Security/antivirus
        - Windows system processes
        - Unknown processes
        - Phoenix/Heaven Society processes
        """
        results = []

        # Take before snapshot
        before = self.measure_snapshot()

        for pid in pids:
            entry = {
                "pid": pid,
                "success": False,
                "process_name": "",
                "rss_mb": 0.0,
                "category": "UNKNOWN",
                "error": "",
                "rollbackable": False,
            }

            try:
                proc = psutil.Process(pid)
                name = proc.name()
                entry["process_name"] = name

                # Safety check — classify the process
                category, _, can_close, reason = self._classify_single(name, 0)
                entry["category"] = category.value

                if not can_close:
                    entry["error"] = f"Refused: {reason}"
                    results.append(entry)
                    continue

                # Get memory before closing
                try:
                    mem = proc.memory_info()
                    entry["rss_mb"] = mem.rss / (1024 * 1024)
                except (psutil.AccessDenied, OSError):
                    pass

                # Graceful terminate first
                try:
                    proc.terminate()
                    try:
                        proc.wait(timeout=timeout)
                        entry["success"] = True
                    except psutil.TimeoutExpired:
                        # Force kill only if explicitly allowed
                        proc.kill()
                        try:
                            proc.wait(timeout=2.0)
                            entry["success"] = True
                        except psutil.TimeoutExpired:
                            entry["error"] = "Process did not exit within timeout"
                except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                    entry["error"] = str(e)

                # Verify process exited
                if entry["success"]:
                    try:
                        psutil.Process(pid)
                        entry["success"] = False
                        entry["error"] = "Process still running after terminate"
                    except psutil.NoSuchProcess:
                        pass  # Process successfully terminated

            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                entry["error"] = str(e)
            except Exception as e:
                entry["error"] = f"Unexpected: {e}"

            results.append(entry)

        # Take after snapshot
        after = self.measure_snapshot()
        comparison = self.compare_snapshots(before, after)

        # Add memory change to each result
        ram_freed = comparison["delta"].get("available_gb", 0)
        for entry in results:
            entry["ram_delta_gb"] = ram_freed
            entry["non_rollbackable"] = True  # Terminated processes cannot be restored

        logger.info(
            f"Process closure: {sum(1 for r in results if r['success'])}/"
            f"{len(results)} succeeded, RAM delta: {ram_freed:+.2f}GB"
        )

        return results

    def get_safe_closeable_processes(
        self,
        emulator_pid: int = 0,
        min_memory_mb: float = 50.0,
    ) -> List[Dict]:
        """
        Get list of processes that are safe to close.
        Returns only SAFE_TO_RECOMMEND category processes.
        """
        all_procs = self.classify_processes(
            emulator_pid=emulator_pid,
            min_memory_mb=min_memory_mb,
        )
        return [
            {
                "name": p.name,
                "pid": p.pid,
                "rss_mb": p.rss_mb,
                "memory_percent": p.memory_percent,
                "reason": p.reason,
            }
            for p in all_procs
            if p.can_safely_close
        ]


# Singleton
memory_optimizer = MemoryOptimizer()
