"""
Background worker for OptimizerPage.

All expensive diagnostics run in a QThread; results are delivered via
signals.  A guard prevents overlapping jobs.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, Any, Dict, List, Tuple

from PySide6.QtCore import QObject, Signal, QThread


# ── result containers ─────────────────────────────────────────────

@dataclass
class OptimizerWorkerResult:
    """All data the GUI needs, computed off-thread."""
    # timing
    elapsed_ms: float = 0.0

    # status (from optimizer.get_current_status)
    opt_status: Optional[dict] = None

    # windows gaming
    win_gaming: Optional[Any] = None

    # resource analysis
    resource: Optional[Any] = None

    # background load
    background: Optional[Any] = None

    # memory
    memory: Optional[Any] = None
    safe_closeable: Optional[list] = None

    # startup
    startup: Optional[Any] = None
    startup_optional_ram: float = 0.0

    # telemetry frame
    telemetry_frame: Optional[Any] = None

    # GPU info dict
    gpu_info: Dict[str, Any] = field(default_factory=dict)

    # emulator target
    target: Optional[Any] = None

    # recommendations
    rec_session: Optional[Any] = None
    rec_bottleneck: str = ""
    rec_confidence: int = 0

    # adaptive
    adaptive_state: Optional[Any] = None
    adaptive_confidence: int = 0
    adaptive_evidence: Optional[list] = None
    adaptive_plan: Optional[Any] = None

    # input
    input_session: Optional[Any] = None
    gameplay: Optional[Any] = None

    # responsiveness
    responsiveness: Optional[Any] = None

    # hardware profile (collected in worker, NOT on GUI thread)
    hw_profile: Optional[Any] = None

    # optimization engine summary (collected in worker, NOT on GUI thread)
    engine_summary: Optional[Dict[str, Any]] = None


# ── worker QObject (runs in QThread) ──────────────────────────────

class _OptimizerWorker(QObject):
    """Performs expensive diagnostics in a background thread."""

    finished = Signal(object)   # OptimizerWorkerResult
    error = Signal(str)

    def do_work(self):
        t0 = time.perf_counter()
        result = OptimizerWorkerResult()
        try:
            self._collect(result)
        except Exception as exc:
            self.error.emit(str(exc))
            return
        result.elapsed_ms = (time.perf_counter() - t0) * 1000
        self.finished.emit(result)

    # ── collection helpers ─────────────────────────────────────

    def _collect(self, r: OptimizerWorkerResult):
        from app.core.telemetry import telemetry_engine
        from app.core.optimizer import optimizer
        from app.core.emulator_controller import emulator_controller

        # 1. Telemetry snapshot (free — from background engine)
        r.telemetry_frame = telemetry_engine.current

        # 2. Emulator target (one scan)
        r.target = emulator_controller.detect_target()
        t_pid = r.target.pid if r.target else 0
        t_name = r.target.name if r.target else ""

        # 3. Optimizer status
        r.opt_status = optimizer.get_current_status()

        # 4. GPU info (fast NVML read)
        self._collect_gpu(r)

        # 5. Windows gaming (~2.6s, WMI)
        self._collect_windows_gaming(r, t_name, t_pid)

        # 6. Background analysis (~1.4s, psutil process_iter)
        self._collect_background(r, t_pid, t_name)

        # 7. Memory analysis (~1.0s)
        self._collect_memory(r, t_pid, t_name)

        # 8. Startup analysis (fast analyze, 0.3s optional RAM)
        self._collect_startup(r)

        # 9. Resource analysis (reuse GPU info + telemetry)
        self._collect_resource(r, t_pid, t_name)

        # 10. Recommendations
        self._collect_recommendations(r, t_pid, t_name)

        # 11. Adaptive status
        self._collect_adaptive(r, t_pid, t_name)

        # 12. Input diagnostics (~1.8s)
        self._collect_input(r, t_pid, t_name)

        # 13. Responsiveness
        self._collect_responsiveness(r, t_pid, t_name)

        # 14. Hardware profile (slow ~1.5s — MUST be collected in worker)
        self._collect_hw_profile(r)

        # 15. Optimization engine summary (slow ~1.7s — MUST be collected in worker)
        self._collect_engine_summary(r)

    def _collect_gpu(self, r: OptimizerWorkerResult):
        try:
            from app.system.gpu import gpu_monitor
            gpus = gpu_monitor.detect()
            if gpus:
                gpu = gpus[0]
                if gpu.vendor == "NVIDIA":
                    gpu = gpu_monitor.update_nvidia(gpu)
                r.gpu_info = {
                    "vram_total_mb": gpu.vram_total_mb,
                    "vram_used_mb": gpu.vram_used_mb,
                    "utilization": gpu.utilization_gpu,
                }
        except Exception:
            pass

    def _collect_windows_gaming(self, r, t_name, t_pid):
        try:
            from app.system.windows_gaming import windows_gaming_analyzer
            r.win_gaming = windows_gaming_analyzer.analyze(t_name, t_pid)
        except Exception:
            pass

    def _collect_background(self, r, t_pid, t_name):
        try:
            from app.system.background_analyzer import background_analyzer
            r.background = background_analyzer.analyze(
                emulator_pid=t_pid, emulator_name=t_name,
            )
        except Exception:
            pass

    def _collect_memory(self, r, t_pid, t_name):
        try:
            from app.system.memory_optimizer import memory_optimizer
            r.memory = memory_optimizer.analyze(
                emulator_pid=t_pid, emulator_name=t_name,
            )
            r.safe_closeable = memory_optimizer.get_safe_closeable_processes(
                emulator_pid=t_pid,
            )
        except Exception:
            pass

    def _collect_startup(self, r):
        try:
            from app.system.startup_analyzer import startup_analyzer
            r.startup = startup_analyzer.analyze()
            r.startup_optional_ram = startup_analyzer.get_ram_usage_of_optional()
        except Exception:
            pass

    def _collect_resource(self, r, t_pid, t_name):
        try:
            from app.core.resource_analyzer import resource_analyzer
            r.resource = resource_analyzer.analyze(
                emulator_pid=t_pid,
                emulator_name=t_name,
                telemetry_frame=r.telemetry_frame,
                gpu_info=r.gpu_info,
            )
        except Exception:
            pass

    def _collect_recommendations(self, r, t_pid, t_name):
        try:
            from app.core.recommendation_engine import recommendation_engine
            from app.performance.telemetry_models import (
                TelemetrySample, BottleneckType,
            )
            frame = r.telemetry_frame
            states = {}
            if r.opt_status:
                for o in r.opt_status.get("optimizations", []):
                    states[o["id"]] = o.get("status", "UNKNOWN")

            samples = []
            if frame and frame.timestamp > 0:
                samples.append(TelemetrySample(
                    timestamp=frame.timestamp,
                    emulator_pid=t_pid,
                    emulator_name=t_name,
                    cpu_total_percent=frame.cpu_utilization,
                    gpu_utilization_percent=frame.gpu_utilization,
                    system_ram_used_mb=frame.ram_used_mb,
                    system_ram_total_mb=frame.ram_total_mb,
                    system_ram_available_mb=(
                        frame.ram_total_mb - frame.ram_used_mb
                        if frame.ram_total_mb else None
                    ),
                ))

            bottleneck = BottleneckType.INSUFFICIENT_DATA
            bn_confidence = 0
            if frame:
                if frame.thermal_status == "THROTTLING":
                    bottleneck = BottleneckType.THERMAL_LIMITED
                    bn_confidence = 70
                elif frame.cpu_utilization > 85:
                    bottleneck = BottleneckType.CPU_BOUND
                    bn_confidence = 60
                elif frame.gpu_utilization > 90:
                    bottleneck = BottleneckType.GPU_BOUND
                    bn_confidence = 60
                elif frame.ram_percent > 85:
                    bottleneck = BottleneckType.MEMORY_BOUND
                    bn_confidence = 60
                else:
                    bottleneck = BottleneckType.NO_CLEAR_BOTTLENECK
                    bn_confidence = 40

            r.rec_session = recommendation_engine.analyze(
                samples=samples,
                bottleneck_type=bottleneck,
                bottleneck_confidence=bn_confidence,
                optimization_states=states,
                target_name=t_name,
                target_pid=t_pid,
            )
            r.rec_bottleneck = bottleneck
            r.rec_confidence = bn_confidence
        except Exception:
            pass

    def _collect_adaptive(self, r, t_pid, t_name):
        try:
            from app.core.adaptive_optimizer import adaptive_optimizer
            from app.performance.telemetry_models import TelemetrySample
            frame = r.telemetry_frame
            states = {}
            if r.opt_status:
                states = {
                    o["id"]: o.get("status", "UNKNOWN")
                    for o in r.opt_status.get("optimizations", [])
                }
            samples = []
            if frame and frame.timestamp > 0:
                samples.append(TelemetrySample(
                    timestamp=frame.timestamp,
                    emulator_pid=t_pid,
                    emulator_name=t_name,
                    cpu_total_percent=frame.cpu_utilization,
                    gpu_utilization_percent=frame.gpu_utilization,
                    system_ram_used_mb=frame.ram_used_mb,
                    system_ram_total_mb=frame.ram_total_mb,
                    system_ram_available_mb=(
                        frame.ram_total_mb - frame.ram_used_mb
                        if frame.ram_total_mb else None
                    ),
                ))
            state, conf, evidence = adaptive_optimizer.classify_state(samples)
            r.adaptive_state = state
            r.adaptive_confidence = conf
            r.adaptive_evidence = evidence
            r.adaptive_plan = adaptive_optimizer.generate_plan(
                samples=samples, state=state, state_confidence=conf,
                state_evidence=evidence, optimization_states=states,
                target_name=t_name, target_pid=t_pid,
            )
        except Exception:
            pass

    def _collect_input(self, r, t_pid, t_name):
        try:
            from app.input.input_diagnostics import run_input_diagnostics
            from app.input.gameplay_diagnostics import run_gameplay_diagnostics
            from app.performance.telemetry_models import TelemetrySample

            frame = r.telemetry_frame
            samples = []
            if frame and frame.timestamp > 0:
                samples.append(TelemetrySample(
                    timestamp=frame.timestamp,
                    emulator_pid=t_pid,
                    emulator_name=t_name,
                    cpu_total_percent=frame.cpu_utilization,
                    gpu_utilization_percent=frame.gpu_utilization,
                    system_ram_used_mb=frame.ram_used_mb,
                    system_ram_total_mb=frame.ram_total_mb,
                    system_ram_available_mb=(
                        frame.ram_total_mb - frame.ram_used_mb
                        if frame.ram_total_mb else None
                    ),
                ))
            r.input_session = run_input_diagnostics(
                target_name=t_name, target_pid=t_pid,
            )
            r.gameplay = run_gameplay_diagnostics(
                samples=samples,
                input_session=r.input_session,
                target_name=t_name,
                target_pid=t_pid,
            )
        except Exception:
            pass

    def _collect_responsiveness(self, r, t_pid, t_name):
        try:
            from app.input.responsiveness_analyzer import analyze_responsiveness
            from app.performance.telemetry_models import TelemetrySample

            frame = r.telemetry_frame
            samples = []
            if frame and frame.timestamp > 0:
                samples.append(TelemetrySample(
                    timestamp=frame.timestamp,
                    emulator_pid=t_pid,
                    emulator_name=t_name,
                    cpu_total_percent=frame.cpu_utilization,
                    gpu_utilization_percent=frame.gpu_utilization,
                    system_ram_used_mb=frame.ram_used_mb,
                    system_ram_total_mb=frame.ram_total_mb,
                    system_ram_available_mb=(
                        frame.ram_total_mb - frame.ram_used_mb
                        if frame.ram_total_mb else None
                    ),
                ))
            input_sess = r.input_session
            if input_sess is None:
                from app.input.input_diagnostics import run_input_diagnostics
                input_sess = run_input_diagnostics(
                    target_name=t_name, target_pid=t_pid,
                )
            r.responsiveness = analyze_responsiveness(
                samples=samples,
                input_session=input_sess,
                target_name=t_name,
                target_pid=t_pid,
            )
        except Exception:
            pass


    def _collect_hw_profile(self, r):
        """Collect hardware profile (slow ~1.5s — safe in worker thread)."""
        try:
            from app.core.hardware_profile import analyze_hardware_profile
            r.hw_profile = analyze_hardware_profile()
        except Exception:
            pass

    def _collect_engine_summary(self, r):
        """Collect optimization engine summary (slow ~1.7s — safe in worker thread)."""
        try:
            from app.core.optimization_engine import optimization_engine
            r.engine_summary = optimization_engine.get_ui_summary()
        except Exception:
            pass


# ── threaded runner ────────────────────────────────────────────────

class OptimizerWorkerThread(QThread):
    """Manages the worker lifecycle from the GUI thread."""

    finished = Signal(object)
    error = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._worker = _OptimizerWorker()
        self._worker.moveToThread(self)
        self._worker.finished.connect(self.finished)
        self._worker.error.connect(self.error)
        self.started.connect(self._worker.do_work)
        self.setObjectName("optimizer_worker")
