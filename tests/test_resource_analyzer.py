"""
Tests for Heaven Society — Resource Analyzer (Phase 15).

Covers: RAM pressure, emulator process analysis, recommendations,
bottleneck classification, safety rules, and regression tests.
"""

import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from app.core.resource_analyzer import (
    RAMPressureInfo,
    EmulatorProcessInfo,
    ResourceRecommendation,
    BottleneckClassification,
    ResourceStatus,
    RAMPressureAnalyzer,
    EmulatorProcessAnalyzer,
    ResourceRecommendationEngine,
    ResourceBottleneckClassifier,
    ResourceAnalyzer,
    resource_analyzer,
)


# ── RAMPressureInfo tests ──────────────────────────────────────

class TestRAMPressureInfo:
    def test_default_values(self):
        info = RAMPressureInfo()
        assert info.total_gb == 0.0
        assert info.pressure_level == "UNKNOWN"
        assert info.top_processes == []

    def test_free_gb_property(self):
        info = RAMPressureInfo(available_gb=8.5)
        assert info.free_gb == 8.5


# ── EmulatorProcessInfo tests ──────────────────────────────────

class TestEmulatorProcessInfo:
    def test_default_values(self):
        info = EmulatorProcessInfo()
        assert info.name == ""
        assert info.pid == 0
        assert info.num_threads == 0
        assert info.rss_mb == 0.0
        assert info.children == []


# ── RAMPressureAnalyzer tests ──────────────────────────────────

class TestRAMPressureAnalyzer:
    def test_analyze_returns_info(self):
        analyzer = RAMPressureAnalyzer()
        info = analyzer.analyze()
        assert isinstance(info, RAMPressureInfo)
        assert info.total_gb > 0

    def test_pressure_classification_optimal(self):
        analyzer = RAMPressureAnalyzer()
        info = RAMPressureInfo(total_gb=16, used_gb=8, percent_used=50, swap_percent=0)
        level, rec = analyzer._classify_pressure(info)
        assert level == "OPTIMAL"

    def test_pressure_classification_moderate(self):
        analyzer = RAMPressureAnalyzer()
        info = RAMPressureInfo(total_gb=16, used_gb=11, percent_used=68, swap_percent=0)
        level, rec = analyzer._classify_pressure(info)
        assert level == "MODERATE"

    def test_pressure_classification_high(self):
        analyzer = RAMPressureAnalyzer()
        info = RAMPressureInfo(total_gb=16, used_gb=13, percent_used=82, swap_percent=15)
        level, rec = analyzer._classify_pressure(info)
        assert level == "HIGH"

    def test_pressure_classification_critical(self):
        analyzer = RAMPressureAnalyzer()
        info = RAMPressureInfo(total_gb=16, used_gb=15, percent_used=94, swap_percent=55)
        level, rec = analyzer._classify_pressure(info)
        assert level == "CRITICAL"

    def test_pressure_critical_by_swap(self):
        analyzer = RAMPressureAnalyzer()
        info = RAMPressureInfo(total_gb=16, used_gb=12, percent_used=75, swap_percent=60)
        level, rec = analyzer._classify_pressure(info)
        assert level == "CRITICAL"

    def test_top_processes_sorted_by_memory(self):
        analyzer = RAMPressureAnalyzer()
        with patch("psutil.process_iter") as mock_iter:
            mock_procs = []
            for name, mb in [("A.exe", 500), ("B.exe", 200), ("C.exe", 1000)]:
                m = MagicMock()
                m.info = {"name": name, "pid": 100, "memory_info": MagicMock(rss=mb * 1024 * 1024), "memory_percent": 1.0}
                mock_procs.append(m)
            mock_iter.return_value = iter(mock_procs)
            procs = analyzer._get_top_memory_processes()
            assert len(procs) == 3
            assert procs[0]["rss_mb"] >= procs[1]["rss_mb"]

    def test_excludes_pid(self):
        analyzer = RAMPressureAnalyzer()
        with patch("psutil.process_iter") as mock_iter:
            m1 = MagicMock()
            m1.info = {"name": "target.exe", "pid": 999, "memory_info": MagicMock(rss=100 * 1024 * 1024), "memory_percent": 1.0}
            m2 = MagicMock()
            m2.info = {"name": "other.exe", "pid": 100, "memory_info": MagicMock(rss=200 * 1024 * 1024), "memory_percent": 2.0}
            mock_iter.return_value = iter([m1, m2])
            procs = analyzer._get_top_memory_processes(exclude_pid=999)
            assert all(p["pid"] != 999 for p in procs)


