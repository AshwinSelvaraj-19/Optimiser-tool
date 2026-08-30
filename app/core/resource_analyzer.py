"""
Resource Analyzer — advanced emulator memory and resource optimization.

Combines:
- RAM pressure analysis (real psutil data)
- Emulator process deep analysis (threads, handles, process tree)
- Hardware-aware recommendation engine
- Enhanced bottleneck analysis (PresentMon + CPU/GPU/RAM telemetry)
- Safe resource optimization (recommendation-only)

All operations are read-only unless explicitly marked as reversible/verifiable.
No process termination. No fake data. No placebo optimizations.
"""

import time
import os
from dataclasses import dataclass, field
from typing import Optional, List, Tuple, Dict
from datetime import datetime

import psutil

from app.utils.logger import get_logger

logger = get_logger("core.resource_analyzer")


# ── Data Models ────────────────────────────────────────────────

@dataclass
class RAMPressureInfo:
    """Detailed RAM pressure analysis."""
    total_gb: float = 0.0
    used_gb: float = 0.0
    available_gb: float = 0.0
    cached_gb: float = 0.0
    buffers_gb: float = 0.0
    percent_used: float = 0.0
    swap_total_gb: float = 0.0
    swap_used_gb: float = 0.0
    swap_percent: float = 0.0
    pressure_level: str = "UNKNOWN"  # OPTIMAL, MODERATE, HIGH, CRITICAL
    recommendation: str = ""
    top_processes: List[Dict] = field(default_factory=list)

    @property
    def free_gb(self) -> float:
        return self.available_gb


@dataclass
class EmulatorProcessInfo:
    """Deep emulator process analysis."""
    name: str = ""
    pid: int = 0
    exe_path: str = ""
    status: str = ""

    # CPU
    cpu_percent: float = 0.0
    cpu_user_percent: float = 0.0
    cpu_system_percent: float = 0.0
    num_threads: int = 0
    num_handles: int = 0

    # Memory
    rss_mb: float = 0.0          # Physical memory
    vms_mb: float = 0.0          # Virtual memory
    private_mb: float = 0.0      # Private memory
    working_set_mb: float = 0.0  # Working set
    memory_percent: float = 0.0
    page_faults: int = 0

    # Process info
    priority: int = 0
    priority_name: str = ""
    affinity_mask: int = 0
    affinity_cpus: int = 0
    total_cpus: int = 0
    create_time: float = 0.0
    uptime_hours: float = 0.0

    # Children
    child_count: int = 0
    children: List[Dict] = field(default_factory=list)

    # GPU
    gpu_name: str = ""
    gpu_engine: str = ""


@dataclass
class ResourceRecommendation:
    """A single resource recommendation."""
    category: str = ""        # CPU, RAM, GPU, EMULATOR, SYSTEM
    priority: str = "LOW"     # LOW, MEDIUM, HIGH
    title: str = ""
    description: str = ""
    reason: str = ""          # WHY this recommendation was generated
    can_auto_apply: bool = False  # Whether this can be safely automated
    estimated_impact: str = ""


@dataclass
class BottleneckClassification:
    """Enhanced bottleneck classification combining multiple data sources."""
    classification: str = "INCONCLUSIVE"  # CPU_BOUND, GPU_BOUND, MEMORY_PRESSURE, FRAME_TIME_LIMITED, NO_CLEAR_BOTTLENECK, INCONCLUSIVE
    confidence: float = 0.0
    description: str = ""
    evidence: Dict = field(default_factory=dict)
    recommendations: List[str] = field(default_factory=list)


@dataclass
class ResourceStatus:
    """Complete resource status for UI/CLI."""
    ram: Optional[RAMPressureInfo] = None
    emulator: Optional[EmulatorProcessInfo] = None
    bottleneck: Optional[BottleneckClassification] = None
    recommendations: List[ResourceRecommendation] = field(default_factory=list)
    timestamp: float = 0.0


# ── RAM Pressure Analyzer ──────────────────────────────────────

