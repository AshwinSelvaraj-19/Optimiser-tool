"""
Background Load Analyzer — Intelligent process impact analysis for gaming/emulator workloads.

Provides:
- Full process inventory with CPU, RAM, thread, and disk activity metrics
- Process categorization (SYSTEM, SECURITY, EMULATOR, USER_APPLICATION, WINDOWS_SERVICE, UNKNOWN)
- Gaming impact score per process based on actual measurements
- CPU competition analysis
- RAM competition analysis
- Disk activity analysis
- GPU competition detection (when available)
- Recommendation engine: SAFE_TO_RECOMMEND / REVIEW_REQUIRED / DO_NOT_TOUCH

All operations are READ-ONLY. Never terminates processes.
Never modifies security software, system processes, or emulator processes.
"""

import time
import os
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum

import psutil

from app.utils.logger import get_logger

logger = get_logger("system.background_analyzer")


# ── Process Classification ─────────────────────────────────────

class ProcessCategory(Enum):
    """Classification of running processes."""
    SYSTEM = "SYSTEM"
    SECURITY = "SECURITY"
    EMULATOR = "EMULATOR"
    WINDOWS_SERVICE = "WINDOWS_SERVICE"
    USER_APPLICATION = "USER_APPLICATION"
    UNKNOWN = "UNKNOWN"


class Recommendation(Enum):
    """Action recommendation for a process."""
    SAFE_TO_RECOMMEND = "SAFE_TO_RECOMMEND"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    DO_NOT_TOUCH = "DO_NOT_TOUCH"


class CompetitionLevel(Enum):
    """Level of resource competition."""
    NONE = "NONE"
    LOW = "LOW"
    MODERATE = "MODERATE"
    HIGH = "HIGH"
    SEVERE = "SEVERE"


# ── Protected processes (never recommend closing) ───────────────

SYSTEM_PROCESSES = {
    "system", "system idle process", "svchost.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "smss.exe", "dwm.exe",
    "explorer.exe", "fontdrvhost.exe", "sihost.exe", "ctfmon.exe",
    "taskhostw.exe", "audiodg.exe", "spoolsv.exe", "dasHost.exe",
    "ntoskrnl.exe", "runtimebroker.exe", "shellexperiencehost.exe",
    "startmenuexperiencehost.exe", "searchui.exe", "applicationframehost.exe",
    "textinputhost.exe", "dllhost.exe", "conhost.exe", "wermgr.exe",
    "werfault.exe", "smartscreen.exe", "searchprotocolhost.exe",
    "searchfilterhost.exe", "compptc.exe",
}

SECURITY_PROCESSES = {
    "msmpeng.exe", "mpcmdrun.exe", "securityhealthservice.exe",
    "senseclosenetwork.exe", "senseanalyticsservice.exe", "senseasoservice.exe",
    "wscsvc.dll",
}

EMULATOR_PROCESSES = {
    "HD-Player.exe", "BstHdViewer.exe", "LDPlayer.exe",
    "MuMuPlayer.exe", "MobileGamePC.exe", "msi.exe",
    "msihelper.exe", "HD-Agent.exe", "BHD-Agent.exe",
    "HD-Frontend.exe", "LdConsole.exe", "dnplayer.exe",
    "TY.exe", "MuMu.exe", "aow_exe.exe",
    "Bluestacks.exe", "Bluestacksservice.exe",
    "HD-Service.exe", "BstHdDriver.exe", "VBoxHeadless.exe",
}

HEAVEN_SOCIETY_PROCESSES = {"python.exe", "pythonw.exe", "PresentMon_x64.exe"}

