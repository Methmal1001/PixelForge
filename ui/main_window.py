"""Main window: three-column studio layout and the editing controller."""

from __future__ import annotations

import re
import threading
from pathlib import Path

from PIL import Image, ImageChops
from PySide6.QtCore import QObject, QRect, QRunnable, QSize, Qt, QThreadPool, QTimer, Signal
from PySide6.QtGui import QAction, QCloseEvent, QColor, QIcon, QImage, QKeySequence
from PySide6.QtWidgets import (
    QAbstractSpinBox,
    QSpinBox,
    QButtonGroup,
    QColorDialog,
    QInputDialog,
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
from services.manus_provider import DEFAULT_PROFILE as MANUS_DEFAULT_PROFILE
from services.manus_provider import ManusImageService
from services.pollinations_provider import PollinationsImageService
from services.generation_service import (
    GenerationCancelledError,
    GenerationError,
    GenerationQuotaError,
    PROVIDER_SETTINGS,
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
    load_image,
    make_thumbnail,
    supported_extensions,
)
from services import region_tools
from services.qt_image import pil_to_qimage
from models.brand import REFERENCE_WIDTH as BRAND_REFERENCE_WIDTH
from models.brand import BrandDetails, BrandField, split_values
from services.text_renderer import TextLayout
from services.sample_artwork import create_sample_design
from ui.adjust_panel import AdjustPanel
from ui.dialogs import CropDialog, ExportDialog, NewDesignDialog, RegionAdjustDialog, ResizeDialog
from ui.editor_canvas import CanvasView
from ui.generation_panel import GenerationPanel
from ui.icons import refresh_icons, set_icon, set_pixmap
from ui.pages import AboutPage, ComingSoonPage, EmptyState, SettingsPage
from ui.preferences import load_brand, save_brand, save_theme_mode
from ui.sidebar import logo_pixmap
from ui.styles import THEME_MODES, active_mode, apply_theme, is_dark
from ui.layers_panel import LayersPanel
from ui.text_panel import TextPanel
from ui.widgets import ElidedLabel, SegmentedControl, ToastManager, confirm, label, make_button

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
        description="Every AI generation is already saved to Pictures\\PiXdEm AI STUDIO\\Generated as a PNG with a JSON file "
                    "holding its prompt and settings. A visual history browser arrives in Stage 3.",
        bullets=["Re-run or tweak previous prompts",
                 "Open any result in the editor",
                 "Until then, open files from that folder with Open Image"],
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
    progress = Signal(str)            # status text from a running generation


def _run_in_background(signals: _BackgroundSignals, task: str, work) -> None:
    """Run ``work()`` on a daemon thread (never blocks app exit) and emit its outcome."""
    def runner() -> None:
        try:
            result = work()
        except Exception as exc:  # noqa: BLE001 - reported to the user via a toast
            signals.failed.emit(task, exc)
        else:
            signals.succeeded.emit(task, result)

    threading.Thread(target=runner, name=f"pixdem-{task}", daemon=True).start()


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
        self._background.progress.connect(self._on_generation_progress)
        self._pending_request: GenerationRequest | None = None
        self._generating_service = None
        self._generation_token = 0      # identifies the run whose result we still want

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
        self.act_duplicate_text = a("Duplicate Text", "copy", self.duplicate_selected_text, ["Ctrl+D"],
                                    "Duplicate the selected text layer")
        self.act_delete_text = a("Delete Text", "trash", self.delete_selected_text,
                                 [QKeySequence.StandardKey.Delete, "Backspace"], "Delete selected text")
        self.act_clear = a("Clear Canvas", "clear", self.clear_canvas, tip="Clear the canvas")
        self.act_export = a("Export", "export", self.export_current, ["Ctrl+E"], "Export PNG or JPEG")
        self.act_generate = a("Generate", "sparkles",
                              lambda: self._on_generate(self.generation_panel.build_request()),
                              ["Ctrl+G"], "Generate with AI")
        self.act_apply_crop = a("Apply Crop", "check", self.apply_crop, ["Return", "Enter"])
        self.act_cancel_crop = a("Cancel", "x", self.cancel_mode, ["Escape"])
        self.act_select = a("Select Area", "select", self.toggle_select, ["M"],
                            "Select an area to adjust, blur, remove, fill or erase")
        self.act_select.setCheckable(True)
        self.act_copy_layer = a("Copy to Layer", "copy", lambda: self._region_action("copy_layer"), ["Ctrl+J"])
        self.act_cut_layer = a("Cut to Layer", "layers", lambda: self._region_action("cut_layer"), ["Shift+Ctrl+J"])
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
        self.title_label = ElidedLabel("Design Studio", "H2", Qt.TextElideMode.ElideRight)
        self.meta_label = ElidedLabel("No design open", "Caption")
        titles.addWidget(self.title_label)
        titles.addWidget(self.meta_label)
        header.addLayout(titles, 1)
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
        bar.addWidget(self._tool(self.act_select))
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

        # area selection bar
        self.select_bar = QFrame()
        self.select_bar.setObjectName("CropBar")
        bar_rows = QVBoxLayout(self.select_bar)
        bar_rows.setContentsMargins(12, 6, 8, 6)
        bar_rows.setSpacing(4)
        sel = QHBoxLayout()
        sel.setSpacing(6)
        actions_row = QHBoxLayout()
        actions_row.setSpacing(4)
        bar_rows.addLayout(sel)
        bar_rows.addLayout(actions_row)
        self._shape_group = QButtonGroup(self)
        self._shape_group.setExclusive(True)
        for key, icon_name, tip in (("rect", "select", "Rectangle selection"),
                                    ("ellipse", "ellipse_select", "Ellipse selection"),
                                    ("lasso", "lasso", "Freehand lasso selection"),
                                    ("wand", "magic", "Magic Wand: click to select an object or area of similar "
                                                      "colour (Shift+click adds)")):
            button = QToolButton()
            button.setCheckable(True)
            set_icon(button, icon_name)
            button.setIconSize(QSize(18, 18))
            button.setToolTip(tip)
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.clicked.connect(lambda _c=False, k=key: self._set_select_shape(k))
            self._shape_group.addButton(button)
            button.setProperty("shape", key)
            if key == "rect":
                button.setChecked(True)
            sel.addWidget(button)
        self.wand_tolerance = QSpinBox()
        self.wand_tolerance.setRange(1, 150)
        self.wand_tolerance.setValue(40)
        self.wand_tolerance.setPrefix("Tolerance ")
        self.wand_tolerance.setButtonSymbols(QAbstractSpinBox.ButtonSymbols.NoButtons)
        self.wand_tolerance.setToolTip("Magic Wand: higher values select a wider range of similar colours")
        self.wand_tolerance.setFixedWidth(118)
        self.wand_tolerance.hide()
        sel.addWidget(self.wand_tolerance)
        sel.addWidget(self._separator())
        self.select_hint = label("Drag on the image to select an area", "H3")
        sel.addWidget(self.select_hint, 1)
        self._region_buttons = []
        for key, text, icon_name, tip in (
            ("adjust", "Adjust…", "settings", "Brightness, contrast, colour inside the selection"),
            ("blur", "Blur", "filter", "Blur the selected area"),
            ("sharpen", "Sharpen", "filter", "Sharpen the selected area"),
            ("remove", "Remove", "magic", "Remove objects or text by filling from the surroundings"),
            ("fill", "Fill…", "bucket", "Fill the selected area with a colour"),
            ("erase", "Erase", "eraser", "Make the selected area transparent"),
            ("crop", "Crop", "crop", "Crop the image to the selection"),
            ("copy_layer", "Copy Layer", "copy", "Copy the selection into a new movable layer (Ctrl+J)"),
            ("cut_layer", "Cut Layer", "layers",
             "Move the selection into a new layer and fill the hole behind it (Shift+Ctrl+J)"),
        ):
            button = make_button(text, "ghost", icon_name, tip)
            button.setStyleSheet("padding: 6px 7px;")
            button.clicked.connect(lambda _c=False, k=key: self._region_action(k))
            self._region_buttons.append(button)
            actions_row.addWidget(button)
        actions_row.addStretch(1)
        done = make_button("Done", "primary", "check", "Leave area selection (Esc)")
        done.clicked.connect(self.exit_select)
        sel.addWidget(done)
        self.select_bar.hide()
        layout.addWidget(self.select_bar)


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
        self.selection_label = ElidedLabel("", "StatusText", Qt.TextElideMode.ElideRight)
        self.zoom_status = label("", "StatusText")
        status.addWidget(self.dims_label)
        status.addWidget(self.selection_label, 1)
        status.addWidget(label("Ctrl + scroll to zoom · Drag to pan when zoomed in", "Caption"))
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

        self.panel_tabs = SegmentedControl([("Generate", "sparkles"), ("Adjust", "settings"), ("Text", "text"),
                                            ("Layers", "layers")])
        tabs_row = QHBoxLayout()
        tabs_row.setContentsMargins(16, 0, 16, 0)
        tabs_row.addWidget(self.panel_tabs)
        layout.addLayout(tabs_row)

        self.generation_panel = GenerationPanel()
        self.adjust_panel = AdjustPanel()
        self.text_panel = TextPanel()
        self.layers_panel = LayersPanel()
        self.panel_stack = QStackedWidget()
        for page in (self.generation_panel, self.adjust_panel, self.text_panel, self.layers_panel):
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
        self.canvas.layers_changed.connect(self._on_layers_changed)
        self.canvas.wand_clicked.connect(self._on_wand_clicked)
        self.layers_panel.item_selected.connect(self._on_layer_list_selected)
        self.layers_panel.layer_changed.connect(self._on_layer_properties)
        self.layers_panel.layer_action.connect(self._on_layer_action)
        self.layers_panel.add_image_requested.connect(self.add_image_layer)
        self.layers_panel.edit_text_requested.connect(lambda: self.panel_tabs.setCurrentIndex(2))
        self.canvas.text_activated.connect(self._on_text_activated)
        self.canvas.crop_changed.connect(lambda r: self.crop_size_label.setText(f"{r.width()} × {r.height()} px"))
        self.canvas.file_dropped.connect(self.open_image_path)

        self.panel_tabs.currentChanged.connect(self.panel_stack.setCurrentIndex)
        self.generation_panel.generate_requested.connect(self._on_generate)
        self.generation_panel.stop_requested.connect(self.stop_generation)
        self.generation_panel.edit_requested.connect(self._on_edit_requested)
        self.canvas.area_selection_changed.connect(self._on_area_selection_changed)
        self.generation_panel.set_brand(load_brand())
        self.generation_panel.notify.connect(lambda k, t, m: self.toasts.show(k, t, m))
        self.adjust_panel.adjustments_changed.connect(self._on_adjustments_changed)
        self.adjust_panel.action_requested.connect(self._on_adjust_action)
        self.text_panel.add_requested.connect(self.add_text)
        self.text_panel.delete_requested.connect(self.delete_selected_text)
        self.text_panel.arrange_requested.connect(self._on_text_arrange)
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
        self._exit_select()
        self._end_text_session()
        self._adjust_session = False
        self.document = document
        self._preview_cache = None
        self.canvas.clear_canvas()
        self.canvas_stack.setCurrentWidget(self.canvas)
        self._refresh_image()
        self.canvas.sync_texts(document.state.texts)
        self.canvas.sync_layers(document.state.layers)
        QTimer.singleShot(0, self.canvas.fit_to_view)
        self.adjust_panel.set_adjustments(document.state.adjustments)
        self._refresh_filter_thumbnails()
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
        self._exit_select()
        self.document = None
        self._preview_cache = None
        self.canvas.clear_canvas()
        self.canvas_stack.setCurrentWidget(self.empty_state)
        self.text_panel.load_element(None)
        self.adjust_panel.set_adjustments(Adjustments())
        self._refresh_filter_thumbnails()
        self._update_ui_state()

    # ================================================================== rendering

    def _refresh_filter_thumbnails(self) -> None:
        base = self.document.state.base if self.document else None
        if base is not getattr(self, "_filter_thumb_base", None):
            self._filter_thumb_base = base
            self.adjust_panel.set_filter_source(self._preview_base() if base is not None else None)

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
        self._refresh_filter_thumbnails()
        self.canvas.sync_texts(doc.state.texts)
        self.canvas.sync_layers(doc.state.layers)
        self.adjust_panel.set_adjustments(doc.state.adjustments)
        text_id = self.canvas.selected_text_id()
        self.text_panel.load_element(doc.get_text(text_id) if text_id else None)
        self._update_ui_state()

    # ================================================================== editing

    def _doc_op(self, operation) -> None:
        if self.document is None:
            return
        self._exit_crop()
        self._exit_select()
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
        elif action == "rotate_angle":
            self.rotate_by_angle()
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

    # ------------------------------------------------------------------ area selection

    def toggle_select(self) -> None:
        if self.canvas.in_select_mode:
            self.exit_select()
            return
        if self.document is None:
            self.act_select.setChecked(False)
            return
        self._exit_crop()
        shape = self._shape_group.checkedButton().property("shape") if self._shape_group.checkedButton() else "rect"
        self.canvas.enter_select_mode(shape)
        self.select_bar.show()
        self.act_select.setChecked(True)
        self._on_area_selection_changed(False)
        self._update_ui_state()

    def _exit_select(self) -> None:
        self.canvas.exit_select_mode()
        self.select_bar.hide()
        self.act_select.setChecked(False)

    def exit_select(self) -> None:
        self._exit_select()
        self._update_ui_state()

    def cancel_mode(self) -> None:
        """Esc: leave crop or area-selection mode."""
        if self.canvas.in_crop_mode:
            self.cancel_crop()
        elif self.canvas.in_select_mode:
            self.exit_select()

    def _on_area_selection_changed(self, selected: bool) -> None:
        for button in self._region_buttons:
            button.setEnabled(selected)
        self.select_hint.setText("Choose an action for the selected area" if selected
                                 else "Drag on the image to select an area")

    def _region_action(self, action: str) -> None:
        doc = self.document
        selection = self.canvas.area_selection()
        if doc is None or selection is None:
            self.toasts.show("info", "Select an area first", "Drag on the image to select an area.")
            return
        shape, points = selection
        if action in ("copy_layer", "cut_layer"):
            QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
            try:
                if action == "copy_layer":
                    layer = doc.copy_to_layer(shape, points)
                else:
                    layer = doc.cut_to_layer(shape, points)
            except ImageProcessingError as exc:
                QApplication.restoreOverrideCursor()
                self.toasts.show("error", "Layer not created", str(exc))
                return
            QApplication.restoreOverrideCursor()
            self._exit_select()
            self._after_change()
            self.canvas.select_layer(layer.id)
            self.panel_tabs.setCurrentIndex(3)
            self.toasts.show("success", f"{layer.name} created",
                             "Drag it to move, drag a corner to resize. Opacity, rotation and more are in "
                             "the Layers tab.", 6000)
            return
        if action == "crop":
            self._exit_select()
            self._doc_op(lambda d: d.crop_to_selection(points))
            return
        options = {}
        if action == "fill":
            color = QColorDialog.getColor(QColor("#FFFFFF"), self, "Fill colour")
            if not color.isValid():
                return
            options["color"] = color.name()
        elif action == "adjust":
            dialog = RegionAdjustDialog(self, lambda values: self._preview_region_adjust(shape, points, values))
            accepted = dialog.exec()
            self._refresh_image()
            if not accepted or dialog.values().is_identity():
                return
            options["adjustments"] = dialog.values()
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            doc.edit_region(shape, points, action, **options)
        except ImageProcessingError as exc:
            QApplication.restoreOverrideCursor()
            self.toasts.show("error", "Edit not applied", str(exc))
            return
        QApplication.restoreOverrideCursor()
        self._after_change()
        names = {"adjust": "Adjusted", "blur": "Blurred", "sharpen": "Sharpened", "remove": "Removed",
                 "fill": "Filled", "erase": "Erased"}
        self.toasts.show("success", f"{names[action]} the selected area", "Undo with Ctrl+Z if needed.", 3000)

    def _preview_region_adjust(self, shape: str, points, values: Adjustments) -> None:
        doc = self.document
        if doc is None:
            return
        preview = self._preview_base()
        scale = preview.width / doc.width
        try:
            if shape == "mask":
                mask = points.resize(preview.size)
            else:
                mask = region_tools.build_mask(preview.size, shape, [(x * scale, y * scale) for x, y in points])
            edited = region_tools.apply_region(preview, mask, "adjust", adjustments=values)
        except ImageProcessingError:
            return
        self._render_generation += 1
        shown = apply_adjustments(edited, doc.state.adjustments)
        self.canvas.set_image(pil_to_qimage(shown), doc.width, doc.height)

    def _on_edit_requested(self, target: str) -> None:
        if self.document is None:
            return
        self._show_studio()
        if target == "text":
            self.panel_tabs.setCurrentIndex(2)
            if self.document.state.texts:
                self.canvas.select_text(self.document.state.texts[0].id)
            else:
                self.add_text("heading")
        elif target == "adjust":
            self.panel_tabs.setCurrentIndex(1)
        elif target == "select":
            if not self.canvas.in_select_mode:
                self.toggle_select()

    # ------------------------------------------------------------------ brand text layers

    def _add_brand_layers(self, document: DesignDocument, brand: BrandDetails) -> int:
        """Place filled-in brand details on the design as editable, centred text layers."""
        width, height = document.size
        scale = width / BRAND_REFERENCE_WIDTH
        margin = height * 0.06
        made = 0

        def element(item: BrandField, text: str, bold: bool, **extra) -> TextElement:
            return TextElement(text=text, font_size=max(10, round(item.size * scale)), color=item.color,
                               bold=bold, align="center", shadow=True, shadow_opacity=0.55,
                               shadow_distance=6, shadow_blur=12, **extra)

        def centre(el: TextElement, y: float) -> TextElement:
            layout = TextLayout(el)
            el.x = (width - layout.width) / 2
            el.y = y
            return el

        y = margin
        for item, bold in ((brand.company, True), (brand.description, False)):
            if item.filled:
                el = centre(element(item, item.text.strip(), bold), y)
                document.add_text(el, record=False)
                y += TextLayout(el).height + height * 0.015
                made += 1

        contact_lines = []
        if brand.phones.filled:
            contact_lines.append((brand.phones, "Tel: " + "  |  ".join(split_values(brand.phones.text))))
        if brand.emails.filled:
            contact_lines.append((brand.emails, "  |  ".join(split_values(brand.emails.text))))
        bottom = height - margin
        for item, text in reversed(contact_lines):
            el = element(item, text, False, background=True, background_color="#000000",
                         background_opacity=0.45, background_padding=35, background_radius=40)
            layout = TextLayout(el)
            bottom -= layout.height + layout.padding
            document.add_text(centre(el, bottom), record=False)
            bottom -= layout.padding + height * 0.015
            made += 1
        return made

    def toggle_crop(self) -> None:
        if self.canvas.in_crop_mode:
            self.cancel_crop()
            return
        if self.document is None:
            self.act_crop.setChecked(False)
            return
        self._exit_select()
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

    TEXT_STYLES = {
        # key: (default text, size as fraction of the shorter side, bold, vertical position)
        "heading": ("Your headline", 0.085, True, 0.10),
        "subheading": ("Add a subheading", 0.05, True, 0.24),
        "body": ("Add a little bit of body text", 0.032, False, 0.34),
    }

    def add_text(self, style: str = "heading") -> None:
        doc = self.document
        if doc is None:
            self.toasts.show("info", "No canvas yet", "Open an image or create a canvas before adding text.")
            return
        if not isinstance(style, str) or style not in self.TEXT_STYLES:
            style = "heading"  # QAction.triggered passes a bool
        self._exit_crop()
        self._end_text_session()
        text, fraction, bold, top = self.TEXT_STYLES[style]
        size = max(12, round(min(doc.width, doc.height) * fraction))
        offset = (len(doc.state.texts) % 4) * size * 0.6
        x, y = doc.width * 0.08 + offset * 0.4, doc.height * top + offset
        preview = apply_adjustments(self._preview_base(), doc.state.adjustments)
        scale = preview.width / doc.width
        box = (int(x * scale), int(y * scale),
               max(int(x * scale) + 2, min(preview.width, int((x + size * 6) * scale))),
               max(int(y * scale) + 2, min(preview.height, int((y + size * 1.3) * scale))))
        color = "#FFFFFF" if average_luminance(preview, box) < 150 else "#111318"
        element = TextElement(text=text, x=x, y=min(y, doc.height * 0.85), font_size=size, color=color, bold=bold)
        doc.add_text(element)
        self.canvas.sync_texts(doc.state.texts)
        self.canvas.sync_layers(doc.state.layers)
        self.canvas.select_text(element.id)
        self.panel_tabs.setCurrentIndex(2)
        self.text_panel.focus_content()
        self._update_ui_state()

    def _on_text_arrange(self, action: str) -> None:
        doc = self.document
        text_id = self.canvas.selected_text_id()
        if doc is None or text_id is None:
            self.toasts.show("info", "Select a text layer", "Click a text layer on the canvas first.")
            return
        self._end_text_session()
        element = doc.get_text(text_id)
        if action == "duplicate":
            copy = doc.duplicate_text(text_id, offset=max(12.0, element.font_size * 0.4))
            self._after_change()
            self.canvas.select_text(copy.id)
            return
        if action in ("forward", "backward"):
            if not doc.move_text_layer(text_id, 1 if action == "forward" else -1):
                where = "top" if action == "forward" else "bottom"
                self.toasts.show("info", f"Already at the {where}", "This text layer cannot move further.")
                return
        elif action in ("center_h", "center_v"):
            layout = TextLayout(element)
            if action == "center_h":
                doc.update_text(text_id, record=True, x=(doc.width - layout.width) / 2)
            else:
                doc.update_text(text_id, record=True, y=(doc.height - layout.height) / 2)
        self._after_change()
        self.canvas.select_text(text_id)

    def duplicate_selected_text(self) -> None:
        if self.canvas.selected_text_id():
            self._on_text_arrange("duplicate")

    def rotate_by_angle(self) -> None:
        if self.document is None:
            return
        angle, ok = QInputDialog.getDouble(self, "Rotate by Angle",
                                           "Angle in degrees (positive = clockwise):", 0.0, -180.0, 180.0, 1)
        if ok and angle:
            self._doc_op(lambda d: d.rotate_angle(angle))

    def delete_selected_text(self) -> None:
        """Delete the selected text layer or image layer."""
        if self.document is None:
            return
        layer_id = self.canvas.selected_layer_id()
        if layer_id is not None:
            self.document.remove_layer(layer_id)
            self._after_change()
            return
        text_id = self.canvas.selected_text_id()
        if text_id is None:
            return
        self._end_text_session()
        self.document.remove_text(text_id)
        self._after_change()

    # ------------------------------------------------------------------ image layers

    def _set_select_shape(self, shape: str) -> None:
        self.canvas.set_select_shape(shape)
        self.wand_tolerance.setVisible(shape == "wand")
        self.select_hint.setText("Click an object or area to select it (Shift+click adds)" if shape == "wand"
                                 else "Drag on the image to select an area")

    def _on_wand_clicked(self, point, additive: bool) -> None:
        doc = self.document
        if doc is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            mask = region_tools.magic_wand(doc.rendered(), (point.x(), point.y()), self.wand_tolerance.value())
            current = self.canvas.selection_mask()
            if additive and current is not None:
                mask = ImageChops.lighter(current, mask)
            self.canvas.set_mask_selection(mask)
        except ImageProcessingError as exc:
            self.toasts.show("info", "Nothing selected", str(exc))
        finally:
            QApplication.restoreOverrideCursor()

    def _on_layers_changed(self, changes: dict) -> None:
        if self.document is None:
            return
        self.document.move_layers(changes)
        layer_id = self.canvas.selected_layer_id()
        self.layers_panel.show_properties(self.document.get_layer(layer_id), "image" if layer_id else "background")
        self._update_ui_state()

    def _on_layer_list_selected(self, kind: str, item_id: str) -> None:
        if kind == "text":
            self.canvas.select_text(item_id)
        elif kind == "image":
            self.canvas.select_layer(item_id)
        else:
            self.canvas.scene().clearSelection()

    def _on_layer_properties(self, changes: dict) -> None:
        doc = self.document
        layer_id = self.canvas.selected_layer_id()
        if doc is None or layer_id is None:
            return
        session = f"layer:{layer_id}"
        if self._text_session_id != session:
            doc.checkpoint()
            self._text_session_id = session
        self._text_session_timer.start()
        try:
            doc.update_layer(layer_id, **changes)
        except ValueError as exc:
            self.toasts.show("error", "Layer not updated", str(exc))
            return
        self.canvas.sync_layers(doc.state.layers)
        self.canvas.select_layer(layer_id)
        self._update_ui_state(refresh_layers=False)

    def _on_layer_action(self, action: str) -> None:
        doc = self.document
        layer_id = self.canvas.selected_layer_id()
        if doc is None or layer_id is None:
            self.toasts.show("info", "Select an image layer", "Click a layer on the canvas or in the list first.")
            return
        self._end_text_session()
        keep = layer_id
        if action == "flip":
            doc.flip_layer(layer_id)
        elif action == "duplicate":
            keep = doc.duplicate_layer(layer_id).id
        elif action in ("up", "down"):
            if not doc.move_layer_order(layer_id, 1 if action == "up" else -1):
                self.toasts.show("info", "Can't move further", "The layer is already at the top or bottom.")
                return
        elif action == "merge":
            doc.merge_layer(layer_id)
            keep = None
        elif action == "delete":
            doc.remove_layer(layer_id)
            keep = None
        self._after_change()
        if keep:
            self.canvas.select_layer(keep)

    def add_image_layer(self) -> None:
        doc = self.document
        if doc is None:
            return
        patterns = " ".join(f"*{ext}" for ext in supported_extensions())
        path, _ = QFileDialog.getOpenFileName(self, "Add Image as Layer", self._last_dir, f"Images ({patterns})")
        if not path:
            return
        try:
            image = load_image(path)
        except ImageLoadError as exc:
            self.toasts.show("error", "Image not added", str(exc))
            return
        layer = doc.add_image_layer(image, name=Path(path).stem[:30])
        self._after_change()
        self.canvas.select_layer(layer.id)
        self.panel_tabs.setCurrentIndex(3)

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
        if element is not None and self.panel_tabs.currentIndex() != 3:
            self.panel_tabs.setCurrentIndex(2)
        if self.canvas.selected_layer_id() is not None:
            self.panel_tabs.setCurrentIndex(3)
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
            output = export_design(rendered, doc.state.texts, options, doc.state.layers)
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
            title = "Check brand details" if request.brand and "prompt" not in str(exc).lower() else "Prompt needed"
            self.toasts.show("warning", title, str(exc))
            if title == "Prompt needed":
                self.generation_panel.prompt.setFocus()
            return
        save_brand(self.generation_panel.brand_details())  # remember the details for next time
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
        self._generating_service = service
        self._generation_token += 1
        self.generation_panel.set_busy(True, service.name)
        if hasattr(service, "progress"):
            service.progress = self._background.progress.emit  # thread-safe: queued to the GUI thread
        _run_in_background(self._background, f"generate:{self._generation_token}",
                           lambda: service.generate(request))

    def stop_generation(self) -> None:
        """Stop the running generation; the app is immediately ready for a new one."""
        service = self._generating_service
        if self._pending_request is None or service is None:
            return
        service.cancel()
        self._generation_token += 1      # any late result from the stopped run is ignored
        self._pending_request = None
        self._generating_service = None
        self.generation_panel.set_busy(False)
        if service.short_name == "Manus":
            detail = "The Manus task is being stopped so it does not use more credits."
        else:
            detail = (f"{service.short_name} cannot cancel a request that is already sent, so any late "
                      "result will be discarded.")
        self.generation_panel.set_status("Generation stopped", detail, "warning")
        self.toasts.show("info", "Generation stopped", detail, 5000)

    def _is_current_generation(self, task: str) -> bool:
        try:
            return int(task.split(":", 1)[1]) == self._generation_token and self._pending_request is not None
        except (IndexError, ValueError):
            return False

    def _on_generation_progress(self, text: str) -> None:
        if self._pending_request is not None and self._generating_service is not None:
            self.generation_panel.set_status(f"Generating with {self._generating_service.name}…", text, "info")

    def _finish_generation(self, image: Image.Image) -> None:
        request = self._pending_request
        service = self._generating_service or self.generation_service
        self._pending_request = None
        self._generating_service = None
        self.generation_panel.set_busy(False)
        model = f"{service.short_name} · {service.model}"
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
            + (" · a copy is saved in Pictures\\PiXdEm AI STUDIO\\Generated" if saved else ""), "success")
        if not self._confirm_discard():
            self.toasts.show("info", "Generated design kept on disk",
                             f"Your current design was left open. The result is in {saved}", 8000)
            return
        document = DesignDocument(image, name=f"AI · {request.prompt.strip()[:32]}", source_path=saved)
        brand_layers = 0
        if request.brand is not None and request.brand.text_mode == "layers" and request.brand.has_text:
            brand_layers = self._add_brand_layers(document, request.brand)
        document.modified = True
        self._show_studio()
        self._set_document(document)
        self.panel_tabs.setCurrentIndex(0)
        self.generation_panel.show_edit_options(True)
        detail = (f"{brand_layers} editable text layer(s) were added from your brand details. "
                  if brand_layers else "")
        self.toasts.show("success", "AI design ready",
                         f"Generated with {service.name}. {detail}Use the Edit buttons to change text "
                         "or any area of the image.", 7000)

    def _fail_generation(self, exc: Exception) -> None:
        self._pending_request = None
        self._generating_service = None
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
        keys = {p: mask_secret(get_setting(key_name)) for p, (key_name, _m) in PROVIDER_SETTINGS.items()}
        models = {"gemini": get_setting("GEMINI_IMAGE_MODEL") or DEFAULT_MODEL,
                  "manus": get_setting("MANUS_AGENT_PROFILE") or MANUS_DEFAULT_PROFILE}
        self.settings_page.set_provider_state(selected_provider(), keys, models, note)
        self.sidebar.set_ai_status(
            f"{service.short_name} AI ready" if service.is_configured else "AI provider not configured",
            "success" if service.is_configured else "warning")

    def _save_provider(self, provider: str, api_key: str, model: str) -> None:
        values: dict[str, str | None] = {"AI_PROVIDER": provider}
        if provider in PROVIDER_SETTINGS:
            key_name, model_name = PROVIDER_SETTINGS[provider]
            if not api_key and not get_setting(key_name):
                self.toasts.show("warning", "API key needed", "Paste the provider's API key first.")
                return
            values[model_name] = model
            if api_key:
                values[key_name] = api_key
        try:
            update_env(values)
        except OSError as exc:
            self.toasts.show("error", "Settings not saved", f"Could not save your settings: {exc}")
            return
        self._refresh_provider_ui("Saved. Use Test Connection to check the provider is reachable.")
        self.toasts.show("success", "AI provider saved", PROVIDERS.get(provider, provider))

    def _test_provider(self, provider: str, api_key: str, model: str) -> None:
        if provider == "pollinations":
            work, task, contacting = PollinationsImageService().check_connection, "test_pollinations", "Pollinations.ai"
        else:
            key_name = PROVIDER_SETTINGS[provider][0]
            key = api_key or get_setting(key_name)
            if not key:
                self.toasts.show("warning", "API key needed", "Paste the provider's API key first.")
                return
            if provider == "manus":
                service = ManusImageService(key, model)
                work, task, contacting = service.check_connection, "test_manus", "Manus"
            else:
                service = GeminiImageService(key, model)
                work, task, contacting = (lambda: (model, service.list_image_models())), "test", "Google"
        self.settings_page.test_button.setEnabled(False)
        self.settings_page.set_provider_note(f"Contacting {contacting}…")
        _run_in_background(self._background, task, work)

    def _remove_provider(self, provider: str) -> None:
        if provider not in PROVIDER_SETTINGS:
            return
        name = PROVIDERS[provider].split(" (")[0]
        if not confirm(self, "Remove API key?", f"The saved {name} API key will be deleted from this computer.",
                       "Remove Key", "This provider will be unavailable until you add a key again."):
            return
        update_env({PROVIDER_SETTINGS[provider][0]: None})
        self._refresh_provider_ui()
        self.toasts.show("info", "API key removed", f"{name} key deleted.")

    def _on_background_succeeded(self, task: str, result) -> None:
        if task.startswith("generate:"):
            if self._is_current_generation(task):
                self._finish_generation(result)
        elif task == "test_manus":
            self.settings_page.test_button.setEnabled(True)
            note = f"Manus key accepted — {result}. No task was created by this check."
            self.settings_page.set_provider_note(note)
            self.toasts.show("success", "Connection OK", note, 7000)
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
        if task.startswith("generate:"):
            if self._is_current_generation(task):
                self._fail_generation(exc)
            elif isinstance(exc, GenerationCancelledError) and "could not be stopped" in str(exc):
                self.toasts.show("warning", "Manus task still running", str(exc), 9000)
        elif task in ("test", "test_pollinations", "test_manus"):
            self.settings_page.test_button.setEnabled(True)
            self.settings_page.set_provider_note(f"Connection failed: {exc}")
            self.toasts.show("error", "Connection failed", str(exc), 9000)

    # ================================================================== status

    def _on_zoom_changed(self, zoom: float) -> None:
        text = f"{zoom * 100:.0f}%"
        self.zoom_button.setText(text)
        self.zoom_status.setText(f"Zoom {text}")

    def _update_ui_state(self, refresh_layers: bool = True) -> None:
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
        selected_layer = self.canvas.selected_layer_id() if has_doc else None
        self.act_delete_text.setEnabled((selected_text is not None or selected_layer is not None) and not cropping)
        if refresh_layers:
            selection = ("text", selected_text) if selected_text else (
                ("image", selected_layer) if selected_layer else None)
            self.layers_panel.refresh(doc, selection)
        self.act_apply_crop.setEnabled(cropping)
        self.act_cancel_crop.setEnabled(cropping or self.canvas.in_select_mode)
        self.act_select.setEnabled(has_doc and not cropping)
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
        elif selected_layer:
            layer = doc.get_layer(selected_layer)
            self.selection_label.setText(
                f"Selected: {layer.name} · {layer.size[0] * layer.scale:.0f} × {layer.size[1] * layer.scale:.0f} px"
                f" · {layer.opacity * 100:.0f}% opacity · x {layer.x:.0f}, y {layer.y:.0f}")
        elif self.canvas.is_image_selected():
            self.selection_label.setText(
                f"Selected: image · {doc.width} × {doc.height} px · {len(doc.state.texts)} text layer(s)")
        else:
            self.selection_label.setText(f"{len(doc.state.texts)} text layer(s) · click an element to select it")

    # ================================================================== window

    def closeEvent(self, event: QCloseEvent) -> None:  # noqa: N802
        if self.document is not None and self.document.modified:
            if not confirm(self, f"Quit {APP_NAME}?", "Your design has unexported changes.",
                           "Quit Without Exporting", "Use Export (Ctrl+E) to save it as PNG or JPEG."):
                event.ignore()
                return
        QThreadPool.globalInstance().waitForDone(2000)
        event.accept()
