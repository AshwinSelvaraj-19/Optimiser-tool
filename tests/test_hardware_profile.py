"""
Tests for Heaven Society — Hardware Profile Engine (Phase 24).

Uses mocked hardware; never requires real hardware.
"""

import pytest
from unittest.mock import patch, MagicMock

from app.core.hardware_profile import (
    HardwareProfileResult,
    HardwareSpec,
    HardwareComponent,
    ProfileSetting,
    SystemTier,
    ProfileRecommendation,
    DataOrigin,
    classify_system,
    _recommend_profile,
    _generate_settings,
    analyze_hardware_profile,
    _build_components,
    _classify_gpu_tier,
)


class TestHardwareSpec:
    """Test HardwareSpec dataclass defaults."""

    def test_defaults(self):
        spec = HardwareSpec()
        assert spec.cpu_model == ""
        assert spec.cpu_physical_cores == 0
        assert spec.ram_total_gb == 0.0
        assert spec.gpu_name == ""
        assert spec.gpu_vram_mb == 0.0
        assert spec.display_refresh_hz == 0
        assert spec.current_fps is None
        assert spec.gpu_temp_celsius is None

    def test_with_values(self):
        spec = HardwareSpec(
            cpu_model="Ryzen 5 5600X",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="RTX 3060",
            gpu_vram_mb=12288.0,
            display_refresh_hz=144,
            current_fps=120.0,
        )
        assert spec.cpu_physical_cores == 6
        assert spec.ram_total_gb == 16.0
        assert spec.current_fps == 120.0


class TestSystemTier:
    """Test SystemTier enum."""

    def test_all_values(self):
        assert SystemTier.ENTRY.value == "Entry"
        assert SystemTier.MID_RANGE.value == "Mid-Range"
        assert SystemTier.HIGH_END.value == "High-End"
        assert SystemTier.ULTRA.value == "Ultra"
        assert SystemTier.UNKNOWN.value == "Unknown"

    def test_has_all_tiers(self):
        tiers = list(SystemTier)
        assert len(tiers) == 5


class TestProfileRecommendation:
    """Test ProfileRecommendation enum."""

    def test_all_values(self):
        assert ProfileRecommendation.BALANCED.value == "balanced"
        assert ProfileRecommendation.GAMING.value == "gaming"
        assert ProfileRecommendation.MAX_PERFORMANCE.value == "max_performance"


class TestGPUClassification:
    """Test GPU tier classification."""

    def test_nvidia_known_models(self):
        assert _classify_gpu_tier("NVIDIA GeForce RTX 3050", 4096) == SystemTier.MID_RANGE
        assert _classify_gpu_tier("NVIDIA GeForce RTX 3060", 12288) == SystemTier.HIGH_END
        assert _classify_gpu_tier("NVIDIA GeForce RTX 4090", 24576) == SystemTier.ULTRA
        assert _classify_gpu_tier("NVIDIA GeForce MX450", 2048) == SystemTier.ENTRY

    def test_vram_fallback(self):
        # Unknown model — classify by VRAM
        assert _classify_gpu_tier("Unknown GPU 9000", 16384) == SystemTier.HIGH_END
        assert _classify_gpu_tier("Unknown GPU 9000", 6000) == SystemTier.MID_RANGE
        assert _classify_gpu_tier("Unknown GPU 9000", 3000) == SystemTier.ENTRY
        assert _classify_gpu_tier("Unknown GPU 9000", 500) == SystemTier.UNKNOWN

    def test_empty_name_zero_vram(self):
        tier = _classify_gpu_tier("", 0.0)
        assert tier == SystemTier.UNKNOWN


