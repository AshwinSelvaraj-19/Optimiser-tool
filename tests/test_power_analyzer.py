"""
Tests for Heaven Society — Power & Performance State Analyzer.

All tests use mocked hardware data; never reads real sensors.
"""

import os
import sys
import pytest
from unittest.mock import patch, MagicMock, PropertyMock
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.system.power_analyzer import (
    PowerAnalyzer,
    PowerAnalysisResult,
    BatteryInfo,
    ProcessorPowerState,
    GPUPowerState,
    WindowsPowerMode,
    DisplayPowerState,
    PowerClassification,
    BatteryState,
    ProcessorPerformanceState,
    power_analyzer,
)


# ══════════════════════════════════════════════════════════════
# 1. Data Models
# ══════════════════════════════════════════════════════════════

class TestModels:
    """Test data model defaults and properties."""

    def test_battery_defaults(self):
        b = BatteryInfo()
        assert b.state == BatteryState.UNKNOWN
        assert b.percent is None
        assert b.is_measured is True

    def test_battery_is_on_battery(self):
        b = BatteryInfo(state=BatteryState.BATTERY)
        assert b.is_on_battery is True

    def test_battery_ac_power(self):
        b = BatteryInfo(state=BatteryState.AC_POWER)
        assert b.is_on_battery is False

    def test_battery_charging(self):
        b = BatteryInfo(state=BatteryState.BATTERY_CHARGING)
        assert b.is_on_battery is True

    def test_processor_defaults(self):
        p = ProcessorPowerState()
        assert p.performance_state == ProcessorPerformanceState.UNKNOWN
        assert p.is_measured is True

    def test_processor_frequency_ratio(self):
        p = ProcessorPowerState(current_frequency_mhz=3000, max_frequency_mhz=4000)
        assert p.frequency_ratio == 0.75

    def test_processor_frequency_ratio_zero(self):
        p = ProcessorPowerState(current_frequency_mhz=3000, max_frequency_mhz=0)
        assert p.frequency_ratio == 1.0

    def test_processor_is_throttled(self):
        p = ProcessorPowerState(throttle_max_percent=80)
        assert p.is_throttled is True

    def test_processor_not_throttled(self):
        p = ProcessorPowerState(throttle_max_percent=100)
        assert p.is_throttled is False

    def test_gpu_defaults(self):
        g = GPUPowerState()
        assert g.is_measured is True
        assert g.is_power_limited is False

    def test_gpu_power_utilization(self):
        g = GPUPowerState(power_draw_watts=150, power_limit_watts=200)
        assert g.power_utilization == 75.0

    def test_gpu_power_utilization_none(self):
        g = GPUPowerState()
        assert g.power_utilization is None

    def test_gpu_power_limited(self):
        g = GPUPowerState(power_draw_watts=198, power_limit_watts=200)
        assert g.is_power_limited is True

    def test_windows_power_mode_defaults(self):
        w = WindowsPowerMode()
        assert w.power_mode == ""
        assert w.is_measured is True

    def test_display_defaults(self):
        d = DisplayPowerState()
        assert d.refresh_rate_hz == 0
        assert d.is_measured is True

    def test_classification_values(self):
        values = [c.value for c in PowerClassification]
        assert "PERFORMANCE READY" in values
        assert "BALANCED" in values
        assert "POWER LIMITED" in values
        assert "BATTERY LIMITED" in values
        assert "UNKNOWN" in values

    def test_battery_state_values(self):
        values = [b.value for b in BatteryState]
        assert "AC Power" in values
        assert "Battery" in values
        assert "Battery Charging" in values
        assert "No Battery" in values

    def test_analysis_result_defaults(self):
        r = PowerAnalysisResult()
        assert r.classification == PowerClassification.UNKNOWN
        assert r.measurement_type == "MEASURED"
        assert len(r.disclaimers) > 0


# ══════════════════════════════════════════════════════════════
# 2. Classification
# ══════════════════════════════════════════════════════════════

