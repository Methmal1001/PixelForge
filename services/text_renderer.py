"""Text layout and painting shared by the on-screen canvas and the exporter.

``TextLayout`` lays out one TextElement (font, spacing, colour, effects) and paints
it in local coordinates. The canvas item and the exporter both paint through it,
so exported text matches exactly what the user sees.
"""

from __future__ import annotations

import math
import os

from PIL import ImageFilter
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QGuiApplication,
    QImage,
    QPainter,
    QPainterPath,
    QPen,
    QTextBlockFormat,
    QTextCharFormat,
    QTextCursor,
    QTextDocument,
    QTextOption,
)

from models.design import TextElement
from services.qt_image import pil_to_qimage, qimage_to_pil

TEXT_MARGIN = 2.0
SHADOW_ANGLE = math.radians(45)  # light from the top-left

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
    size = max(1, int(element.font_size))
    font.setPixelSize(size)
    font.setBold(element.bold)
    font.setItalic(element.italic)
    font.setUnderline(element.underline)
    if element.letter_spacing:
        font.setLetterSpacing(QFont.SpacingType.AbsoluteSpacing, element.letter_spacing / 100 * size)
    font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    # Unhinted metrics keep layout identical at every zoom level and at export.
    font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
    return font


def configure_document(document: QTextDocument, element: TextElement, *, color: str | None = None,
                       outline: QPen | None = None) -> QTextDocument:
    """Lay out ``element`` in ``document`` (font, colour, spacing, alignment, width)."""
    document.setDocumentMargin(TEXT_MARGIN)
    document.setDefaultFont(build_font(element))
    option = QTextOption(_ALIGNMENT.get(element.align, Qt.AlignmentFlag.AlignLeft))
    option.setWrapMode(QTextOption.WrapMode.NoWrap)
    document.setDefaultTextOption(option)
    document.setPlainText(element.text.upper() if element.uppercase else element.text)

    cursor = QTextCursor(document)
    cursor.select(QTextCursor.SelectionType.Document)
    char_format = QTextCharFormat()
    char_format.setForeground(QColor(color or element.color))
    if outline is not None:
        char_format.setTextOutline(outline)
    cursor.mergeCharFormat(char_format)
    if abs(element.line_height - 1.0) > 1e-3:
        block_format = QTextBlockFormat()
        block_format.setLineHeight(max(30.0, element.line_height * 100),
                                   QTextBlockFormat.LineHeightTypes.ProportionalHeight.value)
        cursor.mergeBlockFormat(block_format)

    document.setTextWidth(-1)
    document.setTextWidth(math.ceil(document.size().width()))
    return document


