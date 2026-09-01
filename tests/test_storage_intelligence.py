"""
Phase 52 — Comprehensive tests for Advanced Storage Intelligence.

Tests:
- StorageOverview
- StorageAnalyzer: quick scan, deep scan, directory analysis
- StorageRecommendations
- DriveHealth classification
- Inaccessible directory handling
- Largest directory analysis
- Async deep scan
- CLI commands
- Edge cases
"""
import os
import sys
import time
import tempfile
import shutil

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import pytest
from unittest.mock import MagicMock, patch, PropertyMock
from app.storage.storage_intelligence import (
    ScanDepth,
    DriveHealth,
    StorageRecommendationSeverity,
    DirectoryAnalysis,
    StorageOverview,
    StorageScanResult,
    StorageRecommendation,
    StorageAnalyzer,
    storage_analyzer,
    _format_bytes,
)
from app.system.disk_analyzer import (
    DiskDiagnostics,
    DiskPartitionInfo,
    ReclaimableTarget,
    StoragePressure,
    DiskAnalyzer,
)


# ══════════════════════════════════════════════════════════════════
# 1. Helpers
# ══════════════════════════════════════════════════════════════════

class TestFormatBytes:
    def test_bytes(self):
        assert _format_bytes(0) == "0 B"
        assert _format_bytes(512) == "512 B"

    def test_kb(self):
        assert "KB" in _format_bytes(2048)

    def test_mb(self):
        assert "MB" in _format_bytes(5 * 1024 * 1024)

    def test_gb(self):
        assert "GB" in _format_bytes(3 * 1024 * 1024 * 1024)

    def test_negative(self):
        result = _format_bytes(-100)
        assert "B" in result


# ══════════════════════════════════════════════════════════════════
# 2. Data Models
# ══════════════════════════════════════════════════════════════════

class TestDirectoryAnalysis:
    def test_create(self):
        da = DirectoryAnalysis(path="C:\\test", name="test")
        assert da.accessible is True
        assert da.total_size_bytes == 0

    def test_size_display(self):
        da = DirectoryAnalysis(total_size_bytes=1024 * 1024 * 100)
        assert "MB" in da.size_display

    def test_inaccessible(self):
        da = DirectoryAnalysis(accessible=False, error="Permission denied")
        assert da.accessible is False
        assert "Permission" in da.error


class TestStorageOverview:
    def test_create(self):
        ov = StorageOverview()
        assert ov.drives == []
        assert ov.total_storage_bytes == 0

    def test_display(self):
        ov = StorageOverview(
            total_storage_bytes=500 * 1024**3,
            total_used_bytes=300 * 1024**3,
            total_free_bytes=200 * 1024**3,
        )
        assert "GB" in ov.total_display
        assert "GB" in ov.used_display
        assert "GB" in ov.free_display


class TestStorageScanResult:
    def test_create(self):
        result = StorageScanResult()
        assert result.scan_id.startswith("scan_")
        assert result.scan_depth == ScanDepth.QUICK

    def test_custom_scan_id(self):
        result = StorageScanResult(scan_id="custom_id")
        assert result.scan_id == "custom_id"


class TestStorageRecommendation:
    def test_create(self):
        rec = StorageRecommendation(
            title="Test",
            explanation="Explanation",
            severity=StorageRecommendationSeverity.HIGH,
        )
        assert rec.id.startswith("srec_")
        assert rec.risk == "NONE"

    def test_custom_id(self):
        rec = StorageRecommendation(id="custom_id")
        assert rec.id == "custom_id"


# ══════════════════════════════════════════════════════════════════
# 3. StorageAnalyzer — Unit Tests with Mocks
# ══════════════════════════════════════════════════════════════════

def _make_partition(
    device="C:\\", mountpoint="C:\\", filesystem="NTFS",
    total=500 * 1024**3, used=200 * 1024**3, free=300 * 1024**3,
    pct=40.0, disk_type="SSD"
):
    return DiskPartitionInfo(
        device=device, mountpoint=mountpoint, filesystem=filesystem,
        total_bytes=total, used_bytes=used, free_bytes=free,
        percent_used=pct, is_system_drive=True, disk_type=disk_type,
    )


def _make_diag(**kwargs):
    defaults = dict(
        system_drive=_make_partition(),
        all_partitions=[_make_partition()],
        pressure_level=StoragePressure.NORMAL,
        pressure_description="Healthy",
        reclaimable_targets=[
            ReclaimableTarget(
                name="User Temp", path="/tmp",
                estimated_bytes=100 * 1024 * 1024,
                status="SAFE", category="TEMP",
            ),
        ],
        total_reclaimable_bytes=100 * 1024 * 1024,
        total_reclaimable_safe=100 * 1024 * 1024,
    )
    defaults.update(kwargs)
    return DiskDiagnostics(**defaults)


