"""
Phase 55 — Benchmark & Validation Engine.

Provides meaningful before/after benchmarking with real measurements.

Components:
  BenchmarkMetric    — single metric with before/after/delta/change
  BenchmarkSnapshot  — point-in-time system measurement
  BenchmarkSession   — complete benchmark run (before + after + comparison)
  ComparisonEngine   — compares two snapshots, produces deltas
  BenchmarkEngine    — orchestrates quick/gaming/system benchmarks

Benchmark types:
  QUICK    — 5s telemetry snapshot
  GAMING   — 15s with PresentMon frame data
  SYSTEM   — 30s comprehensive system measurement

Rules:
  - Every number comes from real measurements
  - NOT_AVAILABLE for unmeasurable metrics
  - Never fabricate FPS or performance values
  - Measurements run asynchronously
  - Export results to JSON
"""

import json
import os
import time
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Tuple

import psutil

from app.utils.logger import get_logger

logger = get_logger("performance.benchmark_engine")


# ── Enums ────────────────────────────────────────────────────────


class BenchmarkType(Enum):
    """Type of benchmark to run."""
    QUICK = "QUICK"
    GAMING = "GAMING"
    SYSTEM = "SYSTEM"


class MetricStatus(Enum):
    """Whether a metric was actually measured."""
    MEASURED = "MEASURED"
    NOT_AVAILABLE = "NOT_AVAILABLE"
    FAILED = "FAILED"


class ChangeDirection(Enum):
    """Direction of change between before and after."""
    IMPROVED = "IMPROVED"
    DEGRADED = "DEGRADED"
    UNCHANGED = "UNCHANGED"
    UNKNOWN = "UNKNOWN"


# ── Data Models ────────────────────────────────────────────────────


@dataclass
class BenchmarkMetric:
    """A single benchmark metric with before/after comparison."""
    name: str = ""
    category: str = ""  # CPU, GPU, RAM, FPS, STORAGE, INPUT
    unit: str = ""  # %, MB, FPS, ms, GB

    # Before values
    before_value: Optional[float] = None
    before_status: MetricStatus = MetricStatus.NOT_AVAILABLE

    # After values
    after_value: Optional[float] = None
    after_status: MetricStatus = MetricStatus.NOT_AVAILABLE

    # Comparison
    delta: Optional[float] = None
    percent_change: Optional[float] = None
    direction: ChangeDirection = ChangeDirection.UNKNOWN

    # Metadata
    higher_is_better: bool = True  # False for latency, temperature, usage
    description: str = ""

    def compute_comparison(self):
        """Calculate delta and percent change from before/after values."""
        if self.before_value is None or self.after_value is None:
            self.delta = None
            self.percent_change = None
            self.direction = ChangeDirection.UNKNOWN
            return

        self.delta = self.after_value - self.before_value

        if self.before_value != 0:
            self.percent_change = (self.delta / abs(self.before_value)) * 100
        else:
            self.percent_change = None

        # Determine direction
        if abs(self.delta) < 0.01:
            self.direction = ChangeDirection.UNCHANGED
        elif self.higher_is_better:
            self.direction = (
                ChangeDirection.IMPROVED if self.delta > 0
                else ChangeDirection.DEGRADED
            )
        else:
            # Lower is better (latency, temperature, usage)
            self.direction = (
                ChangeDirection.IMPROVED if self.delta < 0
                else ChangeDirection.DEGRADED
            )

    @property
    def before_display(self) -> str:
        if self.before_value is None:
            return "N/A"
        return f"{self.before_value:.1f}{self.unit}"

    @property
    def after_display(self) -> str:
        if self.after_value is None:
            return "N/A"
        return f"{self.after_value:.1f}{self.unit}"

    @property
    def delta_display(self) -> str:
        if self.delta is None:
            return "N/A"
        sign = "+" if self.delta > 0 else ""
        return f"{sign}{self.delta:.1f}{self.unit}"

    @property
    def change_display(self) -> str:
        if self.percent_change is None:
            return "N/A"
        sign = "+" if self.percent_change > 0 else ""
        return f"{sign}{self.percent_change:.1f}%"

    @property
    def direction_icon(self) -> str:
        icons = {
            ChangeDirection.IMPROVED: "[+]",
            ChangeDirection.DEGRADED: "[-]",
            ChangeDirection.UNCHANGED: "[=]",
            ChangeDirection.UNKNOWN: "[?]",
        }
        return icons.get(self.direction, "[?]")

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "category": self.category,
            "unit": self.unit,
            "before_value": self.before_value,
            "before_status": self.before_status.value,
            "after_value": self.after_value,
            "after_status": self.after_status.value,
            "delta": self.delta,
            "percent_change": self.percent_change,
            "direction": self.direction.value,
            "higher_is_better": self.higher_is_better,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "BenchmarkMetric":
        m = cls(
            name=data.get("name", ""),
            category=data.get("category", ""),
            unit=data.get("unit", ""),
            before_value=data.get("before_value"),
            before_status=MetricStatus(data.get("before_status", "NOT_AVAILABLE")),
            after_value=data.get("after_value"),
            after_status=MetricStatus(data.get("after_status", "NOT_AVAILABLE")),
            higher_is_better=data.get("higher_is_better", True),
        )
        m.compute_comparison()
        return m


