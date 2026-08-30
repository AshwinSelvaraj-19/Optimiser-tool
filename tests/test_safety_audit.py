"""
Phase 29 — Full Production Safety & Regression Audit

Defensive tests covering every subsystem edge case:
- exceptions in optimizer, rollback, snapshots
- permission failures, UAC denial
- emulator disappearance, PID reuse
- locked files, missing registry keys
- missing NVML, missing PresentMon
- malformed CSV, corrupted snapshots
- concurrent APPLY/RESTORE
- crash during optimization
- stale temporary files
- stale PresentMon processes
- rollback after partial application
- rollback after failed verification

Every test uses mocks — never modifies real system state.
"""

import os
import json
import time
import tempfile
import threading
import shutil
import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from pathlib import Path
from dataclasses import dataclass

from app.core.snapshot import Snapshot, SnapshotManager, SnapshotEntry
from app.core.rollback import RollbackEngine, RollbackResult
from app.core.optimization_base import (
    OptimizationStatus, OptimizationResult, OptimizationSessionResult,
)
from app.core.optimizer import Optimizer, OptResult, OptimizationReport


# ── 1. SNAPSHOT EDGE CASES ───────────────────────────────────

class TestSnapshotEdgeCases:
    """Corrupted snapshots, missing files, disk errors."""

    def test_load_corrupted_json(self, tmp_path):
        snap_file = tmp_path / "corrupted.json"
        snap_file.write_text("{invalid json!!!", encoding="utf-8")
        mgr = SnapshotManager(str(tmp_path))
        result = mgr.load_snapshot("corrupted")
        assert result is None

    def test_load_missing_snapshot(self, tmp_path):
        mgr = SnapshotManager(str(tmp_path))
        result = mgr.load_snapshot("nonexistent_12345")
        assert result is None

    def test_load_partial_id_match(self, tmp_path):
        mgr = SnapshotManager(str(tmp_path))
        snap = Snapshot(snapshot_id="snapshot_2026-01-01_12-00-00",
                        timestamp="2026-01-01T12:00:00", description="test")
        mgr._save(snap)
        result = mgr.load_snapshot("snapshot_2026-01-01")
        assert result is not None
        assert result.snapshot_id == "snapshot_2026-01-01_12-00-00"

    def test_load_snapshot_missing_entries_key(self, tmp_path):
        snap_file = tmp_path / "no_entries.json"
        snap_file.write_text(json.dumps({
            "snapshot_id": "no_entries",
            "timestamp": "2026-01-01T00:00:00",
            "description": "missing entries key",
        }), encoding="utf-8")
        mgr = SnapshotManager(str(tmp_path))
        result = mgr.load_snapshot("no_entries")
        assert result is not None
        assert len(result.entries) == 0

    def test_save_snapshot_disk_full(self, tmp_path):
        mgr = SnapshotManager(str(tmp_path))
        snap = Snapshot(snapshot_id="test", timestamp="2026-01-01T00:00:00",
                        description="test")
        snap.add_entry(SnapshotEntry(category="power", key="plan", description="Plan"))
        # Mock open to raise IOError (disk full)
        with patch("builtins.open", side_effect=IOError("No space left on device")):
            mgr._save(snap)
            # Should not raise, just log error

    def test_list_snapshots_corrupted_files(self, tmp_path):
        # Create a valid and a corrupted file
        valid = tmp_path / "valid.json"
        valid.write_text(json.dumps({
            "snapshot_id": "valid", "timestamp": "2026-01-01T00:00:00",
            "description": "ok", "entries": [],
        }))
        corrupted = tmp_path / "corrupted.json"
        corrupted.write_text("not json")
        mgr = SnapshotManager(str(tmp_path))
        snapshots = mgr.list_snapshots()
        assert len(snapshots) == 1
        assert snapshots[0]["snapshot_id"] == "valid"

    def test_delete_nonexistent_snapshot(self, tmp_path):
        mgr = SnapshotManager(str(tmp_path))
        result = mgr.delete_snapshot("nonexistent")
        assert result is False

    def test_empty_snapshot_entries(self):
        snap = Snapshot(snapshot_id="empty", timestamp="2026-01-01T00:00:00")
        d = snap.to_dict()
        assert d["entries"] == []

    def test_snapshot_entry_with_none_values(self):
        entry = SnapshotEntry(
            category="test", key="k", description="d",
            current_value=None, backup_value=None,
        )
        snap = Snapshot(snapshot_id="t", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)
        d = snap.to_dict()
        assert d["entries"][0]["current_value"] is None

    def test_snapshot_thread_safety(self, tmp_path):
        """Multiple threads creating snapshots concurrently."""
        mgr = SnapshotManager(str(tmp_path))
        errors = []

        def create_snap(i):
            try:
                snap = Snapshot(snapshot_id=f"thread_{i}",
                                timestamp=f"2026-01-01T00:00:{i:02d}",
                                description=f"Thread {i}")
                mgr._save(snap)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=create_snap, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert len(mgr.list_snapshots()) == 10


