"""Pollinations.ai image provider: free, anonymous, no API key.

GET https://image.pollinations.ai/prompt/{prompt}?width=..&height=..

Privacy: only the prompt text and image size are sent to a public third-party
service (requests ask for private mode, which Pollinations honours on its side).
No API key, account or local file is ever sent. Reference images are not
supported because the service only accepts public image URLs.

Free-tier behaviour (verified October 2026): one image every 45 seconds per IP,
outputs capped at roughly 0.6 megapixels, and a small "pollinations.ai"
watermark in the corner.
"""

from __future__ import annotations

import io
import json
import random
import re
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable

from PIL import Image, UnidentifiedImageError

from models.presets import find_preset
from services.generation_service import (
    GenerationError,
    GenerationQuotaError,
    GenerationRequest,
    ImageGenerationService,
    compose_prompt,
)
from services.image_processor import normalize_mode

API_BASE = "https://image.pollinations.ai"
DEFAULT_MODEL = "sana"
MAX_PROMPT_CHARS = 1500
USER_AGENT = "PixelForgeAIStudio/0.2"

# (url, timeout) -> (status_code, content_type, body)
Transport = Callable[[str, float], tuple[int, str, bytes]]


def urllib_get(url: str, timeout: float) -> tuple[int, str, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.headers.get("Content-Type", ""), response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.headers.get("Content-Type", "") if exc.headers else "", exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise GenerationError(
            f"Could not reach Pollinations.ai ({reason}). Check your internet connection and try again."
        ) from exc


class PollinationsImageService(ImageGenerationService):
    name = "Pollinations.ai (free)"
    short_name = "Pollinations"
    supports_reference = False

    def __init__(self, model: str = DEFAULT_MODEL, *, transport: Transport | None = None,
                 timeout: float = 150.0) -> None:
        self.model = model
        self._transport = transport or urllib_get
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        return True  # no key needed

    def ready_detail(self) -> str:
        return ("Free, no API key. Sends only your prompt and size to the provider. One image every 45 s; "
                "reference images are not sent.")

    def build_url(self, request: GenerationRequest, seed: int | None = None) -> str:
        preset = find_preset(request.preset_key)
        width, height = (preset.width, preset.height) if preset else (1080, 1080)
        prompt = compose_prompt(request).replace("\n", " ").strip()[:MAX_PROMPT_CHARS]
        query = urllib.parse.urlencode({
            "width": width,
            "height": height,
            "seed": seed if seed is not None else random.randint(1, 2_000_000_000),
            "model": self.model,
            "nologo": "true",
            "private": "true",
            "safe": "true",
        })
        return f"{API_BASE}/prompt/{urllib.parse.quote(prompt, safe='')}?{query}"

    def generate(self, request: GenerationRequest) -> Image.Image:
        request.validate()
        cancel = self.begin_generation()
        status, content_type, body = self._transport(self.build_url(request), self._timeout)
        self.raise_if_cancelled(cancel)  # a single HTTP request cannot be interrupted; discard late results
        if status == 200 and content_type.startswith("image/"):
            try:
                with Image.open(io.BytesIO(body)) as image:
                    image.load()
                    return normalize_mode(image)
            except (UnidentifiedImageError, OSError, ValueError) as exc:
                raise GenerationError("Pollinations returned image data that could not be decoded.") from exc
        raise self._error_for(status, body)

    @staticmethod
    def _error_for(status: int, body: bytes) -> GenerationError:
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = str(error.get("message", "") if isinstance(error, dict) else error).strip()
        if status in (402, 429):
            wait = re.search(r"Retry after (\d+)s", message)
            when = f"Try again in {wait.group(1)} seconds." if wait else "Try again in about a minute."
            return GenerationQuotaError(
                f"Pollinations' free limit is one image every 45 seconds per connection. {when}")
        if status == 200:
            return GenerationError("Pollinations did not return an image. Try rephrasing the prompt.")
        if status in (400, 422):
            return GenerationError(f"Pollinations could not use this prompt. {message[:200]}".strip())
        if status in (401, 403):
            return GenerationError("Pollinations now requires an account key for this request. "
                                   "Switch to Google Gemini in Settings, or try again later.")
        if status >= 500:
            return GenerationError(f"Pollinations had a temporary problem ({status}). Try again shortly.")
        return GenerationError(f"Pollinations request failed ({status}). {message[:200]}".strip())

    def check_connection(self) -> list[str]:
        """Return the anonymous models (generates no image)."""
        status, _content_type, body = self._transport(f"{API_BASE}/models", 30)
        if status != 200:
            raise self._error_for(status, body)
        try:
            models = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise GenerationError("Pollinations returned an unexpected response.") from exc
        return [m if isinstance(m, str) else m.get("name", "") for m in models]
