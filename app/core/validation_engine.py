"""
Phase 30 — Final Real-World Performance Validation Engine.

Standardized reproducible benchmark workflow:

  1.  Clean stale Phoenix resources
  2.  Verify prerequisites
  3.  Detect hardware
  4.  Detect emulator
  5.  Capture baseline
  6.  Run repeated baseline tests
  7.  Apply GAMING profile
  8.  Verify every optimization
  9.  Run repeated optimized tests
  10. Compare medians
  11. Calculate confidence
  12. Detect regressions
  13. Restore changes
  14. Verify restored state
  15. Cleanup all resources
  16. Generate final report

Every value originates from real measurements.
No fabricated values. No fake FPS. No fake improvement claims.

If results are inconsistent → INCONCLUSIVE
If optimized regresses → DEGRADED
Never manufacture improvement.
"""

import json
import os
import time
import statistics
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Tuple
from enum import Enum

from app.utils.logger import get_logger

# Module-level imports for testability (patchable)
from app.performance.elevated_launcher import kill_stale_phoenix_sessions
from app.performance.prerequisites import PrerequisiteChecker
from app.performance.target_process import target_process_detector
from app.system.cpu import cpu_monitor
from app.system.gpu import gpu_monitor
from app.system.memory import memory_monitor
from app.system.display import display_monitor
from app.system.thermal_monitor import thermal_diagnostics
from app.core.optimizer import Optimizer
from app.core.rollback import rollback_engine
from app.core.snapshot import snapshot_manager

logger = get_logger("core.validation_engine")

VALIDATIONS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "validations"
)


# ── Validation Result ─────────────────────────────────────────

class ValidationVerdict(Enum):
    """Final verdict of the validation run."""
    IMPROVED = "IMPROVED"
    DEGRADED = "DEGRADED"
    UNCHANGED = "UNCHANGED"
    INCONCLUSIVE = "INCONCLUSIVE"


class StepStatus(Enum):
    """Status of a single validation step."""
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"
    WARN = "WARN"


@dataclass
class ValidationStep:
    """Result of a single step in the validation workflow."""
    step_number: int
    name: str
    status: StepStatus
    message: str
    duration_seconds: float = 0.0
    details: dict = field(default_factory=dict)


@dataclass
class CaptureMetrics:
    """Metrics from a single PresentMon capture run."""
    present_fps: Optional[float] = None
    one_percent_low: Optional[float] = None
    zero_point_one_percent_low: Optional[float] = None
    average_frame_time: Optional[float] = None
    frame_time_variance: Optional[float] = None
    frame_spikes: Optional[int] = None
    stability: Optional[float] = None
    sample_count: int = 0
    target_pid: int = 0
    monitor_refresh: int = 0
    is_valid: bool = False
    error: str = ""


@dataclass
class CaptureSuite:
    """Aggregated results from repeated captures."""
    label: str = ""  # "baseline" or "optimized"
    captures: List[CaptureMetrics] = field(default_factory=list)

    @property
    def valid_captures(self) -> List[CaptureMetrics]:
        return [c for c in self.captures if c.is_valid]

    @property
    def valid_count(self) -> int:
        return len(self.valid_captures)

    @property
    def total_count(self) -> int:
        return len(self.captures)

    @property
    def pids(self) -> set:
        return {c.target_pid for c in self.valid_captures if c.target_pid > 0}

    @property
    def consistent_pid(self) -> bool:
        return len(self.pids) <= 1

    def _values(self, attr: str) -> List[float]:
        return [getattr(c, attr) for c in self.valid_captures if getattr(c, attr) is not None]

    @property
    def median_fps(self) -> Optional[float]:
        vals = self._values("present_fps")
        return statistics.median(vals) if vals else None

    @property
    def mean_fps(self) -> Optional[float]:
        vals = self._values("present_fps")
        return statistics.mean(vals) if vals else None

    @property
    def stdev_fps(self) -> Optional[float]:
        vals = self._values("present_fps")
        if len(vals) < 2:
            return 0.0
        return statistics.stdev(vals)

    @property
    def median_one_low(self) -> Optional[float]:
        vals = self._values("one_percent_low")
        return statistics.median(vals) if vals else None

    @property
    def median_01_low(self) -> Optional[float]:
        vals = self._values("zero_point_one_percent_low")
        return statistics.median(vals) if vals else None

    @property
    def median_frame_time(self) -> Optional[float]:
        vals = self._values("average_frame_time")
        return statistics.median(vals) if vals else None

    @property
    def median_stability(self) -> Optional[float]:
        vals = self._values("stability")
        return statistics.median(vals) if vals else None

    @property
    def median_spikes(self) -> Optional[float]:
        vals = [float(c.frame_spikes) for c in self.valid_captures if c.frame_spikes is not None]
        return statistics.median(vals) if vals else None

    @property
    def cv_fps(self) -> Optional[float]:
        """Coefficient of variation for FPS."""
        mean = self.mean_fps
        sd = self.stdev_fps
        if mean and mean > 0 and sd is not None:
            return (sd / mean) * 100
        return None

    def to_dict(self) -> dict:
        return {
            "label": self.label,
            "total_captures": self.total_count,
            "valid_captures": self.valid_count,
            "pids": sorted(self.pids),
            "consistent_pid": self.consistent_pid,
            "median_fps": self.median_fps,
            "mean_fps": self.mean_fps,
            "stdev_fps": self.stdev_fps,
            "cv_fps": self.cv_fps,
            "median_one_low": self.median_one_low,
            "median_01_low": self.median_01_low,
            "median_frame_time": self.median_frame_time,
            "median_stability": self.median_stability,
            "median_spikes": self.median_spikes,
        }


