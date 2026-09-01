"""
Target process identification — discovers emulator/game rendering processes.
Identifies which process produces DXGI Present events.
"""

import time
import psutil
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("performance.target_process")

# Known emulator rendering processes (these produce DXGI Present events)
EMULATOR_RENDERERS = {
    # MSI App Player / BlueStacks
    "HD-Player.exe": {"emulator": "MSI App Player / BlueStacks", "priority": 1},
    "BstHdViewer.exe": {"emulator": "BlueStacks", "priority": 1},
    # LDPlayer
    "LDPlayer.exe": {"emulator": "LDPlayer", "priority": 1},
    "LDVBoxHeadless.exe": {"emulator": "LDPlayer", "priority": 2},
    # GameLoop
    "MobileGamePC.exe": {"emulator": "GameLoop", "priority": 1},
    "aow_exe.exe": {"emulator": "GameLoop", "priority": 2},
    # MuMu
    "MuMuPlayer.exe": {"emulator": "MuMu Player", "priority": 1},
    "MuMuVMMHeadless.exe": {"emulator": "MuMu Player", "priority": 2},
    "NemuHeadless.exe": {"emulator": "MuMu Player", "priority": 2},
    # Generic Android
    "qemu-system-x86_64.exe": {"emulator": "Android Emulator", "priority": 1},
}

# Emulator support processes (not renderers, but confirm emulator presence)
EMULATOR_SUPPORT = {
    "msi.exe": "MSI App Player",
    "msihelper.exe": "MSI App Player",
    "HD-Agent.exe": "MSI App Player / BlueStacks",
    "BHD-Agent.exe": "MSI App Player",
    "HD-Frontend.exe": "MSI App Player / BlueStacks",
    "LdConsole.exe": "LDPlayer",
    "dnplayer.exe": "LDPlayer",
    "TY.exe": "GameLoop",
    "MuMu.exe": "MuMu Player",
}


@dataclass
class EmulatorProcess:
    """A detected emulator process."""
    name: str = ""
    pid: int = 0
    emulator: str = "Unknown"
    exe_path: str = ""
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    is_renderer: bool = False
    priority: int = 10
    confidence: float = 0.0


@dataclass
class TargetCandidate:
    """A candidate target for FPS measurement."""
    process_name: str = ""
    pid: int = 0
    emulator: str = ""
    exe_path: str = ""
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    reason: str = ""
    confidence: float = 0.0


class TargetProcessDetector:
    """Discovers running emulator processes and selects the best FPS target."""

    def __init__(self):
        self._candidates_cache = None
        self._candidates_ts = 0.0
        self._candidates_ttl = 3.0  # seconds

    def detect_all(self) -> list:
        """Find all running emulator processes."""
        found = []
        try:
            for proc in psutil.process_iter(['pid', 'name', 'exe', 'cpu_percent', 'memory_info', 'status']):
                try:
                    info = proc.info
                    name = info.get('name', '')

                    # Check renderers
                    if name in EMULATOR_RENDERERS:
                        meta = EMULATOR_RENDERERS[name]
                        mem = info.get('memory_info')
                        mem_mb = (mem.rss / (1024 * 1024)) if mem else 0
                        found.append(EmulatorProcess(
                            name=name,
                            pid=info['pid'],
                            emulator=meta["emulator"],
                            exe_path=info.get('exe', '') or '',
                            cpu_percent=info.get('cpu_percent', 0) or 0,
                            memory_mb=mem_mb,
                            is_renderer=True,
                            priority=meta["priority"],
                            confidence=0.9,
                        ))

                    # Check support processes
                    elif name in EMULATOR_SUPPORT:
                        mem = info.get('memory_info')
                        mem_mb = (mem.rss / (1024 * 1024)) if mem else 0
                        found.append(EmulatorProcess(
                            name=name,
                            pid=info['pid'],
                            emulator=EMULATOR_SUPPORT[name],
                            exe_path=info.get('exe', '') or '',
                            cpu_percent=info.get('cpu_percent', 0) or 0,
                            memory_mb=mem_mb,
                            is_renderer=False,
                            priority=5,
                            confidence=0.7,
                        ))

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception as e:
            logger.error(f"Process detection error: {e}")

        logger.info(f"Found {len(found)} emulator process(es)")
        return found

    def find_instances(self) -> list:
        """Group processes by emulator type into instances."""
        processes = self.detect_all()
        instances = {}
        for p in processes:
            key = p.emulator
            if key not in instances:
                instances[key] = {
                    "emulator": key,
                    "processes": [],
                    "renderers": [],
                    "total_cpu": 0.0,
                    "total_ram_mb": 0.0,
                }
            instances[key]["processes"].append(p)
            instances[key]["total_cpu"] += p.cpu_percent
            instances[key]["total_ram_mb"] += p.memory_mb
            if p.is_renderer:
                instances[key]["renderers"].append(p)

        return list(instances.values())

    def get_candidates(self) -> list:
        """Get sorted list of FPS measurement candidates."""
        now = time.time()
        if self._candidates_cache and (now - self._candidates_ts) < self._candidates_ttl:
            return self._candidates_cache
        processes = self.detect_all()
        candidates = []

        for p in processes:
            if p.is_renderer:
                reason = f"DXGI Present renderer for {p.emulator}"
                conf = 0.9
            else:
                reason = f"Support process for {p.emulator}"
                conf = 0.5

            candidates.append(TargetCandidate(
                process_name=p.name,
                pid=p.pid,
                emulator=p.emulator,
                exe_path=p.exe_path,
                cpu_percent=p.cpu_percent,
                memory_mb=p.memory_mb,
                reason=reason,
                confidence=conf,
            ))

        # Sort by priority (lower = better) then confidence
        candidates.sort(key=lambda c: (-c.confidence, c.process_name))
        self._candidates_cache = candidates
        self._candidates_ts = time.time()
        return candidates

    def select_best_target(self) -> Optional[TargetCandidate]:
        """Select the best target for FPS measurement."""
        candidates = self.get_candidates()
        if not candidates:
            return None

        # Prefer renderers
        renderers = [c for c in candidates if c.confidence >= 0.8]
        if renderers:
            return renderers[0]

        return candidates[0]

    def invalidate_cache(self):
        """Invalidate cached results."""
        self._candidates_cache = None
        self._candidates_ts = 0.0

    def get_all_running_pids(self) -> dict:
        """Get all emulator PIDs grouped by emulator name."""
        processes = self.detect_all()
        result = {}
        for p in processes:
            if p.emulator not in result:
                result[p.emulator] = []
            result[p.emulator].append(p.pid)
        return result


# Singleton
target_process_detector = TargetProcessDetector()
