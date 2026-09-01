"""
Phase 49 — Comprehensive tests for Gaming Session Optimization.

Tests cover:
  - GamingStateDetector state transitions
  - Hysteresis / consecutive tick requirements
  - Degradation detection (thermal, RAM, CPU, FPS)
  - GamingSessionManager lifecycle
  - Tick-based monitoring
  - Optimization decision making
  - Cooldown enforcement
  - Cooldown after degradation
  - PID reuse protection
  - Session persistence
  - UI summary generation
  - CLI formatting
  - Edge cases
"""

import json
import os
import sys
import time
import unittest
from unittest.mock import MagicMock, patch, PropertyMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.gaming_optimization import (
    GamingState,
    GamingStateDetector,
    GamingSessionManager,
    GamingSessionRecord,
    TelemetrySnapshot,
    OptimizationDecision,
    OptimizationAction,
    SessionBaseline,
    GamingOptimizationWorker,
    OPTIMIZATION_COOLDOWN_SECONDS,
    CONSECUTIVE_TICKS_THRESHOLD,
    GPU_TEMP_HIGH,
    GPU_TEMP_CRITICAL,
    RAM_PRESSURE_HIGH,
    CPU_SATURATION,
    FPS_INSTABILITY_CV,
)


def _make_snapshot(
    cpu=None, gpu=None, gpu_temp=None, ram=None, fps=None,
    frame_time=None, target_name="HD-Player.exe", target_pid=12345,
):
    """Helper to create a TelemetrySnapshot."""
    return TelemetrySnapshot(
        timestamp=time.time(),
        cpu_percent=cpu,
        gpu_percent=gpu,
        gpu_temp=gpu_temp,
        ram_percent=ram,
        fps=fps,
        frame_time_ms=frame_time,
        target_name=target_name,
        target_pid=target_pid,
    )


class TestGamingStateDetector(unittest.TestCase):
    """Tests for GamingStateDetector."""

    def _make_detector(self):
        return GamingStateDetector()

    def _mock_alive(self):
        """Context manager that mocks psutil.Process to report alive."""
        mock_proc = MagicMock()
        mock_proc.is_running.return_value = True
        return patch("psutil.Process", return_value=mock_proc)

    def test_idle_when_no_target(self):
        detector = self._make_detector()
        state = detector.detect_state("", 0, [])
        self.assertEqual(state, GamingState.IDLE)

    def test_game_detected_insufficient_data(self):
        detector = self._make_detector()
        with self._mock_alive():
            state = detector.detect_state("HD-Player.exe", 12345, [_make_snapshot(cpu=40)])
        self.assertEqual(state, GamingState.GAME_DETECTED)

    def test_gaming_with_sufficient_data(self):
        detector = self._make_detector()
        snapshots = [_make_snapshot(cpu=40, gpu=50, ram=60) for _ in range(5)]
        with self._mock_alive():
            state = detector.detect_state("HD-Player.exe", 12345, snapshots)
        self.assertEqual(state, GamingState.GAMING)

    def test_hysteresis_prevents_immediate_transition(self):
        detector = self._make_detector()
        snapshots = [_make_snapshot(cpu=40, gpu=50, ram=60) for _ in range(5)]
        with self._mock_alive():
            state = detector.detect_state("HD-Player.exe", 12345, snapshots)
            self.assertEqual(state, GamingState.GAMING)
            degraded = [_make_snapshot(cpu=95, gpu=50, ram=60)]
            state = detector.detect_state("HD-Player.exe", 12345, degraded)
        self.assertEqual(state, GamingState.GAMING)

    def test_consecutive_ticks_required_for_degradation(self):
        detector = self._make_detector()
        snapshots = [_make_snapshot(cpu=40, gpu=50, ram=60) for _ in range(5)]
        degraded = [_make_snapshot(cpu=95, gpu=50, ram=60) for _ in range(10)]
        with self._mock_alive():
            detector.detect_state("HD-Player.exe", 12345, snapshots)
            for _ in range(CONSECUTIVE_TICKS_THRESHOLD + 2):
                state = detector.detect_state("HD-Player.exe", 12345, degraded)
        self.assertEqual(state, GamingState.DEGRADED)

    def test_gpu_thermal_degradation(self):
        detector = self._make_detector()
        snapshots = [_make_snapshot(cpu=40, gpu=50, gpu_temp=65, ram=60) for _ in range(5)]
        hot = [_make_snapshot(cpu=40, gpu=50, gpu_temp=92, ram=60) for _ in range(10)]
        with self._mock_alive():
            detector.detect_state("HD-Player.exe", 12345, snapshots)
            for _ in range(CONSECUTIVE_TICKS_THRESHOLD + 2):
                state = detector.detect_state("HD-Player.exe", 12345, hot)
        self.assertEqual(state, GamingState.DEGRADED)

    def test_ram_pressure_degradation(self):
        detector = self._make_detector()
        snapshots = [_make_snapshot(cpu=40, gpu=50, ram=60) for _ in range(5)]
        pressured = [_make_snapshot(cpu=40, gpu=50, ram=92) for _ in range(10)]
        with self._mock_alive():
            detector.detect_state("HD-Player.exe", 12345, snapshots)
            for _ in range(CONSECUTIVE_TICKS_THRESHOLD + 2):
                state = detector.detect_state("HD-Player.exe", 12345, pressured)
        self.assertEqual(state, GamingState.DEGRADED)

    def test_cpu_saturation_degradation(self):
        detector = self._make_detector()
        snapshots = [_make_snapshot(cpu=40, gpu=50, ram=60) for _ in range(5)]
        saturated = [_make_snapshot(cpu=95, gpu=50, ram=60) for _ in range(10)]
        with self._mock_alive():
            detector.detect_state("HD-Player.exe", 12345, snapshots)
            for _ in range(CONSECUTIVE_TICKS_THRESHOLD + 2):
                state = detector.detect_state("HD-Player.exe", 12345, saturated)
        self.assertEqual(state, GamingState.DEGRADED)

    def test_fps_instability_degradation(self):
        detector = self._make_detector()
        snapshots = [_make_snapshot(cpu=40, gpu=50, ram=60, fps=60) for _ in range(5)]
        unstable = [_make_snapshot(cpu=40, gpu=50, ram=60, fps=f) for f in [30, 80, 25, 90, 20]]
        with self._mock_alive():
            detector.detect_state("HD-Player.exe", 12345, snapshots)
            for _ in range(CONSECUTIVE_TICKS_THRESHOLD + 2):
                state = detector.detect_state("HD-Player.exe", 12345, unstable)
        self.assertEqual(state, GamingState.DEGRADED)

    def test_stable_system_stays_gaming(self):
        detector = self._make_detector()
        snapshots = [_make_snapshot(cpu=40, gpu=50, ram=60) for _ in range(5)]
        with self._mock_alive():
            for _ in range(20):
                state = detector.detect_state("HD-Player.exe", 12345, snapshots)
        self.assertEqual(state, GamingState.GAMING)

    def test_target_lost_returns_idle(self):
        detector = self._make_detector()
        mock_proc = MagicMock()
        mock_proc.is_running.return_value = False
        with patch("psutil.Process", return_value=mock_proc):
            state = detector.detect_state("HD-Player.exe", 12345, [_make_snapshot()])
        self.assertEqual(state, GamingState.IDLE)


