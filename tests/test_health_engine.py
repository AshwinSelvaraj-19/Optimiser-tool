"""
Comprehensive tests for Phase 60 — System Health Scoring Engine.

Tests: HealthMetric, HealthIssue, HealthScore, HealthEngine, all 6 categories,
       scoring thresholds, confidence, formatting, missing data, edge cases.
"""

import pytest
import time
from app.core.health_engine import (
    HealthCategory,
    IssueSeverity,
    HealthMetric,
    HealthIssue,
    HealthScore,
    HealthEngine,
    health_engine,
)


# ── Helpers ──────────────────────────────────────────────────────


def _make_context(**overrides):
    """Create a baseline context with sensible defaults."""
    ctx = {
        "cpu_percent": 50.0,
        "gpu_percent": 60.0,
        "ram_percent": 70.0,
        "ram_available_gb": 4.0,
        "gpu_temp": 65.0,
        "cpu_temp": 55.0,
        "disk_free_gb": 100.0,
        "background_cpu": 15.0,
        "background_ram_mb": 800.0,
        "target_name": "BlueStacks",
        "fps": 60.0,
    }
    ctx.update(overrides)
    return ctx


def _fresh_engine():
    """Create a fresh HealthEngine with no cached score."""
    return HealthEngine()


# ── Data Model Tests ─────────────────────────────────────────────


class TestHealthMetric:
    def test_default_construction(self):
        m = HealthMetric()
        assert m.category == HealthCategory.PERFORMANCE
        assert m.base_score == 100.0
        assert m.deduction == 0.0
        assert m.final_score == 100.0
        assert not m.available

    def test_has_deduction_false(self):
        m = HealthMetric(deduction=0.0)
        assert not m.has_deduction

    def test_has_deduction_true(self):
        m = HealthMetric(deduction=5.0)
        assert m.has_deduction

    def test_to_dict(self):
        m = HealthMetric(
            category=HealthCategory.MEMORY,
            name="RAM",
            measured_value=85.0,
            measured_unit="%",
            available=True,
            deduction=10.0,
            final_score=90.0,
        )
        d = m.to_dict()
        assert d["category"] == "MEMORY"
        assert d["name"] == "RAM"
        assert d["measured_value"] == 85.0
        assert d["available"] is True
        assert d["deduction"] == 10.0


class TestHealthIssue:
    def test_default_construction(self):
        i = HealthIssue()
        assert i.severity == IssueSeverity.NONE
        assert i.deduction == 0.0

    def test_to_dict(self):
        i = HealthIssue(
            category=HealthCategory.THERMAL,
            severity=IssueSeverity.CRITICAL,
            title="Overheating",
            deduction=15.0,
            measured_value=95.0,
            threshold=90.0,
        )
        d = i.to_dict()
        assert d["category"] == "THERMAL"
        assert d["severity"] == "CRITICAL"
        assert d["deduction"] == 15.0
        assert d["measured_value"] == 95.0


class TestHealthScore:
    def test_grade_excellent(self):
        s = HealthScore(overall_score=95)
        assert s.grade == "EXCELLENT"

    def test_grade_good(self):
        s = HealthScore(overall_score=80)
        assert s.grade == "GOOD"

    def test_grade_fair(self):
        s = HealthScore(overall_score=65)
        assert s.grade == "FAIR"

    def test_grade_poor(self):
        s = HealthScore(overall_score=45)
        assert s.grade == "POOR"

    def test_grade_critical(self):
        s = HealthScore(overall_score=20)
        assert s.grade == "CRITICAL"

    def test_grade_color_excellent(self):
        s = HealthScore(overall_score=95)
        assert s.grade_color == "#4CAF50"

    def test_grade_color_critical(self):
        s = HealthScore(overall_score=10)
        assert s.grade_color == "#F44336"

    def test_timestamp_set_automatically(self):
        s = HealthScore()
        assert s.timestamp > 0

    def test_to_dict(self):
        s = HealthScore(overall_score=75, confidence=80.0)
        d = s.to_dict()
        assert d["overall_score"] == 75
        assert d["confidence"] == 80.0
        assert d["grade"] == "GOOD"
        assert "metrics" in d
        assert "issues" in d


# ── Engine Construction ──────────────────────────────────────────