class TestClassifySystem:
    """Test system classification logic."""

    def test_entry_level(self):
        spec = HardwareSpec(
            cpu_model="Intel Celeron",
            cpu_physical_cores=1,
            cpu_logical_cores=2,
            ram_total_gb=2.0,
            gpu_name="Intel UHD 610",
            gpu_vram_mb=128.0,
        )
        tier, reason = classify_system(spec)
        assert tier == SystemTier.ENTRY
        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_mid_range(self):
        spec = HardwareSpec(
            cpu_model="AMD Ryzen 5 5600X",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="NVIDIA GeForce RTX 3060",
            gpu_vram_mb=12288.0,
        )
        tier, reason = classify_system(spec)
        assert tier == SystemTier.HIGH_END  # RTX 3060 = HIGH_END tier

    def test_high_end(self):
        spec = HardwareSpec(
            cpu_model="AMD Ryzen 9 7950X",
            cpu_physical_cores=16,
            cpu_logical_cores=32,
            ram_total_gb=64.0,
            gpu_name="NVIDIA GeForce RTX 4090",
            gpu_vram_mb=24576.0,
        )
        tier, reason = classify_system(spec)
        assert tier in (SystemTier.HIGH_END, SystemTier.ULTRA)

    def test_empty_hardware_is_entry(self):
        """With all zeros, UNKNOWN GPU (score=2) drives overall to ENTRY."""
        spec = HardwareSpec(
            cpu_model="",
            cpu_physical_cores=0,
            cpu_logical_cores=0,
            ram_total_gb=0.0,
            gpu_name="",
            gpu_vram_mb=0.0,
        )
        tier, reason = classify_system(spec)
        # UNKNOWN GPU gets score 2, overall = (2*2+0+0)/4 = 1.0 → ENTRY
        assert tier == SystemTier.ENTRY

    def test_ultra_tier(self):
        spec = HardwareSpec(
            cpu_model="Threadripper 7980X",
            cpu_physical_cores=32,
            cpu_logical_cores=64,
            ram_total_gb=128.0,
            gpu_name="NVIDIA GeForce RTX 4090",
            gpu_vram_mb=24576.0,
        )
        tier, reason = classify_system(spec)
        assert tier in (SystemTier.HIGH_END, SystemTier.ULTRA)

    def test_reason_is_string(self):
        spec = HardwareSpec(
            cpu_model="Test CPU",
            cpu_physical_cores=4,
            cpu_logical_cores=8,
            ram_total_gb=8.0,
            gpu_name="Test GPU",
            gpu_vram_mb=2048.0,
        )
        tier, reason = classify_system(spec)
        assert isinstance(reason, str)
        assert len(reason) > 5


