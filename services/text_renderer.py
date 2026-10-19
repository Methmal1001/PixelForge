"""Text layout shared by the on-screen canvas and the exporter.

Both the QGraphicsTextItem on the canvas and the exporter configure their
QTextDocument through ``configure_document``, so exported text matches what the
user sees.
"""

from __future__ import annotations

import math
import os

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QPainter,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)

from models.design import TextElement

TEXT_MARGIN = 2.0

_ALIGNMENT = {
    "left": Qt.AlignmentFlag.AlignLeft,
    "center": Qt.AlignmentFlag.AlignHCenter,
    "right": Qt.AlignmentFlag.AlignRight,
}

_headless_app: QGuiApplication | None = None


def ensure_gui_application() -> QGuiApplication:
    """Qt needs a GUI application for font rendering; create a headless one if absent."""
    global _headless_app
    app = QGuiApplication.instance()
    if app is None:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
        _headless_app = QGuiApplication([])
        app = _headless_app
    return app  # type: ignore[return-value]


def build_font(element: TextElement) -> QFont:
    font = QFont(element.font_family)
    font.setPixelSize(max(1, int(element.font_size)))
    font.setBold(element.bold)
    font.setItalic(element.italic)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    # Unhinted metrics keep layout identical at every zoom level and at export.
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def configure_document(document: QTextDocument, element: TextElement) -> QTextDocument:
    """Lay out ``element`` in ``document`` (font, colour, alignment, width)."""
    document.setDocumentMargin(TEXT_MARGIN)
    document.setDefaultFont(build_font(element))
    option = QTextOption(_ALIGNMENT.get(element.align, Qt.AlignmentFlag.AlignLeft))
    option.setWrapMode(QTextOption.WrapMode.NoWrap)
    document.setDefaultTextOption(option)
    document.setPlainText(element.text)

    cursor = QTextCursor(document)
    cursor.select(QTextCursor.SelectionType.Document)
    char_format = QTextCharFormat()
    char_format.setForeground(QColor(element.color))
    cursor.mergeCharFormat(char_format)

    document.setTextWidth(-1)
    document.setTextWidth(math.ceil(document.size().width()))
    return document


def text_size(element: TextElement) -> tuple[float, float]:
    """Rendered (width, height) of a text element in image pixels."""
    ensure_gui_application()
    document = configure_document(QTextDocument(), element)
    size = document.size()
    return size.width(), size.height()


def paint_text(painter: QPainter, element: TextElement) -> None:
    """Paint one text element at its image-pixel position."""
    document = configure_document(QTextDocument(), element)
    painter.save()
    painter.translate(element.x, element.y)
    document.drawContents(painter)
    painter.restore()
