"""Main window: two tabs (Chat, Caption Image) over the same
ChatService/ConversationStore the CLI uses - a session started with
`myai story` is visible here too, and vice versa.
"""

from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import QLabel, QMainWindow, QTabWidget

from personalai.core.config import ConfigStore
from personalai.services.chat_service import ChatService
from personalai.ui.caption_tab import CaptionTab
from personalai.ui.chat_tab import ChatTab
from personalai.ui.settings_dialog import SettingsDialog
from personalai.ui.workers import TaskRunner

HEALTH_INTERVAL_MS = 30_000


class MainWindow(QMainWindow):
    def __init__(self, chat_service: ChatService, config_store: ConfigStore) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.config_store = config_store
        self.task_runner = TaskRunner(self)

        self.setWindowTitle("PersonalAI")
        self.resize(1000, 700)

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(ChatTab(chat_service, self.task_runner), "Chat")
        self.tabs.addTab(CaptionTab(chat_service, self.task_runner), "Caption Image")

        self._build_menu()

        self.status_label = QLabel("Ollama: checking…")
        self.statusBar().addPermanentWidget(self.status_label)
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(HEALTH_INTERVAL_MS)
        self._health_timer.timeout.connect(self._check_health)
        self._health_timer.start()
        self._check_health()

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        settings_action = QAction("&Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.chat_service.config, self.config_store, self)
        dialog.exec()

    def _check_health(self) -> None:
        self.task_runner.submit(self.chat_service.client.is_available,
                                on_result=self._show_health)

    def _show_health(self, online: bool) -> None:
        if online:
            self.status_label.setText("Ollama: ● online")
            self.status_label.setStyleSheet("color: #4ec94e;")
        else:
            self.status_label.setText("Ollama: ● offline")
            self.status_label.setStyleSheet("color: #8c8c8c;")