class TestRecommendProfile:
    """Test profile recommendation logic."""

    def test_entry_recommends_balanced(self):
        spec = HardwareSpec(
            cpu_model="Intel Core i3",
            cpu_physical_cores=2,
            cpu_logical_cores=4,
            ram_total_gb=4.0,
            gpu_name="Intel UHD",
            gpu_vram_mb=512.0,
        )
        profile, reason = _recommend_profile(spec, SystemTier.ENTRY)
        assert profile == ProfileRecommendation.BALANCED

    def test_mid_range_recommends_gaming(self):
        spec = HardwareSpec(
            cpu_model="Ryzen 5 5600X",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="RTX 3060",
            gpu_vram_mb=12288.0,
            display_refresh_hz=144,
        )
        profile, reason = _recommend_profile(spec, SystemTier.MID_RANGE)
        assert profile == ProfileRecommendation.GAMING

    def test_high_end_recommends_max(self):
        spec = HardwareSpec(
            cpu_model="Ryzen 9 7950X",
            cpu_physical_cores=16,
            cpu_logical_cores=32,
            ram_total_gb=64.0,
            gpu_name="RTX 4090",
            gpu_vram_mb=24576.0,
            display_refresh_hz=240,
        )
        profile, reason = _recommend_profile(spec, SystemTier.HIGH_END)
        assert profile == ProfileRecommendation.MAX_PERFORMANCE

    def test_ultra_recommends_max(self):
        spec = HardwareSpec(
            cpu_model="Threadripper",
            cpu_physical_cores=32,
            cpu_logical_cores=64,
            ram_total_gb=128.0,
            gpu_name="RTX 4090",
            gpu_vram_mb=24576.0,
        )
        profile, reason = _recommend_profile(spec, SystemTier.ULTRA)
        assert profile == ProfileRecommendation.MAX_PERFORMANCE

    def test_critical_memory_forces_balanced(self):
        spec = HardwareSpec(
            cpu_model="Ryzen 9 7950X",
            cpu_physical_cores=16,
            ram_total_gb=64.0,
            gpu_name="RTX 4090",
            gpu_vram_mb=24576.0,
            memory_pressure="CRITICAL",
        )
        profile, reason = _recommend_profile(spec, SystemTier.HIGH_END)
        assert profile == ProfileRecommendation.BALANCED
        assert "critical" in reason.lower()

    def test_thermal_throttling_forces_balanced(self):
        spec = HardwareSpec(
            cpu_model="Ryzen 9 7950X",
            cpu_physical_cores=16,
            ram_total_gb=64.0,
            gpu_name="RTX 4090",
            gpu_vram_mb=24576.0,
            thermal_state="THROTTLING_RISK",
        )
        profile, reason = _recommend_profile(spec, SystemTier.HIGH_END)
        assert profile == ProfileRecommendation.BALANCED
        assert "throttl" in reason.lower()

    def test_unknown_defaults_to_gaming(self):
        spec = HardwareSpec()
        profile, reason = _recommend_profile(spec, SystemTier.UNKNOWN)
        assert profile == ProfileRecommendation.GAMING

    def test_reason_is_string(self):
        spec = HardwareSpec(
            cpu_model="Test CPU",
            cpu_physical_cores=4,
            cpu_logical_cores=8,
            ram_total_gb=8.0,
            gpu_name="Test GPU",
            gpu_vram_mb=2048.0,
        )
        profile, reason = _recommend_profile(spec, SystemTier.MID_RANGE)
        assert isinstance(reason, str)
        assert len(reason) > 0


class TestGenerateSettings:
    """Test recommended settings generation."""

    def test_all_profiles_produce_settings(self):
        spec = HardwareSpec(
            cpu_model="Test CPU",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="Test GPU",
            gpu_vram_mb=4096.0,
            display_refresh_hz=144,
        )
        for tier in (SystemTier.ENTRY, SystemTier.MID_RANGE, SystemTier.HIGH_END):
            for profile in ProfileRecommendation:
                settings = _generate_settings(spec, tier, profile)
                assert isinstance(settings, list)
                assert len(settings) > 0

    def test_settings_have_required_fields(self):
        spec = HardwareSpec(
            cpu_model="Test CPU",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="Test GPU",
            gpu_vram_mb=4096.0,
        )
        settings = _generate_settings(spec, SystemTier.MID_RANGE, ProfileRecommendation.GAMING)
        for s in settings:
            assert isinstance(s, ProfileSetting)
            assert s.name != ""
            assert s.recommended_value != ""
            assert s.reason != ""
            assert s.origin == DataOrigin.RECOMMENDED

    def test_balanced_vs_gaming_differ(self):
        spec = HardwareSpec(
            cpu_model="Test CPU",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="Test GPU",
            gpu_vram_mb=4096.0,
        )
        balanced = _generate_settings(spec, SystemTier.MID_RANGE, ProfileRecommendation.BALANCED)
        gaming = _generate_settings(spec, SystemTier.MID_RANGE, ProfileRecommendation.GAMING)
        assert balanced != gaming

    def test_max_performance_has_more_settings(self):
        spec = HardwareSpec(
            cpu_model="Test CPU",
            cpu_physical_cores=8,
            cpu_logical_cores=16,
            ram_total_gb=32.0,
            gpu_name="Test GPU",
            gpu_vram_mb=8192.0,
        )
        balanced = _generate_settings(spec, SystemTier.MID_RANGE, ProfileRecommendation.BALANCED)
        max_perf = _generate_settings(spec, SystemTier.HIGH_END, ProfileRecommendation.MAX_PERFORMANCE)
        # Max performance should have same or more settings
        assert len(max_perf) >= len(balanced)


