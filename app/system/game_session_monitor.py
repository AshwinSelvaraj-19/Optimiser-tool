"""
Game Session Monitor — Read-only game/emulator session resource monitoring.

Provides:
- Before/during/after session snapshots
- Real-time CPU, RAM, GPU, emulator metrics
- PresentMon FPS integration (when available)
- Resource delta calculation
- Evidence-based bottleneck recommendations

All operations are READ-ONLY. Never terminates processes.
Never modifies system settings.
"""

import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from enum import Enum

import psutil

from app.utils.logger import get_logger

logger = get_logger("system.game_session_monitor")


# ── Bottleneck Classification ──────────────────────────────────

class BottleneckType(Enum):
    """Detected system bottleneck."""
    CPU_BOUND = "CPU_BOUND"
    GPU_BOUND = "GPU_BOUND"
    MEMORY_PRESSURE = "MEMORY_PRESSURE"
    FRAME_TIME_LIMITED = "FRAME_TIME_LIMITED"
    NO_CLEAR_BOTTLENECK = "NO_CLEAR_BOTTLENECK"
    UNKNOWN = "UNKNOWN"


# ── Data Models ────────────────────────────────────────────────

@dataclass
class SessionSnapshot:
    """A point-in-time snapshot of system + emulator state."""
    timestamp: float = 0.0
    phase: str = ""  # "BEFORE", "DURING", "AFTER"

    # System metrics (MEASURED via psutil)
    cpu_percent: float = 0.0
    ram_total_gb: float = 0.0
    ram_used_gb: float = 0.0
    ram_available_gb: float = 0.0
    ram_percent: float = 0.0
    swap_percent: float = 0.0

    # GPU metrics (MEASURED via NVML when available)
    gpu_utilization: Optional[float] = None
    gpu_temperature: Optional[float] = None
    gpu_vram_used_mb: Optional[float] = None
    gpu_vram_total_mb: Optional[float] = None
    gpu_power_watts: Optional[float] = None

    # Display
    display_refresh_hz: int = 0

    # Emulator (MEASURED via psutil)
    emulator_name: str = ""
    emulator_pid: int = 0
    emulator_cpu_percent: float = 0.0
    emulator_rss_mb: float = 0.0
    emulator_threads: int = 0

    # FPS (MEASURED via PresentMon when available)
    present_fps: Optional[float] = None
    fps_1_low: Optional[float] = None
    fps_01_low: Optional[float] = None
    frame_time_ms: Optional[float] = None
    frame_spikes: Optional[int] = None
    stability: Optional[float] = None

    @property
    def ram_headroom_gb(self) -> float:
        return self.ram_available_gb

    def to_dict(self) -> dict:
        """Serialize to dict for storage."""
        return {k: v for k, v in self.__dict__.items() if v is not None}


@dataclass
class SessionDelta:
    """Calculated delta between two snapshots."""
    available_ram_delta_gb: float = 0.0
    used_ram_delta_gb: float = 0.0
    cpu_delta: float = 0.0
    gpu_delta: Optional[float] = None
    emulator_cpu_delta: float = 0.0
    emulator_rss_delta_mb: float = 0.0
    fps_delta: Optional[float] = None
    pressure_changed: bool = False


@dataclass
class ResourceRecommendation:
    """An evidence-based resource recommendation."""
    category: str = ""  # CPU, RAM, GPU, EMULATOR
    priority: str = ""  # HIGH, MEDIUM, LOW
    title: str = ""
    description: str = ""
    reason: str = ""
    measured_evidence: str = ""
    expected_effect: str = ""


@dataclass
class GameSessionReport:
    """Complete game session monitoring report."""
    target_name: str = ""
    target_pid: int = 0
    before: Optional[SessionSnapshot] = None
    during: Optional[SessionSnapshot] = None
    after: Optional[SessionSnapshot] = None
    delta_before_during: Optional[SessionDelta] = None
    delta_during_after: Optional[SessionDelta] = None
    bottleneck: BottleneckType = BottleneckType.UNKNOWN
    bottleneck_confidence: float = 0.0
    bottleneck_reason: str = ""
    recommendations: List[ResourceRecommendation] = field(default_factory=list)
    duration_seconds: float = 0.0
    timestamp: float = 0.0


# ── Core Monitor ───────────────────────────────────────────────

