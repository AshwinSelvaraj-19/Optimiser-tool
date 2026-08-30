"""
Thermal monitoring module.
Tracks CPU/GPU temperatures and detects thermal throttling.
"""

import time
from dataclasses import dataclass
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("system.thermals")


@dataclass
class ThermalSnapshot:
    """Point-in-time thermal data."""
    cpu_temp: Optional[float] = None
    gpu_temp: Optional[float] = None
    timestamp: float = 0.0
    cpu_throttling: bool = False
    gpu_throttling: bool = False

    @property
    def any_throttling(self) -> bool:
        return self.cpu_throttling or self.gpu_throttling

    @property
    def max_temp(self) -> float:
        temps = [t for t in [self.cpu_temp, self.gpu_temp] if t is not None]
        return max(temps) if temps else 0.0


@dataclass
class ThermalStatus:
    """Overall thermal assessment."""
    status: str = "UNKNOWN"  # NORMAL, WARM, HOT, CRITICAL, THROTTLING
    max_temp_reached: float = 0.0
    cpu_throttling_detected: bool = False
    gpu_throttling_detected: bool = False
    recommendation: str = ""


# Temperature thresholds (Celsius)
TEMP_NORMAL = 70.0
TEMP_WARM = 80.0
TEMP_HOT = 90.0
TEMP_CRITICAL = 95.0


class ThermalMonitor:
    """Temperature monitoring and thermal throttling detection."""

    def __init__(self):
        self._temp_history: list = []
        self._clock_history: list = []
        self._max_history = 60  # 60 samples

    def read_snapshot(self, cpu_temp: Optional[float] = None,
                      gpu_temp: Optional[float] = None) -> ThermalSnapshot:
        """Read a thermal snapshot."""
        snapshot = ThermalSnapshot(
            cpu_temp=cpu_temp,
            gpu_temp=gpu_temp,
            timestamp=time.time(),
        )

        # Detect throttling based on temperature
        if cpu_temp is not None:
            snapshot.cpu_throttling = cpu_temp >= TEMP_HOT
        if gpu_temp is not None:
            snapshot.gpu_throttling = gpu_temp >= TEMP_HOT

        # Track history
        self._temp_history.append(snapshot)
        if len(self._temp_history) > self._max_history:
            self._temp_history.pop(0)

        return snapshot

    def assess_thermal_status(self, current_snapshot: ThermalSnapshot,
                              gpu_clock: Optional[float] = None,
                              prev_gpu_clock: Optional[float] = None) -> ThermalStatus:
        """
        Assess thermal status from current snapshot.
        Detects throttling patterns.
        """
        status = ThermalStatus()

        max_temp = current_snapshot.max_temp

        if max_temp >= TEMP_CRITICAL:
            status.status = "CRITICAL"
            status.recommendation = (
                "CRITICAL TEMPERATURE — Performance will be severely limited. "
                "Improve cooling immediately. Consider lowering emulator settings."
            )
        elif max_temp >= TEMP_HOT:
            status.status = "HOT"
            status.recommendation = (
                "High temperature detected — Thermal throttling is likely active. "
                "Performance may be reduced. Improve airflow or reduce load."
            )
        elif max_temp >= TEMP_WARM:
            status.status = "WARM"
            status.recommendation = (
                "Temperature is elevated. Monitor for further increases. "
                "Consider improving case airflow."
            )
        elif max_temp >= TEMP_NORMAL:
            status.status = "NORMAL"
            status.recommendation = "Temperature within normal operating range."
        else:
            status.status = "COOL"
            status.recommendation = "Temperature is low — no thermal concerns."

        status.max_temp_reached = max_temp

        # Detect clock-based throttling
        if gpu_clock is not None and prev_gpu_clock is not None:
            if prev_gpu_clock > 0 and gpu_clock < prev_gpu_clock * 0.85:
                status.gpu_throttling_detected = True
                status.status = "THROTTLING"
                status.recommendation = (
                    f"GPU clock dropped from {prev_gpu_clock:.0f}MHz to {gpu_clock:.0f}MHz — "
                    "thermal throttling detected. Reduce GPU load or improve cooling."
                )

        # Check sustained throttling
        if len(self._temp_history) >= 10:
            recent = self._temp_history[-10:]
            throttled_count = sum(1 for s in recent if s.any_throttling)
            if throttled_count >= 7:
                status.cpu_throttling_detected = True
                status.gpu_throttling_detected = True
                if status.status != "THROTTLING":
                    status.status = "THROTTLING"
                    status.recommendation = (
                        "Sustained thermal throttling detected over the last 10 samples. "
                        "Performance is being significantly limited. "
                        "Reduce emulator resolution or improve cooling."
                    )

        status.max_temp_reached = max(
            (s.max_temp for s in self._temp_history[-10:] if s.max_temp > 0),
            default=max_temp,
        )

        return status

    def is_thermal_concern(self, snapshot: ThermalSnapshot) -> bool:
        """Quick check if current temperatures are concerning."""
        return snapshot.max_temp >= TEMP_WARM

    def get_avg_temp(self, last_n: int = 10, source: str = "max") -> Optional[float]:
        """Get average temperature over last N samples."""
        if not self._temp_history:
            return None
        recent = self._temp_history[-last_n:]
        if source == "cpu":
            temps = [s.cpu_temp for s in recent if s.cpu_temp is not None]
        elif source == "gpu":
            temps = [s.gpu_temp for s in recent if s.gpu_temp is not None]
        else:
            temps = [s.max_temp for s in recent if s.max_temp > 0]

        return sum(temps) / len(temps) if temps else None

    def clear_history(self):
        """Clear thermal history."""
        self._temp_history.clear()
        self._clock_history.clear()


# Singleton
thermal_monitor = ThermalMonitor()
