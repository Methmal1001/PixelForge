"""Pure Pillow image operations used by the editor and the exporter.

Every function returns a *new* image and never mutates its input. The design
document relies on this to share image references between undo snapshots.
"""

from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageChops, ImageEnhance, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError, features

from models.design import Adjustments

MAX_DIMENSION = 12_000
MAX_ENHANCE_FACTOR = 3.0
FIT_MODES = ("stretch", "fill", "fit")
CANVAS_BACKGROUNDS = {
    "gradient": "Studio gradient",
    "white": "White",
    "black": "Black",
    "transparent": "Transparent",
}

RGBA = tuple[int, int, int, int]


class ImageProcessingError(ValueError):
    """Raised when an image operation receives invalid input."""


class ImageLoadError(ImageProcessingError):
    """Raised when a file cannot be opened as an image."""


# --------------------------------------------------------------------------- loading


def supported_extensions() -> tuple[str, ...]:
    """File extensions this installation can open."""
    extensions = [".png", ".jpg", ".jpeg"]
    if features.check("webp"):
        extensions.append(".webp")
    return tuple(extensions)


def normalize_mode(image: Image.Image) -> Image.Image:
    """Convert any input mode to RGB, or RGBA when the image carries transparency."""
    has_alpha = image.mode in ("RGBA", "LA", "PA", "RGBa", "La") or (
        image.mode == "P" and "transparency" in image.info
    )
    return image.convert("RGBA" if has_alpha else "RGB")


