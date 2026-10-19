"""Right-panel tab for AI generation inputs."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QVBoxLayout,
    QWidget,
)

from services.generation_service import (
    ART_STYLES,
    ASPECT_RATIOS,
    DESIGN_TYPES,
    MAX_PROMPT_LENGTH,
    GenerationRequest,
)
from services.image_processor import ImageLoadError, load_image, make_thumbnail, supported_extensions
from services.qt_image import pil_to_qimage
from ui.icons import set_pixmap
from ui.pages import dropped_image_path
from ui.widgets import divider, label, make_button, section_title

PROMPT_PLACEHOLDER = (
    "Describe the design you want…\n\n"
    "e.g. Create a premium advertisement for a Sri Lankan smartphone shop, using a cinematic "
    "black and blue background, professional product lighting, and an elegant commercial design."
)

EXAMPLE_PROMPTS = (
    ("Smartphone ad",
     "Create a premium advertisement for a Sri Lankan smartphone shop, using a cinematic black and blue "
     "background, professional product lighting, and an elegant commercial design."),
    ("Café promo",
     "A cosy promotional poster for an artisan coffee shop, warm golden lighting, latte art close-up, "
     "generous empty space at the top for a headline."),
    ("Gym opening",
     "Energetic social media post announcing a new gym opening, bold neon accents, dynamic athlete "
     "silhouette, modern sporty layout."),
    ("Festival sale",
     "Colourful Avurudu festival sale banner for a clothing store, traditional patterns, joyful "
     "atmosphere, clean modern layout with room for prices."),
)


class ReferenceDropZone(QFrame):
    """Click-or-drop area that shows the reference thumbnail once loaded."""

    clicked = Signal()
    file_dropped = Signal(str)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("DropZone")
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setMinimumHeight(108)
        self.setToolTip("Click to choose a reference image, or drop one here")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        self._thumb = QLabel()
        self._thumb.setFixedSize(84, 84)
        self._thumb.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._thumb.setObjectName("ThumbBox")
        layout.addWidget(self._thumb)
        texts = QVBoxLayout()
        texts.setSpacing(3)
        self._title = label("", "H3", wrap=True)
        self._detail = label("", "Caption", wrap=True)
        texts.addStretch(1)
        texts.addWidget(self._title)
        texts.addWidget(self._detail)
        texts.addStretch(1)
        layout.addLayout(texts, 1)
        self.show_empty()

    def show_empty(self) -> None:
        set_pixmap(self._thumb, "image", "text_muted", 30)
        self._title.setText("Add a reference image")
        exts = ", ".join(e.lstrip(".").upper() for e in supported_extensions())
        self._detail.setText(f"Click or drop a file · {exts}")

    def show_reference(self, thumb: QPixmap, name: str, detail: str) -> None:
        self._thumb.setProperty("pf_pixmap", None)
        self._thumb.setPixmap(thumb.scaled(84, 84, Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))
        self._title.setText(name)
        self._detail.setText(detail)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802
        if event.button() == Qt.MouseButton.LeftButton and self.rect().contains(event.position().toPoint()):
            self.clicked.emit()
        super().mouseReleaseEvent(event)

    def _set_active(self, active: bool) -> None:
        self.setProperty("active", "true" if active else "false")
        self.style().unpolish(self)
        self.style().polish(self)

    def dragEnterEvent(self, event) -> None:  # noqa: N802
        if dropped_image_path(event.mimeData()):
            event.acceptProposedAction()
            self._set_active(True)

    def dragLeaveEvent(self, event) -> None:  # noqa: N802
        self._set_active(False)

    def dropEvent(self, event) -> None:  # noqa: N802
        self._set_active(False)
        path = dropped_image_path(event.mimeData())
        if path:
            event.acceptProposedAction()
            self.file_dropped.emit(path)


class GenerationPanel(QWidget):
    """Collects a GenerationRequest; the main window decides what to do with it."""

    generate_requested = Signal(object)
    notify = Signal(str, str, str)  # kind, title, message

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.reference_path: Path | None = None
        self._last_dir = str(Path.home())

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 16, 18, 18)
        layout.setSpacing(10)

        head = QHBoxLayout()
        head.setSpacing(8)
        sparkle = QLabel()
        set_pixmap(sparkle, "sparkles", "accent_hover", 20)
        head.addWidget(sparkle)
        head.addWidget(label("AI Generate", "H2"))
        head.addStretch(1)
        self._provider_badge = label("", "Badge")
        head.addWidget(self._provider_badge)
        layout.addLayout(head)
        self._caption = label("", "Caption", wrap=True)
        layout.addWidget(self._caption)
        layout.addSpacing(4)

        prompt_head = QHBoxLayout()
        prompt_head.addWidget(section_title("Prompt"))
        prompt_head.addStretch(1)
        self._counter = label(f"0 / {MAX_PROMPT_LENGTH}", "Caption")
        prompt_head.addWidget(self._counter)
        layout.addLayout(prompt_head)
        self.prompt = QPlainTextEdit()
        self.prompt.setPlaceholderText(PROMPT_PLACEHOLDER)
        self.prompt.setMinimumHeight(128)
        self.prompt.textChanged.connect(self._update_counter)
        layout.addWidget(self.prompt)

        layout.addWidget(section_title("Try an example"))
        examples = QGridLayout()
        examples.setSpacing(6)
        for index, (title, text) in enumerate(EXAMPLE_PROMPTS):
            chip = make_button(title, "chip", tooltip=text)
            chip.clicked.connect(lambda _c=False, t=text: self.prompt.setPlainText(t))
            examples.addWidget(chip, index // 2, index % 2)
        layout.addLayout(examples)

        layout.addWidget(divider())
        layout.addWidget(section_title("Reference image"))
        self.drop_zone = ReferenceDropZone()
        self.drop_zone.clicked.connect(self.choose_reference)
        self.drop_zone.file_dropped.connect(self.load_reference)
        layout.addWidget(self.drop_zone)
        ref_buttons = QHBoxLayout()
        ref_buttons.setSpacing(8)
        self.upload_button = make_button("Upload Reference", None, "upload", "Choose a reference image")
        self.upload_button.clicked.connect(self.choose_reference)
        self.remove_button = make_button("Remove", "ghost", "x", "Remove the reference image")
        self.remove_button.clicked.connect(self.remove_reference)
        ref_buttons.addWidget(self.upload_button, 1)
        ref_buttons.addWidget(self.remove_button)
        layout.addLayout(ref_buttons)

        layout.addWidget(divider())
        layout.addWidget(section_title("Design settings"))
        form = QGridLayout()
        form.setHorizontalSpacing(10)
        form.setVerticalSpacing(8)
        self.design_type = QComboBox()
        self.design_type.addItems(DESIGN_TYPES)
        self.art_style = QComboBox()
        self.art_style.addItems(ART_STYLES)
        self.aspect_ratio = QComboBox()
        self.aspect_ratio.addItems(list(ASPECT_RATIOS))
        for row, (name, combo) in enumerate((("Design type", self.design_type),
                                              ("Art style", self.art_style),
                                              ("Aspect ratio", self.aspect_ratio))):
            form.addWidget(label(name, "Muted"), row, 0)
            form.addWidget(combo, row, 1)
            combo.setCursor(Qt.CursorShape.PointingHandCursor)
        form.setColumnStretch(1, 1)
        layout.addLayout(form)
        layout.addSpacing(6)

        self.generate_button = make_button("Generate Design", "primary", "sparkles",
                                           "Generate a new design with AI (Ctrl+G)")
        self.generate_button.setMinimumHeight(46)
        self.generate_button.setIconSize(QSize(18, 18))
        self.generate_button.clicked.connect(lambda: self.generate_requested.emit(self.build_request()))
        layout.addWidget(self.generate_button)

        status = QFrame()
        status.setObjectName("SubtleCard")
        status_box = QVBoxLayout(status)
        status_box.setContentsMargins(12, 10, 12, 10)
        status_box.setSpacing(4)
        status_row = QHBoxLayout()
        status_row.setSpacing(8)
        self._status_dot = QLabel()
        self._status_dot.setObjectName("StatusDot")
        self._status_dot.setFixedSize(8, 8)
        status_row.addWidget(self._status_dot)
        self._status_title = label("", "H3")
        status_row.addWidget(self._status_title, 1)
        status_box.addLayout(status_row)
        self._status_detail = label("", "Caption", wrap=True)
        status_box.addWidget(self._status_detail)
        layout.addWidget(status)
        layout.addStretch(1)

        self.set_provider(None, False)
        self._update_reference_buttons()

    # ------------------------------------------------------------------ provider state

    def set_provider(self, service, configured: bool) -> None:
        """Show which provider/model Generate will use."""
        self._configured = configured
        if configured:
            self._provider_badge.setObjectName("BadgeAccent")
            self._provider_badge.setText(service.short_name)
            self._caption.setText("Describe your design and set the options. The result opens on the "
                                  "canvas, ready to edit, and is saved in storage/generated.")
            if service.supports_reference:
                detail = f"Model: {service.model}. Each Generate sends one request using your API key."
            else:
                detail = ("Free, no API key. Sends only your prompt and size to the provider. One image "
                          "every 45 s; reference images are not sent.")
            self.set_status(f"Ready · {service.name}", detail, "success")
        else:
            self._provider_badge.setObjectName("Badge")
            self._provider_badge.setText("Not configured")
            self._caption.setText("Describe your design and set the options. Add a Google AI Studio API "
                                  "key in Settings → AI provider to enable generation.")
            self.set_status("AI provider: not configured",
                            "No requests are sent. Add your API key in Settings → AI provider.", "warning")
        self._provider_badge.style().unpolish(self._provider_badge)
        self._provider_badge.style().polish(self._provider_badge)

    def set_busy(self, busy: bool, provider_name: str = "") -> None:
        self.generate_button.setEnabled(not busy)
        self.generate_button.setText("Generating…" if busy else "Generate Design")
        if busy:
            self.set_status(f"Generating with {provider_name or 'AI'}…",
                            "This usually takes 10–60 seconds. You can keep editing meanwhile.", "info")

    # ------------------------------------------------------------------ request

    def build_request(self) -> GenerationRequest:
        return GenerationRequest(
            prompt=self.prompt.toPlainText(),
            design_type=self.design_type.currentText(),
            art_style=self.art_style.currentText(),
            aspect_ratio=self.aspect_ratio.currentText(),
            reference_image=self.reference_path,
        )

    def set_status(self, title: str, detail: str, kind: str = "warning") -> None:
        self._status_dot.setProperty("kind", kind)
        self._status_dot.style().unpolish(self._status_dot)
        self._status_dot.style().polish(self._status_dot)
        self._status_title.setText(title)
        self._status_detail.setText(detail)

    def _update_counter(self) -> None:
        length = len(self.prompt.toPlainText())
        self._counter.setText(f"{length} / {MAX_PROMPT_LENGTH}")
        self._counter.setProperty("over", "true" if length > MAX_PROMPT_LENGTH else "false")
        self._counter.style().unpolish(self._counter)
        self._counter.style().polish(self._counter)

    # ------------------------------------------------------------------ reference image

    def choose_reference(self) -> None:
        patterns = " ".join(f"*{e}" for e in supported_extensions())
        path, _ = QFileDialog.getOpenFileName(self, "Choose Reference Image", self._last_dir,
                                              f"Images ({patterns})")
        if path:
            self.load_reference(path)

    def load_reference(self, path: str) -> None:
        try:
            image = load_image(path)
        except ImageLoadError as exc:
            self.notify.emit("error", "Reference image not loaded", str(exc))
            return
        file_path = Path(path)
        self._last_dir = str(file_path.parent)
        replaced = self.reference_path is not None
        self.reference_path = file_path
        thumb = QPixmap.fromImage(pil_to_qimage(make_thumbnail(image, 256)))
        self.drop_zone.show_reference(thumb, file_path.name, f"{image.width} × {image.height} px · {image.mode}")
        self._update_reference_buttons()
        self.notify.emit("success", "Reference image replaced" if replaced else "Reference image added",
                         file_path.name)

    def remove_reference(self) -> None:
        if self.reference_path is None:
            return
        self.reference_path = None
        self.drop_zone.show_empty()
        self._update_reference_buttons()
        self.notify.emit("info", "Reference image removed", "")

    def _update_reference_buttons(self) -> None:
        has_reference = self.reference_path is not None
        self.remove_button.setEnabled(has_reference)
        self.upload_button.setText("Replace Reference" if has_reference else "Upload Reference")
