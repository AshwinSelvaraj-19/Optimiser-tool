"""
CPU monitoring and detection module.
Provides CPU info, utilization, frequency, and temperature data.
"""

import platform
import time
from dataclasses import dataclass, field
from typing import Optional

import psutil

from app.utils.logger import get_logger

logger = get_logger("system.cpu")


@dataclass
class CPUInfo:
    """Comprehensive CPU information."""
    model: str = "Unknown"
    physical_cores: int = 0
    logical_cores: int = 0
    max_frequency_mhz: float = 0.0
    current_frequency_mhz: float = 0.0
    utilization_percent: float = 0.0
    per_core_percent: list = field(default_factory=list)
    temperature_celsius: Optional[float] = None
    architecture: str = ""
    l2_cache_size: int = 0
    l3_cache_size: int = 0
    flags: list = field(default_factory=list)
    voltage: Optional[float] = None
    supports_sse: bool = False
    supports_avx: bool = False
    supports_avx2: bool = False


class CPUMonitor:
    """CPU detection and monitoring."""

    def __init__(self):
        self._prev_times: Optional[dict] = None
        self._last_read_time: float = 0

    def detect(self) -> CPUInfo:
        """Detect CPU hardware information."""
        info = CPUInfo()
        try:
            info.model = platform.processor() or "Unknown"
            info.physical_cores = psutil.cpu_count(logical=False) or 0
            info.logical_cores = psutil.cpu_count(logical=True) or 0
            info.architecture = platform.machine()

            freq = psutil.cpu_freq()
            if freq:
                info.max_frequency_mhz = freq.max or freq.current
                info.current_frequency_mhz = freq.current

            # Cache info
            try:
                cache = psutil.cpu_cache_info()
                info.l2_cache_size = cache.l2_size if hasattr(cache, 'l2_size') else 0
                info.l3_cache_size = cache.l3_size if hasattr(cache, 'l3_size') else 0
            except (AttributeError, Exception):
                pass

            # Feature detection from cpuinfo
            try:
                cpu_info = psutil.cpu_freq(percpu=False)
                info.flags = getattr(cpu_info, 'flags', []) if cpu_info else []
            except Exception:
                pass

            info.supports_sse = any(f.startswith('sse') for f in info.flags)
            info.supports_avx = 'avx' in info.flags
            info.supports_avx2 = 'avx2' in info.flags

            logger.info(f"CPU detected: {info.model} ({info.physical_cores}C/{info.logical_cores}T)")
        except Exception as e:
            logger.error(f"CPU detection error: {e}")

        return info

    def read_snapshot(self) -> dict:
        """Read a single telemetry snapshot of CPU metrics."""
        snapshot = {}
        try:
            snapshot["utilization_percent"] = psutil.cpu_percent(interval=None)
            snapshot["per_core_percent"] = psutil.cpu_percent(interval=None, percpu=True)

            freq = psutil.cpu_freq()
            if freq:
                snapshot["current_frequency_mhz"] = freq.current

            snapshot["timestamp"] = time.time()
        except Exception as e:
            logger.error(f"CPU snapshot error: {e}")

        return snapshot

    def get_temperature(self) -> Optional[float]:
        """Attempt to read CPU temperature via psutil sensors."""
        try:
            temps = psutil.sensors_temperatures()
            if temps:
                # Try common sensor names
                for name in ["coretemp", "k10temp", "cpu_thermal", "zenpower"]:
                    if name in temps:
                        for entry in temps[name]:
                            if entry.current > 0:
                                return entry.current
        except (AttributeError, Exception) as e:
            logger.debug(f"CPU temperature unavailable: {e}")
        return None

    def update(self, info: CPUInfo) -> CPUInfo:
        """Update mutable CPU metrics."""
        try:
            info.utilization_percent = psutil.cpu_percent(interval=0.1)
            info.per_core_percent = psutil.cpu_percent(interval=0, percpu=True)

            freq = psutil.cpu_freq()
            if freq:
                info.current_frequency_mhz = freq.current

            temp = self.get_temperature()
            if temp is not None:
                info.temperature_celsius = temp
        except Exception as e:
            logger.error(f"CPU update error: {e}")

        return info


# Singleton for telemetry
cpu_monitor = CPUMonitor()
