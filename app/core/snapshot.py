"""
Snapshot system — creates and manages configuration backups.
Every system modification is preceded by a snapshot for safe rollback.
"""

import json
import os
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from app.system.power import power_monitor
from app.utils.commands import run_powershell
from app.utils.logger import get_logger

logger = get_logger("core.snapshot")

SNAPSHOT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "snapshots")


@dataclass
class SnapshotEntry:
    """A single backed-up configuration value."""
    category: str = ""  # power, display, game_mode, emulator, etc.
    key: str = ""
    description: str = ""
    current_value: any = None
    backup_value: any = None
    registry_hive: str = ""
    registry_path: str = ""
    registry_value_name: str = ""


@dataclass
class Snapshot:
    """Complete configuration snapshot."""
    snapshot_id: str = ""
    timestamp: str = ""
    timestamp_epoch: float = 0.0
    description: str = ""
    entries: list = field(default_factory=list)
    is_applied: bool = False

    def add_entry(self, entry: SnapshotEntry):
        self.entries.append(entry)

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "timestamp_epoch": self.timestamp_epoch,
            "description": self.description,
            "is_applied": self.is_applied,
            "entries": [
                {
                    "category": e.category,
                    "key": e.key,
                    "description": e.description,
                    "current_value": e.current_value,
                    "backup_value": e.backup_value,
                    "registry_hive": e.registry_hive,
                    "registry_path": e.registry_path,
                    "registry_value_name": e.registry_value_name,
                }
                for e in self.entries
            ],
        }


class SnapshotManager:
    """Manages configuration snapshots for safe rollback."""

    def __init__(self, snapshot_dir: str = SNAPSHOT_DIR):
        self._dir = snapshot_dir
        os.makedirs(self._dir, exist_ok=True)

    def create_snapshot(self, description: str = "Pre-optimization snapshot") -> Snapshot:
        """Create a new configuration snapshot."""
        now = datetime.now()
        snapshot = Snapshot(
            snapshot_id=f"snapshot_{now.strftime('%Y-%m-%d_%H-%M-%S')}",
            timestamp=now.isoformat(),
            timestamp_epoch=time.time(),
            description=description,
        )

        # Capture current power configuration
        self._capture_power_state(snapshot)

        # Capture display settings
        self._capture_display_settings(snapshot)

        # Capture game mode
        self._capture_game_mode(snapshot)

        # Save to disk
        self._save(snapshot)
        logger.info(f"Snapshot created: {snapshot.snapshot_id} ({len(snapshot.entries)} entries)")
        return snapshot

    def _capture_power_state(self, snapshot: Snapshot):
        """Capture current power plan configuration."""
        try:
            values = power_monitor.get_current_values()
            entry = SnapshotEntry(
                category="power",
                key="active_plan",
                description="Windows Power Plan",
                current_value=values.get("active_plan_guid", ""),
                backup_value=values.get("active_plan_guid", ""),
            )
            snapshot.add_entry(entry)
        except Exception as e:
            logger.error(f"Failed to capture power state: {e}")

    def _capture_display_settings(self, snapshot: Snapshot):
        """Capture current display settings."""
        try:
            success, stdout, _ = run_powershell(
                "Get-CimInstance Win32_VideoController | "
                "Select-Object CurrentRefreshRate, CurrentHorizontalResolution, "
                "CurrentVerticalResolution | ConvertTo-Json"
            )
            import json
            if success and stdout.strip():
                data = json.loads(stdout)
                entry = SnapshotEntry(
                    category="display",
                    key="display_settings",
                    description="Display Resolution and Refresh Rate",
                    current_value=data,
                    backup_value=data,
                )
                snapshot.add_entry(entry)
        except Exception as e:
            logger.debug(f"Display capture: {e}")

    def _capture_game_mode(self, snapshot: Snapshot):
        """Capture Windows Game Mode setting."""
        try:
            from app.utils.registry import read_registry_value
            game_mode = read_registry_value(
                "HKCU",
                r"Software\Microsoft\GameBar",
                "AutoGameModeEnabled",
            )
            entry = SnapshotEntry(
                category="game_mode",
                key="game_mode_enabled",
                description="Windows Game Mode",
                current_value=game_mode,
                backup_value=game_mode,
                registry_hive="HKCU",
                registry_path=r"Software\Microsoft\GameBar",
                registry_value_name="AutoGameModeEnabled",
            )
            snapshot.add_entry(entry)
        except Exception as e:
            logger.debug(f"Game mode capture: {e}")

    def _save(self, snapshot: Snapshot):
        """Save snapshot to disk."""
        filepath = os.path.join(self._dir, f"{snapshot.snapshot_id}.json")
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(snapshot.to_dict(), f, indent=2, default=str)
            logger.debug(f"Snapshot saved: {filepath}")
        except Exception as e:
            logger.error(f"Failed to save snapshot: {e}")

    def load_snapshot(self, snapshot_id: str) -> Optional[Snapshot]:
        """Load a snapshot from disk."""
        filepath = os.path.join(self._dir, f"{snapshot_id}.json")
        if not os.path.exists(filepath):
            # Try matching partial ID
            for fname in os.listdir(self._dir):
                if fname.startswith(snapshot_id) and fname.endswith(".json"):
                    filepath = os.path.join(self._dir, fname)
                    break
            else:
                logger.warning(f"Snapshot not found: {snapshot_id}")
                return None

        try:
            with open(filepath, "r", encoding="utf-8") as f:
                data = json.load(f)
            snapshot = Snapshot(
                snapshot_id=data["snapshot_id"],
                timestamp=data["timestamp"],
                timestamp_epoch=data.get("timestamp_epoch", 0),
                description=data.get("description", ""),
                is_applied=data.get("is_applied", False),
            )
            for entry_data in data.get("entries", []):
                entry = SnapshotEntry(**entry_data)
                snapshot.entries.append(entry)
            return snapshot
        except Exception as e:
            logger.error(f"Failed to load snapshot {snapshot_id}: {e}")
            return None

    def get_latest_snapshot(self) -> Optional[Snapshot]:
        """Get the most recent snapshot."""
        snapshots = self.list_snapshots()
        if snapshots:
            return self.load_snapshot(snapshots[0]["snapshot_id"])
        return None

    def list_snapshots(self) -> list:
        """List all available snapshots."""
        snapshots = []
        try:
            for fname in os.listdir(self._dir):
                if fname.endswith(".json"):
                    filepath = os.path.join(self._dir, fname)
                    try:
                        with open(filepath, "r") as f:
                            data = json.load(f)
                        snapshots.append({
                            "snapshot_id": data.get("snapshot_id", fname.replace(".json", "")),
                            "timestamp": data.get("timestamp", ""),
                            "description": data.get("description", ""),
                            "entry_count": len(data.get("entries", [])),
                        })
                    except Exception:
                        continue
        except Exception as e:
            logger.error(f"Error listing snapshots: {e}")

        # Sort by timestamp descending
        snapshots.sort(key=lambda s: s.get("timestamp", ""), reverse=True)
        return snapshots

    def delete_snapshot(self, snapshot_id: str) -> bool:
        """Delete a snapshot file."""
        filepath = os.path.join(self._dir, f"{snapshot_id}.json")
        if os.path.exists(filepath):
            os.remove(filepath)
            logger.info(f"Deleted snapshot: {snapshot_id}")
            return True
        return False


# Singleton
snapshot_manager = SnapshotManager()
