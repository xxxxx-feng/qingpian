"""Offscreen end-to-end checks using temporary, generated photo fixtures."""

import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import tempfile
import time
import unittest
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from photo_tool.gui import MainWindow, STYLE
from photo_tool.processing import DEFAULT_PRESET, PRESETS, STUDIO_PRESET


class GuiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = QApplication.instance() or QApplication([])
        cls.app.setStyle("Fusion")
        cls.app.setStyleSheet(STYLE)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        yy, xx = np.mgrid[:720, :960]
        pixels = np.stack([25 + xx / 7, 30 + yy / 6, 30 + xx / 11], axis=2).astype(np.uint8)
        self.source = self.root / "周末散步.jpg"
        Image.fromarray(pixels).save(self.source)
        self.window = MainWindow()
        self.window.show()
        self.app.processEvents()

    def tearDown(self):
        self.wait_until(lambda: not any(p.activeThreadCount() for p in
                       [self.window.pool, self.window.scan_pool, self.window.export_pool]))
        self.window.close()
        self.app.processEvents()
        self.temp.cleanup()

    def wait_until(self, predicate, timeout=20):
        started = time.monotonic()
        while not predicate():
            self.app.processEvents()
            QTest.qWait(20)
            if time.monotonic() - started > timeout:
                self.fail("GUI operation timed out")
        self.app.processEvents()

    def import_photo(self):
        self.window.add_paths([self.source])
        self.wait_until(lambda: self.window.view.after is not None)

    def test_import_adjust_preview_export_and_keep_original(self):
        original = self.source.read_bytes()
        self.import_photo()
        self.assertEqual(len(self.window.items), 1)
        self.window.sliders["exposure"].set_value(0.25)
        self.wait_until(lambda: not self.window.view.loading)
        self.window.begin_export([self.source], self.root / "export")
        self.wait_until(lambda: not self.window.exporting)
        exports = list((self.root / "export").glob("*.jpg"))
        self.assertEqual(len(exports), 1)
        with Image.open(exports[0]) as result:
            self.assertEqual(result.size, (960, 720))
        self.assertEqual(self.source.read_bytes(), original)
        self.assertFalse(self.window.failures)
        self.assertTrue(self.window.open_button.isVisible())

    def test_latest_preview_wins_and_zero_strength_matches_original(self):
        self.import_photo()
        for value in (0.2, 0.5, -0.2, 1.0):
            self.window.sliders["exposure"].set_value(value)
            self.app.processEvents()
        self.window.sliders["intensity"].set_value(0)
        self.wait_until(lambda: not self.window.view.loading)
        self.assertEqual(self.window.view.before, self.window.view.after)

    def test_selection_and_removal(self):
        self.import_photo()
        self.window.toggle_all()
        self.assertFalse(self.window.export_button.isEnabled())
        self.window.toggle_all()
        self.assertTrue(self.window.export_button.isEnabled())
        self.window.remove_current()
        self.assertEqual(len(self.window.items), 0)
        self.assertIsNone(self.window.view.before)

    def test_automatic_default_hides_parameters_and_reset_restores_preview(self):
        self.assertEqual(self.window.preset.currentText(), DEFAULT_PRESET)
        self.assertEqual(self.window.settings(), PRESETS[DEFAULT_PRESET])
        self.assertTrue(self.window.settings().adaptive)
        self.assertFalse(self.window.advanced_scroll.isVisible())
        self.assertFalse(self.window.quality.isVisible())
        self.assertFalse(self.window.sliders["exposure"].isEnabled())
        self.import_photo()
        default_image = self.window.view.after.copy()
        self.window.advanced_toggle.click()
        self.assertTrue(self.window.advanced_scroll.isVisible())
        self.window.preset.setCurrentText(STUDIO_PRESET)
        self.assertTrue(self.window.sliders["exposure"].isEnabled())
        self.window.sliders["exposure"].set_value(0.6)
        self.wait_until(lambda: not self.window.view.loading)
        self.assertNotEqual(self.window.view.after, default_image)
        self.window.reset()
        self.wait_until(lambda: not self.window.view.loading)
        self.assertEqual(self.window.view.after, default_image)
        self.window.preset.setCurrentText("自然提亮")
        self.assertEqual(self.window.settings(), PRESETS["自然提亮"])
        self.window.preset.setCurrentText(DEFAULT_PRESET)
        self.assertEqual(self.window.settings(), PRESETS[DEFAULT_PRESET])

    def test_default_batch_needs_no_parameter_changes(self):
        second = self.root / "明亮照片.jpg"
        Image.new("RGB", (800, 600), (210, 214, 210)).save(second)
        self.window.add_paths([self.source, second])
        self.wait_until(lambda: self.window.view.after is not None)
        self.assertEqual(len(self.window.items), 2)
        self.assertTrue(all(item.checkState() == Qt.CheckState.Checked for item in self.window.items.values()))
        self.window.begin_export(list(self.window.items), self.root / "auto-export")
        self.wait_until(lambda: not self.window.exporting)
        self.assertEqual(len(list((self.root / "auto-export").glob("*.jpg"))), 2)
        self.assertFalse(self.window.failures)
        self.assertFalse(self.window.advanced_scroll.isVisible())

    def test_space_compares_original_without_changing_export_selection(self):
        self.import_photo()
        item = self.window.photo_list.currentItem()
        self.window.photo_list.setFocus()
        QTest.keyPress(self.window.photo_list, Qt.Key.Key_Space)
        self.assertTrue(self.window.view.original_only)
        self.assertEqual(item.checkState(), Qt.CheckState.Checked)
        QTest.keyRelease(self.window.photo_list, Qt.Key.Key_Space)
        self.assertFalse(self.window.view.original_only)

    def test_empty_and_loaded_layout_render(self):
        screenshot_dir = os.environ.get("QINGPIAN_SCREENSHOTS")
        if screenshot_dir:
            directory = Path(screenshot_dir)
            directory.mkdir(parents=True, exist_ok=True)
            self.window.grab().save(str(directory / "empty.png"))
        self.import_photo()
        self.window.set_mode("side")
        self.app.processEvents()
        if screenshot_dir:
            self.window.grab().save(str(directory / "preview.png"))
        self.assertTrue(self.window.view.isVisible())


if __name__ == "__main__":
    unittest.main()