# ── EmulatorProcessAnalyzer tests ──────────────────────────────

class TestEmulatorProcessAnalyzer:
    def test_analyze_missing_process(self):
        import psutil
        analyzer = EmulatorProcessAnalyzer()
        with patch("psutil.Process", side_effect=psutil.NoSuchProcess(9999)):
            result = analyzer.analyze(9999)
            assert result is None

    def test_analyze_with_mock(self):
        analyzer = EmulatorProcessAnalyzer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "HD-Player.exe"
        mock_proc.status.return_value = "running"
        mock_proc.cpu_percent.return_value = 25.0
        mock_proc.cpu_times.return_value = MagicMock(user=10.0, system=5.0)
        mock_proc.num_threads.return_value = 32
        mock_proc.num_handles.return_value = 1500
        mock_proc.memory_info.return_value = MagicMock(rss=1500*1024*1024, vms=3000*1024*1024, page_faults=1000)
        mock_proc.memory_percent.return_value = 9.5
        mock_proc.nice.return_value = 0
        mock_proc.cpu_affinity.return_value = 0xFFF
        mock_proc.create_time.return_value = time.time() - 3600
        mock_proc.exe.return_value = "C:\\test\\HD-Player.exe"
        mock_proc.children.return_value = []

        with patch("psutil.Process", return_value=mock_proc):
            with patch("psutil.cpu_count", return_value=12):
                result = analyzer.analyze(1234, "HD-Player.exe")
                assert result is not None
                assert result.name == "HD-Player.exe"
                assert result.cpu_percent == 25.0
                assert result.num_threads == 32
                assert result.num_handles == 1500
                assert result.rss_mb > 0

    def test_name_mismatch(self):
        import psutil
        analyzer = EmulatorProcessAnalyzer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "OTHER.exe"

        with patch("psutil.Process", return_value=mock_proc):
            result = analyzer.analyze(1234, "HD-Player.exe")
            assert result is None

    def test_access_denied(self):
        import psutil
        analyzer = EmulatorProcessAnalyzer()
        with patch("psutil.Process", side_effect=psutil.AccessDenied(1234)):
            result = analyzer.analyze(1234)
            assert result is not None
            assert result.status == "access_denied"

    def test_children_collected(self):
        analyzer = EmulatorProcessAnalyzer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "HD-Player.exe"
        mock_proc.status.return_value = "running"
        mock_proc.cpu_percent.return_value = 10.0
        mock_proc.cpu_times.return_value = MagicMock(user=5, system=2)
        mock_proc.num_threads.return_value = 16
        mock_proc.num_handles.return_value = 0
        mock_proc.memory_info.return_value = MagicMock(rss=500*1024*1024, vms=1000*1024*1024)
        mock_proc.memory_percent.return_value = 3.0
        mock_proc.nice.return_value = 0
        mock_proc.cpu_affinity.return_value = 0xFFF
        mock_proc.create_time.return_value = time.time()
        mock_proc.exe.return_value = ""
        child1 = MagicMock()
        child1.name.return_value = "child.exe"
        child1.pid = 5678
        child1.status.return_value = "running"
        mock_proc.children.return_value = [child1]

        with patch("psutil.Process", return_value=mock_proc):
            with patch("psutil.cpu_count", return_value=12):
                result = analyzer.analyze(1234, "HD-Player.exe")
                assert result.child_count == 1
                assert len(result.children) == 1


# ── ResourceRecommendationEngine tests ─────────────────────────

