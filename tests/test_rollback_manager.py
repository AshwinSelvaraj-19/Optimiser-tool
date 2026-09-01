"""
Phase 56 — Comprehensive tests for Robust Rollback System.

Tests:
- ChangeRecord (create, serialization, status transitions)
- StateSnapshot (create, serialization)
- RestoreSession (create, serialization)
- OptimizationSession (lifecycle, applied/reversible changes)
- RollbackManager (session lifecycle, record change, mark applied, undo, restore)
- Crash recovery detection
- CLI commands
- Edge cases
"""
import os
import sys
import time
import json

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch
from app.core.rollback_manager import (
    ChangeStatus,
    SessionStatus,
    RestoreAction,
    ChangeRecord,
    StateSnapshot,
    RestoreSession,
    OptimizationSession,
    RollbackManager,
    rollback_manager,
)


# ══════════════════════════════════════════════════════════════════
# 1. Enums
# ══════════════════════════════════════════════════════════════════

class TestEnums:
    def test_change_status(self):
        assert ChangeStatus.PENDING.value == "PENDING"
        assert ChangeStatus.APPLIED.value == "APPLIED"
        assert ChangeStatus.ROLLED_BACK.value == "ROLLED_BACK"
        assert ChangeStatus.ROLLBACK_FAILED.value == "ROLLBACK_FAILED"
        assert ChangeStatus.IRREVERSIBLE.value == "IRREVERSIBLE"

    def test_session_status(self):
        assert SessionStatus.IN_PROGRESS.value == "IN_PROGRESS"
        assert SessionStatus.COMPLETED.value == "COMPLETED"
        assert SessionStatus.CRASH_DETECTED.value == "CRASH_DETECTED"

    def test_restore_action(self):
        assert RestoreAction.RESTORE.value == "RESTORE"
        assert RestoreAction.KEEP_CHANGES.value == "KEEP_CHANGES"
        assert RestoreAction.VIEW_DETAILS.value == "VIEW_DETAILS"


# ══════════════════════════════════════════════════════════════════
# 2. ChangeRecord
# ══════════════════════════════════════════════════════════════════

class TestChangeRecord:
    def test_create(self):
        c = ChangeRecord(name="Power Plan", category="power")
        assert c.change_id.startswith("chg_")
        assert c.status == ChangeStatus.PENDING
        assert c.reversible is True

    def test_with_values(self):
        c = ChangeRecord(
            name="Game Mode", category="game_mode",
            previous_value="0", new_value="1",
            reversible=True, risk_level="LOW",
        )
        assert c.previous_value == "0"
        assert c.new_value == "1"

    def test_to_dict(self):
        c = ChangeRecord(name="Test", category="power")
        d = c.to_dict()
        assert d["name"] == "Test"
        assert d["status"] == "PENDING"
        assert d["reversible"] is True

    def test_from_dict(self):
        d = {
            "change_id": "chg_test",
            "name": "Power Plan",
            "category": "power",
            "status": "APPLIED",
            "previous_value": "balanced",
            "new_value": "high_performance",
        }
        c = ChangeRecord.from_dict(d)
        assert c.change_id == "chg_test"
        assert c.status == ChangeStatus.APPLIED

    def test_from_dict_default_status(self):
        c = ChangeRecord.from_dict({"name": "test"})
        assert c.status == ChangeStatus.PENDING


# ══════════════════════════════════════════════════════════════════
# 3. StateSnapshot
# ══════════════════════════════════════════════════════════════════

class TestStateSnapshot:
    def test_create(self):
        ss = StateSnapshot()
        assert ss.snapshot_id.startswith("ss_")
        assert ss.timestamp > 0

    def test_with_values(self):
        ss = StateSnapshot(
            power_plan="high_performance",
            game_mode_enabled=True,
            target_process="HD-Player.exe",
            cpu_percent=50.0, gpu_percent=70.0, ram_percent=60.0,
        )
        assert ss.power_plan == "high_performance"
        assert ss.target_process == "HD-Player.exe"

    def test_to_dict(self):
        ss = StateSnapshot(power_plan="balanced")
        d = ss.to_dict()
        assert d["power_plan"] == "balanced"

    def test_from_dict(self):
        d = {"power_plan": "high_performance", "game_mode_enabled": True}
        ss = StateSnapshot.from_dict(d)
        assert ss.power_plan == "high_performance"
        assert ss.game_mode_enabled is True

    def test_roundtrip(self):
        original = StateSnapshot(
            power_plan="balanced", game_mode_enabled=True,
            target_process="test.exe", cpu_percent=45.0,
        )
        d = original.to_dict()
        restored = StateSnapshot.from_dict(d)
        assert restored.power_plan == original.power_plan
        assert restored.game_mode_enabled == original.game_mode_enabled
        assert restored.cpu_percent == original.cpu_percent