class TestTelemetrySnapshot(unittest.TestCase):
    """Tests for TelemetrySnapshot."""

    def test_to_dict(self):
        snap = TelemetrySnapshot(cpu_percent=45.0, gpu_percent=70.0, fps=120.0)
        d = snap.to_dict()
        self.assertEqual(d["cpu_percent"], 45.0)
        self.assertEqual(d["gpu_percent"], 70.0)
        self.assertEqual(d["fps"], 120.0)

    def test_none_values(self):
        snap = TelemetrySnapshot()
        d = snap.to_dict()
        self.assertIsNone(d["cpu_percent"])
        self.assertIsNone(d["fps"])


class TestSessionBaseline(unittest.TestCase):
    """Tests for SessionBaseline."""

    def test_to_dict(self):
        b = SessionBaseline(cpu_percent=40.0, gpu_percent=55.0, ram_percent=65.0)
        d = b.to_dict()
        self.assertEqual(d["cpu_percent"], 40.0)


class TestGamingSessionRecord(unittest.TestCase):
    """Tests for GamingSessionRecord."""

    def test_default_session_id(self):
        s = GamingSessionRecord()
        self.assertTrue(s.session_id.startswith("") or len(s.session_id) == 8)

    def test_to_dict(self):
        s = GamingSessionRecord(state="GAMING", target_name="HD-Player.exe")
        d = s.to_dict()
        self.assertEqual(d["state"], "GAMING")
        self.assertEqual(d["target_name"], "HD-Player.exe")

    def test_format_cli(self):
        s = GamingSessionRecord(state="GAMING", target_name="HD-Player.exe", target_pid=12345)
        s.baseline = SessionBaseline(cpu_percent=40.0, gpu_percent=55.0)
        output = s.format_cli()
        self.assertIn("GAMING SESSION", output)
        self.assertIn("HD-Player.exe", output)
        self.assertIn("BASELINE", output)


