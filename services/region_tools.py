"""Edit only a selected area of an image (Photoshop-style selections).

A selection is a shape ("rect", "ellipse" or freehand "lasso") given as points in
image pixels. It becomes a soft-edged mask, and region operations change only the
pixels inside it. Every function returns a new image.
"""

from __future__ import annotations

from collections.abc import Sequence

from PIL import Image, ImageChops, ImageColor, ImageDraw, ImageFilter, ImageMath, ImageOps

from models.design import Adjustments
from services.image_processor import ImageProcessingError, adjust_sharpness, apply_adjustments, crop

SHAPES = ("rect", "ellipse", "lasso", "mask")  # "mask": a ready-made mask (magic wand)
REGION_OPERATIONS = ("adjust", "blur", "sharpen", "remove", "fill", "erase")
Point = tuple[float, float]


def selection_bbox(points: Sequence[Point], size: tuple[int, int]) -> tuple[int, int, int, int]:
    """Integer bounding box (left, top, right, bottom) of the points, clamped to the image."""
    if not points:
        raise ImageProcessingError("Nothing is selected.")
    xs = [p[0] for p in points]
    ys = [p[1] for p in points]
    left = max(0, int(min(xs)))
    top = max(0, int(min(ys)))
    right = min(size[0], int(round(max(xs))))
    bottom = min(size[1], int(round(max(ys))))
    if right - left < 2 or bottom - top < 2:
        raise ImageProcessingError("The selection is too small. Drag a larger area on the image.")
    return left, top, right, bottom


def build_mask(size: tuple[int, int], shape: str, points: Sequence[Point], feather: float = 1.5) -> Image.Image:
    """Grayscale mask (255 = selected) for a selection shape, with softly feathered edges."""
    if shape not in SHAPES:
        raise ImageProcessingError(f"Unknown selection shape “{shape}”.")
    if shape == "mask":
        if not isinstance(points, Image.Image) or points.size != size:
            raise ImageProcessingError("The selection does not match the image.")
        if points.getbbox() is None:
            raise ImageProcessingError("Nothing is selected.")
        return points.convert("L")
    mask = Image.new("L", size, 0)
    draw = ImageDraw.Draw(mask)
    if shape == "lasso":
        if len(points) < 3:
            raise ImageProcessingError("Draw around the area to select it.")
        selection_bbox(points, size)
        draw.polygon([(float(x), float(y)) for x, y in points], fill=255)
    else:
        box = selection_bbox(points, size)
        if shape == "rect":
            draw.rectangle((box[0], box[1], box[2] - 1, box[3] - 1), fill=255)
        else:
            draw.ellipse((box[0], box[1], box[2] - 1, box[3] - 1), fill=255)
    if mask.getbbox() is None:
        raise ImageProcessingError("The selection does not cover any part of the image.")
    if feather > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(feather))
    return mask


# --------------------------------------------------------------------------- operations


def _keep_alpha(original: Image.Image, edited: Image.Image) -> Image.Image:
    if original.mode == "RGBA" and edited.mode == "RGBA":
        edited = edited.copy()
        edited.putalpha(original.getchannel("A"))
    return edited


def smart_fill(image: Image.Image, mask: Image.Image) -> Image.Image:
    """Fill the masked area from the surrounding pixels (simple content-aware removal).

    Uses normalised convolution: blur the known pixels and divide by the blurred
    "known" weight, at a small and a large radius so the centre of big areas is
    still filled smoothly.
    """
    box = mask.getbbox()
    if box is None:
        return image.copy()
    span = max(box[2] - box[0], box[3] - box[1])
    small, large = max(3.0, span * 0.12), max(8.0, span * 0.45)
    margin = int(large * 2.5)
    window = (max(0, box[0] - margin), max(0, box[1] - margin),
              min(image.width, box[2] + margin), min(image.height, box[3] + margin))

    region = image.crop(window)
    region_mask = mask.crop(window).point(lambda v: 255 if v > 10 else 0)
    known = ImageOps.invert(region_mask)
    rgb = region.convert("RGB")

    def fill(radius: float) -> tuple[list[Image.Image], Image.Image]:
        weight = known.filter(ImageFilter.GaussianBlur(radius))
        bands = []
        for band in rgb.split():
            total = ImageChops.multiply(band, known).filter(ImageFilter.GaussianBlur(radius))
            bands.append(ImageMath.lambda_eval(
                lambda a: a["convert"](a["t"] * 255 / (a["w"] + 0.5), "L"), t=total, w=weight))
        return bands, weight

    fine, fine_weight = fill(small)
    coarse, _ = fill(large)
    # Use the fine fill where enough known pixels are nearby, the coarse fill elsewhere.
    blend = fine_weight.point(lambda v: min(255, v * 4))
    filled = Image.composite(Image.merge("RGB", fine), Image.merge("RGB", coarse), blend)
    filled = filled.convert(image.mode) if image.mode != "RGB" else filled

    result = image.copy()
    result.paste(_keep_alpha(region, filled), window[:2])
    return result


