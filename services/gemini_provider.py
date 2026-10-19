"""Google Gemini (Google AI Studio) image-generation provider.

Uses the public REST endpoint with the standard library only:
POST https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent
"""

from __future__ import annotations

import base64
import io
import json
import re
import urllib.error
import urllib.request
from collections.abc import Callable

from PIL import Image, UnidentifiedImageError

from services.generation_service import (
    GenerationAuthError,
    GenerationError,
    GenerationQuotaError,
    GenerationRequest,
    ImageGenerationService,
    PRESET_ASPECT_RATIOS,
    compose_prompt,
)
from services.image_processor import ImageLoadError, load_image, make_thumbnail, normalize_mode

API_BASE = "https://generativelanguage.googleapis.com/v1beta"
DEFAULT_MODEL = "gemini-3.1-flash-image"
IMAGE_MODELS = {
    "gemini-3.1-flash-image": "Gemini 3.1 Flash Image",
    "gemini-3.1-flash-lite-image": "Gemini 3.1 Flash Lite Image (fastest)",
    "gemini-2.5-flash-image": "Gemini 2.5 Flash Image",
    "gemini-3-pro-image": "Gemini 3 Pro Image (highest quality)",
}
REFERENCE_MAX_SIDE = 1536

# (method, url, headers, body, timeout) -> (status_code, response_bytes)
Transport = Callable[[str, str, dict, bytes | None, float], tuple[int, bytes]]


def urllib_transport(method: str, url: str, headers: dict, body: bytes | None, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=body, method=method, headers=headers)
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        reason = getattr(exc, "reason", exc)
        raise GenerationError(
            f"Could not reach Google's servers ({reason}). Check your internet connection and try again."
        ) from exc


class GeminiImageService(ImageGenerationService):
    name = "Google Gemini"
    short_name = "Gemini"
    supports_reference = True

    def __init__(self, api_key: str, model: str = DEFAULT_MODEL, *,
                 transport: Transport | None = None, timeout: float = 180.0) -> None:
        self.api_key = (api_key or "").strip()
        self.model = model or DEFAULT_MODEL
        self._transport = transport or urllib_transport
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        return bool(self.api_key)

    # ------------------------------------------------------------------ requests

    def build_prompt(self, request: GenerationRequest) -> str:
        return compose_prompt(request, with_reference=bool(request.reference_image))

    def _reference_part(self, request: GenerationRequest) -> dict | None:
        if not request.reference_image:
            return None
        try:
            image = make_thumbnail(load_image(request.reference_image), REFERENCE_MAX_SIDE)
        except ImageLoadError as exc:
            raise GenerationError(f"The reference image could not be used: {exc}") from exc
        buffer = io.BytesIO()
        if image.mode == "RGBA":
            image.save(buffer, "PNG")
            mime = "image/png"
        else:
            image.save(buffer, "JPEG", quality=90)
            mime = "image/jpeg"
        return {"inline_data": {"mime_type": mime, "data": base64.b64encode(buffer.getvalue()).decode()}}

    def build_body(self, request: GenerationRequest) -> dict:
        parts: list[dict] = [{"text": self.build_prompt(request)}]
        reference = self._reference_part(request)
        if reference:
            parts.append(reference)
        return {
            "contents": [{"role": "user", "parts": parts}],
            "generationConfig": {
                "responseModalities": ["TEXT", "IMAGE"],
                "imageConfig": {"aspectRatio": PRESET_ASPECT_RATIOS.get(request.preset_key, "1:1")},
            },
        }

    def _call(self, method: str, path: str, body: dict | None = None) -> dict:
        if not self.api_key:
            raise GenerationAuthError("No API key is configured. Add it in Settings → AI provider.")
        headers = {"x-goog-api-key": self.api_key, "Content-Type": "application/json"}
        data = json.dumps(body).encode("utf-8") if body is not None else None
        status, raw = self._transport(method, f"{API_BASE}/{path}", headers, data, self._timeout)
        try:
            payload = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            payload = {}
        if status != 200:
            raise self._error_for(status, payload)
        return payload

    def _error_for(self, status: int, payload: dict) -> GenerationError:
        error = payload.get("error", {}) if isinstance(payload, dict) else {}
        message = str(error.get("message", "")).strip()
        details = json.dumps(error)
        if status == 400 and ("API_KEY_INVALID" in details or "API key not valid" in message):
            return GenerationAuthError("Google rejected the API key. Check it in Settings → AI provider.")
        if status in (401, 403):
            return GenerationAuthError(f"This API key is not allowed to use the Gemini API. {message[:200]}")
        if status == 404:
            return GenerationError(f"The model “{self.model}” is not available for this API key. "
                                   "Choose another model in Settings → AI provider.")
        if status == 429:
            if "limit: 0" in message:
                return GenerationQuotaError(
                    f"Your API key works, but its free tier includes no image-generation quota for "
                    f"{self.model} (Google's limit is 0). To generate images, enable billing for the key's "
                    "project in Google AI Studio (aistudio.google.com → API keys → Set up billing).")
            wait = re.search(r"retry in ([0-9hms.]+)", message)
            hint = f" Try again in {wait.group(1)}." if wait else " Wait a minute and try again."
            return GenerationQuotaError("Google's rate limit for this key was reached." + hint)
        if status >= 500:
            return GenerationError(f"Google's image service had a temporary problem ({status}). Try again shortly.")
        return GenerationError(f"The request failed ({status}). {message[:300]}")

    # ------------------------------------------------------------------ public API

    def generate(self, request: GenerationRequest) -> Image.Image:
        request.validate()
        payload = self._call("POST", f"models/{self.model}:generateContent", self.build_body(request))
        return self.parse_image(payload)

    @staticmethod
    def parse_image(payload: dict) -> Image.Image:
        candidates = payload.get("candidates") or []
        if not candidates:
            reason = (payload.get("promptFeedback") or {}).get("blockReason")
            if reason:
                raise GenerationError(f"Google blocked this prompt ({reason}). Try rephrasing it.")
            raise GenerationError("Google returned no result. Try again or rephrase the prompt.")
        candidate = candidates[0]
        parts = (candidate.get("content") or {}).get("parts") or []
        texts = []
        for part in parts:
            inline = part.get("inlineData") or part.get("inline_data")
            if inline and inline.get("data"):
                try:
                    with Image.open(io.BytesIO(base64.b64decode(inline["data"]))) as image:
                        image.load()
                        return normalize_mode(image)
                except (UnidentifiedImageError, OSError, ValueError) as exc:
                    raise GenerationError("Google returned image data that could not be decoded.") from exc
            if part.get("text"):
                texts.append(part["text"].strip())
        reason = candidate.get("finishReason", "")
        detail = " ".join(texts)[:300] or (f"finish reason: {reason}" if reason else "no details")
        raise GenerationError(f"The model did not return an image ({detail}). Try rephrasing the prompt.")

    def list_image_models(self) -> list[str]:
        """Check the key (costs no generation quota) and return the image models it can see."""
        payload = self._call("GET", "models?pageSize=200")
        return sorted(
            m["name"].removeprefix("models/")
            for m in payload.get("models", [])
            if "image" in m.get("name", "") and "generateContent" in m.get("supportedGenerationMethods", [])
        )
