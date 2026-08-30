"""
Tests for Heaven Society — Professional Performance Report (Phase 28).

Uses mocked subsystems; never requires real hardware.
"""

import os
import json
import tempfile
import pytest
from unittest.mock import patch, MagicMock

from app.core.performance_report import (
    PerformanceReport,
    PerformanceReportGenerator,
    SystemSection,
    EmulatorSection,
    PerformanceSection,
    ThermalSection,
    OptimizationSection,
    BenchmarkSection,
    performance_report_generator,
)


class TestSystemSection:
    """Test SystemSection data model."""

    def test_defaults(self):
        s = SystemSection()
        assert s.cpu_model == "N/A"
        assert s.gpu_name == "N/A"
        assert s.cpu_utilization is None
        assert s.gpu_temperature is None
        assert s.ram_total is None
        assert s.display_refresh is None

    def test_with_values(self):
        s = SystemSection(
            cpu_model="Ryzen 5",
            gpu_name="RTX 3060",
            cpu_utilization=45.0,
            gpu_temperature=65.0,
            ram_total=16.0,
            ram_used=8.0,
            ram_percent=50.0,
            display_refresh=144,
        )
        assert s.cpu_model == "Ryzen 5"
        assert s.cpu_utilization == 45.0


class TestEmulatorSection:
    """Test EmulatorSection data model."""

    def test_defaults(self):
        e = EmulatorSection()
        assert e.emulator_name == "N/A"
        assert e.pid == 0

    def test_with_values(self):
        e = EmulatorSection(
            emulator_name="BlueStacks",
            process_name="HD-Player.exe",
            pid=1234,
            priority="NORMAL",
        )
        assert e.pid == 1234


class TestPerformanceSection:
    """Test PerformanceSection data model."""

    def test_defaults(self):
        p = PerformanceSection()
        assert p.present_fps is None
        assert p.sample_count == 0

    def test_with_values(self):
        p = PerformanceSection(
            present_fps=120.0,
            one_percent_low=90.0,
            average_frame_time=8.33,
            sample_count=500,
        )
        assert p.present_fps == 120.0
        assert p.sample_count == 500


class TestThermalSection:
    """Test ThermalSection data model."""

    def test_defaults(self):
        t = ThermalSection()
        assert t.gpu_temperature is None
        assert t.cpu_temperature is None
        assert t.thermal_state == "N/A"

    def test_with_values(self):
        t = ThermalSection(
            gpu_temperature=65.0,
            cpu_temperature=55.0,
            thermal_state="NORMAL",
        )
        assert t.gpu_temperature == 65.0


class TestOptimizationSection:
    """Test OptimizationSection data model."""

    def test_defaults(self):
        o = OptimizationSection()
        assert o.applied == []
        assert o.already_optimal == []
        assert o.rollback_available is False

    def test_with_values(self):
        o = OptimizationSection(
            profile_name="Gaming",
            applied=["Power Plan"],
            already_optimal=["Game Mode"],
            requires_admin=["Emulator Priority"],
        )
        assert len(o.applied) == 1
        assert len(o.already_optimal) == 1
        assert len(o.requires_admin) == 1


class TestBenchmarkSection:
    """Test BenchmarkSection data model."""

    def test_defaults(self):
        b = BenchmarkSection()
        assert b.baseline_fps is None
        assert b.fps_delta is None

    def test_with_values(self):
        b = BenchmarkSection(
            baseline_fps=100.0,
            optimized_fps=110.0,
            fps_delta=10.0,
            fps_delta_percent=10.0,
        )
        assert b.fps_delta == 10.0


class TestPerformanceReport:
    """Test PerformanceReport data model."""

    def test_defaults(self):
        r = PerformanceReport()
        assert r.report_id.startswith("report_")
        assert r.generated_at != ""
        assert r.report_version == "1.0"
        assert isinstance(r.system, SystemSection)
        assert isinstance(r.emulator, EmulatorSection)
        assert isinstance(r.performance, PerformanceSection)
        assert isinstance(r.thermal, ThermalSection)
        assert isinstance(r.optimization, OptimizationSection)
        assert isinstance(r.benchmark, BenchmarkSection)

    def test_to_dict(self):
        r = PerformanceReport(
            report_id="test_report",
            system=SystemSection(cpu_model="Test CPU"),
            performance=PerformanceSection(present_fps=120.0),
        )
        d = r.to_dict()
        assert d["report_id"] == "test_report"
        assert d["system"]["cpu_model"] == "Test CPU"
        assert d["performance"]["present_fps"] == 120.0

    def test_json_serializable(self):
        r = PerformanceReport()
        d = r.to_dict()
        json_str = json.dumps(d, default=str)
        assert "report_id" in json_str


