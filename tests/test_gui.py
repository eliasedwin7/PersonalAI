"""GUI tests via pytest-qt. Run offscreen (QT_QPA_PLATFORM set below)
against real ChatService/ConversationStore + a fake OllamaClient - no
real Qt display and no real Ollama server needed."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

from personalai.core.config import Config
from personalai.core.conversation import ConversationStore
from personalai.services.chat_service import ChatService


class FakeOllamaClient:
    """Mirrors the CLI test suite's fake - canned, deterministic replies,
    no network. Records every images= call for vision-tab assertions."""

    def __init__(self, reply: str = "canned reply") -> None:
        self.reply = reply
        self.calls: list[tuple[list[dict], str]] = []
        self.image_calls: list[list[str]] = []

    def chat(self, messages, model, on_token=None, images=None):
        self.calls.append((messages, model))
        if images is not None:
            self.image_calls.append(images)
        if on_token:
            on_token(self.reply)
        return self.reply

    def is_available(self):
        return True


@pytest.fixture
def chat_service(tmp_path):
    return ChatService(
        config=Config(),
        store=ConversationStore(tmp_path),
        client=FakeOllamaClient(),
    )


@pytest.fixture
def task_runner(qapp):
    from personalai.ui.workers import TaskRunner

    return TaskRunner()


def test_chat_tab_constructs_and_has_default_sessions(qtbot, chat_service, task_runner):
    from personalai.ui.chat_tab import ChatTab

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    assert tab.task_combo.currentText() == "general"
    assert tab.conversation is not None
    assert tab.conversation.task == "general"


def test_chat_tab_send_appends_transcript_and_saves(qtbot, chat_service, task_runner):
    from personalai.ui.chat_tab import ChatTab

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)

    tab.input_edit.setText("hello there")
    tab._send()
    qtbot.waitUntil(lambda: "canned reply" in tab.transcript.toPlainText(), timeout=5000)

    assert "hello there" in tab.transcript.toPlainText()
    reloaded = chat_service.store.load_or_create("general", "general")
    assert len(reloaded.messages) == 2


def test_chat_tab_attach_folder_stages_it_and_appends_on_send(
    qtbot, chat_service, task_runner, tmp_path, monkeypatch
):
    """Covers both the new folder-attach button and that attaching is
    additive (a file and a folder can be staged together)."""
    from PySide6.QtWidgets import QFileDialog

    from personalai.ui.chat_tab import ChatTab

    chapters = tmp_path / "chapters"
    chapters.mkdir()
    (chapters / "ch1.md").write_text("The arrival at dawn.", encoding="utf-8")
    extra_file = tmp_path / "notes.md"
    extra_file.write_text("A loose note.", encoding="utf-8")

    monkeypatch.setattr(QFileDialog, "getExistingDirectory",
                        lambda *a, **k: str(chapters))
    monkeypatch.setattr(QFileDialog, "getOpenFileNames",
                        lambda *a, **k: ([str(extra_file)], ""))

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab._attach_context_folder()
    tab._attach_context()  # additive, not a replace
    assert set(tab.context_paths) == {str(chapters), str(extra_file)}

    tab.input_edit.setText("continue")
    tab._send()
    qtbot.waitUntil(lambda: "canned reply" in tab.transcript.toPlainText(), timeout=5000)

    conv = chat_service.store.load_or_create("general", "general")
    sent = conv.messages[0].content
    assert "The arrival at dawn." in sent
    assert "A loose note." in sent
    assert sent.endswith("continue")
    assert tab.context_paths == []  # cleared after a successful send


def test_chat_tab_switching_task_loads_that_tasks_default_session(
    qtbot, chat_service, task_runner
):
    from personalai.ui.chat_tab import ChatTab

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab.task_combo.setCurrentText("code")
    assert tab.conversation.task == "code"
    assert tab.conversation.name == "code"


def test_chat_tab_new_session_creates_and_lists_it(qtbot, chat_service, task_runner, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from personalai.ui.chat_tab import ChatTab

    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("my-topic", True))
    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab._new_session()

    assert tab.conversation.name == "my-topic"
    names = [tab.session_list.item(i).text() for i in range(tab.session_list.count())]
    assert "my-topic" in names


def test_chat_tab_session_list_filters_by_task(qtbot, chat_service, task_runner):
    """A 'vision' session must never show up under a text task's list -
    see the comment in ChatTab._reload_sessions for why."""
    from personalai.ui.chat_tab import ChatTab

    vision_conv = chat_service.store.load_or_create("vision", "vision")
    chat_service.store.save(vision_conv)

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    names = [tab.session_list.item(i).text() for i in range(tab.session_list.count())]
    assert "vision" not in names


def test_caption_tab_constructs(qtbot, chat_service, task_runner):
    from personalai.ui.caption_tab import CaptionTab

    tab = CaptionTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    assert tab.session_edit.text() == "vision"
    assert tab.image_path is None


def test_caption_tab_requires_image_first(qtbot, chat_service, task_runner):
    from personalai.ui.caption_tab import CaptionTab

    tab = CaptionTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab._caption()
    assert "Choose an image" in tab.output.toPlainText()


def test_caption_tab_captions_a_chosen_image(qtbot, chat_service, task_runner, tmp_path):
    from personalai.ui.caption_tab import CaptionTab

    image = tmp_path / "cat.png"
    image.write_bytes(b"fake bytes")

    tab = CaptionTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab.image_path = image
    tab.instruction_edit.setText("what is this?")
    tab._caption()

    qtbot.waitUntil(lambda: "canned reply" in tab.output.toPlainText(), timeout=5000)
    conv = chat_service.store.load_or_create("vision", "vision")
    assert "cat.png" in conv.messages[0].content


def test_settings_dialog_saves(qtbot, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    config = store.load()
    dialog = SettingsDialog(config, store)
    qtbot.addWidget(dialog)

    dialog.url_edit.setText("http://192.168.1.50:11434")
    dialog.code_edit.setText("deepseek-coder-v2")
    dialog._save()

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.ollama_url == "http://192.168.1.50:11434"
    assert reloaded.model_for("code") == "deepseek-coder-v2"


def test_main_window_constructs_with_both_tabs(qtbot, chat_service, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.main_window import MainWindow

    window = MainWindow(chat_service, ConfigStore(tmp_path / "config.json"))
    qtbot.addWidget(window)
    assert window.tabs.count() == 2
    assert window.tabs.tabText(0) == "Chat"
    assert window.tabs.tabText(1) == "Caption Image"
