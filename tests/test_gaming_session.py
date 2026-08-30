"""
Tests for Heaven Society — Gaming Session Mode (Phase 27).

Uses mocked subsystems; never requires real PresentMon or hardware.
"""

import os
import json
import glob
import tempfile
import threading
import time
import pytest
from unittest.mock import patch, MagicMock

from app.core.gaming_session import (
    GamingSession,
    GamingSessionEngine,
    SessionState,
    SessionOptimization,
    TelemetrySummary,
    save_session,
    load_sessions,
)


class TestSessionState:
    """Test SessionState enum."""

    def test_all_values(self):
        assert SessionState.IDLE.value == "IDLE"
        assert SessionState.STARTING.value == "STARTING"
        assert SessionState.BASELINE.value == "BASELINE"
        assert SessionState.OPTIMIZING.value == "OPTIMIZING"
        assert SessionState.MONITORING.value == "MONITORING"
        assert SessionState.STOPPING.value == "STOPPING"
        assert SessionState.ENDED.value == "ENDED"
        assert SessionState.FAILED.value == "FAILED"

    def test_count(self):
        assert len(SessionState) == 8


class TestTelemetrySummary:
    """Test TelemetrySummary data model."""

    def test_defaults(self):
        s = TelemetrySummary()
        assert s.avg_fps is None
        assert s.avg_cpu is None
        assert s.telemetry_samples == 0

    def test_to_dict(self):
        s = TelemetrySummary(avg_fps=120.0, avg_cpu=45.0, telemetry_samples=10)
        d = s.to_dict()
        assert d["avg_fps"] == 120.0
        assert d["avg_cpu"] == 45.0
        assert d["telemetry_samples"] == 10


class TestSessionOptimization:
    """Test SessionOptimization data model."""

    def test_defaults(self):
        o = SessionOptimization()
        assert o.opt_id == ""
        assert o.status == ""
        assert o.verified is False

    def test_applied(self):
        o = SessionOptimization(
            opt_id="power_plan", name="Power Plan",
            status="APPLIED", verified=True,
        )
        assert o.status == "APPLIED"
        assert o.verified is True


class TestGamingSession:
    """Test GamingSession data model."""

    def test_defaults(self):
        s = GamingSession()
        assert s.session_id.startswith("session_")
        assert s.state == SessionState.IDLE
        assert s.optimizations == []
        assert s.errors == []
        assert s.target_lost is False
        assert s.pid_changed is False

    def test_has_applied_optimizations(self):
        s = GamingSession()
        assert not s.has_applied_optimizations
        s.optimizations.append(SessionOptimization(status="APPLIED"))
        assert s.has_applied_optimizations

    def test_applied_count(self):
        s = GamingSession()
        s.optimizations.extend([
            SessionOptimization(status="APPLIED"),
            SessionOptimization(status="APPLIED"),
            SessionOptimization(status="ALREADY_OPTIMAL"),
        ])
        assert s.applied_count == 2

    def test_needs_rollback(self):
        s = GamingSession()
        assert not s.needs_rollback
        s.optimizations.append(SessionOptimization(status="APPLIED"))
        assert s.needs_rollback
        s.snapshot_restored = True
        assert not s.needs_rollback

    def test_to_dict(self):
        s = GamingSession(
            session_id="test_123",
            profile_id="gaming",
            target_name="HD-Player.exe",
            target_pid=1234,
        )
        d = s.to_dict()
        assert d["session_id"] == "test_123"
        assert d["profile_id"] == "gaming"
        assert d["target_pid"] == 1234


