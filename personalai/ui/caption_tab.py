"""Caption Image tab: pick an image, optionally ask something specific
about it, get a description back - via ChatService.send_with_image().

Independent of any project's own tagging pipeline (see
services/vision_service.py's docstring) - this is a generic "ask a local
vision model about any image" tool.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from personalai.core.conversation import Conversation
from personalai.core.errors import PersonalAIError
from personalai.services import vision_service
from personalai.services.chat_service import VISION_TASK, ChatService
from personalai.ui import transcript_view
from personalai.ui.workers import TaskRunner

PREVIEW_HEIGHT = 220


class CaptionTab(QWidget):
    def __init__(self, chat_service: ChatService, task_runner: TaskRunner) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.task_runner = task_runner
        self.image_path: Path | None = None
        self.conversation: Conversation = chat_service.store.load_or_create(
            VISION_TASK, VISION_TASK
        )
        self.chat_service.store.save(self.conversation)
        self._working = False

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        shell = QSplitter(Qt.Orientation.Horizontal)
        self.session_splitter = shell
        outer.addWidget(shell)

        left = QWidget()
        self.session_pane = left
        left.setObjectName("sessionPane")
        left.setMinimumWidth(220)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 16, 14, 14)
        left_layout.setSpacing(10)
        session_header = QHBoxLayout()
        title = QLabel("Image sessions")
        title.setObjectName("paneTitle")
        session_header.addWidget(title)
        session_header.addStretch(1)
        new_btn = QPushButton("New")
        new_btn.setObjectName("primaryButton")
        new_btn.clicked.connect(self._new_session)
        session_header.addWidget(new_btn)
        left_layout.addLayout(session_header)
        self.session_list = QListWidget()
        self.session_list.itemClicked.connect(self._on_session_selected)
        left_layout.addWidget(self.session_list, stretch=1)
        rename_btn = QPushButton("Rename")
        rename_btn.clicked.connect(self._rename_current_session)
        left_layout.addWidget(rename_btn)
        delete_btn = QPushButton("Delete")
        delete_btn.clicked.connect(self._delete_current_session)
        left_layout.addWidget(delete_btn)
        shell.addWidget(left)

        right = QWidget()
        layout = QVBoxLayout(right)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)

        pick_row = QHBoxLayout()
        pick_btn = QPushButton("Choose image…")
        pick_btn.clicked.connect(self._choose_image)
        self.path_label = QLabel("No image chosen")
        self.path_label.setObjectName("mutedLabel")
        pick_row.addWidget(pick_btn)
        pick_row.addWidget(self.path_label, stretch=1)
        self.sessions_toggle_btn = QPushButton("Hide sessions")
        self.sessions_toggle_btn.setToolTip("Minimize or restore image description sessions.")
        self.sessions_toggle_btn.clicked.connect(self._toggle_session_pane)
        pick_row.addWidget(self.sessions_toggle_btn)
        layout.addLayout(pick_row)

        self.preview = QLabel()
        self.preview.setObjectName("imagePreview")
        self.preview.setFixedHeight(PREVIEW_HEIGHT)
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.preview)

        self.instruction_edit = QLineEdit()
        self.instruction_edit.setPlaceholderText(vision_service.DEFAULT_INSTRUCTION)
        layout.addWidget(self.instruction_edit)

        self.caption_btn = QPushButton("Caption it")
        self.caption_btn.setObjectName("primaryButton")
        self.caption_btn.clicked.connect(self._caption)
        layout.addWidget(self.caption_btn)

        self.output = QTextEdit()
        self.output.setObjectName("chatTranscript")
        self.output.setReadOnly(True)
        layout.addWidget(self.output, stretch=1)

        shell.addWidget(right)
        shell.setStretchFactor(0, 1)
        shell.setStretchFactor(1, 4)
        shell.setSizes([260, 1000])

        self._reload_sessions()
        self._render_transcript()

    # ---- sessions ----

    def _reload_sessions(self) -> None:
        self.session_list.clear()
        for name in self.chat_service.store.list_all():
            conv = self.chat_service.store.load_or_create(name, VISION_TASK)
            if conv.task == VISION_TASK:
                item = QListWidgetItem(conv.name)
                item.setData(Qt.ItemDataRole.UserRole, conv.name)
                self.session_list.addItem(item)

    def _toggle_session_pane(self) -> None:
        hide = not self.session_pane.isHidden()
        self.session_pane.setVisible(not hide)
        self.sessions_toggle_btn.setText("Show sessions" if hide else "Hide sessions")

    def _on_session_selected(self, item: QListWidgetItem) -> None:
        if self._working:
            return
        self._load_session(item.data(Qt.ItemDataRole.UserRole) or item.text())

    def _load_session(self, name: str) -> None:
        self.conversation = self.chat_service.store.load_or_create(name, VISION_TASK)
        self._render_transcript()

    def _new_session(self) -> None:
        if self._working:
            return
        default = "image_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        name, ok = QInputDialog.getText(self, "New image session", "Session name:", text=default)
        if not ok or not name.strip():
            return
        self.conversation = self.chat_service.store.load_or_create(name.strip(), VISION_TASK)
        self.chat_service.store.save(self.conversation)
        self._reload_sessions()
        self._render_transcript()

    def _rename_current_session(self) -> None:
        if self._working:
            return
        name, ok = QInputDialog.getText(
            self, "Rename image session", "New session name:", text=self.conversation.name
        )
        if not ok or not name.strip():
            return
        try:
            self.conversation = self.chat_service.store.rename(self.conversation.name, name.strip())
        except PersonalAIError as exc:
            QMessageBox.warning(self, "Rename image session", str(exc))
            return
        self._reload_sessions()
        self._render_transcript()

    def _delete_current_session(self) -> None:
        if self._working:
            return
        if self.conversation.name == VISION_TASK and not self.conversation.messages:
            return
        answer = QMessageBox.question(
            self,
            "Delete image session",
            f"Delete image session '{self.conversation.name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.chat_service.store.delete(self.conversation.name)
        self.conversation = self.chat_service.store.load_or_create(VISION_TASK, VISION_TASK)
        self.chat_service.store.save(self.conversation)
        self._reload_sessions()
        self._render_transcript()

    def _render_transcript(self) -> None:
        transcript_view.render_transcript(self.output, self.conversation)

    # ---- image asking ----

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
        instruction = self.instruction_edit.text().strip() or vision_service.DEFAULT_INSTRUCTION

        self._working = True
        self.caption_btn.setEnabled(False)
        self.output.clear()

        self.task_runner.submit(
            self.chat_service.send_with_image, self.conversation, instruction, self.image_path,
            on_progress=self._on_token,
            on_result=self._on_done,
            on_error=self._on_error,
        )

    def _on_token(self, token: str) -> None:
        transcript_view.append_body(self.output, token)

    def _on_done(self, _reply: str) -> None:
        self._render_transcript()
        self._reload_sessions()
        self._working = False
        self.caption_btn.setEnabled(True)

    def _on_error(self, exc: BaseException) -> None:
        transcript_view.append_message_block(self.output, "error", str(exc))
        self._working = False
        self.caption_btn.setEnabled(True)