class TestStorageAnalyzerQuickScan:
    def test_singleton_exists(self):
        assert isinstance(storage_analyzer, StorageAnalyzer)

    def test_quick_scan_returns_result(self):
        mock_diag = _make_diag()
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag):
            result = storage_analyzer.quick_scan()
        assert isinstance(result, StorageScanResult)
        assert result.scan_depth == ScanDepth.QUICK
        assert result.overview is not None

    def test_quick_scan_overview_values(self):
        mock_diag = _make_diag()
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag):
            result = storage_analyzer.quick_scan()
        ov = result.overview
        assert ov.total_storage_bytes == 500 * 1024**3
        assert ov.total_used_bytes == 200 * 1024**3
        assert ov.total_free_bytes == 300 * 1024**3
        assert ov.disk_type == "SSD"

    def test_quick_scan_pressure(self):
        mock_diag = _make_diag(pressure_level=StoragePressure.CRITICAL)
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag):
            result = storage_analyzer.quick_scan()
        assert result.overview.system_pressure == StoragePressure.CRITICAL

    def test_quick_scan_cleanup_candidates(self):
        mock_diag = _make_diag()
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag):
            result = storage_analyzer.quick_scan()
        assert len(result.cleanup_candidates) == 1
        assert result.cleanup_candidates[0].name == "User Temp"

    def test_quick_scan_recommendations(self):
        mock_diag = _make_diag()
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag):
            result = storage_analyzer.quick_scan()
        assert isinstance(result.recommendations, list)

    def test_quick_scan_critical_disk(self):
        mock_diag = _make_diag(
            system_drive=_make_partition(
                total=256 * 1024**3, used=254 * 1024**3,
                free=2 * 1024**3, pct=99.0
            ),
            pressure_level=StoragePressure.CRITICAL,
        )
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag):
            result = storage_analyzer.quick_scan()
        # Should have a critical recommendation
        crit_recs = [r for r in result.recommendations if r["severity"] == "CRITICAL"]
        assert len(crit_recs) > 0

    def test_quick_scan_error_handling(self):
        with patch.object(storage_analyzer._base, "diagnose", side_effect=Exception("test")):
            result = storage_analyzer.quick_scan()
        assert len(result.errors) > 0

    def test_quick_scan_stored(self):
        mock_diag = _make_diag()
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag):
            storage_analyzer.quick_scan()
        assert storage_analyzer.last_scan is not None


class TestStorageAnalyzerDeepScan:
    def test_deep_scan_returns_result(self):
        mock_diag = _make_diag()
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag), \
             patch.object(storage_analyzer, "_analyze_directories", return_value=[]):
            result = storage_analyzer.deep_scan()
        assert isinstance(result, StorageScanResult)
        assert result.scan_depth == ScanDepth.DEEP

    def test_deep_scan_with_directories(self):
        mock_diag = _make_diag()
        dirs = [
            DirectoryAnalysis(
                path="C:\\Windows", name="Windows",
                total_size_bytes=10 * 1024**3, file_count=50000,
            ),
            DirectoryAnalysis(
                path="C:\\Users", name="User Profile",
                total_size_bytes=5 * 1024**3, file_count=1000,
            ),
        ]
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag), \
             patch.object(storage_analyzer, "_analyze_directories", return_value=dirs):
            result = storage_analyzer.deep_scan()
        assert len(result.largest_directories) == 2
        # Should be sorted by size descending
        assert result.largest_directories[0].name == "Windows"

    def test_deep_scan_duration(self):
        mock_diag = _make_diag()
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag), \
             patch.object(storage_analyzer, "_analyze_directories", return_value=[]):
            result = storage_analyzer.deep_scan()
        assert result.duration_seconds >= 0

    def test_deep_scan_large_dir_recommendation(self):
        mock_diag = _make_diag()
        dirs = [
            DirectoryAnalysis(
                path="C:\\BigDir", name="Big Directory",
                total_size_bytes=10 * 1024**3, file_count=5000,
            ),
        ]
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag), \
             patch.object(storage_analyzer, "_analyze_directories", return_value=dirs):
            result = storage_analyzer.deep_scan()
        dir_recs = [r for r in result.recommendations if r["category"] == "directory_review"]
        assert len(dir_recs) > 0
        assert "Big Directory" in dir_recs[0]["title"]

    def test_deep_scan_callback(self):
        mock_diag = _make_diag()
        callback = MagicMock()
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag), \
             patch.object(storage_analyzer, "_analyze_directories", return_value=[]):
            result = storage_analyzer.deep_scan(callback=callback)
        callback.assert_called_once()

    def test_hdd_recommendation(self):
        mock_diag = _make_diag(
            system_drive=_make_partition(disk_type="HDD"),
        )
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag), \
             patch.object(storage_analyzer, "_analyze_directories", return_value=[]):
            result = storage_analyzer.deep_scan()
        hw_recs = [r for r in result.recommendations if r["category"] == "hardware"]
        assert len(hw_recs) > 0
        assert "HDD" in hw_recs[0]["title"]


