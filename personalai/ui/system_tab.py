"""System setup, model benchmark, and portability helpers."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from personalai.core.config import LOCAL_MODEL_PROFILES, ConfigStore
from personalai.core.logging_config import LOG_DIR, LOG_FILE
from personalai.core.version import app_version, build_date
from personalai.services import voice_service
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

        self.version_label = QLabel(f"Nexus {app_version()} | build {build_date()}")
        self.version_label.setObjectName("mutedLabel")
        layout.addWidget(self.version_label)

        self.hardware_label = QLabel()
        self.hardware_label.setObjectName("mutedLabel")
        self.hardware_label.setWordWrap(True)
        layout.addWidget(self.hardware_label)

        layout.addWidget(QLabel("Readiness"))
        self.checklist = QListWidget()
        self.checklist.setObjectName("toolResults")
        self.checklist.setMaximumHeight(170)
        layout.addWidget(self.checklist)

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
        repair_btn = QPushButton("Repair")
        repair_btn.clicked.connect(self._repair_setup)
        profile_row.addWidget(repair_btn)
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
        self.refresh_btn = QPushButton("Refresh checks")
        self.refresh_btn.clicked.connect(self.refresh_checklist)
        actions.addWidget(self.refresh_btn)
        self.ollama_btn = QPushButton("Install Ollama")
        self.ollama_btn.clicked.connect(self._open_ollama_download)
        actions.addWidget(self.ollama_btn)
        self.logs_btn = QPushButton("Open logs")
        self.logs_btn.clicked.connect(self._open_logs)
        actions.addWidget(self.logs_btn)
        self.diagnostics_btn = QPushButton("Copy diagnostics")
        self.diagnostics_btn.clicked.connect(self._copy_diagnostics)
        actions.addWidget(self.diagnostics_btn)
        actions.addStretch(1)
        layout.addLayout(actions)

        self.output = QPlainTextEdit()
        self.output.setObjectName("toolOutput")
        self.output.setReadOnly(True)
        self.output.setPlaceholderText("Benchmark and setup results appear here.")
        layout.addWidget(self.output, stretch=1)

        self._refresh_hardware()
        self.refresh_checklist()

    def _refresh_hardware(self) -> None:
        snapshot = detect_hardware()
        profile = LOCAL_MODEL_PROFILES[recommend_profile(snapshot)]["label"]
        self.hardware_label.setText("\n".join([*setup_summary(snapshot), f"Recommended: {profile}"]))

    def _apply_profile(self) -> None:
        self.chat_service.config.apply_local_profile(self.profile_combo.currentData())
        self.chat_service.config.setup_completed = True
        self.config_store.save(self.chat_service.config)
        self.output.setPlainText("Profile applied and saved.")
        self.refresh_checklist()

    def _open_setup(self) -> None:
        dialog = SetupWizard(self.chat_service.config, self.config_store, self)
        if dialog.exec() == dialog.DialogCode.Accepted:
            self.profile_combo.setCurrentIndex(
                max(0, self.profile_combo.findData(self.chat_service.config.local_model_profile))
            )
            self.output.setPlainText("Setup applied.")
            self.refresh_checklist()

    def refresh_checklist(self) -> None:
        config = self.chat_service.config
        checks = [
            ("Setup profile applied", config.setup_completed),
            ("Ollama backend selected", config.backend == "ollama"),
            ("Release GPU memory after replies", config.unload_models_after_reply),
            ("Voice packages available", voice_service.is_recording_available()
             and voice_service.is_transcription_available()),
            ("Knowledge indexed", bool(self.chat_service.knowledge_store
                                      and self.chat_service.knowledge_store.chunks)),
        ]
        installed = self._installed_ollama_models()
        recommended = [model for model in config.recommended_local_models() if model]
        if recommended:
            checks.append(("Recommended models installed", all(model in installed for model in recommended)))
            missing = [model for model in recommended if model not in installed]
            if missing:
                self.output.setPlainText(
                    "Missing recommended model(s):\n"
                    + "\n".join(f"- {model}" for model in missing)
                    + "\n\nUse Install recommended models to repair this."
                )
        self.checklist.clear()
        for label, ok in checks:
            self.checklist.addItem(f"{'PASS' if ok else 'TODO'}  {label}")

    def _installed_ollama_models(self) -> set[str]:
        if self.chat_service.config.backend != "ollama":
            return set()
        try:
            from personalai.services.ollama_client import OllamaClient

            return set(OllamaClient(self.chat_service.config.ollama_url).list_models())
        except (OSError, ValueError):
            return set()

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

    def _repair_setup(self) -> None:
        self.chat_service.config.apply_local_profile(self.profile_combo.currentData())
        self.chat_service.config.setup_completed = True
        self.config_store.save(self.chat_service.config)
        missing = self._missing_recommended_models()
        text = ["Selected profile applied and saved."]
        if missing:
            text.append("")
            text.append("Still missing model(s):")
            text.extend(f"- {model}" for model in missing)
            text.append("")
            text.append("Use Install recommended models to pull them through Ollama.")
        else:
            text.append("Recommended models are installed.")
        self.refresh_checklist()
        self.output.setPlainText("\n".join(text))

    def _missing_recommended_models(self) -> list[str]:
        installed = self._installed_ollama_models()
        return [
            model for model in self.chat_service.config.recommended_local_models()
            if model and model not in installed
        ]

    def _open_ollama_download(self) -> None:
        QDesktopServices.openUrl(QUrl("https://ollama.com/download"))

    def _open_logs(self) -> None:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        if not LOG_FILE.exists():
            LOG_FILE.write_text("", encoding="utf-8")
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(LOG_FILE)))

    def _copy_diagnostics(self) -> None:
        config = self.chat_service.config
        lines = [
            f"Nexus version: {app_version()}",
            f"Build date: {build_date()}",
            f"Backend: {config.backend}",
            f"Ollama URL: {config.ollama_url}",
            f"Profile: {config.local_model_profile}",
            f"GPU unload: {config.unload_models_after_reply}",
            f"Voice available: {voice_service.is_recording_available() and voice_service.is_transcription_available()}",
            f"Knowledge chunks: {len(self.chat_service.knowledge_store.chunks) if self.chat_service.knowledge_store else 0}",
            f"Missing models: {', '.join(self._missing_recommended_models()) or 'none'}",
            f"Log file: {LOG_FILE}",
        ]
        QApplication.clipboard().setText("\n".join(lines))
        self.output.setPlainText("Diagnostics copied to clipboard.")

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
        self.refresh_checklist()

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
