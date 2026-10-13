import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image

import ocr


class TestOCRImagePreprocessing(unittest.TestCase):
    def test_image_is_upscaled_and_tesseract_uses_block_layout_mode(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "photo.png"
            Image.new("RGB", (600, 800), "white").save(path)
            seen = {}

            def fake_ocr(image, **kwargs):
                seen["size"] = image.size
                seen["kwargs"] = kwargs
                return "recognized text"

            with patch.object(ocr.pytesseract, "image_to_string", side_effect=fake_ocr):
                self.assertEqual(ocr.ocr_file(str(path)), "recognized text")

            self.assertGreater(seen["size"][0], 600)
            self.assertGreater(seen["size"][1], 800)
            self.assertLessEqual(max(seen["size"]), 3000)
            self.assertEqual(seen["kwargs"]["lang"], "rus+eng")
            self.assertEqual(seen["kwargs"]["config"], "--psm 6")

    def test_large_image_upscale_is_capped(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "large.png"
            Image.new("RGB", (1800, 3200), "white").save(path)
            seen = {}

            def fake_ocr(image, **kwargs):
                seen["size"] = image.size
                return "ok"

            with patch.object(ocr.pytesseract, "image_to_string", side_effect=fake_ocr):
                self.assertEqual(ocr.ocr_file(str(path)), "ok")

            self.assertEqual(max(seen["size"]), 3000)


if __name__ == "__main__":
    unittest.main()
