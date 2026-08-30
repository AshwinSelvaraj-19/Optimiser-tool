"""
Optimization pipeline — safe, verified, reversible.

Features:
- Thread-safe operation locking (APPLY/RESTORE/BENCHMARK mutual exclusion)
- Target validation before apply (fresh PID detection)
- Session management with structured results
- Safe restore that only reverts actually-applied changes
- Live state refresh after apply/restore
"""

import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Callable

from app.core.optimization_base import (
    Optimization, OptimizationResult, OptimizationStatus, OptimizationSessionResult,
)
from app.core.optimizations import get_all_optimizations, get_optimization_by_id
from app.core.profiles import get_profile, NewOptimizationProfile
from app.core.snapshot import snapshot_manager, Snapshot
from app.core.rollback import rollback_engine, RollbackResult
from app.utils.logger import get_logger

logger = get_logger("core.optimizer")


@dataclass
class OptResult:
    """Result of applying a single optimization."""
    opt_id: str = ""
    name: str = ""
    status: str = ""  # APPLIED, ALREADY_OPTIMAL, REQUIRES_ADMIN, RECOMMENDATION_ONLY, FAILED, NOT_APPLICABLE, SKIPPED
    message: str = ""
    current_value: str = ""
    verified: bool = False
    rollback_available: bool = False


@dataclass
class RollbackEntry:
    """Result of rolling back a single optimization."""
    opt_id: str = ""
    name: str = ""
    action: str = ""  # RESTORED, SKIPPED, FAILED
    message: str = ""


@dataclass
class OptimizationReport:
    """Complete optimization report — structured, no log parsing needed."""
    profile_id: str = ""
    profile_name: str = ""
    timestamp: str = ""
    started_at: str = ""
    duration_seconds: float = 0.0

    # Counts
    applied_count: int = 0
    verified_count: int = 0
    already_optimal_count: int = 0
    requires_admin_count: int = 0
    recommendation_only_count: int = 0
    failed_count: int = 0
    skipped_count: int = 0

    # Detailed results
    results: list = field(default_factory=list)

    # Snapshot
    snapshot_id: str = ""
    snapshot: Optional[Snapshot] = None

    # Rollback
    rollback_results: list = field(default_factory=list)
    rollback_restored: int = 0
    rollback_skipped: int = 0
    rollback_failed: int = 0

    # Session result
    session: Optional[OptimizationSessionResult] = None

    # Performance (optional — only if measured)
    baseline_fps: Optional[float] = None
    baseline_1low: Optional[float] = None
    baseline_01low: Optional[float] = None
    baseline_frame_time: Optional[float] = None
    baseline_frame_variance: Optional[float] = None
    baseline_frame_spikes: Optional[int] = None
    post_fps: Optional[float] = None
    post_1low: Optional[float] = None
    post_01low: Optional[float] = None
    post_frame_time: Optional[float] = None
    post_frame_variance: Optional[float] = None
    post_frame_spikes: Optional[int] = None

    @property
    def fps_delta(self) -> Optional[float]:
        if self.baseline_fps is not None and self.post_fps is not None:
            return self.post_fps - self.baseline_fps
        return None

    @property
    def one_low_delta(self) -> Optional[float]:
        if self.baseline_1low is not None and self.post_1low is not None:
            return self.post_1low - self.baseline_1low
        return None

    @property
    def performance_measured(self) -> bool:
        return self.baseline_fps is not None and self.post_fps is not None


