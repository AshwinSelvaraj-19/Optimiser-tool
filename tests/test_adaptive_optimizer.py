"""
Tests for Heaven Society — Adaptive Gaming Optimizer (Phase 25).

Uses mocked subsystems; never requires real hardware.
"""

import pytest
from unittest.mock import patch, MagicMock

from app.core.adaptive_optimizer import (
    AdaptiveOptimizer,
    OptimizationDecision,
    OptimizationAction,
    BottleneckEvidence,
    BottleneckType,
    ExpectedImpact,
    adaptive_optimizer,
)


class TestBottleneckType:
    """Test BottleneckType enum."""

    def test_all_values(self):
        assert BottleneckType.CPU.value == "CPU"
        assert BottleneckType.GPU.value == "GPU"
        assert BottleneckType.MEMORY.value == "MEMORY"
        assert BottleneckType.THERMAL.value == "THERMAL"
        assert BottleneckType.POWER.value == "POWER"
        assert BottleneckType.FRAME_PACING.value == "FRAME PACING"
        assert BottleneckType.BACKGROUND_LOAD.value == "BACKGROUND LOAD"
        assert BottleneckType.DISPLAY.value == "DISPLAY"
        assert BottleneckType.EMULATOR_CONFIGURATION.value == "EMULATOR CONFIGURATION"
        assert BottleneckType.UNKNOWN.value == "UNKNOWN"

    def test_count(self):
        assert len(BottleneckType) == 10


class TestExpectedImpact:
    """Test ExpectedImpact enum."""

    def test_all_values(self):
        assert ExpectedImpact.HIGH.value == "HIGH"
        assert ExpectedImpact.MEDIUM.value == "MEDIUM"
        assert ExpectedImpact.LOW.value == "LOW"
        assert ExpectedImpact.UNKNOWN.value == "UNKNOWN"


class TestOptimizationDecision:
    """Test OptimizationDecision dataclass."""

    def test_defaults(self):
        d = OptimizationDecision()
        assert d.bottleneck == BottleneckType.UNKNOWN
        assert d.bottleneck_confidence == 0.0
        assert d.evidence == []
        assert d.recommended_optimizations == []
        assert d.skipped_optimizations == []
        assert d.risks == []
        assert d.expected_impact == ExpectedImpact.UNKNOWN
        assert d.has_emulator is False
        assert d.has_fps_data is False
        assert d.timestamp > 0

    def test_with_values(self):
        d = OptimizationDecision(
            bottleneck=BottleneckType.CPU,
            bottleneck_confidence=0.85,
            has_emulator=True,
            emulator_name="HD-Player.exe",
            emulator_pid=1234,
        )
        assert d.bottleneck == BottleneckType.CPU
        assert d.bottleneck_confidence == 0.85
        assert d.emulator_name == "HD-Player.exe"


class TestOptimizationAction:
    """Test OptimizationAction dataclass."""

    def test_defaults(self):
        a = OptimizationAction()
        assert a.id == ""
        assert a.status == ""
        assert a.risk == "LOW"
        assert a.expected_impact == "UNKNOWN"

    def test_with_values(self):
        a = OptimizationAction(
            id="power_plan",
            name="Power Plan",
            status="APPLICABLE",
            risk="LOW",
            expected_impact="MEDIUM",
        )
        assert a.id == "power_plan"
        assert a.status == "APPLICABLE"


class TestBottleneckEvidence:
    """Test BottleneckEvidence dataclass."""

    def test_defaults(self):
        e = BottleneckEvidence()
        assert e.bottleneck_type == BottleneckType.UNKNOWN
        assert e.metric_value == 0.0
        assert e.threshold == 0.0

    def test_with_values(self):
        e = BottleneckEvidence(
            bottleneck_type=BottleneckType.CPU,
            metric_name="CPU Usage",
            metric_value=92.0,
            threshold=85.0,
            source="test",
            description="CPU at 92%",
        )
        assert e.bottleneck_type == BottleneckType.CPU
        assert e.metric_value == 92.0


