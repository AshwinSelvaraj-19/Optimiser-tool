"""
Hardware-Aware Profile Engine — Phase 24

Automatically classifies the system based on detected hardware and recommends
the most appropriate optimization profile.

Every output is clearly classified:
  MEASURED  — read from real hardware APIs
  DETECTED  — discovered from OS/driver info
  INFERRED  — derived from measured data (not a direct measurement)
  RECOMMENDED — suggested action based on analysis
"""

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, List

import psutil

from app.utils.logger import get_logger

logger = get_logger("core.hardware_profile")


# ── Data Classification ──────────────────────────────────────

class DataOrigin(Enum):
    MEASURED = "MEASURED"
    DETECTED = "DETECTED"
    INFERRED = "INFERRED"
    RECOMMENDED = "RECOMMENDED"


class SystemTier(Enum):
    ENTRY = "Entry"
    MID_RANGE = "Mid-Range"
    HIGH_END = "High-End"
    ULTRA = "Ultra"
    UNKNOWN = "Unknown"


class ProfileRecommendation(Enum):
    BALANCED = "balanced"
    GAMING = "gaming"
    MAX_PERFORMANCE = "max_performance"


# ── Data Models ──────────────────────────────────────────────

@dataclass
class HardwareComponent:
    """A single hardware component with origin classification."""
    name: str = ""
    value: str = ""
    origin: DataOrigin = DataOrigin.MEASURED
    detail: str = ""


@dataclass
class HardwareSpec:
    """Complete detected hardware specification."""
    # CPU — MEASURED
    cpu_model: str = ""
    cpu_physical_cores: int = 0
    cpu_logical_cores: int = 0
    cpu_max_freq_mhz: float = 0.0
    cpu_origin: DataOrigin = DataOrigin.MEASURED

    # RAM — MEASURED
    ram_total_gb: float = 0.0
    ram_origin: DataOrigin = DataOrigin.MEASURED

    # GPU — DETECTED/MEASURED
    gpu_name: str = ""
    gpu_vendor: str = ""
    gpu_vram_mb: float = 0.0
    gpu_is_discrete: bool = False
    gpu_origin: DataOrigin = DataOrigin.DETECTED

    # Display — MEASURED
    display_resolution: str = ""
    display_refresh_hz: int = 0
    display_origin: DataOrigin = DataOrigin.MEASURED

    # OS — DETECTED
    os_version: str = ""
    os_origin: DataOrigin = DataOrigin.DETECTED

    # Emulator — DETECTED
    emulator_name: str = ""
    emulator_pid: int = 0
    emulator_origin: DataOrigin = DataOrigin.DETECTED

    # Live telemetry — MEASURED
    current_fps: Optional[float] = None
    fps_origin: DataOrigin = DataOrigin.MEASURED

    # Frame pacing — INFERRED from PresentMon
    frame_pacing_stability: Optional[str] = None
    frame_pacing_origin: DataOrigin = DataOrigin.INFERRED

    # Thermal — MEASURED
    gpu_temp_celsius: Optional[float] = None
    thermal_state: str = ""
    thermal_origin: DataOrigin = DataOrigin.MEASURED

    # Memory pressure — MEASURED
    memory_pressure: str = ""
    memory_pressure_origin: DataOrigin = DataOrigin.MEASURED


@dataclass
class ProfileSetting:
    """A recommended setting with justification."""
    name: str = ""
    recommended_value: str = ""
    current_value: str = ""
    reason: str = ""
    origin: DataOrigin = DataOrigin.RECOMMENDED
    priority: str = "MEDIUM"  # LOW, MEDIUM, HIGH


@dataclass
class HardwareProfileResult:
    """Complete hardware profile analysis."""
    # System classification
    system_tier: SystemTier = SystemTier.UNKNOWN
    tier_reason: str = ""

    # Detected hardware
    hardware: HardwareSpec = field(default_factory=HardwareSpec)

    # Recommended profile
    recommended_profile: ProfileRecommendation = ProfileRecommendation.GAMING
    profile_reason: str = ""

    # Specific settings
    settings: List[ProfileSetting] = field(default_factory=list)

    # Evidence
    components: List[HardwareComponent] = field(default_factory=list)

    # Timestamp
    timestamp: float = 0.0

    def __post_init__(self):
        if self.timestamp == 0.0:
            self.timestamp = time.time()


