"""Tests for the benchmark engine and frame pacing calculations."""

import unittest
from app.performance.frame_analyzer import FramePacingAnalyzer, PacingResult


class TestFramePacingAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = FramePacingAnalyzer()

    def test_metrics_from_frame_times(self):
        """Test real frame time analysis at 60fps."""
        # Simulate 60fps: ~16.67ms frame times
        frame_times = [16.67] * 100
        result = self.analyzer.analyze(frame_times)
        self.assertAlmostEqual(result.avg_fps, 60.0, delta=2.0)
        self.assertGreater(result.one_percent_low, 0)
        self.assertGreater(result.point_one_percent_low, 0)
        self.assertGreater(result.stability_score, 80)  # Perfectly stable

    def test_metrics_empty(self):
        result = self.analyzer.analyze([])
        self.assertEqual(result.avg_fps, 0)
        self.assertEqual(result.one_percent_low, 0)

    def test_frame_spikes_detection(self):
        """Normal frame times with a few spikes."""
        frame_times = [16.67] * 90 + [100.0] * 10  # 10 spikes at 100ms
        result = self.analyzer.analyze(frame_times)
        self.assertGreater(result.spike_count, 0)
        self.assertGreater(result.long_frame_count, 0)

    def test_instability_detection(self):
        """Highly variable frame times should have low stability."""
        # Alternating fast/slow frames
        frame_times = [8.0, 33.0] * 50
        result = self.analyzer.analyze(frame_times)
        self.assertLess(result.stability_score, 70)

    def test_stability_ratings(self):
        # Perfect frames
        result = self.analyzer.analyze([16.67] * 100)
        self.assertEqual(result.stability, "EXCELLENT")

        # Very unstable
        result = self.analyzer.analyze([5.0, 100.0] * 50)
        self.assertIn(result.stability, ["POOR", "BAD"])


class TestBenchmarkMetrics(unittest.TestCase):

    def test_empty_benchmark_result(self):
        """BenchmarkResult without FPS should show unavailable."""
        from app.core.benchmark import BenchmarkResult
        result = BenchmarkResult()
        self.assertFalse(result.fps_available)
        self.assertIsNone(result.fps_metrics)


if __name__ == "__main__":
    unittest.main()