class TestEngineConstruction:
    def test_singleton_exists(self):
        assert health_engine is not None
        assert isinstance(health_engine, HealthEngine)

    def test_fresh_engine_has_no_score(self):
        e = _fresh_engine()
        assert e.last_score is None

    def test_fresh_engine_has_score_after_calculate(self):
        e = _fresh_engine()
        score = e.calculate(_make_context())
        assert e.last_score is not None
        assert e.last_score.overall_score == score.overall_score


# ── PERFORMANCE Scoring ──────────────────────────────────────────


class TestPerformanceScoring:
    def test_normal_cpu(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=50.0))
        cpu_metrics = [m for m in score.metrics if m.name == "CPU Headroom"]
        assert len(cpu_metrics) == 1
        assert cpu_metrics[0].deduction == 0
        assert cpu_metrics[0].final_score == 100

    def test_cpu_high(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=85.0))
        cpu_metrics = [m for m in score.metrics if m.name == "CPU Headroom"]
        assert cpu_metrics[0].deduction > 0
        issues = [i for i in score.issues if "CPU" in i.title]
        assert len(issues) > 0

    def test_cpu_critical(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=95.0))
        cpu_metrics = [m for m in score.metrics if m.name == "CPU Headroom"]
        assert cpu_metrics[0].deduction == (95 - 70) * 2  # 50
        issues = [i for i in score.issues if i.severity == IssueSeverity.CRITICAL]
        assert any("CPU" in i.title for i in issues)

    def test_normal_gpu(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_percent=70.0))
        gpu_metrics = [m for m in score.metrics if m.name == "GPU Headroom"]
        assert gpu_metrics[0].deduction == 0

    def test_gpu_saturated(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_percent=97.0))
        gpu_metrics = [m for m in score.metrics if m.name == "GPU Headroom"]
        assert gpu_metrics[0].deduction > 0
        issues = [i for i in score.issues if "GPU" in i.title]
        assert len(issues) > 0

    def test_cpu_not_available(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=None))
        cpu_metrics = [m for m in score.metrics if m.name == "CPU Headroom"]
        assert cpu_metrics[0].final_score == 80
        assert not cpu_metrics[0].available

    def test_gpu_not_available(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_percent=None))
        gpu_metrics = [m for m in score.metrics if m.name == "GPU Headroom"]
        assert gpu_metrics[0].final_score == 80

    def test_cpu_zero(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=0.0))
        cpu_metrics = [m for m in score.metrics if m.name == "CPU Headroom"]
        assert cpu_metrics[0].final_score == 80  # treated as unavailable


# ── THERMAL Scoring ─────────────────────────────────────────────


class TestThermalScoring:
    def test_normal_gpu_temp(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_temp=65.0))
        therm = [m for m in score.metrics if m.name == "GPU Temperature"]
        assert len(therm) == 1
        assert therm[0].deduction == 0

    def test_gpu_temp_elevated(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_temp=85.0))
        therm = [m for m in score.metrics if m.name == "GPU Temperature"]
        assert therm[0].deduction > 0
        issues = [i for i in score.issues if "GPU temperature" in i.title.lower() or "GPU temperature" in i.title]
        assert len(issues) > 0

    def test_gpu_temp_critical(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_temp=95.0))
        therm = [m for m in score.metrics if m.name == "GPU Temperature"]
        assert therm[0].deduction > 0
        issues = [i for i in score.issues if i.severity == IssueSeverity.CRITICAL]
        assert any("GPU" in i.title for i in issues)

    def test_cpu_temp_critical(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_temp=95.0))
        cpu_temp = [m for m in score.metrics if m.name == "CPU Temperature"]
        assert len(cpu_temp) == 1
        assert cpu_temp[0].deduction > 0

    def test_cpu_temp_not_available(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_temp=None))
        cpu_temp = [m for m in score.metrics if m.name == "CPU Temperature"]
        assert len(cpu_temp) == 0  # CPU temp metric only added when available

    def test_gpu_temp_not_available(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_temp=None))
        therm = [m for m in score.metrics if m.name == "GPU Temperature"]
        assert therm[0].final_score == 80


# ── MEMORY Scoring ──────────────────────────────────────────────