# ── Hardware Detection ───────────────────────────────────────

def _detect_cpu() -> HardwareSpec:
    """Detect CPU information — MEASURED from psutil."""
    spec = HardwareSpec()
    try:
        spec.cpu_model = psutil.cpu_info().brand_raw if hasattr(psutil, 'cpu_info') else ""
        if not spec.cpu_model:
            import platform
            spec.cpu_model = platform.processor() or "Unknown"
        spec.cpu_physical_cores = psutil.cpu_count(logical=False) or 0
        spec.cpu_logical_cores = psutil.cpu_count(logical=True) or 0
        freq = psutil.cpu_freq()
        if freq:
            spec.cpu_max_freq_mhz = freq.max or freq.current
        spec.cpu_origin = DataOrigin.MEASURED
    except Exception as e:
        logger.debug(f"CPU detection: {e}")
    return spec


def _detect_ram(spec: HardwareSpec) -> HardwareSpec:
    """Detect RAM — MEASURED from psutil."""
    try:
        vm = psutil.virtual_memory()
        spec.ram_total_gb = vm.total / (1024 ** 3)
        spec.ram_origin = DataOrigin.MEASURED
    except Exception as e:
        logger.debug(f"RAM detection: {e}")
    return spec


def _detect_gpu(spec: HardwareSpec) -> HardwareSpec:
    """Detect GPU — DETECTED from NVML or WMI."""
    try:
        from app.system.gpu import gpu_monitor
        gpus = gpu_monitor.detect()
        if gpus:
            gpu = gpus[0]
            if gpu.vendor == "NVIDIA":
                gpu = gpu_monitor.update_nvidia(gpu)
            spec.gpu_name = gpu.name
            spec.gpu_vendor = gpu.vendor
            spec.gpu_vram_mb = gpu.vram_total_mb
            spec.gpu_is_discrete = gpu.is_discrete
            spec.gpu_origin = DataOrigin.DETECTED
    except Exception as e:
        logger.debug(f"GPU detection: {e}")
    return spec


def _detect_display(spec: HardwareSpec) -> HardwareSpec:
    """Detect display — MEASURED from display subsystem."""
    try:
        from app.system.display import display_monitor
        disp = display_monitor.detect()
        spec.display_resolution = f"{disp.resolution_x}x{disp.resolution_y}"
        spec.display_refresh_hz = disp.refresh_rate_hz
        spec.display_origin = DataOrigin.MEASURED
    except Exception as e:
        logger.debug(f"Display detection: {e}")
    return spec


def _detect_os(spec: HardwareSpec) -> HardwareSpec:
    """Detect OS — DETECTED from platform."""
    try:
        import platform
        spec.os_version = f"{platform.system()} {platform.release()} {platform.version()}"
        spec.os_origin = DataOrigin.DETECTED
    except Exception as e:
        logger.debug(f"OS detection: {e}")
    return spec


def _detect_emulator(spec: HardwareSpec) -> HardwareSpec:
    """Detect emulator — DETECTED from process list."""
    try:
        from app.core.emulator_controller import emulator_controller
        target = emulator_controller.detect_target()
        if target:
            spec.emulator_name = f"{target.emulator} ({target.name})"
            spec.emulator_pid = target.pid
            spec.emulator_origin = DataOrigin.DETECTED
    except Exception as e:
        logger.debug(f"Emulator detection: {e}")
    return spec


def _detect_thermals(spec: HardwareSpec) -> HardwareSpec:
    """Detect thermal state — MEASURED from NVML."""
    try:
        from app.system.gpu import gpu_monitor
        gpus = gpu_monitor.detect()
        if gpus and gpus[0].vendor == "NVIDIA":
            gpu = gpu_monitor.update_nvidia(gpus[0])
            if gpu.temperature_celsius is not None:
                spec.gpu_temp_celsius = gpu.temperature_celsius
                if gpu.temperature_celsius >= 90:
                    spec.thermal_state = "THROTTLING_RISK"
                elif gpu.temperature_celsius >= 80:
                    spec.thermal_state = "HOT"
                elif gpu.temperature_celsius >= 70:
                    spec.thermal_state = "WARM"
                else:
                    spec.thermal_state = "NORMAL"
                spec.thermal_origin = DataOrigin.MEASURED
            else:
                spec.thermal_state = "UNKNOWN"
    except Exception as e:
        logger.debug(f"Thermal detection: {e}")
    return spec


