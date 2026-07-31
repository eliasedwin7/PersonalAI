"""Knowledge workspace: index local folders once and retrieve them in Chat."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from personalai.core.config import ConfigStore
from personalai.core.errors import PersonalAIError
from personalai.services.chat_service import ChatService
from personalai.services.knowledge_service import KnowledgeStore
from personalai.services.ollama_client import OllamaClient
from personalai.ui.workers import TaskRunner


class KnowledgeTab(QWidget):
    def __init__(self, chat_service: ChatService, task_runner: TaskRunner,
                 config_store: ConfigStore) -> None:
        super().__init__()
        self.chat_service = chat_service
        self.task_runner = task_runner
        self.config_store = config_store
        if chat_service.knowledge_store is None:
            chat_service.knowledge_store = KnowledgeStore()
        self.store = chat_service.knowledge_store

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 18, 24, 18)
        layout.setSpacing(12)
        title = QLabel("Knowledge")
        title.setObjectName("pageTitle")
        layout.addWidget(title)
        note = QLabel("Index local folders once. Nexus retrieves relevant passages automatically in Chat, without uploading your files.")
        note.setObjectName("mutedLabel")
        note.setWordWrap(True)
        layout.addWidget(note)

        folder_row = QHBoxLayout()
        self.folder_edit = QLineEdit()
        self.folder_edit.setPlaceholderText("Folder to make available to Nexus")
        folder_row.addWidget(self.folder_edit, stretch=1)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse)
        folder_row.addWidget(browse_btn)
        self.index_btn = QPushButton("Index folder")
        self.index_btn.setObjectName("primaryButton")
        self.index_btn.clicked.connect(self._index)
        folder_row.addWidget(self.index_btn)
        layout.addLayout(folder_row)

        search_row = QHBoxLayout()
        self.query_edit = QLineEdit()
        self.query_edit.setPlaceholderText("Preview what Nexus will retrieve")
        self.query_edit.returnPressed.connect(self._search)
        search_row.addWidget(self.query_edit, stretch=1)
        search_btn = QPushButton("Search")
        search_btn.clicked.connect(self._search)
        search_row.addWidget(search_btn)
        self.clear_btn = QPushButton("Clear index")
        self.clear_btn.clicked.connect(self._clear)
        search_row.addWidget(self.clear_btn)
        layout.addLayout(search_row)

        self.status = QLabel()
        self.status.setObjectName("mutedLabel")
        layout.addWidget(self.status)
        self.results = QListWidget()
        layout.addWidget(self.results, stretch=1)
        self._show_sources()

    def _browse(self) -> None:
        folder = QFileDialog.getExistingDirectory(self, "Choose knowledge folder")
        if folder:
            self.folder_edit.setText(folder)

    def _embed(self, texts: list[str]) -> list[list[float]]:
        if not isinstance(self.chat_service.client, OllamaClient):
            raise PersonalAIError("Embeddings require the local Ollama backend.")
        return self.chat_service.client.embed(texts, self.chat_service.config.embedding_model)

    def _index(self) -> None:
        folder = Path(self.folder_edit.text().strip()).expanduser()
        if not folder.is_dir():
            self.status.setText("Choose an existing folder first.")
            return
        self.index_btn.setEnabled(False)
        self.status.setText("Indexing local files...")
        embed = self._embed if isinstance(self.chat_service.client, OllamaClient) else None
        self.task_runner.submit(
            self.store.index_folder, folder, embed,
            on_result=self._indexed,
            on_error=self._index_error,
        )

    def _indexed(self, count: int) -> None:
        self.index_btn.setEnabled(True)
        self.status.setText(f"Indexed {count} passage(s).")
        self._show_sources()

    def _index_error(self, exc: BaseException) -> None:
        self.index_btn.setEnabled(True)
        self.status.setText(f"Indexing failed: {exc}")

    def _search(self) -> None:
        query = self.query_edit.text().strip()
        if not query:
            self._show_sources()
            return
        embed = self._embed if isinstance(self.chat_service.client, OllamaClient) else None
        try:
            matches = self.store.search(query, embed_query=embed)
        except PersonalAIError:
            matches = self.store.search(query)
        self.results.clear()
        for chunk in matches:
            self.results.addItem(f"{Path(chunk.source).name}\n{chunk.text[:220]}")
        self.status.setText(f"{len(matches)} relevant passage(s).")

    def _clear(self) -> None:
        self.store.clear()
        self.status.setText("Knowledge index cleared.")
        self._show_sources()

    def _show_sources(self) -> None:
        self.results.clear()
        sources = sorted({chunk.source for chunk in self.store.chunks})
        for source in sources:
            self.results.addItem(source)
        self.status.setText(f"{len(self.store.chunks)} indexed passage(s) from {len(sources)} file(s).")
