"""Full-area pages: the canvas empty state, 'coming soon' placeholders and About."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QPointF, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPixmap, QRadialGradient
from PySide6.QtWidgets import (
    QButtonGroup,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QComboBox,
    QLabel,
    QLineEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app_info import APP_NAME, APP_STAGE, APP_VERSION
from models.presets import SIZE_PRESETS
from services.gemini_provider import IMAGE_MODELS
from services.generation_service import PROVIDERS
from services.image_processor import supported_extensions
from ui.icons import pixmap, set_pixmap
from ui.sidebar import LogoMark
from ui.styles import COLORS, DARK_COLORS, LIGHT_COLORS, THEME_MODES, is_dark
from ui.widgets import label, make_button, section_title


def dropped_image_path(mime_data) -> str | None:
    """Return the first supported local image file in a drag payload."""
    if not mime_data.hasUrls():
        return None
    for url in mime_data.urls():
        if url.isLocalFile():
            path = url.toLocalFile()
            if Path(path).suffix.lower() in supported_extensions():
                return path
    return None


def _paint_backdrop(widget: QWidget, painter: QPainter) -> None:
    rect = widget.rect()
    painter.fillRect(rect, QColor(COLORS["canvas"]))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.setBrush(QColor(255, 255, 255, 16) if is_dark() else QColor(20, 24, 40, 26))
    step = 24
    for x in range(step // 2, rect.width(), step):
        for y in range(step // 2, rect.height(), step):
            painter.drawEllipse(QPointF(x, y), 1.0, 1.0)
    glow = QRadialGradient(QPointF(rect.center()), max(rect.width(), rect.height()) * 0.45)
    glow.setColorAt(0, QColor(124, 92, 255, 48))
    glow.setColorAt(0.5, QColor(79, 124, 255, 14))
    glow.setColorAt(1, QColor(0, 0, 0, 0))
    painter.fillRect(rect, glow)


class HeroArt(QWidget):
    """Layered 'canvas cards' illustration for the empty state."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setFixedSize(150, 116)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        cards = [
            (QRectF(14, 22, 78, 78), -9, QColor(79, 124, 255, 70)),
            (QRectF(58, 18, 78, 78), 8, QColor(124, 92, 255, 80)),
        ]
        for rect, angle, color in cards:
            painter.save()
            painter.translate(rect.center())
            painter.rotate(angle)
            painter.translate(-rect.center())
            painter.setPen(QColor(COLORS["border_strong"]))
            painter.setBrush(color)
            painter.drawRoundedRect(rect, 14, 14)
            painter.restore()
        front = QRectF(37, 12, 78, 90)
        painter.setPen(QColor(COLORS["border_strong"]))
        painter.setBrush(QColor(COLORS["bg2"]))
        painter.drawRoundedRect(front, 16, 16)
        painter.drawPixmap(front.center().toPoint() - QPointF(17, 17).toPoint(), pixmap("image", "strong", 34))
        painter.end()