def _detect_memory_pressure(spec: HardwareSpec) -> HardwareSpec:
    """Detect memory pressure — MEASURED from psutil."""
    try:
        vm = psutil.virtual_memory()
        if vm.percent > 90:
            spec.memory_pressure = "CRITICAL"
        elif vm.percent > 80:
            spec.memory_pressure = "HIGH"
        elif vm.percent > 65:
            spec.memory_pressure = "MODERATE"
        else:
            spec.memory_pressure = "NORMAL"
        spec.memory_pressure_origin = DataOrigin.MEASURED
    except Exception as e:
        logger.debug(f"Memory pressure: {e}")
    return spec


# ── GPU Tier Classification ──────────────────────────────────

# Known NVIDIA mobile GPUs ordered by performance
_NVIDIA_MOBILE_TIERS = {
    # Entry: MX series, older GT
    "entry": [
        "mx150", "mx250", "mx350", "mx450", "mx550",
        "gt 1030", "gt 730", "gt 710",
    ],
    # Mid-range: GTX 1650, RTX 3050
    "mid": [
        "gtx 1650", "gtx 1660", "rtx 3050", "rtx 3050 ti",
        "rx 5500", "rx 6500",
    ],
    # High-end: RTX 3060, RTX 4060
    "high": [
        "rtx 3060", "rtx 3070", "rtx 4060", "rtx 4070",
        "rx 6700", "rx 7600",
    ],
    # Ultra: RTX 3080+, RTX 4080+
    "ultra": [
        "rtx 3080", "rtx 3090", "rtx 4080", "rtx 4090",
        "rx 6800", "rx 6900", "rx 7800", "rx 7900",
    ],
}


def _classify_gpu_tier(gpu_name: str, vram_mb: float) -> SystemTier:
    """Classify GPU tier from name and VRAM — INFERRED."""
    name_lower = gpu_name.lower()

    # Check known models
    for tier_name, models in _NVIDIA_MOBILE_TIERS.items():
        for model in models:
            if model in name_lower:
                if tier_name == "ultra":
                    return SystemTier.ULTRA
                elif tier_name == "high":
                    return SystemTier.HIGH_END
                elif tier_name == "mid":
                    return SystemTier.MID_RANGE
                elif tier_name == "entry":
                    return SystemTier.ENTRY

    # Fallback: classify by VRAM
    if vram_mb >= 8000:
        return SystemTier.HIGH_END
    elif vram_mb >= 4000:
        return SystemTier.MID_RANGE
    elif vram_mb >= 2000:
        return SystemTier.ENTRY
    return SystemTier.UNKNOWN


# ── System Tier Classification ───────────────────────────────

def classify_system(spec: HardwareSpec) -> tuple:
    """
    Classify overall system tier — INFERRED from measured hardware.

    Returns (SystemTier, reason_string).
    """
    gpu_tier = _classify_gpu_tier(spec.gpu_name, spec.gpu_vram_mb)

    # CPU tier — INFERRED from cores + frequency
    cpu_score = 0
    if spec.cpu_logical_cores >= 16:
        cpu_score = 4
    elif spec.cpu_logical_cores >= 12:
        cpu_score = 3
    elif spec.cpu_logical_cores >= 8:
        cpu_score = 2
    elif spec.cpu_logical_cores >= 4:
        cpu_score = 1

    # RAM tier — INFERRED from total
    ram_score = 0
    if spec.ram_total_gb >= 32:
        ram_score = 4
    elif spec.ram_total_gb >= 16:
        ram_score = 3
    elif spec.ram_total_gb >= 8:
        ram_score = 2
    elif spec.ram_total_gb >= 4:
        ram_score = 1

    # GPU score
    gpu_score_map = {
        SystemTier.ENTRY: 1,
        SystemTier.MID_RANGE: 2,
        SystemTier.HIGH_END: 3,
        SystemTier.ULTRA: 4,
        SystemTier.UNKNOWN: 2,
    }
    gpu_score = gpu_score_map.get(gpu_tier, 2)

    # Overall tier is primarily GPU-bound for gaming
    # Use weighted average: GPU 50%, CPU 25%, RAM 25%
    overall = (gpu_score * 2 + cpu_score + ram_score) / 4.0

    if overall >= 3.5:
        tier = SystemTier.ULTRA
    elif overall >= 2.5:
        tier = SystemTier.HIGH_END
    elif overall >= 1.5:
        tier = SystemTier.MID_RANGE
    elif overall >= 0.5:
        tier = SystemTier.ENTRY
    else:
        tier = SystemTier.UNKNOWN

    # Build reason
    parts = []
    if spec.gpu_name:
        parts.append(f"GPU: {spec.gpu_name} ({gpu_tier.value})")
    if spec.cpu_logical_cores > 0:
        parts.append(f"CPU: {spec.cpu_logical_cores} threads")
    if spec.ram_total_gb > 0:
        parts.append(f"RAM: {spec.ram_total_gb:.1f}GB")
    reason = ", ".join(parts) if parts else "Insufficient hardware data"

    return tier, reason


