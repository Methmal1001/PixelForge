"""Creative-studio themes (dark and light): colour tokens and the application stylesheet."""

from __future__ import annotations

from string import Template

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

FONT_FAMILY = "Segoe UI"

DARK_COLORS = {
    "bg0": "#0D0E13",       # window / inputs
    "bg1": "#13151C",       # sidebar & panels
    "bg2": "#1A1D27",       # cards
    "bg3": "#222634",       # buttons / hover
    "bg4": "#2C3142",       # strong hover / slider track
    "canvas": "#0A0B0F",
    "border": "#2A2F3E",
    "border_soft": "#1E222D",
    "border_strong": "#3A4053",
    "strong": "#FFFFFF",    # headings and selected text
    "text": "#E9EBF3",
    "text_dim": "#A0A6BA",
    "text_muted": "#6C728A",
    "on_accent": "#FFFFFF",  # text/icons on accent-coloured fills
    "accent": "#7C5CFF",
    "accent_hover": "#8F74FF",
    "accent2": "#4F7CFF",
    "accent2_hover": "#6890FF",
    "success": "#2FD08F",
    "warning": "#F5B544",
    "danger": "#FF5C7A",
    "checker_a": "#2A2D38",
    "checker_b": "#353948",
}

LIGHT_COLORS = {
    "bg0": "#FFFFFF",
    "bg1": "#F5F6FA",
    "bg2": "#FFFFFF",
    "bg3": "#EDEFF5",
    "bg4": "#DFE3EC",
    "canvas": "#E8EAF1",
    "border": "#D9DDE7",
    "border_soft": "#E4E7EF",
    "border_strong": "#BFC5D3",
    "strong": "#11131C",
    "text": "#1C1F2B",
    "text_dim": "#525972",
    "text_muted": "#868CA2",
    "on_accent": "#FFFFFF",
    "accent": "#6A45FF",
    "accent_hover": "#5A36F0",
    "accent2": "#3D6BFF",
    "accent2_hover": "#2F5BEB",
    "success": "#159F6C",
    "warning": "#B97B0C",
    "danger": "#DE3356",
    "checker_a": "#FFFFFF",
    "checker_b": "#E3E6EE",
}

THEMES = {"dark": DARK_COLORS, "light": LIGHT_COLORS}
THEME_MODES = {"dark": "Dark", "light": "Light", "system": "System"}
DEFAULT_THEME_MODE = "dark"

# The active palette. Mutated in place by apply_theme so every module that
# imported COLORS sees the current theme.
COLORS: dict[str, str] = dict(DARK_COLORS)
_active = {"mode": DEFAULT_THEME_MODE, "effective": "dark"}


def resolve(color: str | None, default: str = "text_dim") -> str:
    """Map a theme token (e.g. ``"text_dim"``) or a literal colour to a hex colour."""
    color = color or default
    return COLORS.get(color, color)


def is_dark() -> bool:
    return _active["effective"] == "dark"


def active_mode() -> str:
    return _active["mode"]


def rgba(hex_color: str, alpha: float) -> str:
    """QSS rgba() with an integer 0–255 alpha."""
    c = QColor(hex_color)
    return f"rgba({c.red()}, {c.green()}, {c.blue()}, {round(alpha * 255)})"


