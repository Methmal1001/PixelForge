"""Design data model: what is on the canvas, independent of how it is displayed."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field, replace

from PIL import Image

DEFAULT_FONT_FAMILY = "Segoe UI"
TEXT_ALIGNMENTS = ("left", "center", "right")


@dataclass(frozen=True)
class Adjustments:
    """Colour adjustments applied on top of the geometry-edited base image.

    Factors follow Pillow's ImageEnhance convention: 1.0 leaves the image unchanged.
    """

    brightness: float = 1.0
    contrast: float = 1.0
    saturation: float = 1.0
    grayscale: bool = False

    def is_identity(self) -> bool:
        return self == Adjustments()


@dataclass
class TextElement:
    """An editable text overlay. Coordinates and size are in image pixels."""

    text: str = "Your headline"
    x: float = 0.0
    y: float = 0.0
    font_family: str = DEFAULT_FONT_FAMILY
    font_size: int = 72
    color: str = "#FFFFFF"
    bold: bool = True
    italic: bool = False
    align: str = "left"
    id: str = field(default_factory=lambda: uuid.uuid4().hex)


@dataclass
class DesignState:
    """One undoable snapshot of a design.

    ``base`` is never modified in place: every edit produces a new image, so
    snapshots can share image references cheaply.
    """

    base: Image.Image
    adjustments: Adjustments = field(default_factory=Adjustments)
    texts: list[TextElement] = field(default_factory=list)

    def copy(self) -> DesignState:
        return DesignState(self.base, self.adjustments, [replace(t) for t in self.texts])
