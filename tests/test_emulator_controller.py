"""
Tests for Heaven Society — Emulator Performance Controller.

Phase 13: Real emulator-focused optimization.
"""

import os
import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import dataclass

from app.core.emulator_controller import (
    EmulatorController,
    EmulatorTarget,
    MemoryPressureInfo,
    BackgroundProcessInfo,
    GPUTargetInfo,
    CpuAffinityOptimization,
    PROTECTED_PROCESSES,
    EMULATOR_PROCESS_NAMES,
)


# ── EmulatorTarget tests ───────────────────────────────────────

class TestEmulatorTarget:
    def test_default_values(self):
        t = EmulatorTarget()
        assert t.name == ""
        assert t.pid == 0
        assert t.priority == 0
        assert t.affinity_cpus == 0
        assert t.total_cpus == 0

    def test_is_high_priority(self):
        t = EmulatorTarget(priority=-1)
        assert t.is_high_priority is True

    def test_not_high_priority(self):
        t = EmulatorTarget(priority=0)
        assert t.is_high_priority is False

    def test_uses_all_cpus(self):
        t = EmulatorTarget(affinity_cpus=12, total_cpus=12)
        assert t.uses_all_cpus is True

    def test_not_all_cpus(self):
        t = EmulatorTarget(affinity_cpus=6, total_cpus=12)
        assert t.uses_all_cpus is False

    def test_priority_name_mapping(self):
        assert EmulatorController._priority_name(-4) == "REALTIME"
        assert EmulatorController._priority_name(-2) == "HIGH"
        assert EmulatorController._priority_name(-1) == "ABOVE NORMAL"
        assert EmulatorController._priority_name(0) == "NORMAL"
        assert EmulatorController._priority_name(1) == "BELOW NORMAL"
        assert EmulatorController._priority_name(4) == "LOW"


# ── EmulatorController tests ───────────────────────────────────

class TestEmulatorController:
    def test_detect_target_no_emulator(self):
        """Returns None when no emulator is running."""
        controller = EmulatorController()
        with patch("app.core.emulator_controller.EmulatorController._get_detailed_process_info", return_value=None):
            with patch("app.performance.target_process.target_process_detector.select_best_target", return_value=None):
                result = controller.detect_target()
                assert result is None

    def test_cache_behavior(self):
        """Target is cached for 2 seconds."""
        controller = EmulatorController()
        with patch.object(controller, "_get_detailed_process_info") as mock_info:
            mock_target = EmulatorTarget(name="HD-Player.exe", pid=1234)
            mock_info.return_value = mock_target

            with patch("app.performance.target_process.target_process_detector.select_best_target") as mock_best:
                mock_best.return_value = MagicMock(process_name="HD-Player.exe", pid=1234, emulator="BlueStacks", confidence=0.9, reason="test")

                # First call
                result1 = controller.detect_target()
                # Second call should use cache
                result2 = controller.detect_target()

                # _get_detailed_process_info should only be called once (cached)
                assert mock_info.call_count == 1

    def test_force_refresh(self):
        """Force flag bypasses cache."""
        controller = EmulatorController()
        with patch.object(controller, "_get_detailed_process_info") as mock_info:
            mock_info.return_value = EmulatorTarget(name="test", pid=1)

            with patch("app.performance.target_process.target_process_detector.select_best_target") as mock_best:
                mock_best.return_value = MagicMock(process_name="test", pid=1, emulator="test", confidence=0.5, reason="test")

                controller.detect_target()
                controller.detect_target(force=True)
                assert mock_info.call_count == 2

    def test_validate_target_pid_reuse(self):
        """PID reuse detection via start time."""
        controller = EmulatorController()
        target = EmulatorTarget(name="HD-Player.exe", pid=1234, create_time=1000.0)

        # Mock process with different start time (PID reuse)
        mock_proc = MagicMock()
        mock_proc.name.return_value = "HD-Player.exe"
        mock_proc.create_time.return_value = 2000.0  # Different start time

        with patch("psutil.Process", return_value=mock_proc):
            assert controller.validate_target(target) is False

    def test_validate_target_same_process(self):
        """Same process validates correctly."""
        controller = EmulatorController()
        target = EmulatorTarget(name="HD-Player.exe", pid=1234, create_time=1000.0)

        mock_proc = MagicMock()
        mock_proc.name.return_value = "HD-Player.exe"
        mock_proc.create_time.return_value = 1000.0  # Same start time

        with patch("psutil.Process", return_value=mock_proc):
            assert controller.validate_target(target) is True

    def test_validate_target_name_mismatch(self):
        """Name mismatch rejects validation."""
        controller = EmulatorController()
        target = EmulatorTarget(name="HD-Player.exe", pid=1234, create_time=1000.0)

        mock_proc = MagicMock()
        mock_proc.name.return_value = "OTHER.exe"
        mock_proc.create_time.return_value = 1000.0

        with patch("psutil.Process", return_value=mock_proc):
            assert controller.validate_target(target) is False

    def test_validate_target_process_gone(self):
        """Missing process fails validation."""
        import psutil
        controller = EmulatorController()
        target = EmulatorTarget(name="HD-Player.exe", pid=1234, create_time=1000.0)

        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(1234)):
            assert controller.validate_target(target) is False