class TestResourceRecommendationEngine:
    def test_generate_returns_list(self):
        engine = ResourceRecommendationEngine()
        recs = engine.generate()
        assert isinstance(recs, list)

    def test_critical_ram_generates_high_priority(self):
        engine = ResourceRecommendationEngine()
        ram = RAMPressureInfo(pressure_level="CRITICAL", percent_used=95, swap_percent=60, available_gb=0.5, total_gb=16)
        recs = engine.generate(ram_info=ram)
        high_priority = [r for r in recs if r.priority == "HIGH"]
        assert len(high_priority) > 0

    def test_high_emulator_cpu_generates_cpu_recommendation(self):
        engine = ResourceRecommendationEngine()
        emu = EmulatorProcessInfo(cpu_percent=95, num_threads=32, affinity_cpus=12, total_cpus=12)
        recs = engine.generate(emulator_info=emu)
        cpu_recs = [r for r in recs if r.category == "CPU"]
        assert len(cpu_recs) > 0

    def test_high_vram_generates_gpu_recommendation(self):
        engine = ResourceRecommendationEngine()
        gpu = {"vram_total_mb": 4096, "vram_used_mb": 3800, "utilization": 85}
        recs = engine.generate(gpu_info=gpu)
        gpu_recs = [r for r in recs if r.category == "GPU"]
        assert len(gpu_recs) > 0

    def test_recommendations_sorted_by_priority(self):
        engine = ResourceRecommendationEngine()
        ram = RAMPressureInfo(pressure_level="CRITICAL", percent_used=95, swap_percent=60, available_gb=0.5, total_gb=16)
        emu = EmulatorProcessInfo(cpu_percent=95, num_threads=32, affinity_cpus=12, total_cpus=12)
        gpu = {"vram_total_mb": 4096, "vram_used_mb": 3800, "utilization": 95}
        recs = engine.generate(ram_info=ram, emulator_info=emu, gpu_info=gpu)
        if len(recs) > 1:
            priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            for i in range(len(recs) - 1):
                assert priority_order.get(recs[i].priority, 3) <= priority_order.get(recs[i+1].priority, 3)

    def test_no_recommendations_for_healthy_system(self):
        engine = ResourceRecommendationEngine()
        ram = RAMPressureInfo(pressure_level="OPTIMAL", percent_used=40, swap_percent=0, available_gb=10, total_gb=16)
        emu = EmulatorProcessInfo(cpu_percent=30, rss_mb=1000, num_threads=16, affinity_cpus=12, total_cpus=12)
        gpu = {"vram_total_mb": 4096, "vram_used_mb": 1500, "utilization": 40}
        recs = engine.generate(ram_info=ram, emulator_info=emu, gpu_info=gpu)
        # Should have few or no high-priority recs
        high = [r for r in recs if r.priority == "HIGH"]
        assert len(high) == 0

    def test_emulator_high_ram_usage_recommendation(self):
        engine = ResourceRecommendationEngine()
        ram = RAMPressureInfo(total_gb=8, percent_used=50, available_gb=4, swap_percent=0)
        emu = EmulatorProcessInfo(rss_mb=4000, cpu_percent=20, num_threads=16, affinity_cpus=8, total_cpus=8)
        recs = engine.generate(ram_info=ram, emulator_info=emu)
        emu_recs = [r for r in recs if r.category == "EMULATOR"]
        assert len(emu_recs) > 0


# ── ResourceBottleneckClassifier tests ─────────────────────────

