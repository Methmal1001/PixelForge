"""DesignDocument: the editable design plus its undo/redo history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import fields, replace
from pathlib import Path

from PIL import Image

from models.design import TEXT_ALIGNMENTS, Adjustments, DesignState, TextElement
from services import image_processor as ip

PointMap = Callable[[float, float], tuple[float, float]]

_TEXT_FIELDS = {f.name for f in fields(TextElement)} - {"id"}


def estimate_text_size(element: TextElement) -> tuple[float, float]:
    """Rough text box size, used to keep text anchored sensibly during transforms."""
    lines = element.text.split("\n") or [""]
    longest = max(len(line) for line in lines)
    return element.font_size * 0.55 * longest, element.font_size * 1.25 * len(lines)


class DesignDocument:
    """Holds the original image, the current design state and the edit history.

    The original import is kept untouched so edits can always be reset, and colour
    adjustments are re-applied to the geometry-edited base on every render so they
    never accumulate quality loss.
    """

    MAX_HISTORY = 50

    def __init__(
        self,
        image: Image.Image,
        *,
        name: str = "Untitled design",
        source_path: str | Path | None = None,
    ) -> None:
        self.original = image
        self.name = name
        self.source_path = Path(source_path) if source_path else None
        self.state = DesignState(base=image)
        self.modified = False
        self._undo: list[DesignState] = []
        self._redo: list[DesignState] = []
        self._render_cache: tuple[Image.Image, Adjustments, Image.Image] | None = None

    # ------------------------------------------------------------------ creation

    @classmethod
    def from_file(cls, path: str | Path) -> DesignDocument:
        image = ip.load_image(path)
        return cls(image, name=Path(path).stem, source_path=path)

    @classmethod
    def blank(cls, width: int, height: int, background: str = "gradient") -> DesignDocument:
        w, h = ip.validate_dimensions(width, height)
        return cls(ip.create_canvas(w, h, background), name=f"New design {w}×{h}")

    # ------------------------------------------------------------------ properties

    @property
    def width(self) -> int:
        return self.state.base.width

    @property
    def height(self) -> int:
        return self.state.base.height

    @property
    def size(self) -> tuple[int, int]:
        return self.state.base.size

    # ------------------------------------------------------------------ history

    def snapshot(self) -> DesignState:
        return self.state.copy()

    def push_undo(self, state: DesignState) -> None:
        self._undo.append(state)
        del self._undo[: -self.MAX_HISTORY]
        self._redo.clear()
        self.modified = True

    def checkpoint(self) -> None:
        """Record the current state so the next change can be undone."""
        self.push_undo(self.snapshot())

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo(self) -> bool:
        if not self._undo:
            return False
        self._redo.append(self.snapshot())
        self.state = self._undo.pop()
        self.modified = True
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        self._undo.append(self.snapshot())
        self.state = self._redo.pop()
        self.modified = True
        return True

    # ------------------------------------------------------------------ rendering

    def rendered(self) -> Image.Image:
        """The base image with colour adjustments applied (text not included)."""
        base, adjustments = self.state.base, self.state.adjustments
        cache = self._render_cache
        if cache and cache[0] is base and cache[1] == adjustments:
            return cache[2]
        result = ip.apply_adjustments(base, adjustments)
        self._render_cache = (base, adjustments, result)
        return result

    # ------------------------------------------------------------------ geometry

    def _apply_geometry(
        self, new_base: Image.Image, point_map: PointMap, font_scale: float = 1.0, record: bool = True
    ) -> None:
        if record:
            self.checkpoint()
        new_w, new_h = new_base.size
        for text in self.state.texts:
            old_w, old_h = estimate_text_size(text)
            cx, cy = point_map(text.x + old_w / 2, text.y + old_h / 2)
            text.font_size = max(4, round(text.font_size * font_scale))
            est_w, est_h = estimate_text_size(text)
            text.x = min(max(cx - est_w / 2, 0.0), max(new_w - 1.0, 0.0))
            text.y = min(max(cy - est_h / 2, 0.0), max(new_h - 1.0, 0.0))
        self.state.base = new_base
        self.modified = True

    def crop(self, left: int, top: int, width: int, height: int, record: bool = True) -> None:
        new_base = ip.crop(self.state.base, left, top, width, height)
        self._apply_geometry(new_base, lambda x, y: (x - left, y - top), record=record)

    def resize(
        self,
        width: int,
        height: int,
        mode: str = "stretch",
        background: ip.RGBA = (0, 0, 0, 0),
        record: bool = True,
    ) -> None:
        old_w, old_h = self.size
        new_base = ip.fit_to_size(self.state.base, width, height, mode, background)
        sx, sy, dx, dy = ip.fit_geometry(old_w, old_h, new_base.width, new_base.height, mode)
        font_scale = (sx + sy) / 2 if mode == "stretch" else sx
        self._apply_geometry(new_base, lambda x, y: (x * sx + dx, y * sy + dy), font_scale, record)

    # Rotate and flip change only the background image. Text layers keep their
    # positions (clamped to the new canvas) so a finished layout is not scattered.

    def rotate_left(self, record: bool = True) -> None:
        self._apply_geometry(ip.rotate_left(self.state.base), lambda x, y: (x, y), record=record)

    def rotate_right(self, record: bool = True) -> None:
        self._apply_geometry(ip.rotate_right(self.state.base), lambda x, y: (x, y), record=record)

    def flip_horizontal(self, record: bool = True) -> None:
        self._apply_geometry(ip.flip_horizontal(self.state.base), lambda x, y: (x, y), record=record)

    def flip_vertical(self, record: bool = True) -> None:
        self._apply_geometry(ip.flip_vertical(self.state.base), lambda x, y: (x, y), record=record)

    # ------------------------------------------------------------------ adjustments

    def set_adjustments(self, adjustments: Adjustments, record: bool = False) -> None:
        for name in ("brightness", "contrast", "saturation"):
            ip._validate_factor(getattr(adjustments, name), name.capitalize())
        if adjustments == self.state.adjustments:
            return
        if record:
            self.checkpoint()
        self.state.adjustments = adjustments
        self.modified = True

    def reset_adjustments(self, record: bool = True) -> bool:
        """Return colour adjustments to neutral. Returns False if nothing changed."""
        if self.state.adjustments.is_identity():
            return False
        self.set_adjustments(Adjustments(), record=record)
        return True

    def reset_image(self, record: bool = True) -> None:
        """Restore the originally imported image; text layers are kept."""
        if record:
            self.checkpoint()
        self.state.base = self.original
        self.state.adjustments = Adjustments()
        w, h = self.original.size
        for text in self.state.texts:
            text.x = min(max(text.x, 0.0), w - 1.0)
            text.y = min(max(text.y, 0.0), h - 1.0)
        self.modified = True

    # ------------------------------------------------------------------ text

    def get_text(self, text_id: str) -> TextElement | None:
        return next((t for t in self.state.texts if t.id == text_id), None)

    def add_text(self, element: TextElement, record: bool = True) -> TextElement:
        if record:
            self.checkpoint()
        self.state.texts.append(element)
        self.modified = True
        return element

    def remove_text(self, text_id: str, record: bool = True) -> bool:
        if self.get_text(text_id) is None:
            return False
        if record:
            self.checkpoint()
        self.state.texts = [t for t in self.state.texts if t.id != text_id]
        self.modified = True
        return True

    def update_text(self, text_id: str, record: bool = False, **changes) -> TextElement:
        element = self.get_text(text_id)
        if element is None:
            raise KeyError(text_id)
        unknown = set(changes) - _TEXT_FIELDS
        if unknown:
            raise ValueError(f"Unknown text properties: {', '.join(sorted(unknown))}")
        if "font_size" in changes and int(changes["font_size"]) < 1:
            raise ValueError("Font size must be at least 1 pixel.")
        if "align" in changes and changes["align"] not in TEXT_ALIGNMENTS:
            raise ValueError(f"Alignment must be one of {', '.join(TEXT_ALIGNMENTS)}.")
        if record:
            self.checkpoint()
        updated = replace(element, **changes)
        index = self.state.texts.index(element)
        self.state.texts[index] = updated
        self.modified = True
        return updated

    def move_texts(self, positions: dict[str, tuple[float, float]], record: bool = True) -> None:
        if not positions:
            return
        if record:
            self.checkpoint()
        for text_id, (x, y) in positions.items():
            element = self.get_text(text_id)
            if element is not None:
                element.x, element.y = float(x), float(y)
        self.modified = True