# ── CPU Affinity tests ─────────────────────────────────────────

class TestCpuAffinity:
    def test_read_affinity_success(self):
        controller = EmulatorController()
        mock_proc = MagicMock()
        mock_proc.cpu_affinity.return_value = 0xFFF  # 12 CPUs

        with patch("psutil.Process", return_value=mock_proc):
            with patch("psutil.cpu_count", return_value=12):
                mask, count, total = controller.read_affinity(1234)
                assert mask == 0xFFF
                assert count == 12
                assert total == 12

    def test_read_affinity_access_denied(self):
        import psutil
        controller = EmulatorController()
        with patch("psutil.Process", side_effect=psutil.AccessDenied(1234)):
            mask, count, total = controller.read_affinity(1234)
            assert mask == 0
            assert count == 0

    def test_get_recommended_affinity_all_cpus(self):
        """No change recommended when already using all CPUs."""
        controller = EmulatorController()
        with patch.object(controller, "read_affinity", return_value=(0xFFF, 12, 12)):
            result = controller.get_recommended_affinity(1234)
            assert result is None

    def test_get_recommended_affinity_few_cpus(self):
        """Recommendation when using too few CPUs on a many-core system."""
        controller = EmulatorController()
        # 3 out of 12 CPUs — less than half
        with patch.object(controller, "read_affinity", return_value=(0x7, 3, 12)):
            result = controller.get_recommended_affinity(1234)
            assert result is not None
            # Should recommend first half (6 CPUs)
            assert bin(result).count("1") == 6

    def test_get_recommended_affinity_normal_usage(self):
        """No change when using reasonable number of CPUs."""
        controller = EmulatorController()
        # 8 out of 12 CPUs — more than half
        with patch.object(controller, "read_affinity", return_value=(0xFF, 8, 12)):
            result = controller.get_recommended_affinity(1234)
            assert result is None

    def test_apply_affinity_success(self):
        controller = EmulatorController()
        mock_proc = MagicMock()
        mock_proc.cpu_affinity.return_value = 0xFF

        with patch("psutil.Process", return_value=mock_proc):
            assert controller.apply_affinity(1234, 0xFF) is True

    def test_apply_affinity_failure(self):
        import psutil
        controller = EmulatorController()
        with patch("psutil.Process", side_effect=psutil.AccessDenied(1234)):
            assert controller.apply_affinity(1234, 0xFF) is False


# ── Priority tests ─────────────────────────────────────────────

class TestPriority:
    def test_read_priority_success(self):
        controller = EmulatorController()
        mock_proc = MagicMock()
        mock_proc.nice.return_value = -1

        with patch("psutil.Process", return_value=mock_proc):
            nice, name = controller.read_priority(1234)
            assert nice == -1
            assert name == "ABOVE NORMAL"

    def test_read_priority_access_denied(self):
        import psutil
        controller = EmulatorController()
        with patch("psutil.Process", side_effect=psutil.AccessDenied(1234)):
            nice, name = controller.read_priority(1234)
            assert nice == 0
            assert name == "UNKNOWN"

    def test_apply_priority_success(self):
        controller = EmulatorController()
        mock_proc = MagicMock()
        mock_proc.nice.return_value = -1

        with patch("psutil.Process", return_value=mock_proc):
            assert controller.apply_priority(1234, -1) is True

    def test_restore_priority(self):
        controller = EmulatorController()
        with patch.object(controller, "apply_priority", return_value=True) as mock_apply:
            assert controller.restore_priority(1234, 0) is True
            mock_apply.assert_called_once_with(1234, 0)


# ── Memory Pressure tests ──────────────────────────────────────