# Known safe-to-recommend processes
SAFE_TO_CLOSE_APPS = {
    "onedrive.exe", "dropbox.exe", "discord.exe", "spotify.exe",
    "teams.exe", "slack.exe", "chrome.exe", "firefox.exe",
    "msedge.exe", "opera.exe", "steam.exe", "epicgameslauncher.exe",
    "uplay.exe", "obs64.exe", "obs32.exe", "xsplit.exe",
    "skype.exe", "zoom.exe", "sublime_text.exe", "notepad++.exe",
    "code.exe", "devenv.exe", "gitkraken.exe", "sourcetree.exe",
    "brave.exe", "vivaldi.exe", "waterfox.exe", "tor.exe",
    "qbittorrent.exe", "transmission.exe", "deluge.exe",
    "utorrent.exe", "bittorrent.exe",
    "rtknguil.exe", "razer synapse.exe", "ghub.exe", "logitech g hub.exe",
    "icue.exe", "armorycrate.exe", "gamenexus.exe",
}


# ── Data Models ────────────────────────────────────────────────

@dataclass
class ProcessInventory:
    """A single process with detailed resource metrics."""
    pid: int = 0
    name: str = ""
    cpu_percent: float = 0.0
    ram_bytes: int = 0
    ram_mb: float = 0.0
    ram_percent: float = 0.0
    thread_count: int = 0
    handle_count: int = 0
    disk_read_bytes: int = 0
    disk_write_bytes: int = 0
    io_read_mb: float = 0.0
    io_write_mb: float = 0.0
    status: str = ""

    # Classification
    category: ProcessCategory = ProcessCategory.UNKNOWN
    recommendation: Recommendation = Recommendation.DO_NOT_TOUCH
    recommendation_reason: str = ""

    # Impact scoring
    gaming_impact_score: float = 0.0  # 0-100 scale
    cpu_competition: bool = False
    ram_competition: bool = False
    disk_competition: bool = False


@dataclass
class CompetitionAnalysis:
    """Analysis of resource competition with the emulator."""
    level: CompetitionLevel = CompetitionLevel.NONE
    cpu_competing_processes: List[ProcessInventory] = field(default_factory=list)
    ram_competing_processes: List[ProcessInventory] = field(default_factory=list)
    disk_competing_processes: List[ProcessInventory] = field(default_factory=list)
    total_competition_cpu: float = 0.0
    total_competition_ram_mb: float = 0.0
    description: str = ""


@dataclass
class BackgroundAnalysis:
    """Complete background load analysis result."""
    # Inventory
    processes: List[ProcessInventory] = field(default_factory=list)
    total_count: int = 0
    significant_count: int = 0  # processes with measurable impact

    # Competition
    cpu_competition: Optional[CompetitionAnalysis] = None
    ram_competition: Optional[CompetitionAnalysis] = None
    disk_competition: Optional[CompetitionAnalysis] = None

    # Top consumers
    top_cpu_processes: List[ProcessInventory] = field(default_factory=list)
    top_ram_processes: List[ProcessInventory] = field(default_factory=list)
    top_disk_processes: List[ProcessInventory] = field(default_factory=list)

    # Safe-to-recommend processes
    safe_candidates: List[ProcessInventory] = field(default_factory=list)

    # Overall gaming impact
    overall_impact_level: CompetitionLevel = CompetitionLevel.NONE
    overall_description: str = ""

    # Emulator info
    emulator_pid: int = 0
    emulator_name: str = ""

    # Timestamp
    timestamp: float = 0.0


# ── Core Analyzer ──────────────────────────────────────────────

