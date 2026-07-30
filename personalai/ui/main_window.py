"""Main window: two tabs (Chat, Caption Image) over the same
ChatService/ConversationStore the CLI uses - a session started with
`myai story` is visible here too, and vice versa.

Meant to be a dependable everyday app, not just a thin CLI wrapper:
window size/position is remembered across restarts, and closing the
window (the X button) minimizes to the system tray instead of quitting,
so PersonalAI can just stay running and accessible - the terminal
remains the tool of choice for one-shot/automated use, not for the
day-to-day conversation.
"""

from __future__ import annotations

import base64
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QAction, QIcon
from PySide6.QtWidgets import (
    QDialog,
    QLabel,
    QMainWindow,
    QMenu,
    QMessageBox,
    QSystemTrayIcon,
    QTabWidget,
)

from personalai import __version__
from personalai.core.config import ConfigStore
from personalai.services.backend_factory import build_llm_client
from personalai.services.chat_service import ChatService
from personalai.ui.caption_tab import CaptionTab
from personalai.ui.chat_tab import ChatTab
from personalai.ui.settings_dialog import SettingsDialog
from personalai.ui.workers import TaskRunner

HEALTH_INTERVAL_MS = 30_000
ICON_PATH = Path(__file__).parent / "icon.ico"


class MainWindow(QMainWindow):
    def __init__(self, chat_service: ChatService, config_store: ConfigStore) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.config_store = config_store
        self.task_runner = TaskRunner(self)

        self.setWindowTitle("PersonalAI")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1000, 700)
        self._restore_geometry()

        self.tabs = QTabWidget()
        self.setCentralWidget(self.tabs)
        self.tabs.addTab(ChatTab(chat_service, self.task_runner, config_store), "Chat")
        self.tabs.addTab(CaptionTab(chat_service, self.task_runner), "Caption Image")

        self._build_menu()

        self.status_label = QLabel(f"{chat_service.config.backend}: checking…")
        self.statusBar().addPermanentWidget(self.status_label)
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(HEALTH_INTERVAL_MS)
        self._health_timer.timeout.connect(self._check_health)
        self._health_timer.start()
        self._check_health()

        self.tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._build_tray()

    # ---- window geometry (remembered across restarts) ----

    def _restore_geometry(self) -> None:
        b64 = self.chat_service.config.window_geometry
        if not b64:
            return
        try:
            self.restoreGeometry(base64.b64decode(b64))
        except (ValueError, TypeError):
            pass  # corrupted/old value - just keep the default size

    def _save_geometry(self) -> None:
        raw = bytes(self.saveGeometry())
        self.chat_service.config.window_geometry = base64.b64encode(raw).decode("ascii")
        self.config_store.save(self.chat_service.config)

    # ---- menu ----

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&File")
        settings_action = QAction("&Settings…", self)
        settings_action.triggered.connect(self._open_settings)
        file_menu.addAction(settings_action)
        file_menu.addSeparator()
        exit_action = QAction("E&xit", self)
        exit_action.triggered.connect(self._quit)
        file_menu.addAction(exit_action)

        help_menu = self.menuBar().addMenu("&Help")
        about_action = QAction("&About PersonalAI", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _show_about(self) -> None:
        QMessageBox.information(
            self, "About PersonalAI",
            f"PersonalAI {__version__}\n\n"
            "A local, offline AI assistant for chat, story writing, coding "
            "help, and image captioning - backed by Ollama, Claude, or any "
            "OpenAI-compatible API.",
        )

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.chat_service.config, self.config_store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Config is mutated in place by the dialog, but the ChatService's
            # client object was already built from the OLD settings - rebuild
            # it so a backend switch (or a new URL/base_url) takes effect
            # immediately instead of needing an app restart.
            self.chat_service.client = build_llm_client(self.chat_service.config)
            self._check_health()

    def _check_health(self) -> None:
        self.task_runner.submit(self.chat_service.client.is_available,
                                on_result=self._show_health)

    def _show_health(self, online: bool) -> None:
        backend = self.chat_service.config.backend
        if online:
            self.status_label.setText(f"{backend}: ● online")
            self.status_label.setStyleSheet("color: #4ec94e;")
        else:
            self.status_label.setText(f"{backend}: ● offline")
            self.status_label.setStyleSheet("color: #8c8c8c;")

    # ---- system tray ----

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        if ICON_PATH.exists():
            self.tray.setIcon(QIcon(str(ICON_PATH)))
        self.tray.setToolTip("PersonalAI")

        menu = QMenu()
        show_action = menu.addAction("Show PersonalAI")
        show_action.triggered.connect(self._show_and_raise)
        menu.addSeparator()
        quit_action = menu.addAction("Quit")
        quit_action.triggered.connect(self._quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()

    def _show_and_raise(self) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def _on_tray_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            if self.isVisible():
                self.hide()
            else:
                self._show_and_raise()

    def _quit(self) -> None:
        from PySide6.QtWidgets import QApplication
        self._save_geometry()
        app = QApplication.instance()
        if app is not None:
            app.quit()

    def closeEvent(self, event) -> None:
        self._save_geometry()
        if self.tray is not None:
            event.ignore()
            self.hide()
            self.tray.showMessage(
                "PersonalAI", "Still running in the tray - right-click the "
                "icon to quit.", QSystemTrayIcon.MessageIcon.Information, 2000,
            )
        else:
            event.accept()
