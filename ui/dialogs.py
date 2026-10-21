"""Modal dialogs: new design, resize, exact crop and export options."""

from __future__ import annotations

from PySide6.QtCore import QRect, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDialog,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QSlider,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from models.design import Adjustments
from models.presets import SIZE_PRESETS, SizePreset
from services.image_processor import CANVAS_BACKGROUNDS, MAX_DIMENSION, ImageProcessingError, validate_dimensions
from ui.styles import COLORS
from ui.widgets import ColorButton, LabeledSlider, SegmentedControl, label, make_button, section_title

FIT_MODE_LABELS = {
    "fill": "Crop to fill (no distortion)",
    "fit": "Fit inside (add padding)",
    "stretch": "Stretch to size",
}


def _spin(maximum: int = MAX_DIMENSION, suffix: str = " px", minimum: int = 1) -> QSpinBox:
    spin = QSpinBox()
    spin.setRange(minimum, maximum)
    spin.setSuffix(suffix)
    spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
    spin.setAccelerated(True)
    spin.setMinimumWidth(110)
    return spin


def ratio_icon(width: int, height: int, size: int = 44) -> QIcon:
    """Icon showing a rectangle with the given aspect ratio."""
    scale = 3
    image = QPixmap(size * scale, size * scale)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    box = size * scale * 0.82
    factor = box / max(width, height)
    w, h = width * factor, height * factor
    rect = QRectF((size * scale - w) / 2, (size * scale - h) / 2, w, h)
    painter.setPen(QColor(COLORS["accent_hover"]))
    accent = QColor(COLORS["accent"])
    accent.setAlpha(60)
    painter.setBrush(accent)
    painter.drawRoundedRect(rect.adjusted(3, 3, -3, -3), 10, 10)
    painter.end()
    image.setDevicePixelRatio(scale)
    return QIcon(image)


class StyledDialog(QDialog):
    """Dialog with a title, subtitle, content area and Cancel / primary buttons."""

    def __init__(self, parent: QWidget | None, title: str, subtitle: str, accept_text: str) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setModal(True)
        self.setMinimumWidth(480)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(26, 22, 26, 22)
        outer.setSpacing(14)
        outer.addWidget(label(title, "H2"))
        if subtitle:
            outer.addWidget(label(subtitle, "Muted", wrap=True))
        self.body = QVBoxLayout()
        self.body.setSpacing(12)
        outer.addLayout(self.body)
        self.error = label("", "ErrorText", wrap=True)
        self.error.hide()
        outer.addWidget(self.error)
        buttons = QHBoxLayout()
        buttons.addStretch(1)
        cancel = make_button("Cancel", "ghost")
        cancel.clicked.connect(self.reject)
        self.accept_button = make_button(accept_text, "primary")
        self.accept_button.setDefault(True)
        self.accept_button.clicked.connect(self._try_accept)
        buttons.addWidget(cancel)
        buttons.addWidget(self.accept_button)
        outer.addLayout(buttons)

    def show_error(self, message: str) -> None:
        self.error.setText(message)
        self.error.show()

    def validate(self) -> str | None:
        """Return an error message, or None when the input is valid."""
        return None

    def _try_accept(self) -> None:
        message = self.validate()
        if message:
            self.show_error(message)
        else:
            self.accept()


class NewDesignDialog(StyledDialog):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, "New Design", "Choose a canvas size and background.", "Create Canvas")
        self.setMinimumWidth(620)
        self.body.addWidget(section_title("Canvas size"))
        tiles = QHBoxLayout()
        tiles.setSpacing(8)
        self._group = QButtonGroup(self)
        self._presets: dict[int, SizePreset | None] = {}
        options: list[SizePreset | None] = [*SIZE_PRESETS, None]
        for index, preset in enumerate(options):
            tile = QToolButton()
            tile.setObjectName("PresetTile")
            tile.setCheckable(True)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tile.setIconSize(QSize(44, 44))
            tile.setMinimumSize(104, 104)
            if preset:
                tile.setIcon(ratio_icon(preset.width, preset.height))
                tile.setText(f"{preset.name}\n{preset.width} × {preset.height}")
            else:
                tile.setIcon(ratio_icon(3, 2))
                tile.setText("Custom\nany size")
            self._group.addButton(tile, index)
            self._presets[index] = preset
            tiles.addWidget(tile)
        self.body.addLayout(tiles)

        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        self.width_spin = _spin()
        self.height_spin = _spin()
        size_row.addWidget(label("Width", "Muted"))
        size_row.addWidget(self.width_spin)
        size_row.addSpacing(10)
        size_row.addWidget(label("Height", "Muted"))
        size_row.addWidget(self.height_spin)
        size_row.addStretch(1)
        self.body.addLayout(size_row)

        self.body.addWidget(section_title("Background"))
        self.background = QComboBox()
        for key, name in CANVAS_BACKGROUNDS.items():
            self.background.addItem(name, key)
        self.body.addWidget(self.background)

        self._group.idClicked.connect(self._on_tile)
        self._group.button(0).setChecked(True)
        self._on_tile(0)

    def _on_tile(self, index: int) -> None:
        preset = self._presets[index]
        custom = preset is None
        self.width_spin.setEnabled(custom)
        self.height_spin.setEnabled(custom)
        if preset:
            self.width_spin.setValue(preset.width)
            self.height_spin.setValue(preset.height)

    def validate(self) -> str | None:
        try:
            validate_dimensions(self.width_spin.value(), self.height_spin.value())
        except ImageProcessingError as exc:
            return str(exc)
        return None

    def values(self) -> tuple[int, int, str]:
        return self.width_spin.value(), self.height_spin.value(), self.background.currentData()


