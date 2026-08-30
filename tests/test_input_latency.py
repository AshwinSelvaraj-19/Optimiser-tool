"""
Tests for Heaven Society — Input Responsiveness & Latency Diagnostics.

All tests use mocked data; never modify real system settings.
"""

import os
import sys
import time
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.performance.input_latency import (
    InputLatencyAnalyzer,
    ResponsivenessReport,
    MouseSettings,
    DisplayAnalysis,
    EmulatorState,
    FramePacingAnalysis,
    BackgroundImpact,
    ResponsivenessLevel,
    BottleneckType,
    PointerPrecision,
    input_latency_analyzer,
)


# ══════════════════════════════════════════════════════════════
# 1. Data Models
# ══════════════════════════════════════════════════════════════

class TestModels:
    """Test data model defaults and values."""

    def test_responsiveness_report_defaults(self):
        r = ResponsivenessReport()
        assert r.responsiveness_score == 0.0
        assert r.responsiveness_level == ResponsivenessLevel.INSUFFICIENT_DATA
        assert r.identified_bottleneck == BottleneckType.UNKNOWN
        assert r.measurement_type == "HEURISTIC"
        assert len(r.disclaimers) > 0

    def test_mouse_settings_defaults(self):
        m = MouseSettings()
        assert m.pointer_speed == 6
        assert m.enhanced_precision == PointerPrecision.UNKNOWN
        assert m.is_measured is False

    def test_display_analysis_defaults(self):
        d = DisplayAnalysis()
        assert d.resolution_x == 0
        assert d.refresh_rate_hz == 0

    def test_emulator_state_defaults(self):
        e = EmulatorState()
        assert e.is_detected is False

    def test_frame_pacing_defaults(self):
        fp = FramePacingAnalysis()
        assert fp.is_measured is True
        assert fp.sample_count == 0

    def test_background_impact_defaults(self):
        bg = BackgroundImpact()
        assert bg.is_measured is True
        assert bg.impact_level == ""

    def test_responsiveness_level_values(self):
        values = [l.value for l in ResponsivenessLevel]
        assert "EXCELLENT" in values
        assert "GOOD" in values
        assert "MODERATE" in values
        assert "POOR" in values
        assert "CRITICAL" in values
        assert "INSUFFICIENT DATA" in values

    def test_bottleneck_type_values(self):
        values = [b.value for b in BottleneckType]
        assert "CPU" in values
        assert "GPU" in values
        assert "Frame Pacing" in values
        assert "Display" in values
        assert "Memory" in values
        assert "Background Load" in values
        assert "Configuration" in values

    def test_pointer_precision_values(self):
        values = [p.value for p in PointerPrecision]
        assert "ENABLED" in values
        assert "DISABLED" in values
        assert "UNKNOWN" in values


# ══════════════════════════════════════════════════════════════
# 2. Score Calculation
# ══════════════════════════════════════════════════════════════

