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
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from personalai.core.config import BACKEND_NAMES, Config, ConfigStore
from personalai.services.voice_service import WHISPER_MODEL_SIZES


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

        form.addRow("General model:", self.general_edit)
        form.addRow("Story model:", self.story_edit)
        form.addRow("Code model:", self.code_edit)
        form.addRow("Vision model:", self.vision_edit)
        form.addRow("Context char limit:", self.limit_spin)

        self.whisper_combo = QComboBox()
        self.whisper_combo.addItems(list(WHISPER_MODEL_SIZES))
        self.whisper_combo.setCurrentText(config.whisper_model)
        self.whisper_combo.setToolTip(
            "Voice input model size (English-only). Bigger = more accurate, "
            "slower on CPU. Downloaded once, then cached offline."
        )
        form.addRow("Voice input model:", self.whisper_combo)
        layout.addLayout(form)

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
        c.models["general"] = self.general_edit.currentText().strip() or c.models["general"]
        c.models["story"] = self.story_edit.currentText().strip() or c.models["story"]
        c.models["code"] = self.code_edit.currentText().strip() or c.models["code"]
        c.models["vision"] = self.vision_edit.currentText().strip() or c.models["vision"]
        c.context_char_limit = self.limit_spin.value()
        c.whisper_model = self.whisper_combo.currentText()
        self.store.save(c)
        self.accept()
