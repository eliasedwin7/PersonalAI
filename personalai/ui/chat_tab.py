"""Chat tab: pick a task + session, type, watch the reply stream in.

Session files are shared with the CLI (same ConversationStore, same
JSON files) - a conversation started with `myai story` shows up here too.

Deliberately typing-only - see ui/voice_tab.py for the "talk to it out
loud" assistant experience. Keeping this tab plain text means it's
still the fastest way to paste in a code block or a paragraph of story
outline and just read the reply, without a mic button in the way.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from personalai.core.conversation import Conversation
from personalai.core.errors import PersonalAIError
from personalai.services import context_service
from personalai.services.chat_service import TEXT_TASKS, ChatService
from personalai.ui import transcript_view
from personalai.ui.workers import TaskRunner

INPUT_MAX_HEIGHT = 90


class ChatInputEdit(QPlainTextEdit):
    """A multi-line input box where Enter sends and Shift+Enter inserts
    a newline - so a longer story/code message can span several lines
    without losing single-Enter-to-send muscle memory."""

    submitted = Signal()

    def keyPressEvent(self, event) -> None:
        is_enter = event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
        if is_enter and not (event.modifiers() & Qt.KeyboardModifier.ShiftModifier):
            self.submitted.emit()
            return
        super().keyPressEvent(event)


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
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._on_session_context_menu)
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

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        right_layout.addWidget(self.transcript, stretch=1)

        input_row = QHBoxLayout()
        self.input_edit = ChatInputEdit()
        self.input_edit.setPlaceholderText(
            "Type a message (Enter to send, Shift+Enter for a new line)…"
        )
        self.input_edit.setMaximumHeight(INPUT_MAX_HEIGHT)
        self.input_edit.submitted.connect(self._send)
        input_row.addWidget(self.input_edit, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.clicked.connect(self._send)
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

    def _on_session_context_menu(self, pos) -> None:
        item = self.session_list.itemAt(pos)
        if item is None:
            return
        menu = QMenu(self)
        delete_action = menu.addAction("Delete session")
        action = menu.exec(self.session_list.mapToGlobal(pos))
        if action is delete_action:
            self._delete_session(item.text())

    def _delete_session(self, name: str) -> None:
        reply = QMessageBox.question(
            self, "Delete session", f"Delete session '{name}'? This can't be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self.chat_service.store.delete(name)
        task = self.task_combo.currentText()
        if self.conversation is not None and self.conversation.name == name:
            self._load_session(task)
        self._reload_sessions()

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
        transcript_view.render_transcript(self.transcript, self.conversation)

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
        text = self.input_edit.toPlainText().strip()
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
        transcript_view.append_role_label(self.transcript, "user")
        transcript_view.append_body(self.transcript, text + "\n\n")
        transcript_view.append_role_label(self.transcript, "assistant")
        self._sending = True
        self.send_btn.setEnabled(False)

        self.task_runner.submit(
            self.chat_service.send, self.conversation, message,
            on_progress=self._on_token,
            on_result=self._on_done,
            on_error=self._on_error,
        )

    def _on_token(self, token: str) -> None:
        transcript_view.append_body(self.transcript, token)

    def _on_done(self, _reply: str) -> None:
        transcript_view.append_body(self.transcript, "\n\n")
        self._sending = False
        self.send_btn.setEnabled(True)
        self._reload_sessions()

    def _on_error(self, exc: BaseException) -> None:
        transcript_view.append_body(self.transcript, f"\n[error] {exc}\n\n")
        self._sending = False
        self.send_btn.setEnabled(True)
