"""
Hardware scanner — full system hardware detection.
Combines CPU, GPU, memory, display, storage, and network detection.
"""

import os
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

import psutil

from app.system.cpu import cpu_monitor, CPUInfo
from app.system.gpu import gpu_monitor, GPUInfo
from app.system.memory import memory_monitor, MemoryInfo
from app.system.display import display_monitor, DisplayInfo
from app.system.thermal_monitor import thermal_diagnostics, ThermalSnapshot
from app.utils.logger import get_logger, LogContext

logger = get_logger("core.scanner")


@dataclass
class StorageInfo:
    """Storage device information."""
    device_name: str = ""
    mount_point: str = ""
    total_gb: float = 0.0
    used_gb: float = 0.0
    free_gb: float = 0.0
    percent_used: float = 0.0
    fs_type: str = ""


@dataclass
class NetworkAdapterInfo:
    """Network adapter information."""
    name: str = ""
    adapter_type: str = ""
    speed_mbps: float = 0.0
    mac_address: str = ""
    is_connected: bool = False
    ipv4_address: str = ""
    dns_servers: list = field(default_factory=list)


@dataclass
class SystemProfile:
    """Complete system hardware profile."""
    cpu: Optional[CPUInfo] = None
    gpus: list = field(default_factory=list)
    memory: Optional[MemoryInfo] = None
    display: Optional[DisplayInfo] = None
    storage: list = field(default_factory=list)
    network_adapters: list = field(default_factory=list)
    thermal: Optional[ThermalSnapshot] = None
    os_version: str = ""
    os_build: str = ""
    hostname: str = ""
    scan_timestamp: float = 0.0

    def get_discrete_gpu(self) -> Optional[GPUInfo]:
        for gpu in self.gpus:
            if gpu.is_discrete:
                return gpu
        return self.gpus[0] if self.gpus else None

    def get_integrated_gpu(self) -> Optional[GPUInfo]:
        for gpu in self.gpus:
            if gpu.is_integrated:
                return gpu
        return None


