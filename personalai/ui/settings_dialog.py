"""Settings dialog: the same knobs as `myai config`, edited from the GUI."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
)

from personalai.core.config import Config, ConfigStore


class SettingsDialog(QDialog):
    def __init__(self, config: Config, store: ConfigStore, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.store = store
        self.setWindowTitle("Settings")

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.url_edit = QLineEdit(config.ollama_url)
        self.general_edit = QLineEdit(config.model_for("general"))
        self.story_edit = QLineEdit(config.model_for("story"))
        self.code_edit = QLineEdit(config.model_for("code"))
        self.vision_edit = QLineEdit(config.model_for("vision"))
        self.limit_spin = QSpinBox()
        self.limit_spin.setRange(500, 200_000)
        self.limit_spin.setValue(config.context_char_limit)

        form.addRow("Ollama URL:", self.url_edit)
        form.addRow("General model:", self.general_edit)
        form.addRow("Story model:", self.story_edit)
        form.addRow("Code model:", self.code_edit)
        form.addRow("Vision model:", self.vision_edit)
        form.addRow("Context char limit:", self.limit_spin)
        layout.addLayout(form)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _save(self) -> None:
        c = self.config
        c.ollama_url = self.url_edit.text().strip() or c.ollama_url
        c.models["general"] = self.general_edit.text().strip() or c.models["general"]
        c.models["story"] = self.story_edit.text().strip() or c.models["story"]
        c.models["code"] = self.code_edit.text().strip() or c.models["code"]
        c.models["vision"] = self.vision_edit.text().strip() or c.models["vision"]
        c.context_char_limit = self.limit_spin.value()
        self.store.save(c)
        self.accept()
