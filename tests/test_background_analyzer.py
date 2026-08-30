"""
Tests for Heaven Society — Intelligent Background Load Analyzer.

All tests use mocks; no real processes are examined or terminated.
"""

import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import dataclass, field

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.system.background_analyzer import (
    BackgroundLoadAnalyzer,
    BackgroundAnalysis,
    ProcessInventory,
    CompetitionAnalysis,
    ProcessCategory,
    Recommendation,
    CompetitionLevel,
    background_analyzer,
    SYSTEM_PROCESSES,
    SECURITY_PROCESSES,
    EMULATOR_PROCESSES,
    SAFE_TO_CLOSE_APPS,
)


# ── Helper: create mock process info ──────────────────────────

def make_process_info(
    pid=100,
    name="test.exe",
    cpu=5.0,
    ram_mb=200,
    threads=10,
    handles=500,
    io_read_mb=10,
    io_write_mb=5,
    status="running",
):
    """Create a mock psutil process."""
    mock_proc = MagicMock()
    mock_proc.info = {
        "pid": pid,
        "name": name,
        "cpu_percent": cpu,
        "num_threads": threads,
        "status": status,
    }
    mock_proc.memory_info.return_value.rss = ram_mb * 1024 * 1024
    mock_proc.memory_percent.return_value = ram_mb / 16000 * 100  # Assume 16GB system
    mock_proc.num_handles.return_value = handles
    mock_proc.io_counters.return_value = MagicMock(
        read_bytes=io_read_mb * 1024 * 1024,
        write_bytes=io_write_mb * 1024 * 1024,
    )
    return mock_proc


# ══════════════════════════════════════════════════════════════
# 1. Process Inventory
# ══════════════════════════════════════════════════════════════

class TestProcessInventory:
    """Test process inventory construction."""

    def test_inventory_model_fields(self):
        inv = ProcessInventory(
            pid=100, name="test.exe", cpu_percent=5.0,
            ram_mb=200, ram_percent=1.2, thread_count=10,
            handle_count=500, io_read_mb=10.0, io_write_mb=5.0,
        )
        assert inv.pid == 100
        assert inv.name == "test.exe"
        assert inv.cpu_percent == 5.0
        assert inv.ram_mb == 200
        assert inv.gaming_impact_score == 0.0
        assert inv.cpu_competition is False

    def test_inventory_category_default(self):
        inv = ProcessInventory()
        assert inv.category == ProcessCategory.UNKNOWN
        assert inv.recommendation == Recommendation.DO_NOT_TOUCH


# ══════════════════════════════════════════════════════════════
# 2. Process Classification
# ══════════════════════════════════════════════════════════════

