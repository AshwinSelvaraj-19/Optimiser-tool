"""Tests for the bottleneck analyzer engine."""

import unittest
from app.core.analyzer import BottleneckAnalyzer
from app.core.telemetry import TelemetryFrame


class TestBottleneckAnalyzer(unittest.TestCase):

    def setUp(self):
        self.analyzer = BottleneckAnalyzer()

    def test_cpu_bottleneck(self):
        frame = TelemetryFrame(
            cpu_utilization=96,
            gpu_utilization=40,
            ram_percent=50,
            timestamp=0,
        )
        result = self.analyzer.analyze(frame)
        self.assertTrue(result.has_critical or any(b.severity == "HIGH" for b in result.bottlenecks))
        self.assertEqual(result.primary_bottleneck.name, "CPU Limitation")

    def test_gpu_bottleneck(self):
        frame = TelemetryFrame(
            cpu_utilization=40,
            gpu_utilization=97,
            ram_percent=50,
            timestamp=0,
        )
        result = self.analyzer.analyze(frame)
        self.assertIn("GPU", result.primary_bottleneck.name)

    def test_thermal_throttling(self):
        frame = TelemetryFrame(
            cpu_utilization=60,
            gpu_utilization=70,
            ram_percent=50,
            thermal_status="THROTTLING",
            timestamp=0,
        )
        result = self.analyzer.analyze(frame)
        self.assertEqual(result.primary_bottleneck.name, "Thermal Throttling")
        self.assertEqual(result.primary_bottleneck.severity, "CRITICAL")

    def test_memory_pressure(self):
        frame = TelemetryFrame(
            cpu_utilization=50,
            gpu_utilization=50,
            ram_percent=95,
            timestamp=0,
        )
        result = self.analyzer.analyze(frame)
        memory_bottlenecks = [b for b in result.bottlenecks if "Memory" in b.name]
        self.assertTrue(len(memory_bottlenecks) > 0)

    def test_balanced_system(self):
        frame = TelemetryFrame(
            cpu_utilization=30,
            gpu_utilization=40,
            ram_percent=50,
            timestamp=0,
        )
        result = self.analyzer.analyze(frame)
        self.assertEqual(result.primary_bottleneck.name, "No Bottleneck Detected")

    def test_performance_classification(self):
        self.assertEqual(self.analyzer._classify_performance(80), "EXCELLENT")
        self.assertEqual(self.analyzer._classify_performance(60), "GOOD")
        self.assertEqual(self.analyzer._classify_performance(40), "AVERAGE")
        self.assertEqual(self.analyzer._classify_performance(20), "BOTTLENECKED")
        self.assertEqual(self.analyzer._classify_performance(5), "SEVERE")


if __name__ == "__main__":
    unittest.main()
