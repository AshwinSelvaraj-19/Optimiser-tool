"""
GPU Counter FPS provider — uses GPU performance counters for frame timing.
Falls back to GPU utilization-based estimation when direct frame timing unavailable.
"""

import time
import threading
from typing import Optional

from app.performance.fps_provider import FPSProvider, FPSMetrics, FrameSample
from app.system.gpu import gpu_monitor, NVML_AVAILABLE
from app.utils.logger import get_logger

logger = get_logger("performance.gpu_counter")


class GPUCounterProvider(FPSProvider):
    """
    FPS provider using GPU performance counters.
    
    NOTE: This provider does NOT estimate FPS from GPU utilization.
    It collects GPU clock/temperature/VRAM telemetry alongside frame timing.
    It is NOT a frame-timing provider by itself — it supplements other providers.
    
    If no frame-timing provider is available, this provider reports UNAVAILABLE.
    """

    name = "GPU Counters"

    def __init__(self):
        self._samples: list = []
        self._running = False
        self._thread = None

    def is_available(self) -> tuple:
        """GPU counters are available but they don't provide frame timing."""
        if NVML_AVAILABLE:
            return False, "GPU counters available but do not provide frame timing"
        return False, "NVML not available"

    def start(self, target_process: str = "") -> bool:
        """Not a frame timing provider — cannot start."""
        return False

    def stop(self) -> bool:
        return False

    def get_samples(self) -> list:
        return []

    def get_metrics(self) -> FPSMetrics:
        """Always returns unavailable — GPU utilization is not FPS."""
        return FPSMetrics(
            available=False,
            provider_name=self.name,
        )