class TestReportGenerator:
    """Test the report generator with mocked subsystems."""

    def test_generate_empty(self):
        gen = PerformanceReportGenerator()
        with patch("app.system.cpu.cpu_monitor") as mock_cpu, \
             patch("app.system.gpu.gpu_monitor") as mock_gpu, \
             patch("app.core.emulator_controller.emulator_controller") as mock_emu, \
             patch("app.system.thermal_monitor.thermal_diagnostics") as mock_therm, \
             patch("app.core.optimizer.optimizer") as mock_opt, \
             patch("app.system.display.display_monitor") as mock_disp, \
             patch("psutil.cpu_percent", return_value=0.0), \
             patch("psutil.virtual_memory") as mock_vm:

            mock_cpu.detect.return_value = MagicMock(
                model="", physical_cores=0, logical_cores=0,
                max_frequency_mhz=0, temperature_celsius=None,
            )
            mock_gpu.detect.return_value = []
            mock_emu.detect_target.return_value = None
            mock_therm.diagnose.return_value = MagicMock(
                gpu=MagicMock(temperature_celsius=None, clock_core_mhz=0,
                              power_draw_watts=None, power_limit_watts=None,
                              power_state=""),
                cpu=MagicMock(temperature_celsius=None, frequency_mhz=0),
                thermal_state="UNKNOWN",
                throttle_indicators=[],
            )
            mock_opt.get_current_status.return_value = {"optimizations": []}
            mock_disp.detect.return_value = MagicMock(
                resolution_x=1920, resolution_y=1080,
                refresh_rate=60, display_name="Default",
            )
            mock_vm.return_value = MagicMock(total=0, used=0, percent=0)

            report = gen.generate()
            assert isinstance(report, PerformanceReport)
            assert isinstance(report.system, SystemSection)
            assert isinstance(report.emulator, EmulatorSection)

    def test_generate_with_hardware(self):
        gen = PerformanceReportGenerator()
        with patch("app.system.cpu.cpu_monitor") as mock_cpu, \
             patch("app.system.gpu.gpu_monitor") as mock_gpu, \
             patch("app.core.emulator_controller.emulator_controller") as mock_emu, \
             patch("app.system.thermal_monitor.thermal_diagnostics") as mock_therm, \
             patch("app.core.optimizer.optimizer") as mock_opt, \
             patch("app.system.display.display_monitor") as mock_disp, \
             patch("psutil.cpu_percent", return_value=45.0), \
             patch("psutil.virtual_memory") as mock_vm:

            mock_cpu.detect.return_value = MagicMock(
                model="Ryzen 5 5600X", physical_cores=6, logical_cores=12,
                max_frequency_mhz=4500, temperature_celsius=55.0,
            )
            gpu = MagicMock(
                name="RTX 3060", vendor="NVIDIA", driver_version="536.23",
                utilization_percent=75.0, temperature_celsius=65.0,
                clock_core_mhz=1800, power_draw_watts=150.0,
                vram_total_mb=12288, vram_used_mb=4096,
            )
            mock_gpu.detect.return_value = [gpu]
            mock_gpu.update.return_value = gpu

            target = MagicMock(
                emulator="BlueStacks", name="HD-Player.exe", pid=1234,
                priority_name="NORMAL", affinity_cpus=12, total_cpus=12,
                cpu_percent=45.0, memory_mb=800.0, gpu_name="RTX 3060",
                confidence=0.95,
            )
            mock_emu.detect_target.return_value = target

            mock_therm.diagnose.return_value = MagicMock(
                gpu=MagicMock(
                    temperature_celsius=65.0, clock_core_mhz=1800,
                    power_draw_watts=150.0, power_limit_watts=200.0,
                    power_state="P0",
                ),
                cpu=MagicMock(temperature_celsius=55.0, frequency_mhz=4500),
                thermal_state=MagicMock(value="NORMAL"),
                throttle_indicators=[],
            )

            mock_opt.get_current_status.return_value = {
                "profile_name": "Gaming",
                "rollback_available": True,
                "optimizations": [
                    {"name": "Power Plan", "status": "APPLIED"},
                    {"name": "Game Mode", "status": "ALREADY_OPTIMAL"},
                    {"name": "Emulator Priority", "status": "REQUIRES_ADMIN"},
                ],
            }

            mock_disp.detect.return_value = MagicMock(
                resolution_x=1920, resolution_y=1080,
                refresh_rate=144, display_name="Primary",
            )
            mock_vm.return_value = MagicMock(total=16*1024**3, used=8*1024**3, percent=50.0)

            report = gen.generate()
            assert "5600X" in report.system.cpu_model
            assert report.emulator.pid == 1234
            assert report.thermal.gpu_temperature == 65.0
            assert "Power Plan" in report.optimization.applied
            assert "Game Mode" in report.optimization.already_optimal

    def test_generate_with_no_emulator(self):
        gen = PerformanceReportGenerator()
        with patch("app.system.cpu.cpu_monitor") as mock_cpu, \
             patch("app.system.gpu.gpu_monitor") as mock_gpu, \
             patch("app.core.emulator_controller.emulator_controller") as mock_emu, \
             patch("app.system.thermal_monitor.thermal_diagnostics") as mock_therm, \
             patch("app.core.optimizer.optimizer") as mock_opt, \
             patch("app.system.display.display_monitor") as mock_disp, \
             patch("psutil.cpu_percent", return_value=30.0), \
             patch("psutil.virtual_memory") as mock_vm:

            mock_cpu.detect.return_value = MagicMock(
                model="Test", physical_cores=4, logical_cores=8,
                max_frequency_mhz=3000, temperature_celsius=None,
            )
            mock_gpu.detect.return_value = []
            mock_emu.detect_target.return_value = None
            mock_therm.diagnose.return_value = MagicMock(
                gpu=MagicMock(temperature_celsius=None, clock_core_mhz=0,
                              power_draw_watts=None, power_limit_watts=None,
                              power_state=""),
                cpu=MagicMock(temperature_celsius=None, frequency_mhz=0),
                thermal_state=MagicMock(value="UNKNOWN"),
                throttle_indicators=[],
            )
            mock_opt.get_current_status.return_value = {"optimizations": []}
            mock_disp.detect.return_value = MagicMock(
                resolution_x=1920, resolution_y=1080,
                refresh_rate=60, display_name="Default",
            )
            mock_vm.return_value = MagicMock(total=8*1024**3, used=4*1024**3, percent=50.0)

            report = gen.generate()
            assert report.emulator.emulator_name == "Not detected"


