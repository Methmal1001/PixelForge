"""Tests for services.export_service (composition with text and file output)."""

import os
import tempfile
import unittest
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402

from models.design import TextElement  # noqa: E402
from services import export_service as es  # noqa: E402
from services.text_renderer import ensure_gui_application  # noqa: E402


def setUpModule() -> None:  # noqa: N802
    ensure_gui_application()


class ExportTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.base = Image.new("RGB", (200, 100), (20, 30, 40))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_compose_renders_text_onto_image(self) -> None:
        text = TextElement("HELLO", x=10, y=10, font_size=40, color="#FFFFFF", bold=True)
        composed = es.compose_design(self.base, [text])
        self.assertEqual(composed.size, (200, 100))
        data = composed.convert("RGB").tobytes()
        bright = sum(1 for i in range(0, len(data), 3) if min(data[i:i + 3]) > 200)
        self.assertGreater(bright, 50, "white text pixels should be present")
        self.assertEqual(composed.getpixel((195, 95))[:3], (20, 30, 40), "background outside text untouched")
        self.assertEqual(self.base.getpixel((15, 30)), (20, 30, 40), "source image must not be modified")

    def test_png_export(self) -> None:
        path = es.export_design(self.base, [], es.ExportOptions(path=self.dir / "out.png", image_format="PNG"))
        with Image.open(path) as image:
            self.assertEqual(image.format, "PNG")
            self.assertEqual(image.size, (200, 100))

    def test_png_preserves_transparency(self) -> None:
        transparent = Image.new("RGBA", (50, 50), (255, 0, 0, 0))
        path = es.export_design(transparent, [], es.ExportOptions(path=self.dir / "alpha.png"))
        with Image.open(path) as image:
            self.assertEqual(image.mode, "RGBA")
            self.assertEqual(image.getpixel((0, 0))[3], 0)

    def test_jpeg_export_flattens_onto_background(self) -> None:
        transparent = Image.new("RGBA", (50, 50), (255, 0, 0, 0))
        options = es.ExportOptions(path=self.dir / "flat.jpg", image_format="JPEG", quality=95,
                                   background="#00FF00")
        path = es.export_design(transparent, [], options)
        with Image.open(path) as image:
            self.assertEqual(image.format, "JPEG")
            self.assertEqual(image.mode, "RGB")
            r, g, b = image.getpixel((25, 25))
            self.assertGreater(g, 240)
            self.assertLess(r, 15)

    def test_export_dimensions(self) -> None:
        text = TextElement("Sale", x=20, y=20, font_size=30)
        for width, height, mode in ((1080, 1080, "fill"), (1080, 1350, "fit"), (1920, 1080, "stretch"),
                                    (64, 32, "fill")):
            with self.subTest(size=(width, height, mode)):
                options = es.ExportOptions(path=self.dir / f"o_{width}x{height}.jpg", image_format="JPEG",
                                           width=width, height=height, fit_mode=mode)
                path = es.export_design(self.base, [text], options)
                with Image.open(path) as image:
                    self.assertEqual(image.size, (width, height))

    def test_wrong_extension_is_corrected(self) -> None:
        path = es.save_image(self.base, self.dir / "photo.png", "JPEG")
        self.assertEqual(path.name, "photo.jpg")
        self.assertTrue(path.exists())
        path = es.save_image(self.base, self.dir / "summer_post", "PNG")
        self.assertEqual(path.name, "summer_post.png")

    def test_invalid_inputs_raise_export_error(self) -> None:
        with self.assertRaises(es.ExportError):
            es.save_image(self.base, self.dir / "x.gif", "GIF")
        with self.assertRaises(es.ExportError):
            es.save_image(self.base, self.dir / "missing_folder" / "x.png", "PNG")
        with self.assertRaises(es.ExportError):
            es.save_image(self.base, self.dir / "x.jpg", "JPEG", quality=0)
        with self.assertRaises(es.ExportError):
            es.export_design(self.base, [], es.ExportOptions(path=self.dir / "x.png", width=-5, height=10))
        with self.assertRaises(es.ExportError):
            es.flatten(Image.new("RGBA", (2, 2)), "not-a-colour")


if __name__ == "__main__":
    unittest.main()
