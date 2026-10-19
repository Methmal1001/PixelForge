"""Reusable themed widgets: toasts, segmented control, sliders, colour picker."""

from __future__ import annotations

from PySide6.QtCore import (
    QEasingCurve,
    QEvent,
    QObject,
    QPoint,
    QPropertyAnimation,
    QSize,
    Qt,
    QTimer,
    Signal,
)
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import (
    QButtonGroup,
    QColorDialog,
    QFrame,
    QGraphicsDropShadowEffect,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QSlider,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ui.icons import pixmap, set_icon, set_pixmap
from ui.styles import resolve, section_font

# --------------------------------------------------------------------------- helpers


def make_button(
    text: str,
    variant: str | None = None,
    icon_name: str | None = None,
    tooltip: str | None = None,
    icon_color: str | None = None,
) -> QPushButton:
    button = QPushButton(text)
    if variant:
        button.setProperty("variant", variant)
    if icon_name:
        if icon_color is None:
            icon_color = {"primary": "on_accent", "danger": "danger"}.get(variant or "", "text_dim")
        set_icon(button, icon_name, icon_color, hover="on_accent" if variant == "primary" else None)
        button.setIconSize(QSize(16, 16))
    if tooltip:
        button.setToolTip(tooltip)
    button.setCursor(Qt.CursorShape.PointingHandCursor)
    return button


def section_title(text: str) -> QLabel:
    label = QLabel(text.upper())
    label.setObjectName("SectionTitle")
    label.setFont(section_font())
    return label


def label(text: str, object_name: str | None = None, wrap: bool = False) -> QLabel:
    widget = QLabel(text)
    if object_name:
        widget.setObjectName(object_name)
    widget.setWordWrap(wrap)
    return widget


def divider() -> QFrame:
    line = QFrame()
    line.setObjectName("Divider")
    line.setFixedHeight(1)
    return line


def add_shadow(widget: QWidget, blur: int = 36, alpha: int = 150, offset: int = 10) -> None:
    effect = QGraphicsDropShadowEffect(widget)
    effect.setBlurRadius(blur)
    effect.setColor(QColor(0, 0, 0, alpha))
    effect.setOffset(0, offset)
    widget.setGraphicsEffect(effect)


def confirm(parent: QWidget, title: str, text: str, confirm_text: str, informative: str = "") -> bool:
    """Themed confirmation dialog for destructive actions."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setIcon(QMessageBox.Icon.Warning)
    box.setText(f"<b>{text}</b>")
    if informative:
        box.setInformativeText(informative)
    ok = box.addButton(confirm_text, QMessageBox.ButtonRole.AcceptRole)
    ok.setProperty("variant", "danger")
    cancel = box.addButton("Cancel", QMessageBox.ButtonRole.RejectRole)
    box.setDefaultButton(cancel)
    box.exec()
    return box.clickedButton() is ok


# --------------------------------------------------------------------------- toast

_TOAST_KINDS = {
    "info": ("info", "accent2"),
    "success": ("circle_check", "success"),
    "warning": ("alert", "warning"),
    "error": ("circle_x", "danger"),
}


class Toast(QFrame):
    """A single non-blocking notification card."""

    dismissed = Signal(object)

    def __init__(self, parent: QWidget, kind: str, title: str, message: str, timeout_ms: int) -> None:
        super().__init__(parent)
        self.setObjectName("Toast")
        self.setFixedWidth(380)
        icon_name, color = _TOAST_KINDS.get(kind, _TOAST_KINDS["info"])

        layout = QHBoxLayout(self)
        layout.setContentsMargins(0, 0, 10, 0)
        layout.setSpacing(12)

        strip = QFrame()
        strip.setStyleSheet(f"background: {resolve(color)}; border-radius: 2px; margin: 10px 0 10px 8px;")
        strip.setFixedWidth(12)
        layout.addWidget(strip)

        icon_label = QLabel()
        icon_label.setPixmap(pixmap(icon_name, color, 22))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignTop)
        icon_label.setContentsMargins(0, 14, 0, 0)
        layout.addWidget(icon_label)

        text_box = QVBoxLayout()
        text_box.setContentsMargins(0, 12, 0, 12)
        text_box.setSpacing(3)
        title_label = QLabel(title)
        title_label.setObjectName("ToastTitle")
        title_label.setWordWrap(True)
        message_label = QLabel(message)
        message_label.setObjectName("ToastMessage")
        message_label.setWordWrap(True)
        text_box.addWidget(title_label)
        if message:
            text_box.addWidget(message_label)
        layout.addLayout(text_box, 1)

        close = QToolButton()
        set_icon(close, "x")
        close.setIconSize(QSize(14, 14))
        close.setCursor(Qt.CursorShape.PointingHandCursor)
        close.clicked.connect(self.dismiss)
        layout.addWidget(close, 0, Qt.AlignmentFlag.AlignTop | Qt.AlignmentFlag.AlignRight)
        close.setContentsMargins(0, 8, 0, 0)

        add_shadow(self, blur=40, alpha=170, offset=12)
        self._closing = False
        QTimer.singleShot(timeout_ms, self.dismiss)

    def dismiss(self) -> None:
        if self._closing:
            return
        self._closing = True
        animation = QPropertyAnimation(self, b"pos", self)
        animation.setDuration(220)
        animation.setEasingCurve(QEasingCurve.Type.InCubic)
        animation.setEndValue(self.pos() + QPoint(self.width() + 40, 0))
        animation.finished.connect(lambda: self.dismissed.emit(self))
        animation.start()


class ToastManager(QObject):
    """Stacks toasts in the top-right corner of a host widget."""

    MARGIN = 20
    SPACING = 10

    def __init__(self, host: QWidget) -> None:
        super().__init__(host)
        self._host = host
        self._toasts: list[Toast] = []
        host.installEventFilter(self)

    def show(self, kind: str, title: str, message: str = "", timeout_ms: int = 4500) -> None:
        toast = Toast(self._host, kind, title, message, timeout_ms)
        toast.dismissed.connect(self._remove)
        toast.adjustSize()
        self._toasts.insert(0, toast)
        while len(self._toasts) > 4:
            self._toasts[-1].dismiss()
            self._toasts.pop()
        toast.move(self._host.width(), self.MARGIN)
        toast.show()
        toast.raise_()
        self._layout(animate=toast)

    def _remove(self, toast: Toast) -> None:
        if toast in self._toasts:
            self._toasts.remove(toast)
        toast.deleteLater()
        self._layout()

    def _layout(self, animate: Toast | None = None) -> None:
        y = self.MARGIN
        for toast in self._toasts:
            if toast._closing:
                continue
            target = QPoint(self._host.width() - toast.width() - self.MARGIN, y)
            if toast is animate:
                animation = QPropertyAnimation(toast, b"pos", toast)
                animation.setDuration(280)
                animation.setEasingCurve(QEasingCurve.Type.OutCubic)
                animation.setEndValue(target)
                animation.start()
            else:
                toast.move(target)
            toast.raise_()
            y += toast.height() + self.SPACING

    def eventFilter(self, watched: QObject, event: QEvent) -> bool:
        if watched is self._host and event.type() == QEvent.Type.Resize:
            self._layout()
        return False


# --------------------------------------------------------------------------- controls


class SegmentedControl(QFrame):
    """Pill-style exclusive tab buttons."""

    currentChanged = Signal(int)

    def __init__(self, items: list[tuple[str, str | None]], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Segmented")
        layout = QHBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        for index, (text, icon_name) in enumerate(items):
            button = make_button(text, "segment", icon_name)
            button.setCheckable(True)
            self._group.addButton(button, index)
            layout.addWidget(button, 1)
        self._group.button(0).setChecked(True)
        self._group.idClicked.connect(self.currentChanged)

    def currentIndex(self) -> int:
        return self._group.checkedId()

    def setCurrentIndex(self, index: int, emit: bool = True) -> None:
        button = self._group.button(index)
        if button is None or button.isChecked():
            return
        button.setChecked(True)
        if emit:
            self.currentChanged.emit(index)


class LabeledSlider(QWidget):
    """A -100…100 slider with an icon, name and live value readout."""

    valueChanged = Signal(int)
    sliderReleased = Signal()

    def __init__(self, name: str, icon_name: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)

        header = QHBoxLayout()
        header.setSpacing(8)
        icon_label = QLabel()
        set_pixmap(icon_label, icon_name, "text_dim", 16)
        header.addWidget(icon_label)
        header.addWidget(QLabel(name))
        header.addStretch(1)
        self._value_label = QLabel("0")
        self._value_label.setObjectName("StatusText")
        header.addWidget(self._value_label)
        layout.addLayout(header)

        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(-100, 100)
        self.slider.setPageStep(10)
        self.slider.setCursor(Qt.CursorShape.PointingHandCursor)
        self.slider.setToolTip(f"Drag to adjust {name.lower()}. Double-click the value to reset.")
        self.slider.valueChanged.connect(self._on_value)
        self.slider.sliderReleased.connect(self.sliderReleased)
        layout.addWidget(self.slider)
        self._value_label.mouseDoubleClickEvent = lambda _e: self.slider.setValue(0)

    def _on_value(self, value: int) -> None:
        self._value_label.setText(f"{value:+d}" if value else "0")
        self.valueChanged.emit(value)

    def value(self) -> int:
        return self.slider.value()

    def setValue(self, value: int, emit: bool = True) -> None:
        self.slider.blockSignals(not emit)
        self.slider.setValue(value)
        self.slider.blockSignals(False)
        self._value_label.setText(f"{value:+d}" if value else "0")

    def isSliderDown(self) -> bool:
        return self.slider.isSliderDown()


def swatch_icon(color: str, size: int = 18) -> QIcon:
    image = QPixmap(size * 3, size * 3)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.setPen(QColor(255, 255, 255, 60))
    painter.setBrush(QColor(color))
    painter.drawEllipse(2, 2, size * 3 - 4, size * 3 - 4)
    painter.end()
    image.setDevicePixelRatio(3)
    return QIcon(image)


class ColorButton(QPushButton):
    """Shows the current colour and opens a colour dialog when clicked."""

    colorChanged = Signal(str)

    def __init__(self, color: str = "#FFFFFF", title: str = "Choose colour", parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._title = title
        self._color = color
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setIconSize(QSize(18, 18))
        self.clicked.connect(self._choose)
        self._refresh()

    def color(self) -> str:
        return self._color

    def setColor(self, color: str, emit: bool = False) -> None:
        self._color = QColor(color).name().upper()
        self._refresh()
        if emit:
            self.colorChanged.emit(self._color)

    def _refresh(self) -> None:
        self.setIcon(swatch_icon(self._color))
        self.setText(f"  {self._color.upper()}")

    def _choose(self) -> None:
        chosen = QColorDialog.getColor(QColor(self._color), self.window(), self._title)
        if chosen.isValid():
            self.setColor(chosen.name(), emit=True)