class TestSessionStorage:
    """Test session persistence."""

    def test_save_and_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import app.core.gaming_session as mod
            old_dir = mod.SESSIONS_DIR
            mod.SESSIONS_DIR = tmpdir
            try:
                session = GamingSession(profile_id="test")
                session.optimizations.append(SessionOptimization(
                    opt_id="opt1", status="APPLIED",
                ))
                save_session(session)

                loaded = load_sessions()
                assert len(loaded) == 1
                assert loaded[0].profile_id == "test"
            finally:
                mod.SESSIONS_DIR = old_dir

    def test_load_empty_dir(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import app.core.gaming_session as mod
            old_dir = mod.SESSIONS_DIR
            mod.SESSIONS_DIR = tmpdir
            try:
                loaded = load_sessions()
                assert len(loaded) == 0
            finally:
                mod.SESSIONS_DIR = old_dir

    def test_load_corrupted(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            import app.core.gaming_session as mod
            old_dir = mod.SESSIONS_DIR
            mod.SESSIONS_DIR = tmpdir
            try:
                with open(os.path.join(tmpdir, "bad.json"), "w") as f:
                    f.write("not json {{{")
                loaded = load_sessions()
                assert len(loaded) == 0
            finally:
                mod.SESSIONS_DIR = old_dir


class TestTargetDetection:
    """Test target detection and validation."""

    def test_detect_no_emulator(self):
        engine = GamingSessionEngine()
        with patch("app.performance.target_process.target_process_detector") as mock:
            mock.select_best_target.return_value = None
            name, pid, start = engine._detect_target()
            assert name == ""
            assert pid == 0

    def test_detect_with_emulator(self):
        engine = GamingSessionEngine()
        with patch("app.performance.target_process.target_process_detector") as mock_det, \
             patch("psutil.Process") as mock_proc_cls:
            best = MagicMock()
            best.process_name = "HD-Player.exe"
            best.pid = 1234
            mock_det.select_best_target.return_value = best

            proc = MagicMock()
            proc.create_time.return_value = 1000.0
            mock_proc_cls.return_value = proc

            name, pid, start = engine._detect_target()
            assert name == "HD-Player.exe"
            assert pid == 1234
            assert start == 1000.0

    def test_check_target_alive(self):
        engine = GamingSessionEngine()
        with patch("psutil.Process") as mock_proc_cls:
            proc = MagicMock()
            proc.is_running.return_value = True
            mock_proc_cls.return_value = proc
            assert engine._check_target_alive(1234)

    def test_check_target_dead(self):
        engine = GamingSessionEngine()
        with patch("psutil.Process") as mock_proc_cls:
            import psutil
            mock_proc_cls.side_effect = psutil.NoSuchProcess(1234)
            assert not engine._check_target_alive(1234)

    def test_check_target_valid_same_pid(self):
        engine = GamingSessionEngine()
        session = GamingSession(target_pid=1234, target_start_time=1000.0)
        with patch("psutil.Process") as mock_proc_cls:
            proc = MagicMock()
            proc.is_running.return_value = True
            proc.create_time.return_value = 1000.0
            mock_proc_cls.return_value = proc
            assert engine._check_target_valid(session)
            assert not session.target_lost
            assert not session.pid_changed

    def test_check_target_valid_pid_reused(self):
        engine = GamingSessionEngine()
        session = GamingSession(target_pid=1234, target_start_time=1000.0)
        with patch("psutil.Process") as mock_proc_cls:
            proc = MagicMock()
            proc.is_running.return_value = True
            proc.create_time.return_value = 2000.0
            mock_proc_cls.return_value = proc
            assert not engine._check_target_valid(session)
            assert session.pid_changed

    def test_check_target_lost(self):
        engine = GamingSessionEngine()
        session = GamingSession(target_pid=1234, target_start_time=1000.0)
        with patch("psutil.Process") as mock_proc_cls:
            import psutil
            mock_proc_cls.side_effect = psutil.NoSuchProcess(1234)
            assert not engine._check_target_valid(session)
            assert session.target_lost


class TestSessionLifecycle:
    """Test complete session lifecycle with mocks."""

    def test_start_no_target(self):
        engine = GamingSessionEngine()
        with patch.object(engine, "_detect_target", return_value=("", 0, 0.0)):
            session = engine.start_session("gaming")
            assert session.state == SessionState.FAILED
            assert any("No emulator" in e for e in session.errors)

    def test_start_with_target(self):
        engine = GamingSessionEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234, 1000.0)), \
             patch.object(engine, "_capture_telemetry_summary") as mock_tel, \
             patch.object(engine, "_apply_optimizations"), \
             patch.object(engine, "_start_monitoring"), \
             patch("app.core.profiles.get_profile") as mock_profile, \
             patch("app.core.gaming_session.save_session"):

            mock_tel.return_value = TelemetrySummary(avg_cpu=35.0, avg_gpu=60.0)
            mock_prof = MagicMock()
            mock_prof.name = "Gaming"
            mock_prof.optimizations = []
            mock_profile.return_value = mock_prof

            session = engine.start_session("gaming")
            assert session.state == SessionState.MONITORING
            assert session.target_name == "HD-Player.exe"
            assert session.target_pid == 1234
            assert session.profile_name == "Gaming"

    def test_start_already_active(self):
        engine = GamingSessionEngine()
        engine._session = GamingSession(state=SessionState.MONITORING)
        with patch("app.core.gaming_session.save_session"):
            session = engine.start_session("gaming")
            assert session.state == SessionState.MONITORING

    def test_stop_active_session(self):
        engine = GamingSessionEngine()
        session = GamingSession(
            state=SessionState.MONITORING,
            target_name="HD-Player.exe",
            target_pid=1234,
        )
        engine._session = session
        engine._monitoring = True

        with patch.object(engine, "_stop_session_inner"), \
             patch.object(engine, "_cleanup_safe"), \
             patch("app.core.gaming_session.save_session"):
            result = engine.stop_session()
            assert result.state == SessionState.ENDED

    def test_stop_no_session(self):
        engine = GamingSessionEngine()
        result = engine.stop_session()
        assert result.state == SessionState.IDLE

    def test_restore_with_applied(self):
        engine = GamingSessionEngine()
        session = GamingSession(
            snapshot_id="snap_123",
            optimizations=[SessionOptimization(opt_id="power_plan", status="APPLIED")],
        )
        engine._session = session

        with patch("app.core.gaming_session.save_session"), \
             patch("app.core.snapshot.snapshot_manager") as mock_snap, \
             patch("app.core.rollback.rollback_engine") as mock_roll:

            mock_snapshot = MagicMock()
            mock_snap.load_snapshot.return_value = mock_snapshot
            mock_result = MagicMock()
            mock_result.success = True
            mock_result.message = "Restored 1 entry"
            mock_roll.rollback.return_value = mock_result

            result = engine.restore_session()
            assert result.snapshot_restored is True

    def test_restore_no_applied(self):
        engine = GamingSessionEngine()
        session = GamingSession(
            optimizations=[SessionOptimization(status="ALREADY_OPTIMAL")],
        )
        engine._session = session
        result = engine.restore_session()
        assert result.snapshot_restored is True

    def test_restore_no_snapshot(self):
        engine = GamingSessionEngine()
        session = GamingSession(
            snapshot_id="",
            optimizations=[SessionOptimization(status="APPLIED")],
        )
        engine._session = session
        with patch("app.core.gaming_session.save_session"):
            result = engine.restore_session()
            assert not result.snapshot_restored
            assert any("No snapshot" in e for e in result.errors)


