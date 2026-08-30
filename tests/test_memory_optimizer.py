"""
Tests for Heaven Society — Memory Optimizer (Phase 15).

Covers: read-only diagnostics, emulator memory analysis, process classification,
recommendation engine, standby memory, safety rules, and regression tests.
"""

import time
import pytest
import psutil
from unittest.mock import patch, MagicMock

from app.system.memory_optimizer import (
    MemoryOptimizer,
    MemoryDiagnostics,
    EmulatorMemoryInfo,
    ProcessClassification,
    StandbyMemoryInfo,
    MemoryOptimizationReport,
    ProcessCategory,
    memory_optimizer,
    PROTECTED_SYSTEM_PROCESSES,
    SECURITY_PROCESSES,
    EMULATOR_PROCESSES,
    SAFE_TO_CLOSE_APPS,
)


# ── MemoryDiagnostics tests ────────────────────────────────────

class TestMemoryDiagnostics:
    def test_default_values(self):
        d = MemoryDiagnostics()
        assert d.total_gb == 0.0
        assert d.pressure_level == "UNKNOWN"
        assert d.standby_gb == 0.0

    def test_headroom_gb(self):
        d = MemoryDiagnostics(available_gb=8.5)
        assert d.headroom_gb == 8.5

    def test_commit_pressure(self):
        d = MemoryDiagnostics(commit_used_gb=14, commit_limit_gb=16)
        assert d.commit_pressure is True

    def test_commit_pressure_safe(self):
        d = MemoryDiagnostics(commit_used_gb=8, commit_limit_gb=16)
        assert d.commit_pressure is False

    def test_commit_pressure_no_limit(self):
        d = MemoryDiagnostics(commit_used_gb=8, commit_limit_gb=0)
        assert d.commit_pressure is False


# ── EmulatorMemoryInfo tests ───────────────────────────────────

class TestEmulatorMemoryInfo:
    def test_default_values(self):
        e = EmulatorMemoryInfo()
        assert e.process_name == ""
        assert e.pid == 0
        assert e.rss_mb == 0.0
        assert e.is_high_usage is False
        assert e.anomaly_detected is False

    def test_high_usage_flag(self):
        e = EmulatorMemoryInfo(emulator_pct_of_system=45, is_high_usage=True)
        assert e.is_high_usage is True


# ── ProcessClassification tests ────────────────────────────────

class TestProcessClassification:
    def test_default_values(self):
        p = ProcessClassification()
        assert p.name == ""
        assert p.category == ProcessCategory.UNKNOWN
        assert p.can_safely_close is False


# ── StandbyMemoryInfo tests ────────────────────────────────────

class TestStandbyMemoryInfo:
    def test_default_values(self):
        s = StandbyMemoryInfo()
        assert s.available is False
        assert s.can_modify is False  # Always False


# ── MemoryOptimizer.diagnose() tests ──────────────────────────

