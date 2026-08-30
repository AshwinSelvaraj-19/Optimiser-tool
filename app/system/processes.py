"""
Process monitoring and classification module.
Classifies running processes by category and importance.
"""

import time
from dataclasses import dataclass, field
from typing import Optional

import psutil

from app.utils.logger import get_logger

logger = get_logger("system.processes")


# Critical Windows processes that must NEVER be terminated
CRITICAL_PROCESSES = {
    "system", "system idle process", "svchost.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "smss.exe", "dwm.exe",
    "explorer.exe", "fontdrvhost.exe", "sihost.exe", "ctfmon.exe",
    "taskhostw.exe", "searchui.exe", "shellexperiencehost.exe",
    "runtimebroker.exe", "startmenuexperiencehost.exe",
    "audiodg.exe", "spoolsv.exe", "dasHost.exe",
}

# Security processes
SECURITY_PROCESSES = {
    "msmpeng.exe", "mpcmdrun.exe", "mssecexec.exe", "csrss.exe",
    "lsass.exe", "securityhealthservice.exe", "senseclosenetwork.exe",
    "senseanalyticsservice.exe",
}

# Emulator processes
EMULATOR_PROCESSES = {
    "msi_app_player": ["msi.exe", "msihelper.exe", "hd-agent.exe", "adb.exe",
                        "bhd-agent.exe", "hd-frontend.exe"],
    "bluestacks": ["bluestacks.exe", "bluestacksservice.exe", "hd-agent.exe",
                    "bluestacksfrontend.exe", "bluestacksthreshservice.exe"],
    "ldplayer": ["ldconsole.exe", "dnplayer.exe", "ld.exe", "ldvboxheadless.exe",
                 "lddocker.exe"],
    "gameloop": ["gameloop.exe", "ty.exe", "appmarket.exe", "aow_exe.exe",
                 "mobilegamepc.exe"],
    "mumu": ["mumu.exe", "mumudriver.exe", "mumuserver.exe", "nemuheadless.exe"],
}

# Known optional background apps
OPTIONAL_PROCESSES = {
    "onedrive.exe", "dropbox.exe", "discord.exe", "spotify.exe",
    "skype.exe", "teams.exe", "slack.exe", "zoom.exe",
    "steam.exe", "epicgameslauncher.exe", "uplay.exe",
    "chrome.exe", "firefox.exe", "msedge.exe", "opera.exe",
    "obs64.exe", "obs32.exe", "xsplit.exe",
    "rtknguil.exe", "razer synapse.exe", "ghub.exe", "logitech g hub.exe",
    "icue.exe", "armorycrate.exe", "gamenexus.exe",
}


@dataclass
class ProcessInfo:
    """Information about a running process."""
    pid: int = 0
    name: str = ""
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    status: str = ""
    category: str = "UNKNOWN"
    importance: str = "LOW"
    recommendation: str = "No action"
    emulator: Optional[str] = None


