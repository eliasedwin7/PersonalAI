"""Agent tab: a file-aware assistant scoped to a workspace folder - the
GUI counterpart of `myai agent`. Two panels: a conversation transcript
(what you asked, the final answer) and an Activity log (every tool
call, in full, regardless of mode - visibility isn't something any mode
turns off).

MANUAL mode confirmations happen on a background thread (AgentService.
run_turn runs via TaskRunner) but need a Qt dialog on the GUI thread and
the calling thread to actually wait for the answer - _ConfirmBridge
does this with a plain threading.Event: the worker thread emits a
queued signal carrying a mutable container, blocks on the event, and
the GUI-thread slot shows the dialog, fills in the answer, and sets the
event to unblock the worker.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from pathlib import Path

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
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
from personalai.services import agent_service
from personalai.services.agent_service import Activity, AgentMode, AgentService
from personalai.services.chat_service import ChatService
from personalai.ui import transcript_view
from personalai.ui.chat_tab import ChatInputEdit
from personalai.ui.workers import TaskRunner

AGENT_SESSION = "agent"
AGENT_TASK = "general"  # picks which model config.model_for() uses; the actual
                        # system prompt comes from agent_service.system_prompt_for()

MODE_LABELS = {
    AgentMode.PLAN: "Plan (propose only, nothing is applied)",
    AgentMode.AUTO_ACCEPT: "Auto-accept (no per-action confirmation)",
    AgentMode.MANUAL: "Manual (confirm every write/edit/command)",
}


class _AgentBridge(QObject):
    """Lives on the GUI thread; its signals are emitted from the worker
    thread running AgentService.run_turn, so Qt automatically delivers
    them as queued (thread-safe) calls to whatever's connected."""

    activity = Signal(object)          # Activity
    confirm_request = Signal(object)   # a {"description", "event", "result"} dict


