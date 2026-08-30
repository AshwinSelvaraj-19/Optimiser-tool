"""
Real-Time Performance Telemetry Engine.

Central orchestrator for continuous emulator/system telemetry collection,
bottleneck correlation, frame pacing analysis, and optimization correlation.

PHASE 34 — Strictly measurement/analysis. Never modifies system state.
"""

import statistics
import threading
import time
from typing import Callable, Dict, List, Optional

from app.performance.telemetry_models import (
    BeforeAfterSnapshot,
    BottleneckAssessment,
    BottleneckType,
    DataAvailability,
    EventType,
    EventSeverity,
    FramePacingStatus,
    MetricValue,
    PerformanceEvent,
    PerformanceSummary,
    TelemetryMetricState,
    TelemetryOverhead,
    TelemetrySample,
    TelemetrySession,
    TargetStatus,
)
from app.performance.telemetry_collector import TelemetryCollector
from app.performance.bottleneck_analyzer import BottleneckAnalyzer
from app.utils.logger import get_logger

logger = get_logger("performance.realtime_telemetry")

# Constants
DEFAULT_INTERVAL_MS = 500
DEFAULT_MAX_SAMPLES = 1200  # 10 minutes at 500ms
PID_REUSE_TOLERANCE_S = 5.0
STALE_THRESHOLD_S = 30.0  # Sample older than this is STALE
FRAME_PACING_MIN_SAMPLES = 10