class TestMemoryScoring:
    def test_normal_ram(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(ram_percent=60.0))
        ram = [m for m in score.metrics if m.name == "RAM Pressure"]
        assert ram[0].deduction == 0

    def test_ram_elevated(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(ram_percent=85.0))
        ram = [m for m in score.metrics if m.name == "RAM Pressure"]
        assert ram[0].deduction == 5

    def test_ram_high(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(ram_percent=92.0))
        ram = [m for m in score.metrics if m.name == "RAM Pressure"]
        assert ram[0].deduction == 10
        issues = [i for i in score.issues if "RAM" in i.title]
        assert len(issues) > 0

    def test_ram_critical(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(ram_percent=97.0))
        ram = [m for m in score.metrics if m.name == "RAM Pressure"]
        assert ram[0].deduction == 15
        issues = [i for i in score.issues if i.severity == IssueSeverity.CRITICAL]
        assert any("RAM" in i.title for i in issues)

    def test_ram_not_available(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(ram_percent=None))
        ram = [m for m in score.metrics if m.name == "RAM Pressure"]
        assert ram[0].final_score == 80


# ── STORAGE Scoring ─────────────────────────────────────────────


class TestStorageScoring:
    def test_normal_disk(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(disk_free_gb=200.0))
        disk = [m for m in score.metrics if m.name == "Disk Free Space"]
        assert disk[0].deduction == 0

    def test_disk_low(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(disk_free_gb=10.0))
        disk = [m for m in score.metrics if m.name == "Disk Free Space"]
        assert disk[0].deduction == 8

    def test_disk_critical(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(disk_free_gb=3.0))
        disk = [m for m in score.metrics if m.name == "Disk Free Space"]
        assert disk[0].deduction == 15
        issues = [i for i in score.issues if i.severity == IssueSeverity.CRITICAL]
        assert any("Disk" in i.title for i in issues)

    def test_disk_moderate(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(disk_free_gb=25.0))
        disk = [m for m in score.metrics if m.name == "Disk Free Space"]
        assert disk[0].deduction == 3

    def test_disk_not_available(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(disk_free_gb=None))
        disk = [m for m in score.metrics if m.name == "Disk Free Space"]
        assert disk[0].final_score == 80


# ── BACKGROUND LOAD Scoring ─────────────────────────────────────


class TestBackgroundLoadScoring:
    def test_low_background_cpu(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(background_cpu=10.0, background_ram_mb=500.0))
        bg = [m for m in score.metrics if m.name == "Background CPU"]
        assert bg[0].deduction == 0

    def test_moderate_background_cpu(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(background_cpu=30.0, background_ram_mb=500.0))
        bg = [m for m in score.metrics if m.name == "Background CPU"]
        assert bg[0].deduction == 3

    def test_high_background_cpu(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(background_cpu=60.0, background_ram_mb=500.0))
        bg = [m for m in score.metrics if m.name == "Background CPU"]
        assert bg[0].deduction == 10

    def test_high_background_ram(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(background_cpu=10.0, background_ram_mb=5000.0))
        bg = [m for m in score.metrics if m.name == "Background RAM"]
        assert bg[0].deduction == 8

    def test_moderate_background_ram(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(background_cpu=10.0, background_ram_mb=3000.0))
        bg = [m for m in score.metrics if m.name == "Background RAM"]
        assert bg[0].deduction == 3

    def test_zero_background(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(background_cpu=0, background_ram_mb=0))
        bg_cpu = [m for m in score.metrics if m.name == "Background CPU"]
        bg_ram = [m for m in score.metrics if m.name == "Background RAM"]
        assert bg_cpu[0].final_score == 85  # neutral for missing
        assert bg_ram[0].final_score == 85


# ── GAMING READINESS Scoring ────────────────────────────────────


class TestGamingReadinessScoring:
    def test_target_detected(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(target_name="BlueStacks"))
        target = [m for m in score.metrics if m.name == "Target Detection"]
        assert target[0].final_score == 100
        assert target[0].available

    def test_no_target(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(target_name=""))
        target = [m for m in score.metrics if m.name == "Target Detection"]
        assert target[0].final_score == 70

    def test_fps_available(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(fps=120.0))
        fps_m = [m for m in score.metrics if m.name == "FPS Data"]
        assert fps_m[0].final_score == 100
        assert fps_m[0].available

    def test_fps_low(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(fps=20.0))
        fps_m = [m for m in score.metrics if m.name == "FPS Data"]
        assert fps_m[0].deduction == 10
        issues = [i for i in score.issues if "frame rate" in i.title.lower()]
        assert len(issues) > 0

    def test_fps_not_available(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(fps=None))
        fps_m = [m for m in score.metrics if m.name == "FPS Data"]
        assert fps_m[0].final_score == 80


