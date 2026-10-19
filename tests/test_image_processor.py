"""Tests for services.image_processor (pure Pillow operations)."""

import tempfile
import unittest
from pathlib import Path

from PIL import Image

from models.design import Adjustments
from services import image_processor as ip


def gradient_image(width: int = 60, height: int = 40, mode: str = "RGB") -> Image.Image:
    image = Image.new(mode, (width, height))
    for x in range(width):
        for y in range(height):
            value = (x * 4 % 256, y * 6 % 256, 120)
            image.putpixel((x, y), value + ((200,) if mode == "RGBA" else ()))
    return image


class LoadImageTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_loads_png_jpeg_and_webp(self) -> None:
        source = gradient_image()
        for ext in (".png", ".jpg", ".jpeg", ".webp"):
            if ext not in ip.supported_extensions():
                continue
            path = self.dir / f"sample{ext}"
            source.save(path)
            loaded = ip.load_image(path)
            self.assertEqual(loaded.size, (60, 40), ext)
            self.assertEqual(loaded.mode, "RGB", ext)

    def test_png_with_alpha_loads_as_rgba(self) -> None:
        path = self.dir / "alpha.png"
        gradient_image(mode="RGBA").save(path)
        self.assertEqual(ip.load_image(path).mode, "RGBA")

    def test_missing_file_raises_readable_error(self) -> None:
        with self.assertRaises(ip.ImageLoadError) as ctx:
            ip.load_image(self.dir / "does_not_exist.png")
        self.assertIn("does not exist", str(ctx.exception))

    def test_empty_path_raises(self) -> None:
        with self.assertRaises(ip.ImageLoadError):
            ip.load_image("")

    def test_directory_path_raises(self) -> None:
        with self.assertRaises(ip.ImageLoadError):
            ip.load_image(self.dir)

    def test_unsupported_extension_raises(self) -> None:
        path = self.dir / "notes.txt"
        path.write_text("hello")
        with self.assertRaises(ip.ImageLoadError) as ctx:
            ip.load_image(path)
        self.assertIn("not a supported image type", str(ctx.exception))

    def test_corrupt_image_raises(self) -> None:
        path = self.dir / "broken.png"
        path.write_bytes(b"\x89PNG\r\n\x1a\nthis is not really a png")
        with self.assertRaises(ip.ImageLoadError) as ctx:
            ip.load_image(path)
        self.assertIn("could not be read", str(ctx.exception))


class GeometryTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image = gradient_image(60, 40)

    def test_resize(self) -> None:
        result = ip.resize(self.image, 30, 90)
        self.assertEqual(result.size, (30, 90))
        self.assertEqual(self.image.size, (60, 40), "input must not be modified")

    def test_resize_rejects_invalid_dimensions(self) -> None:
        for width, height in ((0, 10), (10, -5), ("abc", 10), (None, 10), (ip.MAX_DIMENSION + 1, 10)):
            with self.subTest(width=width, height=height), self.assertRaises(ip.ImageProcessingError):
                ip.resize(self.image, width, height)

    def test_fit_to_size_modes(self) -> None:
        for mode in ip.FIT_MODES:
            with self.subTest(mode=mode):
                self.assertEqual(ip.fit_to_size(self.image, 50, 50, mode).size, (50, 50))
        padded = ip.fit_to_size(self.image, 60, 60, "fit", (0, 0, 0, 0))
        self.assertEqual(padded.mode, "RGBA")
        self.assertEqual(padded.getpixel((0, 0))[3], 0, "padding should be transparent")

    def test_fit_to_size_rejects_unknown_mode(self) -> None:
        with self.assertRaises(ip.ImageProcessingError):
            ip.fit_to_size(self.image, 10, 10, "zoom")

    def test_crop(self) -> None:
        result = ip.crop(self.image, 10, 5, 20, 15)
        self.assertEqual(result.size, (20, 15))
        self.assertEqual(result.getpixel((0, 0)), self.image.getpixel((10, 5)))

    def test_crop_rejects_out_of_bounds(self) -> None:
        for args in ((-1, 0, 10, 10), (0, 0, 0, 10), (50, 0, 20, 10), (0, 35, 10, 10)):
            with self.subTest(args=args), self.assertRaises(ip.ImageProcessingError):
                ip.crop(self.image, *args)

    def test_rotation(self) -> None:
        left = ip.rotate_left(self.image)
        right = ip.rotate_right(self.image)
        self.assertEqual(left.size, (40, 60))
        self.assertEqual(right.size, (40, 60))
        # top-right pixel moves to top-left when rotating counter-clockwise
        self.assertEqual(left.getpixel((0, 0)), self.image.getpixel((59, 0)))
        # top-left pixel moves to top-right when rotating clockwise
        self.assertEqual(right.getpixel((39, 0)), self.image.getpixel((0, 0)))
        self.assertEqual(ip.rotate_right(left).tobytes(), self.image.tobytes())

    def test_flip(self) -> None:
        horizontal = ip.flip_horizontal(self.image)
        vertical = ip.flip_vertical(self.image)
        self.assertEqual(horizontal.getpixel((0, 0)), self.image.getpixel((59, 0)))
        self.assertEqual(vertical.getpixel((0, 0)), self.image.getpixel((0, 39)))
        self.assertEqual(ip.flip_horizontal(horizontal).tobytes(), self.image.tobytes())


class ColorTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image = Image.new("RGB", (10, 10), (100, 150, 50))

    def test_brightness(self) -> None:
        brighter = ip.adjust_brightness(self.image, 1.5).getpixel((0, 0))
        darker = ip.adjust_brightness(self.image, 0.5).getpixel((0, 0))
        self.assertGreater(sum(brighter), sum(self.image.getpixel((0, 0))))
        self.assertLess(sum(darker), sum(self.image.getpixel((0, 0))))
        self.assertEqual(ip.adjust_brightness(self.image, 0).getpixel((0, 0)), (0, 0, 0))

    def test_contrast(self) -> None:
        image = Image.new("RGB", (2, 1))
        image.putpixel((0, 0), (90, 90, 90))
        image.putpixel((1, 0), (160, 160, 160))
        stronger = ip.adjust_contrast(image, 2.0)
        spread_before = 160 - 90
        spread_after = stronger.getpixel((1, 0))[0] - stronger.getpixel((0, 0))[0]
        self.assertGreater(spread_after, spread_before)
        flat = ip.adjust_contrast(image, 0.0)
        self.assertEqual(flat.getpixel((0, 0)), flat.getpixel((1, 0)))

    def test_saturation(self) -> None:
        def spread(pixel):
            return max(pixel) - min(pixel)

        original = spread(self.image.getpixel((0, 0)))
        self.assertGreater(spread(ip.adjust_saturation(self.image, 1.8).getpixel((0, 0))), original)
        self.assertLess(spread(ip.adjust_saturation(self.image, 0.3).getpixel((0, 0))), original)
        self.assertLessEqual(spread(ip.adjust_saturation(self.image, 0.0).getpixel((0, 0))), 1)

    def test_adjustments_preserve_alpha(self) -> None:
        image = Image.new("RGBA", (4, 4), (100, 150, 50, 77))
        for result in (ip.adjust_brightness(image, 1.4), ip.adjust_contrast(image, 1.4),
                       ip.adjust_saturation(image, 1.4), ip.to_grayscale(image)):
            self.assertEqual(result.mode, "RGBA")
            self.assertEqual(result.getpixel((0, 0))[3], 77)

    def test_grayscale(self) -> None:
        r, g, b = ip.to_grayscale(self.image).getpixel((0, 0))
        self.assertTrue(r == g == b)

    def test_invalid_factors_raise(self) -> None:
        for factor in (-0.1, 3.5, "bright", float("nan")):
            with self.subTest(factor=factor), self.assertRaises(ip.ImageProcessingError):
                ip.adjust_brightness(self.image, factor)

    def test_apply_adjustments_identity_returns_same_image(self) -> None:
        self.assertIs(ip.apply_adjustments(self.image, Adjustments()), self.image)

    def test_apply_adjustments_does_not_modify_input(self) -> None:
        before = self.image.getpixel((0, 0))
        ip.apply_adjustments(self.image, Adjustments(brightness=1.5, contrast=1.3, saturation=0.5, grayscale=True))
        self.assertEqual(self.image.getpixel((0, 0)), before)


class CanvasTests(unittest.TestCase):
    def test_create_canvas_backgrounds(self) -> None:
        self.assertEqual(ip.create_canvas(20, 30, "white").getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(ip.create_canvas(20, 30, "transparent").getpixel((0, 0))[3], 0)
        self.assertEqual(ip.create_canvas(120, 80, "gradient").size, (120, 80))
        with self.assertRaises(ip.ImageProcessingError):
            ip.create_canvas(20, 20, "plaid")


if __name__ == "__main__":
    unittest.main()