_QSS = Template(
    """
QWidget { color: $text; }
QMainWindow, QDialog, QWidget#AppRoot { background: $bg0; }
QDialog { background: $bg1; }

/* ---------- Sidebar ---------- */
QFrame#Sidebar { background: $bg1; border-right: 1px solid $border_soft; }
QPushButton#NavButton {
    text-align: left; padding: 9px 12px; border-radius: 10px;
    background: transparent; color: $text_dim; border: 1px solid transparent;
}
QPushButton#NavButton:hover { background: $bg3; color: $text; }
QPushButton#NavButton:checked {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent_a28, stop:1 $accent2_a08);
    border: 1px solid $accent_a35; color: $strong; font-weight: 600;
}
QLabel#NavSection { color: $text_muted; padding: 14px 12px 4px 12px; }
QLabel#Wordmark { font-size: 16px; font-weight: 700; color: $strong; }
QLabel#WordmarkSub { color: $accent_hover; }

/* ---------- Panels & cards ---------- */
QFrame#Panel { background: $bg1; border-left: 1px solid $border_soft; }
QFrame#Card { background: $bg2; border: 1px solid $border; border-radius: 14px; }
QFrame#SubtleCard { background: $bg0; border: 1px solid $border_soft; border-radius: 12px; }
QFrame#CanvasFrame { background: $canvas; border: 1px solid $border_soft; border-radius: 14px; }
QFrame#Toolbar { background: $bg1; border: 1px solid $border_soft; border-radius: 12px; }
QFrame#CropBar {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent_a22, stop:1 $accent2_a10);
    border: 1px solid $accent_a45; border-radius: 12px;
}
QFrame#ToolbarSep { background: $border; }
QFrame#Divider { background: $border_soft; }

QLabel#H1 { font-size: 24px; font-weight: 700; color: $strong; }
QLabel#H2 { font-size: 16px; font-weight: 600; color: $strong; }
QLabel#H3 { font-size: 13px; font-weight: 600; color: $text; }
QLabel#Muted { color: $text_dim; }
QLabel#Caption { color: $text_muted; font-size: 11px; }
QLabel#SectionTitle { color: $text_muted; }
QLabel#StatusText { color: $text_dim; font-size: 12px; }
QLabel#ErrorText { color: $danger; font-size: 12px; }
QLabel#Badge {
    background: $warning_a12; color: $warning; border: 1px solid $warning_a35;
    border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
}
QLabel#BadgeAccent {
    background: $accent_a16; color: $accent_hover; border: 1px solid $accent_a40;
    border-radius: 9px; padding: 2px 9px; font-size: 11px; font-weight: 600;
}
QLabel#BadgeEdited {
    background: $bg3; color: $text_dim; border: 1px solid $border;
    border-radius: 9px; padding: 2px 9px; font-size: 11px;
}

/* ---------- Buttons ---------- */
QPushButton {
    background: $bg3; border: 1px solid $border; border-radius: 9px;
    padding: 8px 14px; color: $text;
}
QPushButton:hover { background: $bg4; border-color: $border_strong; }
QPushButton:pressed { background: $bg2; }
QPushButton:disabled { color: $text_muted; background: $bg2; border-color: $border_soft; }
QPushButton[variant="primary"] {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent, stop:1 $accent2);
    border: 1px solid $accent_a60; color: $on_accent; font-weight: 600;
}
QPushButton[variant="primary"]:hover {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:1, stop:0 $accent_hover, stop:1 $accent2_hover);
}
QPushButton[variant="primary"]:pressed { background: $accent; }
QPushButton[variant="primary"]:disabled { background: $bg3; color: $text_muted; border-color: $border_soft; }
QPushButton[variant="ghost"] { background: transparent; border-color: transparent; color: $text_dim; }
QPushButton[variant="ghost"]:hover { background: $bg3; color: $text; }
QPushButton[variant="danger"] { background: $danger_a10; border-color: $danger_a35; color: $danger; }
QPushButton[variant="danger"]:hover { background: $danger_a20; border-color: $danger; }
QPushButton[variant="danger"]:disabled { background: $bg2; color: $text_muted; border-color: $border_soft; }
QPushButton[variant="chip"] {
    background: $bg2; border: 1px solid $border; border-radius: 15px;
    padding: 6px 12px; color: $text_dim; font-size: 12px;
}
QPushButton[variant="chip"]:hover { border-color: $accent; color: $strong; background: $accent_a12; }
QPushButton[variant="segment"] {
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 7px 10px; color: $text_dim; font-weight: 600;
}
QPushButton[variant="segment"]:hover { color: $text; }
QPushButton[variant="segment"]:checked { background: $bg3; border-color: $border_strong; color: $strong; }
QFrame#Segmented { background: $bg0; border: 1px solid $border_soft; border-radius: 11px; }

QToolButton {
    background: transparent; border: 1px solid transparent; border-radius: 8px;
    padding: 6px; color: $text_dim;
}
QToolButton:hover { background: $bg3; border-color: $border; color: $text; }
QToolButton:pressed { background: $bg2; }
QToolButton:checked { background: $accent_a22; border-color: $accent_a55; color: $strong; }
QToolButton::menu-indicator { image: none; width: 0; }
QToolButton#ZoomButton { color: $text; font-weight: 600; padding: 6px 8px; }
QToolButton#ToolTile {
    background: $bg2; border: 1px solid $border; border-radius: 11px;
    padding: 10px 4px 8px 4px; color: $text_dim; font-size: 11px;
}
QToolButton#ToolTile:hover { border-color: $accent; color: $strong; background: $accent_a10; }
QToolButton#ToolTile:checked { border-color: $accent; color: $strong; background: $accent_a22; }
QToolButton#ToolTile:disabled { color: $text_muted; border-color: $border_soft; background: $bg1; }
QToolButton#Swatch { border-radius: 11px; padding: 0; border: 2px solid $border_strong; }
QToolButton#Swatch:hover { border-color: $strong; }

/* ---------- Inputs ---------- */
QLineEdit, QPlainTextEdit, QTextEdit, QSpinBox, QDoubleSpinBox, QComboBox {
    background: $bg0; border: 1px solid $border; border-radius: 9px;
    padding: 7px 10px; selection-background-color: $accent; selection-color: $on_accent;
}
QPlainTextEdit, QTextEdit { padding: 8px 10px; }
QLineEdit:hover, QPlainTextEdit:hover, QSpinBox:hover, QComboBox:hover { border-color: $border_strong; }
QLineEdit:focus, QPlainTextEdit:focus, QTextEdit:focus, QSpinBox:focus, QComboBox:focus { border-color: $accent; }
QLineEdit:disabled, QPlainTextEdit:disabled, QSpinBox:disabled, QComboBox:disabled {
    color: $text_muted; background: $bg1; border-color: $border_soft;
}
QComboBox { padding-right: 28px; }
QComboBox::drop-down { border: none; width: 26px; subcontrol-origin: padding; subcontrol-position: center right; }
QComboBox::down-arrow { image: url($chevron); width: 14px; height: 14px; }
QSpinBox::up-button, QSpinBox::down-button { subcontrol-origin: border; width: 0px; border: none; }
QComboBox QAbstractItemView {
    background: $bg2; border: 1px solid $border_strong; border-radius: 8px; padding: 4px;
    selection-background-color: $accent_a35; selection-color: $strong; outline: none;
}

QSlider::groove:horizontal { height: 4px; background: $bg4; border-radius: 2px; }
QSlider::sub-page:horizontal {
    background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 $accent, stop:1 $accent2); border-radius: 2px;
}
QSlider::handle:horizontal {
    background: #FFFFFF; width: 14px; height: 14px; margin: -6px 0; border-radius: 8px;
    border: 2px solid $accent;
}
QSlider::handle:horizontal:hover { border-color: $accent2_hover; }
QSlider::sub-page:horizontal:disabled { background: $bg4; }
QSlider::handle:horizontal:disabled { background: $bg4; border-color: $border; }

QCheckBox { spacing: 9px; }
QCheckBox::indicator {
    width: 18px; height: 18px; border-radius: 5px; border: 1px solid $border_strong; background: $bg0;
}
QCheckBox::indicator:hover { border-color: $accent; }
QCheckBox::indicator:checked { background: $accent; border-color: $accent; image: url($check); }
QCheckBox:disabled { color: $text_muted; }

/* ---------- Scrolling ---------- */
QScrollArea { background: transparent; border: none; }
QScrollArea > QWidget > QWidget { background: transparent; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: $bg4; border-radius: 3px; min-height: 30px; }
QScrollBar::handle:vertical:hover { background: $accent_a60; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: $bg4; border-radius: 3px; min-width: 30px; }
QScrollBar::add-line, QScrollBar::sub-line { width: 0; height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: none; }

/* ---------- Misc ---------- */
QToolTip {
    background: $bg2; color: $text; border: 1px solid $border_strong;
    border-radius: 6px; padding: 6px 9px;
}
QMenu { background: $bg2; border: 1px solid $border_strong; border-radius: 10px; padding: 6px; }
QMenu::item { padding: 7px 26px 7px 12px; border-radius: 6px; }
QMenu::item:selected { background: $accent_a28; }
QMenu::separator { height: 1px; background: $border; margin: 5px 8px; }
QMessageBox { background: $bg1; }
QMessageBox QLabel { color: $text; }
QGraphicsView { border: none; background: $canvas; }

QFrame#Toast { background: $bg2; border: 1px solid $border_strong; border-radius: 12px; }
QLabel#ToastTitle { font-weight: 600; color: $strong; }
QLabel#ToastMessage { color: $text_dim; }

QLabel#ThumbBox { background: $bg2; border: 1px solid $border_soft; border-radius: 10px; }
QLabel#StatusDot { background: $warning; border-radius: 4px; }
QLabel#StatusDot[kind="success"] { background: $success; }
QLabel#StatusDot[kind="error"] { background: $danger; }
QLabel#StatusDot[kind="info"] { background: $accent2; }
QLabel#Caption[over="true"] { color: $danger; }
QFrame#ThemeCard { background: $bg2; border: 1px solid $border; border-radius: 14px; }
QFrame#DropZone { background: $bg0; border: 1px dashed $border_strong; border-radius: 12px; }
QFrame#DropZone:hover { border-color: $accent; background: $accent_a06; }
QFrame#DropZone[active="true"] { border: 1px solid $accent; background: $accent_a10; }

QToolButton#PresetTile {
    background: $bg2; border: 1px solid $border; border-radius: 12px;
    padding: 10px 6px; color: $text_dim; font-size: 12px;
}
QToolButton#PresetTile:hover { border-color: $border_strong; color: $text; }
QToolButton#PresetTile:checked { border: 1px solid $accent; background: $accent_a16; color: $strong; }
"""
)


