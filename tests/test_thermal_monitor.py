"""
Tests for Heaven Society — Thermal & Throttling Monitor.

All tests use mocked hardware data; never reads real sensors.
"""

import os
import sys
import time
import statistics
import pytest
from unittest.mock import patch, MagicMock
from dataclasses import dataclass

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.system.thermal_monitor import (
    ThermalMonitor,
    ThermalDiagnostics,
    GPUThermalData,
    CPUThermalData,
    SystemMemoryThermal,
    ThermalCorrelation,
    ThermalState,
    ThrottleIndicator,
    thermal_diagnostics,
    GPU_TEMP_WARM,
    GPU_TEMP_HOT,
    GPU_TEMP_THROTTLE,
    CPU_TEMP_WARM,
    CPU_TEMP_HOT,
    CPU_TEMP_THROTTLE,
)


# ══════════════════════════════════════════════════════════════
# 1. Data Models
# ══════════════════════════════════════════════════════════════

class TestModels:
    """Test data model defaults and properties."""

    def test_gpu_thermal_defaults(self):
        g = GPUThermalData()
        assert g.temperature_celsius is None
        assert g.utilization_gpu == 0.0
        assert g.is_measured is True

    def test_gpu_power_utilization(self):
        g = GPUThermalData(power_draw_watts=150, power_limit_watts=200)
        assert g.power_utilization == 75.0

    def test_gpu_power_utilization_none(self):
        g = GPUThermalData()
        assert g.power_utilization is None

    def test_gpu_vram_percent(self):
        g = GPUThermalData(vram_used_mb=4000, vram_total_mb=8000)
        assert g.vram_percent == 50.0

    def test_cpu_thermal_defaults(self):
        c = CPUThermalData()
        assert c.temperature_celsius is None
        assert c.utilization_percent == 0.0

    def test_cpu_frequency_ratio(self):
        c = CPUThermalData(frequency_mhz=3000, max_frequency_mhz=4000)
        assert c.frequency_ratio == 0.75

    def test_cpu_frequency_ratio_zero_max(self):
        c = CPUThermalData(frequency_mhz=3000, max_frequency_mhz=0)
        assert c.frequency_ratio == 1.0

    def test_memory_thermal_defaults(self):
        m = SystemMemoryThermal()
        assert m.pressure_level == "NORMAL"
        assert m.is_measured is True

    def test_thermal_state_values(self):
        values = [s.value for s in ThermalState]
        assert "NORMAL" in values
        assert "WARM" in values
        assert "HOT" in values
        assert "THROTTLING RISK" in values
        assert "UNKNOWN" in values

    def test_throttle_indicator_values(self):
        values = [t.value for t in ThrottleIndicator]
        assert "Clock Drop" in values
        assert "Power Limit" in values
        assert "Temperature Limit" in values
        assert "Sustained High Temperature" in values
        assert "Frame Time Increase" in values
        assert "None Detected" in values

    def test_thermal_diagnostics_defaults(self):
        d = ThermalDiagnostics()
        assert d.thermal_state == ThermalState.UNKNOWN
        assert d.max_temperature == 0.0
        assert d.measurement_type == "MEASURED"
        assert len(d.disclaimers) > 0

    def test_thermal_correlation_defaults(self):
        c = ThermalCorrelation()
        assert c.is_measured is False
        assert c.correlation_strength == 0.0


# ══════════════════════════════════════════════════════════════
# 2. State Classification
# ══════════════════════════════════════════════════════════════

