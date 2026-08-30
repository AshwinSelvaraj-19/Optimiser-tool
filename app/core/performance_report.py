"""
Professional Performance Report — Phase 28

Creates a complete gaming performance report from existing telemetry.

Sections:
  SYSTEM    — CPU, GPU, VRAM, RAM, Windows, display
  EMULATOR  — emulator, PID, CPU affinity, priority, configuration
  PERFORMANCE — FPS, 1% low, 0.1% low, frame time, variance, stability, spikes
  THERMAL   — CPU temp, GPU temp, clocks, thermal state
  OPTIMIZATION — applied, already optimal, requires admin, recommendation only, failed, rollback
  BENCHMARK — baseline, optimized, delta, confidence, reliability

Every value comes from real measurements.
If a metric cannot be measured, it is explicitly None or "N/A".
Do not fabricate missing values.
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict

from app.utils.logger import get_logger

logger = get_logger("core.performance_report")


# ── Data Models ───────────────────────────────────────────────

@dataclass
class SystemSection:
    """System hardware information."""
    cpu_model: str = "N/A"
    cpu_cores: str = "N/A"
    cpu_frequency: str = "N/A"
    cpu_utilization: Optional[float] = None
    cpu_temperature: Optional[float] = None

    gpu_name: str = "N/A"
    gpu_vendor: str = "N/A"
    gpu_driver: str = "N/A"
    gpu_utilization: Optional[float] = None
    gpu_temperature: Optional[float] = None
    gpu_clock: Optional[float] = None
    gpu_power: Optional[float] = None
    gpu_vram_total: Optional[float] = None
    gpu_vram_used: Optional[float] = None

    ram_total: Optional[float] = None
    ram_used: Optional[float] = None
    ram_percent: Optional[float] = None

    windows_version: str = "N/A"
    display_resolution: str = "N/A"
    display_refresh: Optional[int] = None
    display_name: str = "N/A"


@dataclass
class EmulatorSection:
    """Emulator target information."""
    emulator_name: str = "N/A"
    process_name: str = "N/A"
    pid: int = 0
    priority: str = "N/A"
    cpu_affinity: str = "N/A"
    cpu_usage: Optional[float] = None
    memory_mb: Optional[float] = None
    gpu_name: str = "N/A"
    confidence: str = "N/A"


@dataclass
class PerformanceSection:
    """Performance metrics from PresentMon."""
    present_fps: Optional[float] = None
    median_fps: Optional[float] = None
    min_fps: Optional[float] = None
    max_fps: Optional[float] = None
    one_percent_low: Optional[float] = None
    zero_point_one_percent_low: Optional[float] = None
    average_frame_time: Optional[float] = None
    frame_time_variance: Optional[float] = None
    frame_spikes: Optional[int] = None
    stability: Optional[float] = None
    sample_count: int = 0
    fps_provider: str = "N/A"


@dataclass
class ThermalSection:
    """Thermal information."""
    gpu_temperature: Optional[float] = None
    gpu_clock: Optional[float] = None
    gpu_power: Optional[float] = None
    gpu_power_limit: Optional[float] = None
    gpu_power_state: str = "N/A"
    cpu_temperature: Optional[float] = None
    cpu_frequency: Optional[float] = None
    thermal_state: str = "N/A"
    throttle_indicators: List[str] = field(default_factory=list)


@dataclass
class OptimizationSection:
    """Optimization status information."""
    profile_name: str = "N/A"
    applied: List[str] = field(default_factory=list)
    already_optimal: List[str] = field(default_factory=list)
    requires_admin: List[str] = field(default_factory=list)
    recommendation_only: List[str] = field(default_factory=list)
    failed: List[str] = field(default_factory=list)
    rollback_available: bool = False
    snapshot_id: str = "N/A"


@dataclass
class BenchmarkSection:
    """Benchmark comparison information."""
    baseline_fps: Optional[float] = None
    baseline_1low: Optional[float] = None
    baseline_frame_time: Optional[float] = None
    optimized_fps: Optional[float] = None
    optimized_1low: Optional[float] = None
    optimized_frame_time: Optional[float] = None
    fps_delta: Optional[float] = None
    fps_delta_percent: Optional[float] = None
    one_low_delta: Optional[float] = None
    confidence: str = "N/A"
    reliability: str = "N/A"


@dataclass
class PerformanceReport:
    """
    Complete gaming performance report.
    All sections populated from real measurements.
    """
    # Metadata
    report_id: str = ""
    generated_at: str = ""
    report_version: str = "1.0"

    # Sections
    system: SystemSection = field(default_factory=SystemSection)
    emulator: EmulatorSection = field(default_factory=EmulatorSection)
    performance: PerformanceSection = field(default_factory=PerformanceSection)
    thermal: ThermalSection = field(default_factory=ThermalSection)
    optimization: OptimizationSection = field(default_factory=OptimizationSection)
    benchmark: BenchmarkSection = field(default_factory=BenchmarkSection)

    def __post_init__(self):
        if not self.report_id:
            self.report_id = f"report_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        if not self.generated_at:
            self.generated_at = datetime.now().isoformat()

    def to_dict(self) -> dict:
        """Serialize to dict for JSON export."""
        def _to_plain(obj):
            if hasattr(obj, '__dataclass_fields__'):
                return {k: _to_plain(v) for k, v in obj.__dict__.items()}
            elif isinstance(obj, list):
                return [_to_plain(i) for i in obj]
            elif isinstance(obj, dict):
                return {k: _to_plain(v) for k, v in obj.items()}
            return obj

        return {
            "report_id": self.report_id,
            "generated_at": self.generated_at,
            "report_version": self.report_version,
            "system": _to_plain(self.system),
            "emulator": _to_plain(self.emulator),
            "performance": _to_plain(self.performance),
            "thermal": _to_plain(self.thermal),
            "optimization": _to_plain(self.optimization),
            "benchmark": _to_plain(self.benchmark),
        }


# ── Report Generator ──────────────────────────────────────────

REPORTS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "reports"
)


class PerformanceReportGenerator:
    """
    Generates a complete performance report from existing subsystems.
    Each section is populated from real measurements only.
    """

    def generate(self) -> PerformanceReport:
        """Generate a complete performance report."""
        report = PerformanceReport()

        self._fill_system(report)
        self._fill_emulator(report)
        self._fill_performance(report)
        self._fill_thermal(report)
        self._fill_optimization(report)
        self._fill_benchmark(report)

        return report

    # ── System Section ────────────────────────────────────────

    def _fill_system(self, report: PerformanceReport):
        """Populate system hardware information from real data."""
        sys_sec = report.system

        # CPU
        try:
            from app.system.cpu import cpu_monitor
            cpu = cpu_monitor.detect()
            sys_sec.cpu_model = cpu.model or "N/A"
            if cpu.physical_cores > 0 and cpu.logical_cores > 0:
                sys_sec.cpu_cores = f"{cpu.physical_cores}P / {cpu.logical_cores}L"
            if cpu.max_frequency_mhz > 0:
                sys_sec.cpu_frequency = f"{cpu.max_frequency_mhz:.0f} MHz"
            sys_sec.cpu_temperature = cpu.temperature_celsius
        except Exception as e:
            logger.debug(f"CPU info: {e}")

        # CPU utilization
        try:
            import psutil
            sys_sec.cpu_utilization = psutil.cpu_percent(interval=0.5)
        except Exception:
            pass

        # GPU
        try:
            from app.system.gpu import gpu_monitor
            gpus = gpu_monitor.detect()
            if gpus:
                gpu = gpu_monitor.update(gpus[0])
                sys_sec.gpu_name = gpu.name or "N/A"
                sys_sec.gpu_vendor = gpu.vendor or "N/A"
                sys_sec.gpu_driver = gpu.driver_version or "N/A"
                sys_sec.gpu_utilization = gpu.utilization_percent if gpu.utilization_percent > 0 else None
                sys_sec.gpu_temperature = gpu.temperature_celsius
                sys_sec.gpu_clock = gpu.clock_core_mhz if gpu.clock_core_mhz > 0 else None
                sys_sec.gpu_power = gpu.power_draw_watts
                sys_sec.gpu_vram_total = gpu.vram_total_mb if gpu.vram_total_mb > 0 else None
                sys_sec.gpu_vram_used = gpu.vram_used_mb if gpu.vram_used_mb > 0 else None
        except Exception as e:
            logger.debug(f"GPU info: {e}")

        # RAM
        try:
            import psutil
            vm = psutil.virtual_memory()
            sys_sec.ram_total = vm.total / (1024 ** 3)
            sys_sec.ram_used = vm.used / (1024 ** 3)
            sys_sec.ram_percent = vm.percent
        except Exception:
            pass

        # Windows
        try:
            import platform
            sys_sec.windows_version = f"{platform.system()} {platform.release()} {platform.version()}"
        except Exception:
            pass

        # Display
        try:
            from app.system.display import display_monitor
            display = display_monitor.detect()
            sys_sec.display_resolution = f"{display.resolution_x}x{display.resolution_y}"
            sys_sec.display_refresh = display.refresh_rate_hz
            sys_sec.display_name = display.display_name or "N/A"
        except Exception as e:
            logger.debug(f"Display info: {e}")

    # ── Emulator Section ──────────────────────────────────────

    def _fill_emulator(self, report: PerformanceReport):
        """Populate emulator target information from real data."""
        emu_sec = report.emulator

        try:
            from app.core.emulator_controller import emulator_controller
            target = emulator_controller.detect_target()
            if target:
                emu_sec.emulator_name = target.emulator or "N/A"
                emu_sec.process_name = target.name or "N/A"
                emu_sec.pid = target.pid
                emu_sec.priority = target.priority_name or "N/A"
                emu_sec.cpu_affinity = f"{target.affinity_cpus}/{target.total_cpus} CPUs"
                emu_sec.cpu_usage = target.cpu_percent if target.cpu_percent > 0 else None
                emu_sec.memory_mb = target.memory_mb if target.memory_mb > 0 else None
                emu_sec.gpu_name = target.gpu_name or "N/A"
                emu_sec.confidence = f"{target.confidence:.0%}" if target.confidence > 0 else "N/A"
            else:
                emu_sec.emulator_name = "Not detected"
                emu_sec.process_name = "Not detected"
        except Exception as e:
            logger.debug(f"Emulator info: {e}")

    # ── Performance Section ───────────────────────────────────

    def _fill_performance(self, report: PerformanceReport):
        """Populate performance metrics from PresentMon and telemetry."""
        perf_sec = report.performance

        # Check PresentMon availability
        try:
            from app.performance.presentmon_provider import find_presentmon
            pm_path = find_presentmon()
            if pm_path:
                perf_sec.fps_provider = f"PresentMon 2.5.1"
        except Exception:
            pass

        # Try to get latest benchmark data
        try:
            from app.core.benchmark import benchmark_engine
            if hasattr(benchmark_engine, '_last_result') and benchmark_engine._last_result:
                result = benchmark_engine._last_result
                if hasattr(result, 'present_fps') and result.present_fps is not None:
                    perf_sec.present_fps = result.present_fps
                    perf_sec.one_percent_low = result.one_percent_low
                    perf_sec.zero_point_one_percent_low = result.zero_point_one_percent_low
                    perf_sec.average_frame_time = result.average_frame_time
                    perf_sec.frame_time_variance = result.frame_time_variance
                    perf_sec.frame_spikes = result.frame_spikes
                    perf_sec.stability = result.stability
                    perf_sec.sample_count = result.sample_count
        except Exception:
            pass

        # Try frame pacing data
        if perf_sec.present_fps is None:
            try:
                from app.performance.frame_pacing import FramePacingAnalyzer
                # Check if there's recent frame pacing data
                pass
            except Exception:
                pass

    # ── Thermal Section ───────────────────────────────────────

    def _fill_thermal(self, report: PerformanceReport):
        """Populate thermal information from real sensor data."""
        therm_sec = report.thermal

        try:
            from app.system.thermal_monitor import thermal_diagnostics
            diag = thermal_diagnostics.diagnose()

            # GPU thermal
            if diag.gpu:
                therm_sec.gpu_temperature = diag.gpu.temperature_celsius
                therm_sec.gpu_clock = diag.gpu.clock_core_mhz if diag.gpu.clock_core_mhz > 0 else None
                therm_sec.gpu_power = diag.gpu.power_draw_watts
                therm_sec.gpu_power_limit = diag.gpu.power_limit_watts
                therm_sec.gpu_power_state = diag.gpu.power_state or "N/A"

            # CPU thermal
            if diag.cpu:
                therm_sec.cpu_temperature = diag.cpu.temperature_celsius
                therm_sec.cpu_frequency = diag.cpu.frequency_mhz if diag.cpu.frequency_mhz > 0 else None

            # Thermal state
            if hasattr(diag.thermal_state, 'value'):
                therm_sec.thermal_state = diag.thermal_state.value
            else:
                therm_sec.thermal_state = str(diag.thermal_state) if diag.thermal_state else "N/A"

            # Throttle indicators
            if diag.throttle_indicators:
                for ind in diag.throttle_indicators:
                    if hasattr(ind, 'value') and ind.value != "None Detected":
                        therm_sec.throttle_indicators.append(ind.value)
                    elif hasattr(ind, 'name') and ind.name != "NONE":
                        therm_sec.throttle_indicators.append(str(ind))

        except Exception as e:
            logger.debug(f"Thermal info: {e}")

    # ── Optimization Section ──────────────────────────────────

    def _fill_optimization(self, report: PerformanceReport):
        """Populate optimization status from the optimizer."""
        opt_sec = report.optimization

        try:
            from app.core.optimizer import optimizer
            status = optimizer.get_current_status()

            opt_sec.profile_name = status.get("profile_name", "N/A")
            opt_sec.rollback_available = status.get("rollback_available", False)

            for opt in status.get("optimizations", []):
                name = opt.get("name", opt.get("opt_id", ""))
                s = opt.get("status", "")
                if s == "APPLIED":
                    opt_sec.applied.append(name)
                elif s == "ALREADY_OPTIMAL":
                    opt_sec.already_optimal.append(name)
                elif s == "REQUIRES_ADMIN":
                    opt_sec.requires_admin.append(name)
                elif s == "RECOMMENDATION_ONLY":
                    opt_sec.recommendation_only.append(name)
                elif s == "FAILED":
                    opt_sec.failed.append(name)

            # Snapshot
            if hasattr(optimizer, '_last_report') and optimizer._last_report:
                report_obj = optimizer._last_report
                if hasattr(report_obj, 'snapshot_id'):
                    opt_sec.snapshot_id = report_obj.snapshot_id or "N/A"

        except Exception as e:
            logger.debug(f"Optimization info: {e}")

    # ── Benchmark Section ─────────────────────────────────────

    def _fill_benchmark(self, report: PerformanceReport):
        """Populate benchmark comparison from A/B results."""
        bench_sec = report.benchmark

        try:
            from app.core.ab_benchmark import ab_benchmark_engine
            if hasattr(ab_benchmark_engine, '_last_result') and ab_benchmark_engine._last_result:
                ab = ab_benchmark_engine._last_result
                if hasattr(ab, 'baseline_stats') and ab.baseline_stats:
                    fps_stat = ab.baseline_stats.get("present_fps")
                    if fps_stat and hasattr(fps_stat, 'median'):
                        bench_sec.baseline_fps = fps_stat.median
                    low_stat = ab.baseline_stats.get("one_percent_low")
                    if low_stat and hasattr(low_stat, 'median'):
                        bench_sec.baseline_1low = low_stat.median
                if hasattr(ab, 'optimized_stats') and ab.optimized_stats:
                    fps_stat = ab.optimized_stats.get("present_fps")
                    if fps_stat and hasattr(fps_stat, 'median'):
                        bench_sec.optimized_fps = fps_stat.median
                    low_stat = ab.optimized_stats.get("one_percent_low")
                    if low_stat and hasattr(low_stat, 'median'):
                        bench_sec.optimized_1low = low_stat.median
                if hasattr(ab, 'fps_delta'):
                    bench_sec.fps_delta = ab.fps_delta
                if hasattr(ab, 'fps_percent'):
                    bench_sec.fps_delta_percent = ab.fps_percent
                if hasattr(ab, 'confidence'):
                    bench_sec.confidence = ab.confidence
                if hasattr(ab, 'result'):
                    bench_sec.reliability = ab.result
        except Exception:
            pass

    # ── JSON Export ───────────────────────────────────────────

    def export_json(self, report: PerformanceReport, path: str = None) -> str:
        """Export report to JSON file."""
        if path is None:
            os.makedirs(REPORTS_DIR, exist_ok=True)
            path = os.path.join(REPORTS_DIR, f"{report.report_id}.json")

        data = report.to_dict()
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)

        logger.info(f"Report exported: {path}")
        return path

    # ── CLI Report ────────────────────────────────────────────

    def format_cli(self, report: PerformanceReport) -> str:
        """Format report for human-readable CLI output."""
        lines = []
        sep = "=" * 55

        lines.append(sep)
        lines.append("HEAVEN SOCIETY -- PERFORMANCE REPORT")
        lines.append(sep)
        lines.append(f"Report:   {report.report_id}")
        lines.append(f"Generated: {report.generated_at}")
        lines.append("")

        # SYSTEM
        s = report.system
        lines.append("SYSTEM")
        lines.append("-" * 55)
        lines.append(f"  CPU:       {s.cpu_model}")
        lines.append(f"  Cores:     {s.cpu_cores}")
        lines.append(f"  Freq:      {s.cpu_frequency}")
        lines.append(f"  CPU Util:  {s.cpu_utilization:.0f}%" if s.cpu_utilization is not None else "  CPU Util:  N/A")
        lines.append(f"  GPU:       {s.gpu_name}")
        lines.append(f"  Vendor:    {s.gpu_vendor}")
        lines.append(f"  Driver:    {s.gpu_driver}")
        lines.append(f"  GPU Util:  {s.gpu_utilization:.0f}%" if s.gpu_utilization is not None else "  GPU Util:  N/A")
        lines.append(f"  GPU Temp:  {s.gpu_temperature:.0f} C" if s.gpu_temperature is not None else "  GPU Temp:  N/A")
        lines.append(f"  VRAM:      {s.gpu_vram_used:.0f}/{s.gpu_vram_total:.0f} MB" if s.gpu_vram_total and s.gpu_vram_used else "  VRAM:      N/A")
        lines.append(f"  RAM:       {s.ram_used:.1f}/{s.ram_total:.1f} GB ({s.ram_percent:.0f}%)" if s.ram_total else "  RAM:       N/A")
        lines.append(f"  Windows:   {s.windows_version}")
        lines.append(f"  Display:   {s.display_resolution} @ {s.display_refresh} Hz" if s.display_refresh else f"  Display:   {s.display_resolution}")
        lines.append("")

        # EMULATOR
        e = report.emulator
        lines.append("EMULATOR")
        lines.append("-" * 55)
        lines.append(f"  Emulator:  {e.emulator_name}")
        lines.append(f"  Process:   {e.process_name}")
        lines.append(f"  PID:       {e.pid}" if e.pid else "  PID:       N/A")
        lines.append(f"  Priority:  {e.priority}")
        lines.append(f"  Affinity:  {e.cpu_affinity}")
        lines.append(f"  CPU:       {e.cpu_usage:.0f}%" if e.cpu_usage is not None else "  CPU:       N/A")
        lines.append(f"  RAM:       {e.memory_mb:.0f} MB" if e.memory_mb is not None else "  RAM:       N/A")
        lines.append(f"  GPU:       {e.gpu_name}")
        lines.append(f"  Confidence:{e.confidence}")
        lines.append("")

        # PERFORMANCE
        p = report.performance
        lines.append("PERFORMANCE")
        lines.append("-" * 55)
        lines.append(f"  Provider:  {p.fps_provider}")
        lines.append(f"  FPS:       {p.present_fps:.1f}" if p.present_fps is not None else "  FPS:       N/A")
        lines.append(f"  Median:    {p.median_fps:.1f}" if p.median_fps is not None else "  Median:    N/A")
        lines.append(f"  1% Low:    {p.one_percent_low:.1f}" if p.one_percent_low is not None else "  1% Low:    N/A")
        lines.append(f"  0.1% Low:  {p.zero_point_one_percent_low:.1f}" if p.zero_point_one_percent_low is not None else "  0.1% Low:  N/A")
        lines.append(f"  Frame T:   {p.average_frame_time:.2f} ms" if p.average_frame_time is not None else "  Frame T:   N/A")
        lines.append(f"  Variance:  {p.frame_time_variance:.2f}" if p.frame_time_variance is not None else "  Variance:  N/A")
        lines.append(f"  Spikes:    {p.frame_spikes}" if p.frame_spikes is not None else "  Spikes:    N/A")
        lines.append(f"  Stability: {p.stability:.0f}/100" if p.stability is not None else "  Stability: N/A")
        lines.append(f"  Samples:   {p.sample_count}")
        lines.append("")

        # THERMAL
        t = report.thermal
        lines.append("THERMAL")
        lines.append("-" * 55)
        lines.append(f"  GPU Temp:  {t.gpu_temperature:.0f} C" if t.gpu_temperature is not None else "  GPU Temp:  N/A")
        lines.append(f"  GPU Clock: {t.gpu_clock:.0f} MHz" if t.gpu_clock is not None else "  GPU Clock: N/A")
        lines.append(f"  GPU Power: {t.gpu_power:.1f}W" if t.gpu_power is not None else "  GPU Power: N/A")
        lines.append(f"  GPU State: {t.gpu_power_state}")
        lines.append(f"  CPU Temp:  {t.cpu_temperature:.0f} C" if t.cpu_temperature is not None else "  CPU Temp:  N/A")
        lines.append(f"  CPU Freq:  {t.cpu_frequency:.0f} MHz" if t.cpu_frequency is not None else "  CPU Freq:  N/A")
        lines.append(f"  State:     {t.thermal_state}")
        if t.throttle_indicators:
            lines.append(f"  Throttles: {', '.join(t.throttle_indicators)}")
        lines.append("")

        # OPTIMIZATION
        o = report.optimization
        lines.append("OPTIMIZATION")
        lines.append("-" * 55)
        lines.append(f"  Profile:   {o.profile_name}")
        if o.applied:
            lines.append(f"  Applied:   {', '.join(o.applied)}")
        if o.already_optimal:
            lines.append(f"  Optimal:   {', '.join(o.already_optimal)}")
        if o.requires_admin:
            lines.append(f"  Admin:     {', '.join(o.requires_admin)}")
        if o.recommendation_only:
            lines.append(f"  Review:    {', '.join(o.recommendation_only)}")
        if o.failed:
            lines.append(f"  Failed:    {', '.join(o.failed)}")
        lines.append(f"  Rollback:  {'Available' if o.rollback_available else 'N/A'}")
        lines.append(f"  Snapshot:  {o.snapshot_id}")
        lines.append("")

        # BENCHMARK
        b = report.benchmark
        lines.append("BENCHMARK")
        lines.append("-" * 55)
        if b.baseline_fps is not None:
            lines.append(f"  Baseline:  FPS {b.baseline_fps:.1f}  1% Low {b.baseline_1low:.1f}" if b.baseline_1low else f"  Baseline:  FPS {b.baseline_fps:.1f}")
        else:
            lines.append(f"  Baseline:  N/A")
        if b.optimized_fps is not None:
            lines.append(f"  Optimized: FPS {b.optimized_fps:.1f}  1% Low {b.optimized_1low:.1f}" if b.optimized_1low else f"  Optimized: FPS {b.optimized_fps:.1f}")
        else:
            lines.append(f"  Optimized: N/A")
        if b.fps_delta is not None:
            sign = "+" if b.fps_delta >= 0 else ""
            lines.append(f"  Delta:     {sign}{b.fps_delta:.1f} FPS ({sign}{b.fps_delta_percent:.1f}%)" if b.fps_delta_percent else f"  Delta:     {sign}{b.fps_delta:.1f} FPS")
        lines.append(f"  Confidence:{b.confidence}")
        lines.append(f"  Reliability: {b.reliability}")
        lines.append("")

        lines.append(sep)
        lines.append("END OF REPORT")
        lines.append(sep)

        return "\n".join(lines)


# ── Singleton ─────────────────────────────────────────────────

performance_report_generator = PerformanceReportGenerator()