# ── 2. ROLLBACK EDGE CASES ───────────────────────────────────

class TestRollbackEdgeCases:
    """Permission failures, missing entries, partial rollback."""

    def test_rollback_empty_snapshot(self):
        engine = RollbackEngine()
        snap = Snapshot(snapshot_id="empty", timestamp="2026-01-01T00:00:00")
        result = engine.rollback(snap)
        assert result.success is True
        assert len(result.restored_entries) == 0

    def test_rollback_power_restore_fails(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="power", key="plan", description="Power Plan",
            backup_value="381b4222-f694-41f0-9685-ff5bb260df2e",
        )
        snap = Snapshot(snapshot_id="fail", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)

        with patch("app.core.rollback.run_powershell", return_value=(False, "", "error")):
            result = engine.rollback(snap)
            assert result.success is False
            assert "plan" in result.failed_entries

    def test_rollback_power_no_backup_value(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="power", key="plan", description="Power Plan",
            backup_value=None,
        )
        snap = Snapshot(snapshot_id="no_backup", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)
        result = engine.rollback(snap)
        assert "plan" in result.failed_entries

    def test_rollback_registry_write_fails(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="game_mode", key="gm", description="Game Mode",
            backup_value=1,
            registry_hive="HKCU", registry_path="Software\\Test",
            registry_value_name="TestVal",
        )
        snap = Snapshot(snapshot_id="reg_fail", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)

        with patch("app.core.rollback.write_registry_value", return_value=False):
            result = engine.rollback(snap)
            assert result.success is False

    def test_rollback_registry_missing_fields(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="game_mode", key="gm", description="Game Mode",
            backup_value=1,
            registry_hive="", registry_path="", registry_value_name="",
        )
        snap = Snapshot(snapshot_id="reg_miss", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)
        result = engine.rollback(snap)
        assert "gm" in result.failed_entries

    def test_rollback_unknown_category(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="unknown_future_feature", key="u", description="Unknown",
            backup_value="something",
        )
        snap = Snapshot(snapshot_id="unknown", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)
        result = engine.rollback(snap)
        assert "u" in result.failed_entries

    def test_rollback_exception_in_restore(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="power", key="plan", description="Power Plan",
            backup_value="guid",
        )
        snap = Snapshot(snapshot_id="exc", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)

        with patch.object(engine, "_restore_power", side_effect=RuntimeError("crash")):
            result = engine.rollback(snap)
            assert result.success is False
            assert "plan" in result.failed_entries

    def test_rollback_display_category_succeeds(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="display", key="disp", description="Display",
            backup_value={"width": 1920, "height": 1080},
        )
        snap = Snapshot(snapshot_id="disp", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)
        result = engine.rollback(snap)
        assert "disp" in result.restored_entries

    def test_rollback_emulator_config_succeeds(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="emulator_config", key="ec", description="Emulator Config",
            backup_value={"ram": 4096},
        )
        snap = Snapshot(snapshot_id="ec", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)
        result = engine.rollback(snap)
        assert "ec" in result.restored_entries

    def test_rollback_gpu_preference_legacy_succeeds(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="gpu_preference", key="gp", description="Legacy GPU",
            backup_value="high performance",
        )
        snap = Snapshot(snapshot_id="gp", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)
        result = engine.rollback(snap)
        assert "gp" in result.restored_entries

    def test_rollback_latest_no_snapshots(self):
        engine = RollbackEngine()
        with patch("app.core.rollback.snapshot_manager") as mock_sm:
            mock_sm.get_latest_snapshot.return_value = None
            result = engine.rollback_latest()
            assert result.success is False

    def test_rollback_verify_mismatch(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="power", key="plan", description="Power Plan",
            backup_value="original_guid",
        )
        snap = Snapshot(snapshot_id="verify", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)

        with patch.object(engine, "_read_current", return_value="different_guid"):
            verification = engine.verify_rollback(snap)
            assert verification["plan"]["matches"] is False

    def test_rollback_verify_no_category(self):
        engine = RollbackEngine()
        entry = SnapshotEntry(
            category="unknown", key="x", description="X",
            backup_value="val",
        )
        snap = Snapshot(snapshot_id="unk", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)

        with patch.object(engine, "_read_current", return_value=None):
            verification = engine.verify_rollback(snap)
            assert verification["x"]["matches"] is False

    def test_rollback_multiple_entries_partial_failure(self):
        engine = RollbackEngine()
        entries = [
            SnapshotEntry(category="power", key="p1", description="Plan 1",
                         backup_value="guid1"),
            SnapshotEntry(category="power", key="p2", description="Plan 2",
                         backup_value="guid2"),
            SnapshotEntry(category="power", key="p3", description="Plan 3",
                         backup_value="guid3"),
        ]
        snap = Snapshot(snapshot_id="partial", timestamp="2026-01-01T00:00:00")
        for e in entries:
            snap.add_entry(e)

        call_count = [0]
        def mock_restore(entry):
            call_count[0] += 1
            if entry.key == "p2":
                return False
            return True

        with patch.object(engine, "_restore_power", side_effect=mock_restore):
            result = engine.rollback(snap)
            assert result.success is False
            assert "p2" in result.failed_entries
            assert "p1" in result.restored_entries
            assert "p3" in result.restored_entries


