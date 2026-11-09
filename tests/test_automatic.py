"""Behavior checks for bounded, per-photo automatic correction."""

import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from photo_tool.processing import (Adjustments, Photo, adjust_photo, analyze_photo,
                                   export_batch, load_photo)


class AutomaticTests(unittest.TestCase):
    def render(self, image):
        plan = analyze_photo(image)
        photo = Photo(image, b"", image.size, 0, auto_plan=plan)
        return plan, np.asarray(adjust_photo(photo, Adjustments(adaptive=True)))

    def test_dark_and_bright_photos_get_different_exposure_and_tone(self):
        dark, dark_result = self.render(Image.new("RGB", (240, 180), (65, 65, 65)))
        bright, bright_result = self.render(Image.new("RGB", (240, 180), (225, 225, 225)))
        self.assertGreater(dark.exposure_ev, 0.5)
        self.assertLess(bright.exposure_ev, 0)
        self.assertGreater(dark.shadows, bright.shadows)
        self.assertGreater(bright.highlights, dark.highlights)
        self.assertGreater(dark_result.mean(), 75)
        self.assertLess(bright_result.mean(), 225)
        self.assertGreater(bright_result.mean(), 190)

    def test_backlit_center_is_lifted_without_burning_bright_edges(self):
        pixels = np.full((240, 320, 3), 238, dtype=np.uint8)
        pixels[35:205, 55:265] = (55, 60, 65)
        plan, result = self.render(Image.fromarray(pixels))
        self.assertTrue(plan.backlit)
        self.assertGreater(result[65:175, 85:235].mean(), pixels[65:175, 85:235].mean() + 10)
        self.assertLessEqual(result[:30].max(), 253)
        self.assertGreater(result[:30].mean(), 225)

    def test_night_scene_retains_dark_atmosphere(self):
        rng = np.random.default_rng(42)
        pixels = rng.integers(9, 19, (240, 320, 3), dtype=np.uint8)
        pixels[20:35, 30:70] = 240
        plan, result = self.render(Image.fromarray(pixels))
        self.assertTrue(plan.low_light)
        self.assertLessEqual(plan.exposure_ev, 0.55)
        self.assertLessEqual(plan.shadows, 0.18)
        self.assertLess(np.median(result), 45)
        self.assertEqual(plan.white_balance, (1, 1, 1))

    def test_black_night_with_bright_lights_is_not_mistaken_for_daylight(self):
        pixels = np.zeros((240, 320, 3), dtype=np.uint8)
        pixels[:30, :200] = 230
        plan, result = self.render(Image.fromarray(pixels))
        self.assertTrue(plan.low_light)
        self.assertGreaterEqual(plan.exposure_ev, 0)
        self.assertTrue(np.all(result[100:] == 0))

    def test_balanced_neutrals_remain_neutral_and_change_only_gently(self):
        ramp = np.linspace(80, 205, 320, dtype=np.uint8)
        pixels = np.repeat(np.tile(ramp, (240, 1))[..., None], 3, axis=2)
        plan, result = self.render(Image.fromarray(pixels))
        self.assertEqual(plan.exposure_ev, 0)
        self.assertLess(np.abs(result.astype(float) - pixels).mean(), 6)
        np.testing.assert_array_equal(result[..., 0], result[..., 1])
        np.testing.assert_array_equal(result[..., 1], result[..., 2])

    def test_supported_mild_color_cast_is_reduced_with_bounded_gains(self):
        ramp = np.linspace(75, 205, 320)
        base = np.tile(ramp, (240, 1))[..., None]
        pixels = np.uint8(np.clip(base * np.array([1.08, 1.0, 0.93]), 0, 255))
        plan, result = self.render(Image.fromarray(pixels))
        self.assertGreater(plan.white_balance_confidence, 0.5)
        self.assertTrue(all(0.92 <= gain <= 1.08 for gain in plan.white_balance))
        before_ratio = pixels[120, 150, 0] / float(pixels[120, 150, 2])
        after_ratio = result[120, 150, 0] / float(result[120, 150, 2])
        self.assertLess(abs(after_ratio - 1), abs(before_ratio - 1))

    def test_green_scene_does_not_get_forced_toward_gray(self):
        pixels = np.zeros((240, 320, 3), dtype=np.uint8)
        ramp = np.linspace(0.6, 1, 320)[None, :, None]
        pixels[:] = np.uint8(np.array([40, 175, 65])[None, None, :] * ramp)
        plan, result = self.render(Image.fromarray(pixels))
        self.assertEqual(plan.white_balance_confidence, 0)
        self.assertEqual(plan.white_balance, (1, 1, 1))
        self.assertGreater(result[..., 1].mean(), result[..., 0].mean() * 2)

    def test_low_confidence_single_tint_is_not_rebalanced(self):
        plan, _ = self.render(Image.new("RGB", (240, 180), (180, 166, 151)))
        self.assertEqual(plan.white_balance, (1, 1, 1))

    def test_black_and_white_are_stable_in_automatic_mode(self):
        for value in (0, 255):
            _, result = self.render(Image.new("RGB", (120, 80), (value,) * 3))
            self.assertTrue(np.all(result == value))

    def test_preview_and_export_analyze_the_same_original(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "large.jpg"
            yy, xx = np.mgrid[:1300, :1900]
            pixels = np.stack([30 + xx / 15, 35 + yy / 12, 35 + xx / 20], axis=2).astype(np.uint8)
            Image.fromarray(pixels).save(path)
            full = load_photo(path)
            preview = load_photo(path, preview_edge=600)
            self.assertNotEqual(full.image.size, preview.image.size)
            self.assertEqual(full.auto_plan, preview.auto_plan)
            self.assertEqual(full.suggested_ev, preview.suggested_ev)

    def test_unattended_batch_adapts_each_photo_and_keeps_originals(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = [root / "dark.jpg", root / "bright.jpg"]
            for path, value in zip(paths, (65, 225)):
                Image.new("RGB", (320, 240), (value,) * 3).save(path)
            originals = [path.read_bytes() for path in paths]
            exported, failed = export_batch(paths, root / "out", Adjustments(adaptive=True))
            self.assertFalse(failed)
            self.assertEqual(len(exported), 2)
            means = []
            for path in exported:
                with Image.open(path) as result:
                    means.append(np.asarray(result).mean())
                    self.assertEqual(result.size, (320, 240))
            self.assertGreater(means[0], 75)
            self.assertLess(means[1], 225)
            self.assertEqual([path.read_bytes() for path in paths], originals)


if __name__ == "__main__":
    unittest.main()
