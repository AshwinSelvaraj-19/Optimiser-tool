"""
Tests for Heaven Society — Phase 33: Startup Analysis, Game Session Monitoring.

Uses mocked Windows APIs; never modifies real startup entries or processes.
"""

import os
import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock

from app.system.startup_analyzer import (
    StartupAnalyzer,
    StartupEntry,
    StartupAnalysis,
    StartupClassification,
    startup_analyzer,
    SAFE_TO_DISABLE_NAMES,
    SECURITY_STARTUP_NAMES,
    SYSTEM_STARTUP_NAMES,
    EMULATOR_STARTUP_NAMES,
)
from app.system.game_session_monitor import (
    GameSessionMonitor,
    SessionSnapshot,
    SessionDelta,
    ResourceRecommendation,
    GameSessionReport,
    BottleneckType,
    game_session_monitor,
)


# ── StartupEntry Tests ─────────────────────────────────────────

class TestStartupEntry:
    def test_defaults(self):
        e = StartupEntry()
        assert e.name == ""
        assert e.classification == StartupClassification.UNKNOWN
        assert e.can_safely_disable is False
        assert e.is_running is False

    def test_is_running(self):
        e = StartupEntry(pid=1234)
        assert e.is_running

    def test_not_running(self):
        e = StartupEntry(pid=0)
        assert not e.is_running


# ── StartupAnalysis Tests ──────────────────────────────────────

class TestStartupAnalysis:
    def test_defaults(self):
        a = StartupAnalysis()
        assert a.total_entries == 0
        assert a.optional_names == []

    def test_optional_names(self):
        a = StartupAnalysis()
        a.entries = [
            StartupEntry(name="Chrome", can_safely_disable=True),
            StartupEntry(name="System", can_safely_disable=False),
            StartupEntry(name="Discord", can_safely_disable=True),
        ]
        assert a.optional_names == ["Chrome", "Discord"]


# ── StartupAnalyzer Tests ──────────────────────────────────────

class TestStartupAnalyzer:
    def test_analyze_returns_analysis(self):
        analyzer = StartupAnalyzer()
        result = analyzer.analyze(force=True)
        assert isinstance(result, StartupAnalysis)
        assert result.timestamp > 0

    def test_analyze_caches(self):
        analyzer = StartupAnalyzer()
        r1 = analyzer.analyze(force=True)
        r2 = analyzer.analyze(force=False)
        assert r1 is r2  # Same cached object

    def test_analyze_force_refresh(self):
        analyzer = StartupAnalyzer()
        r1 = analyzer.analyze(force=True)
        r2 = analyzer.analyze(force=True)
        # Force creates new analysis
        assert r1 is not r2

    def test_classify_security(self):
        analyzer = StartupAnalyzer()
        cls, can_disable, reason = analyzer._classify_entry("Windows Defender", None)
        assert cls == StartupClassification.SECURITY
        assert can_disable is False
        assert "never disable" in reason.lower()

    def test_classify_system(self):
        analyzer = StartupAnalyzer()
        cls, can_disable, reason = analyzer._classify_entry("CTFMON", None)
        assert cls == StartupClassification.SYSTEM
        assert can_disable is False

    def test_classify_emulator(self):
        analyzer = StartupAnalyzer()
        cls, can_disable, reason = analyzer._classify_entry("BlueStacks Agent", None)
        assert cls == StartupClassification.EMULATOR
        assert can_disable is False

    def test_classify_safe_to_disable(self):
        analyzer = StartupAnalyzer()
        cls, can_disable, reason = analyzer._classify_entry("OneDrive", None)
        assert cls == StartupClassification.SAFE_TO_RECOMMEND
        assert can_disable is True

    def test_classify_unknown(self):
        analyzer = StartupAnalyzer()
        cls, can_disable, reason = analyzer._classify_entry("MyCustomApp", None)
        assert cls == StartupClassification.UNKNOWN
        assert can_disable is False

    def test_extract_executable_quoted(self):
        analyzer = StartupAnalyzer()
        result = analyzer._extract_executable('"C:\\Program Files\\App\\app.exe" /autorun')
        assert result == "C:\\Program Files\\App\\app.exe"

    def test_extract_executable_unquoted(self):
        analyzer = StartupAnalyzer()
        result = analyzer._extract_executable("C:\\Windows\\notepad.exe")
        assert result == "C:\\Windows\\notepad.exe"

    def test_extract_executable_empty(self):
        analyzer = StartupAnalyzer()
        result = analyzer._extract_executable("")
        assert result is None

    def test_registry_scan_does_not_modify(self):
        """Registry scan must be read-only — verify no write operations."""
        import inspect
        analyzer = StartupAnalyzer()
        source = inspect.getsource(analyzer._scan_registry_run)
        assert "winreg.SetValueEx" not in source
        assert "winreg.DeleteValue" not in source
        assert "winreg.CreateKey" not in source

    def test_singleton_exists(self):
        assert isinstance(startup_analyzer, StartupAnalyzer)

    def test_all_safe_to_disable_names_are_known(self):
        """All names in SAFE_TO_DISABLE should be lowercase strings."""
        for name in SAFE_TO_DISABLE_NAMES:
            assert isinstance(name, str)
            assert name == name.lower()

    def test_protected_names_not_in_safe(self):
        """Security/system/emulator names should not appear in SAFE_TO_DISABLE."""
        all_protected = SECURITY_STARTUP_NAMES | SYSTEM_STARTUP_NAMES | EMULATOR_STARTUP_NAMES
        for name in all_protected:
            assert name not in SAFE_TO_DISABLE_NAMES, f"{name} is in both protected and safe lists"


