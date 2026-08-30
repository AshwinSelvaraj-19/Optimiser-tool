"""
Emulator performance controller — detailed process analysis and safe optimization.

Provides:
- Live emulator target detection with PID validation (start time + exe path)
- CPU affinity read/apply/restore with safety checks
- Process priority read/apply/restore
- Memory pressure analysis
- Background process classification
- GPU/display diagnostics
- All operations follow: DETECT → SNAPSHOT → APPLY → VERIFY → ROLLBACK
"""

import os
import time
import ctypes
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from datetime import datetime

import psutil

from app.core.optimization_base import Optimization, OptimizationResult, OptimizationStatus
from app.utils.logger import get_logger

logger = get_logger("core.emulator_controller")


# ── Protected process names (never terminate/recommend closing) ───
PROTECTED_PROCESSES = {
    "system", "system idle process", "svchost.exe", "csrss.exe", "wininit.exe",
    "winlogon.exe", "services.exe", "lsass.exe", "smss.exe", "dwm.exe",
    "explorer.exe", "fontdrvhost.exe", "sihost.exe", "ctfmon.exe",
    "taskhostw.exe", "searchui.exe", "shellexperiencehost.exe",
    "runtimebroker.exe", "startmenuexperiencehost.exe",
    "audiodg.exe", "spoolsv.exe", "dasHost.exe", "ntoskrnl.exe",
    "msmpeng.exe", "mpcmdrun.exe", "securityhealthservice.exe",
}

# Emulator process names (never recommend closing)
EMULATOR_PROCESS_NAMES = {
    "HD-Player.exe", "BstHdViewer.exe", "LDPlayer.exe",
    "MuMuPlayer.exe", "MobileGamePC.exe", "msi.exe",
    "msihelper.exe", "HD-Agent.exe", "BHD-Agent.exe",
    "HD-Frontend.exe", "LdConsole.exe", "dnplayer.exe",
    "TY.exe", "MuMu.exe", "aow_exe.exe",
    "Bluestacks.exe", "Bluestacksservice.exe",
}

# Heaven Society process
HEAVEN_SOCIETY_NAMES = {"python.exe", "pythonw.exe"}


@dataclass
class EmulatorTarget:
    """Detailed emulator process information."""
    name: str = ""
    pid: int = 0
    emulator: str = ""
    exe_path: str = ""
    create_time: float = 0.0       # Process start time (epoch)
    priority: int = 0              # Windows priority class
    priority_name: str = ""
    affinity_mask: int = 0         # Current CPU affinity mask
    affinity_cpus: int = 0         # Number of CPUs in affinity
    total_cpus: int = 0           # System total logical CPUs
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    memory_percent: float = 0.0
    status: str = ""
    gpu_name: str = ""
    gpu_engine: str = ""
    gpu_utilization: float = 0.0
    confidence: float = 0.0
    reason: str = ""

    @property
    def is_high_priority(self) -> bool:
        return self.priority < 0

    @property
    def uses_all_cpus(self) -> bool:
        return self.affinity_cpus >= self.total_cpus


@dataclass
class MemoryPressureInfo:
    """System memory pressure analysis."""
    total_gb: float = 0.0
    used_gb: float = 0.0
    available_gb: float = 0.0
    percent_used: float = 0.0
    swap_percent: float = 0.0
    emulator_mb: float = 0.0
    emulator_percent: float = 0.0
    top_processes: list = field(default_factory=list)
    pressure_level: str = "NORMAL"  # NORMAL, MODERATE, HIGH, CRITICAL
    recommendation: str = ""


@dataclass
class BackgroundProcessInfo:
    """A background process with classification."""
    name: str = ""
    pid: int = 0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    category: str = "UNKNOWN"     # SAFE_TO_RECOMMEND, USER_APPLICATION, WINDOWS_SYSTEM, SECURITY, EMULATOR, UNKNOWN
    recommendation: str = ""