@dataclass
class SystemSnapshot:
    """Point-in-time system state."""
    cpu_utilization: Optional[float] = None
    gpu_utilization: Optional[float] = None
    ram_percent: Optional[float] = None
    gpu_temp: Optional[float] = None
    gpu_clock_mhz: Optional[float] = None
    gpu_power_watts: Optional[float] = None
    cpu_temp: Optional[float] = None
    cpu_freq_mhz: Optional[float] = None
    thermal_state: str = "UNKNOWN"

    # Hardware info
    cpu_model: str = ""
    cpu_cores: int = 0
    ram_total_gb: float = 0.0
    gpu_model: str = ""
    gpu_vram_mb: float = 0.0
    display_refresh: int = 0
    display_resolution: str = ""

    # Emulator
    emulator_name: str = ""
    emulator_pid: int = 0
    emulator_cpu_affinity: int = 0
    emulator_priority: str = ""

    def to_dict(self) -> dict:
        return {k: v for k, v in self.__dict__.items()}


@dataclass
class OptimizationRecord:
    """Record of a single optimization's state during validation."""
    opt_id: str = ""
    name: str = ""
    status: str = ""  # APPLIED, ALREADY_OPTIMAL, REQUIRES_ADMIN, RECOMMENDATION_ONLY, FAILED
    verified: bool = False
    message: str = ""

    def to_dict(self) -> dict:
        return self.__dict__.copy()


