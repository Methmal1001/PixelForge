"""Right-panel tab for adding and styling text layers (Canva/Photoshop-style controls)."""

from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QButtonGroup,
    QCheckBox,
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
from ui.widgets import (
    CollapsibleSection,
    ColorButton,
    LabeledSlider,
    divider,
    label,
    make_button,
    swatch_icon,
)

SWATCHES = ("#FFFFFF", "#111318", "#7C5CFF", "#4F7CFF", "#38D9F5", "#2FD08F", "#F5B544", "#FF5C7A")
ALIGNMENTS = (("left", "align_left", "Align left"), ("center", "align_center", "Align center"),
              ("right", "align_right", "Align right"))
QUICK_STYLES = (("heading", "Heading", "primary"), ("subheading", "Subheading", None), ("body", "Body text", None))
ARRANGE = (
    ("duplicate", "copy", "Duplicate this text layer (Ctrl+D)"),
    ("forward", "bring_forward", "Bring forward (above other text)"),
    ("backward", "send_backward", "Send backward (below other text)"),
    ("center_h", "center_h", "Center horizontally on the canvas"),
    ("center_v", "center_v", "Center vertically on the canvas"),
)


def _toggle_button(icon_name: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    button.setCheckable(True)
    set_icon(button, icon_name)
    button.setIconSize(QSize(18, 18))
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedSize(36, 34)
    return button


def _icon_button(icon_name: str, tooltip: str) -> QToolButton:
    button = QToolButton()
    set_icon(button, icon_name, hover="strong")
    button.setIconSize(QSize(18, 18))
    button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    button.setFixedSize(40, 36)
    return button


class TextPanel(QWidget):
    """Emits ``properties_changed(dict)`` with TextElement field changes."""

    add_requested = Signal(str)        # quick style: heading / subheading / body
    delete_requested = Signal()
    arrange_requested = Signal(str)    # duplicate / forward / backward / center_h / center_v
    properties_changed = Signal(dict)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(12)

        add_row = QHBoxLayout()
        add_row.setSpacing(6)
        self._add_buttons = []
        for key, text, variant in QUICK_STYLES:
            button = make_button(text, variant, "text" if key == "heading" else None,
                                 f"Add a {text.lower()} layer" + (" (Ctrl+T)" if key == "heading" else ""))
            button.setMinimumHeight(38)
            button.clicked.connect(lambda _c=False, k=key: self.add_requested.emit(k))
            add_row.addWidget(button, 2 if key == "heading" else 1)
            self._add_buttons.append(button)
        layout.addLayout(add_row)

        self._hint = label("Select a text layer on the canvas, or add a new one. "
                           "Text stays editable until you export.", "Caption", wrap=True)
        layout.addWidget(self._hint)

        self._editor = QWidget()
        editor = QVBoxLayout(self._editor)
        editor.setContentsMargins(0, 0, 0, 0)
        editor.setSpacing(14)
        layout.addWidget(self._editor)

        editor.addWidget(divider())
        editor.addWidget(self._build_content())
        editor.addWidget(self._build_font())
        editor.addWidget(self._build_colour())
        editor.addWidget(self._build_spacing())
        editor.addWidget(self._build_effects())
        editor.addWidget(self._build_arrange())

        self.delete_button = make_button("Delete Text Layer", "danger", "trash", "Remove the selected text (Delete)")
        self.delete_button.clicked.connect(self.delete_requested)
        editor.addWidget(self.delete_button)
        editor.addWidget(label("Tip: drag text on the canvas to move it. Double-click it to edit the content.",
                               "Caption", wrap=True))
        layout.addStretch(1)

        self.load_element(None)
        self.set_document_available(False)

    # ------------------------------------------------------------------ sections

    def _build_content(self) -> CollapsibleSection:
        section = CollapsibleSection("Content")
        self.content = QPlainTextEdit()
        self.content.setPlaceholderText("Type your text…")
        self.content.setFixedHeight(84)
        self.content.textChanged.connect(lambda: self._emit(text=self.content.toPlainText()))
        section.addWidget(self.content)
        return section

    def _build_font(self) -> CollapsibleSection:
        section = CollapsibleSection("Font")
        self.font_combo = QFontComboBox()
        self.font_combo.setEditable(False)
        self.font_combo.setMaxVisibleItems(14)
        self.font_combo.currentFontChanged.connect(lambda f: self._emit(font_family=f.family()))
        section.addWidget(self.font_combo)

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
        section.addLayout(size_row)

        style_row = QHBoxLayout()
        style_row.setSpacing(4)
        self.bold = _toggle_button("bold", "Bold")
        self.bold.toggled.connect(lambda v: self._emit(bold=v))
        self.italic = _toggle_button("italic", "Italic")
        self.italic.toggled.connect(lambda v: self._emit(italic=v))
        self.underline = _toggle_button("underline", "Underline")
        self.underline.toggled.connect(lambda v: self._emit(underline=v))
        self.uppercase = _toggle_button("case", "UPPERCASE")
        self.uppercase.toggled.connect(lambda v: self._emit(uppercase=v))
        for button in (self.bold, self.italic, self.underline, self.uppercase):
            style_row.addWidget(button)
        style_row.addSpacing(10)
        self._align_group = QButtonGroup(self)
        self._align_group.setExclusive(True)
        self._align_buttons: dict[str, QToolButton] = {}
        for key, icon_name, tip in ALIGNMENTS:
            button = _toggle_button(icon_name, tip)
            self._align_group.addButton(button)
            self._align_buttons[key] = button
            button.clicked.connect(lambda _c=False, k=key: self._emit(align=k))
            style_row.addWidget(button)
        style_row.addStretch(1)
        section.addLayout(style_row)
        return section

    def _build_colour(self) -> CollapsibleSection:
        section = CollapsibleSection("Colour")
        self.color_button = ColorButton("#FFFFFF", "Choose text colour")
        self.color_button.colorChanged.connect(lambda c: self._emit(color=c))
        section.addWidget(self.color_button)
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
        section.addLayout(swatches)
        return section

    def _slider(self, name: str, field: str, low: int, high: int, default: int, *, suffix: str = "",
                signed: bool = False, scale: float = 1.0) -> LabeledSlider:
        slider = LabeledSlider(name, None, minimum=low, maximum=high, default=default, suffix=suffix, signed=signed)
        slider.valueChanged.connect(lambda v: self._emit(**{field: v / scale}))
        slider.setProperty("scale", scale)
        return slider

    def _build_spacing(self) -> CollapsibleSection:
        section = CollapsibleSection("Spacing & layout")
        self.letter_spacing = self._slider("Letter spacing", "letter_spacing", -10, 50, 0, suffix="%", signed=True)
        self.line_height = self._slider("Line height", "line_height", 70, 250, 100, suffix="%", scale=100)
        self.opacity = self._slider("Opacity", "opacity", 0, 100, 100, suffix="%", scale=100)
        self.rotation = self._slider("Rotation", "rotation", -180, 180, 0, suffix="°", signed=True)
        for slider in (self.letter_spacing, self.line_height, self.opacity, self.rotation):
            section.addWidget(slider)
        return section

    def _effect_header(self, text: str, field: str, color_field: str, color: str) -> tuple[QCheckBox, ColorButton]:
        box = QCheckBox(text)
        box.setCursor(Qt.CursorShape.PointingHandCursor)
        box.toggled.connect(lambda v: self._emit(**{field: v}))
        button = ColorButton(color, f"{text} colour")
        button.colorChanged.connect(lambda c: self._emit(**{color_field: c}))
        return box, button

    def _build_effects(self) -> CollapsibleSection:
        section = CollapsibleSection("Effects")

        self.shadow, self.shadow_color = self._effect_header("Drop shadow", "shadow", "shadow_color", "#000000")
        self.shadow_distance = self._slider("Distance", "shadow_distance", 0, 50, 8, suffix="%")
        self.shadow_blur = self._slider("Blur", "shadow_blur", 0, 50, 10, suffix="%")
        self.shadow_opacity = self._slider("Shadow opacity", "shadow_opacity", 0, 100, 60, suffix="%", scale=100)
        self._shadow_controls = self._effect_group(section, self.shadow, self.shadow_color,
                                                   (self.shadow_distance, self.shadow_blur, self.shadow_opacity))
        section.addWidget(divider())

        self.outline, self.outline_color = self._effect_header("Outline", "outline", "outline_color", "#000000")
        self.outline_width = self._slider("Thickness", "outline_width", 1, 30, 6, suffix="%")
        self._outline_controls = self._effect_group(section, self.outline, self.outline_color, (self.outline_width,))
        section.addWidget(divider())

        self.background, self.background_color = self._effect_header(
            "Background highlight", "background", "background_color", "#7C5CFF")
        self.background_padding = self._slider("Padding", "background_padding", 0, 120, 30, suffix="%")
        self.background_radius = self._slider("Corner radius", "background_radius", 0, 100, 25, suffix="%")
        self.background_opacity = self._slider("Background opacity", "background_opacity", 0, 100, 100,
                                               suffix="%", scale=100)
        self._background_controls = self._effect_group(
            section, self.background, self.background_color,
            (self.background_padding, self.background_radius, self.background_opacity))
        return section

    def _effect_group(self, section: CollapsibleSection, box: QCheckBox, color: ColorButton,
                      sliders: tuple[LabeledSlider, ...]) -> QWidget:
        row = QHBoxLayout()
        row.addWidget(box, 1)
        row.addWidget(color)
        section.addLayout(row)
        controls = QWidget()
        inner = QVBoxLayout(controls)
        inner.setContentsMargins(26, 0, 0, 0)
        inner.setSpacing(8)
        for slider in sliders:
            inner.addWidget(slider)
        section.addWidget(controls)
        box.toggled.connect(lambda on: (controls.setEnabled(on), color.setEnabled(on)))
        return controls

    def _build_arrange(self) -> CollapsibleSection:
        section = CollapsibleSection("Arrange")
        row = QHBoxLayout()
        row.setSpacing(6)
        for key, icon_name, tip in ARRANGE:
            button = _icon_button(icon_name, tip)
            button.clicked.connect(lambda _c=False, k=key: self.arrange_requested.emit(k))
            row.addWidget(button)
        row.addStretch(1)
        section.addLayout(row)
        return section

    # ------------------------------------------------------------------ state

    def set_document_available(self, available: bool) -> None:
        for button in self._add_buttons:
            button.setEnabled(available)

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
            for button, value in ((self.bold, element.bold), (self.italic, element.italic),
                                  (self.underline, element.underline), (self.uppercase, element.uppercase)):
                button.setChecked(value)
            self._align_buttons.get(element.align, self._align_buttons["left"]).setChecked(True)
            self.color_button.setColor(element.color)
            for slider, value in (
                (self.letter_spacing, element.letter_spacing), (self.line_height, element.line_height * 100),
                (self.opacity, element.opacity * 100), (self.rotation, element.rotation),
                (self.shadow_distance, element.shadow_distance), (self.shadow_blur, element.shadow_blur),
                (self.shadow_opacity, element.shadow_opacity * 100), (self.outline_width, element.outline_width),
                (self.background_padding, element.background_padding),
                (self.background_radius, element.background_radius),
                (self.background_opacity, element.background_opacity * 100),
            ):
                slider.setValue(round(value), emit=False)
            for box, color_button, controls, on, color in (
                (self.shadow, self.shadow_color, self._shadow_controls, element.shadow, element.shadow_color),
                (self.outline, self.outline_color, self._outline_controls, element.outline, element.outline_color),
                (self.background, self.background_color, self._background_controls, element.background,
                 element.background_color),
            ):
                box.setChecked(on)
                color_button.setColor(color)
                controls.setEnabled(on)
                color_button.setEnabled(on)
        finally:
            self._loading = False

    def focus_content(self) -> None:
        self.content.setFocus()
        self.content.selectAll()

    def _emit(self, **changes) -> None:
        if not self._loading:
            self.properties_changed.emit(changes)