class TestBottleneckClassification:
    """Test bottleneck classification logic."""

    def _make_optimizer(self):
        return AdaptiveOptimizer()

    def test_no_evidence_gives_unknown(self):
        optimizer = self._make_optimizer()
        bt, conf, desc = optimizer._classify_bottleneck([])
        assert bt == BottleneckType.UNKNOWN
        assert conf == 0.0

    def test_single_cpu_evidence(self):
        optimizer = self._make_optimizer()
        evidence = [
            BottleneckEvidence(
                bottleneck_type=BottleneckType.CPU,
                metric_name="CPU Usage",
                metric_value=95.0,
                threshold=85.0,
                description="CPU at 95%",
            ),
        ]
        bt, conf, desc = optimizer._classify_bottleneck(evidence)
        assert bt == BottleneckType.CPU
        assert conf > 0.0

    def test_dominant_bottleneck(self):
        optimizer = self._make_optimizer()
        evidence = [
            BottleneckEvidence(
                bottleneck_type=BottleneckType.CPU,
                metric_name="CPU",
                metric_value=95.0,
                threshold=85.0,
                description="CPU at 95%",
            ),
            BottleneckEvidence(
                bottleneck_type=BottleneckType.CPU,
                metric_name="CPU/GPU",
                metric_value=3.0,
                threshold=2.0,
                description="CPU bound",
            ),
            BottleneckEvidence(
                bottleneck_type=BottleneckType.GPU,
                metric_name="GPU",
                metric_value=60.0,
                threshold=90.0,
                description="GPU moderate",
            ),
        ]
        bt, conf, desc = optimizer._classify_bottleneck(evidence)
        assert bt == BottleneckType.CPU
        assert conf > 0.3

    def test_multiple_equal_bottlenecks(self):
        optimizer = self._make_optimizer()
        evidence = [
            BottleneckEvidence(
                bottleneck_type=BottleneckType.CPU,
                metric_name="CPU",
                metric_value=90.0,
                threshold=85.0,
                description="CPU high",
            ),
            BottleneckEvidence(
                bottleneck_type=BottleneckType.MEMORY,
                metric_name="RAM",
                metric_value=92.0,
                threshold=90.0,
                description="RAM critical",
            ),
        ]
        bt, conf, desc = optimizer._classify_bottleneck(evidence)
        # One should be selected
        assert bt in (BottleneckType.CPU, BottleneckType.MEMORY)
        assert conf > 0.0

    def test_binary_evidence(self):
        """Evidence without a threshold (binary) should still contribute."""
        optimizer = self._make_optimizer()
        evidence = [
            BottleneckEvidence(
                bottleneck_type=BottleneckType.POWER,
                metric_name="Battery",
                metric_value=0.0,
                threshold=0.0,
                description="On battery",
            ),
        ]
        bt, conf, desc = optimizer._classify_bottleneck(evidence)
        assert bt == BottleneckType.POWER


