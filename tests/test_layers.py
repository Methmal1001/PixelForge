"""Tests for image layers (Layer via Copy/Cut), the magic wand and layer export."""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PIL import Image, ImageChops, ImageDraw  # noqa: E402

from models.design import ImageLayer  # noqa: E402
from services import region_tools as rt  # noqa: E402
from services.design_document import DesignDocument  # noqa: E402
from services.export_service import compose_design  # noqa: E402
from services.image_processor import ImageProcessingError  # noqa: E402
from services.text_renderer import ensure_gui_application  # noqa: E402


def setUpModule() -> None:  # noqa: N802
    ensure_gui_application()


def scene() -> Image.Image:
    """Grey background with a blue 'phone' and a separate blue square far away."""
    image = Image.new("RGB", (300, 200), (200, 200, 200))
    draw = ImageDraw.Draw(image)
    draw.rectangle((40, 40, 99, 159), fill=(20, 60, 200))     # object A
    draw.rectangle((220, 20, 259, 59), fill=(20, 60, 200))    # object B, same colour, not connected
    return image


class MagicWandTests(unittest.TestCase):
    def test_selects_only_the_connected_object(self) -> None:
        mask = rt.magic_wand(scene(), (70, 100), tolerance=30)
        self.assertGreater(mask.getpixel((70, 100)), 200)
        self.assertLess(mask.getpixel((240, 40)), 50, "same colour elsewhere is not selected")
        self.assertLess(mask.getpixel((150, 100)), 50, "background is not selected")
        box = rt.mask_bbox(mask)
        self.assertTrue(abs(box[0] - 40) <= 2 and abs(box[2] - 100) <= 2, box)

    def test_tolerance_and_errors(self) -> None:
        image = Image.linear_gradient("L").resize((100, 100)).convert("RGB")
        narrow = rt.magic_wand(image, (50, 50), tolerance=2)
        wide = rt.magic_wand(image, (50, 50), tolerance=80)
        self.assertGreater(rt.mask_bbox(wide)[3] - rt.mask_bbox(wide)[1],
                           rt.mask_bbox(narrow)[3] - rt.mask_bbox(narrow)[1])
        with self.assertRaises(ImageProcessingError):
            rt.magic_wand(image, (500, 5))


class LayerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.doc = DesignDocument(scene())

    def test_copy_to_layer_keeps_background(self) -> None:
        layer = self.doc.copy_to_layer("rect", [(40, 40), (100, 160)])
        # the soft (feathered) selection edge adds a few transparent pixels around the object
        self.assertTrue(36 <= layer.x <= 40 and 36 <= layer.y <= 40, (layer.x, layer.y))
        self.assertEqual(layer.image.mode, "RGBA")
        self.assertEqual(layer.image.getpixel((int(70 - layer.x), int(100 - layer.y)))[:3], (20, 60, 200))
        self.assertEqual(self.doc.state.base.getpixel((70, 100)), (20, 60, 200), "copy leaves the original")

    def test_cut_to_layer_fills_the_hole(self) -> None:
        mask = rt.magic_wand(self.doc.rendered(), (70, 100), tolerance=30)
        layer = self.doc.cut_to_layer("mask", mask)
        r, g, b = self.doc.state.base.getpixel((70, 100))
        self.assertTrue(abs(r - 200) < 25 and abs(b - 200) < 25, "hole filled from the grey surroundings")
        self.assertEqual(layer.image.getpixel((5, 5))[3], 255)
        self.doc.undo()
        self.assertEqual(self.doc.state.base.getpixel((70, 100)), (20, 60, 200))
        self.assertEqual(self.doc.state.layers, [])

    def test_move_resize_rotate_order_merge_delete(self) -> None:
        first = self.doc.copy_to_layer("rect", [(40, 40), (100, 160)])
        second = self.doc.copy_to_layer("rect", [(220, 20), (260, 60)])
        self.doc.move_layers({first.id: {"x": 150.0, "y": 10.0, "scale": 0.5}})
        moved = self.doc.get_layer(first.id)
        self.assertEqual((moved.x, moved.y, moved.scale), (150.0, 10.0, 0.5))
        self.doc.update_layer(first.id, record=True, rotation=30, opacity=0.5)
        with self.assertRaises(ValueError):
            self.doc.update_layer(first.id, opacity=3)
        self.assertTrue(self.doc.move_layer_order(first.id, +1))
        self.assertEqual(self.doc.state.layers[-1].id, first.id)
        copy = self.doc.duplicate_layer(second.id)
        self.assertEqual(len(self.doc.state.layers), 3)
        self.doc.remove_layer(copy.id)
        self.doc.merge_layer(second.id)
        self.assertEqual([layer.id for layer in self.doc.state.layers], [first.id])
        for _ in range(6):
            self.doc.undo()
        self.assertEqual(len(self.doc.state.layers), 2)

    def test_crop_moves_layers_with_the_image(self) -> None:
        layer = self.doc.copy_to_layer("rect", [(40, 40), (100, 160)])
        before = layer.x
        self.doc.crop(20, 20, 200, 150)
        self.assertAlmostEqual(self.doc.get_layer(layer.id).x, before - 20, delta=0.5)

    def test_layers_are_exported_between_background_and_text(self) -> None:
        white = Image.new("RGB", (200, 200), "white")
        red = Image.new("RGBA", (50, 50), (255, 0, 0, 255))
        layer = ImageLayer(image=red, x=100, y=100, scale=2.0)  # scaled around its centre → 75..175
        composed = compose_design(white, [], [layer])
        self.assertEqual(composed.getpixel((80, 80))[:3], (255, 0, 0))
        self.assertEqual(composed.getpixel((60, 60))[:3], (255, 255, 255))
        faded = compose_design(white, [], [ImageLayer(image=red, x=0, y=0, opacity=0.5)])
        r, g, b = faded.getpixel((25, 25))[:3]
        self.assertEqual(r, 255)
        self.assertTrue(110 < g < 145, g)

    def test_merge_matches_export(self) -> None:
        layer = self.doc.copy_to_layer("rect", [(40, 40), (100, 160)])
        self.doc.update_layer(layer.id, x=150.0, rotation=15)
        exported = compose_design(self.doc.rendered(), [], self.doc.state.layers).convert("RGB")
        self.doc.merge_layer(layer.id)
        diff = ImageChops.difference(exported, self.doc.state.base.convert("RGB")).getbbox()
        self.assertIsNone(diff, "merging gives exactly what export showed")


if __name__ == "__main__":
    unittest.main()