class ResizeDialog(StyledDialog):
    def __init__(self, parent: QWidget | None, width: int, height: int, preset_key: str | None = None) -> None:
        super().__init__(parent, "Resize Canvas", f"Current size: {width} × {height} px", "Resize")
        self._source = (width, height)
        self._syncing = False

        self.preset = QComboBox()
        self.preset.addItem("Custom size", None)
        for preset in SIZE_PRESETS:
            self.preset.addItem(preset.label, preset.key)
        self.body.addWidget(section_title("Preset"))
        self.body.addWidget(self.preset)

        self.body.addWidget(section_title("Dimensions"))
        row = QHBoxLayout()
        row.setSpacing(8)
        self.width_spin = _spin()
        self.width_spin.setValue(width)
        self.height_spin = _spin()
        self.height_spin.setValue(height)
        row.addWidget(label("Width", "Muted"))
        row.addWidget(self.width_spin)
        row.addSpacing(10)
        row.addWidget(label("Height", "Muted"))
        row.addWidget(self.height_spin)
        row.addStretch(1)
        self.body.addLayout(row)
        self.keep_aspect = QCheckBox("Maintain aspect ratio")
        self.keep_aspect.setChecked(True)
        self.body.addWidget(self.keep_aspect)

        self.body.addWidget(section_title("When the aspect ratio changes"))
        self.mode = QComboBox()
        for key, text in FIT_MODE_LABELS.items():
            self.mode.addItem(text, key)
        self.body.addWidget(self.mode)
        self.summary = label("", "Caption")
        self.body.addWidget(self.summary)

        self.width_spin.valueChanged.connect(self._on_width)
        self.height_spin.valueChanged.connect(self._on_height)
        self.keep_aspect.toggled.connect(self._update_state)
        self.preset.currentIndexChanged.connect(self._on_preset)
        if preset_key:
            index = self.preset.findData(preset_key)
            if index >= 0:
                self.preset.setCurrentIndex(index)
        self._update_state()

    def _on_preset(self, _index: int) -> None:
        key = self.preset.currentData()
        preset = next((p for p in SIZE_PRESETS if p.key == key), None)
        if preset is None:
            return
        self._syncing = True
        self.keep_aspect.setChecked(False)
        self.width_spin.setValue(preset.width)
        self.height_spin.setValue(preset.height)
        self.mode.setCurrentIndex(self.mode.findData("fill"))
        self._syncing = False
        self._update_state()

    def _on_width(self, value: int) -> None:
        if self.keep_aspect.isChecked() and not self._syncing:
            self._syncing = True
            self.height_spin.setValue(max(1, round(value * self._source[1] / self._source[0])))
            self._syncing = False
        self._mark_custom()
        self._update_state()

    def _on_height(self, value: int) -> None:
        if self.keep_aspect.isChecked() and not self._syncing:
            self._syncing = True
            self.width_spin.setValue(max(1, round(value * self._source[0] / self._source[1])))
            self._syncing = False
        self._mark_custom()
        self._update_state()

    def _mark_custom(self) -> None:
        if self._syncing:
            return
        key = self.preset.currentData()
        preset = next((p for p in SIZE_PRESETS if p.key == key), None)
        if preset and (preset.width, preset.height) != (self.width_spin.value(), self.height_spin.value()):
            self.preset.blockSignals(True)
            self.preset.setCurrentIndex(0)
            self.preset.blockSignals(False)

    def _update_state(self) -> None:
        w, h = self.width_spin.value(), self.height_spin.value()
        src_w, src_h = self._source
        ratio_changed = abs(w / h - src_w / src_h) > 0.005
        self.mode.setEnabled(ratio_changed)
        self.summary.setText(f"{src_w} × {src_h} px  →  {w} × {h} px")

    def validate(self) -> str | None:
        try:
            validate_dimensions(self.width_spin.value(), self.height_spin.value())
        except ImageProcessingError as exc:
            return str(exc)
        return None

    def values(self) -> tuple[int, int, str]:
        mode = self.mode.currentData() if self.mode.isEnabled() else "stretch"
        return self.width_spin.value(), self.height_spin.value(), mode


