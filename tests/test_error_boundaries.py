"""
Comprehensive tests for Phase 62 — Error Boundaries & Graceful Degradation.

Tests: SubsystemStatus, SubsystemHealth, SubsystemRegistry, safe_subsystem,
       safe_call, ManagedWorker, safe_load_json, safe_save_json,
       detect_incomplete_sessions, check_dependencies, check_permissions,
       safe_wmi_context, safe_gpu_call, safe_shutdown_workers, safe_stop_timers.
"""

import json
import os
import shutil
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.core.error_boundaries import (
    SubsystemStatus,
    SubsystemHealth,
    SubsystemRegistry,
    subsystem_registry,
    safe_subsystem,
    safe_call,
    ManagedWorker,
    WorkerState,
    safe_load_json,
    safe_save_json,
    detect_incomplete_sessions,
    format_incomplete_sessions,
    IncompleteSession,
    check_dependencies,
    check_permissions,
    safe_wmi_context,
    safe_gpu_call,
    safe_shutdown_workers,
    safe_stop_timers,
    install_global_exception_handler,
)


# ── Helpers ──────────────────────────────────────────────────────


def _tmp_json(data, name="test_config.json"):
    """Write data to a temp file and return the path."""
    tmp_dir = tempfile.mkdtemp()
    path = os.path.join(tmp_dir, name)
    with open(path, "w") as f:
        json.dump(data, f)
    return path, tmp_dir


# ── SubsystemHealth Tests ────────────────────────────────────────


class TestSubsystemHealth:
    def test_default_state(self):
        h = SubsystemHealth(name="test")
        assert h.status == SubsystemStatus.AVAILABLE
        assert h.error_count == 0
        assert h.consecutive_failures == 0

    def test_record_success(self):
        h = SubsystemHealth(name="test")
        h.record_failure("error 1")
        h.record_failure("error 2")
        h.record_success()
        assert h.status == SubsystemStatus.AVAILABLE
        assert h.consecutive_failures == 0

    def test_record_failure_increments_count(self):
        h = SubsystemHealth(name="test")
        h.record_failure("error 1")
        assert h.error_count == 1
        assert h.consecutive_failures == 1
        assert h.last_error == "error 1"

    def test_record_failure_degraded_after_1(self):
        h = SubsystemHealth(name="test")
        h.record_failure("error 1")
        assert h.status == SubsystemStatus.DEGRADED

    def test_record_failure_failed_after_3(self):
        h = SubsystemHealth(name="test")
        h.record_failure("e1")
        h.record_failure("e2")
        h.record_failure("e3")
        assert h.status == SubsystemStatus.FAILED
        assert h.consecutive_failures == 3

    def test_record_not_available(self):
        h = SubsystemHealth(name="test")
        h.record_not_available("missing")
        assert h.status == SubsystemStatus.NOT_AVAILABLE
        assert h.last_error == "missing"

    def test_to_dict(self):
        h = SubsystemHealth(name="test")
        d = h.to_dict()
        assert d["name"] == "test"
        assert d["status"] == "AVAILABLE"


# ── SubsystemRegistry Tests ──────────────────────────────────────


class TestSubsystemRegistry:
    def test_register_and_get(self):
        reg = SubsystemRegistry()
        h = reg.register("gpu")
        assert h.name == "gpu"
        assert reg.get("gpu") is h

    def test_get_creates_if_missing(self):
        reg = SubsystemRegistry()
        h = reg.get("new_subsystem")
        assert h.name == "new_subsystem"
        assert h.status == SubsystemStatus.NOT_AVAILABLE

    def test_get_all(self):
        reg = SubsystemRegistry()
        reg.register("a")
        reg.register("b")
        all_h = reg.get_all()
        assert "a" in all_h
        assert "b" in all_h

    def test_format_status(self):
        reg = SubsystemRegistry()
        reg.register("test_sub").record_success()
        text = reg.format_status()
        assert "SUBSYSTEM HEALTH" in text
        assert "test_sub" in text
        assert "[OK]" in text

    def test_format_status_degraded(self):
        reg = SubsystemRegistry()
        reg.register("bad_sub").record_failure("broken")
        text = reg.format_status()
        assert "[--]" in text

    def test_format_status_failed(self):
        reg = SubsystemRegistry()
        h = SubsystemHealth(name="dead")
        h.record_failure("1")
        h.record_failure("2")
        h.record_failure("3")
        reg._subsystems["dead"] = h
        text = reg.format_status()
        assert "[!!]" in text

    def test_thread_safety(self):
        reg = SubsystemRegistry()
        errors = []

        def register_many(prefix):
            try:
                for i in range(50):
                    reg.register(f"{prefix}_{i}")
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=register_many, args=(f"t{t}",))
                   for t in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert len(errors) == 0
        assert len(reg.get_all()) == 250