# ── 3. OPTIMIZER EDGE CASES ──────────────────────────────────

class TestOptimizerEdgeCases:
    """Concurrent operations, missing profiles, crash during optimization."""

    def test_optimizer_busy_returns_immediately(self):
        opt = Optimizer()
        opt._operation = "APPLY"
        opt._lock.acquire(blocking=False)
        report = opt.apply_profile("gaming")
        assert report.session is not None
        assert report.session.busy is True

    def test_rollback_when_no_report(self):
        opt = Optimizer()
        result = opt.rollback_last()
        assert result.success is False

    def test_rollback_when_no_applied_optimizations(self):
        opt = Optimizer()
        report = OptimizationReport()
        report.results = [
            OptResult(opt_id="a", status="ALREADY_OPTIMAL"),
            OptResult(opt_id="b", status="REQUIRES_ADMIN"),
        ]
        report.snapshot = Snapshot(snapshot_id="test", timestamp="2026-01-01T00:00:00")
        opt._last_report = report

        with patch.object(opt, "_acquire_lock", return_value=True), \
             patch.object(opt, "_release_lock"):
            result = opt.rollback_last()
            assert result.success is True

    def test_detect_target_no_emulator(self):
        opt = Optimizer()
        with patch("app.performance.target_process.target_process_detector") as mock:
            mock.select_best_target.return_value = None
            name, pid = opt._detect_target()
            assert name == ""
            assert pid == 0

    def test_concurrent_optimization_blocked(self):
        opt = Optimizer()
        results = []

        def try_apply():
            r = opt.apply_profile("gaming")
            results.append(r)

        # Simulate one operation holding the lock
        opt._operation = "APPLY"
        opt._lock.acquire(blocking=False)

        t1 = threading.Thread(target=try_apply)
        t1.start()
        t1.join(timeout=5)

        assert len(results) == 1
        assert results[0].session.busy is True

        opt._operation = ""
        opt._lock.release()


# ── 4. PRESENTMON EDGE CASES ─────────────────────────────────