@dataclass
class ValidationReport:
    """Complete validation report — the final output of Phase 30."""
    validation_id: str = ""
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0

    # Environment
    system: SystemSnapshot = field(default_factory=SystemSnapshot)

    # Steps
    steps: List[ValidationStep] = field(default_factory=list)

    # Captures
    baseline: CaptureSuite = field(default_factory=lambda: CaptureSuite(label="baseline"))
    optimized: CaptureSuite = field(default_factory=lambda: CaptureSuite(label="optimized"))

    # Optimization
    profile_id: str = "gaming"
    optimizations_applied: List[OptimizationRecord] = field(default_factory=list)
    snapshot_id: str = ""

    # Comparison
    fps_delta: Optional[float] = None
    fps_delta_percent: Optional[float] = None
    one_low_delta: Optional[float] = None
    one_low_delta_percent: Optional[float] = None
    frame_time_delta: Optional[float] = None
    stability_delta: Optional[float] = None

    # Confidence
    confidence: str = "INCONCLUSIVE"  # HIGH, MODERATE, LOW, INCONCLUSIVE
    confidence_reason: str = ""

    # Verdict
    verdict: ValidationVerdict = ValidationVerdict.INCONCLUSIVE
    verdict_reason: str = ""

    # Cleanup state
    cleanup_complete: bool = False
    rollback_complete: bool = False

    def step_pass(self, num: int, name: str, msg: str, dur: float = 0.0, details: dict = None):
        self.steps.append(ValidationStep(num, name, StepStatus.PASS, msg, dur, details or {}))

    def step_fail(self, num: int, name: str, msg: str, dur: float = 0.0, details: dict = None):
        self.steps.append(ValidationStep(num, name, StepStatus.FAIL, msg, dur, details or {}))

    def step_skip(self, num: int, name: str, msg: str, dur: float = 0.0, details: dict = None):
        self.steps.append(ValidationStep(num, name, StepStatus.SKIP, msg, dur, details or {}))

    def step_warn(self, num: int, name: str, msg: str, dur: float = 0.0, details: dict = None):
        self.steps.append(ValidationStep(num, name, StepStatus.WARN, msg, dur, details or {}))

    def to_dict(self) -> dict:
        return {
            "validation_id": self.validation_id,
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "system": self.system.to_dict(),
            "steps": [
                {"step": s.step_number, "name": s.name, "status": s.status.value,
                 "message": s.message, "duration": s.duration_seconds}
                for s in self.steps
            ],
            "baseline": self.baseline.to_dict(),
            "optimized": self.optimized.to_dict(),
            "profile_id": self.profile_id,
            "optimizations": [o.to_dict() for o in self.optimizations_applied],
            "snapshot_id": self.snapshot_id,
            "comparison": {
                "fps_delta": self.fps_delta,
                "fps_delta_percent": self.fps_delta_percent,
                "one_low_delta": self.one_low_delta,
                "one_low_delta_percent": self.one_low_delta_percent,
                "frame_time_delta": self.frame_time_delta,
                "stability_delta": self.stability_delta,
            },
            "confidence": self.confidence,
            "confidence_reason": self.confidence_reason,
            "verdict": self.verdict.value,
            "verdict_reason": self.verdict_reason,
            "cleanup_complete": self.cleanup_complete,
            "rollback_complete": self.rollback_complete,
        }

    def format_cli(self) -> str:
        """Format for human-readable CLI output."""
        lines = []
        w = 60

        lines.append("=" * w)
        lines.append("  HEAVEN SOCIETY — FINAL PERFORMANCE VALIDATION")
        lines.append("=" * w)
        lines.append("")

        # System
        s = self.system
        lines.append("SYSTEM")
        lines.append("-" * w)
        if s.cpu_model:
            lines.append(f"  CPU:       {s.cpu_model} ({s.cpu_cores} cores)")
        if s.gpu_model:
            lines.append(f"  GPU:       {s.gpu_model} ({s.gpu_vram_mb:.0f} MB)")
        if s.ram_total_gb:
            lines.append(f"  RAM:       {s.ram_total_gb:.1f} GB")
        if s.display_resolution:
            lines.append(f"  Display:   {s.display_resolution} @ {s.display_refresh}Hz")
        if s.emulator_name:
            lines.append(f"  Emulator:  {s.emulator_name} PID {s.emulator_pid}")
        lines.append("")

        # Steps summary
        passed = sum(1 for st in self.steps if st.status == StepStatus.PASS)
        failed = sum(1 for st in self.steps if st.status == StepStatus.FAIL)
        skipped = sum(1 for st in self.steps if st.status == StepStatus.SKIP)
        warned = sum(1 for st in self.steps if st.status == StepStatus.WARN)

        lines.append("STEPS")
        lines.append("-" * w)
        for st in self.steps:
            icon = {"PASS": "[OK]", "FAIL": "[XX]", "SKIP": "--", "WARN": "[!!]"}
            lines.append(f"  {icon.get(st.status.value, '??'):4s} {st.step_number:2d}. {st.name}: {st.message}")
        lines.append("")

        # Baseline
        lines.append("BASELINE (median of {} captures)".format(self.baseline.valid_count))
        lines.append("-" * w)
        self._format_suite(lines, self.baseline)
        lines.append("")

        # Optimizations
        if self.optimizations_applied:
            lines.append("OPTIMIZATION: {}".format(self.profile_id.upper()))
            lines.append("-" * w)
            for o in self.optimizations_applied:
                icon = {"APPLIED": "[OK]", "ALREADY_OPTIMAL": "[==]",
                        "REQUIRES_ADMIN": "[!!]", "RECOMMENDATION_ONLY": "[>>]",
                        "FAILED": "[XX]", "SKIPPED": "--"}
                lines.append(f"  {icon.get(o.status, '??'):4s} {o.name}: {o.status}")
                if o.message:
                    lines.append(f"       {o.message}")
            lines.append("")

        # Optimized
        lines.append("OPTIMIZED (median of {} captures)".format(self.optimized.valid_count))
        lines.append("-" * w)
        self._format_suite(lines, self.optimized)
        lines.append("")

        # Comparison
        lines.append("COMPARISON")
        lines.append("-" * w)
        if self.fps_delta is not None:
            sign = "+" if self.fps_delta >= 0 else ""
            pct = f" ({self.fps_delta_percent:+.1f}%)" if self.fps_delta_percent is not None else ""
            lines.append(f"  FPS:           {sign}{self.fps_delta:.1f}{pct}")
        else:
            lines.append(f"  FPS:           N/A")
        if self.one_low_delta is not None:
            sign = "+" if self.one_low_delta >= 0 else ""
            pct = f" ({self.one_low_delta_percent:+.1f}%)" if self.one_low_delta_percent is not None else ""
            lines.append(f"  1% Low:        {sign}{self.one_low_delta:.1f}{pct}")
        else:
            lines.append(f"  1% Low:        N/A")
        if self.frame_time_delta is not None:
            sign = "+" if self.frame_time_delta >= 0 else ""
            lines.append(f"  Frame Time:    {sign}{self.frame_time_delta:.2f} ms")
        else:
            lines.append(f"  Frame Time:    N/A")
        if self.stability_delta is not None:
            sign = "+" if self.stability_delta >= 0 else ""
            lines.append(f"  Stability:     {sign}{self.stability_delta:.1f}")
        else:
            lines.append(f"  Stability:     N/A")
        lines.append("")

        # Confidence & verdict
        lines.append("CONFIDENCE:  {}".format(self.confidence))
        if self.confidence_reason:
            lines.append(f"  Reason: {self.confidence_reason}")
        lines.append("")
        lines.append("RESULT:      {}".format(self.verdict.value))
        if self.verdict_reason:
            lines.append(f"  Reason: {self.verdict_reason}")
        lines.append("")

        # Cleanup
        lines.append("CLEANUP")
        lines.append("-" * w)
        lines.append(f"  Rollback:  {'COMPLETE' if self.rollback_complete else 'PENDING'}")
        lines.append(f"  Resources: {'CLEAN' if self.cleanup_complete else 'PENDING'}")
        lines.append("")

        # Duration
        lines.append(f"Duration: {self.duration_seconds:.1f}s")
        lines.append("=" * w)

        return "\n".join(lines)

    def _format_suite(self, lines: list, suite: CaptureSuite):
        """Format a CaptureSuite for CLI output."""
        if suite.valid_count == 0:
            lines.append(f"  No valid captures")
            return
        fmt = "  {:<18s} {:>10s}"
        lines.append(fmt.format("Present FPS:", f"{suite.median_fps:.1f}" if suite.median_fps else "N/A"))
        lines.append(fmt.format("1% Low:", f"{suite.median_one_low:.1f}" if suite.median_one_low else "N/A"))
        lines.append(fmt.format("0.1% Low:", f"{suite.median_01_low:.1f}" if suite.median_01_low else "N/A"))
        lines.append(fmt.format("Frame Time:", f"{suite.median_frame_time:.2f} ms" if suite.median_frame_time else "N/A"))
        lines.append(fmt.format("Stability:", f"{suite.median_stability:.1f}" if suite.median_stability else "N/A"))
        if suite.median_spikes is not None:
            lines.append(fmt.format("Frame Spikes:", f"{suite.median_spikes:.0f}"))
        if suite.cv_fps is not None:
            lines.append(fmt.format("FPS CV:", f"{suite.cv_fps:.1f}%"))
        lines.append(f"  Valid runs: {suite.valid_count}/{suite.total_count}")


