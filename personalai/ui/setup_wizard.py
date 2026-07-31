"""First-run Nexus setup dialog."""

from __future__ import annotations

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from personalai.core.config import LOCAL_MODEL_PROFILES, Config, ConfigStore
from personalai.services.setup_service import detect_hardware, recommend_profile, setup_summary


class SetupWizard(QDialog):
    def __init__(self, config: Config, store: ConfigStore, parent=None) -> None:
        super().__init__(parent)
        self.config = config
        self.store = store
        self.snapshot = detect_hardware()
        self.setWindowTitle("Set up Nexus")
        self.setMinimumWidth(520)

        layout = QVBoxLayout(self)
        title = QLabel("Nexus setup")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        details = QLabel("\n".join(setup_summary(self.snapshot)))
        details.setObjectName("mutedLabel")
        details.setWordWrap(True)
        layout.addWidget(details)

        layout.addWidget(QLabel("Hardware profile"))
        self.profile_combo = QComboBox()
        recommended = recommend_profile(self.snapshot)
        for key, profile in LOCAL_MODEL_PROFILES.items():
            label = profile["label"]
            if key == recommended:
                label += " (recommended)"
            self.profile_combo.addItem(label, key)
        self.profile_combo.setCurrentIndex(max(0, self.profile_combo.findData(recommended)))
        layout.addWidget(self.profile_combo)

        self.hotkey_check = QCheckBox("Enable Ctrl+Alt+N to open Nexus")
        self.hotkey_check.setChecked(config.global_hotkey_enabled)
        layout.addWidget(self.hotkey_check)

        note = QLabel(
            "This applies safe defaults. Model downloads are managed from System or Settings."
        )
        note.setWordWrap(True)
        note.setObjectName("mutedLabel")
        layout.addWidget(note)

        buttons = QDialogButtonBox()
        apply_btn = QPushButton("Apply setup")
        apply_btn.setObjectName("primaryButton")
        buttons.addButton(apply_btn, QDialogButtonBox.ButtonRole.AcceptRole)
        skip_btn = QPushButton("Skip")
        buttons.addButton(skip_btn, QDialogButtonBox.ButtonRole.RejectRole)
        buttons.accepted.connect(self._apply)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _apply(self) -> None:
        self.config.apply_local_profile(self.profile_combo.currentData())
        self.config.global_hotkey_enabled = self.hotkey_check.isChecked()
        self.config.setup_completed = True
        self.store.save(self.config)
        self.accept()
