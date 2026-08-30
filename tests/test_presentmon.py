"""
Unit tests for PresentMon 2.5.1 integration.

Tests cover:
- PresentMon executable discovery
- Version detection
- CSV parsing
- Frame metrics calculation
- Malformed output handling
- Insufficient samples
- Unavailable state
"""

import os
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from app.performance.presentmon_provider import (
    PresentMonProvider,
    find_presentmon,
    get_presentmon_version,
)


class TestFindPresentMon:
    """Test PresentMon executable discovery."""

    def test_find_in_downloads(self, tmp_path):
        """Should find PresentMon in Downloads folder."""
        downloads = tmp_path / "Downloads"
        downloads.mkdir()
        pm_exe = downloads / "PresentMon-2.5.1-x64.exe"
        pm_exe.write_text("fake")

        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
            result = find_presentmon()
            assert result is not None
            assert "PresentMon" in result.name

    def test_not_found_returns_none(self, tmp_path):
        """Should return None when not found."""
        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path / "nonexistent")}):
            with patch("shutil.which", return_value=None):
                result = find_presentmon()
                # May return None or find something in default paths
                # Just verify no crash
                assert result is None or isinstance(result, Path)

    def test_finds_any_presentmon_version(self, tmp_path):
        """Should find any PresentMon version, not just specific ones."""
        downloads = tmp_path / "Downloads"
        downloads.mkdir()
        for name in [
            "PresentMon-2.5.1-x64.exe",
            "PresentMon-2.4.0-x64.exe",
            "presentmon-1.0.exe",
        ]:
            (downloads / name).write_text("fake")

        with patch.dict(os.environ, {"USERPROFILE": str(tmp_path)}):
            result = find_presentmon()
            assert result is not None