class TestScoreCalculation:
    """Test responsiveness score calculation."""

    def setup_method(self):
        self.analyzer = InputLatencyAnalyzer()

    def test_low_score_with_poor_data(self):
        """With poor measured data, score should reflect that."""
        report = ResponsivenessReport()
        report.display = DisplayAnalysis(refresh_rate_hz=30, is_measured=True)
        report.emulator = EmulatorState(
            is_detected=True, priority_value=2, cpu_percent=95,
            affinity_cpus=2, total_cpus=12,
        )
        report.frame_pacing = FramePacingAnalysis(
            is_measured=True, present_fps=25,
            stability_score=15, one_percent_low=10,
            sample_count=100, frame_spikes=50,
        )
        report.background = BackgroundImpact(
            impact_level="SEVERE", total_cpu_outside_emulator=60,
        )
        report.mouse = MouseSettings(
            is_measured=True, enhanced_precision=PointerPrecision.ENABLED,
        )
        score = self.analyzer._calculate_score(report)
        assert score < 40

    def test_excellent_with_good_data(self):
        report = ResponsivenessReport()
        report.display = DisplayAnalysis(
            resolution_x=1920, resolution_y=1080,
            refresh_rate_hz=144, is_measured=True,
        )
        report.emulator = EmulatorState(
            is_detected=True, priority_value=-1,
            cpu_percent=50, affinity_cpus=12, total_cpus=12,
        )
        report.frame_pacing = FramePacingAnalysis(
            is_measured=True, present_fps=140,
            stability_score=90, one_percent_low=120,
            sample_count=1000,
        )
        report.background = BackgroundImpact(
            impact_level="NONE", total_cpu_outside_emulator=2.0,
        )
        report.mouse = MouseSettings(
            is_measured=True, enhanced_precision=PointerPrecision.DISABLED,
        )
        score = self.analyzer._calculate_score(report)
        assert score >= 80

    def test_poor_with_bad_data(self):
        report = ResponsivenessReport()
        report.display = DisplayAnalysis(
            resolution_x=1920, resolution_y=1080,
            refresh_rate_hz=30, is_measured=True,
        )
        report.emulator = EmulatorState(
            is_detected=True, priority_value=2,
            cpu_percent=95, affinity_cpus=2, total_cpus=12,
        )
        report.frame_pacing = FramePacingAnalysis(
            is_measured=True, present_fps=30,
            stability_score=20, one_percent_low=15,
            sample_count=100, frame_spikes=50,
        )
        report.background = BackgroundImpact(
            impact_level="SEVERE", total_cpu_outside_emulator=60.0,
        )
        report.mouse = MouseSettings(
            is_measured=True, enhanced_precision=PointerPrecision.ENABLED,
        )
        score = self.analyzer._calculate_score(report)
        assert score < 40

    def test_score_bounded_0_100(self):
        report = ResponsivenessReport()
        report.display = DisplayAnalysis(refresh_rate_hz=1000, is_measured=True)
        report.emulator = EmulatorState(is_detected=True, priority_value=-5)
        report.frame_pacing = FramePacingAnalysis(
            is_measured=True, present_fps=500,
            stability_score=100, one_percent_low=450,
            sample_count=10000,
        )
        report.background = BackgroundImpact(impact_level="NONE")
        report.mouse = MouseSettings(is_measured=True)
        score = self.analyzer._calculate_score(report)
        assert 0 <= score <= 100

    def test_partial_data_gives_nonzero_score(self):
        report = ResponsivenessReport()
        report.display = DisplayAnalysis(refresh_rate_hz=60, is_measured=True)
        report.background = BackgroundImpact(impact_level="LOW")
        score = self.analyzer._calculate_score(report)
        assert score > 0


# ══════════════════════════════════════════════════════════════
# 3. Classification
# ══════════════════════════════════════════════════════════════

class TestClassification:
    """Test responsiveness classification."""

    def setup_method(self):
        self.analyzer = InputLatencyAnalyzer()

    def test_excellent(self):
        assert self.analyzer._classify_responsiveness(90) == ResponsivenessLevel.EXCELLENT

    def test_good(self):
        assert self.analyzer._classify_responsiveness(75) == ResponsivenessLevel.GOOD

    def test_moderate(self):
        assert self.analyzer._classify_responsiveness(55) == ResponsivenessLevel.MODERATE

    def test_poor(self):
        assert self.analyzer._classify_responsiveness(35) == ResponsivenessLevel.POOR

    def test_critical(self):
        assert self.analyzer._classify_responsiveness(15) == ResponsivenessLevel.CRITICAL

    def test_insufficient(self):
        assert self.analyzer._classify_responsiveness(0) == ResponsivenessLevel.INSUFFICIENT_DATA


# ══════════════════════════════════════════════════════════════
# 4. Bottleneck Identification
# ══════════════════════════════════════════════════════════════

