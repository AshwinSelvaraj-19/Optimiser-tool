"""
Phase 53 — Comprehensive tests for Background Resource Intelligence.

Tests:
- ProcessCategory, ProcessState, ResourcePressure, RecommendedAction enums
- ProcessResourceSnapshot
- ProcessResourceHistory (avg, max, current, is_high_resource)
- ProcessRecommendation
- ProcessScanResult
- Extended classification (_classify_extended)
- ResourceTracker (snapshot, history, top consumers, stale cleanup)
- ProcessRecommendationEngine (exclusions, safe recommendations)
- ProcessIntelligence (scan, pressure classification, formatting)
- CLI commands
- Edge cases
"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from app.system.process_intelligence import (
    ProcessCategory,
    ProcessState,
    ResourcePressure,
    RecommendedAction,
    ProcessResourceSnapshot,
    ProcessResourceHistory,
    ProcessRecommendation,
    ProcessScanResult,
    ProcessRecommendationEngine,
    ProcessIntelligence,
    ResourceTracker,
    _classify_extended,
    process_intelligence,
    SAFE_TO_CLOSE_PROCESSES,
    KNOWN_GAME_PROCESSES,
)


# ══════════════════════════════════════════════════════════════════
# 1. Enums
# ══════════════════════════════════════════════════════════════════

class TestEnums:
    def test_process_category_values(self):
        assert ProcessCategory.SYSTEM.value == "SYSTEM"
        assert ProcessCategory.GAME.value == "GAME"
        assert ProcessCategory.EMULATOR.value == "EMULATOR"
        assert ProcessCategory.USER_APPLICATION.value == "USER APPLICATION"
        assert ProcessCategory.BACKGROUND.value == "BACKGROUND"
        assert ProcessCategory.UNKNOWN.value == "UNKNOWN"

    def test_process_state(self):
        assert ProcessState.FOREGROUND.value == "FOREGROUND"
        assert ProcessState.BACKGROUND.value == "BACKGROUND"

    def test_resource_pressure(self):
        assert ResourcePressure.NONE.value == "NONE"
        assert ResourcePressure.CRITICAL.value == "CRITICAL"

    def test_recommended_action(self):
        assert RecommendedAction.IGNORE.value == "IGNORE"
        assert RecommendedAction.CLOSE.value == "CLOSE"
        assert RecommendedAction.REVIEW.value == "REVIEW"
        assert RecommendedAction.ADD_TO_EXCLUSION.value == "ADD_TO_EXCLUSION"
        assert RecommendedAction.MONITOR.value == "MONITOR"


# ══════════════════════════════════════════════════════════════════
# 2. Data Models
# ══════════════════════════════════════════════════════════════════

class TestProcessResourceSnapshot:
    def test_create(self):
        snap = ProcessResourceSnapshot(pid=1234, name="test.exe")
        assert snap.pid == 1234
        assert snap.name == "test.exe"
        assert snap.cpu_percent == 0.0
        assert snap.category == ProcessCategory.UNKNOWN

    def test_with_values(self):
        snap = ProcessResourceSnapshot(
            pid=100, name="chrome.exe", cpu_percent=50.0,
            memory_mb=1024.0, category=ProcessCategory.BACKGROUND,
        )
        assert snap.cpu_percent == 50.0
        assert snap.memory_mb == 1024.0
        assert snap.category == ProcessCategory.BACKGROUND


class TestProcessResourceHistory:
    def test_empty_history(self):
        h = ProcessResourceHistory(pid=1, name="test.exe")
        assert h.avg_cpu == 0.0
        assert h.max_cpu == 0.0
        assert h.avg_memory_mb == 0.0
        assert h.max_memory_mb == 0.0
        assert h.current_memory_mb == 0.0
        assert h.is_high_resource is False

    def test_with_snapshots(self):
        h = ProcessResourceHistory(pid=1, name="test.exe")
        h.snapshots = [
            ProcessResourceSnapshot(cpu_percent=10.0, memory_mb=200.0),
            ProcessResourceSnapshot(cpu_percent=30.0, memory_mb=500.0),
            ProcessResourceSnapshot(cpu_percent=20.0, memory_mb=300.0),
        ]
        assert h.avg_cpu == 20.0
        assert h.max_cpu == 30.0
        assert h.avg_memory_mb == pytest.approx(333.3, abs=1)
        assert h.max_memory_mb == 500.0
        assert h.current_memory_mb == 300.0

    def test_is_high_resource_cpu(self):
        h = ProcessResourceHistory(pid=1, name="test.exe")
        h.snapshots = [ProcessResourceSnapshot(cpu_percent=25.0, memory_mb=50.0)]
        assert h.is_high_resource is True

    def test_is_high_resource_memory(self):
        h = ProcessResourceHistory(pid=1, name="test.exe")
        h.snapshots = [ProcessResourceSnapshot(cpu_percent=1.0, memory_mb=600.0)]
        assert h.is_high_resource is True

    def test_not_high_resource(self):
        h = ProcessResourceHistory(pid=1, name="test.exe")
        h.snapshots = [ProcessResourceSnapshot(cpu_percent=2.0, memory_mb=50.0)]
        assert h.is_high_resource is False


class TestProcessRecommendation:
    def test_create(self):
        rec = ProcessRecommendation(
            pid=100, name="chrome.exe",
            action=RecommendedAction.CLOSE,
            title="Chrome — 500 MB RAM",
        )
        assert rec.id.startswith("prec_")
        assert rec.risk == "NONE"

    def test_custom_id(self):
        rec = ProcessRecommendation(id="custom_id")
        assert rec.id == "custom_id"


class TestProcessScanResult:
    def test_create(self):
        result = ProcessScanResult()
        assert result.scan_id.startswith("pscan_")
        assert result.total_processes == 0

    def test_custom_id(self):
        result = ProcessScanResult(scan_id="custom")
        assert result.scan_id == "custom"


# ══════════════════════════════════════════════════════════════════
# 3. Extended Classification
# ══════════════════════════════════════════════════════════════════

class TestClassifyExtended:
    def test_system_process(self):
        assert _classify_extended("svchost.exe") == ProcessCategory.SYSTEM
        assert _classify_extended("csrss.exe") == ProcessCategory.SYSTEM
        assert _classify_extended("lsass.exe") == ProcessCategory.SYSTEM

    def test_security_process(self):
        assert _classify_extended("MsMpEng.exe") == ProcessCategory.SYSTEM

    def test_emulator_process(self):
        assert _classify_extended("HD-Agent.exe") == ProcessCategory.EMULATOR
        assert _classify_extended("bluestacks.exe") == ProcessCategory.EMULATOR

    def test_game_process(self):
        assert _classify_extended("steam.exe") == ProcessCategory.GAME
        assert _classify_extended("Fortnite.exe") == ProcessCategory.GAME

    def test_background_process(self):
        assert _classify_extended("chrome.exe") == ProcessCategory.BACKGROUND
        assert _classify_extended("Discord.exe") == ProcessCategory.BACKGROUND
        assert _classify_extended("Spotify.exe") == ProcessCategory.BACKGROUND

    def test_user_application(self):
        assert _classify_extended("Code.exe") == ProcessCategory.USER_APPLICATION
        assert _classify_extended("Excel.exe") == ProcessCategory.USER_APPLICATION

    def test_unknown_process(self):
        assert _classify_extended("some_random_app.exe") == ProcessCategory.UNKNOWN

    def test_case_insensitive(self):
        assert _classify_extended("CHROME.EXE") == ProcessCategory.BACKGROUND
        assert _classify_extended("SVCHOST.EXE") == ProcessCategory.SYSTEM


# ══════════════════════════════════════════════════════════════════
# 4. ResourceTracker
# ══════════════════════════════════════════════════════════════════

class TestResourceTracker:
    def test_create(self):
        tracker = ResourceTracker()
        assert len(tracker.get_all_histories()) == 0

    def test_snapshot_adds_history(self):
        tracker = ResourceTracker()
        snaps = [
            ProcessResourceSnapshot(pid=100, name="test.exe", memory_mb=500.0),
        ]
        tracker.snapshot(snaps)
        assert len(tracker.get_all_histories()) == 1
        hist = tracker.get_history(100)
        assert hist is not None
        assert hist.name == "test.exe"

    def test_multiple_snapshots(self):
        tracker = ResourceTracker()
        tracker.snapshot([ProcessResourceSnapshot(pid=100, name="test.exe", memory_mb=100)])
        tracker.snapshot([ProcessResourceSnapshot(pid=100, name="test.exe", memory_mb=200)])
        tracker.snapshot([ProcessResourceSnapshot(pid=100, name="test.exe", memory_mb=300)])
        hist = tracker.get_history(100)
        assert len(hist.snapshots) == 3
        assert hist.current_memory_mb == 300.0

    def test_rolling_window(self):
        tracker = ResourceTracker()
        for i in range(35):
            tracker.snapshot([ProcessResourceSnapshot(pid=100, name="test.exe", memory_mb=float(i))])
        hist = tracker.get_history(100)
        assert len(hist.snapshots) <= ResourceTracker.MAX_HISTORY

    def test_max_tracked_processes(self):
        tracker = ResourceTracker()
        tracker.MAX_TRACKED_PROCESSES = 5
        for i in range(10):
            tracker.snapshot([ProcessResourceSnapshot(pid=i, name=f"proc{i}.exe")])
        assert len(tracker.get_all_histories()) <= 5

    def test_get_top_consumers_memory(self):
        tracker = ResourceTracker()
        tracker.snapshot([
            ProcessResourceSnapshot(pid=1, name="small.exe", memory_mb=50.0),
            ProcessResourceSnapshot(pid=2, name="big.exe", memory_mb=2000.0),
            ProcessResourceSnapshot(pid=3, name="medium.exe", memory_mb=500.0),
        ])
        top = tracker.get_top_consumers("memory", limit=2)
        assert top[0].name == "big.exe"
        assert top[1].name == "medium.exe"

    def test_get_top_consumers_cpu(self):
        tracker = ResourceTracker()
        tracker.snapshot([
            ProcessResourceSnapshot(pid=1, name="idle.exe", cpu_percent=1.0),
            ProcessResourceSnapshot(pid=2, name="busy.exe", cpu_percent=90.0),
        ])
        top = tracker.get_top_consumers("cpu", limit=1)
        assert top[0].name == "busy.exe"

    def test_cleanup_stale(self):
        tracker = ResourceTracker()
        tracker.snapshot([ProcessResourceSnapshot(pid=100, name="old.exe")])
        # Manually age the entry
        hist = tracker.get_history(100)
        hist.last_seen = time.time() - 600
        tracker.cleanup_stale(max_age_seconds=300)
        assert tracker.get_history(100) is None

    def test_get_history_nonexistent(self):
        tracker = ResourceTracker()
        assert tracker.get_history(999) is None


# ══════════════════════════════════════════════════════════════════
# 5. ProcessRecommendationEngine
# ══════════════════════════════════════════════════════════════════

class TestProcessRecommendationEngine:
    def test_create(self):
        engine = ProcessRecommendationEngine()
        assert engine.exclusions == []

    def test_add_exclusion(self):
        engine = ProcessRecommendationEngine()
        engine.add_exclusion("chrome.exe")
        assert engine.is_excluded("chrome.exe")
        assert engine.is_excluded("Chrome.exe")  # case-insensitive

    def test_remove_exclusion(self):
        engine = ProcessRecommendationEngine()
        engine.add_exclusion("chrome.exe")
        engine.remove_exclusion("chrome.exe")
        assert not engine.is_excluded("chrome.exe")

    def test_exclusions_sorted(self):
        engine = ProcessRecommendationEngine()
        engine.add_exclusion("z.exe")
        engine.add_exclusion("a.exe")
        assert engine.exclusions == ["a.exe", "z.exe"]

    def test_no_recommendation_for_system(self):
        engine = ProcessRecommendationEngine()
        hist = ProcessResourceHistory(
            pid=1, name="svchost.exe", category=ProcessCategory.SYSTEM,
        )
        hist.snapshots = [ProcessResourceSnapshot(cpu_percent=50.0, memory_mb=200.0)]
        recs = engine.generate_recommendations([hist])
        assert len(recs) == 0

    def test_no_recommendation_for_emulator(self):
        engine = ProcessRecommendationEngine()
        hist = ProcessResourceHistory(
            pid=1, name="HD-Agent.exe", category=ProcessCategory.EMULATOR,
        )
        hist.snapshots = [ProcessResourceSnapshot(cpu_percent=50.0, memory_mb=500.0)]
        recs = engine.generate_recommendations([hist])
        assert len(recs) == 0

    def test_no_recommendation_for_excluded(self):
        engine = ProcessRecommendationEngine()
        engine.add_exclusion("chrome.exe")
        hist = ProcessResourceHistory(
            pid=1, name="chrome.exe", category=ProcessCategory.BACKGROUND,
        )
        hist.snapshots = [ProcessResourceSnapshot(cpu_percent=1.0, memory_mb=600.0)]
        recs = engine.generate_recommendations([hist])
        assert len(recs) == 0

    def test_no_recommendation_for_low_resource(self):
        engine = ProcessRecommendationEngine()
        hist = ProcessResourceHistory(
            pid=1, name="tiny.exe", category=ProcessCategory.BACKGROUND,
        )
        hist.snapshots = [ProcessResourceSnapshot(cpu_percent=1.0, memory_mb=50.0)]
        recs = engine.generate_recommendations([hist])
        assert len(recs) == 0

    def test_close_recommendation_for_heavy_background(self):
        engine = ProcessRecommendationEngine()
        hist = ProcessResourceHistory(
            pid=1, name="chrome.exe", category=ProcessCategory.BACKGROUND,
        )
        hist.snapshots = [ProcessResourceSnapshot(cpu_percent=1.0, memory_mb=600.0)]
        recs = engine.generate_recommendations([hist])
        assert len(recs) == 1
        assert recs[0].action == RecommendedAction.CLOSE
        assert recs[0].safe_to_auto_suggest is True

    def test_review_recommendation_for_moderate_background(self):
        engine = ProcessRecommendationEngine()
        hist = ProcessResourceHistory(
            pid=1, name="discord.exe", category=ProcessCategory.BACKGROUND,
        )
        hist.snapshots = [ProcessResourceSnapshot(cpu_percent=5.0, memory_mb=250.0)]
        recs = engine.generate_recommendations([hist])
        assert len(recs) == 1
        assert recs[0].action == RecommendedAction.REVIEW
        assert recs[0].safe_to_auto_suggest is False

    def test_review_for_heavy_user_application(self):
        engine = ProcessRecommendationEngine()
        hist = ProcessResourceHistory(
            pid=1, name="Photoshop.exe", category=ProcessCategory.USER_APPLICATION,
        )
        hist.snapshots = [ProcessResourceSnapshot(cpu_percent=60.0, memory_mb=2000.0)]
        recs = engine.generate_recommendations([hist])
        assert len(recs) == 1
        assert recs[0].action == RecommendedAction.REVIEW

    def test_review_for_unknown_heavy(self):
        engine = ProcessRecommendationEngine()
        hist = ProcessResourceHistory(
            pid=1, name="mystery.exe", category=ProcessCategory.UNKNOWN,
        )
        hist.snapshots = [ProcessResourceSnapshot(cpu_percent=30.0, memory_mb=400.0)]
        recs = engine.generate_recommendations([hist])
        assert len(recs) == 1
        assert recs[0].action == RecommendedAction.REVIEW
        assert "Unknown" in recs[0].title

    def test_recommendations_sorted_by_impact(self):
        engine = ProcessRecommendationEngine()
        h1 = ProcessResourceHistory(pid=1, name="small.exe", category=ProcessCategory.BACKGROUND)
        h1.snapshots = [ProcessResourceSnapshot(cpu_percent=1.0, memory_mb=250.0)]
        h2 = ProcessResourceHistory(pid=2, name="big.exe", category=ProcessCategory.BACKGROUND)
        h2.snapshots = [ProcessResourceSnapshot(cpu_percent=1.0, memory_mb=800.0)]
        recs = engine.generate_recommendations([h1, h2])
        assert len(recs) == 2
        assert recs[0].name == "big.exe"


# ══════════════════════════════════════════════════════════════════
# 6. ProcessIntelligence
# ══════════════════════════════════════════════════════════════════

class TestProcessIntelligence:
    def test_singleton_exists(self):
        assert isinstance(process_intelligence, ProcessIntelligence)

    def test_scan_returns_result(self):
        pi = ProcessIntelligence()
        with patch.object(pi._tracker, "_collect_processes", return_value=[
            ProcessResourceSnapshot(pid=100, name="test.exe", cpu_percent=5.0, memory_mb=200.0),
        ]):
            result = pi.scan()
        assert isinstance(result, ProcessScanResult)
        assert result.total_processes == 1

    def test_scan_classifies_processes(self):
        pi = ProcessIntelligence()
        with patch.object(pi._tracker, "_collect_processes", return_value=[
            ProcessResourceSnapshot(
                pid=100, name="chrome.exe", cpu_percent=5.0,
                memory_mb=200.0, category=ProcessCategory.BACKGROUND,
            ),
            ProcessResourceSnapshot(
                pid=101, name="svchost.exe", cpu_percent=2.0,
                memory_mb=50.0, category=ProcessCategory.SYSTEM,
            ),
        ]):
            result = pi.scan()
        assert result.classified_processes.get("BACKGROUND", 0) == 1
        assert result.classified_processes.get("SYSTEM", 0) == 1

    def test_scan_pressure_none(self):
        pi = ProcessIntelligence()
        with patch.object(pi._tracker, "_collect_processes", return_value=[
            ProcessResourceSnapshot(pid=100, name="test.exe", cpu_percent=1.0, memory_mb=50.0),
        ]):
            result = pi.scan()
        assert result.resource_pressure in (ResourcePressure.NONE, ResourcePressure.LOW)

    def test_scan_pressure_critical(self):
        pi = ProcessIntelligence()
        with patch.object(pi._tracker, "_collect_processes", return_value=[
            ProcessResourceSnapshot(
                pid=i, name=f"proc{i}.exe", cpu_percent=20.0,
                memory_mb=500.0, category=ProcessCategory.BACKGROUND,
            )
            for i in range(5)
        ]):
            result = pi.scan()
        # 5 procs × 500MB = 2500MB background → at least HIGH
        assert result.resource_pressure in (
            ResourcePressure.HIGH, ResourcePressure.CRITICAL
        )

    def test_scan_generates_recommendations(self):
        pi = ProcessIntelligence()
        with patch.object(pi._tracker, "_collect_processes", return_value=[
            ProcessResourceSnapshot(
                pid=100, name="chrome.exe", cpu_percent=1.0,
                memory_mb=600.0, category=ProcessCategory.BACKGROUND,
            ),
        ]), patch.object(pi._tracker, "get_all_histories", return_value=[
            ProcessResourceHistory(
                pid=100, name="chrome.exe", category=ProcessCategory.BACKGROUND,
                snapshots=[ProcessResourceSnapshot(cpu_percent=1.0, memory_mb=600.0)],
            ),
        ]):
            result = pi.scan()
        assert len(result.recommendations) > 0
        assert result.recommendations[0].action == RecommendedAction.CLOSE

    def test_scan_stored(self):
        pi = ProcessIntelligence()
        with patch.object(pi._tracker, "_collect_processes", return_value=[]):
            pi.scan()
        assert pi.last_scan is not None

    def test_scan_error_handling(self):
        pi = ProcessIntelligence()
        with patch.object(pi._tracker, "_collect_processes", side_effect=Exception("test")):
            result = pi.scan()
        assert len(result.errors) > 0

    def test_format_status(self):
        pi = ProcessIntelligence()
        with patch.object(pi._tracker, "_collect_processes", return_value=[
            ProcessResourceSnapshot(
                pid=100, name="test.exe", cpu_percent=5.0, memory_mb=200.0,
            ),
        ]):
            status = pi.format_status()
        assert "PROCESS RESOURCE INTELLIGENCE" in status

    def test_classify_pressure(self):
        pi = ProcessIntelligence()
        assert pi._classify_pressure(0, 0, 50) == ResourcePressure.NONE
        assert pi._classify_pressure(100, 5000, 250) == ResourcePressure.CRITICAL
        assert pi._classify_pressure(60, 2500, 150) == ResourcePressure.HIGH
        assert pi._classify_pressure(60, 1200, 80) == ResourcePressure.MODERATE
        assert pi._classify_pressure(10, 500, 60) == ResourcePressure.NONE


# ══════════════════════════════════════════════════════════════════
# 7. CLI Integration
# ══════════════════════════════════════════════════════════════════

class TestCLIIntegration:
    def test_process_status(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--process-status"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "PROCESS RESOURCE STATUS" in result.stdout

    def test_process_scan(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--process-scan"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "PROCESS RESOURCE INTELLIGENCE" in result.stdout

    def test_process_report_json(self):
        import subprocess
        import json
        result = subprocess.run(
            [sys.executable, "main.py", "--process-report"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        # Filter out log lines — JSON starts with '{'
        json_lines = [l for l in result.stdout.splitlines() if l.strip().startswith('{') or l.strip().startswith('"') or l.strip().startswith('[') or l.strip().startswith(']') or l.strip().startswith('}') or l.strip().startswith(',')]
        # Find JSON block
        start = result.stdout.find('{')
        assert start >= 0, f"No JSON found in output: {result.stdout[:200]}"
        data = json.loads(result.stdout[start:])
        assert "total_processes" in data
        assert "pressure" in data
        assert "top_memory" in data


# ══════════════════════════════════════════════════════════════════
# 8. Edge Cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_empty_snapshot(self):
        tracker = ResourceTracker()
        tracker.snapshot([])
        assert len(tracker.get_all_histories()) == 0

    def test_recommendation_engine_empty(self):
        engine = ProcessRecommendationEngine()
        recs = engine.generate_recommendations([])
        assert recs == []

    def test_safe_to_close_processes_defined(self):
        assert len(SAFE_TO_CLOSE_PROCESSES) > 0
        assert "chrome.exe" in SAFE_TO_CLOSE_PROCESSES

    def test_known_game_processes_defined(self):
        assert len(KNOWN_GAME_PROCESSES) > 0
        assert "steam.exe" in KNOWN_GAME_PROCESSES

    def test_resource_tracker_lock(self):
        """Verify tracker uses a lock for thread safety."""
        tracker = ResourceTracker()
        assert hasattr(tracker, "_lock")

    def test_process_intelligence_components(self):
        pi = ProcessIntelligence()
        assert pi._tracker is not None
        assert pi._rec_engine is not None
        assert pi._monitor is not None

    def test_format_status_without_scan(self):
        """format_status should auto-scan if no previous scan exists."""
        pi = ProcessIntelligence()
        with patch.object(pi._tracker, "_collect_processes", return_value=[]):
            status = pi.format_status()
        assert "PROCESS RESOURCE INTELLIGENCE" in status
