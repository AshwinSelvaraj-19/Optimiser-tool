"""
Phase 56 — Robust Rollback System.

Every system-changing optimization registers its rollback operation.

Components:
  StateSnapshot     — captures complete system state before changes
  ChangeRecord      — tracks a single change with undo capability
  RollbackManager   — orchestrates undo, restore, crash recovery
  RestoreSession    — tracks a full restore operation

Features:
  - Undo Last Optimization
  - Undo Session
  - Restore Profile
  - Restore All Changes
  - Crash recovery detection at startup
  - Persist rollback metadata safely
  - Never silently leave partially applied changes

Rules:
  - Every change must be reversible or explicitly marked irreversible
  - Crash recovery must detect incomplete sessions
  - Rollback metadata must survive application restarts
  - Never silently leave partially applied changes
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

from app.utils.logger import get_logger

logger = get_logger("core.rollback_manager")


# ── Enums ────────────────────────────────────────────────────────


class ChangeStatus(Enum):
    """Status of a tracked change."""
    PENDING = "PENDING"
    APPLIED = "APPLIED"
    ROLLED_BACK = "ROLLED_BACK"
    ROLLBACK_FAILED = "ROLLBACK_FAILED"
    IRREVERSIBLE = "IRREVERSIBLE"


class SessionStatus(Enum):
    """Status of an optimization session."""
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    ROLLED_BACK = "ROLLED_BACK"
    PARTIAL = "PARTIAL"
    CRASH_DETECTED = "CRASH_DETECTED"


class RestoreAction(Enum):
    """Actions available for crash recovery."""
    RESTORE = "RESTORE"
    KEEP_CHANGES = "KEEP_CHANGES"
    VIEW_DETAILS = "VIEW_DETAILS"


# ── Data Models ────────────────────────────────────────────────────


@dataclass
class ChangeRecord:
    """Tracks a single system change with undo capability."""
    change_id: str = ""
    timestamp: float = 0.0
    session_id: str = ""

    # What changed
    category: str = ""  # power, game_mode, emulator_priority, etc.
    name: str = ""
    description: str = ""
    target_process: str = ""
    target_pid: int = 0

    # Before/after values
    previous_value: any = None
    new_value: any = None

    # Rollback
    reversible: bool = True
    rollback_function: Optional[str] = None  # named function for deserialized rollback
    status: ChangeStatus = ChangeStatus.PENDING

    # Metadata
    profile_id: str = ""
    admin_required: bool = False
    risk_level: str = "LOW"

    def __post_init__(self):
        if not self.change_id:
            self.change_id = f"chg_{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "change_id": self.change_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "category": self.category,
            "name": self.name,
            "description": self.description,
            "target_process": self.target_process,
            "target_pid": self.target_pid,
            "previous_value": self.previous_value,
            "new_value": self.new_value,
            "reversible": self.reversible,
            "rollback_function": self.rollback_function,
            "status": self.status.value,
            "profile_id": self.profile_id,
            "admin_required": self.admin_required,
            "risk_level": self.risk_level,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ChangeRecord":
        status = ChangeStatus(data.get("status", "PENDING"))
        return cls(
            change_id=data.get("change_id", ""),
            timestamp=data.get("timestamp", 0.0),
            session_id=data.get("session_id", ""),
            category=data.get("category", ""),
            name=data.get("name", ""),
            description=data.get("description", ""),
            target_process=data.get("target_process", ""),
            target_pid=data.get("target_pid", 0),
            previous_value=data.get("previous_value"),
            new_value=data.get("new_value"),
            reversible=data.get("reversible", True),
            rollback_function=data.get("rollback_function"),
            status=status,
            profile_id=data.get("profile_id", ""),
            admin_required=data.get("admin_required", False),
            risk_level=data.get("risk_level", "LOW"),
        )


@dataclass
class StateSnapshot:
    """Complete system state before optimization changes."""
    snapshot_id: str = ""
    timestamp: float = 0.0
    session_id: str = ""
    profile_id: str = ""

    # System state
    power_plan: str = ""
    game_mode_enabled: Optional[bool] = None
    game_bar_enabled: Optional[bool] = None
    background_recording: Optional[bool] = None

    # Process state
    target_process: str = ""
    target_pid: int = 0
    target_priority: str = ""

    # Telemetry baseline
    cpu_percent: Optional[float] = None
    gpu_percent: Optional[float] = None
    ram_percent: Optional[float] = None
    fps: Optional[float] = None

    def __post_init__(self):
        if not self.snapshot_id:
            self.snapshot_id = f"ss_{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "snapshot_id": self.snapshot_id,
            "timestamp": self.timestamp,
            "session_id": self.session_id,
            "profile_id": self.profile_id,
            "power_plan": self.power_plan,
            "game_mode_enabled": self.game_mode_enabled,
            "game_bar_enabled": self.game_bar_enabled,
            "background_recording": self.background_recording,
            "target_process": self.target_process,
            "target_pid": self.target_pid,
            "target_priority": self.target_priority,
            "cpu_percent": self.cpu_percent,
            "gpu_percent": self.gpu_percent,
            "ram_percent": self.ram_percent,
            "fps": self.fps,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "StateSnapshot":
        return cls(**{k: v for k, v in data.items() if hasattr(cls, k)})


@dataclass
class RestoreSession:
    """Tracks a complete restore/rollback session."""
    session_id: str = ""
    timestamp: float = 0.0
    target_session_id: str = ""  # the session being rolled back
    status: SessionStatus = SessionStatus.IN_PROGRESS
    changes_attempted: int = 0
    changes_succeeded: int = 0
    changes_failed: int = 0
    errors: List[str] = field(default_factory=list)
    duration_seconds: float = 0.0

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"rs_{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "target_session_id": self.target_session_id,
            "status": self.status.value,
            "changes_attempted": self.changes_attempted,
            "changes_succeeded": self.changes_succeeded,
            "changes_failed": self.changes_failed,
            "errors": self.errors,
            "duration_seconds": self.duration_seconds,
        }


@dataclass
class OptimizationSession:
    """Tracks an optimization session with its changes."""
    session_id: str = ""
    timestamp: float = 0.0
    profile_id: str = ""
    status: SessionStatus = SessionStatus.IN_PROGRESS
    changes: List[ChangeRecord] = field(default_factory=list)
    state_snapshot: Optional[StateSnapshot] = None

    def __post_init__(self):
        if not self.session_id:
            self.session_id = f"opt_{uuid.uuid4().hex[:8]}"
        if self.timestamp == 0.0:
            self.timestamp = time.time()

    @property
    def applied_changes(self) -> List[ChangeRecord]:
        return [c for c in self.changes if c.status == ChangeStatus.APPLIED]

    @property
    def reversible_changes(self) -> List[ChangeRecord]:
        return [c for c in self.changes if c.status == ChangeStatus.APPLIED and c.reversible]

    @property
    def has_irreversible(self) -> bool:
        return any(c.status == ChangeStatus.APPLIED and not c.reversible for c in self.changes)

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "timestamp": self.timestamp,
            "profile_id": self.profile_id,
            "status": self.status.value,
            "changes": [c.to_dict() for c in self.changes],
            "state_snapshot": self.state_snapshot.to_dict() if self.state_snapshot else None,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "OptimizationSession":
        status = SessionStatus(data.get("status", "IN_PROGRESS"))
        changes = [ChangeRecord.from_dict(c) for c in data.get("changes", [])]
        ss_data = data.get("state_snapshot")
        ss = StateSnapshot.from_dict(ss_data) if ss_data else None
        return cls(
            session_id=data.get("session_id", ""),
            timestamp=data.get("timestamp", 0.0),
            profile_id=data.get("profile_id", ""),
            status=status,
            changes=changes,
            state_snapshot=ss,
        )


# ── Rollback Manager ──────────────────────────────────────────────


class RollbackManager:
    """
    Robust rollback system with crash recovery.

    Persists all session and change data to disk.
    Detects incomplete sessions at startup.
    Provides undo-last, undo-session, restore-all operations.
    """

    DATA_DIR = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__)
        ))),
        "rollback_data",
    )

    # Rollback functions registry (name -> callable)
    _rollback_functions: Dict[str, Callable] = {}

    def __init__(self, data_dir: Optional[str] = None):
        self._dir = data_dir or self.DATA_DIR
        os.makedirs(self._dir, exist_ok=True)
        self._current_session: Optional[OptimizationSession] = None
        self._sessions: Dict[str, OptimizationSession] = {}
        self._load_sessions()

    @property
    def current_session(self) -> Optional[OptimizationSession]:
        return self._current_session

    @property
    def sessions(self) -> Dict[str, OptimizationSession]:
        return self._sessions

    @classmethod
    def register_rollback(cls, name: str, func: Callable):
        """Register a rollback function by name."""
        cls._rollback_functions[name] = func

    # ── Session Lifecycle ──────────────────────────────────────

    def start_session(
        self, profile_id: str = "", description: str = ""
    ) -> OptimizationSession:
        """Start a new optimization session."""
        session = OptimizationSession(profile_id=profile_id)
        self._current_session = session
        self._sessions[session.session_id] = session
        self._save_session(session)
        self._save_manifest()
        logger.info(f"Rollback session started: {session.session_id}")
        return session

    def capture_state_snapshot(
        self, session_id: Optional[str] = None
    ) -> StateSnapshot:
        """Capture current system state before changes."""
        session = self._get_session(session_id)
        if not session:
            raise ValueError("No active session")

        snapshot = StateSnapshot(session_id=session.session_id)

        # Capture power plan
        try:
            from app.system.power import power_monitor
            values = power_monitor.get_current_values()
            snapshot.power_plan = values.get("active_plan_name", "unknown")
        except Exception:
            pass

        # Capture game mode
        try:
            from app.utils.registry import read_registry_value
            gm = read_registry_value(
                "HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled"
            )
            snapshot.game_mode_enabled = gm is not None and str(gm) == "1"
        except Exception:
            pass

        # Capture target process
        try:
            from app.core.emulator_controller import emulator_controller
            target = emulator_controller.detect_target()
            if target:
                snapshot.target_process = target.name
                snapshot.target_pid = target.pid
        except Exception:
            pass

        # Capture telemetry baseline
        try:
            from app.core.telemetry import telemetry_engine
            frame = telemetry_engine.current
            snapshot.cpu_percent = frame.cpu_utilization
            snapshot.gpu_percent = frame.gpu_utilization
            snapshot.ram_percent = frame.ram_percent
        except Exception:
            pass

        session.state_snapshot = snapshot
        self._save_session(session)
        return snapshot

    def record_change(
        self,
        name: str,
        description: str,
        category: str,
        previous_value: any = None,
        new_value: any = None,
        reversible: bool = True,
        rollback_function: Optional[str] = None,
        session_id: Optional[str] = None,
        **kwargs,
    ) -> ChangeRecord:
        """Record a system change for rollback tracking."""
        session = self._get_session(session_id)
        if not session:
            raise ValueError("No active session")

        change = ChangeRecord(
            session_id=session.session_id,
            category=category,
            name=name,
            description=description,
            previous_value=previous_value,
            new_value=new_value,
            reversible=reversible,
            rollback_function=rollback_function,
            profile_id=session.profile_id,
            **kwargs,
        )

        session.changes.append(change)
        self._save_session(session)
        return change

    def mark_applied(self, change_id: str, session_id: Optional[str] = None):
        """Mark a change as successfully applied."""
        session = self._get_session(session_id)
        if not session:
            return
        for change in session.changes:
            if change.change_id == change_id:
                change.status = ChangeStatus.APPLIED
                self._save_session(session)
                return

    def mark_irreversible(self, change_id: str, session_id: Optional[str] = None):
        """Mark a change as irreversible (cannot be undone)."""
        session = self._get_session(session_id)
        if not session:
            return
        for change in session.changes:
            if change.change_id == change_id:
                change.status = ChangeStatus.IRREVERSIBLE
                change.reversible = False
                self._save_session(session)
                return

    def complete_session(self, session_id: Optional[str] = None):
        """Mark the session as completed."""
        session = self._get_session(session_id)
        if not session:
            return
        session.status = SessionStatus.COMPLETED
        self._save_session(session)
        self._save_manifest()
        if self._current_session and self._current_session.session_id == session.session_id:
            self._current_session = None
        logger.info(f"Session completed: {session.session_id}")

    # ── Rollback Operations ────────────────────────────────────

    def undo_last_change(self) -> Tuple[bool, str]:
        """Undo the most recently applied change in the current session."""
        session = self._current_session
        if not session:
            # Find most recent session with applied changes
            for sid in reversed(list(self._sessions.keys())):
                s = self._sessions[sid]
                if s.applied_changes:
                    session = s
                    break
        if not session:
            return False, "No changes to undo"

        # Find last applied reversible change
        for change in reversed(session.changes):
            if change.status == ChangeStatus.APPLIED and change.reversible:
                success = self._rollback_change(change)
                if success:
                    change.status = ChangeStatus.ROLLED_BACK
                    self._save_session(session)
                    return True, f"Undone: {change.name}"
                else:
                    change.status = ChangeStatus.ROLLBACK_FAILED
                    self._save_session(session)
                    return False, f"Failed to undo: {change.name}"

        return False, "No reversible changes found"

    def undo_session(self, session_id: Optional[str] = None) -> RestoreSession:
        """Undo all applied changes in a session."""
        session = self._get_session(session_id)
        if not session:
            restore = RestoreSession(status=SessionStatus.COMPLETED)
            restore.errors.append("Session not found")
            return restore

        restore = RestoreSession(
            target_session_id=session.session_id,
            status=SessionStatus.IN_PROGRESS,
        )

        for change in reversed(session.changes):
            if change.status == ChangeStatus.APPLIED and change.reversible:
                restore.changes_attempted += 1
                success = self._rollback_change(change)
                if success:
                    change.status = ChangeStatus.ROLLED_BACK
                    restore.changes_succeeded += 1
                else:
                    change.status = ChangeStatus.ROLLBACK_FAILED
                    restore.changes_failed += 1
                    restore.errors.append(f"Failed: {change.name}")

        restore.status = (
            SessionStatus.ROLLED_BACK if restore.changes_failed == 0
            else SessionStatus.PARTIAL
        )
        restore.duration_seconds = time.time() - restore.timestamp
        session.status = restore.status

        self._save_session(session)
        self._save_restore(restore)
        self._save_manifest()

        return restore

    def restore_all(self) -> RestoreSession:
        """Restore all changes across all sessions."""
        restore = RestoreSession(status=SessionStatus.IN_PROGRESS)

        for session in reversed(list(self._sessions.values())):
            for change in reversed(session.changes):
                if change.status == ChangeStatus.APPLIED and change.reversible:
                    restore.changes_attempted += 1
                    success = self._rollback_change(change)
                    if success:
                        change.status = ChangeStatus.ROLLED_BACK
                        restore.changes_succeeded += 1
                    else:
                        change.status = ChangeStatus.ROLLBACK_FAILED
                        restore.changes_failed += 1
                        restore.errors.append(f"Failed: {change.name} ({session.session_id})")
            self._save_session(session)

        restore.status = (
            SessionStatus.ROLLED_BACK if restore.changes_failed == 0
            else SessionStatus.PARTIAL
        )
        restore.duration_seconds = time.time() - restore.timestamp

        self._save_restore(restore)
        self._save_manifest()
        return restore

    # ── Crash Recovery ─────────────────────────────────────────

    def detect_incomplete_sessions(self) -> List[OptimizationSession]:
        """
        Detect optimization sessions that did not complete.
        Called at application startup.
        """
        incomplete = []
        for session in self._sessions.values():
            if session.status == SessionStatus.IN_PROGRESS:
                session.status = SessionStatus.CRASH_DETECTED
                self._save_session(session)
                incomplete.append(session)
        if incomplete:
            self._save_manifest()
            logger.warning(f"Detected {len(incomplete)} incomplete optimization session(s)")
        return incomplete

    def format_crash_recovery(self, sessions: List[OptimizationSession]) -> str:
        """Format crash recovery prompt for CLI/GUI."""
        if not sessions:
            return ""

        lines = []
        lines.append("=" * 55)
        lines.append("  WARNING: INCOMPLETE OPTIMIZATION SESSION(S) DETECTED")
        lines.append("=" * 55)

        for session in sessions:
            applied = len(session.applied_changes)
            total = len(session.changes)
            lines.append(f"\n  Session: {session.session_id}")
            lines.append(f"  Profile: {session.profile_id or 'unknown'}")
            lines.append(f"  Changes: {applied} applied / {total} total")
            lines.append(f"  Time: {datetime.fromtimestamp(session.timestamp).strftime('%Y-%m-%d %H:%M:%S')}")

            if session.applied_changes:
                lines.append(f"\n  Applied changes:")
                for change in session.applied_changes:
                    rev = "reversible" if change.reversible else "IRREVERSIBLE"
                    lines.append(f"    - {change.name} [{rev}]")

        lines.append(f"\n  OPTIONS:")
        lines.append(f"    RESTORE    — Roll back all applied changes")
        lines.append(f"    KEEP       — Keep current changes, mark session complete")
        lines.append(f"    DETAILS    — View full session details")
        lines.append("=" * 55)

        return "\n".join(lines)

    def resolve_incomplete_session(
        self, session_id: str, action: RestoreAction
    ) -> str:
        """Resolve an incomplete session after crash detection."""
        session = self._sessions.get(session_id)
        if not session:
            return "Session not found"

        if action == RestoreAction.RESTORE:
            restore = self.undo_session(session_id)
            return f"Restored {restore.changes_succeeded}/{restore.changes_attempted} changes"
        elif action == RestoreAction.KEEP_CHANGES:
            session.status = SessionStatus.COMPLETED
            self._save_session(session)
            self._save_manifest()
            return "Changes kept, session marked complete"
        elif action == RestoreAction.VIEW_DETAILS:
            return self.format_crash_recovery([session])
        return "Unknown action"

    # ── Status ─────────────────────────────────────────────────

    def get_status(self) -> Dict:
        """Get current rollback system status."""
        total_sessions = len(self._sessions)
        active = sum(
            1 for s in self._sessions.values()
            if s.status == SessionStatus.IN_PROGRESS
        )
        completed = sum(
            1 for s in self._sessions.values()
            if s.status == SessionStatus.COMPLETED
        )
        rolled_back = sum(
            1 for s in self._sessions.values()
            if s.status in (SessionStatus.ROLLED_BACK, SessionStatus.PARTIAL)
        )
        crash_detected = sum(
            1 for s in self._sessions.values()
            if s.status == SessionStatus.CRASH_DETECTED
        )

        total_changes = sum(len(s.changes) for s in self._sessions.values())
        applied = sum(len(s.applied_changes) for s in self._sessions.values())
        reversible = sum(len(s.reversible_changes) for s in self._sessions.values())

        return {
            "total_sessions": total_sessions,
            "active_sessions": active,
            "completed_sessions": completed,
            "rolled_back_sessions": rolled_back,
            "crash_detected_sessions": crash_detected,
            "total_changes": total_changes,
            "applied_changes": applied,
            "reversible_changes": reversible,
            "current_session": self._current_session.session_id if self._current_session else None,
        }

    def format_status(self) -> str:
        """Format status for CLI display."""
        status = self.get_status()
        lines = []
        lines.append("=" * 55)
        lines.append("  HEAVEN SOCIETY — ROLLBACK SYSTEM STATUS")
        lines.append("=" * 55)
        lines.append(f"\n  Sessions:     {status['total_sessions']}")
        lines.append(f"  Active:       {status['active_sessions']}")
        lines.append(f"  Completed:    {status['completed_sessions']}")
        lines.append(f"  Rolled Back:  {status['rolled_back_sessions']}")
        lines.append(f"  Crash Detected: {status['crash_detected_sessions']}")
        lines.append(f"\n  Total Changes:    {status['total_changes']}")
        lines.append(f"  Applied:          {status['applied_changes']}")
        lines.append(f"  Reversible:       {status['reversible_changes']}")
        if status["current_session"]:
            lines.append(f"\n  Current Session:  {status['current_session']}")
        lines.append("\n" + "=" * 55)
        return "\n".join(lines)

    # ── Internal ───────────────────────────────────────────────

    def _get_session(self, session_id: Optional[str] = None) -> Optional[OptimizationSession]:
        """Get a session by ID or the current session."""
        if session_id:
            return self._sessions.get(session_id)
        return self._current_session

    def _rollback_change(self, change: ChangeRecord) -> bool:
        """Execute rollback for a single change."""
        try:
            # Try registered rollback function
            if change.rollback_function and change.rollback_function in self._rollback_functions:
                func = self._rollback_functions[change.rollback_function]
                func(change)
                return True

            # Category-based rollback
            if change.category == "power":
                return self._rollback_power(change)
            elif change.category == "game_mode":
                return self._rollback_registry(change)
            elif change.category == "game_bar":
                return self._rollback_registry(change)
            elif change.category == "emulator_priority":
                return self._rollback_process_priority(change)
            elif change.category == "background_recording":
                return self._rollback_registry(change)
            else:
                logger.warning(f"No rollback handler for category: {change.category}")
                return False
        except Exception as e:
            logger.error(f"Rollback error for {change.name}: {e}")
            return False

    def _rollback_power(self, change: ChangeRecord) -> bool:
        """Rollback power plan change."""
        try:
            from app.system.power import power_monitor
            if change.previous_value:
                power_monitor.set_power_plan(change.previous_value)
                return True
            return False
        except Exception as e:
            logger.error(f"Power rollback failed: {e}")
            return False

    def _rollback_registry(self, change: ChangeRecord) -> bool:
        """Rollback a registry change."""
        try:
            from app.utils.registry import write_registry_value
            if change.previous_value is not None:
                # Determine registry path from category
                reg_map = {
                    "game_mode": ("HKCU", r"Software\Microsoft\GameBar", "AutoGameModeEnabled"),
                    "game_bar": ("HKCU", r"Software\Microsoft\GameBar", "AppCapturingEnabled"),
                    "background_recording": ("HKCU", r"Software\Microsoft\GameBar", "AllowBackgroundCapture"),
                }
                if change.category in reg_map:
                    hive, path, name = reg_map[change.category]
                    write_registry_value(hive, path, name, change.previous_value)
                    return True
            return False
        except Exception as e:
            logger.error(f"Registry rollback failed: {e}")
            return False

    def _rollback_process_priority(self, change: ChangeRecord) -> bool:
        """Rollback process priority change."""
        try:
            if change.target_pid and change.previous_value:
                import psutil
                proc = psutil.Process(change.target_pid)
                proc.nice(change.previous_value)
                return True
            return False
        except Exception as e:
            logger.error(f"Process priority rollback failed: {e}")
            return False

    def _load_sessions(self):
        """Load all sessions from disk."""
        sessions_dir = os.path.join(self._dir, "sessions")
        if not os.path.exists(sessions_dir):
            return
        try:
            for fname in os.listdir(sessions_dir):
                if fname.endswith(".json"):
                    filepath = os.path.join(sessions_dir, fname)
                    try:
                        with open(filepath) as f:
                            data = json.load(f)
                        session = OptimizationSession.from_dict(data)
                        self._sessions[session.session_id] = session
                    except Exception as e:
                        logger.debug(f"Failed to load session {fname}: {e}")
        except Exception:
            pass

    def _save_session(self, session: OptimizationSession):
        """Save a session to disk."""
        sessions_dir = os.path.join(self._dir, "sessions")
        os.makedirs(sessions_dir, exist_ok=True)
        filepath = os.path.join(sessions_dir, f"{session.session_id}.json")
        try:
            with open(filepath, "w") as f:
                json.dump(session.to_dict(), f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save session: {e}")

    def _save_restore(self, restore: RestoreSession):
        """Save a restore session to disk."""
        restores_dir = os.path.join(self._dir, "restores")
        os.makedirs(restores_dir, exist_ok=True)
        filepath = os.path.join(restores_dir, f"{restore.session_id}.json")
        try:
            with open(filepath, "w") as f:
                json.dump(restore.to_dict(), f, indent=2, default=str)
        except Exception as e:
            logger.error(f"Failed to save restore: {e}")

    def _save_manifest(self):
        """Save a manifest of all sessions for quick startup check."""
        manifest = {
            "timestamp": time.time(),
            "sessions": {},
        }
        for sid, session in self._sessions.items():
            manifest["sessions"][sid] = {
                "status": session.status.value,
                "profile_id": session.profile_id,
                "change_count": len(session.changes),
                "applied_count": len(session.applied_changes),
            }
        filepath = os.path.join(self._dir, "manifest.json")
        try:
            with open(filepath, "w") as f:
                json.dump(manifest, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save manifest: {e}")


# ── Singleton ────────────────────────────────────────────────────

rollback_manager = RollbackManager()