class BackgroundLoadAnalyzer:
    """
    Intelligent background load analyzer for gaming/emulator workloads.
    All operations are READ-ONLY. Never terminates processes.
    """

    def __init__(self):
        self._cache: Optional[BackgroundAnalysis] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 3.0  # seconds

    def analyze(
        self,
        emulator_pid: int = 0,
        emulator_name: str = "",
        force: bool = False,
    ) -> BackgroundAnalysis:
        """
        Perform full background load analysis.
        Returns structured analysis of all processes competing for resources.
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        result = BackgroundAnalysis(
            emulator_pid=emulator_pid,
            emulator_name=emulator_name,
            timestamp=now,
        )

        try:
            # 1. Build process inventory
            result.processes = self._build_inventory(emulator_pid)
            result.total_count = len(result.processes)
            result.significant_count = sum(
                1 for p in result.processes
                if p.cpu_percent > 0.5 or p.ram_mb > 50
            )

            # 2. Classify processes
            for proc in result.processes:
                proc.category, proc.recommendation, proc.recommendation_reason = \
                    self._classify_process(proc.name, proc.pid, emulator_pid)

            # 3. Calculate gaming impact scores
            self._calculate_impact_scores(result.processes)

            # 4. Analyze competitions
            result.cpu_competition = self._analyze_cpu_competition(
                result.processes, emulator_pid
            )
            result.ram_competition = self._analyze_ram_competition(
                result.processes, emulator_pid
            )
            result.disk_competition = self._analyze_disk_competition(
                result.processes, emulator_pid
            )

            # 5. Top consumers
            result.top_cpu_processes = sorted(
                [p for p in result.processes if p.pid != emulator_pid],
                key=lambda x: x.cpu_percent, reverse=True
            )[:10]
            result.top_ram_processes = sorted(
                [p for p in result.processes if p.pid != emulator_pid],
                key=lambda x: x.ram_mb, reverse=True
            )[:10]
            result.top_disk_processes = sorted(
                [p for p in result.processes if p.pid != emulator_pid],
                key=lambda x: x.io_read_mb + x.io_write_mb, reverse=True
            )[:10]

            # 6. Safe candidates
            result.safe_candidates = [
                p for p in result.processes
                if p.recommendation == Recommendation.SAFE_TO_RECOMMEND
                and p.gaming_impact_score > 5
            ]
            result.safe_candidates.sort(
                key=lambda x: x.gaming_impact_score, reverse=True
            )

            # 7. Overall assessment
            result.overall_impact_level, result.overall_description = \
                self._assess_overall_impact(result)

        except Exception as e:
            logger.error(f"Background analysis error: {e}")
            result.overall_description = f"Analysis error: {e}"

        self._cache = result
        self._cache_time = now
        return result

    def _build_inventory(self, emulator_pid: int) -> List[ProcessInventory]:
        """Build a full inventory of running processes with resource metrics."""
        processes = []

        # Pre-collect IO counters for all processes
        io_counters = {}
        try:
            for proc in psutil.process_iter(["pid"]):
                try:
                    pid = proc.info["pid"]
                    io = proc.io_counters()
                    io_counters[pid] = {
                        "read_bytes": io.read_bytes,
                        "write_bytes": io.write_bytes,
                    }
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                    continue
        except Exception:
            pass

        # Build inventory
        for proc in psutil.process_iter([
            "pid", "name", "cpu_percent", "memory_info",
            "num_threads", "status"
        ]):
            try:
                info = proc.info
                name = info.get("name", "")
                pid = info.get("pid", 0)
                if not name or pid <= 0:
                    continue

                cpu = info.get("cpu_percent", 0.0) or 0.0

                mem = info.get("memory_info")
                ram_bytes = mem.rss if mem else 0
                ram_mb = ram_bytes / (1024 * 1024)

                # Skip very low-impact processes
                if cpu < 0.1 and ram_mb < 10:
                    continue

                # Memory percent
                try:
                    ram_percent = proc.memory_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    ram_percent = 0.0

                # Thread count
                threads = info.get("num_threads", 0) or 0

                # Handle count (Windows only)
                handles = 0
                try:
                    handles = proc.num_handles()
                except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError, OSError):
                    pass

                # IO counters
                io = io_counters.get(pid, {})
                io_read = io.get("read_bytes", 0)
                io_write = io.get("write_bytes", 0)

                processes.append(ProcessInventory(
                    pid=pid,
                    name=name,
                    cpu_percent=cpu,
                    ram_bytes=ram_bytes,
                    ram_mb=round(ram_mb, 1),
                    ram_percent=round(ram_percent, 2),
                    thread_count=threads,
                    handle_count=handles,
                    disk_read_bytes=io_read,
                    disk_write_bytes=io_write,
                    io_read_mb=round(io_read / (1024 * 1024), 1),
                    io_write_mb=round(io_write / (1024 * 1024), 1),
                    status=info.get("status", "unknown"),
                ))

            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            except Exception:
                continue

        return processes

    def _classify_process(
        self,
        name: str,
        pid: int,
        emulator_pid: int,
    ) -> Tuple[ProcessCategory, Recommendation, str]:
        """
        Classify a process into category and determine recommendation.
        Returns (category, recommendation, reason).
        """
        name_lower = name.lower()

        # Emulator process
        if name in EMULATOR_PROCESSES or pid == emulator_pid:
            return (
                ProcessCategory.EMULATOR,
                Recommendation.DO_NOT_TOUCH,
                "Emulator process — required for gaming"
            )

        # System process
        if name_lower in SYSTEM_PROCESSES or name_lower.startswith("svchost"):
            return (
                ProcessCategory.SYSTEM,
                Recommendation.DO_NOT_TOUCH,
                "Windows system process"
            )

        # Security process
        if name_lower in SECURITY_PROCESSES:
            return (
                ProcessCategory.SECURITY,
                Recommendation.DO_NOT_TOUCH,
                "Security software — never disable"
            )

        # Windows Service (by status)
        try:
            proc = psutil.Process(pid)
            if proc.status() == psutil.STATUS_RUNNING:
                pass  # Continue to other checks
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Known safe-to-close
        if name_lower in {n.lower() for n in SAFE_TO_CLOSE_APPS}:
            return (
                ProcessCategory.USER_APPLICATION,
                Recommendation.SAFE_TO_RECOMMEND,
                "Known optional application — safe to close"
            )

        # Heaven Society
        if name_lower in {n.lower() for n in HEAVEN_SOCIETY_PROCESSES}:
            return (
                ProcessCategory.SYSTEM,
                Recommendation.DO_NOT_TOUCH,
                "Heaven Society process"
            )

        # Check if it's a known Windows service by path
        try:
            proc = psutil.Process(pid)
            exe = proc.exe()
            if "\\windows\\" in exe.lower() or "\\microsoft\\" in exe.lower():
                return (
                    ProcessCategory.WINDOWS_SERVICE,
                    Recommendation.REVIEW_REQUIRED,
                    "Windows component — review before closing"
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            pass

        # Unknown user application
        return (
            ProcessCategory.USER_APPLICATION,
            Recommendation.REVIEW_REQUIRED,
            "Unknown application — review before closing"
        )

    def _calculate_impact_scores(self, processes: List[ProcessInventory]):
        """
        Calculate gaming impact score (0-100) for each process.
        Higher score = more competition with emulator.
        """
        for proc in processes:
            score = 0.0

            # CPU impact (0-40 points)
            if proc.cpu_percent > 20:
                score += min(40, proc.cpu_percent * 2)
            elif proc.cpu_percent > 5:
                score += proc.cpu_percent
            elif proc.cpu_percent > 1:
                score += proc.cpu_percent * 0.5

            # RAM impact (0-30 points)
            if proc.ram_mb > 500:
                score += min(30, proc.ram_mb / 30)
            elif proc.ram_mb > 100:
                score += proc.ram_mb / 20
            elif proc.ram_mb > 50:
                score += proc.ram_mb / 50

            # Thread count impact (0-10 points)
            if proc.thread_count > 50:
                score += min(10, proc.thread_count / 10)
            elif proc.thread_count > 20:
                score += proc.thread_count / 20

            # Disk I/O impact (0-15 points)
            total_io = proc.io_read_mb + proc.io_write_mb
            if total_io > 1000:
                score += min(15, total_io / 100)
            elif total_io > 100:
                score += total_io / 100

            # High handle count (0-5 points)
            if proc.handle_count > 1000:
                score += min(5, proc.handle_count / 500)

            # Cap at 100
            proc.gaming_impact_score = round(min(100.0, score), 1)

            # Mark competition types
            proc.cpu_competition = proc.cpu_percent > 3
            proc.ram_competition = proc.ram_mb > 200
            proc.disk_competition = (proc.io_read_mb + proc.io_write_mb) > 500

    def _analyze_cpu_competition(
        self,
        processes: List[ProcessInventory],
        emulator_pid: int,
    ) -> CompetitionAnalysis:
        """Analyze CPU competition with the emulator."""
        analysis = CompetitionAnalysis()

        competing = [
            p for p in processes
            if p.pid != emulator_pid
            and p.cpu_competition
            and p.recommendation != Recommendation.DO_NOT_TOUCH
        ]
        competing.sort(key=lambda x: x.cpu_percent, reverse=True)

        analysis.cpu_competing_processes = competing[:10]
        analysis.total_competition_cpu = sum(p.cpu_percent for p in competing)

        # Determine level
        if analysis.total_competition_cpu > 30:
            analysis.level = CompetitionLevel.SEVERE
            analysis.description = (
                f"{len(competing)} processes using {analysis.total_competition_cpu:.1f}% CPU "
                f"outside emulator — significant CPU competition detected"
            )
        elif analysis.total_competition_cpu > 15:
            analysis.level = CompetitionLevel.HIGH
            analysis.description = (
                f"{len(competing)} processes using {analysis.total_competition_cpu:.1f}% CPU "
                f"outside emulator — notable CPU competition"
            )
        elif analysis.total_competition_cpu > 5:
            analysis.level = CompetitionLevel.MODERATE
            analysis.description = (
                f"{len(competing)} processes using {analysis.total_competition_cpu:.1f}% CPU "
                f"outside emulator — moderate CPU competition"
            )
        elif analysis.total_competition_cpu > 1:
            analysis.level = CompetitionLevel.LOW
            analysis.description = (
                f"{len(competing)} processes using {analysis.total_competition_cpu:.1f}% CPU "
                f"outside emulator — minor competition"
            )
        else:
            analysis.level = CompetitionLevel.NONE
            analysis.description = "No significant CPU competition detected"

        return analysis

    def _analyze_ram_competition(
        self,
        processes: List[ProcessInventory],
        emulator_pid: int,
    ) -> CompetitionAnalysis:
        """Analyze RAM competition with the emulator."""
        analysis = CompetitionAnalysis()

        competing = [
            p for p in processes
            if p.pid != emulator_pid
            and p.ram_competition
            and p.recommendation != Recommendation.DO_NOT_TOUCH
        ]
        competing.sort(key=lambda x: x.ram_mb, reverse=True)

        analysis.ram_competing_processes = competing[:10]
        analysis.total_competition_ram_mb = sum(p.ram_mb for p in competing)

        total_gb = analysis.total_competition_ram_mb / 1024

        if total_gb > 4:
            analysis.level = CompetitionLevel.SEVERE
            analysis.description = (
                f"{len(competing)} processes using {total_gb:.1f}GB RAM "
                f"outside emulator — significant memory pressure"
            )
        elif total_gb > 2:
            analysis.level = CompetitionLevel.HIGH
            analysis.description = (
                f"{len(competing)} processes using {total_gb:.1f}GB RAM "
                f"outside emulator — notable memory usage"
            )
        elif total_gb > 1:
            analysis.level = CompetitionLevel.MODERATE
            analysis.description = (
                f"{len(competing)} processes using {total_gb:.1f}GB RAM "
                f"outside emulator — moderate usage"
            )
        elif total_gb > 0.3:
            analysis.level = CompetitionLevel.LOW
            analysis.description = (
                f"{len(competing)} processes using {total_gb:.1f}GB RAM "
                f"outside emulator — minor usage"
            )
        else:
            analysis.level = CompetitionLevel.NONE
            analysis.description = "No significant RAM competition detected"

        return analysis

    def _analyze_disk_competition(
        self,
        processes: List[ProcessInventory],
        emulator_pid: int,
    ) -> CompetitionAnalysis:
        """Analyze disk I/O competition with the emulator."""
        analysis = CompetitionAnalysis()

        competing = [
            p for p in processes
            if p.pid != emulator_pid
            and p.disk_competition
            and p.recommendation != Recommendation.DO_NOT_TOUCH
        ]
        competing.sort(
            key=lambda x: x.io_read_mb + x.io_write_mb, reverse=True
        )

        analysis.disk_competing_processes = competing[:10]
        total_io = sum(p.io_read_mb + p.io_write_mb for p in competing)
        analysis.total_competition_ram_mb = total_io  # Reuse field for total IO MB

        if total_io > 5000:
            analysis.level = CompetitionLevel.SEVERE
            analysis.description = (
                f"{len(competing)} processes with {total_io:.0f}MB total I/O "
                f"— significant disk contention"
            )
        elif total_io > 2000:
            analysis.level = CompetitionLevel.HIGH
            analysis.description = (
                f"{len(competing)} processes with {total_io:.0f}MB total I/O "
                f"— notable disk activity"
            )
        elif total_io > 500:
            analysis.level = CompetitionLevel.MODERATE
            analysis.description = (
                f"{len(competing)} processes with {total_io:.0f}MB total I/O "
                f"— moderate disk activity"
            )
        elif total_io > 100:
            analysis.level = CompetitionLevel.LOW
            analysis.description = (
                f"{len(competing)} processes with {total_io:.0f}MB total I/O "
                f"— minor disk activity"
            )
        else:
            analysis.level = CompetitionLevel.NONE
            analysis.description = "No significant disk competition detected"

        return analysis

    def _assess_overall_impact(
        self, result: BackgroundAnalysis
    ) -> Tuple[CompetitionLevel, str]:
        """Assess overall gaming impact from all competition analyses."""
        levels = []

        if result.cpu_competition:
            levels.append(result.cpu_competition.level)
        if result.ram_competition:
            levels.append(result.ram_competition.level)
        if result.disk_competition:
            levels.append(result.disk_competition.level)

        if not levels:
            return CompetitionLevel.NONE, "No competition data available"

        # Overall is the worst of all
        level_order = [
            CompetitionLevel.NONE, CompetitionLevel.LOW,
            CompetitionLevel.MODERATE, CompetitionLevel.HIGH,
            CompetitionLevel.SEVERE,
        ]
        worst = max(levels, key=lambda l: level_order.index(l))

        # Build summary
        parts = []
        if result.cpu_competition and result.cpu_competition.level.value not in ("NONE", "LOW"):
            parts.append(f"CPU: {result.cpu_competition.total_competition_cpu:.1f}%")
        if result.ram_competition and result.ram_competition.level.value not in ("NONE", "LOW"):
            parts.append(f"RAM: {result.ram_competition.total_competition_ram_mb / 1024:.1f}GB")
        if result.disk_competition and result.disk_competition.level.value not in ("NONE", "LOW"):
            parts.append(f"Disk: {result.disk_competition.total_competition_ram_mb:.0f}MB I/O")

        if parts:
            desc = f"Background impact: {', '.join(parts)}"
        elif worst == CompetitionLevel.NONE:
            desc = "No significant background resource competition detected"
        elif worst == CompetitionLevel.LOW:
            desc = "Minor background resource usage — no action needed"
        else:
            desc = f"Background impact level: {worst.value}"

        return worst, desc


# Singleton
background_analyzer = BackgroundLoadAnalyzer()
