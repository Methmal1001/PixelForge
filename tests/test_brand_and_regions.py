"""Tests for brand details in prompts and for area (selection) editing."""

import unittest

from PIL import Image, ImageDraw

from models.brand import BrandDetails, BrandField, split_values
from models.design import Adjustments
from services import region_tools as rt
from services.design_document import DesignDocument
from services.generation_service import GenerationRequest, compose_prompt
from services.image_processor import ImageProcessingError


def brand(**overrides) -> BrandDetails:
    values = dict(company=BrandField("Colombo Mobile Hub", 86, "#FFFFFF"),
                  description=BrandField("Latest smartphones at the best prices", 40, "#F5B544"),
                  phones=BrandField("+94 77 123 4567, +94 11 234 5678", 30, "#FFFFFF"),
                  emails=BrandField("info@colombomobile.lk", 30, "#FFFFFF"))
    values.update(overrides)
    return BrandDetails(**values)


def request(brand_details=None) -> GenerationRequest:
    return GenerationRequest("A premium smartphone shop advertisement", "Advertisement", "Cinematic",
                             "1:1 · Square Post", brand=brand_details)


class BrandTests(unittest.TestCase):
    def test_empty_brand_adds_nothing(self) -> None:
        self.assertTrue(BrandDetails().is_empty)
        self.assertEqual(compose_prompt(request(BrandDetails())), compose_prompt(request(None)))

    def test_layers_mode_asks_for_clean_space_and_keeps_text_out_of_the_image(self) -> None:
        prompt = compose_prompt(request(brand(theme="ocean")))
        self.assertIn("Colombo Mobile Hub", prompt)
        self.assertIn("do NOT render any text", prompt)
        self.assertIn("#0B3D91", prompt, "colour theme palette is included")
        self.assertNotIn("+94 77", prompt, "contact text is added as layers, not sent to be drawn")

    def test_ai_mode_sends_exact_text_with_sizes_and_colours(self) -> None:
        prompt = compose_prompt(request(brand(text_mode="ai", theme="custom",
                                              custom_colors=("#112233", "#445566"))))
        self.assertIn("“Colombo Mobile Hub” — about 86px", prompt)
        self.assertIn("colour #F5B544", prompt)
        self.assertIn("+94 77 123 4567, +94 11 234 5678", prompt)
        self.assertIn("info@colombomobile.lk", prompt)
        self.assertIn("#112233, #445566", prompt)

    def test_validation(self) -> None:
        request(brand()).validate()
        with self.assertRaises(ValueError):
            request(brand(emails=BrandField("not-an-email"))).validate()
        with self.assertRaises(ValueError):
            request(brand(phones=BrandField("call me"))).validate()
        with self.assertRaises(ValueError):
            request(brand(company=BrandField("X", size=2))).validate()

    def test_round_trip_and_split(self) -> None:
        original = brand(theme="luxury", text_mode="ai")
        self.assertEqual(BrandDetails.from_dict(original.to_dict()), original)
        self.assertEqual(BrandDetails.from_dict({"theme": "nonsense"}).theme, "auto")
        self.assertEqual(split_values("a, b;c\nd"), ["a", "b", "c", "d"])


class RegionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.image = Image.new("RGB", (200, 100), (100, 100, 100))
        ImageDraw.Draw(self.image).rectangle((0, 0, 99, 99), fill=(30, 140, 220))

    def test_masks_for_each_shape(self) -> None:
        rect = rt.build_mask((200, 100), "rect", [(10, 10), (60, 50)], feather=0)
        self.assertEqual(rect.getbbox(), (10, 10, 60, 50))
        ellipse = rt.build_mask((200, 100), "ellipse", [(10, 10), (60, 50)], feather=0)
        self.assertEqual(ellipse.getpixel((11, 11)), 0, "ellipse corners are not selected")
        self.assertEqual(ellipse.getpixel((35, 30)), 255)
        lasso = rt.build_mask((200, 100), "lasso", [(20, 20), (80, 20), (50, 80)], feather=0)
        self.assertEqual(lasso.getpixel((50, 30)), 255)
        self.assertEqual(lasso.getpixel((22, 70)), 0)
        with self.assertRaises(ImageProcessingError):
            rt.build_mask((200, 100), "rect", [(5, 5), (6, 6)])
        with self.assertRaises(ImageProcessingError):
            rt.build_mask((200, 100), "star", [(5, 5), (60, 60)])

    def test_operations_change_only_the_selection(self) -> None:
        mask = rt.build_mask(self.image.size, "rect", [(20, 20), (80, 80)], feather=0)
        outside = self.image.getpixel((150, 50))
        brighter = rt.apply_region(self.image, mask, "adjust", adjustments=Adjustments(brightness=1.6))
        self.assertGreater(sum(brighter.getpixel((50, 50))), sum(self.image.getpixel((50, 50))))
        self.assertEqual(brighter.getpixel((150, 50)), outside)
        filled = rt.apply_region(self.image, mask, "fill", color="#FF0000")
        self.assertEqual(filled.getpixel((50, 50)), (255, 0, 0))
        self.assertEqual(filled.getpixel((5, 5)), self.image.getpixel((5, 5)))
        erased = rt.apply_region(self.image, mask, "erase")
        self.assertEqual(erased.getpixel((50, 50))[3], 0)
        self.assertEqual(erased.getpixel((150, 50))[3], 255)
        for operation in ("blur", "sharpen", "remove"):
            with self.subTest(operation=operation):
                result = rt.apply_region(self.image, mask, operation)
                self.assertEqual(result.getpixel((150, 50)), outside)

    def test_remove_fills_from_surroundings(self) -> None:
        scene = Image.new("RGB", (300, 200), (40, 160, 90))
        ImageDraw.Draw(scene).text((120, 90), "SALE", fill=(255, 255, 255))
        ImageDraw.Draw(scene).rectangle((110, 85, 190, 110), fill=(255, 255, 255))
        mask = rt.build_mask(scene.size, "rect", [(100, 75), (200, 120)])
        cleaned = rt.apply_region(scene, mask, "remove")
        r, g, b = cleaned.getpixel((150, 97))
        self.assertTrue(abs(r - 40) < 15 and abs(g - 160) < 15 and abs(b - 90) < 15, (r, g, b))

    def test_document_area_edit_and_undo(self) -> None:
        doc = DesignDocument(self.image)
        doc.edit_region("ellipse", [(10, 10), (90, 90)], "fill", color="#00FF00")
        self.assertEqual(doc.state.base.getpixel((50, 50)), (0, 255, 0))
        self.assertIs(doc.original, self.image)
        doc.undo()
        self.assertEqual(doc.state.base.getpixel((50, 50)), (30, 140, 220))
        doc.crop_to_selection([(10, 20), (110, 70)])
        self.assertEqual(doc.size, (100, 50))
        with self.assertRaises(ImageProcessingError):
            doc.edit_region("rect", [(10, 10), (60, 60)], "teleport")


if __name__ == "__main__":
    unittest.main()
