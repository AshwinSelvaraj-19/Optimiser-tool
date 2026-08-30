"""
Optimization profiles — backward-compatible with existing tests.

Provides:
- ProfileManager, OptimizationProfile, ProfileSetting (existing interface)
- BALANCED, GAMING, MAX_PERFORMANCE optimization profiles (new engine)

Profile differentiation:
  BALANCED:    Game Mode only (safe, minimal)
  GAMING:      Game Mode + Power Plan + Emulator Priority (if admin)
  MAX PERF:    Game Mode + Power Plan + Emulator Priority + Background review
"""

import json
import os
from dataclasses import dataclass, field
from typing import List, Optional


# ── Existing backward-compatible classes ────────────────────

@dataclass
class ProfileSetting:
    """A single profile setting."""
    key: str = ""
    name: str = ""
    description: str = ""
    default_value: any = None
    current_value: any = None
    options: list = field(default_factory=list)


@dataclass
class OptimizationProfile:
    """Optimization profile with settings."""
    name: str = ""
    description: str = ""
    target: str = ""  # MAX FPS, BALANCED, etc.
    settings: list = field(default_factory=list)


class ProfileManager:
    """Manages optimization profiles from JSON files."""

    DEFAULT_PROFILES = {
        "max_fps": OptimizationProfile(
            name="MAX FPS",
            description="Maximum FPS for competitive gaming",
            target="MAX FPS",
            settings=[
                ProfileSetting(key="power_plan", name="Power Plan", description="High Performance", default_value="high_performance"),
                ProfileSetting(key="gpu_preference", name="GPU Preference", description="High Performance GPU", default_value="high_performance"),
                ProfileSetting(key="game_mode", name="Game Mode", description="Enable Windows Game Mode", default_value=True),
                ProfileSetting(key="background_load", name="Background Load", description="Close background processes", default_value=True),
                ProfileSetting(key="emulator_cpu", name="Emulator CPU", description="Optimize CPU allocation", default_value="auto"),
                ProfileSetting(key="emulator_ram", name="Emulator RAM", description="Optimize RAM allocation", default_value="auto"),
            ],
        ),
        "balanced": OptimizationProfile(
            name="BALANCED",
            description="Balanced performance and system stability",
            target="BALANCED",
            settings=[
                ProfileSetting(key="power_plan", name="Power Plan", description="Balanced", default_value="balanced"),
                ProfileSetting(key="game_mode", name="Game Mode", description="Enable Windows Game Mode", default_value=True),
            ],
        ),
    }

    def __init__(self, profiles_dir: str = None):
        if profiles_dir is None:
            profiles_dir = os.path.join(
                os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
                "profiles"
            )
        self._dir = profiles_dir
        os.makedirs(self._dir, exist_ok=True)

    def list_profiles(self) -> list:
        profiles = []
        for key, profile in self.DEFAULT_PROFILES.items():
            profiles.append({"key": key, "name": profile.name, "description": profile.description})
        for fname in os.listdir(self._dir):
            if fname.endswith(".json"):
                key = fname.replace(".json", "")
                if key not in self.DEFAULT_PROFILES:
                    try:
                        with open(os.path.join(self._dir, fname)) as f:
                            data = json.load(f)
                        profiles.append({"key": key, "name": data.get("name", key), "description": data.get("description", "")})
                    except Exception:
                        continue
        return profiles

    def get_profile(self, name: str) -> Optional[OptimizationProfile]:
        name_lower = name.lower().replace(" ", "_")
        for key, profile in self.DEFAULT_PROFILES.items():
            if key == name_lower or profile.name.lower() == name.lower():
                return profile
        safe_name = name.lower().replace(" ", "_")
        filepath = os.path.join(self._dir, f"{safe_name}.json")
        if not os.path.exists(filepath):
            filepath = os.path.join(self._dir, f"{name}.json")
        if os.path.exists(filepath):
            try:
                with open(filepath) as f:
                    data = json.load(f)
                settings = [ProfileSetting(**s) for s in data.get("settings", [])]
                return OptimizationProfile(
                    name=data.get("name", name),
                    description=data.get("description", ""),
                    target=data.get("target", ""),
                    settings=settings,
                )
            except Exception:
                pass
        return None

    def save_custom_profile(self, profile: OptimizationProfile) -> bool:
        try:
            data = {
                "name": profile.name,
                "description": profile.description,
                "target": profile.target,
                "settings": [
                    {"key": s.key, "name": s.name, "description": s.description,
                     "default_value": s.default_value, "current_value": s.current_value,
                     "options": s.options}
                    for s in profile.settings
                ],
            }
            filepath = os.path.join(self._dir, f"{profile.name.lower().replace(' ', '_')}.json")
            with open(filepath, "w") as f:
                json.dump(data, f, indent=2)
            return True
        except Exception:
            return False


