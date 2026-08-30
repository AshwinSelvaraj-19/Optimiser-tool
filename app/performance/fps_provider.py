"""
FPS Provider architecture — pluggable frame-timing providers.
Each provider implements: is_available, start, stop, get_samples, get_metrics.
"""

import time
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional

from app.utils.logger import get_logger

logger = get_logger("performance.fps_provider")


@dataclass
class FrameSample:
    """A single frame presentation timestamp."""
    timestamp: float = 0.0  # time.time() when frame was presented
    frame_time_ms: float = 0.0  # ms since previous frame

    # PresentMon 2.5.1 extended fields
    process_name: str = ""
    pid: int = 0
    cpu_ms: float = 0.0
    display_ms: float = 0.0
    gpu_ms: float = 0.0
    gpu_busy: float = 0.0
    gpu_latency: float = 0.0
    render_latency: float = 0.0
    displayed_ms: float = 0.0
    input_latency: float = 0.0
    sync_interval: int = 0
    present_mode: str = ""


@dataclass
class FPSMetrics:
    """Calculated FPS metrics from real frame timestamps."""
    available: bool = False
    provider_name: str = "None"
    sample_count: int = 0
    duration_seconds: float = 0.0

    avg_fps: float = 0.0
    median_fps: float = 0.0
    min_fps: float = 0.0
    max_fps: float = 0.0
    one_percent_low: float = 0.0
    point_one_percent_low: float = 0.0

    avg_frame_time_ms: float = 0.0
    median_frame_time_ms: float = 0.0
    frame_time_variance: float = 0.0
    frame_spikes: int = 0
    frame_drops: int = 0
    stability_score: float = 0.0  # 0-100

    def unavailable(self) -> "FPSMetrics":
        """Return an explicitly unavailable metrics object."""
        return FPSMetrics(available=False, provider_name="None")


class FPSProvider(ABC):
    """Abstract base class for frame-timing providers."""

    name: str = "base"

    @abstractmethod
    def is_available(self) -> tuple:
        """
        Check if this provider is available on the current system.
        Returns: (is_available: bool, reason: str)
        """
        pass

    @abstractmethod
    def start(self, target_process: str = "") -> bool:
        """Start collecting frame timestamps. Returns True on success."""
        pass

    @abstractmethod
    def stop(self) -> bool:
        """Stop collecting. Returns True on success."""
        pass

    @abstractmethod
    def get_samples(self) -> list:
        """Get collected frame samples."""
        pass

    @abstractmethod
    def get_metrics(self) -> FPSMetrics:
        """Calculate and return metrics from collected samples."""
        pass


class FPSProviderRegistry:
    """Manages available FPS providers with auto-selection."""

    def __init__(self):
        self._providers: list = []
        self._active: Optional[FPSProvider] = None
        self._registered = False

    def _ensure_registered(self):
        """Lazily register providers to avoid circular imports."""
        if self._registered:
            return
        self._registered = True
        from app.performance.presentmon_provider import PresentMonProvider
        from app.performance.dwm_provider import DWMFrameProvider
        from app.performance.gpu_counter_provider import GPUCounterProvider
        self._providers = [
            PresentMonProvider(),
            DWMFrameProvider(),
            GPUCounterProvider(),
        ]

    def detect_available(self) -> list:
        """Check all providers and return availability status."""
        self._ensure_registered()
        results = []
        for provider in self._providers:
            available, reason = provider.is_available()
            results.append({
                "name": provider.name,
                "available": available,
                "reason": reason,
            })
        return results

    def select_best(self) -> Optional[FPSProvider]:
        """Auto-select the best available provider."""
        self._ensure_registered()
        for provider in self._providers:
            available, reason = provider.is_available()
            if available:
                self._active = provider
                logger.info(f"Selected FPS provider: {provider.name}")
                return provider
        self._active = None
        logger.info("No FPS provider available")
        return None

    @property
    def active(self) -> Optional[FPSProvider]:
        return self._active

    def get_status(self) -> dict:
        """Get current provider status for UI display."""
        if self._active:
            # Get extra info from PresentMon provider
            extra = {}
            if hasattr(self._active, 'get_version'):
                extra["version"] = self._active.get_version()
            if hasattr(self._active, 'get_path'):
                extra["path"] = self._active.get_path()
            return {
                "provider": self._active.name,
                "available": True,
                "status": "ACTIVE",
                **extra,
            }
        return {
            "provider": "None",
            "available": False,
            "status": "UNAVAILABLE",
        }


# Singleton
fps_registry = FPSProviderRegistry()
