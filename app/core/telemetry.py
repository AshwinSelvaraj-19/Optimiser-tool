"""
Real-time telemetry engine.
Runs background workers to continuously update system metrics.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

from app.system.cpu import cpu_monitor, CPUInfo
from app.system.gpu import gpu_monitor, GPUInfo
from app.system.memory import memory_monitor
from app.system.thermals import thermal_monitor, ThermalSnapshot
from app.core.scanner import hardware_scanner
from app.utils.logger import get_logger

logger = get_logger("core.telemetry")


@dataclass
class TelemetryFrame:
    """Single telemetry reading at a point in time."""
    timestamp: float = 0.0
    cpu_utilization: float = 0.0
    cpu_per_core: list = field(default_factory=list)
    cpu_frequency_mhz: float = 0.0
    cpu_temp: Optional[float] = None
    gpu_utilization: float = 0.0
    gpu_temp: Optional[float] = None
    gpu_clock_mhz: float = 0.0
    gpu_memory_used_mb: float = 0.0
    gpu_memory_total_mb: float = 0.0
    gpu_power_watts: Optional[float] = None
    ram_percent: float = 0.0
    ram_used_gb: float = 0.0
    ram_total_gb: float = 0.0
    swap_percent: float = 0.0
    thermal_status: Optional[str] = None
    is_emulator_running: bool = False
    emulator_cpu_percent: float = 0.0
    emulator_memory_mb: float = 0.0

    @property
    def gpu_percent(self) -> float:
        return self.gpu_utilization

    @property
    def vram_percent(self) -> float:
        if self.gpu_memory_total_mb > 0:
            return (self.gpu_memory_used_mb / self.gpu_memory_total_mb) * 100
        return 0.0


class TelemetryEngine:
    """Background telemetry collection engine."""

    def __init__(self, interval_ms: int = 1000):
        self._interval = interval_ms / 1000.0
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._current_frame = TelemetryFrame()
        self._history: list = []
        self._max_history = 600  # 10 minutes at 1s interval
        self._callbacks: list = []
        self._emulator_pids: list = []

    @property
    def current(self) -> TelemetryFrame:
        """Get the latest telemetry frame (thread-safe)."""
        with self._lock:
            return self._current_frame

    @property
    def history(self) -> list:
        """Get telemetry history."""
        with self._lock:
            return list(self._history)

    def on_update(self, callback: Callable[[TelemetryFrame], None]):
        """Register a callback for telemetry updates."""
        self._callbacks.append(callback)

    def start(self):
        """Start background telemetry collection."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._worker, daemon=True, name="telemetry")
        self._thread.start()
        logger.info(f"Telemetry engine started (interval: {self._interval*1000:.0f}ms)")

    def stop(self):
        """Stop background telemetry collection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        logger.info("Telemetry engine stopped")

    def set_interval(self, interval_ms: int):
        """Change the telemetry interval."""
        self._interval = max(0.25, interval_ms / 1000.0)  # Minimum 250ms

    def set_emulator_pids(self, pids: list):
        """Set PIDs to monitor for emulator-specific metrics."""
        with self._lock:
            self._emulator_pids = pids

    def _worker(self):
        """Background telemetry collection loop."""
        import psutil
        # Prime CPU percent counter
        psutil.cpu_percent(interval=None)

        while self._running:
            try:
                frame = self._collect_frame()
                with self._lock:
                    self._current_frame = frame
                    self._history.append(frame)
                    if len(self._history) > self._max_history:
                        self._history.pop(0)

                # Notify callbacks
                for cb in self._callbacks:
                    try:
                        cb(frame)
                    except Exception as e:
                        logger.error(f"Telemetry callback error: {e}")

            except Exception as e:
                logger.error(f"Telemetry collection error: {e}")

            time.sleep(self._interval)

    def _collect_frame(self) -> TelemetryFrame:
        """Collect a single telemetry frame from all sources."""
        import psutil
        frame = TelemetryFrame(timestamp=time.time())

        # CPU
        try:
            frame.cpu_utilization = psutil.cpu_percent(interval=None)
            frame.cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
            freq = psutil.cpu_freq()
            if freq:
                frame.cpu_frequency_mhz = freq.current
            frame.cpu_temp = cpu_monitor.get_temperature()
        except Exception as e:
            logger.debug(f"CPU telemetry error: {e}")

        # GPU (primary discrete if available)
        try:
            profile = hardware_scanner.scan()
            if profile.gpus:
                gpu = profile.gpus[0]
                if gpu.vendor == "NVIDIA":
                    gpu = gpu_monitor.update_nvidia(gpu)
                frame.gpu_utilization = gpu.utilization_gpu
                frame.gpu_temp = gpu.temperature_celsius
                frame.gpu_clock_mhz = gpu.clock_core_mhz
                frame.gpu_memory_used_mb = gpu.vram_used_mb
                frame.gpu_memory_total_mb = gpu.vram_total_mb
                frame.gpu_power_watts = gpu.power_draw_watts
        except Exception as e:
            logger.debug(f"GPU telemetry error: {e}")

        # Memory
        try:
            mem = memory_monitor.read_snapshot()
            frame.ram_percent = mem.get("ram_percent", 0)
            frame.ram_used_gb = mem.get("ram_used_gb", 0)
            frame.ram_total_gb = mem.get("ram_total_gb", 0)
            frame.swap_percent = mem.get("swap_percent", 0)
        except Exception as e:
            logger.debug(f"Memory telemetry error: {e}")

        # Thermal
        try:
            snap = thermal_monitor.read_snapshot(
                cpu_temp=frame.cpu_temp,
                gpu_temp=frame.gpu_temp,
            )
            frame.thermal_status = "THROTTLING" if snap.any_throttling else "NORMAL"
        except Exception as e:
            logger.debug(f"Thermal telemetry error: {e}")

        # Emulator processes
        try:
            import psutil as _psutil
            emulator_cpu = 0.0
            emulator_mem = 0.0
            emulator_running = False
            for pid in self._emulator_pids:
                try:
                    proc = _psutil.Process(pid)
                    if proc.is_running():
                        emulator_running = True
                        emulator_cpu += proc.cpu_percent(interval=None)
                        mem_info = proc.memory_info()
                        emulator_mem += mem_info.rss / (1024 * 1024)
                except (_psutil.NoSuchProcess, _psutil.AccessDenied):
                    continue
            frame.is_emulator_running = emulator_running
            frame.emulator_cpu_percent = emulator_cpu
            frame.emulator_memory_mb = emulator_mem
        except Exception:
            pass

        return frame

    def get_avg_metrics(self, last_n: int = 30) -> dict:
        """Get average metrics over the last N frames."""
        with self._lock:
            frames = self._history[-last_n:] if self._history else []

        if not frames:
            return {}

        n = len(frames)
        return {
            "avg_cpu": sum(f.cpu_utilization for f in frames) / n,
            "avg_gpu": sum(f.gpu_utilization for f in frames) / n,
            "avg_ram": sum(f.ram_percent for f in frames) / n,
            "avg_gpu_temp": sum(f.gpu_temp for f in frames if f.gpu_temp) / max(1, sum(1 for f in frames if f.gpu_temp)),
            "avg_cpu_temp": sum(f.cpu_temp for f in frames if f.cpu_temp) / max(1, sum(1 for f in frames if f.cpu_temp)),
            "max_cpu": max(f.cpu_utilization for f in frames),
            "max_gpu": max(f.gpu_utilization for f in frames),
            "sample_count": n,
        }


# Singleton
import psutil
telemetry_engine = TelemetryEngine()