# ── New optimization profiles for the engine ───────────────

@dataclass
class ProfileOptimization:
    """A single optimization in a new-style profile."""
    opt_id: str = ""
    name: str = ""
    enabled: bool = True
    description: str = ""


@dataclass
class NewOptimizationProfile:
    """A named optimization profile for the new engine."""
    id: str = ""
    name: str = ""
    description: str = ""
    optimizations: List[ProfileOptimization] = field(default_factory=list)


# ── BALANCED — Safe, minimal changes ───────────────────────
# Only Game Mode: reversible registry change, no system impact
BALANCED = NewOptimizationProfile(
    id="balanced",
    name="BALANCED",
    description="Safe, minimal changes. Game Mode only.",
    optimizations=[
        ProfileOptimization(
            opt_id="game_mode", name="Game Mode",
            description="Enable Windows Game Mode",
        ),
    ],
)

# ── GAMING — Standard gaming optimizations ─────────────────
# Game Mode + Power Plan + Emulator Priority (when admin)
GAMING = NewOptimizationProfile(
    id="gaming",
    name="GAMING",
    description="Game Mode, High Performance power plan, emulator priority, memory analysis.",
    optimizations=[
        ProfileOptimization(
            opt_id="power_plan", name="Power Plan",
            description="Switch to High Performance power plan",
        ),
        ProfileOptimization(
            opt_id="game_mode", name="Game Mode",
            description="Enable Windows Game Mode",
        ),
        ProfileOptimization(
            opt_id="emulator_priority", name="Emulator Priority",
            description="Set emulator process to high priority (requires admin)",
        ),
        ProfileOptimization(
            opt_id="memory_analysis", name="Memory Analysis",
            description="Analyze memory pressure and provide safe recommendations",
        ),
    ],
)

# ── MAX PERFORMANCE — All available verified optimizations ──
# Power + Game Mode + Priority + Affinity + Background review
MAX_PERFORMANCE = NewOptimizationProfile(
    id="max_performance",
    name="MAX PERFORMANCE",
    description="All verified optimizations plus Windows gaming and diagnostics.",
    optimizations=[
        ProfileOptimization(
            opt_id="power_plan", name="Power Plan",
            description="Switch to High Performance power plan",
        ),
        ProfileOptimization(
            opt_id="game_mode", name="Game Mode",
            description="Enable Windows Game Mode",
        ),
        ProfileOptimization(
            opt_id="game_bar", name="Game Bar",
            description="Disable Xbox Game Bar overlay",
        ),
        ProfileOptimization(
            opt_id="background_recording", name="Background Recording",
            description="Disable background recording",
        ),
        ProfileOptimization(
            opt_id="emulator_priority", name="Emulator Priority",
            description="Set emulator process to high priority (requires admin)",
        ),
        ProfileOptimization(
            opt_id="cpu_affinity", name="CPU Affinity",
            description="Optimize CPU core assignment for the emulator",
        ),
        ProfileOptimization(
            opt_id="memory_analysis", name="Memory Analysis",
            description="Analyze memory pressure and provide safe recommendations",
        ),
        ProfileOptimization(
            opt_id="background_load", name="Background Load",
            description="Review optional background processes (recommendation only)",
        ),
    ],
)

PROFILES = {
    "balanced": BALANCED,
    "gaming": GAMING,
    "max_performance": MAX_PERFORMANCE,
}


def get_profile(profile_id: str) -> NewOptimizationProfile:
    """Get a new-style profile by ID."""
    return PROFILES.get(profile_id, GAMING)


def get_all_profiles() -> list:
    """Get all new-style profiles."""
    return list(PROFILES.values())
