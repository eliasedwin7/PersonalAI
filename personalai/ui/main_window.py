"""Main window: five tabs (Chat, Voice, Caption Image, Agent, Image)
over the same ChatService/ConversationStore the CLI uses - a session
started with `myai story` is visible here too, and vice versa.

Meant to be a dependable everyday app, not just a thin CLI wrapper:
window size/position is remembered across restarts, minimizing the
window moves it to the system tray, and closing it exits cleanly.
"""

from __future__ import annotations

import base64
import os
from pathlib import Path

from PySide6.QtCore import QEvent, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
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
from personalai.ui.knowledge_tab import KnowledgeTab
from personalai.ui.settings_dialog import SettingsDialog
from personalai.ui.setup_wizard import SetupWizard
from personalai.ui.system_tab import SystemTab
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
        self.hotkey_manager = None

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
        if (
            not self.chat_service.config.setup_completed
            and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        ):
            QTimer.singleShot(350, self._maybe_show_setup)

    def _build_workspace(self) -> None:
        shell = QWidget()
        shell.setObjectName("workspaceShell")
        shell_layout = QHBoxLayout(shell)
        shell_layout.setContentsMargins(0, 0, 0, 0)
        shell_layout.setSpacing(0)

        side_bar = QWidget()
        side_bar.setObjectName("sideBar")
        side_bar.setFixedWidth(224)
        side_layout = QVBoxLayout(side_bar)
        side_layout.setContentsMargins(14, 16, 14, 14)
        side_layout.setSpacing(12)
        brand = QLabel("Nexus")
        brand.setObjectName("brand")
        side_layout.addWidget(brand)
        subtitle = QLabel("Local AI workbench")
        subtitle.setObjectName("sideSubtitle")
        side_layout.addWidget(subtitle)

        self.navigation = QListWidget()
        self.navigation.setObjectName("navigationList")
        self._page_labels = ("Chat", "Voice", "Knowledge", "Images", "Agent", "System")
        for label in self._page_labels:
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, label)
            self.navigation.addItem(item)
        self.navigation.currentRowChanged.connect(self._select_page)
        side_layout.addWidget(self.navigation, stretch=1)

        self.connection_label = QLabel("Checking connection")
        self.connection_label.setObjectName("connectionStatus")
        side_layout.addWidget(self.connection_label)
        settings_button = QPushButton("Settings")
        settings_button.setObjectName("sideButton")
        settings_button.clicked.connect(self._open_settings)
        side_layout.addWidget(settings_button)
        shell_layout.addWidget(side_bar)

        self.pages = QStackedWidget()
        self.pages.setObjectName("pageStack")
        self.chat_tab = ChatTab(self.chat_service, self.task_runner, self.config_store)
        self.voice_tab = VoiceTab(self.chat_service, self.task_runner, self.config_store)
        self.voice_tab.command_requested.connect(self._handle_app_command)
        self.knowledge_tab = KnowledgeTab(self.chat_service, self.task_runner, self.config_store)
        self.images_page = ImagesPage(self.chat_service, self.task_runner)
        self.caption_tab = self.images_page.caption_tab
        self.image_tab = self.images_page.image_tab
        self.agent_tab = AgentTab(self.chat_service, self.task_runner, self.config_store)
        self.system_tab = SystemTab(self.chat_service, self.task_runner, self.config_store)
        for page in (
            self.chat_tab, self.voice_tab, self.knowledge_tab, self.images_page,
            self.agent_tab, self.system_tab,
        ):
            self.pages.addWidget(page)
        shell_layout.addWidget(self.pages, stretch=1)
        self.setCentralWidget(shell)
        self.navigation.setCurrentRow(0)

    def _select_page(self, index: int) -> None:
        if index < 0:
            return
        self.pages.setCurrentIndex(index)

    def select_page(self, label: str) -> bool:
        for index, page_label in enumerate(self._page_labels):
            if page_label.casefold() == label.casefold():
                self.navigation.setCurrentRow(index)
                return True
        return False

    def current_page_label(self) -> str:
        index = self.pages.currentIndex()
        if 0 <= index < len(self._page_labels):
            return self._page_labels[index]
        return ""

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
        dialog = SettingsDialog(
            self.chat_service.config, self.config_store, self, self.task_runner
        )
        if dialog.exec() == QDialog.DialogCode.Accepted:
            # Config is mutated in place by the dialog, but the ChatService's
            # client object was already built from the OLD settings - rebuild
            # it so a backend switch (or a new URL/base_url) takes effect
            # immediately instead of needing an app restart.
            self.chat_service.client = build_llm_client(self.chat_service.config)
            self.chat_tab._update_model_label()
            self._check_health()
            # ImageTab keeps its own ForgeClient (independent of the
            # chat backend) - rebuild it too so a changed Forge URL
            # takes effect immediately, same reasoning as the line above.
            self.image_tab.client = build_forge_client(self.chat_service.config)
            self.image_tab._check_health()
            if self.hotkey_manager is not None:
                self.hotkey_manager.configure(self.chat_service.config.global_hotkey_enabled)

    def _maybe_show_setup(self) -> None:
        dialog = SetupWizard(self.chat_service.config, self.config_store, self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            if self.hotkey_manager is not None:
                self.hotkey_manager.configure(self.chat_service.config.global_hotkey_enabled)
            self.chat_tab._update_model_label()
            self.system_tab._refresh_hardware()

    def _handle_app_command(self, command) -> None:
        if command.action == "select_page":
            self.select_page(command.target)
        elif command.action == "open_settings":
            self._open_settings()
        elif command.action == "new_chat":
            self.select_page("Chat")
            self.chat_tab.start_quick_session()
        elif command.action == "test_microphone":
            self.select_page("Voice")
            self.voice_tab._test_microphone()
        self.voice_tab.show_command_response(command.response)

    def set_hotkey_manager(self, manager) -> None:
        self.hotkey_manager = manager

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

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and self.isMinimized()
            and self.tray is not None
        ):
            # Queue this until Qt has completed the minimize transition.
            # Hiding keeps Nexus accessible from the tray without a taskbar
            # entry, while preserving a normal close button for exit.
            QTimer.singleShot(0, self.hide)

    def closeEvent(self, event) -> None:
        self._save_geometry()
        event.accept()
