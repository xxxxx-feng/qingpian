import hashlib
import tempfile
import threading
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

from photo_tool.processing import (Adjustments, ProcessingCancelled, SRGB_BYTES,
                                   adjust_photo, collect_photos, export_batch,
                                   export_photo, load_photo)


class ProcessingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        # A dark image with a bright window; avoids a meaningless solid fixture.
        yy, xx = np.mgrid[0:240, 0:320]
        pixels = np.stack([25 + xx / 5, 20 + yy / 5, 30 + xx / 8], axis=2)
        pixels[20:70, 220:290] = [244, 246, 242]
        self.image = Image.fromarray(pixels.astype(np.uint8))
        self.source = self.root / "手机原片.JPG"
        exif = Image.Exif()
        exif[271] = "Test Phone"
        exif[34665] = {36867: "2025:06:01 12:30:00", 40961: 1,
                       40962: 320, 40963: 240}
        exif[34853] = {1: "N", 2: (31.0, 12.0, 0.0), 3: "E", 4: (121.0, 30.0, 0.0)}
        self.image.save(self.source, quality=97, exif=exif, icc_profile=SRGB_BYTES)

    def tearDown(self):
        self.temp.cleanup()

    def test_default_lifts_shadows_while_preserving_highlights(self):
        photo = load_photo(self.source)
        before = np.asarray(photo.image).astype(float)
        after = np.asarray(adjust_photo(photo, Adjustments())).astype(float)
        self.assertGreater(after[100:200, 30:200].mean(), before[100:200, 30:200].mean() + 10)
        self.assertGreater(after[20:70, 220:290].mean(), 235)
        self.assertLess(after[20:70, 220:290].mean(), 253)
        self.assertEqual(photo.image.size, (320, 240))

    def test_zero_intensity_returns_exact_original_pixels(self):
        photo = load_photo(self.source)
        np.testing.assert_array_equal(np.asarray(photo.image),
                        np.asarray(adjust_photo(photo, Adjustments(intensity=0))))

    def test_neutral_adjustment_is_identity(self):
        photo = load_photo(self.source)
        neutral = Adjustments(auto=0, exposure=0, shadows=0, highlights=0,
                              contrast=0, temperature=0, vibrance=0)
        np.testing.assert_array_equal(np.asarray(photo.image), np.asarray(adjust_photo(photo, neutral)))

    def test_black_stays_black_and_white_stays_white(self):
        for color in (0, 255):
            path = self.root / f"{color}.jpg"
            Image.new("RGB", (80, 80), (color,) * 3).save(path)
            photo = load_photo(path)
            result = np.asarray(adjust_photo(photo, Adjustments()))
            self.assertTrue(np.all(result == color))

    def test_exif_orientation_and_camera_date_survive_export(self):
        path = self.root / "rotated.jpeg"
        exif = Image.Exif()
        exif[274] = 6
        exif[34665] = {36867: "2025:06:01 12:30:00"}
        self.image.save(path, exif=exif)
        destination = export_photo(path, self.root / "out", Adjustments())
        with Image.open(destination) as exported:
            self.assertEqual(exported.size, (240, 320))
            self.assertNotIn(274, exported.getexif())
            self.assertEqual(exported.getexif().get_ifd(34665)[36867], "2025:06:01 12:30:00")
            self.assertEqual(exported.getexif().get_ifd(34665)[40962], 240)
            self.assertTrue(exported.info["icc_profile"])

    def test_heic_can_be_decoded_and_exported(self):
        heic = self.root / "手机.HEIC"
        self.image.save(heic, format="HEIF", quality=95, icc_profile=SRGB_BYTES)
        photo = load_photo(heic)
        self.assertEqual(photo.size, self.image.size)
        exported = export_photo(heic, self.root / "out", Adjustments())
        with Image.open(exported) as result:
            self.assertEqual(result.format, "JPEG")
            self.assertEqual(result.size, self.image.size)

    def test_metadata_can_be_removed_including_gps(self):
        keep = export_photo(self.source, self.root / "out", Adjustments(), keep_metadata=True)
        private = export_photo(self.source, self.root / "out", Adjustments(), keep_metadata=False)
        with Image.open(keep) as image:
            self.assertEqual(image.getexif().get_ifd(34853)[1], "N")
        with Image.open(private) as image:
            self.assertFalse(image.getexif())
            self.assertTrue(image.info["icc_profile"])

    def test_exports_never_overwrite_and_source_is_untouched(self):
        digest = hashlib.sha256(self.source.read_bytes()).hexdigest()
        first = export_photo(self.source, self.root, Adjustments())
        original_export = first.read_bytes()
        second = export_photo(self.source, self.root, Adjustments(exposure=0.5))
        self.assertNotEqual(first, second)
        self.assertEqual(first.read_bytes(), original_export)
        self.assertEqual(hashlib.sha256(self.source.read_bytes()).hexdigest(), digest)

    def test_collision_between_jpeg_and_heic_is_handled(self):
        jpeg = self.root / "same.jpg"
        heic = self.root / "same.heic"
        self.image.save(jpeg)
        self.image.save(heic, format="HEIF")
        successful, failed = export_batch([jpeg, heic], self.root / "out", Adjustments())
        self.assertEqual(len(successful), 2)
        self.assertEqual(len(set(successful)), 2)
        self.assertFalse(failed)

    def test_corrupt_photo_is_reported_and_batch_continues(self):
        broken = self.root / "broken.jpg"
        broken.write_bytes(b"not a JPEG")
        updates = []
        successful, failed = export_batch([broken, self.source], self.root / "out", Adjustments(),
                                         progress=lambda *args: updates.append(args))
        self.assertEqual(len(successful), 1)
        self.assertEqual(failed[0][0], broken)
        self.assertEqual(len(updates), 2)

    def test_cancel_does_not_create_an_output(self):
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(ProcessingCancelled):
            export_photo(self.source, self.root / "out", Adjustments(), cancel=cancel)
        self.assertFalse((self.root / "out").exists())

    def test_cancel_between_photos_retains_only_finished_exports(self):
        cancel = threading.Event()
        success, failed = export_batch([self.source, self.source], self.root / "out", Adjustments(),
                        cancel=cancel, progress=lambda *args: cancel.set())
        self.assertEqual(len(success), 1)
        self.assertFalse(failed)
        self.assertEqual(len(list((self.root / "out").glob("*.jpg"))), 1)

    def test_folder_recursion_and_deduplication(self):
        child = self.root / "child"
        child.mkdir()
        nested = child / "nested.JPEG"
        self.image.save(nested)
        (self.root / "ignore.txt").write_text("ignore")
        self.assertEqual(collect_photos([self.root, self.source]), [self.source.resolve()])
        self.assertEqual(set(collect_photos([self.root], recursive=True)),
                         {self.source.resolve(), nested.resolve()})

    def test_invalid_settings_are_rejected(self):
        for kwargs in ({"exposure": float("nan")}, {"auto": 4}, {"intensity": -1}):
            with self.assertRaises(ValueError):
                Adjustments(**kwargs)


if __name__ == "__main__":
    unittest.main()