class EmptyState(QWidget):
    """Welcome screen shown on the canvas when no design is open."""

    open_requested = Signal()
    new_requested = Signal()
    sample_requested = Signal()
    preset_requested = Signal(str)
    file_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setAcceptDrops(True)
        outer = QVBoxLayout(self)
        outer.addStretch(1)

        column = QVBoxLayout()
        column.setSpacing(10)
        column.setAlignment(Qt.AlignmentFlag.AlignHCenter)
        hero = HeroArt()
        column.addWidget(hero, 0, Qt.AlignmentFlag.AlignHCenter)
        column.addSpacing(6)

        title = label("Start creating something remarkable", "H1")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(title)
        subtitle = label(
            "Open an image to edit, start from a social-media size, or explore the sample layout.\n"
            "Or describe a design in the AI Generate panel to create one with Google Gemini.",
            "Muted",
        )
        subtitle.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(subtitle)
        column.addSpacing(10)

        buttons = QHBoxLayout()
        buttons.setSpacing(10)
        buttons.addStretch(1)
        open_button = make_button("Open Image", "primary", "upload", "Open a PNG, JPEG or WebP image (Ctrl+O)")
        open_button.setMinimumHeight(40)
        open_button.clicked.connect(self.open_requested)
        new_button = make_button("New Blank Canvas", None, "plus", "Create an empty canvas (Ctrl+N)")
        new_button.setMinimumHeight(40)
        new_button.clicked.connect(self.new_requested)
        sample_button = make_button(
            "Load Sample Design", None, "wand", "Open locally drawn placeholder artwork with editable text"
        )
        sample_button.setMinimumHeight(40)
        sample_button.clicked.connect(self.sample_requested)
        for button in (open_button, new_button, sample_button):
            buttons.addWidget(button)
        buttons.addStretch(1)
        column.addLayout(buttons)
        column.addSpacing(18)

        sizes_title = section_title("Quick-start sizes")
        sizes_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(sizes_title)
        chips = QHBoxLayout()
        chips.setSpacing(8)
        chips.addStretch(1)
        for preset in SIZE_PRESETS:
            chip = make_button(f"{preset.ratio}  {preset.name}", "chip",
                               tooltip=f"New {preset.width} × {preset.height} px canvas")
            chip.clicked.connect(lambda _c=False, key=preset.key: self.preset_requested.emit(key))
            chips.addWidget(chip)
        chips.addStretch(1)
        column.addLayout(chips)
        column.addSpacing(16)

        hint = label("Tip: drag and drop an image file anywhere on this area to open it.", "Caption")
        hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        column.addWidget(hint)

        outer.addLayout(column)
        outer.addStretch(1)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        _paint_backdrop(self, painter)
        painter.end()

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if dropped_image_path(event.mimeData()):
            event.acceptProposedAction()

    def dropEvent(self, event) -> None:  # noqa: N802
        path = dropped_image_path(event.mimeData())
        if path:
            event.acceptProposedAction()
            self.file_dropped.emit(path)


class ComingSoonPage(QWidget):
    """Informational page for navigation items planned for later stages."""

    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(1)

        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(560)
        box = QVBoxLayout(card)
        box.setContentsMargins(34, 30, 34, 30)
        box.setSpacing(12)

        self._icon = QLabel()
        box.addWidget(self._icon)
        self._badge = label("", "Badge")
        box.addWidget(self._badge, 0, Qt.AlignmentFlag.AlignLeft)
        self._title = label("", "H1")
        box.addWidget(self._title)
        self._description = label("", "Muted", wrap=True)
        box.addWidget(self._description)
        self._bullets = QVBoxLayout()
        self._bullets.setSpacing(6)
        box.addLayout(self._bullets)
        box.addSpacing(8)
        back = make_button("Back to Studio", "primary", "arrow_left")
        back.clicked.connect(self.back_requested)
        box.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card, 10)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    def set_content(self, icon_name: str, title: str, stage: str, description: str, bullets: list[str]) -> None:
        set_pixmap(self._icon, icon_name, "accent_hover", 40)
        self._badge.setText(stage)
        self._title.setText(title)
        self._description.setText(description)
        while self._bullets.count():
            item = self._bullets.takeAt(0)
            if item.layout():
                while item.layout().count():
                    child = item.layout().takeAt(0)
                    if child.widget():
                        child.widget().deleteLater()
        for text in bullets:
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel()
            set_pixmap(dot, "check", "accent_hover", 15)
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label(text, "Muted", wrap=True), 1)
            self._bullets.addLayout(row)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        _paint_backdrop(self, painter)
        painter.end()


class AboutPage(QWidget):
    back_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        card = QFrame()
        card.setObjectName("Card")
        card.setMaximumWidth(620)
        box = QVBoxLayout(card)
        box.setContentsMargins(34, 30, 34, 30)
        box.setSpacing(12)

        head = QHBoxLayout()
        head.setSpacing(16)
        head.addWidget(LogoMark(64))
        names = QVBoxLayout()
        names.setSpacing(2)
        names.addWidget(label(APP_NAME, "H1"))
        names.addWidget(label(f"Version {APP_VERSION} · {APP_STAGE}", "Muted"))
        head.addLayout(names, 1)
        box.addLayout(head)
        box.addSpacing(4)
        box.addWidget(label(
            "A desktop studio for social-media posts, advertisements and promotional graphics. "
            "Stage 1 delivers the editor: open images, transform and colour-correct them, add "
            "editable text and export at social-media sizes.",
            "Muted", wrap=True,
        ))

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(8)
        rows = [
            ("Image editor", "Available", "BadgeAccent"),
            ("Text overlays & export", "Available", "BadgeAccent"),
            ("AI image generation", "Google Gemini (your API key)", "BadgeAccent"),
            ("Projects, templates & history", "Stage 3", "Badge"),
        ]
        for row, (name, status, style) in enumerate(rows):
            grid.addWidget(label(name, "H3"), row, 0)
            grid.addWidget(label(status, style), row, 1, Qt.AlignmentFlag.AlignLeft)
        grid.setColumnStretch(1, 1)
        box.addLayout(grid)
        box.addWidget(label("Built with Python 3.12 · PySide6 (Qt 6) · Pillow. No API key required.", "Caption"))
        box.addSpacing(6)
        back = make_button("Back to Studio", "primary", "arrow_left")
        back.clicked.connect(self.back_requested)
        box.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)

        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(card, 10)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        _paint_backdrop(self, painter)
        painter.end()