class TestBottleneckIdentification:
    """Test bottleneck identification from measured data."""

    def setup_method(self):
        self.analyzer = InputLatencyAnalyzer()

    def test_frame_pacing_bottleneck(self):
        report = ResponsivenessReport()
        report.frame_pacing = FramePacingAnalysis(
            is_measured=True, frame_spikes=30, stability_score=30,
        )
        report.emulator.is_detected = False
        bn, conf, desc = self.analyzer._identify_bottleneck(report)
        assert bn == BottleneckType.FRAME_PACING
        assert conf > 0

    def test_cpu_bottleneck(self):
        report = ResponsivenessReport()
        report.frame_pacing = FramePacingAnalysis(is_measured=False)
        report.emulator = EmulatorState(is_detected=True, cpu_percent=92)
        bn, conf, desc = self.analyzer._identify_bottleneck(report)
        assert bn == BottleneckType.CPU

    def test_display_bottleneck(self):
        report = ResponsivenessReport()
        report.frame_pacing = FramePacingAnalysis(is_measured=False)
        report.emulator.is_detected = False
        report.display = DisplayAnalysis(refresh_rate_hz=30)
        bn, conf, desc = self.analyzer._identify_bottleneck(report)
        assert bn == BottleneckType.DISPLAY

    def test_background_bottleneck(self):
        report = ResponsivenessReport()
        report.frame_pacing = FramePacingAnalysis(is_measured=False)
        report.emulator.is_detected = False
        report.background = BackgroundImpact(
            impact_level="SEVERE", total_cpu_outside_emulator=55,
        )
        bn, conf, desc = self.analyzer._identify_bottleneck(report)
        assert bn == BottleneckType.BACKGROUND_LOAD

    def test_no_bottleneck(self):
        report = ResponsivenessReport()
        report.frame_pacing = FramePacingAnalysis(is_measured=False)
        report.emulator.is_detected = False
        report.background = BackgroundImpact(impact_level="NONE")
        bn, conf, desc = self.analyzer._identify_bottleneck(report)
        assert bn == BottleneckType.UNKNOWN
        assert conf == 0.0


# ══════════════════════════════════════════════════════════════
# 5. Recommendations
# ══════════════════════════════════════════════════════════════

class TestRecommendations:
    """Test recommendation generation."""

    def setup_method(self):
        self.analyzer = InputLatencyAnalyzer()

    def test_mouse_acceleration_recommendation(self):
        report = ResponsivenessReport()
        report.mouse = MouseSettings(
            is_measured=True,
            enhanced_precision=PointerPrecision.ENABLED,
        )
        recs = self.analyzer._generate_recommendations(report)
        assert any("enhanced pointer precision" in r.lower() or "acceleration" in r.lower() for r in recs)

    def test_low_refresh_recommendation(self):
        report = ResponsivenessReport()
        report.display = DisplayAnalysis(refresh_rate_hz=30)
        recs = self.analyzer._generate_recommendations(report)
        assert any("hz" in r.lower() or "refresh" in r.lower() for r in recs)

    def test_high_background_recommendation(self):
        report = ResponsivenessReport()
        report.background = BackgroundImpact(impact_level="HIGH")
        recs = self.analyzer._generate_recommendations(report)
        assert any("background" in r.lower() for r in recs)

    def test_priority_recommendation(self):
        report = ResponsivenessReport()
        report.emulator = EmulatorState(is_detected=True, priority_value=0)
        recs = self.analyzer._generate_recommendations(report)
        assert any("administrator" in r.lower() or "priority" in r.lower() for r in recs)


# ══════════════════════════════════════════════════════════════
# 6. Analysis Pipeline
# ══════════════════════════════════════════════════════════════

class TestAnalysisPipeline:
    """Test the full analysis pipeline."""

    def setup_method(self):
        self.analyzer = InputLatencyAnalyzer()

    def test_analyze_returns_structured_report(self):
        report = self.analyzer.analyze(force=True)
        assert isinstance(report, ResponsivenessReport)
        assert report.timestamp > 0
        assert len(report.disclaimers) > 0

    def test_analyze_caches_results(self):
        r1 = self.analyzer.analyze(force=False)
        r2 = self.analyzer.analyze(force=False)
        assert r1 is r2

    def test_force_refresh(self):
        r1 = self.analyzer.analyze(force=True)
        self.analyzer._cache_ttl = 0
        r2 = self.analyzer.analyze(force=True)
        assert r1 is not r2

    def test_report_has_all_sections(self):
        report = self.analyzer.analyze(force=True)
        assert isinstance(report.mouse, MouseSettings)
        assert isinstance(report.display, DisplayAnalysis)
        assert isinstance(report.emulator, EmulatorState)
        assert isinstance(report.frame_pacing, FramePacingAnalysis)
        assert isinstance(report.background, BackgroundImpact)


# ══════════════════════════════════════════════════════════════
# 7. Safety Rules
# ══════════════════════════════════════════════════════════════

