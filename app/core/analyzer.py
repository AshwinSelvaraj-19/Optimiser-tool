"""
Bottleneck analyzer engine.
Rules-based detection of performance bottlenecks with confidence scoring.
"""

from dataclasses import dataclass, field
from typing import Optional

from app.core.telemetry import TelemetryFrame
from app.utils.logger import get_logger

logger = get_logger("core.analyzer")


@dataclass
class Bottleneck:
    """A detected performance bottleneck."""
    name: str = ""
    severity: str = "LOW"  # LOW, MEDIUM, HIGH, CRITICAL
    confidence: float = 0.0  # 0.0 to 1.0
    description: str = ""
    recommendation: str = ""
    metrics: dict = field(default_factory=dict)


@dataclass
class AnalysisResult:
    """Complete bottleneck analysis result."""
    bottlenecks: list = field(default_factory=list)
    primary_bottleneck: Optional[Bottleneck] = None
    overall_score: float = 0.0  # 0-100, higher is better
    performance_class: str = "UNKNOWN"  # EXCELLENT, GOOD, AVERAGE, BOTTLENECKED, SEVERE
    timestamp: float = 0.0

    @property
    def has_critical(self) -> bool:
        return any(b.severity == "CRITICAL" for b in self.bottlenecks)


class BottleneckAnalyzer:
    """Rules-based bottleneck detection engine."""

    def __init__(self):
        self._analysis_history: list = []

    def analyze(self, frame: TelemetryFrame, gpu_vendor: str = "Unknown") -> AnalysisResult:
        """Analyze a telemetry frame for performance bottlenecks."""
        result = AnalysisResult(timestamp=frame.timestamp)
        bottlenecks = []

        # --- CPU Bottleneck ---
        if frame.cpu_utilization > 90:
            cpu_bottleneck = Bottleneck(
                name="CPU Limitation",
                severity="HIGH" if frame.cpu_utilization > 95 else "MEDIUM",
                confidence=min(1.0, (frame.cpu_utilization - 80) / 20),
                description=(
                    f"CPU utilization is {frame.cpu_utilization:.1f}%, indicating the CPU is "
                    f"near or at full capacity. This limits frame generation and emulation speed."
                ),
                recommendation=(
                    "Reduce emulator CPU allocation, close CPU-heavy background processes, "
                    "check for thermal throttling, or upgrade CPU."
                ),
                metrics={"cpu_percent": frame.cpu_utilization},
            )
            bottlenecks.append(cpu_bottleneck)
        elif frame.cpu_utilization > 75:
            # Check if GPU is low — might be CPU-bound at lower total load
            if frame.gpu_utilization < 60:
                cpu_bottleneck = Bottleneck(
                    name="Potential CPU Limitation",
                    severity="MEDIUM",
                    confidence=0.5,
                    description=(
                        f"CPU at {frame.cpu_utilization:.1f}% while GPU is only {frame.gpu_utilization:.1f}%. "
                        f"The CPU may be limiting frame delivery to the GPU."
                    ),
                    recommendation=(
                        "Check emulator CPU allocation. Reduce background CPU usage. "
                        "Verify emulator is not CPU-throttled by power settings."
                    ),
                    metrics={"cpu_percent": frame.cpu_utilization, "gpu_percent": frame.gpu_utilization},
                )
                bottlenecks.append(cpu_bottleneck)

        # --- GPU Bottleneck ---
        if frame.gpu_utilization > 90:
            severity = "CRITICAL" if frame.gpu_utilization > 97 else "HIGH"
            gpu_bottleneck = Bottleneck(
                name="GPU Limitation",
                severity=severity,
                confidence=min(1.0, (frame.gpu_utilization - 80) / 20),
                description=(
                    f"GPU utilization is {frame.gpu_utilization:.1f}%. The GPU is the primary "
                    f"performance bottleneck. Rendering is limited by GPU capacity."
                ),
                recommendation=(
                    "Reduce emulator resolution or graphics quality. Lower render scale. "
                    "Switch emulator renderer if available. Check for thermal throttling."
                ),
                metrics={"gpu_percent": frame.gpu_utilization},
            )
            bottlenecks.append(gpu_bottleneck)
        elif frame.gpu_utilization > 75 and frame.cpu_utilization < 50:
            gpu_bottleneck = Bottleneck(
                name="GPU Limitation (Moderate)",
                severity="MEDIUM",
                confidence=0.5,
                description=(
                    f"GPU at {frame.gpu_utilization:.1f}% while CPU is low ({frame.cpu_utilization:.1f}%). "
                    f"GPU is the limiting factor."
                ),
                recommendation=(
                    "Consider reducing emulator graphics settings or resolution."
                ),
                metrics={"gpu_percent": frame.gpu_utilization, "cpu_percent": frame.cpu_utilization},
            )
            bottlenecks.append(gpu_bottleneck)

        # --- Memory Pressure ---
        if frame.ram_percent > 90:
            mem_bottleneck = Bottleneck(
                name="Memory Pressure",
                severity="HIGH",
                confidence=min(1.0, (frame.ram_percent - 80) / 20),
                description=(
                    f"RAM usage is {frame.ram_percent:.1f}%. The system is under severe memory "
                    f"pressure, which causes page file usage and frame stutters."
                ),
                recommendation=(
                    "Close memory-heavy background applications. Increase emulator RAM allocation "
                    "if available. Consider adding physical RAM."
                ),
                metrics={"ram_percent": frame.ram_percent},
            )
            bottlenecks.append(mem_bottleneck)
        elif frame.ram_percent > 80:
            mem_bottleneck = Bottleneck(
                name="Memory Pressure (Moderate)",
                severity="MEDIUM",
                confidence=0.6,
                description=(
                    f"RAM usage is {frame.ram_percent:.1f}%. Memory pressure may cause "
                    f"intermittent stutters due to paging."
                ),
                recommendation=(
                    "Monitor memory usage. Close non-essential background applications."
                ),
                metrics={"ram_percent": frame.ram_percent},
            )
            bottlenecks.append(mem_bottleneck)

        # --- VRAM Pressure ---
        if frame.gpu_memory_total_mb > 0:
            vram_pct = (frame.gpu_memory_used_mb / frame.gpu_memory_total_mb) * 100
            if vram_pct > 90:
                vram_bottleneck = Bottleneck(
                    name="VRAM Pressure",
                    severity="HIGH",
                    confidence=min(1.0, (vram_pct - 80) / 20),
                    description=(
                        f"VRAM usage is {vram_pct:.1f}% ({frame.gpu_memory_used_mb:.0f}/"
                        f"{frame.gpu_memory_total_mb:.0f}MB). This can cause severe stutters "
                        f"as data is swapped to system RAM."
                    ),
                    recommendation=(
                        "Reduce emulator resolution and texture quality. "
                        "Disable high-resolution textures if available."
                    ),
                    metrics={"vram_percent": vram_pct},
                )
                bottlenecks.append(vram_bottleneck)

        # --- Thermal Throttling ---
        if frame.thermal_status == "THROTTLING":
            thermal_bottleneck = Bottleneck(
                name="Thermal Throttling",
                severity="CRITICAL",
                confidence=0.95,
                description=(
                    "Thermal throttling is actively reducing performance. "
                    "CPU/GPU clocks are being lowered to manage temperature."
                ),
                recommendation=(
                    "Improve cooling — increase case airflow, clean dust, "
                    "consider a laptop cooling pad. Reduce emulator resolution "
                    "and graphics settings to lower heat generation."
                ),
                metrics={
                    "cpu_temp": frame.cpu_temp,
                    "gpu_temp": frame.gpu_temp,
                },
            )
            bottlenecks.append(thermal_bottleneck)
        else:
            # Check individual temperatures
            if frame.gpu_temp is not None and frame.gpu_temp > 85:
                thermal_bottleneck = Bottleneck(
                    name="GPU Thermal Concern",
                    severity="MEDIUM",
                    confidence=0.7,
                    description=(
                        f"GPU temperature is {frame.gpu_temp:.0f}°C. "
                        f"Approaching thermal throttling threshold."
                    ),
                    recommendation="Monitor GPU temperature. Improve GPU cooling if possible.",
                    metrics={"gpu_temp": frame.gpu_temp},
                )
                bottlenecks.append(thermal_bottleneck)

            if frame.cpu_temp is not None and frame.cpu_temp > 85:
                thermal_bottleneck = Bottleneck(
                    name="CPU Thermal Concern",
                    severity="MEDIUM",
                    confidence=0.7,
                    description=(
                        f"CPU temperature is {frame.cpu_temp:.0f}°C. "
                        f"Approaching thermal throttling threshold."
                    ),
                    recommendation="Monitor CPU temperature. Improve CPU cooling if possible.",
                    metrics={"cpu_temp": frame.cpu_temp},
                )
                bottlenecks.append(thermal_bottleneck)

        # --- Balanced / No bottleneck ---
        if not bottlenecks:
            balanced = Bottleneck(
                name="No Bottleneck Detected",
                severity="NONE",
                confidence=0.8,
                description=(
                    f"No significant bottleneck detected. CPU: {frame.cpu_utilization:.1f}%, "
                    f"GPU: {frame.gpu_utilization:.1f}%, RAM: {frame.ram_percent:.1f}%. "
                    f"System appears balanced."
                ),
                recommendation="System is well-balanced. Monitor for changes.",
                metrics={
                    "cpu_percent": frame.cpu_utilization,
                    "gpu_percent": frame.gpu_utilization,
                    "ram_percent": frame.ram_percent,
                },
            )
            bottlenecks.append(balanced)

        # Sort by severity and confidence
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}
        bottlenecks.sort(key=lambda b: (severity_order.get(b.severity, 5), -b.confidence))

        result.bottlenecks = bottlenecks
        result.primary_bottleneck = bottlenecks[0] if bottlenecks else None

        # Calculate overall score
        result.overall_score = self._calculate_score(frame)
        result.performance_class = self._classify_performance(result.overall_score)

        self._analysis_history.append(result)
        logger.info(
            f"Analysis: {result.performance_class} ({result.overall_score:.1f}/100) "
            f"— Primary: {result.primary_bottleneck.name if result.primary_bottleneck else 'None'}"
        )

        return result

    def _calculate_score(self, frame: TelemetryFrame) -> float:
        """Calculate a 0-100 performance score from telemetry."""
        # Lower CPU/GPU/RAM usage generally means more headroom = better score
        # But too-low GPU usage while gaming means CPU bottleneck
        cpu_score = max(0, 100 - frame.cpu_utilization)
        gpu_score = max(0, 100 - frame.gpu_utilization)
        ram_score = max(0, 100 - frame.ram_percent)

        # Weighted average
        score = (cpu_score * 0.35 + gpu_score * 0.40 + ram_score * 0.25)

        # Thermal penalty
        if frame.thermal_status == "THROTTLING":
            score *= 0.6

        return max(0, min(100, score))

    def _classify_performance(self, score: float) -> str:
        """Classify performance based on score."""
        if score >= 75:
            return "EXCELLENT"
        elif score >= 55:
            return "GOOD"
        elif score >= 35:
            return "AVERAGE"
        elif score >= 15:
            return "BOTTLENECKED"
        else:
            return "SEVERE"

    def analyze_window(self, frames: list, window_seconds: int = 10) -> AnalysisResult:
        """
        Analyze a measurement window of telemetry frames.
        Uses sustained behavior over the window for more reliable bottleneck detection.
        """
        import statistics

        if not frames:
            return AnalysisResult()

        # Use only the last N seconds of frames
        cutoff = time.time() - window_seconds
        window = [f for f in frames if f.timestamp >= cutoff]
        if not window:
            window = frames[-30:]  # Fallback to last 30 frames

        n = len(window)

        # Calculate statistics
        cpu_vals = [f.cpu_utilization for f in window]
        gpu_vals = [f.gpu_utilization for f in window]
        ram_vals = [f.ram_percent for f in window]

        cpu_avg = statistics.mean(cpu_vals) if cpu_vals else 0
        gpu_avg = statistics.mean(gpu_vals) if gpu_vals else 0
        ram_avg = statistics.mean(ram_vals) if ram_vals else 0

        # Percentage of time above threshold
        cpu_above_90 = sum(1 for v in cpu_vals if v > 90) / max(1, n) * 100
        gpu_above_90 = sum(1 for v in gpu_vals if v > 90) / max(1, n) * 100
        ram_above_90 = sum(1 for v in ram_vals if v > 90) / max(1, n) * 100

        # Use the last frame for the AnalysisResult
        last_frame = window[-1]

        # Build bottleneck list based on windowed data
        bottlenecks = []

        if gpu_above_90 > 50:  # GPU above 90% for >50% of window
            confidence = min(0.99, 0.5 + (gpu_above_90 / 200))
            bottlenecks.append(Bottleneck(
                name="GPU Limitation",
                severity="HIGH" if gpu_above_90 > 80 else "MEDIUM",
                confidence=confidence,
                description=(
                    f"GPU utilization averaged {gpu_avg:.1f}% and was above 90% for {gpu_above_90:.0f}% of the "
                    f"{window_seconds}s measurement window. GPU rendering is the primary bottleneck."
                ),
                recommendation="Reduce emulator resolution/graphics settings. Check for thermal throttling.",
                metrics={"gpu_avg": gpu_avg, "gpu_above_90_pct": gpu_above_90},
            ))
        elif cpu_above_90 > 50 and gpu_avg < 70:
            confidence = min(0.99, 0.5 + (cpu_above_90 / 200))
            bottlenecks.append(Bottleneck(
                name="CPU Limitation",
                severity="HIGH" if cpu_above_90 > 80 else "MEDIUM",
                confidence=confidence,
                description=(
                    f"CPU utilization averaged {cpu_avg:.1f}% and was above 90% for {cpu_above_90:.0f}% of the "
                    f"{window_seconds}s window, while GPU averaged only {gpu_avg:.1f}%. "
                    f"CPU is limiting frame delivery to the GPU."
                ),
                recommendation="Reduce emulator CPU-heavy workload. Close background processes.",
                metrics={"cpu_avg": cpu_avg, "cpu_above_90_pct": cpu_above_90, "gpu_avg": gpu_avg},
            ))
        elif ram_above_90 > 30:
            bottlenecks.append(Bottleneck(
                name="Memory Pressure",
                severity="HIGH" if ram_above_90 > 60 else "MEDIUM",
                confidence=0.7,
                description=(
                    f"RAM usage averaged {ram_avg:.1f}% and was above 90% for {ram_above_90:.0f}% of the window. "
                    f"Memory pressure causes page file usage and frame stutters."
                ),
                recommendation="Close memory-heavy processes. Check emulator RAM allocation.",
                metrics={"ram_avg": ram_avg, "ram_above_90_pct": ram_above_90},
            ))

        # Check for thermal throttling across window
        gpu_temps = [f.gpu_temp for f in window if f.gpu_temp is not None]
        if gpu_temps:
            gpu_temp_avg = statistics.mean(gpu_temps)
            gpu_temp_max = max(gpu_temps)
            if gpu_temp_max > 90:
                bottlenecks.append(Bottleneck(
                    name="Thermal Throttling",
                    severity="CRITICAL",
                    confidence=0.9,
                    description=(
                        f"GPU temperature peaked at {gpu_temp_max:.0f}°C (avg {gpu_temp_avg:.0f}°C). "
                        f"Thermal throttling is actively reducing performance."
                    ),
                    recommendation="Improve cooling. Reduce emulator graphics settings.",
                    metrics={"gpu_temp_avg": gpu_temp_avg, "gpu_temp_max": gpu_temp_max},
                ))
            elif gpu_temp_max > 80:
                bottlenecks.append(Bottleneck(
                    name="GPU Thermal Concern",
                    severity="MEDIUM",
                    confidence=0.7,
                    description=f"GPU temperature peaked at {gpu_temp_max:.0f}°C — approaching throttling threshold.",
                    recommendation="Monitor GPU temperature.",
                    metrics={"gpu_temp_max": gpu_temp_max},
                ))

        # No bottleneck
        if not bottlenecks:
            bottlenecks.append(Bottleneck(
                name="No Bottleneck Detected",
                severity="NONE",
                confidence=0.8,
                description=(
                    f"Over {window_seconds}s: CPU avg {cpu_avg:.1f}%, GPU avg {gpu_avg:.1f}%, "
                    f"RAM avg {ram_avg:.1f}%. System is balanced."
                ),
                recommendation="System performing well.",
                metrics={"cpu_avg": cpu_avg, "gpu_avg": gpu_avg, "ram_avg": ram_avg},
            ))

        # Sort by severity
        severity_order = {"CRITICAL": 0, "HIGH": 1, "MEDIUM": 2, "LOW": 3, "NONE": 4}
        bottlenecks.sort(key=lambda b: (severity_order.get(b.severity, 5), -b.confidence))

        result = AnalysisResult(
            bottlenecks=bottlenecks,
            primary_bottleneck=bottlenecks[0] if bottlenecks else None,
            timestamp=time.time(),
        )
        result.overall_score = self._calculate_score(last_frame)
        result.performance_class = self._classify_performance(result.overall_score)

        logger.info(
            f"Window analysis ({window_seconds}s, {n} frames): "
            f"{result.performance_class} — {result.primary_bottleneck.name} "
            f"(confidence: {result.primary_bottleneck.confidence:.0%})"
        )

        return result

    def get_history(self, last_n: int = 10) -> list:
        """Get recent analysis history."""
        return self._analysis_history[-last_n:]


# Singleton
bottleneck_analyzer = BottleneckAnalyzer()