# ── Profile Recommendation Engine ────────────────────────────

def _recommend_profile(spec: HardwareSpec, tier: SystemTier) -> tuple:
    """
    Recommend the most appropriate optimization profile — RECOMMENDED.

    Returns (ProfileRecommendation, reason_string).
    """
    reasons = []

    # Memory pressure influence
    if spec.memory_pressure == "CRITICAL":
        reasons.append("Memory critically low — use minimal optimizations")
        return ProfileRecommendation.BALANCED, "; ".join(reasons)

    # Thermal influence
    if spec.thermal_state == "THROTTLING_RISK":
        reasons.append("GPU thermal throttling risk — conservative approach")
        return ProfileRecommendation.BALANCED, "; ".join(reasons)

    # Tier-based recommendation
    if tier == SystemTier.ENTRY:
        reasons.append("Entry-level hardware — safe minimal optimizations")
        return ProfileRecommendation.BALANCED, "; ".join(reasons)
    elif tier == SystemTier.MID_RANGE:
        reasons.append("Mid-range hardware — standard gaming optimizations")
        return ProfileRecommendation.GAMING, "; ".join(reasons)
    elif tier == SystemTier.HIGH_END:
        reasons.append("High-end hardware — full optimization suite")
        return ProfileRecommendation.MAX_PERFORMANCE, "; ".join(reasons)
    elif tier == SystemTier.ULTRA:
        reasons.append("Ultra hardware — maximum optimization for peak performance")
        return ProfileRecommendation.MAX_PERFORMANCE, "; ".join(reasons)

    # Default
    reasons.append("Unknown hardware — defaulting to gaming profile")
    return ProfileRecommendation.GAMING, "; ".join(reasons)