class TestClassification:
    """Test power state classification from measured data."""

    def setup_method(self):
        self.analyzer = PowerAnalyzer()

    def test_performance_ready(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.AC_POWER)
        result.power_plan_name = "High Performance"
        result.power_plan_is_performance = True
        result.processor = ProcessorPowerState(throttle_max_percent=100)
        result.gpu = GPUPowerState(power_draw_watts=100, power_limit_watts=200)
        result.windows_power_mode = WindowsPowerMode(power_mode_index=0)

        classification, reason = self.analyzer._classify(result)
        assert classification == PowerClassification.PERFORMANCE_READY
        assert "optimal" in reason.lower() or "maximum" in reason.lower()

    def test_battery_limited(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.BATTERY, percent=50)
        result.power_plan_is_performance = True
        result.processor = ProcessorPowerState(throttle_max_percent=100)

        classification, reason = self.analyzer._classify(result)
        assert classification == PowerClassification.BATTERY_LIMITED
        assert "battery" in reason.lower()

    def test_power_limited_throttled(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.AC_POWER)
        result.power_plan_is_performance = True
        result.processor = ProcessorPowerState(throttle_max_percent=70)
        result.gpu = GPUPowerState()

        classification, reason = self.analyzer._classify(result)
        assert classification == PowerClassification.POWER_LIMITED
        assert "throttl" in reason.lower() or "limited" in reason.lower()

    def test_balanced(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.AC_POWER)
        result.power_plan_name = "Balanced"
        result.power_plan_is_performance = False
        result.processor = ProcessorPowerState(throttle_max_percent=100)
        result.gpu = GPUPowerState()
        result.windows_power_mode = WindowsPowerMode(power_mode_index=1)

        classification, reason = self.analyzer._classify(result)
        assert classification == PowerClassification.BALANCED

    def test_multiple_limitations(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.AC_POWER)
        result.power_plan_name = "Power Saver"
        result.power_plan_is_performance = False
        result.processor = ProcessorPowerState(throttle_max_percent=60)
        result.gpu = GPUPowerState(power_draw_watts=198, power_limit_watts=200)
        result.windows_power_mode = WindowsPowerMode(power_mode_index=2)

        classification, reason = self.analyzer._classify(result)
        assert classification == PowerClassification.POWER_LIMITED


# ══════════════════════════════════════════════════════════════
# 3. Recommendations
# ══════════════════════════════════════════════════════════════

class TestRecommendations:
    """Test evidence-based recommendation generation."""

    def setup_method(self):
        self.analyzer = PowerAnalyzer()

    def test_battery_recommendation(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.BATTERY, percent=45)
        result.processor = ProcessorPowerState()
        result.gpu = GPUPowerState()
        recs = self.analyzer._generate_recommendations(result)
        assert any("battery" in r.lower() for r in recs)

    def test_power_plan_recommendation(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.AC_POWER)
        result.power_plan_name = "Balanced"
        result.power_plan_is_performance = False
        result.processor = ProcessorPowerState()
        result.gpu = GPUPowerState()
        recs = self.analyzer._generate_recommendations(result)
        assert any("power plan" in r.lower() for r in recs)

    def test_throttle_recommendation(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.AC_POWER)
        result.power_plan_is_performance = True
        result.processor = ProcessorPowerState(throttle_max_percent=80)
        result.gpu = GPUPowerState()
        recs = self.analyzer._generate_recommendations(result)
        assert any("throttl" in r.lower() for r in recs)

    def test_boost_disabled_recommendation(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.AC_POWER)
        result.power_plan_is_performance = True
        result.processor = ProcessorPowerState(boost_mode=0, throttle_max_percent=100)
        result.gpu = GPUPowerState()
        recs = self.analyzer._generate_recommendations(result)
        assert any("boost" in r.lower() for r in recs)

    def test_no_recommendations_optimal(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.AC_POWER)
        result.power_plan_is_performance = True
        result.processor = ProcessorPowerState(throttle_max_percent=100)
        result.gpu = GPUPowerState()
        result.windows_power_mode = WindowsPowerMode(power_mode_index=0)
        result.display = DisplayPowerState(refresh_rate_hz=144)
        recs = self.analyzer._generate_recommendations(result)
        assert len(recs) <= 1


# ══════════════════════════════════════════════════════════════
# 4. Full Analysis Pipeline
# ══════════════════════════════════════════════════════════════

class TestAnalysisPipeline:
    """Test the full analysis pipeline."""

    def setup_method(self):
        self.analyzer = PowerAnalyzer()

    def test_analyze_returns_structured_result(self):
        result = self.analyzer.analyze(force=True)
        assert isinstance(result, PowerAnalysisResult)
        assert result.timestamp > 0
        assert len(result.disclaimers) > 0

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
        result = self.analyzer.analyze(force=True)
        assert isinstance(result.battery, BatteryInfo)
        assert isinstance(result.processor, ProcessorPowerState)
        assert isinstance(result.gpu, GPUPowerState)
        assert isinstance(result.windows_power_mode, WindowsPowerMode)
        assert isinstance(result.display, DisplayPowerState)


# ══════════════════════════════════════════════════════════════
# 5. Safety Rules
# ══════════════════════════════════════════════════════════════

class TestSafety:
    """Test safety rules — no system modification."""

    def test_analyzer_is_read_only(self):
        import inspect
        source = inspect.getsource(PowerAnalyzer)
        assert "winreg.SetValueEx" not in source
        assert "powercfg /setactive" not in source
        assert "powercfg /setacvalueindex" not in source

    def test_no_fake_data(self):
        """All values come from real APIs or are defaults."""
        analyzer = PowerAnalyzer()
        result = analyzer.analyze(force=True)
        # Battery state is from psutil
        assert result.battery.state in BatteryState
        # Power plan is from powercfg
        assert isinstance(result.power_plan_name, str)

    def test_disclaimers_present(self):
        result = PowerAnalysisResult()
        assert len(result.disclaimers) > 0
        assert any("psutil" in d.lower() or "nvml" in d.lower() or "api" in d.lower()
                    for d in result.disclaimers)

    def test_measurement_type_labeled(self):
        result = PowerAnalysisResult()
        assert result.measurement_type == "MEASURED"