# ── Overall Score Computation ────────────────────────────────────


class TestOverallScore:
    def test_perfect_system(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(
            cpu_percent=30.0, gpu_percent=50.0,
            ram_percent=40.0, gpu_temp=55.0,
            disk_free_gb=500.0, background_cpu=5.0,
            background_ram_mb=200.0, target_name="Game",
            fps=144.0,
        ))
        assert score.overall_score == 100.0
        assert score.grade == "EXCELLENT"

    def test_stressed_system(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(
            cpu_percent=95.0, gpu_percent=98.0,
            ram_percent=96.0, gpu_temp=95.0,
            disk_free_gb=2.0, background_cpu=60.0,
            background_ram_mb=6000.0, target_name="",
            fps=15.0,
        ))
        assert score.overall_score < 50
        assert score.grade in ("POOR", "CRITICAL")

    def test_score_never_negative(self):
        e = _fresh_engine()
        # Provide extreme values to ensure floor at 0
        score = e.calculate(_make_context(
            cpu_percent=100.0, gpu_percent=100.0,
            ram_percent=100.0, gpu_temp=120.0,
            disk_free_gb=0.1, background_cpu=100.0,
            background_ram_mb=20000.0,
            fps=1.0,
        ))
        assert score.overall_score >= 0

    def test_category_scores_populated(self):
        e = _fresh_engine()
        score = e.calculate(_make_context())
        expected = {"PERFORMANCE", "THERMAL", "MEMORY", "STORAGE",
                    "BACKGROUND_LOAD", "GAMING_READINESS"}
        assert set(score.category_scores.keys()) == expected

    def test_all_deductions_explained(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=92.0))
        issues_with_deduction = [i for i in score.issues if i.deduction > 0]
        total = sum(i.deduction for i in issues_with_deduction)
        # Deductions should sum to total deducted from 100
        assert score.overall_score <= 100.0
        assert score.overall_score == max(0.0, 100.0 - total)


# ── Confidence ──────────────────────────────────────────────────


class TestConfidence:
    def test_full_data_high_confidence(self):
        e = _fresh_engine()
        score = e.calculate(_make_context())
        assert score.confidence > 50  # most metrics available
        assert score.data_completeness > 50

    def test_no_data_low_confidence(self):
        e = _fresh_engine()
        score = e.calculate({})
        assert score.confidence < 50

    def test_missing_all_optional_metrics(self):
        e = _fresh_engine()
        ctx = _make_context(cpu_temp=None, fps=None, target_name="")
        score = e.calculate(ctx)
        # Still has some data
        assert score.data_completeness > 0


# ── Formatting ──────────────────────────────────────────────────


class TestFormatting:
    def test_format_score_returns_string(self):
        e = _fresh_engine()
        result = e.format_score(e.calculate(_make_context()))
        assert isinstance(result, str)
        assert "SYSTEM HEALTH" in result

    def test_format_score_shows_grade(self):
        e = _fresh_engine()
        result = e.format_score(e.calculate(_make_context()))
        assert "EXCELLENT" in result or "GOOD" in result or "FAIR" in result

    def test_format_score_shows_categories(self):
        e = _fresh_engine()
        result = e.format_score(e.calculate(_make_context()))
        assert "PERFORMANCE" in result
        assert "MEMORY" in result
        assert "THERMAL" in result

    def test_format_brief(self):
        e = _fresh_engine()
        result = e.format_brief(e.calculate(_make_context()))
        assert "/100" in result
        assert isinstance(result, str)

    def test_format_with_issues(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=95.0, ram_percent=96.0))
        result = e.format_score(score)
        assert "DEDUCTIONS" in result

    def test_format_no_issues(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(
            cpu_percent=30.0, gpu_percent=50.0,
            ram_percent=40.0, gpu_temp=55.0,
            disk_free_gb=500.0, background_cpu=5.0,
            background_ram_mb=200.0, target_name="Game",
            fps=144.0,
        ))
        result = e.format_score(score)
        assert "No deductions" in result