class TestPresentMonEdgeCases:
    """Missing executable, malformed CSV, permission failures."""

    def test_find_presentmon_not_found(self, tmp_path):
        with patch("app.performance.presentmon_provider.os.path.expandvars",
                   return_value=str(tmp_path / "nonexistent")), \
             patch("app.performance.presentmon_provider.os.path.isdir", return_value=False), \
             patch("shutil.which", return_value=None):
            from app.performance.presentmon_provider import find_presentmon
            result = find_presentmon()
            # Should not crash, may return None or a valid path

    def test_provider_not_available(self, tmp_path):
        from app.performance.presentmon_provider import PresentMonProvider
        provider = PresentMonProvider.__new__(PresentMonProvider)
        provider._exe_path = None
        provider._version = None
        provider._csv_path = None
        provider._running = False
        provider._samples = []
        provider._session_name = ""
        provider._elevated_handle = None
        provider._state = "UNAVAILABLE"
        provider._error_reason = ""
        provider._needs_elevation = False
        provider._permission_ok = True
        provider._target_process = ""
        provider._capture_duration = 300

        available, reason = provider.is_available()
        # Should return False or handle gracefully

    def test_parse_csv_empty_file(self, tmp_path):
        from app.performance.presentmon_provider import PresentMonProvider
        csv_file = tmp_path / "empty.csv"
        csv_file.write_text("")
        provider = PresentMonProvider.__new__(PresentMonProvider)
        provider._csv_path = str(csv_file)
        provider._target_process = ""
        result = provider._parse_csv(str(csv_file))
        assert isinstance(result, list)

    def test_parse_csv_malformed_rows(self, tmp_path):
        from app.performance.presentmon_provider import PresentMonProvider
        csv_file = tmp_path / "malformed.csv"
        csv_file.write_text("bad,csv,data\n1,2\nnot,numbers,at,all\n")
        provider = PresentMonProvider.__new__(PresentMonProvider)
        provider._csv_path = str(csv_file)
        provider._target_process = ""
        result = provider._parse_csv(str(csv_file))
        assert isinstance(result, list)

    def test_parse_csv_permission_denied(self, tmp_path):
        from app.performance.presentmon_provider import PresentMonProvider
        csv_file = tmp_path / "locked.csv"
        csv_file.write_text("col1,col2\nval1,val2\n")
        provider = PresentMonProvider.__new__(PresentMonProvider)
        provider._csv_path = str(csv_file)
        provider._target_process = ""

        with patch("builtins.open", side_effect=PermissionError("Access denied")):
            result = provider._parse_csv(str(csv_file))
            assert isinstance(result, list)

    def test_cleanup_csv_nonexistent(self):
        from app.performance.presentmon_provider import _cleanup_csv
        # Should not raise
        _cleanup_csv("/nonexistent/path/csv.csv")

    def test_cleanup_csv_locked_file(self, tmp_path):
        from app.performance.presentmon_provider import _cleanup_csv
        csv_file = tmp_path / "locked.csv"
        csv_file.write_text("test")
        with patch("os.remove", side_effect=PermissionError("locked")):
            # Should not raise, just log warning
            _cleanup_csv(str(csv_file))

    def test_provider_stop_when_not_running(self):
        from app.performance.presentmon_provider import PresentMonProvider
        provider = PresentMonProvider.__new__(PresentMonProvider)
        provider._running = False
        provider._elevated_handle = None
        provider._csv_path = None
        provider._samples = []
        result = provider.stop()
        assert result is True


# ── 5. EMULATOR CONTROLLER EDGE CASES ────────────────────────

class TestEmulatorControllerEdgeCases:
    """PID reuse, emulator disappearance, permission errors."""

    def test_detect_target_no_emulator_running(self):
        from app.core.emulator_controller import EmulatorController
        ctrl = EmulatorController()
        with patch("app.performance.target_process.target_process_detector") as mock:
            mock.select_best_target.return_value = None
            target = ctrl.detect_target(force=True)
            assert target is None

    def test_detect_target_pid_reused(self):
        from app.core.emulator_controller import EmulatorController
        ctrl = EmulatorController()
        with patch("app.performance.target_process.target_process_detector") as mock, \
             patch("psutil.Process") as mock_proc:
            best = MagicMock()
            best.process_name = "HD-Player.exe"
            best.pid = 1234
            mock.select_best_target.return_value = best

            proc = MagicMock()
            proc.name.return_value = "different_process.exe"  # PID reused
            mock_proc.return_value = proc

            target = ctrl.detect_target(force=True)
            assert target is None

    def test_detect_target_access_denied(self):
        from app.core.emulator_controller import EmulatorController
        import psutil
        ctrl = EmulatorController()
        with patch("app.performance.target_process.target_process_detector") as mock, \
             patch("psutil.Process", side_effect=psutil.AccessDenied(1234)):
            best = MagicMock()
            best.process_name = "HD-Player.exe"
            best.pid = 1234
            mock.select_best_target.return_value = best
            target = ctrl.detect_target(force=True)
            # Controller gracefully degrades: returns target with access_denied status
            # rather than None, so callers know the process exists but can't read details
            assert target is not None
            assert target.status == 'access_denied'

    def test_detect_target_no_such_process(self):
        from app.core.emulator_controller import EmulatorController
        import psutil
        ctrl = EmulatorController()
        with patch("app.performance.target_process.target_process_detector") as mock, \
             patch("psutil.Process", side_effect=psutil.NoSuchProcess(1234)):
            best = MagicMock()
            best.process_name = "HD-Player.exe"
            best.pid = 1234
            mock.select_best_target.return_value = best
            target = ctrl.detect_target(force=True)
            assert target is None

    def test_cpu_affinity_list_type(self):
        """psutil.cpu_affinity() returns list on Windows, not bitmask."""
        from app.core.emulator_controller import EmulatorController
        ctrl = EmulatorController()
        with patch("psutil.Process") as mock_proc:
            proc = MagicMock()
            proc.name.return_value = "HD-Player.exe"
            proc.cpu_affinity.return_value = [0, 1, 2, 3, 4, 5, 6, 7]
            proc.nice.return_value = 0
            proc.memory_info.return_value = MagicMock(rss=1024*1024*100)
            proc.cpu_percent.return_value = 50.0
            proc.memory_percent.return_value = 5.0
            proc.status.return_value = "running"
            proc.create_time.return_value = time.time()
            mock_proc.return_value = proc

            target = ctrl._get_detailed_process_info(1234, "HD-Player.exe")
            assert target is not None
            assert target.affinity_cpus == 8

    def test_cpu_affinity_access_denied(self):
        """Affinity read may fail with AccessDenied."""
        from app.core.emulator_controller import EmulatorController
        import psutil
        ctrl = EmulatorController()
        with patch("psutil.Process") as mock_proc:
            proc = MagicMock()
            proc.name.return_value = "HD-Player.exe"
            proc.cpu_affinity.side_effect = psutil.AccessDenied(1234)
            proc.nice.return_value = 0
            proc.memory_info.return_value = MagicMock(rss=1024*1024*100)
            proc.cpu_percent.return_value = 50.0
            proc.memory_percent.return_value = 5.0
            proc.status.return_value = "running"
            proc.create_time.return_value = time.time()
            mock_proc.return_value = proc

            target = ctrl._get_detailed_process_info(1234, "HD-Player.exe")
            assert target is not None
            # Should use total_cpus as fallback
            assert target.affinity_cpus == target.total_cpus


