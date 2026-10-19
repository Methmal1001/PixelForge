"""Main window: three-column studio layout and the editing controller."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from PIL import Image
from PySide6.QtCore import QObject, QRect, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QIcon, QImage, QKeySequence
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QScrollArea,
    QStackedWidget,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from app_info import APP_NAME
from models.design import Adjustments, TextElement
from models.presets import find_preset
from services.design_document import DesignDocument
from services.export_service import ExportError, ExportOptions, export_design
from services.config import get_setting, mask_secret, update_env
from services.gemini_provider import DEFAULT_MODEL, GeminiImageService
from services.pollinations_provider import PollinationsImageService
from services.generation_service import (
    GenerationError,
    GenerationQuotaError,
    PROVIDERS,
    GenerationRequest,
    get_generation_service,
    selected_provider,
    save_generation,
)
from services.image_processor import (
    ImageLoadError,
    ImageProcessingError,
    apply_adjustments,
    average_luminance,
    fit_to_size,
    has_transparency,
    make_thumbnail,
    supported_extensions,
)
from services.qt_image import pil_to_qimage
from services.sample_artwork import create_sample_design
from ui.adjust_panel import AdjustPanel
from ui.dialogs import CropDialog, ExportDialog, NewDesignDialog, ResizeDialog
from ui.editor_canvas import CanvasView
from ui.generation_panel import GenerationPanel
from ui.icons import refresh_icons, set_icon, set_pixmap
from ui.pages import AboutPage, ComingSoonPage, EmptyState, SettingsPage
from ui.preferences import save_theme_mode
from ui.sidebar import logo_pixmap
from ui.styles import THEME_MODES, active_mode, apply_theme, is_dark
from ui.text_panel import TextPanel
from ui.widgets import SegmentedControl, ToastManager, confirm, label, make_button

PREVIEW_MAX_SIDE = 1400
TEXT_SESSION_MS = 900

PLACEHOLDERS = {
    "projects": dict(
        icon_name="folder", title="My Projects", stage="Planned for Stage 3",
        description="Save designs as editable projects and reopen them later, with text layers intact.",
        bullets=["Project files stored in the local storage/projects folder",
                 "Auto-save and version snapshots",
                 "Until then, use Export to save PNG or JPEG files"],
    ),
    "recent": dict(
        icon_name="clock", title="Recent Designs", stage="Planned for Stage 3",
        description="Quickly jump back into designs you edited recently.",
        bullets=["Thumbnails of recently opened and exported designs",
                 "One-click reopen", "Pin favourites"],
    ),
    "templates": dict(
        icon_name="template", title="Templates", stage="Planned for Stage 3",
        description="Start from professionally laid-out templates for posts, stories and banners.",
        bullets=["Templates for each social-media size",
                 "Editable text placeholders",
                 "For now, try “Load Sample Design” on the empty canvas"],
    ),
    "history": dict(
        icon_name="history", title="Generation History", stage="Browser planned for Stage 3",
        description="Every AI generation is already saved to storage/generated as a PNG with a JSON file "
                    "holding its prompt and settings. A visual history browser arrives in Stage 3.",
        bullets=["Re-run or tweak previous prompts",
                 "Open any result in the editor",
                 "Until then, open files from storage/generated with Open Image"],
    ),
}


def _slug(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_") or "design"


class _RenderSignals(QObject):
    finished = Signal(int, object)


class _BackgroundSignals(QObject):
    """Delivers results of network work from a daemon thread to the GUI thread."""

    succeeded = Signal(str, object)   # task, result
    failed = Signal(str, object)      # task, exception


def _run_in_background(signals: _BackgroundSignals, task: str, work) -> None:
    """Run ``work()`` on a daemon thread (never blocks app exit) and emit its outcome."""
    def runner() -> None:
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - reported to the user via a toast
            signals.failed.emit(task, exc)
        else:
            signals.succeeded.emit(task, result)

    threading.Thread(target=runner, name=f"pixelforge-{task}", daemon=True).start()


class _RenderJob(QRunnable):
    """Applies colour adjustments to the full-resolution image off the GUI thread."""

    def __init__(self, generation: int, base: Image.Image, adjustments: Adjustments,
                 signals: _RenderSignals) -> None:
        super().__init__()
        self._generation = generation
        self._base = base
        self._adjustments = adjustments
        self._signals = signals

    def run(self) -> None:
        image = apply_adjustments(self._base, self._adjustments)
        self._signals.finished.emit(self._generation, pil_to_qimage(image))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(logo_pixmap()))
        self.resize(1500, 940)
        self.setMinimumSize(1120, 720)

        self.document: DesignDocument | None = None
        self.generation_service = get_generation_service()
        self._last_dir = str(Path.home() / "Pictures") if (Path.home() / "Pictures").exists() else str(Path.home())
        self._last_export_dir = self._last_dir
        self._render_generation = 0
        self._preview_cache: tuple[Image.Image, Image.Image] | None = None
        self._adjust_session = False
        self._text_session_id: str | None = None
        self._text_session_timer = QTimer(self)
        self._text_session_timer.setSingleShot(True)
        self._text_session_timer.setInterval(TEXT_SESSION_MS)
        self._text_session_timer.timeout.connect(self._end_text_session)
        self._render_signals = _RenderSignals()
        self._render_signals.finished.connect(self._on_render_finished)
        self._background = _BackgroundSignals()
        self._background.succeeded.connect(self._on_background_succeeded)
        self._background.failed.connect(self._on_background_failed)
        self._pending_request: GenerationRequest | None = None

        self._create_actions()
        self._build_ui()
        self._connect_signals()
        self.toasts = ToastManager(self.centralWidget())
        self._refresh_provider_ui()
        self._update_ui_state()

    # ================================================================== UI construction

    def _action(self, text: str, icon_name: str, slot, shortcuts=(), tip: str | None = None) -> QAction:
        action = QAction(text, self)
        set_icon(action, icon_name, hover="strong")
        if shortcuts:
            action.setShortcuts([QKeySequence(s) for s in shortcuts])
            hint = QKeySequence(shortcuts[0]).toString(QKeySequence.SequenceFormat.NativeText)
            action.setToolTip(f"{tip or text}  ({hint})")
        else:
            action.setToolTip(tip or text)
        action.triggered.connect(slot)
        self.addAction(action)
        return action

    def _create_actions(self) -> None:
        a = self._action
        self.act_open = a("Open Image", "upload", self.open_image, ["Ctrl+O"], "Open an image")
        self.act_new = a("New Design", "plus_square", self.new_design, ["Ctrl+N"], "New blank canvas")
        self.act_undo = a("Undo", "undo", self.undo, [QKeySequence.StandardKey.Undo])
        self.act_redo = a("Redo", "redo", self.redo, ["Ctrl+Y", "Ctrl+Shift+Z"])
        self.act_zoom_in = a("Zoom In", "zoom_in", lambda: self.canvas.zoom_in(), ["Ctrl+=", "Ctrl++"])
        self.act_zoom_out = a("Zoom Out", "zoom_out", lambda: self.canvas.zoom_out(), ["Ctrl+-"])
        self.act_fit = a("Fit to Screen", "fit", lambda: self.canvas.fit_to_view(), ["Ctrl+0"])
        self.act_actual = a("Actual Size (100%)", "actual", lambda: self.canvas.actual_size(), ["Ctrl+1"])
        self.act_crop = a("Crop", "crop", self.toggle_crop, ["C"], "Crop — drag on the image to select")
        self.act_crop.setCheckable(True)
        self.act_resize = a("Resize", "resize", lambda: self.resize_canvas(), ["Ctrl+R"], "Resize canvas")
        self.act_rotate_left = a("Rotate Left", "rotate_left", lambda: self._doc_op(lambda d: d.rotate_left()),
                                 ["Ctrl+["], "Rotate 90° left")
        self.act_rotate_right = a("Rotate Right", "rotate_right",
                                  lambda: self._doc_op(lambda d: d.rotate_right()), ["Ctrl+]"], "Rotate 90° right")
        self.act_flip_h = a("Flip Horizontal", "flip_h", lambda: self._doc_op(lambda d: d.flip_horizontal()))
        self.act_flip_v = a("Flip Vertical", "flip_v", lambda: self._doc_op(lambda d: d.flip_vertical()))
        self.act_add_text = a("Add Text", "text", self.add_text, ["Ctrl+T"], "Add a text layer")
        self.act_delete_text = a("Delete Text", "trash", self.delete_selected_text,
                                 [QKeySequence.StandardKey.Delete, "Backspace"], "Delete selected text")
        self.act_clear = a("Clear Canvas", "clear", self.clear_canvas, tip="Clear the canvas")
        self.act_export = a("Export", "export", self.export_current, ["Ctrl+E"], "Export PNG or JPEG")
        self.act_generate = a("Generate", "sparkles",
                              lambda: self._on_generate(self.generation_panel.build_request()),
                              ["Ctrl+G"], "Generate with AI")
        self.act_apply_crop = a("Apply Crop", "check", self.apply_crop, ["Return", "Enter"])
        self.act_cancel_crop = a("Cancel Crop", "x", self.cancel_crop, ["Escape"])
        self.act_delete_text.setShortcutContext(Qt.ShortcutContext.WidgetWithChildrenShortcut)

    def _tool(self, action: QAction) -> QToolButton:
        button = QToolButton()
        button.setDefaultAction(action)
        button.setIconSize(QSize(19, 19))
        button.setAutoRaise(True)
        button.setCursor(Qt.CursorShape.PointingHandCursor)
        return button

    @staticmethod
    def _separator() -> QFrame:
        line = QFrame()
        line.setObjectName("ToolbarSep")
        line.setFixedSize(1, 22)
        return line

    def _build_ui(self) -> None:
        from ui.sidebar import Sidebar

        root = QWidget()
        root.setObjectName("AppRoot")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(0, 0, 0, 0)
        root_layout.setSpacing(0)

        self.sidebar = Sidebar()
        root_layout.addWidget(self.sidebar)
        self.main_stack = QStackedWidget()
        root_layout.addWidget(self.main_stack, 1)

        studio = QWidget()
        studio_layout = QHBoxLayout(studio)
        studio_layout.setContentsMargins(0, 0, 0, 0)
        studio_layout.setSpacing(0)
        studio_layout.addWidget(self._build_workspace(), 1)
        studio_layout.addWidget(self._build_right_panel())

        self.coming_soon = ComingSoonPage()
        self.about_page = AboutPage()
        self.settings_page = SettingsPage()
        self.settings_page.set_current(active_mode(), "dark" if is_dark() else "light")
        self.main_stack.addWidget(studio)
        self.main_stack.addWidget(self.coming_soon)
        self.main_stack.addWidget(self.about_page)
        self.main_stack.addWidget(self.settings_page)
        self.setCentralWidget(root)

    def _build_workspace(self) -> QWidget:
        workspace = QWidget()
        layout = QVBoxLayout(workspace)
        layout.setContentsMargins(22, 16, 22, 12)
        layout.setSpacing(12)

        # header
        header = QHBoxLayout()
        header.setSpacing(12)
        titles = QVBoxLayout()
        titles.setSpacing(1)
        self.title_label = label("Design Studio", "H2")
        self.meta_label = label("No design open", "Caption")
        titles.addWidget(self.title_label)
        titles.addWidget(self.meta_label)
        header.addLayout(titles)
        header.addSpacing(6)
        self.edited_badge = label("Unexported changes", "BadgeEdited")
        header.addWidget(self.edited_badge, 0, Qt.AlignmentFlag.AlignVCenter)
        header.addStretch(1)
        self.open_button = make_button("Open Image", None, "upload", "Open an image (Ctrl+O)")
        self.open_button.clicked.connect(self.open_image)
        header.addWidget(self.open_button)
        self.export_button = make_button("Export", "primary", "export", "Export PNG or JPEG (Ctrl+E)")
        self.export_button.setMinimumWidth(112)
        self.export_button.clicked.connect(self.export_current)
        header.addWidget(self.export_button)
        layout.addLayout(header)

        # toolbar
        toolbar = QFrame()
        toolbar.setObjectName("Toolbar")
        bar = QHBoxLayout(toolbar)
        bar.setContentsMargins(8, 5, 8, 5)
        bar.setSpacing(2)
        bar.addWidget(self._tool(self.act_open))
        bar.addWidget(self._tool(self.act_undo))
        bar.addWidget(self._tool(self.act_redo))
        bar.addWidget(self._separator())
        bar.addWidget(self._tool(self.act_zoom_out))
        self.zoom_button = QToolButton()
        self.zoom_button.setObjectName("ZoomButton")
        self.zoom_button.setText("100%")
        self.zoom_button.setFixedWidth(62)
        self.zoom_button.setToolTip("Zoom presets")
        self.zoom_button.setCursor(Qt.CursorShape.PointingHandCursor)
        self.zoom_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        zoom_menu = QMenu(self.zoom_button)
        for percent in (25, 50, 75, 100, 150, 200, 400):
            zoom_menu.addAction(f"{percent}%", lambda p=percent: self.canvas.zoom_to(p / 100))
        zoom_menu.addSeparator()
        zoom_menu.addAction(self.act_fit)
        self.zoom_button.setMenu(zoom_menu)
        bar.addWidget(self.zoom_button)
        bar.addWidget(self._tool(self.act_zoom_in))
        bar.addWidget(self._tool(self.act_fit))
        bar.addWidget(self._tool(self.act_actual))
        bar.addWidget(self._separator())
        for action in (self.act_crop, self.act_resize, self.act_rotate_left, self.act_rotate_right,
                       self.act_flip_h, self.act_flip_v):
            bar.addWidget(self._tool(action))
        bar.addWidget(self._separator())
        bar.addWidget(self._tool(self.act_add_text))
        bar.addWidget(self._tool(self.act_delete_text))
        bar.addStretch(1)
        bar.addWidget(self._tool(self.act_clear))
        layout.addWidget(toolbar)

        # crop bar
        self.crop_bar = QFrame()
        self.crop_bar.setObjectName("CropBar")
        crop = QHBoxLayout(self.crop_bar)
        crop.setContentsMargins(14, 8, 10, 8)
        crop.setSpacing(10)
        crop_icon = QLabel()
        set_pixmap(crop_icon, "crop", "strong", 18)
        crop.addWidget(crop_icon)
        crop_hint = label("Drag on the image to select the area to keep", "H3")
        crop_hint.setToolTip("Drag inside the selection to move it. Enter applies, Esc cancels.")
        crop.addWidget(crop_hint)
        crop.addStretch(1)
        self.crop_size_label = label("", "StatusText")
        crop.addWidget(self.crop_size_label)
        exact = make_button("Exact Values…", "ghost")
        exact.clicked.connect(self.crop_exact)
        cancel = make_button("Cancel", "ghost")
        cancel.clicked.connect(self.cancel_crop)
        apply = make_button("Apply Crop", "primary", "check")
        apply.clicked.connect(self.apply_crop)
        for button in (exact, cancel, apply):
            crop.addWidget(button)
        self.crop_bar.hide()
        layout.addWidget(self.crop_bar)

        # canvas
        canvas_frame = QFrame()
        canvas_frame.setObjectName("CanvasFrame")
        frame_layout = QVBoxLayout(canvas_frame)
        frame_layout.setContentsMargins(1, 1, 1, 1)
        self.canvas_stack = QStackedWidget()
        self.empty_state = EmptyState()
        self.canvas = CanvasView()
        self.canvas_stack.addWidget(self.empty_state)
        self.canvas_stack.addWidget(self.canvas)
        frame_layout.addWidget(self.canvas_stack)
        layout.addWidget(canvas_frame, 1)
        # Delete/Backspace only act while the canvas has focus, never while typing in a field.
        self.removeAction(self.act_delete_text)
        self.canvas.addAction(self.act_delete_text)

        # status row
        status = QHBoxLayout()
        status.setSpacing(18)
        self.dims_label = label("", "StatusText")
        self.selection_label = label("", "StatusText")
        self.zoom_status = label("", "StatusText")
        status.addWidget(self.dims_label)
        status.addWidget(self.selection_label, 1)
        status.addWidget(label("Ctrl + scroll to zoom · Middle-drag to pan", "Caption"))
        status.addWidget(self.zoom_status)
        layout.addLayout(status)
        return workspace

    def _build_right_panel(self) -> QWidget:
        panel = QFrame()
        panel.setObjectName("Panel")
        panel.setFixedWidth(372)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 16, 0, 0)
        layout.setSpacing(4)

        self.panel_tabs = SegmentedControl([("Generate", "sparkles"), ("Adjust", "settings"), ("Text", "text")])
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(16, 0, 16, 0)
        tabs_row.addWidget(self.panel_tabs)
        layout.addLayout(tabs_row)

        self.generation_panel = GenerationPanel()
        self.adjust_panel = AdjustPanel()
        self.text_panel = TextPanel()
        self.panel_stack = QStackedWidget()
        for page in (self.generation_panel, self.adjust_panel, self.text_panel):
            scroll = QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            scroll.setWidget(page)
            self.panel_stack.addWidget(scroll)
        layout.addWidget(self.panel_stack, 1)
        return panel

    def _connect_signals(self) -> None:
        self.sidebar.navigate.connect(self._on_navigate)
        self.coming_soon.back_requested.connect(self._show_studio)
        self.about_page.back_requested.connect(self._show_studio)
        self.settings_page.back_requested.connect(self._show_studio)
        self.settings_page.theme_selected.connect(self.set_theme)
        self.settings_page.provider_saved.connect(self._save_provider)
        self.settings_page.provider_test_requested.connect(self._test_provider)
        self.settings_page.provider_removed.connect(self._remove_provider)
        try:  # follow live Windows light/dark changes while in System mode
            QApplication.styleHints().colorSchemeChanged.connect(self._on_system_scheme_changed)
        except AttributeError:
            pass

        self.empty_state.open_requested.connect(self.open_image)
        self.empty_state.new_requested.connect(self.new_design)
        self.empty_state.sample_requested.connect(self.load_sample)
        self.empty_state.preset_requested.connect(self.new_from_preset)
        self.empty_state.file_dropped.connect(self.open_image_path)

        self.canvas.zoom_changed.connect(self._on_zoom_changed)
        self.canvas.selection_changed.connect(self._on_selection_changed)
        self.canvas.texts_moved.connect(self._on_texts_moved)
        self.canvas.text_activated.connect(self._on_text_activated)
        self.canvas.crop_changed.connect(lambda r: self.crop_size_label.setText(f"{r.width()} × {r.height()} px"))
        self.canvas.file_dropped.connect(self.open_image_path)

        self.panel_tabs.currentChanged.connect(self.panel_stack.setCurrentIndex)
        self.generation_panel.generate_requested.connect(self._on_generate)
        self.generation_panel.notify.connect(lambda k, t, m: self.toasts.show(k, t, m))
        self.adjust_panel.adjustments_changed.connect(self._on_adjustments_changed)
        self.adjust_panel.action_requested.connect(self._on_adjust_action)
        self.text_panel.add_requested.connect(self.add_text)
        self.text_panel.delete_requested.connect(self.delete_selected_text)
        self.text_panel.properties_changed.connect(self._on_text_properties)

    # ================================================================== navigation

    def _on_navigate(self, key: str) -> None:
        if key == "new":
            self._show_studio()
            self.new_design()
        elif key == "about":
            self.main_stack.setCurrentWidget(self.about_page)
        elif key == "settings":
            self.main_stack.setCurrentWidget(self.settings_page)
        elif key in PLACEHOLDERS:
            self.coming_soon.set_content(**PLACEHOLDERS[key])
            self.main_stack.setCurrentWidget(self.coming_soon)

    # ================================================================== theme

    def set_theme(self, mode: str, announce: bool = True) -> None:
        """Switch the colour theme ("dark", "light" or "system") and remember it."""
        if mode not in THEME_MODES:
            return
        self._applying_theme = True
        try:
            effective = apply_theme(QApplication.instance(), mode)
        finally:
            self._applying_theme = False
        save_theme_mode(mode)
        refresh_icons(self)
        self.canvas.apply_theme()
        self.settings_page.set_current(mode, effective)
        for widget in self.findChildren(QWidget):
            widget.update()
        if announce:
            detail = f"Following Windows — currently {effective}." if mode == "system" else ""
            self.toasts.show("success", f"{THEME_MODES[mode]} theme applied", detail, 2500)

    def _on_system_scheme_changed(self, *_args) -> None:
        if active_mode() == "system" and not getattr(self, "_applying_theme", False):
            QTimer.singleShot(0, lambda: self.set_theme("system", announce=False))

    def _show_studio(self) -> None:
        self.main_stack.setCurrentIndex(0)
        self.sidebar.set_current("new")

    # ================================================================== document lifecycle

    def _confirm_discard(self) -> bool:
        if self.document is None or not self.document.modified:
            return True
        return confirm(self, "Replace current design?", "Your current design has unexported changes.",
                       "Discard Changes", "Export it first if you want to keep it.")

    def open_image(self) -> None:
        patterns = " ".join(f"*{ext}" for ext in supported_extensions())
        path, _ = QFileDialog.getOpenFileName(self, "Open Image", self._last_dir, f"Images ({patterns})")
        if path:
            self.open_image_path(path)

    def open_image_path(self, path: str) -> None:
        self._show_studio()
        if not self._confirm_discard():
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            document = DesignDocument.from_file(path)
        except ImageLoadError as exc:
            QApplication.restoreOverrideCursor()
            self.toasts.show("error", "Couldn't open image", str(exc), 7000)
            return
        QApplication.restoreOverrideCursor()
        self._last_dir = str(Path(path).parent)
        self._set_document(document)
        self.toasts.show("success", f"Opened {Path(path).name}", f"{document.width} × {document.height} px")

    def new_design(self) -> None:
        dialog = NewDesignDialog(self)
        if dialog.exec() and self._confirm_discard():
            width, height, background = dialog.values()
            self._set_document(DesignDocument.blank(width, height, background))

    def new_from_preset(self, key: str) -> None:
        preset = find_preset(key)
        if preset and self._confirm_discard():
            document = DesignDocument.blank(preset.width, preset.height, "gradient")
            document.name = f"{preset.name} {preset.width}×{preset.height}"
            self._set_document(document)

    def load_sample(self) -> None:
        if not self._confirm_discard():
            return
        image, texts = create_sample_design()
        document = DesignDocument(image, name="Sample design")
        for element in texts:
            document.add_text(element, record=False)
        document.modified = False
        self._set_document(document)
        self.toasts.show("info", "Sample design loaded",
                         "Placeholder artwork drawn locally with Pillow — not AI-generated. "
                         "Every text layer is editable.", 6000)

    def _set_document(self, document: DesignDocument) -> None:
        self._exit_crop()
        self._end_text_session()
        self._adjust_session = False
        self.document = document
        self._preview_cache = None
        self.canvas.clear_canvas()
        self.canvas_stack.setCurrentWidget(self.canvas)
        self._refresh_image()
        self.canvas.sync_texts(document.state.texts)
        QTimer.singleShot(0, self.canvas.fit_to_view)
        self.adjust_panel.set_adjustments(document.state.adjustments)
        self.text_panel.load_element(None)
        if self.panel_tabs.currentIndex() == 0:
            self.panel_tabs.setCurrentIndex(1)
        self._update_ui_state()

    def clear_canvas(self) -> None:
        if self.document is None:
            return
        if not confirm(self, "Clear canvas?", "This removes the image and all text layers from the canvas.",
                       "Clear Canvas", "This cannot be undone. Export first if you want to keep the design."):
            return
        self._exit_crop()
        self.document = None
        self._preview_cache = None
        self.canvas.clear_canvas()
        self.canvas_stack.setCurrentWidget(self.empty_state)
        self.text_panel.load_element(None)
        self.adjust_panel.set_adjustments(Adjustments())
        self._update_ui_state()

    # ================================================================== rendering

    def _preview_base(self) -> Image.Image:
        base = self.document.state.base
        if self._preview_cache is None or self._preview_cache[0] is not base:
            preview = base if max(base.size) <= PREVIEW_MAX_SIDE else make_thumbnail(base, PREVIEW_MAX_SIDE)
            self._preview_cache = (base, preview)
        return self._preview_cache[1]

    def _show_preview(self) -> None:
        doc = self.document
        preview = apply_adjustments(self._preview_base(), doc.state.adjustments)
        self.canvas.set_image(pil_to_qimage(preview), doc.width, doc.height)

    def _refresh_image(self) -> None:
        """Show the current image; adjustments render at full size in the background."""
        doc = self.document
        if doc is None:
            return
        self._render_generation += 1
        if doc.state.adjustments.is_identity():
            self.canvas.set_image(pil_to_qimage(doc.state.base), doc.width, doc.height)
            return
        self._show_preview()
        job = _RenderJob(self._render_generation, doc.state.base, doc.state.adjustments, self._render_signals)
        QThreadPool.globalInstance().start(job)

    def _on_render_finished(self, generation: int, image: QImage) -> None:
        if generation == self._render_generation and self.document is not None:
            self.canvas.set_image(image, self.document.width, self.document.height)

    def _after_change(self) -> None:
        """Bring every view back in sync with the document."""
        doc = self.document
        if doc is None:
            return
        self._refresh_image()
        self.canvas.sync_texts(doc.state.texts)
        self.adjust_panel.set_adjustments(doc.state.adjustments)
        text_id = self.canvas.selected_text_id()
        self.text_panel.load_element(doc.get_text(text_id) if text_id else None)
        self._update_ui_state()

    # ================================================================== editing

    def _doc_op(self, operation) -> None:
        if self.document is None:
            return
        self._exit_crop()
        self._end_text_session()
        try:
            operation(self.document)
        except ImageProcessingError as exc:
            self.toasts.show("error", "Edit not applied", str(exc))
            return
        self._after_change()

    def undo(self) -> None:
        if self.document and not self.canvas.in_crop_mode and self.document.undo():
            self._end_text_session()
            self._adjust_session = False
            self._after_change()

    def redo(self) -> None:
        if self.document and not self.canvas.in_crop_mode and self.document.redo():
            self._end_text_session()
            self._adjust_session = False
            self._after_change()

    def resize_canvas(self, preset_key: str | None = None) -> None:
        if self.document is None:
            return
        dialog = ResizeDialog(self, self.document.width, self.document.height, preset_key)
        if dialog.exec():
            width, height, mode = dialog.values()
            self._doc_op(lambda d: d.resize(width, height, mode))

    def _on_adjust_action(self, action: str) -> None:
        if self.document is None:
            return
        if action.startswith("preset:"):
            self.resize_canvas(action.split(":", 1)[1])
        elif action == "crop":
            self.toggle_crop()
        elif action == "resize":
            self.resize_canvas()
        elif action == "rotate_left":
            self._doc_op(lambda d: d.rotate_left())
        elif action == "rotate_right":
            self._doc_op(lambda d: d.rotate_right())
        elif action == "flip_h":
            self._doc_op(lambda d: d.flip_horizontal())
        elif action == "flip_v":
            self._doc_op(lambda d: d.flip_vertical())
        elif action == "reset_adjustments":
            if self.document.state.adjustments.is_identity():
                self.toasts.show("info", "Nothing to reset", "Adjustments are already neutral.")
            else:
                self._doc_op(lambda d: d.reset_adjustments())
        elif action == "reset_image":
            if confirm(self, "Reset all image edits?",
                       "Crop, resize, rotation, flips and colour adjustments will be removed.",
                       "Reset Image", "Text layers are kept. You can undo this with Ctrl+Z."):
                self._doc_op(lambda d: d.reset_image())
                self.toasts.show("success", "Original image restored", "")

    def _on_adjustments_changed(self, adjustments: Adjustments, interactive: bool) -> None:
        doc = self.document
        if doc is None:
            return
        if adjustments != doc.state.adjustments:
            if not self._adjust_session:
                doc.checkpoint()
                self._adjust_session = True
            doc.set_adjustments(adjustments)
        if interactive:
            self._render_generation += 1
            self._show_preview()
        else:
            self._adjust_session = False
            self._refresh_image()
        self._update_ui_state()

    # ------------------------------------------------------------------ crop

    def toggle_crop(self) -> None:
        if self.canvas.in_crop_mode:
            self.cancel_crop()
            return
        if self.document is None:
            self.act_crop.setChecked(False)
            return
        self.canvas.enter_crop_mode()
        self.crop_bar.show()
        self.act_crop.setChecked(True)
        self._update_ui_state()

    def _exit_crop(self) -> None:
        self.canvas.exit_crop_mode()
        self.crop_bar.hide()
        self.act_crop.setChecked(False)

    def cancel_crop(self) -> None:
        self._exit_crop()
        self._update_ui_state()

    def apply_crop(self) -> None:
        if not self.canvas.in_crop_mode:
            return
        rect = self.canvas.crop_selection()
        self._apply_crop_rect(rect)

    def crop_exact(self) -> None:
        if self.document is None:
            return
        dialog = CropDialog(self, self.document.width, self.document.height, self.canvas.crop_selection())
        if dialog.exec():
            self._apply_crop_rect(dialog.values())

    def _apply_crop_rect(self, rect: QRect) -> None:
        self._doc_op(lambda d: d.crop(rect.left(), rect.top(), rect.width(), rect.height()))

    # ------------------------------------------------------------------ text

    def add_text(self) -> None:
        doc = self.document
        if doc is None:
            self.toasts.show("info", "No canvas yet", "Open an image or create a canvas before adding text.")
            return
        self._exit_crop()
        self._end_text_session()
        size = max(16, round(min(doc.width, doc.height) * 0.08))
        offset = (len(doc.state.texts) % 5) * size * 0.9
        x, y = doc.width * 0.08 + offset * 0.4, doc.height * 0.1 + offset
        preview = apply_adjustments(self._preview_base(), doc.state.adjustments)
        scale = preview.width / doc.width
        box = (int(x * scale), int(y * scale),
               max(int(x * scale) + 2, min(preview.width, int((x + size * 6) * scale))),
               max(int(y * scale) + 2, min(preview.height, int((y + size * 1.3) * scale))))
        color = "#FFFFFF" if average_luminance(preview, box) < 150 else "#111318"
        element = TextElement(text="Your headline", x=x, y=y, font_size=size, color=color, bold=True)
        doc.add_text(element)
        self.canvas.sync_texts(doc.state.texts)
        self.canvas.select_text(element.id)
        self.panel_tabs.setCurrentIndex(2)
        self.text_panel.focus_content()
        self._update_ui_state()

    def delete_selected_text(self) -> None:
        text_id = self.canvas.selected_text_id()
        if self.document is None or text_id is None:
            return
        self._end_text_session()
        self.document.remove_text(text_id)
        self._after_change()

    def _end_text_session(self) -> None:
        self._text_session_timer.stop()
        self._text_session_id = None

    def _on_text_properties(self, changes: dict) -> None:
        doc = self.document
        text_id = self.canvas.selected_text_id()
        if doc is None or text_id is None:
            return
        if self._text_session_id != text_id:
            doc.checkpoint()
            self._text_session_id = text_id
        self._text_session_timer.start()
        try:
            element = doc.update_text(text_id, **changes)
        except ValueError as exc:
            self.toasts.show("error", "Text not updated", str(exc))
            return
        self.canvas.update_text(element)
        self._update_ui_state()

    def _on_texts_moved(self, positions: dict) -> None:
        if self.document is None:
            return
        self._end_text_session()
        self.document.move_texts(positions)
        self._update_ui_state()

    def _on_text_activated(self, text_id: str) -> None:
        self.canvas.select_text(text_id)
        self.panel_tabs.setCurrentIndex(2)
        self.text_panel.focus_content()

    def _on_selection_changed(self) -> None:
        self._end_text_session()
        text_id = self.canvas.selected_text_id()
        element = self.document.get_text(text_id) if (self.document and text_id) else None
        self.text_panel.load_element(element)
        if element is not None:
            self.panel_tabs.setCurrentIndex(2)
        self._update_ui_state()

    # ================================================================== export & generation

    def export_current(self) -> None:
        doc = self.document
        if doc is None:
            self.toasts.show("info", "Nothing to export", "Open an image or create a canvas first.")
            return
        self._exit_crop()
        rendered = doc.rendered()
        dialog = ExportDialog(self, doc.width, doc.height, has_transparency(rendered))
        if not dialog.exec():
            return
        values = dialog.values()
        extension = ".png" if values["image_format"] == "PNG" else ".jpg"
        file_filter = "PNG image (*.png)" if extension == ".png" else "JPEG image (*.jpg *.jpeg)"
        default = Path(self._last_export_dir) / f"{_slug(doc.name)}_{values['width']}x{values['height']}{extension}"
        path, _ = QFileDialog.getSaveFileName(self, "Export Design", str(default), file_filter)
        if not path:
            return
        options = ExportOptions(path=Path(path), **values)
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            output = export_design(rendered, doc.state.texts, options)
        except (ExportError, ImageProcessingError) as exc:
            QApplication.restoreOverrideCursor()
            self.toasts.show("error", "Export failed", str(exc), 7000)
            return
        QApplication.restoreOverrideCursor()
        self._last_export_dir = str(output.parent)
        doc.modified = False
        self._update_ui_state()
        self.toasts.show("success", "Design exported",
                         f"{output.name} · {options.width} × {options.height} px\n{output.parent}", 6000)

    def _on_generate(self, request: GenerationRequest) -> None:
        self.panel_tabs.setCurrentIndex(0)
        if self._pending_request is not None:
            self.toasts.show("info", "Already generating", "Please wait for the current design to finish.")
            return
        try:
            request.validate()
        except ValueError as exc:
            self.toasts.show("warning", "Prompt needed", str(exc))
            self.generation_panel.prompt.setFocus()
            return
        service = self.generation_service
        if not service.is_configured:
            self.toasts.show("info", "AI generation is not configured",
                             "Add your Google AI Studio API key in Settings → AI provider.", 7000)
            self.generation_panel.set_status(
                "AI provider: not configured",
                "Nothing was sent. Open Settings → AI provider and paste your API key.", "warning")
            return
        if request.reference_image and not service.supports_reference:
            self.toasts.show("info", "Reference image not sent",
                             f"{service.short_name} does not accept uploaded reference images; "
                             "generating from the prompt only.", 6000)
        self._pending_request = request
        self.generation_panel.set_busy(True, service.name)
        _run_in_background(self._background, "generate", lambda: service.generate(request))

    def _finish_generation(self, image: Image.Image) -> None:
        request = self._pending_request
        self._pending_request = None
        self.generation_panel.set_busy(False)
        model = f"{self.generation_service.short_name} · {self.generation_service.model}"
        preset = find_preset(request.preset_key)
        if preset and image.size != (preset.width, preset.height):
            image = fit_to_size(image, preset.width, preset.height, "fill")
        try:
            saved = save_generation(image, request, model)
        except OSError as exc:
            saved = None
            self.toasts.show("warning", "Result not saved to disk", str(exc))
        self.generation_panel.set_status(
            "Design generated", f"{image.width} × {image.height} px · {model}"
            + (" · a copy is saved in the storage/generated folder" if saved else ""), "success")
        if not self._confirm_discard():
            self.toasts.show("info", "Generated design kept on disk",
                             f"Your current design was left open. The result is in {saved}", 8000)
            return
        document = DesignDocument(image, name=f"AI · {request.prompt.strip()[:32]}", source_path=saved)
        document.modified = True
        self._show_studio()
        self._set_document(document)
        self.panel_tabs.setCurrentIndex(0)
        self.toasts.show("success", "AI design ready",
                         f"Generated with {self.generation_service.name}. Edit it, add text, then Export.",
                         6000)

    def _fail_generation(self, exc: Exception) -> None:
        self._pending_request = None
        self.generation_panel.set_busy(False)
        message = str(exc) if isinstance(exc, GenerationError) else f"Unexpected error: {exc}"
        title = "Image quota unavailable" if isinstance(exc, GenerationQuotaError) else "Generation failed"
        self.generation_panel.set_status(title, message, "error")
        self.toasts.show("error", title, message, 12000)

    # ------------------------------------------------------------------ provider settings

    def _refresh_provider_ui(self, note: str = "") -> None:
        self.generation_service = get_generation_service()
        service = self.generation_service
        self.generation_panel.set_provider(service, service.is_configured)
        model = get_setting("GEMINI_IMAGE_MODEL") or DEFAULT_MODEL
        self.settings_page.set_provider_state(
            selected_provider(), mask_secret(get_setting("GEMINI_API_KEY")), model, note)
        self.sidebar.set_ai_status(
            f"{service.short_name} AI ready" if service.is_configured else "AI provider not configured",
            "success" if service.is_configured else "warning")

    def _save_provider(self, provider: str, api_key: str, model: str) -> None:
        values: dict[str, str | None] = {"AI_PROVIDER": provider}
        if provider == "gemini":
            if not api_key and not get_setting("GEMINI_API_KEY"):
                self.toasts.show("warning", "API key needed", "Paste your Google AI Studio API key first.")
                return
            values["GEMINI_IMAGE_MODEL"] = model
            if api_key:
                values["GEMINI_API_KEY"] = api_key
        try:
            update_env(values)
        except OSError as exc:
            self.toasts.show("error", "Settings not saved", f"Could not write .env: {exc}")
            return
        self._refresh_provider_ui("Saved. Use Test Connection to check the provider is reachable.")
        self.toasts.show("success", "AI provider saved", PROVIDERS.get(provider, provider))

    def _test_provider(self, provider: str, api_key: str, model: str) -> None:
        if provider == "pollinations":
            self.settings_page.test_button.setEnabled(False)
            self.settings_page.set_provider_note("Contacting Pollinations.ai…")
            service = PollinationsImageService()
            _run_in_background(self._background, "test_pollinations", service.check_connection)
            return
        key = api_key or get_setting("GEMINI_API_KEY")
        if not key:
            self.toasts.show("warning", "API key needed", "Paste your Google AI Studio API key first.")
            return
        self.settings_page.test_button.setEnabled(False)
        self.settings_page.set_provider_note("Contacting Google…")
        service = GeminiImageService(key, model)
        _run_in_background(self._background, "test", lambda: (model, service.list_image_models()))

    def _remove_provider(self) -> None:
        if not confirm(self, "Remove API key?", "The saved Google AI Studio key will be deleted from .env.",
                       "Remove Key", "AI generation will be disabled until you add a key again."):
            return
        update_env({"GEMINI_API_KEY": None})
        self._refresh_provider_ui()
        self.toasts.show("info", "API key removed", "AI generation is now disabled.")

    def _on_background_succeeded(self, task: str, result) -> None:
        if task == "generate":
            self._finish_generation(result)
        elif task == "test_pollinations":
            self.settings_page.test_button.setEnabled(True)
            note = (f"Pollinations.ai is reachable (free model: {', '.join(result) or 'unknown'}). "
                    "No image was generated by this check.")
            self.settings_page.set_provider_note(note)
            self.toasts.show("success", "Connection OK", note, 7000)
        elif task == "test":
            model, models = result
            self.settings_page.test_button.setEnabled(True)
            available = model in models
            note = (f"Key accepted by Google. {len(models)} image models visible; "
                    f"“{model}” is {'available' if available else 'NOT available — choose another model'}. "
                    "This check uses no quota, so it cannot confirm image quota or billing.")
            self.settings_page.set_provider_note(note)
            self.toasts.show("success" if available else "warning",
                             "Connection OK" if available else "Model not available", note, 9000)

    def _on_background_failed(self, task: str, exc: Exception) -> None:
        if task == "generate":
            self._fail_generation(exc)
        elif task in ("test", "test_pollinations"):
            self.settings_page.test_button.setEnabled(True)
            self.settings_page.set_provider_note(f"Connection failed: {exc}")
            self.toasts.show("error", "Connection failed", str(exc), 9000)

    # ================================================================== status

    def _on_zoom_changed(self, zoom: float) -> None:
        text = f"{zoom * 100:.0f}%"
        self.zoom_button.setText(text)
        self.zoom_status.setText(f"Zoom {text}")

    def _update_ui_state(self) -> None:
        doc = self.document
        has_doc = doc is not None
        cropping = self.canvas.in_crop_mode
        selected_text = self.canvas.selected_text_id() if has_doc else None

        for action in (self.act_zoom_in, self.act_zoom_out, self.act_fit, self.act_actual, self.act_crop,
                       self.act_clear, self.act_add_text):
            action.setEnabled(has_doc)
        for action in (self.act_resize, self.act_rotate_left, self.act_rotate_right,
                       self.act_flip_h, self.act_flip_v, self.act_export):
            action.setEnabled(has_doc and not cropping)
        self.act_undo.setEnabled(has_doc and doc.can_undo and not cropping)
        self.act_redo.setEnabled(has_doc and doc.can_redo and not cropping)
        self.act_delete_text.setEnabled(selected_text is not None and not cropping)
        self.act_apply_crop.setEnabled(cropping)
        self.act_cancel_crop.setEnabled(cropping)
        self.export_button.setEnabled(has_doc)
        self.adjust_panel.set_document_available(has_doc)
        self.text_panel.set_document_available(has_doc)

        if not has_doc:
            self.title_label.setText("Design Studio")
            self.meta_label.setText("No design open — open an image or start a new canvas")
            self.edited_badge.hide()
            self.dims_label.setText("")
            self.selection_label.setText("")
            self.zoom_status.setText("")
            self.zoom_button.setText("—")
            self.setWindowTitle(APP_NAME)
            return

        source = f" · {doc.source_path.name}" if doc.source_path else ""
        self.title_label.setText(doc.name)
        self.meta_label.setText(f"{doc.width} × {doc.height} px · {doc.state.base.mode}{source}")
        self.edited_badge.setVisible(doc.modified)
        self.setWindowTitle(f"{doc.name}{' •' if doc.modified else ''} — {APP_NAME}")
        self.dims_label.setText(f"Canvas  {doc.width} × {doc.height} px")

        if selected_text:
            element = doc.get_text(selected_text)
            preview = element.text.replace("\n", " ")
            preview = preview if len(preview) <= 28 else preview[:27] + "…"
            self.selection_label.setText(
                f"Selected: text “{preview}” · {element.font_size}px {element.font_family} · "
                f"x {element.x:.0f}, y {element.y:.0f}")
        elif self.canvas.is_image_selected():
            self.selection_label.setText(
                f"Selected: image · {doc.width} × {doc.height} px · {len(doc.state.texts)} text layer(s)")
        else:
            self.selection_label.setText(f"{len(doc.state.texts)} text layer(s) · click an element to select it")

    # ================================================================== window

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.document is not None and self.document.modified:
            if not confirm(self, "Quit PixelForge AI Studio?", "Your design has unexported changes.",
                           "Quit Without Exporting", "Use Export (Ctrl+E) to save it as PNG or JPEG."):
                event.ignore()
                return
        QThreadPool.globalInstance().waitForDone(2000)
        event.accept()
