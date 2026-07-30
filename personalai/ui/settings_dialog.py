"""Settings dialog: the same knobs as `myai config`, edited from the GUI.

API keys are deliberately NOT edited here - same reasoning as the CLI's
`config set` refusing anthropic_api_key/openai_api_key (see cli.py):
they come from the ANTHROPIC_API_KEY / OPENAI_API_KEY environment
variables only, never written into a config file by this app.
"""

from __future__ import annotations

import os

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPlainTextEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from personalai.core.config import BACKEND_NAMES, Config, ConfigStore
from personalai.services import voice_service
from personalai.services.chat_service import SYSTEM_PROMPTS, TEXT_TASKS, VISION_TASK
from personalai.services.voice_service import WHISPER_MODEL_SIZES

PROMPT_TASKS = (*TEXT_TASKS, VISION_TASK)


def _model_combo(current_value: str, pulled_models: list[str]) -> QComboBox:
    """An editable combo box: pick from what's actually pulled in Ollama,
    or type any other model name (needed for Claude/OpenAI model names,
    which aren't listable this way)."""
    combo = QComboBox()
    combo.setEditable(True)
    items = list(pulled_models)
    if current_value not in items:
        items.insert(0, current_value)
    combo.addItems(items)
    combo.setCurrentText(current_value)
    return combo