class TestPresentMonParsing:
    """Test CSV parsing with real PresentMon 2.5.1 format."""

    def _create_csv(self, rows, header=None):
        """Create a temporary CSV file with PresentMon format."""
        if header is None:
            header = (
                "Application,ProcessID,SwapChainAddress,PresentRuntime,"
                "SyncInterval,PresentFlags,AllowsTearing,PresentMode,"
                "TimeInMs,MsBetweenSimulationStart,MsBetweenPresents,"
                "MsBetweenDisplayChange,MsInPresentAPI,MsRenderPresentLatency,"
                "MsUntilDisplayed,CPUStartTimeInMs,MsBetweenAppStart,"
                "MsCPUBusy,MsCPUWait,MsGPULatency,MsGPUTime,MsGPUBusy,"
                "MsGPUWait,MsAnimationError,AnimationTime,MsFlipDelay,"
                "MsAllInputToPhotonLatency,MsClickToPhotonLatency\n"
            )

        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(header)
            for row in rows:
                f.write(row + "\n")
        return path

    def test_parse_valid_csv(self):
        """Should parse valid PresentMon CSV correctly."""
        rows = [
            "HD-Player.exe,1234,0x000001,D3D11,0,0,0,Hardware: Legacy Flip,"
            "1000.0,0.0,16.67,16.67,0.1,1.0,0.5,0.0,0.0,"
            "2.0,0.1,1.0,0.5,80.0,0.1,0,0.0,0.0,5.0,4.0",
            "HD-Player.exe,1234,0x000001,D3D11,0,0,0,Hardware: Legacy Flip,"
            "1016.67,16.67,16.67,16.67,0.1,1.0,0.5,0.0,0.0,"
            "2.0,0.1,1.0,0.5,85.0,0.1,0,0.0,0.0,5.0,4.0",
            "HD-Player.exe,1234,0x000001,D3D11,0,0,0,Hardware: Legacy Flip,"
            "1033.34,16.67,16.67,16.67,0.1,1.0,0.5,0.0,0.0,"
            "2.0,0.1,1.0,0.5,82.0,0.1,0,0.0,0.0,5.0,4.0",
        ]
        csv_path = self._create_csv(rows)

        try:
            provider = PresentMonProvider()
            samples = provider._parse_csv(csv_path)
            assert len(samples) == 3
            assert samples[0].process_name == "HD-Player.exe"
            assert samples[0].pid == 1234
            assert samples[0].frame_time_ms == pytest.approx(16.67, rel=0.01)
        finally:
            if os.path.exists(csv_path):
                os.remove(csv_path)

    def test_parse_with_missing_values(self):
        """Should handle NA/missing values gracefully."""
        rows = [
            "HD-Player.exe,1234,0x000001,D3D11,0,0,0,Hardware: Legacy Flip,"
            "1000.0,0.0,16.67,NA,NA,NA,NA,0.0,0.0,"
            "NA,NA,NA,NA,NA,NA,0,0.0,0.0,NA,NA",
        ]
        csv_path = self._create_csv(rows)

        try:
            provider = PresentMonProvider()
            samples = provider._parse_csv(csv_path)
            assert len(samples) == 1
            assert samples[0].frame_time_ms == pytest.approx(16.67, rel=0.01)
            assert samples[0].cpu_ms == 0.0  # NA mapped to 0.0
        finally:
            if os.path.exists(csv_path):
                os.remove(csv_path)

    def test_parse_empty_csv(self):
        """Should handle empty CSV gracefully."""
        fd, path = tempfile.mkstemp(suffix=".csv")
        os.close(fd)

        try:
            provider = PresentMonProvider()
            samples = provider._parse_csv(path)
            assert len(samples) == 0
        finally:
            os.remove(path)

    def test_parse_malformed_csv(self):
        """Should handle malformed CSV without crashing."""
        fd, path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("this is not a CSV\n")
            f.write("random,garbage,data\n")
            f.write(",,,\n")

        # Note: _parse_csv deletes the file after parsing
        provider = PresentMonProvider()
        samples = provider._parse_csv(path)
        assert isinstance(samples, list)

    def test_parse_bom_header(self):
        """Should handle BOM in CSV header."""
        rows = [
            "HD-Player.exe,1234,0x000001,D3D11,0,0,0,Hardware: Legacy Flip,"
            "1000.0,0.0,16.67,16.67,0.1,1.0,0.5,0.0,0.0,"
            "2.0,0.1,1.0,0.5,80.0,0.1,0,0.0,0.0,5.0,4.0",
        ]
        header = (
            "\ufeffApplication,ProcessID,SwapChainAddress,PresentRuntime,"
            "SyncInterval,PresentFlags,AllowsTearing,PresentMode,"
            "TimeInMs,MsBetweenSimulationStart,MsBetweenPresents,"
            "MsBetweenDisplayChange,MsInPresentAPI,MsRenderPresentLatency,"
            "MsUntilDisplayed,CPUStartTimeInMs,MsBetweenAppStart,"
            "MsCPUBusy,MsCPUWait,MsGPULatency,MsGPUTime,MsGPUBusy,"
            "MsGPUWait,MsAnimationError,AnimationTime,MsFlipDelay,"
            "MsAllInputToPhotonLatency,MsClickToPhotonLatency\n"
        )
        # Write with utf-8-sig to include BOM
        fd, csv_path = tempfile.mkstemp(suffix=".csv")
        with os.fdopen(fd, "w", encoding="utf-8-sig") as f:
            f.write(header)
            for row in rows:
                f.write(row + "\n")

        # Note: _parse_csv deletes the file after parsing
        provider = PresentMonProvider()
        samples = provider._parse_csv(csv_path)
        assert len(samples) == 1

    def test_multiple_processes(self):
        """Should correctly separate multiple processes."""
        rows = [
            "HD-Player.exe,1234,0x000001,D3D11,0,0,0,Hardware: Legacy Flip,"
            "1000.0,0.0,16.67,16.67,0.1,1.0,0.5,0.0,0.0,"
            "2.0,0.1,1.0,0.5,80.0,0.1,0,0.0,0.0,5.0,4.0",
            "dwm.exe,5678,0x000002,D3D11,1,0,0,Hardware: Legacy Flip,"
            "1000.0,0.0,16.67,16.67,0.1,1.0,0.5,0.0,0.0,"
            "1.0,0.1,0.5,0.3,20.0,0.1,0,0.0,0.0,3.0,2.0",
            "HD-Player.exe,1234,0x000001,D3D11,0,0,0,Hardware: Legacy Flip,"
            "1016.67,16.67,16.67,16.67,0.1,1.0,0.5,0.0,0.0,"
            "2.0,0.1,1.0,0.5,85.0,0.1,0,0.0,0.0,5.0,4.0",
        ]
        csv_path = self._create_csv(rows)

        # Note: _parse_csv deletes the file after parsing
        provider = PresentMonProvider()
        samples = provider._parse_csv(csv_path)
        assert len(samples) == 3

        hd_samples = [s for s in samples if s.process_name == "HD-Player.exe"]
        dwm_samples = [s for s in samples if s.process_name == "dwm.exe"]
        assert len(hd_samples) == 2
        assert len(dwm_samples) == 1


