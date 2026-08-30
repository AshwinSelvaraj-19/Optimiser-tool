"""
Benchmark engine — collects real performance metrics.
Uses pluggable FPS providers. Never fabricates FPS data.
"""

import threading
import time
from dataclasses import dataclass, field
from typing import Optional

from app.core.telemetry import telemetry_engine
from app.core.scoring import BenchmarkMetrics, PerformanceScore, performance_scorer
from app.performance.fps_provider import fps_registry, FPSMetrics
from app.utils.logger import get_logger

logger = get_logger("core.benchmark")


@dataclass
class BenchmarkConfig:
    """Benchmark configuration."""
    duration_seconds: int = 30
    sample_interval_ms: int = 100
    warmup_seconds: int = 3
    target_process: str = ""


@dataclass
class BenchmarkResult:
    """Complete benchmark result — only contains measured data."""
    config: BenchmarkConfig = field(default_factory=BenchmarkConfig)
    fps_metrics: Optional[FPSMetrics] = None
    score: Optional[PerformanceScore] = None
    system_samples: list = field(default_factory=list)
    start_time: str = ""
    end_time: str = ""
    duration_actual: float = 0.0
    is_valid: bool = False
    fps_available: bool = False
    notes: str = ""

    @property
    def metrics(self) -> BenchmarkMetrics:
        """Convert FPS metrics to scoring format if available."""
        if self.fps_metrics and self.fps_metrics.available:
            return BenchmarkMetrics(
                avg_fps=self.fps_metrics.avg_fps,
                one_percent_low=self.fps_metrics.one_percent_low,
                point_one_percent_low=self.fps_metrics.point_one_percent_low,
                avg_frame_time_ms=self.fps_metrics.avg_frame_time_ms,
                frame_time_variance=self.fps_metrics.frame_time_variance,
                frame_spikes=self.fps_metrics.frame_spikes,
                fps_drops=self.fps_metrics.frame_drops,
                duration_seconds=self.fps_metrics.duration_seconds,
                avg_gpu_util=self._get_avg_system("gpu_percent"),
            )
        return BenchmarkMetrics()


class BenchmarkEngine:
    """Performance benchmark engine — uses real measurements only."""

    def __init__(self):
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._progress_callback = None
        self._complete_callback = None
        self._result: Optional[BenchmarkResult] = None

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def last_result(self) -> Optional[BenchmarkResult]:
        return self._result

    def on_progress(self, callback):
        self._progress_callback = callback

    def on_complete(self, callback):
        self._complete_callback = callback

    def start(self, config: Optional[BenchmarkConfig] = None):
        """Start benchmark in background thread."""
        if self._running:
            return
        if config is None:
            config = BenchmarkConfig()
        self._running = True
        self._thread = threading.Thread(
            target=self._run, args=(config,), daemon=True, name="benchmark"
        )
        self._thread.start()

    def stop(self):
        self._running = False

    def run_sync(self, config: Optional[BenchmarkConfig] = None) -> BenchmarkResult:
        """Run benchmark synchronously."""
        if config is None:
            config = BenchmarkConfig()
        self._running = True
        return self._run(config)

    def _run(self, config: BenchmarkConfig) -> BenchmarkResult:
        """Execute the benchmark with real measurements."""
        from datetime import datetime
        result = BenchmarkResult(config=config)
        result.start_time = datetime.now().isoformat()

        logger.info(f"Benchmark starting: {config.duration_seconds}s")

        # Detect FPS provider
        provider = fps_registry.select_best()
        fps_available = False

        if provider:
            available, reason = provider.is_available()
            if available:
                fps_available = True
                result.fps_available = True
                logger.info(f"FPS provider: {provider.name} — {reason}")
                provider.start(config.target_process)
            else:
                logger.info(f"FPS provider unavailable: {reason}")
        else:
            logger.info("No FPS provider available")

        # Warmup
        logger.info(f"Warming up ({config.warmup_seconds}s)...")
        time.sleep(config.warmup_seconds)

        # Collect system telemetry samples
        start_time = time.time()
        total_samples = int(config.duration_seconds * 1000 / config.sample_interval_ms)
        system_samples = []

        logger.info("Collecting benchmark data...")

        for i in range(total_samples):
            if not self._running:
                break

            try:
                frame = telemetry_engine.current
                now = time.time()
                sample = {
                    "timestamp": now,
                    "cpu_percent": frame.cpu_utilization,
                    "gpu_percent": frame.gpu_utilization,
                    "ram_percent": frame.ram_percent,
                    "gpu_temp": frame.gpu_temp,
                    "cpu_temp": frame.cpu_temp,
                    "gpu_clock": frame.gpu_clock_mhz,
                    "gpu_vram_used": frame.gpu_memory_used_mb,
                    "gpu_vram_total": frame.gpu_memory_total_mb,
                }
                system_samples.append(sample)
            except Exception as e:
                logger.debug(f"System sample error: {e}")

            if self._progress_callback:
                self._progress_callback((i + 1) / total_samples)

            time.sleep(config.sample_interval_ms / 1000.0)

        result.duration_actual = time.time() - start_time
        result.system_samples = system_samples

        # Stop FPS provider and get metrics
        if fps_available and provider:
            provider.stop()
            result.fps_metrics = provider.get_metrics()
            logger.info(
                f"FPS metrics: avg={result.fps_metrics.avg_fps:.1f}, "
                f"1% low={result.fps_metrics.one_percent_low:.1f}, "
                f"frames={result.fps_metrics.sample_count}"
            )
        else:
            result.fps_metrics = FPSMetrics(available=False, provider_name="None")
            logger.info("FPS metrics: UNAVAILABLE (no provider)")

        # Calculate score
        if result.fps_metrics and result.fps_metrics.available:
            any_throttling = any(
                s.get("gpu_temp") is not None and s.get("gpu_temp", 0) > 85
                for s in system_samples
            )
            result.score = performance_scorer.calculate(
                result.metrics,
                cpu_temp=self._get_avg(system_samples, "cpu_temp"),
                gpu_temp=self._get_avg(system_samples, "gpu_temp"),
                thermal_throttling=any_throttling,
            )
        else:
            # Score without FPS — system health only
            result.score = PerformanceScore(
                total_score=0,
                grade="N/A",
            )

        result.is_valid = len(system_samples) >= 10
        result.end_time = datetime.now().isoformat()

        if not fps_available:
            result.notes = "FPS TELEMETRY UNAVAILABLE — No frame-timing provider found. System metrics collected only."
        elif result.fps_metrics.sample_count < 30:
            result.notes = f"Limited samples ({result.fps_metrics.sample_count}) — results may be less reliable"
        else:
            result.notes = f"Real FPS measurement via {result.fps_metrics.provider_name}"

        self._result = result
        self._running = False

        # Log summary
        if result.fps_metrics and result.fps_metrics.available:
            logger.info(
                f"Benchmark complete: {result.fps_metrics.avg_fps:.1f} FPS avg, "
                f"1% Low: {result.fps_metrics.one_percent_low:.1f}, "
                f"Score: {result.score.total_score:.1f}/100 ({result.score.grade})"
            )
        else:
            logger.info("Benchmark complete: FPS metrics UNAVAILABLE")

        if self._complete_callback:
            self._complete_callback(result)

        return result

    def _get_avg(self, samples: list, key: str) -> Optional[float]:
        """Get average of a key from samples, ignoring None."""
        vals = [s[key] for s in samples if s.get(key) is not None]
        return sum(vals) / len(vals) if vals else None


# Singleton
benchmark_engine = BenchmarkEngine()
