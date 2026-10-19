"""Left navigation sidebar with the PixelForge wordmark."""

from __future__ import annotations

from PySide6.QtCore import QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

from app_info import APP_STAGE, APP_VERSION
from ui.icons import set_icon
from ui.styles import COLORS, section_font

NAV_ITEMS = (
    ("new", "New Design", "plus_square", "Start a new design or return to the studio"),
    ("projects", "My Projects", "folder", "Saved projects (planned for Stage 3)"),
    ("recent", "Recent Designs", "clock", "Recently edited designs (planned for Stage 3)"),
    ("templates", "Templates", "template", "Ready-made layouts (planned for Stage 3)"),
    ("history", "Generation History", "history", "Past AI generations (browser planned for Stage 3)"),
)
SYSTEM_ITEMS = (
    ("settings", "Settings", "settings", "Colour theme (Dark / Light / System) and preferences"),
    ("about", "About", "info", "About PixelForge AI Studio"),
)


def paint_logo(painter: QPainter, rect: QRectF) -> None:
    """Draw the PixelForge mark: a gradient tile with a pixel 'P' and a spark."""
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    gradient = QLinearGradient(rect.topLeft(), rect.bottomRight())
    gradient.setColorAt(0, QColor(COLORS["accent"]))
    gradient.setColorAt(1, QColor(COLORS["accent2"]))
    path = QPainterPath()
    path.addRoundedRect(rect, rect.width() * 0.28, rect.width() * 0.28)
    painter.fillPath(path, gradient)

    unit = rect.width() / 7
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor("#FFFFFF"))
    cells = [(2, 1), (3, 1), (4, 1), (2, 2), (5, 2), (2, 3), (3, 3), (4, 3), (2, 4), (2, 5)]
    for cx, cy in cells:
        painter.drawRoundedRect(
            QRectF(rect.left() + cx * unit, rect.top() + cy * unit, unit * 0.92, unit * 0.92),
            unit * 0.2, unit * 0.2,
        )
    painter.setBrush(QColor(255, 255, 255, 170))
    sx, sy, s = rect.left() + 5.1 * unit, rect.top() + 4.6 * unit, unit * 0.75
    spark = QPainterPath()
    spark.moveTo(sx, sy - s)
    spark.quadTo(sx, sy, sx + s, sy)
    spark.quadTo(sx, sy, sx, sy + s)
    spark.quadTo(sx, sy, sx - s, sy)
    spark.quadTo(sx, sy, sx, sy - s)
    painter.drawPath(spark)


def logo_pixmap(size: int = 256) -> QPixmap:
    image = QPixmap(size, size)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    paint_logo(painter, QRectF(0, 0, size, size))
    painter.end()
    return image


class LogoMark(QWidget):
    def __init__(self, size: int = 36, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(size, size)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        paint_logo(painter, QRectF(self.rect()))
        painter.end()


class Sidebar(QFrame):
    """Emits ``navigate(key)`` when a navigation item is clicked."""

    navigate = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("Sidebar")
        self.setFixedWidth(232)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(3)

        brand = QHBoxLayout()
        brand.setContentsMargins(6, 0, 0, 10)
        brand.setSpacing(11)
        brand.addWidget(LogoMark(38))
        words = QVBoxLayout()
        words.setSpacing(0)
        title = QLabel("PixelForge")
        title.setObjectName("Wordmark")
        subtitle = QLabel("AI STUDIO")
        subtitle.setObjectName("WordmarkSub")
        subtitle.setFont(section_font(10))
        words.addWidget(title)
        words.addWidget(subtitle)
        brand.addLayout(words)
        brand.addStretch(1)
        layout.addLayout(brand)

        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._buttons: dict[str, QPushButton] = {}

        layout.addWidget(self._section("Workspace"))
        for item in NAV_ITEMS:
            layout.addWidget(self._nav_button(*item))
        layout.addStretch(1)
        layout.addWidget(self._section("System"))
        for item in SYSTEM_ITEMS:
            layout.addWidget(self._nav_button(*item))

        layout.addSpacing(12)
        layout.addWidget(self._status_card())
        self.set_current("new")

    def _section(self, text: str) -> QLabel:
        section = QLabel(text.upper())
        section.setObjectName("NavSection")
        section.setFont(section_font(10))
        return section

    def _nav_button(self, key: str, text: str, icon_name: str, tooltip: str) -> QPushButton:
        button = QPushButton(f"  {text}")
        button.setObjectName("NavButton")
        button.setCheckable(True)
        set_icon(button, icon_name, "text_dim", checked="strong")
        button.setIconSize(QSize(18, 18))
        button.setToolTip(tooltip)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        button.clicked.connect(lambda _checked=False, k=key: self.navigate.emit(k))
        self._group.addButton(button)
        self._buttons[key] = button
        return button

    def _status_card(self) -> QFrame:
        card = QFrame()
        card.setObjectName("SubtleCard")
        box = QVBoxLayout(card)
        box.setContentsMargins(12, 10, 12, 11)
        box.setSpacing(4)
        row = QHBoxLayout()
        row.setSpacing(7)
        self._ai_dot = QLabel()
        self._ai_dot.setObjectName("StatusDot")
        self._ai_dot.setFixedSize(8, 8)
        row.addWidget(self._ai_dot)
        self._ai_status = QLabel("AI provider not configured")
        self._ai_status.setObjectName("StatusText")
        row.addWidget(self._ai_status, 1)
        box.addLayout(row)
        version = QLabel(f"v{APP_VERSION} · {APP_STAGE.split(' — ')[0]}")
        version.setObjectName("Caption")
        box.addWidget(version)
        return card

    def set_ai_status(self, text: str, kind: str) -> None:
        self._ai_status.setText(text)
        self._ai_status.setToolTip(text)
        self._ai_dot.setProperty("kind", kind)
        self._ai_dot.style().unpolish(self._ai_dot)
        self._ai_dot.style().polish(self._ai_dot)

    def set_current(self, key: str) -> None:
        button = self._buttons.get(key)
        if button:
            button.setChecked(True)
