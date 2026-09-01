"""
Phase 54 — Data-Driven Optimization Profiles.

Provides 6 built-in profiles + custom profile management:
  BALANCED — Safe, minimal changes
  GAMING — Standard gaming optimizations
  COMPETITIVE — Maximum FPS for competitive play
  BATTERY — Power saving with gaming awareness
  PERFORMANCE — All verified optimizations
  CUSTOM — User-defined profile

Each profile is a complete data object defining:
  - Optimization rules (what to change)
  - Monitoring thresholds (when to alert)
  - Cleanup recommendations (what to suggest)
  - Power configuration preferences
  - Background workload policy

CRUD operations:
  Create, Edit, Duplicate, Delete, Export, Import, Reset

Rules:
  - No dangerous registry tweaks
  - Every profile change is explained before applying
  - Profiles are data-driven, not hardcoded in UI
  - All built-in profiles are read-only (cannot be deleted)
  - Custom profiles are persisted to profiles/ directory
"""

import json
import os
import time
import uuid
import copy
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("core.optimization_profiles")


# ── Enums ────────────────────────────────────────────────────────


class ProfileType(Enum):
    """Whether a profile is built-in or user-created."""
    BUILT_IN = "BUILT_IN"
    CUSTOM = "CUSTOM"


class OptimizationCategory(Enum):
    """Categories of optimizations a profile can enable."""
    POWER = "power"
    GAME_MODE = "game_mode"
    EMULATOR = "emulator"
    MEMORY = "memory"
    BACKGROUND = "background"
    WINDOWS_GAMING = "windows_gaming"
    CLEANUP = "cleanup"
    DIAGNOSTIC = "diagnostic"


class BackgroundWorkloadPolicy(Enum):
    """How aggressively to handle background processes."""
    DO_NOTHING = "DO_NOTHING"
    RECOMMEND_ONLY = "RECOMMEND_ONLY"
    SUSGEST_CLOSE = "SUGGEST_CLOSE"
    AGGRESSIVE = "AGGRESSIVE"


class CleanupPolicy(Enum):
    """When to suggest cleanup."""
    NEVER = "NEVER"
    ON_PRESSURE = "ON_PRESSURE"
    PROACTIVE = "PROACTIVE"


# ── Data Models ────────────────────────────────────────────────────


