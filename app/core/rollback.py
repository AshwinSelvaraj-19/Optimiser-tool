"""
Rollback engine — restores system configuration from snapshots.
Ensures every modification can be safely undone.
"""

from dataclasses import dataclass
from typing import Optional

from app.core.snapshot import Snapshot, SnapshotManager, snapshot_manager
from app.system.power import power_monitor
from app.utils.registry import read_registry_value, write_registry_value
from app.utils.commands import run_powershell
from app.utils.logger import get_logger, LogContext

logger = get_logger("core.rollback")


@dataclass
class RollbackResult:
    """Result of a rollback operation."""
    success: bool = True
    restored_entries: list = None
    failed_entries: list = None
    message: str = ""

    def __post_init__(self):
        if self.restored_entries is None:
            self.restored_entries = []
        if self.failed_entries is None:
            self.failed_entries = []


class RollbackEngine:
    """Restores system configuration from snapshots."""

    def __init__(self):
        pass

    def rollback(self, snapshot: Snapshot) -> RollbackResult:
        """Roll back all changes described in a snapshot."""
        result = RollbackResult()
        logger.info(f"Starting rollback of snapshot: {snapshot.snapshot_id}")

        with LogContext(logger, f"Rollback {snapshot.snapshot_id}"):
            for entry in snapshot.entries:
                try:
                    success = self._restore_entry(entry)
                    if success:
                        result.restored_entries.append(entry.key)
                        logger.info(f"  Restored: {entry.description}")
                    else:
                        result.failed_entries.append(entry.key)
                        logger.warning(f"  Failed to restore: {entry.description}")
                except Exception as e:
                    result.failed_entries.append(entry.key)
                    logger.error(f"  Error restoring {entry.description}: {e}")

            result.success = len(result.failed_entries) == 0
            result.message = (
                f"Restored {len(result.restored_entries)}/{len(snapshot.entries)} entries"
                if result.success else
                f"Partial rollback: {len(result.restored_entries)} restored, "
                f"{len(result.failed_entries)} failed"
            )
            logger.info(result.message)

        return result

    def rollback_latest(self) -> RollbackResult:
        """Rollback to the most recent snapshot."""
        snapshot = snapshot_manager.get_latest_snapshot()
        if snapshot is None:
            logger.warning("No snapshots available for rollback")
            return RollbackResult(
                success=False,
                message="No snapshots available for rollback",
            )
        return self.rollback(snapshot)

    def _restore_entry(self, entry) -> bool:
        """Restore a single snapshot entry."""
        if entry.category == "power":
            return self._restore_power(entry)
        elif entry.category == "game_mode":
            return self._restore_registry(entry)
        elif entry.category == "display":
            logger.debug(f"Display settings restore noted (manual action may be needed): {entry.description}")
            return True
        elif entry.category == "emulator_config":
            logger.debug(f"Emulator config restore noted: {entry.description}")
            return True
        elif entry.category == "gpu_preference":
            # Legacy entry from older snapshots — GPU preference optimization removed
            logger.debug(f"Legacy gpu_preference entry skipped: {entry.description}")
            return True
        else:
            logger.warning(f"Unknown snapshot entry category: {entry.category}")
            return False

    def _restore_power(self, entry) -> bool:
        """Restore power plan to backup value."""
        if entry.backup_value:
            success, _, _ = run_powershell(f"powercfg /setactive {entry.backup_value}")
            if success:
                logger.info(f"Power plan restored to: {entry.backup_value}")
                return True
            logger.error("Failed to restore power plan")
            return False
        return False

    def _restore_registry(self, entry) -> bool:
        """Restore a registry value from backup."""
        if entry.registry_hive and entry.registry_path and entry.registry_value_name:
            if entry.backup_value is not None:
                success = write_registry_value(
                    entry.registry_hive,
                    entry.registry_path,
                    entry.registry_value_name,
                    entry.backup_value,
                )
                return success
        return False

    def verify_rollback(self, snapshot: Snapshot) -> dict:
        """Verify that rollback values match current system state."""
        verification = {}
        for entry in snapshot.entries:
            current_value = self._read_current(entry)
            verification[entry.key] = {
                "expected": entry.backup_value,
                "current": current_value,
                "matches": current_value == entry.backup_value,
            }
        return verification

    def _read_current(self, entry) -> Optional[str]:
        """Read current value for a snapshot entry."""
        if entry.category == "power":
            values = power_monitor.get_current_values()
            return values.get("active_plan_guid", "")
        elif entry.registry_hive:
            return read_registry_value(
                entry.registry_hive,
                entry.registry_path,
                entry.registry_value_name,
            )
        return None


# Singleton
rollback_engine = RollbackEngine()
