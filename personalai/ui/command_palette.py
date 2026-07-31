"""Ctrl+K command palette for quick Nexus actions."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)


@dataclass(frozen=True)
class PaletteAction:
    title: str
    detail: str
    callback: Callable[[], None]


class CommandPalette(QDialog):
    def __init__(self, actions: list[PaletteAction], parent=None) -> None:
        super().__init__(parent)
        self.actions = actions
        self.setWindowTitle("Command palette")
        self.setObjectName("commandPalette")
        self.setModal(True)
        self.resize(520, 420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search commands")
        self.search.textChanged.connect(self._filter)
        layout.addWidget(self.search)

        self.list_widget = QListWidget()
        self.list_widget.itemActivated.connect(self._activate)
        layout.addWidget(self.list_widget, stretch=1)
        self._filter("")

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.search.setFocus(Qt.FocusReason.PopupFocusReason)
        self.search.selectAll()

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            item = self.list_widget.currentItem()
            if item is not None:
                self._activate(item)
                return
        super().keyPressEvent(event)

    def _filter(self, query: str) -> None:
        words = query.casefold().split()
        self.list_widget.clear()
        for index, action in enumerate(self.actions):
            haystack = f"{action.title} {action.detail}".casefold()
            if all(word in haystack for word in words):
                item = QListWidgetItem(f"{action.title}\n{action.detail}")
                item.setData(Qt.ItemDataRole.UserRole, index)
                self.list_widget.addItem(item)
        if self.list_widget.count():
            self.list_widget.setCurrentRow(0)

    def _activate(self, item: QListWidgetItem) -> None:
        index = item.data(Qt.ItemDataRole.UserRole)
        self.accept()
        self.actions[index].callback()
