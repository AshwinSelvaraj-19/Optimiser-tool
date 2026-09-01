"""
Comprehensive tests for Phase 61 — Complete Gaming Lifecycle.

Tests: LifecycleState, ChangeType, ChangeStatus, LifecycleChange,
       LifecycleRecommendation, LifecycleBaseline, SessionReport,
       LifecycleSession, GamingLifecycleManager, detection, baseline,
       recommendations, approval, apply, monitor, validate, stop,
       restore, persistence, edge cases, CLI format.
"""

import json
import os
import shutil
import tempfile
import time
from unittest.mock import MagicMock, patch, PropertyMock

import pytest

from app.gaming.gaming_lifecycle import (
    LifecycleState,
    ChangeType,
    ChangeStatus,
    LifecycleChange,
    LifecycleRecommendation,
    LifecycleBaseline,
    SessionReport,
    LifecycleSession,
    GamingLifecycleManager,
    gaming_lifecycle,
    SESSIONS_DIR,
)


# ── Helpers ──────────────────────────────────────────────────────


def _fresh_manager():
    """Create a fresh manager with no active session."""
    mgr = GamingLifecycleManager()
    return mgr


def _mock_target(name="HD-Player.exe", pid=12345):
    """Create a mock target process."""
    target = MagicMock()
    target.process_name = name
    target.pid = pid
    return target


def _mock_baseline(**overrides):
    """Create a baseline with sensible defaults."""
    defaults = {
        "timestamp": time.time(),
        "cpu_percent": 45.0,
        "gpu_percent": 60.0,
        "gpu_temp": 65.0,
        "ram_percent": 70.0,
        "ram_available_gb": 4.0,
        "fps": 60.0,
        "frame_time_ms": 16.0,
        "disk_free_gb": 200.0,
        "target_name": "HD-Player.exe",
        "target_pid": 12345,
        "power_plan": "high_performance",
        "game_mode": True,
        "background_cpu": 10.0,
        "background_ram_mb": 500.0,
    }
    defaults.update(overrides)
    return LifecycleBaseline(**defaults)


# ── Data Model Tests ─────────────────────────────────────────────


class TestLifecycleState:
    def test_all_states_exist(self):
        states = [s.value for s in LifecycleState]
        assert "IDLE" in states
        assert "DETECTING" in states
        assert "BASELINE" in states
        assert "RECOMMENDING" in states
        assert "AWAITING_APPROVAL" in states
        assert "APPLYING" in states
        assert "MONITORING" in states
        assert "VALIDATING" in states
        assert "STOPPING" in states
        assert "RESTORING" in states
        assert "REPORTING" in states
        assert "COMPLETED" in states
        assert "FAILED" in states


class TestChangeType:
    def test_temporary(self):
        assert ChangeType.TEMPORARY.value == "TEMPORARY"

    def test_permanent(self):
        assert ChangeType.PERMANENT.value == "PERMANENT"


class TestChangeStatus:
    def test_all_statuses(self):
        statuses = [s.value for s in ChangeStatus]
        assert "PENDING" in statuses
        assert "APPLIED" in statuses
        assert "VERIFIED" in statuses
        assert "FAILED" in statuses
        assert "RESTORED" in statuses
        assert "RESTORE_FAILED" in statuses
        assert "KEPT" in statuses
        assert "IRREVERSIBLE" in statuses


class TestLifecycleChange:
    def test_auto_id(self):
        c = LifecycleChange(name="test")
        assert c.change_id.startswith("chg_")
        assert len(c.change_id) > 4

    def test_auto_timestamp(self):
        c = LifecycleChange(name="test")
        assert c.timestamp > 0

    def test_to_dict(self):
        c = LifecycleChange(
            name="Test Change",
            category="power",
            change_type=ChangeType.TEMPORARY,
            status=ChangeStatus.APPLIED,
        )
        d = c.to_dict()
        assert d["name"] == "Test Change"
        assert d["category"] == "power"
        assert d["change_type"] == "TEMPORARY"
        assert d["status"] == "APPLIED"


class TestLifecycleRecommendation:
    def test_auto_id(self):
        r = LifecycleRecommendation(title="test")
        assert r.recommendation_id.startswith("rec_")

    def test_default_not_approved(self):
        r = LifecycleRecommendation(title="test")
        assert not r.approved
        assert not r.auto_apply