def _generate_settings(spec: HardwareSpec, tier: SystemTier,
                       profile: ProfileRecommendation) -> List[ProfileSetting]:
    """
    Generate specific hardware-aware setting recommendations — RECOMMENDED.
    """
    settings = []

    # Power Plan
    if profile in (ProfileRecommendation.GAMING, ProfileRecommendation.MAX_PERFORMANCE):
        settings.append(ProfileSetting(
            name="Power Plan",
            recommended_value="High Performance",
            reason="Gaming workload benefits from maximum CPU/GPU throughput",
            origin=DataOrigin.RECOMMENDED,
            priority="HIGH",
        ))
    else:
        settings.append(ProfileSetting(
            name="Power Plan",
            recommended_value="Balanced",
            reason="Entry-level hardware benefits from balanced power management",
            origin=DataOrigin.RECOMMENDED,
            priority="MEDIUM",
        ))

    # Game Mode
    settings.append(ProfileSetting(
        name="Game Mode",
        recommended_value="ENABLED",
        reason="Windows Game Mode optimizes resource allocation for gaming",
        origin=DataOrigin.RECOMMENDED,
        priority="MEDIUM",
    ))

    # Emulator Priority
    if spec.emulator_pid > 0:
        if profile == ProfileRecommendation.BALANCED:
            settings.append(ProfileSetting(
                name="Emulator Priority",
                recommended_value="NORMAL",
                reason="Entry systems benefit from fair scheduling",
                origin=DataOrigin.RECOMMENDED,
                priority="LOW",
            ))
        else:
            settings.append(ProfileSetting(
                name="Emulator Priority",
                recommended_value="HIGH (requires admin)",
                reason="Higher priority improves frame delivery consistency",
                origin=DataOrigin.RECOMMENDED,
                priority="MEDIUM",
            ))

    # CPU Affinity (only for high-core-count systems)
    if spec.cpu_logical_cores >= 12:
        settings.append(ProfileSetting(
            name="CPU Affinity",
            recommended_value=f"Use all {spec.cpu_logical_cores} threads",
            reason="Sufficient cores — all threads available for emulator",
            origin=DataOrigin.RECOMMENDED,
            priority="LOW",
        ))

    # VRAM-aware recommendation
    if spec.gpu_vram_mb > 0 and spec.gpu_vram_mb < 3000:
        settings.append(ProfileSetting(
            name="Emulator Graphics",
            recommended_value="Medium/Low textures",
            reason=f"Limited VRAM ({spec.gpu_vram_mb:.0f}MB) — reduce texture quality to avoid stutters",
            origin=DataOrigin.RECOMMENDED,
            priority="HIGH",
        ))
    elif spec.gpu_vram_mb >= 6000:
        settings.append(ProfileSetting(
            name="Emulator Graphics",
            recommended_value="High textures OK",
            reason=f"Sufficient VRAM ({spec.gpu_vram_mb:.0f}MB) — high quality textures supported",
            origin=DataOrigin.RECOMMENDED,
            priority="LOW",
        ))

    # RAM-aware recommendation
    if spec.ram_total_gb > 0 and spec.ram_total_gb < 8:
        settings.append(ProfileSetting(
            name="Emulator RAM Allocation",
            recommended_value="2-3 GB",
            reason=f"Limited system RAM ({spec.ram_total_gb:.1f}GB) — allocate conservatively",
            origin=DataOrigin.RECOMMENDED,
            priority="HIGH",
        ))
    elif spec.ram_total_gb >= 16:
        settings.append(ProfileSetting(
            name="Emulator RAM Allocation",
            recommended_value="4-6 GB",
            reason=f"Ample system RAM ({spec.ram_total_gb:.1f}GB) — can allocate generously",
            origin=DataOrigin.RECOMMENDED,
            priority="LOW",
        ))

    # Thermal recommendation
    if spec.thermal_state in ("HOT", "THROTTLING_RISK"):
        settings.append(ProfileSetting(
            name="Thermal Management",
            recommended_value="Reduce graphics quality",
            reason=f"GPU at {spec.gpu_temp_celsius:.0f}°C — throttling risk detected",
            origin=DataOrigin.RECOMMENDED,
            priority="HIGH",
        ))

    # Memory pressure recommendation
    if spec.memory_pressure in ("HIGH", "CRITICAL"):
        settings.append(ProfileSetting(
            name="Memory Management",
            recommended_value="Close background apps",
            reason=f"Memory pressure: {spec.memory_pressure} — system may stutter",
            origin=DataOrigin.RECOMMENDED,
            priority="HIGH",
        ))

    # Background load (MAX PERFORMANCE only)
    if profile == ProfileRecommendation.MAX_PERFORMANCE:
        settings.append(ProfileSetting(
            name="Background Processes",
            recommended_value="Review optional apps",
            reason="Maximize available resources for emulator",
            origin=DataOrigin.RECOMMENDED,
            priority="MEDIUM",
        ))

    return settings


def _build_components(spec: HardwareSpec) -> List[HardwareComponent]:
    """Build list of detected hardware components with origin labels."""
    components = []

    if spec.cpu_model:
        components.append(HardwareComponent(
            name="CPU",
            value=f"{spec.cpu_model} ({spec.cpu_logical_cores}T)",
            origin=spec.cpu_origin,
            detail=f"{spec.cpu_physical_cores}P/{spec.cpu_logical_cores}L cores, {spec.cpu_max_freq_mhz:.0f}MHz max",
        ))

    if spec.ram_total_gb > 0:
        components.append(HardwareComponent(
            name="RAM",
            value=f"{spec.ram_total_gb:.1f} GB",
            origin=spec.ram_origin,
        ))

    if spec.gpu_name:
        components.append(HardwareComponent(
            name="GPU",
            value=spec.gpu_name,
            origin=spec.gpu_origin,
            detail=f"{spec.gpu_vram_mb:.0f}MB VRAM, {'Discrete' if spec.gpu_is_discrete else 'Integrated'}",
        ))

    if spec.display_resolution:
        components.append(HardwareComponent(
            name="Display",
            value=f"{spec.display_resolution} @ {spec.display_refresh_hz}Hz",
            origin=spec.display_origin,
        ))

    if spec.emulator_name:
        components.append(HardwareComponent(
            name="Emulator",
            value=spec.emulator_name,
            origin=spec.emulator_origin,
            detail=f"PID {spec.emulator_pid}" if spec.emulator_pid else "",
        ))

    if spec.gpu_temp_celsius is not None:
        components.append(HardwareComponent(
            name="Thermal",
            value=f"GPU {spec.gpu_temp_celsius:.0f}°C ({spec.thermal_state})",
            origin=spec.thermal_origin,
        ))

    if spec.memory_pressure:
        components.append(HardwareComponent(
            name="Memory Pressure",
            value=spec.memory_pressure,
            origin=spec.memory_pressure_origin,
        ))

    return components