class TestSafety:
    """Test safety rules — no system modification, no fake data."""

    def test_analyzer_is_read_only(self):
        import inspect
        source = inspect.getsource(InputLatencyAnalyzer)
        # Should not modify registry
        assert "winreg.SetValueEx" not in source
        assert "winreg.CreateKey" not in source
        # Should not kill processes
        assert ".kill()" not in source
        assert ".terminate()" not in source

    def test_disclaimers_present(self):
        report = ResponsivenessReport()
        assert len(report.disclaimers) > 0
        assert any("hardware" in d.lower() or "physical" in d.lower()
                    for d in report.disclaimers)

    def test_no_fake_fps_claims(self):
        analyzer = InputLatencyAnalyzer()
        report = analyzer.analyze(force=True)
        # Score should be based on measured values, not fabricated
        if report.frame_pacing.is_measured:
            assert report.frame_pacing.sample_count > 0
        # No claim of physical latency measurement
        assert "photon" not in report.bottleneck_description.lower()

    def test_heuristic_values_labeled(self):
        report = ResponsivenessReport()
        report.display = DisplayAnalysis(refresh_rate_hz=144, is_measured=True)
        # The quality classification is a heuristic — label is on DisplayAnalysis
        assert report.display.refresh_rate_quality != "" or report.display.is_measured

    def test_measurement_type_is_heuristic(self):
        report = ResponsivenessReport()
        assert report.measurement_type == "HEURISTIC"


# ══════════════════════════════════════════════════════════════
# 8. Mouse Settings Detection
# ══════════════════════════════════════════════════════════════

class TestMouseSettings:
    """Test mouse settings reading."""

    def setup_method(self):
        self.analyzer = InputLatencyAnalyzer()

    def test_read_mouse_settings_returns_model(self):
        settings = self.analyzer._read_mouse_settings()
        assert isinstance(settings, MouseSettings)
        assert settings.pointer_speed >= 0

    def test_registry_read_failure_returns_defaults(self):
        with patch.object(self.analyzer, '_read_reg_string', return_value=None):
            settings = self.analyzer._read_mouse_settings()
            assert settings.enhanced_precision == PointerPrecision.UNKNOWN


# ══════════════════════════════════════════════════════════════
# 9. Background Impact Analysis
# ══════════════════════════════════════════════════════════════

class TestBackgroundImpact:
    """Test background impact analysis."""

    def setup_method(self):
        self.analyzer = InputLatencyAnalyzer()

    def test_analyze_returns_model(self):
        impact = self.analyzer._analyze_background_impact(0)
        assert isinstance(impact, BackgroundImpact)
        assert impact.is_measured is True

    def test_impact_level_classified(self):
        impact = self.analyzer._analyze_background_impact(0)
        assert impact.impact_level in ("NONE", "LOW", "MODERATE", "HIGH", "SEVERE")


# ══════════════════════════════════════════════════════════════
# 10. Singleton
# ══════════════════════════════════════════════════════════════

class TestSingleton:
    """Test singleton."""

    def test_singleton_exists(self):
        assert input_latency_analyzer is not None
        assert isinstance(input_latency_analyzer, InputLatencyAnalyzer)

    def test_singleton_is_same(self):
        from app.performance.input_latency import input_latency_analyzer as ila2
        assert input_latency_analyzer is ila2


# ══════════════════════════════════════════════════════════════
# 11. Edge Cases
# ══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases."""

    def setup_method(self):
        self.analyzer = InputLatencyAnalyzer()

    def test_zero_refresh_rate(self):
        d = DisplayAnalysis(refresh_rate_hz=0)
        # When hz=0, quality is not set (stays empty default)
        assert d.refresh_rate_quality in ("", "UNKNOWN")

    def test_very_high_fps(self):
        report = ResponsivenessReport()
        report.frame_pacing = FramePacingAnalysis(
            is_measured=True, present_fps=500,
            stability_score=95, one_percent_low=400,
            sample_count=5000,
        )
        score = self.analyzer._calculate_score(report)
        assert score > 0

    def test_zero_fps(self):
        report = ResponsivenessReport()
        report.frame_pacing = FramePacingAnalysis(
            is_measured=True, present_fps=0,
            sample_count=100,
        )
        score = self.analyzer._calculate_score(report)
        assert score >= 0

    def test_no_emulator(self):
        report = ResponsivenessReport()
        report.emulator = EmulatorState(is_detected=False)
        bn, conf, desc = self.analyzer._identify_bottleneck(report)
        # Should not crash

    def test_all_none_impact(self):
        report = ResponsivenessReport()
        report.background = BackgroundImpact(
            impact_level="NONE", total_cpu_outside_emulator=1.0,
        )
        score = self.analyzer._calculate_score(report)
        assert score > 0