class TestCLIFormatting:
    """Test CLI report formatting."""

    def test_format_cli(self):
        gen = PerformanceReportGenerator()
        report = PerformanceReport(
            report_id="test_report",
            system=SystemSection(
                cpu_model="Ryzen 5", cpu_cores="6P / 12L",
                gpu_name="RTX 3060", ram_total=16.0, ram_used=8.0, ram_percent=50.0,
            ),
            emulator=EmulatorSection(
                emulator_name="BlueStacks", process_name="HD-Player.exe", pid=1234,
            ),
            performance=PerformanceSection(
                present_fps=120.0, one_percent_low=90.0, average_frame_time=8.33,
                sample_count=500,
            ),
            thermal=ThermalSection(gpu_temperature=65.0, thermal_state="NORMAL"),
            optimization=OptimizationSection(
                profile_name="Gaming", applied=["Power Plan"],
            ),
        )
        cli = gen.format_cli(report)
        assert "HEAVEN SOCIETY" in cli
        assert "Ryzen 5" in cli
        assert "RTX 3060" in cli
        assert "BlueStacks" in cli
        assert "120.0" in cli
        assert "65" in cli  # GPU temp formatted as integer
        assert "Power Plan" in cli
        assert "END OF REPORT" in cli

    def test_format_cli_nas(self):
        gen = PerformanceReportGenerator()
        report = PerformanceReport()
        cli = gen.format_cli(report)
        assert "N/A" in cli


class TestJSONExport:
    """Test JSON export."""

    def test_export_json(self):
        gen = PerformanceReportGenerator()
        report = PerformanceReport(report_id="test_export")

        with tempfile.TemporaryDirectory() as tmpdir:
            path = os.path.join(tmpdir, "test_report.json")
            result = gen.export_json(report, path)
            assert os.path.exists(result)

            with open(result, "r") as f:
                data = json.load(f)
            assert data["report_id"] == "test_export"

    def test_export_json_default_path(self):
        gen = PerformanceReportGenerator()
        report = PerformanceReport(report_id="test_default")

        import app.core.performance_report as mod
        old_dir = mod.REPORTS_DIR
        with tempfile.TemporaryDirectory() as tmpdir:
            mod.REPORTS_DIR = tmpdir
            try:
                path = gen.export_json(report)
                assert os.path.exists(path)
            finally:
                mod.REPORTS_DIR = old_dir


class TestSingleton:
    """Test the singleton instance."""

    def test_singleton_exists(self):
        assert performance_report_generator is not None
        assert isinstance(performance_report_generator, PerformanceReportGenerator)


class TestEdgeCases:
    """Test edge cases."""

    def test_all_none_values(self):
        """Ensure N/A handling for all None values."""
        gen = PerformanceReportGenerator()
        report = PerformanceReport()
        cli = gen.format_cli(report)
        # Should not crash
        assert isinstance(cli, str)

    def test_optimization_empty_lists(self):
        """Ensure empty optimization lists don't crash."""
        gen = PerformanceReportGenerator()
        report = PerformanceReport(
            optimization=OptimizationSection(
                applied=[], already_optimal=[], requires_admin=[],
                recommendation_only=[], failed=[],
            ),
        )
        cli = gen.format_cli(report)
        assert "OPTIMIZATION" in cli

    def test_benchmark_all_none(self):
        """Ensure benchmark section handles all None values."""
        gen = PerformanceReportGenerator()
        report = PerformanceReport(
            benchmark=BenchmarkSection(),
        )
        cli = gen.format_cli(report)
        assert "BENCHMARK" in cli
        assert "N/A" in cli

    def test_thermal_no_throttle(self):
        """Ensure thermal section handles empty throttle list."""
        gen = PerformanceReportGenerator()
        report = PerformanceReport(
            thermal=ThermalSection(
                gpu_temperature=55.0,
                thermal_state="NORMAL",
                throttle_indicators=[],
            ),
        )
        cli = gen.format_cli(report)
        assert "55" in cli  # GPU temp formatted as integer
        assert "NORMAL" in cli