class TestStorageAnalyzerDirectoryAnalysis:
    def test_analyze_existing_directory(self):
        # Use a known directory
        result = storage_analyzer._analyze_single_directory(
            tempfile.gettempdir(), "Temp", max_depth=1
        )
        assert result.accessible is True
        assert result.name == "Temp"
        assert result.path == tempfile.gettempdir()

    def test_analyze_nonexistent_directory(self):
        result = storage_analyzer._analyze_single_directory(
            "C:\\nonexistent_path_12345", "Missing"
        )
        # Should handle gracefully
        assert result.total_size_bytes == 0

    def test_analyze_with_max_depth_zero(self):
        result = storage_analyzer._analyze_single_directory(
            tempfile.gettempdir(), "Temp", max_depth=0
        )
        assert result.accessible is True

    def test_largest_files_tracking(self):
        result = storage_analyzer._analyze_single_directory(
            tempfile.gettempdir(), "Temp", max_depth=1
        )
        # largest_files should be a list of tuples
        assert isinstance(result.largest_files, list)
        for item in result.largest_files:
            assert len(item) == 2
            assert isinstance(item[1], int)


class TestStorageAnalyzerDriveHealth:
    def test_healthy(self):
        diag = _make_diag(pressure_level=StoragePressure.NORMAL)
        health = storage_analyzer._classify_drive_health(diag)
        assert health == DriveHealth.HEALTHY

    def test_warning(self):
        diag = _make_diag(pressure_level=StoragePressure.CRITICAL)
        health = storage_analyzer._classify_drive_health(diag)
        assert health == DriveHealth.WARNING

    def test_attention(self):
        diag = _make_diag(pressure_level=StoragePressure.HIGH_PRESSURE)
        health = storage_analyzer._classify_drive_health(diag)
        assert health == DriveHealth.ATTENTION

    def test_unknown_when_no_drive(self):
        diag = _make_diag(system_drive=None)
        health = storage_analyzer._classify_drive_health(diag)
        assert health == DriveHealth.UNKNOWN


class TestStorageAnalyzerRecommendations:
    def test_normal_drive_no_recs(self):
        diag = _make_diag()
        overview = storage_analyzer._build_overview(diag, ScanDepth.QUICK)
        recs = storage_analyzer._generate_recommendations(
            overview, diag.reclaimable_targets
        )
        # Healthy drive should not have pressure recs
        pressure_recs = [r for r in recs if r.category == "disk_pressure"]
        assert len(pressure_recs) == 0

    def test_critical_drive_has_rec(self):
        diag = _make_diag(
            system_drive=_make_partition(
                total=100 * 1024**3, used=99 * 1024**3,
                free=1 * 1024**3, pct=99.0
            ),
        )
        overview = storage_analyzer._build_overview(diag, ScanDepth.QUICK)
        recs = storage_analyzer._generate_recommendations(
            overview, diag.reclaimable_targets
        )
        pressure_recs = [r for r in recs if r.category == "disk_pressure"]
        assert len(pressure_recs) > 0
        assert pressure_recs[0].severity == StorageRecommendationSeverity.CRITICAL

    def test_cleanup_recommendation(self):
        diag = _make_diag()
        overview = storage_analyzer._build_overview(diag, ScanDepth.QUICK)
        candidates = [
            ReclaimableTarget(
                name="Temp", path="/tmp",
                estimated_bytes=3 * 1024**3,
                status="SAFE", category="TEMP",
            ),
        ]
        recs = storage_analyzer._generate_recommendations(overview, candidates)
        cleanup_recs = [r for r in recs if r.category == "cleanup"]
        assert len(cleanup_recs) > 0

    def test_no_overview(self):
        recs = storage_analyzer._generate_recommendations(None, [])
        assert recs == []


