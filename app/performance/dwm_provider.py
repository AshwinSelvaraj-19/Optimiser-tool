"""
DWM Frame Timing Provider — uses Windows Performance Counters for frame timing.
Measures Desktop Window Manager frame presentation intervals.
"""

import time
from typing import Optional

from app.performance.fps_provider import FPSProvider, FPSMetrics, FrameSample
from app.utils.commands import run_powershell
from app.utils.logger import get_logger

logger = get_logger("performance.dwm")


class DWMFrameProvider(FPSProvider):
    """FPS provider using DWM frame timing via Windows Performance Counters."""

    name = "DWM Frame Timing"

    def __init__(self):
        self._samples: list = []
        self._running = False
        self._thread = None
        self._interval_ms: int = 16  # ~60fps sampling

    def is_available(self) -> tuple:
        """Check if DWM frame timing is available."""
        try:
            # Test if we can read DWM counter
            success, stdout, _ = run_powershell(
                'Get-Counter "\\Desktop Window Manager\\Frame Rate" -ErrorAction SilentlyContinue | '
                'Select-Object -ExpandProperty CounterSamples | Select-Object -ExpandProperty CookedValue'
            )
            if success and stdout.strip():
                try:
                    val = float(stdout.strip())
                    if val > 0:
                        return True, f"DWM frame rate counter available ({val:.0f} fps)"
                except ValueError:
                    pass
        except Exception:
            pass

        # DWM counters may not be available on all systems
        return False, "DWM frame rate counter not available on this system"

    def start(self, target_process: str = "") -> bool:
        """Start DWM frame timing collection."""
        import threading

        self._running = True
        self._samples = []
        self._thread = threading.Thread(target=self._collect_loop, daemon=True)
        self._thread.start()
        logger.info("DWM frame timing started")
        return True

    def _collect_loop(self):
        """Background collection loop."""
        prev_timestamp = None
        while self._running:
            try:
                success, stdout, _ = run_powershell(
                    'Get-Counter "\\Desktop Window Manager\\Frame Rate" -ErrorAction SilentlyContinue | '
                    'Select-Object -ExpandProperty CounterSamples | Select-Object -ExpandProperty CookedValue'
                )
                if success and stdout.strip():
                    fps = float(stdout.strip())
                    if fps > 0:
                        now = time.time()
                        if prev_timestamp is not None:
                            # DWM gives us instantaneous FPS, convert to frame time
                            frame_time_ms = 1000.0 / fps
                            self._samples.append(FrameSample(
                                timestamp=now,
                                frame_time_ms=frame_time_ms,
                            ))
                        prev_timestamp = now
            except Exception:
                pass

            time.sleep(self._interval_ms / 1000.0)

    def stop(self) -> bool:
        """Stop collection."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=3)
        logger.info(f"DWM frame timing stopped: {len(self._samples)} samples")
        return True

    def get_samples(self) -> list:
        return self._samples

    def get_metrics(self) -> FPSMetrics:
        """Calculate metrics from DWM samples."""
        if not self._samples:
            return FPSMetrics(available=False, provider_name=self.name)

        frame_times = [s.frame_time_ms for s in self._samples if s.frame_time_ms > 0]
        if not frame_times:
            return FPSMetrics(available=False, provider_name=self.name)

        from app.performance.frame_analyzer import frame_analyzer
        pacing = frame_analyzer.analyze(frame_times)

        return FPSMetrics(
            available=True,
            provider_name=self.name,
            sample_count=len(frame_times),
            duration_seconds=sum(frame_times) / 1000.0,
            avg_fps=pacing.avg_fps,
            median_fps=pacing.median_fps,
            min_fps=pacing.min_fps,
            max_fps=pacing.max_fps,
            one_percent_low=pacing.one_percent_low,
            point_one_percent_low=pacing.point_one_percent_low,
            avg_frame_time_ms=pacing.avg_frame_time_ms,
            median_frame_time_ms=pacing.median_frame_time_ms,
            frame_time_variance=pacing.variance_ms,
            frame_spikes=pacing.spike_count,
            frame_drops=pacing.long_frame_count,
            stability_score=pacing.stability_score,
        )
