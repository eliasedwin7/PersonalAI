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
    QInputDialog,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from personalai.core.config import (
    BACKEND_NAMES,
    LOCAL_MODEL_PROFILES,
    Config,
    ConfigStore,
    MemoryEntry,
)
from personalai.core.errors import PersonalAIError
from personalai.services.chat_service import SYSTEM_PROMPTS, TEXT_TASKS, VISION_TASK
from personalai.services.voice_service import WHISPER_MODEL_SIZES
from personalai.ui.model_picker import populate_model_combo, selected_model
from personalai.ui.workers import TaskRunner

PROMPT_TASKS = (*TEXT_TASKS, VISION_TASK)


def _model_combo(
    current_value: str,
    pulled_models: list[str],
    recommended_models: list[str] | None = None,
) -> QComboBox:
    """An editable picker that also permits remote/API model names."""
    combo = QComboBox()
    combo.setEditable(True)
    populate_model_combo(combo, current_value, pulled_models, recommended_models or [])
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
        self.resize(760, 680)

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

        setup = QWidget()
        setup_row = QHBoxLayout(setup)
        setup_row.setContentsMargins(0, 0, 0, 0)
        self.profile_combo = QComboBox()
        for key, profile in LOCAL_MODEL_PROFILES.items():
            self.profile_combo.addItem(profile["label"], key)
        self.profile_combo.setCurrentIndex(self.profile_combo.findData(config.local_model_profile))
        setup_row.addWidget(self.profile_combo, stretch=1)
        apply_profile_btn = QPushButton("Apply profile")
        apply_profile_btn.clicked.connect(self._apply_local_profile)
        setup_row.addWidget(apply_profile_btn)
        self.install_profile_btn = QPushButton("Install recommended")
        self.install_profile_btn.setObjectName("primaryButton")
        self.install_profile_btn.clicked.connect(self._install_local_profile)
        setup_row.addWidget(self.install_profile_btn)
        form.addRow("Local AI setup:", setup)

        pulled_models = self._pulled_ollama_models(config)
        recommended_models = self._selected_recommended_chat_models()
        self.general_edit = _model_combo(config.model_for("general"), pulled_models, recommended_models)
        self.story_edit = _model_combo(config.model_for("story"), pulled_models, recommended_models)
        self.code_edit = _model_combo(config.model_for("code"), pulled_models, recommended_models)
        self.vision_edit = _model_combo(config.model_for("vision"), pulled_models)
        form.addRow("Chat model:", self.general_edit)
        form.addRow("Writing model:", self.story_edit)
        form.addRow("Code model:", self.code_edit)
        form.addRow("Vision model:", self.vision_edit)

        self.routing_check = QCheckBox("Use a compact model for simple chat messages")
        self.routing_check.setChecked(config.intelligent_routing)
        form.addRow("Smart routing:", self.routing_check)
        self.unload_models_check = QCheckBox("Release GPU memory after each reply")
        self.unload_models_check.setChecked(config.unload_models_after_reply)
        self.unload_models_check.setToolTip(
            "Recommended when Forge or ComfyUI share this GPU."
        )
        form.addRow("Shared GPU:", self.unload_models_check)

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
        self.model_action_status = QLabel()
        self.model_action_status.setObjectName("mutedLabel")
        self.model_action_status.hide()
        manager_layout.addWidget(self.model_action_status)
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

        self.voice_commands_check = QCheckBox("Handle local voice commands")
        self.voice_commands_check.setChecked(config.voice_commands_enabled)
        self.voice_commands_check.setToolTip(
            "Examples: 'Nexus open settings', 'Nexus go to knowledge', 'Nexus test microphone'."
        )
        form.addRow("Commands:", self.voice_commands_check)
        self.wake_word_edit = QLineEdit(config.voice_wake_word)
        self.wake_word_edit.setToolTip("Word Nexus listens for at the start of local voice commands.")
        form.addRow("Wake word:", self.wake_word_edit)

        self.continuous_voice_check = QCheckBox("Keep listening after spoken replies")
        self.continuous_voice_check.setChecked(config.voice_continuous_conversation)
        form.addRow("Conversation mode:", self.continuous_voice_check)

        self.tts_rate_spin = QSpinBox()
        self.tts_rate_spin.setRange(120, 220)
        self.tts_rate_spin.setValue(config.voice_tts_rate)
        self.tts_rate_spin.setToolTip("Lower values sound calmer; Windows default is often faster.")
        form.addRow("Speech speed:", self.tts_rate_spin)

        self.tts_volume_spin = QSpinBox()
        self.tts_volume_spin.setRange(20, 100)
        self.tts_volume_spin.setValue(round(config.voice_tts_volume * 100))
        form.addRow("Speech volume:", self.tts_volume_spin)
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

        layout.addWidget(QLabel("Approved memory"))
        self._memory_entries = [
            MemoryEntry(entry.text, entry.created_at, entry.source, entry.category)
            for entry in config.memory_entries
        ]
        self.memory_list = QListWidget()
        self.memory_list.setMaximumHeight(118)
        self._refresh_memory_entries()
        layout.addWidget(self.memory_list)
        memory_actions = QHBoxLayout()
        add_memory_btn = QPushButton("Add")
        add_memory_btn.clicked.connect(self._add_memory_entry)
        memory_actions.addWidget(add_memory_btn)
        edit_memory_btn = QPushButton("Edit selected")
        edit_memory_btn.clicked.connect(self._edit_memory_entry)
        memory_actions.addWidget(edit_memory_btn)
        delete_memory_btn = QPushButton("Delete selected")
        delete_memory_btn.clicked.connect(self._delete_memory_entry)
        memory_actions.addWidget(delete_memory_btn)
        memory_actions.addStretch(1)
        layout.addLayout(memory_actions)

        self.global_hotkey_check = QCheckBox("Open Nexus with Ctrl+Alt+N (Windows)")
        self.global_hotkey_check.setChecked(config.global_hotkey_enabled)
        layout.addWidget(self.global_hotkey_check)

        self.agent_verify_check = QCheckBox("Review completed Agent changes before reporting success")
        self.agent_verify_check.setChecked(config.agent_verify_changes)
        layout.addWidget(self.agent_verify_check)

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

    def _refresh_memory_entries(self) -> None:
        self.memory_list.clear()
        for index, entry in enumerate(self._memory_entries):
            item = QListWidgetItem(entry.text)
            item.setData(Qt.ItemDataRole.UserRole, index)
            item.setToolTip(f"{entry.source}\n{entry.created_at}")
            self.memory_list.addItem(item)

    def _selected_memory_index(self) -> int | None:
        item = self.memory_list.currentItem()
        return None if item is None else item.data(Qt.ItemDataRole.UserRole)

    def _add_memory_entry(self) -> None:
        text, ok = QInputDialog.getText(self, "Add memory", "Fact to remember:")
        if ok and text.strip():
            self._memory_entries.append(MemoryEntry(text=text.strip(), source="Added in Settings"))
            self._refresh_memory_entries()

    def _edit_memory_entry(self) -> None:
        index = self._selected_memory_index()
        if index is None:
            return
        entry = self._memory_entries[index]
        text, ok = QInputDialog.getText(self, "Edit memory", "Fact to remember:", text=entry.text)
        if ok and text.strip():
            entry.text = text.strip()
            entry.source = "Edited in Settings"
            self._refresh_memory_entries()

    def _delete_memory_entry(self) -> None:
        index = self._selected_memory_index()
        if index is None:
            return
        del self._memory_entries[index]
        self._refresh_memory_entries()

    @staticmethod
    def _pulled_ollama_models(config: Config) -> list[str]:
        from personalai.services.ollama_client import OllamaClient

        return OllamaClient(config.ollama_url).list_models()

    def _set_installed_models(self, models: list[str]) -> None:
        self.installed_models.clear()
        self.installed_models.addItems(models or ["No local Ollama models found."])

    def _apply_local_profile(self) -> None:
        profile = LOCAL_MODEL_PROFILES[self.profile_combo.currentData()]
        installed_models = [
            self.installed_models.item(index).text()
            for index in range(self.installed_models.count())
            if self.installed_models.item(index).text() != "No local Ollama models found."
        ]
        recommended_models = self._selected_recommended_chat_models()
        populate_model_combo(
            self.general_edit, profile["models"]["general"], installed_models, recommended_models
        )
        populate_model_combo(
            self.story_edit, profile["models"]["story"], installed_models, recommended_models
        )
        populate_model_combo(
            self.code_edit, profile["models"]["code"], installed_models, recommended_models
        )
        populate_model_combo(self.vision_edit, profile["models"]["vision"], installed_models, [])
        self.routing_check.setChecked(True)
        self.unload_models_check.setChecked(True)
        self.model_action_status.setText("Profile applied. Save Settings to keep it.")
        self.model_action_status.show()

    def _selected_recommended_chat_models(self) -> list[str]:
        profile = LOCAL_MODEL_PROFILES[self.profile_combo.currentData()]
        names = profile.get("chat_models", [
            *profile["models"].values(),
            profile["fast_model"],
            profile["deep_model"],
        ])
        return [model for model in dict.fromkeys(names) if model][:5]

    def _install_local_profile(self) -> None:
        profile = LOCAL_MODEL_PROFILES[self.profile_combo.currentData()]
        models = list(dict.fromkeys([
            *profile["models"].values(),
            profile["fast_model"],
            profile["deep_model"],
            profile["embedding_model"],
        ]))
        models = [model for model in models if model]
        client = self._ollama_client()
        if self.task_runner is None:
            try:
                self._pull_models(client, models)
            except PersonalAIError as exc:
                QMessageBox.warning(self, "Install recommended models", str(exc))
                return
            self._profile_installed()
            return
        self._set_model_manager_busy(True, "Installing recommended local models...")
        self.task_runner.submit(
            self._pull_models, client, models,
            on_result=lambda _result: self._profile_installed(),
            on_error=self._on_model_action_error,
        )

    @staticmethod
    def _pull_models(client, models: list[str]) -> None:
        for model in models:
            client.pull_model(model)

    def _profile_installed(self) -> None:
        self.config.apply_local_profile(self.profile_combo.currentData())
        self.store.save(self.config)
        self._apply_local_profile()
        self._set_model_manager_busy(False)
        self._refresh_installed_models()
        self.model_action_status.setText("Recommended models installed and profile saved.")
        self.model_action_status.show()

    def _ollama_client(self):
        from personalai.services.ollama_client import OllamaClient

        return OllamaClient(self.url_edit.text().strip() or self.config.ollama_url)

    def _refresh_installed_models(self) -> None:
        models = self._ollama_client().list_models()
        self._set_installed_models(models)
        recommended_models = self._selected_recommended_chat_models()
        for combo in (self.general_edit, self.story_edit, self.code_edit):
            populate_model_combo(combo, selected_model(combo), models, recommended_models)
        populate_model_combo(self.vision_edit, selected_model(self.vision_edit), models, [])

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
        self._set_model_manager_busy(True, f"Pulling {model}...")
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
        self._set_model_manager_busy(True, f"Removing {model}...")
        self.task_runner.submit(
            client.delete_model, model,
            on_result=lambda _result: self._model_removed(),
            on_error=self._on_model_action_error,
        )

    def _set_model_manager_busy(self, busy: bool, status: str = "") -> None:
        self._model_action_in_progress = busy
        for widget in (
            self.installed_models, self.refresh_models_btn, self.remove_model_btn,
            self.pull_model_edit, self.pull_model_btn, self.install_profile_btn,
        ):
            widget.setEnabled(not busy)
        self.model_action_status.setText(status)
        self.model_action_status.setVisible(busy)

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
        config.models["general"] = selected_model(self.general_edit) or config.models["general"]
        config.models["story"] = selected_model(self.story_edit) or config.models["story"]
        config.models["code"] = selected_model(self.code_edit) or config.models["code"]
        config.models["vision"] = selected_model(self.vision_edit) or config.models["vision"]
        config.context_char_limit = self.limit_spin.value()
        config.history_char_limit = self.history_limit_spin.value()
        config.mic_device = None
        config.whisper_model = self.whisper_combo.currentText()
        config.voice_commands_enabled = self.voice_commands_check.isChecked()
        config.voice_wake_word = self.wake_word_edit.text().strip() or "nexus"
        config.voice_continuous_conversation = self.continuous_voice_check.isChecked()
        config.voice_tts_rate = self.tts_rate_spin.value()
        config.voice_tts_volume = self.tts_volume_spin.value() / 100
        config.assistant_memory = self.memory_edit.toPlainText().strip()
        config.memory_entries = self._memory_entries
        config.apply_local_profile(self.profile_combo.currentData())
        config.models["general"] = selected_model(self.general_edit) or config.models["general"]
        config.models["story"] = selected_model(self.story_edit) or config.models["story"]
        config.models["code"] = selected_model(self.code_edit) or config.models["code"]
        config.models["vision"] = selected_model(self.vision_edit) or config.models["vision"]
        config.global_hotkey_enabled = self.global_hotkey_check.isChecked()
        config.agent_verify_changes = self.agent_verify_check.isChecked()
        config.intelligent_routing = self.routing_check.isChecked()
        config.unload_models_after_reply = self.unload_models_check.isChecked()

        self._prompt_texts[self.prompt_task_combo.currentText()] = self.prompt_edit.toPlainText()
        for task in PROMPT_TASKS:
            text = self._prompt_texts[task].strip()
            if text and text != SYSTEM_PROMPTS[task]:
                config.system_prompts[task] = text
            else:
                config.system_prompts.pop(task, None)

        self.store.save(config)
        self.accept()