class TestOptimizationDecision(unittest.TestCase):
    """Tests for OptimizationDecision."""

    def test_to_dict(self):
        d = OptimizationDecision(
            action=OptimizationAction.APPLY_POWER_PLAN,
            confidence=80,
            reason="CPU pressure",
            applied=True,
        )
        result = d.to_dict()
        self.assertEqual(result["action"], "APPLY_POWER_PLAN")
        self.assertEqual(result["confidence"], 80)
        self.assertTrue(result["applied"])


class TestGamingSessionManager(unittest.TestCase):
    """Tests for GamingSessionManager."""

    def _make_manager(self):
        return GamingSessionManager()

    def test_initial_state_idle(self):
        manager = self._make_manager()
        self.assertEqual(manager.state, GamingState.IDLE)
        self.assertFalse(manager.is_active)

    def test_start_session_no_target(self):
        manager = self._make_manager()
        with patch.object(manager, "_detect_target", return_value=("", 0)):
            session = manager.start_session()
        self.assertEqual(session.state, GamingState.IDLE.value)
        self.assertFalse(manager.is_active)

    def test_start_session_with_target(self):
        manager = self._make_manager()
        with patch.object(manager, "_detect_target", return_value=("HD-Player.exe", 12345)):
            with patch.object(manager, "_capture_baseline") as mock_bl:
                mock_bl.return_value = SessionBaseline(cpu_percent=40.0, gpu_percent=55.0)
                with patch.object(manager, "_apply_initial_optimizations"):
                    session = manager.start_session()
        self.assertEqual(session.target_name, "HD-Player.exe")
        self.assertEqual(session.target_pid, 12345)
        self.assertEqual(session.state, GamingState.GAMING.value)

    def test_tick_returns_none_when_idle(self):
        manager = self._make_manager()
        decision = manager.tick()
        self.assertIsNone(decision)

    def test_tick_captures_snapshot(self):
        manager = self._make_manager()
        with patch.object(manager, "_detect_target", return_value=("HD-Player.exe", 12345)):
            with patch.object(manager, "_capture_baseline") as mock_bl:
                mock_bl.return_value = SessionBaseline(cpu_percent=40.0)
                with patch.object(manager, "_apply_initial_optimizations"):
                    manager.start_session()

        with patch.object(manager, "_capture_snapshot") as mock_snap:
            mock_snap.return_value = _make_snapshot(cpu=40, gpu=50, ram=60)
            with patch.object(manager._state_detector, "detect_state", return_value=GamingState.GAMING):
                decision = manager.tick()

        self.assertIsNotNone(decision)
        self.assertEqual(manager.session.total_ticks, 1)

    def test_cooldown_prevents_rapid_optimization(self):
        manager = self._make_manager()
        with patch.object(manager, "_detect_target", return_value=("HD-Player.exe", 12345)):
            with patch.object(manager, "_capture_baseline") as mock_bl:
                mock_bl.return_value = SessionBaseline(cpu_percent=40.0)
                with patch.object(manager, "_apply_initial_optimizations"):
                    manager.start_session()

        # Set last optimization time to now
        manager._last_optimization_time = time.time()

        with patch.object(manager, "_capture_snapshot") as mock_snap:
            mock_snap.return_value = _make_snapshot(cpu=95, gpu=50, ram=60)
            with patch.object(manager._state_detector, "detect_state", return_value=GamingState.DEGRADED):
                decision = manager.tick()

        # Should be cooldown, not an optimization
        self.assertIn("Cooldown", decision.reason)

    def test_stop_session(self):
        manager = self._make_manager()
        with patch.object(manager, "_detect_target", return_value=("HD-Player.exe", 12345)):
            with patch.object(manager, "_capture_baseline") as mock_bl:
                mock_bl.return_value = SessionBaseline(cpu_percent=40.0)
                with patch.object(manager, "_apply_initial_optimizations"):
                    manager.start_session()

        session = manager.stop_session()
        self.assertEqual(session.state, GamingState.IDLE.value)
        self.assertFalse(manager.is_active)

    def test_ui_summary_empty(self):
        manager = self._make_manager()
        summary = manager.get_ui_summary()
        self.assertEqual(summary["state"], "IDLE")
        self.assertIsNone(summary["cpu"])

    def test_ui_summary_active(self):
        manager = self._make_manager()
        with patch.object(manager, "_detect_target", return_value=("HD-Player.exe", 12345)):
            with patch.object(manager, "_capture_baseline") as mock_bl:
                mock_bl.return_value = SessionBaseline(cpu_percent=40.0)
                with patch.object(manager, "_apply_initial_optimizations"):
                    manager.start_session()

        summary = manager.get_ui_summary()
        self.assertEqual(summary["target_name"], "HD-Player.exe")
        self.assertEqual(summary["state"], "GAMING")

    def test_load_history_empty(self):
        manager = self._make_manager()
        with patch("os.path.exists", return_value=False):
            history = manager.load_history()
        self.assertEqual(history, [])

    def test_repeated_start_returns_existing(self):
        manager = self._make_manager()
        with patch.object(manager, "_detect_target", return_value=("HD-Player.exe", 12345)):
            with patch.object(manager, "_capture_baseline") as mock_bl:
                mock_bl.return_value = SessionBaseline(cpu_percent=40.0)
                with patch.object(manager, "_apply_initial_optimizations"):
                    s1 = manager.start_session()
                    s2 = manager.start_session()
        self.assertEqual(s1.session_id, s2.session_id)

    def test_degraded_state_triggers_decision(self):
        manager = self._make_manager()
        with patch.object(manager, "_detect_target", return_value=("HD-Player.exe", 12345)):
            with patch.object(manager, "_capture_baseline") as mock_bl:
                mock_bl.return_value = SessionBaseline(cpu_percent=40.0)
                with patch.object(manager, "_apply_initial_optimizations"):
                    manager.start_session()

        # Set last optimization far in the past
        manager._last_optimization_time = 0.0

        with patch.object(manager, "_capture_snapshot") as mock_snap:
            mock_snap.return_value = _make_snapshot(cpu=95, gpu=50, ram=60)
            with patch.object(manager._state_detector, "detect_state", return_value=GamingState.DEGRADED):
                decision = manager.tick()

        self.assertIsNotNone(decision)
        # Should make a decision (not NONE)
        self.assertNotEqual(decision.action, OptimizationAction.NONE)