def build_stylesheet(assets: dict[str, str]) -> str:
    tokens = dict(COLORS)
    for alpha in (6, 8, 10, 12, 16, 20, 22, 28, 35, 40, 45, 55, 60):
        tokens[f"accent_a{alpha:02d}"] = rgba(COLORS["accent"], alpha / 100)
        tokens[f"accent2_a{alpha:02d}"] = rgba(COLORS["accent2"], alpha / 100)
    for name in ("warning", "danger"):
        for alpha in (10, 12, 20, 35):
            tokens[f"{name}_a{alpha}"] = rgba(COLORS[name], alpha / 100)
    tokens.update(assets)
    return _QSS.substitute(tokens)


def section_font(size_px: int = 10) -> QFont:
    """Small, spaced uppercase font used for section labels."""
    font = QFont(FONT_FAMILY)
    font.setPixelSize(size_px)
    font.setWeight(QFont.Weight.Bold)
    font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, 1.2)
    return font


def _windows_prefers_light() -> bool | None:
    """Read the Windows 'app mode' setting; None when unavailable."""
    try:
        import winreg

        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER,
                             r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        value, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
        winreg.CloseKey(key)
        return bool(value)
    except (ImportError, OSError):
        return None


def system_theme(app: QApplication) -> str:
    """The operating system's current preference: ``"dark"`` or ``"light"``."""
    hints = app.styleHints()
    try:
        hints.unsetColorScheme()  # stop overriding, follow the OS (Qt ≥ 6.8)
    except AttributeError:
        pass
    try:
        scheme = hints.colorScheme()
    except AttributeError:
        scheme = None
    if scheme == Qt.ColorScheme.Light:
        return "light"
    if scheme == Qt.ColorScheme.Dark:
        return "dark"
    prefers_light = _windows_prefers_light()
    return "light" if prefers_light else "dark"


