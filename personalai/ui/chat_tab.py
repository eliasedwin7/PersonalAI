"""Chat tab: pick a task + session, type, watch the reply stream in.

Session files are shared with the CLI (same ConversationStore, same
JSON files) - a conversation started with `myai story` shows up here too.

Deliberately typing-only - see ui/voice_tab.py for the "talk to it out
loud" assistant experience. Keeping this tab plain text means it's
still the fastest way to paste in a code block or a paragraph of story
outline and just read the reply, without a mic button in the way.
"""

from __future__ import annotations

import time
from datetime import UTC, datetime
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSplitter,
    QStackedWidget,
    QStyle,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from personalai.core.config import ConfigStore
from personalai.core.conversation import Conversation
from personalai.core.errors import PersonalAIError
from personalai.services import context_service
from personalai.services.chat_service import TEXT_TASKS, ChatService
from personalai.services.memory_service import add_approved_entries
from personalai.ui import transcript_view
from personalai.ui.icons import standard_icon
from personalai.ui.workers import TaskHandle, TaskRunner

INPUT_MAX_HEIGHT = 90
IMAGE_PREVIEW_HEIGHT = 56
IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}


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


class MemoryApprovalDialog(QDialog):
    """A review screen where each proposed memory starts unapproved."""

    def __init__(self, suggestions: list[str], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Review memory")
        self.setMinimumWidth(460)
        layout = QVBoxLayout(self)
        note = QLabel("Select only the facts Nexus should remember in future chats.")
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        layout.addWidget(note)
        self.checkboxes: list[QCheckBox] = []
        for suggestion in suggestions:
            checkbox = QCheckBox(suggestion)
            layout.addWidget(checkbox)
            self.checkboxes.append(checkbox)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Save | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def approved(self) -> list[str]:
        return [box.text() for box in self.checkboxes if box.isChecked()]


class ChatTab(QWidget):
    def __init__(self, chat_service: ChatService, task_runner: TaskRunner,
                 config_store: ConfigStore | None = None) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.task_runner = task_runner
        self.config_store = config_store or ConfigStore()
        self.conversation: Conversation | None = None
        self.context_paths: list[str] = []
        self.attached_image_path: Path | None = None
        self._sending = False
        self._send_task: TaskHandle | None = None
        self._memory_suggesting = False
        self._generation_started_at: float | None = None
        self.setAcceptDrops(True)

        outer = QHBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        outer.addWidget(splitter)

        left = QWidget()
        left.setObjectName("sessionPane")
        left.setMinimumWidth(220)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(14, 16, 14, 14)
        left_layout.setSpacing(10)
        session_header = QHBoxLayout()
        sessions_title = QLabel("Chats")
        sessions_title.setObjectName("paneTitle")
        session_header.addWidget(sessions_title)
        session_header.addStretch(1)
        new_btn = QPushButton("New chat")
        new_btn.setObjectName("primaryButton")
        self._set_button_icon(new_btn, QStyle.StandardPixmap.SP_FileDialogNewFolder)
        new_btn.setToolTip("Create a new chat")
        new_btn.clicked.connect(self._new_session)
        session_header.addWidget(new_btn)
        left_layout.addLayout(session_header)
        self.session_search = QLineEdit()
        self.session_search.setPlaceholderText("Search chats and messages")
        self.session_search.setToolTip("Search saved chat titles and message text across all chat modes.")
        self.session_search.textChanged.connect(self._filter_sessions)
        left_layout.addWidget(self.session_search)
        self.session_list = QListWidget()
        self.session_list.itemClicked.connect(self._on_session_selected)
        self.session_list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.session_list.customContextMenuRequested.connect(self._on_session_context_menu)
        left_layout.addWidget(self.session_list)
        clear_session_btn = QPushButton("Clear current session")
        self._set_button_icon(clear_session_btn, QStyle.StandardPixmap.SP_DialogDiscardButton)
        clear_session_btn.setToolTip("Clear the selected chat history")
        clear_session_btn.clicked.connect(self._clear_current_session)
        left_layout.addWidget(clear_session_btn)
        splitter.addWidget(left)

        right = QWidget()
        right.setObjectName("chatWorkspace")
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(24, 18, 24, 18)
        right_layout.setSpacing(12)
        top_row = QHBoxLayout()
        self.conversation_title = QLabel("New conversation")
        self.conversation_title.setObjectName("paneTitle")
        top_row.addWidget(self.conversation_title)
        top_row.addStretch(1)
        self.task_combo = QComboBox()
        self.task_combo.addItems(list(TEXT_TASKS))
        self.task_combo.currentTextChanged.connect(self._on_task_changed)
        self.task_combo.setToolTip("Select the assistant mode for this conversation.")
        top_row.addWidget(self.task_combo)
        self.model_label = QLabel()
        self.model_label.setObjectName("mutedLabel")
        top_row.addWidget(self.model_label)
        self.deep_btn = QPushButton("Deep")
        self._set_button_icon(self.deep_btn, QStyle.StandardPixmap.SP_ArrowUp)
        self.deep_btn.setCheckable(True)
        self.deep_btn.setToolTip("Use the full-quality model and a more deliberate reasoning prompt for this reply.")
        top_row.addWidget(self.deep_btn)
        self.memory_btn = QPushButton("Review memory")
        self._set_button_icon(self.memory_btn, QStyle.StandardPixmap.SP_DialogApplyButton)
        self.memory_btn.setToolTip("Suggest lasting facts from this chat for your approval.")
        self.memory_btn.clicked.connect(self._review_memory)
        top_row.addWidget(self.memory_btn)
        self.attach_btn = QToolButton()
        self.attach_btn.setText("Attach")
        icon = standard_icon(QStyle.StandardPixmap.SP_DirOpenIcon)
        if icon is not None:
            self.attach_btn.setIcon(icon)
        self.attach_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        attach_menu = QMenu(self.attach_btn)
        attach_menu.addAction("Reference files", self._attach_context)
        attach_menu.addAction("Reference folder", self._attach_context_folder)
        attach_menu.addAction("Image", self._choose_image)
        self.attach_btn.setMenu(attach_menu)
        self.attach_btn.setToolTip("Attach reference files, a folder, or an image to the next message.")
        top_row.addWidget(self.attach_btn)
        right_layout.addLayout(top_row)

        self.attachment_widget = QWidget()
        attachment_row = QHBoxLayout(self.attachment_widget)
        attachment_row.setContentsMargins(0, 0, 0, 0)
        self.image_preview = QLabel()
        self.image_preview.setFixedHeight(56)
        self.image_preview.hide()
        attachment_row.addWidget(self.image_preview)
        self.context_label = QLabel("No attachments")
        self.context_label.setObjectName("mutedLabel")
        attachment_row.addWidget(self.context_label, stretch=1)
        self.clear_attachments_btn = QPushButton("Clear")
        self._set_button_icon(self.clear_attachments_btn, QStyle.StandardPixmap.SP_DialogCloseButton)
        self.clear_attachments_btn.clicked.connect(self._clear_attachments)
        self.clear_attachments_btn.setEnabled(False)
        attachment_row.addWidget(self.clear_attachments_btn)
        right_layout.addWidget(self.attachment_widget)

        self.content_stack = QStackedWidget()
        self.empty_state = QWidget()
        self.empty_state.setObjectName("emptyChatState")
        empty_layout = QVBoxLayout(self.empty_state)
        empty_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_title = QLabel("What are you working on?")
        empty_title.setObjectName("emptyStateTitle")
        empty_title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        empty_layout.addWidget(empty_title)
        suggestions = QHBoxLayout()
        for prompt in ("Plan a task", "Explain code", "Draft something"):
            suggestion = QPushButton(prompt)
            suggestion.clicked.connect(lambda _checked=False, text=prompt: self.input_edit.setPlainText(text))
            suggestions.addWidget(suggestion)
        empty_layout.addLayout(suggestions)

        self.transcript = QTextEdit()
        self.transcript.setObjectName("chatTranscript")
        self.transcript.setReadOnly(True)
        self.content_stack.addWidget(self.empty_state)
        self.content_stack.addWidget(self.transcript)
        right_layout.addWidget(self.content_stack, stretch=1)

        input_row = QHBoxLayout()
        self.input_edit = ChatInputEdit()
        self.input_edit.setPlaceholderText(
            "Message Nexus"
        )
        self.input_edit.setMinimumHeight(72)
        self.input_edit.setMaximumHeight(INPUT_MAX_HEIGHT)
        self.input_edit.submitted.connect(self._send)
        input_row.addWidget(self.input_edit, stretch=1)

        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primaryButton")
        self._set_button_icon(self.send_btn, QStyle.StandardPixmap.SP_ArrowForward)
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.send_btn)
        self.copy_latest_btn = QPushButton("Copy")
        self._set_button_icon(self.copy_latest_btn, QStyle.StandardPixmap.SP_DialogSaveButton)
        self.copy_latest_btn.setToolTip("Copy the latest assistant reply")
        self.copy_latest_btn.clicked.connect(self._copy_latest_reply)
        input_row.addWidget(self.copy_latest_btn)
        self.regenerate_btn = QPushButton("Regenerate")
        self._set_button_icon(self.regenerate_btn, QStyle.StandardPixmap.SP_BrowserReload)
        self.regenerate_btn.setToolTip("Generate a new response to the most recent text message.")
        self.regenerate_btn.clicked.connect(self._regenerate)
        input_row.addWidget(self.regenerate_btn)
        self.stop_btn = QPushButton("Stop")
        self._set_button_icon(self.stop_btn, QStyle.StandardPixmap.SP_DialogCancelButton)
        self.stop_btn.setToolTip("Stop the reply currently being generated.")
        self.stop_btn.clicked.connect(self._stop_generation)
        self.stop_btn.setVisible(False)
        input_row.addWidget(self.stop_btn)
        self.generation_status = QLabel()
        self.generation_status.setObjectName("mutedLabel")
        self.generation_status.hide()
        input_row.addWidget(self.generation_status)
        right_layout.addLayout(input_row)

        self._generation_timer = QTimer(self)
        self._generation_timer.setInterval(1_000)
        self._generation_timer.timeout.connect(self._update_generation_status)

        splitter.addWidget(right)
        splitter.setStretchFactor(0, 1)
        splitter.setStretchFactor(1, 3)
        splitter.setSizes([260, 900])

        self._reload_sessions()
        self._load_session(self.task_combo.currentText())
        self._refresh_attachment_status()

    @staticmethod
    def _set_button_icon(button, pixmap: QStyle.StandardPixmap) -> None:
        icon = standard_icon(pixmap)
        if icon is not None:
            button.setIcon(icon)

    # ---- sessions ----

    def _reload_sessions(self) -> None:
        """Only list sessions belonging to the CURRENTLY selected task -
        a caption-tab "vision" session shouldn't show up under Story, and
        clicking it there would silently mix system prompts."""
        current_task = self.task_combo.currentText()
        self._session_names: list[str] = []
        for name in self.chat_service.store.list_all():
            conv = self.chat_service.store.load_or_create(name, current_task)
            if conv.task == current_task:
                self._session_names.append(name)
        self._filter_sessions(self.session_search.text())

    def _filter_sessions(self, query: str) -> None:
        query = query.strip().lower()
        self.session_list.clear()
        if query:
            for result in self.chat_service.store.search(query):
                if result.task not in TEXT_TASKS:
                    continue
                item = QListWidgetItem(f"{result.name} · {result.task}\n{result.snippet}")
                item.setData(Qt.ItemDataRole.UserRole, (result.name, result.task))
                item.setToolTip(result.snippet)
                self.session_list.addItem(item)
            return
        for name in getattr(self, "_session_names", []):
            self.session_list.addItem(QListWidgetItem(name))

    def _on_session_selected(self, item: QListWidgetItem) -> None:
        result = item.data(Qt.ItemDataRole.UserRole)
        if result is None:
            self._load_session(item.text())
            return
        name, task = result
        if task != self.task_combo.currentText():
            self.task_combo.blockSignals(True)
            self.task_combo.setCurrentText(task)
            self.task_combo.blockSignals(False)
            self._reload_sessions()
        self._load_session(name)

    def _on_session_context_menu(self, pos) -> None:
        item = self.session_list.itemAt(pos)
        if item is None:
            return
        result = item.data(Qt.ItemDataRole.UserRole)
        name = result[0] if result is not None else item.text()
        menu = QMenu(self)
        rename_action = menu.addAction("Rename session")
        delete_action = menu.addAction("Delete session")
        action = menu.exec(self.session_list.mapToGlobal(pos))
        if action is rename_action:
            self._rename_session(name)
        elif action is delete_action:
            self._delete_session(name)

    def _rename_session(self, name: str) -> None:
        new_name, ok = QInputDialog.getText(self, "Rename session", "New session name:", text=name)
        if not ok or not new_name.strip():
            return
        try:
            conversation = self.chat_service.store.rename(name, new_name.strip())
        except PersonalAIError as exc:
            QMessageBox.warning(self, "Rename session", str(exc))
            return
        if self.conversation is not None and self.conversation.name == name:
            self.conversation = conversation
        self._reload_sessions()
        self._render_transcript()

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
        self.start_session(name.strip())

    def start_session(self, name: str) -> None:
        task = self.task_combo.currentText()
        self.conversation = self.chat_service.store.load_or_create(name, task)
        self.chat_service.store.save(self.conversation)
        self._reload_sessions()
        self._render_transcript()

    def start_quick_session(self) -> None:
        self.task_combo.setCurrentText("general")
        self.start_session("chat_" + datetime.now(UTC).strftime("%Y%m%d_%H%M%S"))

    def _clear_current_session(self) -> None:
        if self.conversation is None or not self.conversation.messages:
            return
        answer = QMessageBox.question(
            self,
            "Clear session",
            f"Clear every message in '{self.conversation.name}'? This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.conversation.messages.clear()
        self.chat_service.store.save(self.conversation)
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
        is_empty = self.conversation is None or not self.conversation.messages
        self.content_stack.setCurrentWidget(self.empty_state if is_empty else self.transcript)
        self._update_model_label()
        self.regenerate_btn.setEnabled(self._can_regenerate())
        self.copy_latest_btn.setEnabled(self._latest_assistant_reply() is not None)
        self.memory_btn.setEnabled(not self._sending and not self._memory_suggesting and not is_empty)

    def _update_model_label(self) -> None:
        model = self.chat_service.config.model_for(self.task_combo.currentText())
        self.model_label.setText(f"Model: {model}")
        if self.conversation is not None:
            self.conversation_title.setText(self.conversation.name.replace("_", " "))

    def _can_regenerate(self) -> bool:
        if self._sending or self.conversation is None or len(self.conversation.messages) < 2:
            return False
        reply, request = self.conversation.messages[-1], self.conversation.messages[-2]
        return (
            reply.role == "assistant"
            and request.role == "user"
            and not request.content.startswith("[image:")
        )

    def _latest_assistant_reply(self) -> str | None:
        if self.conversation is None:
            return None
        for message in reversed(self.conversation.messages):
            if message.role == "assistant" and message.content.strip():
                return message.content
        return None

    def _copy_latest_reply(self) -> None:
        reply = self._latest_assistant_reply()
        if reply:
            QApplication.clipboard().setText(reply)

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
        self._refresh_attachment_status()

    def _clear_context(self) -> None:
        self.context_paths = []
        self._refresh_attachment_status()

    # ---- image attach (button or drag-and-drop) ----

    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Choose an image", "", "Images (*.png *.jpg *.jpeg *.webp *.gif *.bmp)",
        )
        if path:
            self._attach_image(Path(path))

    def _attach_image(self, path: Path) -> None:
        """Only one image at a time (unlike --context's multiple files) -
        matches send_with_image()'s one-image contract and keeps the
        "what will actually get sent" state unambiguous at a glance."""
        self.attached_image_path = path
        pixmap = QPixmap(str(path))
        if not pixmap.isNull():
            self.image_preview.setPixmap(pixmap.scaledToHeight(
                IMAGE_PREVIEW_HEIGHT, Qt.TransformationMode.SmoothTransformation))
            self.image_preview.show()
        else:
            self.image_preview.hide()
        self._refresh_attachment_status()

    def _clear_image(self) -> None:
        self.attached_image_path = None
        self.image_preview.clear()
        self.image_preview.hide()
        self._refresh_attachment_status()

    def _clear_attachments(self) -> None:
        self.context_paths = []
        self.attached_image_path = None
        self.image_preview.clear()
        self.image_preview.hide()
        self._refresh_attachment_status()

    def _refresh_attachment_status(self) -> None:
        staged = [Path(path).name for path in self.context_paths]
        if self.attached_image_path is not None:
            staged.append(self.attached_image_path.name)
        self.context_label.setText("No attachments" if not staged else ", ".join(staged))
        self.clear_attachments_btn.setEnabled(bool(staged))
        self.clear_attachments_btn.setVisible(bool(staged))
        self.attachment_widget.setVisible(bool(staged))

    @staticmethod
    def _dropped_image_path(mime_data) -> Path | None:
        if not mime_data.hasUrls():
            return None
        for url in mime_data.urls():
            path = Path(url.toLocalFile())
            if path.suffix.lower() in IMAGE_SUFFIXES:
                return path
        return None

    def dragEnterEvent(self, event) -> None:
        if self._dropped_image_path(event.mimeData()) is not None:
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dropEvent(self, event) -> None:
        path = self._dropped_image_path(event.mimeData())
        if path is not None:
            self._attach_image(path)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)

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
        image_path = self.attached_image_path
        display_text = (
            text if image_path is None else f"[image: {image_path.name}] {message}".strip()
        )
        self._clear_context()
        self._clear_image()

        self.input_edit.clear()
        self.content_stack.setCurrentWidget(self.transcript)
        transcript_view.append_role_label(self.transcript, "user")
        transcript_view.append_body(self.transcript, display_text + "\n\n")
        transcript_view.append_role_label(self.transcript, "assistant")
        self._sending = True
        self._start_generation_status()
        self.send_btn.setEnabled(False)
        self.regenerate_btn.setEnabled(False)
        self.memory_btn.setEnabled(False)
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)

        if image_path is None:
            self._send_task = self.task_runner.submit(
                self.chat_service.send, self.conversation, message,
                on_progress=self._on_token,
                on_result=self._on_done,
                on_error=self._on_error,
                on_cancelled=self._on_cancelled,
                deep_thinking=self.deep_btn.isChecked(),
            )
        else:
            self._send_task = self.task_runner.submit(
                self.chat_service.send_with_image, self.conversation, message, image_path,
                on_progress=self._on_token,
                on_result=self._on_done,
                on_error=self._on_error,
                on_cancelled=self._on_cancelled,
            )

    def _on_token(self, token: str) -> None:
        transcript_view.append_body(self.transcript, token)

    def _on_done(self, _reply: str) -> None:
        # Re-render from the now-saved conversation instead of just
        # appending "\n\n" to the raw streamed text - this replaces the
        # plain-text streamed reply with a markdown-rendered one (code
        # blocks, bold, lists, ...) now that the full message is known.
        self._render_transcript()
        self._sending = False
        self._stop_generation_status()
        self._send_task = None
        self.send_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.memory_btn.setEnabled(not self._memory_suggesting)
        self._reload_sessions()

    def _on_error(self, exc: BaseException) -> None:
        transcript_view.append_body(self.transcript, f"\n[error] {exc}\n\n")
        self._sending = False
        self._stop_generation_status()
        self._send_task = None
        self.send_btn.setEnabled(True)
        self.stop_btn.setVisible(False)
        self.regenerate_btn.setEnabled(self._can_regenerate())
        self.memory_btn.setEnabled(not self._memory_suggesting and self.conversation is not None)

    def _on_cancelled(self) -> None:
        if (
            self.conversation is not None
            and self.conversation.messages
            and self.conversation.messages[-1].role == "assistant"
        ):
            # Cancellation normally stops before ChatService appends a reply.
            # If it arrived just after a response completed, remove that reply
            # so the saved conversation reflects the user's Stop action.
            self.conversation.messages.pop()
            self.chat_service.store.save(self.conversation)
        self._sending = False
        self._stop_generation_status()
        self._send_task = None
        self.stop_btn.setVisible(False)
        self.send_btn.setEnabled(True)
        self._render_transcript()

    def _stop_generation(self) -> None:
        if self._send_task is not None:
            self.stop_btn.setEnabled(False)
            self._send_task.cancel()

    def _start_generation_status(self) -> None:
        self._generation_started_at = time.monotonic()
        self._generation_timer.start()
        self._update_generation_status()
        self.generation_status.show()

    def _update_generation_status(self) -> None:
        if self._generation_started_at is None:
            return
        elapsed = int(time.monotonic() - self._generation_started_at)
        self.generation_status.setText(f"Generating {elapsed // 60}:{elapsed % 60:02d}")

    def _stop_generation_status(self) -> None:
        self._generation_timer.stop()
        self._generation_started_at = None
        self.generation_status.hide()

    def _regenerate(self) -> None:
        if not self._can_regenerate() or self.conversation is None:
            return
        try:
            self.chat_service.discard_last_reply(self.conversation)
        except PersonalAIError as exc:
            QMessageBox.warning(self, "Regenerate", str(exc))
            return
        self._render_transcript()
        self.content_stack.setCurrentWidget(self.transcript)
        transcript_view.append_role_label(self.transcript, "assistant")
        self._sending = True
        self._start_generation_status()
        self.send_btn.setEnabled(False)
        self.regenerate_btn.setEnabled(False)
        self.memory_btn.setEnabled(False)
        self.stop_btn.setVisible(True)
        self.stop_btn.setEnabled(True)
        self._send_task = self.task_runner.submit(
            self.chat_service.regenerate, self.conversation,
            on_progress=self._on_token,
            on_result=self._on_done,
            on_error=self._on_error,
            on_cancelled=self._on_cancelled,
            deep_thinking=self.deep_btn.isChecked(),
        )

    # ---- persistent memory ----

    def _review_memory(self) -> None:
        if self.conversation is None or self._memory_suggesting:
            return
        self._memory_suggesting = True
        self.memory_btn.setEnabled(False)
        self.task_runner.submit(
            self.chat_service.suggest_memory, self.conversation,
            on_result=self._show_memory_suggestions,
            on_error=self._on_memory_suggestion_error,
        )

    def _show_memory_suggestions(self, suggestions: list[str]) -> None:
        self._memory_suggesting = False
        self.memory_btn.setEnabled(not self._sending)
        if not suggestions:
            QMessageBox.information(self, "Review memory", "No lasting facts were suggested from this chat.")
            return
        dialog = MemoryApprovalDialog(suggestions, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        approved = dialog.approved()
        if not approved:
            return
        config = self.chat_service.config
        add_approved_entries(config.memory_entries, approved)
        self.config_store.save(config)

    def _on_memory_suggestion_error(self, exc: BaseException) -> None:
        self._memory_suggesting = False
        self.memory_btn.setEnabled(not self._sending and self.conversation is not None)
        QMessageBox.warning(self, "Review memory", str(exc))
