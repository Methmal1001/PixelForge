"""Inline vector icon set (24×24 stroke icons) rendered with QtSvg."""

from __future__ import annotations

import json
import tempfile
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import QByteArray, QObject, QRectF, Qt
from PySide6.QtGui import QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

from ui.styles import resolve

_PATHS: dict[str, str] = {
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "plus_square": '<rect x="3" y="3" width="18" height="18" rx="3"/><path d="M12 8v8M8 12h8"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/>',
    "clock": '<circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/>',
    "template": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/>',
    "history": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/><path d="M12 7v5l4 2"/>',
    "settings": '<path d="M4 21v-7M4 10V3M12 21v-9M12 8V3M20 21v-5M20 12V3M1 14h6M9 8h6M17 16h6"/>',
    "info": '<circle cx="12" cy="12" r="9"/><path d="M12 16v-4M12 8h.01"/>',
    "image": '<rect x="3" y="3" width="18" height="18" rx="2"/><circle cx="9" cy="9" r="2"/>'
             '<path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    "upload": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m17 8-5-5-5 5"/><path d="M12 3v12"/>',
    "export": '<path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><path d="m7 10 5 5 5-5"/><path d="M12 15V3"/>',
    "undo": '<path d="M9 14 4 9l5-5"/><path d="M4 9h10.5a5.5 5.5 0 0 1 0 11H11"/>',
    "redo": '<path d="m15 14 5-5-5-5"/><path d="M20 9H9.5a5.5 5.5 0 0 0 0 11H13"/>',
    "zoom_in": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3M11 8v6M8 11h6"/>',
    "zoom_out": '<circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3M8 11h6"/>',
    "fit": '<path d="M8 3H5a2 2 0 0 0-2 2v3M21 8V5a2 2 0 0 0-2-2h-3M3 16v3a2 2 0 0 0 2 2h3M16 21h3a2 2 0 0 0 2-2v-3"/>',
    "actual": '<rect x="3" y="5" width="18" height="14" rx="2"/><path d="M8 10v5M7 10h1M16 10v5M15 10h1M12 11v.01M12 14v.01"/>',
    "crop": '<path d="M6 2v14a2 2 0 0 0 2 2h14"/><path d="M18 22V8a2 2 0 0 0-2-2H2"/>',
    "resize": '<path d="M15 3h6v6M21 3l-7 7M9 21H3v-6M3 21l7-7"/>',
    "rotate_left": '<path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/>',
    "rotate_right": '<path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/>',
    "flip_h": '<path d="M12 3v18"/><path d="M8 7 3 12l5 5z"/><path d="m16 7 5 5-5 5z"/>',
    "flip_v": '<path d="M3 12h18"/><path d="M7 8l5-5 5 5z"/><path d="m7 16 5 5 5-5z"/>',
    "text": '<path d="M4 7V4h16v3M9 20h6M12 4v16"/>',
    "trash": '<path d="M3 6h18M8 6V4h8v2M19 6l-1 14a2 2 0 0 1-2 2H8a2 2 0 0 1-2-2L5 6M10 11v6M14 11v6"/>',
    "clear": '<rect x="3" y="3" width="18" height="18" rx="2"/><path d="m9 9 6 6M15 9l-6 6"/>',
    "sparkles": '<path d="M12 3l1.9 5.1L19 10l-5.1 1.9L12 17l-1.9-5.1L5 10l5.1-1.9z"/>'
                '<path d="M19 3v4M17 5h4M5 17v4M3 19h4"/>',
    "x": '<path d="M18 6 6 18M6 6l12 12"/>',
    "sun": '<circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4'
           'M2 12h2M20 12h2M6.3 17.7l-1.4 1.4M19.1 4.9l-1.4 1.4"/>',
    "contrast": '<circle cx="12" cy="12" r="9"/><path d="M12 3v18a9 9 0 0 0 0-18z" fill="currentColor"/>',
    "droplet": '<path d="M12 2.7l5.7 5.7a8 8 0 1 1-11.4 0z"/>',
    "grayscale": '<circle cx="12" cy="12" r="9"/><path d="M12 3v18M12 8h6.6M12 12h9M12 16h6.6"/>',
    "reset": '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>',
    "bold": '<path d="M6 4h8a4 4 0 0 1 0 8H6zM6 12h9a4 4 0 0 1 0 8H6z"/>',
    "italic": '<path d="M19 4h-9M14 20H5M15 4 9 20"/>',
    "align_left": '<path d="M3 6h18M3 12h12M3 18h16"/>',
    "align_center": '<path d="M3 6h18M6 12h12M4 18h16"/>',
    "align_right": '<path d="M3 6h18M9 12h12M5 18h16"/>',
    "check": '<path d="M20 6 9 17l-5-5"/>',
    "chevron_down": '<path d="m6 9 6 6 6-6"/>',
    "chevron_right": '<path d="m9 6 6 6-6 6"/>',
    "select": '<rect x="3" y="3" width="18" height="18" rx="2" stroke-dasharray="3 3"/>',
    "ellipse_select": '<ellipse cx="12" cy="12" rx="9" ry="7" stroke-dasharray="3 3"/>',
    "lasso": '<path d="M7 22a5 5 0 0 1-2-4M3.3 14A6.8 6.8 0 0 1 2 10c0-4.4 4.5-8 10-8s10 3.6 10 8-4.5 8-10 8a12 12 0 0 1-5-1"/><circle cx="5" cy="16" r="2"/>',
    "eraser": '<path d="m7 21-4.3-4.3a1 1 0 0 1 0-1.4l10-10a1 1 0 0 1 1.4 0l5.6 5.6a1 1 0 0 1 0 1.4L13 19"/><path d="M22 21H7M5 11l9 9"/>',
    "bucket": '<path d="m19 11-8-8-8.6 8.6a2 2 0 0 0 0 2.8l5.2 5.2a2 2 0 0 0 2.8 0L19 11Z"/><path d="m5 2 5 5M2 13h15M22 20a2 2 0 1 1-4 0c0-1.6 1.7-2.4 2-4 .3 1.6 2 2.4 2 4Z"/>',
    "magic": '<path d="m21.6 2.4-1.2-1.2a1.2 1.2 0 0 0-1.7 0L2.4 17.5a1.2 1.2 0 0 0 0 1.7l1.2 1.2a1.2 1.2 0 0 0 1.7 0L21.6 4.1a1.2 1.2 0 0 0 0-1.7Z"/><path d="m14 7 3 3M5 6v4M19 14v4M10 2v2M7 8H3M21 16h-4M11 3H9"/>',
    "copy": '<rect x="8" y="8" width="13" height="13" rx="2"/><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3"/>',
    "bring_forward": '<rect x="8" y="3" width="13" height="13" rx="2" fill="currentColor" fill-opacity=".25"/><path d="M3 8v11a2 2 0 0 0 2 2h11"/>',
    "send_backward": '<rect x="3" y="8" width="13" height="13" rx="2"/><path d="M8 3h11a2 2 0 0 1 2 2v11"/>',
    "center_h": '<path d="M12 3v18M6 8h12v8H6z"/>',
    "center_v": '<path d="M3 12h18M8 6h8v12H8z"/>',
    "underline": '<path d="M6 4v6a6 6 0 0 0 12 0V4M4 20h16"/>',
    "case": '<path d="M3 17 7 7l4 10M4.5 13.5h5M15 11.5a3 3 0 1 1 0 5.5M18 11v6"/>',
    "rotate_angle": '<path d="M21 12a9 9 0 1 1-6.2-8.6"/><path d="M21 4v5h-5"/><path d="M12 7v5l3 3"/>',
    "filter": '<circle cx="9" cy="9" r="6"/><circle cx="15" cy="15" r="6"/>',
    "wand": '<path d="M15 4V2M15 16v-2M8 9h2M20 9h2M17.8 11.8 19 13M17.8 6.2 19 5M3 21l9-9M12.2 6.2 11 5"/>',
    "alert": '<path d="M12 9v4M12 17h.01"/><path d="M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a2 2 0 0 0-3.4 0z"/>',
    "circle_check": '<circle cx="12" cy="12" r="9"/><path d="m8 12 3 3 5-6"/>',
    "circle_x": '<circle cx="12" cy="12" r="9"/><path d="m15 9-6 6M9 9l6 6"/>',
    "layers": '<path d="m12 2 10 5-10 5L2 7z"/><path d="m2 17 10 5 10-5M2 12l10 5 10-5"/>',
    "palette": '<circle cx="13.5" cy="6.5" r="1"/><circle cx="17.5" cy="10.5" r="1"/><circle cx="8.5" cy="7.5" r="1"/>'
               '<circle cx="6.5" cy="12.5" r="1"/><path d="M12 2a10 10 0 0 0 0 20c1 0 1.7-.8 1.7-1.7 0-.4-.2-.8-.4-1.1'
               '-.3-.3-.4-.7-.4-1.1 0-.9.8-1.7 1.7-1.7H17a5 5 0 0 0 5-5c0-4.9-4.5-8.4-10-8.4z"/>',
    "arrow_left": '<path d="M19 12H5M12 19l-7-7 7-7"/>',
    "lock": '<rect x="4" y="11" width="16" height="10" rx="2"/><path d="M8 11V7a4 4 0 0 1 8 0v4"/>',
}