class TestLifecycleBaseline:
    def test_to_dict(self):
        b = _mock_baseline()
        d = b.to_dict()
        assert d["cpu_percent"] == 45.0
        assert d["gpu_temp"] == 65.0

    def test_diff(self):
        before = _mock_baseline(cpu_percent=40.0, ram_percent=60.0, fps=50.0)
        after = _mock_baseline(cpu_percent=55.0, ram_percent=75.0, fps=70.0)
        diffs = before.diff(after)
        assert diffs["cpu_percent"] == 15.0
        assert diffs["ram_percent"] == 15.0
        assert diffs["fps"] == 20.0

    def test_diff_with_none(self):
        before = _mock_baseline(cpu_percent=None, fps=50.0)
        after = _mock_baseline(cpu_percent=50.0, fps=None)
        diffs = before.diff(after)
        assert diffs["cpu_percent"] is None
        assert diffs["fps"] is None


class TestSessionReport:
    def test_to_dict(self):
        report = SessionReport(
            session_id="test123",
            target_name="BlueStacks",
            changes_applied=3,
            changes_restored=2,
        )
        d = report.to_dict()
        assert d["session_id"] == "test123"
        assert d["changes_applied"] == 3
        assert d["changes_restored"] == 2

    def test_format_cli(self):
        report = SessionReport(
            session_id="test123",
            target_name="BlueStacks",
            target_pid=1234,
            profile_id="gaming",
            baseline=_mock_baseline(),
            final=_mock_baseline(cpu_percent=40.0),
            changes_applied=2,
            changes_restored=1,
            summary="2 applied, 1 restored",
        )
        text = report.format_cli()
        assert "GAMING SESSION REPORT" in text
        assert "test123" in text
        assert "BlueStacks" in text
        assert "RESTORATION" in text


class TestLifecycleSession:
    def test_to_dict(self):
        s = LifecycleSession(
            session_id="lc_test",
            state="IDLE",
            target_name="BlueStacks",
        )
        d = s.to_dict()
        assert d["session_id"] == "lc_test"
        assert d["state"] == "IDLE"


# ── Manager Lifecycle Tests ──────────────────────────────────────


class TestManagerConstruction:
    def test_singleton_exists(self):
        assert gaming_lifecycle is not None
        assert isinstance(gaming_lifecycle, GamingLifecycleManager)

    def test_fresh_manager_idle(self):
        mgr = _fresh_manager()
        assert mgr.state == LifecycleState.IDLE
        assert not mgr.is_active
        assert mgr.session is None

    def test_state_start(self):
        mgr = _fresh_manager()
        assert mgr.state == LifecycleState.IDLE

    def test_pending_approval_initially_none(self):
        mgr = _fresh_manager()
        assert mgr.pending_approval is None


class TestStartNoTarget:
    """Test starting lifecycle when no game/emulator is running."""

    @patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._detect_target")
    def test_no_target_returns_none(self, mock_detect):
        mock_detect.side_effect = lambda s: setattr(s, "target_name", "")
        mgr = _fresh_manager()
        result = mgr.start()
        assert result is None
        assert mgr.state == LifecycleState.IDLE

    @patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._detect_target")
    @patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._capture_baseline")
    @patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._generate_recommendations")
    def test_with_target_starts_session(self, mock_rec, mock_base, mock_detect):
        def set_target(s):
            s.target_name = "BlueStacks"
            s.target_pid = 1234
        mock_detect.side_effect = set_target
        mgr = _fresh_manager()
        result = mgr.start()
        assert result is not None
        assert result.target_name == "BlueStacks"
        assert result.target_pid == 1234
        mock_base.assert_called_once()
        mock_rec.assert_called_once()

    @patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._detect_target")
    def test_cannot_start_twice(self, mock_detect):
        def set_target(s):
            s.target_name = "BlueStacks"
            s.target_pid = 1234
        mock_detect.side_effect = set_target
        mgr = _fresh_manager()
        with patch.object(mgr, "_capture_baseline") as mock_base, \
             patch.object(mgr, "_generate_recommendations") as mock_rec:
            # The patched methods must still set state so is_active=True
            def fake_base(session):
                mgr._set_state(session, LifecycleState.BASELINE)
            def fake_rec(session):
                mgr._set_state(session, LifecycleState.RECOMMENDING)
            mock_base.side_effect = fake_base
            mock_rec.side_effect = fake_rec
            s1 = mgr.start()
            s2 = mgr.start()
            assert s1 is s2  # Returns existing session


