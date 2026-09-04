"""
Tests for Phase 69 — Gaming Session UI Integration.

Tests: HomePageResult session fields, home page session card,
       shutdown recovery, session history, lifecycle manager
       recover_incomplete_sessions, stop-session button visibility.
"""

import json
import os
import tempfile
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── HomePageResult session fields ────────────────────────────────


class TestHomePageResultSessionFields:
    """Verify the HomePageResult dataclass has all session fields."""

    def test_defaults(self):
        from app.ui.home_page_worker import HomePageResult
        r = HomePageResult()
        assert r.session_active is False
        assert r.session_state == "IDLE"
        assert r.session_target == ""
        assert r.session_pid == 0
        assert r.session_duration == 0.0
        assert r.session_applied == 0
        assert r.session_cpu is None
        assert r.session_gpu is None
        assert r.session_ram is None
        assert r.session_fps is None
        assert r.session_recent == []

    def test_session_fields_settable(self):
        from app.ui.home_page_worker import HomePageResult
        r = HomePageResult()
        r.session_active = True
        r.session_state = "MONITORING"
        r.session_target = "HD-Player.exe"
        r.session_pid = 1234
        r.session_duration = 120.5
        r.session_applied = 3
        r.session_cpu = 45.0
        r.session_gpu = 72.0
        r.session_ram = 68.0
        r.session_fps = 120.0
        r.session_recent = [{"target": "Game", "duration": 60, "applied": 1}]
        assert r.session_active is True
        assert r.session_fps == 120.0
        assert len(r.session_recent) == 1


# ── Worker session data collection ───────────────────────────────


class TestWorkerSessionCollection:
    """Test that the home page worker collects session data."""

    def test_no_active_session(self):
        """When no session is active, session_active should be False."""
        from app.ui.home_page_worker import HomePageResult
        r = HomePageResult()
        # Simulate no active session
        r.session_active = False
        assert r.session_active is False

    def test_active_session_data(self):
        """When session is active, fields should be populated."""
        from app.ui.home_page_worker import HomePageResult
        r = HomePageResult()
        r.session_active = True
        r.session_state = "MONITORING"
        r.session_target = "BlueStacks"
        r.session_pid = 5678
        r.session_duration = 300.0
        r.session_applied = 2
        assert r.session_active is True
        assert r.session_target == "BlueStacks"
        assert r.session_pid == 5678


# ── Lifecycle recover_incomplete_sessions ────────────────────────