# ── Edge Cases ──────────────────────────────────────────────────


class TestEdgeCases:
    def test_empty_context(self):
        e = _fresh_engine()
        score = e.calculate({})
        assert score.overall_score > 0
        assert len(score.metrics) > 0

    def test_all_none_context(self):
        e = _fresh_engine()
        ctx = {
            "cpu_percent": None,
            "gpu_percent": None,
            "ram_percent": None,
            "gpu_temp": None,
            "disk_free_gb": None,
        }
        score = e.calculate(ctx)
        assert score.overall_score >= 0

    def test_negative_values(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=-1.0, ram_percent=-1.0))
        assert score.overall_score >= 0

    def test_very_high_values(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=200.0, gpu_percent=200.0))
        assert score.overall_score >= 0

    def test_boundary_ram_80(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(ram_percent=80.0))
        ram = [m for m in score.metrics if m.name == "RAM Pressure"]
        assert ram[0].deduction == 5

    def test_boundary_ram_90(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(ram_percent=90.0))
        ram = [m for m in score.metrics if m.name == "RAM Pressure"]
        assert ram[0].deduction == 10

    def test_boundary_ram_95(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(ram_percent=95.0))
        ram = [m for m in score.metrics if m.name == "RAM Pressure"]
        assert ram[0].deduction == 15

    def test_boundary_disk_5(self):
        # 5 < 5 is False, so disk=5 falls to < 15 branch (deduction=8)
        e = _fresh_engine()
        score = e.calculate(_make_context(disk_free_gb=5.0))
        disk = [m for m in score.metrics if m.name == "Disk Free Space"]
        assert disk[0].deduction == 8

    def test_boundary_disk_15(self):
        # 15 < 15 is False, so disk=15 falls to < 30 branch (deduction=3)
        e = _fresh_engine()
        score = e.calculate(_make_context(disk_free_gb=15.0))
        disk = [m for m in score.metrics if m.name == "Disk Free Space"]
        assert disk[0].deduction == 3

    def test_boundary_disk_30(self):
        # 30 < 30 is False, so disk=30 is healthy (deduction=0)
        e = _fresh_engine()
        score = e.calculate(_make_context(disk_free_gb=30.0))
        disk = [m for m in score.metrics if m.name == "Disk Free Space"]
        assert disk[0].deduction == 0

    def test_boundary_cpu_80(self):
        # CPU: deduction = max(0, cpu - 70) * 2 when cpu > 70
        # At 80: deduction = (80-70)*2 = 20
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=80.0))
        cpu = [m for m in score.metrics if m.name == "CPU Headroom"]
        assert cpu[0].deduction == 20.0

    def test_boundary_cpu_81(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=81.0))
        cpu = [m for m in score.metrics if m.name == "CPU Headroom"]
        assert cpu[0].deduction > 0

    def test_boundary_gpu_85(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_percent=85.0))
        gpu = [m for m in score.metrics if m.name == "GPU Headroom"]
        assert gpu[0].deduction == 0

    def test_boundary_gpu_86(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_percent=86.0))
        gpu = [m for m in score.metrics if m.name == "GPU Headroom"]
        assert gpu[0].deduction > 0

    def test_boundary_gpu_temp_90(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(gpu_temp=90.0))
        therm = [m for m in score.metrics if m.name == "GPU Temperature"]
        assert therm[0].deduction > 0

    def test_boundary_fps_30(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(fps=30.0))
        fps_m = [m for m in score.metrics if m.name == "FPS Data"]
        assert fps_m[0].deduction == 0  # threshold is < 30

    def test_boundary_fps_29(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(fps=29.0))
        fps_m = [m for m in score.metrics if m.name == "FPS Data"]
        assert fps_m[0].deduction == 10


# ── Multiple Calculations ───────────────────────────────────────


