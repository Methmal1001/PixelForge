"""Compose a design (image + text overlays) and write it to PNG or JPEG."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageColor
from PySide6.QtGui import QPainter

from models.design import TextElement
from services.image_processor import ImageProcessingError, fit_to_size, has_transparency
from services.qt_image import pil_to_qimage, qimage_to_pil
from services.text_renderer import ensure_gui_application, paint_text

FORMAT_EXTENSIONS = {"PNG": (".png",), "JPEG": (".jpg", ".jpeg")}


class ExportError(Exception):
    """Raised with a user-readable message when an export cannot be completed."""


@dataclass
class ExportOptions:
    path: Path
    image_format: str = "PNG"
    width: int | None = None
    height: int | None = None
    fit_mode: str = "fill"
    quality: int = 92
    background: str = "#FFFFFF"


def normalize_format(image_format: str) -> str:
    fmt = (image_format or "").strip().upper()
    if fmt == "JPG":
        fmt = "JPEG"
    if fmt not in FORMAT_EXTENSIONS:
        raise ExportError(f"“{image_format}” is not a supported export format. Use PNG or JPEG.")
    return fmt


def parse_color(value: str) -> tuple[int, int, int]:
    try:
        return ImageColor.getrgb(value)[:3]
    except (ValueError, AttributeError) as exc:
        raise ExportError(f"“{value}” is not a valid colour.") from exc


def compose_design(base: Image.Image, texts: Iterable[TextElement]) -> Image.Image:
    """Render text overlays onto a copy of ``base``. Returns an RGBA image."""
    texts = list(texts)
    if not texts:
        return base.convert("RGBA")
    ensure_gui_application()
    canvas = pil_to_qimage(base)
    painter = QPainter(canvas)
    painter.setRenderHints(
        QPainter.RenderHint.Antialiasing
        | QPainter.RenderHint.TextAntialiasing
        | QPainter.RenderHint.SmoothPixmapTransform
    )
    try:
        for element in texts:
            paint_text(painter, element)
    finally:
        painter.end()
    return qimage_to_pil(canvas)


def flatten(image: Image.Image, background: str | tuple[int, int, int]) -> Image.Image:
    """Composite a possibly transparent image onto a solid colour."""
    color = parse_color(background) if isinstance(background, str) else background
    if image.mode != "RGBA":
        return image.convert("RGB")
    solid = Image.new("RGBA", image.size, (*color, 255))
    return Image.alpha_composite(solid, image).convert("RGB")


def save_image(
    image: Image.Image,
    path: str | Path,
    image_format: str = "PNG",
    quality: int = 92,
    background: str = "#FFFFFF",
) -> Path:
    """Write ``image`` to disk. Returns the final path (extension corrected if needed)."""
    fmt = normalize_format(image_format)
    target = Path(path)
    if not target.name or target.name in (".", ".."):
        raise ExportError("Please choose a file name for the export.")
    if not target.parent.exists():
        raise ExportError(f"The folder “{target.parent}” does not exist.")
    if target.suffix.lower() not in FORMAT_EXTENSIONS[fmt]:
        known = {ext for extensions in FORMAT_EXTENSIONS.values() for ext in extensions}
        if target.suffix.lower() in known:
            target = target.with_suffix(FORMAT_EXTENSIONS[fmt][0])
        else:
            target = target.with_name(target.name + FORMAT_EXTENSIONS[fmt][0])

    try:
        if fmt == "JPEG":
            try:
                quality = int(quality)
            except (TypeError, ValueError) as exc:
                raise ExportError("JPEG quality must be a whole number.") from exc
            if not 1 <= quality <= 100:
                raise ExportError("JPEG quality must be between 1 and 100.")
            flatten(image, background).save(
                target, "JPEG", quality=quality, optimize=True, subsampling=0 if quality >= 90 else 2
            )
        else:
            output = image if has_transparency(image) else image.convert("RGB")
            output.save(target, "PNG", compress_level=6)
    except OSError as exc:
        raise ExportError(f"Could not write “{target.name}”: {exc.strerror or exc}") from exc
    return target


def export_design(base: Image.Image, texts: Iterable[TextElement], options: ExportOptions) -> Path:
    """Compose, resize to the requested output dimensions and save the design."""
    fmt = normalize_format(options.image_format)
    composed = compose_design(base, texts)
    width = options.width or composed.width
    height = options.height or composed.height
    if (width, height) != composed.size:
        padding = (0, 0, 0, 0) if fmt == "PNG" else (*parse_color(options.background), 255)
        try:
            composed = fit_to_size(composed, width, height, options.fit_mode, padding)
        except ImageProcessingError as exc:
            raise ExportError(str(exc)) from exc
    return save_image(composed, options.path, fmt, options.quality, options.background)
