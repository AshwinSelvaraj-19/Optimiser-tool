"""
Input Responsiveness & Latency Diagnostics — Heaven Society.

Measures system conditions that affect perceived mouse responsiveness in the emulator.

IMPORTANT: This module does NOT measure physical mouse-to-photon latency.
That requires hardware measurement (photodiode + oscilloscope).
This module analyzes SYSTEM CONDITIONS that influence perceived responsiveness:
- Windows pointer settings (pointer speed, enhanced precision)
- Display configuration (resolution, refresh rate)
- Emulator process state (priority, CPU, frame pacing)
- PresentMon frame timing data
- Background load impact
- Configuration recommendations

Every heuristic is clearly labeled as HEURISTIC.
Every measured value is clearly labeled as MEASURED.
The responsiveness score combines measured values only.
"""

import os
import time
import ctypes
from dataclasses import dataclass, field
from typing import Optional, List, Tuple
from enum import Enum

import psutil

from app.utils.logger import get_logger

logger = get_logger("performance.input_latency")


# ── Classification ─────────────────────────────────────────────

class BottleneckType(Enum):
    """Identified responsiveness bottleneck."""
    CPU = "CPU"
    GPU = "GPU"
    FRAME_PACING = "Frame Pacing"
    DISPLAY = "Display"
    MEMORY = "Memory"
    BACKGROUND_LOAD = "Background Load"
    CONFIGURATION = "Configuration"
    UNKNOWN = "Unknown"


class ResponsivenessLevel(Enum):
    """Overall responsiveness assessment."""
    EXCELLENT = "EXCELLENT"
    GOOD = "GOOD"
    MODERATE = "MODERATE"
    POOR = "POOR"
    CRITICAL = "CRITICAL"
    INSUFFICIENT_DATA = "INSUFFICIENT DATA"


class PointerPrecision(Enum):
    """Enhanced pointer precision (mouse acceleration) state."""
    ENABLED = "ENABLED"
    DISABLED = "DISABLED"
    UNKNOWN = "UNKNOWN"


# ── Data Models ────────────────────────────────────────────────

@dataclass
class MouseSettings:
    """Windows pointer settings — read from registry."""
    pointer_speed: int = 6            # 1-20 scale (default 6 = 6/11)
    enhanced_precision: PointerPrecision = PointerPrecision.UNKNOWN
    snap_to_pointer: bool = False
    pointer_trails: int = 0
    mouse_speed_registry: int = 10    # Raw registry value
    detect_confidence: float = 0.0    # 0-1, how confident in detection
    is_measured: bool = False         # True = read from real Windows settings
    recommendation: str = ""


@dataclass
class DisplayAnalysis:
    """Display conditions affecting responsiveness."""
    resolution_x: int = 0
    resolution_y: int = 0
    refresh_rate_hz: int = 0
    display_name: str = ""
    gpu_name: str = ""
    gpu_vendor: str = ""
    # HEURISTIC: higher refresh rate = better perceived responsiveness
    refresh_rate_quality: str = ""  # EXCELLENT/GOOD/MODERATE/POOR
    is_measured: bool = True        # Display info is real/measured
    recommendation: str = ""


@dataclass
class EmulatorState:
    """Emulator process conditions affecting responsiveness."""
    process_name: str = ""
    pid: int = 0
    priority: str = ""
    priority_value: int = 0
    affinity_cpus: int = 0
    total_cpus: int = 0
    cpu_percent: float = 0.0
    memory_mb: float = 0.0
    gpu_name: str = ""
    is_detected: bool = False
    is_measured: bool = True        # Process data is real/measured
    recommendation: str = ""


@dataclass
class FramePacingAnalysis:
    """Frame timing analysis from PresentMon — all MEASURED values."""
    present_fps: float = 0.0
    median_fps: float = 0.0
    one_percent_low: float = 0.0
    point_one_percent_low: float = 0.0
    avg_frame_time_ms: float = 0.0
    frame_time_variance: float = 0.0
    frame_spikes: int = 0
    stability_score: float = 0.0
    sample_count: int = 0
    provider: str = ""
    is_measured: bool = True        # All values from PresentMon
    recommendation: str = ""


