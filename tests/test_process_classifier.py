"""Tests for process classification."""

import unittest
from app.system.processes import ProcessMonitor, ProcessInfo


class TestProcessClassifier(unittest.TestCase):

    def setUp(self):
        self.monitor = ProcessMonitor()

    def test_critical_process_classification(self):
        cat, imp = self.monitor.classify_process("svchost.exe")
        self.assertEqual(cat, "SYSTEM")
        self.assertEqual(imp, "CRITICAL")

    def test_emulator_process_classification(self):
        cat, imp = self.monitor.classify_process("msi.exe")
        self.assertEqual(cat, "TARGET")
        self.assertEqual(imp, "HIGH")

    def test_optional_process_classification(self):
        cat, imp = self.monitor.classify_process("discord.exe")
        self.assertEqual(cat, "OPTIONAL BACKGROUND")

    def test_unknown_process(self):
        cat, imp = self.monitor.classify_process("randomapp.exe")
        self.assertEqual(cat, "UNKNOWN")

    def test_recommendation_critical(self):
        pi = ProcessInfo(name="svchost.exe", category="SYSTEM", importance="CRITICAL")
        rec = self.monitor.get_process_recommendation(pi)
        self.assertIn("DO NOT", rec)

    def test_recommendation_optional(self):
        pi = ProcessInfo(name="discord.exe", category="OPTIONAL BACKGROUND", importance="LOW")
        rec = self.monitor.get_process_recommendation(pi)
        self.assertIn("Optional", rec)

    def test_classification_caching(self):
        cat1, imp1 = self.monitor.classify_process("test.exe")
        cat2, imp2 = self.monitor.classify_process("test.exe")
        self.assertEqual(cat1, cat2)
        self.assertEqual(imp1, imp2)


if __name__ == "__main__":
    unittest.main()
