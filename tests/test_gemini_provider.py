"""Tests for the Gemini provider and .env config. Uses a fake transport: no network, no quota."""

import base64
import io
import json
import tempfile
import unittest
from pathlib import Path

from PIL import Image

from services import config
from services.gemini_provider import GeminiImageService
from services.generation_service import (
    GenerationAuthError,
    GenerationError,
    GenerationQuotaError,
    GenerationRequest,
    save_generation,
)


def png_b64(size=(64, 80), color=(200, 30, 90)) -> str:
    buffer = io.BytesIO()
    Image.new("RGB", size, color).save(buffer, "PNG")
    return base64.b64encode(buffer.getvalue()).decode()


class FakeTransport:
    def __init__(self, status: int, payload: dict) -> None:
        self.status, self.payload, self.calls = status, payload, []

    def __call__(self, method, url, headers, body, timeout):
        self.calls.append({"method": method, "url": url, "headers": headers,
                           "body": json.loads(body) if body else None})
        return self.status, json.dumps(self.payload).encode()


def request(**overrides) -> GenerationRequest:
    values = dict(prompt="A premium smartphone advertisement with blue lighting",
                  design_type="Advertisement", art_style="Cinematic", aspect_ratio="4:5 · Portrait Post")
    values.update(overrides)
    return GenerationRequest(**values)