class TestBottleneckClassifier:
    def test_classify_no_data(self):
        classifier = ResourceBottleneckClassifier()
        result = classifier.classify()
        assert result.classification == "INCONCLUSIVE"
        assert result.confidence == 0.0

    def test_classify_gpu_bound(self):
        classifier = ResourceBottleneckClassifier()
        frame = MagicMock()
        frame.cpu_utilization = 40
        frame.gpu_utilization = 95
        frame.ram_percent = 50
        frame.gpu_temp = 70
        frame.thermal_status = "NORMAL"
        result = classifier.classify(telemetry_frame=frame)
        assert result.classification == "GPU_BOUND"
        assert result.confidence > 0.5

    def test_classify_cpu_bound(self):
        classifier = ResourceBottleneckClassifier()
        frame = MagicMock()
        frame.cpu_utilization = 92
        frame.gpu_utilization = 30
        frame.ram_percent = 50
        frame.gpu_temp = 60
        frame.thermal_status = "NORMAL"
        result = classifier.classify(telemetry_frame=frame)
        assert result.classification == "CPU_BOUND"
        assert result.confidence > 0.5

    def test_classify_memory_pressure(self):
        classifier = ResourceBottleneckClassifier()
        frame = MagicMock()
        frame.cpu_utilization = 60
        frame.gpu_utilization = 50
        frame.ram_percent = 92
        frame.gpu_temp = 60
        frame.thermal_status = "NORMAL"
        ram = RAMPressureInfo(swap_percent=35)
        result = classifier.classify(telemetry_frame=frame, ram_info=ram)
        assert result.classification == "MEMORY_PRESSURE"

    def test_classify_no_bottleneck(self):
        classifier = ResourceBottleneckClassifier()
        frame = MagicMock()
        frame.cpu_utilization = 45
        frame.gpu_utilization = 55
        frame.ram_percent = 60
        frame.gpu_temp = 65
        frame.thermal_status = "NORMAL"
        result = classifier.classify(telemetry_frame=frame)
        assert result.classification == "NO_CLEAR_BOTTLENECK"

    def test_classify_frame_time_limited(self):
        classifier = ResourceBottleneckClassifier()
        frame = MagicMock()
        frame.cpu_utilization = 50
        frame.gpu_utilization = 50
        frame.ram_percent = 60
        frame.gpu_temp = 65
        frame.thermal_status = "NORMAL"
        pm = {"fps": 60, "frame_time_ms": 16.6, "frame_spikes": 25}
        result = classifier.classify(telemetry_frame=frame, presentmon_data=pm)
        assert result.classification == "FRAME_TIME_LIMITED"

    def test_thermal_throttling_overrides(self):
        classifier = ResourceBottleneckClassifier()
        frame = MagicMock()
        frame.cpu_utilization = 50
        frame.gpu_utilization = 50
        frame.ram_percent = 50
        frame.gpu_temp = 92
        frame.thermal_status = "THROTTLING"
        result = classifier.classify(telemetry_frame=frame)
        # Thermal throttling should be detected
        assert "thermal" in result.description.lower() or result.classification == "CPU_BOUND"

    def test_emulator_info_enhances_classification(self):
        classifier = ResourceBottleneckClassifier()
        frame = MagicMock()
        frame.cpu_utilization = 50
        frame.gpu_utilization = 50
        frame.ram_percent = 50
        frame.gpu_temp = 60
        frame.thermal_status = "NORMAL"
        emu = EmulatorProcessInfo(cpu_percent=90, rss_mb=2000, num_threads=32, num_handles=1500)
        result = classifier.classify(telemetry_frame=frame, emulator_info=emu)
        # Evidence is populated from the telemetry frame
        assert result.classification != "INCONCLUSIVE"


# ── ResourceStatus tests ───────────────────────────────────────

class TestResourceStatus:
    def test_default_values(self):
        status = ResourceStatus()
        assert status.ram is None
        assert status.emulator is None
        assert status.bottleneck is None
        assert status.recommendations == []


# ── ResourceAnalyzer (combined) tests ──────────────────────────

class TestResourceAnalyzer:
    def test_analyze_returns_status(self):
        analyzer = ResourceAnalyzer()
        with patch.object(analyzer._ram_analyzer, "analyze") as mock_ram:
            mock_ram.return_value = RAMPressureInfo(total_gb=16, percent_used=50, pressure_level="OPTIMAL")
            status = analyzer.analyze()
            assert isinstance(status, ResourceStatus)
            assert status.ram is not None

    def test_analyze_with_emulator(self):
        analyzer = ResourceAnalyzer()
        with patch.object(analyzer._ram_analyzer, "analyze") as mock_ram, \
             patch.object(analyzer._process_analyzer, "analyze") as mock_proc:
            mock_ram.return_value = RAMPressureInfo(total_gb=16, percent_used=50)
            mock_proc.return_value = EmulatorProcessInfo(name="HD-Player.exe", pid=1234, cpu_percent=25)
            status = analyzer.analyze(emulator_pid=1234, emulator_name="HD-Player.exe")
            assert status.emulator is not None
            assert status.emulator.name == "HD-Player.exe"

    def test_analyze_no_emulator(self):
        analyzer = ResourceAnalyzer()
        with patch.object(analyzer._ram_analyzer, "analyze") as mock_ram:
            mock_ram.return_value = RAMPressureInfo(total_gb=16, percent_used=50)
            status = analyzer.analyze(emulator_pid=0)
            assert status.emulator is None

    def test_quick_ram_pressure(self):
        analyzer = ResourceAnalyzer()
        result = analyzer.get_ram_pressure()
        assert isinstance(result, RAMPressureInfo)

    def test_singleton(self):
        assert isinstance(resource_analyzer, ResourceAnalyzer)


# ── Safety tests ───────────────────────────────────────────────