class ProcessMonitor:
    """Process monitoring and classification."""

    def __init__(self):
        self._prev_process_times: dict = {}
        self._classification_cache: dict = {}

    def classify_process(self, name: str) -> tuple:
        """
        Classify a process by category and importance.
        Returns (category, importance).
        """
        name_lower = name.lower()

        # Check cache
        if name_lower in self._classification_cache:
            return self._classification_cache[name_lower]

        category = "UNKNOWN"
        importance = "LOW"

        # Check critical
        if name_lower in CRITICAL_PROCESSES:
            category = "SYSTEM"
            importance = "CRITICAL"
        # Check security
        elif name_lower in SECURITY_PROCESSES:
            category = "SYSTEM"
            importance = "CRITICAL"
        # Check emulator processes
        else:
            for emulator_name, processes in EMULATOR_PROCESSES.items():
                if name_lower in [p.lower() for p in processes]:
                    category = "TARGET"
                    importance = "HIGH"
                    break

        # Check optional
        if category == "UNKNOWN" and name_lower in OPTIONAL_PROCESSES:
            category = "OPTIONAL BACKGROUND"
            importance = "LOW"

        # Check user application pattern
        if category == "UNKNOWN":
            # Common patterns for user apps
            if any(p in name_lower for p in ["office", "word", "excel", "powerpoint", "outlook"]):
                category = "USER APPLICATION"
                importance = "MEDIUM"
            elif any(p in name_lower for p in ["photoshop", "illustrator", "premiere"]):
                category = "USER APPLICATION"
                importance = "MEDIUM"

        self._classification_cache[name_lower] = (category, importance)
        return category, importance

    def get_process_recommendation(self, proc_info: ProcessInfo) -> str:
        """Generate recommendation for a process."""
        if proc_info.importance == "CRITICAL":
            return "DO NOT terminate — required by Windows"
        if proc_info.category == "TARGET":
            return "DO NOT terminate — Free Fire emulator process"
        if proc_info.category == "ESSENTIAL":
            return "DO NOT terminate — system essential"
        if proc_info.category == "SYSTEM":
            return "DO NOT terminate — system process"
        if proc_info.cpu_percent > 50:
            return f"HIGH CPU USAGE ({proc_info.cpu_percent:.1f}%) — consider closing if not needed"
        if proc_info.memory_mb > 500:
            return f"HIGH MEMORY ({proc_info.memory_mb:.0f}MB) — consider closing if not needed"
        if proc_info.category == "OPTIONAL BACKGROUND":
            return "Optional — can be closed to free resources"
        if proc_info.category == "USER APPLICATION":
            return "User application — close if not in use"
        return "No action recommended"

    def list_processes(self, include_system: bool = False) -> list:
        """Get all running processes with classification."""
        processes = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'cpu_percent', 'memory_info', 'status']):
                try:
                    info = proc.info
                    name = info['name'] or "unknown"
                    cpu = info.get('cpu_percent', 0.0) or 0.0
                    mem = info.get('memory_info')
                    mem_mb = (mem.rss / (1024 * 1024)) if mem else 0
                    mem_pct = proc.memory_percent() if mem else 0

                    category, importance = self.classify_process(name)

                    # Skip system processes if requested
                    if not include_system and category == "SYSTEM":
                        continue

                    pi = ProcessInfo(
                        pid=info['pid'],
                        name=name,
                        cpu_percent=cpu,
                        memory_mb=mem_mb,
                        memory_percent=mem_pct,
                        status=info.get('status', 'unknown'),
                        category=category,
                        importance=importance,
                    )
                    pi.recommendation = self.get_process_recommendation(pi)
                    processes.append(pi)

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.error(f"Error listing processes: {e}")

        # Sort by CPU usage descending
        processes.sort(key=lambda p: p.cpu_percent, reverse=True)
        return processes

    def get_emulator_processes(self) -> dict:
        """Get all processes belonging to detected emulators."""
        emulator_procs = {name: [] for name in EMULATOR_PROCESSES}
        try:
            for proc in psutil.process_iter(['pid', 'name']):
                try:
                    name = (proc.info['name'] or "").lower()
                    for emulator_name, known_procs in EMULATOR_PROCESSES.items():
                        known_lower = [p.lower() for p in known_procs]
                        if name in known_lower:
                            emulator_procs[emulator_name].append({
                                "pid": proc.info['pid'],
                                "name": proc.info['name'],
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.error(f"Error detecting emulator processes: {e}")

        return emulator_procs

    def is_emulator_running(self) -> dict:
        """Check which emulators are currently running."""
        status = {}
        all_procs = self.get_emulator_processes()
        for emulator_name, procs in all_procs.items():
            status[emulator_name] = len(procs) > 0
        return status

    def get_total_cpu_usage(self) -> float:
        """Get total CPU usage across all processes."""
        try:
            return psutil.cpu_percent(interval=0.1)
        except Exception:
            return 0.0

    def get_total_memory_usage(self) -> float:
        """Get total memory usage percentage."""
        try:
            return psutil.virtual_memory().percent
        except Exception:
            return 0.0


# Singleton
process_monitor = ProcessMonitor()
