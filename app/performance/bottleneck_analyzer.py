"""
Bottleneck correlation engine.

Analyzes synchronized telemetry samples to identify performance bottlenecks.
Uses evidence from multiple samples for reliable classification.
"""

import statistics
from typing import List, Optional, Tuple

from app.performance.telemetry_models import (
    BottleneckAssessment,
    BottleneckType,
    DataAvailability,
    PerformanceSummary,
    TelemetrySample,
)
from app.utils.logger import get_logger

logger = get_logger("performance.bottleneck_analyzer")

# Thresholds
GPU_SATURATION_THRESHOLD = 90.0     # GPU% above this = GPU-bound candidate
CPU_HIGH_THRESHOLD = 85.0           # CPU% above this = CPU-bound candidate
EMULATOR_CPU_HIGH = 80.0            # Emulator CPU% above this = high
RAM_PRESSURE_THRESHOLD = 85.0       # RAM used% above this = memory pressure
THERMAL_WARNING_THRESHOLD = 85.0    # GPU temp above this = thermal concern
FPS_LOW_RELATIVE = 0.7              # FPS below 70% of expected = low
MIN_SAMPLES_FOR_ANALYSIS = 5        # Minimum samples to classify


class BottleneckAnalyzer:
    """
    Analyzes synchronized telemetry data to identify performance bottlenecks.

    Uses multiple samples and metrics for evidence-based classification.
    """

    def __init__(self):
        pass

    def analyze_samples(
        self,
        samples: List[TelemetrySample],
        display_refresh: Optional[int] = None,
    ) -> BottleneckAssessment:
        """
        Analyze a list of telemetry samples to identify the primary bottleneck.

        Args:
            samples: List of telemetry samples (chronological)
            display_refresh: Monitor refresh rate for expected-FPS comparison

        Returns:
            BottleneckAssessment with type, confidence, evidence, recommendations
        """
        if not samples or len(samples) < MIN_SAMPLES_FOR_ANALYSIS:
            return BottleneckAssessment(
                bottleneck=BottleneckType.INSUFFICIENT_DATA,
                confidence=0,
                evidence=[f"Only {len(samples) if samples else 0} samples available, "
                          f"need {MIN_SAMPLES_FOR_ANALYSIS} minimum"],
                data_availability=DataAvailability.NOT_AVAILABLE,
            )

        # Calculate summary statistics
        summary = self._summarize(samples)

        # Collect evidence for each bottleneck type
        gpu_evidence = self._assess_gpu_bound(summary, samples)
        cpu_evidence = self._assess_cpu_bound(summary, samples)
        mem_evidence = self._assess_memory_bound(summary, samples)
        thermal_evidence = self._assess_thermal_limited(summary, samples)
        frame_evidence = self._assess_frame_instability(summary, samples)

        # Determine primary bottleneck (highest confidence)
        candidates = [
            (BottleneckType.GPU_BOUND, gpu_evidence),
            (BottleneckType.CPU_BOUND, cpu_evidence),
            (BottleneckType.MEMORY_BOUND, mem_evidence),
            (BottleneckType.THERMAL_LIMITED, thermal_evidence),
            (BottleneckType.FRAME_TIME_INSTABILITY, frame_evidence),
        ]

        # Filter out low-confidence candidates
        valid_candidates = [
            (bt, ev) for bt, ev in candidates if ev[0] > 0
        ]

        if not valid_candidates:
            # Check if we have any data at all
            has_any = (
                summary.avg_cpu_percent is not None
                or summary.avg_gpu_percent is not None
                or summary.avg_fps is not None
            )
            if has_any:
                return BottleneckAssessment(
                    bottleneck=BottleneckType.NO_CLEAR_BOTTLENECK,
                    confidence=60,
                    evidence=["No persistent resource bottleneck detected"],
                    recommendations=["System appears balanced — no specific optimization target identified"],
                    data_availability=DataAvailability.MEASURED,
                )
            else:
                return BottleneckAssessment(
                    bottleneck=BottleneckType.INSUFFICIENT_DATA,
                    confidence=0,
                    evidence=["No valid telemetry data collected"],
                    data_availability=DataAvailability.NOT_AVAILABLE,
                )

        # Select highest-confidence bottleneck
        valid_candidates.sort(key=lambda x: x[1][0], reverse=True)
        best_type, (confidence, evidence, recommendations) = valid_candidates[0]

        return BottleneckAssessment(
            bottleneck=best_type,
            confidence=min(confidence, 100),
            evidence=evidence,
            recommendations=recommendations,
            data_availability=DataAvailability.MEASURED,
        )

    def _summarize(self, samples: List[TelemetrySample]) -> PerformanceSummary:
        """Calculate summary from samples."""
        from app.performance.telemetry_collector import TelemetryCollector
        collector = TelemetryCollector()
        return collector._summarize(samples)

    def _assess_gpu_bound(
        self, summary: PerformanceSummary, samples: List[TelemetrySample]
    ) -> Tuple[int, List[str], List[str]]:
        """Assess GPU-bound evidence. Returns (confidence, evidence, recommendations)."""
        confidence = 0
        evidence = []
        recommendations = []

        gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
        cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
        emu_cpu_vals = [s.emulator_cpu_percent for s in samples if s.emulator_cpu_percent is not None]

        if not gpu_vals:
            return 0, [], []

        avg_gpu = statistics.mean(gpu_vals)
        peak_gpu = max(gpu_vals)

        # GPU saturation
        if avg_gpu >= GPU_SATURATION_THRESHOLD:
            confidence += 40
            evidence.append(f"GPU utilization averaged {avg_gpu:.1f}% (sustained saturation)")

            if peak_gpu >= 98:
                confidence += 15
                evidence.append(f"GPU peaked at {peak_gpu:.1f}% (hard saturation)")
        elif avg_gpu >= 75:
            confidence += 15
            evidence.append(f"GPU utilization averaged {avg_gpu:.1f}% (elevated)")

        # CPU headroom while GPU is saturated
        if cpu_vals:
            avg_cpu = statistics.mean(cpu_vals)
            if avg_gpu >= 80 and avg_cpu < 60:
                confidence += 20
                evidence.append(f"CPU has headroom ({avg_cpu:.1f}% avg) while GPU is loaded ({avg_gpu:.1f}%)")

        if emu_cpu_vals:
            avg_emu_cpu = statistics.mean(emu_cpu_vals)
            if avg_gpu >= 80 and avg_emu_cpu < 50:
                confidence += 10
                evidence.append(f"Emulator CPU ({avg_emu_cpu:.1f}%) low relative to GPU load")

        if confidence >= 30:
            recommendations.append(
                "GPU appears to be the limiting factor. "
                "Consider reducing emulator graphics quality, resolution, or rendering mode."
            )

        return confidence, evidence, recommendations

    def _assess_cpu_bound(
        self, summary: PerformanceSummary, samples: List[TelemetrySample]
    ) -> Tuple[int, List[str], List[str]]:
        """Assess CPU-bound evidence."""
        confidence = 0
        evidence = []
        recommendations = []

        cpu_vals = [s.cpu_total_percent for s in samples if s.cpu_total_percent is not None]
        gpu_vals = [s.gpu_utilization_percent for s in samples if s.gpu_utilization_percent is not None]
        emu_cpu_vals = [s.emulator_cpu_percent for s in samples if s.emulator_cpu_percent is not None]

        if not cpu_vals:
            return 0, [], []

        avg_cpu = statistics.mean(cpu_vals)
        peak_cpu = max(cpu_vals)

        # High CPU utilization
        if avg_cpu >= CPU_HIGH_THRESHOLD:
            confidence += 35
            evidence.append(f"System CPU averaged {avg_cpu:.1f}% (sustained high)")
            if peak_cpu >= 95:
                confidence += 15
                evidence.append(f"CPU peaked at {peak_cpu:.1f}%")
        elif avg_cpu >= 70:
            confidence += 10
            evidence.append(f"System CPU averaged {avg_cpu:.1f}% (elevated)")

        # High emulator CPU
        if emu_cpu_vals:
            avg_emu = statistics.mean(emu_cpu_vals)
            if avg_emu >= EMULATOR_CPU_HIGH:
                confidence += 20
                evidence.append(f"Emulator CPU averaged {avg_emu:.1f}% (high)")

        # GPU headroom while CPU is loaded
        if gpu_vals:
            avg_gpu = statistics.mean(gpu_vals)
            if avg_cpu >= 75 and avg_gpu < 50:
                confidence += 20
                evidence.append(f"GPU has headroom ({avg_gpu:.1f}%) while CPU is loaded ({avg_cpu:.1f}%)")

        if confidence >= 30:
            recommendations.append(
                "CPU appears to be the limiting factor. "
                "Check for background CPU consumers and emulator CPU allocation."
            )

        return confidence, evidence, recommendations

    def _assess_memory_bound(
        self, summary: PerformanceSummary, samples: List[TelemetrySample]
    ) -> Tuple[int, List[str], List[str]]:
        """Assess memory-bound evidence."""
        confidence = 0
        evidence = []
        recommendations = []

        ram_used = [s.system_ram_used_mb for s in samples if s.system_ram_used_mb is not None]
        ram_total = [s.system_ram_total_mb for s in samples if s.system_ram_total_mb is not None]
        ram_avail = [s.system_ram_available_mb for s in samples if s.system_ram_available_mb is not None]

        if not ram_used or not ram_total:
            return 0, [], []

        avg_used = statistics.mean(ram_used)
        total = ram_total[0]

        if total <= 0:
            return 0, [], []

        used_percent = (avg_used / total) * 100

        # High memory pressure
        if used_percent >= RAM_PRESSURE_THRESHOLD:
            confidence += 35
            evidence.append(f"RAM usage averaged {used_percent:.1f}% ({avg_used:.0f}/{total:.0f} MB)")

            if ram_avail:
                min_avail = min(ram_avail)
                if min_avail < 1024:
                    confidence += 20
                    evidence.append(f"Available RAM dropped to {min_avail:.0f} MB (critically low)")
                elif min_avail < 2048:
                    confidence += 10
                    evidence.append(f"Available RAM dropped to {min_avail:.0f} MB (low)")
        elif used_percent >= 75:
            confidence += 10
            evidence.append(f"RAM usage averaged {used_percent:.1f}% (elevated)")

        # Emulator memory consumption
        emu_ram = [s.emulator_ram_mb for s in samples if s.emulator_ram_mb is not None]
        if emu_ram:
            avg_emu = statistics.mean(emu_ram)
            emu_percent = (avg_emu / total) * 100
            if emu_percent > 40:
                confidence += 10
                evidence.append(f"Emulator using {emu_percent:.1f}% of total RAM ({avg_emu:.0f} MB)")

        if confidence >= 30:
            recommendations.append(
                "System memory pressure is high. "
                "Close unnecessary background applications to free RAM for the emulator."
            )

        return confidence, evidence, recommendations

    def _assess_thermal_limited(
        self, summary: PerformanceSummary, samples: List[TelemetrySample]
    ) -> Tuple[int, List[str], List[str]]:
        """Assess thermal throttling evidence."""
        confidence = 0
        evidence = []
        recommendations = []

        gpu_temps = [s.gpu_temperature_c for s in samples if s.gpu_temperature_c is not None]
        cpu_temps = [s.cpu_temperature_c for s in samples if s.cpu_temperature_c is not None]

        # GPU thermal
        if gpu_temps:
            max_gpu = max(gpu_temps)
            avg_gpu = statistics.mean(gpu_temps)

            if max_gpu >= 90:
                confidence += 40
                evidence.append(f"GPU temperature peaked at {max_gpu:.0f}°C (thermal throttling likely)")
            elif max_gpu >= THERMAL_WARNING_THRESHOLD:
                confidence += 25
                evidence.append(f"GPU temperature peaked at {max_gpu:.0f}°C (approaching throttle)")
            elif max_gpu >= 80:
                confidence += 10
                evidence.append(f"GPU temperature averaged {avg_gpu:.0f}°C (warm)")

            # Temperature trend — rising temps indicate thermal buildup
            if len(gpu_temps) >= 10:
                first_half = statistics.mean(gpu_temps[:len(gpu_temps) // 2])
                second_half = statistics.mean(gpu_temps[len(gpu_temps) // 2:])
                if second_half - first_half > 5:
                    confidence += 10
                    evidence.append(f"GPU temperature rising ({first_half:.0f}→{second_half:.0f}°C)")

        # CPU thermal
        if cpu_temps:
            max_cpu = max(cpu_temps)
            if max_cpu >= 90:
                confidence += 25
                evidence.append(f"CPU temperature peaked at {max_cpu:.0f}°C")
            elif max_cpu >= 85:
                confidence += 10
                evidence.append(f"CPU temperature peaked at {max_cpu:.0f}°C (warm)")

        if confidence >= 30:
            recommendations.append(
                "Thermal conditions may be limiting performance. "
                "Improve case airflow or reduce emulator graphics settings."
            )

        return confidence, evidence, recommendations

    def _assess_frame_instability(
        self, summary: PerformanceSummary, samples: List[TelemetrySample]
    ) -> Tuple[int, List[str], List[str]]:
        """Assess frame-time instability evidence."""
        confidence = 0
        evidence = []
        recommendations = []

        ft_vals = [s.frame_time_ms for s in samples if s.frame_time_ms is not None and s.frame_time_ms > 0]

        if not ft_vals or len(ft_vals) < 3:
            return 0, [], []

        avg_ft = statistics.mean(ft_vals)
        if avg_ft <= 0:
            return 0, [], []

        cv = statistics.stdev(ft_vals) / avg_ft if len(ft_vals) > 1 else 0
        spikes = sum(1 for ft in ft_vals if ft > avg_ft * 2)

        # High coefficient of variation
        if cv > 0.5:
            confidence += 35
            evidence.append(f"Frame time variation is high (CV={cv:.2f})")
        elif cv > 0.3:
            confidence += 15
            evidence.append(f"Frame time variation is moderate (CV={cv:.2f})")

        # Many spikes
        spike_pct = (spikes / len(ft_vals)) * 100 if ft_vals else 0
        if spike_pct > 10:
            confidence += 25
            evidence.append(f"Frame spikes: {spikes}/{len(ft_vals)} frames ({spike_pct:.1f}%)")
        elif spike_pct > 5:
            confidence += 10
            evidence.append(f"Moderate frame spikes: {spikes}/{len(ft_vals)} frames ({spike_pct:.1f}%)")

        # Stability score
        if summary.stability_score > 0 and summary.stability_score < 50:
            confidence += 15
            evidence.append(f"Stability score: {summary.stability_score:.0f}/100 ({summary.stability_rating})")

        if confidence >= 30:
            recommendations.append(
                "Frame delivery is inconsistent. "
                "Investigate background interference, thermal throttling, or emulator scheduling."
            )

        return confidence, evidence, recommendations


# Singleton
bottleneck_analyzer = BottleneckAnalyzer()