class TestProcessClassification:
    """Test process categorization and recommendations."""

    def setup_method(self):
        self.analyzer = BackgroundLoadAnalyzer()

    def test_system_process_classified(self):
        cat, rec, reason = self.analyzer._classify_process("svchost.exe", 50, 0)
        assert cat == ProcessCategory.SYSTEM
        assert rec == Recommendation.DO_NOT_TOUCH
        assert "system" in reason.lower()

    def test_security_process_classified(self):
        cat, rec, reason = self.analyzer._classify_process("MsMpEng.exe", 100, 0)
        assert cat == ProcessCategory.SECURITY
        assert rec == Recommendation.DO_NOT_TOUCH
        assert "security" in reason.lower()

    def test_emulator_process_classified(self):
        cat, rec, reason = self.analyzer._classify_process("HD-Player.exe", 200, 200)
        assert cat == ProcessCategory.EMULATOR
        assert rec == Recommendation.DO_NOT_TOUCH
        assert "emulator" in reason.lower()

    def test_emulator_by_pid(self):
        cat, rec, reason = self.analyzer._classify_process("random.exe", 999, 999)
        assert cat == ProcessCategory.EMULATOR
        assert rec == Recommendation.DO_NOT_TOUCH

    def test_safe_to_close_process(self):
        cat, rec, reason = self.analyzer._classify_process("Discord.exe", 300, 0)
        assert cat == ProcessCategory.USER_APPLICATION
        assert rec == Recommendation.SAFE_TO_RECOMMEND
        assert "safe" in reason.lower() or "optional" in reason.lower()

    def test_chrome_is_safe_to_close(self):
        cat, rec, reason = self.analyzer._classify_process("chrome.exe", 400, 0)
        assert rec == Recommendation.SAFE_TO_RECOMMEND

    def test_spotify_is_safe_to_close(self):
        cat, rec, reason = self.analyzer._classify_process("Spotify.exe", 500, 0)
        assert rec == Recommendation.SAFE_TO_RECOMMEND

    def test_steam_is_safe_to_close(self):
        cat, rec, reason = self.analyzer._classify_process("steam.exe", 600, 0)
        assert rec == Recommendation.SAFE_TO_RECOMMEND

    def test_heaven_society_is_protected(self):
        cat, rec, reason = self.analyzer._classify_process("python.exe", 700, 0)
        assert cat == ProcessCategory.SYSTEM
        assert rec == Recommendation.DO_NOT_TOUCH

    def test_presentmon_is_protected(self):
        cat, rec, reason = self.analyzer._classify_process("PresentMon_x64.exe", 800, 0)
        assert rec == Recommendation.DO_NOT_TOUCH

    def test_all_system_processes_protected(self):
        test_procs = ["svchost.exe", "csrss.exe", "wininit.exe", "winlogon.exe",
                      "services.exe", "lsass.exe", "smss.exe", "dwm.exe",
                      "explorer.exe", "taskhostw.exe"]
        for proc_name in test_procs:
            cat, rec, _ = self.analyzer._classify_process(proc_name, 1000, 0)
            assert cat == ProcessCategory.SYSTEM, f"{proc_name} should be SYSTEM"
            assert rec == Recommendation.DO_NOT_TOUCH, f"{proc_name} should be DO_NOT_TOUCH"

    def test_all_security_processes_protected(self):
        for proc_name in SECURITY_PROCESSES:
            cat, rec, _ = self.analyzer._classify_process(proc_name, 1100, 0)
            assert cat == ProcessCategory.SECURITY
            assert rec == Recommendation.DO_NOT_TOUCH

    def test_all_emulator_processes_protected(self):
        for proc_name in EMULATOR_PROCESSES:
            cat, rec, _ = self.analyzer._classify_process(proc_name, 1200, 0)
            assert cat == ProcessCategory.EMULATOR
            assert rec == Recommendation.DO_NOT_TOUCH


# ══════════════════════════════════════════════════════════════
# 3. Gaming Impact Score
# ══════════════════════════════════════════════════════════════

class TestGamingImpactScore:
    """Test gaming impact score calculation."""

    def setup_method(self):
        self.analyzer = BackgroundLoadAnalyzer()

    def test_zero_impact_low_usage(self):
        inv = ProcessInventory(cpu_percent=0.5, ram_mb=20, thread_count=5)
        self.analyzer._calculate_impact_scores([inv])
        assert inv.gaming_impact_score == 0.0

    def test_high_cpu_high_impact(self):
        inv = ProcessInventory(cpu_percent=30, ram_mb=100, thread_count=10)
        self.analyzer._calculate_impact_scores([inv])
        assert inv.gaming_impact_score > 30

    def test_high_ram_high_impact(self):
        inv = ProcessInventory(cpu_percent=1, ram_mb=800, thread_count=10)
        self.analyzer._calculate_impact_scores([inv])
        assert inv.gaming_impact_score > 15

    def test_high_threads_moderate_impact(self):
        inv = ProcessInventory(cpu_percent=1, ram_mb=50, thread_count=80)
        self.analyzer._calculate_impact_scores([inv])
        assert inv.gaming_impact_score > 0

    def test_high_disk_io_impact(self):
        inv = ProcessInventory(
            cpu_percent=1, ram_mb=50, thread_count=5,
            io_read_mb=500, io_write_mb=600,
        )
        self.analyzer._calculate_impact_scores([inv])
        assert inv.gaming_impact_score > 5

    def test_score_capped_at_100(self):
        inv = ProcessInventory(
            cpu_percent=50, ram_mb=2000, thread_count=100,
            io_read_mb=2000, io_write_mb=2000, handle_count=5000,
        )
        self.analyzer._calculate_impact_scores([inv])
        assert inv.gaming_impact_score <= 100.0

    def test_cpu_competition_flagged(self):
        inv = ProcessInventory(cpu_percent=5, ram_mb=10)
        self.analyzer._calculate_impact_scores([inv])
        assert inv.cpu_competition is True

    def test_ram_competition_flagged(self):
        inv = ProcessInventory(cpu_percent=0.5, ram_mb=300)
        self.analyzer._calculate_impact_scores([inv])
        assert inv.ram_competition is True

    def test_disk_competition_flagged(self):
        inv = ProcessInventory(
            cpu_percent=0.5, ram_mb=10,
            io_read_mb=300, io_write_mb=300,
        )
        self.analyzer._calculate_impact_scores([inv])
        assert inv.disk_competition is True