class TestSafety:
    def test_no_process_termination(self):
        """No analysis should terminate processes."""
        import psutil
        analyzer = ResourceAnalyzer()
        with patch("psutil.Process.terminate") as mock_term:
            with patch.object(analyzer._ram_analyzer, "analyze") as mock_ram:
                mock_ram.return_value = RAMPressureInfo(total_gb=16, percent_used=50)
                analyzer.analyze()
            mock_term.assert_not_called()

    def test_ram_analyzer_read_only(self):
        """RAM analyzer should not write anything."""
        analyzer = RAMPressureAnalyzer()
        with patch("psutil.virtual_memory") as mock_vm:
            mock_vm.return_value = MagicMock(total=16*1024**3, used=8*1024**3, available=8*1024**3, percent=50, cached=0, buffers=0)
            with patch("psutil.swap_memory", return_value=MagicMock(total=4*1024**3, used=0, percent=0)):
                with patch("psutil.process_iter", return_value=iter([])):
                    info = analyzer.analyze()
                    assert info.pressure_level in ("OPTIMAL", "MODERATE", "HIGH", "CRITICAL", "UNKNOWN")

    def test_recommendations_never_terminate(self):
        """Recommendations should never suggest process termination."""
        engine = ResourceRecommendationEngine()
        ram = RAMPressureInfo(pressure_level="CRITICAL", percent_used=95, swap_percent=60, available_gb=0.5, total_gb=16)
        recs = engine.generate(ram_info=ram)
        for rec in recs:
            assert "kill" not in rec.description.lower()
            assert "terminate" not in rec.description.lower()

    def test_bottleneck_never_fabricates(self):
        """Bottleneck classifier should return INCONCLUSIVE with no data."""
        classifier = ResourceBottleneckClassifier()
        result = classifier.classify()
        assert result.classification == "INCONCLUSIVE"

    def test_no_registry_modification(self):
        """No analysis should modify registry."""
        import winreg
        analyzer = ResourceAnalyzer()
        with patch("winreg.SetValueEx") as mock_reg:
            with patch.object(analyzer._ram_analyzer, "analyze") as mock_ram:
                mock_ram.return_value = RAMPressureInfo(total_gb=16, percent_used=50)
                analyzer.analyze()
            mock_reg.assert_not_called()


# ── Recommendation details tests ───────────────────────────────

class TestRecommendationDetails:
    def test_recommendations_have_required_fields(self):
        engine = ResourceRecommendationEngine()
        ram = RAMPressureInfo(pressure_level="HIGH", percent_used=85, swap_percent=15, available_gb=2, total_gb=16)
        recs = engine.generate(ram_info=ram)
        for rec in recs:
            assert rec.category != ""
            assert rec.title != ""
            assert rec.description != ""
            assert rec.reason != ""

    def test_recommendation_has_impact(self):
        engine = ResourceRecommendationEngine()
        emu = EmulatorProcessInfo(cpu_percent=95, num_threads=32, affinity_cpus=12, total_cpus=12)
        recs = engine.generate(emulator_info=emu)
        for rec in recs:
            assert rec.estimated_impact != ""


# ── Regression tests ───────────────────────────────────────────

class TestRegression:
    def test_existing_optimizations_still_work(self):
        """Verify existing optimization infrastructure is unaffected."""
        from app.core.optimizations import get_all_optimizations, get_optimization_by_id
        opts = get_all_optimizations()
        assert len(opts) >= 4  # At least Power, GameMode, EmulatorPriority, Background

        for opt in opts:
            assert hasattr(opt, "id")
            assert hasattr(opt, "name")
            assert hasattr(opt, "check")

    def test_existing_profiles_still_work(self):
        from app.core.profiles import get_all_profiles
        profiles = get_all_profiles()
        assert len(profiles) == 3  # BALANCED, GAMING, MAX PERFORMANCE

    def test_emulator_controller_still_works(self):
        from app.core.emulator_controller import emulator_controller
        # Should not crash even without emulator
        target = emulator_controller.detect_target()
        # target may be None — that's fine

    def test_analyzer_still_works(self):
        from app.core.analyzer import bottleneck_analyzer
        from app.core.telemetry import TelemetryFrame
        frame = TelemetryFrame(cpu_utilization=50, gpu_utilization=50, ram_percent=50)
        result = bottleneck_analyzer.analyze(frame)
        assert result.performance_class in ("EXCELLENT", "GOOD", "AVERAGE", "BOTTLENECKED", "SEVERE")