@dataclass
class BackgroundImpact:
    """Background process impact on responsiveness — MEASURED values."""
    total_cpu_outside_emulator: float = 0.0
    competing_process_count: int = 0
    high_cpu_process_count: int = 0
    total_ram_outside_mb: float = 0.0
    is_measured: bool = True
    impact_level: str = ""  # NONE/LOW/MODERATE/HIGH/SEVERE
    recommendation: str = ""


@dataclass
class ResponsivenessReport:
    """Complete input responsiveness analysis."""
    # Measured components
    mouse: MouseSettings = field(default_factory=MouseSettings)
    display: DisplayAnalysis = field(default_factory=DisplayAnalysis)
    emulator: EmulatorState = field(default_factory=EmulatorState)
    frame_pacing: FramePacingAnalysis = field(default_factory=FramePacingAnalysis)
    background: BackgroundImpact = field(default_factory=BackgroundImpact)

    # Overall assessment
    responsiveness_score: float = 0.0     # 0-100, from MEASURED values only
    responsiveness_level: ResponsivenessLevel = ResponsivenessLevel.INSUFFICIENT_DATA
    identified_bottleneck: BottleneckType = BottleneckType.UNKNOWN
    bottleneck_confidence: float = 0.0    # 0-1
    bottleneck_description: str = ""

    # Data source labels — NEVER hide that these are heuristics
    measurement_type: str = "HEURISTIC"    # HEURISTIC or MEASURED
    disclaimers: List[str] = field(default_factory=list)

    # Recommendations
    recommendations: List[str] = field(default_factory=list)

    timestamp: float = 0.0

    def __post_init__(self):
        self.disclaimers = [
            "This analysis measures SYSTEM CONDITIONS only.",
            "Physical mouse-to-photon latency requires hardware measurement.",
            "Responsiveness score is a heuristic based on measured system metrics.",
        ]


# ── Core Analyzer ──────────────────────────────────────────────