# ── Main Analysis Function ───────────────────────────────────

def analyze_hardware_profile() -> HardwareProfileResult:
    """
    Analyze the complete hardware configuration and recommend a profile.

    Every output is clearly classified:
      MEASURED  — from real hardware APIs
      DETECTED  — from OS/driver info
      INFERRED  — derived from measured data
      RECOMMENDED — suggested actions
    """
    result = HardwareProfileResult()

    # Detect hardware — MEASURED/DETECTED
    spec = _detect_cpu()
    spec = _detect_ram(spec)
    spec = _detect_gpu(spec)
    spec = _detect_display(spec)
    spec = _detect_os(spec)
    spec = _detect_emulator(spec)
    spec = _detect_thermals(spec)
    spec = _detect_memory_pressure(spec)

    result.hardware = spec

    # Classify system — INFERRED
    tier, tier_reason = classify_system(spec)
    result.system_tier = tier
    result.tier_reason = tier_reason

    # Recommend profile — RECOMMENDED
    profile, profile_reason = _recommend_profile(spec, tier)
    result.recommended_profile = profile
    result.profile_reason = profile_reason

    # Generate settings — RECOMMENDED
    result.settings = _generate_settings(spec, tier, profile)

    # Build component list
    result.components = _build_components(spec)

    logger.info(
        f"Hardware profile: {tier.value} — "
        f"Recommended: {profile.value}"
    )

    return result


# ── CLI Display ──────────────────────────────────────────────

def print_hardware_profile(result: HardwareProfileResult):
    """Print hardware profile in a compact CLI format."""
    print("=" * 50)
    print("HEAVEN SOCIETY — HARDWARE PROFILE")
    print("=" * 50)

    # System tier
    tier_colors = {
        SystemTier.ENTRY: "Entry Level",
        SystemTier.MID_RANGE: "Mid-Range",
        SystemTier.HIGH_END: "High-End",
        SystemTier.ULTRA: "Ultra",
        SystemTier.UNKNOWN: "Unknown",
    }
    print(f"\nSYSTEM CLASSIFICATION")
    print(f"  Tier:       {tier_colors.get(result.system_tier, 'Unknown')}")
    print(f"  Reason:     {result.tier_reason}")

    # Hardware components
    print(f"\nDETECTED HARDWARE")
    for comp in result.components:
        origin_tag = f"[{comp.origin.value}]"
        detail = f"  ({comp.detail})" if comp.detail else ""
        print(f"  {comp.name:16s} {comp.value:30s} {origin_tag}{detail}")

    # Recommended profile
    profile_names = {
        ProfileRecommendation.BALANCED: "BALANCED",
        ProfileRecommendation.GAMING: "GAMING",
        ProfileRecommendation.MAX_PERFORMANCE: "MAX PERFORMANCE",
    }
    print(f"\nRECOMMENDED PROFILE")
    print(f"  Profile:    {profile_names.get(result.recommended_profile, 'Unknown')}")
    print(f"  Reason:     {result.profile_reason}")

    # Settings
    if result.settings:
        print(f"\nRECOMMENDED SETTINGS")
        for s in result.settings:
            print(f"  {s.name:24s} {s.recommended_value}")
            print(f"    Reason: {s.reason} [{s.origin.value}]")

    # Disclaimers
    print(f"\nDISCLAIMERS")
    print(f"  • MEASURED values are read from real hardware APIs.")
    print(f"  • INFERRED values are derived from measured data.")
    print(f"  • RECOMMENDED settings are suggestions, not requirements.")
    print(f"  • No settings are modified by this analysis.")

    print(f"\n{'=' * 50}")
    print("HARDWARE PROFILE COMPLETE")
    print("=" * 50)