# ══════════════════════════════════════════════════════════════════
# 4. RestoreSession
# ══════════════════════════════════════════════════════════════════

class TestRestoreSession:
    def test_create(self):
        rs = RestoreSession()
        assert rs.session_id.startswith("rs_")
        assert rs.status == SessionStatus.IN_PROGRESS

    def test_to_dict(self):
        rs = RestoreSession(
            changes_attempted=3, changes_succeeded=2, changes_failed=1,
        )
        d = rs.to_dict()
        assert d["changes_attempted"] == 3
        assert d["changes_succeeded"] == 2


# ══════════════════════════════════════════════════════════════════
# 5. OptimizationSession
# ══════════════════════════════════════════════════════════════════

class TestOptimizationSession:
    def test_create(self):
        s = OptimizationSession()
        assert s.session_id.startswith("opt_")
        assert s.status == SessionStatus.IN_PROGRESS

    def test_applied_changes(self):
        s = OptimizationSession()
        s.changes = [
            ChangeRecord(name="A", status=ChangeStatus.APPLIED),
            ChangeRecord(name="B", status=ChangeStatus.PENDING),
            ChangeRecord(name="C", status=ChangeStatus.APPLIED),
        ]
        assert len(s.applied_changes) == 2

    def test_reversible_changes(self):
        s = OptimizationSession()
        s.changes = [
            ChangeRecord(name="A", status=ChangeStatus.APPLIED, reversible=True),
            ChangeRecord(name="B", status=ChangeStatus.APPLIED, reversible=False),
        ]
        assert len(s.reversible_changes) == 1
        assert s.reversible_changes[0].name == "A"

    def test_has_irreversible(self):
        s = OptimizationSession()
        s.changes = [
            ChangeRecord(name="A", status=ChangeStatus.APPLIED, reversible=False),
        ]
        assert s.has_irreversible is True

    def test_no_irreversible(self):
        s = OptimizationSession()
        s.changes = [
            ChangeRecord(name="A", status=ChangeStatus.APPLIED, reversible=True),
        ]
        assert s.has_irreversible is False

    def test_to_dict(self):
        s = OptimizationSession(profile_id="gaming")
        d = s.to_dict()
        assert d["profile_id"] == "gaming"
        assert "changes" in d

    def test_from_dict(self):
        d = {
            "session_id": "opt_test",
            "profile_id": "gaming",
            "status": "COMPLETED",
            "changes": [
                {"name": "Power Plan", "category": "power", "status": "APPLIED"},
            ],
        }
        s = OptimizationSession.from_dict(d)
        assert s.session_id == "opt_test"
        assert len(s.changes) == 1
        assert s.changes[0].status == ChangeStatus.APPLIED


# ══════════════════════════════════════════════════════════════════
# 6. RollbackManager
# ══════════════════════════════════════════════════════════════════