class GeminiProviderTests(unittest.TestCase):
    def test_successful_generation_returns_image_and_sends_correct_request(self) -> None:
        transport = FakeTransport(200, {"candidates": [{"content": {"parts": [
            {"text": "Here is your design"}, {"inlineData": {"mimeType": "image/png", "data": png_b64()}}]}}]})
        service = GeminiImageService("test-key", "gemini-3.1-flash-image", transport=transport)
        image = service.generate(request())
        self.assertEqual(image.size, (64, 80))
        call = transport.calls[0]
        self.assertEqual(call["method"], "POST")
        self.assertTrue(call["url"].endswith("/models/gemini-3.1-flash-image:generateContent"))
        self.assertEqual(call["headers"]["x-goog-api-key"], "test-key")
        self.assertNotIn("test-key", call["url"], "the key must not be placed in the URL")
        config_body = call["body"]["generationConfig"]
        self.assertEqual(config_body["imageConfig"]["aspectRatio"], "4:5")
        self.assertIn("IMAGE", config_body["responseModalities"])
        prompt = call["body"]["contents"][0]["parts"][0]["text"]
        self.assertIn("smartphone", prompt)
        self.assertIn("advertisement", prompt)

    def test_reference_image_is_attached(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            ref = Path(tmp) / "ref.jpg"
            Image.new("RGB", (3000, 2000), (10, 20, 30)).save(ref)
            transport = FakeTransport(200, {"candidates": [{"content": {"parts": [
                {"inlineData": {"mimeType": "image/png", "data": png_b64()}}]}}]})
            GeminiImageService("k", transport=transport).generate(request(reference_image=ref))
        parts = transport.calls[0]["body"]["contents"][0]["parts"]
        inline = parts[1]["inline_data"]
        self.assertEqual(inline["mime_type"], "image/jpeg")
        with Image.open(io.BytesIO(base64.b64decode(inline["data"]))) as sent:
            self.assertLessEqual(max(sent.size), 1536, "reference images are downscaled before upload")
        self.assertIn("reference image", parts[0]["text"])

    def test_free_tier_without_image_quota_gives_clear_message(self) -> None:
        payload = {"error": {"code": 429, "status": "RESOURCE_EXHAUSTED", "message":
                   "You exceeded your current quota.\n* Quota exceeded for metric: "
                   "generate_content_free_tier_requests, limit: 0, model: gemini-2.5-flash-preview-image"}}
        service = GeminiImageService("k", transport=FakeTransport(429, payload))
        with self.assertRaises(GenerationQuotaError) as ctx:
            service.generate(request())
        self.assertIn("billing", str(ctx.exception))

    def test_rate_limit_reports_retry_time(self) -> None:
        payload = {"error": {"code": 429, "message": "Rate limited. Please retry in 37.2s."}}
        with self.assertRaises(GenerationQuotaError) as ctx:
            GeminiImageService("k", transport=FakeTransport(429, payload)).generate(request())
        self.assertIn("37.2s", str(ctx.exception))

    def test_invalid_key_and_missing_model(self) -> None:
        bad_key = {"error": {"code": 400, "message": "API key not valid. Please pass a valid API key.",
                             "details": [{"reason": "API_KEY_INVALID"}]}}
        with self.assertRaises(GenerationAuthError):
            GeminiImageService("bad", transport=FakeTransport(400, bad_key)).generate(request())
        with self.assertRaises(GenerationError) as ctx:
            GeminiImageService("k", "nope", transport=FakeTransport(404, {"error": {"message": "not found"}})
                               ).generate(request())
        self.assertIn("nope", str(ctx.exception))
        with self.assertRaises(GenerationAuthError):
            GeminiImageService("", transport=FakeTransport(200, {})).generate(request())

    def test_blocked_or_text_only_responses(self) -> None:
        blocked = {"promptFeedback": {"blockReason": "SAFETY"}}
        with self.assertRaises(GenerationError) as ctx:
            GeminiImageService("k", transport=FakeTransport(200, blocked)).generate(request())
        self.assertIn("SAFETY", str(ctx.exception))
        text_only = {"candidates": [{"finishReason": "STOP", "content": {"parts": [{"text": "I cannot draw that"}]}}]}
        with self.assertRaises(GenerationError) as ctx:
            GeminiImageService("k", transport=FakeTransport(200, text_only)).generate(request())
        self.assertIn("I cannot draw that", str(ctx.exception))

    def test_invalid_prompt_is_rejected_before_any_request(self) -> None:
        transport = FakeTransport(200, {})
        with self.assertRaises(ValueError):
            GeminiImageService("k", transport=transport).generate(request(prompt="hi"))
        self.assertEqual(transport.calls, [])

    def test_list_image_models(self) -> None:
        payload = {"models": [
            {"name": "models/gemini-3.1-flash-image", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.8", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/imagen-x-image", "supportedGenerationMethods": ["predict"]}]}
        models = GeminiImageService("k", transport=FakeTransport(200, payload)).list_image_models()
        self.assertEqual(models, ["gemini-3.1-flash-image"])


class ConfigAndStorageTests(unittest.TestCase):
    def test_env_round_trip_preserves_other_lines(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            env = Path(tmp) / ".env"
            env.write_text("# comment\nOTHER=1\nGEMINI_API_KEY='old'\n", encoding="utf-8")
            self.assertEqual(config.read_env(env)["GEMINI_API_KEY"], "old")
            config.update_env({"GEMINI_API_KEY": "new", "GEMINI_IMAGE_MODEL": "m"}, env)
            values = config.read_env(env)
            self.assertEqual((values["GEMINI_API_KEY"], values["GEMINI_IMAGE_MODEL"], values["OTHER"]),
                             ("new", "m", "1"))
            self.assertIn("# comment", env.read_text(encoding="utf-8"))
            config.update_env({"GEMINI_API_KEY": None}, env)
            self.assertNotIn("GEMINI_API_KEY", config.read_env(env))

    def test_mask_secret_hides_the_key(self) -> None:
        masked = config.mask_secret("AQ.abcdefghijklmnop1234")
        self.assertTrue(masked.startswith("AQ.abc") and masked.endswith("1234"))
        self.assertNotIn("ghijklmnop", masked)

    def test_save_generation_writes_png_and_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = save_generation(Image.new("RGB", (40, 50)), request(), "gemini-x", Path(tmp))
            self.assertTrue(path.exists())
            meta = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertEqual((meta["model"], meta["width"], meta["height"]), ("gemini-x", 40, 50))
            self.assertIn("smartphone", meta["prompt"])


if __name__ == "__main__":
    unittest.main()
