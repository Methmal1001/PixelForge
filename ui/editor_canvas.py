"""Interactive design canvas built on QGraphicsView / QGraphicsScene.

Scene coordinates equal image pixels, so text positions on screen map 1:1 to the
exported design.
"""

from __future__ import annotations

from PySide6.QtCore import QPointF, QRect, QRectF, Qt, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QPainter, QPainterPath, QPen, QPixmap, QTransform
from PySide6.QtWidgets import (
    QGraphicsItem,
    QGraphicsPixmapItem,
    QGraphicsScene,
    QGraphicsTextItem,
    QGraphicsView,
    QStyle,
    QStyleOptionGraphicsItem,
)

from models.design import TextElement
from services.text_renderer import configure_document
from ui.pages import dropped_image_path
from ui.styles import COLORS, is_dark

MIN_ZOOM = 0.02
MAX_ZOOM = 16.0
ZOOM_STEP = 1.25
FIT_PADDING = 36


def _cosmetic_pen(color: str | QColor, width: float = 1.5, style=Qt.PenStyle.SolidLine) -> QPen:
    pen = QPen(QColor(color), width, style)
    pen.setCosmetic(True)
    return pen


def _without_selection(option: QStyleOptionGraphicsItem) -> QStyleOptionGraphicsItem:
    plain = QStyleOptionGraphicsItem(option)
    plain.state = plain.state & ~QStyle.StateFlag.State_Selected & ~QStyle.StateFlag.State_HasFocus
    return plain


class ImageItem(QGraphicsPixmapItem):
    """The background image. Selectable (for info) but not movable."""

    def __init__(self) -> None:
        super().__init__()
        self.setTransformationMode(Qt.TransformationMode.SmoothTransformation)
        self.setShapeMode(QGraphicsPixmapItem.ShapeMode.BoundingRectShape)
        self.setFlag(QGraphicsItem.GraphicsItemFlag.ItemIsSelectable)
        self.setZValue(0)

    def paint(self, painter, option, widget=None) -> None:
        super().paint(painter, _without_selection(option), widget)
        if self.isSelected():
            painter.setPen(_cosmetic_pen(COLORS["accent2"], 2))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(self.boundingRect())


class TextItem(QGraphicsTextItem):
    """A movable, selectable text overlay bound to a TextElement id."""

    def __init__(self, element_id: str) -> None:
        super().__init__()
        self.element_id = element_id
        self.setFlags(
            QGraphicsItem.GraphicsItemFlag.ItemIsMovable
            | QGraphicsItem.GraphicsItemFlag.ItemIsSelectable
            | QGraphicsItem.GraphicsItemFlag.ItemSendsGeometryChanges
        )
        self.setTextInteractionFlags(Qt.TextInteractionFlag.NoTextInteraction)
        self.setAcceptHoverEvents(True)
        self.setCursor(Qt.CursorShape.SizeAllCursor)
        self.setToolTip("Drag to move · Double-click to edit text · Delete to remove")
        self._hovered = False

    def apply_element(self, element: TextElement) -> None:
        self.prepareGeometryChange()
        configure_document(self.document(), element)
        self.setPos(element.x, element.y)
        self.update()

    def hoverEnterEvent(self, event) -> None:  # noqa: N802
        self._hovered = True
        self.update()
        super().hoverEnterEvent(event)

    def hoverLeaveEvent(self, event) -> None:  # noqa: N802
        self._hovered = False
        self.update()
        super().hoverLeaveEvent(event)

    def paint(self, painter, option, widget=None) -> None:
        super().paint(painter, _without_selection(option), widget)
        rect = self.boundingRect()
        if self.isSelected():
            painter.setPen(_cosmetic_pen(COLORS["accent"], 1.6))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)
            scale = painter.worldTransform().m11() or 1.0
            handle = 7 / scale
            painter.setPen(_cosmetic_pen(COLORS["accent"], 1.4))
            painter.setBrush(QColor("#FFFFFF"))
            for corner in (rect.topLeft(), rect.topRight(), rect.bottomLeft(), rect.bottomRight()):
                painter.drawRect(QRectF(corner.x() - handle / 2, corner.y() - handle / 2, handle, handle))
        elif self._hovered:
            painter.setPen(_cosmetic_pen(COLORS["accent_hover"], 1.2, Qt.PenStyle.DashLine))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRect(rect)