def apply_region(image: Image.Image, mask: Image.Image, operation: str, *,
                 adjustments: Adjustments | None = None, color: str = "#FFFFFF",
                 amount: float = 50) -> Image.Image:
    """Apply ``operation`` to the masked area of ``image`` only."""
    if mask.size != image.size:
        raise ImageProcessingError("The selection does not match the image size.")
    if operation not in REGION_OPERATIONS:
        raise ImageProcessingError(f"Unknown area operation “{operation}”.")
    box = mask.getbbox()
    if box is None:
        raise ImageProcessingError("Nothing is selected.")
    span = max(box[2] - box[0], box[3] - box[1])

    if operation == "erase":
        result = image.convert("RGBA")
        alpha = ImageChops.multiply(result.getchannel("A"), ImageOps.invert(mask))
        result.putalpha(alpha)
        return result
    if operation == "adjust":
        edited = apply_adjustments(image, adjustments or Adjustments())
    elif operation == "blur":
        radius = max(1.0, max(0.0, min(100.0, float(amount))) / 100 * span * 0.08)
        edited = image.filter(ImageFilter.GaussianBlur(radius))
    elif operation == "sharpen":
        edited = adjust_sharpness(image, 2.5)
    elif operation == "fill":
        try:
            rgb = ImageColor.getrgb(color)[:3]
        except ValueError as exc:
            raise ImageProcessingError(f"“{color}” is not a valid colour.") from exc
        edited = Image.new(image.mode, image.size, rgb + ((255,) if image.mode == "RGBA" else ()))
    else:  # remove
        edited = smart_fill(image, mask)
    edited = _keep_alpha(image, edited.convert(image.mode))
    return Image.composite(edited, image, mask)


def magic_wand(image: Image.Image, point: Point, tolerance: int = 32) -> Image.Image:
    """Select the connected area of similar colour around ``point`` (Photoshop's Magic Wand)."""
    x, y = int(point[0]), int(point[1])
    if not (0 <= x < image.width and 0 <= y < image.height):
        raise ImageProcessingError("Click inside the image to use the Magic Wand.")
    tolerance = max(0, min(255, int(tolerance)))
    rgb = image.convert("RGB")
    target = rgb.getpixel((x, y))
    difference = ImageChops.difference(rgb, Image.new("RGB", rgb.size, target))
    r, g, b = difference.split()
    distance = ImageChops.lighter(ImageChops.lighter(r, g), b)       # max channel difference
    similar = distance.point(lambda v: 255 if v <= tolerance else 0)
    ImageDraw.floodfill(similar, (x, y), 128, thresh=0)              # keep only the connected part
    region = similar.point(lambda v: 255 if v == 128 else 0)
    if image.mode == "RGBA":                                         # never select fully transparent pixels
        region = ImageChops.multiply(region, image.getchannel("A").point(lambda v: 255 if v > 0 else 0))
    return region.filter(ImageFilter.GaussianBlur(0.8))


def mask_bbox(mask: Image.Image) -> tuple[int, int, int, int]:
    box = mask.point(lambda v: 255 if v > 8 else 0).getbbox()
    if box is None:
        raise ImageProcessingError("Nothing is selected.")
    return box


def extract_layer(image: Image.Image, mask: Image.Image) -> tuple[Image.Image, tuple[int, int]]:
    """Copy the selected pixels into a transparent RGBA image. Returns (layer image, top-left)."""
    box = mask_bbox(mask)
    piece = image.convert("RGBA").crop(box)
    alpha = ImageChops.multiply(piece.getchannel("A"), mask.crop(box))
    piece.putalpha(alpha)
    return piece, (box[0], box[1])


def crop_to_selection(image: Image.Image, points: Sequence[Point]) -> Image.Image:
    left, top, right, bottom = selection_bbox(points, image.size)
    return crop(image, left, top, right - left, bottom - top)
