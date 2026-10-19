"""Tests for the Pollinations provider. Uses a fake transport: no network."""

import io
import json
import unittest
import urllib.parse
from unittest import mock

from PIL import Image

from services.generation_service import (
    GenerationError,
    GenerationQuotaError,
    GenerationRequest,
    get_generation_service,
)
from services.pollinations_provider import PollinationsImageService


def jpeg_bytes(size=(686, 858)) -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", size, (120, 80, 40)).save(buffer, "JPEG")
    return buffer.getvalue()


class FakeGet:
    def __init__(self, status, content_type, body) -> None:
        self.response, self.urls = (status, content_type, body), []

    def __call__(self, url, timeout):
        self.urls.append(url)
        return self.response


def request(**overrides) -> GenerationRequest:
    values = dict(prompt="A cozy coffee shop post with a steaming latte", design_type="Social Media Post",
                  art_style="Photorealistic", aspect_ratio="4:5 · Portrait Post")
    values.update(overrides)
    return GenerationRequest(**values)


class PollinationsTests(unittest.TestCase):
    def test_generate_returns_image_and_builds_private_url(self) -> None:
        fake = FakeGet(200, "image/jpeg", jpeg_bytes())
        image = PollinationsImageService(transport=fake).generate(request())
        self.assertEqual(image.size, (686, 858))
        parsed = urllib.parse.urlparse(fake.urls[0])
        query = urllib.parse.parse_qs(parsed.query)
        self.assertEqual((query["width"], query["height"]), (["1080"], ["1350"]))
        self.assertEqual(query["private"], ["true"])
        self.assertEqual(query["safe"], ["true"])
        prompt = urllib.parse.unquote(parsed.path.removeprefix("/prompt/"))
        self.assertIn("latte", prompt)
        self.assertNotIn("\n", prompt)

    def test_nothing_secret_is_sent(self) -> None:
        fake = FakeGet(200, "image/jpeg", jpeg_bytes())
        with mock.patch.dict("os.environ", {"GEMINI_API_KEY": "SECRET-KEY-123"}):
            PollinationsImageService(transport=fake).generate(request(reference_image="C:/private/photo.png"))
        self.assertNotIn("SECRET-KEY-123", fake.urls[0])
        self.assertNotIn("photo.png", urllib.parse.unquote(fake.urls[0]))

    def test_free_limit_reports_wait_time(self) -> None:
        body = json.dumps({"status": 402, "error": {"code": "FREE_LIMIT",
                           "message": "Free limit reached: 1 image every 45 seconds per IP. Retry after 23s"}})
        with self.assertRaises(GenerationQuotaError) as ctx:
            PollinationsImageService(transport=FakeGet(402, "application/json", body.encode())).generate(request())
        self.assertIn("23 seconds", str(ctx.exception))

    def test_non_image_and_server_errors(self) -> None:
        with self.assertRaises(GenerationError):
            PollinationsImageService(transport=FakeGet(200, "text/html", b"<html>")).generate(request())
        with self.assertRaises(GenerationError) as ctx:
            PollinationsImageService(transport=FakeGet(503, "text/plain", b"busy")).generate(request())
        self.assertIn("temporary", str(ctx.exception))
        with self.assertRaises(GenerationError):
            PollinationsImageService(transport=FakeGet(200, "image/jpeg", b"not an image")).generate(request())

    def test_invalid_prompt_sends_nothing(self) -> None:
        fake = FakeGet(200, "image/jpeg", jpeg_bytes())
        with self.assertRaises(ValueError):
            PollinationsImageService(transport=fake).generate(request(prompt="hey"))
        self.assertEqual(fake.urls, [])

    def test_check_connection_lists_models(self) -> None:
        fake = FakeGet(200, "application/json", b'["sana"]')
        self.assertEqual(PollinationsImageService(transport=fake).check_connection(), ["sana"])

    def test_selected_by_ai_provider_setting(self) -> None:
        settings = {"AI_PROVIDER": "pollinations"}
        with mock.patch("services.config.get_setting", side_effect=lambda name, *a, **k: settings.get(name)):
            service = get_generation_service()
        self.assertIsInstance(service, PollinationsImageService)
        self.assertTrue(service.is_configured)
        self.assertFalse(service.supports_reference)


if __name__ == "__main__":
    unittest.main()