class AgentTab(QWidget):
    def __init__(self, chat_service: ChatService, task_runner: TaskRunner,
                config_store=None) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.task_runner = task_runner
        self.config_store = config_store
        self.agent = AgentService(chat_service=chat_service)
        self.conversation: Conversation = chat_service.store.load_or_create(
            AGENT_SESSION, AGENT_TASK
        )
        self._sending = False
        self._active_mode: AgentMode | None = None
        self._last_plan_request: str | None = None
        self._updating_model_combo = False
        self._available_models = self._load_available_models()

        self._bridge = _AgentBridge()
        self._bridge.activity.connect(self._on_activity)
        self._bridge.confirm_request.connect(self._on_confirm_request)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        top_row = QHBoxLayout()
        top_row.addWidget(QLabel("Workspace:"))
        self.workspace_edit = QLineEdit(chat_service.config.agent_workspace or "")
        self.workspace_edit.setPlaceholderText("Folder the agent may read/edit/run commands in")
        top_row.addWidget(self.workspace_edit, stretch=1)
        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._browse_workspace)
        top_row.addWidget(browse_btn)

        layout.addLayout(top_row)

        control_row = QHBoxLayout()
        control_row.addWidget(QLabel("Mode:"))
        self.mode_combo = QComboBox()
        for mode in AgentMode:
            self.mode_combo.addItem(MODE_LABELS[mode], mode.value)
        self.mode_combo.setCurrentIndex(
            self.mode_combo.findData(chat_service.config.agent_mode)
        )
        control_row.addWidget(self.mode_combo, stretch=1)
        control_row.addWidget(QLabel("Model:"))
        self.model_combo = QComboBox()
        self.model_combo.setEditable(True)
        self.model_combo.setMinimumWidth(180)
        self.model_combo.setToolTip(
            "Model used by Agent. Pick an installed Ollama model or type one."
        )
        self.model_combo.currentTextChanged.connect(self._on_model_changed)
        control_row.addWidget(self.model_combo)
        self.refresh_model_btn = QPushButton("Refresh")
        self.refresh_model_btn.setToolTip("Refresh installed Ollama models.")
        self.refresh_model_btn.clicked.connect(self._refresh_available_models)
        control_row.addWidget(self.refresh_model_btn)
        layout.addLayout(control_row)

        splitter = QSplitter(Qt.Orientation.Vertical)

        transcript_container = QWidget()
        transcript_layout = QVBoxLayout(transcript_container)
        transcript_layout.setContentsMargins(0, 0, 0, 0)
        transcript_layout.addWidget(QLabel("Conversation"))
        self.transcript = QTextEdit()
        self.transcript.setObjectName("chatTranscript")
        self.transcript.setReadOnly(True)
        transcript_layout.addWidget(self.transcript)
        splitter.addWidget(transcript_container)

        activity_container = QWidget()
        activity_layout = QVBoxLayout(activity_container)
        activity_layout.setContentsMargins(0, 0, 0, 0)
        activity_layout.addWidget(QLabel("Activity (every tool call, regardless of mode)"))
        self.activity_log = QPlainTextEdit()
        self.activity_log.setObjectName("toolOutput")
        self.activity_log.setReadOnly(True)
        activity_layout.addWidget(self.activity_log)
        splitter.addWidget(activity_container)

        splitter.setStretchFactor(0, 2)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

        input_row = QHBoxLayout()
        self.input_edit = ChatInputEdit()
        self.input_edit.setPlaceholderText(
            "Ask the agent to do something in the workspace (Enter to send)…"
        )
        self.input_edit.setMaximumHeight(90)
        self.input_edit.submitted.connect(self._send)
        input_row.addWidget(self.input_edit, stretch=1)
        self.do_it_btn = QPushButton("Do it")
        self.do_it_btn.setObjectName("primaryButton")
        self.do_it_btn.setEnabled(False)
        self.do_it_btn.setToolTip("Run the latest Plan response once in Auto-accept mode.")
        self.do_it_btn.clicked.connect(self._do_latest_plan)
        input_row.addWidget(self.do_it_btn)
        self.send_btn = QPushButton("Send")
        self.send_btn.setObjectName("primaryButton")
        self.send_btn.clicked.connect(self._send)
        input_row.addWidget(self.send_btn)
        layout.addLayout(input_row)

        self._render_transcript()
        self._update_model_combo()

    # ---- workspace/mode ----

    def _browse_workspace(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose a workspace folder")
        if folder:
            self.workspace_edit.setText(folder)
            self.chat_service.config.agent_workspace = folder
            if self.config_store is not None:
                self.config_store.save(self.chat_service.config)

    def _current_mode(self) -> AgentMode:
        return AgentMode(self.mode_combo.currentData())

    def _load_available_models(self) -> list[str]:
        try:
            from personalai.services.ollama_client import OllamaClient

            return OllamaClient(self.chat_service.config.ollama_url).list_models()
        except (ImportError, OSError, PersonalAIError):
            return []

    def _refresh_available_models(self) -> None:
        self._available_models = self._load_available_models()
        self._update_model_combo()

    def _update_model_combo(self) -> None:
        current = self.chat_service.config.model_for(AGENT_TASK)
        self._updating_model_combo = True
        try:
            items = list(self._available_models)
            if current and current not in items:
                items.insert(0, current)
            self.model_combo.clear()
            self.model_combo.addItems(items)
            self.model_combo.setCurrentText(current)
        finally:
            self._updating_model_combo = False

    def _on_model_changed(self, model: str) -> None:
        if self._updating_model_combo:
            return
        model = model.strip()
        if not model:
            return
        self.chat_service.config.models[AGENT_TASK] = model
        self.chat_service.config.fast_model = ""
        if self.config_store is not None:
            self.config_store.save(self.chat_service.config)

    # ---- transcript rendering ----
    #
    # Deliberately NOT transcript_view.render_transcript() unmodified:
    # AgentService.run_turn() appends synthetic "user"-role turns to
    # feed tool results back to the model (agent_service.
    # TOOL_RESULT_PREFIX) and assistant turns that are themselves raw
    # JSON tool calls - neither is something a human said or should read
    # as prose. Those are exactly what the Activity panel already shows
    # in a more useful form, so this view filters them out and shows
    # only the human's question and the model's real final answers.

    def _render_transcript(self) -> None:
        self.transcript.clear()
        for msg in self.conversation.messages:
            if msg.content.startswith(agent_service.TOOL_RESULT_PREFIX):
                continue
            if msg.role == "assistant" and agent_service.parse_tool_call(msg.content):
                continue
            transcript_view.append_message_block(self.transcript, msg.role, msg.content, msg.timestamp)
        transcript_view.scroll_to_bottom(self.transcript)

    # ---- activity + confirmation (called from the worker thread via signals) ----

    def _on_activity(self, activity: Activity) -> None:
        marker = "applied" if activity.applied else "proposed/skipped"
        self.activity_log.appendPlainText(
            f"[{activity.tool} - {marker}] {activity.args}\n{activity.result}\n"
        )

    def _on_confirm_request(self, container: dict) -> None:
        answer = QMessageBox.question(
            self, "Confirm agent action", container["description"],
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        container["result"] = answer == QMessageBox.StandardButton.Yes
        container["event"].set()

    def _make_confirm_callback(self) -> Callable[[str], bool]:
        def on_confirm(description: str) -> bool:
            event = threading.Event()
            container = {"description": description, "event": event, "result": False}
            self._bridge.confirm_request.emit(container)
            event.wait()
            return container["result"]
        return on_confirm

    # ---- sending ----

    def _send(self) -> None:
        if self._sending:
            return
        text = self.input_edit.toPlainText().strip()
        if not text:
            return
        self._submit_turn(text, self._current_mode())

    def _do_latest_plan(self) -> None:
        if self._sending or not self._last_plan_request:
            return
        self._submit_turn(
            self._last_plan_request,
            AgentMode.AUTO_ACCEPT,
            display_text=f"Do it: {self._last_plan_request}",
        )

    def _workspace_path(self) -> Path | None:
        workspace_str = self.workspace_edit.text().strip()
        if not workspace_str:
            QMessageBox.warning(self, "Agent", "Choose a workspace folder first.")
            return None
        workspace = Path(workspace_str).expanduser()
        if not workspace.is_dir():
            QMessageBox.warning(self, "Agent", f"Workspace folder not found: {workspace}")
            return None
        return workspace

    def _submit_turn(
        self,
        text: str,
        mode: AgentMode,
        display_text: str | None = None,
    ) -> None:
        workspace = self._workspace_path()
        if workspace is None:
            return
        self.input_edit.clear()
        transcript_view.append_message_block(self.transcript, "user", display_text or text)
        self._sending = True
        self._active_mode = mode
        self.do_it_btn.setEnabled(False)
        self.send_btn.setEnabled(False)
        if mode is AgentMode.PLAN:
            self._last_plan_request = text

        kwargs: dict = {
            "on_activity": self._bridge.activity.emit,
        }
        if mode is AgentMode.MANUAL:
            kwargs["on_confirm"] = self._make_confirm_callback()

        self.task_runner.submit(
            self.agent.run_turn, self.conversation, text, workspace, mode,
            on_result=self._on_done, on_error=self._on_error, **kwargs,
        )

    def _on_done(self, reply: str) -> None:
        transcript_view.append_message_block(self.transcript, "assistant", reply)
        completed_mode = self._active_mode
        if completed_mode is not AgentMode.PLAN:
            self._last_plan_request = None
        self._active_mode = None
        self._sending = False
        self.send_btn.setEnabled(True)
        self.do_it_btn.setEnabled(
            completed_mode is AgentMode.PLAN and bool(self._last_plan_request)
        )

    def _on_error(self, exc: BaseException) -> None:
        if isinstance(exc, PersonalAIError):
            transcript_view.append_message_block(self.transcript, "error", str(exc))
        else:
            transcript_view.append_message_block(self.transcript, "error", f"Unexpected error: {exc}")
        if self._active_mode is not AgentMode.PLAN:
            self._last_plan_request = None
        self._active_mode = None
        self._sending = False
        self.send_btn.setEnabled(True)
        self.do_it_btn.setEnabled(False)