class RealtimeTelemetry:
    """
    Real-time telemetry engine for the running emulator/game.

    Continuously collects CPU/GPU/RAM/emulator/FPS data, classifies
    bottlenecks, tracks frame pacing, and supports optimization correlation.

    Strictly measurement/analysis — never modifies system state.
    """

    def __init__(
        self,
        interval_ms: int = DEFAULT_INTERVAL_MS,
        max_samples: int = DEFAULT_MAX_SAMPLES,
    ):
        self._collector = TelemetryCollector(
            interval_ms=interval_ms, max_samples=max_samples
        )
        self._bottleneck_analyzer = BottleneckAnalyzer()
        self._interval_ms = interval_ms

        # Session
        self._session: Optional[TelemetrySession] = None
        self._running = False

        # Target
        self._target_name: str = ""
        self._target_pid: int = 0
        self._target_start_time: float = 0.0
        self._target_status: TargetStatus = TargetStatus.NOT_DETECTED

        # Optimization correlation
        self._before_snapshot: Optional[BeforeAfterSnapshot] = None
        self._after_snapshot: Optional[BeforeAfterSnapshot] = None

        # Overhead tracking
        self._overhead = TelemetryOverhead()
        self._collection_times: List[float] = []

        # Events
        self._events: List[PerformanceEvent] = []

        # Callbacks
        self._on_sample_callbacks: List[Callable] = []
        self._on_event_callbacks: List[Callable] = []
        self._on_target_change_callbacks: List[Callable] = []

        # Lock for thread safety
        self._lock = threading.Lock()

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def session(self) -> Optional[TelemetrySession]:
        return self._session

    @property
    def target_status(self) -> TargetStatus:
        return self._target_status

    @property
    def target_name(self) -> str:
        return self._target_name

    @property
    def target_pid(self) -> int:
        return self._target_pid

    @property
    def overhead(self) -> TelemetryOverhead:
        return self._overhead

    @property
    def events(self) -> List[PerformanceEvent]:
        with self._lock:
            return list(self._events)

    @property
    def before_snapshot(self) -> Optional[BeforeAfterSnapshot]:
        return self._before_snapshot

    @property
    def after_snapshot(self) -> Optional[BeforeAfterSnapshot]:
        return self._after_snapshot

    # ── Callbacks ──────────────────────────────────────────────

    def on_sample(self, callback: Callable[[TelemetrySample], None]):
        """Register callback for each new sample."""
        self._on_sample_callbacks.append(callback)

    def on_event(self, callback: Callable[[PerformanceEvent], None]):
        """Register callback for detected events."""
        self._on_event_callbacks.append(callback)

    def on_target_change(self, callback: Callable[[TargetStatus, str, int], None]):
        """Register callback for target status changes."""
        self._on_target_change_callbacks.append(callback)

    # ── Target Management ─────────────────────────────────────

    def set_target(
        self, pid: int, name: str = "", start_time: float = 0.0
    ):
        """
        Set the emulator target to monitor.

        Validates PID reuse by comparing process start time.
        """
        reuse_detected = False
        with self._lock:
            # PID reuse detection
            if self._target_pid == pid and pid > 0:
                # Same PID — verify it's still the same process
                if start_time > 0 and self._target_start_time > 0:
                    if abs(start_time - self._target_start_time) > PID_REUSE_TOLERANCE_S:
                        reuse_detected = True
                        logger.warning(
                            f"PID reuse detected: {pid} "
                            f"(old start={self._target_start_time}, new={start_time})"
                        )

            self._target_pid = pid
            self._target_name = name
            self._target_start_time = start_time

            if reuse_detected:
                self._target_status = TargetStatus.PID_REUSE_DETECTED
            elif pid > 0:
                self._target_status = TargetStatus.ACTIVE
            else:
                self._target_status = TargetStatus.NOT_DETECTED

        if reuse_detected:
            self._fire_target_change(
                TargetStatus.PID_REUSE_DETECTED, name, pid
            )

        # Propagate to collector
        self._collector.set_target(pid, name, start_time)

    def clear_target(self):
        """Clear the current target."""
        with self._lock:
            self._target_pid = 0
            self._target_name = ""
            self._target_start_time = 0.0
            self._target_status = TargetStatus.NOT_DETECTED
        self._collector.set_target(0, "", 0.0)

    def set_fps_provider(self, provider):
        """Set the PresentMon FPS provider."""
        self._collector.set_fps_provider(provider)

    def set_display_refresh(self, hz: int):
        """Set monitor refresh rate."""
        self._collector.set_display_refresh(hz)

    # ── Session Lifecycle ─────────────────────────────────────

    def start_session(self, target_name: str = "", target_pid: int = 0) -> TelemetrySession:
        """
        Start a new telemetry session.

        Creates a session, sets the target, and begins collection.
        """
        if self._running:
            logger.warning("Telemetry already running — stopping previous session")
            self.stop_session()

        self._session = TelemetrySession(
            started_at=time.time(),
            target_name=target_name,
            target_pid=target_pid,
        )

        if target_pid > 0:
            self.set_target(target_pid, target_name)

        # Reset state
        self._collector.clear()
        with self._lock:
            self._events.clear()
            self._collection_times.clear()
            self._before_snapshot = None
            self._after_snapshot = None
            self._overhead = TelemetryOverhead()

        # Start collection
        self._running = True
        self._collector.start()

        logger.info(
            f"Telemetry session started: {self._session.session_id} "
            f"target={target_name} pid={target_pid}"
        )
        return self._session

    def stop_session(self) -> Optional[TelemetrySession]:
        """
        Stop the current telemetry session.

        Returns the completed session with aggregated metrics.
        """
        if not self._running:
            return self._session

        self._running = False
        self._collector.stop()

        if self._session:
            self._session.completed_at = time.time()

            # Calculate summary
            summary = self._collector.calculate_summary()
            self._fill_session_from_summary(summary)

            # Bottleneck analysis
            samples = self._collector.samples
            self._session.bottleneck = self._bottleneck_analyzer.analyze_samples(samples)

            # Events
            with self._lock:
                self._session.events = list(self._events)

            # Overhead
            self._calculate_overhead()

            logger.info(
                f"Telemetry session stopped: {self._session.session_id} "
                f"samples={self._session.sample_count}"
            )

        return self._session

    def _fill_session_from_summary(self, summary: PerformanceSummary):
        """Fill session fields from a PerformanceSummary."""
        if not self._session:
            return
        self._session.sample_count = summary.sample_count
        self._session.avg_fps = summary.avg_fps
        self._session.median_fps = summary.median_fps
        self._session.min_fps = summary.min_fps
        self._session.max_fps = summary.max_fps
        self._session.one_percent_low = summary.one_percent_low
        self._session.point_one_percent_low = summary.point_one_percent_low
        self._session.avg_frame_time_ms = summary.avg_frame_time_ms
        self._session.frame_time_variance = summary.frame_time_variance
        self._session.frame_spikes = summary.frame_spikes
        self._session.avg_cpu_percent = summary.avg_cpu_percent
        self._session.peak_cpu_percent = summary.peak_cpu_percent
        self._session.avg_gpu_percent = summary.avg_gpu_percent
        self._session.peak_gpu_percent = summary.peak_gpu_percent
        self._session.max_gpu_temp = summary.max_gpu_temp
        self._session.avg_ram_used_mb = summary.avg_ram_used_mb
        self._session.peak_ram_used_mb = summary.peak_ram_used_mb
        self._session.min_ram_available_mb = summary.min_ram_available_mb
        self._session.avg_emulator_cpu = summary.avg_emulator_cpu
        self._session.avg_emulator_ram_mb = summary.avg_emulator_ram_mb

    # ── Data Access ───────────────────────────────────────────

    def latest_snapshot(self) -> Optional[TelemetrySample]:
        """Get the most recent telemetry sample."""
        return self._collector.current

    def recent_snapshots(self, count: int = 0) -> List[TelemetrySample]:
        """
        Get recent samples.

        If count <= 0, returns all samples in the bounded buffer.
        """
        all_samples = self._collector.samples
        if count > 0:
            return all_samples[-count:]
        return all_samples

    def calculate_summary(self) -> PerformanceSummary:
        """Calculate aggregated summary from all collected samples."""
        return self._collector.calculate_summary()

    def get_frame_pacing_status(self) -> FramePacingStatus:
        """Classify current frame pacing from recent samples."""
        samples = self._collector.samples
        if len(samples) < FRAME_PACING_MIN_SAMPLES:
            return FramePacingStatus.INSUFFICIENT_DATA

        ft_vals = [
            s.frame_time_ms
            for s in samples
            if s.frame_time_ms is not None and s.frame_time_ms > 0
        ]

        if len(ft_vals) < FRAME_PACING_MIN_SAMPLES:
            return FramePacingStatus.INSUFFICIENT_DATA

        avg_ft = statistics.mean(ft_vals)
        if avg_ft <= 0:
            return FramePacingStatus.INSUFFICIENT_DATA

        cv = statistics.stdev(ft_vals) / avg_ft if len(ft_vals) > 1 else 0

        if cv < 0.15:
            return FramePacingStatus.STABLE
        elif cv < 0.35:
            return FramePacingStatus.MILDLY_UNSTABLE
        else:
            return FramePacingStatus.UNSTABLE

    def get_bottleneck(self) -> BottleneckAssessment:
        """Get the current bottleneck assessment from recent samples."""
        samples = self._collector.samples
        return self._bottleneck_analyzer.analyze_samples(samples)

    # ── Optimization Correlation ──────────────────────────────

    def capture_before_snapshot(self, label: str = "BEFORE") -> BeforeAfterSnapshot:
        """
        Capture a before-optimization snapshot.

        Record current telemetry state for later comparison.
        """
        snapshot = self._create_snapshot(label)
        self._before_snapshot = snapshot
        logger.info(f"Before snapshot captured: {label}")
        return snapshot

    def capture_after_snapshot(self, label: str = "AFTER") -> BeforeAfterSnapshot:
        """
        Capture an after-optimization snapshot.

        Record current telemetry state for comparison with before.
        """
        snapshot = self._create_snapshot(label)
        self._after_snapshot = snapshot
        logger.info(f"After snapshot captured: {label}")
        return snapshot

    def _create_snapshot(self, label: str) -> BeforeAfterSnapshot:
        """Create a snapshot from the latest telemetry data."""
        sample = self._collector.current
        now = time.time()

        snapshot = BeforeAfterSnapshot(label=label, timestamp=now)

        if sample is None:
            return snapshot

        # FPS
        if sample.fps is not None and sample.fps > 0:
            snapshot.fps = MetricValue(
                value=sample.fps,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )

        # 1% Low
        if sample.one_percent_low is not None and sample.one_percent_low > 0:
            snapshot.one_percent_low = MetricValue(
                value=sample.one_percent_low,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )

        # Frame time
        if sample.frame_time_ms is not None and sample.frame_time_ms > 0:
            snapshot.frame_time_ms = MetricValue(
                value=sample.frame_time_ms,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )

        # CPU
        if sample.cpu_total_percent is not None:
            snapshot.cpu_percent = MetricValue(
                value=sample.cpu_total_percent,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )

        # GPU
        if sample.gpu_utilization_percent is not None:
            snapshot.gpu_percent = MetricValue(
                value=sample.gpu_utilization_percent,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )

        # GPU temp
        if sample.gpu_temperature_c is not None:
            snapshot.gpu_temp_c = MetricValue(
                value=sample.gpu_temperature_c,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )

        # RAM
        if sample.system_ram_used_mb is not None:
            snapshot.ram_used_mb = MetricValue(
                value=sample.system_ram_used_mb,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )
        if sample.system_ram_available_mb is not None:
            snapshot.ram_available_mb = MetricValue(
                value=sample.system_ram_available_mb,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )

        # Emulator
        if sample.emulator_cpu_percent is not None:
            snapshot.emulator_cpu_percent = MetricValue(
                value=sample.emulator_cpu_percent,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )
        if sample.emulator_ram_mb is not None:
            snapshot.emulator_ram_mb = MetricValue(
                value=sample.emulator_ram_mb,
                state=TelemetryMetricState.MEASURED,
                last_updated=sample.timestamp,
            )

        # Stability
        summary = self._collector.calculate_summary()
        snapshot.stability_score = summary.stability_score

        return snapshot

    def get_optimization_delta(
        self,
    ) -> Optional[Dict[str, Optional[float]]]:
        """
        Calculate the delta between before and after snapshots.

        Returns None if either snapshot is missing.
        Returns a dict of metric_name -> delta_value.
        """
        if not self._before_snapshot or not self._after_snapshot:
            return None

        deltas = {}

        pairs = [
            ("fps", self._before_snapshot.fps, self._after_snapshot.fps),
            ("one_percent_low", self._before_snapshot.one_percent_low, self._after_snapshot.one_percent_low),
            ("frame_time_ms", self._before_snapshot.frame_time_ms, self._after_snapshot.frame_time_ms),
            ("cpu_percent", self._before_snapshot.cpu_percent, self._after_snapshot.cpu_percent),
            ("gpu_percent", self._before_snapshot.gpu_percent, self._after_snapshot.gpu_percent),
            ("gpu_temp_c", self._before_snapshot.gpu_temp_c, self._after_snapshot.gpu_temp_c),
            ("ram_used_mb", self._before_snapshot.ram_used_mb, self._after_snapshot.ram_used_mb),
            ("ram_available_mb", self._before_snapshot.ram_available_mb, self._after_snapshot.ram_available_mb),
            ("emulator_cpu_percent", self._before_snapshot.emulator_cpu_percent, self._after_snapshot.emulator_cpu_percent),
            ("emulator_ram_mb", self._before_snapshot.emulator_ram_mb, self._after_snapshot.emulator_ram_mb),
        ]

        for name, before, after in pairs:
            if before.is_available() and after.is_available():
                deltas[name] = after.value - before.value
            else:
                deltas[name] = None

        return deltas

    # ── Overhead Measurement ──────────────────────────────────

    def _record_collection_time(self, duration_ms: float):
        """Record the time taken for a single collection cycle."""
        self._collection_times.append(duration_ms)
        # Keep last 100 measurements
        if len(self._collection_times) > 100:
            self._collection_times.pop(0)

    def _calculate_overhead(self):
        """Calculate telemetry overhead from recorded collection times."""
        if not self._collection_times:
            return

        self._overhead.measurement_count = len(self._collection_times)
        self._overhead.avg_collection_time_ms = statistics.mean(self._collection_times)
        self._overhead.peak_collection_time_ms = max(self._collection_times)
        self._overhead.collection_time_ms = self._collection_times[-1]

        # Calculate samples per second
        if self._overhead.avg_collection_time_ms > 0:
            self._overhead.samples_per_second = 1000.0 / (
                self._overhead.avg_collection_time_ms + (self._interval_ms - self._overhead.avg_collection_time_ms)
            )

        # CPU overhead estimate (collection time / interval)
        if self._interval_ms > 0:
            self._overhead.cpu_overhead_percent = (
                self._overhead.avg_collection_time_ms / self._interval_ms
            ) * 100

    def measure_overhead(self, samples: int = 20) -> TelemetryOverhead:
        """
        Actively measure the telemetry engine's collection overhead.

        Runs N collection cycles and records timing.
        """
        times = []
        for _ in range(samples):
            t0 = time.perf_counter()
            self._collector.collect_sample()
            elapsed = (time.perf_counter() - t0) * 1000
            times.append(elapsed)

        overhead = TelemetryOverhead(
            measurement_count=len(times),
            avg_collection_time_ms=statistics.mean(times),
            peak_collection_time_ms=max(times),
            collection_time_ms=times[-1] if times else 0,
        )

        if overhead.avg_collection_time_ms > 0:
            overhead.samples_per_second = 1000.0 / (
                overhead.avg_collection_time_ms + self._interval_ms
            )
        if self._interval_ms > 0:
            overhead.cpu_overhead_percent = (
                overhead.avg_collection_time_ms / self._interval_ms
            ) * 100

        self._overhead = overhead
        return overhead

    # ── Events ────────────────────────────────────────────────

    def _detect_events(self, sample: TelemetrySample):
        """Detect performance events from a new sample."""
        # GPU saturation
        if sample.gpu_utilization_percent is not None:
            if sample.gpu_utilization_percent >= 95:
                self._fire_event(
                    PerformanceEvent(
                        timestamp=sample.timestamp,
                        event_type=EventType.GPU_SATURATION,
                        severity=EventSeverity.WARNING,
                        measured_value=sample.gpu_utilization_percent,
                        threshold=95.0,
                        explanation=f"GPU utilization at {sample.gpu_utilization_percent:.1f}%",
                    )
                )

        # GPU thermal warning
        if sample.gpu_temperature_c is not None:
            if sample.gpu_temperature_c >= 85:
                self._fire_event(
                    PerformanceEvent(
                        timestamp=sample.timestamp,
                        event_type=EventType.GPU_THERMAL_WARNING,
                        severity=EventSeverity.WARNING if sample.gpu_temperature_c < 90 else EventSeverity.CRITICAL,
                        measured_value=sample.gpu_temperature_c,
                        threshold=85.0,
                        explanation=f"GPU temperature at {sample.gpu_temperature_c:.0f}°C",
                    )
                )

        # FPS drop (if we have FPS data)
        if sample.fps is not None and sample.fps > 0:
            if sample.fps < 30:
                self._fire_event(
                    PerformanceEvent(
                        timestamp=sample.timestamp,
                        event_type=EventType.FPS_DROP,
                        severity=EventSeverity.CRITICAL,
                        measured_value=sample.fps,
                        threshold=30.0,
                        explanation=f"FPS dropped to {sample.fps:.1f}",
                    )
                )
            elif sample.fps < 50:
                self._fire_event(
                    PerformanceEvent(
                        timestamp=sample.timestamp,
                        event_type=EventType.FPS_DROP,
                        severity=EventSeverity.WARNING,
                        measured_value=sample.fps,
                        threshold=50.0,
                        explanation=f"FPS at {sample.fps:.1f} (below expected)",
                    )
                )

        # Frame time spike
        if sample.frame_time_ms is not None and sample.frame_time_ms > 0:
            if sample.frame_time_ms > 50:  # >50ms = <20fps
                self._fire_event(
                    PerformanceEvent(
                        timestamp=sample.timestamp,
                        event_type=EventType.FRAME_TIME_SPIKE,
                        severity=EventSeverity.WARNING,
                        measured_value=sample.frame_time_ms,
                        threshold=50.0,
                        explanation=f"Frame time spike: {sample.frame_time_ms:.1f}ms",
                    )
                )

        # Emulator exit
        if sample.emulator_pid == 0 and self._target_pid > 0:
            self._fire_event(
                PerformanceEvent(
                    timestamp=sample.timestamp,
                    event_type=EventType.EMULATOR_EXITED,
                    severity=EventSeverity.WARNING,
                    explanation=f"Emulator target (PID {self._target_pid}) no longer detected",
                )
            )
            self._target_status = TargetStatus.STOPPED

    def _fire_event(self, event: PerformanceEvent):
        """Record an event and notify callbacks."""
        with self._lock:
            self._events.append(event)
            # Cap events at 200
            if len(self._events) > 200:
                self._events = self._events[-200:]

        for cb in self._on_event_callbacks:
            try:
                cb(event)
            except Exception as e:
                logger.debug(f"Event callback error: {e}")

    def _fire_target_change(self, status: TargetStatus, name: str, pid: int):
        """Notify target change callbacks."""
        for cb in self._on_target_change_callbacks:
            try:
                cb(status, name, pid)
            except Exception as e:
                logger.debug(f"Target change callback error: {e}")

    # ── Snapshot Access (thread-safe) ─────────────────────────

    def get_status_dict(self) -> Dict:
        """Get a complete status dictionary for CLI/UI consumption."""
        sample = self._collector.current
        summary = self._collector.calculate_summary() if self._collector.sample_count > 0 else None
        bottleneck = self.get_bottleneck()
        pacing = self.get_frame_pacing_status()

        # Build metric states
        def _metric_state(val, threshold_high=None, threshold_low=None):
            if val is None:
                return TelemetryMetricState.NOT_AVAILABLE.value
            return TelemetryMetricState.MEASURED.value

        result = {
            "target_name": self._target_name,
            "target_pid": self._target_pid,
            "target_status": self._target_status.value,
            "session_id": self._session.session_id if self._session else None,
            "sample_count": self._collector.sample_count,
            "is_running": self._running,
            "frame_pacing": pacing.value,
            "bottleneck": bottleneck.to_dict(),
            "overhead": self._overhead.to_dict(),
        }

        if sample:
            result["latest"] = {
                "timestamp": sample.timestamp,
                "fps": sample.fps,
                "one_percent_low": sample.one_percent_low,
                "frame_time_ms": sample.frame_time_ms,
                "cpu_percent": sample.cpu_total_percent,
                "gpu_percent": sample.gpu_utilization_percent,
                "gpu_temp_c": sample.gpu_temperature_c,
                "gpu_vram_used_mb": sample.gpu_vram_used_mb,
                "gpu_vram_total_mb": sample.gpu_vram_total_mb,
                "ram_used_mb": sample.system_ram_used_mb,
                "ram_available_mb": sample.system_ram_available_mb,
                "ram_total_mb": sample.system_ram_total_mb,
                "emulator_cpu_percent": sample.emulator_cpu_percent,
                "emulator_ram_mb": sample.emulator_ram_mb,
                "cpu_temperature_c": sample.cpu_temperature_c,
                "display_refresh_hz": sample.display_refresh_hz,
            }

        if summary:
            result["summary"] = summary.to_dict()

        # Optimization correlation
        if self._before_snapshot:
            result["before_snapshot"] = self._before_snapshot.to_dict()
        if self._after_snapshot:
            result["after_snapshot"] = self._after_snapshot.to_dict()
        delta = self.get_optimization_delta()
        if delta:
            result["optimization_delta"] = delta

        return result


# ── Singleton ─────────────────────────────────────────────────
realtime_telemetry = RealtimeTelemetry()
