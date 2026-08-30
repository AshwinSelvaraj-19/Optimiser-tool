"""Tests for registry utilities (mocked where needed)."""

import unittest
from app.utils.registry import (
    read_registry_value, backup_registry_key,
    registry_key_exists
)


class TestRegistryUtils(unittest.TestCase):

    def test_read_nonexistent_key(self):
        """Reading a nonexistent key should return None, not crash."""
        result = read_registry_value(
            "HKCU",
            "Software\\PhoenixOptimizerTest_Nonexistent\\Key",
            "NonexistentValue"
        )
        self.assertIsNone(result)

    def test_key_exists_check(self):
        """Check if a known Windows key exists."""
        exists = registry_key_exists("HKCU", "Software\\Microsoft\\Windows")
        # This should exist on Windows
        self.assertTrue(exists)

    def test_key_not_exists(self):
        exists = registry_key_exists(
            "HKCU",
            "Software\\PhoenixOptimizerTest_Definitely_Nonexistent"
        )
        self.assertFalse(exists)

    def test_backup_nonexistent(self):
        """Backing up nonexistent key should return empty backup."""
        backup = backup_registry_key(
            "HKCU",
            "Software\\PhoenixOptimizerTest_Nonexistent"
        )
        self.assertEqual(len(backup["values"]), 0)


if __name__ == "__main__":
    unittest.main()