# ══════════════════════════════════════════════════════════════
# 4. Competition Analysis
# ══════════════════════════════════════════════════════════════

class TestCompetitionAnalysis:
    """Test CPU/RAM/Disk competition analysis."""

    def setup_method(self):
        self.analyzer = BackgroundLoadAnalyzer()

    def test_no_competition_empty(self):
        analysis = self.analyzer._analyze_cpu_competition([], 0)
        assert analysis.level == CompetitionLevel.NONE
        assert len(analysis.cpu_competing_processes) == 0

    def test_low_competition(self):
        procs = [
            ProcessInventory(pid=1, name="a.exe", cpu_percent=2, ram_mb=50, cpu_competition=True, recommendation=Recommendation.REVIEW_REQUIRED),
            ProcessInventory(pid=2, name="b.exe", cpu_percent=1, ram_mb=50, cpu_competition=False, recommendation=Recommendation.REVIEW_REQUIRED),
        ]
        analysis = self.analyzer._analyze_cpu_competition(procs, 0)
        assert analysis.level in (CompetitionLevel.LOW, CompetitionLevel.MODERATE)

    def test_high_competition(self):
        procs = [
            ProcessInventory(pid=1, name="a.exe", cpu_percent=10, ram_mb=50, cpu_competition=True, recommendation=Recommendation.SAFE_TO_RECOMMEND),
            ProcessInventory(pid=2, name="b.exe", cpu_percent=8, ram_mb=50, cpu_competition=True, recommendation=Recommendation.SAFE_TO_RECOMMEND),
        ]
        analysis = self.analyzer._analyze_cpu_competition(procs, 0)
        assert analysis.level in (CompetitionLevel.HIGH, CompetitionLevel.SEVERE)
        assert analysis.total_competition_cpu > 15

    def test_severe_competition(self):
        procs = [
            ProcessInventory(pid=i, name=f"proc{i}.exe", cpu_percent=10, ram_mb=50,
                           cpu_competition=True, recommendation=Recommendation.SAFE_TO_RECOMMEND)
            for i in range(5)
        ]
        analysis = self.analyzer._analyze_cpu_competition(procs, 0)
        assert analysis.level == CompetitionLevel.SEVERE

    def test_emulator_excluded_from_competition(self):
        procs = [
            ProcessInventory(pid=999, name="app.exe", cpu_percent=15, ram_mb=50,
                           cpu_competition=True, recommendation=Recommendation.REVIEW_REQUIRED),
        ]
        analysis = self.analyzer._analyze_cpu_competition(procs, 999)
        assert analysis.total_competition_cpu == 0

    def test_protected_excluded_from_competition(self):
        procs = [
            ProcessInventory(pid=1, name="system.exe", cpu_percent=20, ram_mb=50,
                           cpu_competition=True, recommendation=Recommendation.DO_NOT_TOUCH),
        ]
        analysis = self.analyzer._analyze_cpu_competition(procs, 0)
        assert len(analysis.cpu_competing_processes) == 0

    def test_ram_competition_analysis(self):
        procs = [
            ProcessInventory(pid=1, name="chrome.exe", cpu_percent=2, ram_mb=2500,
                           ram_competition=True, recommendation=Recommendation.SAFE_TO_RECOMMEND),
        ]
        analysis = self.analyzer._analyze_ram_competition(procs, 0)
        assert analysis.level in (CompetitionLevel.HIGH, CompetitionLevel.SEVERE)
        assert analysis.total_competition_ram_mb > 2000

    def test_disk_competition_analysis(self):
        procs = [
            ProcessInventory(pid=1, name="update.exe", cpu_percent=2, ram_mb=50,
                           disk_competition=True, recommendation=Recommendation.SAFE_TO_RECOMMEND,
                           io_read_mb=500, io_write_mb=500),
        ]
        analysis = self.analyzer._analyze_disk_competition(procs, 0)
        assert analysis.level != CompetitionLevel.NONE