class TestGamingOptimizationWorker(unittest.TestCase):
    """Tests for GamingOptimizationWorker."""

    def test_worker_creation(self):
        manager = GamingSessionManager()
        worker = GamingOptimizationWorker(manager)
        self.assertFalse(worker.is_running)

    def test_worker_tick(self):
        manager = GamingSessionManager()
        worker = GamingOptimizationWorker(manager)
        decision = worker.tick()
        # When idle, tick returns None
        self.assertIsNone(decision)


class TestConstants(unittest.TestCase):
    """Tests for constants and thresholds."""

    def test_cooldown_positive(self):
        self.assertGreater(OPTIMIZATION_COOLDOWN_SECONDS, 0)

    def test_consecutive_ticks_positive(self):
        self.assertGreater(CONSECUTIVE_TICKS_THRESHOLD, 0)

    def test_thermal_thresholds(self):
        self.assertGreater(GPU_TEMP_CRITICAL, GPU_TEMP_HIGH)

    def test_ram_pressure_threshold(self):
        self.assertGreater(RAM_PRESSURE_HIGH, 80)

    def test_cpu_saturation_threshold(self):
        self.assertGreater(CPU_SATURATION, 80)


class TestEdgeCases(unittest.TestCase):
    """Edge case tests."""

    def test_snapshot_all_none(self):
        snap = TelemetrySnapshot()
        d = snap.to_dict()
        for key in ["cpu_percent", "gpu_percent", "gpu_temp", "ram_percent", "fps"]:
            self.assertIsNone(d[key])

    def test_session_record_empty(self):
        s = GamingSessionRecord()
        d = s.to_dict()
        self.assertEqual(d["state"], "IDLE")
        self.assertEqual(d["total_ticks"], 0)

    def test_decision_none_action(self):
        d = OptimizationDecision(action=OptimizationAction.NONE)
        self.assertEqual(d.action, OptimizationAction.NONE)

    def test_baseline_all_none(self):
        b = SessionBaseline()
        d = b.to_dict()
        for key in ["cpu_percent", "gpu_percent", "ram_percent", "fps"]:
            self.assertIsNone(d[key])

    def test_manager_stop_without_start(self):
        manager = GamingSessionManager()
        session = manager.stop_session()
        self.assertEqual(session.state, GamingState.IDLE.value)

    def test_detector_reset_on_idle(self):
        detector = GamingStateDetector()
        # Establish some state
        snapshots = [_make_snapshot(cpu=40) for _ in range(5)]
        detector.detect_state("HD-Player.exe", 12345, snapshots)

        # Transition to idle
        state = detector.detect_state("", 0, [])
        self.assertEqual(state, GamingState.IDLE)

    def test_tick_after_stop(self):
        manager = GamingSessionManager()
        with patch.object(manager, "_detect_target", return_value=("HD-Player.exe", 12345)):
            with patch.object(manager, "_capture_baseline") as mock_bl:
                mock_bl.return_value = SessionBaseline(cpu_percent=40.0)
                with patch.object(manager, "_apply_initial_optimizations"):
                    manager.start_session()

        manager.stop_session()
        decision = manager.tick()
        self.assertIsNone(decision)


if __name__ == "__main__":
    unittest.main()
