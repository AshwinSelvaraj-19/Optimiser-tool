"""
Base optimization class — every optimization implements this interface.
Each optimization follows: CHECK → SNAPSHOT → APPLY → VERIFY → ROLLBACK
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional, List


class OptimizationStatus(Enum):
    PENDING = "PENDING"
    CHECKED = "CHECKED"
    OPTIMIZABLE = "OPTIMIZABLE"
    NOT_APPLICABLE = "NOT APPLICABLE"
    ALREADY_OPTIMAL = "ALREADY OPTIMAL"
    REQUIRES_ADMIN = "REQUIRES_ADMIN"
    RECOMMENDATION_ONLY = "RECOMMENDATION ONLY"
    SNAPSHOT_TAKEN = "SNAPSHOT TAKEN"
    APPLIED = "APPLIED"
    VERIFIED = "VERIFIED"
    REVERTED = "REVERTED"
    FAILED = "FAILED"
    NOT_AVAILABLE = "NOT AVAILABLE"


@dataclass
class OptimizationResult:
    """Result of an optimization operation."""
    status: OptimizationStatus = OptimizationStatus.PENDING
    current_value: str = ""
    recommended_value: str = ""
    message: str = ""
    snapshot_data: Optional[dict] = None


@dataclass
class OptimizationSessionResult:
    """Structured result of an optimization session."""
    session_id: str = ""
    profile_id: str = ""
    profile_name: str = ""
    target_name: str = ""
    target_pid: int = 0
    started_at: str = ""
    completed_at: str = ""
    duration_seconds: float = 0.0

    # Per-optimization results
    applied: List["OptResult"] = field(default_factory=list)
    already_optimal: List["OptResult"] = field(default_factory=list)
    requires_admin: List["OptResult"] = field(default_factory=list)
    failed: List["OptResult"] = field(default_factory=list)
    recommendation_only: List["OptResult"] = field(default_factory=list)
    not_available: List["OptResult"] = field(default_factory=list)

    # Aggregate
    success: bool = True
    rollback_available: bool = False
    message: str = ""
    busy: bool = False

    @property
    def applied_count(self) -> int:
        return len(self.applied)

    @property
    def optimal_count(self) -> int:
        return len(self.already_optimal)

    @property
    def admin_count(self) -> int:
        return len(self.requires_admin)

    @property
    def failed_count(self) -> int:
        return len(self.failed)

    @property
    def review_count(self) -> int:
        return len(self.recommendation_only)

    @property
    def all_results(self) -> list:
        return (
            self.applied + self.already_optimal + self.requires_admin +
            self.failed + self.recommendation_only + self.not_available
        )


class Optimization(ABC):
    """
    Base class for all optimizations.
    Each optimization must implement all methods.
    """

    id: str = ""
    name: str = ""
    description: str = ""
    category: str = ""
    risk_level: str = "LOW"  # LOW, MEDIUM, HIGH

    def __init__(self):
        self._status = OptimizationStatus.PENDING
        self._snapshot_data: Optional[dict] = None

    @property
    def status(self) -> OptimizationStatus:
        return self._status

    @abstractmethod
    def check(self) -> OptimizationResult:
        """
        Check if this optimization is applicable.
        Returns current state and whether optimization is needed.
        """
        pass

    @abstractmethod
    def snapshot(self) -> dict:
        """
        Capture current state before modification.
        Must be called BEFORE apply().
        Returns snapshot data for rollback.
        """
        pass

    @abstractmethod
    def apply(self) -> OptimizationResult:
        """
        Apply the optimization.
        Must call snapshot() first or have snapshot data available.
        """
        pass

    @abstractmethod
    def verify(self) -> bool:
        """
        Verify the optimization was applied correctly.
        Returns True if verification passes.
        """
        pass

    @abstractmethod
    def rollback(self) -> bool:
        """
        Revert to the state captured by snapshot().
        Returns True if rollback succeeded.
        """
        pass

    def get_status_display(self) -> str:
        """Get human-readable status for UI."""
        return self._status.value

    def get_current_value(self) -> str:
        """Get current value for UI display."""
        result = self.check()
        return result.current_value

    def get_recommended_value(self) -> str:
        """Get recommended value for UI display."""
        result = self.check()
        return result.recommended_value
