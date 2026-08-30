"""
Real-time telemetry collector — bounded sampling engine.

Collects synchronized CPU/GPU/RAM/emulator/FPS data at configurable intervals.
Maintains a bounded sample buffer to prevent memory growth.
Never blocks the UI thread.
"""

import statistics
import threading
import time
from typing import Callable, List, Optional

from app.performance.telemetry_models import (
    DataAvailability,
    PerformanceSummary,
    TelemetrySample,
)
from app.utils.logger import get_logger

logger = get_logger("performance.telemetry_collector")


def _safe_avg(values: list) -> Optional[float]:
    """Calculate average of non-None values."""
    valid = [v for v in values if v is not None and v != 0]
    return statistics.mean(valid) if valid else None


def _safe_max(values: list) -> Optional[float]:
    """Calculate max of non-None values."""
    valid = [v for v in values if v is not None]
    return max(valid) if valid else None


def _safe_min(values: list) -> Optional[float]:
    """Calculate min of non-None values."""
    valid = [v for v in values if v is not None]
    return min(valid) if valid else None


class TelemetryCollector:
    """
    Bounded real-time sampling engine.

    Collects synchronized telemetry from CPU, GPU, memory, emulator
    and PresentMon (when active) at a configurable interval.
    """

    def __init__(self, interval_ms: int = 500, max_samples: int = 600):
        self._interval = max(0.25, interval_ms / 1000.0)
        self._max_samples = max_samples
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._lock = threading.Lock()
        self._samples: List[TelemetrySample] = []
        self._current: Optional[TelemetrySample] = None
        self._callbacks: List[Callable] = []
        self._emulator_pid: int = 0
        self._emulator_name: str = ""
        self._emulator_start_time: float = 0.0
        self._presentmon_available: bool = False
        self._fps_provider = None
        self._display_refresh: Optional[int] = None
        self._cpu_count: int = 0
        self._total_ram_mb: float = 0.0

    @property
    def current(self) -> Optional[TelemetrySample]:
        with self._lock:
            return self._current

    @property
    def sample_count(self) -> int:
        with self._lock:
            return len(self._samples)

    @property
    def samples(self) -> List[TelemetrySample]:
        with self._lock:
            return list(self._samples)

    def on_update(self, callback: Callable[[TelemetrySample], None]):
        """Register a callback for new samples."""
        self._callbacks.append(callback)

    def set_target(self, pid: int, name: str = "", start_time: float = 0.0):
        """Set the emulator target to monitor."""
        with self._lock:
            self._emulator_pid = pid
            self._emulator_name = name
            self._emulator_start_time = start_time

    def set_display_refresh(self, hz: int):
        """Set monitor refresh rate."""
        self._display_refresh = hz

    def set_fps_provider(self, provider):
        """Set the PresentMon FPS provider for FPS correlation."""
        self._fps_provider = provider

    def start(self):
        """Start background collection."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker, daemon=True, name="telemetry_collector"
        )
        self._thread.start()

    def stop(self):
        """Stop collection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)

    def clear(self):
        """Clear all collected samples."""
        with self._lock:
            self._samples.clear()
            self._current = None

    def collect_sample(self) -> TelemetrySample:
        """Collect a single synchronized telemetry sample (thread-safe)."""
        import psutil

        sample = TelemetrySample(timestamp=time.time())

        # System info
        try:
            if self._cpu_count == 0:
                self._cpu_count = psutil.cpu_count(logical=True) or 1
        except Exception:
            self._cpu_count = 1

        try:
            if self._total_ram_mb == 0:
                mem = psutil.virtual_memory()
                self._total_ram_mb = mem.total / (1024 * 1024)
        except Exception:
            pass

        # CPU metrics
        try:
            sample.cpu_total_percent = psutil.cpu_percent(interval=None)
            per_core = psutil.cpu_percent(interval=None, percpu=True)
            if per_core:
                sample.cpu_per_core_percent = per_core
            freq = psutil.cpu_freq()
            if freq:
                pass  # frequency not stored in TelemetrySample directly
        except Exception as e:
            logger.debug(f"CPU collection error: {e}")

        # RAM metrics
        try:
            mem = psutil.virtual_memory()
            sample.system_ram_used_mb = mem.used / (1024 * 1024)
            sample.system_ram_available_mb = mem.available / (1024 * 1024)
            sample.system_ram_total_mb = mem.total / (1024 * 1024)
        except Exception as e:
            logger.debug(f"RAM collection error: {e}")

        # GPU metrics (NVIDIA via NVML)
        try:
            from app.system.gpu import gpu_monitor
            from app.core.scanner import hardware_scanner
            profile = hardware_scanner.scan()
            if profile.gpus:
                gpu = profile.gpus[0]
                if gpu.vendor == "NVIDIA":
                    gpu = gpu_monitor.update_nvidia(gpu)
                sample.gpu_utilization_percent = gpu.utilization_gpu if gpu.utilization_gpu > 0 else None
                sample.gpu_temperature_c = gpu.temperature_celsius
                sample.gpu_vram_used_mb = gpu.vram_used_mb if gpu.vram_used_mb > 0 else None
                sample.gpu_vram_total_mb = gpu.vram_total_mb if gpu.vram_total_mb > 0 else None
                sample.gpu_clock_mhz = gpu.clock_core_mhz if gpu.clock_core_mhz > 0 else None
                sample.gpu_power_watts = gpu.power_draw_watts
        except Exception as e:
            logger.debug(f"GPU collection error: {e}")

        # Emulator metrics
        with self._lock:
            target_pid = self._emulator_pid
            target_name = self._emulator_name

        if target_pid > 0:
            sample.emulator_pid = target_pid
            sample.emulator_name = target_name
            try:
                proc = psutil.Process(target_pid)
                if proc.is_running():
                    # Validate start time for PID reuse protection
                    if self._emulator_start_time > 0:
                        proc_start = proc.create_time()
                        if abs(proc_start - self._emulator_start_time) > 5:
                            # PID was reused
                            sample.emulator_pid = 0
                            sample.emulator_name = ""
                        else:
                            sample.emulator_cpu_percent = proc.cpu_percent(interval=None)
                            mem_info = proc.memory_info()
                            sample.emulator_ram_mb = mem_info.rss / (1024 * 1024)
                    else:
                        sample.emulator_cpu_percent = proc.cpu_percent(interval=None)
                        mem_info = proc.memory_info()
                        sample.emulator_ram_mb = mem_info.rss / (1024 * 1024)
                else:
                    # Process exited
                    sample.emulator_pid = 0
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # CPU temperature (if available)
        try:
            from app.system.cpu import cpu_monitor
            cpu_temp = cpu_monitor.get_temperature()
            if cpu_temp is not None and cpu_temp > 0:
                sample.cpu_temperature_c = cpu_temp
        except Exception:
            pass

        # FPS from PresentMon (if provider has recent data)
        try:
            if self._fps_provider and hasattr(self._fps_provider, 'get_metrics'):
                metrics = self._fps_provider.get_metrics()
                if metrics and metrics.available and metrics.sample_count > 0:
                    sample.fps = metrics.median_fps if metrics.median_fps > 0 else metrics.avg_fps
                    sample.one_percent_low = metrics.one_percent_low if metrics.one_percent_low > 0 else None
                    sample.frame_time_ms = metrics.avg_frame_time_ms if metrics.avg_frame_time_ms > 0 else None
        except Exception as e:
            logger.debug(f"FPS collection error: {e}")

        # Display refresh
        if self._display_refresh:
            sample.display_refresh_hz = self._display_refresh

        # Store sample
        with self._lock:
            self._current = sample
            self._samples.append(sample)
            if len(self._samples) > self._max_samples:
                self._samples.pop(0)

        # Notify callbacks
        for cb in self._callbacks:
            try:
                cb(sample)
            except Exception as e:
                logger.debug(f"Telemetry callback error: {e}")

        return sample

    def _worker(self):
        """Background collection loop."""
        import psutil
        # Prime CPU percent counter
        try:
            psutil.cpu_percent(interval=None)
            for _ in range(psutil.cpu_count(logical=True) or 1):
                psutil.cpu_percent(interval=None, percpu=True)
        except Exception:
            pass

        while self._running:
            try:
                self.collect_sample()
            except Exception as e:
                logger.error(f"Telemetry collection error: {e}")
            time.sleep(self._interval)

    def calculate_summary(self) -> PerformanceSummary:
        """Calculate aggregated summary from collected samples."""
        with self._lock:
            samples = list(self._samples)

        return self._summarize(samples)

    def _summarize(self, samples: List[TelemetrySample]) -> PerformanceSummary:
        """Calculate summary from a list of samples."""
        import statistics as stats

        summary = PerformanceSummary()
        summary.sample_count = len(samples)

        if not samples:
            return summary

        summary.duration_seconds = samples[-1].timestamp - samples[0].timestamp

        # FPS
        fps_vals = [s.fps for s in samples if s.fps is not None and s.fps > 0]
        if fps_vals:
            summary.valid_sample_count = len(fps_vals)
            summary.avg_fps = stats.mean(fps_vals)
            summary.median_fps = stats.median(fps_vals)
            summary.min_fps = min(fps_vals)
            summary.max_fps = max(fps_vals)
            sorted_fps = sorted(fps_vals)
            n = len(sorted_fps)
            if n >= 10:
                summary.one_percent_low = sorted_fps[max(0, int(n * 0.99))]
                summary.point_one_percent_low = sorted_fps[max(0, int(n * 0.999))]
            else:
                summary.one_percent_low = sorted_fps[0]
                summary.point_one_percent_low = sorted_fps[0]

        # Frame time
        ft_vals = [s.frame_time_ms for s in samples if s.frame_time_ms is not None and s.frame_time_ms > 0]
        if ft_vals:
            summary.avg_frame_time_ms = stats.mean(ft_vals)
            summary.median_frame_time_ms = stats.median(ft_vals)
            if len(ft_vals) > 1:
                summary.frame_time_variance = stats.variance(ft_vals)
                summary.frame_time_std_dev = stats.stdev(ft_vals)
            spike_threshold = summary.avg_frame_time_ms * 2 if summary.avg_frame_time_ms else 33.33
            summary.frame_spikes = sum(1 for ft in ft_vals if ft > spike_threshold)
            summary.long_frame_count = sum(1 for ft in ft_vals if ft > spike_threshold * 2)

            # Stability
            if summary.avg_frame_time_ms > 0 and summary.frame_time_std_dev is not None:
                cv = summary.frame_time_std_dev / summary.avg_frame_time_ms
                summary.stability_score = max(0, min(100, 100 - (cv * 200)))
                if summary.stability_score >= 85:
                    summary.stability_rating = "EXCELLENT"
                elif summary.stability_score >= 70:
                    summary.stability_rating = "GOOD"
                elif summary.stability_score >= 50:
                    summary.stability_rating = "FAIR"
                elif summary.stability_score >= 30:
                    summary.stability_rating = "POOR"
                else:
                    summary.stability_rating = "BAD"
            else:
                summary.stability_score = 50.0
                summary.stability_rating = "UNKNOWN"

        # CPU
        cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
        if cpu_vals:
            summary.avg_cpu_percent = stats.mean(cpu_vals)
            summary.peak_cpu_percent = max(cpu_vals)
            # Per-core averages
            core_data = [s.cpu_per_core_percent for s in samples if s.cpu_per_core_percent]
            if core_data:
                n_cores = max(len(c) for c in core_data)
                summary.cpu_per_core_avg = [
                    stats.mean([c[i] for c in core_data if i < len(c)])
                    for i in range(n_cores)
                ]

        # GPU
        gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
        if gpu_vals:
            summary.avg_gpu_percent = stats.mean(gpu_vals)
            summary.peak_gpu_percent = max(gpu_vals)
        gpu_temps = [s.gpu_temperature_c for s in samples if s.gpu_temperature_c is not None]
        if gpu_temps:
            summary.max_gpu_temp = max(gpu_temps)
            summary.avg_gpu_temp = stats.mean(gpu_temps)
        vram_vals = [s.gpu_vram_used_mb for s in samples if s.gpu_vram_used_mb is not None]
        if vram_vals:
            summary.gpu_vram_used_avg = stats.mean(vram_vals)
        vram_total = [s.gpu_vram_total_mb for s in samples if s.gpu_vram_total_mb is not None]
        if vram_total:
            summary.gpu_vram_total = vram_total[0]

        # RAM
        ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
        if ram_used:
            summary.avg_ram_used_mb = stats.mean(ram_used)
            summary.peak_ram_used_mb = max(ram_used)
        ram_avail = [s.system_ram_available_mb for s in samples if s.system_ram_available_mb is not None]
        if ram_avail:
            summary.min_ram_available_mb = min(ram_avail)
            summary.avg_ram_available_mb = stats.mean(ram_avail)
        ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
        if ram_total:
            summary.ram_total_mb = ram_total[0]

        # Emulator
        emu_cpu = [s.emulator_cpu_percent for s in samples if s.emulator_cpu_percent is not None]
        if emu_cpu:
            summary.avg_emulator_cpu = stats.mean(emu_cpu)
            summary.peak_emulator_cpu = max(emu_cpu)
        emu_ram = [s.emulator_ram_mb for s in samples if s.emulator_ram_mb is not None]
        if emu_ram:
            summary.avg_emulator_ram_mb = stats.mean(emu_ram)
            summary.peak_emulator_ram_mb = max(emu_ram)

        return summary


# Singleton
telemetry_collector = TelemetryCollector()