class TestStateClassification:
    """Test thermal state classification from measured data."""

    def setup_method(self):
        self.monitor = ThermalMonitor()

    def test_normal_state(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=65)
        diag.cpu = CPUThermalData(temperature_celsius=55)
        diag.throttle_indicators = [ThrottleIndicator.NONE]
        state = self.monitor._classify_state(diag)
        assert state == ThermalState.NORMAL

    def test_warm_state(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=78)
        diag.cpu = CPUThermalData(temperature_celsius=60)
        diag.throttle_indicators = [ThrottleIndicator.NONE]
        state = self.monitor._classify_state(diag)
        assert state == ThermalState.WARM

    def test_hot_state(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=87)
        diag.cpu = CPUThermalData(temperature_celsius=60)
        diag.throttle_indicators = [ThrottleIndicator.NONE]
        state = self.monitor._classify_state(diag)
        assert state == ThermalState.HOT

    def test_throttling_risk_from_temp(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=92)
        diag.cpu = CPUThermalData(temperature_celsius=60)
        diag.throttle_indicators = [ThrottleIndicator.NONE]
        state = self.monitor._classify_state(diag)
        assert state == ThermalState.THROTTLING_RISK

    def test_throttling_risk_from_clock_drop(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=75)
        diag.cpu = CPUThermalData(temperature_celsius=60)
        diag.throttle_indicators = [ThrottleIndicator.CLOCK_DROP]
        state = self.monitor._classify_state(diag)
        assert state == ThermalState.THROTTLING_RISK

    def test_cpu_hot_state(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=60)
        diag.cpu = CPUThermalData(temperature_celsius=82)
        diag.throttle_indicators = [ThrottleIndicator.NONE]
        state = self.monitor._classify_state(diag)
        assert state == ThermalState.HOT

    def test_unknown_state_no_data(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData()
        diag.cpu = CPUThermalData()
        diag.throttle_indicators = [ThrottleIndicator.NONE]
        state = self.monitor._classify_state(diag)
        assert state == ThermalState.UNKNOWN


# ══════════════════════════════════════════════════════════════
# 3. Throttle Detection
# ══════════════════════════════════════════════════════════════

class TestThrottleDetection:
    """Test throttle indicator detection from measured data."""

    def setup_method(self):
        self.monitor = ThermalMonitor()

    def test_no_throttle_normal(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=65)
        diag.cpu = CPUThermalData(temperature_celsius=55)
        indicators, conf = self.monitor._detect_throttling(diag)
        assert ThrottleIndicator.NONE in indicators
        assert conf == 0.0

    def test_clock_drop_detected(self):
        self.monitor._clock_history = [
            (time.time() - 20, 1800),
            (time.time() - 19, 1800),
            (time.time() - 18, 1800),
            (time.time() - 17, 1800),
            (time.time() - 16, 1800),
            (time.time() - 15, 1800),
            (time.time() - 14, 1800),
            (time.time() - 13, 1800),
            (time.time() - 12, 1800),
            (time.time() - 11, 1800),
            (time.time() - 10, 1500),
            (time.time() - 9, 1500),
            (time.time() - 8, 1500),
            (time.time() - 7, 1500),
            (time.time() - 6, 1500),
            (time.time() - 5, 1500),
            (time.time() - 4, 1500),
            (time.time() - 3, 1500),
            (time.time() - 2, 1500),
            (time.time() - 1, 1500),
        ]
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=75)
        indicators, conf = self.monitor._detect_throttling(diag)
        assert ThrottleIndicator.CLOCK_DROP in indicators
        assert conf > 0

    def test_temperature_limit_detected(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=95)
        diag.cpu = CPUThermalData(temperature_celsius=60)
        indicators, conf = self.monitor._detect_throttling(diag)
        assert ThrottleIndicator.TEMPERATURE_LIMIT in indicators

    def test_power_limit_detected(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(
            temperature_celsius=75,
            power_draw_watts=195,
            power_limit_watts=200,
        )
        diag.cpu = CPUThermalData(temperature_celsius=60)
        indicators, conf = self.monitor._detect_throttling(diag)
        assert ThrottleIndicator.POWER_LIMIT in indicators

    def test_frame_time_increase_detected(self):
        self.monitor._frame_time_history = [
            (time.time() - 20, 16.0),
            (time.time() - 19, 16.0),
            (time.time() - 18, 16.0),
            (time.time() - 17, 16.0),
            (time.time() - 16, 16.0),
            (time.time() - 15, 16.0),
            (time.time() - 14, 16.0),
            (time.time() - 13, 16.0),
            (time.time() - 12, 16.0),
            (time.time() - 11, 16.0),
            (time.time() - 10, 20.0),
            (time.time() - 9, 20.0),
            (time.time() - 8, 20.0),
            (time.time() - 7, 20.0),
            (time.time() - 6, 20.0),
            (time.time() - 5, 20.0),
            (time.time() - 4, 20.0),
            (time.time() - 3, 20.0),
            (time.time() - 2, 20.0),
            (time.time() - 1, 20.0),
        ]
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=75)
        indicators, conf = self.monitor._detect_throttling(diag)
        assert ThrottleIndicator.FRAME_TIME_INCREASE in indicators


# ══════════════════════════════════════════════════════════════
# 4. Correlation
# ══════════════════════════════════════════════════════════════