class TestEvidenceCollection:
    """Test evidence collection from mocked subsystems."""

    def _make_optimizer(self):
        return AdaptiveOptimizer()

    def test_collect_with_cpu_bottleneck(self):
        optimizer = self._make_optimizer()

        # Mock emulator target with high CPU
        emu = MagicMock()
        emu.cpu_percent = 92.0
        emu.priority = 0
        emu.priority_name = "NORMAL"
        emu.is_high_priority = False
        emu.affinity_cpus = 6
        emu.total_cpus = 12
        emu.uses_all_cpus = False

        gpu = MagicMock()
        gpu.utilization_percent = 40.0
        gpu.temperature_celsius = None

        evidence = optimizer._collect_evidence(
            hw_spec=None, emulator_target=emu, windows_gaming=None,
            memory_diag=None, bg_analysis=None, gpu_data=gpu,
            thermal_diag=None, power_result=None, emu_proc=emu,
        )
        cpu_evidence = [e for e in evidence if e.bottleneck_type == BottleneckType.CPU]
        assert len(cpu_evidence) > 0

    def test_collect_with_thermal_throttling(self):
        optimizer = self._make_optimizer()

        thermal = MagicMock()
        thermal.thermal_state = MagicMock()
        thermal.thermal_state.value = "THROTTLING RISK"
        thermal.thermal_state.upper.return_value = "THROTTLING RISK"

        evidence = optimizer._collect_evidence(
            hw_spec=None, emulator_target=None, windows_gaming=None,
            memory_diag=None, bg_analysis=None, gpu_data=None,
            thermal_diag=thermal, power_result=None, emu_proc=None,
        )
        thermal_ev = [e for e in evidence if e.bottleneck_type == BottleneckType.THERMAL]
        assert len(thermal_ev) > 0

    def test_collect_with_memory_pressure(self):
        optimizer = self._make_optimizer()

        mem = MagicMock()
        mem.pressure_level = "CRITICAL"
        mem.percent_used = 95.0

        evidence = optimizer._collect_evidence(
            hw_spec=None, emulator_target=None, windows_gaming=None,
            memory_diag=mem, bg_analysis=None, gpu_data=None,
            thermal_diag=None, power_result=None, emu_proc=None,
        )
        mem_ev = [e for e in evidence if e.bottleneck_type == BottleneckType.MEMORY]
        assert len(mem_ev) > 0

    def test_collect_with_battery(self):
        optimizer = self._make_optimizer()

        power = MagicMock()
        power.classification = MagicMock()
        power.classification.value = "BATTERY LIMITED"

        evidence = optimizer._collect_evidence(
            hw_spec=None, emulator_target=None, windows_gaming=None,
            memory_diag=None, bg_analysis=None, gpu_data=None,
            thermal_diag=None, power_result=power, emu_proc=None,
        )
        power_ev = [e for e in evidence if e.bottleneck_type == BottleneckType.POWER]
        assert len(power_ev) > 0

    def test_collect_with_gpu_bound(self):
        optimizer = self._make_optimizer()

        emu = MagicMock()
        emu.cpu_percent = 40.0

        gpu = MagicMock()
        gpu.utilization_percent = 95.0
        gpu.temperature_celsius = None

        evidence = optimizer._collect_evidence(
            hw_spec=None, emulator_target=emu, windows_gaming=None,
            memory_diag=None, bg_analysis=None, gpu_data=gpu,
            thermal_diag=None, power_result=None, emu_proc=emu,
        )
        gpu_ev = [e for e in evidence if e.bottleneck_type == BottleneckType.GPU]
        assert len(gpu_ev) > 0

    def test_collect_with_background_load(self):
        optimizer = self._make_optimizer()

        bg = MagicMock()
        bg.cpu_competition = MagicMock()
        bg.cpu_competition.value = "SEVERE"
        bg.significant_count = 15

        evidence = optimizer._collect_evidence(
            hw_spec=None, emulator_target=None, windows_gaming=None,
            memory_diag=None, bg_analysis=bg, gpu_data=None,
            thermal_diag=None, power_result=None, emu_proc=None,
        )
        bg_ev = [e for e in evidence if e.bottleneck_type == BottleneckType.BACKGROUND_LOAD]
        assert len(bg_ev) > 0

    def test_collect_with_emulator_config(self):
        optimizer = self._make_optimizer()

        emu = MagicMock()
        emu.cpu_percent = 50.0
        emu.priority = 0
        emu.priority_name = "NORMAL"
        emu.is_high_priority = False
        emu.affinity_cpus = 4
        emu.total_cpus = 12
        emu.uses_all_cpus = False

        evidence = optimizer._collect_evidence(
            hw_spec=None, emulator_target=emu, windows_gaming=None,
            memory_diag=None, bg_analysis=None, gpu_data=None,
            thermal_diag=None, power_result=None, emu_proc=emu,
        )
        config_ev = [e for e in evidence if e.bottleneck_type == BottleneckType.EMULATOR_CONFIGURATION]
        assert len(config_ev) > 0