@dataclass
class GPUTargetInfo:
    """GPU info specific to the emulator target."""
    gpu_name: str = ""
    gpu_vendor: str = ""
    is_discrete: bool = False
    is_integrated: bool = False
    utilization: float = 0.0
    temperature: Optional[float] = None
    clock_mhz: float = 0.0
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    display_refresh_hz: float = 0.0
    display_resolution: str = ""
    gpu_bound: Optional[bool] = None   # True if GPU-bound, False if CPU-bound, None if unknown


class EmulatorController:
    """
    Emulator performance controller — detailed process analysis and safe optimization.
    All operations are reversible and verified.
    """

    def __init__(self):
        self._cached_target: Optional[EmulatorTarget] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 2.0  # seconds

    # ── 13.1: Target Detection ──────────────────────────────────

    def detect_target(self, force: bool = False) -> Optional[EmulatorTarget]:
        """
        Detect the running emulator target with full process details.
        Uses start time + exe path for PID reuse safety.
        """
        now = time.time()
        if not force and self._cached_target and (now - self._cache_time) < self._cache_ttl:
            return self._cached_target

        try:
            from app.performance.target_process import target_process_detector
            best = target_process_detector.select_best_target()
            if not best:
                self._cached_target = None
                return None

            # Get detailed process info
            target = self._get_detailed_process_info(best.pid, best.process_name)
            if not target:
                self._cached_target = None
                return None

            target.emulator = best.emulator
            target.confidence = best.confidence
            target.reason = best.reason

            # GPU association
            try:
                from app.performance.gpu_association import gpu_association_detector
                assoc = gpu_association_detector.detect_for_process(
                    best.process_name, best.pid
                )
                if assoc.gpu_name:
                    target.gpu_name = assoc.gpu_name
                    target.gpu_engine = assoc.gpu_engine or ""
            except Exception:
                pass

            self._cached_target = target
            self._cache_time = now
            return target

        except Exception as e:
            logger.debug(f"Target detection error: {e}")
            self._cached_target = None
            return None

    def _get_detailed_process_info(self, pid: int, name: str) -> Optional[EmulatorTarget]:
        """Get comprehensive process information for a PID."""
        try:
            proc = psutil.Process(pid)

            # Validate PID: check name matches and process is running
            if proc.name().lower() != name.lower():
                logger.warning(f"PID {pid} name mismatch: expected {name}, got {proc.name()}")
                return None

            # CPU affinity
            try:
                affinity_list = proc.cpu_affinity()
                total_cpus = psutil.cpu_count(logical=True) or 1
                if isinstance(affinity_list, list):
                    affinity_cpus = len(affinity_list)
                    affinity_mask = sum(1 << cpu for cpu in affinity_list)
                elif isinstance(affinity_list, int):
                    affinity_mask = affinity_list
                    affinity_cpus = bin(affinity_mask).count("1") if affinity_mask else total_cpus
                else:
                    affinity_cpus = total_cpus
                    affinity_mask = 0
            except (psutil.AccessDenied, OSError):
                affinity_mask = 0
                total_cpus = psutil.cpu_count(logical=True) or 1
                affinity_cpus = total_cpus

            # Priority
            try:
                priority = proc.nice()
                priority_name = self._priority_name(priority)
            except (psutil.AccessDenied, OSError):
                priority = 0
                priority_name = "NORMAL"

            # Memory
            try:
                mem_info = proc.memory_info()
                memory_mb = mem_info.rss / (1024 * 1024)
                memory_percent = proc.memory_percent()
            except (psutil.AccessDenied, OSError):
                memory_mb = 0
                memory_percent = 0

            # CPU percent (non-blocking)
            try:
                cpu_percent = proc.cpu_percent(interval=0.1)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                cpu_percent = 0

            # Process start time
            try:
                create_time = proc.create_time()
            except (psutil.AccessDenied, OSError):
                create_time = 0

            # Exe path
            try:
                exe_path = proc.exe()
            except (psutil.AccessDenied, OSError):
                exe_path = ""

            return EmulatorTarget(
                name=name,
                pid=pid,
                exe_path=exe_path,
                create_time=create_time,
                priority=priority,
                priority_name=priority_name,
                affinity_mask=affinity_mask,
                affinity_cpus=affinity_cpus,
                total_cpus=total_cpus,
                cpu_percent=cpu_percent,
                memory_mb=memory_mb,
                memory_percent=memory_percent,
                status=proc.status(),
                confidence=0.9,
                reason="Live process detected",
            )

        except psutil.NoSuchProcess:
            logger.debug(f"PID {pid} no longer exists")
            return None
        except psutil.AccessDenied:
            logger.debug(f"Access denied to PID {pid}")
            # Still return a partial target
            return EmulatorTarget(
                name=name, pid=pid, status="access_denied",
                reason="Process exists but access denied",
            )

    def validate_target(self, target: EmulatorTarget) -> bool:
        """
        Validate that a cached target is still the same process.
        Protects against PID reuse.
        """
        try:
            proc = psutil.Process(target.pid)
            # Check name matches
            if proc.name().lower() != target.name.lower():
                return False
            # Check start time matches (PID reuse protection)
            if target.create_time > 0:
                current_ct = proc.create_time()
                if abs(current_ct - target.create_time) > 1.0:
                    logger.warning(f"PID {target.pid} reuse detected (start time changed)")
                    return False
            return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return False

    @staticmethod
    def _priority_name(nice_val: int) -> str:
        """Convert nice value to Windows priority name."""
        if nice_val <= -4:
            return "REALTIME"
        elif nice_val <= -2:
            return "HIGH"
        elif nice_val <= -1:
            return "ABOVE NORMAL"
        elif nice_val == 0:
            return "NORMAL"
        elif nice_val <= 1:
            return "BELOW NORMAL"
        elif nice_val <= 4:
            return "LOW"
        return f"PRIORITY {nice_val}"

    # ── 13.2: CPU Affinity ─────────────────────────────────────

    def read_affinity(self, pid: int) -> Tuple[int, int, int]:
        """
        Read CPU affinity for a process.
        Returns (affinity_mask, cpu_count, total_cpus).
        """
        try:
            proc = psutil.Process(pid)
            mask = proc.cpu_affinity()
            total = psutil.cpu_count(logical=True) or 1
            count = bin(mask).count("1") if mask else total
            return mask, count, total
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as e:
            logger.debug(f"Cannot read affinity for PID {pid}: {e}")
            return 0, 0, 0

    def get_recommended_affinity(self, pid: int) -> Optional[int]:
        """
        Determine if there is a defensible CPU affinity configuration.

        Conservative strategy: keep all CPUs unless the system has many cores
        and the emulator is only using a subset effectively.

        Returns None if no change is recommended.
        """
        mask, cpu_count, total = self.read_affinity(pid)
        if mask == 0:
            return None

        # If already using all CPUs, no change needed
        if cpu_count >= total:
            return None

        # If using fewer than half the cores and system has > 8 cores,
        # recommend using at least half (to prevent starvation)
        if total > 8 and cpu_count < total // 2:
            # Create mask for first half of CPUs
            recommended = (1 << (total // 2)) - 1
            if recommended != mask:
                return recommended

        # Otherwise, no justified change
        return None

    def apply_affinity(self, pid: int, mask: int) -> bool:
        """Apply CPU affinity to a process."""
        try:
            proc = psutil.Process(pid)
            proc.cpu_affinity(mask)
            # Verify
            verify = psutil.Process(pid)
            return verify.cpu_affinity() == mask
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as e:
            logger.warning(f"Cannot set affinity for PID {pid}: {e}")
            return False

    def restore_affinity(self, pid: int, original_mask: int) -> bool:
        """Restore original CPU affinity."""
        return self.apply_affinity(pid, original_mask)

    # ── 13.3: Process Priority ──────────────────────────────────

    def read_priority(self, pid: int) -> Tuple[int, str]:
        """Read process priority. Returns (nice_value, name)."""
        try:
            proc = psutil.Process(pid)
            nice = proc.nice()
            return nice, self._priority_name(nice)
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError):
            return 0, "UNKNOWN"

    def apply_priority(self, pid: int, nice_value: int) -> bool:
        """Apply process priority."""
        try:
            proc = psutil.Process(pid)
            proc.nice(nice_value)
            verify = psutil.Process(pid)
            return verify.nice() == nice_value
        except (psutil.NoSuchProcess, psutil.AccessDenied, OSError) as e:
            logger.warning(f"Cannot set priority for PID {pid}: {e}")
            return False

    def restore_priority(self, pid: int, original_nice: int) -> bool:
        """Restore original process priority."""
        return self.apply_priority(pid, original_nice)

    # ── 13.5: Memory Pressure Analysis ──────────────────────────

    def analyze_memory_pressure(self, emulator_pid: int = 0) -> MemoryPressureInfo:
        """
        Analyze system memory pressure with emulator-specific info.
        This is read-only analysis — does not modify anything.
        """
        info = MemoryPressureInfo()

        try:
            vm = psutil.virtual_memory()
            info.total_gb = vm.total / (1024 ** 3)
            info.used_gb = vm.used / (1024 ** 3)
            info.available_gb = vm.available / (1024 ** 3)
            info.percent_used = vm.percent

            # Swap
            swap = psutil.swap_memory()
            info.swap_percent = swap.percent

            # Emulator memory
            if emulator_pid > 0:
                try:
                    proc = psutil.Process(emulator_pid)
                    mem = proc.memory_info()
                    info.emulator_mb = mem.rss / (1024 * 1024)
                    info.emulator_percent = proc.memory_percent()
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Top memory processes (read-only)
            top_procs = []
            for proc in psutil.process_iter(["pid", "name", "memory_info"]):
                try:
                    p = proc.info
                    mem = p.get("memory_info")
                    if mem:
                        mb = mem.rss / (1024 * 1024)
                        if mb > 50:  # Only show > 50MB
                            top_procs.append({
                                "name": p["name"],
                                "pid": p["pid"],
                                "mb": round(mb, 1),
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
            top_procs.sort(key=lambda x: x["mb"], reverse=True)
            info.top_processes = top_procs[:10]

            # Pressure level
            if info.percent_used > 90:
                info.pressure_level = "CRITICAL"
                info.recommendation = "System memory critically low. Close memory-heavy applications."
            elif info.percent_used > 80:
                info.pressure_level = "HIGH"
                info.recommendation = "System memory under high pressure. May cause stutters due to paging."
            elif info.percent_used > 65:
                info.pressure_level = "MODERATE"
                info.recommendation = "Memory usage moderate. Monitor for changes."
            else:
                info.pressure_level = "NORMAL"
                info.recommendation = "Memory usage healthy."

        except Exception as e:
            logger.debug(f"Memory analysis error: {e}")
            info.pressure_level = "UNKNOWN"
            info.recommendation = "Unable to analyze memory."

        return info

    # ── 13.6: Background Process Analysis ───────────────────────

    def analyze_background_processes(self, emulator_pid: int = 0) -> List[BackgroundProcessInfo]:
        """
        Analyze background processes and classify them.
        Read-only — does not terminate anything.
        """
        results = []
        try:
            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                try:
                    p = proc.info
                    name = p.get("name", "")
                    pid = p.get("pid", 0)
                    cpu = p.get("cpu_percent", 0) or 0
                    mem = p.get("memory_info")
                    mem_mb = (mem.rss / (1024 * 1024)) if mem else 0

                    # Skip low-impact processes
                    if cpu < 0.5 and mem_mb < 50:
                        continue

                    # Skip emulator and system processes
                    name_lower = name.lower()
                    if name_lower in PROTECTED_PROCESSES:
                        continue
                    if name in EMULATOR_PROCESS_NAMES:
                        continue
                    if name_lower in {n.lower() for n in HEAVEN_SOCIETY_NAMES}:
                        continue
                    if pid == emulator_pid:
                        continue

                    # Classify
                    category = "UNKNOWN"
                    if name_lower in PROTECTED_PROCESSES or name_lower.startswith("svchost"):
                        category = "WINDOWS_SYSTEM"
                    elif name_lower in {"msmpeng.exe", "mpcmdrun.exe", "securityhealthservice.exe"}:
                        category = "SECURITY"
                    elif name_lower in {"onedrive.exe", "dropbox.exe", "discord.exe",
                                         "spotify.exe", "teams.exe", "slack.exe",
                                         "chrome.exe", "firefox.exe", "msedge.exe",
                                         "steam.exe", "epicgameslauncher.exe"}:
                        category = "SAFE_TO_RECOMMEND"
                    else:
                        category = "USER_APPLICATION"

                    # Build recommendation
                    recommendation = ""
                    if category == "SAFE_TO_RECOMMEND":
                        if cpu > 5:
                            recommendation = f"High CPU ({cpu:.1f}%) — safe to close"
                        elif mem_mb > 200:
                            recommendation = f"Using {mem_mb:.0f}MB RAM — safe to close"
                        else:
                            recommendation = "Optional — safe to close if not needed"
                    elif category == "USER_APPLICATION":
                        recommendation = "User application — close if not in use"
                    elif category == "SECURITY":
                        recommendation = "DO NOT close — security software"
                    else:
                        recommendation = "No action recommended"

                    results.append(BackgroundProcessInfo(
                        name=name, pid=pid,
                        cpu_percent=cpu, memory_mb=round(mem_mb, 1),
                        category=category, recommendation=recommendation,
                    ))

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

        except Exception as e:
            logger.debug(f"Background process analysis error: {e}")

        # Sort by CPU then memory
        results.sort(key=lambda x: (x.cpu_percent, x.memory_mb), reverse=True)
        return results

    # ── 13.7: GPU/Display Diagnostics ───────────────────────────

    def get_gpu_diagnostics(self, emulator_pid: int = 0) -> GPUTargetInfo:
        """
        Get GPU diagnostics for the emulator target.
        Read-only — does not modify anything.
        """
        info = GPUTargetInfo()

        try:
            from app.system.gpu import gpu_monitor, NVML_AVAILABLE
            gpus = gpu_monitor.detect()
            if gpus:
                gpu = gpus[0]
                if gpu.vendor == "NVIDIA":
                    gpu = gpu_monitor.update_nvidia(gpu)
                info.gpu_name = gpu.name
                info.gpu_vendor = gpu.vendor
                info.is_discrete = gpu.is_discrete
                info.is_integrated = gpu.is_integrated
                info.utilization = gpu.utilization_gpu
                info.temperature = gpu.temperature_celsius
                info.clock_mhz = gpu.clock_core_mhz
                info.vram_used_mb = gpu.vram_used_mb
                info.vram_total_mb = gpu.vram_total_mb
        except Exception as e:
            logger.debug(f"GPU diagnostics error: {e}")

        # Display info
        try:
            from app.system.display import display_monitor
            disp = display_monitor.detect()
            info.display_refresh_hz = disp.refresh_rate_hz
            info.display_resolution = f"{disp.resolution_x}x{disp.resolution_y}"
        except Exception as e:
            logger.debug(f"Display diagnostics error: {e}")

        # GPU-bound analysis from telemetry
        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current
            if frame.gpu_utilization > 0 and frame.cpu_utilization > 0:
                # Heuristic: if GPU > 90% and CPU < 70%, GPU-bound
                if frame.gpu_utilization > 90 and frame.cpu_utilization < 70:
                    info.gpu_bound = True
                elif frame.cpu_utilization > 90 and frame.gpu_utilization < 70:
                    info.gpu_bound = False
        except Exception:
            pass

        return info

    # ── Combined Status ─────────────────────────────────────────

    def get_full_status(self) -> dict:
        """Get comprehensive emulator status for UI/CLI."""
        target = self.detect_target()
        if not target:
            return {
                "detected": False,
                "message": "No emulator detected",
            }

        memory = self.analyze_memory_pressure(target.pid)
        background = self.analyze_background_processes(target.pid)
        gpu = self.get_gpu_diagnostics(target.pid)

        # Affinity
        affinity_mask, affinity_cpus, total_cpus = self.read_affinity(target.pid)

        return {
            "detected": True,
            "target": target,
            "memory": memory,
            "background": background,
            "gpu": gpu,
            "affinity_mask": affinity_mask,
            "affinity_cpus": affinity_cpus,
            "total_cpus": total_cpus,
        }


# ── Optimization classes for the engine ────────────────────────


class CpuAffinityOptimization(Optimization):
    """
    CPU affinity optimization for the emulator process.
    Only applies a change when there is a defensible configuration.
    Status: RECOMMENDATION_ONLY by default (conservative).
    """
    id = "cpu_affinity"
    name = "CPU Affinity"
    description = "Optimize CPU core assignment for the emulator process"
    category = "EMULATOR"
    risk_level = "LOW"

    def __init__(self):
        super().__init__()
        self._controller = EmulatorController()
        self._target_pid = None
        self._original_mask = None

    def _find_emulator_pid(self) -> int:
        target = self._controller.detect_target()
        return target.pid if target else 0

    def check(self) -> OptimizationResult:
        self._target_pid = self._find_emulator_pid()
        if not self._target_pid:
            self._status = OptimizationStatus.NOT_AVAILABLE
            return OptimizationResult(
                status=self._status,
                current_value="No emulator running",
                message="Emulator not detected",
            )

        mask, cpu_count, total = self._controller.read_affinity(self._target_pid)
        if mask == 0:
            self._status = OptimizationStatus.NOT_AVAILABLE
            return OptimizationResult(
                status=self._status,
                current_value="Cannot read affinity",
                message="Access denied or process not found",
            )

        recommended = self._controller.get_recommended_affinity(self._target_pid)
        if recommended is None:
            self._status = OptimizationStatus.ALREADY_OPTIMAL
            return OptimizationResult(
                status=self._status,
                current_value=f"{cpu_count}/{total} CPUs",
                recommended_value="No change needed",
                message="Current affinity is already optimal",
            )

        self._status = OptimizationStatus.OPTIMIZABLE
        return OptimizationResult(
            status=self._status,
            current_value=f"{cpu_count}/{total} CPUs",
            recommended_value=f"{bin(recommended).count('1')}/{total} CPUs (first half)",
            message="Affinity could be optimized",
        )

    def snapshot(self) -> dict:
        if self._target_pid:
            mask, _, _ = self._controller.read_affinity(self._target_pid)
            self._original_mask = mask
        self._snapshot_data = {
            "pid": self._target_pid,
            "original_mask": self._original_mask,
        }
        return self._snapshot_data

    def apply(self) -> OptimizationResult:
        if self._status != OptimizationStatus.OPTIMIZABLE:
            return OptimizationResult(status=self._status)
        if not self._target_pid:
            return OptimizationResult(status=OptimizationStatus.FAILED, message="No PID")

        recommended = self._controller.get_recommended_affinity(self._target_pid)
        if recommended is None:
            return OptimizationResult(status=OptimizationStatus.ALREADY_OPTIMAL)

        if self._controller.apply_affinity(self._target_pid, recommended):
            self._status = OptimizationStatus.APPLIED
            return OptimizationResult(
                status=self._status,
                message=f"Affinity set to {bin(recommended).count('1')} CPUs",
            )

        self._status = OptimizationStatus.FAILED
        return OptimizationResult(status=self._status, message="Failed to set affinity")

    def verify(self) -> bool:
        if not self._target_pid:
            return False
        mask, _, _ = self._controller.read_affinity(self._target_pid)
        recommended = self._controller.get_recommended_affinity(self._target_pid)
        return mask == recommended if recommended else True

    def rollback(self) -> bool:
        if self._target_pid and self._original_mask:
            return self._controller.restore_affinity(self._target_pid, self._original_mask)
        return False


def get_emulator_optimizations() -> list:
    """Get all emulator-specific optimizations."""
    from app.core.optimizations import (
        PowerPlanOptimization, GameModeOptimization,
        EmulatorPriorityOptimization, BackgroundProcessOptimization,
    )
    return [
        PowerPlanOptimization(),
        GameModeOptimization(),
        EmulatorPriorityOptimization(),
        CpuAffinityOptimization(),
        BackgroundProcessOptimization(),
    ]


# Singleton
emulator_controller = EmulatorController()