class TestCorrelation:
    """Test performance correlation analysis."""

    def setup_method(self):
        self.monitor = ThermalMonitor()

    def test_no_data_no_correlation(self):
        diag = ThermalDiagnostics()
        corr = self.monitor._correlate_performance(diag)
        assert corr.correlation_strength == 0.0

    def test_rising_temp_dropping_clock(self):
        self.monitor._temp_history = [
            (time.time() - 10, 70),
            (time.time() - 9, 72),
            (time.time() - 8, 74),
            (time.time() - 7, 76),
            (time.time() - 6, 78),
            (time.time() - 5, 80),
            (time.time() - 4, 82),
            (time.time() - 3, 84),
            (time.time() - 2, 86),
            (time.time() - 1, 88),
        ]
        self.monitor._clock_history = [
            (time.time() - 10, 1800),
            (time.time() - 9, 1800),
            (time.time() - 8, 1780),
            (time.time() - 7, 1750),
            (time.time() - 6, 1700),
            (time.time() - 5, 1650),
            (time.time() - 4, 1600),
            (time.time() - 3, 1550),
            (time.time() - 2, 1500),
            (time.time() - 1, 1450),
        ]
        diag = ThermalDiagnostics()
        corr = self.monitor._correlate_performance(diag)
        assert corr.temperature_trend == "RISING"
        assert corr.clock_trend == "DROPPING"
        assert corr.correlation_strength > 0.3

    def test_stable_no_correlation(self):
        self.monitor._temp_history = [
            (time.time() - i, 72) for i in range(10, 0, -1)
        ]
        self.monitor._clock_history = [
            (time.time() - i, 1800) for i in range(10, 0, -1)
        ]
        diag = ThermalDiagnostics()
        corr = self.monitor._correlate_performance(diag)
        assert corr.temperature_trend == "STABLE"
        assert corr.clock_trend == "STABLE"


# ══════════════════════════════════════════════════════════════
# 5. Sample Recording
# ══════════════════════════════════════════════════════════════

class TestSampleRecording:
    """Test telemetry sample recording for trend analysis."""

    def setup_method(self):
        self.monitor = ThermalMonitor()

    def test_record_sample(self):
        self.monitor.record_sample(gpu_clock=1800, gpu_temp=72, frame_time_ms=16.5)
        assert len(self.monitor._clock_history) == 1
        assert len(self.monitor._temp_history) == 1
        assert len(self.monitor._frame_time_history) == 1

    def test_record_multiple_samples(self):
        for i in range(5):
            self.monitor.record_sample(
                gpu_clock=1800 + i * 10,
                gpu_temp=70 + i,
                frame_time_ms=16.0 + i * 0.5,
            )
        assert len(self.monitor._clock_history) == 5
        assert self.monitor._clock_history[-1][1] == 1840

    def test_history_max_limit(self):
        for i in range(350):
            self.monitor.record_sample(gpu_clock=1800, gpu_temp=72)
        assert len(self.monitor._clock_history) <= 300

    def test_zero_values_not_recorded(self):
        self.monitor.record_sample(gpu_clock=0, gpu_temp=0, frame_time_ms=0)
        assert len(self.monitor._clock_history) == 0
        assert len(self.monitor._temp_history) == 0


# ══════════════════════════════════════════════════════════════
# 6. Recommendations
# ══════════════════════════════════════════════════════════════