_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="{color}" '
    'stroke-width="{stroke}" stroke-linecap="round" stroke-linejoin="round">{body}</svg>'
)


def svg_markup(name: str, color: str, stroke: float = 1.8) -> str:
    body = _PATHS[name].replace("currentColor", color)
    return _SVG.format(color=color, stroke=stroke, body=body)


@lru_cache(maxsize=1024)
def _render(name: str, color: str, size: int) -> QPixmap:
    scale = 3
    result = QPixmap(size * scale, size * scale)
    result.fill(Qt.GlobalColor.transparent)
    renderer = QSvgRenderer(QByteArray(svg_markup(name, color).encode()))
    painter = QPainter(result)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)
    renderer.render(painter, QRectF(0, 0, size * scale, size * scale))
    painter.end()
    result.setDevicePixelRatio(scale)
    return result


def pixmap(name: str, color: str | None = None, size: int = 20) -> QPixmap:
    """Render an icon to a high-DPI pixmap. ``color`` is a theme token or a literal colour."""
    return _render(name, resolve(color), size)


def icon(
    name: str,
    color: str | None = None,
    *,
    checked: str | None = "strong",
    hover: str | None = None,
) -> QIcon:
    """Build a QIcon with normal, hover, checked and disabled colour states.

    Colours may be theme tokens (``"text_dim"``) or literal hex colours.
    """
    normal = color or "text_dim"
    result = QIcon()
    result.addPixmap(pixmap(name, normal, 24), QIcon.Mode.Normal, QIcon.State.Off)
    result.addPixmap(pixmap(name, hover or "text", 24), QIcon.Mode.Active, QIcon.State.Off)
    result.addPixmap(pixmap(name, "border_strong", 24), QIcon.Mode.Disabled, QIcon.State.Off)
    on_color = checked or normal
    result.addPixmap(pixmap(name, on_color, 24), QIcon.Mode.Normal, QIcon.State.On)
    result.addPixmap(pixmap(name, on_color, 24), QIcon.Mode.Active, QIcon.State.On)
    result.addPixmap(pixmap(name, "border_strong", 24), QIcon.Mode.Disabled, QIcon.State.On)
    return result


