"""
Thermal & Throttling Monitor — Heaven Society.

Comprehensive GPU/CPU thermal diagnostics with performance correlation.
Builds on existing gpu.py, cpu.py, and thermals.py infrastructure.

IMPORTANT:
- Do NOT control fan speed
- Do NOT change BIOS settings
- Do NOT undervolt/overclock
- Do NOT claim throttling unless supported by measured data
- Do NOT fabricate CPU temperature if psutil cannot provide it

All values originate from real hardware sensors (NVML, psutil).
Thermal states and correlations are HEURISTIC based on measured values.
"""

import time
import statistics
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from enum import Enum

import psutil

from app.utils.logger import get_logger

logger = get_logger("system.thermal_monitor")


# ── Legacy Compatibility ────────────────────────────────────────
# Replaces the old app.system.thermals module.

TEMP_NORMAL = 70.0
TEMP_WARM = 80.0
TEMP_HOT = 90.0
TEMP_CRITICAL = 95.0


@dataclass
class ThermalSnapshot:
    """Point-in-time thermal data (legacy compatibility)."""
    cpu_temp: Optional[float] = None
    gpu_temp: Optional[float] = None
    timestamp: float = 0.0
    cpu_throttling: bool = False
    gpu_throttling: bool = False

    @property
    def any_throttling(self) -> bool:
        return self.cpu_throttling or self.gpu_throttling

    @property
    def max_temp(self) -> float:
        temps = [t for t in [self.cpu_temp, self.gpu_temp] if t is not None]
        return max(temps) if temps else 0.0


# ── Thermal States ─────────────────────────────────────────────

class ThermalState(Enum):
    """Thermal state classification."""
    NORMAL = "NORMAL"
    WARM = "WARM"
    HOT = "HOT"
    THROTTLING_RISK = "THROTTLING RISK"
    UNKNOWN = "UNKNOWN"


class ThrottleIndicator(Enum):
    """Specific throttle indicators detected."""
    CLOCK_DROP = "Clock Drop"
    POWER_LIMIT = "Power Limit"
    TEMPERATURE_LIMIT = "Temperature Limit"
    SUSTAINED_HIGH_TEMP = "Sustained High Temperature"
    FRAME_TIME_INCREASE = "Frame Time Increase"
    NONE = "None Detected"


# ── Data Models ────────────────────────────────────────────────

@dataclass
class GPUThermalData:
    """GPU thermal metrics — all MEASURED from NVML."""
    temperature_celsius: Optional[float] = None
    utilization_gpu: float = 0.0
    utilization_memory: float = 0.0
    clock_core_mhz: float = 0.0
    clock_memory_mhz: float = 0.0
    power_draw_watts: Optional[float] = None
    power_limit_watts: Optional[float] = None
    power_state: str = ""
    vram_used_mb: float = 0.0
    vram_total_mb: float = 0.0
    fan_speed_percent: Optional[float] = None
    name: str = ""
    is_measured: bool = True

    @property
    def power_utilization(self) -> Optional[float]:
        """Percentage of power limit being used."""
        if self.power_draw_watts and self.power_limit_watts and self.power_limit_watts > 0:
            return (self.power_draw_watts / self.power_limit_watts) * 100
        return None

    @property
    def vram_percent(self) -> float:
        if self.vram_total_mb > 0:
            return (self.vram_used_mb / self.vram_total_mb) * 100
        return 0.0


@dataclass
class CPUThermalData:
    """CPU thermal metrics — all MEASURED from psutil."""
    temperature_celsius: Optional[float] = None
    utilization_percent: float = 0.0
    frequency_mhz: float = 0.0
    max_frequency_mhz: float = 0.0
    per_core_percent: list = field(default_factory=list)
    model: str = ""
    is_measured: bool = True  # False if temperature unavailable

    @property
    def frequency_ratio(self) -> float:
        """Current vs max frequency ratio (1.0 = full speed)."""
        if self.max_frequency_mhz > 0:
            return self.frequency_mhz / self.max_frequency_mhz
        return 1.0