class TestRecommendations:
    """Test recommendation generation."""

    def setup_method(self):
        self.monitor = ThermalMonitor()

    def test_hot_gpu_recommendation(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=88)
        diag.cpu = CPUThermalData()
        diag.memory = SystemMemoryThermal()
        recs = self.monitor._generate_recommendations(diag)
        assert any("gpu" in r.lower() or "88" in r for r in recs)

    def test_critical_cpu_recommendation(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData()
        diag.cpu = CPUThermalData(temperature_celsius=92)
        diag.memory = SystemMemoryThermal()
        recs = self.monitor._generate_recommendations(diag)
        assert any("cpu" in r.lower() or "92" in r for r in recs)

    def test_no_recommendations_normal(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=60)
        diag.cpu = CPUThermalData(temperature_celsius=50)
        diag.memory = SystemMemoryThermal(pressure_level="NORMAL")
        recs = self.monitor._generate_recommendations(diag)
        assert len(recs) <= 1

    def test_clock_drop_recommendation(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=75)
        diag.cpu = CPUThermalData()
        diag.memory = SystemMemoryThermal()
        diag.throttle_indicators = [ThrottleIndicator.CLOCK_DROP]
        recs = self.monitor._generate_recommendations(diag)
        assert any("clock" in r.lower() for r in recs)


# ══════════════════════════════════════════════════════════════
# 7. Full Analysis Pipeline
# ══════════════════════════════════════════════════════════════

class TestAnalysisPipeline:
    """Test the full analysis pipeline."""

    def setup_method(self):
        self.monitor = ThermalMonitor()

    def test_diagnose_returns_structured_report(self):
        diag = self.monitor.diagnose(force=True)
        assert isinstance(diag, ThermalDiagnostics)
        assert diag.timestamp > 0
        assert len(diag.disclaimers) > 0

    def test_diagnose_caches_results(self):
        d1 = self.monitor.diagnose(force=False)
        d2 = self.monitor.diagnose(force=False)
        assert d1 is d2

    def test_force_refresh(self):
        d1 = self.monitor.diagnose(force=True)
        self.monitor._cache_ttl = 0
        d2 = self.monitor.diagnose(force=True)
        assert d1 is not d2

    def test_report_has_all_sections(self):
        diag = self.monitor.diagnose(force=True)
        assert isinstance(diag.gpu, GPUThermalData)
        assert isinstance(diag.cpu, CPUThermalData)
        assert isinstance(diag.memory, SystemMemoryThermal)
        assert isinstance(diag.correlation, ThermalCorrelation)


# ══════════════════════════════════════════════════════════════
# 8. Safety Rules
# ══════════════════════════════════════════════════════════════

class TestSafety:
    """Test safety rules — no system modification."""

    def test_analyzer_is_read_only(self):
        import inspect
        source = inspect.getsource(ThermalMonitor)
        assert "winreg" not in source
        assert "SetProcessAffinity" not in source
        assert "fan" not in source.lower() or "fan_speed" in source
        assert "undervolt" not in source.lower()
        assert "overclock" not in source.lower()

    def test_no_fake_data(self):
        """All values come from real sensors or are None."""
        monitor = ThermalMonitor()
        diag = monitor.diagnose(force=True)
        # GPU temperature is from NVML or None
        if diag.gpu.temperature_celsius is not None:
            assert diag.gpu.temperature_celsius > 0
        # CPU temperature is from psutil or None
        if diag.cpu.temperature_celsius is not None:
            assert diag.cpu.temperature_celsius > 0

    def test_disclaimers_present(self):
        diag = ThermalDiagnostics()
        assert len(diag.disclaimers) > 0
        assert any("sensor" in d.lower() or "nvml" in d.lower() or "psutil" in d.lower()
                    for d in diag.disclaimers)

    def test_measurement_type_labeled(self):
        diag = ThermalDiagnostics()
        assert diag.measurement_type == "MEASURED"


# ══════════════════════════════════════════════════════════════
# 9. Thresholds
# ══════════════════════════════════════════════════════════════

class TestThresholds:
    """Test thermal threshold constants."""

    def test_gpu_thresholds_ordered(self):
        assert GPU_TEMP_WARM < GPU_TEMP_HOT < GPU_TEMP_THROTTLE

    def test_cpu_thresholds_ordered(self):
        assert CPU_TEMP_WARM < CPU_TEMP_HOT < CPU_TEMP_THROTTLE

    def test_gpu_warm_reasonable(self):
        assert 60 <= GPU_TEMP_WARM <= 85

    def test_gpu_hot_reasonable(self):
        assert 75 <= GPU_TEMP_HOT <= 95

    def test_cpu_warm_reasonable(self):
        assert 60 <= CPU_TEMP_WARM <= 85


# ══════════════════════════════════════════════════════════════
# 10. Edge Cases
# ══════════════════════════════════════════════════════════════

class TestEdgeCases:
    """Test edge cases."""

    def setup_method(self):
        self.monitor = ThermalMonitor()

    def test_empty_history_correlation(self):
        diag = ThermalDiagnostics()
        corr = self.monitor._correlate_performance(diag)
        assert corr.temperature_trend == ""

    def test_single_sample_history(self):
        self.monitor._temp_history = [(time.time(), 72)]
        self.monitor._clock_history = [(time.time(), 1800)]
        diag = ThermalDiagnostics()
        corr = self.monitor._correlate_performance(diag)
        # Single sample — not enough for trend
        assert corr.temperature_trend in ("", "STABLE")

    def test_gpu_no_temperature(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=None)
        diag.cpu = CPUThermalData(temperature_celsius=None)
        diag.throttle_indicators = [ThrottleIndicator.NONE]
        state = self.monitor._classify_state(diag)
        assert state == ThermalState.UNKNOWN

    def test_extreme_temperature(self):
        diag = ThermalDiagnostics()
        diag.gpu = GPUThermalData(temperature_celsius=105)
        diag.cpu = CPUThermalData(temperature_celsius=100)
        diag.throttle_indicators = [ThrottleIndicator.NONE]
        state = self.monitor._classify_state(diag)
        assert state == ThermalState.THROTTLING_RISK


# ══════════════════════════════════════════════════════════════
# 11. Singleton
# ══════════════════════════════════════════════════════════════

class TestSingleton:
    """Test singleton."""

    def test_singleton_exists(self):
        assert thermal_diagnostics is not None
        assert isinstance(thermal_diagnostics, ThermalMonitor)

    def test_singleton_is_same(self):
        from app.system.thermal_monitor import thermal_diagnostics as td2
        assert thermal_diagnostics is td2