# --------------------------------------------------------------------------- theme-aware binding

_ICON_SPEC = "pf_icon"
_PIXMAP_SPEC = "pf_pixmap"


def set_icon(target: QObject, name: str, color: str | None = None, *,
             checked: str | None = "strong", hover: str | None = None) -> None:
    """Set an icon on a button or action and remember how to rebuild it for another theme."""
    target.setProperty(_ICON_SPEC, json.dumps([name, color, checked, hover]))
    target.setIcon(icon(name, color, checked=checked, hover=hover))


def set_pixmap(label: QObject, name: str, color: str | None, size: int) -> None:
    """Set an icon pixmap on a QLabel and remember how to rebuild it for another theme."""
    label.setProperty(_PIXMAP_SPEC, json.dumps([name, color, size]))
    label.setPixmap(pixmap(name, color, size))


def refresh_icons(root: QObject) -> None:
    """Re-render every icon set through set_icon/set_pixmap under ``root``."""
    for obj in [root, *root.findChildren(QObject)]:
        spec = obj.property(_ICON_SPEC)
        if spec:
            name, color, checked, hover = json.loads(spec)
            obj.setIcon(icon(name, color, checked=checked, hover=hover))
        spec = obj.property(_PIXMAP_SPEC)
        if spec:
            name, color, size = json.loads(spec)
            obj.setPixmap(pixmap(name, color, size))


def write_stylesheet_assets(theme: str = "dark") -> dict[str, str]:
    """Write the small SVGs the stylesheet references; return their url paths.

    File names include the theme because Qt caches stylesheet images by path.
    """
    folder = Path(tempfile.gettempdir()) / "pixdem_ai_studio" / "qss"
    folder.mkdir(parents=True, exist_ok=True)
    assets = {
        "chevron": ("chevron_down", resolve("text_dim"), 2.0),
        "check": ("check", "#FFFFFF", 3.0),
    }
    result = {}
    for key, (name, color, stroke) in assets.items():
        path = folder / f"{name}_{theme}.svg"
        path.write_text(svg_markup(name, color, stroke), encoding="utf-8")
        result[key] = path.as_posix()
    return result