class RAMPressureAnalyzer:
    """
    Analyze system RAM pressure using real psutil data.
    Read-only — does not modify anything.
    """

    def analyze(self, emulator_pid: int = 0) -> RAMPressureInfo:
        """Full RAM pressure analysis."""
        info = RAMPressureInfo()

        try:
            vm = psutil.virtual_memory()
            info.total_gb = vm.total / (1024 ** 3)
            info.used_gb = vm.used / (1024 ** 3)
            info.available_gb = vm.available / (1024 ** 3)
            info.percent_used = vm.percent

            # Cached/buffers (available on some platforms)
            if hasattr(vm, 'cached'):
                info.cached_gb = vm.cached / (1024 ** 3)
            if hasattr(vm, 'buffers'):
                info.buffers_gb = vm.buffers / (1024 ** 3)

            # Swap
            swap = psutil.swap_memory()
            info.swap_total_gb = swap.total / (1024 ** 3)
            info.swap_used_gb = swap.used / (1024 ** 3)
            info.swap_percent = swap.percent

            # Emulator-specific memory
            if emulator_pid > 0:
                try:
                    proc = psutil.Process(emulator_pid)
                    mem = proc.memory_info()
                    # This is already captured in EmulatorProcessInfo
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            # Top memory consumers
            info.top_processes = self._get_top_memory_processes(emulator_pid)

            # Pressure classification
            info.pressure_level, info.recommendation = self._classify_pressure(info)

        except Exception as e:
            logger.debug(f"RAM analysis error: {e}")
            info.pressure_level = "UNKNOWN"
            info.recommendation = "Unable to analyze RAM."

        return info

    def _get_top_memory_processes(self, exclude_pid: int = 0) -> List[Dict]:
        """Get top memory-consuming processes (read-only)."""
        procs = []
        try:
            for proc in psutil.process_iter(["pid", "name", "memory_info", "memory_percent"]):
                try:
                    p = proc.info
                    pid = p.get("pid", 0)
                    if pid == exclude_pid:
                        continue
                    mem = p.get("memory_info")
                    if mem:
                        rss_mb = mem.rss / (1024 * 1024)
                        if rss_mb > 50:  # Only > 50MB
                            procs.append({
                                "name": p.get("name", "?"),
                                "pid": pid,
                                "rss_mb": round(rss_mb, 1),
                                "percent": round(p.get("memory_percent", 0), 1),
                            })
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue
        except Exception:
            pass

        procs.sort(key=lambda x: x["rss_mb"], reverse=True)
        return procs[:10]

    def _classify_pressure(self, info: RAMPressureInfo) -> Tuple[str, str]:
        """Classify RAM pressure level."""
        pct = info.percent_used
        swap_pct = info.swap_percent

        # Critical: > 90% RAM or significant swap usage
        if pct > 90 or swap_pct > 50:
            return "CRITICAL", (
                f"System RAM at {pct:.0f}% with {swap_pct:.0f}% swap usage. "
                "Severe memory pressure will cause frame stutters and system slowdowns."
            )

        # High: > 80% RAM or moderate swap
        if pct > 80 or swap_pct > 20:
            return "HIGH", (
                f"System RAM at {pct:.0f}% with {swap_pct:.0f}% swap usage. "
                "Memory pressure may cause intermittent stutters."
            )

        # Moderate: > 65% RAM
        if pct > 65:
            return "MODERATE", (
                f"System RAM at {pct:.0f}%. "
                "Moderate usage — monitor for increases during gaming."
            )

        # Optimal
        return "OPTIMAL", (
            f"System RAM at {pct:.0f}% with {info.available_gb:.1f}GB available. "
            "Memory usage is healthy."
        )


# ── Emulator Process Analyzer ──────────────────────────────────