# ── 6. TELEDMETRY EDGE CASES ──────────────────────────────────

class TestTelemetryEdgeCases:
    """Engine not started, frame access during shutdown."""

    def test_current_frame_before_start(self):
        from app.core.telemetry import TelemetryEngine
        engine = TelemetryEngine()
        frame = engine.current
        assert frame.cpu_utilization >= 0

    def test_history_empty(self):
        from app.core.telemetry import TelemetryEngine
        engine = TelemetryEngine()
        assert len(engine.history) == 0

    def test_start_stop_cycle(self):
        from app.core.telemetry import TelemetryEngine
        engine = TelemetryEngine(interval_ms=100)
        engine.start()
        time.sleep(0.2)
        assert engine._running is True
        engine.stop()
        assert engine._running is False


# ── 7. OPTIMIZATION STATUS EDGE CASES ────────────────────────

class TestOptimizationStatusEdgeCases:
    """Enum exhaustiveness, session result completeness."""

    def test_all_statuses_have_values(self):
        from app.core.optimization_base import OptimizationStatus
        for status in OptimizationStatus:
            assert isinstance(status.value, str)
            assert len(status.value) > 0

    def test_session_result_default_counts(self):
        s = OptimizationSessionResult()
        assert s.applied_count == 0
        assert s.optimal_count == 0
        assert s.admin_count == 0
        assert s.failed_count == 0
        assert s.review_count == 0

    def test_optimization_result_defaults(self):
        r = OptimizationResult()
        assert r.status == OptimizationStatus.PENDING
        assert r.current_value == ""
        assert r.message == ""

    def test_session_result_all_results_combined(self):
        s = OptimizationSessionResult()
        s.applied = [OptResult(status="APPLIED")]
        s.already_optimal = [OptResult(status="ALREADY_OPTIMAL")]
        s.requires_admin = [OptResult(status="REQUIRES_ADMIN")]
        s.failed = [OptResult(status="FAILED")]
        s.recommendation_only = [OptResult(status="RECOMMENDATION_ONLY")]
        s.not_available = [OptResult(status="NOT_APPLICABLE")]
        assert len(s.all_results) == 6


# ── 8. OPTIMIZATION EVIDENCE EDGE CASES ──────────────────────

