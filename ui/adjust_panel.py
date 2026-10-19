"""Right-panel tab with transform tools, colour adjustments and size presets."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtWidgets import QCheckBox, QGridLayout, QSizePolicy, QToolButton, QVBoxLayout, QWidget

from models.design import Adjustments
from models.presets import SIZE_PRESETS
from ui.icons import set_icon
from ui.widgets import LabeledSlider, divider, label, make_button, section_title

TRANSFORM_TOOLS = (
    ("crop", "Crop", "crop", "Select an area to keep (C)"),
    ("resize", "Resize", "resize", "Change the canvas size in pixels"),
    ("rotate_left", "Rotate L", "rotate_left", "Rotate 90° counter-clockwise"),
    ("rotate_right", "Rotate R", "rotate_right", "Rotate 90° clockwise"),
    ("flip_h", "Flip H", "flip_h", "Mirror horizontally"),
    ("flip_v", "Flip V", "flip_v", "Mirror vertically"),
)


def _factor(slider_value: int) -> float:
    return round(1.0 + slider_value / 100.0, 3)


def _slider_value(factor: float) -> int:
    return int(round((factor - 1.0) * 100))


class AdjustPanel(QWidget):
    """Emits ``adjustments_changed(Adjustments, interactive)`` and ``action_requested(name)``."""

    adjustments_changed = Signal(object, bool)
    action_requested = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        self._hint = label("Open an image or create a canvas to start editing.", "Caption", wrap=True)
        layout.addWidget(self._hint)

        self._content = QWidget()
        content = QVBoxLayout(self._content)
        content.setContentsMargins(0, 0, 0, 0)
        content.setSpacing(12)
        layout.addWidget(self._content)

        content.addWidget(section_title("Transform"))
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
            button.setMinimumHeight(62)
            button.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
            button.clicked.connect(lambda _c=False, k=key: self.action_requested.emit(k))
            self.tool_buttons[key] = button
            grid.addWidget(button, index // 3, index % 3)
        content.addLayout(grid)

        content.addWidget(divider())
        content.addWidget(section_title("Adjustments"))
        self.brightness = LabeledSlider("Brightness", "sun")
        self.contrast = LabeledSlider("Contrast", "contrast")
        self.saturation = LabeledSlider("Saturation", "droplet")
        for slider in (self.brightness, self.contrast, self.saturation):
            slider.valueChanged.connect(self._on_slider_changed)
            slider.sliderReleased.connect(self._emit_final)
            content.addWidget(slider)
        self.grayscale = QCheckBox("Black && white (grayscale)")
        self.grayscale.setCursor(Qt.CursorShape.PointingHandCursor)
        self.grayscale.toggled.connect(lambda _v: self._emit_final())
        content.addWidget(self.grayscale)
        reset_adjustments = make_button("Reset Adjustments", None, "reset",
                                        "Return brightness, contrast, saturation and grayscale to neutral")
        reset_adjustments.clicked.connect(lambda: self.action_requested.emit("reset_adjustments"))
        content.addWidget(reset_adjustments)

        content.addWidget(divider())
        content.addWidget(section_title("Social media sizes"))
        content.addWidget(label("Resize the canvas to a preset. You can choose crop-to-fill or padding.",
                                "Caption", wrap=True))
        presets = QGridLayout()
        presets.setSpacing(8)
        for index, preset in enumerate(SIZE_PRESETS):
            button = make_button(f"{preset.ratio}  {preset.name}", "chip",
                                 tooltip=f"{preset.width} × {preset.height} px")
            button.clicked.connect(lambda _c=False, k=preset.key: self.action_requested.emit(f"preset:{k}"))
            presets.addWidget(button, index // 2, index % 2)
        content.addLayout(presets)

        content.addWidget(divider())
        content.addWidget(section_title("Restore"))
        reset_image = make_button("Reset All Image Edits", "danger", "reset",
                                  "Restore the originally imported image (text layers are kept)")
        reset_image.clicked.connect(lambda: self.action_requested.emit("reset_image"))
        content.addWidget(reset_image)
        content.addWidget(label("Restores the original image you opened. Text layers are kept and "
                                "the action can be undone.", "Caption", wrap=True))
        layout.addStretch(1)

        self._final_timer = QTimer(self)
        self._final_timer.setSingleShot(True)
        self._final_timer.setInterval(160)
        self._final_timer.timeout.connect(self._emit_final)
        self.set_document_available(False)

    # ------------------------------------------------------------------ state

    def current(self) -> Adjustments:
        return Adjustments(
            brightness=_factor(self.brightness.value()),
            contrast=_factor(self.contrast.value()),
            saturation=_factor(self.saturation.value()),
            grayscale=self.grayscale.isChecked(),
        )

    def set_adjustments(self, adjustments: Adjustments) -> None:
        self._final_timer.stop()
        self.brightness.setValue(_slider_value(adjustments.brightness), emit=False)
        self.contrast.setValue(_slider_value(adjustments.contrast), emit=False)
        self.saturation.setValue(_slider_value(adjustments.saturation), emit=False)
        self.grayscale.blockSignals(True)
        self.grayscale.setChecked(adjustments.grayscale)
        self.grayscale.blockSignals(False)

    def set_document_available(self, available: bool) -> None:
        self._content.setEnabled(available)
        self._hint.setVisible(not available)

    # ------------------------------------------------------------------ signals

    def _on_slider_changed(self, _value: int) -> None:
        dragging = any(s.isSliderDown() for s in (self.brightness, self.contrast, self.saturation))
        if dragging:
            self.adjustments_changed.emit(self.current(), True)
        else:
            self._final_timer.start()

    def _emit_final(self) -> None:
        self._final_timer.stop()
        self.adjustments_changed.emit(self.current(), False)
