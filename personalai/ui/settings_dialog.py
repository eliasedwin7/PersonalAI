"""Grouped desktop settings for connection, model, voice, and assistant preferences."""

from __future__ import annotations

import os
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from personalai.core.config import BACKEND_NAMES, Config, ConfigStore
from personalai.core.errors import PersonalAIError
from personalai.services.chat_service import SYSTEM_PROMPTS, TEXT_TASKS, VISION_TASK
from personalai.services.voice_service import WHISPER_MODEL_SIZES
from personalai.ui.workers import TaskRunner

PROMPT_TASKS = (*TEXT_TASKS, VISION_TASK)


def _model_combo(current_value: str, pulled_models: list[str]) -> QComboBox:
    """An editable picker that also permits remote/API model names."""
    combo = QComboBox()
    combo.setEditable(True)
    items = list(pulled_models)
    if current_value not in items:
        items.insert(0, current_value)
    combo.addItems(items)
    combo.setCurrentText(current_value)
    return combo


class SettingsDialog(QDialog):
    def __init__(self, config: Config, store: ConfigStore, parent=None,
                 task_runner: TaskRunner | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.store = store
        self.task_runner = task_runner
        self._model_action_in_progress = False
        self.setWindowTitle("Settings")
        self.resize(760, 600)

        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs, stretch=1)

        self._build_connection_tab(config)
        self._build_models_tab(config)
        self._build_voice_tab(config)
        self._build_assistant_tab(config)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _build_connection_tab(self, config: Config) -> None:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 18, 18, 18)
        form.setVerticalSpacing(12)

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(list(BACKEND_NAMES))
        self.backend_combo.setCurrentText(config.backend)
        form.addRow("Backend:", self.backend_combo)

        self.url_edit = QLineEdit(config.ollama_url)
        self.url_edit.setToolTip("Address of your local Ollama server.")
        form.addRow("Ollama URL:", self.url_edit)

        self.openai_base_edit = QLineEdit(config.openai_base_url)
        self.openai_base_edit.setToolTip(
            "Endpoint for OpenAI-compatible providers, local servers, or proxies."
        )
        form.addRow("OpenAI-compatible URL:", self.openai_base_edit)

        self.forge_url_edit = QLineEdit(config.forge_url)
        self.forge_url_edit.setToolTip(
            "Stable Diffusion Forge address used in Images. Credentials stay in environment variables."
        )
        form.addRow("Forge URL:", self.forge_url_edit)

        key_note = QLabel(
            "API keys are read only from ANTHROPIC_API_KEY and OPENAI_API_KEY. "
            + self._key_status()
        )
        key_note.setWordWrap(True)
        key_note.setObjectName("mutedLabel")
        form.addRow(key_note)
        self.tabs.addTab(page, "Connection")

    def _build_models_tab(self, config: Config) -> None:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 18, 18, 18)
        form.setVerticalSpacing(12)

        pulled_models = self._pulled_ollama_models(config)
        self.general_edit = _model_combo(config.model_for("general"), pulled_models)
        self.story_edit = _model_combo(config.model_for("story"), pulled_models)
        self.code_edit = _model_combo(config.model_for("code"), pulled_models)
        self.vision_edit = _model_combo(config.model_for("vision"), pulled_models)
        form.addRow("Chat model:", self.general_edit)
        form.addRow("Writing model:", self.story_edit)
        form.addRow("Code model:", self.code_edit)
        form.addRow("Vision model:", self.vision_edit)

        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(500, 200_000)
        self.limit_spin.setValue(config.context_char_limit)
        self.limit_spin.setToolTip("Maximum characters read from staged reference files per message.")
        form.addRow("Reference context limit:", self.limit_spin)

        self.history_limit_spin = QSpinBox()
        self.history_limit_spin.setRange(1000, 1_000_000)
        self.history_limit_spin.setValue(config.history_char_limit)
        self.history_limit_spin.setToolTip(
            "Conversation history sent per request. Older turns are dropped first."
        )
        form.addRow("Conversation history limit:", self.history_limit_spin)

        self.airllm_tokens_spin = QSpinBox()
        self.airllm_tokens_spin.setRange(1, 8192)
        self.airllm_tokens_spin.setValue(config.airllm_max_new_tokens)
        self.airllm_tokens_spin.setToolTip(
            "Maximum new tokens per AirLLM reply. Keep this modest because AirLLM can be slow."
        )
        form.addRow("AirLLM reply limit:", self.airllm_tokens_spin)

        manager = QWidget()
        manager_layout = QVBoxLayout(manager)
        manager_layout.setContentsMargins(0, 0, 0, 0)
        self.installed_models = QListWidget()
        self.installed_models.setMaximumHeight(110)
        self._set_installed_models(pulled_models)
        manager_layout.addWidget(self.installed_models)
        manager_actions = QHBoxLayout()
        self.refresh_models_btn = QPushButton("Refresh")
        self.refresh_models_btn.clicked.connect(self._refresh_installed_models)
        manager_actions.addWidget(self.refresh_models_btn)
        self.remove_model_btn = QPushButton("Remove selected")
        self.remove_model_btn.clicked.connect(self._remove_selected_model)
        manager_actions.addWidget(self.remove_model_btn)
        manager_actions.addStretch(1)
        manager_layout.addLayout(manager_actions)
        pull_row = QHBoxLayout()
        self.pull_model_edit = QLineEdit()
        self.pull_model_edit.setPlaceholderText("Model to pull, e.g. llama3.1")
        pull_row.addWidget(self.pull_model_edit)
        self.pull_model_btn = QPushButton("Pull")
        self.pull_model_btn.clicked.connect(self._pull_model)
        pull_row.addWidget(self.pull_model_btn)
        manager_layout.addLayout(pull_row)
        form.addRow("Installed Ollama models:", manager)
        self.tabs.addTab(page, "Models")

    def _build_voice_tab(self, config: Config) -> None:
        page = QWidget()
        form = QFormLayout(page)
        form.setContentsMargins(18, 18, 18, 18)
        form.setVerticalSpacing(12)

        form.addRow("Microphone:", QLabel("System default"))

        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(list(WHISPER_MODEL_SIZES))
        self.whisper_combo.setCurrentText(config.whisper_model)
        self.whisper_combo.setToolTip("Larger voice models are more accurate but slower on CPU.")
        form.addRow("Transcription model:", self.whisper_combo)

        note = QLabel("Use Voice > Test microphone to confirm the system default input receives sound.")
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        form.addRow(note)
        self.tabs.addTab(page, "Voice")

    def _build_assistant_tab(self, config: Config) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        layout.setAlignment(Qt.AlignmentFlag.AlignTop)

        layout.addWidget(QLabel("Personal memory"))
        memory_note = QLabel("Information you choose to send with every assistant request.")
        memory_note.setObjectName("mutedLabel")
        layout.addWidget(memory_note)
        self.memory_edit = QPlainTextEdit(config.assistant_memory)
        self.memory_edit.setPlaceholderText(
            "Preferences, ongoing projects, names, or facts to remember"
        )
        self.memory_edit.setMaximumHeight(90)
        layout.addWidget(self.memory_edit)

        self.global_hotkey_check = QCheckBox("Open Nexus with Ctrl+Alt+N (Windows)")
        self.global_hotkey_check.setChecked(config.global_hotkey_enabled)
        layout.addWidget(self.global_hotkey_check)

        backup_row = QHBoxLayout()
        backup_row.addWidget(QLabel("Your conversations and approved memory:"))
        backup_row.addStretch(1)
        backup_btn = QPushButton("Export backup")
        backup_btn.clicked.connect(self._export_backup)
        backup_row.addWidget(backup_btn)
        layout.addLayout(backup_row)

        layout.addWidget(QLabel("System prompt"))
        prompt_task_row = QHBoxLayout()
        prompt_task_row.addWidget(QLabel("Mode:"))
        self.prompt_task_combo = QComboBox()
        self.prompt_task_combo.addItems(list(PROMPT_TASKS))
        prompt_task_row.addWidget(self.prompt_task_combo)
        reset_prompt_btn = QPushButton("Reset")
        reset_prompt_btn.setToolTip("Restore the built-in prompt for the selected mode.")
        reset_prompt_btn.clicked.connect(self._reset_current_prompt)
        prompt_task_row.addWidget(reset_prompt_btn)
        prompt_task_row.addStretch(1)
        layout.addLayout(prompt_task_row)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setMaximumHeight(130)
        layout.addWidget(self.prompt_edit)

        self._prompt_texts = {
            task: config.system_prompts.get(task) or SYSTEM_PROMPTS[task]
            for task in PROMPT_TASKS
        }
        self._last_prompt_task = self.prompt_task_combo.currentText()
        self.prompt_edit.setPlainText(self._prompt_texts[self._last_prompt_task])
        self.prompt_task_combo.currentTextChanged.connect(self._on_prompt_task_changed)
        layout.addStretch(1)
        self.tabs.addTab(page, "Assistant")

    def _on_prompt_task_changed(self, new_task: str) -> None:
        self._prompt_texts[self._last_prompt_task] = self.prompt_edit.toPlainText()
        self._last_prompt_task = new_task
        self.prompt_edit.setPlainText(self._prompt_texts[new_task])

    def _reset_current_prompt(self) -> None:
        task = self.prompt_task_combo.currentText()
        self._prompt_texts[task] = SYSTEM_PROMPTS[task]
        self.prompt_edit.setPlainText(SYSTEM_PROMPTS[task])

    @staticmethod
    def _pulled_ollama_models(config: Config) -> list[str]:
        from personalai.services.ollama_client import OllamaClient

        return OllamaClient(config.ollama_url).list_models()

    def _set_installed_models(self, models: list[str]) -> None:
        self.installed_models.clear()
        self.installed_models.addItems(models or ["No local Ollama models found."])

    def _ollama_client(self):
        from personalai.services.ollama_client import OllamaClient

        return OllamaClient(self.url_edit.text().strip() or self.config.ollama_url)

    def _refresh_installed_models(self) -> None:
        models = self._ollama_client().list_models()
        self._set_installed_models(models)
        for combo in (self.general_edit, self.story_edit, self.code_edit, self.vision_edit):
            current = combo.currentText()
            combo.clear()
            combo.addItems(models)
            combo.setCurrentText(current)

    def _pull_model(self) -> None:
        model = self.pull_model_edit.text().strip()
        if not model:
            return
        client = self._ollama_client()
        if self.task_runner is None:
            try:
                client.pull_model(model)
            except PersonalAIError as exc:
                QMessageBox.warning(self, "Pull model", str(exc))
                return
            self._model_pulled()
            return
        self._set_model_manager_busy(True)
        self.task_runner.submit(
            client.pull_model, model,
            on_result=lambda _result: self._model_pulled(),
            on_error=self._on_model_action_error,
        )

    def _remove_selected_model(self) -> None:
        item = self.installed_models.currentItem()
        if item is None or item.text() == "No local Ollama models found.":
            return
        model = item.text()
        answer = QMessageBox.question(
            self, "Remove model", f"Remove the local Ollama model '{model}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        client = self._ollama_client()
        if self.task_runner is None:
            try:
                client.delete_model(model)
            except PersonalAIError as exc:
                QMessageBox.warning(self, "Remove model", str(exc))
                return
            self._refresh_installed_models()
            return
        self._set_model_manager_busy(True)
        self.task_runner.submit(
            client.delete_model, model,
            on_result=lambda _result: self._model_removed(),
            on_error=self._on_model_action_error,
        )

    def _set_model_manager_busy(self, busy: bool) -> None:
        self._model_action_in_progress = busy
        for widget in (
            self.installed_models, self.refresh_models_btn, self.remove_model_btn,
            self.pull_model_edit, self.pull_model_btn,
        ):
            widget.setEnabled(not busy)

    def _model_pulled(self) -> None:
        self.pull_model_edit.clear()
        self._set_model_manager_busy(False)
        self._refresh_installed_models()

    def _model_removed(self) -> None:
        self._set_model_manager_busy(False)
        self._refresh_installed_models()

    def _on_model_action_error(self, exc: BaseException) -> None:
        self._set_model_manager_busy(False)
        QMessageBox.warning(self, "Ollama model", str(exc))

    def _export_backup(self) -> None:
        from personalai.core.backup import export_backup
        from personalai.core.conversation import ConversationStore

        path, _ = QFileDialog.getSaveFileName(
            self, "Export Nexus backup", "nexus-backup.zip", "ZIP files (*.zip)"
        )
        if not path:
            return
        try:
            saved = export_backup(Path(path), self.store.path, ConversationStore())
        except OSError as exc:
            QMessageBox.warning(self, "Export backup", str(exc))
            return
        QMessageBox.information(self, "Export backup", f"Backup saved to:\n{saved}")

    @staticmethod
    def _key_status() -> str:
        anthropic = "set" if os.environ.get("ANTHROPIC_API_KEY") else "not set"
        openai = "set" if os.environ.get("OPENAI_API_KEY") else "not set"
        return f"Currently: ANTHROPIC_API_KEY {anthropic}, OPENAI_API_KEY {openai}."

    def _save(self) -> None:
        config = self.config
        config.backend = self.backend_combo.currentText()
        config.ollama_url = self.url_edit.text().strip() or config.ollama_url
        config.openai_base_url = self.openai_base_edit.text().strip() or config.openai_base_url
        config.airllm_max_new_tokens = self.airllm_tokens_spin.value()
        config.forge_url = self.forge_url_edit.text().strip() or config.forge_url
        config.models["general"] = self.general_edit.currentText().strip() or config.models["general"]
        config.models["story"] = self.story_edit.currentText().strip() or config.models["story"]
        config.models["code"] = self.code_edit.currentText().strip() or config.models["code"]
        config.models["vision"] = self.vision_edit.currentText().strip() or config.models["vision"]
        config.context_char_limit = self.limit_spin.value()
        config.history_char_limit = self.history_limit_spin.value()
        config.mic_device = None
        config.whisper_model = self.whisper_combo.currentText()
        config.assistant_memory = self.memory_edit.toPlainText().strip()
        config.global_hotkey_enabled = self.global_hotkey_check.isChecked()

        self._prompt_texts[self.prompt_task_combo.currentText()] = self.prompt_edit.toPlainText()
        for task in PROMPT_TASKS:
            text = self._prompt_texts[task].strip()
            if text and text != SYSTEM_PROMPTS[task]:
                config.system_prompts[task] = text
            else:
                config.system_prompts.pop(task, None)

        self.store.save(config)
        self.accept()