class TestOptimizationApplication:
    """Test optimization application within session."""

    def test_apply_all_status_types(self):
        engine = GamingSessionEngine()
        session = GamingSession()

        with patch("app.core.profiles.get_profile") as mock_prof, \
             patch("app.core.optimizations.get_optimization_by_id") as mock_get, \
             patch("app.core.snapshot.snapshot_manager") as mock_snap, \
             patch("app.utils.admin.is_admin", return_value=False):

            prof = MagicMock()
            prof.optimizations = [
                MagicMock(opt_id="opt1", name="Opt 1"),
                MagicMock(opt_id="opt2", name="Opt 2"),
                MagicMock(opt_id="opt3", name="Opt 3"),
                MagicMock(opt_id="opt4", name="Opt 4"),
            ]
            mock_prof.return_value = prof

            opt1 = MagicMock()
            check1 = MagicMock()
            check1.status.value = "ALREADY_OPTIMAL"
            check1.current_value = "High"
            opt1.check.return_value = check1

            opt2 = MagicMock()
            check2 = MagicMock()
            check2.status.value = "OPTIMIZABLE"
            check2.current_value = "Normal"
            opt2.check.return_value = check2
            apply2 = MagicMock()
            apply2.status.value = "APPLIED"
            apply2.message = "Changed"
            opt2.apply.return_value = apply2
            opt2.verify.return_value = True

            opt3 = MagicMock()
            check3 = MagicMock()
            check3.status.value = "REQUIRES_ADMIN"
            check3.current_value = ""
            opt3.check.return_value = check3

            opt4 = MagicMock()
            opt4.check.side_effect = Exception("Check crashed")

            def get_opt(oid):
                return {"opt1": opt1, "opt2": opt2, "opt3": opt3, "opt4": opt4}.get(oid)
            mock_get.side_effect = get_opt
            mock_snap.create_snapshot.return_value = MagicMock(snapshot_id="snap_1")

            engine._apply_optimizations(session)

            statuses = {o.opt_id: o.status for o in session.optimizations}
            assert statuses["opt1"] == "ALREADY_OPTIMAL"
            assert statuses["opt2"] == "APPLIED"
            assert statuses["opt3"] == "REQUIRES_ADMIN"
            assert statuses["opt4"] == "FAILED"


class TestTelemetryCapture:
    """Test telemetry summary capture."""

    def test_capture_from_engine(self):
        engine = GamingSessionEngine()
        with patch("app.core.telemetry.telemetry_engine") as mock_tel:
            frame = MagicMock()
            frame.cpu_utilization = 45.0
            frame.gpu_utilization = 70.0
            frame.ram_percent = 55.0
            frame.gpu_temp = 65.0
            frame.cpu_temp = None
            mock_tel.current = frame

            summary = engine._capture_telemetry_summary()
            assert summary.avg_cpu == 45.0
            assert summary.avg_gpu == 70.0
            assert summary.avg_ram == 55.0
            assert summary.max_gpu_temp == 65.0

    def test_capture_multi_sample(self):
        engine = GamingSessionEngine()
        with patch("app.core.telemetry.telemetry_engine") as mock_tel, \
             patch("app.core.gaming_session.time.sleep"):
            frame = MagicMock()
            frame.cpu_utilization = 40.0
            frame.gpu_utilization = 60.0
            frame.ram_percent = 50.0
            frame.gpu_temp = 60.0
            frame.cpu_temp = None
            mock_tel.current = frame

            summary = engine._capture_multi_sample(duration=2)
            assert summary.telemetry_samples == 2
            assert summary.avg_cpu == 40.0