def load_image(path: str | Path) -> Image.Image:
    """Open, validate and normalise an image file.

    Raises ImageLoadError with a user-readable message on any failure.
    """
    if path is None or not str(path).strip():
        raise ImageLoadError("No file was selected.")
    file_path = Path(path)
    if not file_path.exists():
        raise ImageLoadError(f"The file “{file_path.name}” does not exist.")
    if not file_path.is_file():
        raise ImageLoadError(f"“{file_path.name}” is a folder, not an image file.")
    allowed = supported_extensions()
    if file_path.suffix.lower() not in allowed:
        names = ", ".join(ext.lstrip(".").upper() for ext in allowed)
        raise ImageLoadError(f"“{file_path.name}” is not a supported image type. Use {names}.")

    try:
        with Image.open(file_path) as probe:
            probe.verify()
        with Image.open(file_path) as img:
            img.load()
            result = normalize_mode(ImageOps.exif_transpose(img))
    except Image.DecompressionBombError as exc:
        raise ImageLoadError(f"“{file_path.name}” is too large to open safely.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as exc:
        raise ImageLoadError(
            f"“{file_path.name}” could not be read as an image. "
            "The file may be damaged or is not really an image."
        ) from exc

    if result.width > MAX_DIMENSION or result.height > MAX_DIMENSION:
        raise ImageLoadError(
            f"“{file_path.name}” is {result.width} × {result.height} px. "
            f"The maximum supported size is {MAX_DIMENSION} px per side."
        )
    return result


# --------------------------------------------------------------------------- geometry


def validate_dimensions(width: object, height: object) -> tuple[int, int]:
    """Return (width, height) as ints, or raise ImageProcessingError."""
    try:
        w, h = int(width), int(height)  # type: ignore[call-overload]
    except (TypeError, ValueError) as exc:
        raise ImageProcessingError("Width and height must be whole numbers.") from exc
    if w < 1 or h < 1:
        raise ImageProcessingError("Width and height must be at least 1 pixel.")
    if w > MAX_DIMENSION or h > MAX_DIMENSION:
        raise ImageProcessingError(f"Width and height cannot exceed {MAX_DIMENSION} pixels.")
    return w, h


def resize(image: Image.Image, width: int, height: int) -> Image.Image:
    """Resize to exactly width × height (may change the aspect ratio)."""
    w, h = validate_dimensions(width, height)
    if (w, h) == image.size:
        return image.copy()
    return image.resize((w, h), Image.Resampling.LANCZOS)


def fit_geometry(
    src_w: int, src_h: int, dst_w: int, dst_h: int, mode: str
) -> tuple[float, float, float, float]:
    """Return (scale_x, scale_y, offset_x, offset_y) mapping source to destination pixels."""
    if mode == "stretch":
        return dst_w / src_w, dst_h / src_h, 0.0, 0.0
    if mode == "fill":
        scale = max(dst_w / src_w, dst_h / src_h)
    elif mode == "fit":
        scale = min(dst_w / src_w, dst_h / src_h)
    else:
        raise ImageProcessingError(f"Unknown fit mode “{mode}”.")
    return scale, scale, (dst_w - src_w * scale) / 2, (dst_h - src_h * scale) / 2


def fit_to_size(
    image: Image.Image,
    width: int,
    height: int,
    mode: str = "stretch",
    background: RGBA = (0, 0, 0, 0),
) -> Image.Image:
    """Bring an image to width × height.

    ``stretch`` distorts, ``fill`` scales and centre-crops, ``fit`` scales and pads
    with ``background``.
    """
    w, h = validate_dimensions(width, height)
    if mode not in FIT_MODES:
        raise ImageProcessingError(f"Unknown fit mode “{mode}”.")
    if mode == "stretch":
        return resize(image, w, h)

    scale = fit_geometry(image.width, image.height, w, h, mode)[0]
    new_w = max(1, round(image.width * scale))
    new_h = max(1, round(image.height * scale))
    if mode == "fill":
        new_w, new_h = max(new_w, w), max(new_h, h)
    scaled = image.resize((new_w, new_h), Image.Resampling.LANCZOS)

    if mode == "fill":
        left, top = (new_w - w) // 2, (new_h - h) // 2
        return scaled.crop((left, top, left + w, top + h))

    use_alpha = background[3] < 255 or scaled.mode == "RGBA"
    position = ((w - new_w) // 2, (h - new_h) // 2)
    if use_alpha:
        canvas = Image.new("RGBA", (w, h), background)
        canvas.alpha_composite(scaled.convert("RGBA"), dest=position)
    else:
        canvas = Image.new("RGB", (w, h), background[:3])
        canvas.paste(scaled.convert("RGB"), position)
    return canvas


def crop(image: Image.Image, left: int, top: int, width: int, height: int) -> Image.Image:
    """Crop a width × height region whose top-left corner is (left, top)."""
    try:
        left, top, width, height = int(left), int(top), int(width), int(height)
    except (TypeError, ValueError) as exc:
        raise ImageProcessingError("Crop values must be whole numbers.") from exc
    if width < 1 or height < 1:
        raise ImageProcessingError("The crop area must be at least 1 × 1 pixel.")
    if left < 0 or top < 0:
        raise ImageProcessingError("The crop area must start inside the image.")
    if left + width > image.width or top + height > image.height:
        raise ImageProcessingError(
            f"The crop area extends beyond the image ({image.width} × {image.height} px)."
        )
    return image.crop((left, top, left + width, top + height))


def rotate_left(image: Image.Image) -> Image.Image:
    """Rotate 90° counter-clockwise."""
    return image.transpose(Image.Transpose.ROTATE_90)


def rotate_right(image: Image.Image) -> Image.Image:
    """Rotate 90° clockwise."""
    return image.transpose(Image.Transpose.ROTATE_270)


def flip_horizontal(image: Image.Image) -> Image.Image:
    return image.transpose(Image.Transpose.FLIP_LEFT_RIGHT)


def flip_vertical(image: Image.Image) -> Image.Image:
    return image.transpose(Image.Transpose.FLIP_TOP_BOTTOM)


def rotate_free(image: Image.Image, degrees: float) -> Image.Image:
    """Rotate clockwise by any angle. The canvas grows to fit; new corners are transparent."""
    try:
        angle = float(degrees)
    except (TypeError, ValueError) as exc:
        raise ImageProcessingError("The rotation angle must be a number.") from exc
    if not math.isfinite(angle) or abs(angle) > 360:
        raise ImageProcessingError("The rotation angle must be between -360 and 360 degrees.")
    if angle % 360 == 0:
        return image.copy()
    return image.convert("RGBA").rotate(-angle, resample=Image.Resampling.BICUBIC, expand=True,
                                        fillcolor=(0, 0, 0, 0))


# --------------------------------------------------------------------------- colour


def _validate_factor(factor: object, name: str) -> float:
    try:
        value = float(factor)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ImageProcessingError(f"{name} must be a number.") from exc
    if not math.isfinite(value) or value < 0 or value > MAX_ENHANCE_FACTOR:
        raise ImageProcessingError(f"{name} must be between 0 and {MAX_ENHANCE_FACTOR:g}.")
    return value


def _apply_to_color(image: Image.Image, operation) -> Image.Image:
    """Run an RGB operation while leaving any alpha channel untouched."""
    if image.mode not in ("RGB", "RGBA"):
        image = normalize_mode(image)
    if image.mode == "RGBA":
        alpha = image.getchannel("A")
        result = operation(image.convert("RGB"))
        result.putalpha(alpha)
        return result
    return operation(image)


def adjust_brightness(image: Image.Image, factor: float) -> Image.Image:
    value = _validate_factor(factor, "Brightness")
    return _apply_to_color(image, lambda im: ImageEnhance.Brightness(im).enhance(value))


def adjust_contrast(image: Image.Image, factor: float) -> Image.Image:
    value = _validate_factor(factor, "Contrast")
    return _apply_to_color(image, lambda im: ImageEnhance.Contrast(im).enhance(value))


def adjust_saturation(image: Image.Image, factor: float) -> Image.Image:
    value = _validate_factor(factor, "Saturation")
    return _apply_to_color(image, lambda im: ImageEnhance.Color(im).enhance(value))


def to_grayscale(image: Image.Image) -> Image.Image:
    return _apply_to_color(image, lambda im: ImageOps.grayscale(im).convert("RGB"))


def _clamp_amount(value: object, low: int, high: int, name: str) -> float:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError) as exc:
        raise ImageProcessingError(f"{name} must be a number.") from exc
    if not math.isfinite(number):
        raise ImageProcessingError(f"{name} must be a number.")
    return max(low, min(high, number))


def _lut(function) -> list[int]:
    return [max(0, min(255, round(function(v / 255.0) * 255))) for v in range(256)]


def adjust_sharpness(image: Image.Image, factor: float) -> Image.Image:
    value = _validate_factor(factor, "Sharpness")
    return _apply_to_color(image, lambda im: ImageEnhance.Sharpness(im).enhance(value))


def adjust_tone(image: Image.Image, highlights: float = 0, shadows: float = 0) -> Image.Image:
    """Lift or darken shadows and highlights independently (-100 … 100), keeping pure black/white."""
    h = _clamp_amount(highlights, -100, 100, "Highlights") / 100
    sh = _clamp_amount(shadows, -100, 100, "Shadows") / 100
    if not h and not sh:
        return image.copy()
    table = _lut(lambda x: x + 0.5 * sh * 4 * x * (1 - x) ** 2 + 0.5 * h * 4 * (1 - x) * x ** 2)
    return _apply_to_color(image, lambda im: im.point(table * 3))


def adjust_white_balance(image: Image.Image, warmth: float = 0, tint: float = 0) -> Image.Image:
    """Warmth shifts blue↔orange, tint shifts green↔magenta (-100 … 100)."""
    w = _clamp_amount(warmth, -100, 100, "Warmth") / 100
    t = _clamp_amount(tint, -100, 100, "Tint") / 100
    if not w and not t:
        return image.copy()
    red = _lut(lambda x: x * (1 + 0.18 * w) + 0.04 * w)
    green = _lut(lambda x: x * (1 - 0.15 * t))
    blue = _lut(lambda x: x * (1 - 0.18 * w))
    return _apply_to_color(image, lambda im: im.point(red + green + blue))


def shift_hue(image: Image.Image, degrees: float) -> Image.Image:
    """Rotate every hue around the colour wheel (-180 … 180 degrees)."""
    shift = round(_clamp_amount(degrees, -180, 180, "Hue") / 360 * 256) % 256
    if not shift:
        return image.copy()

    def rotate(im: Image.Image) -> Image.Image:
        h, s_, v = im.convert("HSV").split()
        return Image.merge("HSV", (h.point(lambda p: (p + shift) % 256), s_, v)).convert("RGB")

    return _apply_to_color(image, rotate)


def apply_blur(image: Image.Image, amount: float) -> Image.Image:
    """Gaussian blur; ``amount`` 0 … 100 is relative to the image size."""
    value = _clamp_amount(amount, 0, 100, "Blur")
    if not value:
        return image.copy()
    radius = value / 100 * max(image.size) * 0.02
    return image.filter(ImageFilter.GaussianBlur(radius))


def apply_vignette(image: Image.Image, amount: float) -> Image.Image:
    """Darken the edges (0 … 100) with a smooth elliptical falloff."""
    value = _clamp_amount(amount, 0, 100, "Vignette") / 100
    if not value:
        return image.copy()
    strength = 0.85 * value

    def falloff(x: float) -> float:
        t = min(1.0, max(0.0, (x - 0.45) / 0.55))
        return 1 - strength * t * t * (3 - 2 * t)

    mask = Image.radial_gradient("L").point(_lut(falloff)).resize(image.size, Image.Resampling.BILINEAR)

    def darken(im: Image.Image) -> Image.Image:
        return ImageChops.multiply(im, Image.merge("RGB", (mask, mask, mask)))

    return _apply_to_color(image, darken)


def to_sepia(image: Image.Image) -> Image.Image:
    return _apply_to_color(image, lambda im: ImageOps.colorize(
        ImageOps.grayscale(im), black="#2B1D0E", white="#F6E8CB", mid="#A3805A"))


def invert_colors(image: Image.Image) -> Image.Image:
    return _apply_to_color(image, ImageOps.invert)


def apply_adjustments(image: Image.Image, adjustments: Adjustments) -> Image.Image:
    """Apply every adjustment to ``image`` in a fixed, photo-editor-like order.

    Returns ``image`` itself when there is nothing to do, so callers must not
    mutate the result.
    """
    a = adjustments
    result = image
    if a.highlights or a.shadows:
        result = adjust_tone(result, a.highlights, a.shadows)
    if a.brightness != 1.0:
        result = adjust_brightness(result, a.brightness)
    if a.contrast != 1.0:
        result = adjust_contrast(result, a.contrast)
    if a.saturation != 1.0:
        result = adjust_saturation(result, a.saturation)
    if a.warmth or a.tint:
        result = adjust_white_balance(result, a.warmth, a.tint)
    if a.hue:
        result = shift_hue(result, a.hue)
    if a.grayscale:
        result = to_grayscale(result)
    if a.sepia:
        result = to_sepia(result)
    if a.invert:
        result = invert_colors(result)
    if a.sharpness != 1.0:
        result = adjust_sharpness(result, a.sharpness)
    if a.blur:
        result = apply_blur(result, a.blur)
    if a.vignette:
        result = apply_vignette(result, a.vignette)
    return result


# --------------------------------------------------------------------------- helpers


def create_canvas(width: int, height: int, background: str = "gradient") -> Image.Image:
    """Create a blank canvas. ``gradient`` draws a dark studio backdrop."""
    w, h = validate_dimensions(width, height)
    if background == "white":
        return Image.new("RGB", (w, h), (255, 255, 255))
    if background == "black":
        return Image.new("RGB", (w, h), (0, 0, 0))
    if background == "transparent":
        return Image.new("RGBA", (w, h), (0, 0, 0, 0))
    if background != "gradient":
        raise ImageProcessingError(f"Unknown canvas background “{background}”.")

    ramp = Image.linear_gradient("L").resize((w, h))
    canvas = ImageOps.colorize(ramp, black="#1B1240", mid="#141A3A", white="#0A0F22")
    glow_size = max(2, int(max(w, h) * 0.95))
    glow_mask = ImageOps.invert(Image.radial_gradient("L")).resize((glow_size, glow_size))
    glow_mask = glow_mask.point(lambda v: int(v * 0.42))
    canvas.paste(
        Image.new("RGB", (glow_size, glow_size), "#5B3DF5"),
        (int(w * 0.55) - glow_size // 2, int(h * 0.25) - glow_size // 2),
        glow_mask,
    )
    return canvas


def has_transparency(image: Image.Image) -> bool:
    return image.mode == "RGBA" and image.getchannel("A").getextrema()[0] < 255


def average_luminance(image: Image.Image, box: tuple[int, int, int, int] | None = None) -> float:
    """Mean luminance (0–255) of the whole image or of ``box``."""
    region = image.crop(box) if box else image
    small = region.convert("L").resize((48, 48))
    return float(ImageStat.Stat(small).mean[0])


def make_thumbnail(image: Image.Image, max_side: int) -> Image.Image:
    thumb = image.copy()
    thumb.thumbnail((max_side, max_side), Image.Resampling.LANCZOS)
    return thumb
