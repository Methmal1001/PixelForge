"""Tests for the advanced editing tools: adjustments, filters, free rotation and text effects."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image  # noqa: E402

from models.design import Adjustments, TextElement  # noqa: E402
from models.filters import FILTER_PRESETS, filter_adjustments  # noqa: E402
from services import image_processor as ip  # noqa: E402
from services.design_document import DesignDocument  # noqa: E402
from services.export_service import compose_design  # noqa: E402
from services.text_renderer import TextLayout, ensure_gui_application  # noqa: E402


def setUpModule() -> None:  # noqa: N802
    ensure_gui_application()


def mean(image: Image.Image, channel: int | None = None) -> float:
    data = image.convert("RGB").tobytes()
    if channel is None:
        return sum(data) / len(data)
    values = data[channel::3]
    return sum(values) / len(values)


class AdjustmentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.gradient = Image.linear_gradient("L").resize((64, 64)).convert("RGB")
        self.colour = Image.new("RGB", (40, 40), (180, 90, 60))

    def test_shadows_and_highlights(self) -> None:
        lifted = ip.adjust_tone(self.gradient, shadows=80)
        self.assertGreater(lifted.getpixel((5, 16))[0], self.gradient.getpixel((5, 16))[0])
        self.assertEqual(ip.adjust_tone(Image.new("RGB", (4, 4), "black"), shadows=80).getpixel((0, 0)), (0, 0, 0),
                         "pure black is kept")
        darker = ip.adjust_tone(self.gradient, highlights=-80)
        self.assertLess(darker.getpixel((5, 44))[0], self.gradient.getpixel((5, 44))[0])

    def test_warmth_tint_and_hue(self) -> None:
        warm = ip.adjust_white_balance(self.colour, warmth=80)
        self.assertGreater(mean(warm, 0), mean(self.colour, 0))
        self.assertLess(mean(warm, 2), mean(self.colour, 2))
        magenta = ip.adjust_white_balance(self.colour, tint=80)
        self.assertLess(mean(magenta, 1), mean(self.colour, 1))
        shifted = ip.shift_hue(self.colour, 120)
        self.assertNotEqual(shifted.getpixel((0, 0)), self.colour.getpixel((0, 0)))
        self.assertGreater(shifted.getpixel((0, 0))[1], shifted.getpixel((0, 0))[0], "red shifts towards green")

    def test_blur_vignette_sepia_invert_sharpness(self) -> None:
        checker = Image.new("RGB", (64, 64), "white")
        for x in range(0, 64, 2):
            for y in range(64):
                checker.putpixel((x, y), (0, 0, 0))
        self.assertNotEqual(ip.apply_blur(checker, 60).getpixel((10, 10)), checker.getpixel((10, 10)))
        white = Image.new("RGB", (80, 80), "white")
        vignetted = ip.apply_vignette(white, 100)
        self.assertLess(vignetted.getpixel((0, 0))[0], 120)
        self.assertGreater(vignetted.getpixel((40, 40))[0], 240)
        r, g, b = ip.to_sepia(self.colour).getpixel((0, 0))
        self.assertTrue(r > g > b, "sepia is warm brown")
        self.assertEqual(ip.invert_colors(self.colour).getpixel((0, 0)), (75, 165, 195))
        self.assertEqual(ip.adjust_sharpness(self.colour, 2.0).size, self.colour.size)

    def test_adjustments_keep_alpha_and_input(self) -> None:
        image = Image.new("RGBA", (30, 30), (120, 60, 200, 90))
        before = image.tobytes()
        result = ip.apply_adjustments(image, Adjustments(warmth=50, hue=40, shadows=30, vignette=50, sepia=True,
                                                         blur=10, sharpness=1.5))
        self.assertEqual(result.mode, "RGBA")
        self.assertEqual(result.getpixel((15, 15))[3], 90)
        self.assertEqual(image.tobytes(), before)

    def test_invalid_amounts_raise(self) -> None:
        with self.assertRaises(ip.ImageProcessingError):
            ip.shift_hue(self.colour, "lots")
        with self.assertRaises(ip.ImageProcessingError):
            ip.adjust_sharpness(self.colour, 9)

    def test_filters(self) -> None:
        self.assertTrue(filter_adjustments("none").is_identity())
        for key in FILTER_PRESETS:
            with self.subTest(filter=key):
                values = filter_adjustments(key)
                self.assertEqual(values.filter_name, key)
                self.assertEqual(ip.apply_adjustments(self.colour, values).size, self.colour.size)
        mono = ip.apply_adjustments(self.colour, filter_adjustments("mono")).getpixel((5, 5))
        self.assertTrue(mono[0] == mono[1] == mono[2])

    def test_free_rotation_expands_canvas(self) -> None:
        rotated = ip.rotate_free(Image.new("RGB", (100, 50), "red"), 30)
        self.assertEqual(rotated.mode, "RGBA")
        self.assertGreater(rotated.width, 100)
        self.assertEqual(rotated.getpixel((0, 0))[3], 0, "new corners are transparent")
        self.assertEqual(ip.rotate_free(Image.new("RGB", (10, 10)), 0).size, (10, 10))
        with self.assertRaises(ip.ImageProcessingError):
            ip.rotate_free(Image.new("RGB", (10, 10)), 999)


class TextEffectTests(unittest.TestCase):
    def setUp(self) -> None:
        self.base = Image.new("RGB", (400, 200), (255, 255, 255))

    def _count(self, image, colour, tolerance=40):
        data = image.convert("RGB").tobytes()
        return sum(1 for i in range(0, len(data), 3)
                   if all(abs(data[i + k] - colour[k]) <= tolerance for k in range(3)))

    def test_background_shadow_and_outline_render_in_export(self) -> None:
        plain = TextElement("SALE", x=40, y=40, font_size=60, color="#FFFFFF")
        self.assertEqual(self._count(compose_design(self.base, [plain]), (124, 92, 255)), 0)

        boxed = TextElement("SALE", x=40, y=40, font_size=60, color="#FFFFFF", background=True,
                            background_color="#7C5CFF")
        self.assertGreater(self._count(compose_design(self.base, [boxed]), (124, 92, 255)), 2000)

        outlined = TextElement("SALE", x=40, y=40, font_size=60, color="#FFFFFF", outline=True,
                               outline_color="#FF0000", outline_width=8)
        self.assertGreater(self._count(compose_design(self.base, [outlined]), (255, 0, 0)), 300)

        shadowed = TextElement("SALE", x=40, y=40, font_size=60, color="#FFFFFF", shadow=True,
                               shadow_color="#000000", shadow_opacity=1.0, shadow_blur=0, shadow_distance=10)
        self.assertGreater(self._count(compose_design(self.base, [shadowed]), (0, 0, 0)), 300)

    def test_layout_geometry_includes_effects(self) -> None:
        element = TextElement("Hello", font_size=50)
        plain = TextLayout(element).bounding_rect()
        element.background = True
        element.shadow = True
        effected = TextLayout(element).bounding_rect()
        self.assertGreater(effected.width(), plain.width())
        self.assertGreater(effected.height(), plain.height())

    def test_typography_changes_layout(self) -> None:
        normal = TextLayout(TextElement("Hello\nWorld", font_size=40))
        spaced = TextLayout(TextElement("Hello\nWorld", font_size=40, letter_spacing=40, line_height=2.0))
        upper = TextLayout(TextElement("hello", font_size=40, uppercase=True))
        lower = TextLayout(TextElement("hello", font_size=40))
        self.assertGreater(spaced.width, normal.width)
        self.assertGreater(spaced.height, normal.height)
        # Headless test fonts give every glyph the same width, so check the laid-out text itself.
        self.assertEqual(upper.document.toPlainText(), "HELLO")
        self.assertEqual(lower.document.toPlainText(), "hello")

    def test_rotation_and_opacity(self) -> None:
        dark = Image.new("RGB", (300, 300), (0, 0, 0))
        straight = compose_design(dark, [TextElement("IIIIIIIII", x=40, y=120, font_size=50)])
        rotated = compose_design(dark, [TextElement("IIIIIIIII", x=40, y=120, font_size=50, rotation=90)])
        self.assertNotEqual(straight.tobytes(), rotated.tobytes())
        faint = compose_design(dark, [TextElement("IIIIIIIII", x=40, y=120, font_size=50, opacity=0.3)])
        self.assertLess(mean(faint), mean(straight))


class DocumentToolTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = DesignDocument(Image.new("RGB", (200, 100), "white"))

    def test_duplicate_and_layer_order(self) -> None:
        first = self.doc.add_text(TextElement("A", x=10, y=10))
        second = self.doc.add_text(TextElement("B"))
        copy = self.doc.duplicate_text(first.id)
        self.assertNotEqual(copy.id, first.id)
        self.assertEqual((copy.text, copy.x), ("A", first.x + 24))
        self.assertEqual([t.text for t in self.doc.state.texts], ["A", "B", "A"])
        self.assertTrue(self.doc.move_text_layer(first.id, +1))
        self.assertEqual(self.doc.state.texts[1].id, first.id)
        self.assertFalse(self.doc.move_text_layer(copy.id, +1), "already on top")
        self.doc.undo()
        self.assertEqual(self.doc.state.texts[0].id, first.id)
        self.assertIsNotNone(second)

    def test_rotate_angle_keeps_text_position_relative(self) -> None:
        text = self.doc.add_text(TextElement("A", x=50, y=40, font_size=10))
        self.doc.rotate_angle(15)
        self.assertGreater(self.doc.width, 200)
        moved = self.doc.get_text(text.id)
        self.assertAlmostEqual(moved.x, 50 + (self.doc.width - 200) / 2, delta=1)
        self.doc.undo()
        self.assertEqual(self.doc.size, (200, 100))

    def test_text_value_ranges_are_validated(self) -> None:
        text = self.doc.add_text(TextElement("A"))
        with self.assertRaises(ValueError):
            self.doc.update_text(text.id, opacity=1.5)
        with self.assertRaises(ValueError):
            self.doc.update_text(text.id, line_height=10)
        self.doc.update_text(text.id, shadow=True, rotation=-45, letter_spacing=20)
        self.assertEqual(self.doc.get_text(text.id).rotation, -45)


if __name__ == "__main__":
    unittest.main()
