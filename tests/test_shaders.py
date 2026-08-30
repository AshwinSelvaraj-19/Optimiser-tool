"""Tests for shader preset loading and validation."""

import json
import os
import unittest

SHADER_PRESETS_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "profiles", "shaders"
)

REQUIRED_KEYS = ["name", "description", "saturation", "contrast", "sharpness", "bloom", "hdr", "ambient_light", "vignette", "shadow"]


class TestShaderPresets(unittest.TestCase):

    def test_presets_directory_exists(self):
        self.assertTrue(os.path.exists(SHADER_PRESETS_DIR))

    def test_required_preset_files_exist(self):
        required = ["default.json", "vibrant.json", "competitive.json", "high_contrast.json"]
        for fname in required:
            path = os.path.join(SHADER_PRESETS_DIR, fname)
            self.assertTrue(os.path.exists(path), f"Missing preset: {fname}")

    def test_all_presets_valid_json(self):
        for fname in os.listdir(SHADER_PRESETS_DIR):
            if fname.endswith(".json"):
                path = os.path.join(SHADER_PRESETS_DIR, fname)
                with open(path, "r") as f:
                    data = json.load(f)
                self.assertIsInstance(data, dict)

    def test_all_presets_have_required_keys(self):
        for fname in os.listdir(SHADER_PRESETS_DIR):
            if fname.endswith(".json"):
                path = os.path.join(SHADER_PRESETS_DIR, fname)
                with open(path, "r") as f:
                    data = json.load(f)
                for key in REQUIRED_KEYS:
                    self.assertIn(key, data, f"{fname} missing key: {key}")

    def test_slider_value_ranges(self):
        ranges = {
            "saturation": (0, 200),
            "contrast": (0, 200),
            "sharpness": (0, 100),
            "bloom": (0, 100),
            "hdr": (0, 100),
            "ambient_light": (0, 100),
            "vignette": (0, 100),
            "shadow": (-50, 50),
        }
        for fname in os.listdir(SHADER_PRESETS_DIR):
            if fname.endswith(".json"):
                path = os.path.join(SHADER_PRESETS_DIR, fname)
                with open(path, "r") as f:
                    data = json.load(f)
                for key, (min_val, max_val) in ranges.items():
                    if key in data:
                        self.assertGreaterEqual(data[key], min_val, f"{fname}.{key} below min")
                        self.assertLessEqual(data[key], max_val, f"{fname}.{key} above max")


if __name__ == "__main__":
    unittest.main()