class CropOverlay(QGraphicsItem):
    """Dims everything outside the crop selection and draws guides."""

    def __init__(self, bounds: QRectF) -> None:
        super().__init__()
        self.bounds = QRectF(bounds)
        self.selection = QRectF(bounds)
        self.setZValue(10_000)

    def boundingRect(self) -> QRectF:  # noqa: N802
        return self.bounds

    def set_selection(self, rect: QRectF) -> None:
        self.selection = rect.normalized().intersected(self.bounds)
        self.update()

    def paint(self, painter, option, widget=None) -> None:
        outside = QPainterPath()
        outside.addRect(self.bounds)
        inner = QPainterPath()
        inner.addRect(self.selection)
        painter.fillPath(outside.subtracted(inner), QColor(6, 7, 12, 170))

        sel = self.selection
        painter.setPen(_cosmetic_pen(QColor(255, 255, 255, 70), 1))
        for i in (1, 2):
            x = sel.left() + sel.width() * i / 3
            y = sel.top() + sel.height() * i / 3
            painter.drawLine(QPointF(x, sel.top()), QPointF(x, sel.bottom()))
            painter.drawLine(QPointF(sel.left(), y), QPointF(sel.right(), y))
        painter.setPen(_cosmetic_pen("#FFFFFF", 1.5))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(sel)

        scale = painter.worldTransform().m11() or 1.0
        arm = min(22 / scale, sel.width() / 3, sel.height() / 3)
        painter.setPen(_cosmetic_pen(COLORS["accent"], 4))
        corners = (
            (sel.topLeft(), 1, 1), (sel.topRight(), -1, 1),
            (sel.bottomLeft(), 1, -1), (sel.bottomRight(), -1, -1),
        )
        for point, dx, dy in corners:
            painter.drawLine(point, point + QPointF(arm * dx, 0))
            painter.drawLine(point, point + QPointF(0, arm * dy))


def _checker_brush() -> QBrush:
    tile = QPixmap(16, 16)
    tile.fill(QColor(COLORS["checker_a"]))
    painter = QPainter(tile)
    painter.fillRect(0, 0, 8, 8, QColor(COLORS["checker_b"]))
    painter.fillRect(8, 8, 8, 8, QColor(COLORS["checker_b"]))
    painter.end()
    return QBrush(tile)