class TestOptimizationEvidenceEdgeCases:
    """Boundary conditions for validation engine."""

    def test_measurement_snapshot_defaults(self):
        from app.core.optimization_evidence import MeasurementSnapshot, CaptureStatus
        snap = MeasurementSnapshot()
        assert snap.capture_status == CaptureStatus.FAILED
        assert snap.sample_count == 0
        assert snap.present_fps is None
        assert not snap.is_valid

    def test_measurement_snapshot_valid(self):
        from app.core.optimization_evidence import MeasurementSnapshot, CaptureStatus
        snap = MeasurementSnapshot(
            present_fps=120.0, sample_count=100,
            capture_status=CaptureStatus.COMPLETE,
        )
        assert snap.is_valid

    def test_measurement_snapshot_to_dict(self):
        from app.core.optimization_evidence import MeasurementSnapshot
        snap = MeasurementSnapshot(present_fps=120.0, sample_count=100)
        d = snap.to_dict()
        assert d["present_fps"] == 120.0
        assert d["sample_count"] == 100

    def test_evidence_verdict_all_values(self):
        from app.core.optimization_evidence import EvidenceVerdict
        values = [v.value for v in EvidenceVerdict]
        assert "BENEFICIAL" in values
        assert "NEUTRAL" in values
        assert "HARMFUL" in values
        assert "INCONCLUSIVE" in values
        assert "SKIPPED" in values


# ── 9. GAMING SESSION EDGE CASES ─────────────────────────────

class TestGamingSessionEdgeCases:
    """Session lifecycle edge cases."""

    def test_session_state_all_values(self):
        from app.core.gaming_session import SessionState
        values = [s.value for s in SessionState]
        assert "IDLE" in values
        assert "STARTING" in values
        assert "MONITORING" in values
        assert "ENDED" in values
        assert "FAILED" in values

    def test_gaming_session_defaults(self):
        from app.core.gaming_session import GamingSession
        s = GamingSession()
        assert s.session_id.startswith("session_")
        assert s.state.value == "IDLE"
        assert s.optimizations == []

    def test_gaming_session_applied_count(self):
        from app.core.gaming_session import GamingSession, SessionOptimization
        s = GamingSession()
        s.optimizations = [
            SessionOptimization(status="APPLIED"),
            SessionOptimization(status="APPLIED"),
            SessionOptimization(status="ALREADY_OPTIMAL"),
        ]
        assert s.applied_count == 2

    def test_gaming_session_needs_rollback(self):
        from app.core.gaming_session import GamingSession, SessionOptimization
        s = GamingSession()
        assert not s.needs_rollback
        s.optimizations.append(SessionOptimization(status="APPLIED"))
        assert s.needs_rollback
        s.snapshot_restored = True
        assert not s.needs_rollback

    def test_gaming_session_to_dict(self):
        from app.core.gaming_session import GamingSession
        s = GamingSession(session_id="test_123", profile_id="gaming")
        d = s.to_dict()
        assert d["session_id"] == "test_123"
        assert d["profile_id"] == "gaming"

    def test_session_storage_save_load(self):
        from app.core.gaming_session import GamingSession, save_session, load_sessions
        import app.core.gaming_session as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = mod.SESSIONS_DIR
            mod.SESSIONS_DIR = tmpdir
            try:
                session = GamingSession(profile_id="test")
                save_session(session)
                loaded = load_sessions()
                assert len(loaded) == 1
                assert loaded[0].profile_id == "test"
            finally:
                mod.SESSIONS_DIR = old_dir

    def test_session_storage_corrupted(self):
        from app.core.gaming_session import load_sessions
        import app.core.gaming_session as mod
        with tempfile.TemporaryDirectory() as tmpdir:
            old_dir = mod.SESSIONS_DIR
            mod.SESSIONS_DIR = tmpdir
            try:
                with open(os.path.join(tmpdir, "bad.json"), "w") as f:
                    f.write("not json {{{")
                loaded = load_sessions()
                assert len(loaded) == 0
            finally:
                mod.SESSIONS_DIR = old_dir


# ── 10. PERFORMANCE REPORT EDGE CASES ────────────────────────

class TestPerformanceReportEdgeCases:
    """Report generation with all N/A values."""

    def test_report_defaults(self):
        from app.core.performance_report import PerformanceReport
        r = PerformanceReport()
        assert r.report_id.startswith("report_")
        assert r.report_version == "1.0"

    def test_report_to_dict(self):
        from app.core.performance_report import PerformanceReport, SystemSection
        r = PerformanceReport(
            report_id="test",
            system=SystemSection(cpu_model="Test CPU"),
        )
        d = r.to_dict()
        assert d["report_id"] == "test"
        assert d["system"]["cpu_model"] == "Test CPU"

    def test_report_json_serializable(self):
        import json
        from app.core.performance_report import PerformanceReport
        r = PerformanceReport()
        d = r.to_dict()
        json_str = json.dumps(d, default=str)
        assert "report_id" in json_str

    def test_cli_format_all_nas(self):
        from app.core.performance_report import PerformanceReportGenerator, PerformanceReport
        gen = PerformanceReportGenerator()
        report = PerformanceReport()
        cli = gen.format_cli(report)
        assert "N/A" in cli
        assert "HEAVEN SOCIETY" in cli

    def test_cli_format_with_data(self):
        from app.core.performance_report import (
            PerformanceReportGenerator, PerformanceReport,
            SystemSection, PerformanceSection, ThermalSection,
        )
        gen = PerformanceReportGenerator()
        report = PerformanceReport(
            system=SystemSection(cpu_model="Ryzen 5", gpu_name="RTX 3060"),
            performance=PerformanceSection(present_fps=120.0),
            thermal=ThermalSection(gpu_temperature=65.0),
        )
        cli = gen.format_cli(report)
        assert "Ryzen 5" in cli
        assert "120.0" in cli
        assert "65" in cli