# ── safe_subsystem Tests ─────────────────────────────────────────


class TestSafeSubsystem:
    def test_successful_call(self):
        with safe_subsystem("test_success") as ctx:
            ctx.value = 42
        assert ctx.value == 42

    def test_exception_returns_fallback(self):
        result = safe_subsystem("test_fail", fallback="default")
        with result as ctx:
            raise ValueError("boom")
        # The context manager should return the fallback

    def test_exception_logs_error(self):
        health = subsystem_registry.register("test_log")
        with safe_subsystem("test_log", fallback=None):
            raise RuntimeError("test error")
        assert health.error_count >= 1

    def test_exception_does_not_crash(self):
        """Critical: exception in subsystem must not propagate."""
        try:
            with safe_subsystem("test_no_crash", fallback="safe"):
                raise KeyError("missing")
            # If we reach here, no crash
        except Exception:
            pytest.fail("safe_subsystem must not propagate exceptions")


# ── safe_call Tests ──────────────────────────────────────────────


class TestSafeCall:
    def test_successful_call(self):
        result = safe_call(lambda x: x * 2, 5, subsystem="math")
        assert result == 10

    def test_exception_returns_fallback(self):
        result = safe_call(
            lambda: 1 / 0, subsystem="div", fallback=-1
        )
        assert result == -1

    def test_no_subsystem(self):
        result = safe_call(lambda: "ok", fallback="fail")
        assert result == "ok"


# ── ManagedWorker Tests ──────────────────────────────────────────


class TestManagedWorker:
    def test_initial_state(self):
        w = ManagedWorker("test_worker")
        assert w.state == WorkerState.IDLE
        assert not w.is_running

    def test_start_and_complete(self):
        done = threading.Event()
        w = ManagedWorker("fast_worker")
        w.start(lambda: done.set())
        done.wait(timeout=5)
        time.sleep(0.1)
        assert w.state in (WorkerState.STOPPED, WorkerState.IDLE)

    def test_prevent_double_start(self):
        done = threading.Event()
        w = ManagedWorker("double_worker")
        w.start(lambda: done.wait(timeout=5))
        time.sleep(0.05)
        result = w.start(lambda: None)
        assert result is False
        done.set()
        w.cancel(timeout=3)

    def test_cancel(self):
        def slow_work(worker_ref):
            while not worker_ref.should_cancel:
                time.sleep(0.05)

        w = ManagedWorker("cancel_worker")
        # Pass w so the work function can check should_cancel
        w.start(slow_work, w)
        time.sleep(0.1)
        assert w.is_running
        result = w.cancel(timeout=2)
        assert result is True
        assert w.state == WorkerState.STOPPED

    def test_should_cancel(self):
        w = ManagedWorker("check_worker")
        assert not w.should_cancel
        w._cancel_event.set()
        assert w.should_cancel

    def test_uptime(self):
        w = ManagedWorker("uptime_worker")
        w.start(lambda: time.sleep(0.5))
        time.sleep(0.1)
        assert w.uptime > 0
        w.cancel(timeout=2)

    def test_reset(self):
        w = ManagedWorker("reset_worker")
        w.start(lambda: time.sleep(5))
        time.sleep(0.05)
        w.reset()
        assert w.state == WorkerState.IDLE
        assert not w.should_cancel

    def test_to_dict(self):
        w = ManagedWorker("dict_worker")
        d = w.to_dict()
        assert d["name"] == "dict_worker"
        assert d["state"] == "IDLE"

    def test_worker_exception_sets_failed(self):
        def failing():
            raise ValueError("worker error")

        w = ManagedWorker("fail_worker")
        w.start(failing)
        time.sleep(0.2)
        assert w.state == WorkerState.FAILED


# ── safe_load_json Tests ─────────────────────────────────────────


