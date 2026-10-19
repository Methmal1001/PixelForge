"""Conversions between Pillow images and Qt QImages."""

from __future__ import annotations

from PIL import Image
from PySide6.QtGui import QImage


def pil_to_qimage(image: Image.Image) -> QImage:
    """Convert a Pillow image to an independent RGBA QImage."""
    if image.mode != "RGBA":
        image = image.convert("RGBA")
    data = image.tobytes("raw", "RGBA")
    qimage = QImage(data, image.width, image.height, image.width * 4, QImage.Format.Format_RGBA8888)
    return qimage.copy()  # detach from the Python bytes buffer


def qimage_to_pil(qimage: QImage) -> Image.Image:
    """Convert a QImage to an RGBA Pillow image."""
    converted = qimage.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height, stride = converted.width(), converted.height(), converted.bytesPerLine()
    buffer = bytes(converted.constBits())
    return Image.frombuffer("RGBA", (width, height), buffer, "raw", "RGBA", stride, 1).copy()