@dataclass
class BenchmarkSnapshot:
    """Point-in-time system measurement."""
    snapshot_id: str = ""
    timestamp: float = 0.0
    label: str = ""  # "BEFORE" or "AFTER"
    benchmark_type: BenchmarkType = BenchmarkType.QUICK
    duration_seconds: float = 0.0

    # CPU
    cpu_percent: Optional[float] = None
    cpu_per_core: List[float] = field(default_factory=list)

    # GPU
    gpu_utilization: Optional[float] = None
    gpu_temperature: Optional[float] = None
    gpu_vram_used: Optional[float] = None
    gpu_vram_total: Optional[float] = None

    # RAM
    ram_percent: Optional[float] = None
    ram_used_mb: Optional[float] = None
    ram_available_mb: Optional[float] = None
    ram_total_mb: Optional[float] = None

    # FPS (from PresentMon when available)
    fps: Optional[float] = None
    one_percent_low: Optional[float] = None
    frame_time_ms: Optional[float] = None
    frame_time_variance: Optional[float] = None

    # Storage
    disk_free_gb: Optional[float] = None
    disk_percent_used: Optional[float] = None

    # Target
    target_name: str = ""
    target_pid: int = 0

    def __post_init__(self):
        if not self.snapshot_id:
            self.snapshot_id = f"snap_{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "label": self.label,
            "benchmark_type": self.benchmark_type.value,
            "duration_seconds": self.duration_seconds,
            "cpu_percent": self.cpu_percent,
            "gpu_utilization": self.gpu_utilization,
            "gpu_temperature": self.gpu_temperature,
            "gpu_vram_used": self.gpu_vram_used,
            "gpu_vram_total": self.gpu_vram_total,
            "ram_percent": self.ram_percent,
            "ram_used_mb": self.ram_used_mb,
            "ram_available_mb": self.ram_available_mb,
            "ram_total_mb": self.ram_total_mb,
            "fps": self.fps,
            "one_percent_low": self.one_percent_low,
            "frame_time_ms": self.frame_time_ms,
            "frame_time_variance": self.frame_time_variance,
            "disk_free_gb": self.disk_free_gb,
            "disk_percent_used": self.disk_percent_used,
            "target_name": self.target_name,
            "target_pid": self.target_pid,
        }