class TestRollbackManager:
    @pytest.fixture
    def tmp_manager(self, tmp_path):
        return RollbackManager(data_dir=str(tmp_path))

    def test_singleton_exists(self):
        assert isinstance(rollback_manager, RollbackManager)

    def test_start_session(self, tmp_manager):
        session = tmp_manager.start_session(profile_id="gaming")
        assert session.session_id.startswith("opt_")
        assert session.profile_id == "gaming"
        assert tmp_manager.current_session is not None

    def test_record_change(self, tmp_manager):
        tmp_manager.start_session(profile_id="gaming")
        change = tmp_manager.record_change(
            name="Power Plan",
            description="Switch to High Performance",
            category="power",
            previous_value="balanced",
            new_value="high_performance",
        )
        assert change.change_id.startswith("chg_")
        assert len(tmp_manager.current_session.changes) == 1

    def test_mark_applied(self, tmp_manager):
        tmp_manager.start_session()
        change = tmp_manager.record_change(
            name="Test", description="Test", category="power",
        )
        tmp_manager.mark_applied(change.change_id)
        assert tmp_manager.current_session.changes[0].status == ChangeStatus.APPLIED

    def test_mark_irreversible(self, tmp_manager):
        tmp_manager.start_session()
        change = tmp_manager.record_change(
            name="Test", description="Test", category="power",
        )
        tmp_manager.mark_applied(change.change_id)
        tmp_manager.mark_irreversible(change.change_id)
        c = tmp_manager.current_session.changes[0]
        assert c.status == ChangeStatus.IRREVERSIBLE
        assert c.reversible is False

    def test_complete_session(self, tmp_manager):
        tmp_manager.start_session()
        tmp_manager.record_change(
            name="Test", description="Test", category="power",
        )
        tmp_manager.complete_session()
        assert tmp_manager.current_session is None

    def test_undo_last_change(self, tmp_manager):
        tmp_manager.start_session()
        change = tmp_manager.record_change(
            name="Power Plan", description="Test", category="power",
            previous_value="balanced",
        )
        tmp_manager.mark_applied(change.change_id)

        # Mock the rollback
        with patch.object(tmp_manager, "_rollback_change", return_value=True):
            success, msg = tmp_manager.undo_last_change()
        assert success is True
        assert "Undone" in msg

    def test_undo_last_nothing(self, tmp_manager):
        success, msg = tmp_manager.undo_last_change()
        assert success is False
        assert "No changes" in msg

    def test_undo_session(self, tmp_manager):
        tmp_manager.start_session()
        c1 = tmp_manager.record_change(
            name="Power Plan", description="Test", category="power",
            previous_value="balanced",
        )
        c2 = tmp_manager.record_change(
            name="Game Mode", description="Test", category="game_mode",
            previous_value="0",
        )
        tmp_manager.mark_applied(c1.change_id)
        tmp_manager.mark_applied(c2.change_id)

        with patch.object(tmp_manager, "_rollback_change", return_value=True):
            restore = tmp_manager.undo_session()
        assert restore.changes_succeeded == 2
        assert restore.status == SessionStatus.ROLLED_BACK

    def test_undo_session_partial_failure(self, tmp_manager):
        tmp_manager.start_session()
        c1 = tmp_manager.record_change(
            name="A", description="Test", category="power",
            previous_value="balanced",
        )
        c2 = tmp_manager.record_change(
            name="B", description="Test", category="game_mode",
            previous_value="0",
        )
        tmp_manager.mark_applied(c1.change_id)
        tmp_manager.mark_applied(c2.change_id)

        call_count = [0]
        def mock_rollback(change):
            call_count[0] += 1
            return call_count[0] != 1  # First succeeds, second fails

        with patch.object(tmp_manager, "_rollback_change", side_effect=mock_rollback):
            restore = tmp_manager.undo_session()
        assert restore.changes_succeeded == 1
        assert restore.changes_failed == 1
        assert restore.status == SessionStatus.PARTIAL

    def test_restore_all(self, tmp_manager):
        # Create two sessions with applied changes
        tmp_manager.start_session()
        c1 = tmp_manager.record_change(
            name="A", description="Test", category="power",
            previous_value="balanced",
        )
        tmp_manager.mark_applied(c1.change_id)
        tmp_manager.complete_session()

        tmp_manager.start_session()
        c2 = tmp_manager.record_change(
            name="B", description="Test", category="game_mode",
            previous_value="0",
        )
        tmp_manager.mark_applied(c2.change_id)
        tmp_manager.complete_session()

        with patch.object(tmp_manager, "_rollback_change", return_value=True):
            restore = tmp_manager.restore_all()
        assert restore.changes_succeeded == 2

    def test_crash_recovery(self, tmp_manager):
        # Create a session but don't complete it
        tmp_manager.start_session()
        tmp_manager.record_change(
            name="Test", description="Test", category="power",
        )
        # Save without completing
        tmp_manager._save_session(tmp_manager.current_session)

        # Create a new manager to simulate restart
        manager2 = RollbackManager(data_dir=str(tmp_manager._dir))
        incomplete = manager2.detect_incomplete_sessions()
        assert len(incomplete) == 1
        assert incomplete[0].status == SessionStatus.CRASH_DETECTED

    def test_resolve_incomplete_restore(self, tmp_manager):
        tmp_manager.start_session()
        c = tmp_manager.record_change(
            name="Test", description="Test", category="power",
            previous_value="balanced",
        )
        tmp_manager.mark_applied(c.change_id)
        tmp_manager._save_session(tmp_manager.current_session)
        sid = tmp_manager.current_session.session_id

        manager2 = RollbackManager(data_dir=str(tmp_manager._dir))
        incomplete = manager2.detect_incomplete_sessions()
        assert len(incomplete) == 1

        with patch.object(manager2, "_rollback_change", return_value=True):
            result = manager2.resolve_incomplete_session(sid, RestoreAction.RESTORE)
        assert "Restored" in result

    def test_resolve_incomplete_keep(self, tmp_manager):
        tmp_manager.start_session()
        tmp_manager.record_change(
            name="Test", description="Test", category="power",
        )
        tmp_manager._save_session(tmp_manager.current_session)
        sid = tmp_manager.current_session.session_id

        manager2 = RollbackManager(data_dir=str(tmp_manager._dir))
        manager2.detect_incomplete_sessions()
        result = manager2.resolve_incomplete_session(sid, RestoreAction.KEEP_CHANGES)
        assert "kept" in result.lower()

    def test_format_status(self, tmp_manager):
        status = tmp_manager.format_status()
        assert "ROLLBACK SYSTEM STATUS" in status

    def test_format_crash_recovery_empty(self, tmp_manager):
        result = tmp_manager.format_crash_recovery([])
        assert result == ""

    def test_format_crash_recovery(self, tmp_manager):
        session = OptimizationSession(
            status=SessionStatus.CRASH_DETECTED,
            profile_id="gaming",
        )
        session.changes = [
            ChangeRecord(name="Power Plan", status=ChangeStatus.APPLIED),
        ]
        result = tmp_manager.format_crash_recovery([session])
        assert "INCOMPLETE" in result
        assert "Power Plan" in result

    def test_persistence(self, tmp_path):
        m1 = RollbackManager(data_dir=str(tmp_path))
        m1.start_session(profile_id="test")
        c = m1.record_change(name="Test", description="Test", category="power")
        m1.mark_applied(c.change_id)
        m1._save_session(m1.current_session)

        m2 = RollbackManager(data_dir=str(tmp_path))
        assert len(m2.sessions) == 1
        session = list(m2.sessions.values())[0]
        assert len(session.changes) == 1
        assert session.changes[0].status == ChangeStatus.APPLIED

    def test_get_status(self, tmp_manager):
        tmp_manager.start_session()
        tmp_manager.record_change(name="A", description="Test", category="power")
        status = tmp_manager.get_status()
        assert status["total_sessions"] == 1
        assert status["active_sessions"] == 1
        assert status["total_changes"] == 1

    def test_record_change_no_session(self, tmp_manager):
        with pytest.raises(ValueError, match="No active session"):
            tmp_manager.record_change(name="Test", description="Test", category="power")

    def test_register_rollback_function(self, tmp_manager):
        called = [False]
        def my_rollback(change):
            called[0] = True

        RollbackManager.register_rollback("my_rollback", my_rollback)
        tmp_manager.start_session()
        c = tmp_manager.record_change(
            name="Test", description="Test", category="custom",
            rollback_function="my_rollback",
        )
        tmp_manager.mark_applied(c.change_id)
        tmp_manager._rollback_change(c)
        assert called[0] is True


