"""
Startup Analyzer — Read-only Windows startup application detection.

Detects startup entries from:
- HKCU Software Microsoft Windows CurrentVersion Run
- HKLM Software Microsoft Windows CurrentVersion Run
- HKCU Software Microsoft Windows CurrentVersion RunOnce
- HKLM Software Microsoft Windows CurrentVersion RunOnce
- User Startup folder
- Common Startup folder

All operations are READ-ONLY. Never modifies registry or startup entries.
Never automatically disables startup applications.
"""

import os
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Tuple
from enum import Enum

import psutil

from app.utils.logger import get_logger

logger = get_logger("system.startup_analyzer")


# ── Classifications ────────────────────────────────────────────

class StartupClassification(Enum):
    """Classification of a startup entry."""
    SYSTEM = "SYSTEM"
    SECURITY = "SECURITY"
    EMULATOR = "EMULATOR"
    USER_APPLICATION = "USER_APPLICATION"
    SAFE_TO_RECOMMEND = "SAFE_TO_RECOMMEND"
    UNKNOWN = "UNKNOWN"


# Protected processes — never recommend disabling
SYSTEM_STARTUP_NAMES = {
    "windows defender", "microsoft security client", "securityhealth",
    "ctfmon", "explorer", "runtimebroker", "sihost",
}

SECURITY_STARTUP_NAMES = {
    "windows defender", "msseces", "securityhealth", "mpcmdrun",
    "savservice", "bdagent", "avgui", "avp", "klnagent",
}

EMULATOR_STARTUP_NAMES = {
    "bluestacks", "bsthdagent", "bsthdviewer", "hd-agent",
    "msi app player", "msihelper", "ldplayer", "dnplayer",
    "gameloop", "mumu",
}

SAFE_TO_DISABLE_NAMES = {
    "onedrive", "dropbox", "spotify", "discord", "steam",
    "epicgameslauncher", "uplay", "skype", "teams", "slack",
    "zoom", "obs", "xsplit", "utorrent", "bittorrent",
    "adobe genuine", "adobe creative cloud", "googledrivesync",
    "icloud", "box sync", "copy cloud",
}


# ── Data Models ────────────────────────────────────────────────

@dataclass
class StartupEntry:
    """A single detected startup entry."""
    name: str = ""
    command: str = ""
    executable_path: str = ""
    source: str = ""  # "HKCU\Run", "HKLM\Run", "Startup Folder", etc.
    classification: StartupClassification = StartupClassification.UNKNOWN
    enabled: bool = True
    can_safely_disable: bool = False
    reason: str = ""
    file_exists: bool = False
    file_size: int = 0
    pid: int = 0  # If currently running

    @property
    def is_running(self) -> bool:
        return self.pid > 0


@dataclass
class StartupAnalysis:
    """Complete startup analysis result."""
    entries: List[StartupEntry] = field(default_factory=list)
    total_entries: int = 0
    enabled_entries: int = 0
    optional_entries: int = 0
    system_entries: int = 0
    security_entries: int = 0
    emulator_entries: int = 0
    unknown_entries: int = 0
    total_optional_ram_mb: float = 0.0
    timestamp: float = 0.0

    @property
    def optional_names(self) -> List[str]:
        """Names of entries that are safe to recommend disabling."""
        return [e.name for e in self.entries if e.can_safely_disable]


# ── Core Analyzer ──────────────────────────────────────────────