@dataclass
class BenchmarkSession:
    """Complete benchmark session with before, after, and comparison."""
    session_id: str = ""
    benchmark_type: BenchmarkType = BenchmarkType.QUICK
    timestamp: float = 0.0
    duration_seconds: float = 0.0

    before: Optional[BenchmarkSnapshot] = None
    after: Optional[BenchmarkSnapshot] = None
    metrics: List[BenchmarkMetric] = field(default_factory=list)

    # Summary
    total_improved: int = 0
    total_degraded: int = 0
    total_unchanged: int = 0
    overall_verdict: str = "INCONCLUSIVE"

    # Errors
    errors: List[str] = field(default_factory=list)

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"bench_{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def compute_verdict(self):
        """Compute overall verdict from metrics."""
        improved = sum(1 for m in self.metrics if m.direction == ChangeDirection.IMPROVED)
        degraded = sum(1 for m in self.metrics if m.direction == ChangeDirection.DEGRADED)
        unchanged = sum(1 for m in self.metrics if m.direction == ChangeDirection.UNCHANGED)

        self.total_improved = improved
        self.total_degraded = degraded
        self.total_unchanged = unchanged

        if improved > 0 and degraded == 0:
            self.overall_verdict = "IMPROVED"
        elif degraded > 0 and improved == 0:
            self.overall_verdict = "DEGRADED"
        elif improved > degraded:
            self.overall_verdict = "MIXED_POSITIVE"
        elif degraded > improved:
            self.overall_verdict = "MIXED_NEGATIVE"
        elif improved == 0 and degraded == 0:
            self.overall_verdict = "UNCHANGED"
        else:
            self.overall_verdict = "MIXED"

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "benchmark_type": self.benchmark_type.value,
            "timestamp": self.timestamp,
            "duration_seconds": self.duration_seconds,
            "before": self.before.to_dict() if self.before else None,
            "after": self.after.to_dict() if self.after else None,
            "metrics": [m.to_dict() for m in self.metrics],
            "total_improved": self.total_improved,
            "total_degraded": self.total_degraded,
            "total_unchanged": self.total_unchanged,
            "overall_verdict": self.overall_verdict,
            "errors": self.errors,
        }


# ── Comparison Engine ──────────────────────────────────────────────


class ComparisonEngine:
    """Compare two BenchmarkSnapshots and produce BenchmarkMetrics."""

    @staticmethod
    def compare(
        before: BenchmarkSnapshot,
        after: BenchmarkSnapshot,
    ) -> List[BenchmarkMetric]:
        """Compare before and after snapshots, return list of metrics."""
        metrics = []

        def _add(name, cat, unit, before_val, after_val, higher_better=True, desc=""):
            m = BenchmarkMetric(
                name=name, category=cat, unit=unit,
                before_value=before_val, after_value=after_val,
                higher_is_better=higher_better, description=desc,
            )
            m.before_status = (
                MetricStatus.MEASURED if before_val is not None
                else MetricStatus.NOT_AVAILABLE
            )
            m.after_status = (
                MetricStatus.MEASURED if after_val is not None
                else MetricStatus.NOT_AVAILABLE
            )
            m.compute_comparison()
            metrics.append(m)

        # CPU
        _add("CPU Utilization", "CPU", "%",
             before.cpu_percent, after.cpu_percent,
             higher_better=False, desc="Total CPU usage")

        # GPU
        _add("GPU Utilization", "GPU", "%",
             before.gpu_utilization, after.gpu_utilization,
             higher_better=False, desc="GPU utilization")

        _add("GPU Temperature", "GPU", "°C",
             before.gpu_temperature, after.gpu_temperature,
             higher_better=False, desc="GPU temperature")

        if before.gpu_vram_used is not None or after.gpu_vram_used is not None:
            _add("GPU VRAM Used", "GPU", "MB",
                 before.gpu_vram_used, after.gpu_vram_used,
                 higher_better=False, desc="GPU VRAM usage")

        # RAM
        _add("RAM Usage", "RAM", "%",
             before.ram_percent, after.ram_percent,
             higher_better=False, desc="System RAM utilization")

        if before.ram_used_mb is not None or after.ram_used_mb is not None:
            _add("RAM Used", "RAM", "MB",
                 before.ram_used_mb, after.ram_used_mb,
                 higher_better=False, desc="RAM used in MB")

        # FPS
        _add("FPS", "FPS", "",
             before.fps, after.fps,
             higher_better=True, desc="Average frames per second")

        _add("1% Low FPS", "FPS", "",
             before.one_percent_low, after.one_percent_low,
             higher_better=True, desc="1% low frame rate")

        _add("Frame Time", "FPS", "ms",
             before.frame_time_ms, after.frame_time_ms,
             higher_better=False, desc="Average frame time")

        # Storage
        _add("Disk Free", "STORAGE", "GB",
             before.disk_free_gb, after.disk_free_gb,
             higher_better=True, desc="Free disk space")

        return metrics


# ── Benchmark Engine ──────────────────────────────────────────────