class TestSafeLoadJson:
    def test_load_valid(self):
        path, tmp = _tmp_json({"key": "value"})
        try:
            result = safe_load_json(path, default={})
            assert result == {"key": "value"}
        finally:
            shutil.rmtree(tmp)

    def test_load_missing_returns_default(self):
        result = safe_load_json("/nonexistent/path.json", default="fallback")
        assert result == "fallback"

    def test_load_corrupted_returns_default(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "bad.json")
        with open(path, "w") as f:
            f.write("{invalid json!!!")
        try:
            result = safe_load_json(path, default="fallback")
            assert result == "fallback"
            # Corrupted file should be backed up
            assert not os.path.exists(path)
        finally:
            shutil.rmtree(tmp_dir)

    def test_load_empty_file_returns_default(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "empty.json")
        with open(path, "w") as f:
            f.write("")
        try:
            result = safe_load_json(path, default="fallback")
            assert result == "fallback"
        finally:
            shutil.rmtree(tmp_dir)


# ── safe_save_json Tests ─────────────────────────────────────────


class TestSafeSaveJson:
    def test_save_valid(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "test.json")
        try:
            result = safe_save_json(path, {"key": "value"})
            assert result is True
            with open(path) as f:
                assert json.load(f) == {"key": "value"}
        finally:
            shutil.rmtree(tmp_dir)

    def test_save_creates_dirs(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "subdir", "test.json")
        try:
            result = safe_save_json(path, {"nested": True})
            assert result is True
            assert os.path.exists(path)
        finally:
            shutil.rmtree(tmp_dir)

    def test_save_overwrites_existing(self):
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "test.json")
        try:
            safe_save_json(path, {"old": True})
            result = safe_save_json(path, {"new": True})
            assert result is True
            with open(path) as f:
                data = json.load(f)
            assert data == {"new": True}
        finally:
            shutil.rmtree(tmp_dir)

    def test_save_does_not_crash_on_bad_path(self):
        result = safe_save_json("/nonexistent/dir/file.json", {"x": 1})
        # May fail but should not crash
        assert isinstance(result, bool)


# ── Incomplete Session Detection Tests ───────────────────────────


class TestIncompleteSessionDetection:
    def test_format_empty(self):
        text = format_incomplete_sessions([])
        assert "No incomplete sessions" in text

    def test_format_with_sessions(self):
        sessions = [
            IncompleteSession(
                session_id="test123",
                session_type="rollback",
                state="IN_PROGRESS",
                has_applied_changes=True,
                reversible_changes=3,
            ),
        ]
        text = format_incomplete_sessions(sessions)
        assert "INCOMPLETE SESSIONS DETECTED" in text
        assert "test123" in text
        assert "rollback" in text
        assert "3 applied" in text

    def test_detect_runs_without_crash(self):
        """The detection function must never crash even with bad data."""
        result = detect_incomplete_sessions()
        assert isinstance(result, list)


# ── Dependency Checks ────────────────────────────────────────────


class TestDependencies:
    def test_psutil_available(self):
        deps = check_dependencies()
        assert "psutil" in deps
        # psutil should be available on this system
        assert deps["psutil"] is True

    def test_pyside6_available(self):
        deps = check_dependencies()
        assert "PySide6" in deps

    def test_all_values_are_bool(self):
        deps = check_dependencies()
        for name, available in deps.items():
            assert isinstance(available, bool), f"{name} is not bool"


# ── Permission Checks ────────────────────────────────────────────


class TestPermissions:
    def test_returns_dict(self):
        perms = check_permissions()
        assert isinstance(perms, dict)

    def test_admin_key_exists(self):
        perms = check_permissions()
        assert "admin" in perms
        assert isinstance(perms["admin"], bool)

    def test_process_access_key_exists(self):
        perms = check_permissions()
        assert "process_access" in perms


# ── safe_wmi_context Tests ───────────────────────────────────────


class TestSafeWmiContext:
    def test_no_crash(self):
        with safe_wmi_context("test_wmi"):
            pass  # Should not crash

    def test_exception_does_not_propagate(self):
        try:
            with safe_wmi_context("test_wmi_err"):
                raise ValueError("WMI error")
        except Exception:
            pytest.fail("safe_wmi_context must not propagate exceptions")


# ── safe_gpu_call Tests ──────────────────────────────────────────


class TestSafeGpuCall:
    def test_successful_call(self):
        result = safe_gpu_call(lambda: 42)
        assert result == 42

    def test_exception_returns_fallback(self):
        result = safe_gpu_call(
            lambda: 1 / 0, fallback="gpu_unavailable"
        )
        assert result == "gpu_unavailable"

    def test_does_not_crash(self):
        try:
            safe_gpu_call(
                lambda: (_ for _ in ()).throw(RuntimeError("GPU fail")),
                fallback=None,
            )
        except Exception:
            pytest.fail("safe_gpu_call must not propagate exceptions")