class TestRecommendationGeneration:
    """Test recommendation generation logic."""

    def _make_optimizer(self):
        return AdaptiveOptimizer()

    def test_priority_recommendation_when_not_high(self):
        optimizer = self._make_optimizer()

        emu = MagicMock()
        emu.is_high_priority = False
        emu.priority_name = "NORMAL"
        emu.uses_all_cpus = True
        emu.total_cpus = 8

        recs, skips = optimizer._generate_recommendations(
            bottleneck=BottleneckType.CPU,
            evidence=[],
            emulator_target=emu,
            windows_gaming=None,
            power_result=None,
            bg_analysis=None,
            thermal_diag=None,
            memory_diag=None,
            hw_spec=None,
        )
        priority_recs = [r for r in recs if r.id == "emulator_priority"]
        assert len(priority_recs) == 1
        assert priority_recs[0].status in ("APPLICABLE", "RECOMMENDATION_ONLY")

    def test_priority_skipped_when_high(self):
        optimizer = self._make_optimizer()

        emu = MagicMock()
        emu.is_high_priority = True
        emu.uses_all_cpus = True
        emu.total_cpus = 8

        recs, skips = optimizer._generate_recommendations(
            bottleneck=BottleneckType.UNKNOWN,
            evidence=[],
            emulator_target=emu,
            windows_gaming=None,
            power_result=None,
            bg_analysis=None,
            thermal_diag=None,
            memory_diag=None,
            hw_spec=None,
        )
        priority_skips = [s for s in skips if s["id"] == "emulator_priority"]
        assert len(priority_skips) == 1

    def test_power_plan_recommendation(self):
        optimizer = self._make_optimizer()

        power = MagicMock()
        power.power_plan_is_performance = False
        power.power_plan_name = "Balanced"

        recs, skips = optimizer._generate_recommendations(
            bottleneck=BottleneckType.POWER,
            evidence=[],
            emulator_target=None,
            windows_gaming=None,
            power_result=power,
            bg_analysis=None,
            thermal_diag=None,
            memory_diag=None,
            hw_spec=None,
        )
        power_recs = [r for r in recs if r.id == "power_plan"]
        assert len(power_recs) == 1

    def test_power_plan_skipped_when_optimal(self):
        optimizer = self._make_optimizer()

        power = MagicMock()
        power.power_plan_is_performance = True
        power.power_plan_name = "High Performance"

        recs, skips = optimizer._generate_recommendations(
            bottleneck=BottleneckType.UNKNOWN,
            evidence=[],
            emulator_target=None,
            windows_gaming=None,
            power_result=power,
            bg_analysis=None,
            thermal_diag=None,
            memory_diag=None,
            hw_spec=None,
        )
        power_skips = [s for s in skips if s["id"] == "power_plan"]
        assert len(power_skips) == 1

    def test_game_mode_recommendation(self):
        optimizer = self._make_optimizer()

        gm_item = MagicMock()
        gm_item.name = "Game Mode"
        gm_item.status = "DISABLED"

        win_gaming = MagicMock()
        win_gaming.items = [gm_item]

        recs, skips = optimizer._generate_recommendations(
            bottleneck=BottleneckType.UNKNOWN,
            evidence=[],
            emulator_target=None,
            windows_gaming=win_gaming,
            power_result=None,
            bg_analysis=None,
            thermal_diag=None,
            memory_diag=None,
            hw_spec=None,
        )
        gm_recs = [r for r in recs if r.id == "game_mode"]
        assert len(gm_recs) == 1

    def test_no_emulator_skips_priority(self):
        optimizer = self._make_optimizer()

        recs, skips = optimizer._generate_recommendations(
            bottleneck=BottleneckType.UNKNOWN,
            evidence=[],
            emulator_target=None,
            windows_gaming=None,
            power_result=None,
            bg_analysis=None,
            thermal_diag=None,
            memory_diag=None,
            hw_spec=None,
        )
        # Should not have emulator_priority recommendation
        priority_recs = [r for r in recs if r.id == "emulator_priority"]
        assert len(priority_recs) == 0

    def test_recommendation_only_for_background(self):
        optimizer = self._make_optimizer()

        bg = MagicMock()
        candidate = MagicMock()
        candidate.name = "chrome.exe"
        candidate.recommendation = "SAFE_TO_RECOMMEND"
        bg.top_cpu_processes = [candidate]

        recs, skips = optimizer._generate_recommendations(
            bottleneck=BottleneckType.BACKGROUND_LOAD,
            evidence=[BottleneckEvidence(
                bottleneck_type=BottleneckType.BACKGROUND_LOAD,
                metric_name="CPU Competition",
                metric_value=10.0,
                threshold=5.0,
                description="High competition",
            )],
            emulator_target=None,
            windows_gaming=None,
            power_result=None,
            bg_analysis=bg,
            thermal_diag=None,
            memory_diag=None,
            hw_spec=None,
        )
        bg_recs = [r for r in recs if r.id == "background_load"]
        assert len(bg_recs) == 1
        assert bg_recs[0].status == "RECOMMENDATION_ONLY"

    def test_cpu_affinity_with_bottleneck(self):
        optimizer = self._make_optimizer()

        emu = MagicMock()
        emu.is_high_priority = True
        emu.uses_all_cpus = False
        emu.total_cpus = 12
        emu.affinity_cpus = 6

        recs, skips = optimizer._generate_recommendations(
            bottleneck=BottleneckType.CPU,
            evidence=[BottleneckEvidence(
                bottleneck_type=BottleneckType.CPU,
                metric_name="CPU",
                metric_value=90.0,
                threshold=85.0,
                description="CPU bound",
            )],
            emulator_target=emu,
            windows_gaming=None,
            power_result=None,
            bg_analysis=None,
            thermal_diag=None,
            memory_diag=None,
            hw_spec=None,
        )
        affinity_recs = [r for r in recs if r.id == "cpu_affinity"]
        assert len(affinity_recs) == 1


