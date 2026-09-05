"""
Heaven Society — Optimization Command Center

Provides optimization-focused UI components:
- OptimizationCategory cards with status
- OptimizationStatus indicators
- ActiveOptimizationTracker
- OptimizationResult display

Centralizes the optimization UX so the OptimizerPage focuses on
"What can be optimized?" rather than raw telemetry.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional

from app.utils.logger import get_logger

logger = get_logger("ui.optimization_center")


# ══════════════════════════════════════════════════════════════
#  ENUMS
# ══════════════════════════════════════════════════════════════


class OptimizationStatus(Enum):
    """Current state of an optimization."""
    UNKNOWN = "UNKNOWN"
    CURRENT = "CURRENT"        # Already at optimal state
    RECOMMENDED = "RECOMMENDED"  # Should be applied
    APPLIED = "APPLIED"        # Successfully applied
    FAILED = "FAILED"          # Application failed
    ROLLED_BACK = "ROLLED_BACK"  # Was applied, now reverted
    INACTIVE = "INACTIVE"      # Not applicable


class OptimizationRisk(Enum):
    """Risk level of an optimization."""
    SAFE = "SAFE"
    LOW = "LOW"
    REVIEW = "REVIEW"
    HIGH = "HIGH"


class OptimizationCategory(Enum):
    """High-level optimization categories."""
    PERFORMANCE = "PERFORMANCE"
    MEMORY = "MEMORY"
    POWER = "POWER"
    GAMING = "GAMING"
    STARTUP = "STARTUP"
    CLEANUP = "CLEANUP"
    SYSTEM = "SYSTEM"


# ══════════════════════════════════════════════════════════════
#  DATA MODELS
# ══════════════════════════════════════════════════════════════


@dataclass
class OptimizationItem:
    """One optimization entry in the command center."""
    opt_id: str
    name: str
    description: str
    category: OptimizationCategory
    current_state: str = "Unknown"
    recommended_state: str = ""
    risk: OptimizationRisk = OptimizationRisk.LOW
    reversible: bool = True
    requires_admin: bool = False
    status: OptimizationStatus = OptimizationStatus.UNKNOWN
    why: str = ""  # Why it is recommended
    result_detail: str = ""  # Apply result detail
    applied_at: Optional[float] = None

    def to_dict(self) -> dict:
        return {
            "opt_id": self.opt_id,
            "name": self.name,
            "category": self.category.value,
            "status": self.status.value,
            "current_state": self.current_state,
            "recommended_state": self.recommended_state,
            "risk": self.risk.value,
            "reversible": self.reversible,
            "requires_admin": self.requires_admin,
        }


@dataclass
class ActiveOptimization:
    """A currently-applied reversible optimization."""
    opt_id: str
    name: str
    category: str
    applied_at: float = 0.0
    previous_state: str = ""
    current_state: str = ""
    rollback_available: bool = True


@dataclass
class OptimizationResult:
    """Result of applying an optimization."""
    opt_id: str
    name: str
    success: bool
    verification_passed: bool = False
    before_state: str = ""
    after_state: str = ""
    impact: str = "INSUFFICIENT_DATA"  # HELPED / NO_SIGNIFICANT_CHANGE / HARMFUL / INSUFFICIENT_DATA
    rollback_available: bool = True
    message: str = ""


# ══════════════════════════════════════════════════════════════
#  OPTIMIZATION REGISTRY (builds from existing implementations)
# ══════════════════════════════════════════════════════════════


# Mapping from optimization ID to command center metadata
# Categories match the actual optimization implementations
_OPTIMIZATION_REGISTRY: Dict[str, dict] = {
    # POWER
    "power_plan": {
        "name": "Power Plan",
        "description": "Switch Windows power plan for optimal performance",
        "category": OptimizationCategory.POWER,
        "risk": OptimizationRisk.LOW,
        "reversible": True,
        "requires_admin": True,
    },
    # PERFORMANCE
    "background_load": {
        "name": "Background Load",
        "description": "Detect optional background applications consuming resources",
        "category": OptimizationCategory.PERFORMANCE,
        "risk": OptimizationRisk.LOW,
        "reversible": True,
        "requires_admin": False,
    },
    # MEMORY
    "memory_analysis": {
        "name": "Memory Analysis",
        "description": "Analyze memory pressure and identify heavy processes",
        "category": OptimizationCategory.MEMORY,
        "risk": OptimizationRisk.SAFE,
        "reversible": False,
        "requires_admin": False,
    },
    # GAMING
    "game_mode": {
        "name": "Game Mode",
        "description": "Enable Windows Game Mode for gaming optimization",
        "category": OptimizationCategory.GAMING,
        "risk": OptimizationRisk.SAFE,
        "reversible": True,
        "requires_admin": False,
    },
    "emulator_priority": {
        "name": "Process Priority",
        "description": "Raise emulator/game process priority for better CPU scheduling",
        "category": OptimizationCategory.GAMING,
        "risk": OptimizationRisk.LOW,
        "reversible": True,
        "requires_admin": False,
    },
    "game_bar": {
        "name": "Game Bar Overlay",
        "description": "Disable Xbox Game Bar overlay to reduce background usage",
        "category": OptimizationCategory.GAMING,
        "risk": OptimizationRisk.LOW,
        "reversible": True,
        "requires_admin": False,
    },
    "background_recording": {
        "name": "Background Recording",
        "description": "Disable background recording to reduce CPU/disk overhead",
        "category": OptimizationCategory.GAMING,
        "risk": OptimizationRisk.LOW,
        "reversible": True,
        "requires_admin": False,
    },
    # STARTUP
    "startup_analysis": {
        "name": "Startup Analysis",
        "description": "Analyze startup entries and recommend safe optimizations",
        "category": OptimizationCategory.STARTUP,
        "risk": OptimizationRisk.SAFE,
        "reversible": False,
        "requires_admin": False,
    },
    # CLEANUP
    "cleanup_files": {
        "name": "File Cleanup",
        "description": "Clean temporary files and caches to free disk space",
        "category": OptimizationCategory.CLEANUP,
        "risk": OptimizationRisk.LOW,
        "reversible": False,  # Deleted files cannot be restored
        "requires_admin": False,
    },
    # SYSTEM
    "visual_effects": {
        "name": "Visual Effects",
        "description": "Reduce Windows visual effects for better performance",
        "category": OptimizationCategory.SYSTEM,
        "risk": OptimizationRisk.LOW,
        "reversible": True,
        "requires_admin": False,
    },
}


def get_optimization_items() -> List[OptimizationItem]:
    """Build the optimization items list from the registry."""
    items = []
    for opt_id, meta in _OPTIMIZATION_REGISTRY.items():
        items.append(OptimizationItem(
            opt_id=opt_id,
            name=meta["name"],
            description=meta["description"],
            category=meta["category"],
            risk=OptimizationRisk(meta["risk"].value) if isinstance(meta["risk"], OptimizationRisk) else meta["risk"],
            reversible=meta["reversible"],
            requires_admin=meta["requires_admin"],
        ))
    return items


def get_optimization_items_by_category() -> Dict[OptimizationCategory, List[OptimizationItem]]:
    """Group optimization items by category."""
    items = get_optimization_items()
    groups: Dict[OptimizationCategory, List[OptimizationItem]] = {}
    for item in items:
        groups.setdefault(item.category, []).append(item)
    return groups


def get_category_label(cat: OptimizationCategory) -> str:
    """Human-readable category label."""
    labels = {
        OptimizationCategory.PERFORMANCE: "PERFORMANCE",
        OptimizationCategory.MEMORY: "MEMORY",
        OptimizationCategory.POWER: "POWER",
        OptimizationCategory.GAMING: "GAMING",
        OptimizationCategory.STARTUP: "STARTUP",
        OptimizationCategory.CLEANUP: "CLEANUP",
        OptimizationCategory.SYSTEM: "SYSTEM",
    }
    return labels.get(cat, cat.value)


def get_category_icon(cat: OptimizationCategory) -> str:
    """Compact icon/emoji for each category."""
    icons = {
        OptimizationCategory.PERFORMANCE: "\u26a1",  # ⚡
        OptimizationCategory.MEMORY: "\U0001f9e0",    # 🧠
        OptimizationCategory.POWER: "\U0001f50b",     # 🔋
        OptimizationCategory.GAMING: "\U0001f3ae",    # 🎮
        OptimizationCategory.STARTUP: "🚀",   # 🚀
        OptimizationCategory.CLEANUP: "\U0001f9f9",   # 🧹
        OptimizationCategory.SYSTEM: "\u2699\ufe0f",  # ⚙️
    }
    return icons.get(cat, "\u25cf")


def get_status_color(status: OptimizationStatus) -> str:
    """Return a color string for a status."""
    from app.ui.theme import STATUS_OK, STATUS_WARN, STATUS_ERROR, ACCENT_PRIMARY, TEXT_TERTIARY
    colors = {
        OptimizationStatus.CURRENT: STATUS_OK,
        OptimizationStatus.RECOMMENDED: STATUS_WARN,
        OptimizationStatus.APPLIED: STATUS_OK,
        OptimizationStatus.FAILED: STATUS_ERROR,
        OptimizationStatus.ROLLED_BACK: ACCENT_PRIMARY,
        OptimizationStatus.INACTIVE: TEXT_TERTIARY,
        OptimizationStatus.UNKNOWN: TEXT_TERTIARY,
    }
    return colors.get(status, TEXT_TERTIARY)


def get_status_label(status: OptimizationStatus) -> str:
    """Human-readable status label."""
    labels = {
        OptimizationStatus.CURRENT: "OPTIMAL",
        OptimizationStatus.RECOMMENDED: "RECOMMENDED",
        OptimizationStatus.APPLIED: "ACTIVE",
        OptimizationStatus.FAILED: "FAILED",
        OptimizationStatus.ROLLED_BACK: "RESTORED",
        OptimizationStatus.INACTIVE: "N/A",
        OptimizationStatus.UNKNOWN: "CHECKING",
    }
    return labels.get(status, "UNKNOWN")