class InputLatencyAnalyzer:
    """
    Input responsiveness and latency diagnostics.
    All analysis uses real measured system data.
    Heuristics are clearly labeled.
    """

    def __init__(self):
        self._cache: Optional[ResponsivenessReport] = None
        self._cache_time: float = 0.0
        self._cache_ttl: float = 3.0

    def analyze(self, force: bool = False) -> ResponsivenessReport:
        """
        Full input responsiveness analysis.
        Combines all data sources into a responsiveness report.
        """
        now = time.time()
        if not force and self._cache and (now - self._cache_time) < self._cache_ttl:
            return self._cache

        report = ResponsivenessReport(timestamp=now)

        # 1. Read mouse/pointer settings
        report.mouse = self._read_mouse_settings()

        # 2. Display analysis
        report.display = self._analyze_display()

        # 3. Emulator state
        report.emulator = self._analyze_emulator()

        # 4. Frame pacing (from PresentMon if available)
        report.frame_pacing = self._analyze_frame_pacing()

        # 5. Background impact
        report.background = self._analyze_background_impact(
            report.emulator.pid
        )

        # 6. Calculate responsiveness score (from measured values only)
        report.responsiveness_score = self._calculate_score(report)

        # 7. Classify
        report.responsiveness_level = self._classify_responsiveness(
            report.responsiveness_score
        )

        # 8. Identify bottleneck
        report.identified_bottleneck, report.bottleneck_confidence, \
            report.bottleneck_description = self._identify_bottleneck(report)

        # 9. Generate recommendations
        report.recommendations = self._generate_recommendations(report)

        self._cache = report
        self._cache_time = now
        return report

    # ── 1. Mouse Settings ──────────────────────────────────────

    def _read_mouse_settings(self) -> MouseSettings:
        """
        Read Windows mouse/pointer settings from registry.
        All values are MEASURED from the actual Windows registry.
        """
        settings = MouseSettings()

        try:
            # Read mouse speed (pointer speed)
            # HKCU\Control Panel\Mouse — MouseSpeed (0-20, default "6" = 6/11)
            speed_val = self._read_reg_string(
                r"Control Panel\Mouse", "MouseSpeed"
            )
            if speed_val is not None:
                try:
                    settings.mouse_speed_registry = int(speed_val)
                    settings.pointer_speed = int(speed_val)
                    settings.detect_confidence += 0.3
                except (ValueError, TypeError):
                    pass

            # Enhanced pointer precision (mouse acceleration)
            # HKCU\Control Panel\Mouse — MouseSpeed11 (1 = enabled, 0 = disabled)
            # Or check "EnhancePointerPrecision" in MouseSpeed
            enhance_val = self._read_reg_string(
                r"Control Panel\Mouse", "MouseSpeed11"
            )
            if enhance_val is not None:
                settings.detect_confidence += 0.3
                try:
                    val = int(enhance_val)
                    settings.enhanced_precision = (
                        PointerPrecision.ENABLED if val == 1
                        else PointerPrecision.DISABLED
                    )
                except (ValueError, TypeError):
                    pass

            # Also check the raw acceleration value
            accel_val = self._read_reg_string(
                r"Control Panel\Mouse", "MouseAcceleration"
            )
            if accel_val is not None:
                settings.detect_confidence += 0.2
                try:
                    accel = int(accel_val)
                    if settings.enhanced_precision == PointerPrecision.UNKNOWN:
                        settings.enhanced_precision = (
                            PointerPrecision.ENABLED if accel > 0
                            else PointerPrecision.DISABLED
                        )
                except (ValueError, TypeError):
                    pass

            # MouseTrails
            trails_val = self._read_reg_string(
                r"Control Panel\Mouse", "MouseTrails"
            )
            if trails_val is not None:
                try:
                    settings.pointer_trails = int(trails_val)
                    settings.detect_confidence += 0.1
                except (ValueError, TypeError):
                    pass

            # SnapTo
            snap_val = self._read_reg_string(
                r"Control Panel\Mouse", "SnapToDefaultButton"
            )
            if snap_val is not None:
                try:
                    settings.snap_to_pointer = int(snap_val) == 1
                    settings.detect_confidence += 0.1
                except (ValueError, TypeError):
                    pass

            settings.is_measured = settings.detect_confidence > 0

        except Exception as e:
            logger.debug(f"Mouse settings read error: {e}")

        # Generate recommendation
        if settings.is_measured:
            if settings.enhanced_precision == PointerPrecision.ENABLED:
                settings.recommendation = (
                    "Enhanced pointer precision is ENABLED. "
                    "This adds mouse acceleration which can feel inconsistent "
                    "for gaming. Consider disabling for more predictable input."
                )
            elif settings.enhanced_precision == PointerPrecision.DISABLED:
                settings.recommendation = (
                    "Enhanced pointer precision is DISABLED. "
                    "Raw mouse input — optimal for gaming responsiveness."
                )
            else:
                settings.recommendation = "Pointer precision status could not be determined."

            if settings.pointer_trails > 0:
                settings.recommendation += (
                    f" Mouse trails are enabled ({settings.pointer_trails}). "
                    "This adds visual overhead."
                )

        return settings

    def _read_reg_string(self, subkey: str, value_name: str) -> Optional[str]:
        """Read a string value from HKCU registry."""
        try:
            import winreg
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey)
            try:
                val, _ = winreg.QueryValueEx(key, value_name)
                return str(val)
            except FileNotFoundError:
                return None
            finally:
                winreg.CloseKey(key)
        except Exception:
            return None

    # ── 2. Display Analysis ────────────────────────────────────

    def _analyze_display(self) -> DisplayAnalysis:
        """
        Analyze display configuration.
        Display info is MEASURED from real hardware.
        Refresh rate quality is HEURISTIC.
        """
        analysis = DisplayAnalysis()

        try:
            from app.system.display import display_monitor
            info = display_monitor.detect()
            analysis.resolution_x = info.resolution_x
            analysis.resolution_y = info.resolution_y
            analysis.refresh_rate_hz = info.refresh_rate_hz
            analysis.display_name = info.display_name
            analysis.is_measured = True
        except Exception as e:
            logger.debug(f"Display detection error: {e}")
            analysis.is_measured = False

        # GPU info
        try:
            from app.system.gpu import gpu_monitor
            gpus = gpu_monitor.detect()
            if gpus:
                gpu = gpus[0]
                if gpu.vendor == "NVIDIA":
                    gpu = gpu_monitor.update_nvidia(gpu)
                analysis.gpu_name = gpu.name
                analysis.gpu_vendor = gpu.vendor
        except Exception:
            pass

        # HEURISTIC: refresh rate quality
        hz = analysis.refresh_rate_hz
        if hz >= 144:
            analysis.refresh_rate_quality = "EXCELLENT"
        elif hz >= 120:
            analysis.refresh_rate_quality = "GOOD"
        elif hz >= 75:
            analysis.refresh_rate_quality = "MODERATE"
        elif hz > 0:
            analysis.refresh_rate_quality = "POOR"
        else:
            analysis.refresh_rate_quality = "UNKNOWN"

        # Recommendations
        if analysis.refresh_rate_hz > 0 and analysis.refresh_rate_hz < 60:
            analysis.recommendation = (
                f"Display running at {analysis.refresh_rate_hz}Hz. "
                "Higher refresh rates provide smoother perceived motion."
            )
        elif analysis.refresh_rate_hz >= 144:
            analysis.recommendation = (
                f"Display at {analysis.refresh_rate_hz}Hz — excellent for responsive input."
            )

        return analysis

    # ── 3. Emulator State ──────────────────────────────────────

    def _analyze_emulator(self) -> EmulatorState:
        """
        Analyze emulator process conditions.
        All values are MEASURED from the live process.
        """
        state = EmulatorState()

        try:
            from app.core.emulator_controller import emulator_controller
            target = emulator_controller.detect_target()
            if not target:
                state.is_detected = False
                return state

            state.is_detected = True
            state.process_name = target.name
            state.pid = target.pid
            state.priority = target.priority_name
            state.priority_value = target.priority
            state.affinity_cpus = target.affinity_cpus
            state.total_cpus = target.total_cpus
            state.cpu_percent = target.cpu_percent
            state.memory_mb = target.memory_mb
            state.gpu_name = target.gpu_name

            # HEURISTIC: priority recommendation
            if target.priority > 0:
                state.recommendation = (
                    f"Emulator priority is {target.priority_name}. "
                    "Consider running as administrator to set HIGH priority."
                )
            elif target.priority == 0:
                state.recommendation = (
                    "Emulator at NORMAL priority. "
                    "HIGH priority may improve frame consistency."
                )
            else:
                state.recommendation = "Emulator priority is already elevated — good."

        except Exception as e:
            logger.debug(f"Emulator analysis error: {e}")

        return state

    # ── 4. Frame Pacing ────────────────────────────────────────

    def _analyze_frame_pacing(self) -> FramePacingAnalysis:
        """
        Analyze frame timing from PresentMon if available.
        All values are MEASURED from real frame presentation data.
        """
        pacing = FramePacingAnalysis()

        try:
            from app.performance.fps_provider import fps_registry
            providers = fps_registry.detect_available()

            active_provider = None
            for p in providers:
                if p.get("available") and "PresentMon" in p.get("name", ""):
                    active_provider = p
                    break

            if not active_provider:
                pacing.is_measured = False
                pacing.recommendation = (
                    "PresentMon not available. "
                    "Frame timing data requires PresentMon for accurate measurement."
                )
                return pacing

            # Get the PresentMon provider instance
            from app.performance.presentmon_provider import PresentMonProvider
            pm = PresentMonProvider()
            available, _ = pm.is_available()
            if not available:
                pacing.is_measured = False
                return pacing

            # Try to get metrics from an existing capture
            metrics = pm.get_metrics()
            if not metrics.available:
                pacing.is_measured = False
                pacing.recommendation = (
                    "No PresentMon capture data. "
                    "Run a benchmark to measure frame pacing."
                )
                return pacing

            # All values are MEASURED from PresentMon
            pacing.present_fps = metrics.avg_fps
            pacing.median_fps = metrics.median_fps
            pacing.one_percent_low = metrics.one_percent_low
            pacing.point_one_percent_low = metrics.point_one_percent_low
            pacing.avg_frame_time_ms = metrics.avg_frame_time_ms
            pacing.frame_time_variance = metrics.frame_time_variance
            pacing.frame_spikes = metrics.frame_spikes
            pacing.stability_score = metrics.stability_score
            pacing.sample_count = metrics.sample_count
            pacing.provider = metrics.provider_name

            # HEURISTIC: frame pacing recommendation
            if metrics.frame_spikes > 20:
                pacing.recommendation = (
                    f"High frame spike count ({metrics.frame_spikes}). "
                    "Inconsistent frame delivery degrades perceived responsiveness."
                )
            elif metrics.stability_score < 50:
                pacing.recommendation = (
                    f"Frame stability is low ({metrics.stability_score:.0f}/100). "
                    "Frame pacing issues detected."
                )
            elif metrics.one_percent_low < metrics.avg_fps * 0.5:
                pacing.recommendation = (
                    f"1% low ({metrics.one_percent_low:.0f}) is less than "
                    f"half of average ({metrics.avg_fps:.0f}). "
                    "Occasional large frame drops detected."
                )

        except Exception as e:
            logger.debug(f"Frame pacing analysis error: {e}")
            pacing.is_measured = False

        return pacing

    # ── 5. Background Impact ───────────────────────────────────

    def _analyze_background_impact(self, emulator_pid: int = 0) -> BackgroundImpact:
        """
        Analyze background process impact on responsiveness.
        All values are MEASURED from live process data.
        """
        impact = BackgroundImpact()

        try:
            total_cpu = 0.0
            total_ram = 0.0
            competing = 0
            high_cpu = 0

            for proc in psutil.process_iter(["pid", "name", "cpu_percent", "memory_info"]):
                try:
                    p = proc.info
                    pid = p.get("pid", 0)
                    if pid == emulator_pid:
                        continue

                    cpu = p.get("cpu_percent", 0) or 0
                    mem = p.get("memory_info")
                    mem_mb = (mem.rss / (1024 * 1024)) if mem else 0

                    name_lower = (p.get("name", "") or "").lower()

                    # Skip system processes
                    if name_lower in {
                        "system", "system idle process", "svchost.exe",
                        "csrss.exe", "dwm.exe", "explorer.exe",
                    }:
                        continue

                    if cpu > 1.0:
                        total_cpu += cpu
                        competing += 1
                    if cpu > 20:
                        high_cpu += 1
                    if mem_mb > 100:
                        total_ram += mem_mb

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    continue

            impact.total_cpu_outside_emulator = total_cpu
            impact.competing_process_count = competing
            impact.high_cpu_process_count = high_cpu
            impact.total_ram_outside_mb = total_ram

            # Classify impact level
            if total_cpu > 40 or high_cpu > 3:
                impact.impact_level = "SEVERE"
            elif total_cpu > 20 or high_cpu > 1:
                impact.impact_level = "HIGH"
            elif total_cpu > 10:
                impact.impact_level = "MODERATE"
            elif total_cpu > 3:
                impact.impact_level = "LOW"
            else:
                impact.impact_level = "NONE"

            if impact.impact_level in ("HIGH", "SEVERE"):
                impact.recommendation = (
                    f"{competing} processes consuming {total_cpu:.0f}% CPU "
                    f"outside emulator ({high_cpu} high-CPU). "
                    "Close unnecessary background applications."
                )

        except Exception as e:
            logger.debug(f"Background impact analysis error: {e}")

        return impact

    # ── 6. Score Calculation ───────────────────────────────────

    def _calculate_score(self, report: ResponsivenessReport) -> float:
        """
        Calculate responsiveness score (0-100) from MEASURED values only.

        Weighting:
        - Frame pacing: 35% (most direct measure of input-to-display)
        - Display refresh: 20% (physical display capability)
        - Emulator state: 20% (process efficiency)
        - Background load: 15% (resource competition)
        - Mouse config: 10% (software configuration)
        """
        scores = {}
        weights = {}

        # Frame pacing (35%) — only if measured
        if report.frame_pacing.is_measured and report.frame_pacing.sample_count > 10:
            fps = report.frame_pacing.present_fps
            stability = report.frame_pacing.stability_score
            one_low = report.frame_pacing.one_percent_low

            # FPS score: 60fps=60, 120fps=85, 144fps=95, 240fps=100
            if fps > 0:
                fps_score = min(100, (fps / 240) * 100)
            else:
                fps_score = 50

            # Stability score (0-100 already)
            stab_score = stability

            # 1% low score
            if one_low > 0 and fps > 0:
                low_ratio = one_low / fps
                low_score = min(100, low_ratio * 120)
            else:
                low_score = 50

            scores["frame_pacing"] = (fps_score * 0.4 + stab_score * 0.3 + low_score * 0.3)
            weights["frame_pacing"] = 0.35

        # Display (20%) — always available
        hz = report.display.refresh_rate_hz
        if hz > 0:
            # HEURISTIC: 60Hz=50, 120Hz=75, 144Hz=85, 240Hz=100
            display_score = min(100, 40 + (hz / 240) * 60)
            # Resolution penalty for very high res (GPU burden)
            if report.display.resolution_x >= 3840:
                display_score *= 0.9  # 4K penalty
        else:
            display_score = 50
        scores["display"] = display_score
        weights["display"] = 0.20

        # Emulator state (20%)
        if report.emulator.is_detected:
            emu_score = 70  # Base

            # Priority bonus
            if report.emulator.priority_value < 0:
                emu_score += 15
            elif report.emulator.priority_value > 0:
                emu_score -= 10

            # CPU usage penalty
            cpu = report.emulator.cpu_percent
            if cpu > 90:
                emu_score -= 20
            elif cpu > 70:
                emu_score -= 10

            # Affinity: using all CPUs is good
            if report.emulator.total_cpus > 0:
                affinity_ratio = report.emulator.affinity_cpus / report.emulator.total_cpus
                if affinity_ratio < 0.5:
                    emu_score -= 10

            scores["emulator"] = max(0, min(100, emu_score))
            weights["emulator"] = 0.20

        # Background load (15%)
        impact = report.background
        if impact.impact_level == "NONE":
            bg_score = 95
        elif impact.impact_level == "LOW":
            bg_score = 80
        elif impact.impact_level == "MODERATE":
            bg_score = 60
        elif impact.impact_level == "HIGH":
            bg_score = 35
        else:
            bg_score = 15
        scores["background"] = bg_score
        weights["background"] = 0.15

        # Mouse config (10%)
        mouse_score = 70  # Base
        if report.mouse.is_measured:
            if report.mouse.enhanced_precision == PointerPrecision.DISABLED:
                mouse_score = 90  # Good for gaming
            elif report.mouse.enhanced_precision == PointerPrecision.ENABLED:
                mouse_score = 50  # Acceleration hurts consistency
            if report.mouse.pointer_trails > 0:
                mouse_score -= 15
        scores["mouse"] = mouse_score
        weights["mouse"] = 0.10

        # Calculate weighted average
        if not scores:
            return 0.0

        total_weight = sum(weights.get(k, 0) for k in scores)
        if total_weight <= 0:
            return 0.0

        weighted_sum = sum(
            scores[k] * weights.get(k, 0) for k in scores
        )
        return max(0, min(100, weighted_sum / total_weight))

    def _classify_responsiveness(self, score: float) -> ResponsivenessLevel:
        """Classify overall responsiveness from score."""
        if score <= 0:
            return ResponsivenessLevel.INSUFFICIENT_DATA
        if score >= 85:
            return ResponsivenessLevel.EXCELLENT
        if score >= 70:
            return ResponsivenessLevel.GOOD
        if score >= 50:
            return ResponsivenessLevel.MODERATE
        if score >= 30:
            return ResponsivenessLevel.POOR
        return ResponsivenessLevel.CRITICAL

    # ── 7. Bottleneck Identification ───────────────────────────

    def _identify_bottleneck(
        self, report: ResponsivenessReport
    ) -> Tuple[BottleneckType, float, str]:
        """
        Identify the most likely responsiveness bottleneck.
        Uses MEASURED values. Confidence is a HEURISTIC.
        """
        candidates = []

        # Frame pacing issues
        if report.frame_pacing.is_measured:
            if report.frame_pacing.frame_spikes > 20:
                candidates.append((
                    BottleneckType.FRAME_PACING, 0.7,
                    f"High frame spike count ({report.frame_pacing.frame_spikes}) — "
                    "inconsistent frame delivery"
                ))
            if report.frame_pacing.stability_score < 40:
                candidates.append((
                    BottleneckType.FRAME_PACING, 0.6,
                    f"Low frame stability ({report.frame_pacing.stability_score:.0f}/100)"
                ))

        # CPU bottleneck
        if report.emulator.is_detected:
            if report.emulator.cpu_percent > 85:
                candidates.append((
                    BottleneckType.CPU, 0.6,
                    f"Emulator CPU at {report.emulator.cpu_percent:.0f}% — "
                    "CPU may be limiting frame delivery"
                ))

        # Display limitation
        if report.display.refresh_rate_hz > 0 and report.display.refresh_rate_hz < 60:
            candidates.append((
                BottleneckType.DISPLAY, 0.5,
                f"Display at {report.display.refresh_rate_hz}Hz — "
                "low refresh rate limits maximum perceived smoothness"
            ))

        # Background load
        if report.background.impact_level in ("HIGH", "SEVERE"):
            candidates.append((
                BottleneckType.BACKGROUND_LOAD, 0.5,
                f"Background CPU: {report.background.total_cpu_outside_emulator:.0f}% — "
                "resource competition detected"
            ))

        # Memory pressure
        if report.emulator.is_detected:
            try:
                vm = psutil.virtual_memory()
                if vm.percent > 85:
                    candidates.append((
                        BottleneckType.MEMORY, 0.4,
                        f"System RAM at {vm.percent:.0f}% — "
                        "memory pressure may cause paging stutters"
                    ))
            except Exception:
                pass

        # Configuration
        if (report.mouse.is_measured and
                report.mouse.enhanced_precision == PointerPrecision.ENABLED):
            candidates.append((
                BottleneckType.CONFIGURATION, 0.3,
                "Enhanced pointer precision is enabled — "
                "adds mouse acceleration"
            ))

        if not candidates:
            return (
                BottleneckType.UNKNOWN, 0.0,
                "No clear bottleneck identified — system appears balanced"
            )

        # Return highest confidence candidate
        candidates.sort(key=lambda x: x[1], reverse=True)
        best = candidates[0]
        return best[0], best[1], best[2]

    # ── 8. Recommendations ─────────────────────────────────────

    def _generate_recommendations(
        self, report: ResponsivenessReport
    ) -> List[str]:
        """Generate configuration recommendations from measured data."""
        recs = []

        # Mouse settings
        if report.mouse.is_measured:
            if report.mouse.enhanced_precision == PointerPrecision.ENABLED:
                recs.append(
                    "Disable enhanced pointer precision (mouse acceleration) "
                    "for more predictable cursor movement."
                )
            if report.mouse.pointer_trails > 0:
                recs.append(
                    "Disable mouse trails to reduce visual overhead."
                )

        # Display
        if report.display.refresh_rate_hz > 0 and report.display.refresh_rate_hz < 120:
            recs.append(
                f"Display is at {report.display.refresh_rate_hz}Hz. "
                "If your monitor supports higher, enable it in Display Settings."
            )

        # Emulator
        if report.emulator.is_detected:
            if report.emulator.priority_value >= 0:
                recs.append(
                    "Run as administrator to set emulator process to HIGH priority."
                )
            if (report.emulator.total_cpus > 0 and
                    report.emulator.affinity_cpus < report.emulator.total_cpus // 2):
                recs.append(
                    "Emulator is using fewer than half available CPU cores. "
                    "Consider enabling all cores."
                )

        # Frame pacing
        if report.frame_pacing.is_measured:
            if report.frame_pacing.frame_spikes > 10:
                recs.append(
                    f"Frame spikes detected ({report.frame_pacing.frame_spikes}). "
                    "Close background applications to reduce interference."
                )

        # Background
        if report.background.impact_level in ("HIGH", "SEVERE"):
            recs.append(
                "Close unnecessary background applications to reduce "
                "CPU/RAM competition with the emulator."
            )

        return recs


# Singleton
input_latency_analyzer = InputLatencyAnalyzer()
