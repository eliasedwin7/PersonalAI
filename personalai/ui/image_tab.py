"""Image tab: generate an image from a prompt, or a prompt + an
uploaded reference image, through Stable Diffusion Forge - the GUI
counterpart of `myai image`. See services/image_service.py's docstring
for why Forge (not ComfyUI) was picked for this feature.

Every generated image is auto-saved into image_save_dir (mirroring the
CLI's own behavior) so there's always a real folder of past results to
open, not just whatever happens to still be in the widget.
"""

from __future__ import annotations

import datetime
from pathlib import Path

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QDesktopServices, QPixmap
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from personalai.core import config as config_mod
from personalai.core.errors import PersonalAIError
from personalai.services.chat_service import ChatService
from personalai.services.image_service import ForgeClient, build_forge_client
from personalai.ui.workers import TaskRunner

PREVIEW_HEIGHT = 320


def _image_save_dir(config: config_mod.Config) -> Path:
    """Mirrors cli.py's _image_save_dir - same default so CLI-generated
    and GUI-generated images land in one place."""
    if config.image_save_dir:
        return Path(config.image_save_dir).expanduser()
    return config_mod.APP_DIR / "images"


class ImageTab(QWidget):
    def __init__(self, chat_service: ChatService, task_runner: TaskRunner) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.task_runner = task_runner
        self.client: ForgeClient = build_forge_client(chat_service.config)
        self.reference_path: Path | None = None
        self.last_saved_path: Path | None = None
        self._working = False

        layout = QVBoxLayout(self)

        status_row = QHBoxLayout()
        self.status_label = QLabel("Forge: checking…")
        status_row.addWidget(self.status_label)
        status_row.addStretch(1)
        refresh_btn = QPushButton("Refresh checkpoints")
        refresh_btn.clicked.connect(self._refresh_checkpoints)
        status_row.addWidget(refresh_btn)
        layout.addLayout(status_row)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setPlaceholderText("Describe the image you want…")
        self.prompt_edit.setMaximumHeight(80)
        layout.addWidget(QLabel("Prompt:"))
        layout.addWidget(self.prompt_edit)

        self.negative_edit = QLineEdit()
        self.negative_edit.setPlaceholderText("Negative prompt (optional)")
        layout.addWidget(self.negative_edit)

        ref_row = QHBoxLayout()
        ref_btn = QPushButton("Attach reference image…")
        ref_btn.clicked.connect(self._choose_reference)
        clear_ref_btn = QPushButton("Clear reference")
        clear_ref_btn.clicked.connect(self._clear_reference)
        self.reference_label = QLabel("No reference image (plain text-to-image)")
        self.reference_label.setStyleSheet("color: #8c8c8c;")
        ref_row.addWidget(ref_btn)
        ref_row.addWidget(clear_ref_btn)
        ref_row.addWidget(self.reference_label, stretch=1)
        layout.addLayout(ref_row)

        params_row = QHBoxLayout()
        self.checkpoint_combo = QComboBox()
        self.checkpoint_combo.setEditable(True)
        params_row.addWidget(QLabel("Checkpoint:"))
        params_row.addWidget(self.checkpoint_combo, stretch=1)

        self.steps_spin = QSpinBox()
        self.steps_spin.setRange(1, 150)
        self.steps_spin.setValue(20)
        params_row.addWidget(QLabel("Steps:"))
        params_row.addWidget(self.steps_spin)

        self.cfg_spin = QDoubleSpinBox()
        self.cfg_spin.setRange(1.0, 30.0)
        self.cfg_spin.setValue(7.0)
        params_row.addWidget(QLabel("CFG:"))
        params_row.addWidget(self.cfg_spin)

        self.width_spin = QSpinBox()
        self.width_spin.setRange(64, 2048)
        self.width_spin.setSingleStep(64)
        self.width_spin.setValue(512)
        params_row.addWidget(QLabel("Width:"))
        params_row.addWidget(self.width_spin)

        self.height_spin = QSpinBox()
        self.height_spin.setRange(64, 2048)
        self.height_spin.setSingleStep(64)
        self.height_spin.setValue(512)
        params_row.addWidget(QLabel("Height:"))
        params_row.addWidget(self.height_spin)

        self.denoise_spin = QDoubleSpinBox()
        self.denoise_spin.setRange(0.0, 1.0)
        self.denoise_spin.setSingleStep(0.05)
        self.denoise_spin.setValue(0.75)
        self.denoise_spin.setEnabled(False)
        self.denoise_spin.setToolTip("Only used with a reference image (img2img).")
        params_row.addWidget(QLabel("Denoise:"))
        params_row.addWidget(self.denoise_spin)
        layout.addLayout(params_row)

        self.generate_btn = QPushButton("Generate")
        self.generate_btn.clicked.connect(self._generate)
        layout.addWidget(self.generate_btn)

        self.preview = QLabel()
        self.preview.setFixedHeight(PREVIEW_HEIGHT)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setStyleSheet("background: #1e1e1e; border: 1px solid #3f3f46;")
        self.preview.setText("Generated image will appear here")
        layout.addWidget(self.preview)

        result_row = QHBoxLayout()
        self.save_as_btn = QPushButton("Save As…")
        self.save_as_btn.setEnabled(False)
        self.save_as_btn.clicked.connect(self._save_as)
        self.open_folder_btn = QPushButton("Open folder")
        self.open_folder_btn.clicked.connect(self._open_folder)
        result_row.addWidget(self.save_as_btn)
        result_row.addWidget(self.open_folder_btn)
        result_row.addStretch(1)
        layout.addLayout(result_row)

        self._check_health()
        self._refresh_checkpoints()

    # ---- reference image ----

    def _choose_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose a reference image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.bmp)",
        )
        if not path:
            return
        self.reference_path = Path(path)
        self.reference_label.setText(self.reference_path.name)
        self.denoise_spin.setEnabled(True)

    def _clear_reference(self) -> None:
        self.reference_path = None
        self.reference_label.setText("No reference image (plain text-to-image)")
        self.denoise_spin.setEnabled(False)

    # ---- health / checkpoints ----

    def _check_health(self) -> None:
        self.task_runner.submit(self.client.health, on_result=self._show_health)

    def _show_health(self, online: bool) -> None:
        if online:
            self.status_label.setText("Forge: ● online")
            self.status_label.setStyleSheet("color: #4ec94e;")
        else:
            self.status_label.setText("Forge: ● offline")
            self.status_label.setStyleSheet("color: #8c8c8c;")

    def _refresh_checkpoints(self) -> None:
        self.task_runner.submit(self.client.list_checkpoints, on_result=self._fill_checkpoints)

    def _fill_checkpoints(self, checkpoints: list[str]) -> None:
        current = self.checkpoint_combo.currentText()
        self.checkpoint_combo.clear()
        self.checkpoint_combo.addItems(checkpoints)
        if current:
            self.checkpoint_combo.setCurrentText(current)

    # ---- generation ----

    def _generate(self) -> None:
        if self._working:
            return
        prompt = self.prompt_edit.toPlainText().strip()
        if not prompt:
            QMessageBox.warning(self, "Image", "Enter a prompt first.")
            return

        # Read every widget value here, on the GUI thread - _run_generation
        # executes on a worker thread (via TaskRunner) where touching Qt
        # widgets isn't safe (see ui/workers.py's threading rule).
        checkpoint = self.checkpoint_combo.currentText().strip()
        negative = self.negative_edit.text().strip()
        steps, cfg = self.steps_spin.value(), self.cfg_spin.value()
        width, height = self.width_spin.value(), self.height_spin.value()
        denoise = self.denoise_spin.value()
        reference_path = self.reference_path

        self._working = True
        self.generate_btn.setEnabled(False)
        self.preview.setText("Generating…")

        self.task_runner.submit(
            self._run_generation, prompt, checkpoint, negative, steps, cfg,
            width, height, denoise, reference_path,
            on_result=self._on_done, on_error=self._on_error,
        )

    def _run_generation(
        self, prompt: str, checkpoint: str, negative: str, steps: int, cfg: float,
        width: int, height: int, denoise: float, reference_path: Path | None,
    ) -> bytes:
        """Runs on the worker thread - only self.client (plain HTTP, no
        Qt) and plain arguments, no widget access."""
        if checkpoint:
            self.client.set_checkpoint(checkpoint)
        if reference_path is not None:
            return self.client.img2img(
                prompt, reference_path.read_bytes(), negative_prompt=negative,
                denoising_strength=denoise, steps=steps, cfg=cfg,
                width=width, height=height,
            )
        return self.client.txt2img(
            prompt, negative_prompt=negative, steps=steps, cfg=cfg,
            width=width, height=height,
        )

    def _on_done(self, image_bytes: bytes) -> None:
        pixmap = QPixmap()
        pixmap.loadFromData(image_bytes)
        if not pixmap.isNull():
            self.preview.setPixmap(pixmap.scaledToHeight(
                PREVIEW_HEIGHT, Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.setText("Forge returned data that isn't a valid image.")

        save_dir = _image_save_dir(self.chat_service.config)
        save_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d_%H%M%S")
        out_path = save_dir / f"image_{stamp}.png"
        out_path.write_bytes(image_bytes)
        self.last_saved_path = out_path
        self.save_as_btn.setEnabled(True)

        self._working = False
        self.generate_btn.setEnabled(True)

    def _on_error(self, exc: BaseException) -> None:
        message = str(exc) if isinstance(exc, PersonalAIError) else f"Unexpected error: {exc}"
        self.preview.setText(message)
        self._working = False
        self.generate_btn.setEnabled(True)

    # ---- result actions ----

    def _save_as(self) -> None:
        if self.last_saved_path is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Save image as", self.last_saved_path.name, "PNG (*.png)",
        )
        if path:
            Path(path).write_bytes(self.last_saved_path.read_bytes())

    def _open_folder(self) -> None:
        save_dir = _image_save_dir(self.chat_service.config)
        save_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(save_dir)))