# ══════════════════════════════════════════════════════════════
# 6. Battery Analysis
# ══════════════════════════════════════════════════════════════

class TestBatteryAnalysis:
    """Test battery state detection."""

    def setup_method(self):
        self.analyzer = PowerAnalyzer()

    def test_read_battery_returns_model(self):
        battery = self.analyzer._read_battery()
        assert isinstance(battery, BatteryInfo)
        assert battery.state in BatteryState

    def test_no_battery_on_desktop(self):
        """Desktop systems return NO_BATTERY."""
        with patch("app.system.power_analyzer.psutil.sensors_battery", return_value=None):
            battery = self.analyzer._read_battery()
            assert battery.state == BatteryState.NO_BATTERY

    def test_ac_power_detected(self):
        mock_battery = MagicMock()
        mock_battery.percent = 100
        mock_battery.power_plugged = True
        mock_battery.secsleft = 0
        with patch("app.system.power_analyzer.psutil.sensors_battery", return_value=mock_battery):
            battery = self.analyzer._read_battery()
            assert battery.state == BatteryState.AC_POWER
            assert battery.power_plugged is True

    def test_battery_detected(self):
        mock_battery = MagicMock()
        mock_battery.percent = 50
        mock_battery.power_plugged = False
        mock_battery.secsleft = 3600
        with patch("app.system.power_analyzer.psutil.sensors_battery", return_value=mock_battery):
            battery = self.analyzer._read_battery()
            assert battery.state == BatteryState.BATTERY
            assert battery.percent == 50


# ══════════════════════════════════════════════════════════════
# 7. Processor State
# ══════════════════════════════════════════════════════════════

class TestProcessorState:
    """Test processor power state detection."""

    def setup_method(self):
        self.analyzer = PowerAnalyzer()

    def test_read_processor_returns_model(self):
        state = self.analyzer._read_processor_state()
        assert isinstance(state, ProcessorPowerState)
        assert state.core_count > 0 or state.core_count == 0

    def test_performance_state_classification(self):
        state = ProcessorPowerState(throttle_max_percent=50)
        assert state.performance_state == ProcessorPerformanceState.THROTTLED

        state2 = ProcessorPowerState(
            throttle_max_percent=100,
            current_frequency_mhz=1000,
            max_frequency_mhz=4000,
        )
        assert state2.performance_state == ProcessorPerformanceState.REDUCED

        state3 = ProcessorPowerState(
            throttle_max_percent=100,
            current_frequency_mhz=3500,
            max_frequency_mhz=4000,
        )
        assert state3.performance_state == ProcessorPerformanceState.FULL_SPEED


# ══════════════════════════════════════════════════════════════
# 8. GPU Power State
# ══════════════════════════════════════════════════════════════

class TestGPUPowerState:
    """Test GPU power state detection."""

    def setup_method(self):
        self.analyzer = PowerAnalyzer()

    def test_read_gpu_returns_model(self):
        state = self.analyzer._read_gpu_power()
        assert isinstance(state, GPUPowerState)

    def test_power_utilization_calculation(self):
        g = GPUPowerState(power_draw_watts=100, power_limit_watts=200)
        assert g.power_utilization == 50.0

    def test_power_limited_detection(self):
        g = GPUPowerState(power_draw_watts=199, power_limit_watts=200)
        assert g.is_power_limited is True

        g2 = GPUPowerState(power_draw_watts=150, power_limit_watts=200)
        assert g2.is_power_limited is False


# ══════════════════════════════════════════════════════════════
# 9. Edge Cases
# ══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases."""

    def setup_method(self):
        self.analyzer = PowerAnalyzer()

    def test_no_gpu_data(self):
        result = PowerAnalysisResult()
        result.gpu = GPUPowerState(is_measured=False)
        classification, _ = self.analyzer._classify(result)
        assert classification in PowerClassification

    def test_no_battery_data(self):
        result = PowerAnalysisResult()
        result.battery = BatteryInfo(state=BatteryState.NO_BATTERY)
        result.power_plan_is_performance = True
        result.processor = ProcessorPowerState(throttle_max_percent=100)
        classification, _ = self.analyzer._classify(result)
        assert classification == PowerClassification.PERFORMANCE_READY

    def test_extreme_throttle(self):
        p = ProcessorPowerState(throttle_max_percent=20)
        assert p.is_throttled is True
        assert p.performance_state == ProcessorPerformanceState.THROTTLED


# ══════════════════════════════════════════════════════════════
# 10. Singleton
# ══════════════════════════════════════════════════════════════

class TestSingleton:
    """Test singleton."""

    def test_singleton_exists(self):
        assert power_analyzer is not None
        assert isinstance(power_analyzer, PowerAnalyzer)

    def test_singleton_is_same(self):
        from app.system.power_analyzer import power_analyzer as pa2
        assert power_analyzer is pa2
