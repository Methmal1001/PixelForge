"""Design data model: what is on the canvas, independent of how it is displayed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace

from PIL import Image

DEFAULT_FONT_FAMILY = "Segoe UI"
TEXT_ALIGNMENTS = ("left", "center", "right")


@dataclass(frozen=True)
class Adjustments:
    """Non-destructive image adjustments applied on top of the geometry-edited base image.

    ``brightness``, ``contrast``, ``saturation`` and ``sharpness`` are Pillow
    ImageEnhance factors (1.0 = unchanged). The other values are slider amounts:
    0 means unchanged. Sizes (blur, vignette) are relative to the image, so the
    downscaled live preview and the full-size export look the same.
    """

    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    grayscale: bool = False
    # light
    highlights: int = 0      # -100 … 100
    shadows: int = 0         # -100 … 100
    # colour
    warmth: int = 0          # -100 (cool) … 100 (warm)
    tint: int = 0            # -100 (green) … 100 (magenta)
    hue: int = 0             # -180 … 180 degrees
    # effects
    sharpness: float = 1.0   # 0 … 3 factor
    blur: int = 0            # 0 … 100
    vignette: int = 0        # 0 … 100
    sepia: bool = False
    invert: bool = False
    filter_name: str = "none"  # the preset these values came from (display only)

    def is_identity(self) -> bool:
        return replace(self, filter_name="none") == Adjustments()


@dataclass
class TextElement:
    """An editable text overlay. Coordinates and font size are in image pixels.

    Effect sizes (shadow, outline, background padding) are percentages of the
    font size, so they scale naturally when the design is resized.
    """

    text: str = "Your headline"
    x: float = 0.0
    y: float = 0.0
    font_family: str = DEFAULT_FONT_FAMILY
    font_size: int = 72
    color: str = "#FFFFFF"
    bold: bool = True
    italic: bool = False
    align: str = "left"
    # typography
    underline: bool = False
    uppercase: bool = False
    letter_spacing: float = 0.0   # extra spacing, % of font size (-10 … 50)
    line_height: float = 1.0      # multiple of the normal line height (0.7 … 2.5)
    # layout
    opacity: float = 1.0          # 0 … 1
    rotation: float = 0.0         # degrees, around the text box centre
    # effects
    shadow: bool = False
    shadow_color: str = "#000000"
    shadow_distance: float = 8.0  # % of font size
    shadow_blur: float = 10.0     # % of font size
    shadow_opacity: float = 0.6
    outline: bool = False
    outline_color: str = "#000000"
    outline_width: float = 6.0    # % of font size
    background: bool = False
    background_color: str = "#7C5CFF"
    background_opacity: float = 1.0
    background_padding: float = 30.0  # % of font size
    background_radius: float = 25.0   # % of font size
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class ImageLayer:
    """A movable picture layer (e.g. an object copied out of the background).

    ``image`` is RGBA and is never modified in place. ``x``/``y`` is the top-left of
    the unscaled layer; scale and rotation are applied around the layer centre.
    """

    image: Image.Image
    x: float = 0.0
    y: float = 0.0
    scale: float = 1.0
    rotation: float = 0.0
    opacity: float = 1.0
    name: str = "Layer"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)

    @property
    def size(self) -> tuple[int, int]:
        return self.image.size


@dataclass
class DesignState:
    """One undoable snapshot of a design.

    ``base`` is never modified in place: every edit produces a new image, so
    snapshots can share image references cheaply.
    """

    base: Image.Image
    adjustments: Adjustments = field(default_factory=Adjustments)
    texts: list[TextElement] = field(default_factory=list)
    layers: list[ImageLayer] = field(default_factory=list)  # bottom → top, drawn below text

    def copy(self) -> DesignState:
        return DesignState(self.base, self.adjustments, [replace(t) for t in self.texts],
                           [replace(layer) for layer in self.layers])