class CanvasView(QGraphicsView):
    """Displays the design and reports user interactions to the main window."""

    zoom_changed = Signal(float)
    selection_changed = Signal()
    texts_moved = Signal(dict)       # {element_id: (x, y)} after a drag
    text_activated = Signal(str)     # double-clicked text element id
    crop_changed = Signal(QRect)
    file_dropped = Signal(str)

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self.setRenderHints(
            QPainter.RenderHint.Antialiasing
            | QPainter.RenderHint.SmoothPixmapTransform
            | QPainter.RenderHint.TextAntialiasing
        )
        self.setViewportUpdateMode(QGraphicsView.ViewportUpdateMode.FullViewportUpdate)
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self.setResizeAnchor(QGraphicsView.ViewportAnchor.AnchorViewCenter)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.setFrameShape(QGraphicsView.Shape.NoFrame)
        self.setAcceptDrops(True)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._image_item = ImageItem()
        self._scene.addItem(self._image_item)
        self._image_size = (0, 0)
        self._texts: dict[str, TextItem] = {}
        self._zoom = 1.0
        self._auto_fit = True
        self._checker = _checker_brush()
        self._press_positions: dict[str, QPointF] = {}
        self._pan_origin: QPointF | None = None
        self._crop: CropOverlay | None = None
        self._crop_anchor: QPointF | None = None
        self._crop_move_offset: QPointF | None = None
        self._scene.selectionChanged.connect(self.selection_changed)

    # ------------------------------------------------------------------ content

    @property
    def has_image(self) -> bool:
        return self._image_size != (0, 0)

    def image_rect(self) -> QRectF:
        return QRectF(0, 0, *self._image_size)

    def set_image(self, image: QImage, width: int, height: int) -> None:
        """Show ``image`` scaled to occupy width × height scene units."""
        pix = QPixmap.fromImage(image)
        self._image_item.setPixmap(pix)
        self._image_item.setScale(width / max(1, pix.width()))
        size_changed = (width, height) != self._image_size
        self._image_size = (width, height)
        if size_changed:
            margin = max(width, height) * 2
            self.setSceneRect(self.image_rect().adjusted(-margin, -margin, margin, margin))
            if self._auto_fit:
                self.fit_to_view()
        self.viewport().update()

    def sync_texts(self, texts: list[TextElement]) -> None:
        ids = {t.id for t in texts}
        for element_id in list(self._texts):
            if element_id not in ids:
                self._scene.removeItem(self._texts.pop(element_id))
        for z, element in enumerate(texts):
            item = self._texts.get(element.id)
            if item is None:
                item = TextItem(element.id)
                self._texts[element.id] = item
                self._scene.addItem(item)
            item.apply_element(element)
            item.setZValue(10 + z)

    def update_text(self, element: TextElement) -> None:
        item = self._texts.get(element.id)
        if item is not None:
            item.apply_element(element)

    def select_text(self, element_id: str) -> None:
        item = self._texts.get(element_id)
        if item is not None:
            self._scene.clearSelection()
            item.setSelected(True)
            self.ensureVisible(item, 40, 40)

    def selected_text_id(self) -> str | None:
        for item in self._scene.selectedItems():
            if isinstance(item, TextItem):
                return item.element_id
        return None

    def is_image_selected(self) -> bool:
        return self._image_item.isSelected()

    def clear_canvas(self) -> None:
        self.exit_crop_mode()
        for item in self._texts.values():
            self._scene.removeItem(item)
        self._texts.clear()
        self._image_item.setPixmap(QPixmap())
        self._image_size = (0, 0)
        self._auto_fit = True
        self.resetTransform()
        self._zoom = 1.0

    # ------------------------------------------------------------------ zoom

    def zoom(self) -> float:
        return self._zoom

    def set_zoom(self, value: float, under_mouse: bool = False) -> None:
        value = min(MAX_ZOOM, max(MIN_ZOOM, value))
        anchor = (
            QGraphicsView.ViewportAnchor.AnchorUnderMouse if under_mouse
            else QGraphicsView.ViewportAnchor.AnchorViewCenter
        )
        self.setTransformationAnchor(anchor)
        self.setTransform(QTransform.fromScale(value, value))
        self.setTransformationAnchor(QGraphicsView.ViewportAnchor.AnchorUnderMouse)
        self._zoom = value
        self.zoom_changed.emit(value)

    def zoom_in(self) -> None:
        self._auto_fit = False
        self.set_zoom(self._zoom * ZOOM_STEP)

    def zoom_out(self) -> None:
        self._auto_fit = False
        self.set_zoom(self._zoom / ZOOM_STEP)

    def zoom_to(self, value: float) -> None:
        self._auto_fit = False
        self.set_zoom(value)
        self.centerOn(self.image_rect().center())

    def fit_to_view(self) -> None:
        if not self.has_image:
            return
        width, height = self._image_size
        available_w = max(40, self.viewport().width() - FIT_PADDING * 2)
        available_h = max(40, self.viewport().height() - FIT_PADDING * 2)
        self.set_zoom(min(available_w / width, available_h / height))
        self.centerOn(self.image_rect().center())
        self._auto_fit = True

    def actual_size(self) -> None:
        self.zoom_to(1.0)

    def resizeEvent(self, event) -> None:  # noqa: N802
        super().resizeEvent(event)
        if self._auto_fit and self.has_image:
            self.fit_to_view()

    def wheelEvent(self, event) -> None:  # noqa: N802
        if event.modifiers() & Qt.KeyboardModifier.ControlModifier:
            steps = event.angleDelta().y() / 120
            if steps:
                self._auto_fit = False
                self.set_zoom(self._zoom * (1.15 ** steps), under_mouse=True)
            event.accept()
            return
        super().wheelEvent(event)

    # ------------------------------------------------------------------ painting

    def apply_theme(self) -> None:
        """Rebuild theme-dependent brushes after a theme change."""
        self._checker = _checker_brush()
        self._scene.update()
        self.viewport().update()

    def drawBackground(self, painter: QPainter, rect: QRectF) -> None:  # noqa: N802
        painter.fillRect(rect, QColor(COLORS["canvas"]))
        if not self.has_image:
            return
        device_rect = self.mapFromScene(self.image_rect()).boundingRect()
        painter.save()
        painter.resetTransform()
        painter.setPen(Qt.PenStyle.NoPen)
        strength = 1.0 if is_dark() else 0.35
        for spread, alpha in ((18, 18), (10, 30), (4, 50)):
            painter.setBrush(QColor(0, 0, 0, round(alpha * strength)))
            painter.drawRoundedRect(QRectF(device_rect).adjusted(-spread, -spread + 6, spread, spread + 6),
                                    spread, spread)
        painter.fillRect(device_rect, self._checker)
        painter.restore()

    # ------------------------------------------------------------------ crop mode

    @property
    def in_crop_mode(self) -> bool:
        return self._crop is not None

    def enter_crop_mode(self) -> None:
        if not self.has_image or self._crop is not None:
            return
        self._scene.clearSelection()
        self._crop = CropOverlay(self.image_rect())
        rect = self.image_rect()
        self._crop.set_selection(rect.adjusted(rect.width() * 0.08, rect.height() * 0.08,
                                               -rect.width() * 0.08, -rect.height() * 0.08))
        self._scene.addItem(self._crop)
        for item in self._texts.values():
            item.unsetCursor()
        self.viewport().setCursor(Qt.CursorShape.CrossCursor)
        self.crop_changed.emit(self.crop_selection())

    def exit_crop_mode(self) -> None:
        if self._crop is None:
            return
        self._scene.removeItem(self._crop)
        self._crop = None
        self._crop_anchor = self._crop_move_offset = None
        for item in self._texts.values():
            item.setCursor(Qt.CursorShape.SizeAllCursor)
        self.viewport().unsetCursor()

    def crop_selection(self) -> QRect:
        """Current crop selection in whole image pixels, clamped to the image."""
        if self._crop is None:
            return QRect()
        sel = self._crop.selection
        width, height = self._image_size
        left = int(round(max(0, sel.left())))
        top = int(round(max(0, sel.top())))
        right = int(round(min(width, sel.right())))
        bottom = int(round(min(height, sel.bottom())))
        return QRect(left, top, max(1, right - left), max(1, bottom - top))

    def set_crop_selection(self, rect: QRect) -> None:
        if self._crop is not None:
            self._crop.set_selection(QRectF(rect))
            self.crop_changed.emit(self.crop_selection())

    def _clamp_to_image(self, point: QPointF) -> QPointF:
        width, height = self._image_size
        return QPointF(min(max(point.x(), 0.0), width), min(max(point.y(), 0.0), height))

    # ------------------------------------------------------------------ mouse

    def mousePressEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = event.position()
            self.viewport().setCursor(Qt.CursorShape.ClosedHandCursor)
            event.accept()
            return
        if self._crop is not None:
            if event.button() == Qt.MouseButton.LeftButton:
                point = self.mapToScene(event.position().toPoint())
                if self._crop.selection.contains(point):
                    self._crop_move_offset = point - self._crop.selection.topLeft()
                else:
                    self._crop_anchor = self._clamp_to_image(point)
                    self._crop.set_selection(QRectF(self._crop_anchor, self._crop_anchor))
            event.accept()
            return
        self._press_positions = {eid: QPointF(item.pos()) for eid, item in self._texts.items()}
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event) -> None:  # noqa: N802
        if self._pan_origin is not None:
            delta = event.position() - self._pan_origin
            self._pan_origin = event.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(delta.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(delta.y()))
            event.accept()
            return
        if self._crop is not None:
            point = self.mapToScene(event.position().toPoint())
            if self._crop_anchor is not None:
                self._crop.set_selection(QRectF(self._crop_anchor, self._clamp_to_image(point)))
                self.crop_changed.emit(self.crop_selection())
            elif self._crop_move_offset is not None:
                sel = QRectF(self._crop.selection)
                width, height = self._image_size
                top_left = point - self._crop_move_offset
                x = min(max(top_left.x(), 0.0), width - sel.width())
                y = min(max(top_left.y(), 0.0), height - sel.height())
                sel.moveTo(x, y)
                self._crop.set_selection(sel)
                self.crop_changed.emit(self.crop_selection())
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if self._pan_origin is not None and event.button() == Qt.MouseButton.MiddleButton:
            self._pan_origin = None
            if self._crop is not None:
                self.viewport().setCursor(Qt.CursorShape.CrossCursor)
            else:
                self.viewport().unsetCursor()
            event.accept()
            return
        if self._crop is not None:
            if self._crop_anchor is not None:
                sel = self._crop.selection
                if sel.width() < 4 or sel.height() < 4:  # a click, not a drag: select everything
                    self._crop.set_selection(self.image_rect())
            self._crop_anchor = self._crop_move_offset = None
            self.crop_changed.emit(self.crop_selection())
            event.accept()
            return
        super().mouseReleaseEvent(event)
        moved = {
            eid: (item.pos().x(), item.pos().y())
            for eid, item in self._texts.items()
            if eid in self._press_positions and item.pos() != self._press_positions[eid]
        }
        self._press_positions = {}
        if moved:
            self.texts_moved.emit(moved)

    def mouseDoubleClickEvent(self, event) -> None:  # noqa: N802
        if self._crop is None:
            item = self.itemAt(event.position().toPoint())
            if isinstance(item, TextItem):
                self.text_activated.emit(item.element_id)
                event.accept()
                return
        super().mouseDoubleClickEvent(event)

    # ------------------------------------------------------------------ drag & drop

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if dropped_image_path(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event) -> None:  # noqa: N802
        if dropped_image_path(event.mimeData()):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:  # noqa: N802
        path = dropped_image_path(event.mimeData())
        if path:
            event.acceptProposedAction()
            self.file_dropped.emit(path)