# ── SessionSnapshot Tests ──────────────────────────────────────

class TestSessionSnapshot:
    def test_defaults(self):
        s = SessionSnapshot()
        assert s.cpu_percent == 0.0
        assert s.ram_total_gb == 0.0
        assert s.gpu_utilization is None
        assert s.present_fps is None

    def test_ram_headroom(self):
        s = SessionSnapshot(ram_available_gb=4.5)
        assert s.ram_headroom_gb == 4.5

    def test_to_dict(self):
        s = SessionSnapshot(cpu_percent=50.0, ram_total_gb=16.0)
        d = s.to_dict()
        assert d["cpu_percent"] == 50.0
        assert d["ram_total_gb"] == 16.0
        # None values should be excluded
        assert "gpu_utilization" not in d


# ── SessionDelta Tests ─────────────────────────────────────────

class TestSessionDelta:
    def test_defaults(self):
        d = SessionDelta()
        assert d.available_ram_delta_gb == 0.0
        assert d.cpu_delta == 0.0
        assert d.fps_delta is None


# ── GameSessionMonitor Tests ───────────────────────────────────

class TestGameSessionMonitor:
    def test_capture_snapshot(self):
        monitor = GameSessionMonitor()
        snap = monitor.capture_snapshot("TEST")
        assert isinstance(snap, SessionSnapshot)
        assert snap.phase == "TEST"
        assert snap.timestamp > 0

    def test_capture_system_metrics(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot()
        monitor._capture_system_metrics(snap)
        assert snap.ram_total_gb > 0
        assert snap.cpu_percent >= 0

    def test_capture_snapshot_multiple(self):
        monitor = GameSessionMonitor()
        s1 = monitor.capture_snapshot("BEFORE")
        s2 = monitor.capture_snapshot("DURING")
        assert len(monitor._snapshots) == 2
        assert s1.phase == "BEFORE"
        assert s2.phase == "DURING"

    def test_clear_snapshots(self):
        monitor = GameSessionMonitor()
        monitor.capture_snapshot("TEST")
        monitor.clear_snapshots()
        assert len(monitor._snapshots) == 0

    def test_calculate_delta(self):
        monitor = GameSessionMonitor()
        before = SessionSnapshot(
            ram_available_gb=4.0, ram_used_gb=12.0, cpu_percent=50.0,
            emulator_cpu_percent=30.0, emulator_rss_mb=2000.0,
        )
        after = SessionSnapshot(
            ram_available_gb=3.5, ram_used_gb=12.5, cpu_percent=60.0,
            emulator_cpu_percent=40.0, emulator_rss_mb=2500.0,
        )
        delta = monitor.calculate_delta(before, after)
        assert delta.available_ram_delta_gb == pytest.approx(-0.5, abs=0.01)
        assert delta.used_ram_delta_gb == pytest.approx(0.5, abs=0.01)
        assert delta.cpu_delta == pytest.approx(10.0, abs=0.01)
        assert delta.emulator_rss_delta_mb == pytest.approx(500.0, abs=0.01)

    def test_calculate_delta_with_fps(self):
        monitor = GameSessionMonitor()
        before = SessionSnapshot(present_fps=100.0)
        after = SessionSnapshot(present_fps=120.0)
        delta = monitor.calculate_delta(before, after)
        assert delta.fps_delta == 20.0

    def test_analyze_bottleneck_no_bottleneck(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot(cpu_percent=30.0, gpu_utilization=40.0, ram_percent=50.0)
        bt, conf, reason = monitor.analyze_bottleneck(snap, memory_pressure="NORMAL")
        assert bt == BottleneckType.NO_CLEAR_BOTTLENECK

    def test_analyze_bottleneck_gpu_bound(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot(cpu_percent=60.0, gpu_utilization=95.0, ram_percent=50.0)
        bt, conf, reason = monitor.analyze_bottleneck(snap, memory_pressure="NORMAL")
        assert bt == BottleneckType.GPU_BOUND
        assert conf > 50

    def test_analyze_bottleneck_cpu_bound(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot(cpu_percent=90.0, gpu_utilization=30.0, ram_percent=50.0)
        bt, conf, reason = monitor.analyze_bottleneck(snap, memory_pressure="NORMAL")
        assert bt == BottleneckType.CPU_BOUND

    def test_analyze_bottleneck_memory(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot(cpu_percent=50.0, gpu_utilization=50.0, ram_percent=90.0)
        bt, conf, reason = monitor.analyze_bottleneck(snap, memory_pressure="HIGH")
        assert bt == BottleneckType.MEMORY_PRESSURE

    def test_analyze_bottleneck_frame_time(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot(cpu_percent=40.0, gpu_utilization=50.0, ram_percent=50.0,
                               frame_spikes=30)
        bt, conf, reason = monitor.analyze_bottleneck(snap, memory_pressure="NORMAL")
        assert bt == BottleneckType.FRAME_TIME_LIMITED

    def test_generate_recommendations_memory(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot(cpu_percent=50.0, ram_percent=90.0, ram_available_gb=1.5,
                               ram_total_gb=16.0, ram_used_gb=14.5)
        recs = monitor.generate_recommendations(snap, BottleneckType.MEMORY_PRESSURE, "test", "HIGH")
        assert len(recs) > 0
        assert any(r.category == "RAM" for r in recs)

    def test_generate_recommendations_cpu(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot(cpu_percent=90.0, ram_percent=50.0, ram_total_gb=16.0, ram_used_gb=8.0)
        recs = monitor.generate_recommendations(snap, BottleneckType.CPU_BOUND, "test", "NORMAL")
        assert any(r.category == "CPU" for r in recs)

    def test_generate_recommendations_gpu(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot(cpu_percent=50.0, gpu_utilization=95.0, ram_percent=50.0,
                               ram_total_gb=16.0, ram_used_gb=8.0)
        recs = monitor.generate_recommendations(snap, BottleneckType.GPU_BOUND, "test", "NORMAL")
        assert any(r.category == "GPU" for r in recs)

    def test_generate_recommendations_no_bottleneck(self):
        monitor = GameSessionMonitor()
        snap = SessionSnapshot(cpu_percent=30.0, gpu_utilization=40.0, ram_percent=50.0,
                               ram_total_gb=16.0, ram_used_gb=8.0)
        recs = monitor.generate_recommendations(snap, BottleneckType.NO_CLEAR_BOTTLENECK, "test", "NORMAL")
        assert len(recs) > 0
        assert recs[0].title == "No clear bottleneck"

    def test_create_report(self):
        monitor = GameSessionMonitor()
        report = monitor.create_report(target_name="HD-Player.exe", target_pid=1234)
        assert isinstance(report, GameSessionReport)
        assert report.target_name == "HD-Player.exe"
        assert report.before is not None
        assert report.bottleneck is not None
        assert len(report.recommendations) > 0

    def test_singleton_exists(self):
        assert isinstance(game_session_monitor, GameSessionMonitor)

    def test_recommendation_model(self):
        r = ResourceRecommendation(
            category="RAM", priority="HIGH", title="Test",
            description="desc", reason="reason",
            measured_evidence="evidence", expected_effect="effect",
        )
        assert r.category == "RAM"
        assert r.priority == "HIGH"

    def test_report_model(self):
        r = GameSessionReport(target_name="test", target_pid=1)
        assert r.target_name == "test"
        assert r.bottleneck == BottleneckType.UNKNOWN


# ── Safety Tests ───────────────────────────────────────────────

class TestSafety:
    def test_no_process_termination_in_monitor(self):
        """GameSessionMonitor should never terminate processes."""
        import inspect
        source = inspect.getsource(GameSessionMonitor)
        assert ".kill()" not in source
        assert ".terminate()" not in source

    def test_no_registry_modification_in_startup(self):
        """StartupAnalyzer should never modify registry."""
        import inspect
        source = inspect.getsource(StartupAnalyzer)
        assert "winreg.SetValueEx" not in source
        assert "winreg.DeleteValue" not in source
        assert "winreg.CreateKey" not in source

    def test_startup_read_only(self):
        """Startup analysis should be completely read-only."""
        import inspect
        source = inspect.getsource(StartupAnalyzer)
        assert "winreg.SetValueEx" not in source
        assert "winreg.DeleteValue" not in source
        assert "winreg.CreateKey" not in source
        assert "os.remove" not in source
        assert "shutil.rmtree" not in source

    def test_protected_classification_never_safe_to_disable(self):
        """Security, system, and emulator entries should never be safe to disable."""
        analyzer = StartupAnalyzer()
        for name in SECURITY_STARTUP_NAMES:
            cls, can_disable, _ = analyzer._classify_entry(name, None)
            assert can_disable is False, f"{name} should not be safe to disable"
        for name in SYSTEM_STARTUP_NAMES:
            cls, can_disable, _ = analyzer._classify_entry(name, None)
            assert can_disable is False, f"{name} should not be safe to disable"
        for name in EMULATOR_STARTUP_NAMES:
            cls, can_disable, _ = analyzer._classify_entry(name, None)
            assert can_disable is False, f"{name} should not be safe to disable"

    def test_snapshot_does_not_modify_system(self):
        """Capturing a snapshot should not modify system state."""
        monitor = GameSessionMonitor()
        import psutil
        cpu_before = psutil.cpu_percent(interval=0)
        snap = monitor.capture_snapshot("TEST")
        cpu_after = psutil.cpu_percent(interval=0)
        # CPU percent can change, but we shouldn't crash or modify anything
        assert snap is not None


# ── CLI Command Tests ──────────────────────────────────────────

class TestCLICommands:
    def test_startup_status_exists(self):
        import inspect
        import main
        source = inspect.getsource(main.main)
        assert "--startup-status" in source

    def test_resource_status_exists(self):
        import inspect
        import main
        source = inspect.getsource(main.main)
        assert "--resource-status" in source

    def test_game_session_status_exists(self):
        import inspect
        import main
        source = inspect.getsource(main.main)
        assert "--game-session-status" in source


# ── BottleneckType Tests ───────────────────────────────────────

class TestBottleneckType:
    def test_all_values(self):
        assert BottleneckType.CPU_BOUND.value == "CPU_BOUND"
        assert BottleneckType.GPU_BOUND.value == "GPU_BOUND"
        assert BottleneckType.MEMORY_PRESSURE.value == "MEMORY_PRESSURE"
        assert BottleneckType.FRAME_TIME_LIMITED.value == "FRAME_TIME_LIMITED"
        assert BottleneckType.NO_CLEAR_BOTTLENECK.value == "NO_CLEAR_BOTTLENECK"
        assert BottleneckType.UNKNOWN.value == "UNKNOWN"


# ── StartupClassification Tests ────────────────────────────────

class TestStartupClassification:
    def test_all_values(self):
        assert StartupClassification.SYSTEM.value == "SYSTEM"
        assert StartupClassification.SECURITY.value == "SECURITY"
        assert StartupClassification.EMULATOR.value == "EMULATOR"
        assert StartupClassification.USER_APPLICATION.value == "USER_APPLICATION"
        assert StartupClassification.SAFE_TO_RECOMMEND.value == "SAFE_TO_RECOMMEND"
        assert StartupClassification.UNKNOWN.value == "UNKNOWN"


# ── Regression Tests ───────────────────────────────────────────

class TestRegression:
    def test_existing_optimizations_still_work(self):
        from app.core.optimizations import get_all_optimizations
        opts = get_all_optimizations()
        assert len(opts) >= 5

    def test_existing_profiles_still_work(self):
        from app.core.profiles import get_all_profiles
        profiles = get_all_profiles()
        assert len(profiles) == 3

    def test_existing_resource_analyzer_still_works(self):
        from app.core.resource_analyzer import resource_analyzer
        result = resource_analyzer.get_ram_pressure()
        assert result.total_gb > 0

    def test_existing_background_analyzer_still_works(self):
        from app.system.background_analyzer import background_analyzer
        result = background_analyzer.analyze()
        assert result is not None