def theme_preview_icon(mode: str, width: int = 120, height: int = 76) -> QIcon:
    """A miniature app window drawn in the given theme ("system" is split diagonally)."""
    scale = 3
    image = QPixmap(width * scale, height * scale)
    image.fill(Qt.GlobalColor.transparent)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    painter.scale(scale, scale)
    frame = QRectF(1, 1, width - 2, height - 2)

    def draw(colors: dict[str, str]) -> None:
        painter.setPen(QColor(colors["border_strong"]))
        painter.setBrush(QColor(colors["bg0"]))
        painter.drawRoundedRect(frame, 9, 9)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(colors["bg1"]))
        painter.drawRoundedRect(QRectF(5, 5, 26, height - 10), 5, 5)
        painter.setBrush(QColor(colors["accent"]))
        painter.drawRoundedRect(QRectF(9, 11, 18, 5), 2, 2)
        painter.setBrush(QColor(colors["text_muted"]))
        for i in range(3):
            painter.drawRoundedRect(QRectF(9, 22 + i * 9, 14, 3), 1.5, 1.5)
        painter.setBrush(QColor(colors["canvas"]))
        painter.drawRoundedRect(QRectF(36, 14, width - 66, height - 24), 5, 5)
        painter.setBrush(QColor(colors["accent2"]))
        painter.drawRoundedRect(QRectF(44, 24, width - 82, height - 44), 4, 4)
        painter.setBrush(QColor(colors["bg1"]))
        painter.drawRoundedRect(QRectF(width - 26, 5, 21, height - 10), 5, 5)
        painter.setBrush(QColor(colors["strong"]))
        painter.drawRoundedRect(QRectF(36, 6, 30, 4), 2, 2)

    if mode == "system":
        draw(LIGHT_COLORS)
        clip = QPainterPath()
        clip.moveTo(width * 0.62, 0)
        clip.lineTo(width, 0)
        clip.lineTo(width, height)
        clip.lineTo(width * 0.38, height)
        clip.closeSubpath()
        painter.setClipPath(clip)
        draw(DARK_COLORS)
    else:
        draw(DARK_COLORS if mode == "dark" else LIGHT_COLORS)
    painter.end()
    image.setDevicePixelRatio(scale)
    return QIcon(image)