@dataclass
class SystemMemoryThermal:
    """System memory pressure — MEASURED from psutil."""
    total_gb: float = 0.0
    used_gb: float = 0.0
    available_gb: float = 0.0
    percent_used: float = 0.0
    swap_percent: float = 0.0
    pressure_level: str = "NORMAL"  # NORMAL, MODERATE, HIGH, CRITICAL
    is_measured: bool = True


@dataclass
class ThermalCorrelation:
    """Correlation between thermal state and performance — HEURISTIC."""
    temperature_trend: str = ""       # RISING, STABLE, FALLING
    clock_trend: str = ""             # DROPPING, STABLE, RISING
    frame_time_trend: str = ""        # INCREASING, STABLE, DECREASING
    correlation_strength: float = 0.0  # 0-1, how strongly correlated
    correlation_description: str = ""
    is_measured: bool = False         # Correlation is heuristic


@dataclass
class ThermalDiagnostics:
    """Complete thermal diagnostics report."""
    # Measured components
    gpu: GPUThermalData = field(default_factory=GPUThermalData)
    cpu: CPUThermalData = field(default_factory=CPUThermalData)
    memory: SystemMemoryThermal = field(default_factory=SystemMemoryThermal)

    # Overall assessment
    thermal_state: ThermalState = ThermalState.UNKNOWN
    max_temperature: float = 0.0
    throttle_indicators: List[ThrottleIndicator] = field(default_factory=list)
    throttle_confidence: float = 0.0  # 0-1

    # Correlation
    correlation: ThermalCorrelation = field(default_factory=ThermalCorrelation)

    # Recommendations
    recommendations: List[str] = field(default_factory=list)

    # Data source labels
    measurement_type: str = "MEASURED"  # MEASURED or HEURISTIC
    disclaimers: List[str] = field(default_factory=list)

    timestamp: float = 0.0

    def __post_init__(self):
        self.disclaimers = [
            "Temperature values are from hardware sensors (NVML/psutil).",
            "Throttle detection is heuristic — not a definitive hardware reading.",
            "No system settings are modified by this analysis.",
        ]


# ── Thresholds (Celsius) ──────────────────────────────────────

GPU_TEMP_WARM = 75.0
GPU_TEMP_HOT = 85.0
GPU_TEMP_THROTTLE = 90.0

CPU_TEMP_WARM = 70.0
CPU_TEMP_HOT = 80.0
CPU_TEMP_THROTTLE = 90.0


# ── Core Analyzer ──────────────────────────────────────────────

