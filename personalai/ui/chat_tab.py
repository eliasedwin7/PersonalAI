"""Chat tab: pick a task + session, talk, watch the reply stream in.

Session files are shared with the CLI (same ConversationStore, same
JSON files) - a conversation started with `myai story` shows up here too.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from personalai.core.conversation import Conversation
from personalai.core.errors import PersonalAIError
from personalai.services import context_service
from personalai.services.chat_service import TEXT_TASKS, ChatService
from personalai.ui.workers import TaskRunner


class ChatTab(QWidget):
    def __init__(self, chat_service: ChatService, task_runner: TaskRunner) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.task_runner = task_runner
        self.conversation: Conversation | None = None
        self.context_paths: list[str] = []
        self._sending = False

        outer = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.addWidget(QLabel("Sessions"))
        self.session_list = QListWidget()
        self.session_list.itemClicked.connect(self._on_session_selected)
        left_layout.addWidget(self.session_list)
        new_btn = QPushButton("New session…")
        new_btn.clicked.connect(self._new_session)
        left_layout.addWidget(new_btn)
        splitter.addWidget(left)

        right = QWidget()
        right_layout = QVBoxLayout(right)
        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Task:"))
        self.task_combo = QComboBox()
        self.task_combo.addItems(list(TEXT_TASKS))
        self.task_combo.currentTextChanged.connect(self._on_task_changed)
        top_row.addWidget(self.task_combo)
        top_row.addStretch(1)
        self.context_label = QLabel("no context files")
        self.context_label.setStyleSheet("color: #8c8c8c;")
        top_row.addWidget(self.context_label)
        attach_btn = QPushButton("Attach file…")
        attach_btn.clicked.connect(self._attach_context)
        top_row.addWidget(attach_btn)
        attach_folder_btn = QPushButton("Attach folder…")
        attach_folder_btn.setToolTip(
            "Attach every text file in a folder (e.g. a chapters/ "
            "directory) as reference material, combined and truncated "
            "the same way a single file would be."
        )
        attach_folder_btn.clicked.connect(self._attach_context_folder)
        top_row.addWidget(attach_folder_btn)
        right_layout.addLayout(top_row)

        self.transcript = QPlainTextEdit()
        self.transcript.setReadOnly(True)
        right_layout.addWidget(self.transcript, stretch=1)

        input_row = QHBoxLayout()
        self.input_edit = QLineEdit()
        self.input_edit.setPlaceholderText("Type a message and press Enter…")
        self.input_edit.returnPressed.connect(self._send)
        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.input_edit, stretch=1)
        input_row.addWidget(self.send_btn)
        right_layout.addLayout(input_row)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)

        self._reload_sessions()
        self._load_session(self.task_combo.currentText())

    # ---- sessions ----

    def _reload_sessions(self) -> None:
        """Only list sessions belonging to the CURRENTLY selected task -
        a caption-tab "vision" session shouldn't show up under Story, and
        clicking it there would silently mix system prompts."""
        self.session_list.clear()
        current_task = self.task_combo.currentText()
        for name in self.chat_service.store.list_all():
            conv = self.chat_service.store.load_or_create(name, current_task)
            if conv.task == current_task:
                self.session_list.addItem(QListWidgetItem(name))

    def _on_session_selected(self, item: QListWidgetItem) -> None:
        self._load_session(item.text())

    def _new_session(self) -> None:
        name, ok = QInputDialog.getText(self, "New session", "Session name:")
        if not ok or not name.strip():
            return
        task = self.task_combo.currentText()
        self.conversation = self.chat_service.store.load_or_create(name.strip(), task)
        self.chat_service.store.save(self.conversation)
        self._reload_sessions()
        self._render_transcript()

    def _on_task_changed(self, task: str) -> None:
        self._reload_sessions()
        self._load_session(task)

    def _load_session(self, name: str) -> None:
        task = self.task_combo.currentText()
        self.conversation = self.chat_service.store.load_or_create(name, task)
        self._render_transcript()

    def _render_transcript(self) -> None:
        self.transcript.clear()
        if self.conversation is None:
            return
        for msg in self.conversation.messages:
            prefix = {"user": "you", "assistant": "ai"}.get(msg.role, msg.role)
            self.transcript.appendPlainText(f"{prefix}> {msg.content}\n")

    # ---- context ----

    def _attach_context(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Choose context file(s)")
        if paths:
            self._add_context_paths(paths)

    def _attach_context_folder(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a context folder")
        if folder:
            self._add_context_paths([folder])

    def _add_context_paths(self, paths: list[str]) -> None:
        """Attaching adds to whatever's already staged (files + folders can
        be combined) - cleared automatically once actually sent."""
        self.context_paths.extend(paths)
        names = ", ".join(Path(p).name for p in self.context_paths)
        self.context_label.setText(f"context: {names}")

    # ---- sending ----

    def _send(self) -> None:
        if self._sending or self.conversation is None:
            return
        text = self.input_edit.text().strip()
        if not text:
            return

        context_blocks = []
        for p in self.context_paths:
            try:
                context_blocks.append(
                    context_service.load_context_path(
                        Path(p), self.chat_service.config.context_char_limit
                    )
                )
            except PersonalAIError as exc:
                QMessageBox.warning(self, "Context file", str(exc))
                return
        message = context_service.build_user_message(text, context_blocks)
        self.context_paths = []
        self.context_label.setText("no context files")

        self.input_edit.clear()
        self.transcript.appendPlainText(f"you> {text}\n")
        self.transcript.appendPlainText("ai> ")
        self._sending = True
        self.send_btn.setEnabled(False)

        self.task_runner.submit(
            self.chat_service.send, self.conversation, message,
            on_progress=self._on_token,
            on_result=self._on_done,
            on_error=self._on_error,
        )

    def _on_token(self, token: str) -> None:
        cursor = self.transcript.textCursor()
        cursor.movePosition(cursor.MoveOperation.End)
        cursor.insertText(token)
        self.transcript.setTextCursor(cursor)

    def _on_done(self, _reply: str) -> None:
        self.transcript.appendPlainText("\n")
        self._sending = False
        self.send_btn.setEnabled(True)
        self._reload_sessions()

    def _on_error(self, exc: BaseException) -> None:
        self.transcript.appendPlainText(f"\n[error] {exc}\n")
        self._sending = False
        self.send_btn.setEnabled(True)