class TestMultipleCalculations:
    def test_recalculate_updates_last_score(self):
        e = _fresh_engine()
        s1 = e.calculate(_make_context(cpu_percent=50.0))
        s2 = e.calculate(_make_context(cpu_percent=90.0))
        assert e.last_score.overall_score <= s1.overall_score
        assert s2.overall_score < s1.overall_score

    def test_sequential_calculations(self):
        e = _fresh_engine()
        for cpu_val in range(0, 100, 5):
            score = e.calculate(_make_context(cpu_percent=float(cpu_val)))
            assert score.overall_score >= 0


# ── Recommendation Consistency ──────────────────────────────────


class TestRecommendationConsistency:
    def test_high_cpu_has_recommendation(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(cpu_percent=95.0))
        cpu_issues = [i for i in score.issues if "CPU" in i.title and i.deduction > 0]
        assert len(cpu_issues) > 0
        assert cpu_issues[0].recommendation != ""

    def test_high_ram_has_recommendation(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(ram_percent=96.0))
        ram_issues = [i for i in score.issues if "RAM" in i.title and i.deduction > 0]
        assert len(ram_issues) > 0
        assert ram_issues[0].recommendation != ""

    def test_low_disk_has_recommendation(self):
        e = _fresh_engine()
        score = e.calculate(_make_context(disk_free_gb=3.0))
        disk_issues = [i for i in score.issues if "Disk" in i.title and i.deduction > 0]
        assert len(disk_issues) > 0
        assert disk_issues[0].recommendation != ""


# ── Category Score Calculation ──────────────────────────────────


class TestCategoryScoreCalculation:
    def test_category_score_available_metrics(self):
        e = _fresh_engine()
        score = e.calculate(_make_context())
        for cat, cat_score in score.category_scores.items():
            assert 0 <= cat_score <= 100

    def test_category_score_empty(self):
        e = _fresh_engine()
        assert e._category_score([]) == 100.0

    def test_category_score_all_unavailable(self):
        e = _fresh_engine()
        metrics = [
            HealthMetric(available=False, final_score=50),
            HealthMetric(available=False, final_score=60),
        ]
        assert e._category_score(metrics) == 80.0  # neutral for missing

    def test_category_score_mixed(self):
        e = _fresh_engine()
        metrics = [
            HealthMetric(available=True, final_score=100),
            HealthMetric(available=True, final_score=80),
            HealthMetric(available=False, final_score=50),
        ]
        # Only available metrics count
        assert e._category_score(metrics) == 90.0


# ── Enum Values ─────────────────────────────────────────────────


class TestEnumValues:
    def test_health_categories(self):
        cats = [c.value for c in HealthCategory]
        assert "PERFORMANCE" in cats
        assert "THERMAL" in cats
        assert "MEMORY" in cats
        assert "STORAGE" in cats
        assert "BACKGROUND_LOAD" in cats
        assert "GAMING_READINESS" in cats

    def test_issue_severities(self):
        sevs = [s.value for s in IssueSeverity]
        assert "NONE" in sevs
        assert "MINOR" in sevs
        assert "MODERATE" in sevs
        assert "MAJOR" in sevs
        assert "CRITICAL" in sevs


# ── Combined Stress ─────────────────────────────────────────────


class TestCombinedStress:
    def test_all_warnings(self):
        """All metrics at warning thresholds."""
        e = _fresh_engine()
        score = e.calculate(_make_context(
            cpu_percent=85.0, gpu_percent=87.0,
            ram_percent=85.0, gpu_temp=85.0,
            disk_free_gb=10.0, background_cpu=30.0,
            background_ram_mb=3000.0, target_name="",
            fps=25.0,
        ))
        assert score.overall_score < 100
        assert len(score.issues) > 0
        assert score.confidence > 50

    def test_mixed_state(self):
        """Some metrics good, some bad."""
        e = _fresh_engine()
        score = e.calculate(_make_context(
            cpu_percent=40.0,  # good
            gpu_percent=97.0,  # bad
            ram_percent=50.0,  # good
            gpu_temp=55.0,     # good
            disk_free_gb=3.0,  # bad
            background_cpu=5.0,  # good
            background_ram_mb=200.0,  # good
            target_name="BlueStacks",
            fps=60.0,
        ))
        # GPU + Disk issues should deduct points
        assert score.overall_score < 100
        # But some categories should be fine
        assert score.category_scores.get("MEMORY", 0) >= 95
        assert score.category_scores.get("THERMAL", 0) >= 95
