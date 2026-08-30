"""Tests for the performance scoring engine."""

import unittest
from app.core.scoring import (
    PerformanceScorer, BenchmarkMetrics, PerformanceScore, ScoreWeights
)


class TestPerformanceScorer(unittest.TestCase):

    def setUp(self):
        self.scorer = PerformanceScorer()

    def test_high_fps_high_score(self):
        metrics = BenchmarkMetrics(
            avg_fps=120.0,
            one_percent_low=90.0,
            point_one_percent_low=60.0,
            avg_frame_time_ms=8.33,
            frame_time_variance=1.0,
        )
        score = self.scorer.calculate(metrics)
        self.assertGreater(score.total_score, 70)
        self.assertIn(score.grade, ["S", "A", "B"])

    def test_low_fps_low_score(self):
        metrics = BenchmarkMetrics(
            avg_fps=15.0,
            one_percent_low=5.0,
            point_one_percent_low=1.0,
            avg_frame_time_ms=66.67,
            frame_time_variance=100.0,
        )
        score = self.scorer.calculate(metrics)
        self.assertLess(score.total_score, 30)
        self.assertIn(score.grade, ["E", "F"])

    def test_thermal_penalty(self):
        metrics = BenchmarkMetrics(avg_fps=100.0, one_percent_low=80.0)
        score_normal = self.scorer.calculate(metrics, thermal_throttling=False)
        score_throttled = self.scorer.calculate(metrics, thermal_throttling=True)
        self.assertGreater(score_normal.total_score, score_throttled.total_score)

    def test_grade_mapping(self):
        self.assertEqual(self.scorer._grade(95), "S")
        self.assertEqual(self.scorer._grade(85), "A")
        self.assertEqual(self.scorer._grade(75), "B")
        self.assertEqual(self.scorer._grade(65), "C")
        self.assertEqual(self.scorer._grade(45), "E")
        self.assertEqual(self.scorer._grade(20), "F")
        self.assertEqual(self.scorer._grade(5), "F")

    def test_delta_calculation(self):
        before = PerformanceScore(total_score=50, grade="D", component_scores={"avg_fps": 40, "one_percent_low": 30})
        after = PerformanceScore(total_score=60, grade="C", component_scores={"avg_fps": 50, "one_percent_low": 45})
        delta = self.scorer.calculate_delta(before, after)
        self.assertGreater(delta["score_change"], 0)
        self.assertIn("avg_fps", delta["component_changes"])

    def test_should_keep_improvement(self):
        before = PerformanceScore(total_score=50, grade="D")
        after = PerformanceScore(total_score=55, grade="D")
        keep, reason = self.scorer.should_keep_change(before, after)
        self.assertTrue(keep)

    def test_should_revert_regression(self):
        before = PerformanceScore(total_score=50, grade="D")
        after = PerformanceScore(total_score=40, grade="E")
        keep, reason = self.scorer.should_keep_change(before, after)
        self.assertFalse(keep)

    def test_empty_metrics(self):
        metrics = BenchmarkMetrics()
        score = self.scorer.calculate(metrics)
        self.assertLessEqual(score.total_score, 10)


class TestScoreWeights(unittest.TestCase):

    def test_normalize(self):
        w = ScoreWeights(avg_fps=4, one_percent_low=3, point_one_percent_low=2, frame_stability=1)
        w.normalize()
        total = w.avg_fps + w.one_percent_low + w.point_one_percent_low + w.frame_stability
        self.assertAlmostEqual(total, 1.0, places=6)


if __name__ == "__main__":
    unittest.main()