class CropDialog(StyledDialog):
    RATIOS = (("Free", None), ("1:1", (1, 1)), ("4:5", (4, 5)), ("9:16", (9, 16)), ("16:9", (16, 9)))

    def __init__(self, parent: QWidget | None, image_width: int, image_height: int, rect: QRect) -> None:
        super().__init__(parent, "Crop to Exact Values",
                         f"Image size: {image_width} × {image_height} px. Values are in pixels.", "Apply Crop")
        self._size = (image_width, image_height)
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(8)
        self.left = _spin(image_width - 1, minimum=0)
        self.top = _spin(image_height - 1, minimum=0)
        self.width_spin = _spin(image_width)
        self.height_spin = _spin(image_height)
        for spin, value in ((self.left, rect.left()), (self.top, rect.top()),
                            (self.width_spin, rect.width()), (self.height_spin, rect.height())):
            spin.setValue(value)
        grid.addWidget(label("Left (X)", "Muted"), 0, 0)
        grid.addWidget(self.left, 0, 1)
        grid.addWidget(label("Top (Y)", "Muted"), 0, 2)
        grid.addWidget(self.top, 0, 3)
        grid.addWidget(label("Width", "Muted"), 1, 0)
        grid.addWidget(self.width_spin, 1, 1)
        grid.addWidget(label("Height", "Muted"), 1, 2)
        grid.addWidget(self.height_spin, 1, 3)
        self.body.addLayout(grid)

        self.body.addWidget(section_title("Centered aspect ratio"))
        ratios = QHBoxLayout()
        ratios.setSpacing(6)
        for name, ratio in self.RATIOS:
            chip = make_button(name, "chip")
            chip.clicked.connect(lambda _c=False, r=ratio: self._apply_ratio(r))
            ratios.addWidget(chip)
        ratios.addStretch(1)
        self.body.addLayout(ratios)

    def _apply_ratio(self, ratio: tuple[int, int] | None) -> None:
        img_w, img_h = self._size
        if ratio is None:
            w, h = img_w, img_h
        else:
            rw, rh = ratio
            w = img_w
            h = round(w * rh / rw)
            if h > img_h:
                h = img_h
                w = round(h * rw / rh)
        self.left.setValue((img_w - w) // 2)
        self.top.setValue((img_h - h) // 2)
        self.width_spin.setValue(w)
        self.height_spin.setValue(h)

    def validate(self) -> str | None:
        img_w, img_h = self._size
        if self.left.value() + self.width_spin.value() > img_w:
            return f"Left + width must not exceed the image width ({img_w} px)."
        if self.top.value() + self.height_spin.value() > img_h:
            return f"Top + height must not exceed the image height ({img_h} px)."
        return None

    def values(self) -> QRect:
        return QRect(self.left.value(), self.top.value(), self.width_spin.value(), self.height_spin.value())


class RegionAdjustDialog(StyledDialog):
    """Adjust only the selected area, with a live preview on the canvas."""

    SLIDERS = (("brightness", "Brightness", "factor"), ("contrast", "Contrast", "factor"),
               ("saturation", "Saturation", "factor"), ("warmth", "Warmth", "int"), ("hue", "Hue", "hue"))

    def __init__(self, parent: QWidget | None, on_preview) -> None:
        super().__init__(parent, "Adjust Selected Area",
                         "Changes apply only inside the selection. The canvas shows a live preview.", "Apply")
        self._on_preview = on_preview
        self._sliders: dict[str, tuple[LabeledSlider, str]] = {}
        for key, name, kind in self.SLIDERS:
            low, high, suffix = (-180, 180, "°") if kind == "hue" else (-100, 100, "")
            slider = LabeledSlider(name, None, minimum=low, maximum=high, default=0, suffix=suffix)
            slider.valueChanged.connect(lambda _v: self._on_preview(self.values()))
            self._sliders[key] = (slider, kind)
            self.body.addWidget(slider)

    def values(self) -> Adjustments:
        values = {}
        for key, (slider, kind) in self._sliders.items():
            values[key] = round(1 + slider.value() / 100, 3) if kind == "factor" else int(slider.value())
        return Adjustments(**values)


class ExportDialog(StyledDialog):
    def __init__(self, parent: QWidget | None, width: int, height: int, has_transparency: bool) -> None:
        super().__init__(parent, "Export Design",
                         "Exports the image with all text layers. The app interface is never included.",
                         "Choose Location & Export…")
        self.setMinimumWidth(520)
        self._canvas = (width, height)

        self.body.addWidget(section_title("Format"))
        self.format = SegmentedControl([("PNG", None), ("JPEG", None)])
        self.body.addWidget(self.format)
        self.png_note = label(
            "PNG is lossless. Transparency in your design is preserved." if has_transparency
            else "PNG is lossless — best for graphics with text.", "Caption", wrap=True)
        self.body.addWidget(self.png_note)

        self.body.addWidget(section_title("Output size"))
        self.size = QComboBox()
        self.size.addItem(f"Canvas size ({width} × {height})", "canvas")
        for preset in SIZE_PRESETS:
            self.size.addItem(preset.label, preset.key)
        self.size.addItem("Custom size", "custom")
        self.body.addWidget(self.size)
        row = QHBoxLayout()
        row.setSpacing(8)
        self.width_spin = _spin()
        self.height_spin = _spin()
        row.addWidget(label("Width", "Muted"))
        row.addWidget(self.width_spin)
        row.addSpacing(10)
        row.addWidget(label("Height", "Muted"))
        row.addWidget(self.height_spin)
        row.addStretch(1)
        self.body.addLayout(row)
        self.mode = QComboBox()
        for key, text in FIT_MODE_LABELS.items():
            self.mode.addItem(text, key)
        self.body.addWidget(self.mode)

        self.jpeg_box = QWidget()
        jpeg = QVBoxLayout(self.jpeg_box)
        jpeg.setContentsMargins(0, 0, 0, 0)
        jpeg.setSpacing(8)
        quality_head = QHBoxLayout()
        quality_head.addWidget(section_title("JPEG quality"))
        quality_head.addStretch(1)
        self.quality_label = QLabel("92")
        self.quality_label.setObjectName("StatusText")
        quality_head.addWidget(self.quality_label)
        jpeg.addLayout(quality_head)
        self.quality = QSlider(Qt.Orientation.Horizontal)
        self.quality.setRange(1, 100)
        self.quality.setValue(92)
        self.quality.valueChanged.connect(lambda v: self.quality_label.setText(str(v)))
        jpeg.addWidget(self.quality)
        jpeg.addWidget(section_title("Background for transparent areas"))
        self.background = ColorButton("#FFFFFF", "JPEG background colour")
        jpeg.addWidget(self.background)
        self.body.addWidget(self.jpeg_box)

        self.summary = label("", "H3")
        self.body.addWidget(self.summary)

        self.format.currentChanged.connect(lambda _i: self._update_state())
        self.size.currentIndexChanged.connect(self._on_size)
        self.width_spin.valueChanged.connect(lambda _v: self._update_state())
        self.height_spin.valueChanged.connect(lambda _v: self._update_state())
        self._on_size(0)

    def image_format(self) -> str:
        return "PNG" if self.format.currentIndex() == 0 else "JPEG"

    def _on_size(self, _index: int) -> None:
        key = self.size.currentData()
        custom = key == "custom"
        self.width_spin.setEnabled(custom)
        self.height_spin.setEnabled(custom)
        if key == "canvas":
            w, h = self._canvas
        elif not custom:
            preset = next(p for p in SIZE_PRESETS if p.key == key)
            w, h = preset.width, preset.height
        else:
            w, h = self.width_spin.value(), self.height_spin.value()
        self.width_spin.setValue(w)
        self.height_spin.setValue(h)
        self._update_state()

    def _update_state(self) -> None:
        is_jpeg = self.image_format() == "JPEG"
        self.jpeg_box.setVisible(is_jpeg)
        self.png_note.setVisible(not is_jpeg)
        w, h = self.width_spin.value(), self.height_spin.value()
        canvas_w, canvas_h = self._canvas
        self.mode.setEnabled(abs(w / h - canvas_w / canvas_h) > 0.005)
        self.summary.setText(f"Output: {w} × {h} px · {self.image_format()}")
        self.adjustSize()

    def validate(self) -> str | None:
        try:
            validate_dimensions(self.width_spin.value(), self.height_spin.value())
        except ImageProcessingError as exc:
            return str(exc)
        return None

    def values(self) -> dict:
        return {
            "image_format": self.image_format(),
            "width": self.width_spin.value(),
            "height": self.height_spin.value(),
            "fit_mode": self.mode.currentData() if self.mode.isEnabled() else "stretch",
            "quality": self.quality.value(),
            "background": self.background.color(),
        }