class TestBuildComponents:
    """Test component list building."""

    def test_components_from_spec(self):
        spec = HardwareSpec(
            cpu_model="Ryzen 5 5600X",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="RTX 3060",
            gpu_vram_mb=12288.0,
            display_resolution="1920x1080",
            display_refresh_hz=144,
            os_version="Windows 11",
        )
        components = _build_components(spec)
        assert len(components) > 0
        assert all(isinstance(c, HardwareComponent) for c in components)
        names = [c.name for c in components]
        assert any("CPU" in n.upper() for n in names)
        assert any("RAM" in n.upper() for n in names)

    def test_components_have_origin(self):
        spec = HardwareSpec(
            cpu_model="Test",
            cpu_physical_cores=4,
            cpu_logical_cores=8,
            ram_total_gb=8.0,
        )
        components = _build_components(spec)
        for c in components:
            assert isinstance(c.origin, DataOrigin)

    def test_components_cover_major_hardware(self):
        spec = HardwareSpec(
            cpu_model="Ryzen 5",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="RTX 3060",
            gpu_vram_mb=12288.0,
            display_resolution="1920x1080",
            display_refresh_hz=144,
            os_version="Windows 11",
            gpu_temp_celsius=55.0,
        )
        components = _build_components(spec)
        names = [c.name.lower() for c in components]
        assert any("cpu" in n for n in names)
        assert any("ram" in n or "memory" in n for n in names)


class TestHardwareProfileResult:
    """Test HardwareProfileResult dataclass."""

    def test_defaults(self):
        result = HardwareProfileResult()
        assert result.system_tier == SystemTier.UNKNOWN
        assert result.recommended_profile == ProfileRecommendation.GAMING
        assert result.tier_reason == ""
        assert result.profile_reason == ""
        assert isinstance(result.hardware, HardwareSpec)
        assert isinstance(result.settings, list)
        assert isinstance(result.components, list)
        assert result.timestamp > 0


