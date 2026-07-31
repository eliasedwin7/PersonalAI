"""Caption Image tab: pick an image, optionally ask something specific
about it, get a description back - via ChatService.send_with_image().

Independent of any project's own tagging pipeline (see
services/vision_service.py's docstring) - this is a generic "ask a local
vision model about any image" tool.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from personalai.services import vision_service
from personalai.services.chat_service import VISION_TASK, ChatService
from personalai.ui.workers import TaskRunner

PREVIEW_HEIGHT = 220


class CaptionTab(QWidget):
    def __init__(self, chat_service: ChatService, task_runner: TaskRunner) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.task_runner = task_runner
        self.image_path: Path | None = None
        self._working = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        pick_row = QHBoxLayout()
        pick_btn = QPushButton("Choose image…")
        pick_btn.clicked.connect(self._choose_image)
        self.path_label = QLabel("No image chosen")
        self.path_label.setObjectName("mutedLabel")
        pick_row.addWidget(pick_btn)
        pick_row.addWidget(self.path_label, stretch=1)
        layout.addLayout(pick_row)

        self.preview = QLabel()
        self.preview.setObjectName("imagePreview")
        self.preview.setFixedHeight(PREVIEW_HEIGHT)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview)

        session_row = QHBoxLayout()
        session_row.addWidget(QLabel("Session:"))
        self.session_edit = QLineEdit(VISION_TASK)
        session_row.addWidget(self.session_edit)
        layout.addLayout(session_row)

        self.instruction_edit = QLineEdit()
        self.instruction_edit.setPlaceholderText(vision_service.DEFAULT_INSTRUCTION)
        layout.addWidget(self.instruction_edit)

        self.caption_btn = QPushButton("Caption it")
        self.caption_btn.setObjectName("primaryButton")
        self.caption_btn.clicked.connect(self._caption)
        layout.addWidget(self.caption_btn)

        self.output = QPlainTextEdit()
        self.output.setReadOnly(True)
        layout.addWidget(self.output, stretch=1)

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an image", "",
            "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp)",
        )
        if not path:
            return
        self.image_path = Path(path)
        self.path_label.setText(self.image_path.name)
        pixmap = QPixmap(path)
        if not pixmap.isNull():
            self.preview.setPixmap(pixmap.scaledToHeight(
                PREVIEW_HEIGHT, Qt.TransformationMode.SmoothTransformation))
        else:
            self.preview.clear()

    def _caption(self) -> None:
        if self._working:
            return
        if self.image_path is None:
            self.output.setPlainText("Choose an image first.")
            return
        session_name = self.session_edit.text().strip() or VISION_TASK
        instruction = self.instruction_edit.text().strip() or vision_service.DEFAULT_INSTRUCTION
        conversation = self.chat_service.store.load_or_create(session_name, VISION_TASK)

        self._working = True
        self.caption_btn.setEnabled(False)
        self.output.clear()

        self.task_runner.submit(
            self.chat_service.send_with_image, conversation, instruction, self.image_path,
            on_progress=self._on_token,
            on_result=self._on_done,
            on_error=self._on_error,
        )

    def _on_token(self, token: str) -> None:
        cursor = self.output.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(token)
        self.output.setTextCursor(cursor)

    def _on_done(self, _reply: str) -> None:
        self._working = False
        self.caption_btn.setEnabled(True)

    def _on_error(self, exc: BaseException) -> None:
        self.output.appendPlainText(f"\n[error] {exc}")
        self._working = False
        self.caption_btn.setEnabled(True)