@dataclass
class ProfileOptimizationRule:
    """A single optimization enabled by a profile."""
    rule_id: str = ""
    name: str = ""
    description: str = ""
    category: OptimizationCategory = OptimizationCategory.DIAGNOSTIC
    enabled: bool = True
    requires_admin: bool = False
    reversible: bool = True
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "name": self.name,
            "description": self.description,
            "category": self.category.value,
            "enabled": self.enabled,
            "requires_admin": self.requires_admin,
            "reversible": self.reversible,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ProfileOptimizationRule":
        cat = OptimizationCategory(data.get("category", "diagnostic"))
        return cls(
            rule_id=data.get("rule_id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            category=cat,
            enabled=data.get("enabled", True),
            requires_admin=data.get("requires_admin", False),
            reversible=data.get("reversible", True),
            risk_level=data.get("risk_level", "LOW"),
        )


@dataclass
class MonitoringThresholds:
    """Thresholds for when to alert or take action."""
    cpu_warning: float = 80.0
    cpu_critical: float = 95.0
    ram_warning: float = 80.0
    ram_critical: float = 90.0
    gpu_temp_warning: float = 80.0
    gpu_temp_critical: float = 90.0
    gpu_utilization_low: float = 50.0
    fps_low: float = 30.0
    fps_critical: float = 15.0
    frame_time_warning_ms: float = 16.67  # 60fps target
    frame_time_critical_ms: float = 33.33  # 30fps target
    disk_free_warning_gb: float = 15.0
    disk_free_critical_gb: float = 5.0

    def to_dict(self) -> dict:
        return {
            "cpu_warning": self.cpu_warning,
            "cpu_critical": self.cpu_critical,
            "ram_warning": self.ram_warning,
            "ram_critical": self.ram_critical,
            "gpu_temp_warning": self.gpu_temp_warning,
            "gpu_temp_critical": self.gpu_temp_critical,
            "gpu_utilization_low": self.gpu_utilization_low,
            "fps_low": self.fps_low,
            "fps_critical": self.fps_critical,
            "frame_time_warning_ms": self.frame_time_warning_ms,
            "frame_time_critical_ms": self.frame_time_critical_ms,
            "disk_free_warning_gb": self.disk_free_warning_gb,
            "disk_free_critical_gb": self.disk_free_critical_gb,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "MonitoringThresholds":
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


@dataclass
class PowerConfig:
    """Power configuration preferences."""
    power_plan: str = "balanced"  # balanced, high_performance, power_saver
    processor_max_state: int = 100  # percentage
    processor_min_state: int = 5
    display_timeout_minutes: int = 15
    sleep_timeout_minutes: int = 0  # 0 = never
    hibernate_enabled: bool = False

    def to_dict(self) -> dict:
        return {
            "power_plan": self.power_plan,
            "processor_max_state": self.processor_max_state,
            "processor_min_state": self.processor_min_state,
            "display_timeout_minutes": self.display_timeout_minutes,
            "sleep_timeout_minutes": self.sleep_timeout_minutes,
            "hibernate_enabled": self.hibernate_enabled,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "PowerConfig":
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


@dataclass
class CleanupRecommendation:
    """What cleanup a profile recommends."""
    policy: CleanupPolicy = CleanupPolicy.ON_PRESSURE
    min_age_days: int = 7
    include_temp: bool = True
    include_crash_dumps: bool = True
    include_logs: bool = True
    include_shader_cache: bool = False
    include_browser_cache: bool = False
    include_recycle_bin: bool = False

    def to_dict(self) -> dict:
        return {
            "policy": self.policy.value,
            "min_age_days": self.min_age_days,
            "include_temp": self.include_temp,
            "include_crash_dumps": self.include_crash_dumps,
            "include_logs": self.include_logs,
            "include_shader_cache": self.include_shader_cache,
            "include_browser_cache": self.include_browser_cache,
            "include_recycle_bin": self.include_recycle_bin,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CleanupRecommendation":
        policy = CleanupPolicy(data.get("policy", "ON_PRESSURE"))
        d = {k: v for k, v in data.items() if hasattr(cls, k) and k != "policy"}
        return cls(policy=policy, **d)


@dataclass
class OptimizationProfileConfig:
    """
    A complete, data-driven optimization profile.
    Everything is defined as data — no hardcoded logic in UI.
    """
    id: str = ""
    name: str = ""
    description: str = ""
    profile_type: ProfileType = ProfileType.CUSTOM

    # Optimizations
    optimizations: List[ProfileOptimizationRule] = field(default_factory=list)

    # Monitoring
    thresholds: MonitoringThresholds = field(default_factory=MonitoringThresholds)

    # Power
    power: PowerConfig = field(default_factory=PowerConfig)

    # Cleanup
    cleanup: CleanupRecommendation = field(default_factory=CleanupRecommendation)

    # Background workload
    background_policy: BackgroundWorkloadPolicy = BackgroundWorkloadPolicy.RECOMMEND_ONLY

    # Metadata
    created_at: float = 0.0
    modified_at: float = 0.0
    author: str = "Heaven Society"

    def __post_init__(self):
        if not self.id:
            self.id = f"custom_{uuid.uuid4().hex[:8]}"
        if self.created_at == 0.0:
            self.created_at = time.time()
        if self.modified_at == 0.0:
            self.modified_at = time.time()

    @property
    def is_built_in(self) -> bool:
        return self.profile_type == ProfileType.BUILT_IN

    @property
    def enabled_optimizations(self) -> List[ProfileOptimizationRule]:
        return [o for o in self.optimizations if o.enabled]

    @property
    def requires_admin(self) -> bool:
        return any(o.requires_admin for o in self.enabled_optimizations)

    def explain(self) -> str:
        """
        Generate a human-readable explanation of what this profile changes.
        Must be called before applying.
        """
        lines = []
        lines.append(f"PROFILE: {self.name}")
        lines.append(f"DESCRIPTION: {self.description}")
        lines.append(f"TYPE: {self.profile_type.value}")
        lines.append("")

        # Optimizations
        lines.append("OPTIMIZATIONS:")
        for opt in self.enabled_optimizations:
            admin = " [REQUIRES ADMIN]" if opt.requires_admin else ""
            risk = f" (risk: {opt.risk_level})" if opt.risk_level != "LOW" else ""
            lines.append(f"  [*] {opt.name}{admin}{risk}")
            lines.append(f"    {opt.description}")
        lines.append("")

        # Power
        lines.append("POWER CONFIGURATION:")
        plan_display = self.power.power_plan.upper().replace("_", " ")
        lines.append(f"  Power Plan: {plan_display}")
        lines.append(f"  CPU Max: {self.power.processor_max_state}%")
        lines.append(f"  Sleep: {'Disabled' if self.power.sleep_timeout_minutes == 0 else f'{self.power.sleep_timeout_minutes} min'}")
        lines.append("")

        # Monitoring
        lines.append("MONITORING THRESHOLDS:")
        lines.append(f"  CPU Warning: {self.thresholds.cpu_warning:.0f}%  Critical: {self.thresholds.cpu_critical:.0f}%")
        lines.append(f"  RAM Warning: {self.thresholds.ram_warning:.0f}%  Critical: {self.thresholds.ram_critical:.0f}%")
        lines.append(f"  GPU Temp Warning: {self.thresholds.gpu_temp_warning:.0f}°C  Critical: {self.thresholds.gpu_temp_critical:.0f}°C")
        lines.append(f"  FPS Low: {self.thresholds.fps_low:.0f}  Critical: {self.thresholds.fps_critical:.0f}")
        lines.append("")

        # Cleanup
        lines.append("CLEANUP POLICY:")
        lines.append(f"  Policy: {self.cleanup.policy.value}")
        if self.cleanup.include_temp:
            lines.append(f"  [*] Temporary files (>{self.cleanup.min_age_days} days old)")
        if self.cleanup.include_crash_dumps:
            lines.append(f"  [*] Crash dumps (>{self.cleanup.min_age_days} days old)")
        if self.cleanup.include_logs:
            lines.append(f"  [*] Old logs (>{self.cleanup.min_age_days} days old)")
        if self.cleanup.include_shader_cache:
            lines.append(f"  [*] Shader cache")
        if self.cleanup.include_browser_cache:
            lines.append(f"  [*] Browser cache")
        lines.append("")

        # Background
        lines.append("BACKGROUND WORKLOAD:")
        lines.append(f"  Policy: {self.background_policy.value}")

        return "\n".join(lines)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "profile_type": self.profile_type.value,
            "optimizations": [o.to_dict() for o in self.optimizations],
            "thresholds": self.thresholds.to_dict(),
            "power": self.power.to_dict(),
            "cleanup": self.cleanup.to_dict(),
            "background_policy": self.background_policy.value,
            "created_at": self.created_at,
            "modified_at": self.modified_at,
            "author": self.author,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OptimizationProfileConfig":
        pt = ProfileType(data.get("profile_type", "CUSTOM"))
        bp = BackgroundWorkloadPolicy(data.get("background_policy", "RECOMMEND_ONLY"))
        optimizations = [
            ProfileOptimizationRule.from_dict(o)
            for o in data.get("optimizations", [])
        ]
        thresholds = MonitoringThresholds.from_dict(data.get("thresholds", {}))
        power = PowerConfig.from_dict(data.get("power", {}))
        cleanup = CleanupRecommendation.from_dict(data.get("cleanup", {}))
        return cls(
            id=data.get("id", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            profile_type=pt,
            optimizations=optimizations,
            thresholds=thresholds,
            power=power,
            cleanup=cleanup,
            background_policy=bp,
            created_at=data.get("created_at", 0.0),
            modified_at=data.get("modified_at", 0.0),
            author=data.get("author", "Heaven Society"),
        )


# ══════════════════════════════════════════════════════════════════
# BUILT-IN PROFILES
# ══════════════════════════════════════════════════════════════════

def _builtin(**kwargs) -> OptimizationProfileConfig:
    """Helper to create a built-in profile."""
    kwargs["profile_type"] = ProfileType.BUILT_IN
    kwargs.setdefault("author", "Heaven Society")
    return OptimizationProfileConfig(**kwargs)


BALANCED_PROFILE = _builtin(
    id="balanced",
    name="BALANCED",
    description="Safe, minimal changes. Game Mode only. Recommended for general use.",
    optimizations=[
        ProfileOptimizationRule(
            rule_id="game_mode", name="Game Mode",
            description="Enable Windows Game Mode for better scheduling",
            category=OptimizationCategory.GAME_MODE,
        ),
    ],
    thresholds=MonitoringThresholds(
        cpu_warning=85.0, cpu_critical=95.0,
        ram_warning=85.0, ram_critical=92.0,
    ),
    power=PowerConfig(power_plan="balanced"),
    cleanup=CleanupRecommendation(policy=CleanupPolicy.ON_PRESSURE),
    background_policy=BackgroundWorkloadPolicy.DO_NOTHING,
)

GAMING_PROFILE = _builtin(
    id="gaming",
    name="GAMING",
    description="Standard gaming optimizations. Game Mode + Power Plan + Emulator Priority.",
    optimizations=[
        ProfileOptimizationRule(
            rule_id="game_mode", name="Game Mode",
            description="Enable Windows Game Mode for better scheduling",
            category=OptimizationCategory.GAME_MODE,
        ),
        ProfileOptimizationRule(
            rule_id="power_plan", name="Power Plan",
            description="Switch to High Performance power plan",
            category=OptimizationCategory.POWER,
        ),
        ProfileOptimizationRule(
            rule_id="emulator_priority", name="Emulator Priority",
            description="Set emulator process to high priority",
            category=OptimizationCategory.EMULATOR,
            requires_admin=True,
        ),
        ProfileOptimizationRule(
            rule_id="memory_analysis", name="Memory Analysis",
            description="Analyze memory pressure and provide safe recommendations",
            category=OptimizationCategory.MEMORY,
        ),
    ],
    thresholds=MonitoringThresholds(
        cpu_warning=80.0, cpu_critical=95.0,
        ram_warning=80.0, ram_critical=90.0,
        fps_low=30.0, fps_critical=15.0,
    ),
    power=PowerConfig(power_plan="high_performance"),
    cleanup=CleanupRecommendation(policy=CleanupPolicy.ON_PRESSURE),
    background_policy=BackgroundWorkloadPolicy.RECOMMEND_ONLY,
)

COMPETITIVE_PROFILE = _builtin(
    id="competitive",
    name="COMPETITIVE",
    description="Maximum FPS for competitive play. All gaming optimizations + aggressive monitoring.",
    optimizations=[
        ProfileOptimizationRule(
            rule_id="game_mode", name="Game Mode",
            description="Enable Windows Game Mode for better scheduling",
            category=OptimizationCategory.GAME_MODE,
        ),
        ProfileOptimizationRule(
            rule_id="power_plan", name="Power Plan",
            description="Switch to High Performance power plan",
            category=OptimizationCategory.POWER,
        ),
        ProfileOptimizationRule(
            rule_id="game_bar", name="Game Bar",
            description="Disable Xbox Game Bar overlay to reduce overhead",
            category=OptimizationCategory.WINDOWS_GAMING,
        ),
        ProfileOptimizationRule(
            rule_id="background_recording", name="Background Recording",
            description="Disable Windows background recording",
            category=OptimizationCategory.WINDOWS_GAMING,
        ),
        ProfileOptimizationRule(
            rule_id="emulator_priority", name="Emulator Priority",
            description="Set emulator process to high priority",
            category=OptimizationCategory.EMULATOR,
            requires_admin=True,
        ),
        ProfileOptimizationRule(
            rule_id="cpu_affinity", name="CPU Affinity",
            description="Optimize CPU core assignment for the emulator",
            category=OptimizationCategory.EMULATOR,
            requires_admin=True,
        ),
        ProfileOptimizationRule(
            rule_id="memory_analysis", name="Memory Analysis",
            description="Analyze memory pressure and provide safe recommendations",
            category=OptimizationCategory.MEMORY,
        ),
        ProfileOptimizationRule(
            rule_id="background_load", name="Background Load",
            description="Review optional background processes",
            category=OptimizationCategory.BACKGROUND,
        ),
    ],
    thresholds=MonitoringThresholds(
        cpu_warning=75.0, cpu_critical=90.0,
        ram_warning=75.0, ram_critical=88.0,
        gpu_temp_warning=78.0, gpu_temp_critical=88.0,
        fps_low=40.0, fps_critical=25.0,
        frame_time_warning_ms=12.0,
        frame_time_critical_ms=25.0,
    ),
    power=PowerConfig(
        power_plan="high_performance",
        processor_max_state=100,
        sleep_timeout_minutes=0,
    ),
    cleanup=CleanupRecommendation(policy=CleanupPolicy.PROACTIVE),
    background_policy=BackgroundWorkloadPolicy.SUSGEST_CLOSE,
)

BATTERY_PROFILE = _builtin(
    id="battery",
    name="BATTERY",
    description="Power saving with gaming awareness. Reduced performance for longer battery life.",
    optimizations=[
        ProfileOptimizationRule(
            rule_id="game_mode", name="Game Mode",
            description="Enable Windows Game Mode",
            category=OptimizationCategory.GAME_MODE,
        ),
        ProfileOptimizationRule(
            rule_id="memory_analysis", name="Memory Analysis",
            description="Monitor memory pressure",
            category=OptimizationCategory.MEMORY,
        ),
    ],
    thresholds=MonitoringThresholds(
        cpu_warning=85.0, cpu_critical=95.0,
        ram_warning=85.0, ram_critical=92.0,
        gpu_temp_warning=82.0, gpu_temp_critical=90.0,
        fps_low=25.0, fps_critical=15.0,
    ),
    power=PowerConfig(
        power_plan="power_saver",
        processor_max_state=70,
        processor_min_state=5,
        display_timeout_minutes=10,
        sleep_timeout_minutes=15,
        hibernate_enabled=True,
    ),
    cleanup=CleanupRecommendation(policy=CleanupPolicy.NEVER),
    background_policy=BackgroundWorkloadPolicy.DO_NOTHING,
)

PERFORMANCE_PROFILE = _builtin(
    id="performance",
    name="PERFORMANCE",
    description="All verified optimizations. Windows gaming settings + diagnostics + cleanup.",
    optimizations=[
        ProfileOptimizationRule(
            rule_id="game_mode", name="Game Mode",
            description="Enable Windows Game Mode for better scheduling",
            category=OptimizationCategory.GAME_MODE,
        ),
        ProfileOptimizationRule(
            rule_id="power_plan", name="Power Plan",
            description="Switch to High Performance power plan",
            category=OptimizationCategory.POWER,
        ),
        ProfileOptimizationRule(
            rule_id="game_bar", name="Game Bar",
            description="Disable Xbox Game Bar overlay",
            category=OptimizationCategory.WINDOWS_GAMING,
        ),
        ProfileOptimizationRule(
            rule_id="background_recording", name="Background Recording",
            description="Disable background recording",
            category=OptimizationCategory.WINDOWS_GAMING,
        ),
        ProfileOptimizationRule(
            rule_id="emulator_priority", name="Emulator Priority",
            description="Set emulator process to high priority",
            category=OptimizationCategory.EMULATOR,
            requires_admin=True,
        ),
        ProfileOptimizationRule(
            rule_id="cpu_affinity", name="CPU Affinity",
            description="Optimize CPU core assignment",
            category=OptimizationCategory.EMULATOR,
            requires_admin=True,
        ),
        ProfileOptimizationRule(
            rule_id="memory_analysis", name="Memory Analysis",
            description="Analyze memory pressure and provide safe recommendations",
            category=OptimizationCategory.MEMORY,
        ),
        ProfileOptimizationRule(
            rule_id="background_load", name="Background Load",
            description="Review optional background processes",
            category=OptimizationCategory.BACKGROUND,
        ),
    ],
    thresholds=MonitoringThresholds(
        cpu_warning=78.0, cpu_critical=92.0,
        ram_warning=78.0, ram_critical=88.0,
        gpu_temp_warning=78.0, gpu_temp_critical=88.0,
        fps_low=35.0, fps_critical=20.0,
    ),
    power=PowerConfig(
        power_plan="high_performance",
        processor_max_state=100,
        sleep_timeout_minutes=0,
    ),
    cleanup=CleanupRecommendation(policy=CleanupPolicy.PROACTIVE),
    background_policy=BackgroundWorkloadPolicy.RECOMMEND_ONLY,
)


# ══════════════════════════════════════════════════════════════════
# Profile Manager
# ══════════════════════════════════════════════════════════════════

# Built-in profile registry
BUILTIN_PROFILES: Dict[str, OptimizationProfileConfig] = {
    "balanced": BALANCED_PROFILE,
    "gaming": GAMING_PROFILE,
    "competitive": COMPETITIVE_PROFILE,
    "battery": BATTERY_PROFILE,
    "performance": PERFORMANCE_PROFILE,
}


class OptimizationProfileManager:
    """
    Manages optimization profiles: built-in + custom.
    Supports CRUD, import, export, and reset.
    """

    def __init__(self, profiles_dir: Optional[str] = None):
        if profiles_dir is None:
            profiles_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(
                    os.path.abspath(__file__)
                ))),
                "profiles",
            )
        self._dir = profiles_dir
        os.makedirs(self._dir, exist_ok=True)
        self._custom_cache: Dict[str, OptimizationProfileConfig] = {}
        self._load_custom()

    # ── List ──────────────────────────────────────────────────

    def list_profiles(self) -> List[Dict]:
        """List all available profiles (built-in + custom)."""
        result = []
        for pid, profile in BUILTIN_PROFILES.items():
            result.append({
                "id": pid,
                "name": profile.name,
                "description": profile.description,
                "type": "BUILT_IN",
                "optimizations": len(profile.enabled_optimizations),
                "requires_admin": profile.requires_admin,
            })
        for pid, profile in self._custom_cache.items():
            result.append({
                "id": pid,
                "name": profile.name,
                "description": profile.description,
                "type": "CUSTOM",
                "optimizations": len(profile.enabled_optimizations),
                "requires_admin": profile.requires_admin,
            })
        return result

    # ── Get ───────────────────────────────────────────────────

    def get_profile(self, profile_id: str) -> Optional[OptimizationProfileConfig]:
        """Get a profile by ID."""
        pid = profile_id.lower().replace(" ", "_")
        if pid in BUILTIN_PROFILES:
            return BUILTIN_PROFILES[pid]
        return self._custom_cache.get(pid)

    # ── Create ────────────────────────────────────────────────

    def create_profile(
        self,
        name: str,
        description: str = "",
        base_profile_id: Optional[str] = None,
    ) -> OptimizationProfileConfig:
        """
        Create a new custom profile.
        Optionally base it on an existing profile.
        """
        pid = name.lower().replace(" ", "_")
        if pid in BUILTIN_PROFILES:
            raise ValueError(f"Cannot overwrite built-in profile '{name}'")
        if pid in self._custom_cache:
            raise ValueError(f"Profile '{name}' already exists")

        if base_profile_id:
            base = self.get_profile(base_profile_id)
            if base:
                profile = copy.deepcopy(base)
                profile.id = pid
                profile.name = name
                profile.description = description or base.description
                profile.profile_type = ProfileType.CUSTOM
                profile.created_at = time.time()
                profile.modified_at = time.time()
            else:
                raise ValueError(f"Base profile '{base_profile_id}' not found")
        else:
            profile = OptimizationProfileConfig(
                id=pid,
                name=name,
                description=description,
                profile_type=ProfileType.CUSTOM,
            )

        self._custom_cache[pid] = profile
        self._save_custom(profile)
        return profile

    # ── Edit ──────────────────────────────────────────────────

    def update_profile(
        self,
        profile_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
        optimizations: Optional[List[ProfileOptimizationRule]] = None,
        thresholds: Optional[MonitoringThresholds] = None,
        power: Optional[PowerConfig] = None,
        cleanup: Optional[CleanupRecommendation] = None,
        background_policy: Optional[BackgroundWorkloadPolicy] = None,
    ) -> Optional[OptimizationProfileConfig]:
        """Update a custom profile. Built-in profiles cannot be modified."""
        profile = self.get_profile(profile_id)
        if not profile:
            return None
        if profile.is_built_in:
            raise ValueError(f"Cannot modify built-in profile '{profile.name}'")

        if name is not None:
            profile.name = name
        if description is not None:
            profile.description = description
        if optimizations is not None:
            profile.optimizations = optimizations
        if thresholds is not None:
            profile.thresholds = thresholds
        if power is not None:
            profile.power = power
        if cleanup is not None:
            profile.cleanup = cleanup
        if background_policy is not None:
            profile.background_policy = background_policy

        profile.modified_at = time.time()
        self._custom_cache[profile.id] = profile
        self._save_custom(profile)
        return profile

    # ── Duplicate ─────────────────────────────────────────────

    def duplicate_profile(
        self, source_id: str, new_name: str
    ) -> Optional[OptimizationProfileConfig]:
        """Duplicate a profile (built-in or custom) as a new custom profile."""
        source = self.get_profile(source_id)
        if not source:
            return None
        return self.create_profile(
            name=new_name,
            description=f"Copy of {source.name}",
            base_profile_id=source_id,
        )

    # ── Delete ────────────────────────────────────────────────

    def delete_profile(self, profile_id: str) -> bool:
        """Delete a custom profile. Built-in profiles cannot be deleted."""
        pid = profile_id.lower().replace(" ", "_")
        if pid in BUILTIN_PROFILES:
            raise ValueError(f"Cannot delete built-in profile '{pid}'")
        if pid not in self._custom_cache:
            return False

        del self._custom_cache[pid]
        filepath = os.path.join(self._dir, f"{pid}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
        return True

    # ── Reset ─────────────────────────────────────────────────

    def reset_profile(self, profile_id: str) -> Optional[OptimizationProfileConfig]:
        """
        Reset a custom profile to its last saved state.
        For built-in profiles, returns a fresh copy of defaults.
        """
        pid = profile_id.lower().replace(" ", "_")
        if pid in BUILTIN_PROFILES:
            return copy.deepcopy(BUILTIN_PROFILES[pid])
        # Reload from disk
        self._load_custom()
        return self._custom_cache.get(pid)

    # ── Export / Import ───────────────────────────────────────

    def export_profile(self, profile_id: str) -> Optional[Dict]:
        """Export a profile as a portable dict."""
        profile = self.get_profile(profile_id)
        if not profile:
            return None
        data = profile.to_dict()
        data["export_version"] = 1
        data["exported_at"] = time.time()
        return data

    def import_profile(self, data: Dict) -> Optional[OptimizationProfileConfig]:
        """Import a profile from an exported dict."""
        try:
            # Strip export metadata
            data.pop("export_version", None)
            data.pop("exported_at", None)

            # Force as custom
            data["profile_type"] = "CUSTOM"
            if not data.get("id"):
                data["id"] = f"custom_{uuid.uuid4().hex[:8]}"

            profile = OptimizationProfileConfig.from_dict(data)
            pid = profile.id

            # Overwrite if exists
            self._custom_cache[pid] = profile
            self._save_custom(profile)
            return profile
        except Exception as e:
            logger.error(f"Profile import error: {e}")
            return None

    def export_profile_to_file(self, profile_id: str, filepath: str) -> bool:
        """Export a profile to a JSON file."""
        data = self.export_profile(profile_id)
        if not data:
            return False
        try:
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception as e:
            logger.error(f"Profile export error: {e}")
            return False

    def import_profile_from_file(self, filepath: str) -> Optional[OptimizationProfileConfig]:
        """Import a profile from a JSON file."""
        try:
            with open(filepath) as f:
                data = json.load(f)
            return self.import_profile(data)
        except Exception as e:
            logger.error(f"Profile import error: {e}")
            return None

    # ── Explanation ───────────────────────────────────────────

    def explain_profile(self, profile_id: str) -> str:
        """Get a full explanation of what a profile does."""
        profile = self.get_profile(profile_id)
        if not profile:
            return f"Profile '{profile_id}' not found."
        return profile.explain()

    # ── Compatibility ─────────────────────────────────────────

    def get_profile_id_list(self) -> List[str]:
        """Get all profile IDs (for backward compatibility)."""
        return list(BUILTIN_PROFILES.keys()) + list(self._custom_cache.keys())

    # ── Internal ──────────────────────────────────────────────

    def _load_custom(self):
        """Load custom profiles from disk."""
        self._custom_cache.clear()
        try:
            for fname in os.listdir(self._dir):
                if fname.endswith(".json"):
                    filepath = os.path.join(self._dir, fname)
                    try:
                        with open(filepath) as f:
                            data = json.load(f)
                        profile = OptimizationProfileConfig.from_dict(data)
                        if profile.profile_type != ProfileType.BUILT_IN:
                            self._custom_cache[profile.id] = profile
                    except Exception as e:
                        logger.debug(f"Failed to load profile {fname}: {e}")
        except Exception:
            pass

    def _save_custom(self, profile: OptimizationProfileConfig):
        """Save a custom profile to disk."""
        try:
            filepath = os.path.join(self._dir, f"{profile.id}.json")
            with open(filepath, "w") as f:
                json.dump(profile.to_dict(), f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save profile {profile.name}: {e}")


# ── Singleton ────────────────────────────────────────────────────

profile_manager = OptimizationProfileManager()