class TestMemoryPressure:
    def test_analyze_memory_pressure(self):
        controller = EmulatorController()
        mock_vm = MagicMock()
        mock_vm.total = 16 * 1024 ** 3
        mock_vm.used = 8 * 1024 ** 3
        mock_vm.available = 8 * 1024 ** 3
        mock_vm.percent = 50.0

        mock_swap = MagicMock()
        mock_swap.percent = 10.0

        with patch("psutil.virtual_memory", return_value=mock_vm):
            with patch("psutil.swap_memory", return_value=mock_swap):
                with patch("psutil.process_iter", return_value=iter([])):
                    info = controller.analyze_memory_pressure()
                    assert info.total_gb == 16.0
                    assert info.percent_used == 50.0
                    assert info.pressure_level == "NORMAL"

    def test_critical_pressure(self):
        controller = EmulatorController()
        mock_vm = MagicMock()
        mock_vm.total = 16 * 1024 ** 3
        mock_vm.used = 15 * 1024 ** 3
        mock_vm.available = 1 * 1024 ** 3
        mock_vm.percent = 93.0

        mock_swap = MagicMock()
        mock_swap.percent = 50.0

        with patch("psutil.virtual_memory", return_value=mock_vm):
            with patch("psutil.swap_memory", return_value=mock_swap):
                with patch("psutil.process_iter", return_value=iter([])):
                    info = controller.analyze_memory_pressure()
                    assert info.pressure_level == "CRITICAL"
                    assert "critically low" in info.recommendation.lower()


# ── Background Process tests ───────────────────────────────────

class TestBackgroundProcesses:
    def test_analyze_background_processes(self):
        controller = EmulatorController()

        # Create mock processes
        mock_procs = []
        for name, cpu, mem_mb in [
            ("discord.exe", 5.0, 200),
            ("explorer.exe", 1.0, 80),  # Protected
            ("HD-Player.exe", 50.0, 1000),  # Emulator
            ("chrome.exe", 2.0, 300),  # Safe to recommend
            ("msmpeng.exe", 3.0, 100),  # Security
        ]:
            m = MagicMock()
            m.info = {"name": name, "pid": 100 + hash(name) % 1000}
            m.info["cpu_percent"] = cpu
            mem_mock = MagicMock()
            mem_mock.rss = mem_mb * 1024 * 1024
            m.info["memory_info"] = mem_mock
            mock_procs.append(m)

        with patch("psutil.process_iter", return_value=iter(mock_procs)):
            results = controller.analyze_background_processes()

            # Should not include protected/emulator processes
            names = [r.name for r in results]
            assert "explorer.exe" not in names
            assert "HD-Player.exe" not in names
            assert "msmpeng.exe" not in names

            # Should include safe-to-recommend and user apps
            safe = [r for r in results if r.category == "SAFE_TO_RECOMMEND"]
            assert len(safe) >= 1

    def test_process_classification(self):
        controller = EmulatorController()

        mock_procs = []
        for name in ["notepad.exe", "chrome.exe", "svchost.exe"]:
            m = MagicMock()
            m.info = {"name": name, "pid": 100}
            m.info["cpu_percent"] = 10.0  # High enough to not skip
            mem_mock = MagicMock()
            mem_mock.rss = 100 * 1024 * 1024
            m.info["memory_info"] = mem_mock
            mock_procs.append(m)

        with patch("psutil.process_iter", return_value=iter(mock_procs)):
            results = controller.analyze_background_processes()
            notepad = [r for r in results if r.name == "notepad.exe"]
            if notepad:
                assert notepad[0].category == "USER_APPLICATION"

    def test_empty_process_list(self):
        controller = EmulatorController()
        with patch("psutil.process_iter", return_value=iter([])):
            results = controller.analyze_background_processes()
            assert results == []


# ── GPU Diagnostics tests ──────────────────────────────────────

class TestGPUTargetInfo:
    def test_default_values(self):
        info = GPUTargetInfo()
        assert info.gpu_name == ""
        assert info.utilization == 0.0
        assert info.gpu_bound is None

    def test_discrete_gpu(self):
        info = GPUTargetInfo(is_discrete=True)
        assert info.is_discrete is True
        assert info.is_integrated is False


# ── CpuAffinityOptimization tests ──────────────────────────────