class BenchmarkEngine:
    """
    Orchestrates benchmark sessions: quick, gaming, and system benchmarks.

    Workflow:
      1. Capture BEFORE snapshot
      2. User applies optimization (manual)
      3. Capture AFTER snapshot
      4. Compare and produce results
      5. Export/save results
    """

    BENCHMARKS_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))),
        "benchmark_results",
    )

    def __init__(self):
        self._last_session: Optional[BenchmarkSession] = None
        self._history: List[Dict] = []
        os.makedirs(self.BENCHMARKS_DIR, exist_ok=True)
        self._load_history()

    @property
    def last_session(self) -> Optional[BenchmarkSession]:
        return self._last_session

    @property
    def history(self) -> List[Dict]:
        return self._history

    def capture_snapshot(
        self,
        label: str = "",
        benchmark_type: BenchmarkType = BenchmarkType.QUICK,
        duration_seconds: float = 5.0,
    ) -> BenchmarkSnapshot:
        """
        Capture a point-in-time system snapshot.
        Reads real system data from psutil and telemetry.
        """
        start = time.time()
        snap = BenchmarkSnapshot(
            label=label,
            benchmark_type=benchmark_type,
            timestamp=start,
        )

        try:
            # CPU
            snap.cpu_percent = psutil.cpu_percent(interval=1.0)
            try:
                snap.cpu_per_core = psutil.cpu_percent(interval=None, percpu=True)
            except Exception:
                pass

            # RAM
            vm = psutil.virtual_memory()
            snap.ram_percent = vm.percent
            snap.ram_used_mb = vm.used / (1024 * 1024)
            snap.ram_available_mb = vm.available / (1024 * 1024)
            snap.ram_total_mb = vm.total / (1024 * 1024)

            # GPU (from NVML when available)
            try:
                from app.system.gpu import gpu_monitor
                gpu_info = gpu_monitor.get_stats()
                if gpu_info:
                    snap.gpu_utilization = gpu_info.get("utilization_gpu")
                    snap.gpu_temperature = gpu_info.get("temperature_gpu")
                    snap.gpu_vram_used = gpu_info.get("memory_used")
                    snap.gpu_vram_total = gpu_info.get("memory_total")
            except Exception:
                pass

            # FPS from present telemetry
            try:
                from app.core.telemetry import telemetry_engine
                frame = telemetry_engine.current
                if frame.fps and frame.fps > 0:
                    snap.fps = frame.fps
                if frame.one_percent_low and frame.one_percent_low > 0:
                    snap.one_percent_low = frame.one_percent_low
                if frame.frame_time_ms and frame.frame_time_ms > 0:
                    snap.frame_time_ms = frame.frame_time_ms
            except Exception:
                pass

            # FPS from FPS provider if available
            if snap.fps is None:
                try:
                    from app.performance.fps_provider import fps_registry
                    if fps_registry.active and hasattr(fps_registry.active, 'get_metrics'):
                        metrics = fps_registry.active.get_metrics()
                        if metrics and metrics.available and metrics.sample_count > 0:
                            fps_val = metrics.median_fps if metrics.median_fps > 0 else metrics.avg_fps
                            if fps_val > 0:
                                snap.fps = fps_val
                            if metrics.one_percent_low > 0:
                                snap.one_percent_low = metrics.one_percent_low
                            if metrics.average_frame_time > 0:
                                snap.frame_time_ms = metrics.average_frame_time
                except Exception:
                    pass

            # Target process
            try:
                from app.core.emulator_controller import emulator_controller
                target = emulator_controller.detect_target()
                if target:
                    snap.target_name = target.name
                    snap.target_pid = target.pid
            except Exception:
                pass

            # Disk
            try:
                disk = psutil.disk_usage("C:\\")
                snap.disk_free_gb = disk.free / (1024 ** 3)
                snap.disk_percent_used = disk.percent
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Snapshot capture error: {e}")

        snap.duration_seconds = time.time() - start
        return snap

    def run_benchmark(
        self,
        benchmark_type: BenchmarkType = BenchmarkType.QUICK,
        before_snapshot: Optional[BenchmarkSnapshot] = None,
        duration_seconds: Optional[float] = None,
    ) -> BenchmarkSession:
        """
        Run a complete benchmark session.
        If before_snapshot is provided, captures AFTER and compares.
        Otherwise, just captures a single snapshot.
        """
        if duration_seconds is None:
            durations = {
                BenchmarkType.QUICK: 5.0,
                BenchmarkType.GAMING: 15.0,
                BenchmarkType.SYSTEM: 30.0,
            }
            duration_seconds = durations.get(benchmark_type, 5.0)

        session = BenchmarkSession(
            benchmark_type=benchmark_type,
            timestamp=time.time(),
        )

        try:
            if before_snapshot:
                # We're capturing the AFTER snapshot
                session.before = before_snapshot
                time.sleep(duration_seconds)
                session.after = self.capture_snapshot(
                    label="AFTER",
                    benchmark_type=benchmark_type,
                )
                session.duration_seconds = time.time() - session.timestamp

                # Compare
                if session.before and session.after:
                    session.metrics = ComparisonEngine.compare(
                        session.before, session.after
                    )
                    session.compute_verdict()
            else:
                # Just capture a single snapshot
                time.sleep(duration_seconds)
                session.after = self.capture_snapshot(
                    label="CURRENT",
                    benchmark_type=benchmark_type,
                )
                session.duration_seconds = time.time() - session.timestamp

                # Create metrics from single snapshot (no comparison)
                snap = session.after
                session.metrics = [
                    BenchmarkMetric(
                        name="CPU Utilization", category="CPU", unit="%",
                        after_value=snap.cpu_percent,
                        after_status=MetricStatus.MEASURED if snap.cpu_percent is not None else MetricStatus.NOT_AVAILABLE,
                    ),
                    BenchmarkMetric(
                        name="GPU Utilization", category="GPU", unit="%",
                        after_value=snap.gpu_utilization,
                        after_status=MetricStatus.MEASURED if snap.gpu_utilization is not None else MetricStatus.NOT_AVAILABLE,
                    ),
                    BenchmarkMetric(
                        name="GPU Temperature", category="GPU", unit="°C",
                        after_value=snap.gpu_temperature,
                        after_status=MetricStatus.MEASURED if snap.gpu_temperature is not None else MetricStatus.NOT_AVAILABLE,
                    ),
                    BenchmarkMetric(
                        name="RAM Usage", category="RAM", unit="%",
                        after_value=snap.ram_percent,
                        after_status=MetricStatus.MEASURED if snap.ram_percent is not None else MetricStatus.NOT_AVAILABLE,
                    ),
                    BenchmarkMetric(
                        name="FPS", category="FPS", unit="",
                        after_value=snap.fps,
                        after_status=MetricStatus.MEASURED if snap.fps is not None else MetricStatus.NOT_AVAILABLE,
                    ),
                    BenchmarkMetric(
                        name="1% Low FPS", category="FPS", unit="",
                        after_value=snap.one_percent_low,
                        after_status=MetricStatus.MEASURED if snap.one_percent_low is not None else MetricStatus.NOT_AVAILABLE,
                    ),
                    BenchmarkMetric(
                        name="Frame Time", category="FPS", unit="ms",
                        after_value=snap.frame_time_ms,
                        after_status=MetricStatus.MEASURED if snap.frame_time_ms is not None else MetricStatus.NOT_AVAILABLE,
                    ),
                    BenchmarkMetric(
                        name="Disk Free", category="STORAGE", unit="GB",
                        after_value=snap.disk_free_gb,
                        after_status=MetricStatus.MEASURED if snap.disk_free_gb is not None else MetricStatus.NOT_AVAILABLE,
                    ),
                ]

        except Exception as e:
            logger.error(f"Benchmark error: {e}")
            session.errors.append(str(e))

        self._last_session = session
        return session

    def save_session(self, session: Optional[BenchmarkSession] = None) -> bool:
        """Save a benchmark session to disk."""
        session = session or self._last_session
        if not session:
            return False

        try:
            filepath = os.path.join(
                self.BENCHMARKS_DIR,
                f"{session.session_id}.json",
            )
            with open(filepath, "w") as f:
                json.dump(session.to_dict(), f, indent=2)

            # Add to history
            self._history.append({
                "session_id": session.session_id,
                "benchmark_type": session.benchmark_type.value,
                "timestamp": session.timestamp,
                "verdict": session.overall_verdict,
                "improved": session.total_improved,
                "degraded": session.total_degraded,
            })
            self._save_history()
            return True
        except Exception as e:
            logger.error(f"Failed to save benchmark: {e}")
            return False

    def export_session(self, session: Optional[BenchmarkSession] = None) -> Optional[Dict]:
        """Export a session as a portable dict."""
        session = session or self._last_session
        if not session:
            return None
        return session.to_dict()

    def format_session(self, session: Optional[BenchmarkSession] = None) -> str:
        """Format a benchmark session for CLI display."""
        session = session or self._last_session
        if not session:
            return "No benchmark session available."

        lines = []
        w = 60
        lines.append("=" * w)
        lines.append(f"  HEAVEN SOCIETY — {session.benchmark_type.value} BENCHMARK")
        lines.append("=" * w)

        if session.before:
            lines.append(f"\n  BEFORE snapshot: {session.before.snapshot_id}")
            lines.append(f"    CPU: {session.before.cpu_percent:.1f}%" if session.before.cpu_percent else "    CPU: N/A")
            lines.append(f"    GPU: {session.before.gpu_utilization:.1f}%" if session.before.gpu_utilization else "    GPU: N/A")
            lines.append(f"    RAM: {session.before.ram_percent:.1f}%" if session.before.ram_percent else "    RAM: N/A")
            lines.append(f"    FPS: {session.before.fps:.1f}" if session.before.fps else "    FPS: N/A")
            lines.append(f"    Temp: {session.before.gpu_temperature:.0f}°C" if session.before.gpu_temperature else "    Temp: N/A")

        if session.after:
            label = "AFTER" if session.before else "CURRENT"
            lines.append(f"\n  {label} snapshot: {session.after.snapshot_id}")
            lines.append(f"    CPU: {session.after.cpu_percent:.1f}%" if session.after.cpu_percent else "    CPU: N/A")
            lines.append(f"    GPU: {session.after.gpu_utilization:.1f}%" if session.after.gpu_utilization else "    GPU: N/A")
            lines.append(f"    RAM: {session.after.ram_percent:.1f}%" if session.after.ram_percent else "    RAM: N/A")
            lines.append(f"    FPS: {session.after.fps:.1f}" if session.after.fps else "    FPS: N/A")
            lines.append(f"    Temp: {session.after.gpu_temperature:.0f}°C" if session.after.gpu_temperature else "    Temp: N/A")

        if session.before and session.after:
            lines.append(f"\n  COMPARISON")
            lines.append("  " + "-" * (w - 4))
            lines.append(
                f"  {'METRIC':<20} {'BEFORE':>10} {'AFTER':>10} {'DELTA':>10} {'CHANGE':>10} {'DIR':<5}"
            )
            lines.append("  " + "-" * (w - 4))
            for m in session.metrics:
                if m.before_value is not None or m.after_value is not None:
                    lines.append(
                        f"  {m.name:<20} {m.before_display:>10} {m.after_display:>10} "
                        f"{m.delta_display:>10} {m.change_display:>10} {m.direction_icon:<5}"
                    )

            lines.append(f"\n  VERDICT: {session.overall_verdict}")
            lines.append(
                f"  Improved: {session.total_improved}  "
                f"Degraded: {session.total_degraded}  "
                f"Unchanged: {session.total_unchanged}"
            )
        else:
            lines.append(f"\n  CURRENT MEASUREMENTS")
            lines.append("  " + "-" * (w - 4))
            for m in session.metrics:
                status = m.after_status.value
                val = m.after_display if m.after_value is not None else "N/A"
                lines.append(f"  {m.name:<20} {val:>10}  [{status}]")

        if session.errors:
            lines.append(f"\n  ERRORS")
            for e in session.errors:
                lines.append(f"    {e}")

        lines.append("\n" + "=" * w)
        return "\n".join(lines)

    # ── Internal ──────────────────────────────────────────────

    def _load_history(self):
        """Load benchmark history from disk."""
        try:
            history_file = os.path.join(self.BENCHMARKS_DIR, "_history.json")
            if os.path.exists(history_file):
                with open(history_file) as f:
                    self._history = json.load(f)
        except Exception:
            self._history = []

    def _save_history(self):
        """Save benchmark history to disk."""
        try:
            history_file = os.path.join(self.BENCHMARKS_DIR, "_history.json")
            with open(history_file, "w") as f:
                json.dump(self._history[-100:], f, indent=2)  # Keep last 100
        except Exception:
            pass


# ── Singleton ────────────────────────────────────────────────────

benchmark_engine = BenchmarkEngine()
