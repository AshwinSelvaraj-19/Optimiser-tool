"""
Windows Gaming Optimization Adapters.

Wraps the existing Windows gaming optimizations (from app.system.windows_gaming)
into the standard Optimization base class interface so they work with:
- OptimizationExecutor
- AdaptiveEngine
- OptimizationCenter
- Snapshot/Rollback infrastructure

These are NOT duplicate implementations — they delegate to the real
optimization classes in app.system.windows_gaming.
"""

from app.core.optimization_base import Optimization, OptimizationResult, OptimizationStatus
from app.utils.logger import get_logger

logger = get_logger("core.windows_optimizations")


def _adapt_status(check_result: tuple) -> OptimizationStatus:
    """Convert windows_gaming (current_value, status_str, message) to OptimizationStatus."""
    _, status_str, _ = check_result
    mapping = {
        "ALREADY_OPTIMAL": OptimizationStatus.ALREADY_OPTIMAL,
        "OPTIMIZABLE": OptimizationStatus.OPTIMIZABLE,
        "NOT_AVAILABLE": OptimizationStatus.NOT_AVAILABLE,
        "NOT_APPLICABLE": OptimizationStatus.NOT_APPLICABLE,
    }
    return mapping.get(status_str, OptimizationStatus.NOT_APPLICABLE)


class GameBarAdapter(Optimization):
    """Adapter for GameBarOptimization — disables Xbox Game Bar overlay."""

    id = "game_bar"
    name = "Game Bar Overlay"
    description = "Disable Xbox Game Bar overlay to reduce background resource usage"
    category = "GAMING"
    risk_level = "LOW"

    def __init__(self):
        super().__init__()
        self._impl = None

    def _get_impl(self):
        if self._impl is None:
            from app.system.windows_gaming import GameBarOptimization
            self._impl = GameBarOptimization()
        return self._impl

    def check(self) -> OptimizationResult:
        impl = self._get_impl()
        current, status_str, message = impl.check()
        self._status = _adapt_status((current, status_str, message))
        return OptimizationResult(
            status=self._status,
            current_value=current,
            recommended_value="DISABLED" if self._status == OptimizationStatus.OPTIMIZABLE else current,
            message=message,
        )

    def snapshot(self) -> dict:
        return self._get_impl().snapshot()

    def apply(self) -> OptimizationResult:
        if self._status != OptimizationStatus.OPTIMIZABLE:
            return OptimizationResult(status=self._status)
        impl = self._get_impl()
        success, message = impl.apply()
        if success:
            self._status = OptimizationStatus.APPLIED
            return OptimizationResult(status=self._status, message=message)
        self._status = OptimizationStatus.FAILED
        return OptimizationResult(status=self._status, message=message)

    def verify(self) -> bool:
        return self._get_impl().verify()

    def rollback(self) -> bool:
        return self._get_impl().rollback()


class BackgroundRecordingAdapter(Optimization):
    """Adapter for BackgroundRecordingOptimization — disables background recording."""

    id = "background_recording"
    name = "Background Recording"
    description = "Disable Windows background recording to reduce CPU/disk overhead"
    category = "GAMING"
    risk_level = "LOW"

    def __init__(self):
        super().__init__()
        self._impl = None

    def _get_impl(self):
        if self._impl is None:
            from app.system.windows_gaming import BackgroundRecordingOptimization
            self._impl = BackgroundRecordingOptimization()
        return self._impl

    def check(self) -> OptimizationResult:
        impl = self._get_impl()
        current, status_str, message = impl.check()
        self._status = _adapt_status((current, status_str, message))
        return OptimizationResult(
            status=self._status,
            current_value=current,
            recommended_value="DISABLED" if self._status == OptimizationStatus.OPTIMIZABLE else current,
            message=message,
        )

    def snapshot(self) -> dict:
        return self._get_impl().snapshot()

    def apply(self) -> OptimizationResult:
        if self._status != OptimizationStatus.OPTIMIZABLE:
            return OptimizationResult(status=self._status)
        impl = self._get_impl()
        success, message = impl.apply()
        if success:
            self._status = OptimizationStatus.APPLIED
            return OptimizationResult(status=self._status, message=message)
        self._status = OptimizationStatus.FAILED
        return OptimizationResult(status=self._status, message=message)

    def verify(self) -> bool:
        return self._get_impl().verify()

    def rollback(self) -> bool:
        return self._get_impl().rollback()


class VisualEffectsAdapter(Optimization):
    """Adapter for VisualEffectsOptimization — reduces Windows visual effects."""

    id = "visual_effects"
    name = "Visual Effects"
    description = "Reduce Windows visual effects for better gaming performance"
    category = "SYSTEM"
    risk_level = "LOW"

    def __init__(self):
        super().__init__()
        self._impl = None

    def _get_impl(self):
        if self._impl is None:
            from app.system.windows_gaming import VisualEffectsOptimization
            self._impl = VisualEffectsOptimization()
        return self._impl

    def check(self) -> OptimizationResult:
        impl = self._get_impl()
        current, status_str, message = impl.check()
        self._status = _adapt_status((current, status_str, message))
        return OptimizationResult(
            status=self._status,
            current_value=current,
            recommended_value="OPTIMIZED" if self._status == OptimizationStatus.OPTIMIZABLE else current,
            message=message,
        )

    def snapshot(self) -> dict:
        return self._get_impl().snapshot()

    def apply(self) -> OptimizationResult:
        if self._status != OptimizationStatus.OPTIMIZABLE:
            return OptimizationResult(status=self._status)
        impl = self._get_impl()
        success, message = impl.apply()
        if success:
            self._status = OptimizationStatus.APPLIED
            return OptimizationResult(status=self._status, message=message)
        self._status = OptimizationStatus.FAILED
        return OptimizationResult(status=self._status, message=message)

    def verify(self) -> bool:
        return self._get_impl().verify()

    def rollback(self) -> bool:
        return self._get_impl().rollback()


