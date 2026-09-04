"""
Tests for Phase 69.1 — Abnormal Shutdown Recovery Hardening.

Tests: recover_incomplete_sessions, idempotency, partial rollback,
       corrupted JSON, missing rollback_data, unknown states,
       recovery status persistence, _restore_change_from_data.
"""

import json
import os
import tempfile
import time
from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from app.gaming.gaming_lifecycle import (
    GamingLifecycleManager,
    LifecycleChange,
    LifecycleState,
    ChangeType,
    ChangeStatus,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_session_data(
    session_id="test_session",
    state="MONITORING",
    changes=None,
    recovery_status=None,
):
    """Create a minimal session JSON structure."""
    if changes is None:
        changes = []
    data = {
        "session_id": session_id,
        "state": state,
        "target_name": "HD-Player.exe",
        "target_pid": 1234,
        "profile_id": "gaming",
        "started_at": datetime.now().isoformat(),
        "changes": changes,
        "changes_applied": 0,
        "changes_restored": 0,
        "changes_kept": 0,
        "changes_failed": 0,
    }
    if recovery_status is not None:
        data["recovery_status"] = recovery_status
    return data


def _make_applied_change(
    change_id="chg_test",
    name="Power Plan",
    category="power",
    change_type="TEMPORARY",
    reversible=True,
    rollback_data=None,
):
    """Create a change dict as it would appear in persisted JSON."""
    if rollback_data is None:
        rollback_data = {"previous_plan": "balanced"}
    return {
        "change_id": change_id,
        "name": name,
        "category": category,
        "change_type": change_type,
        "status": "APPLIED",
        "reversible": reversible,
        "rollback_data": rollback_data,
        "previous_value": None,
        "new_value": f"Applied: {name}",
        "timestamp": time.time(),
    }


# ══════════════════════════════════════════════════════════════
#  1. EARLY STATE CLEANUP
# ══════════════════════════════════════════════════════════════


class TestEarlyStateCleanup:
    """Sessions in early states should be marked FAILED with no restoration."""

    @pytest.mark.parametrize("state", [
        "DETECTING", "BASELINE", "RECOMMENDING", "AWAITING_APPROVAL",
    ])
    def test_early_state_marked_failed(self, state):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                data = _make_session_data(state=state)
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert len(results) == 1
                assert results[0]["recovery_status"] == "NO_RESTORE_NEEDED"

                # Verify file was updated
                with open(os.path.join(tmpdir, "sess.json")) as f:
                    updated = json.load(f)
                assert updated["state"] == "FAILED"
                assert updated["recovery_status"] == "NO_RESTORE_NEEDED"

    @pytest.mark.parametrize("state", [
        "COMPLETED", "FAILED", "IDLE",
    ])
    def test_terminal_states_skipped(self, state):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                data = _make_session_data(state=state)
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert len(results) == 0

                # File should NOT be modified
                with open(os.path.join(tmpdir, "sess.json")) as f:
                    updated = json.load(f)
                assert updated["state"] == state


# ══════════════════════════════════════════════════════════════
#  2. SUCCESSFUL RECOVERY
# ══════════════════════════════════════════════════════════════


class TestSuccessfulRecovery:
    """Sessions with applied changes should be restored successfully."""

    def test_monitoring_session_power_restored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(
                    category="power",
                    rollback_data={"previous_plan": "balanced"},
                )
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                with patch.object(mgr, "_apply_power_plan", return_value=True) as mock_pp:
                    results = mgr.recover_incomplete_sessions()
                    mock_pp.assert_called_once_with("balanced")

                assert len(results) == 1
                assert results[0]["recovery_status"] == "RECOVERED"
                assert results[0]["changes_restored"] == 1
                assert results[0]["changes_failed"] == 0

                # Verify file state
                with open(os.path.join(tmpdir, "sess.json")) as f:
                    updated = json.load(f)
                assert updated["state"] == "RECOVERED"
                assert updated["recovery_status"] == "RECOVERED"
                assert updated["changes"][0]["status"] == "RESTORED"

    def test_monitoring_session_game_mode_restored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(
                    name="Game Mode",
                    category="game_mode",
                    rollback_data={"previous_enabled": False},
                )
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                with patch.object(mgr, "_apply_game_mode", return_value=True) as mock_gm:
                    results = mgr.recover_incomplete_sessions()
                    mock_gm.assert_called_with(False)

                assert results[0]["recovery_status"] == "RECOVERED"

    def test_stoppping_state_session_restored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                data = _make_session_data(
                    state="STOPPING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                with patch.object(mgr, "_apply_power_plan", return_value=True):
                    results = mgr.recover_incomplete_sessions()
                assert results[0]["recovery_status"] == "RECOVERED"


# ══════════════════════════════════════════════════════════════
#  3. PARTIAL RECOVERY
# ══════════════════════════════════════════════════════════════


class TestPartialRecovery:
    """When some changes restore and others fail, report partial recovery."""

    def test_one_succeeds_one_fails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change1 = _make_applied_change(
                    change_id="chg_ok", name="Power Plan",
                    category="power",
                    rollback_data={"previous_plan": "balanced"},
                )
                change2 = _make_applied_change(
                    change_id="chg_fail", name="Game Mode",
                    category="game_mode",
                    rollback_data={"previous_enabled": False},
                )
                data = _make_session_data(
                    state="MONITORING", changes=[change1, change2],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                # Power succeeds, game mode fails
                with patch.object(mgr, "_apply_power_plan", return_value=True), \
                     patch.object(mgr, "_apply_game_mode", return_value=False):
                    results = mgr.recover_incomplete_sessions()

                assert len(results) == 1
                r = results[0]
                assert r["recovery_status"] == "PARTIAL_RECOVERY"
                assert r["changes_restored"] == 1
                assert r["changes_failed"] == 1
                assert "chg_ok" in r["restored_ids"]
                assert len(r["failed_details"]) == 1

                # Verify file: one RESTORED, one RESTORE_FAILED
                with open(os.path.join(tmpdir, "sess.json")) as f:
                    updated = json.load(f)
                statuses = {c["change_id"]: c["status"] for c in updated["changes"]}
                assert statuses["chg_ok"] == "RESTORED"
                assert statuses["chg_fail"] == "RESTORE_FAILED"

    def test_all_fail(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                with patch.object(mgr, "_apply_power_plan", return_value=False):
                    results = mgr.recover_incomplete_sessions()

                assert results[0]["recovery_status"] == "RECOVERY_FAILED"
                assert results[0]["changes_restored"] == 0
                assert results[0]["changes_failed"] == 1


# ══════════════════════════════════════════════════════════════
#  4. IDEMPOTENT RECOVERY
# ══════════════════════════════════════════════════════════════


class TestIdempotentRecovery:
    """Recovery must be safe if executed multiple times."""

    def test_already_recovered_skipped(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                    recovery_status="RECOVERED",
                )
                data["state"] = "RECOVERED"
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                with patch.object(mgr, "_apply_power_plan") as mock_pp:
                    results = mgr.recover_incomplete_sessions()
                    mock_pp.assert_not_called()  # Must NOT restore again

                assert len(results) == 0

    def test_recovery_failed_not_retried(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                    recovery_status="RECOVERY_FAILED",
                )
                data["state"] = "FAILED"
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                with patch.object(mgr, "_apply_power_plan") as mock_pp:
                    results = mgr.recover_incomplete_sessions()
                    mock_pp.assert_not_called()

                assert len(results) == 0

    def test_no_restore_needed_not_retried(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                data = _make_session_data(
                    state="FAILED",
                    recovery_status="NO_RESTORE_NEEDED",
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert len(results) == 0


# ══════════════════════════════════════════════════════════════
#  5. CORRUPTED SESSION HANDLING
# ══════════════════════════════════════════════════════════════


class TestCorruptedSessions:
    """Corrupted files must not crash recovery."""

    def test_malformed_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                with open(os.path.join(tmpdir, "bad.json"), "w") as f:
                    f.write("not valid json {{{")

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert results == []  # No crash, no results

    def test_not_a_dict(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                with open(os.path.join(tmpdir, "list.json"), "w") as f:
                    json.dump([1, 2, 3], f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert results == []

    def test_missing_session_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                with open(os.path.join(tmpdir, "noid.json"), "w") as f:
                    json.dump({"state": "MONITORING"}, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert results == []

    def test_missing_state(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                with open(os.path.join(tmpdir, "nostate.json"), "w") as f:
                    json.dump({"session_id": "test"}, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert results == []

    def test_nonexistent_directory(self):
        mgr = GamingLifecycleManager()
        with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", "/nonexistent/path"):
            results = mgr.recover_incomplete_sessions()
            assert results == []


# ══════════════════════════════════════════════════════════════
#  6. MISSING / INVALID ROLLBACK DATA
# ══════════════════════════════════════════════════════════════


class TestMissingRollbackData:
    """Changes with missing or invalid rollback data should be handled safely."""

    def test_empty_rollback_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(
                    category="power", rollback_data={},
                )
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert results[0]["changes_failed"] == 1
                assert "missing_rollback_data" in results[0]["failed_details"][0]["reason"]

    def test_none_rollback_data(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                change["rollback_data"] = None
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert results[0]["changes_failed"] == 1

    def test_irreversible_change(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(
                    category="performance", reversible=False,
                    rollback_data={},
                )
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                # Should be marked IRREVERSIBLE, not counted as failed restore
                with open(os.path.join(tmpdir, "sess.json")) as f:
                    updated = json.load(f)
                assert updated["changes"][0]["status"] == "IRREVERSIBLE"

    def test_permanent_change_kept(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(
                    category="performance", change_type="PERMANENT",
                )
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                with open(os.path.join(tmpdir, "sess.json")) as f:
                    updated = json.load(f)
                assert updated["changes"][0]["status"] == "KEPT"


# ══════════════════════════════════════════════════════════════
#  7. RECOVERY STATUS PERSISTENCE
# ══════════════════════════════════════════════════════════════


class TestRecoveryStatusPersistence:
    """Recovery status must be persisted to prevent re-processing."""

    def test_recovery_fields_written(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                with patch.object(mgr, "_apply_power_plan", return_value=True):
                    mgr.recover_incomplete_sessions()

                with open(os.path.join(tmpdir, "sess.json")) as f:
                    updated = json.load(f)
                assert "recovery_status" in updated
                assert "recovery_timestamp" in updated
                assert "recovery_notes" in updated
                assert updated["recovery_status"] == "RECOVERED"

    def test_early_state_fields_written(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                data = _make_session_data(state="DETECTING")
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                mgr.recover_incomplete_sessions()

                with open(os.path.join(tmpdir, "sess.json")) as f:
                    updated = json.load(f)
                assert updated["recovery_status"] == "NO_RESTORE_NEEDED"
                assert "recovery_timestamp" in updated


# ══════════════════════════════════════════════════════════════
#  8. REPEATED STARTUP RECOVERY
# ══════════════════════════════════════════════════════════════


class TestRepeatedStartupRecovery:
    """Simulate multiple application restarts with the same session file."""

    def test_second_startup_does_not_restore_again(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                # First startup
                mgr1 = GamingLifecycleManager()
                with patch.object(mgr1, "_apply_power_plan", return_value=True) as mock_pp1:
                    results1 = mgr1.recover_incomplete_sessions()
                    assert mock_pp1.call_count == 1
                assert results1[0]["recovery_status"] == "RECOVERED"

                # Second startup — must not restore again
                mgr2 = GamingLifecycleManager()
                with patch.object(mgr2, "_apply_power_plan", return_value=True) as mock_pp2:
                    results2 = mgr2.recover_incomplete_sessions()
                    mock_pp2.assert_not_called()
                assert len(results2) == 0


# ══════════════════════════════════════════════════════════════
#  9. RESTORE HANDLER COVERAGE
# ══════════════════════════════════════════════════════════════


class TestRestoreHandlerCoverage:
    """Verify _restore_change_from_data handles all categories."""

    def test_power_category(self):
        mgr = GamingLifecycleManager()
        with patch.object(mgr, "_apply_power_plan", return_value=True) as mock:
            result = mgr._restore_change_from_data(
                "power", {"previous_plan": "balanced"},
            )
            mock.assert_called_once_with("balanced")
            assert result is True

    def test_game_mode_category(self):
        mgr = GamingLifecycleManager()
        with patch.object(mgr, "_apply_game_mode", return_value=True) as mock:
            result = mgr._restore_change_from_data(
                "game_mode", {"previous_enabled": False},
            )
            mock.assert_called_once_with(False)
            assert result is True

    def test_background_category(self):
        mgr = GamingLifecycleManager()
        result = mgr._restore_change_from_data(
            "background", {"previous_background_cpu": 20},
        )
        assert result is True  # Always succeeds (diagnostic only)

    def test_unknown_category(self):
        mgr = GamingLifecycleManager()
        result = mgr._restore_change_from_data("unknown_category", {})
        assert result is False


# ══════════════════════════════════════════════════════════════
#  10. NO APPLIED CHANGES
# ══════════════════════════════════════════════════════════════


class TestNoAppliedChanges:
    """Sessions with changes in non-applied states need no restoration."""

    def test_all_pending(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                change["status"] = "PENDING"  # Not applied
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert results[0]["recovery_status"] == "NO_RESTORE_NEEDED"

    def test_all_failed(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                change["status"] = "FAILED"
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert results[0]["recovery_status"] == "NO_RESTORE_NEEDED"

    def test_no_changes_at_all(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                data = _make_session_data(state="MONITORING", changes=[])
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                results = mgr.recover_incomplete_sessions()
                assert results[0]["recovery_status"] == "NO_RESTORE_NEEDED"


# ══════════════════════════════════════════════════════════════
#  11. EXCEPTION DURING RESTORE
# ══════════════════════════════════════════════════════════════


class TestRestoreException:
    """Exceptions during restore should not crash recovery."""

    def test_power_restore_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                change = _make_applied_change(category="power")
                data = _make_session_data(
                    state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "sess.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                with patch.object(
                    mgr, "_apply_power_plan",
                    side_effect=RuntimeError("WMI failed"),
                ):
                    results = mgr.recover_incomplete_sessions()

                assert results[0]["changes_failed"] == 1
                assert results[0]["recovery_status"] == "RECOVERY_FAILED"
                assert "WMI failed" in results[0]["failed_details"][0]["reason"]


# ══════════════════════════════════════════════════════════════
#  12. MULTIPLE SESSIONS
# ══════════════════════════════════════════════════════════════


class TestMultipleSessions:
    """Recovery should handle multiple interrupted sessions."""

    def test_mixed_states(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                # Session 1: early state — should be cleaned up
                d1 = _make_session_data(session_id="s1", state="DETECTING")
                with open(os.path.join(tmpdir, "s1.json"), "w") as f:
                    json.dump(d1, f)

                # Session 2: applied changes — should be restored
                change = _make_applied_change(category="power")
                d2 = _make_session_data(
                    session_id="s2", state="MONITORING", changes=[change],
                )
                with open(os.path.join(tmpdir, "s2.json"), "w") as f:
                    json.dump(d2, f)

                # Session 3: already completed — should be skipped
                d3 = _make_session_data(session_id="s3", state="COMPLETED")
                with open(os.path.join(tmpdir, "s3.json"), "w") as f:
                    json.dump(d3, f)

                mgr = GamingLifecycleManager()
                with patch.object(mgr, "_apply_power_plan", return_value=True):
                    results = mgr.recover_incomplete_sessions()

                # Should get results for s1 and s2
                assert len(results) == 2
                statuses = {r["session_id"]: r["recovery_status"] for r in results}
                assert statuses["s1"] == "NO_RESTORE_NEEDED"
                assert statuses["s2"] == "RECOVERED"