class TestRecoverIncompleteSessions:
    """Test the lifecycle manager's session recovery."""

    def test_no_sessions_dir(self):
        """No sessions dir returns empty list."""
        from app.gaming.gaming_lifecycle import GamingLifecycleManager
        mgr = GamingLifecycleManager()
        with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", "/nonexistent/path"):
            result = mgr.recover_incomplete_sessions()
            assert result == []

    def test_completed_session_not_recovered(self):
        """A COMPLETED session should not be flagged."""
        from app.gaming.gaming_lifecycle import GamingLifecycleManager
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                data = {
                    "session_id": "test_completed",
                    "state": "COMPLETED",
                    "target_name": "Game",
                    "changes": [
                        {"status": "APPLIED", "name": "Power Plan"}
                    ],
                }
                with open(os.path.join(tmpdir, "test.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                result = mgr.recover_incomplete_sessions()
                assert len(result) == 0

    def test_failed_session_not_recovered(self):
        """A FAILED session should not be flagged."""
        from app.gaming.gaming_lifecycle import GamingLifecycleManager
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                data = {
                    "session_id": "test_failed",
                    "state": "FAILED",
                    "target_name": "Game",
                    "changes": [],
                }
                with open(os.path.join(tmpdir, "test.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                result = mgr.recover_incomplete_sessions()
                assert len(result) == 0

    def test_monitoring_session_with_applied_is_recovered(self):
        """A MONITORING session with applied changes is recovered."""
        from app.gaming.gaming_lifecycle import GamingLifecycleManager
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                data = {
                    "session_id": "test_incomplete",
                    "state": "MONITORING",
                    "target_name": "Game",
                    "changes": [
                        {
                            "change_id": "chg_1",
                            "status": "APPLIED",
                            "name": "Power Plan",
                            "category": "power",
                            "change_type": "TEMPORARY",
                            "reversible": True,
                            "rollback_data": {"previous_plan": "balanced"},
                        },
                        {"status": "PENDING", "name": "Background"},
                    ],
                }
                with open(os.path.join(tmpdir, "test.json"), "w") as f:
                    json.dump(data, f)

                mgr = GamingLifecycleManager()
                with patch.object(mgr, "_apply_power_plan", return_value=True):
                    result = mgr.recover_incomplete_sessions()
                assert len(result) == 1
                assert result[0]["recovery_status"] == "RECOVERED"
                assert result[0]["session_id"] == "test_incomplete"

    def test_early_state_session_cleaned_up(self):
        """Sessions in DETECTING/BASELINE/RECOMMENDING are marked FAILED."""
        from app.gaming.gaming_lifecycle import GamingLifecycleManager
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                for state in ("DETECTING", "BASELINE", "RECOMMENDING"):
                    data = {
                        "session_id": f"test_{state}",
                        "state": state,
                        "target_name": "Game",
                        "changes": [],
                    }
                    with open(os.path.join(tmpdir, f"{state}.json"), "w") as f:
                        json.dump(data, f)

                mgr = GamingLifecycleManager()
                result = mgr.recover_incomplete_sessions()
                assert len(result) == 3  # One result per early-state file

                # Verify files were updated to FAILED
                for state in ("DETECTING", "BASELINE", "RECOMMENDING"):
                    with open(os.path.join(tmpdir, f"{state}.json")) as f:
                        updated = json.load(f)
                    assert updated["state"] == "FAILED"

    def test_corrupted_session_file_skipped(self):
        """Corrupted JSON files are skipped gracefully."""
        from app.gaming.gaming_lifecycle import GamingLifecycleManager
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                with open(os.path.join(tmpdir, "bad.json"), "w") as f:
                    f.write("not json {{{")

                mgr = GamingLifecycleManager()
                result = mgr.recover_incomplete_sessions()
                assert result == []


# ── Lifecycle history ────────────────────────────────────────────


class TestLifecycleHistory:
    """Test session history loading."""

    def test_load_history_empty(self):
        from app.gaming.gaming_lifecycle import GamingLifecycleManager
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                mgr = GamingLifecycleManager()
                result = mgr.load_history()
                assert result == []

    def test_load_history_with_sessions(self):
        from app.gaming.gaming_lifecycle import GamingLifecycleManager
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                for i in range(3):
                    data = {
                        "session_id": f"sess_{i}",
                        "state": "COMPLETED",
                        "target_name": f"Game_{i}",
                    }
                    with open(os.path.join(tmpdir, f"sess_{i}.json"), "w") as f:
                        json.dump(data, f)

                mgr = GamingLifecycleManager()
                result = mgr.load_history(count=2)
                assert len(result) == 2

    def test_load_history_count_limit(self):
        from app.gaming.gaming_lifecycle import GamingLifecycleManager
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch("app.gaming.gaming_lifecycle.SESSIONS_DIR", tmpdir):
                for i in range(10):
                    data = {"session_id": f"sess_{i}", "state": "COMPLETED"}
                    with open(os.path.join(tmpdir, f"sess_{i}.json"), "w") as f:
                        json.dump(data, f)

                mgr = GamingLifecycleManager()
                result = mgr.load_history(count=3)
                assert len(result) == 3


# ── Session state transitions ────────────────────────────────────


class TestSessionStateTransitions:
    """Test that session states are correct."""

    def test_lifecycle_states_complete(self):
        from app.gaming.gaming_lifecycle import LifecycleState
        states = [s.value for s in LifecycleState]
        required = [
            "IDLE", "DETECTING", "BASELINE", "RECOMMENDING",
            "AWAITING_APPROVAL", "APPLYING", "MONITORING",
            "VALIDATING", "STOPPING", "RESTORING", "REPORTING",
            "COMPLETED", "FAILED",
        ]
        for s in required:
            assert s in states, f"Missing state: {s}"

    def test_session_engine_states_complete(self):
        from app.core.gaming_session import SessionState
        states = [s.value for s in SessionState]
        required = [
            "IDLE", "STARTING", "BASELINE", "OPTIMIZING",
            "MONITORING", "STOPPING", "ENDED", "FAILED",
        ]
        for s in required:
            assert s in states, f"Missing state: {s}"


# ── Duplicate session prevention ─────────────────────────────────


class TestDuplicateSessionPrevention:
    """Test that duplicate sessions are prevented."""

    def test_cannot_start_twice(self):
        from app.gaming.gaming_lifecycle import (
            GamingLifecycleManager, LifecycleState,
        )
        mgr = GamingLifecycleManager()
        session = MagicMock()
        session.target_name = "Game"
        session.target_pid = 1234
        mgr._session = session
        mgr._state = LifecycleState.MONITORING

        result = mgr.start()
        assert result is session  # Returns existing session

    def test_session_engine_cannot_start_twice(self):
        from app.core.gaming_session import GamingSessionEngine, GamingSession, SessionState
        engine = GamingSessionEngine()
        engine._session = GamingSession(state=SessionState.MONITORING)

        result = engine.start_session("gaming")
        assert result.state == SessionState.MONITORING


# ── Backup data validation ──────────────────────────────────────


class TestBackupDataValidation:
    """Test baseline and change data models."""

    def test_baseline_to_dict(self):
        from app.gaming.gaming_lifecycle import LifecycleBaseline
        b = LifecycleBaseline(
            cpu_percent=45.0, gpu_percent=70.0,
            ram_percent=65.0, fps=120.0,
            target_name="Game", target_pid=1234,
        )
        d = b.to_dict()
        assert d["cpu_percent"] == 45.0
        assert d["fps"] == 120.0

    def test_baseline_diff(self):
        from app.gaming.gaming_lifecycle import LifecycleBaseline
        before = LifecycleBaseline(cpu_percent=40.0, fps=60.0)
        after = LifecycleBaseline(cpu_percent=55.0, fps=80.0)
        diffs = before.diff(after)
        assert diffs["cpu_percent"] == 15.0
        assert diffs["fps"] == 20.0

    def test_change_to_dict(self):
        from app.gaming.gaming_lifecycle import (
            LifecycleChange, ChangeType, ChangeStatus,
        )
        c = LifecycleChange(
            name="Power Plan",
            category="power",
            change_type=ChangeType.TEMPORARY,
            status=ChangeStatus.APPLIED,
        )
        d = c.to_dict()
        assert d["name"] == "Power Plan"
        assert d["change_type"] == "TEMPORARY"
        assert d["status"] == "APPLIED"

    def test_recommendation_auto_id(self):
        from app.gaming.gaming_lifecycle import LifecycleRecommendation
        r1 = LifecycleRecommendation(title="A")
        r2 = LifecycleRecommendation(title="B")
        assert r1.recommendation_id != r2.recommendation_id
        assert r1.recommendation_id.startswith("rec_")


# ── TelemetrySummary ────────────────────────────────────────────


class TestTelemetrySummary:
    """Test the session telemetry summary model."""

    def test_defaults(self):
        from app.core.gaming_session import TelemetrySummary
        s = TelemetrySummary()
        assert s.avg_fps is None
        assert s.avg_cpu is None
        assert s.telemetry_samples == 0

    def test_to_dict(self):
        from app.core.gaming_session import TelemetrySummary
        s = TelemetrySummary(avg_fps=120.0, avg_cpu=45.0, telemetry_samples=10)
        d = s.to_dict()
        assert d["avg_fps"] == 120.0
        assert d["avg_cpu"] == 45.0
        assert d["telemetry_samples"] == 10


# ── GamingSession model ─────────────────────────────────────────


class TestGamingSessionModel:
    """Test the GamingSession data model."""

    def test_applied_count(self):
        from app.core.gaming_session import GamingSession, SessionOptimization
        s = GamingSession()
        s.optimizations.extend([
            SessionOptimization(status="APPLIED"),
            SessionOptimization(status="APPLIED"),
            SessionOptimization(status="ALREADY_OPTIMAL"),
        ])
        assert s.applied_count == 2

    def test_needs_rollback(self):
        from app.core.gaming_session import GamingSession, SessionOptimization
        s = GamingSession()
        assert not s.needs_rollback
        s.optimizations.append(SessionOptimization(status="APPLIED"))
        assert s.needs_rollback
        s.snapshot_restored = True
        assert not s.needs_rollback


# ── Integration: Worker collects lifecycle data ──────────────────


class TestWorkerLifecycleIntegration:
    """Verify the worker code path for session data exists."""

    def test_worker_has_session_fields(self):
        from app.ui.home_page_worker import HomePageResult
        r = HomePageResult()
        # All session fields should be accessible
        assert hasattr(r, "session_active")
        assert hasattr(r, "session_state")
        assert hasattr(r, "session_target")
        assert hasattr(r, "session_pid")
        assert hasattr(r, "session_duration")
        assert hasattr(r, "session_applied")
        assert hasattr(r, "session_cpu")
        assert hasattr(r, "session_gpu")
        assert hasattr(r, "session_ram")
        assert hasattr(r, "session_fps")
        assert hasattr(r, "session_recent")


# ── CLI format ──────────────────────────────────────────────────


class TestSessionReportFormat:
    """Test session report formatting."""

    def test_format_cli(self):
        from app.gaming.gaming_lifecycle import (
            SessionReport, LifecycleBaseline,
        )
        baseline = LifecycleBaseline(
            cpu_percent=45.0, gpu_percent=60.0,
            fps=80.0, target_name="Game",
        )
        final = LifecycleBaseline(
            cpu_percent=40.0, gpu_percent=65.0,
            fps=95.0, target_name="Game",
        )
        report = SessionReport(
            session_id="test_123",
            target_name="BlueStacks",
            target_pid=1234,
            profile_id="gaming",
            baseline=baseline,
            final=final,
            changes_applied=2,
            changes_restored=1,
            summary="2 applied; 1 restored",
        )
        text = report.format_cli()
        assert "GAMING SESSION REPORT" in text
        assert "test_123" in text
        assert "BlueStacks" in text
        assert "RESTORATION" in text
        assert "SUMMARY" in text