class StartupAnalyzer:
    """
    Read-only Windows startup application analyzer.
    Never modifies registry or startup entries.
    """

    def __init__(self):
        self._cache: Optional[StartupAnalysis] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 30.0

    def analyze(self, force: bool = False) -> StartupAnalysis:
        """
        Detect all startup entries from supported locations.
        Returns read-only analysis.
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        analysis = StartupAnalysis(timestamp=now)

        # 1. Registry Run keys
        self._scan_registry_run(analysis, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\Run")
        self._scan_registry_run(analysis, "HKLM", r"Software\Microsoft\Windows\CurrentVersion\Run")
        self._scan_registry_run(analysis, "HKCU", r"Software\Microsoft\Windows\CurrentVersion\RunOnce")
        self._scan_registry_run(analysis, "HKLM", r"Software\Microsoft\Windows\CurrentVersion\RunOnce")

        # 2. Startup folders
        self._scan_startup_folder(analysis, "User Startup", self._get_user_startup_folder())
        self._scan_startup_folder(analysis, "Common Startup", self._get_common_startup_folder())

        # 3. Compute summary statistics
        self._compute_stats(analysis)

        self._cache = analysis
        self._cache_time = now

        logger.info(
            f"[STARTUP] Analysis: {analysis.total_entries} entries, "
            f"{analysis.enabled_entries} enabled, "
            f"{analysis.optional_entries} optional"
        )

        return analysis

    def _scan_registry_run(self, analysis: StartupAnalysis, hive: str, key_path: str):
        """Scan a Windows registry Run key for startup entries."""
        try:
            import winreg
            access = winreg.KEY_READ
            if hive == "HKLM":
                access |= winreg.KEY_WOW64_64KEY

            reg_key = winreg.OpenKey(
                getattr(winreg, hive),
                key_path,
                0,
                access,
            )

            i = 0
            while True:
                try:
                    name, value, reg_type = winreg.EnumValue(reg_key, i)
                    i += 1

                    entry = self._create_entry_from_registry(name, value, f"{hive}\\{key_path}")
                    analysis.entries.append(entry)
                except OSError:
                    break

            winreg.CloseKey(reg_key)

        except FileNotFoundError:
            pass  # Key doesn't exist — normal
        except PermissionError:
            logger.debug(f"Cannot access registry: {hive}\\{key_path}")
        except Exception as e:
            logger.debug(f"Registry scan error: {e}")

    def _create_entry_from_registry(self, name: str, value: str, source: str) -> StartupEntry:
        """Create a StartupEntry from a registry value."""
        entry = StartupEntry(
            name=name,
            command=value,
            source=source,
        )

        # Try to resolve executable path
        exe_path = self._extract_executable(value)
        if exe_path:
            entry.executable_path = exe_path
            entry.file_exists = os.path.isfile(exe_path)
            if entry.file_exists:
                try:
                    entry.file_size = os.path.getsize(exe_path)
                except OSError:
                    pass

        # Classify
        entry.classification, entry.can_safely_disable, entry.reason = self._classify_entry(name, exe_path)

        # Check if currently running
        entry.pid = self._find_running_pid(name, exe_path)

        return entry

    def _scan_startup_folder(self, analysis: StartupAnalysis, source_name: str, folder_path: Optional[str]):
        """Scan a Startup folder for startup entries."""
        if not folder_path or not os.path.isdir(folder_path):
            return

        try:
            for entry_name in os.listdir(folder_path):
                entry_path = os.path.join(folder_path, entry_name)
                if not os.path.isfile(entry_path):
                    continue

                # Skip desktop.ini
                if entry_name.lower() == "desktop.ini":
                    continue

                ext = os.path.splitext(entry_name)[1].lower()
                if ext not in (".lnk", ".exe", ".bat", ".cmd", ".vbs", ".ps1"):
                    continue

                entry = StartupEntry(
                    name=os.path.splitext(entry_name)[0],
                    command=entry_path,
                    executable_path=entry_path if ext == ".exe" else "",
                    source=f"{source_name}: {folder_path}",
                    file_exists=True,
                )

                try:
                    entry.file_size = os.path.getsize(entry_path)
                except OSError:
                    pass

                # For .lnk files, try to resolve the target
                if ext == ".lnk":
                    target = self._resolve_shortcut(entry_path)
                    if target:
                        entry.command = target
                        entry.executable_path = target
                        entry.file_exists = os.path.isfile(target)

                entry.classification, entry.can_safely_disable, entry.reason = self._classify_entry(
                    entry.name, entry.executable_path
                )
                entry.pid = self._find_running_pid(entry.name, entry.executable_path)

                analysis.entries.append(entry)

        except (OSError, PermissionError) as e:
            logger.debug(f"Cannot scan startup folder: {e}")

    def _classify_entry(self, name: str, exe_path: Optional[str]) -> Tuple[StartupClassification, bool, str]:
        """Classify a startup entry by safety."""
        name_lower = name.lower()
        exe_lower = (exe_path or "").lower()

        # Security — never disable
        for sec_name in SECURITY_STARTUP_NAMES:
            if sec_name in name_lower or sec_name in exe_lower:
                return (
                    StartupClassification.SECURITY,
                    False,
                    "Security/antivirus — never disable",
                )

        # System — never disable
        for sys_name in SYSTEM_STARTUP_NAMES:
            if sys_name in name_lower or sys_name in exe_lower:
                return (
                    StartupClassification.SYSTEM,
                    False,
                    "Windows system — required for operation",
                )

        # Emulator — never disable while gaming
        for emu_name in EMULATOR_STARTUP_NAMES:
            if emu_name in name_lower or emu_name in exe_lower:
                return (
                    StartupClassification.EMULATOR,
                    False,
                    "Emulator component — needed for gaming",
                )

        # Safe to recommend disabling
        for safe_name in SAFE_TO_DISABLE_NAMES:
            if safe_name in name_lower or safe_name in exe_lower:
                return (
                    StartupClassification.SAFE_TO_RECOMMEND,
                    True,
                    "Optional background application",
                )

        # Check if it's a known user application by examining the process
        if exe_path and os.path.isfile(exe_path):
            # Check file description or publisher if available
            return (
                StartupClassification.USER_APPLICATION,
                False,
                "User application — manual review recommended",
            )

        return (
            StartupClassification.UNKNOWN,
            False,
            "Unknown startup entry",
        )

    def _find_running_pid(self, name: str, exe_path: Optional[str]) -> int:
        """Find PID if the startup entry's process is currently running."""
        try:
            name_lower = name.lower()
            for proc in psutil.process_iter(["pid", "name", "exe"]):
                try:
                    p = proc.info
                    proc_name = (p.get("name") or "").lower()
                    proc_exe = (p.get("exe") or "").lower()

                    if name_lower in proc_name or (exe_path and proc_exe == exe_path.lower()):
                        return p.get("pid", 0)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return 0

    def _extract_executable(self, command: str) -> Optional[str]:
        """Extract executable path from a registry command string."""
        if not command:
            return None

        cmd = command.strip()

        # Handle quoted paths
        if cmd.startswith('"'):
            end = cmd.find('"', 1)
            if end > 0:
                return cmd[1:end]

        # Handle unquoted paths
        parts = cmd.split()
        if parts:
            return parts[0]

        return cmd

    def _resolve_shortcut(self, lnk_path: str) -> Optional[str]:
        """Resolve a .lnk shortcut to its target path."""
        try:
            # Try using win32com for proper .lnk resolution
            import pythoncom
            import win32com.client
            pythoncom.CoInitialize()
            try:
                shell = win32com.client.Dispatch("WScript.Shell")
                shortcut = shell.CreateShortCut(lnk_path)
                return shortcut.Targetpath
            finally:
                pythoncom.CoUninitialize()
        except (ImportError, Exception):
            pass

        # Fallback: read the .lnk file and look for common patterns
        try:
            with open(lnk_path, "rb") as f:
                data = f.read()
                # Look for common executable patterns in binary
                for ext in [".exe", ".bat", ".cmd"]:
                    idx = data.find(ext.encode())
                    if idx > 0:
                        # Walk backwards to find the start of the path
                        start = max(0, idx - 200)
                        chunk = data[start:idx + len(ext)]
                        # Find null byte before the path
                        null_pos = chunk.rfind(b"\x00")
                        if null_pos >= 0:
                            path_bytes = chunk[null_pos + 1:]
                            try:
                                return path_bytes.decode("utf-16-le").rstrip("\x00")
                            except (UnicodeDecodeError, ValueError):
                                try:
                                    return path_bytes.decode("cp1252").rstrip("\x00")
                                except (UnicodeDecodeError, ValueError):
                                    pass
        except (OSError, PermissionError):
            pass

        return None

    def _get_user_startup_folder(self) -> Optional[str]:
        """Get the user's Startup folder path."""
        try:
            return os.path.join(
                os.environ.get("APPDATA", ""),
                "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
            )
        except Exception:
            return None

    def _get_common_startup_folder(self) -> Optional[str]:
        """Get the common Startup folder path."""
        try:
            program_data = os.environ.get("ProgramData", r"C:\ProgramData")
            return os.path.join(
                program_data,
                "Microsoft", "Windows", "Start Menu", "Programs", "Startup"
            )
        except Exception:
            return None

    def _compute_stats(self, analysis: StartupAnalysis):
        """Compute summary statistics for the analysis."""
        analysis.total_entries = len(analysis.entries)

        for entry in analysis.entries:
            if entry.enabled:
                analysis.enabled_entries += 1

            if entry.can_safely_disable:
                analysis.optional_entries += 1

            if entry.classification == StartupClassification.SYSTEM:
                analysis.system_entries += 1
            elif entry.classification == StartupClassification.SECURITY:
                analysis.security_entries += 1
            elif entry.classification == StartupClassification.EMULATOR:
                analysis.emulator_entries += 1
            elif entry.classification == StartupClassification.UNKNOWN:
                analysis.unknown_entries += 1

    def get_ram_usage_of_optional(self) -> float:
        """Estimate RAM usage of optional startup processes (MB)."""
        total_mb = 0.0
        try:
            for proc in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    p = proc.info
                    name = (p.get("name") or "").lower()
                    for safe_name in SAFE_TO_DISABLE_NAMES:
                        if safe_name in name:
                            mem = p.get("memory_info")
                            if mem:
                                total_mb += mem.rss / (1024 * 1024)
                            break
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return total_mb


# Singleton
startup_analyzer = StartupAnalyzer()
