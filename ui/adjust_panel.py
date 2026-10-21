"""Right-panel tab: filters, transform tools, light/colour/effect adjustments and size presets."""

from __future__ import annotations

from dataclasses import replace

from PIL import Image
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QGridLayout,
    QHBoxLayout,
    QSizePolicy,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from models.design import Adjustments
from models.filters import FILTER_PRESETS, filter_adjustments
from models.presets import SIZE_PRESETS
from services.image_processor import apply_adjustments, fit_to_size
from services.qt_image import pil_to_qimage
from ui.icons import set_icon
from ui.widgets import CollapsibleSection, LabeledSlider, label, make_button

TRANSFORM_TOOLS = (
    ("crop", "Crop", "crop", "Select an area to keep (C)"),
    ("resize", "Resize", "resize", "Change the canvas size in pixels"),
    ("rotate_angle", "Rotate °", "rotate_angle", "Rotate by any angle (straighten)"),
    ("rotate_left", "Rotate L", "rotate_left", "Rotate 90° counter-clockwise"),
    ("rotate_right", "Rotate R", "rotate_right", "Rotate 90° clockwise"),
    ("flip_h", "Flip H", "flip_h", "Mirror horizontally"),
    ("flip_v", "Flip V", "flip_v", "Mirror vertically"),
)

# slider key -> (label, icon, min, max, suffix, signed, kind) ; kind "factor" maps -100…100 to 0…2
SLIDERS = {
    "light": [
        ("brightness", "Brightness", "sun", -100, 100, "", True, "factor"),
        ("contrast", "Contrast", "contrast", -100, 100, "", True, "factor"),
        ("highlights", "Highlights", "sun", -100, 100, "", True, "int"),
        ("shadows", "Shadows", "contrast", -100, 100, "", True, "int"),
    ],
    "colour": [
        ("saturation", "Saturation", "droplet", -100, 100, "", True, "factor"),
        ("warmth", "Warmth", "sun", -100, 100, "", True, "int"),
        ("tint", "Tint", "droplet", -100, 100, "", True, "int"),
        ("hue", "Hue", "palette", -180, 180, "°", True, "int"),
    ],
    "effects": [
        ("sharpness", "Sharpness", "filter", -100, 100, "", True, "factor"),
        ("blur", "Blur", "filter", 0, 100, "", False, "int"),
        ("vignette", "Vignette", "filter", 0, 100, "", False, "int"),
    ],
}
TOGGLES = (("grayscale", "Black && white"), ("sepia", "Sepia"), ("invert", "Invert colours"))
FILTER_THUMB = 60


def _to_factor(value: int) -> float:
    return round(1.0 + value / 100.0, 3)


def _from_factor(factor: float) -> int:
    return int(round((factor - 1.0) * 100))