class TestImpactAssessment:
    """Test impact assessment logic."""

    def _make_optimizer(self):
        return AdaptiveOptimizer()

    def test_no_emulator_gives_unknown(self):
        optimizer = self._make_optimizer()
        impact, reason = optimizer._assess_impact(
            BottleneckType.CPU, [], None
        )
        assert impact == ExpectedImpact.UNKNOWN

    def test_unknown_bottleneck_gives_unknown(self):
        optimizer = self._make_optimizer()
        emu = MagicMock()
        impact, reason = optimizer._assess_impact(
            BottleneckType.UNKNOWN, [], emu
        )
        assert impact == ExpectedImpact.UNKNOWN

    def test_high_severity_gives_high_impact(self):
        optimizer = self._make_optimizer()
        emu = MagicMock()
        evidence = [
            BottleneckEvidence(
                bottleneck_type=BottleneckType.CPU,
                metric_name="CPU",
                metric_value=95.0,
                threshold=85.0,
                description="CPU at 95%",
            ),
            BottleneckEvidence(
                bottleneck_type=BottleneckType.CPU,
                metric_name="CPU/GPU",
                metric_value=3.0,
                threshold=2.0,
                description="CPU bound",
            ),
        ]
        impact, reason = optimizer._assess_impact(
            BottleneckType.CPU, evidence, emu
        )
        assert impact == ExpectedImpact.HIGH

    def test_single_moderate_evidence_gives_medium(self):
        optimizer = self._make_optimizer()
        emu = MagicMock()
        evidence = [
            BottleneckEvidence(
                bottleneck_type=BottleneckType.CPU,
                metric_name="CPU",
                metric_value=88.0,
                threshold=85.0,
                description="CPU moderate",
            ),
        ]
        impact, reason = optimizer._assess_impact(
            BottleneckType.CPU, evidence, emu
        )
        assert impact in (ExpectedImpact.MEDIUM, ExpectedImpact.HIGH)


class TestHardwareRisks:
    """Test hardware risk detection."""

    def _make_optimizer(self):
        return AdaptiveOptimizer()

    def test_low_ram_risk(self):
        optimizer = self._make_optimizer()
        hw = MagicMock()
        hw.ram_total_gb = 4.0
        hw.gpu_vram_mb = 8192.0
        hw.cpu_physical_cores = 8
        risks = optimizer._hardware_risks(hw)
        assert any("limited RAM" in r for r in risks)

    def test_low_vram_risk(self):
        optimizer = self._make_optimizer()
        hw = MagicMock()
        hw.ram_total_gb = 16.0
        hw.gpu_vram_mb = 1024.0
        hw.cpu_physical_cores = 8
        risks = optimizer._hardware_risks(hw)
        assert any("VRAM" in r for r in risks)

    def test_low_cores_risk(self):
        optimizer = self._make_optimizer()
        hw = MagicMock()
        hw.ram_total_gb = 16.0
        hw.gpu_vram_mb = 4096.0
        hw.cpu_physical_cores = 2
        risks = optimizer._hardware_risks(hw)
        assert any("few cores" in r for r in risks)

    def test_good_hardware_no_risks(self):
        optimizer = self._make_optimizer()
        hw = MagicMock()
        hw.ram_total_gb = 32.0
        hw.gpu_vram_mb = 8192.0
        hw.cpu_physical_cores = 8
        risks = optimizer._hardware_risks(hw)
        assert len(risks) == 0

    def test_none_hw_no_risks(self):
        optimizer = self._make_optimizer()
        risks = optimizer._hardware_risks(None)
        assert len(risks) == 0


