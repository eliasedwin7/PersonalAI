"""Main window: five tabs (Chat, Voice, Caption Image, Agent, Image)
over the same ChatService/ConversationStore the CLI uses - a session
started with `myai story` is visible here too, and vice versa.

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
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QTabBar,
    QVBoxLayout,
    QWidget,
)

from personalai.core.config import ConfigStore
from personalai.services.backend_factory import build_llm_client
from personalai.services.chat_service import ChatService
from personalai.services.image_service import build_forge_client
from personalai.ui.agent_tab import AgentTab
from personalai.ui.chat_tab import ChatTab
from personalai.ui.images_page import ImagesPage
from personalai.ui.settings_dialog import SettingsDialog
from personalai.ui.voice_tab import VoiceTab
from personalai.ui.workers import TaskRunner

HEALTH_INTERVAL_MS = 30_000
ICON_PATH = Path(__file__).parent / "icon.ico"


class MainWindow(QMainWindow):
    def __init__(self, chat_service: ChatService, config_store: ConfigStore) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.config_store = config_store
        self.task_runner = TaskRunner(self)

        self.setWindowTitle("Nexus")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1000, 700)
        self._restore_geometry()

        self._build_workspace()

        self.status_label = QLabel(f"{chat_service.config.backend}: checking…")
        self.statusBar().addPermanentWidget(self.status_label)
        self.statusBar().hide()
        self._health_timer = QTimer(self)
        self._health_timer.setInterval(HEALTH_INTERVAL_MS)
        self._health_timer.timeout.connect(self._check_health)
        self._health_timer.start()
        self._check_health()

        self.tray: QSystemTrayIcon | None = None
        if QSystemTrayIcon.isSystemTrayAvailable():
            self._build_tray()

    def _build_workspace(self) -> None:
        shell = QWidget()
        shell.setObjectName("workspaceShell")
        shell_layout = QVBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        app_bar = QWidget()
        app_bar.setObjectName("appBar")
        app_bar_layout = QHBoxLayout(app_bar)
        app_bar_layout.setContentsMargins(18, 8, 18, 8)
        app_bar_layout.setSpacing(14)
        brand = QLabel("Nexus")
        brand.setObjectName("brand")
        app_bar_layout.addWidget(brand)
        self.navigation = QTabBar()
        self.navigation.setObjectName("navigation")
        for label in ("Chat", "Voice", "Images", "Agent"):
            self.navigation.addTab(label)
        self.navigation.currentChanged.connect(self._select_page)
        app_bar_layout.addWidget(self.navigation)
        app_bar_layout.addStretch(1)
        self.connection_label = QLabel("Checking connection")
        self.connection_label.setObjectName("connectionStatus")
        app_bar_layout.addWidget(self.connection_label)
        settings_button = QPushButton("Settings")
        settings_button.clicked.connect(self._open_settings)
        app_bar_layout.addWidget(settings_button)
        shell_layout.addWidget(app_bar)

        self.pages = QStackedWidget()
        self.chat_tab = ChatTab(self.chat_service, self.task_runner)
        self.voice_tab = VoiceTab(self.chat_service, self.task_runner, self.config_store)
        self.images_page = ImagesPage(self.chat_service, self.task_runner)
        self.caption_tab = self.images_page.caption_tab
        self.image_tab = self.images_page.image_tab
        self.agent_tab = AgentTab(self.chat_service, self.task_runner, self.config_store)
        for page in (self.chat_tab, self.voice_tab, self.images_page, self.agent_tab):
            self.pages.addWidget(page)
        shell_layout.addWidget(self.pages, stretch=1)
        self.setCentralWidget(shell)
        self.navigation.setCurrentIndex(0)

    def _select_page(self, index: int) -> None:
        if index < 0:
            return
        self.pages.setCurrentIndex(index)

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

    def _open_settings(self) -> None:
        dialog = SettingsDialog(self.chat_service.config, self.config_store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Config is mutated in place by the dialog, but the ChatService's
            # client object was already built from the OLD settings - rebuild
            # it so a backend switch (or a new URL/base_url) takes effect
            # immediately instead of needing an app restart.
            self.chat_service.client = build_llm_client(self.chat_service.config)
            self.chat_tab._update_model_label()
            self.voice_tab._refresh_microphones()
            self._check_health()
            # ImageTab keeps its own ForgeClient (independent of the
            # chat backend) - rebuild it too so a changed Forge URL
            # takes effect immediately, same reasoning as the line above.
            self.image_tab.client = build_forge_client(self.chat_service.config)
            self.image_tab._check_health()

    def _check_health(self) -> None:
        self.task_runner.submit(self.chat_service.client.is_available,
                                on_result=self._show_health)

    def _show_health(self, online: bool) -> None:
        backend = self.chat_service.config.backend
        if online:
            self.status_label.setText(f"{backend}: ● online")
            self.status_label.setStyleSheet("color: #4ec94e;")
            self.connection_label.setText(f"{backend}: online")
            self.connection_label.setProperty("online", True)
        else:
            self.status_label.setText(f"{backend}: ● offline")
            self.status_label.setStyleSheet("color: #8c8c8c;")
            self.connection_label.setText(f"{backend}: offline")
            self.connection_label.setProperty("online", False)
        self.connection_label.style().unpolish(self.connection_label)
        self.connection_label.style().polish(self.connection_label)

    # ---- system tray ----

    def _build_tray(self) -> None:
        self.tray = QSystemTrayIcon(self)
        if ICON_PATH.exists():
            self.tray.setIcon(QIcon(str(ICON_PATH)))
        self.tray.setToolTip("Nexus")

        menu = QMenu()
        show_action = menu.addAction("Show Nexus")
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
                "Nexus", "Still running in the tray - right-click the "
                "icon to quit.", QSystemTrayIcon.MessageIcon.Information, 2000,
            )
        else:
            event.accept()
