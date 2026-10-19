"""Right-panel tab for adding and styling text overlays."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QFontComboBox,
    QHBoxLayout,
    QPlainTextEdit,
    QSpinBox,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from models.design import TextElement
from ui.icons import set_icon
from ui.widgets import ColorButton, divider, label, make_button, section_title, swatch_icon

SWATCHES = ("#FFFFFF", "#111318", "#7C5CFF", "#4F7CFF", "#38D9F5", "#2FD08F", "#F5B544", "#FF5C7A")
ALIGNMENTS = (("left", "align_left", "Align left"), ("center", "align_center", "Align center"),
              ("right", "align_right", "Align right"))


def _style_button(icon_name: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setCheckable(True)
    set_icon(button, icon_name)
    button.setIconSize(QSize(18, 18))
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedSize(38, 36)
    return button


class TextPanel(QWidget):
    """Emits ``properties_changed(dict)`` with TextElement field changes."""

    add_requested = Signal()
    delete_requested = Signal()
    properties_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        self.add_button = make_button("Add Text Layer", "primary", "text", "Add a new text layer (Ctrl+T)")
        self.add_button.setMinimumHeight(40)
        self.add_button.clicked.connect(self.add_requested)
        layout.addWidget(self.add_button)

        self._hint = label("Select a text layer on the canvas, or add a new one. "
                           "Text stays editable until you export.", "Caption", wrap=True)
        layout.addWidget(self._hint)

        self._editor = QWidget()
        editor = QVBoxLayout(self._editor)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setSpacing(10)
        layout.addWidget(self._editor)

        editor.addWidget(divider())
        editor.addWidget(section_title("Content"))
        self.content = QPlainTextEdit()
        self.content.setPlaceholderText("Type your text…")
        self.content.setFixedHeight(92)
        self.content.textChanged.connect(lambda: self._emit(text=self.content.toPlainText()))
        editor.addWidget(self.content)

        editor.addWidget(section_title("Font"))
        self.font_combo = QFontComboBox()
        self.font_combo.setEditable(False)
        self.font_combo.setMaxVisibleItems(14)
        self.font_combo.currentFontChanged.connect(lambda f: self._emit(font_family=f.family()))
        editor.addWidget(self.font_combo)

        size_row = QHBoxLayout()
        size_row.setSpacing(8)
        size_row.addWidget(label("Size", "Muted"))
        self.size_spin = QSpinBox()
        self.size_spin.setRange(6, 1000)
        self.size_spin.setSuffix(" px")
        self.size_spin.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.size_spin.setAccelerated(True)
        self.size_spin.setToolTip("Font size in image pixels. Use the mouse wheel or arrow keys.")
        self.size_spin.valueChanged.connect(lambda v: self._emit(font_size=v))
        size_row.addWidget(self.size_spin, 1)
        for delta, name in ((-4, "Smaller"), (4, "Larger")):
            step = make_button("−" if delta < 0 else "+", None, tooltip=f"{name} text")
            step.setFixedWidth(40)
            step.clicked.connect(lambda _c=False, d=delta: self.size_spin.setValue(self.size_spin.value() + d))
            size_row.addWidget(step)
        editor.addLayout(size_row)

        editor.addWidget(section_title("Style & alignment"))
        style_row = QHBoxLayout()
        style_row.setSpacing(6)
        self.bold = _style_button("bold", "Bold")
        self.bold.toggled.connect(lambda v: self._emit(bold=v))
        self.italic = _style_button("italic", "Italic")
        self.italic.toggled.connect(lambda v: self._emit(italic=v))
        style_row.addWidget(self.bold)
        style_row.addWidget(self.italic)
        style_row.addSpacing(12)
        self._align_group = QButtonGroup(self)
        self._align_group.setExclusive(True)
        self._align_buttons: dict[str, QToolButton] = {}
        for key, icon_name, tip in ALIGNMENTS:
            button = _style_button(icon_name, tip)
            self._align_group.addButton(button)
            self._align_buttons[key] = button
            button.clicked.connect(lambda _c=False, k=key: self._emit(align=k))
            style_row.addWidget(button)
        style_row.addStretch(1)
        editor.addLayout(style_row)

        editor.addWidget(section_title("Colour"))
        self.color_button = ColorButton("#FFFFFF", "Choose text colour")
        self.color_button.colorChanged.connect(lambda c: self._emit(color=c))
        editor.addWidget(self.color_button)
        swatches = QHBoxLayout()
        swatches.setSpacing(6)
        for color in SWATCHES:
            swatch = QToolButton()
            swatch.setObjectName("Swatch")
            swatch.setIcon(swatch_icon(color, 18))
            swatch.setIconSize(QSize(18, 18))
            swatch.setFixedSize(26, 26)
            swatch.setToolTip(color)
            swatch.setCursor(Qt.CursorShape.PointingHandCursor)
            swatch.clicked.connect(lambda _c=False, col=color: self.color_button.setColor(col, emit=True))
            swatches.addWidget(swatch)
        swatches.addStretch(1)
        editor.addLayout(swatches)

        editor.addWidget(divider())
        self.delete_button = make_button("Delete Text Layer", "danger", "trash", "Remove the selected text (Delete)")
        self.delete_button.clicked.connect(self.delete_requested)
        editor.addWidget(self.delete_button)
        editor.addWidget(label("Tip: drag text on the canvas to move it. Double-click it to edit the content.",
                               "Caption", wrap=True))
        layout.addStretch(1)

        self._loading = False
        self.load_element(None)
        self.set_document_available(False)

    def set_document_available(self, available: bool) -> None:
        self.add_button.setEnabled(available)

    def load_element(self, element: TextElement | None) -> None:
        """Show ``element``'s properties without emitting change signals."""
        self._loading = True
        try:
            self._editor.setVisible(element is not None)
            self._hint.setVisible(element is None)
            if element is None:
                return
            if self.content.toPlainText() != element.text:
                self.content.setPlainText(element.text)
            self.font_combo.setCurrentFont(QFont(element.font_family))
            self.size_spin.setValue(int(element.font_size))
            self.bold.setChecked(element.bold)
            self.italic.setChecked(element.italic)
            self._align_buttons.get(element.align, self._align_buttons["left"]).setChecked(True)
            self.color_button.setColor(element.color)
        finally:
            self._loading = False

    def focus_content(self) -> None:
        self.content.setFocus()
        self.content.selectAll()

    def _emit(self, **changes) -> None:
        if not self._loading:
            self.properties_changed.emit(changes)
