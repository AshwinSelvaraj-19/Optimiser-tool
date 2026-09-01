"""
Phase 48 — Comprehensive tests for the centralized OptimizationEngine.

Tests cover:
  - Engine lifecycle (idle, busy, completion)
  - Baseline capture
  - Safety gates
  - Dry run mode
  - Single optimization execution
  - Impact evaluation (degradation detection)
  - Auto-rollback on degradation
  - Profile filtering
  - Target validation / PID reuse
  - Admin required handling
  - Recommendation-only blocking
  - Already optimal detection
  - Session persistence
  - History loading
  - UI summary generation
  - CLI formatting
  - Thread safety
  - Edge cases
"""

import json
import os
import sys
import threading
import time
import unittest
from dataclasses import dataclass
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


# ── Test Helpers ─────────────────────────────────────────────

@dataclass
class MockCheckResult:
    status: object = None
    current_value: str = ""


class MockOptimization:
    """Minimal mock of the Optimization base class."""

    def __init__(self, opt_id="test_opt", name="Test Optimization",
                 status_value="OPTIMIZABLE", risk_level="LOW", category="SYSTEM"):
        self.id = opt_id
        self.name = name
        self.risk_level = risk_level
        self.category = category
        self.description = f"Test optimization {opt_id}"
        self._status_value = status_value
        self.apply_called = False
        self.verify_result = True
        self.rollback_result = True

    def check(self):
        from app.core.optimization_base import OptimizationStatus
        status_map = {
            "OPTIMIZABLE": OptimizationStatus.OPTIMIZABLE,
            "ALREADY_OPTIMAL": OptimizationStatus.ALREADY_OPTIMAL,
            "REQUIRES_ADMIN": OptimizationStatus.REQUIRES_ADMIN,
            "RECOMMENDATION_ONLY": OptimizationStatus.RECOMMENDATION_ONLY,
            "NOT_APPLICABLE": OptimizationStatus.NOT_APPLICABLE,
            "NOT_AVAILABLE": OptimizationStatus.NOT_AVAILABLE,
        }
        return MockCheckResult(
            status=status_map.get(self._status_value, OptimizationStatus.OPTIMIZABLE),
            current_value=f"Current state: {self._status_value}",
        )

    def snapshot(self):
        return {"backup": "value"}

    def apply(self):
        self.apply_called = True
        from app.core.optimization_base import OptimizationResult, OptimizationStatus
        if self._status_value == "OPTIMIZABLE":
            return OptimizationResult(status=OptimizationStatus.APPLIED, message="Applied")
        return OptimizationResult(
            status=status_map.get(self._status_value, OptimizationStatus.FAILED),
            message=f"Status: {self._status_value}",
        )

    def verify(self):
        return self.verify_result

    def rollback(self):
        return self.rollback_result


@dataclass
class MockTarget:
    process_name: str = "HD-Player.exe"
    pid: int = 12345
    start_time: float = 1000.0


@dataclass
class MockGPUInfo:
    utilization: float = 50.0
    temperature: float = 65.0


# ── Import the engine ──────────────────────────────────────────
from app.core.optimization_engine import (
    OptimizationEngine,
    OptimizationRunResult,
    OptimizationAction,
    SystemBaseline,
    EnginePhase,
    EngineVerdict,
    OptActionVerdict,
    EngineStatus,
)