# ══════════════════════════════════════════════════════════════════
# 7. CLI Integration
# ══════════════════════════════════════════════════════════════════

class TestCLIIntegration:
    def test_rollback_status(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--rollback-status"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "ROLLBACK SYSTEM STATUS" in result.stdout

    def test_rollback_check(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--rollback-check"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "incomplete" in result.stdout.lower() or "No incomplete" in result.stdout

    def test_rollback_undo(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--rollback-undo"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "No changes" in result.stdout or "Undone" in result.stdout


# ══════════════════════════════════════════════════════════════════
# 8. Edge Cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_session_undo(self, tmp_path):
        m = RollbackManager(data_dir=str(tmp_path))
        success, msg = m.undo_last_change()
        assert success is False

    def test_undo_irreversible_skipped(self, tmp_path):
        m = RollbackManager(data_dir=str(tmp_path))
        m.start_session()
        c = m.record_change(
            name="Test", description="Test", category="power",
            reversible=False,
        )
        m.mark_applied(c.change_id)
        m.mark_irreversible(c.change_id)
        success, msg = m.undo_last_change()
        assert success is False
        assert "No reversible" in msg

    def test_multiple_sessions_independence(self, tmp_path):
        m = RollbackManager(data_dir=str(tmp_path))
        m.start_session(profile_id="s1")
        c1 = m.record_change(name="A", description="Test", category="power")
        m.mark_applied(c1.change_id)
        m.complete_session()

        m.start_session(profile_id="s2")
        c2 = m.record_change(name="B", description="Test", category="game_mode")
        m.mark_applied(c2.change_id)

        # Undo only affects current session
        with patch.object(m, "_rollback_change", return_value=True):
            success, msg = m.undo_last_change()
        assert "B" in msg

    def test_restore_all_empty(self, tmp_path):
        m = RollbackManager(data_dir=str(tmp_path))
        restore = m.restore_all()
        assert restore.changes_attempted == 0

    def test_change_record_auto_id(self):
        c1 = ChangeRecord()
        c2 = ChangeRecord()
        assert c1.change_id != c2.change_id

    def test_snapshot_auto_id(self):
        s1 = StateSnapshot()
        s2 = StateSnapshot()
        assert s1.snapshot_id != s2.snapshot_id
