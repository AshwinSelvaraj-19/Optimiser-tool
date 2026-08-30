"""Tests for optimization profiles management."""

import unittest
import tempfile
import shutil
from app.core.profiles import ProfileManager, OptimizationProfile, ProfileSetting


class TestProfileManager(unittest.TestCase):

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.manager = ProfileManager(self.test_dir)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_default_profiles_exist(self):
        profiles = self.manager.list_profiles()
        names = [p["key"] for p in profiles]
        self.assertIn("max_fps", names)
        self.assertIn("balanced", names)

    def test_get_profile(self):
        profile = self.manager.get_profile("max_fps")
        self.assertIsNotNone(profile)
        self.assertEqual(profile.name, "MAX FPS")

    def test_get_profile_case_insensitive(self):
        profile = self.manager.get_profile("max_fps")
        self.assertIsNotNone(profile)

    def test_get_nonexistent_profile(self):
        profile = self.manager.get_profile("nonexistent")
        self.assertIsNone(profile)

    def test_save_custom_profile(self):
        profile = OptimizationProfile(
            name="Test Custom",
            description="Test",
            target="TEST",
            settings=[ProfileSetting(key="test", name="Test", description="Test", default_value=True)],
        )
        self.assertTrue(self.manager.save_custom_profile(profile))
        loaded = self.manager.get_profile("Test Custom")
        self.assertIsNotNone(loaded)

    def test_max_fps_profile_has_settings(self):
        profile = self.manager.get_profile("max_fps")
        self.assertGreater(len(profile.settings), 0)
        keys = [s.key for s in profile.settings]
        self.assertIn("power_plan", keys)
        self.assertIn("game_mode", keys)


if __name__ == "__main__":
    unittest.main()