class TestCpuAffinityOptimization:
    def test_check_no_emulator(self):
        from app.core.optimization_base import OptimizationStatus
        opt = CpuAffinityOptimization()
        with patch.object(opt._controller, "detect_target", return_value=None):
            result = opt.check()
            assert result.status == OptimizationStatus.NOT_AVAILABLE

    def test_check_already_optimal(self):
        from app.core.optimization_base import OptimizationStatus
        opt = CpuAffinityOptimization()
        mock_target = EmulatorTarget(pid=1234)
        with patch.object(opt._controller, "detect_target", return_value=mock_target):
            with patch.object(opt._controller, "read_affinity", return_value=(0xFFF, 12, 12)):
                with patch.object(opt._controller, "get_recommended_affinity", return_value=None):
                    result = opt.check()
                    assert result.status == OptimizationStatus.ALREADY_OPTIMAL

    def test_snapshot(self):
        from app.core.optimization_base import OptimizationStatus
        opt = CpuAffinityOptimization()
        opt._target_pid = 1234
        with patch.object(opt._controller, "read_affinity", return_value=(0xFF, 8, 12)):
            snap = opt.snapshot()
            assert snap["pid"] == 1234
            assert snap["original_mask"] == 0xFF

    def test_rollback(self):
        opt = CpuAffinityOptimization()
        opt._target_pid = 1234
        opt._original_mask = 0xFFF
        with patch.object(opt._controller, "restore_affinity", return_value=True):
            assert opt.rollback() is True

    def test_rollback_no_pid(self):
        opt = CpuAffinityOptimization()
        assert opt.rollback() is False


# ── Protected process lists ────────────────────────────────────

class TestProtectedProcesses:
    def test_explorer_protected(self):
        assert "explorer.exe" in PROTECTED_PROCESSES

    def test_system_protected(self):
        assert "system" in PROTECTED_PROCESSES

    def test_svchost_protected(self):
        assert "svchost.exe" in PROTECTED_PROCESSES

    def test_hd_player_not_protected(self):
        assert "HD-Player.exe" not in PROTECTED_PROCESSES

    def test_hd_player_in_emulator_names(self):
        assert "HD-Player.exe" in EMULATOR_PROCESS_NAMES


# ── Integration tests ──────────────────────────────────────────

class TestIntegration:
    def test_controller_reuses_singleton(self):
        from app.core.emulator_controller import emulator_controller
        assert isinstance(emulator_controller, EmulatorController)

    def test_full_status_no_emulator(self):
        controller = EmulatorController()
        with patch.object(controller, "detect_target", return_value=None):
            status = controller.get_full_status()
            assert status["detected"] is False

    def test_full_status_with_emulator(self):
        controller = EmulatorController()
        target = EmulatorTarget(
            name="HD-Player.exe", pid=1234,
            priority=0, priority_name="NORMAL",
            affinity_cpus=12, total_cpus=12,
            cpu_percent=25.0, memory_mb=1500.0,
            emulator="BlueStacks",
        )

        with patch.object(controller, "detect_target", return_value=target):
            with patch.object(controller, "analyze_memory_pressure") as mock_mem:
                mock_mem.return_value = MemoryPressureInfo(
                    total_gb=16.0, used_gb=8.0, percent_used=50.0,
                    pressure_level="NORMAL",
                )
                with patch.object(controller, "analyze_background_processes") as mock_bg:
                    mock_bg.return_value = []
                    with patch.object(controller, "get_gpu_diagnostics") as mock_gpu:
                        mock_gpu.return_value = GPUTargetInfo(gpu_name="RTX 3050")
                        with patch.object(controller, "read_affinity", return_value=(0xFFF, 12, 12)):
                            status = controller.get_full_status()
                            assert status["detected"] is True
                            assert status["target"].name == "HD-Player.exe"

    def test_apply_then_rollback_affinity(self):
        """Test apply → verify → rollback cycle."""
        controller = EmulatorController()

        # Create separate mock processes for apply vs restore
        mock_proc_apply = MagicMock()
        mock_proc_apply.cpu_affinity.return_value = 0xFF

        mock_proc_restore = MagicMock()
        mock_proc_restore.cpu_affinity.return_value = 0xFFF

        call_count = [0]
        def make_proc(pid):
            call_count[0] += 1
            if call_count[0] <= 2:  # First two calls: apply + verify
                return mock_proc_apply
            return mock_proc_restore  # Restore calls

        with patch("psutil.Process", side_effect=make_proc):
            # Apply
            assert controller.apply_affinity(1234, 0xFF) is True
            # Restore
            assert controller.restore_affinity(1234, 0xFFF) is True