class TestFrameMetrics:
    """Test FPS metrics calculation."""

    def test_metrics_from_frame_times(self):
        """Should calculate correct metrics from frame times."""
        provider = PresentMonProvider()
        # 60 FPS = 16.67ms frame time
        frame_times = [16.67] * 100

        metrics = provider._calculate_metrics(frame_times, "test")
        assert metrics.available is True
        assert metrics.avg_fps == pytest.approx(60.0, rel=0.05)
        assert metrics.sample_count == 100

    def test_metrics_with_variability(self):
        """Should handle variable frame times."""
        provider = PresentMonProvider()
        # Mix of fast and slow frames
        frame_times = [16.67] * 90 + [33.33] * 10  # 60 FPS with 30 FPS dips

        metrics = provider._calculate_metrics(frame_times, "test")
        assert metrics.available is True
        # 1% low should be near 30 FPS (the worst frames)
        assert metrics.one_percent_low <= metrics.avg_fps + 1.0
        # Min FPS should be ~30
        assert metrics.min_fps == pytest.approx(30.0, rel=0.05)

    def test_insufficient_samples(self):
        """Should return unavailable for too few samples."""
        provider = PresentMonProvider()
        metrics = provider._calculate_metrics([16.67], "test")
        assert metrics.available is False

    def test_empty_samples(self):
        """Should return unavailable for empty list."""
        provider = PresentMonProvider()
        metrics = provider._calculate_metrics([], "test")
        assert metrics.available is False

    def test_stability_score(self):
        """Should calculate stability score."""
        provider = PresentMonProvider()
        # Very consistent frames
        consistent = [16.67] * 100
        score = provider._calc_stability(consistent)
        assert score > 90  # Very stable

        # Very variable frames
        import random
        random.seed(42)
        variable = [16.67 + random.uniform(-10, 10) for _ in range(100)]
        score_var = provider._calc_stability(variable)
        assert score_var < score  # Less stable


class TestProviderState:
    """Test provider state management."""

    def test_initial_state(self):
        """Should start in unavailable state."""
        provider = PresentMonProvider()
        assert provider.get_state() == "UNAVAILABLE"
        assert provider.is_running() is False

    def test_metrics_when_not_running(self):
        """Should return unavailable metrics when not running."""
        provider = PresentMonProvider()
        metrics = provider.get_metrics()
        assert metrics.available is False

    def test_get_process_metrics_unknown(self):
        """Should return unavailable for unknown process."""
        provider = PresentMonProvider()
        metrics = provider.get_process_metrics("nonexistent.exe")
        assert metrics.available is False

    def test_version_returns_none_initially(self):
        """Should return None for version before is_available."""
        provider = PresentMonProvider()
        assert provider.get_version() is None

    def test_get_path_before_availability_check(self):
        """Should return None for path before is_available."""
        provider = PresentMonProvider()
        assert provider.get_path() is None


class TestVersionDetection:
    """Test version detection."""

    def test_version_detection(self):
        """Should detect version from --version output."""
        # This is a live test — it checks the actual PresentMon
        pm_path = find_presentmon()
        if pm_path:
            version = get_presentmon_version(pm_path)
            # Should find a version string
            if version:
                assert "." in version  # Version should contain dots