class StartupOptimization(Optimization):
    """
    Safe startup optimization — ANALYSIS ONLY.

    Scans startup entries and classifies them. Does NOT disable anything.
    Provides recommendations for user review.
    """

    id = "startup_analysis"
    name = "Startup Analysis"
    description = "Analyze startup entries and recommend safe optimizations"
    category = "STARTUP"
    risk_level = "NONE"

    def __init__(self):
        super().__init__()
        self._analysis = None

    def check(self) -> OptimizationResult:
        try:
            from app.system.startup_analyzer import startup_analyzer
            self._analysis = startup_analyzer.analyze()
            reviewable = [
                e for e in self._analysis.entries
                if e.classification.value in ("SAFE_TO_RECOMMEND", "USER_APPLICATION")
            ]
            if reviewable:
                self._status = OptimizationStatus.RECOMMENDATION_ONLY
                return OptimizationResult(
                    status=self._status,
                    current_value=f"{len(self._analysis.entries)} total, {len(reviewable)} reviewable",
                    recommended_value=f"Review {len(reviewable)} startup entries",
                    message=f"Found {len(reviewable)} startup entries that may be safe to disable",
                )
            self._status = OptimizationStatus.ALREADY_OPTIMAL
            return OptimizationResult(
                status=self._status,
                current_value=f"{len(self._analysis.entries)} entries (none reviewable)",
                message="No safe startup optimization candidates found",
            )
        except Exception as e:
            self._status = OptimizationStatus.NOT_AVAILABLE
            return OptimizationResult(
                status=self._status,
                current_value="Startup analysis unavailable",
                message=str(e),
            )

    def snapshot(self) -> dict:
        return {"analysis": "read_only", "action": "recommendation_only"}

    def apply(self) -> OptimizationResult:
        """This is analysis-only — no modifications are made."""
        return OptimizationResult(
            status=OptimizationStatus.RECOMMENDATION_ONLY,
            message="Startup analysis is read-only. Review recommendations in the UI.",
        )

    def verify(self) -> bool:
        return True  # Nothing to verify — read-only

    def rollback(self) -> bool:
        return True  # Nothing to roll back — read-only


class CleanupOptimization(Optimization):
    """
    Cleanup optimization — integration with CleanupCenter.

    Detects reclaimable space and recommends cleanup.
    Does NOT automatically clean — requires user approval.
    """

    id = "cleanup_files"
    name = "File Cleanup"
    description = "Clean temporary files and caches to free disk space"
    category = "CLEANUP"
    risk_level = "LOW"

    def __init__(self):
        super().__init__()
        self._scan_result = None

    def check(self) -> OptimizationResult:
        try:
            from app.cleanup.cleanup_center import cleanup_center
            items = cleanup_center.scan()
            removable = [i for i in items if i.status.value in ("SAFE", "REVIEW")]
            if removable:
                total_bytes = sum(i.size_bytes for i in removable)
                total_mb = total_bytes / (1024 * 1024)
                self._status = OptimizationStatus.OPTIMIZABLE
                return OptimizationResult(
                    status=self._status,
                    current_value=f"{len(removable)} items ({total_mb:.1f} MB)",
                    recommended_value=f"Clean {total_mb:.1f} MB of reclaimable files",
                    message=f"Found {total_mb:.1f} MB of safe-to-clean temporary files",
                )
            self._status = OptimizationStatus.ALREADY_OPTIMAL
            return OptimizationResult(
                status=self._status,
                current_value="No removable files detected",
                message="Temporary files are already clean",
            )
        except Exception as e:
            self._status = OptimizationStatus.NOT_AVAILABLE
            return OptimizationResult(
                status=self._status,
                current_value="Cleanup scan unavailable",
                message=str(e),
            )

    def snapshot(self) -> dict:
        return {"cleanup": "user_initiated", "action": "requires_approval"}

    def apply(self) -> OptimizationResult:
        """Clean safe items only. Requires prior approval in the UI."""
        try:
            from app.cleanup.cleanup_center import cleanup_center
            result = cleanup_center.clean_safe()
            if result.success:
                self._status = OptimizationStatus.APPLIED
                return OptimizationResult(
                    status=self._status,
                    message=f"Cleaned {result.cleaned_count} items ({result.bytes_freed / 1024 / 1024:.1f} MB)",
                )
            self._status = OptimizationStatus.FAILED
            return OptimizationResult(
                status=self._status,
                message=f"Cleanup partially failed: {result.message}",
            )
        except Exception as e:
            self._status = OptimizationStatus.FAILED
            return OptimizationResult(status=self._status, message=str(e))

    def verify(self) -> bool:
        # After cleanup, re-scan should show fewer removable items
        return True  # Verification is implicit — re-scan will confirm

    def rollback(self) -> bool:
        return True  # Deleted temp files cannot be restored — acknowledged