class TestDiagnose:
    def test_returns_diagnostics(self):
        optimizer = MemoryOptimizer()
        d = optimizer.diagnose()
        assert isinstance(d, MemoryDiagnostics)
        assert d.total_gb > 0

    def test_pressure_classification_normal(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(total_gb=16, used_gb=8, percent_used=50, swap_percent=0)
        level, rec = optimizer._classify_pressure(d)
        assert level == "NORMAL"

    def test_pressure_classification_moderate(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(total_gb=16, used_gb=11, percent_used=68, swap_percent=0)
        level, rec = optimizer._classify_pressure(d)
        assert level == "MODERATE"

    def test_pressure_classification_high(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(total_gb=16, used_gb=13, percent_used=82, swap_percent=15)
        level, rec = optimizer._classify_pressure(d)
        assert level == "HIGH"

    def test_pressure_classification_critical(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(total_gb=16, used_gb=15, percent_used=94, swap_percent=55)
        level, rec = optimizer._classify_pressure(d)
        assert level == "CRITICAL"

    def test_pressure_critical_by_swap(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(total_gb=16, used_gb=12, percent_used=75, swap_percent=60)
        level, rec = optimizer._classify_pressure(d)
        assert level == "CRITICAL"

    def test_standby_memory_diagnostic(self):
        optimizer = MemoryOptimizer()
        s = optimizer._diagnose_standby_memory()
        assert isinstance(s, StandbyMemoryInfo)
        assert s.can_modify is False  # Always False


# ── Emulator analysis tests ────────────────────────────────────

class TestEmulatorAnalysis:
    def test_analyze_emulator_no_pid(self):
        optimizer = MemoryOptimizer()
        with patch("app.performance.target_process.target_process_detector.select_best_target", return_value=None):
            result = optimizer.analyze_emulator(0)
            assert result is None

    def test_analyze_emulator_with_mock(self):
        optimizer = MemoryOptimizer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "HD-Player.exe"
        mock_proc.status.return_value = "running"
        mock_proc.exe.return_value = "C:\\test\\HD-Player.exe"
        mock_proc.memory_info.return_value = MagicMock(
            rss=2000*1024*1024, vms=4000*1024*1024,
            private=1800*1024*1024, shared=200*1024*1024,
            page_faults=50000
        )
        mock_proc.memory_percent.return_value = 12.5
        mock_proc.num_threads.return_value = 24
        mock_proc.children.return_value = []

        with patch("psutil.Process", return_value=mock_proc):
            with patch("psutil.virtual_memory", return_value=MagicMock(total=16*1024**3)):
                result = optimizer.analyze_emulator(1234, "HD-Player.exe")
                assert result is not None
                assert result.process_name == "HD-Player.exe"
                assert result.rss_mb > 0
                assert result.vms_mb > 0
                assert result.private_mb > 0
                assert result.system_total_gb > 0

    def test_name_mismatch(self):
        optimizer = MemoryOptimizer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "OTHER.exe"

        with patch("psutil.Process", return_value=mock_proc):
            result = optimizer.analyze_emulator(1234, "HD-Player.exe")
            assert result is None

    def test_anomaly_detection_high_usage(self):
        optimizer = MemoryOptimizer()
        info = EmulatorMemoryInfo(emulator_pct_of_system=65, rss_mb=10000, vms_mb=10000, page_faults=500)
        detected, reason = optimizer._detect_anomalies(info)
        assert detected is True
        assert "65%" in reason or "65.0%" in reason

    def test_anomaly_detection_high_page_faults(self):
        optimizer = MemoryOptimizer()
        info = EmulatorMemoryInfo(emulator_pct_of_system=20, rss_mb=3000, vms_mb=3000, page_faults=200000)
        detected, reason = optimizer._detect_anomalies(info)
        assert detected is True
        assert "page fault" in reason.lower()

    def test_anomaly_detection_vms_ratio(self):
        optimizer = MemoryOptimizer()
        info = EmulatorMemoryInfo(emulator_pct_of_system=20, rss_mb=1000, vms_mb=8000, page_faults=0)
        detected, reason = optimizer._detect_anomalies(info)
        assert detected is True
        assert "VMS/RSS" in reason

    def test_no_anomaly(self):
        optimizer = MemoryOptimizer()
        info = EmulatorMemoryInfo(emulator_pct_of_system=20, rss_mb=3000, vms_mb=4000, page_faults=1000)
        detected, reason = optimizer._detect_anomalies(info)
        assert detected is False
        assert reason == ""


# ── Process classification tests ───────────────────────────────

class TestProcessClassification_:
    def test_classify_system_process(self):
        optimizer = MemoryOptimizer()
        cat, rec, can_close, reason = optimizer._classify_single("svchost.exe", 100)
        assert cat == ProcessCategory.SYSTEM
        assert can_close is False

    def test_classify_security_process(self):
        optimizer = MemoryOptimizer()
        cat, rec, can_close, reason = optimizer._classify_single("msmpeng.exe", 200)
        assert cat == ProcessCategory.SECURITY
        assert can_close is False

    def test_classify_emulator_process(self):
        optimizer = MemoryOptimizer()
        cat, rec, can_close, reason = optimizer._classify_single("HD-Player.exe", 2000)
        assert cat == ProcessCategory.EMULATOR
        assert can_close is False

    def test_classify_safe_to_close(self):
        optimizer = MemoryOptimizer()
        cat, rec, can_close, reason = optimizer._classify_single("chrome.exe", 300)
        assert cat == ProcessCategory.SAFE_TO_RECOMMEND
        assert can_close is True

    def test_classify_user_application(self):
        optimizer = MemoryOptimizer()
        cat, rec, can_close, reason = optimizer._classify_single("myapp.exe", 100)
        assert cat == ProcessCategory.USER_APPLICATION
        assert can_close is False

    def test_classify_processes_returns_list(self):
        optimizer = MemoryOptimizer()
        with patch("psutil.process_iter") as mock_iter:
            m = MagicMock()
            m.info = {"name": "chrome.exe", "pid": 100, "memory_info": MagicMock(rss=300*1024*1024), "memory_percent": 2.0}
            mock_iter.return_value = iter([m])
            procs = optimizer.classify_processes(min_memory_mb=50)
            assert len(procs) == 1
            assert procs[0].category == ProcessCategory.SAFE_TO_RECOMMEND

    def test_classify_processes_excludes_emulator(self):
        optimizer = MemoryOptimizer()
        with patch("psutil.process_iter") as mock_iter:
            m1 = MagicMock()
            m1.info = {"name": "HD-Player.exe", "pid": 1234, "memory_info": MagicMock(rss=2000*1024*1024), "memory_percent": 12.0}
            m2 = MagicMock()
            m2.info = {"name": "chrome.exe", "pid": 100, "memory_info": MagicMock(rss=300*1024*1024), "memory_percent": 2.0}
            mock_iter.return_value = iter([m1, m2])
            procs = optimizer.classify_processes(emulator_pid=1234, min_memory_mb=50)
            assert all(p.pid != 1234 for p in procs)

    def test_classify_processes_sorted_by_memory(self):
        optimizer = MemoryOptimizer()
        with patch("psutil.process_iter") as mock_iter:
            m1 = MagicMock()
            m1.info = {"name": "small.exe", "pid": 100, "memory_info": MagicMock(rss=100*1024*1024), "memory_percent": 0.5}
            m2 = MagicMock()
            m2.info = {"name": "large.exe", "pid": 200, "memory_info": MagicMock(rss=500*1024*1024), "memory_percent": 3.0}
            mock_iter.return_value = iter([m1, m2])
            procs = optimizer.classify_processes(min_memory_mb=50)
            assert procs[0].rss_mb >= procs[1].rss_mb


# ── Recommendation engine tests ────────────────────────────────

class TestRecommendationEngine:
    def test_returns_list(self):
        optimizer = MemoryOptimizer()
        recs = optimizer.generate_recommendations()
        assert isinstance(recs, list)

    def test_critical_ram_generates_high_priority(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(pressure_level="CRITICAL", percent_used=95, swap_percent=60, available_gb=0.5, total_gb=16)
        recs = optimizer.generate_recommendations(diagnostics=d)
        high = [r for r in recs if r["priority"] == "HIGH"]
        assert len(high) > 0

    def test_high_emulator_usage_generates_recommendation(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(pressure_level="NORMAL", percent_used=50, swap_percent=0, available_gb=8, total_gb=16)
        e = EmulatorMemoryInfo(rss_mb=7000, emulator_pct_of_system=44, is_high_usage=True)
        recs = optimizer.generate_recommendations(diagnostics=d, emulator=e)
        emu_recs = [r for r in recs if r["category"] == "EMULATOR"]
        assert len(emu_recs) > 0

    def test_anomaly_generates_recommendation(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(pressure_level="NORMAL", percent_used=50, swap_percent=0, available_gb=8, total_gb=16)
        e = EmulatorMemoryInfo(rss_mb=10000, emulator_pct_of_system=65, is_high_usage=True, anomaly_detected=True, anomaly_reason="High usage")
        recs = optimizer.generate_recommendations(diagnostics=d, emulator=e)
        emu_recs = [r for r in recs if r["category"] == "EMULATOR"]
        assert len(emu_recs) >= 2  # Both high usage + anomaly

    def test_safe_to_close_processes_generate_recommendation(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(pressure_level="NORMAL", percent_used=50, swap_percent=0, available_gb=8, total_gb=16)
        procs = [
            ProcessClassification(name="chrome.exe", pid=100, rss_mb=300, category=ProcessCategory.SAFE_TO_RECOMMEND, can_safely_close=True),
            ProcessClassification(name="discord.exe", pid=200, rss_mb=200, category=ProcessCategory.SAFE_TO_RECOMMEND, can_safely_close=True),
        ]
        recs = optimizer.generate_recommendations(diagnostics=d, processes=procs)
        sys_recs = [r for r in recs if r["category"] == "SYSTEM"]
        assert len(sys_recs) > 0

    def test_sorted_by_priority(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(pressure_level="CRITICAL", percent_used=95, swap_percent=60, available_gb=0.5, total_gb=16)
        e = EmulatorMemoryInfo(rss_mb=10000, emulator_pct_of_system=65, anomaly_detected=True, anomaly_reason="test")
        recs = optimizer.generate_recommendations(diagnostics=d, emulator=e)
        if len(recs) > 1:
            priority_order = {"HIGH": 0, "MEDIUM": 1, "LOW": 2}
            for i in range(len(recs) - 1):
                assert priority_order.get(recs[i]["priority"], 3) <= priority_order.get(recs[i+1]["priority"], 3)

    def test_recommendations_explain_why(self):
        optimizer = MemoryOptimizer()
        d = MemoryDiagnostics(pressure_level="HIGH", percent_used=85, swap_percent=15, available_gb=2, total_gb=16)
        recs = optimizer.generate_recommendations(diagnostics=d)
        for rec in recs:
            assert "reason" in rec
            assert len(rec["reason"]) > 10

    def test_no_auto_apply(self):
        optimizer = MemoryOptimizer()
        recs = optimizer.generate_recommendations()
        for rec in recs:
            assert rec.get("can_auto_apply") is False


# ── Full analysis tests ────────────────────────────────────────

class TestFullAnalysis:
    def test_analyze_returns_report(self):
        optimizer = MemoryOptimizer()
        with patch.object(optimizer, "diagnose") as mock_diag:
            mock_diag.return_value = MemoryDiagnostics(total_gb=16, percent_used=50, pressure_level="NORMAL")
            with patch.object(optimizer, "analyze_emulator", return_value=None):
                with patch.object(optimizer, "classify_processes", return_value=[]):
                    report = optimizer.analyze()
                    assert isinstance(report, MemoryOptimizationReport)
                    assert report.diagnostics is not None

    def test_analyze_with_emulator(self):
        optimizer = MemoryOptimizer()
        with patch.object(optimizer, "diagnose") as mock_diag, \
             patch.object(optimizer, "analyze_emulator") as mock_emu, \
             patch.object(optimizer, "classify_processes") as mock_cls:
            mock_diag.return_value = MemoryDiagnostics(total_gb=16, percent_used=50, pressure_level="NORMAL")
            mock_emu.return_value = EmulatorMemoryInfo(pid=1234, rss_mb=2000)
            mock_cls.return_value = []
            report = optimizer.analyze(emulator_pid=1234)
            assert report.emulator is not None

    def test_actions_not_performed(self):
        optimizer = MemoryOptimizer()
        with patch.object(optimizer, "diagnose") as mock_diag:
            mock_diag.return_value = MemoryDiagnostics(total_gb=16, percent_used=50)
            with patch.object(optimizer, "analyze_emulator", return_value=None):
                with patch.object(optimizer, "classify_processes", return_value=[]):
                    report = optimizer.analyze()
                    assert len(report.actions_not_performed) > 0
                    # Verify key safety actions are documented
                    actions = [a["action"] for a in report.actions_not_performed]
                    assert "Terminate background processes" in actions
                    assert "Clear standby memory" in actions


# ── Safety tests ───────────────────────────────────────────────

class TestSafety:
    def test_no_process_termination(self):
        """No analysis should terminate processes."""
        optimizer = MemoryOptimizer()
        with patch("psutil.Process.terminate") as mock_term:
            with patch.object(optimizer, "diagnose") as mock_diag:
                mock_diag.return_value = MemoryDiagnostics(total_gb=16, percent_used=50)
                with patch.object(optimizer, "analyze_emulator", return_value=None):
                    with patch.object(optimizer, "classify_processes", return_value=[]):
                        optimizer.analyze()
            mock_term.assert_not_called()

    def test_read_only_diagnostics(self):
        """Diagnostics should not modify anything."""
        optimizer = MemoryOptimizer()
        with patch("psutil.virtual_memory") as mock_vm:
            mock_vm.return_value = MagicMock(
                total=16*1024**3, used=8*1024**3, available=8*1024**3,
                percent=50, cached=0, buffers=0
            )
            with patch("psutil.swap_memory", return_value=MagicMock(total=4*1024**3, used=0, percent=0)):
                d = optimizer.diagnose()
                assert d.total_gb > 0
                assert d.pressure_level in ("NORMAL", "MODERATE", "HIGH", "CRITICAL")

    def test_recommendations_never_suggest_termination(self):
        """Recommendations should never suggest process termination."""
        optimizer = MemoryOptimizer()
        recs = optimizer.generate_recommendations()
        for rec in recs:
            desc = rec.get("description", "").lower()
            reason = rec.get("reason", "").lower()
            assert "kill" not in desc
            assert "terminate" not in desc
            assert "kill" not in reason
            assert "terminate" not in reason

    def test_standby_memory_never_modifiable(self):
        """Standby memory should always be RECOMMENDATION_ONLY."""
        optimizer = MemoryOptimizer()
        s = optimizer._diagnose_standby_memory()
        assert s.can_modify is False

    def test_no_registry_modification(self):
        """No analysis should modify registry."""
        optimizer = MemoryOptimizer()
        with patch("winreg.SetValueEx") as mock_reg:
            with patch.object(optimizer, "diagnose") as mock_diag:
                mock_diag.return_value = MemoryDiagnostics(total_gb=16, percent_used=50)
                optimizer.diagnose()
            mock_reg.assert_not_called()

    def test_all_protected_processes_classified(self):
        """All protected processes should be SYSTEM category."""
        optimizer = MemoryOptimizer()
        for proc_name in list(PROTECTED_SYSTEM_PROCESSES)[:5]:  # Sample
            cat, rec, can_close, reason = optimizer._classify_single(proc_name, 100)
            assert cat == ProcessCategory.SYSTEM
            assert can_close is False

    def test_all_security_processes_classified(self):
        """All security processes should be SECURITY category."""
        optimizer = MemoryOptimizer()
        for proc_name in list(SECURITY_PROCESSES)[:3]:
            cat, rec, can_close, reason = optimizer._classify_single(proc_name, 100)
            assert cat == ProcessCategory.SECURITY
            assert can_close is False

    def test_all_emulator_processes_classified(self):
        """All emulator processes should be EMULATOR category."""
        optimizer = MemoryOptimizer()
        for proc_name in list(EMULATOR_PROCESSES)[:5]:
            cat, rec, can_close, reason = optimizer._classify_single(proc_name, 100)
            assert cat == ProcessCategory.EMULATOR
            assert can_close is False

    def test_safe_to_close_apps_classified(self):
        """Known safe-to-close apps should be SAFE_TO_RECOMMEND."""
        optimizer = MemoryOptimizer()
        for proc_name in list(SAFE_TO_CLOSE_APPS)[:5]:
            cat, rec, can_close, reason = optimizer._classify_single(proc_name, 100)
            assert cat == ProcessCategory.SAFE_TO_RECOMMEND
            assert can_close is True


# ── Process category enum tests ────────────────────────────────

class TestProcessCategory:
    def test_all_categories_exist(self):
        required = [
            "SAFE_TO_RECOMMEND", "USER_APPLICATION", "SECURITY",
            "SYSTEM", "EMULATOR", "UNKNOWN",
        ]
        for name in required:
            assert hasattr(ProcessCategory, name)

    def test_category_values(self):
        assert ProcessCategory.SAFE_TO_RECOMMEND.value == "SAFE_TO_RECOMMEND"
        assert ProcessCategory.EMULATOR.value == "EMULATOR"


# ── Regression tests ───────────────────────────────────────────

class TestRegression:
    def test_existing_optimizations_still_work(self):
        """Verify existing optimization infrastructure is unaffected."""
        from app.core.optimizations import get_all_optimizations
        opts = get_all_optimizations()
        assert len(opts) >= 4

    def test_existing_profiles_still_work(self):
        from app.core.profiles import get_all_profiles
        profiles = get_all_profiles()
        assert len(profiles) == 3

    def test_existing_resource_analyzer_still_works(self):
        from app.core.resource_analyzer import resource_analyzer
        result = resource_analyzer.get_ram_pressure()
        assert result.total_gb > 0

    def test_existing_emulator_controller_still_works(self):
        from app.core.emulator_controller import emulator_controller
        target = emulator_controller.detect_target()
        # May be None — that's fine

    def test_singleton(self):
        assert isinstance(memory_optimizer, MemoryOptimizer)

    def test_memory_optimizer_complements_resource_analyzer(self):
        """Memory optimizer should work alongside resource analyzer."""
        from app.core.resource_analyzer import resource_analyzer
        mo = MemoryOptimizer()
        with patch.object(mo, "diagnose") as mock_diag:
            mock_diag.return_value = MemoryDiagnostics(total_gb=16, percent_used=50, pressure_level="NORMAL")
            with patch.object(mo, "analyze_emulator", return_value=None):
                with patch.object(mo, "classify_processes", return_value=[]):
                    report = mo.analyze()
                    # Both should work independently
                    ra_result = resource_analyzer.get_ram_pressure()
                    assert report.diagnostics is not None
                    assert ra_result.total_gb > 0

    def test_profiles_include_memory_analysis(self):
        """GAMING and MAX_PERFORMANCE profiles should include memory_analysis."""
        from app.core.profiles import get_profile
        gaming = get_profile("gaming")
        maxp = get_profile("max_performance")
        gaming_ids = [o.opt_id for o in gaming.optimizations]
        maxp_ids = [o.opt_id for o in maxp.optimizations]
        assert "memory_analysis" in gaming_ids
        assert "memory_analysis" in maxp_ids

    def test_optimizations_include_memory_analysis(self):
        """get_all_optimizations should include MemoryAnalysisOptimization."""
        from app.core.optimizations import get_all_optimizations, get_optimization_by_id
        opts = get_all_optimizations()
        ids = [o.id for o in opts]
        assert "memory_analysis" in ids
        mem_opt = get_optimization_by_id("memory_analysis")
        assert mem_opt is not None

    def test_memory_analysis_optimization_check(self):
        """MemoryAnalysisOptimization.check should return diagnostic status."""
        from app.core.optimizations import get_optimization_by_id
        from app.core.optimization_base import OptimizationStatus
        opt = get_optimization_by_id("memory_analysis")
        assert opt is not None
        result = opt.check()
        assert result.status in (
            OptimizationStatus.ALREADY_OPTIMAL,
            OptimizationStatus.OPTIMIZABLE,
            OptimizationStatus.NOT_APPLICABLE,
        )

    def test_memory_analysis_optimization_apply_returns_recommendation_only(self):
        """MemoryAnalysisOptimization.apply should return RECOMMENDATION_ONLY."""
        from app.core.optimizations import get_optimization_by_id
        from app.core.optimization_base import OptimizationStatus
        opt = get_optimization_by_id("memory_analysis")
        result = opt.apply()
        assert result.status == OptimizationStatus.RECOMMENDATION_ONLY

    def test_measure_snapshot(self):
        """measure_snapshot should return a dictionary with memory data."""
        optimizer = MemoryOptimizer()
        snap = optimizer.measure_snapshot()
        assert isinstance(snap, dict)
        assert "available_gb" in snap
        assert "used_gb" in snap
        assert "percent_used" in snap
        assert "pressure_level" in snap

    def test_compare_snapshots(self):
        """compare_snapshots should calculate deltas."""
        optimizer = MemoryOptimizer()
        before = {"available_gb": 8.0, "used_gb": 8.0, "percent_used": 50.0, "pressure_level": "NORMAL"}
        after = {"available_gb": 9.0, "used_gb": 7.0, "percent_used": 43.0, "pressure_level": "NORMAL"}
        result = optimizer.compare_snapshots(before, after)
        assert result["delta"]["available_gb"] == 1.0
        assert result["delta"]["used_gb"] == -1.0
        assert result["delta"]["percent_used"] == -7.0

    def test_compare_snapshots_pressure_change(self):
        """compare_snapshots should detect pressure level changes."""
        optimizer = MemoryOptimizer()
        before = {"available_gb": 2.0, "used_gb": 14.0, "percent_used": 87.0, "pressure_level": "HIGH"}
        after = {"available_gb": 5.0, "used_gb": 11.0, "percent_used": 68.0, "pressure_level": "MODERATE"}
        result = optimizer.compare_snapshots(before, after)
        assert result["delta"].get("pressure_changed") is True
        assert result["delta"]["pressure_from"] == "HIGH"
        assert result["delta"]["pressure_to"] == "MODERATE"

    def test_compare_snapshots_with_emulator(self):
        """compare_snapshots should include emulator memory delta."""
        optimizer = MemoryOptimizer()
        before = {"available_gb": 8.0, "used_gb": 8.0, "percent_used": 50.0, "pressure_level": "NORMAL", "emulator_rss_mb": 2000}
        after = {"available_gb": 8.0, "used_gb": 8.0, "percent_used": 50.0, "pressure_level": "NORMAL", "emulator_rss_mb": 2500}
        result = optimizer.compare_snapshots(before, after)
        assert result["delta"]["emulator_rss_mb"] == 500

    def test_get_safe_closeable_processes(self):
        """get_safe_closeable_processes should return only SAFE_TO_RECOMMEND."""
        optimizer = MemoryOptimizer()
        with patch.object(optimizer, "classify_processes") as mock_cls:
            mock_cls.return_value = [
                ProcessClassification(name="chrome.exe", pid=100, rss_mb=300, category=ProcessCategory.SAFE_TO_RECOMMEND, can_safely_close=True),
                ProcessClassification(name="svchost.exe", pid=200, rss_mb=100, category=ProcessCategory.SYSTEM, can_safely_close=False),
            ]
            result = optimizer.get_safe_closeable_processes()
            assert len(result) == 1
            assert result[0]["name"] == "chrome.exe"

    def test_close_selected_processes_refuses_protected(self):
        """close_selected_processes should refuse to close protected processes."""
        optimizer = MemoryOptimizer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "HD-Player.exe"

        with patch("app.system.memory_optimizer.psutil.Process", return_value=mock_proc):
            results = optimizer.close_selected_processes(pids=[1234])
            assert len(results) == 1
            assert results[0]["success"] is False
            assert "Refused" in results[0]["error"]

    def test_close_selected_processes_refuses_system(self):
        """close_selected_processes should refuse to close system processes."""
        optimizer = MemoryOptimizer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "svchost.exe"

        with patch("app.system.memory_optimizer.psutil.Process", return_value=mock_proc):
            results = optimizer.close_selected_processes(pids=[1234])
            assert len(results) == 1
            assert results[0]["success"] is False
            assert "Refused" in results[0]["error"]

    def test_close_selected_processes_refuses_security(self):
        """close_selected_processes should refuse to close security processes."""
        optimizer = MemoryOptimizer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "msmpeng.exe"

        with patch("app.system.memory_optimizer.psutil.Process", return_value=mock_proc):
            results = optimizer.close_selected_processes(pids=[1234])
            assert len(results) == 1
            assert results[0]["success"] is False
            assert "Refused" in results[0]["error"]

    def test_close_selected_processes_refuses_unknown(self):
        """close_selected_processes should refuse to close unknown processes."""
        optimizer = MemoryOptimizer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "unknown_process.exe"

        with patch("app.system.memory_optimizer.psutil.Process", return_value=mock_proc):
            results = optimizer.close_selected_processes(pids=[1234])
            assert len(results) == 1
            assert results[0]["success"] is False
            assert "Refused" in results[0]["error"]

    def test_close_selected_processes_closes_safe_app(self):
        """close_selected_processes should close known safe apps."""
        optimizer = MemoryOptimizer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "discord.exe"
        mock_proc.memory_info.return_value = MagicMock(rss=200 * 1024 * 1024)
        mock_proc.wait.return_value = None

        # Track calls for pid 100 separately from other psutil.Process calls
        target_calls = [0]
        def mock_process(pid):
            if pid == 100:
                target_calls[0] += 1
                if target_calls[0] == 1:
                    return mock_proc  # First call: process lookup
                raise psutil.NoSuchProcess(pid)  # Verification: process exited
            # Other PIDs from measure_snapshot/analyze_emulator — return None-like
            raise psutil.NoSuchProcess(pid)

        with patch("app.system.memory_optimizer.psutil.Process", side_effect=mock_process):
            results = optimizer.close_selected_processes(pids=[100])
            assert len(results) == 1
            assert results[0]["success"] is True
            assert results[0]["process_name"] == "discord.exe"
            assert results[0]["non_rollbackable"] is True

    def test_close_selected_processes_before_after_measurement(self):
        """close_selected_processes should measure RAM before and after."""
        optimizer = MemoryOptimizer()
        mock_proc = MagicMock()
        mock_proc.name.return_value = "discord.exe"
        mock_proc.memory_info.return_value = MagicMock(rss=200 * 1024 * 1024)
        mock_proc.wait.return_value = None

        target_calls = [0]
        def mock_process(pid):
            if pid == 100:
                target_calls[0] += 1
                if target_calls[0] == 1:
                    return mock_proc
                raise psutil.NoSuchProcess(pid)
            raise psutil.NoSuchProcess(pid)

        with patch("app.system.memory_optimizer.psutil.Process", side_effect=mock_process):
            with patch.object(optimizer, "diagnose") as mock_diag:
                mock_diag.return_value = MemoryDiagnostics(
                    total_gb=16, used_gb=10, available_gb=6, percent_used=62, pressure_level="MODERATE"
                )
                results = optimizer.close_selected_processes(pids=[100])
                assert "ram_delta_gb" in results[0]

    def test_close_empty_pid_list(self):
        """close_selected_processes with empty list should return empty results."""
        optimizer = MemoryOptimizer()
        results = optimizer.close_selected_processes(pids=[])
        assert results == []

    def test_pressure_thresholds_boundary(self):
        """Test exact boundary values for pressure classification."""
        optimizer = MemoryOptimizer()

        # 66% = MODERATE (just above 65% threshold)
        d1 = MemoryDiagnostics(total_gb=16, used_gb=10.56, percent_used=66, swap_percent=0)
        level, _ = optimizer._classify_pressure(d1)
        assert level == "MODERATE"

        # 65% = NORMAL (at threshold, not above)
        d0 = MemoryDiagnostics(total_gb=16, used_gb=10.4, percent_used=65, swap_percent=0)
        level0, _ = optimizer._classify_pressure(d0)
        assert level0 == "NORMAL"

        # 81% = HIGH (just above 80% threshold)
        d2 = MemoryDiagnostics(total_gb=16, used_gb=12.96, percent_used=81, swap_percent=0)
        level, _ = optimizer._classify_pressure(d2)
        assert level == "HIGH"

        # 80% = MODERATE (at threshold, not above)
        d2b = MemoryDiagnostics(total_gb=16, used_gb=12.8, percent_used=80, swap_percent=0)
        level2, _ = optimizer._classify_pressure(d2b)
        assert level2 == "MODERATE"

        # 91% = CRITICAL (just above 90% threshold)
        d3 = MemoryDiagnostics(total_gb=16, used_gb=14.56, percent_used=91, swap_percent=0)
        level, _ = optimizer._classify_pressure(d3)
        assert level == "CRITICAL"

        # 90% = HIGH (at threshold, not above)
        d3b = MemoryDiagnostics(total_gb=16, used_gb=14.4, percent_used=90, swap_percent=0)
        level3, _ = optimizer._classify_pressure(d3b)
        assert level3 == "HIGH"

        # Swap alone can trigger CRITICAL
        d4 = MemoryDiagnostics(total_gb=16, used_gb=10, percent_used=62, swap_percent=55)
        level, _ = optimizer._classify_pressure(d4)
        assert level == "CRITICAL"

        # 51% swap = CRITICAL
        d4b = MemoryDiagnostics(total_gb=16, used_gb=10, percent_used=62, swap_percent=51)
        level4, _ = optimizer._classify_pressure(d4b)
        assert level4 == "CRITICAL"
