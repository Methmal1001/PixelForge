"""Right-panel tab listing every layer (Photoshop-style Layers panel)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QListWidget, QListWidgetItem, QToolButton, QVBoxLayout, QWidget

from services.image_processor import make_thumbnail
from services.qt_image import pil_to_qimage
from ui.icons import pixmap, set_icon
from ui.widgets import CollapsibleSection, LabeledSlider, label, make_button

THUMB = 40
LAYER_ACTIONS = (
    ("flip", "flip_h", "Flip the layer horizontally"),
    ("duplicate", "copy", "Duplicate the layer"),
    ("up", "bring_forward", "Move the layer up"),
    ("down", "send_backward", "Move the layer down"),
    ("merge", "layers", "Merge into the background (no longer movable)"),
    ("delete", "trash", "Delete the layer (Delete)"),
)


def _icon_button(icon_name: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    set_icon(button, icon_name, hover="strong")
    button.setIconSize(QSize(18, 18))
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedSize(40, 36)
    return button


class LayersPanel(QWidget):
    item_selected = Signal(str, str)       # kind ("text" / "image" / "background"), id
    layer_changed = Signal(dict)           # property changes for the selected image layer
    layer_action = Signal(str)             # flip / duplicate / up / down / merge / delete
    add_image_requested = Signal()
    edit_text_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        self._thumbs: dict[int, QIcon] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        top = QHBoxLayout()
        self.add_image_button = make_button("Add Image…", "primary", "image",
                                            "Place a picture (e.g. a logo or product photo) as a new layer")
        self.add_image_button.clicked.connect(self.add_image_requested)
        top.addWidget(self.add_image_button, 1)
        layout.addLayout(top)
        layout.addWidget(label("Top of the list is in front. To edit part of the picture as a separate "
                               "object, use Select Area (M) → Copy to Layer or Cut to Layer.",
                               "Caption", wrap=True))

        self.list = QListWidget()
        self.list.setIconSize(QSize(THUMB, THUMB))
        self.list.setMinimumHeight(220)
        self.list.setSpacing(2)
        self.list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.list)

        self.properties = CollapsibleSection("Layer properties")
        self._title = label("", "H3")
        self.properties.addWidget(self._title)
        self.opacity = LabeledSlider("Opacity", None, minimum=0, maximum=100, default=100, suffix="%", signed=False)
        self.opacity.valueChanged.connect(lambda v: self._emit(opacity=v / 100))
        self.size = LabeledSlider("Size", None, minimum=5, maximum=400, default=100, suffix="%", signed=False)
        self.size.valueChanged.connect(lambda v: self._emit(scale=v / 100))
        self.rotation = LabeledSlider("Rotation", None, minimum=-180, maximum=180, default=0, suffix="°")
        self.rotation.valueChanged.connect(lambda v: self._emit(rotation=float(v)))
        for slider in (self.opacity, self.size, self.rotation):
            self.properties.addWidget(slider)
        actions = QHBoxLayout()
        actions.setSpacing(4)
        for key, icon_name, tip in LAYER_ACTIONS:
            button = _icon_button(icon_name, tip)
            button.clicked.connect(lambda _c=False, k=key: self.layer_action.emit(k))
            actions.addWidget(button)
        actions.addStretch(1)
        self.properties.addLayout(actions)
        self.properties.addWidget(label("Tip: drag the layer on the canvas to move it, or drag a corner handle "
                                        "to resize it.", "Caption", wrap=True))
        layout.addWidget(self.properties)

        self._text_box = QWidget()
        text_layout = QVBoxLayout(self._text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.addWidget(label("Text layers are edited in the Text tab.", "Caption", wrap=True))
        open_text = make_button("Edit in Text tab", None, "text")
        open_text.clicked.connect(self.edit_text_requested)
        text_layout.addWidget(open_text)
        layout.addWidget(self._text_box)
        layout.addStretch(1)
        self.show_properties(None)

    # ------------------------------------------------------------------ list

    def _thumbnail(self, image) -> QIcon:
        key = id(image)
        icon = self._thumbs.get(key)
        if icon is None:
            thumb = make_thumbnail(image, THUMB * 2)
            canvas = QPixmap(THUMB * 2, THUMB * 2)
            canvas.fill(QColor(60, 63, 75))
            from PySide6.QtGui import QPainter

            painter = QPainter(canvas)
            painter.drawImage((THUMB * 2 - thumb.width) // 2, (THUMB * 2 - thumb.height) // 2, pil_to_qimage(thumb))
            painter.end()
            canvas.setDevicePixelRatio(2)
            icon = QIcon(canvas)
            if len(self._thumbs) > 200:
                self._thumbs.clear()
            self._thumbs[key] = icon
        return icon

    def refresh(self, document, selected: tuple[str, str] | None) -> None:
        """Rebuild the list from ``document`` and highlight ``selected`` (kind, id)."""
        self._loading = True
        try:
            self.list.clear()
            self.add_image_button.setEnabled(document is not None)
            if document is None:
                self.show_properties(None)
                return
            rows = []
            for element in reversed(document.state.texts):
                preview = element.text.replace("\n", " ").strip() or "(empty text)"
                rows.append(("text", element.id, f"T   {preview[:34]}", QIcon(pixmap("text", "text_dim", 20))))
            for layer in reversed(document.state.layers):
                rows.append(("image", layer.id, layer.name, self._thumbnail(layer.image)))
            rows.append(("background", "", "Background", self._thumbnail(document.state.base)))
            current_row = len(rows) - 1 if selected is None else 0
            for index, (kind, item_id, text, icon) in enumerate(rows):
                item = QListWidgetItem(icon, text)
                item.setData(Qt.ItemDataRole.UserRole, (kind, item_id))
                self.list.addItem(item)
                if selected is not None and (kind, item_id) == tuple(selected):
                    current_row = index
            self.list.setCurrentRow(current_row)
            kind, item_id = rows[current_row][0], rows[current_row][1]
            layer = document.get_layer(item_id) if kind == "image" else None
            self.show_properties(layer, kind)
        finally:
            self._loading = False

    def show_properties(self, layer, kind: str = "background") -> None:
        self.properties.setVisible(layer is not None)
        self._text_box.setVisible(kind == "text")
        if layer is None:
            return
        self._loading = True
        try:
            self._title.setText(layer.name)
            self.opacity.setValue(round(layer.opacity * 100), emit=False)
            self.size.setValue(round(layer.scale * 100), emit=False)
            self.rotation.setValue(round(layer.rotation), emit=False)
        finally:
            self._loading = False

    def _on_current_changed(self, current: QListWidgetItem | None, _previous) -> None:
        if self._loading or current is None:
            return
        kind, item_id = current.data(Qt.ItemDataRole.UserRole)
        self.item_selected.emit(kind, item_id)

    def _emit(self, **changes) -> None:
        if not self._loading:
            self.layer_changed.emit(changes)