class EmulatorProcessAnalyzer:
    """
    Deep emulator process analysis — threads, handles, process tree, working set.
    Read-only — does not modify anything.
    """

    def analyze(self, pid: int, name: str = "") -> Optional[EmulatorProcessInfo]:
        """Analyze a specific emulator process in detail."""
        try:
            proc = psutil.Process(pid)

            info = EmulatorProcessInfo()
            info.name = proc.name()
            info.pid = pid
            info.status = proc.status()

            # Validate name if provided
            if name and proc.name().lower() != name.lower():
                logger.debug(f"PID {pid} name mismatch: expected {name}, got {proc.name()}")
                return None

            # CPU
            try:
                info.cpu_percent = proc.cpu_percent(interval=0.1)
                cpu_times = proc.cpu_times()
                info.cpu_user_percent = getattr(cpu_times, 'user', 0)
                info.cpu_system_percent = getattr(cpu_times, 'system', 0)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Threads and handles
            try:
                info.num_threads = proc.num_threads()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            try:
                info.num_handles = proc.num_handles()
            except (psutil.NoSuchProcess, psutil.AccessDenied, AttributeError):
                pass  # num_handles not available on all platforms

            # Memory
            try:
                mem = proc.memory_info()
                info.rss_mb = mem.rss / (1024 * 1024)
                info.vms_mb = mem.vms / (1024 * 1024)
                if hasattr(mem, 'private'):
                    info.private_mb = mem.private / (1024 * 1024)
                info.working_set_mb = info.rss_mb  # RSS is working set on Windows
                info.memory_percent = proc.memory_percent()
                if hasattr(mem, 'page_faults'):
                    info.page_faults = mem.page_faults
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            # Priority
            try:
                info.priority = proc.nice()
                info.priority_name = self._priority_name(info.priority)
            except (psutil.AccessDenied, OSError):
                pass

            # Affinity
            try:
                mask = proc.cpu_affinity()
                info.affinity_mask = mask
                info.total_cpus = psutil.cpu_count(logical=True) or 1
                info.affinity_cpus = bin(mask).count("1") if mask else info.total_cpus
            except (psutil.AccessDenied, OSError):
                info.total_cpus = psutil.cpu_count(logical=True) or 1
                info.affinity_cpus = info.total_cpus

            # Process start time and uptime
            try:
                info.create_time = proc.create_time()
                uptime_sec = time.time() - info.create_time
                info.uptime_hours = uptime_sec / 3600
            except (psutil.AccessDenied, OSError):
                pass

            # Exe path
            try:
                info.exe_path = proc.exe()
            except (psutil.AccessDenied, OSError):
                pass

            # Children (process tree)
            try:
                children = proc.children(recursive=True)
                info.child_count = len(children)
                for child in children[:10]:  # Limit to 10
                    try:
                        info.children.append({
                            "name": child.name(),
                            "pid": child.pid,
                            "status": child.status(),
                        })
                    except (psutil.NoSuchProcess, psutil.AccessDenied):
                        continue
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

            return info

        except psutil.NoSuchProcess:
            logger.debug(f"PID {pid} no longer exists")
            return None
        except psutil.AccessDenied:
            logger.debug(f"Access denied to PID {pid}")
            return EmulatorProcessInfo(name=name, pid=pid, status="access_denied")

    @staticmethod
    def _priority_name(nice_val: int) -> str:
        if nice_val <= -4:
            return "REALTIME"
        elif nice_val <= -2:
            return "HIGH"
        elif nice_val <= -1:
            return "ABOVE NORMAL"
        elif nice_val == 0:
            return "NORMAL"
        elif nice_val <= 1:
            return "BELOW NORMAL"
        elif nice_val <= 4:
            return "LOW"
        return f"PRIORITY {nice_val}"


# ── Resource Recommendation Engine ─────────────────────────────