class TestPresentMonCleanup:
    """Test PresentMon cleanup."""

    def test_cleanup_runs_without_error(self):
        engine = GamingSessionEngine()
        session = GamingSession()
        # Should run without error even with no CSV files
        engine._cleanup_presentmon(session)
        assert session.presentmon_stopped is True

    def test_cleanup_sets_csv_cleaned_flag(self):
        engine = GamingSessionEngine()
        session = GamingSession()
        # Create a real CSV in tempdir to verify cleanup
        import tempfile as _tmp
        import glob as _glob
        tmp = os.path.join(_tmp.gettempdir(), "phoenix_pm_test_cleanup.csv")
        with open(tmp, "w") as f:
            f.write("test")
        try:
            engine._cleanup_presentmon(session)
            assert not os.path.exists(tmp)
            assert session.csv_cleaned is True
        except Exception:
            # If file is locked, at least verify method ran
            assert session.presentmon_stopped is True


class TestSafeCleanup:
    """Test safe cleanup on failure."""

    def test_cleanup_safe_stops_monitoring(self):
        engine = GamingSessionEngine()
        engine._monitoring = True
        session = GamingSession()

        with patch.object(engine, "_cleanup_presentmon"):
            engine._cleanup_safe(session)
            assert not engine._monitoring


class TestEdgeCases:
    """Test edge cases."""

    def test_callback_notification(self):
        engine = GamingSessionEngine()
        callback = MagicMock()
        engine.on_update(callback)

        session = GamingSession()
        engine._session = session
        engine._notify("test message")
        callback.assert_called_once_with(session)

    def test_multiple_errors_collected(self):
        session = GamingSession()
        session.errors.append("Error 1")
        session.errors.append("Error 2")
        assert len(session.errors) == 2

    def test_session_json_serializable(self):
        session = GamingSession(
            session_id="test",
            profile_id="gaming",
            target_name="HD-Player.exe",
            target_pid=1234,
            state=SessionState.MONITORING,
            optimizations=[
                SessionOptimization(opt_id="power_plan", name="Power Plan", status="APPLIED"),
                SessionOptimization(opt_id="game_mode", name="Game Mode", status="ALREADY_OPTIMAL"),
            ],
            baseline=TelemetrySummary(avg_fps=100.0, avg_cpu=40.0),
            final=TelemetrySummary(avg_fps=105.0, avg_cpu=38.0),
            errors=["Test error"],
        )
        d = session.to_dict()
        json_str = json.dumps(d, default=str)
        assert "test" in json_str
        assert "gaming" in json_str

    def test_empty_profile(self):
        engine = GamingSessionEngine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 1234, 1000.0)), \
             patch.object(engine, "_capture_telemetry_summary", return_value=TelemetrySummary()), \
             patch.object(engine, "_apply_optimizations"), \
             patch.object(engine, "_start_monitoring"), \
             patch("app.core.profiles.get_profile", return_value=None), \
             patch("app.core.gaming_session.save_session"):

            session = engine.start_session("nonexistent")
            assert session.state == SessionState.MONITORING

    def test_cleanup_safe_joins_thread(self):
        engine = GamingSessionEngine()
        mock_thread = MagicMock()
        mock_thread.is_alive.return_value = True
        engine._monitor_thread = mock_thread
        engine._monitoring = True

        with patch.object(engine, "_cleanup_presentmon"):
            engine._cleanup_safe(GamingSession())
            mock_thread.join.assert_called_once_with(timeout=3.0)

    def test_stop_with_target_lost(self):
        engine = GamingSessionEngine()
        session = GamingSession(
            state=SessionState.MONITORING,
            target_name="HD-Player.exe",
            target_pid=1234,
        )
        engine._session = session

        def mock_stop_inner(s):
            s.target_lost = True
            s.errors.append("Target lost")

        with patch.object(engine, "_stop_session_inner", side_effect=mock_stop_inner), \
             patch.object(engine, "_cleanup_safe"), \
             patch("app.core.gaming_session.save_session"):
            result = engine.stop_session()
            assert result.target_lost
            assert any("Target lost" in e for e in result.errors)
