"""Drawing image layers, shared by the exporter and "merge into background".

The canvas shows layers with QGraphicsPixmapItem using the same maths:
position = layer top-left, then scale and rotation around the layer centre.
"""

from __future__ import annotations

from PIL import Image
from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainter

from models.design import ImageLayer
from services.qt_image import pil_to_qimage, qimage_to_pil


def paint_layer(painter: QPainter, layer: ImageLayer) -> None:
    """Paint one layer in image-pixel coordinates."""
    width, height = layer.size
    center = QPointF(width / 2, height / 2)
    painter.save()
    painter.setRenderHints(QPainter.RenderHint.Antialiasing | QPainter.RenderHint.SmoothPixmapTransform)
    painter.setOpacity(painter.opacity() * max(0.0, min(1.0, layer.opacity)))
    painter.translate(layer.x, layer.y)
    painter.translate(center)
    painter.rotate(layer.rotation)
    painter.scale(layer.scale, layer.scale)
    painter.translate(-center)
    painter.drawImage(QPointF(0, 0), pil_to_qimage(layer.image))
    painter.restore()


def composite_layer(base: Image.Image, layer: ImageLayer) -> Image.Image:
    """Return ``base`` with ``layer`` drawn onto it (used to merge a layer down)."""
    from services.text_renderer import ensure_gui_application

    ensure_gui_application()
    canvas = pil_to_qimage(base)
    painter = QPainter(canvas)
    paint_layer(painter, layer)
    painter.end()
    merged = qimage_to_pil(canvas)
    return merged if base.mode == "RGBA" else merged.convert(base.mode)