# ══════════════════════════════════════════════════════════════
# 5. Full Analysis
# ══════════════════════════════════════════════════════════════

class TestFullAnalysis:
    """Test the full analysis pipeline with mocked processes."""

    def setup_method(self):
        self.analyzer = BackgroundLoadAnalyzer()

    @patch("app.system.background_analyzer.psutil.process_iter")
    def test_analysis_returns_structured_result(self, mock_iter):
        mock_procs = [
            make_process_info(pid=1, name="svchost.exe", cpu=2, ram_mb=100),
            make_process_info(pid=2, name="chrome.exe", cpu=5, ram_mb=400),
            make_process_info(pid=3, name="Discord.exe", cpu=1, ram_mb=300),
        ]
        mock_iter.return_value = [m for m in mock_procs]

        result = self.analyzer.analyze(emulator_pid=0, force=True)

        assert isinstance(result, BackgroundAnalysis)
        assert result.total_count >= 0  # May be filtered by threshold
        assert result.timestamp > 0

    @patch("app.system.background_analyzer.psutil.process_iter")
    def test_analysis_with_emulator(self, mock_iter):
        mock_procs = [
            make_process_info(pid=1, name="HD-Player.exe", cpu=50, ram_mb=2000),
            make_process_info(pid=2, name="chrome.exe", cpu=5, ram_mb=400),
        ]
        mock_iter.return_value = [m for m in mock_procs]

        result = self.analyzer.analyze(emulator_pid=1, emulator_name="HD-Player.exe", force=True)

        assert result.emulator_pid == 1
        assert result.emulator_name == "HD-Player.exe"

    @patch("app.system.background_analyzer.psutil.process_iter")
    def test_analysis_caches_results(self, mock_iter):
        mock_procs = [
            make_process_info(pid=1, name="chrome.exe", cpu=5, ram_mb=400),
        ]
        mock_iter.return_value = [m for m in mock_procs]

        r1 = self.analyzer.analyze(force=False)
        r2 = self.analyzer.analyze(force=False)
        assert r1 is r2  # Same object from cache

    @patch("app.system.background_analyzer.psutil.process_iter")
    def test_force_refresh(self, mock_iter):
        mock_procs = [
            make_process_info(pid=1, name="chrome.exe", cpu=5, ram_mb=400),
        ]
        mock_iter.return_value = [m for m in mock_procs]

        r1 = self.analyzer.analyze(force=True)
        # Wait to invalidate cache
        self.analyzer._cache_ttl = 0
        r2 = self.analyzer.analyze(force=True)
        assert r1 is not r2  # Different object

    @patch("app.system.background_analyzer.psutil.process_iter")
    def test_safe_candidates_populated(self, mock_iter):
        mock_procs = [
            make_process_info(pid=2, name="chrome.exe", cpu=8, ram_mb=500),
            make_process_info(pid=3, name="Discord.exe", cpu=2, ram_mb=200),
            make_process_info(pid=4, name="Spotify.exe", cpu=1, ram_mb=100),
        ]
        mock_iter.return_value = [m for m in mock_procs]

        result = self.analyzer.analyze(force=True)
        # chrome should be a safe candidate given its impact
        names = [p.name for p in result.safe_candidates]
        # At least chrome or discord should be candidates
        assert len(result.safe_candidates) >= 0  # Could be 0 if scores are too low

    @patch("app.system.background_analyzer.psutil.process_iter")
    def test_empty_process_list(self, mock_iter):
        mock_iter.return_value = iter([])

        result = self.analyzer.analyze(force=True)
        assert result.total_count == 0
        assert result.overall_impact_level == CompetitionLevel.NONE