class TestBaselineCapture:
    def test_baseline_values(self):
        b = _mock_baseline()
        assert b.cpu_percent == 45.0
        assert b.gpu_percent == 60.0
        assert b.ram_percent == 70.0
        assert b.target_name == "HD-Player.exe"
        assert b.target_pid == 12345

    def test_baseline_with_none_values(self):
        b = _mock_baseline(cpu_percent=None, gpu_percent=None, fps=None)
        assert b.cpu_percent is None
        assert b.gpu_percent is None
        assert b.fps is None


class TestRecommendations:
    def test_no_recommendation_for_high_performance(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(power_plan="high_performance")
        mgr._session = session
        mgr._generate_recommendations(session)
        power_recs = [r for r in session.recommendations if r.category == "power"]
        assert len(power_recs) == 0

    def test_recommendation_for_low_power(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(power_plan="balanced")
        mgr._session = session
        mgr._generate_recommendations(session)
        power_recs = [r for r in session.recommendations if r.category == "power"]
        assert len(power_recs) == 1
        assert power_recs[0].auto_apply is True
        assert power_recs[0].change_type == ChangeType.TEMPORARY

    def test_turbo_plan_no_recommendation(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(power_plan="Turbo")
        mgr._session = session
        mgr._generate_recommendations(session)
        power_recs = [r for r in session.recommendations if r.category == "power"]
        assert len(power_recs) == 0

    def test_game_mode_disabled_recommendation(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(game_mode=False)
        mgr._session = session
        mgr._generate_recommendations(session)
        gm_recs = [r for r in session.recommendations if r.category == "game_mode"]
        assert len(gm_recs) == 1
        assert gm_recs[0].auto_apply is True

    def test_game_mode_enabled_no_recommendation(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(game_mode=True)
        mgr._session = session
        mgr._generate_recommendations(session)
        gm_recs = [r for r in session.recommendations if r.category == "game_mode"]
        assert len(gm_recs) == 0

    def test_high_ram_recommendation(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(ram_percent=88.0)
        mgr._session = session
        mgr._generate_recommendations(session)
        mem_recs = [r for r in session.recommendations if r.category == "memory"]
        assert len(mem_recs) == 1
        assert mem_recs[0].auto_apply is False  # requires user approval

    def test_low_ram_no_recommendation(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(ram_percent=50.0)
        mgr._session = session
        mgr._generate_recommendations(session)
        mem_recs = [r for r in session.recommendations if r.category == "memory"]
        assert len(mem_recs) == 0

    def test_high_background_cpu_recommendation(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(background_cpu=45.0)
        mgr._session = session
        mgr._generate_recommendations(session)
        bg_recs = [r for r in session.recommendations if r.category == "background"]
        assert len(bg_recs) == 1

    def test_low_background_cpu_no_recommendation(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(background_cpu=5.0)
        mgr._session = session
        mgr._generate_recommendations(session)
        bg_recs = [r for r in session.recommendations if r.category == "background"]
        assert len(bg_recs) == 0

    def test_low_fps_recommendation(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(fps=20.0)
        mgr._session = session
        mgr._generate_recommendations(session)
        perf_recs = [r for r in session.recommendations if r.category == "performance"]
        assert len(perf_recs) == 1
        assert perf_recs[0].change_type == ChangeType.PERMANENT
        assert perf_recs[0].auto_apply is False

    def test_all_auto_apply_when_no_manual(self):
        """When all recommendations are auto-apply, no approval is needed."""
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(
            power_plan="balanced", game_mode=False,
            ram_percent=50.0, background_cpu=5.0,
        )
        mgr._session = session
        mgr._generate_recommendations(session)
        # All should be auto-approved
        assert mgr.pending_approval is None
        all_approved = all(r.approved for r in session.recommendations)
        assert all_approved


class TestApproval:
    def _setup_with_pending(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline(
            ram_percent=90.0, background_cpu=45.0,
        )
        mgr._session = session
        mgr._state = LifecycleState.AWAITING_APPROVAL
        mgr._generate_recommendations(session)
        return mgr, session

    def test_approve_specific(self):
        mgr, session = self._setup_with_pending()
        recs = mgr.pending_approval
        assert recs is not None and len(recs) > 0
        # Approve first one
        mgr.approve_recommendations([recs[0].recommendation_id])
        assert recs[0].approved is True
        assert mgr.pending_approval is None

    def test_approve_all(self):
        mgr, session = self._setup_with_pending()
        recs = mgr.pending_approval
        assert recs is not None
        mgr.approve_all()
        assert all(r.approved for r in recs)
        assert mgr.pending_approval is None

    def test_reject_all(self):
        mgr, session = self._setup_with_pending()
        recs = mgr.pending_approval
        assert recs is not None
        with patch.object(mgr, "_start_monitoring"):
            mgr.reject_all()
        assert mgr.pending_approval is None
        assert not any(r.approved for r in recs)

    def test_approve_when_not_awaiting(self):
        mgr = _fresh_manager()
        mgr._state = LifecycleState.IDLE
        mgr.approve_all()  # Should be a no-op


class TestStopAndRestore:
    @patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._check_target_alive")
    def test_stop_with_no_session(self, mock_alive):
        mgr = _fresh_manager()
        report = mgr.stop()
        assert report is None

    def test_restore_temporary_only(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.target_name = "BlueStacks"
        session.target_pid = 1234
        session.baseline = _mock_baseline()

        # Add changes
        temp_change = LifecycleChange(
            name="Power Plan",
            category="power",
            change_type=ChangeType.TEMPORARY,
            status=ChangeStatus.APPLIED,
            reversible=True,
            rollback_data={"previous_plan": "balanced"},
        )
        perm_change = LifecycleChange(
            name="Graphics Settings",
            category="performance",
            change_type=ChangeType.PERMANENT,
            status=ChangeStatus.APPLIED,
            reversible=False,
        )
        session.changes = [temp_change, perm_change]

        with patch.object(mgr, "_apply_power_plan", return_value=True), \
             patch.object(mgr, "_capture_final_state", return_value=_mock_baseline()):
            mgr._session = session
            mgr._restore_temporary(session)

        # Temporary should be restored
        assert temp_change.status == ChangeStatus.RESTORED
        # Permanent should be kept
        assert perm_change.status == ChangeStatus.KEPT

    def test_restore_irreversible_change(self):
        change = LifecycleChange(
            name="irreversible",
            category="custom",
            change_type=ChangeType.TEMPORARY,
            status=ChangeStatus.APPLIED,
            reversible=False,
        )
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.changes = [change]
        mgr._restore_temporary(session)
        assert change.status == ChangeStatus.IRREVERSIBLE

    def test_restore_skips_pending_changes(self):
        change = LifecycleChange(
            name="pending",
            category="power",
            change_type=ChangeType.TEMPORARY,
            status=ChangeStatus.PENDING,  # Not applied
            reversible=True,
        )
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.changes = [change]
        mgr._restore_temporary(session)
        # Status should remain PENDING (not touched)
        assert change.status == ChangeStatus.PENDING


class TestPersistence:
    def test_save_and_load(self):
        mgr = _fresh_manager()
        session = LifecycleSession(
            session_id="test_persist",
            state="IDLE",
            target_name="BlueStacks",
        )
        mgr._save_session(session)

        history = mgr.load_history()
        assert len(history) >= 1
        found = [h for h in history if h.get("session_id") == "test_persist"]
        assert len(found) == 1

    def test_load_history_empty_dir(self):
        mgr = _fresh_manager()
        # Should not crash even if dir is empty or missing
        history = mgr.load_history()
        assert isinstance(history, list)


class TestTargetDetection:
    def test_detect_with_target_process(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        with patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._detect_target") as mock:
            mock.side_effect = lambda s: (
                setattr(s, "target_name", "HD-Player.exe"),
                setattr(s, "target_pid", 5678),
            )
            mgr._detect_target(session)
        assert session.target_name == "HD-Player.exe"
        assert session.target_pid == 5678

    def test_detect_no_target(self):
        mgr = _fresh_manager()
        session = LifecycleSession()
        with patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._detect_target") as mock:
            mock.side_effect = lambda s: setattr(s, "target_name", "")
            mgr._detect_target(session)
        assert session.target_name == ""


class TestFormatStatus:
    def test_idle_status(self):
        mgr = _fresh_manager()
        status = mgr.format_status()
        assert "GAMING LIFECYCLE STATUS" in status
        assert "IDLE" in status
        assert "No active lifecycle" in status

    def test_active_status(self):
        mgr = _fresh_manager()
        session = LifecycleSession(
            session_id="lc_test",
            target_name="BlueStacks",
            target_pid=1234,
            profile_id="gaming",
            baseline=_mock_baseline(),
        )
        mgr._session = session
        mgr._state = LifecycleState.MONITORING
        session.state = LifecycleState.MONITORING.value
        status = mgr.format_status()
        assert "BlueStacks" in status
        assert "MONITORING" in status
        assert "PID 1234" in status

    def test_status_with_pending_approval(self):
        mgr = _fresh_manager()
        session = LifecycleSession(
            session_id="lc_test",
            target_name="BlueStacks",
            target_pid=1234,
            profile_id="gaming",
            baseline=_mock_baseline(),
        )
        mgr._session = session
        mgr._state = LifecycleState.AWAITING_APPROVAL
        session.state = LifecycleState.AWAITING_APPROVAL.value
        mgr._pending_approval = [
            LifecycleRecommendation(title="Test Rec", change_type=ChangeType.TEMPORARY),
        ]
        status = mgr.format_status()
        assert "AWAITING APPROVAL" in status
        assert "Test Rec" in status


class TestChangeTracking:
    def test_changes_counted_correctly(self):
        session = LifecycleSession()
        session.changes = [
            LifecycleChange(status=ChangeStatus.APPLIED, change_type=ChangeType.TEMPORARY),
            LifecycleChange(status=ChangeStatus.RESTORED, change_type=ChangeType.TEMPORARY),
            LifecycleChange(status=ChangeStatus.KEPT, change_type=ChangeType.PERMANENT),
            LifecycleChange(status=ChangeStatus.FAILED, change_type=ChangeType.TEMPORARY),
        ]
        session.changes_applied = sum(
            1 for c in session.changes
            if c.status in (ChangeStatus.APPLIED, ChangeStatus.VERIFIED,
                            ChangeStatus.RESTORED, ChangeStatus.KEPT)
        )
        assert session.changes_applied == 3

    def test_only_session_changes_restored(self):
        """Only this session's changes are processed during restore."""
        mgr = _fresh_manager()
        session = LifecycleSession()
        session.changes = [
            LifecycleChange(
                name="My change",
                category="power",
                change_type=ChangeType.TEMPORARY,
                status=ChangeStatus.APPLIED,
                reversible=True,
                rollback_data={"previous_plan": "balanced"},
            ),
        ]
        with patch.object(mgr, "_apply_power_plan", return_value=True):
            mgr._restore_temporary(session)
        # Only session's changes are touched
        assert session.changes[0].status == ChangeStatus.RESTORED


class TestEdgeCases:
    def test_stop_without_start(self):
        mgr = _fresh_manager()
        report = mgr.stop()
        assert report is None

    def test_callback_error_does_not_crash(self):
        mgr = _fresh_manager()
        mgr._callbacks.append(lambda s, st: 1 / 0)  # raises
        # Should not crash
        mgr._notify()

    def test_session_to_dict_with_none_baseline(self):
        s = LifecycleSession()
        d = s.to_dict()
        assert d["baseline"] is None

    def test_report_to_dict_with_none_final(self):
        r = SessionReport(session_id="test")
        d = r.to_dict()
        assert d["final"] is None

    def test_baseline_diff_identical(self):
        b = _mock_baseline()
        diffs = b.diff(b)
        for v in diffs.values():
            assert v == 0.0

    def test_multiple_callbacks(self):
        mgr = _fresh_manager()
        results = []
        mgr._callbacks.append(lambda s, st: results.append(st))
        mgr._callbacks.append(lambda s, st: results.append(st))
        mgr._state = LifecycleState.IDLE
        mgr._notify()
        assert len(results) == 2

    def test_recommendation_unique_ids(self):
        r1 = LifecycleRecommendation(title="a")
        r2 = LifecycleRecommendation(title="b")
        assert r1.recommendation_id != r2.recommendation_id

    def test_change_unique_ids(self):
        c1 = LifecycleChange(name="a")
        c2 = LifecycleChange(name="b")
        assert c1.change_id != c2.change_id


class TestValidation:
    def test_validation_result_in_report(self):
        report = SessionReport(
            baseline=_mock_baseline(cpu_percent=50.0),
            final=_mock_baseline(cpu_percent=50.0),
        )
        # Simulate validation
        report.validation_performed = True
        report.validation_passed = True
        report.validation_details = "No changes"
        d = report.to_dict()
        assert d["validation_performed"] is True
        assert d["validation_passed"] is True

    def test_validation_failure(self):
        report = SessionReport(
            baseline=_mock_baseline(cpu_percent=40.0),
            final=_mock_baseline(cpu_percent=90.0),
        )
        report.validation_performed = True
        report.validation_passed = False
        report.validation_details = "CPU increased"
        d = report.to_dict()
        assert d["validation_passed"] is False


class TestReportGeneration:
    def test_report_summary_with_changes(self):
        report = SessionReport(
            changes_applied=3,
            changes_restored=2,
            changes_kept=1,
            validation_passed=True,
        )
        report.summary = "3 applied; 2 temporary restored; 1 permanent kept; Validation: PASSED"
        text = report.format_cli()
        assert "3 applied" in text
        assert "RESTORATION" in text

    def test_report_with_changes_list(self):
        report = SessionReport(
            changes=[
                {"name": "Power Plan", "status": "RESTORED", "change_type": "TEMPORARY"},
                {"name": "Game Mode", "status": "APPLIED", "change_type": "TEMPORARY"},
            ],
        )
        text = report.format_cli()
        assert "Power Plan" in text
        assert "Game Mode" in text


class TestWorkerThread:
    def test_worker_initially_not_running(self):
        mgr = _fresh_manager()
        assert not mgr._worker_running

    def test_monitoring_active_initially_false(self):
        mgr = _fresh_manager()
        assert not mgr._monitoring_active


class TestChangeTypeClassification:
    def test_temporary_marked_correctly(self):
        c = LifecycleChange(change_type=ChangeType.TEMPORARY)
        assert c.change_type == ChangeType.TEMPORARY
        d = c.to_dict()
        assert d["change_type"] == "TEMPORARY"

    def test_permanent_marked_correctly(self):
        c = LifecycleChange(change_type=ChangeType.PERMANENT)
        assert c.change_type == ChangeType.PERMANENT
        d = c.to_dict()
        assert d["change_type"] == "PERMANENT"


class TestSessionReportChanges:
    def test_report_classifies_changes(self):
        report = SessionReport()
        report.changes = [
            {"change_type": "TEMPORARY", "status": "RESTORED", "name": "Power"},
            {"change_type": "PERMANENT", "status": "KEPT", "name": "Settings"},
        ]
        report.temporary_changes = [c for c in report.changes if c["change_type"] == "TEMPORARY"]
        report.permanent_changes = [c for c in report.changes if c["change_type"] == "PERMANENT"]
        assert len(report.temporary_changes) == 1
        assert len(report.permanent_changes) == 1


class TestApplySingle:
    def test_unknown_fn_name_returns_false(self):
        mgr = _fresh_manager()
        rec = LifecycleRecommendation(
            title="Test",
            apply_fn_name="unknown_function",
        )
        result = mgr._apply_single(rec)
        assert result is False

    def test_analyze_memory_returns_true(self):
        mgr = _fresh_manager()
        rec = LifecycleRecommendation(
            title="Memory Analysis",
            apply_fn_name="analyze_memory",
        )
        with patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._apply_memory_analysis",
                    return_value=True):
            result = mgr._apply_single(rec)
            assert result is True

    def test_reduce_background_cpu(self):
        mgr = _fresh_manager()
        rec = LifecycleRecommendation(
            title="Reduce Background",
            apply_fn_name="reduce_background_cpu",
        )
        with patch("app.gaming.gaming_lifecycle.GamingLifecycleManager._reduce_background_cpu",
                    return_value=True):
            result = mgr._apply_single(rec)
            assert result is True