class TestAssessmentGeneration:
    """Test assessment text generation."""

    def _make_optimizer(self):
        return AdaptiveOptimizer()

    def test_unknown_bottleneck_assessment(self):
        optimizer = self._make_optimizer()
        decision = OptimizationDecision(
            bottleneck=BottleneckType.UNKNOWN,
            has_emulator=False,
        )
        assessment = optimizer._generate_assessment(decision)
        assert "No clear" in assessment or "UNKNOWN" in assessment

    def test_with_emulator_assessment(self):
        optimizer = self._make_optimizer()
        decision = OptimizationDecision(
            bottleneck=BottleneckType.CPU,
            bottleneck_confidence=0.8,
            has_emulator=True,
            emulator_name="HD-Player.exe",
            emulator_pid=1234,
        )
        assessment = optimizer._generate_assessment(decision)
        assert "HD-Player.exe" in assessment

    def test_with_recommendations_assessment(self):
        optimizer = self._make_optimizer()
        decision = OptimizationDecision(
            bottleneck=BottleneckType.CPU,
            bottleneck_confidence=0.75,
            has_emulator=True,
            emulator_name="HD-Player.exe",
            emulator_pid=1234,
            recommended_optimizations=[
                OptimizationAction(status="APPLICABLE"),
                OptimizationAction(status="RECOMMENDATION_ONLY"),
            ],
        )
        assessment = optimizer._generate_assessment(decision)
        assert "1 optimization" in assessment
        assert "1 recommendation" in assessment


