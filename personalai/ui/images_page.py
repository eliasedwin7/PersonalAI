"""A single home for image understanding and image generation."""

from __future__ import annotations

from PySide6.QtWidgets import QLabel, QTabWidget, QVBoxLayout, QWidget

from personalai.services.chat_service import ChatService
from personalai.ui.caption_tab import CaptionTab
from personalai.ui.image_tab import ImageTab
from personalai.ui.workers import TaskRunner


class ImagesPage(QWidget):
    """Keeps the two image workflows together without hiding either capability."""

    def __init__(self, chat_service: ChatService, task_runner: TaskRunner) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        title = QLabel("Images")
        title.setObjectName("pageTitle")
        layout.addWidget(title)

        self.tabs = QTabWidget()
        self.caption_tab = CaptionTab(chat_service, task_runner)
        self.image_tab = ImageTab(chat_service, task_runner)
        self.tabs.addTab(self.caption_tab, "Describe")
        self.tabs.addTab(self.image_tab, "Generate")
        layout.addWidget(self.tabs, stretch=1)