class TestOptimizationEngine(unittest.TestCase):
    """Comprehensive tests for the OptimizationEngine."""

    def _make_engine(self):
        return OptimizationEngine()

    # ══════════════════════════════════════════════════════════
    # 1. ENGINE LIFECYCLE
    # ══════════════════════════════════════════════════════════

    def test_engine_initial_state(self):
        engine = self._make_engine()
        self.assertFalse(engine.is_busy)
        self.assertIsNone(engine.current_run)
        self.assertIsNone(engine.last_run)
        self.assertEqual(len(engine._history), 0)

    def test_engine_status_initial(self):
        engine = self._make_engine()
        status = engine.get_status()
        self.assertFalse(status.is_busy)
        self.assertEqual(status.current_phase, "IDLE")
        self.assertIsNone(status.last_run)

    def test_engine_is_busy_during_run(self):
        engine = self._make_engine()
        engine._current_run = OptimizationRunResult(phase=EnginePhase.EXECUTING)
        self.assertTrue(engine.is_busy)

    def test_engine_not_busy_after_completion(self):
        engine = self._make_engine()
        engine._current_run = OptimizationRunResult(phase=EnginePhase.COMPLETED)
        self.assertFalse(engine.is_busy)

    # ══════════════════════════════════════════════════════════
    # 2. TARGET DETECTION & VALIDATION
    # ══════════════════════════════════════════════════════════

    def test_detect_target_returns_empty_when_no_emulator(self):
        engine = self._make_engine()
        with patch("app.performance.target_process.target_process_detector") as mock_detector:
            mock_detector.select_best_target.return_value = None
            name, pid, start = engine._detect_target()
            self.assertEqual(name, "")
            self.assertEqual(pid, 0)

    def test_detect_target_returns_emulator(self):
        engine = self._make_engine()
        with patch("app.performance.target_process.target_process_detector") as mock_detector:
            mock_detector.select_best_target.return_value = MockTarget()
            name, pid, start = engine._detect_target()
            self.assertEqual(name, "HD-Player.exe")
            self.assertEqual(pid, 12345)

    def test_validate_target_rejects_pid_zero(self):
        engine = self._make_engine()
        valid, msg = engine._validate_target("test.exe", 0, 0.0)
        self.assertFalse(valid)
        self.assertIn("No emulator target", msg)

    def test_validate_target_rejects_wrong_process_name(self):
        engine = self._make_engine()
        with patch("psutil.Process") as MockProcess:
            mock_proc = MagicMock()
            mock_proc.name.return_value = "wrong.exe"
            MockProcess.return_value = mock_proc
            valid, msg = engine._validate_target("HD-Player.exe", 12345, 1000.0)
            self.assertFalse(valid)
            self.assertIn("wrong.exe", msg)

    def test_validate_target_accepts_valid(self):
        engine = self._make_engine()
        with patch("psutil.Process") as MockProcess:
            mock_proc = MagicMock()
            mock_proc.name.return_value = "HD-Player.exe"
            mock_proc.create_time.return_value = 1000.0
            MockProcess.return_value = mock_proc
            valid, msg = engine._validate_target("HD-Player.exe", 12345, 1000.0)
            self.assertTrue(valid)

    def test_validate_target_rejects_reused_pid(self):
        engine = self._make_engine()
        with patch("psutil.Process") as MockProcess:
            mock_proc = MagicMock()
            mock_proc.name.return_value = "HD-Player.exe"
            mock_proc.create_time.return_value = 5000.0  # Different start time
            MockProcess.return_value = mock_proc
            valid, msg = engine._validate_target("HD-Player.exe", 12345, 1000.0)
            self.assertFalse(valid)
            self.assertIn("reused", msg)

    # ══════════════════════════════════════════════════════════
    # 3. SAFETY GATES
    # ══════════════════════════════════════════════════════════

    def test_safety_gate_blocks_no_target(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=0)
        allowed, reason = engine._safety_gate("power_plan", run)
        self.assertFalse(allowed)

    def test_safety_gate_blocks_not_in_profile(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, profile_id="balanced")
        allowed, reason = engine._safety_gate("emulator_priority", run)
        self.assertFalse(allowed)
        self.assertIn("not in profile", reason.lower())

    def test_safety_gate_blocks_already_optimal(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, profile_id="gaming")
        mock_opt = MockOptimization(status_value="ALREADY_OPTIMAL")
        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            allowed, reason = engine._safety_gate("game_mode", run)
            self.assertFalse(allowed)
            self.assertIn("already optimal", reason.lower())

    def test_safety_gate_blocks_recommendation_only(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, profile_id="gaming")
        mock_opt = MockOptimization(status_value="RECOMMENDATION_ONLY")
        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            # memory_analysis is in gaming profile and can be RECOMMENDATION_ONLY
            allowed, reason = engine._safety_gate("memory_analysis", run)
            self.assertFalse(allowed)
            self.assertIn("recommendation", reason.lower())

    def test_safety_gate_blocks_admin_required_without_admin(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, profile_id="gaming", is_admin=False)
        mock_opt = MockOptimization(status_value="REQUIRES_ADMIN")
        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            allowed, reason = engine._safety_gate("emulator_priority", run)
            self.assertFalse(allowed)
            self.assertIn("administrator", reason.lower())

    def test_safety_gate_allows_admin_available(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, profile_id="gaming", is_admin=True)
        mock_opt = MockOptimization(status_value="REQUIRES_ADMIN")
        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            allowed, reason = engine._safety_gate("emulator_priority", run)
            self.assertTrue(allowed)

    def test_safety_gate_blocks_thermal_performance_increase(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, profile_id="gaming", is_admin=True)
        mock_opt = MockOptimization(status_value="OPTIMIZABLE")
        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            allowed, reason = engine._safety_gate("power_plan", run, thermal_state="THROTTLING")
            self.assertFalse(allowed)
            self.assertIn("thermal", reason.lower())

    def test_safety_gate_allows_optimizable(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, profile_id="gaming", is_admin=False)
        mock_opt = MockOptimization(status_value="OPTIMIZABLE")
        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            allowed, reason = engine._safety_gate("game_mode", run)
            self.assertTrue(allowed)

    # ══════════════════════════════════════════════════════════
    # 4. DRY RUN MODE
    # ══════════════════════════════════════════════════════════

    def test_dry_run_no_emulator(self):
        engine = self._make_engine()
        with patch.object(engine, "_detect_target", return_value=("", 0, 0.0)):
            result = engine.run(profile_id="gaming", mode="dry_run")
        self.assertEqual(result.mode, "dry_run")
        self.assertEqual(result.verdict, EngineVerdict.NO_EMULATOR)

    def test_dry_run_with_target(self):
        engine = self._make_engine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 12345, 1000.0)):
            with patch.object(engine, "_validate_target", return_value=(True, "OK")):
                with patch.object(engine, "_get_optimization_states", return_value={"game_mode": "OPTIMIZABLE"}):
                    with patch.object(engine, "capture_baseline") as mock_bl:
                        mock_bl.return_value = SystemBaseline(cpu_percent=45.0, ram_percent=60.0)
                        result = engine.run(profile_id="gaming", mode="dry_run")
        self.assertEqual(result.mode, "dry_run")
        self.assertIn("Dry run", result.verdict_reason)

    # ══════════════════════════════════════════════════════════
    # 5. NO EMULATOR HANDLING
    # ══════════════════════════════════════════════════════════

    def test_run_no_emulator(self):
        engine = self._make_engine()
        with patch.object(engine, "_detect_target", return_value=("", 0, 0.0)):
            result = engine.run(profile_id="gaming")
        self.assertEqual(result.verdict, EngineVerdict.NO_EMULATOR)

    def test_run_invalid_target(self):
        engine = self._make_engine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 12345, 1000.0)):
            with patch.object(engine, "_validate_target", return_value=(False, "PID reused")):
                result = engine.run(profile_id="gaming")
        self.assertEqual(result.verdict, EngineVerdict.NO_EMULATOR)

    # ══════════════════════════════════════════════════════════
    # 6. ALL OPTIMAL DETECTION
    # ══════════════════════════════════════════════════════════

    def test_run_all_optimal(self):
        engine = self._make_engine()
        states = {
            "game_mode": "ALREADY_OPTIMAL",
            "power_plan": "ALREADY_OPTIMAL",
            "emulator_priority": "ALREADY_OPTIMAL",
            "memory_analysis": "ALREADY_OPTIMAL",
        }
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 12345, 1000.0)):
            with patch.object(engine, "_validate_target", return_value=(True, "OK")):
                with patch.object(engine, "_get_optimization_states", return_value=states):
                    with patch.object(engine, "capture_baseline") as mock_bl:
                        mock_bl.return_value = SystemBaseline(cpu_percent=40.0, ram_percent=55.0)
                        result = engine.run(profile_id="gaming")
        self.assertEqual(result.verdict, EngineVerdict.ALL_OPTIMAL)

    # ══════════════════════════════════════════════════════════
    # 7. EXECUTION & VERIFICATION
    # ══════════════════════════════════════════════════════════

    def test_execute_single_optimization(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, target_name="HD-Player.exe", profile_id="gaming")
        mock_opt = MockOptimization("game_mode", "Game Mode", "OPTIMIZABLE")
        mock_opt.verify_result = True
        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            with patch.object(engine, "_quick_snapshot", return_value={"cpu_percent": 45.0}):
                action = engine._execute_single("game_mode", run)
        self.assertEqual(action.verdict, OptActionVerdict.APPLIED)
        self.assertTrue(action.verified)

    def test_execute_single_verification_failure_rollback(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, target_name="HD-Player.exe", profile_id="gaming")
        mock_opt = MockOptimization("game_mode", "Game Mode", "OPTIMIZABLE")
        mock_opt.verify_result = False
        mock_opt.rollback_result = True
        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            with patch.object(engine, "_quick_snapshot", return_value={"cpu_percent": 45.0}):
                action = engine._execute_single("game_mode", run)
        self.assertEqual(action.verdict, OptActionVerdict.ROLLED_BACK)
        self.assertIn("verification failed", action.reason.lower())

    def test_execute_single_degradation_auto_rollback(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, target_name="HD-Player.exe", profile_id="gaming")
        mock_opt = MockOptimization("game_mode", "Game Mode", "OPTIMIZABLE")
        mock_opt.verify_result = True
        mock_opt.rollback_result = True

        call_count = [0]
        def mock_snap(*a, **kw):
            call_count[0] += 1
            return {"gpu_temperature": 70.0} if call_count[0] == 1 else {"gpu_temperature": 80.0}

        with patch("app.core.optimizations.get_optimization_by_id", return_value=mock_opt):
            with patch.object(engine, "_quick_snapshot", side_effect=mock_snap):
                action = engine._execute_single("game_mode", run)
        self.assertEqual(action.verdict, OptActionVerdict.ROLLED_BACK)
        self.assertIn("temperature", action.reason.lower())

    def test_execute_single_not_found(self):
        engine = self._make_engine()
        run = OptimizationRunResult(target_pid=12345, profile_id="gaming")
        with patch("app.core.optimizations.get_optimization_by_id", return_value=None):
            action = engine._execute_single("nonexistent", run)
        self.assertEqual(action.verdict, OptActionVerdict.FAILED)

    # ══════════════════════════════════════════════════════════
    # 8. IMPACT EVALUATION
    # ══════════════════════════════════════════════════════════

    def test_impact_unchanged(self):
        engine = self._make_engine()
        verdict, _ = engine._evaluate_impact({"gpu_temperature": 70.0}, {"gpu_temperature": 71.0})
        self.assertEqual(verdict, "UNCHANGED")

    def test_impact_degraded_temperature(self):
        engine = self._make_engine()
        verdict, reason = engine._evaluate_impact({"gpu_temperature": 65.0}, {"gpu_temperature": 75.0})
        self.assertEqual(verdict, "DEGRADED")
        self.assertIn("temperature", reason.lower())

    def test_impact_unchanged_no_data(self):
        engine = self._make_engine()
        verdict, _ = engine._evaluate_impact({"cpu_percent": 45.0}, {"cpu_percent": 50.0})
        self.assertEqual(verdict, "UNCHANGED")

    def test_delta_calculation(self):
        engine = self._make_engine()
        pre = SystemBaseline(cpu_percent=40.0, ram_percent=60.0)
        post = SystemBaseline(cpu_percent=50.0, ram_percent=55.0)
        self.assertAlmostEqual(engine._delta(pre, post, "cpu_percent"), 10.0)
        self.assertAlmostEqual(engine._delta(pre, post, "ram_percent"), -5.0)

    def test_delta_none_values(self):
        engine = self._make_engine()
        pre = SystemBaseline(cpu_percent=None)
        post = SystemBaseline(cpu_percent=50.0)
        self.assertIsNone(engine._delta(pre, post, "cpu_percent"))

    # ══════════════════════════════════════════════════════════
    # 9. PLANNING
    # ══════════════════════════════════════════════════════════

    def test_plan_filters_already_optimal(self):
        engine = self._make_engine()
        run = OptimizationRunResult(profile_id="gaming", is_admin=False)
        states = {
            "game_mode": "ALREADY_OPTIMAL",
            "power_plan": "OPTIMIZABLE",
            "emulator_priority": "NOT_APPLICABLE",
            "memory_analysis": "RECOMMENDATION_ONLY",
        }
        planned = engine._plan(run, states)
        self.assertIn("power_plan", planned)
        self.assertNotIn("game_mode", planned)
        self.assertNotIn("emulator_priority", planned)
        self.assertNotIn("memory_analysis", planned)

    def test_plan_filters_admin_without_admin(self):
        engine = self._make_engine()
        run = OptimizationRunResult(profile_id="gaming", is_admin=False)
        states = {"emulator_priority": "REQUIRES_ADMIN", "game_mode": "OPTIMIZABLE"}
        planned = engine._plan(run, states)
        self.assertNotIn("emulator_priority", planned)

    # ══════════════════════════════════════════════════════════
    # 10. THREAD SAFETY
    # ══════════════════════════════════════════════════════════

    def test_concurrent_runs_rejected(self):
        engine = self._make_engine()
        engine._current_run = OptimizationRunResult(phase=EnginePhase.EXECUTING)
        result = engine.run(profile_id="gaming")
        self.assertEqual(result.verdict, EngineVerdict.CANCELLED)

    def test_lock_prevents_concurrent(self):
        engine = self._make_engine()
        engine._lock.acquire()
        result = engine.run(profile_id="gaming")
        self.assertEqual(result.verdict, EngineVerdict.CANCELLED)
        engine._lock.release()

    # ══════════════════════════════════════════════════════════
    # 11. PROGRESS CALLBACK
    # ══════════════════════════════════════════════════════════

    def test_progress_callback_called(self):
        engine = self._make_engine()
        calls = []
        engine.on_progress(lambda p, pct, m: calls.append((p, pct, m)))
        with patch.object(engine, "_detect_target", return_value=("", 0, 0.0)):
            engine.run(profile_id="gaming")
        self.assertGreater(len(calls), 0)

    def test_progress_callback_exception_safe(self):
        engine = self._make_engine()
        engine.on_progress(lambda p, pct, m: 1 / 0)
        with patch.object(engine, "_detect_target", return_value=("", 0, 0.0)):
            result = engine.run(profile_id="gaming")
        self.assertEqual(result.verdict, EngineVerdict.NO_EMULATOR)

    # ══════════════════════════════════════════════════════════
    # 12. HISTORY & PERSISTENCE
    # ══════════════════════════════════════════════════════════

    def test_run_added_to_history(self):
        engine = self._make_engine()
        with patch.object(engine, "_detect_target", return_value=("", 0, 0.0)):
            engine.run(profile_id="gaming")
        self.assertEqual(len(engine._history), 1)

    def test_load_history_empty(self):
        engine = self._make_engine()
        with patch("os.path.exists", return_value=False):
            history = engine.load_history()
        self.assertEqual(history, [])

    def test_status_history_count(self):
        engine = self._make_engine()
        engine._history = [MagicMock(), MagicMock()]
        status = engine.get_status()
        self.assertEqual(status.history_count, 2)

    # ══════════════════════════════════════════════════════════
    # 13. UI SUMMARY
    # ══════════════════════════════════════════════════════════

    def test_ui_summary_empty(self):
        engine = self._make_engine()
        summary = engine.get_ui_summary()
        self.assertEqual(summary["verdict"], "N/A")
        self.assertEqual(summary["actions"], [])

    def test_ui_summary_with_last_run(self):
        engine = self._make_engine()
        engine._last_run = OptimizationRunResult(
            verdict=EngineVerdict.UNCHANGED,
            bottleneck="CPU Limitation",
            bottleneck_confidence=80,
            adaptive_state="CPU_BOUND",
            actions=[OptimizationAction(name="Game Mode", verdict=OptActionVerdict.APPLIED)],
        )
        summary = engine.get_ui_summary()
        self.assertEqual(summary["verdict"], "UNCHANGED")
        self.assertEqual(summary["bottleneck"], "CPU Limitation")
        self.assertEqual(len(summary["actions"]), 1)

    # ══════════════════════════════════════════════════════════
    # 14. CLI FORMATTING
    # ══════════════════════════════════════════════════════════

    def test_format_cli_header(self):
        run = OptimizationRunResult(verdict=EngineVerdict.UNCHANGED)
        output = run.format_cli()
        self.assertIn("OPTIMIZATION ENGINE RUN", output)
        self.assertIn("VERDICT", output)

    def test_format_cli_actions(self):
        run = OptimizationRunResult(
            verdict=EngineVerdict.UNCHANGED,
            actions=[OptimizationAction(name="Game Mode", verdict=OptActionVerdict.APPLIED)],
        )
        output = run.format_cli()
        self.assertIn("Game Mode", output)

    def test_format_cli_no_emulator(self):
        run = OptimizationRunResult(verdict=EngineVerdict.NO_EMULATOR, verdict_reason="No emulator")
        output = run.format_cli()
        self.assertIn("NO_EMULATOR", output)

    # ══════════════════════════════════════════════════════════
    # 15. ROLLBACK
    # ══════════════════════════════════════════════════════════

    def test_rollback_no_run(self):
        engine = self._make_engine()
        result = engine.rollback_last()
        self.assertFalse(result["success"])

    def test_rollback_no_applied(self):
        engine = self._make_engine()
        engine._last_run = OptimizationRunResult(
            actions=[OptimizationAction(verdict=OptActionVerdict.ALREADY_OPTIMAL)]
        )
        result = engine.rollback_last()
        self.assertTrue(result["success"])

    def test_rollback_with_applied(self):
        engine = self._make_engine()
        engine._last_run = OptimizationRunResult(
            actions=[OptimizationAction(verdict=OptActionVerdict.APPLIED)]
        )
        mock_rb = MagicMock(success=True, message="Restored")
        with patch("app.core.optimizer.optimizer") as mock_opt:
            mock_opt.rollback_last.return_value = mock_rb
            result = engine.rollback_last()
        self.assertTrue(result["success"])
        self.assertEqual(engine._last_run.verdict, EngineVerdict.DEGRADED)

    # ══════════════════════════════════════════════════════════
    # 16. EDGE CASES & SERIALIZATION
    # ══════════════════════════════════════════════════════════

    def test_action_to_dict(self):
        action = OptimizationAction(
            action_id="t1", optimization_id="game_mode",
            name="Game Mode", verdict=OptActionVerdict.APPLIED,
        )
        d = action.to_dict()
        self.assertEqual(d["verdict"], "APPLIED")

    def test_baseline_to_dict(self):
        baseline = SystemBaseline(cpu_percent=45.0, target_name="test.exe")
        d = baseline.to_dict()
        self.assertEqual(d["cpu_percent"], 45.0)

    def test_engine_status_to_dict(self):
        status = EngineStatus(is_busy=True, current_phase="EXECUTING")
        d = status.to_dict()
        self.assertTrue(d["is_busy"])

    def test_delta_dict(self):
        self.assertEqual(OptimizationEngine._delta_dict({"a": 10.0}, {"a": 15.0}, "a"), 5.0)
        self.assertIsNone(OptimizationEngine._delta_dict({"a": 10.0}, {"a": 15.0}, "b"))

    def test_quick_snapshot(self):
        engine = self._make_engine()
        with patch("psutil.cpu_percent", return_value=45.0):
            with patch("psutil.virtual_memory") as mock_vm:
                mock_vm.return_value = MagicMock(used=8e9, percent=60.0)
                with patch("app.system.gpu.gpu_monitor") as mock_gpu:
                    mock_gpu.detect.return_value = MockGPUInfo(75.0, 68.0)
                    snap = engine._quick_snapshot(12345)
        self.assertEqual(snap["cpu_percent"], 45.0)
        self.assertEqual(snap["gpu_utilization"], 75.0)

    def test_run_exception_in_baseline(self):
        engine = self._make_engine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 12345, 1000.0)):
            with patch.object(engine, "_validate_target", return_value=(True, "OK")):
                with patch.object(engine, "capture_baseline", side_effect=Exception("err")):
                    result = engine.run(profile_id="gaming")
        self.assertIsNotNone(result)

    def test_run_exception_in_analysis(self):
        engine = self._make_engine()
        with patch.object(engine, "_detect_target", return_value=("HD-Player.exe", 12345, 1000.0)):
            with patch.object(engine, "_validate_target", return_value=(True, "OK")):
                with patch.object(engine, "capture_baseline", return_value=SystemBaseline(cpu_percent=40.0)):
                    with patch.object(engine, "_analyze", side_effect=Exception("err")):
                        result = engine.run(profile_id="gaming")
        self.assertIsNotNone(result)

    def test_max_actions_per_run(self):
        from app.core.optimization_engine import MAX_ACTIONS_PER_RUN
        self.assertLessEqual(MAX_ACTIONS_PER_RUN, 50)


if __name__ == "__main__":
    unittest.main()