class TestEndToEnd:
    """Test complete analysis flow with mocked subsystems."""

    @patch("app.core.adaptive_optimizer.adaptive_optimizer._collect_evidence")
    @patch("app.core.adaptive_optimizer.adaptive_optimizer._classify_bottleneck")
    @patch("app.core.adaptive_optimizer.adaptive_optimizer._generate_recommendations")
    @patch("app.core.adaptive_optimizer.adaptive_optimizer._assess_impact")
    @patch("app.core.adaptive_optimizer.adaptive_optimizer._generate_assessment")
    @patch("app.core.adaptive_optimizer.adaptive_optimizer._hardware_risks")
    def test_full_analysis_with_emulator(
        self, mock_risks, mock_assess, mock_impact, mock_recs,
        mock_classify, mock_evidence
    ):
        # Setup mocks
        mock_risks.return_value = []
        mock_evidence.return_value = [
            BottleneckEvidence(
                bottleneck_type=BottleneckType.CPU,
                metric_name="CPU",
                metric_value=90.0,
                threshold=85.0,
                description="CPU high",
            ),
        ]
        mock_classify.return_value = (
            BottleneckType.CPU, 0.8, "CPU bottleneck detected"
        )
        mock_recs.return_value = (
            [OptimizationAction(id="power_plan", status="APPLICABLE")],
            [{"id": "game_mode", "reason": "Already enabled"}],
        )
        mock_impact.return_value = (ExpectedImpact.HIGH, "Strong CPU evidence")
        mock_assess.return_value = "CPU bottleneck with 1 optimization applicable"

        optimizer = AdaptiveOptimizer()

        # Mock all subsystems — using correct singleton names
        with patch("app.core.hardware_profile.analyze_hardware_profile") as mock_hw, \
             patch("app.core.emulator_controller.emulator_controller") as mock_emu, \
             patch("app.system.windows_gaming.windows_gaming_analyzer") as mock_win, \
             patch("app.system.memory_optimizer.memory_optimizer") as mock_mem, \
             patch("app.system.background_analyzer.background_analyzer") as mock_bg, \
             patch("app.system.gpu.gpu_monitor") as mock_gpu, \
             patch("app.system.thermal_monitor.thermal_diagnostics") as mock_therm, \
             patch("app.system.power_analyzer.power_analyzer") as mock_power, \
             patch("app.performance.presentmon_provider.find_presentmon") as mock_pm:

            # Hardware
            hw_result = MagicMock()
            hw_result.hardware = MagicMock()
            mock_hw.return_value = hw_result

            # Emulator
            emu_target = MagicMock()
            emu_target.name = "HD-Player.exe"
            emu_target.pid = 1234
            emu_target.is_high_priority = False
            emu_target.uses_all_cpus = False
            emu_target.total_cpus = 12
            emu_target.affinity_cpus = 6
            emu_target.priority = 0
            emu_target.priority_name = "NORMAL"
            mock_emu.detect_target.return_value = emu_target

            # Windows gaming
            mock_win.analyze.return_value = MagicMock()

            # Memory
            mock_mem.diagnose.return_value = MagicMock()

            # Background
            mock_bg.analyze.return_value = MagicMock()

            # GPU
            mock_gpu.detect.return_value = [MagicMock()]
            mock_gpu.update.return_value = MagicMock()

            # Thermal
            mock_therm.diagnose.return_value = MagicMock()

            # Power
            mock_power.analyze.return_value = MagicMock()

            # PresentMon
            mock_pm.return_value = "/path/to/presentmon.exe"

            result = optimizer.analyze(force=True)

            assert isinstance(result, OptimizationDecision)
            assert result.has_emulator is True
            assert result.emulator_name == "HD-Player.exe"
            assert result.emulator_pid == 1234
            assert result.has_fps_data is True
            assert result.fps_provider == "PresentMon 2.5.1"

    def test_analysis_without_emulator(self):
        optimizer = AdaptiveOptimizer()

        with patch("app.core.hardware_profile.analyze_hardware_profile") as mock_hw, \
             patch("app.core.emulator_controller.emulator_controller") as mock_emu, \
             patch("app.system.windows_gaming.windows_gaming_analyzer") as mock_win, \
             patch("app.system.memory_optimizer.memory_optimizer") as mock_mem, \
             patch("app.system.background_analyzer.background_analyzer") as mock_bg, \
             patch("app.system.gpu.gpu_monitor") as mock_gpu, \
             patch("app.system.thermal_monitor.thermal_diagnostics") as mock_therm, \
             patch("app.system.power_analyzer.power_analyzer") as mock_power, \
             patch("app.performance.presentmon_provider.find_presentmon") as mock_pm:

            hw_result = MagicMock()
            hw_result.hardware = MagicMock()
            mock_hw.return_value = hw_result
            mock_emu.detect_target.return_value = None
            mock_win.analyze.return_value = MagicMock()
            mock_mem.diagnose.return_value = MagicMock()
            mock_bg.analyze.return_value = MagicMock()
            mock_gpu.detect.return_value = []
            mock_therm.diagnose.return_value = MagicMock()
            mock_power.analyze.return_value = MagicMock()
            mock_pm.return_value = None

            result = optimizer.analyze(force=True)

            assert result.has_emulator is False
            assert result.emulator_name == ""
            assert result.has_fps_data is False

    def test_cache_behavior(self):
        optimizer = AdaptiveOptimizer()

        with patch("app.core.hardware_profile.analyze_hardware_profile") as mock_hw, \
             patch("app.core.emulator_controller.emulator_controller") as mock_emu, \
             patch("app.system.windows_gaming.windows_gaming_analyzer"), \
             patch("app.system.memory_optimizer.memory_optimizer"), \
             patch("app.system.background_analyzer.background_analyzer"), \
             patch("app.system.gpu.gpu_monitor") as mock_gpu, \
             patch("app.system.thermal_monitor.thermal_diagnostics"), \
             patch("app.system.power_analyzer.power_analyzer"), \
             patch("app.performance.presentmon_provider.find_presentmon"):

            hw_result = MagicMock()
            hw_result.hardware = MagicMock()
            mock_hw.return_value = hw_result
            mock_emu.detect_target.return_value = None
            mock_gpu.detect.return_value = []

            # First call
            result1 = optimizer.analyze(force=True)
            # Second call (cached)
            result2 = optimizer.analyze()
            # Same object
            assert result1 is result2

            # Force refresh
            result3 = optimizer.analyze(force=True)
            assert result3 is not result1


class TestSingleton:
    """Test the singleton instance."""

    def test_singleton_exists(self):
        assert adaptive_optimizer is not None
        assert isinstance(adaptive_optimizer, AdaptiveOptimizer)
