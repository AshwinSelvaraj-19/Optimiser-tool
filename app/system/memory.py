"""
Memory monitoring module.
Tracks RAM and VRAM usage, paging, and memory pressure.
"""

import time
from dataclasses import dataclass
from typing import Optional

import psutil

from app.utils.logger import get_logger

logger = get_logger("system.memory")


@dataclass
class MemoryInfo:
    """System memory information."""
    ram_total_gb: float = 0.0
    ram_available_gb: float = 0.0
    ram_used_gb: float = 0.0
    ram_percent: float = 0.0
    swap_total_gb: float = 0.0
    swap_used_gb: float = 0.0
    swap_percent: float = 0.0
    page_faults_per_sec: float = 0.0
    committed_bytes: float = 0.0
    cached_bytes: float = 0.0
    timestamp: float = 0.0


class MemoryMonitor:
    """System memory monitoring."""

    def detect(self) -> MemoryInfo:
        """Get current memory information."""
        info = MemoryInfo()
        try:
            vm = psutil.virtual_memory()
            info.ram_total_gb = vm.total / (1024 ** 3)
            info.ram_available_gb = vm.available / (1024 ** 3)
            info.ram_used_gb = vm.used / (1024 ** 3)
            info.ram_percent = vm.percent

            swap = psutil.swap_memory()
            info.swap_total_gb = swap.total / (1024 ** 3)
            info.swap_used_gb = swap.used / (1024 ** 3)
            info.swap_percent = swap.percent

            info.timestamp = time.time()

            logger.info(
                f"RAM: {info.ram_total_gb:.1f}GB total, "
                f"{info.ram_used_gb:.1f}GB used ({info.ram_percent:.1f}%)"
            )
        except Exception as e:
            logger.error(f"Memory detection error: {e}")

        return info

    def read_snapshot(self) -> dict:
        """Read a telemetry snapshot."""
        info = self.detect()
        return {
            "ram_total_gb": info.ram_total_gb,
            "ram_used_gb": info.ram_used_gb,
            "ram_available_gb": info.ram_available_gb,
            "ram_percent": info.ram_percent,
            "swap_percent": info.swap_percent,
            "timestamp": info.timestamp,
        }

    def is_under_pressure(self, threshold: float = 85.0) -> bool:
        """Check if system is under memory pressure."""
        vm = psutil.virtual_memory()
        return vm.percent >= threshold

    def get_process_memory(self, pid: int) -> Optional[dict]:
        """Get memory usage for a specific process."""
        try:
            proc = psutil.Process(pid)
            mem = proc.memory_info()
            return {
                "pid": pid,
                "name": proc.name(),
                "rss_mb": mem.rss / (1024 * 1024),
                "vms_mb": mem.vms / (1024 * 1024),
                "percent": proc.memory_percent(),
            }
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            return None


# Singleton
memory_monitor = MemoryMonitor()