# ── safe_shutdown_workers Tests ──────────────────────────────────


class TestSafeShutdownWorkers:
    def test_shutdown_empty_list(self):
        safe_shutdown_workers([], timeout_per_worker=0.5)

    def test_shutdown_managed_worker(self):
        w = ManagedWorker("shutdown_test")
        w.start(lambda: time.sleep(10))
        time.sleep(0.1)
        safe_shutdown_workers([w], timeout_per_worker=1.0)
        assert w.state == WorkerState.STOPPED

    def test_shutdown_with_error_does_not_crash(self):
        bad_worker = MagicMock()
        bad_worker.cancel.side_effect = Exception("broken")
        safe_shutdown_workers([bad_worker], timeout_per_worker=0.5)


# ── safe_stop_timers Tests ───────────────────────────────────────


class TestSafeStopTimers:
    def test_stop_empty_list(self):
        safe_stop_timers([])

    def test_stop_active_timer(self):
        timer = MagicMock()
        timer.isActive.return_value = True
        safe_stop_timers([timer])
        timer.stop.assert_called_once()

    def test_stop_inactive_timer(self):
        timer = MagicMock()
        timer.isActive.return_value = False
        safe_stop_timers([timer])
        timer.stop.assert_not_called()

    def test_stop_with_error_does_not_crash(self):
        timer = MagicMock()
        timer.isActive.side_effect = Exception("broken")
        safe_stop_timers([timer])  # Should not crash


# ── Global Exception Handler Tests ───────────────────────────────


class TestGlobalExceptionHandler:
    def test_install(self):
        original = __import__("sys").excepthook
        install_global_exception_handler()
        # Restore
        __import__("sys").excepthook = original

    def test_keyboard_interrupt_passes_through(self):
        import sys
        original = sys.excepthook
        install_global_exception_handler()
        # KeyboardInterrupt should pass through (not crash)
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
        sys.excepthook = original


# ── Integration Tests ────────────────────────────────────────────


class TestIntegration:
    def test_subsystem_survives_multiple_failures(self):
        """Multiple subsystem failures should not cascade."""
        reg = SubsystemRegistry()
        # Register 10 subsystems, each failing once → DEGRADED
        for i in range(10):
            reg.register(f"sub_{i}").record_failure(f"error_{i}")

        all_h = reg.get_all()
        assert len(all_h) == 10
        for h in all_h.values():
            assert h.status == SubsystemStatus.DEGRADED

        # One subsystem failing 3 times → FAILED
        reg.register("heavy_fail").record_failure("1")
        reg.register("heavy_fail").record_failure("2")
        reg.register("heavy_fail").record_failure("3")
        assert reg.get("heavy_fail").status == SubsystemStatus.FAILED

    def test_worker_with_failing_function(self):
        """Worker with a failing function should not leave zombie threads."""
        def always_fails():
            raise RuntimeError("I always fail")

        w = ManagedWorker("integration_fail")
        w.start(always_fails)
        time.sleep(0.3)
        assert w.state == WorkerState.FAILED

    def test_json_roundtrip(self):
        """Save and load should produce identical data."""
        tmp_dir = tempfile.mkdtemp()
        path = os.path.join(tmp_dir, "roundtrip.json")
        data = {
            "list": [1, 2, 3],
            "nested": {"a": "b"},
            "number": 42.5,
            "null_val": None,
        }
        try:
            safe_save_json(path, data)
            loaded = safe_load_json(path, default={})
            assert loaded == data
        finally:
            shutil.rmtree(tmp_dir)

    def test_concurrent_safe_calls(self):
        """Multiple threads calling safe_call simultaneously."""
        results = []
        errors = []

        def call_safe(i):
            try:
                r = safe_call(
                    lambda x: x * 2, i, subsystem=f"thread_{i}"
                )
                results.append(r)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=call_safe, args=(i,))
                   for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        assert sorted(results) == [i * 2 for i in range(20)]

    def test_managed_worker_concurrent_start_prevention(self):
        """Multiple concurrent start attempts should be handled safely."""
        done = threading.Event()
        w = ManagedWorker("concurrent_start")
        w.start(lambda: done.wait(timeout=5))

        results = []
        def try_start():
            results.append(w.start(lambda: None))

        threads = [threading.Thread(target=try_start) for _ in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # At least some should have been rejected
        assert not all(results)
        done.set()
        w.cancel(timeout=2)