class Optimizer:
    """Optimization pipeline — safe, verified, reversible with session management."""

    def __init__(self):
        self._last_report: Optional[OptimizationReport] = None
        self._last_session: Optional[OptimizationSessionResult] = None
        self._progress_callback: Optional[Callable] = None
        self._lock = threading.Lock()
        self._operation: str = ""  # "", "APPLY", "RESTORE", "BENCHMARK"

    @property
    def last_report(self) -> Optional[OptimizationReport]:
        return self._last_report

    @property
    def last_session(self) -> Optional[OptimizationSessionResult]:
        return self._last_session

    @property
    def is_busy(self) -> bool:
        return self._operation != ""

    @property
    def current_operation(self) -> str:
        return self._operation

    def on_progress(self, callback):
        self._progress_callback = callback

    def _progress(self, pct: float, msg: str = ""):
        logger.info(f"[{pct*100:.0f}%] {msg}")
        if self._progress_callback:
            self._progress_callback(pct, msg)

    def _acquire_lock(self, operation: str) -> bool:
        """Try to acquire the operation lock. Returns False if busy."""
        if not self._lock.acquire(blocking=False):
            return False
        self._operation = operation
        return True

    def _release_lock(self):
        """Release the operation lock."""
        self._operation = ""
        self._lock.release()

    def _detect_target(self) -> tuple:
        """Detect current emulator target. Returns (name, pid) or empty."""
        try:
            from app.performance.target_process import target_process_detector
            best = target_process_detector.select_best_target()
            if best:
                return best.process_name, best.pid
        except Exception as e:
            logger.debug(f"Target detection: {e}")
        return "", 0

    def apply_profile(self, profile_id: str) -> OptimizationReport:
        """
        Apply an optimization profile with session management.

        Pipeline:
        1. Acquire lock (BUSY if already running)
        2. Detect target
        3. Create snapshot
        4. Check, snapshot, apply, verify each optimization
        5. Generate structured session result
        """
        if not self._acquire_lock("APPLY"):
            session = OptimizationSessionResult(
                busy=True, message="Another operation is running",
            )
            report = OptimizationReport(session=session)
            return report

        try:
            return self._apply_profile_inner(profile_id)
        finally:
            self._release_lock()

    def _apply_profile_inner(self, profile_id: str) -> OptimizationReport:
        now = datetime.now()
        report = OptimizationReport(
            profile_id=profile_id,
            timestamp=now.isoformat(),
            started_at=now.strftime("%H:%M:%S"),
        )
        start_time = time.time()

        profile = get_profile(profile_id)
        report.profile_name = profile.name
        self._progress(0.0, f"Starting {profile.name}...")

        # Step 1: Detect target
        self._progress(0.05, "Detecting target...")
        target_name, target_pid = self._detect_target()

        # Step 2: Check admin
        is_admin = False
        try:
            from app.utils.admin import is_admin as check_admin
            is_admin = check_admin()
        except Exception:
            pass

        # Step 3: Create snapshot
        self._progress(0.1, "Creating snapshot...")
        snapshot = snapshot_manager.create_snapshot(
            f"Pre-{profile.name} optimization"
        )
        report.snapshot = snapshot
        report.snapshot_id = snapshot.snapshot_id
        self._progress(0.2, f"Snapshot created ({len(snapshot.entries)} entries)")

        # Initialize session result
        session = OptimizationSessionResult(
            session_id=f"session_{uuid.uuid4().hex[:8]}",
            profile_id=profile_id,
            profile_name=profile.name,
            target_name=target_name,
            target_pid=target_pid,
            started_at=now.isoformat(),
        )

        # Step 4: Apply each optimization
        total = len(profile.optimizations)
        for i, po in enumerate(profile.optimizations):
            pct = 0.2 + (0.6 * (i / max(1, total)))
            self._progress(pct, f"Checking {po.name}...")

            opt = get_optimization_by_id(po.opt_id)
            if not opt:
                result = OptResult(
                    opt_id=po.opt_id, name=po.name,
                    status="SKIPPED", message="Not found",
                )
                report.results.append(result)
                report.skipped_count += 1
                continue

            # Check
            try:
                check_result = opt.check()
            except Exception as e:
                result = OptResult(
                    opt_id=po.opt_id, name=po.name,
                    status="FAILED", message=f"Check failed: {e}",
                )
                report.results.append(result)
                report.failed_count += 1
                session.failed.append(result)
                continue

            # Route by status
            if check_result.status == OptimizationStatus.NOT_APPLICABLE:
                result = OptResult(
                    opt_id=po.opt_id, name=po.name,
                    status="NOT_APPLICABLE", message=check_result.message,
                    current_value=check_result.current_value,
                )
                report.results.append(result)
                report.skipped_count += 1
                session.not_available.append(result)

            elif check_result.status == OptimizationStatus.ALREADY_OPTIMAL:
                result = OptResult(
                    opt_id=po.opt_id, name=po.name,
                    status="ALREADY_OPTIMAL", message="Already optimal",
                    current_value=check_result.current_value,
                    verified=True,
                )
                report.results.append(result)
                report.already_optimal_count += 1
                session.already_optimal.append(result)

            elif check_result.status == OptimizationStatus.REQUIRES_ADMIN:
                result = OptResult(
                    opt_id=po.opt_id, name=po.name,
                    status="REQUIRES_ADMIN", message="Administrator privileges required",
                    current_value=check_result.current_value,
                )
                report.results.append(result)
                report.requires_admin_count += 1
                session.requires_admin.append(result)

            elif check_result.status == OptimizationStatus.RECOMMENDATION_ONLY:
                result = OptResult(
                    opt_id=po.opt_id, name=po.name,
                    status="RECOMMENDATION_ONLY", message=check_result.message,
                    current_value=check_result.current_value,
                )
                report.results.append(result)
                report.recommendation_only_count += 1
                session.recommendation_only.append(result)

            else:
                # OPTIMIZABLE — apply it
                self._progress(pct, f"Applying {po.name}...")

                try:
                    opt.snapshot()
                except Exception as e:
                    logger.warning(f"[OPTIMIZE] {po.name} snapshot failed: {e}")

                try:
                    apply_result = opt.apply()
                    if apply_result.status == OptimizationStatus.APPLIED:
                        time.sleep(0.5)
                        verified = opt.verify()
                        status = "APPLIED" if verified else "FAILED"
                        if verified:
                            report.applied_count += 1
                            report.verified_count += 1
                            logger.info(f"[VERIFY] {po.name}: PASS")
                        else:
                            report.failed_count += 1
                            logger.warning(f"[VERIFY] {po.name}: FAIL")

                        result = OptResult(
                            opt_id=po.opt_id, name=po.name,
                            status=status, message=apply_result.message,
                            current_value=check_result.current_value,
                            verified=verified,
                            rollback_available=True,
                        )
                        report.results.append(result)
                        if verified:
                            session.applied.append(result)
                            session.rollback_available = True
                        else:
                            session.failed.append(result)
                    elif apply_result.status == OptimizationStatus.RECOMMENDATION_ONLY:
                        result = OptResult(
                            opt_id=po.opt_id, name=po.name,
                            status="RECOMMENDATION_ONLY", message=apply_result.message,
                            current_value=check_result.current_value,
                        )
                        report.results.append(result)
                        report.recommendation_only_count += 1
                        session.recommendation_only.append(result)
                    else:
                        result = OptResult(
                            opt_id=po.opt_id, name=po.name,
                            status="FAILED", message=apply_result.message,
                            current_value=check_result.current_value,
                        )
                        report.results.append(result)
                        report.failed_count += 1
                        session.failed.append(result)
                except Exception as e:
                    result = OptResult(
                        opt_id=po.opt_id, name=po.name,
                        status="FAILED", message=str(e),
                        current_value=check_result.current_value,
                    )
                    report.results.append(result)
                    report.failed_count += 1
                    session.failed.append(result)
                    logger.error(f"[OPTIMIZE] {po.name}: ERROR — {e}")

        # Finalize
        self._progress(0.9, "Finalizing...")
        report.duration_seconds = time.time() - start_time
        session.completed_at = datetime.now().isoformat()
        session.duration_seconds = report.duration_seconds
        session.success = report.failed_count == 0
        report.session = session

        self._last_report = report
        self._last_session = session

        summary = (
            f"Applied: {report.applied_count}  "
            f"Optimal: {report.already_optimal_count}  "
            f"Admin Required: {report.requires_admin_count}  "
            f"Failed: {report.failed_count}"
        )
        self._progress(1.0, summary)
        logger.info(f"[OPTIMIZE] {profile.name}: {summary}")

        return report

    def rollback_last(self) -> RollbackResult:
        """
        Rollback the last optimization session.

        Only restores settings that were actually APPLIED.
        Verifies each restoration.
        """
        if not self._acquire_lock("RESTORE"):
            return RollbackResult(
                success=False, message="Another operation is running",
            )

        try:
            return self._rollback_last_inner()
        finally:
            self._release_lock()

    def _rollback_last_inner(self) -> RollbackResult:
        if not self._last_report or not self._last_report.snapshot:
            return RollbackResult(success=False, message="No optimization to rollback")

        report = self._last_report

        # Determine which optimizations were actually applied
        applied_opt_ids = {
            r.opt_id for r in report.results
            if r.status == "APPLIED"
        }

        if not applied_opt_ids:
            logger.info("[ROLLBACK] No applied optimizations to restore")
            report.rollback_restored = 0
            report.rollback_skipped = len(report.results)
            report.rollback_failed = 0
            return RollbackResult(
                success=True,
                message="No changes were applied — nothing to restore",
            )

        # Filter snapshot entries to only applied optimizations
        category_to_opt = {
            "power": "power_plan",
            "game_mode": "game_mode",
            "emulator_priority": "emulator_priority",
        }

        from app.core.snapshot import Snapshot, SnapshotEntry
        filtered = Snapshot(
            snapshot_id=report.snapshot.snapshot_id,
            timestamp=report.snapshot.timestamp,
            description="Rollback — applied optimizations only",
        )
        skipped_entries = []
        for entry in report.snapshot.entries:
            opt_id = category_to_opt.get(entry.category)
            if opt_id and opt_id in applied_opt_ids:
                filtered.add_entry(entry)
            else:
                skipped_entries.append(entry)

        if not filtered.entries:
            logger.info("[ROLLBACK] No applied snapshot entries to restore")
            report.rollback_restored = 0
            report.rollback_skipped = len(report.results)
            report.rollback_failed = 0
            return RollbackResult(
                success=True,
                message="No changes were applied — nothing to restore",
            )

        logger.info("[ROLLBACK] Restoring previous state...")
        result = rollback_engine.rollback(filtered)

        # Verify each restoration
        verification = {}
        for entry in filtered.entries:
            opt_id = category_to_opt.get(entry.category)
            if opt_id:
                opt = get_optimization_by_id(opt_id)
                if opt:
                    try:
                        verified = opt.verify()
                        verification[opt_id] = verified
                    except Exception:
                        verification[opt_id] = False

        # Build structured rollback report
        report.rollback_restored = len(result.restored_entries)
        report.rollback_failed = len(result.failed_entries)
        report.rollback_skipped = len(skipped_entries)

        for entry_key in result.restored_entries:
            verified = verification.get(entry_key, None)
            action = "RESTORED" if verified else "RESTORED_UNVERIFIED"
            report.rollback_results.append(RollbackEntry(
                opt_id=entry_key, name=entry_key,
                action=action,
                message=f"Restored (verified: {verified})" if verified is not None else "Restored",
            ))
        for entry_key in result.failed_entries:
            report.rollback_results.append(RollbackEntry(
                opt_id=entry_key, name=entry_key,
                action="FAILED", message="Restore failed",
            ))
        for entry in skipped_entries:
            report.rollback_results.append(RollbackEntry(
                opt_id=entry.key, name=entry.description,
                action="SKIPPED", message="Not applied — no restore needed",
            ))

        if result.success:
            logger.info(
                f"[ROLLBACK] SUCCESS — {report.rollback_restored} restored, "
                f"{report.rollback_skipped} skipped"
            )
        else:
            logger.warning(f"[ROLLBACK] PARTIAL — {result.message}")

        return result

    def get_current_status(self) -> dict:
        """Get current optimization status for UI with live target detection."""
        status = {
            "optimizations": [],
            "admin": False,
            "target_name": "",
            "target_pid": 0,
            "busy": self.is_busy,
            "operation": self._operation,
        }

        try:
            from app.utils.admin import is_admin
            status["admin"] = is_admin()
        except Exception:
            pass

        # Live target detection
        target_name, target_pid = self._detect_target()
        status["target_name"] = target_name
        status["target_pid"] = target_pid

        for opt in get_all_optimizations():
            try:
                result = opt.check()
                status["optimizations"].append({
                    "id": opt.id,
                    "name": opt.name,
                    "description": opt.description,
                    "category": opt.category,
                    "risk": opt.risk_level,
                    "status": result.status.value,
                    "current_value": result.current_value,
                    "recommended_value": result.recommended_value,
                    "message": result.message,
                })
            except Exception as e:
                status["optimizations"].append({
                    "id": opt.id, "name": opt.name,
                    "status": "ERROR", "message": str(e),
                })

        return status


# Singleton
optimizer = Optimizer()