class SettingsDialog(QDialog):
    def __init__(self, config: Config, store: ConfigStore, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.store = store
        self.setWindowTitle("Settings")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.backend_combo = QComboBox()
        self.backend_combo.addItems(list(BACKEND_NAMES))
        self.backend_combo.setCurrentText(config.backend)
        form.addRow("Backend:", self.backend_combo)

        self.url_edit = QLineEdit(config.ollama_url)
        form.addRow("Ollama URL:", self.url_edit)

        self.forge_url_edit = QLineEdit(config.forge_url)
        self.forge_url_edit.setToolTip(
            "Stable Diffusion Forge's URL (the Image tab). Point this at "
            "the GPU PC's LAN address, e.g. http://192.168.1.50:7860. "
            "Credentials (if Forge is gated with --gradio-auth) come from "
            "FORGE_USERNAME/FORGE_PASSWORD environment variables, not here."
        )
        form.addRow("Forge URL:", self.forge_url_edit)

        self.openai_base_edit = QLineEdit(config.openai_base_url)
        self.openai_base_edit.setToolTip(
            "Override for Codex-compatible endpoints, OpenRouter, a local "
            "server, or anything else exposing the OpenAI chat/completions "
            "API shape."
        )
        form.addRow("OpenAI-compatible base URL:", self.openai_base_edit)

        pulled_models = self._pulled_ollama_models(config)
        self.general_edit = _model_combo(config.model_for("general"), pulled_models)
        self.story_edit = _model_combo(config.model_for("story"), pulled_models)
        self.code_edit = _model_combo(config.model_for("code"), pulled_models)
        self.vision_edit = _model_combo(config.model_for("vision"), pulled_models)
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(500, 200_000)
        self.limit_spin.setValue(config.context_char_limit)

        self.history_limit_spin = QSpinBox()
        self.history_limit_spin.setRange(1000, 1_000_000)
        self.history_limit_spin.setValue(config.history_char_limit)
        self.history_limit_spin.setToolTip(
            "How much conversation HISTORY gets sent per turn - the oldest "
            "turns are dropped first once a session's transcript exceeds "
            "this, so a long-running conversation doesn't eventually "
            "overflow the model's real context window."
        )

        form.addRow("General model:", self.general_edit)
        form.addRow("Story model:", self.story_edit)
        form.addRow("Code model:", self.code_edit)
        form.addRow("Vision model:", self.vision_edit)
        form.addRow("Context char limit:", self.limit_spin)
        form.addRow("History char limit:", self.history_limit_spin)

        self.mic_combo = QComboBox()
        self.mic_combo.addItem("System default", None)
        for idx, name, is_default in voice_service.list_input_devices_detailed():
            label = f"[{idx}] {name}" + (" (default)" if is_default else "")
            self.mic_combo.addItem(label, idx)
        if config.mic_device is not None:
            found = self.mic_combo.findData(config.mic_device)
            if found >= 0:
                self.mic_combo.setCurrentIndex(found)
        self.mic_combo.setToolTip(
            "If the Voice tab says \"Didn't hear anything\" even while you're "
            "talking, your OS's default input device may not actually carry "
            "audio - a known issue on some laptops (Realtek Smart Sound "
            "Technology routing the real mic through a different endpoint). "
            "Try picking a specific device here, or run `myai mic-test "
            "--device N` first to check which one actually works."
        )
        form.addRow("Microphone:", self.mic_combo)

        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(list(WHISPER_MODEL_SIZES))
        self.whisper_combo.setCurrentText(config.whisper_model)
        self.whisper_combo.setToolTip(
            "Voice input model size (English-only). Bigger = more accurate, "
            "slower on CPU. Downloaded once, then cached offline."
        )
        form.addRow("Voice input model:", self.whisper_combo)
        layout.addLayout(form)

        layout.addWidget(QLabel("System prompt (per task):"))
        prompt_task_row = QHBoxLayout()
        prompt_task_row.addWidget(QLabel("Task:"))
        self.prompt_task_combo = QComboBox()
        self.prompt_task_combo.addItems(list(PROMPT_TASKS))
        prompt_task_row.addWidget(self.prompt_task_combo)
        reset_prompt_btn = QPushButton("Reset to default")
        reset_prompt_btn.clicked.connect(self._reset_current_prompt)
        prompt_task_row.addWidget(reset_prompt_btn)
        prompt_task_row.addStretch(1)
        layout.addLayout(prompt_task_row)

        self.prompt_edit = QPlainTextEdit()
        self.prompt_edit.setMaximumHeight(100)
        layout.addWidget(self.prompt_edit)

        # Staged per-task edits, not written into config.system_prompts
        # until _save() - lets the user flip between tasks without
        # losing what they typed for another one.
        self._prompt_texts = {
            task: config.system_prompts.get(task) or SYSTEM_PROMPTS[task]
            for task in PROMPT_TASKS
        }
        self._last_prompt_task = self.prompt_task_combo.currentText()
        self.prompt_edit.setPlainText(self._prompt_texts[self._last_prompt_task])
        self.prompt_task_combo.currentTextChanged.connect(self._on_prompt_task_changed)

        key_note = QLabel(
            "API keys aren't set here - point ANTHROPIC_API_KEY / "
            "OPENAI_API_KEY at your key as environment variables before "
            "launching. " + self._key_status()
        )
        key_note.setWordWrap(True)
        key_note.setStyleSheet("color: #8c8c8c;")
        layout.addWidget(key_note)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _on_prompt_task_changed(self, new_task: str) -> None:
        # currentTextChanged only reports the NEW value, so the task
        # being switched away FROM has to be tracked separately in
        # order to save whatever was just typed for it.
        self._prompt_texts[self._last_prompt_task] = self.prompt_edit.toPlainText()
        self._last_prompt_task = new_task
        self.prompt_edit.setPlainText(self._prompt_texts[new_task])

    def _reset_current_prompt(self) -> None:
        task = self.prompt_task_combo.currentText()
        self._prompt_texts[task] = SYSTEM_PROMPTS[task]
        self.prompt_edit.setPlainText(SYSTEM_PROMPTS[task])

    @staticmethod
    def _pulled_ollama_models(config: Config) -> list[str]:
        """Best-effort list of models Ollama already has pulled, so the
        model fields can be a pick-list instead of free text prone to
        typos. Ollama's own list_models() already swallows connection
        errors and returns [] rather than raising, so a stopped/missing
        Ollama server just means an empty pick-list, not a slow dialog."""
        from personalai.services.ollama_client import OllamaClient

        return OllamaClient(config.ollama_url).list_models()

    @staticmethod
    def _key_status() -> str:
        anthropic = "set" if os.environ.get("ANTHROPIC_API_KEY") else "not set"
        openai = "set" if os.environ.get("OPENAI_API_KEY") else "not set"
        return f"Currently: ANTHROPIC_API_KEY {anthropic}, OPENAI_API_KEY {openai}."

    def _save(self) -> None:
        c = self.config
        c.backend = self.backend_combo.currentText()
        c.ollama_url = self.url_edit.text().strip() or c.ollama_url
        c.openai_base_url = self.openai_base_edit.text().strip() or c.openai_base_url
        c.forge_url = self.forge_url_edit.text().strip() or c.forge_url
        c.models["general"] = self.general_edit.currentText().strip() or c.models["general"]
        c.models["story"] = self.story_edit.currentText().strip() or c.models["story"]
        c.models["code"] = self.code_edit.currentText().strip() or c.models["code"]
        c.models["vision"] = self.vision_edit.currentText().strip() or c.models["vision"]
        c.context_char_limit = self.limit_spin.value()
        c.history_char_limit = self.history_limit_spin.value()
        c.mic_device = self.mic_combo.currentData()
        c.whisper_model = self.whisper_combo.currentText()

        # Capture whatever's on screen right now for the currently-shown
        # task (the combo's currentTextChanged handler only captures a
        # task's text when you switch AWAY from it).
        self._prompt_texts[self.prompt_task_combo.currentText()] = self.prompt_edit.toPlainText()
        for task in PROMPT_TASKS:
            text = self._prompt_texts[task].strip()
            if text and text != SYSTEM_PROMPTS[task]:
                c.system_prompts[task] = text
            else:
                c.system_prompts.pop(task, None)

        self.store.save(c)
        self.accept()
