"""AI image-generation interface and provider selection.

The GUI talks only to ``ImageGenerationService``. Stage 2 adds the Google Gemini
provider (services/gemini_provider.py), selected when an API key is configured
in the git-ignored .env file (or the GEMINI_API_KEY environment variable).
"""

from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from PIL import Image

MAX_PROMPT_LENGTH = 2000

DESIGN_TYPES = (
    "Social Media Post",
    "Advertisement",
    "Promotional Banner",
    "Product Showcase",
    "Event Flyer",
    "Story / Reel Cover",
)

ART_STYLES = (
    "Photorealistic",
    "Cinematic",
    "Luxury / Premium",
    "Minimalist",
    "3D Render",
    "Illustration",
    "Flat Vector",
    "Neon / Cyberpunk",
)

# Label -> canvas preset key (see models.presets)
ASPECT_RATIOS = {
    "1:1 · Square Post": "square",
    "4:5 · Portrait Post": "portrait",
    "9:16 · Story": "story",
    "16:9 · Landscape Banner": "landscape",
}

NOT_CONFIGURED_MESSAGE = (
    "AI generation is not configured. Add your Google AI Studio API key in Settings → AI provider."
)

GENERATED_DIR = Path(__file__).resolve().parent.parent / "storage" / "generated"


class GenerationError(RuntimeError):
    """A generation failure with a user-readable message."""


class GenerationNotConfiguredError(GenerationError):
    """Raised when no AI provider has been configured."""


class GenerationAuthError(GenerationError):
    """The provider rejected the API key."""


class GenerationQuotaError(GenerationError):
    """The API key has no remaining (or no) quota for the request."""


@dataclass(frozen=True)
class GenerationRequest:
    prompt: str
    design_type: str
    art_style: str
    aspect_ratio: str
    reference_image: Path | None = None

    def validate(self) -> None:
        prompt = self.prompt.strip()
        if not prompt:
            raise ValueError("Describe the design you want before generating.")
        if len(prompt) < 10:
            raise ValueError("Please write a more descriptive prompt (at least 10 characters).")
        if len(prompt) > MAX_PROMPT_LENGTH:
            raise ValueError(f"Prompts are limited to {MAX_PROMPT_LENGTH} characters.")

    @property
    def preset_key(self) -> str:
        return ASPECT_RATIOS.get(self.aspect_ratio, "square")


PRESET_ASPECT_RATIOS = {"square": "1:1", "portrait": "4:5", "story": "9:16", "landscape": "16:9"}

# Provider ids stored as AI_PROVIDER in .env
PROVIDERS = {
    "gemini": "Google Gemini (your API key)",
    "pollinations": "Pollinations.ai (free, no key)",
}


def compose_prompt(request: GenerationRequest, with_reference: bool = False) -> str:
    """Turn the user's prompt and panel settings into one provider-neutral prompt."""
    ratio = PRESET_ASPECT_RATIOS.get(request.preset_key, "1:1")
    lines = [
        request.prompt.strip(),
        "",
        f"Create this as a finished {request.design_type.lower()} in a {request.art_style.lower()} style, "
        f"aspect ratio {ratio}.",
        "Professional marketing-graphic quality: sharp details, balanced composition, polished lighting.",
    ]
    if with_reference:
        lines.append("Use the attached reference image as visual guidance for the product, colours "
                     "or composition.")
    return "\n".join(lines)


class ImageGenerationService(ABC):
    """Interface every AI provider implements."""

    name: str = "Provider"
    short_name: str = "AI"
    model: str = ""
    supports_reference: bool = False

    @property
    @abstractmethod
    def is_configured(self) -> bool: ...

    @abstractmethod
    def generate(self, request: GenerationRequest) -> Image.Image:
        """Generate an image for ``request``. Raises GenerationError on failure."""


class NotConfiguredGenerationService(ImageGenerationService):
    """Used when no API key is configured. Never contacts any server."""

    name = "Not configured"

    @property
    def is_configured(self) -> bool:
        return False

    def generate(self, request: GenerationRequest) -> Image.Image:
        raise GenerationNotConfiguredError(NOT_CONFIGURED_MESSAGE)


def selected_provider() -> str:
    """The provider chosen in Settings (AI_PROVIDER); defaults to Gemini when a key exists."""
    from services.config import get_setting

    provider = (get_setting("AI_PROVIDER") or "").lower()
    if provider in PROVIDERS:
        return provider
    return "gemini" if get_setting("GEMINI_API_KEY") else "none"


def get_generation_service() -> ImageGenerationService:
    """Return the active provider according to Settings / .env."""
    from services.config import get_setting

    provider = selected_provider()
    if provider == "pollinations":
        from services.pollinations_provider import PollinationsImageService

        return PollinationsImageService()
    if provider == "gemini":
        from services.gemini_provider import DEFAULT_MODEL, GeminiImageService

        api_key = get_setting("GEMINI_API_KEY")
        if api_key:
            return GeminiImageService(api_key, get_setting("GEMINI_IMAGE_MODEL") or DEFAULT_MODEL)
    return NotConfiguredGenerationService()


def save_generation(image: Image.Image, request: GenerationRequest, model: str,
                    folder: Path = GENERATED_DIR) -> Path:
    """Save a generated image plus a JSON sidecar with its prompt and settings."""
    folder.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^A-Za-z0-9]+", "_", request.prompt.strip())[:40].strip("_").lower() or "design"
    stem = f"{datetime.now():%Y%m%d_%H%M%S}_{slug}"
    image_path = folder / f"{stem}.png"
    image.save(image_path, "PNG")
    meta = asdict(request)
    meta["reference_image"] = str(request.reference_image) if request.reference_image else None
    meta.update(model=model, created=datetime.now().isoformat(timespec="seconds"),
                width=image.width, height=image.height)
    (folder / f"{stem}.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return image_path