class SettingsPage(QWidget):
    """Preferences: colour theme (Dark / Light / System) and AI provider status."""

    back_requested = Signal()
    theme_selected = Signal(str)
    provider_saved = Signal(str, str, str)           # provider, api key ("" keeps saved key), model
    provider_test_requested = Signal(str, str, str)  # provider, api key ("" uses saved key), model
    provider_removed = Signal()

    DESCRIPTIONS = {
        "dark": "Charcoal studio theme — easy on the eyes for long sessions.",
        "light": "Bright, clean theme for well-lit rooms.",
        "system": "Follows your Windows light/dark setting automatically.",
    }

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        outer = QVBoxLayout(self)
        outer.addStretch(1)
        column = QVBoxLayout()
        column.setSpacing(16)

        head = QHBoxLayout()
        head.setSpacing(12)
        gear = QLabel()
        set_pixmap(gear, "settings", "accent_hover", 30)
        head.addWidget(gear)
        head.addWidget(label("Settings", "H1"))
        head.addStretch(1)
        column.addLayout(head)

        appearance = QFrame()
        appearance.setObjectName("Card")
        box = QVBoxLayout(appearance)
        box.setContentsMargins(26, 22, 26, 24)
        box.setSpacing(12)
        set_title = QHBoxLayout()
        palette_icon = QLabel()
        set_pixmap(palette_icon, "palette", "accent_hover", 20)
        set_title.addWidget(palette_icon)
        set_title.addWidget(label("Appearance", "H2"))
        set_title.addStretch(1)
        box.addLayout(set_title)
        box.addWidget(label("Choose the colour theme for the whole application. "
                            "Your choice is saved and used the next time you open PixelForge.",
                            "Muted", wrap=True))
        box.addWidget(section_title("Colour theme"))

        tiles = QHBoxLayout()
        tiles.setSpacing(12)
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._tiles: dict[str, QToolButton] = {}
        for mode, name in THEME_MODES.items():
            tile = QToolButton()
            tile.setObjectName("PresetTile")
            tile.setCheckable(True)
            tile.setCursor(Qt.CursorShape.PointingHandCursor)
            tile.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonTextUnderIcon)
            tile.setIcon(theme_preview_icon(mode))
            tile.setIconSize(QSize(120, 76))
            tile.setText(name)
            tile.setToolTip(self.DESCRIPTIONS[mode])
            tile.setMinimumSize(150, 120)
            tile.clicked.connect(lambda _c=False, m=mode: self.theme_selected.emit(m))
            self._group.addButton(tile)
            self._tiles[mode] = tile
            tiles.addWidget(tile)
        tiles.addStretch(1)
        box.addLayout(tiles)
        self._theme_note = label("", "Caption", wrap=True)
        box.addWidget(self._theme_note)
        column.addWidget(appearance)

        provider = QFrame()
        provider.setObjectName("Card")
        pbox = QVBoxLayout(provider)
        pbox.setContentsMargins(26, 20, 26, 22)
        pbox.setSpacing(10)
        prow = QHBoxLayout()
        sparkle = QLabel()
        set_pixmap(sparkle, "sparkles", "accent_hover", 20)
        prow.addWidget(sparkle)
        prow.addWidget(label("AI provider", "H2"))
        prow.addStretch(1)
        self._provider_badge = label("", "Badge")
        prow.addWidget(self._provider_badge)
        pbox.addLayout(prow)

        pbox.addWidget(section_title("Provider"))
        self.provider_combo = QComboBox()
        for provider_id, provider_name in PROVIDERS.items():
            self.provider_combo.addItem(provider_name, provider_id)
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        pbox.addWidget(self.provider_combo)

        # --- Gemini fields
        self._gemini_box = QWidget()
        gbox = QVBoxLayout(self._gemini_box)
        gbox.setContentsMargins(0, 4, 0, 0)
        gbox.setSpacing(10)
        gbox.addWidget(label("Paste a Google AI Studio API key (aistudio.google.com/apikey). It is stored "
                             "only in the local .env file, which is excluded from git. Image generation "
                             "needs billing enabled on the key's project.", "Muted", wrap=True))
        gbox.addWidget(section_title("API key"))
        key_row = QHBoxLayout()
        key_row.setSpacing(8)
        self.key_edit = QLineEdit()
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.key_edit.setClearButtonEnabled(True)
        key_row.addWidget(self.key_edit, 1)
        self._show_key = make_button("Show", "ghost")
        self._show_key.setCheckable(True)
        self._show_key.toggled.connect(self._toggle_key_visibility)
        key_row.addWidget(self._show_key)
        gbox.addLayout(key_row)
        gbox.addWidget(section_title("Image model"))
        self.model_combo = QComboBox()
        for model_id, model_name in IMAGE_MODELS.items():
            self.model_combo.addItem(f"{model_name}  ·  {model_id}", model_id)
        gbox.addWidget(self.model_combo)
        pbox.addWidget(self._gemini_box)

        # --- Pollinations notes
        self._pollinations_box = QWidget()
        nbox = QVBoxLayout(self._pollinations_box)
        nbox.setContentsMargins(0, 4, 0, 0)
        nbox.setSpacing(6)
        nbox.addWidget(label("Free and anonymous: no account or API key is needed or sent.", "Muted", wrap=True))
        for text in ("Only your prompt text and the image size are sent to Pollinations.ai, a public "
                     "third-party service. Avoid confidential details in prompts.",
                     "Free limit: one image every 45 seconds. Images are lower resolution and carry a "
                     "small “pollinations.ai” watermark.",
                     "Reference images are not sent to Pollinations."):
            row = QHBoxLayout()
            row.setSpacing(8)
            dot = QLabel()
            set_pixmap(dot, "info", "text_muted", 14)
            row.addWidget(dot, 0, Qt.AlignmentFlag.AlignTop)
            row.addWidget(label(text, "Caption", wrap=True), 1)
            nbox.addLayout(row)
        pbox.addWidget(self._pollinations_box)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        save = make_button("Save", "primary", "check")
        save.clicked.connect(lambda: self.provider_saved.emit(
            self.provider_combo.currentData(), self.key_edit.text().strip(), self.model_combo.currentData()))
        self.test_button = make_button("Test Connection", None, "sparkles",
                                       "Check the provider is reachable (generates no image)")
        self.test_button.clicked.connect(lambda: self.provider_test_requested.emit(
            self.provider_combo.currentData(), self.key_edit.text().strip(), self.model_combo.currentData()))
        self.remove_button = make_button("Remove Gemini Key", "danger", "trash")
        self.remove_button.clicked.connect(self.provider_removed)
        actions.addWidget(save)
        actions.addWidget(self.test_button)
        actions.addStretch(1)
        actions.addWidget(self.remove_button)
        pbox.addLayout(actions)
        self._provider_note = label("", "Caption", wrap=True)
        pbox.addWidget(self._provider_note)
        column.addWidget(provider)

        back = make_button("Back to Studio", "primary", "arrow_left")
        back.clicked.connect(self.back_requested)
        column.addWidget(back, 0, Qt.AlignmentFlag.AlignLeft)

        holder = QWidget()
        holder.setLayout(column)
        holder.setMaximumWidth(640)
        row = QHBoxLayout()
        row.addStretch(1)
        row.addWidget(holder, 10)
        row.addStretch(1)
        outer.addLayout(row)
        outer.addStretch(2)

    def set_current(self, mode: str, effective: str) -> None:
        tile = self._tiles.get(mode)
        if tile:
            tile.setChecked(True)
        note = self.DESCRIPTIONS.get(mode, "")
        if mode == "system":
            note += f" Windows is currently using the {effective} theme."
        self._theme_note.setText(note)

    def paintEvent(self, event) -> None:  # noqa: N802
        painter = QPainter(self)
        _paint_backdrop(self, painter)
        painter.end()

    def _toggle_key_visibility(self, visible: bool) -> None:
        self.key_edit.setEchoMode(QLineEdit.EchoMode.Normal if visible else QLineEdit.EchoMode.Password)
        self._show_key.setText("Hide" if visible else "Show")

    def _on_provider_changed(self, _index: int = 0) -> None:
        gemini = self.provider_combo.currentData() == "gemini"
        self._gemini_box.setVisible(gemini)
        self._pollinations_box.setVisible(not gemini)
        self.remove_button.setVisible(gemini)

    def set_provider_state(self, provider: str, masked_key: str, model: str, note: str = "") -> None:
        """Show the active provider, whether a Gemini key is saved (masked) and the model."""
        index = self.provider_combo.findData(provider if provider in PROVIDERS else "pollinations")
        self.provider_combo.setCurrentIndex(max(0, index))
        self._on_provider_changed()
        self.key_edit.clear()
        self.key_edit.setPlaceholderText(
            f"Saved key {masked_key} — paste a new key to replace it" if masked_key
            else "Paste your Google AI Studio API key")
        if provider == "pollinations":
            badge, style = "Active: Pollinations", "BadgeAccent"
        elif provider == "gemini" and masked_key:
            badge, style = "Active: Gemini", "BadgeAccent"
        else:
            badge, style = "Not configured", "Badge"
        self._provider_badge.setObjectName(style)
        self._provider_badge.setText(badge)
        self._provider_badge.style().unpolish(self._provider_badge)
        self._provider_badge.style().polish(self._provider_badge)
        self.remove_button.setEnabled(bool(masked_key))
        self.model_combo.setCurrentIndex(max(0, self.model_combo.findData(model)))
        self.set_provider_note(note)

    def set_provider_note(self, note: str) -> None:
        self._provider_note.setText(note)
        self._provider_note.setVisible(bool(note))