class ResourceRecommendationEngine:
    """
    Hardware-aware conservative recommendation engine.
    Generates recommendations based on actual hardware and current state.
    """

    def __init__(self):
        self._ram_analyzer = RAMPressureAnalyzer()
        self._process_analyzer = EmulatorProcessAnalyzer()

    def generate(
        self,
        ram_info: Optional[RAMPressureInfo] = None,
        emulator_info: Optional[EmulatorProcessInfo] = None,
        gpu_info: Optional[dict] = None,
        telemetry_frame=None,
    ) -> List[ResourceRecommendation]:
        """
        Generate hardware-aware recommendations.
        Each recommendation explains WHY it was generated.
        """
        recs = []

        # Get hardware info
        logical_cpus = psutil.cpu_count(logical=True) or 1
        physical_cpus = psutil.cpu_count(logical=False) or logical_cpus
        vm = psutil.virtual_memory()
        total_ram_gb = vm.total / (1024 ** 3)

        # GPU info
        gpu_vram_total = 0
        gpu_vram_used = 0
        gpu_util = 0
        if gpu_info:
            gpu_vram_total = gpu_info.get("vram_total_mb", 0)
            gpu_vram_used = gpu_info.get("vram_used_mb", 0)
            gpu_util = gpu_info.get("utilization", 0)

        # RAM recommendations
        if ram_info:
            if ram_info.pressure_level == "CRITICAL":
                recs.append(ResourceRecommendation(
                    category="RAM",
                    priority="HIGH",
                    title="Critical memory pressure",
                    description=(
                        f"System RAM at {ram_info.percent_used:.0f}% with "
                        f"{ram_info.swap_percent:.0f}% swap usage."
                    ),
                    reason="High swap usage causes disk I/O and frame stutters",
                    can_auto_apply=False,
                    estimated_impact="Significant — reduces stuttering",
                ))
            elif ram_info.pressure_level == "HIGH":
                recs.append(ResourceRecommendation(
                    category="RAM",
                    priority="MEDIUM",
                    title="High memory usage",
                    description=(
                        f"System RAM at {ram_info.percent_used:.0f}% with "
                        f"{ram_info.available_gb:.1f}GB available."
                    ),
                    reason="Limited RAM headroom may cause issues during heavy scenes",
                    can_auto_apply=False,
                    estimated_impact="Moderate — improves stability",
                ))

            # Check if emulator is using disproportionate RAM
            if emulator_info and ram_info.total_gb > 0:
                emu_pct = (emulator_info.rss_mb / 1024) / ram_info.total_gb * 100
                if emu_pct > 40:
                    recs.append(ResourceRecommendation(
                        category="EMULATOR",
                        priority="MEDIUM",
                        title="High emulator RAM usage",
                        description=(
                            f"Emulator using {emulator_info.rss_mb:.0f}MB "
                            f"({emu_pct:.0f}% of total RAM)."
                        ),
                        reason="Emulator consuming large portion of available RAM",
                        can_auto_apply=False,
                        estimated_impact="Frees system RAM for other processes",
                    ))

        # CPU recommendations
        if emulator_info:
            if emulator_info.cpu_percent > 90:
                recs.append(ResourceRecommendation(
                    category="CPU",
                    priority="HIGH",
                    title="Emulator CPU saturation",
                    description=(
                        f"Emulator using {emulator_info.cpu_percent:.0f}% CPU "
                        f"with {emulator_info.num_threads} threads."
                    ),
                    reason="CPU saturation limits frame generation speed",
                    can_auto_apply=False,
                    estimated_impact="High — directly improves frame rate",
                ))
            elif emulator_info.cpu_percent > 70 and emulator_info.affinity_cpus < logical_cpus // 2:
                recs.append(ResourceRecommendation(
                    category="CPU",
                    priority="MEDIUM",
                    title="Emulator CPU limited by affinity",
                    description=(
                        f"Emulator using {emulator_info.affinity_cpus}/{logical_cpus} CPUs "
                        f"at {emulator_info.cpu_percent:.0f}% usage."
                    ),
                    reason="Restricted CPU affinity may limit performance on multi-core systems",
                    can_auto_apply=True,
                    estimated_impact="Moderate — allows better CPU scheduling",
                ))

            # Thread count analysis
            if emulator_info.num_threads > logical_cpus * 2:
                recs.append(ResourceRecommendation(
                    category="EMULATOR",
                    priority="LOW",
                    title="High thread count",
                    description=(
                        f"Emulator has {emulator_info.num_threads} threads "
                        f"on {logical_cpus} logical CPUs."
                    ),
                    reason="Excessive thread count can cause scheduling overhead",
                    can_auto_apply=False,
                    estimated_impact="Low — usually managed by emulator",
                ))

        # GPU recommendations
        if gpu_vram_total > 0:
            vram_pct = (gpu_vram_used / gpu_vram_total) * 100
            if vram_pct > 85:
                recs.append(ResourceRecommendation(
                    category="GPU",
                    priority="HIGH",
                    title="VRAM pressure",
                    description=(
                        f"VRAM at {vram_pct:.0f}% "
                        f"({gpu_vram_used:.0f}/{gpu_vram_total:.0f}MB)."
                    ),
                    reason="High VRAM usage causes texture streaming and frame drops",
                    can_auto_apply=False,
                    estimated_impact="High — reduces texture stuttering",
                ))

        if gpu_util > 90:
            recs.append(ResourceRecommendation(
                category="GPU",
                priority="HIGH",
                title="GPU utilization saturated",
                description=f"GPU at {gpu_util:.0f}% utilization.",
                reason="GPU is the rendering bottleneck — cannot generate frames faster",
                can_auto_apply=False,
                estimated_impact="Requires graphics settings reduction",
            ))

        # System-level recommendations
        if logical_cpus >= 8 and ram_info and ram_info.total_gb >= 16:
            recs.append(ResourceRecommendation(
                category="SYSTEM",
                priority="LOW",
                title="Hardware capable",
                description=(
                    f"{logical_cpus} CPU threads, {ram_info.total_gb:.0f}GB RAM. "
                    f"System hardware is adequate for emulator gaming."
                ),
                reason="Baseline hardware assessment",
                can_auto_apply=False,
                estimated_impact="Informational",
            ))

        # Sort by priority
        priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
        recs.sort(key=lambda r: priority_order.get(r.priority, 3))

        return recs