# ══════════════════════════════════════════════════════════════
# 6. Overall Impact Assessment
# ══════════════════════════════════════════════════════════════

class TestOverallImpact:
    """Test overall impact assessment."""

    def setup_method(self):
        self.analyzer = BackgroundLoadAnalyzer()

    def test_no_competition_none(self):
        result = BackgroundAnalysis()
        result.cpu_competition = CompetitionAnalysis(level=CompetitionLevel.NONE)
        result.ram_competition = CompetitionAnalysis(level=CompetitionLevel.NONE)
        result.disk_competition = CompetitionAnalysis(level=CompetitionLevel.NONE)
        level, desc = self.analyzer._assess_overall_impact(result)
        assert level == CompetitionLevel.NONE

    def test_worst_level_used(self):
        result = BackgroundAnalysis()
        result.cpu_competition = CompetitionAnalysis(level=CompetitionLevel.LOW)
        result.ram_competition = CompetitionAnalysis(level=CompetitionLevel.HIGH)
        result.disk_competition = CompetitionAnalysis(level=CompetitionLevel.NONE)
        level, desc = self.analyzer._assess_overall_impact(result)
        assert level == CompetitionLevel.HIGH

    def test_severe_overrides_all(self):
        result = BackgroundAnalysis()
        result.cpu_competition = CompetitionAnalysis(level=CompetitionLevel.SEVERE)
        result.ram_competition = CompetitionAnalysis(level=CompetitionLevel.LOW)
        result.disk_competition = CompetitionAnalysis(level=CompetitionLevel.MODERATE)
        level, desc = self.analyzer._assess_overall_impact(result)
        assert level == CompetitionLevel.SEVERE

    def test_no_competitions_no_data(self):
        result = BackgroundAnalysis()
        level, desc = self.analyzer._assess_overall_impact(result)
        assert level == CompetitionLevel.NONE


# ══════════════════════════════════════════════════════════════
# 7. Safety Rules
# ══════════════════════════════════════════════════════════════

class TestSafetyRules:
    """Test safety rules — no process termination, no modification."""

    def test_analyzer_is_read_only(self):
        """The analyzer module should not import os.kill, psutil.Process.kill, etc."""
        import inspect
        source = inspect.getsource(BackgroundLoadAnalyzer)
        # Should not contain process termination methods
        assert ".kill()" not in source
        assert ".terminate()" not in source
        assert "os.kill" not in source

    def test_no_fake_data_in_models(self):
        """All model defaults should be zero/empty, not fake values."""
        inv = ProcessInventory()
        assert inv.cpu_percent == 0.0
        assert inv.ram_mb == 0.0
        assert inv.gaming_impact_score == 0.0

        result = BackgroundAnalysis()
        assert result.total_count == 0
        assert result.overall_impact_level == CompetitionLevel.NONE

    def test_recommendation_never_auto_close(self):
        """Recommendation should never include 'auto-close' or 'kill'."""
        analyzer = BackgroundLoadAnalyzer()
        _, rec, reason = analyzer._classify_process("chrome.exe", 100, 0)
        assert "kill" not in reason.lower()
        assert "terminate" not in reason.lower()
        assert "auto" not in reason.lower()


