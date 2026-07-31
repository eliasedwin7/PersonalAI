"""System setup, model benchmark, and portability helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from personalai.core.config import LOCAL_MODEL_PROFILES, ConfigStore
from personalai.services.benchmark_service import benchmark_models, format_benchmark_report
from personalai.services.chat_service import ChatService
from personalai.services.setup_service import detect_hardware, recommend_profile, setup_summary
from personalai.ui.setup_wizard import SetupWizard
from personalai.ui.workers import TaskRunner


class SystemTab(QWidget):
    def __init__(self, chat_service: ChatService, task_runner: TaskRunner,
                 config_store: ConfigStore) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.task_runner = task_runner
        self.config_store = config_store
        self._benchmarking = False

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)

        title = QLabel("System")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.hardware_label = QLabel()
        self.hardware_label.setObjectName("mutedLabel")
        self.hardware_label.setWordWrap(True)
        layout.addWidget(self.hardware_label)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Local profile:"))
        self.profile_combo = QComboBox()
        for key, profile in LOCAL_MODEL_PROFILES.items():
            self.profile_combo.addItem(profile["label"], key)
        self.profile_combo.setCurrentIndex(
            max(0, self.profile_combo.findData(chat_service.config.local_model_profile))
        )
        profile_row.addWidget(self.profile_combo, stretch=1)
        apply_profile_btn = QPushButton("Apply")
        apply_profile_btn.clicked.connect(self._apply_profile)
        profile_row.addWidget(apply_profile_btn)
        setup_btn = QPushButton("Setup")
        setup_btn.clicked.connect(self._open_setup)
        profile_row.addWidget(setup_btn)
        layout.addLayout(profile_row)

        actions = QHBoxLayout()
        self.install_btn = QPushButton("Install recommended models")
        self.install_btn.setObjectName("primaryButton")
        self.install_btn.clicked.connect(self._install_recommended)
        actions.addWidget(self.install_btn)
        self.benchmark_btn = QPushButton("Run benchmark")
        self.benchmark_btn.clicked.connect(self._run_benchmark)
        actions.addWidget(self.benchmark_btn)
        self.portable_btn = QPushButton("Portable bundle folder")
        self.portable_btn.clicked.connect(self._show_portable_folder)
        actions.addWidget(self.portable_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.output = QPlainTextEdit()
        self.output.setObjectName("toolOutput")
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Benchmark and setup results appear here.")
        layout.addWidget(self.output, stretch=1)

        self._refresh_hardware()

    def _refresh_hardware(self) -> None:
        snapshot = detect_hardware()
        profile = LOCAL_MODEL_PROFILES[recommend_profile(snapshot)]["label"]
        self.hardware_label.setText("\n".join([*setup_summary(snapshot), f"Recommended: {profile}"]))

    def _apply_profile(self) -> None:
        self.chat_service.config.apply_local_profile(self.profile_combo.currentData())
        self.chat_service.config.setup_completed = True
        self.config_store.save(self.chat_service.config)
        self.output.setPlainText("Profile applied and saved.")

    def _open_setup(self) -> None:
        dialog = SetupWizard(self.chat_service.config, self.config_store, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.profile_combo.setCurrentIndex(
                max(0, self.profile_combo.findData(self.chat_service.config.local_model_profile))
            )
            self.output.setPlainText("Setup applied.")

    def _run_benchmark(self) -> None:
        if self._benchmarking:
            return
        self._benchmarking = True
        self.benchmark_btn.setEnabled(False)
        self.output.setPlainText("Benchmarking local models...")
        self.task_runner.submit(
            benchmark_models, self.chat_service.config, self.chat_service.client,
            on_result=self._show_benchmark,
            on_error=self._benchmark_error,
        )

    def _show_benchmark(self, results) -> None:
        self._benchmarking = False
        self.benchmark_btn.setEnabled(True)
        self.output.setPlainText(format_benchmark_report(results))

    def _benchmark_error(self, exc: BaseException) -> None:
        self._benchmarking = False
        self.benchmark_btn.setEnabled(True)
        self.output.setPlainText(f"Benchmark failed: {exc}")

    def _install_recommended(self) -> None:
        models = self.chat_service.config.recommended_local_models()
        if not models:
            return
        from personalai.services.ollama_client import OllamaClient

        client = OllamaClient(
            self.chat_service.config.ollama_url,
            self.chat_service.config.unload_models_after_reply,
        )
        self.install_btn.setEnabled(False)
        self.output.setPlainText("Installing recommended Ollama models...")
        self.task_runner.submit(
            self._pull_models, client, models,
            on_result=lambda _r: self._install_done(),
            on_error=self._install_error,
        )

    @staticmethod
    def _pull_models(client, models: list[str]) -> None:
        for model in models:
            client.pull_model(model)

    def _install_done(self) -> None:
        self.install_btn.setEnabled(True)
        self.output.setPlainText("Recommended models installed.")

    def _install_error(self, exc: BaseException) -> None:
        self.install_btn.setEnabled(True)
        QMessageBox.warning(self, "Install models", str(exc))

    def _show_portable_folder(self) -> None:
        folder = Path.cwd() / "dist" / "Nexus"
        QFileDialog.getExistingDirectory(
            self,
            "Nexus portable bundle folder",
            str(folder if folder.exists() else Path.cwd()),
            QFileDialog.Option.ShowDirsOnly,
        )