# ── Validation Engine ─────────────────────────────────────────

class ValidationEngine:
    """
    Standardized reproducible validation workflow.

    Orchestrates all Heaven Society subsystems into a single
    16-step validation pass.
    """

    def __init__(self, profile_id: str = "gaming", runs: int = 3, duration: int = 10):
        self.profile_id = profile_id
        self.runs = max(1, runs)
        self.duration = max(5, duration)
        self.report = ValidationReport(
            validation_id=f"val_{uuid.uuid4().hex[:8]}",
            profile_id=profile_id,
        )

    def run(self) -> ValidationReport:
        """Execute the full 16-step validation workflow."""
        self.report.started_at = datetime.now().isoformat()
        start = time.time()

        try:
            self._step_01_clean_stale()
            self._step_02_prerequisites()
            self._step_03_hardware()
            self._step_04_emulator()
            self._step_05_baseline_capture()
            self._step_06_repeated_baseline()
            self._step_07_apply_profile()
            self._step_08_verify_optimizations()
            self._step_09_repeated_optimized()
            self._step_10_compare_medians()
            self._step_11_calculate_confidence()
            self._step_12_detect_regressions()
            self._step_13_restore_changes()
            self._step_14_verify_restored()
            self._step_15_cleanup_resources()
            self._step_16_generate_report()
        except Exception as e:
            logger.error(f"Validation failed: {e}")
            self.report.step_fail(0, "VALIDATION", f"Unexpected error: {e}")

        self.report.completed_at = datetime.now().isoformat()
        self.report.duration_seconds = time.time() - start

        # Save report
        self._save_report()

        return self.report

    # ── Step 1: Clean stale resources ──────────────────────────

    def _step_01_clean_stale(self):
        t0 = time.time()
        try:
            import glob as globmod

            # Kill stale Phoenix PresentMon sessions
            killed = kill_stale_phoenix_sessions("PhoenixPerf_") or 0
            time.sleep(0.5)

            # Clean stale CSV files
            import tempfile
            csv_files = globmod.glob(os.path.join(tempfile.gettempdir(), "phoenix_pm_*.csv"))
            removed = 0
            for f in csv_files:
                try:
                    os.remove(f)
                    removed += 1
                except Exception:
                    pass

            dur = time.time() - t0
            self.report.step_pass(1, "Clean Stale Resources",
                                  f"Killed {killed} sessions, removed {removed} CSV files", dur)
        except Exception as e:
            self.report.step_fail(1, "Clean Stale Resources", str(e), time.time() - t0)

    # ── Step 2: Verify prerequisites ───────────────────────────

    def _step_02_prerequisites(self):
        t0 = time.time()
        try:
            checker = PrerequisiteChecker()
            result = checker.check_all()

            passed = sum(1 for p in result.prerequisites if p.status == "PASS")
            total = len(result.prerequisites)
            dur = time.time() - t0

            if passed == total:
                self.report.step_pass(2, "Verify Prerequisites",
                                      f"All {total} prerequisites met", dur)
            else:
                failed = [p.name for p in result.prerequisites if p.status == "FAIL"]
                self.report.step_fail(2, "Verify Prerequisites",
                                      f"{passed}/{total} met. Failed: {', '.join(failed)}", dur)
        except Exception as e:
            self.report.step_fail(2, "Verify Prerequisites", str(e), time.time() - t0)

    # ── Step 3: Detect hardware ────────────────────────────────

    def _step_03_hardware(self):
        t0 = time.time()
        try:
            sys = self.report.system

            # CPU
            try:
                cpu_info = cpu_monitor.detect()
                sys.cpu_model = getattr(cpu_info, 'model', '') or ""
                sys.cpu_cores = getattr(cpu_info, 'logical_cores', 0) or 0
                sys.cpu_freq_mhz = getattr(cpu_info, 'frequency_mhz', None)
            except Exception:
                pass

            # GPU
            try:
                gpu_info = gpu_monitor.detect()
                sys.gpu_model = getattr(gpu_info, 'name', '') or ""
                sys.gpu_vram_mb = getattr(gpu_info, 'vram_total_mb', 0) or 0
                sys.gpu_utilization = getattr(gpu_info, 'utilization_percent', None)
                sys.gpu_temp = getattr(gpu_info, 'temperature_c', None)
                sys.gpu_clock_mhz = getattr(gpu_info, 'clock_mhz', None)
                sys.gpu_power_watts = getattr(gpu_info, 'power_watts', None)
            except Exception:
                pass

            # RAM
            try:
                mem = memory_monitor.get_memory_info()
                sys.ram_total_gb = getattr(mem, 'total_gb', 0) or 0
                sys.ram_percent = getattr(mem, 'used_percent', None)
            except Exception:
                pass

            # Display
            try:
                disp = display_monitor.detect()
                sys.display_refresh = getattr(disp, 'refresh_rate_hz', 0) or 0
                w = getattr(disp, 'width', 0) or 0
                h = getattr(disp, 'height', 0) or 0
                if w and h:
                    sys.display_resolution = f"{w}x{h}"
            except Exception:
                pass

            # Thermal
            try:
                therm = thermal_diagnostics.get_status()
                sys.thermal_state = getattr(therm, 'status', 'UNKNOWN') or "UNKNOWN"
                sys.cpu_temp = getattr(therm, 'cpu_temperature', None)
            except Exception:
                pass

            dur = time.time() - t0
            info = []
            if sys.cpu_model:
                info.append(f"CPU={sys.cpu_model[:20]}")
            if sys.gpu_model:
                info.append(f"GPU={sys.gpu_model[:20]}")
            if sys.ram_total_gb:
                info.append(f"RAM={sys.ram_total_gb:.1f}GB")
            self.report.step_pass(3, "Detect Hardware",
                                  ", ".join(info) if info else "Hardware detected", dur)
        except Exception as e:
            self.report.step_fail(3, "Detect Hardware", str(e), time.time() - t0)

    # ── Step 4: Detect emulator ────────────────────────────────

    def _step_04_emulator(self):
        t0 = time.time()
        try:
            sys = self.report.system

            best = target_process_detector.select_best_target()

            if best:
                sys.emulator_name = best.process_name or ""
                sys.emulator_pid = best.pid or 0

                # Get detailed process info
                try:
                    import psutil
                    proc = psutil.Process(sys.emulator_pid)
                    affinity = proc.cpu_affinity()
                    sys.emulator_cpu_affinity = len(affinity) if isinstance(affinity, list) else bin(affinity).count('1')
                    import psutil as _ps
                    nice = proc.nice()
                    priority_names = {
                        -2: "LOW", -1: "BELOW NORMAL", 0: "NORMAL",
                        1: "ABOVE NORMAL", 2: "HIGH", 3: "ABOVE HIGH",
                    }
                    sys.emulator_priority = priority_names.get(nice, f"NICE={nice}")
                except Exception:
                    pass

                dur = time.time() - t0
                self.report.step_pass(4, "Detect Emulator",
                                      f"{sys.emulator_name} PID {sys.emulator_pid}", dur)
            else:
                dur = time.time() - t0
                self.report.step_skip(4, "Detect Emulator",
                                      "No emulator running — FPS capture will be unavailable", dur)

        except Exception as e:
            self.report.step_fail(4, "Detect Emulator", str(e), time.time() - t0)

    # ── Step 5: Baseline capture ───────────────────────────────

    def _step_05_baseline_capture(self):
        """Single baseline capture to verify PresentMon works."""
        t0 = time.time()
        sys = self.report.system

        if not sys.emulator_pid:
            self.report.step_skip(5, "Baseline Capture",
                                  "No emulator target — skipping capture")
            return

        try:
            metrics = self._single_capture()
            dur = time.time() - t0

            if metrics.is_valid:
                self.report.step_pass(5, "Baseline Capture",
                                      f"FPS={metrics.present_fps:.1f}, "
                                      f"1% Low={metrics.one_percent_low:.1f}, "
                                      f"Samples={metrics.sample_count}", dur)
            else:
                self.report.step_warn(5, "Baseline Capture",
                                      f"Capture failed: {metrics.error}", dur)
        except Exception as e:
            self.report.step_fail(5, "Baseline Capture", str(e), time.time() - t0)

    # ── Step 6: Repeated baseline ──────────────────────────────

    def _step_06_repeated_baseline(self):
        t0 = time.time()
        suite = self.report.baseline

        if not self.report.system.emulator_pid:
            self.report.step_skip(6, "Repeated Baseline",
                                  "No emulator target — skipping")
            return

        for i in range(self.runs):
            try:
                metrics = self._single_capture()
                suite.captures.append(metrics)
                if metrics.is_valid:
                    logger.info(f"Baseline run {i+1}: FPS={metrics.present_fps:.1f}")
                else:
                    logger.warning(f"Baseline run {i+1}: {metrics.error}")
            except Exception as e:
                suite.captures.append(CaptureMetrics(error=str(e)))
                logger.error(f"Baseline run {i+1} exception: {e}")

            # Brief pause between runs
            if i < self.runs - 1:
                time.sleep(2)

        dur = time.time() - t0
        valid = suite.valid_count
        if valid > 0:
            self.report.step_pass(6, "Repeated Baseline",
                                  f"{valid}/{self.runs} valid, median FPS={suite.median_fps:.1f}",
                                  dur)
        else:
            self.report.step_fail(6, "Repeated Baseline",
                                  f"0/{self.runs} valid captures", dur)

    # ── Step 7: Apply profile ──────────────────────────────────

    def _step_07_apply_profile(self):
        t0 = time.time()
        try:
            optimizer = Optimizer()

            report = optimizer.apply_profile(self.profile_id)

            # Record optimization results
            for r in report.results:
                rec = OptimizationRecord(
                    opt_id=r.opt_id,
                    name=r.name,
                    status=r.status,
                    verified=r.verified,
                    message=r.message,
                )
                self.report.optimizations_applied.append(rec)

            self.report.snapshot_id = report.snapshot_id

            dur = time.time() - t0
            applied = report.applied_count
            optimal = report.already_optimal_count
            admin = report.requires_admin_count
            failed = report.failed_count

            if report.session and report.session.busy:
                self.report.step_warn(7, "Apply Profile", "Optimizer busy", dur)
                return

            self.report.step_pass(7, "Apply Profile",
                                  f"Applied={applied} Optimal={optimal} "
                                  f"Admin={admin} Failed={failed}", dur)
        except Exception as e:
            self.report.step_fail(7, "Apply Profile", str(e), time.time() - t0)

    # ── Step 8: Verify optimizations ───────────────────────────

    def _step_08_verify_optimizations(self):
        t0 = time.time()
        verified = 0
        total = 0
        for rec in self.report.optimizations_applied:
            if rec.status in ("APPLIED", "ALREADY_OPTIMAL"):
                total += 1
                if rec.verified or rec.status == "ALREADY_OPTIMAL":
                    verified += 1

        dur = time.time() - t0
        if total == 0:
            self.report.step_skip(8, "Verify Optimizations",
                                  "No optimizations to verify")
        elif verified == total:
            self.report.step_pass(8, "Verify Optimizations",
                                  f"{verified}/{total} verified", dur)
        else:
            self.report.step_warn(8, "Verify Optimizations",
                                  f"{verified}/{total} verified", dur)

    # ── Step 9: Repeated optimized ─────────────────────────────

    def _step_09_repeated_optimized(self):
        t0 = time.time()
        suite = self.report.optimized

        if not self.report.system.emulator_pid:
            self.report.step_skip(9, "Repeated Optimized",
                                  "No emulator target — skipping")
            return

        # Brief stabilization delay
        time.sleep(2)

        for i in range(self.runs):
            try:
                metrics = self._single_capture()
                suite.captures.append(metrics)
                if metrics.is_valid:
                    logger.info(f"Optimized run {i+1}: FPS={metrics.present_fps:.1f}")
                else:
                    logger.warning(f"Optimized run {i+1}: {metrics.error}")
            except Exception as e:
                suite.captures.append(CaptureMetrics(error=str(e)))
                logger.error(f"Optimized run {i+1} exception: {e}")

            if i < self.runs - 1:
                time.sleep(2)

        dur = time.time() - t0
        valid = suite.valid_count
        if valid > 0:
            self.report.step_pass(9, "Repeated Optimized",
                                  f"{valid}/{self.runs} valid, median FPS={suite.median_fps:.1f}",
                                  dur)
        else:
            self.report.step_fail(9, "Repeated Optimized",
                                  f"0/{self.runs} valid captures", dur)

    # ── Step 10: Compare medians ───────────────────────────────

    def _step_10_compare_medians(self):
        t0 = time.time()
        base = self.report.baseline
        opt = self.report.optimized

        if base.valid_count == 0 or opt.valid_count == 0:
            self.report.step_skip(10, "Compare Medians",
                                  "Insufficient valid captures for comparison")
            return

        # FPS delta
        if base.median_fps is not None and opt.median_fps is not None:
            self.report.fps_delta = opt.median_fps - base.median_fps
            if base.median_fps > 0:
                self.report.fps_delta_percent = (self.report.fps_delta / base.median_fps) * 100

        # 1% Low delta
        if base.median_one_low is not None and opt.median_one_low is not None:
            self.report.one_low_delta = opt.median_one_low - base.median_one_low
            if base.median_one_low and base.median_one_low > 0:
                self.report.one_low_delta_percent = (self.report.one_low_delta / base.median_one_low) * 100

        # Frame time delta
        if base.median_frame_time is not None and opt.median_frame_time is not None:
            self.report.frame_time_delta = opt.median_frame_time - base.median_frame_time

        # Stability delta
        if base.median_stability is not None and opt.median_stability is not None:
            self.report.stability_delta = opt.median_stability - base.median_stability

        dur = time.time() - t0
        self.report.step_pass(10, "Compare Medians", "Comparison calculated", dur)

    # ── Step 11: Calculate confidence ──────────────────────────

    def _step_11_calculate_confidence(self):
        t0 = time.time()
        base = self.report.baseline
        opt = self.report.optimized

        reasons = []
        score = 0

        # Valid runs
        if base.valid_count >= self.runs:
            score += 30
        elif base.valid_count >= 2:
            score += 15
        else:
            reasons.append(f"Only {base.valid_count}/{self.runs} baseline runs valid")

        if opt.valid_count >= self.runs:
            score += 30
        elif opt.valid_count >= 2:
            score += 15
        else:
            reasons.append(f"Only {opt.valid_count}/{self.runs} optimized runs valid")

        # Consistent PIDs
        if base.consistent_pid and opt.consistent_pid:
            score += 20
        else:
            reasons.append("PID changed between runs")

        # Low variance
        if base.cv_fps is not None and base.cv_fps < 15:
            score += 10
        elif base.cv_fps is not None and base.cv_fps < 30:
            score += 5
        else:
            reasons.append(f"High FPS variance (CV={base.cv_fps:.1f}%)" if base.cv_fps else "FPS variance unknown")

        if opt.cv_fps is not None and opt.cv_fps < 15:
            score += 10
        elif opt.cv_fps is not None and opt.cv_fps < 30:
            score += 5
        else:
            reasons.append(f"High optimized variance (CV={opt.cv_fps:.1f}%)" if opt.cv_fps else "")

        # Classify
        if score >= 80:
            self.report.confidence = "HIGH"
        elif score >= 50:
            self.report.confidence = "MODERATE"
        elif score >= 25:
            self.report.confidence = "LOW"
        else:
            self.report.confidence = "INCONCLUSIVE"

        self.report.confidence_reason = "; ".join(r for r in reasons if r) or "Adequate data quality"

        dur = time.time() - t0
        self.report.step_pass(11, "Calculate Confidence",
                              f"{self.report.confidence} (score={score})", dur)

    # ── Step 12: Detect regressions ────────────────────────────

    def _step_12_detect_regressions(self):
        t0 = time.time()

        # Only classify if we have comparison data
        if self.report.fps_delta is None:
            self.report.verdict = ValidationVerdict.INCONCLUSIVE
            self.report.verdict_reason = "No valid comparison data"
            dur = time.time() - t0
            self.report.step_pass(12, "Detect Regressions",
                                  "INCONCLUSIVE — no comparison data", dur)
            return

        # Confidence must be at least MODERATE for a verdict
        if self.report.confidence in ("LOW", "INCONCLUSIVE"):
            self.report.verdict = ValidationVerdict.INCONCLUSIVE
            self.report.verdict_reason = f"Insufficient confidence ({self.report.confidence})"
            dur = time.time() - t0
            self.report.step_pass(12, "Detect Regressions",
                                  f"INCONCLUSIVE — {self.report.confidence} confidence", dur)
            return

        # Use significance thresholds
        fps_delta = self.report.fps_delta or 0
        fps_pct = self.report.fps_delta_percent or 0
        one_low_delta = self.report.one_low_delta or 0

        # IMPROVED: FPS increased >2 AND >1.5%, OR 1% low improved >2
        if (fps_delta > 2 and fps_pct > 1.5) or one_low_delta > 2:
            self.report.verdict = ValidationVerdict.IMPROVED
            self.report.verdict_reason = (
                f"FPS changed {fps_delta:+.1f} ({fps_pct:+.1f}%), "
                f"1% Low changed {one_low_delta:+.1f}"
            )
        # DEGRADED: FPS decreased >2 AND >1.5%
        elif (fps_delta < -2 and fps_pct < -1.5):
            self.report.verdict = ValidationVerdict.DEGRADED
            self.report.verdict_reason = (
                f"FPS regressed {fps_delta:+.1f} ({fps_pct:+.1f}%)"
            )
        # UNCHANGED
        else:
            self.report.verdict = ValidationVerdict.UNCHANGED
            self.report.verdict_reason = (
                f"FPS change {fps_delta:+.1f} ({fps_pct:+.1f}%) within noise margin"
            )

        dur = time.time() - t0
        self.report.step_pass(12, "Detect Regressions",
                              f"{self.report.verdict.value}: {self.report.verdict_reason}", dur)

    # ── Step 13: Restore changes ───────────────────────────────

    def _step_13_restore_changes(self):
        t0 = time.time()
        try:
            if not self.report.snapshot_id:
                self.report.step_skip(13, "Restore Changes",
                                      "No snapshot to restore")
                return

            snapshot = snapshot_manager.load_snapshot(self.report.snapshot_id)
            if snapshot is None:
                self.report.step_skip(13, "Restore Changes",
                                      f"Snapshot {self.report.snapshot_id} not found")
                return

            result = rollback_engine.rollback(snapshot)
            self.report.rollback_complete = result.success

            dur = time.time() - t0
            if result.success:
                self.report.step_pass(13, "Restore Changes",
                                      f"Restored {len(result.restored_entries)} entries", dur)
            else:
                self.report.step_warn(13, "Restore Changes",
                                      f"Partial: {len(result.restored_entries)} restored, "
                                      f"{len(result.failed_entries)} failed", dur)
        except Exception as e:
            self.report.step_fail(13, "Restore Changes", str(e), time.time() - t0)

    # ── Step 14: Verify restored state ─────────────────────────

    def _step_14_verify_restored(self):
        t0 = time.time()
        if not self.report.rollback_complete:
            self.report.step_skip(14, "Verify Restored",
                                  "Rollback not completed")
            return

        # Read current power plan to verify
        try:
            from app.system.power import power_monitor
            values = power_monitor.get_current_values()
            plan = values.get("active_plan", "unknown") if isinstance(values, dict) else "unknown"
            dur = time.time() - t0
            self.report.step_pass(14, "Verify Restored",
                                  f"Power plan: {plan}", dur)
        except Exception as e:
            self.report.step_warn(14, "Verify Restored",
                                  f"Verification partial: {e}", time.time() - t0)

    # ── Step 15: Cleanup resources ─────────────────────────────

    def _step_15_cleanup_resources(self):
        t0 = time.time()
        try:
            import glob as globmod
            import tempfile

            # Kill any remaining Phoenix PresentMon
            kill_stale_phoenix_sessions("PhoenixPerf_")
            time.sleep(0.5)

            # Clean CSV files
            csv_files = globmod.glob(os.path.join(tempfile.gettempdir(), "phoenix_pm_*.csv"))
            removed = 0
            for f in csv_files:
                try:
                    os.remove(f)
                    removed += 1
                except Exception:
                    pass

            self.report.cleanup_complete = True
            dur = time.time() - t0
            self.report.step_pass(15, "Cleanup Resources",
                                  f"Removed {removed} CSV files, cleaned sessions", dur)
        except Exception as e:
            self.report.step_fail(15, "Cleanup Resources", str(e), time.time() - t0)

    # ── Step 16: Generate report ───────────────────────────────

    def _step_16_generate_report(self):
        t0 = time.time()
        steps_passed = sum(1 for s in self.report.steps if s.status == StepStatus.PASS)
        steps_failed = sum(1 for s in self.report.steps if s.status == StepStatus.FAIL)
        steps_total = len(self.report.steps)

        dur = time.time() - t0
        self.report.step_pass(16, "Generate Report",
                              f"{steps_passed}/{steps_total} steps passed, "
                              f"verdict={self.report.verdict.value}", dur)

    # ── Single capture helper ──────────────────────────────────

    def _single_capture(self) -> CaptureMetrics:
        """Run a single PresentMon capture. Returns CaptureMetrics."""
        sys = self.report.system
        target = sys.emulator_name
        pid = sys.emulator_pid

        if not target or not pid:
            return CaptureMetrics(error="No target process")

        try:
            from app.performance.presentmon_provider import PresentMonProvider, find_presentmon
            from app.performance.elevated_launcher import kill_stale_phoenix_sessions

            pm_path = find_presentmon()
            if not pm_path:
                return CaptureMetrics(error="PresentMon not found")

            # Clean before capture
            kill_stale_phoenix_sessions("PhoenixPerf_")
            time.sleep(0.3)

            provider = PresentMonProvider()
            available, reason = provider.is_available()
            if not available:
                return CaptureMetrics(error=f"PresentMon not available: {reason}")

            start_ok = provider.start(target_process=target, duration=self.duration)
            if not start_ok:
                return CaptureMetrics(error=f"PresentMon start failed: {provider.get_error_reason()}")

            # Wait for capture
            time.sleep(self.duration + 5)

            # Get results
            sample = provider.get_latest_sample()
            samples = provider.get_frame_samples()

            provider.stop()
            time.sleep(1)

            if not sample and not samples:
                return CaptureMetrics(error="No frame samples collected")

            # Parse frame data
            from app.performance.frame_analyzer import FrameAnalyzer
            analyzer = FrameAnalyzer()
            analysis = analyzer.analyze(samples if samples else [sample])

            if not analysis:
                return CaptureMetrics(error="Frame analysis returned no results")

            metrics = CaptureMetrics(
                present_fps=analysis.get("present_fps"),
                one_percent_low=analysis.get("one_percent_low"),
                zero_point_one_percent_low=analysis.get("zero_point_one_percent_low"),
                average_frame_time=analysis.get("average_frame_time_ms"),
                frame_time_variance=analysis.get("frame_time_variance"),
                frame_spikes=analysis.get("frame_spikes"),
                stability=analysis.get("stability"),
                sample_count=analysis.get("sample_count", 0),
                target_pid=pid,
                monitor_refresh=sys.display_refresh,
                is_valid=analysis.get("present_fps") is not None and analysis.get("sample_count", 0) > 0,
            )
            return metrics

        except Exception as e:
            return CaptureMetrics(error=f"Capture exception: {e}")

    # ── Save report ────────────────────────────────────────────

    def _save_report(self):
        """Save validation report to disk."""
        try:
            os.makedirs(VALIDATIONS_DIR, exist_ok=True)
            filename = f"validation_{self.report.validation_id}.json"
            filepath = os.path.join(VALIDATIONS_DIR, filename)
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(self.report.to_dict(), f, indent=2, default=str)
            logger.info(f"Validation report saved: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save validation report: {e}")


# ── Convenience function ──────────────────────────────────────

def run_final_validation(profile_id: str = "gaming", runs: int = 3,
                         duration: int = 10) -> ValidationReport:
    """Run the complete Phase 30 validation workflow."""
    engine = ValidationEngine(profile_id=profile_id, runs=runs, duration=duration)
    return engine.run()