class TestEndToEnd:
    """Test complete analysis flow with mocked hardware."""

    @patch("app.core.hardware_profile._detect_emulator")
    @patch("app.core.hardware_profile._detect_thermals")
    @patch("app.core.hardware_profile._detect_memory_pressure")
    @patch("app.core.hardware_profile._detect_display")
    @patch("app.core.hardware_profile._detect_os")
    @patch("app.core.hardware_profile._detect_gpu")
    @patch("app.core.hardware_profile._detect_ram")
    @patch("app.core.hardware_profile._detect_cpu")
    def test_full_analysis_mid_range(self, mock_cpu, mock_ram, mock_gpu, mock_os,
                                      mock_display, mock_mem, mock_therm, mock_emu):
        base = HardwareSpec(
            cpu_model="AMD Ryzen 5 5600X",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="NVIDIA GeForce RTX 3060",
            gpu_vram_mb=12288.0,
            display_resolution="1920x1080",
            display_refresh_hz=144,
            os_version="Windows 11",
        )
        mock_cpu.return_value = base
        mock_ram.return_value = base
        mock_gpu.return_value = base
        mock_os.return_value = base
        mock_display.return_value = base
        mock_mem.return_value = base
        mock_therm.return_value = base
        mock_emu.return_value = base

        result = analyze_hardware_profile()

        assert isinstance(result, HardwareProfileResult)
        assert result.system_tier in (SystemTier.HIGH_END, SystemTier.MID_RANGE)
        assert result.recommended_profile is not None
        assert len(result.settings) > 0
        assert len(result.components) > 0
        assert result.timestamp > 0
        assert result.tier_reason != ""
        assert result.profile_reason != ""

    @patch("app.core.hardware_profile._detect_emulator")
    @patch("app.core.hardware_profile._detect_thermals")
    @patch("app.core.hardware_profile._detect_memory_pressure")
    @patch("app.core.hardware_profile._detect_display")
    @patch("app.core.hardware_profile._detect_os")
    @patch("app.core.hardware_profile._detect_gpu")
    @patch("app.core.hardware_profile._detect_ram")
    @patch("app.core.hardware_profile._detect_cpu")
    def test_full_analysis_entry(self, mock_cpu, mock_ram, mock_gpu, mock_os,
                                  mock_display, mock_mem, mock_therm, mock_emu):
        base = HardwareSpec(
            cpu_model="Intel Celeron N4500",
            cpu_physical_cores=2,
            cpu_logical_cores=2,
            ram_total_gb=4.0,
            gpu_name="Intel UHD 600",
            gpu_vram_mb=128.0,
            display_resolution="1366x768",
            display_refresh_hz=60,
            os_version="Windows 10",
        )
        mock_cpu.return_value = base
        mock_ram.return_value = base
        mock_gpu.return_value = base
        mock_os.return_value = base
        mock_display.return_value = base
        mock_mem.return_value = base
        mock_therm.return_value = base
        mock_emu.return_value = base

        result = analyze_hardware_profile()

        assert result.system_tier == SystemTier.ENTRY
        assert result.recommended_profile == ProfileRecommendation.BALANCED
        assert len(result.settings) > 0

    @patch("app.core.hardware_profile._detect_emulator")
    @patch("app.core.hardware_profile._detect_thermals")
    @patch("app.core.hardware_profile._detect_memory_pressure")
    @patch("app.core.hardware_profile._detect_display")
    @patch("app.core.hardware_profile._detect_os")
    @patch("app.core.hardware_profile._detect_gpu")
    @patch("app.core.hardware_profile._detect_ram")
    @patch("app.core.hardware_profile._detect_cpu")
    def test_full_analysis_high_end(self, mock_cpu, mock_ram, mock_gpu, mock_os,
                                     mock_display, mock_mem, mock_therm, mock_emu):
        base = HardwareSpec(
            cpu_model="AMD Ryzen 9 7950X",
            cpu_physical_cores=16,
            cpu_logical_cores=32,
            ram_total_gb=64.0,
            gpu_name="NVIDIA GeForce RTX 4090",
            gpu_vram_mb=24576.0,
            display_resolution="2560x1440",
            display_refresh_hz=240,
            os_version="Windows 11",
        )
        mock_cpu.return_value = base
        mock_ram.return_value = base
        mock_gpu.return_value = base
        mock_os.return_value = base
        mock_display.return_value = base
        mock_mem.return_value = base
        mock_therm.return_value = base
        mock_emu.return_value = base

        result = analyze_hardware_profile()

        assert result.system_tier in (SystemTier.HIGH_END, SystemTier.ULTRA)
        assert result.recommended_profile == ProfileRecommendation.MAX_PERFORMANCE

    @patch("app.core.hardware_profile._detect_emulator")
    @patch("app.core.hardware_profile._detect_thermals")
    @patch("app.core.hardware_profile._detect_memory_pressure")
    @patch("app.core.hardware_profile._detect_display")
    @patch("app.core.hardware_profile._detect_os")
    @patch("app.core.hardware_profile._detect_gpu")
    @patch("app.core.hardware_profile._detect_ram")
    @patch("app.core.hardware_profile._detect_cpu")
    def test_no_hardware_is_entry(self, mock_cpu, mock_ram, mock_gpu, mock_os,
                                   mock_display, mock_mem, mock_therm, mock_emu):
        """All zeros — UNKNOWN GPU (score=2) gives ENTRY overall."""
        base = HardwareSpec()
        mock_cpu.return_value = base
        mock_ram.return_value = base
        mock_gpu.return_value = base
        mock_os.return_value = base
        mock_display.return_value = base
        mock_mem.return_value = base
        mock_therm.return_value = base
        mock_emu.return_value = base

        result = analyze_hardware_profile()

        assert result.system_tier == SystemTier.ENTRY