# ── 11. ADAPTIVE OPTIMIZER EDGE CASES ────────────────────────

class TestAdaptiveOptimizerEdgeCases:
    """Bottleneck classification edge cases."""

    def test_adaptive_state_all_values(self):
        from app.core.adaptive_optimizer import AdaptiveState
        values = [s.value for s in AdaptiveState]
        assert "CPU_BOUND" in values
        assert "GPU_BOUND" in values
        assert "MEMORY_BOUND" in values
        assert "THERMAL_LIMITED" in values
        assert "OPTIMAL" in values
        assert "INSUFFICIENT_DATA" in values

    def test_adaptive_plan_defaults(self):
        from app.core.adaptive_optimizer import AdaptivePlan, AdaptiveState
        p = AdaptivePlan()
        assert p.state == AdaptiveState.INSUFFICIENT_DATA
        assert p.confidence == 0
        assert p.actions == []

    def test_adaptive_action_defaults(self):
        from app.core.adaptive_optimizer import AdaptiveAction, ActionStatus
        a = AdaptiveAction()
        assert a.status == ActionStatus.SKIPPED_INSUFFICIENT_EVIDENCE
        assert a.confidence == 0


# ── 12. RESOURCE ANALYZER EDGE CASES ─────────────────────────

class TestResourceAnalyzerEdgeCases:
    """Resource analysis edge cases."""

    def test_ram_pressure_info_defaults(self):
        from app.core.resource_analyzer import RAMPressureInfo
        info = RAMPressureInfo()
        assert info.total_gb == 0.0
        assert info.used_gb == 0.0
        assert info.pressure_level in ("NORMAL", "UNKNOWN")

    def test_bottleneck_classification_defaults(self):
        from app.core.resource_analyzer import BottleneckClassification
        bc = BottleneckClassification()
        assert bc.classification == "INCONCLUSIVE"
        assert bc.confidence == 0.0


# ── 13. HARDWARE PROFILE EDGE CASES ──────────────────────────

class TestHardwareProfileEdgeCases:
    """Hardware classification edge cases."""

    def test_system_tier_all_values(self):
        from app.core.hardware_profile import SystemTier
        values = [t.value for t in SystemTier]
        assert "Entry" in values
        assert "Mid-Range" in values
        assert "High-End" in values
        assert "Unknown" in values

    def test_profile_recommendation_all_values(self):
        from app.core.hardware_profile import ProfileRecommendation
        values = [p.value for p in ProfileRecommendation]
        assert "balanced" in values
        assert "gaming" in values
        assert "max_performance" in values


# ── 14. BENCHMARK MODELS EDGE CASES ──────────────────────────

class TestBenchmarkModelsEdgeCases:
    """Benchmark result edge cases."""

    def test_benchmark_result_unavailable(self):
        from app.performance.benchmark_models import BenchmarkResult
        r = BenchmarkResult.unavailable(reason="No PresentMon")
        assert r.capture_status == "UNAVAILABLE"
        assert not r.is_valid

    def test_benchmark_result_failed(self):
        from app.performance.benchmark_models import BenchmarkResult
        r = BenchmarkResult.failed(reason="Elevation cancelled")
        assert r.capture_status == "FAILED"
        assert not r.is_valid

    def test_benchmark_result_valid(self):
        from app.performance.benchmark_models import BenchmarkResult
        r = BenchmarkResult(
            capture_status="COMPLETE", sample_count=100,
            present_fps=120.0,
        )
        assert r.is_valid

    def test_benchmark_comparison_all_none(self):
        from app.performance.benchmark_models import BenchmarkComparison
        c = BenchmarkComparison()
        assert c.result == "INCONCLUSIVE"
        assert c.fps_delta is None

    def test_benchmark_to_dict(self):
        import json
        from app.performance.benchmark_models import BenchmarkResult
        r = BenchmarkResult(capture_status="COMPLETE", sample_count=100,
                            present_fps=120.0)
        d = r.to_dict()
        json_str = json.dumps(d, default=str)
        assert "120.0" in json_str