class TextLayout:
    """A laid-out text element that can report its geometry and paint itself."""

    def __init__(self, element: TextElement) -> None:
        ensure_gui_application()
        self.element = element
        size = max(1, element.font_size)
        self.document = configure_document(QTextDocument(), element)
        doc_size = self.document.size()
        self.width, self.height = doc_size.width(), doc_size.height()

        self.padding = element.background_padding / 100 * size if element.background else 0.0
        self.radius = element.background_radius / 100 * size if element.background else 0.0
        self.outline_px = element.outline_width / 100 * size if element.outline else 0.0
        self.shadow_px = element.shadow_distance / 100 * size if element.shadow else 0.0
        self.shadow_blur_px = element.shadow_blur / 100 * size if element.shadow else 0.0

        self.outline_document = None
        if element.outline and self.outline_px > 0:
            pen = QPen(QColor(element.outline_color), self.outline_px * 2)
            pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            self.outline_document = configure_document(QTextDocument(), element,
                                                       color=element.outline_color, outline=pen)
        self.shadow_document = None
        if element.shadow and not element.background:
            pen = None
            if self.outline_px > 0:
                pen = QPen(QColor(element.shadow_color), self.outline_px * 2)
                pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
            self.shadow_document = configure_document(QTextDocument(), element,
                                                      color=element.shadow_color, outline=pen)
        self._shadow_image: tuple[QImage, QPointF] | None = None

    # ------------------------------------------------------------------ geometry

    def text_rect(self) -> QRectF:
        return QRectF(0, 0, self.width, self.height)

    def body_rect(self) -> QRectF:
        """Visible box of the text: background box if any, else text plus outline."""
        if self.element.background:
            p = self.padding
            return self.text_rect().adjusted(-p, -p, p, p)
        o = self.outline_px
        return self.text_rect().adjusted(-o, -o, o, o)

    def shadow_offset(self) -> QPointF:
        return QPointF(math.cos(SHADOW_ANGLE) * self.shadow_px, math.sin(SHADOW_ANGLE) * self.shadow_px)

    def bounding_rect(self) -> QRectF:
        rect = self.body_rect()
        if self.element.shadow:
            spread = self.shadow_blur_px * 1.5
            shadow = rect.translated(self.shadow_offset()).adjusted(-spread, -spread, spread, spread)
            rect = rect.united(shadow)
        return rect

    # ------------------------------------------------------------------ painting

    def _background_path(self, rect: QRectF) -> QPainterPath:
        path = QPainterPath()
        radius = min(self.radius, rect.height() / 2, rect.width() / 2)
        path.addRoundedRect(rect, radius, radius)
        return path

    def _paint_shadow_shape(self, painter: QPainter) -> None:
        if self.element.background:
            painter.fillPath(self._background_path(self.body_rect()), QColor(self.element.shadow_color))
        elif self.shadow_document is not None:
            self.shadow_document.drawContents(painter)

    def _blurred_shadow(self) -> tuple[QImage, QPointF]:
        if self._shadow_image is None:
            margin = math.ceil(self.shadow_blur_px * 1.5) + 2
            body = self.body_rect()
            width = max(1, math.ceil(body.width()) + margin * 2)
            height = max(1, math.ceil(body.height()) + margin * 2)
            image = QImage(width, height, QImage.Format.Format_RGBA8888)
            image.fill(Qt.GlobalColor.transparent)
            origin = QPointF(margin - body.left(), margin - body.top())
            painter = QPainter(image)
            painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing)
            painter.translate(origin)
            self._paint_shadow_shape(painter)
            painter.end()
            blurred = qimage_to_pil(image).filter(ImageFilter.GaussianBlur(self.shadow_blur_px / 2))
            self._shadow_image = (pil_to_qimage(blurred), -origin)
        return self._shadow_image

    def paint(self, painter: QPainter) -> None:
        """Paint in local coordinates (text box top-left at 0, 0)."""
        element = self.element
        painter.save()
        painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.TextAntialiasing
                               | QPainter.RenderHint.SmoothPixmapTransform)
        base_opacity = painter.opacity() * max(0.0, min(1.0, element.opacity))
        painter.setOpacity(base_opacity)

        if element.shadow and element.shadow_opacity > 0:
            painter.save()
            painter.setOpacity(base_opacity * element.shadow_opacity)
            if self.shadow_blur_px >= 0.5:
                image, top_left = self._blurred_shadow()
                painter.drawImage(top_left + self.shadow_offset(), image)
            else:
                painter.translate(self.shadow_offset())
                self._paint_shadow_shape(painter)
            painter.restore()

        if element.background:
            color = QColor(element.background_color)
            color.setAlphaF(max(0.0, min(1.0, element.background_opacity)))
            painter.fillPath(self._background_path(self.body_rect()), color)

        if self.outline_document is not None:
            self.outline_document.drawContents(painter)
        self.document.drawContents(painter)
        painter.restore()

    def paint_at(self, painter: QPainter) -> None:
        """Paint at the element's image position, applying its rotation."""
        painter.save()
        painter.translate(self.element.x, self.element.y)
        if self.element.rotation:
            center = self.text_rect().center()
            painter.translate(center)
            painter.rotate(self.element.rotation)
            painter.translate(-center)
        self.paint(painter)
        painter.restore()


def text_size(element: TextElement) -> tuple[float, float]:
    """Rendered (width, height) of the text box in image pixels (without effects)."""
    layout = TextLayout(element)
    return layout.width, layout.height


def paint_text(painter: QPainter, element: TextElement) -> None:
    """Paint one text element at its image-pixel position."""
    TextLayout(element).paint_at(painter)