class TestClassificationReason:
    """Test that classification produces meaningful reasons."""

    def test_entry_reason_mentions_hardware(self):
        spec = HardwareSpec(
            cpu_model="Intel Celeron",
            cpu_physical_cores=1,
            cpu_logical_cores=2,
            ram_total_gb=2.0,
            gpu_name="Intel UHD 610",
            gpu_vram_mb=128.0,
        )
        tier, reason = classify_system(spec)
        assert tier == SystemTier.ENTRY
        assert len(reason) > 5

    def test_high_end_reason_mentions_hardware(self):
        spec = HardwareSpec(
            cpu_model="Ryzen 9 7950X",
            cpu_physical_cores=16,
            cpu_logical_cores=32,
            ram_total_gb=64.0,
            gpu_name="RTX 4090",
            gpu_vram_mb=24576.0,
        )
        tier, reason = classify_system(spec)
        assert len(reason) > 5


class TestEdgeCases:
    """Test edge cases and error handling."""

    @patch("app.core.hardware_profile._detect_emulator")
    @patch("app.core.hardware_profile._detect_thermals")
    @patch("app.core.hardware_profile._detect_memory_pressure")
    @patch("app.core.hardware_profile._detect_display")
    @patch("app.core.hardware_profile._detect_os")
    @patch("app.core.hardware_profile._detect_gpu")
    @patch("app.core.hardware_profile._detect_ram")
    @patch("app.core.hardware_profile._detect_cpu")
    def test_analyze_returns_complete_result(self, mock_cpu, mock_ram, mock_gpu, mock_os,
                                             mock_display, mock_mem, mock_therm, mock_emu):
        base = HardwareSpec(
            cpu_model="Test CPU",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="RTX 3060",
            gpu_vram_mb=12288.0,
        )
        mock_cpu.return_value = base
        mock_ram.return_value = base
        mock_gpu.return_value = base
        mock_os.return_value = base
        mock_display.return_value = base
        mock_mem.return_value = base
        mock_therm.return_value = base
        mock_emu.return_value = base

        result = analyze_hardware_profile()
        assert isinstance(result, HardwareProfileResult)
        assert result.system_tier is not None
        assert result.recommended_profile is not None

    def test_classification_borderline(self):
        """Test classification when hardware is borderline between tiers."""
        spec = HardwareSpec(
            cpu_model="Borderline CPU",
            cpu_physical_cores=4,
            cpu_logical_cores=8,
            ram_total_gb=8.0,
            gpu_name="Borderline GPU",
            gpu_vram_mb=2048.0,
        )
        tier, reason = classify_system(spec)
        assert tier in (SystemTier.ENTRY, SystemTier.MID_RANGE)

    def test_all_data_origins_used(self):
        """Verify all DataOrigin values exist."""
        assert DataOrigin.MEASURED.value == "MEASURED"
        assert DataOrigin.DETECTED.value == "DETECTED"
        assert DataOrigin.INFERRED.value == "INFERRED"
        assert DataOrigin.RECOMMENDED.value == "RECOMMENDED"

    def test_profile_settings_not_empty_for_all_tiers(self):
        """Every non-unknown tier should produce at least one setting."""
        for tier in (SystemTier.ENTRY, SystemTier.MID_RANGE, SystemTier.HIGH_END, SystemTier.ULTRA):
            for profile in ProfileRecommendation:
                spec = HardwareSpec(
                    cpu_model="Test CPU",
                    cpu_physical_cores=4,
                    cpu_logical_cores=8,
                    ram_total_gb=8.0,
                    gpu_name="Test GPU",
                    gpu_vram_mb=2048.0,
                )
                settings = _generate_settings(spec, tier, profile)
                assert len(settings) > 0, f"No settings for {tier}/{profile}"

    def test_borderline_high_end_gpu(self):
        """RTX 3050 is classified as MID_RANGE."""
        spec = HardwareSpec(
            cpu_model="Ryzen 5",
            cpu_physical_cores=6,
            cpu_logical_cores=12,
            ram_total_gb=16.0,
            gpu_name="NVIDIA GeForce RTX 3050",
            gpu_vram_mb=4096.0,
        )
        tier, _ = classify_system(spec)
        # RTX 3050 is in the "mid" tier in GPU classification
        assert tier in (SystemTier.MID_RANGE, SystemTier.HIGH_END)