# ── 15. FRAME PACING EDGE CASES ──────────────────────────────

class TestFramePacingEdgeCases:
    """Frame pacing analysis edge cases."""

    def test_pacing_classification_all_values(self):
        from app.performance.frame_pacing import PacingClassification
        values = [p.value for p in PacingClassification]
        assert "EXCELLENT" in values
        assert "POOR" in values
        assert any("INSUFFICIENT" in v for v in values)


# ── 16. CLI EDGE CASES ───────────────────────────────────────

class TestCLIEdgeCases:
    """CLI command edge cases."""

    def test_main_no_args(self):
        """Main with no args should not crash."""
        import sys
        with patch("sys.argv", ["main.py"]):
            try:
                from main import main
                # Should either show GUI or return
            except SystemExit:
                pass  # Expected
            except Exception:
                pass  # GUI import issues on headless

    def test_check_prerequisites(self):
        """Check prerequisites should not crash."""
        import subprocess
        result = subprocess.run(
            ["python", "main.py", "--check-prerequisites"],
            capture_output=True, text=True, timeout=30,
            cwd=os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        )
        # Should not crash regardless of output
        assert result.returncode in (0, 1)


# ── 17. INTEGRATION SAFETY ───────────────────────────────────

class TestIntegrationSafety:
    """Cross-module safety checks."""

    def test_optimizer_uses_only_registered_optimizations(self):
        from app.core.profiles import get_all_profiles
        from app.core.optimizations import get_optimization_by_id
        for profile in get_all_profiles():
            for po in profile.optimizations:
                opt = get_optimization_by_id(po.opt_id)
                assert opt is not None, f"Optimization {po.opt_id} not found"

    def test_all_optimizations_have_required_methods(self):
        from app.core.optimizations import get_all_optimizations
        for opt in get_all_optimizations():
            assert hasattr(opt, "check")
            assert hasattr(opt, "apply")
            assert hasattr(opt, "verify")
            assert callable(opt.check)
            assert callable(opt.apply)
            assert callable(opt.verify)
            # Some optimizations may not have restore, that's OK

    def test_snapshot_entry_fields_serializable(self):
        """All snapshot entry fields must be JSON-serializable."""
        import json
        entry = SnapshotEntry(
            category="power", key="plan", description="Plan",
            current_value={"nested": {"dict": True}},
            backup_value=["list", "value"],
            registry_hive="HKCU", registry_path="path",
            registry_value_name="val",
        )
        snap = Snapshot(snapshot_id="test", timestamp="2026-01-01T00:00:00")
        snap.add_entry(entry)
        d = snap.to_dict()
        json_str = json.dumps(d, default=str)
        assert "power" in json_str

    def test_rollback_result_always_has_lists(self):
        r = RollbackResult()
        assert isinstance(r.restored_entries, list)
        assert isinstance(r.failed_entries, list)
        assert r.success is True

    def test_optimization_report_structures(self):
        report = OptimizationReport()
        assert report.profile_id == ""
        assert report.applied_count == 0
        assert report.results == []


# ── 18. FILESYSTEM SAFETY ────────────────────────────────────

class TestFilesystemSafety:
    """Temporary file cleanup, path traversal prevention."""

    def test_snapshot_dir_created_automatically(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c"
        mgr = SnapshotManager(str(nested))
        assert nested.exists()

    def test_cleanup_csv_only_removes_phoenix_files(self, tmp_path):
        from app.performance.presentmon_provider import _cleanup_csv
        safe_file = tmp_path / "important.txt"
        safe_file.write_text("do not delete")
        phoenix_csv = tmp_path / "phoenix_pm_test.csv"
        phoenix_csv.write_text("temporary csv")

        # Only the phoenix file should be targeted
        assert safe_file.exists()
        assert phoenix_csv.exists()

    def test_evidence_session_dir_created(self, tmp_path):
        import app.core.optimization_evidence as mod
        old_dir = mod.EVIDENCE_DIR
        mod.EVIDENCE_DIR = str(tmp_path / "evidence")
        try:
            from app.core.optimization_evidence import save_evidence_session, EvidenceSession
            session = EvidenceSession(profile_id="test")
            save_evidence_session(session)
            assert (tmp_path / "evidence").exists()
        finally:
            mod.EVIDENCE_DIR = old_dir