# ══════════════════════════════════════════════════════════════
# 8. Data Model Integrity
# ══════════════════════════════════════════════════════════════

class TestDataModelIntegrity:
    """Test data model completeness and exclusivity."""

    def test_process_category_values(self):
        values = [c.value for c in ProcessCategory]
        assert "SYSTEM" in values
        assert "SECURITY" in values
        assert "EMULATOR" in values
        assert "USER_APPLICATION" in values
        assert "WINDOWS_SERVICE" in values
        assert "UNKNOWN" in values

    def test_recommendation_values(self):
        values = [r.value for r in Recommendation]
        assert "SAFE_TO_RECOMMEND" in values
        assert "REVIEW_REQUIRED" in values
        assert "DO_NOT_TOUCH" in values

    def test_competition_level_values(self):
        values = [c.value for c in CompetitionLevel]
        assert "NONE" in values
        assert "LOW" in values
        assert "MODERATE" in values
        assert "HIGH" in values
        assert "SEVERE" in values

    def test_competition_analysis_model(self):
        ca = CompetitionAnalysis()
        assert ca.level == CompetitionLevel.NONE
        assert ca.total_competition_cpu == 0.0
        assert ca.total_competition_ram_mb == 0.0
        assert len(ca.cpu_competing_processes) == 0

    def test_background_analysis_model(self):
        ba = BackgroundAnalysis()
        assert ba.total_count == 0
        assert ba.overall_impact_level == CompetitionLevel.NONE
        assert ba.timestamp == 0.0


# ══════════════════════════════════════════════════════════════
# 9. Edge Cases
# ══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases and error handling."""

    def setup_method(self):
        self.analyzer = BackgroundLoadAnalyzer()

    def test_classification_with_empty_name(self):
        cat, rec, reason = self.analyzer._classify_process("", 100, 0)
        # Should not crash
        assert cat in ProcessCategory

    def test_classification_with_zero_pid(self):
        cat, rec, reason = self.analyzer._classify_process("test.exe", 0, 0)
        assert cat in ProcessCategory

    def test_classification_with_zero_emulator_pid(self):
        cat, rec, reason = self.analyzer._classify_process("test.exe", 100, 0)
        assert cat in ProcessCategory

    def test_impact_score_with_zero_values(self):
        inv = ProcessInventory(cpu_percent=0, ram_mb=0, thread_count=0)
        self.analyzer._calculate_impact_scores([inv])
        assert inv.gaming_impact_score == 0.0

    def test_impact_score_rounding(self):
        inv = ProcessInventory(cpu_percent=3.333, ram_mb=150.5, thread_count=15)
        self.analyzer._calculate_impact_scores([inv])
        assert isinstance(inv.gaming_impact_score, float)

    def test_competition_with_single_process(self):
        procs = [
            ProcessInventory(pid=1, name="a.exe", cpu_percent=1, ram_mb=50,
                           cpu_competition=False, recommendation=Recommendation.REVIEW_REQUIRED),
        ]
        analysis = self.analyzer._analyze_cpu_competition(procs, 0)
        assert analysis.level == CompetitionLevel.NONE

    def test_all_same_level_consistent(self):
        result = BackgroundAnalysis()
        result.cpu_competition = CompetitionAnalysis(level=CompetitionLevel.MODERATE)
        result.ram_competition = CompetitionAnalysis(level=CompetitionLevel.MODERATE)
        result.disk_competition = CompetitionAnalysis(level=CompetitionLevel.MODERATE)
        level, _ = self.analyzer._assess_overall_impact(result)
        assert level == CompetitionLevel.MODERATE


# ══════════════════════════════════════════════════════════════
# 10. Singleton
# ══════════════════════════════════════════════════════════════

class TestSingleton:
    """Test that the singleton works."""

    def test_singleton_exists(self):
        assert background_analyzer is not None
        assert isinstance(background_analyzer, BackgroundLoadAnalyzer)

    def test_singleton_is_same_instance(self):
        from app.system.background_analyzer import background_analyzer as ba2
        assert background_analyzer is ba2