class HardwareScanner:
    """Full hardware detection and profiling."""

    def __init__(self):
        self._profile: Optional[SystemProfile] = None
        self._last_scan: float = 0
        self._scan_interval: float = 300  # Re-scan hardware every 5 minutes
        self._lock = threading.Lock()

    def scan(self, force: bool = False) -> SystemProfile:
        """Perform a full hardware scan. Returns SystemProfile."""
        # Fast path: return cached profile if still valid
        now = time.time()
        if not force and self._profile and (now - self._last_scan) < self._scan_interval:
            return self._profile

        with self._lock:
            # Double-check after acquiring lock (another thread may have scanned)
            now = time.time()
            if not force and self._profile and (now - self._last_scan) < self._scan_interval:
                return self._profile

            # Suppress harmless pywin32 IUnknown::Release() SEH exceptions
            # that print to C-level stderr during deferred COM object teardown
            _devnull_fd = os.open(os.devnull, os.O_WRONLY)
            _old_stderr_fd = os.dup(2)
            os.dup2(_devnull_fd, 2)
            try:
                profile = SystemProfile()
                self._do_scan(profile, now)
            finally:
                os.dup2(_old_stderr_fd, 2)
                os.close(_old_stderr_fd)
                os.close(_devnull_fd)

            self._profile = profile
            self._last_scan = now

            logger.info("Hardware scan complete")
            self._log_summary(profile)

            return profile

    def _do_scan(self, profile: SystemProfile, now: float):
        """Perform the actual hardware detection (called inside scan lock)."""
        logger.info("Starting full hardware scan...")
        with LogContext(logger, "Hardware Scan"):
            profile.scan_timestamp = now

            # CPU
            try:
                profile.cpu = cpu_monitor.detect()
            except Exception as e:
                logger.error(f"CPU detection failed: {e}")

            # GPU
            try:
                profile.gpus = gpu_monitor.detect()
            except Exception as e:
                logger.error(f"GPU detection failed: {e}")

            # Memory
            try:
                profile.memory = memory_monitor.detect()
            except Exception as e:
                logger.error(f"Memory detection failed: {e}")

            # Display
            try:
                profile.display = display_monitor.detect()
            except Exception as e:
                logger.error(f"Display detection failed: {e}")

            # Storage
            try:
                profile.storage = self._scan_storage()
            except Exception as e:
                logger.error(f"Storage detection failed: {e}")

            # Network
            try:
                profile.network_adapters = self._scan_network()
            except Exception as e:
                logger.error(f"Network detection failed: {e}")

            # OS info
            try:
                import platform
                profile.os_version = platform.platform()
                profile.os_build = platform.version()
                profile.hostname = platform.node()
            except Exception as e:
                logger.error(f"OS info failed: {e}")

    def _scan_storage(self) -> list:
        """Detect storage devices."""
        storage = []
        try:
            for partition in psutil.disk_partitions():
                try:
                    usage = psutil.disk_usage(partition.mountpoint)
                    storage.append(StorageInfo(
                        device_name=partition.device,
                        mount_point=partition.mountpoint,
                        total_gb=usage.total / (1024 ** 3),
                        used_gb=usage.used / (1024 ** 3),
                        free_gb=usage.free / (1024 ** 3),
                        percent_used=usage.percent,
                        fs_type=partition.fstype,
                    ))
                except (PermissionError, OSError):
                    continue
        except Exception as e:
            logger.error(f"Storage scan error: {e}")
        return storage

    def _scan_network(self) -> list:
        """Detect network adapters."""
        adapters = []
        try:
            addrs = psutil.net_if_addrs()
            stats = psutil.net_if_stats()
            io_counters = psutil.net_io_counters(pernic=True)

            for name, addr_list in addrs.items():
                adapter = NetworkAdapterInfo(name=name)
                adapter.is_connected = stats.get(name, None) and stats[name].isup
                adapter.speed_mbps = stats.get(name, None) and getattr(stats[name], 'speed', 0) or 0

                for addr in addr_list:
                    if addr.family.name == 'AF_INET':
                        adapter.ipv4_address = addr.address
                    elif addr.family.name == 'AF_LINK':
                        adapter.mac_address = addr.address

                # Get DNS servers
                try:
                    import subprocess
                    result = subprocess.run(
                        f'netsh interface ip show dns name="{name}"',
                        capture_output=True, text=True, shell=True, timeout=5
                    )
                    if result.returncode == 0:
                        for line in result.stdout.split('\n'):
                            if line.strip() and 'DNS' in line:
                                adapter.dns_servers.append(line.strip())
                except Exception:
                    pass

                adapters.append(adapter)
        except Exception as e:
            logger.error(f"Network scan error: {e}")
        return adapters

    def _log_summary(self, profile: SystemProfile):
        """Log a summary of the hardware scan."""
        if profile.cpu:
            logger.info(f"CPU: {profile.cpu.model} ({profile.cpu.physical_cores}C/{profile.cpu.logical_cores}T)")
        for gpu in profile.gpus:
            gpu_type = "Discrete" if gpu.is_discrete else ("Integrated" if gpu.is_integrated else "Unknown")
            logger.info(f"GPU: {gpu.name} ({gpu.vendor}, {gpu_type})")
        if profile.memory:
            logger.info(f"RAM: {profile.memory.ram_total_gb:.1f}GB ({profile.memory.ram_percent:.1f}% used)")
        if profile.display:
            logger.info(f"Display: {profile.display.resolution_x}x{profile.display.resolution_y} @ {profile.display.refresh_rate_hz}Hz")
        logger.info(f"Storage devices: {len(profile.storage)}")
        logger.info(f"Network adapters: {len(profile.network_adapters)}")

    def update_telemetry(self, profile: SystemProfile) -> SystemProfile:
        """Update mutable telemetry in an existing profile without full rescan."""
        if profile.cpu:
            cpu_monitor.update(profile.cpu)
        if profile.gpus:
            for i, gpu in enumerate(profile.gpus):
                profile.gpus[i] = gpu_monitor.update(gpu)
        if profile.memory:
            profile.memory = memory_monitor.detect()
        profile.scan_timestamp = time.time()
        return profile


# Singleton
hardware_scanner = HardwareScanner()