# ── Enhanced Bottleneck Classifier ─────────────────────────────

class ResourceBottleneckClassifier:
    """
    Enhanced bottleneck classification combining PresentMon telemetry,
    CPU/GPU/RAM data, and emulator process metrics.
    """

    def classify(
        self,
        telemetry_frame=None,
        emulator_info: Optional[EmulatorProcessInfo] = None,
        ram_info: Optional[RAMPressureInfo] = None,
        presentmon_data: Optional[dict] = None,
    ) -> BottleneckClassification:
        """
        Classify the system bottleneck using all available data sources.
        """
        result = BottleneckClassification()
        evidence = {}
        recs = []

        # Gather data from telemetry
        cpu_util = 0.0
        gpu_util = 0.0
        ram_pct = 0.0
        gpu_temp = None
        thermal_status = None

        if telemetry_frame:
            cpu_util = telemetry_frame.cpu_utilization
            gpu_util = telemetry_frame.gpu_utilization
            ram_pct = telemetry_frame.ram_percent
            gpu_temp = telemetry_frame.gpu_temp
            thermal_status = telemetry_frame.thermal_status
            evidence["cpu_util"] = cpu_util
            evidence["gpu_util"] = gpu_util
            evidence["ram_pct"] = ram_pct

        # Enhance with emulator process data
        if emulator_info:
            evidence["emu_cpu"] = emulator_info.cpu_percent
            evidence["emu_threads"] = emulator_info.num_threads
            evidence["emu_handles"] = emulator_info.num_handles
            evidence["emu_rss_mb"] = emulator_info.rss_mb

        # Enhance with RAM data
        if ram_info:
            evidence["ram_total_gb"] = ram_info.total_gb
            evidence["ram_available_gb"] = ram_info.available_gb
            evidence["swap_pct"] = ram_info.swap_percent
            evidence["ram_pressure"] = ram_info.pressure_level

        # Enhance with PresentMon data
        if presentmon_data:
            evidence["present_fps"] = presentmon_data.get("fps", 0)
            evidence["frame_time_ms"] = presentmon_data.get("frame_time_ms", 0)
            evidence["frame_spikes"] = presentmon_data.get("frame_spikes", 0)

        # Classification logic (requires sufficient evidence)
        if not evidence:
            result.classification = "INCONCLUSIVE"
            result.confidence = 0.0
            result.description = "Insufficient telemetry data for classification."
            return result

        # Check thermal first (highest priority)
        if thermal_status == "THROTTLING" or (gpu_temp and gpu_temp > 90):
            result.classification = "CPU_BOUND"  # Thermal throttling is effectively CPU-bound
            result.confidence = 0.9
            result.description = (
                f"Thermal throttling detected. GPU temp: {gpu_temp}°C. "
                f"CPU/GPU clocks are being reduced."
            )
            result.recommendations = [
                "Improve cooling — clean dust, add cooling pad",
                "Reduce emulator graphics settings",
                "Lower resolution if possible",
            ]
            return result

        # Check memory pressure first
        swap_pct = evidence.get("swap_pct", 0)
        if ram_pct > 85 or swap_pct > 30:
            result.classification = "MEMORY_PRESSURE"
            result.confidence = min(0.95, 0.5 + (ram_pct - 70) / 30)
            result.description = (
                f"RAM at {ram_pct:.0f}% with {swap_pct:.0f}% swap usage. "
                "Memory pressure causes disk I/O and frame stutters."
            )
            result.recommendations = [
                "Close memory-heavy background processes",
                "Check emulator RAM allocation",
            ]
            return result

        # GPU-bound detection
        if gpu_util > 88:
            severity = "HIGH" if gpu_util > 95 else "MEDIUM"
            result.classification = "GPU_BOUND"
            result.confidence = min(0.95, 0.5 + (gpu_util - 75) / 25)
            result.description = (
                f"GPU at {gpu_util:.0f}% utilization is the primary bottleneck. "
                "Rendering is limited by GPU capacity."
            )
            result.recommendations = [
                "Reduce emulator graphics quality",
                "Lower render resolution",
                "Disable unnecessary visual effects",
            ]
            return result

        # CPU-bound detection
        emu_cpu = evidence.get("emu_cpu", cpu_util)
        if cpu_util > 85 and gpu_util < 65:
            result.classification = "CPU_BOUND"
            result.confidence = min(0.95, 0.5 + (cpu_util - 70) / 30)
            result.description = (
                f"CPU at {cpu_util:.0f}% while GPU is only {gpu_util:.0f}%. "
                "CPU is limiting frame delivery to the GPU."
            )
            result.recommendations = [
                "Close CPU-heavy background processes",
                "Check emulator CPU allocation",
                "Verify power plan is High Performance",
            ]
            return result

        # Frame-time limited (high FPS variance without clear CPU/GPU bottleneck)
        frame_spikes = evidence.get("frame_spikes", 0)
        if frame_spikes > 20 and cpu_util < 80 and gpu_util < 80:
            result.classification = "FRAME_TIME_LIMITED"
            result.confidence = 0.6
            result.description = (
                f"Frame time instability detected ({frame_spikes} spikes) "
                f"without clear CPU ({cpu_util:.0f}%) or GPU ({gpu_util:.0f}%) bottleneck. "
                "Likely caused by background processes, thermal throttling, or driver issues."
            )
            result.recommendations = [
                "Monitor for background process interference",
                "Check for thermal throttling",
                "Update GPU drivers",
            ]
            return result

        # No clear bottleneck
        result.classification = "NO_CLEAR_BOTTLENECK"
        result.confidence = 0.7
        result.description = (
            f"CPU: {cpu_util:.0f}%, GPU: {gpu_util:.0f}%, RAM: {ram_pct:.0f}%. "
            "No single resource is the clear bottleneck."
        )
        result.recommendations = ["System is balanced. Monitor for changes."]
        return result