class AdjustPanel(QWidget):
    """Emits ``adjustments_changed(Adjustments, interactive)`` and ``action_requested(name)``."""

    adjustments_changed = Signal(object, bool)
    action_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._active_filter = "none"
        self._sliders: dict[str, tuple[LabeledSlider, str]] = {}
        self._toggles: dict[str, QCheckBox] = {}

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)
        self._hint = label("Open an image or create a canvas to start editing.", "Caption", wrap=True)
        layout.addWidget(self._hint)

        self._content = QWidget()
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(14)
        layout.addWidget(self._content)

        content.addWidget(self._build_filters())
        content.addWidget(self._build_transform())
        light = CollapsibleSection("Light")
        self._add_sliders(light, "light")
        content.addWidget(light)
        colour = CollapsibleSection("Colour")
        self._add_sliders(colour, "colour")
        content.addWidget(colour)
        effects = CollapsibleSection("Effects")
        self._add_sliders(effects, "effects")
        toggles = QGridLayout()
        toggles.setHorizontalSpacing(12)
        toggles.setVerticalSpacing(8)
        for index, (key, text) in enumerate(TOGGLES):
            box = QCheckBox(text)
            box.setCursor(Qt.CursorShape.PointingHandCursor)
            box.toggled.connect(lambda _v: self._on_manual_change(final=True))
            self._toggles[key] = box
            toggles.addWidget(box, index // 2, index % 2)
        effects.addLayout(toggles)
        content.addWidget(effects)

        reset = make_button("Reset Adjustments", None, "reset", "Return every adjustment and filter to neutral")
        reset.clicked.connect(lambda: self.action_requested.emit("reset_adjustments"))
        content.addWidget(reset)

        content.addWidget(self._build_sizes())
        restore = CollapsibleSection("Restore", expanded=False)
        reset_image = make_button("Reset All Image Edits", "danger", "reset",
                                  "Restore the originally imported image (text layers are kept)")
        reset_image.clicked.connect(lambda: self.action_requested.emit("reset_image"))
        restore.addWidget(reset_image)
        restore.addWidget(label("Restores the original image you opened. Text layers are kept and the "
                                "action can be undone.", "Caption", wrap=True))
        content.addWidget(restore)
        layout.addStretch(1)

        self._final_timer = QTimer(self)
        self._final_timer.setSingleShot(True)
        self._final_timer.setInterval(160)
        self._final_timer.timeout.connect(lambda: self._on_manual_change(final=True))
        self.set_document_available(False)

    # ------------------------------------------------------------------ building

    def _build_filters(self) -> CollapsibleSection:
        section = CollapsibleSection("Filters")
        grid = QGridLayout()
        grid.setSpacing(6)
        self._filter_group = QButtonGroup(self)
        self._filter_group.setExclusive(True)
        self._filter_buttons: dict[str, QToolButton] = {}
        for index, (key, (name, _values)) in enumerate(FILTER_PRESETS.items()):
            tile = QToolButton()
            tile.setObjectName("FilterTile")
            tile.setCheckable(True)
            tile.setText(name)
            tile.setToolTip(f"Apply the {name} filter")
            tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tile.setIconSize(QSize(FILTER_THUMB, FILTER_THUMB))
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            tile.clicked.connect(lambda _c=False, k=key: self._apply_filter(k))
            self._filter_group.addButton(tile)
            self._filter_buttons[key] = tile
            grid.addWidget(tile, index // 4, index % 4)
        self._filter_buttons["none"].setChecked(True)
        section.addLayout(grid)
        return section

    def _build_transform(self) -> CollapsibleSection:
        section = CollapsibleSection("Transform")
        grid = QGridLayout()
        grid.setSpacing(8)
        self.tool_buttons: dict[str, QToolButton] = {}
        for index, (key, text, icon_name, tip) in enumerate(TRANSFORM_TOOLS):
            button = QToolButton()
            button.setObjectName("ToolTile")
            button.setText(text)
            set_icon(button, icon_name, hover="strong")
            button.setIconSize(QSize(20, 20))
            button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setMinimumHeight(58)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _c=False, k=key: self.action_requested.emit(k))
            self.tool_buttons[key] = button
            grid.addWidget(button, index // 4, index % 4)
        section.addLayout(grid)
        return section

    def _build_sizes(self) -> CollapsibleSection:
        section = CollapsibleSection("Social media sizes", expanded=False)
        section.addWidget(label("Resize the canvas to a preset. You can choose crop-to-fill or padding.",
                                "Caption", wrap=True))
        grid = QGridLayout()
        grid.setSpacing(8)
        for index, preset in enumerate(SIZE_PRESETS):
            button = make_button(f"{preset.ratio}  {preset.name}", "chip", tooltip=f"{preset.width} × {preset.height} px")
            button.clicked.connect(lambda _c=False, k=preset.key: self.action_requested.emit(f"preset:{k}"))
            grid.addWidget(button, index // 2, index % 2)
        section.addLayout(grid)
        return section

    def _add_sliders(self, section: CollapsibleSection, group: str) -> None:
        for key, name, icon_name, low, high, suffix, signed, kind in SLIDERS[group]:
            slider = LabeledSlider(name, icon_name, minimum=low, maximum=high, default=0,
                                   suffix=suffix, signed=signed)
            slider.valueChanged.connect(lambda _v: self._on_manual_change(final=False))
            slider.sliderReleased.connect(lambda: self._on_manual_change(final=True))
            self._sliders[key] = (slider, kind)
            section.addWidget(slider)

    # ------------------------------------------------------------------ state

    def current(self) -> Adjustments:
        values: dict = {}
        for key, (slider, kind) in self._sliders.items():
            values[key] = _to_factor(slider.value()) if kind == "factor" else int(slider.value())
        for key, box in self._toggles.items():
            values[key] = box.isChecked()
        return Adjustments(filter_name=self._active_filter, **values)

    def set_adjustments(self, adjustments: Adjustments) -> None:
        """Show ``adjustments`` without emitting change signals."""
        self._final_timer.stop()
        for key, (slider, kind) in self._sliders.items():
            value = getattr(adjustments, key)
            slider.setValue(_from_factor(value) if kind == "factor" else int(value), emit=False)
        for key, box in self._toggles.items():
            box.blockSignals(True)
            box.setChecked(bool(getattr(adjustments, key)))
            box.blockSignals(False)
        self._active_filter = adjustments.filter_name
        self._show_filter(adjustments.filter_name)

    def _show_filter(self, key: str) -> None:
        button = self._filter_buttons.get(key)
        if button is not None:
            button.setChecked(True)
        else:  # custom values: no tile selected
            self._filter_group.setExclusive(False)
            for tile in self._filter_buttons.values():
                tile.setChecked(False)
            self._filter_group.setExclusive(True)

    def set_document_available(self, available: bool) -> None:
        self._content.setEnabled(available)
        self._hint.setVisible(not available)

    def set_filter_source(self, image: Image.Image | None) -> None:
        """Render each filter tile as a thumbnail of the current image."""
        if image is None:
            for button in self._filter_buttons.values():
                button.setIcon(QIcon())
            return
        thumb = fit_to_size(image.convert("RGB") if image.mode not in ("RGB", "RGBA") else image,
                            FILTER_THUMB * 2, FILTER_THUMB * 2, "fill")
        for key, button in self._filter_buttons.items():
            preview = apply_adjustments(thumb, filter_adjustments(key))
            pixmap = QPixmap.fromImage(pil_to_qimage(preview))
            pixmap.setDevicePixelRatio(2)
            button.setIcon(QIcon(pixmap))

    # ------------------------------------------------------------------ signals

    def _apply_filter(self, key: str) -> None:
        values = filter_adjustments(key)
        self.set_adjustments(values)
        self.adjustments_changed.emit(values, False)

    def _on_manual_change(self, final: bool) -> None:
        if self._active_filter != "custom":
            self._active_filter = "custom"
            self._show_filter("custom")
        adjustments = self.current()
        if final:
            self._final_timer.stop()
            self.adjustments_changed.emit(replace(adjustments), False)
            return
        dragging = any(slider.isSliderDown() for slider, _kind in self._sliders.values())
        if dragging:
            self.adjustments_changed.emit(adjustments, True)
        else:
            self._final_timer.start()