class ThermalMonitor:
    """
    Comprehensive thermal diagnostics with performance correlation.
    All analysis uses real measured data.
    Throttle detection and correlation are HEURISTIC.
    """

    def __init__(self):
        self._cache: Optional[ThermalDiagnostics] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 3.0
        self._clock_history: List[Tuple[float, float]] = []  # (timestamp, clock_mhz)
        self._temp_history: List[Tuple[float, float]] = []   # (timestamp, temp)
        self._frame_time_history: List[Tuple[float, float]] = []  # (timestamp, frame_time_ms)
        self._snapshot_history: List[ThermalSnapshot] = []
        self._max_snapshot_history = 60

    # ── Legacy compatibility API (replaces thermals.py) ────────

    def read_snapshot(self, cpu_temp: Optional[float] = None,
                      gpu_temp: Optional[float] = None) -> ThermalSnapshot:
        """Read a thermal snapshot (legacy compatibility)."""
        snapshot = ThermalSnapshot(
            cpu_temp=cpu_temp,
            gpu_temp=gpu_temp,
            timestamp=time.time(),
        )
        if cpu_temp is not None:
            snapshot.cpu_throttling = cpu_temp >= TEMP_HOT
        if gpu_temp is not None:
            snapshot.gpu_throttling = gpu_temp >= TEMP_HOT
        self._snapshot_history.append(snapshot)
        if len(self._snapshot_history) > self._max_snapshot_history:
            self._snapshot_history.pop(0)
        return snapshot

    def diagnose(self, force: bool = False) -> ThermalDiagnostics:
        """
        Full thermal diagnostics.
        Returns real hardware sensor data.
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        diag = ThermalDiagnostics(timestamp=now)

        # 1. GPU thermal data (MEASURED from NVML)
        diag.gpu = self._read_gpu_thermal()

        # 2. CPU thermal data (MEASURED from psutil)
        diag.cpu = self._read_cpu_thermal()

        # 3. System memory (MEASURED from psutil)
        diag.memory = self._read_memory_pressure()

        # 4. Determine max temperature
        temps = [t for t in [diag.gpu.temperature_celsius, diag.cpu.temperature_celsius] if t is not None]
        diag.max_temperature = max(temps) if temps else 0.0

        # 5. Classify thermal state
        diag.thermal_state = self._classify_state(diag)

        # 6. Detect throttle indicators (HEURISTIC)
        diag.throttle_indicators, diag.throttle_confidence = \
            self._detect_throttling(diag)

        # 7. Performance correlation (HEURISTIC)
        diag.correlation = self._correlate_performance(diag)

        # 8. Generate recommendations
        diag.recommendations = self._generate_recommendations(diag)

        self._cache = diag
        self._cache_time = now
        return diag

    def record_sample(
        self,
        gpu_clock: float = 0.0,
        gpu_temp: float = 0.0,
        frame_time_ms: float = 0.0,
    ):
        """
        Record a telemetry sample for trend analysis.
        Call this periodically from the telemetry engine.
        """
        now = time.time()

        if gpu_clock > 0:
            self._clock_history.append((now, gpu_clock))
            if len(self._clock_history) > 300:
                self._clock_history.pop(0)

        if gpu_temp > 0:
            self._temp_history.append((now, gpu_temp))
            if len(self._temp_history) > 300:
                self._temp_history.pop(0)

        if frame_time_ms > 0:
            self._frame_time_history.append((now, frame_time_ms))
            if len(self._frame_time_history) > 300:
                self._frame_time_history.pop(0)

    # ── 1. GPU Thermal ────────────────────────────────────────

    def _read_gpu_thermal(self) -> GPUThermalData:
        """
        Read GPU thermal data from NVML.
        All values are MEASURED from real hardware.
        """
        data = GPUThermalData()

        try:
            from app.system.gpu import gpu_monitor, NVML_AVAILABLE
            if not NVML_AVAILABLE:
                data.is_measured = False
                return data

            gpus = gpu_monitor.detect()
            if not gpus:
                data.is_measured = False
                return data

            gpu = gpus[0]
            if gpu.vendor == "NVIDIA":
                gpu = gpu_monitor.update_nvidia(gpu)

            data.name = gpu.name
            data.temperature_celsius = gpu.temperature_celsius
            data.utilization_gpu = gpu.utilization_gpu
            data.utilization_memory = gpu.utilization_memory
            data.clock_core_mhz = gpu.clock_core_mhz
            data.clock_memory_mhz = gpu.clock_memory_mhz
            data.power_draw_watts = gpu.power_draw_watts
            data.power_limit_watts = gpu.power_limit_watts
            data.power_state = gpu.power_state
            data.vram_used_mb = gpu.vram_used_mb
            data.vram_total_mb = gpu.vram_total_mb
            data.fan_speed_percent = gpu.fan_speed_percent

            # Record for trend analysis
            if gpu.temperature_celsius is not None:
                self.record_sample(
                    gpu_clock=gpu.clock_core_mhz,
                    gpu_temp=gpu.temperature_celsius,
                )

        except Exception as e:
            logger.debug(f"GPU thermal read error: {e}")
            data.is_measured = False

        return data

    # ── 2. CPU Thermal ────────────────────────────────────────

    def _read_cpu_thermal(self) -> CPUThermalData:
        """
        Read CPU thermal data from psutil.
        Temperature may be unavailable on some systems — reported as None.
        """
        data = CPUThermalData()

        try:
            # CPU utilization and frequency (always available)
            data.utilization_percent = psutil.cpu_percent(interval=0.1)
            freq = psutil.cpu_freq()
            if freq:
                data.frequency_mhz = freq.current
                data.max_frequency_mhz = freq.max or freq.current
            data.per_core_percent = psutil.cpu_percent(interval=0, percpu=True)

            # CPU temperature (may not be available)
            try:
                temps = psutil.sensors_temperatures()
                if temps:
                    for name in ["coretemp", "k10temp", "cpu_thermal", "zenpower",
                                 "acpitz", "pch_skylake", "soc_dts0"]:
                        if name in temps:
                            for entry in temps[name]:
                                if entry.current > 0:
                                    data.temperature_celsius = entry.current
                                    break
                        if data.temperature_celsius is not None:
                            break
            except (AttributeError, Exception):
                # sensors_temperatures not available on this platform
                data.is_measured = False

            # CPU model
            import platform
            data.model = platform.processor() or "Unknown"

        except Exception as e:
            logger.debug(f"CPU thermal read error: {e}")

        return data

    # ── 3. Memory Pressure ────────────────────────────────────

    def _read_memory_pressure(self) -> SystemMemoryThermal:
        """Read system memory pressure — MEASURED from psutil."""
        data = SystemMemoryThermal()

        try:
            vm = psutil.virtual_memory()
            data.total_gb = vm.total / (1024 ** 3)
            data.used_gb = vm.used / (1024 ** 3)
            data.available_gb = vm.available / (1024 ** 3)
            data.percent_used = vm.percent

            swap = psutil.swap_memory()
            data.swap_percent = swap.percent

            # Classify pressure
            if vm.percent > 90 or swap.percent > 50:
                data.pressure_level = "CRITICAL"
            elif vm.percent > 80 or swap.percent > 20:
                data.pressure_level = "HIGH"
            elif vm.percent > 65:
                data.pressure_level = "MODERATE"
            else:
                data.pressure_level = "NORMAL"

        except Exception as e:
            logger.debug(f"Memory pressure read error: {e}")

        return data

    # ── 4. State Classification ───────────────────────────────

    def _classify_state(self, diag: ThermalDiagnostics) -> ThermalState:
        """
        Classify overall thermal state from measured temperatures.
        HEURISTIC thresholds based on hardware specifications.
        """
        temps = []
        if diag.gpu.temperature_celsius is not None:
            temps.append(("GPU", diag.gpu.temperature_celsius))
        if diag.cpu.temperature_celsius is not None:
            temps.append(("CPU", diag.cpu.temperature_celsius))

        if not temps:
            return ThermalState.UNKNOWN

        max_temp = max(t for _, t in temps)

        # Check for active throttle indicators
        if ThrottleIndicator.CLOCK_DROP in diag.throttle_indicators:
            return ThermalState.THROTTLING_RISK

        if max_temp >= GPU_TEMP_THROTTLE or max_temp >= CPU_TEMP_THROTTLE:
            return ThermalState.THROTTLING_RISK
        if max_temp >= GPU_TEMP_HOT or max_temp >= CPU_TEMP_HOT:
            return ThermalState.HOT
        if max_temp >= GPU_TEMP_WARM or max_temp >= CPU_TEMP_WARM:
            return ThermalState.WARM
        return ThermalState.NORMAL

    # ── 5. Throttle Detection ─────────────────────────────────

    def _detect_throttling(
        self, diag: ThermalDiagnostics
    ) -> Tuple[List[ThrottleIndicator], float]:
        """
        Detect throttle indicators from measured data.
        Each indicator is HEURISTIC — not a definitive hardware reading.
        """
        indicators = []
        total_confidence = 0.0

        # ── Clock drop detection ───────────────────────────────
        if len(self._clock_history) >= 10:
            recent_clocks = [c for _, c in self._clock_history[-10:]]
            older_clocks = [c for _, c in self._clock_history[-20:-10]] \
                if len(self._clock_history) >= 20 else recent_clocks[:5]

            if older_clocks and recent_clocks:
                avg_recent = statistics.mean(recent_clocks)
                avg_older = statistics.mean(older_clocks)
                if avg_older > 0 and avg_recent < avg_older * 0.90:
                    drop_pct = (1 - avg_recent / avg_older) * 100
                    indicators.append(ThrottleIndicator.CLOCK_DROP)
                    total_confidence += min(0.4, drop_pct / 100)

        # ── Temperature limit detection ────────────────────────
        gpu_temp = diag.gpu.temperature_celsius
        cpu_temp = diag.cpu.temperature_celsius

        if gpu_temp is not None and gpu_temp >= GPU_TEMP_THROTTLE:
            indicators.append(ThrottleIndicator.TEMPERATURE_LIMIT)
            total_confidence += 0.3

        if cpu_temp is not None and cpu_temp >= CPU_TEMP_THROTTLE:
            indicators.append(ThrottleIndicator.TEMPERATURE_LIMIT)
            total_confidence += 0.3

        # ── Power limit detection ──────────────────────────────
        if diag.gpu.power_utilization is not None:
            if diag.gpu.power_utilization >= 95:
                indicators.append(ThrottleIndicator.POWER_LIMIT)
                total_confidence += 0.2

        # ── Sustained high temperature ─────────────────────────
        if len(self._temp_history) >= 15:
            recent_temps = [t for _, t in self._temp_history[-15:]]
            hot_count = sum(1 for t in recent_temps if t >= GPU_TEMP_HOT)
            if hot_count >= 10:
                indicators.append(ThrottleIndicator.SUSTAINED_HIGH_TEMP)
                total_confidence += 0.3

        # ── Frame time increase detection ──────────────────────
        if len(self._frame_time_history) >= 20:
            ft_values = [ft for _, ft in self._frame_time_history[-20:]]
            first_half = statistics.mean(ft_values[:10])
            second_half = statistics.mean(ft_values[10:])
            if first_half > 0 and second_half > first_half * 1.15:
                indicators.append(ThrottleIndicator.FRAME_TIME_INCREASE)
                total_confidence += 0.25

        # Remove NONE if other indicators found
        if indicators and ThrottleIndicator.NONE in indicators:
            indicators.remove(ThrottleIndicator.NONE)

        if not indicators:
            indicators.append(ThrottleIndicator.NONE)
            total_confidence = 0.0

        return indicators, min(1.0, total_confidence)

    # ── 6. Performance Correlation ─────────────────────────────

    def _correlate_performance(self, diag: ThermalDiagnostics) -> ThermalCorrelation:
        """
        Correlate thermal data with performance trends.
        HEURISTIC — not a definitive causal analysis.
        """
        corr = ThermalCorrelation()
        corr.is_measured = False  # Correlation is heuristic

        # Temperature trend
        if len(self._temp_history) >= 10:
            temps = [t for _, t in self._temp_history[-10:]]
            first = statistics.mean(temps[:3])
            last = statistics.mean(temps[-3:])
            if first > 0:
                change = (last - first) / first
                if change > 0.05:
                    corr.temperature_trend = "RISING"
                elif change < -0.05:
                    corr.temperature_trend = "FALLING"
                else:
                    corr.temperature_trend = "STABLE"

        # Clock trend
        if len(self._clock_history) >= 10:
            clocks = [c for _, c in self._clock_history[-10:]]
            first = statistics.mean(clocks[:3])
            last = statistics.mean(clocks[-3:])
            if first > 0:
                change = (last - first) / first
                if change < -0.05:
                    corr.clock_trend = "DROPPING"
                elif change > 0.05:
                    corr.clock_trend = "RISING"
                else:
                    corr.clock_trend = "STABLE"

        # Frame time trend
        if len(self._frame_time_history) >= 10:
            fts = [ft for _, ft in self._frame_time_history[-10:]]
            first = statistics.mean(fts[:3])
            last = statistics.mean(fts[-3:])
            if first > 0:
                change = (last - first) / first
                if change > 0.10:
                    corr.frame_time_trend = "INCREASING"
                elif change < -0.10:
                    corr.frame_time_trend = "DECREASING"
                else:
                    corr.frame_time_trend = "STABLE"

        # Correlation strength (HEURISTIC)
        score = 0.0
        if corr.temperature_trend == "RISING" and corr.clock_trend == "DROPPING":
            score += 0.4
        if corr.temperature_trend == "RISING" and corr.frame_time_trend == "INCREASING":
            score += 0.3
        if corr.clock_trend == "DROPPING" and corr.frame_time_trend == "INCREASING":
            score += 0.3

        corr.correlation_strength = min(1.0, score)

        if score > 0.5:
            corr.correlation_description = (
                "Strong correlation: rising temperature coincides with "
                "dropping clock speeds and increasing frame times. "
                "Likely thermal throttling affecting performance."
            )
        elif score > 0.2:
            corr.correlation_description = (
                "Moderate correlation: some thermal indicators align "
                "with performance changes. Monitor for further degradation."
            )
        else:
            corr.correlation_description = (
                "No strong thermal-performance correlation detected."
            )

        return corr

    # ── 7. Recommendations ─────────────────────────────────────

    def _generate_recommendations(self, diag: ThermalDiagnostics) -> List[str]:
        """Generate recommendations from measured thermal data."""
        recs = []

        # GPU temperature
        if diag.gpu.temperature_celsius is not None:
            temp = diag.gpu.temperature_celsius
            if temp >= GPU_TEMP_THROTTLE:
                recs.append(
                    f"GPU at {temp:.0f}°C — critical temperature. "
                    "Performance is likely being throttled. "
                    "Improve cooling immediately."
                )
            elif temp >= GPU_TEMP_HOT:
                recs.append(
                    f"GPU at {temp:.0f}°C — high temperature. "
                    "Thermal throttling may activate soon. "
                    "Improve case airflow."
                )
            elif temp >= GPU_TEMP_WARM:
                recs.append(
                    f"GPU at {temp:.0f}°C — warm. "
                    "Monitor for further increases."
                )

        # CPU temperature
        if diag.cpu.temperature_celsius is not None:
            temp = diag.cpu.temperature_celsius
            if temp >= CPU_TEMP_THROTTLE:
                recs.append(
                    f"CPU at {temp:.0f}°C — critical temperature. "
                    "May be thermally throttled. Check cooling."
                )
            elif temp >= CPU_TEMP_HOT:
                recs.append(
                    f"CPU at {temp:.0f}°C — high temperature. "
                    "Consider improving CPU cooling."
                )
        elif diag.cpu.is_measured and diag.cpu.temperature_celsius is None:
            recs.append(
                "CPU temperature unavailable — psutil sensors not "
                "supported on this platform."
            )

        # Clock drop
        if ThrottleIndicator.CLOCK_DROP in diag.throttle_indicators:
            recs.append(
                "GPU clock speed reduction detected — "
                "likely thermal throttling. Reduce GPU load or improve cooling."
            )

        # Power limit
        if ThrottleIndicator.POWER_LIMIT in diag.throttle_indicators:
            recs.append(
                "GPU operating near power limit — "
                "performance may be power-constrained."
            )

        # Memory pressure
        if diag.memory.pressure_level in ("HIGH", "CRITICAL"):
            recs.append(
                f"System memory at {diag.memory.percent_used:.0f}% — "
                "memory pressure may cause additional thermal load."
            )

        # Correlation
        if diag.correlation.correlation_strength > 0.5:
            recs.append(
                "Strong thermal-performance correlation detected. "
                "Reducing emulator settings may improve both thermals and frame pacing."
            )

        if not recs:
            recs.append("Thermal conditions appear normal. No action needed.")

        return recs


# Singleton
thermal_diagnostics = ThermalMonitor()