# ── Main Resource Analyzer (combined) ──────────────────────────

class ResourceAnalyzer:
    """
    Combined resource analyzer — RAM, emulator process, recommendations, bottleneck.
    Single entry point for all resource analysis.
    """

    def __init__(self):
        self._ram_analyzer = RAMPressureAnalyzer()
        self._process_analyzer = EmulatorProcessAnalyzer()
        self._recommendation_engine = ResourceRecommendationEngine()
        self._bottleneck_classifier = ResourceBottleneckClassifier()

    def analyze(
        self,
        emulator_pid: int = 0,
        emulator_name: str = "",
        telemetry_frame=None,
        gpu_info: Optional[dict] = None,
        presentmon_data: Optional[dict] = None,
    ) -> ResourceStatus:
        """
        Complete resource analysis.
        Read-only — does not modify anything.
        """
        status = ResourceStatus(timestamp=time.time())

        # RAM analysis
        status.ram = self._ram_analyzer.analyze(emulator_pid)

        # Emulator process analysis
        if emulator_pid > 0:
            status.emulator = self._process_analyzer.analyze(emulator_pid, emulator_name)

        # Bottleneck classification
        status.bottleneck = self._bottleneck_classifier.classify(
            telemetry_frame=telemetry_frame,
            emulator_info=status.emulator,
            ram_info=status.ram,
            presentmon_data=presentmon_data,
        )

        # Generate recommendations
        status.recommendations = self._recommendation_engine.generate(
            ram_info=status.ram,
            emulator_info=status.emulator,
            gpu_info=gpu_info,
            telemetry_frame=telemetry_frame,
        )

        return status

    def get_ram_pressure(self, emulator_pid: int = 0) -> RAMPressureInfo:
        """Quick RAM pressure check."""
        return self._ram_analyzer.analyze(emulator_pid)

    def get_emulator_process(self, pid: int, name: str = "") -> Optional[EmulatorProcessInfo]:
        """Quick emulator process check."""
        return self._process_analyzer.analyze(pid, name)

    def get_recommendations(self, status: ResourceStatus) -> List[ResourceRecommendation]:
        """Generate recommendations from a resource status."""
        return self._recommendation_engine.generate(
            ram_info=status.ram,
            emulator_info=status.emulator,
        )


# Singleton
resource_analyzer = ResourceAnalyzer()