def apply_theme(app: QApplication, mode: str = DEFAULT_THEME_MODE) -> str:
    """Apply ``mode`` ("dark", "light" or "system"). Returns the effective theme."""
    from ui.icons import write_stylesheet_assets

    if mode not in THEME_MODES:
        mode = DEFAULT_THEME_MODE
    effective = system_theme(app) if mode == "system" else mode
    _active.update(mode=mode, effective=effective)
    COLORS.clear()
    COLORS.update(THEMES[effective])

    app.setStyle("Fusion")
    font = QFont(FONT_FAMILY)
    font.setPixelSize(13)
    app.setFont(font)

    if mode != "system":
        try:  # native title-bar colour follows this hint (Qt ≥ 6.8)
            app.styleHints().setColorScheme(
                Qt.ColorScheme.Dark if effective == "dark" else Qt.ColorScheme.Light)
        except AttributeError:
            pass

    palette = QPalette()
    roles = {
        QPalette.ColorRole.Window: COLORS["bg1"],
        QPalette.ColorRole.WindowText: COLORS["text"],
        QPalette.ColorRole.Base: COLORS["bg0"],
        QPalette.ColorRole.AlternateBase: COLORS["bg2"],
        QPalette.ColorRole.Text: COLORS["text"],
        QPalette.ColorRole.Button: COLORS["bg3"],
        QPalette.ColorRole.ButtonText: COLORS["text"],
        QPalette.ColorRole.Highlight: COLORS["accent"],
        QPalette.ColorRole.HighlightedText: "#FFFFFF",
        QPalette.ColorRole.ToolTipBase: COLORS["bg2"],
        QPalette.ColorRole.ToolTipText: COLORS["text"],
        QPalette.ColorRole.PlaceholderText: COLORS["text_muted"],
        QPalette.ColorRole.Link: COLORS["accent2"],
    }
    for role, color in roles.items():
        palette.setColor(role, QColor(color))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.Text, QColor(COLORS["text_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.ButtonText, QColor(COLORS["text_muted"]))
    palette.setColor(QPalette.ColorGroup.Disabled, QPalette.ColorRole.WindowText, QColor(COLORS["text_muted"]))
    app.setPalette(palette)
    app.setStyleSheet(build_stylesheet(write_stylesheet_assets(effective)))
    return effective
