"""Tests for DesignDocument: undo/redo, original preservation and text layers."""

import unittest
from unittest import mock

from PIL import Image

from models.design import Adjustments, TextElement
from services.design_document import DesignDocument
from services.gemini_provider import GeminiImageService
from services.generation_service import (
    GenerationNotConfiguredError,
    GenerationRequest,
    NotConfiguredGenerationService,
    get_generation_service,
)
from services.image_processor import ImageProcessingError


class DesignDocumentTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original = Image.new("RGB", (100, 50), (10, 120, 200))
        self.doc = DesignDocument(self.original, name="test")

    def test_edits_never_modify_original(self) -> None:
        before = self.original.tobytes()
        self.doc.rotate_left()
        self.doc.crop(0, 0, 20, 20)
        self.doc.resize(40, 40)
        self.doc.set_adjustments(Adjustments(brightness=1.5, grayscale=True), record=True)
        self.doc.rendered()
        self.assertEqual(self.original.tobytes(), before)
        self.assertIs(self.doc.original, self.original)

    def test_reset_image_restores_original(self) -> None:
        self.doc.flip_horizontal()
        self.doc.resize(30, 30)
        self.doc.set_adjustments(Adjustments(contrast=2.0), record=True)
        self.doc.reset_image()
        self.assertIs(self.doc.state.base, self.original)
        self.assertTrue(self.doc.state.adjustments.is_identity())
        self.assertEqual(self.doc.rendered().getpixel((0, 0)), (10, 120, 200))

    def test_adjustments_are_applied_from_base_not_accumulated(self) -> None:
        self.doc.set_adjustments(Adjustments(brightness=0.2))
        self.doc.set_adjustments(Adjustments(brightness=1.0))
        self.assertEqual(self.doc.rendered().getpixel((0, 0)), (10, 120, 200))

    def test_undo_redo(self) -> None:
        self.doc.rotate_right()
        self.assertEqual(self.doc.size, (50, 100))
        self.doc.resize(25, 50)
        self.assertTrue(self.doc.undo())
        self.assertEqual(self.doc.size, (50, 100))
        self.assertTrue(self.doc.undo())
        self.assertEqual(self.doc.size, (100, 50))
        self.assertFalse(self.doc.undo())
        self.assertTrue(self.doc.redo())
        self.assertEqual(self.doc.size, (50, 100))
        self.doc.flip_vertical()
        self.assertFalse(self.doc.can_redo, "a new edit clears the redo stack")

    def test_text_add_update_move_delete_with_undo(self) -> None:
        text = self.doc.add_text(TextElement("Hello", x=5, y=5, font_size=12))
        self.doc.update_text(text.id, record=True, text="World", color="#FF0000")
        self.assertEqual(self.doc.get_text(text.id).text, "World")
        self.doc.move_texts({text.id: (30, 20)})
        self.assertEqual((self.doc.get_text(text.id).x, self.doc.get_text(text.id).y), (30, 20))
        self.doc.remove_text(text.id)
        self.assertIsNone(self.doc.get_text(text.id))
        self.doc.undo()
        self.assertEqual(self.doc.get_text(text.id).x, 30)
        self.doc.undo()
        self.assertEqual(self.doc.get_text(text.id).x, 5)
        self.doc.undo()
        self.assertEqual(self.doc.get_text(text.id).text, "Hello")

    def test_update_text_validates(self) -> None:
        text = self.doc.add_text(TextElement("Hi"))
        with self.assertRaises(ValueError):
            self.doc.update_text(text.id, font_size=0)
        with self.assertRaises(ValueError):
            self.doc.update_text(text.id, align="justify")
        with self.assertRaises(ValueError):
            self.doc.update_text(text.id, glow_strength=0.5)

    def test_crop_shifts_text_and_resize_scales_it(self) -> None:
        text = self.doc.add_text(TextElement("A", x=60, y=30, font_size=10))
        self.doc.crop(50, 20, 50, 30)
        moved = self.doc.get_text(text.id)
        self.assertAlmostEqual(moved.x, 10, delta=0.01)
        self.assertAlmostEqual(moved.y, 10, delta=0.01)
        self.doc.resize(100, 60)
        scaled = self.doc.get_text(text.id)
        self.assertEqual(scaled.font_size, 20)

    def test_invalid_operations_leave_document_unchanged(self) -> None:
        with self.assertRaises(ImageProcessingError):
            self.doc.resize(0, 10)
        with self.assertRaises(ImageProcessingError):
            self.doc.crop(90, 0, 50, 10)
        self.assertEqual(self.doc.size, (100, 50))
        self.assertFalse(self.doc.can_undo, "failed edits must not create undo entries")

    def test_blank_document(self) -> None:
        doc = DesignDocument.blank(1080, 1350, "white")
        self.assertEqual(doc.size, (1080, 1350))
        with self.assertRaises(ImageProcessingError):
            DesignDocument.blank(0, 100)


class GenerationServiceTests(unittest.TestCase):
    def test_without_key_provider_is_not_configured_and_sends_nothing(self) -> None:
        service = NotConfiguredGenerationService()
        self.assertFalse(service.is_configured)
        request = GenerationRequest("A premium smartphone advertisement", "Advertisement", "Cinematic", "1:1")
        request.validate()
        with self.assertRaises(GenerationNotConfiguredError) as ctx:
            service.generate(request)
        self.assertIn("API key", str(ctx.exception))

    def test_provider_selection_follows_api_key(self) -> None:
        with mock.patch("services.config.get_setting", return_value=None):
            self.assertIsInstance(get_generation_service(), NotConfiguredGenerationService)
        settings = {"GEMINI_API_KEY": "test-key", "GEMINI_IMAGE_MODEL": "gemini-3.1-flash-lite-image"}
        with mock.patch("services.config.get_setting", side_effect=lambda name, *a, **k: settings.get(name)):
            service = get_generation_service()
        self.assertIsInstance(service, GeminiImageService)
        self.assertTrue(service.is_configured)
        self.assertEqual(service.model, "gemini-3.1-flash-lite-image")

    def test_request_validation(self) -> None:
        for prompt in ("", "   ", "short", "x" * 2001):
            with self.subTest(prompt=prompt[:10]), self.assertRaises(ValueError):
                GenerationRequest(prompt, "Advertisement", "Cinematic", "1:1").validate()


if __name__ == "__main__":
    unittest.main()