class TestStorageAnalyzerOverview:
    def test_overview_aggregation(self):
        p1 = DiskPartitionInfo(
            device="C:\\", mountpoint="C:\\", filesystem="NTFS",
            total_bytes=500 * 1024**3, used_bytes=200 * 1024**3,
            free_bytes=300 * 1024**3, percent_used=40.0,
            is_system_drive=True, disk_type="SSD",
        )
        p2 = DiskPartitionInfo(
            device="D:\\", mountpoint="D:\\", filesystem="NTFS",
            total_bytes=1000 * 1024**3, used_bytes=400 * 1024**3,
            free_bytes=600 * 1024**3, percent_used=40.0,
            is_system_drive=False, disk_type="UNKNOWN",
        )
        diag = _make_diag(all_partitions=[p1, p2])
        overview = storage_analyzer._build_overview(diag, ScanDepth.QUICK)
        assert overview.total_storage_bytes == 1500 * 1024**3
        assert overview.total_used_bytes == 600 * 1024**3
        assert overview.total_free_bytes == 900 * 1024**3


class TestAsyncDeepScan:
    def test_is_deep_scanning(self):
        assert storage_analyzer.is_deep_scanning is False

    def test_start_deep_scan(self):
        mock_diag = _make_diag()
        with patch.object(storage_analyzer._base, "diagnose", return_value=mock_diag), \
             patch.object(storage_analyzer, "_analyze_directories", return_value=[]):
            # Start and wait for completion
            scan_id = storage_analyzer.start_deep_scan_async()
            assert isinstance(scan_id, str)
            # Wait for thread to complete
            storage_analyzer._deep_scan_thread.join(timeout=10)
        assert storage_analyzer.is_deep_scanning is False

    def test_stop_deep_scan(self):
        # Should not raise
        storage_analyzer.stop_deep_scan()
        assert storage_analyzer.is_deep_scanning is False


class TestStorageRecToDict:
    def test_to_dict(self):
        rec = StorageRecommendation(
            title="Test",
            explanation="Explanation",
            severity=StorageRecommendationSeverity.HIGH,
            evidence={"free_gb": 3.0},
            estimated_benefit="Reclaim space",
            risk="NONE",
            category="disk_pressure",
        )
        d = StorageAnalyzer._rec_to_dict(rec)
        assert d["title"] == "Test"
        assert d["severity"] == "HIGH"
        assert d["evidence"]["free_gb"] == 3.0


# ══════════════════════════════════════════════════════════════════
# 4. CLI Integration
# ══════════════════════════════════════════════════════════════════

class TestCLIIntegration:
    def test_storage_status(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--storage-status"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=30,
        )
        assert result.returncode == 0
        assert "STORAGE STATUS" in result.stdout

    def test_storage_scan(self):
        import subprocess
        result = subprocess.run(
            [sys.executable, "main.py", "--storage-scan"],
            cwd=os.path.join(os.path.dirname(__file__), ".."),
            capture_output=True, text=True, timeout=60,
        )
        assert result.returncode == 0
        assert "DEEP STORAGE SCAN" in result.stdout


# ══════════════════════════════════════════════════════════════════
# 5. Edge Cases
# ══════════════════════════════════════════════════════════════════

class TestEdgeCases:
    def test_scan_depth_enum(self):
        assert ScanDepth.QUICK.value == "QUICK"
        assert ScanDepth.DEEP.value == "DEEP"

    def test_drive_health_enum(self):
        assert DriveHealth.HEALTHY.value == "HEALTHY"
        assert DriveHealth.ATTENTION.value == "ATTENTION"
        assert DriveHealth.WARNING.value == "WARNING"
        assert DriveHealth.UNKNOWN.value == "UNKNOWN"

    def test_severity_enum(self):
        assert StorageRecommendationSeverity.CRITICAL.value == "CRITICAL"
        assert StorageRecommendationSeverity.HIGH.value == "HIGH"
        assert StorageRecommendationSeverity.MEDIUM.value == "MEDIUM"
        assert StorageRecommendationSeverity.LOW.value == "LOW"
        assert StorageRecommendationSeverity.INFO.value == "INFO"

    def test_empty_partition_list(self):
        diag = _make_diag(all_partitions=[], system_drive=None)
        overview = storage_analyzer._build_overview(diag, ScanDepth.QUICK)
        assert overview.total_storage_bytes == 0
        assert overview.disk_health == DriveHealth.UNKNOWN

    def test_overview_preserves_scan_depth(self):
        diag = _make_diag()
        ov = storage_analyzer._build_overview(diag, ScanDepth.DEEP)
        assert ov.scan_depth == ScanDepth.DEEP

    def test_scan_result_post_init(self):
        result = StorageScanResult(scan_id="")
        assert result.scan_id.startswith("scan_")

    def test_recommendation_post_init(self):
        rec = StorageRecommendation(id="")
        assert rec.id.startswith("srec_")