class GameSessionMonitor:
    """
    Read-only game/emulator session monitor.
    Captures before/during/after snapshots and provides recommendations.
    """

    def __init__(self):
        self._snapshots: List[SessionSnapshot] = []

    def capture_snapshot(self, phase: str = "DURING") -> SessionSnapshot:
        """Capture a point-in-time system + emulator snapshot."""
        snap = SessionSnapshot(timestamp=time.time(), phase=phase)

        # System metrics
        self._capture_system_metrics(snap)

        # GPU metrics
        self._capture_gpu_metrics(snap)

        # Display
        self._capture_display(snap)

        # Emulator
        self._capture_emulator(snap)

        # FPS from PresentMon if available
        self._capture_fps(snap)

        self._snapshots.append(snap)

        logger.debug(
            f"[SESSION] Snapshot {phase}: CPU={snap.cpu_percent:.0f}% "
            f"RAM={snap.ram_used_gb:.1f}/{snap.ram_total_gb:.1f}GB "
            f"GPU={'%.0f%%' % snap.gpu_utilization if snap.gpu_utilization is not None else 'N/A'}"
        )

        return snap

    def calculate_delta(self, before: SessionSnapshot, after: SessionSnapshot) -> SessionDelta:
        """Calculate delta between two snapshots."""
        delta = SessionDelta(
            available_ram_delta_gb=after.ram_available_gb - before.ram_available_gb,
            used_ram_delta_gb=after.ram_used_gb - before.ram_used_gb,
            cpu_delta=after.cpu_percent - before.cpu_percent,
            emulator_cpu_delta=after.emulator_cpu_percent - before.emulator_cpu_percent,
            emulator_rss_delta_mb=after.emulator_rss_mb - before.emulator_rss_mb,
        )

        if before.gpu_utilization is not None and after.gpu_utilization is not None:
            delta.gpu_delta = after.gpu_utilization - before.gpu_utilization

        if before.present_fps is not None and after.present_fps is not None:
            delta.fps_delta = after.present_fps - before.present_fps

        return delta

    def analyze_bottleneck(
        self,
        snapshot: SessionSnapshot,
        cpu_pressure: float = 0.0,
        gpu_pressure: float = 0.0,
        memory_pressure: str = "NORMAL",
    ) -> tuple:
        """
        Classify the current bottleneck based on measured metrics.
        Returns (BottleneckType, confidence, reason).
        """
        evidence = []

        # GPU-bound: high GPU utilization
        if snapshot.gpu_utilization is not None and snapshot.gpu_utilization > 90:
            evidence.append(f"GPU utilization {snapshot.gpu_utilization:.0f}%")

        # CPU-bound: high CPU + low GPU
        if snapshot.cpu_percent > 85:
            evidence.append(f"CPU utilization {snapshot.cpu_percent:.0f}%")
        if (snapshot.gpu_utilization is not None and snapshot.gpu_utilization < 50
                and snapshot.cpu_percent > 70):
            evidence.append("High CPU + low GPU = likely CPU-bound")

        # Memory pressure
        if memory_pressure in ("HIGH", "CRITICAL"):
            evidence.append(f"Memory pressure: {memory_pressure}")
        if snapshot.ram_percent > 85:
            evidence.append(f"RAM usage {snapshot.ram_percent:.0f}%")

        # Frame time issues
        if snapshot.frame_spikes is not None and snapshot.frame_spikes > 20:
            evidence.append(f"Frame spikes: {snapshot.frame_spikes}")
        if snapshot.stability is not None and snapshot.stability < 60:
            evidence.append(f"Frame stability: {snapshot.stability:.0f}/100")

        # Classify
        if not evidence:
            return BottleneckType.NO_CLEAR_BOTTLENECK, 30.0, "No significant resource bottleneck detected"

        # Determine primary bottleneck
        if (snapshot.gpu_utilization is not None and snapshot.gpu_utilization > 90
                and snapshot.cpu_percent < 80):
            return BottleneckType.GPU_BOUND, 75.0, "; ".join(evidence)

        if snapshot.cpu_percent > 85 and (snapshot.gpu_utilization is None or snapshot.gpu_utilization < 60):
            return BottleneckType.CPU_BOUND, 70.0, "; ".join(evidence)

        if memory_pressure in ("HIGH", "CRITICAL") or snapshot.ram_percent > 85:
            return BottleneckType.MEMORY_PRESSURE, 65.0, "; ".join(evidence)

        if snapshot.frame_spikes is not None and snapshot.frame_spikes > 20:
            return BottleneckType.FRAME_TIME_LIMITED, 60.0, "; ".join(evidence)

        return BottleneckType.NO_CLEAR_BOTTLENECK, 40.0, "; ".join(evidence)

    def generate_recommendations(
        self,
        snapshot: SessionSnapshot,
        bottleneck: BottleneckType,
        bottleneck_reason: str,
        memory_pressure: str = "NORMAL",
    ) -> List[ResourceRecommendation]:
        """Generate evidence-based recommendations from measured data."""
        recs = []

        if bottleneck == BottleneckType.MEMORY_PRESSURE:
            recs.append(ResourceRecommendation(
                category="RAM",
                priority="HIGH",
                title="High memory usage detected",
                description=(
                    f"System RAM at {snapshot.ram_percent:.0f}% with "
                    f"{snapshot.ram_available_gb:.1f}GB available."
                ),
                reason="Limited RAM headroom may cause stuttering during heavy game scenes.",
                measured_evidence=f"RAM: {snapshot.ram_used_gb:.1f}/{snapshot.ram_total_gb:.1f}GB ({snapshot.ram_percent:.0f}%)",
                expected_effect="Frees RAM for emulator — may reduce stuttering",
            ))

            # Find optional processes consuming memory
            optional_mb = self._find_optional_process_memory()
            if optional_mb > 200:
                recs.append(ResourceRecommendation(
                    category="RAM",
                    priority="MEDIUM",
                    title=f"Optional processes using {optional_mb:.0f}MB",
                    description="Background applications consuming significant RAM.",
                    reason="Closing optional apps frees RAM for the emulator.",
                    measured_evidence=f"Optional process RAM: {optional_mb:.0f}MB",
                    expected_effect=f"Frees ~{optional_mb:.0f}MB for gaming",
                ))

        if bottleneck == BottleneckType.CPU_BOUND:
            recs.append(ResourceRecommendation(
                category="CPU",
                priority="MEDIUM",
                title="High CPU utilization",
                description=f"CPU at {snapshot.cpu_percent:.0f}% — emulator may be CPU-limited.",
                reason="High CPU load can cause frame drops and input lag.",
                measured_evidence=f"CPU: {snapshot.cpu_percent:.0f}%",
                expected_effect="Reduced CPU contention may improve frame consistency",
            ))

        if bottleneck == BottleneckType.GPU_BOUND:
            recs.append(ResourceRecommendation(
                category="GPU",
                priority="MEDIUM",
                title="GPU saturation detected",
                description=f"GPU at {snapshot.gpu_utilization:.0f}% — graphics-limited.",
                reason="GPU is the primary bottleneck — consider reducing graphics settings in-game.",
                measured_evidence=f"GPU: {snapshot.gpu_utilization:.0f}%",
                expected_effect="Lower in-game graphics settings may improve FPS",
            ))

        if snapshot.emulator_rss_mb > snapshot.ram_total_gb * 1024 * 0.4:
            recs.append(ResourceRecommendation(
                category="EMULATOR",
                priority="MEDIUM",
                title="Emulator using significant RAM",
                description=f"Emulator using {snapshot.emulator_rss_mb:.0f}MB ({snapshot.emulator_rss_mb / (snapshot.ram_total_gb * 1024) * 100:.0f}% of system RAM).",
                reason="High emulator memory may indicate configuration issues.",
                measured_evidence=f"Emulator RSS: {snapshot.emulator_rss_mb:.0f}MB",
                expected_effect="Emulator memory optimization may help",
            ))

        if not recs:
            recs.append(ResourceRecommendation(
                category="SYSTEM",
                priority="LOW",
                title="No clear bottleneck",
                description="System resources appear adequate for gaming.",
                reason="No significant resource pressure detected.",
                measured_evidence=f"CPU: {snapshot.cpu_percent:.0f}%, RAM: {snapshot.ram_percent:.0f}%, GPU: {'%.0f%%' % snapshot.gpu_utilization if snapshot.gpu_utilization is not None else 'N/A'}",
                expected_effect="System is within normal operating parameters",
            ))

        return recs

    def create_report(
        self,
        target_name: str = "",
        target_pid: int = 0,
        memory_pressure: str = "NORMAL",
    ) -> GameSessionReport:
        """Create a complete session report with before/during/after snapshots."""
        report = GameSessionReport(
            target_name=target_name,
            target_pid=target_pid,
            timestamp=time.time(),
        )

        # Capture before snapshot
        report.before = self.capture_snapshot("BEFORE")

        # For a quick status, we only capture before
        # For a full session, during/after would be captured separately

        # Analyze bottleneck
        report.bottleneck, report.bottleneck_confidence, report.bottleneck_reason = \
            self.analyze_bottleneck(report.before, memory_pressure=memory_pressure)

        # Generate recommendations
        report.recommendations = self.generate_recommendations(
            report.before, report.bottleneck, report.bottleneck_reason, memory_pressure
        )

        return report

    # ── Internal Capture Methods ───────────────────────────────

    def _capture_system_metrics(self, snap: SessionSnapshot):
        """Capture system CPU and RAM metrics."""
        try:
            snap.cpu_percent = psutil.cpu_percent(interval=0.1)
        except Exception:
            pass

        try:
            vm = psutil.virtual_memory()
            snap.ram_total_gb = vm.total / (1024 ** 3)
            snap.ram_used_gb = vm.used / (1024 ** 3)
            snap.ram_available_gb = vm.available / (1024 ** 3)
            snap.ram_percent = vm.percent
        except Exception:
            pass

        try:
            swap = psutil.swap_memory()
            snap.swap_percent = swap.percent
        except Exception:
            pass

    def _capture_gpu_metrics(self, snap: SessionSnapshot):
        """Capture GPU metrics via NVML when available."""
        try:
            import pynvml
            pynvml.nvmlInit()
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(0)

                # Utilization
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    snap.gpu_utilization = util.gpu
                except Exception:
                    pass

                # Temperature
                try:
                    snap.gpu_temperature = pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU)
                except Exception:
                    pass

                # VRAM
                try:
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    snap.gpu_vram_used_mb = mem.used / (1024 * 1024)
                    snap.gpu_vram_total_mb = mem.total / (1024 * 1024)
                except Exception:
                    pass

                # Power
                try:
                    snap.gpu_power_watts = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
                except Exception:
                    pass

            finally:
                pynvml.nvmlShutdown()
        except (ImportError, Exception):
            pass

    def _capture_display(self, snap: SessionSnapshot):
        """Capture display refresh rate."""
        try:
            from app.system.display import display_monitor
            disp = display_monitor.detect()
            snap.display_refresh_hz = getattr(disp, "refresh_rate_hz", 0) or 0
        except Exception:
            pass

    def _capture_emulator(self, snap: SessionSnapshot):
        """Capture emulator process metrics."""
        try:
            from app.performance.target_process import target_process_detector
            best = target_process_detector.select_best_target()
            if best:
                snap.emulator_name = best.process_name or ""
                snap.emulator_pid = best.pid or 0

                if snap.emulator_pid:
                    proc = psutil.Process(snap.emulator_pid)
                    snap.emulator_cpu_percent = proc.cpu_percent(interval=0.1)
                    mem = proc.memory_info()
                    snap.emulator_rss_mb = mem.rss / (1024 * 1024)
                    snap.emulator_threads = proc.num_threads()
        except (psutil.NoSuchProcess, psutil.AccessDenied, Exception):
            pass

    def _capture_fps(self, snap: SessionSnapshot):
        """Capture FPS from PresentMon if available."""
        try:
            from app.performance.presentmon_provider import PresentMonProvider
            provider = PresentMonProvider()
            if provider.is_running:
                sample = provider.get_latest_sample()
                if sample:
                    snap.present_fps = getattr(sample, "present_fps", None)
                    snap.fps_1_low = getattr(sample, "one_percent_low", None)
                    snap.frame_time_ms = getattr(sample, "average_frame_time_ms", None)
        except Exception:
            pass

    def _find_optional_process_memory(self) -> float:
        """Find total RAM used by optional user applications."""
        optional_names = {
            "onedrive.exe", "dropbox.exe", "discord.exe", "spotify.exe",
            "teams.exe", "slack.exe", "zoom.exe", "chrome.exe", "firefox.exe",
            "msedge.exe", "steam.exe", "epicgameslauncher.exe",
        }
        total_mb = 0.0
        try:
            for proc in psutil.process_iter(["name", "memory_info"]):
                try:
                    p = proc.info
                    name = (p.get("name") or "").lower()
                    if name in optional_names:
                        mem = p.get("memory_info")
                        if mem:
                            total_mb += mem.rss / (1024 * 1024)
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass
        return total_mb

    def clear_snapshots(self):
        """Clear all stored snapshots."""
        self._snapshots.clear()


# Singleton
game_session_monitor = GameSessionMonitor()
