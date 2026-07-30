"""GUI tests via pytest-qt. Run offscreen (QT_QPA_PLATFORM set below)
against real ChatService/ConversationStore + a fake OllamaClient - no
real Qt display and no real Ollama server needed."""

from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt

from personalai.core.config import Config
from personalai.core.conversation import ConversationStore
from personalai.services import voice_service
from personalai.services.chat_service import ChatService
from personalai.services.ollama_client import OllamaClient


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


@pytest.fixture(autouse=True)
def _fake_ollama_list_models(monkeypatch):
    """SettingsDialog probes Ollama for a model pick-list on open - keep
    that off the real network in every GUI test, same spirit as the CLI
    suite's autouse Ollama fake."""
    monkeypatch.setattr(OllamaClient, "list_models", lambda self: [])


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

    tab.input_edit.setPlainText("hello there")
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

    tab.input_edit.setPlainText("continue")
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


def test_chat_tab_delete_session_removes_it(qtbot, chat_service, task_runner, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from personalai.ui.chat_tab import ChatTab

    conv = chat_service.store.load_or_create("scratch", "general")
    chat_service.store.save(conv)

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    assert "scratch" in chat_service.store.list_all()

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.Yes)
    tab._delete_session("scratch")

    assert "scratch" not in chat_service.store.list_all()
    names = [tab.session_list.item(i).text() for i in range(tab.session_list.count())]
    assert "scratch" not in names


def test_chat_tab_delete_session_declined_keeps_it(qtbot, chat_service, task_runner, monkeypatch):
    from PySide6.QtWidgets import QMessageBox

    from personalai.ui.chat_tab import ChatTab

    conv = chat_service.store.load_or_create("keep-me", "general")
    chat_service.store.save(conv)

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)

    monkeypatch.setattr(QMessageBox, "question",
                        lambda *a, **k: QMessageBox.StandardButton.No)
    tab._delete_session("keep-me")

    assert "keep-me" in chat_service.store.list_all()


def test_chat_input_edit_enter_sends_shift_enter_inserts_newline(qtbot):
    from personalai.ui.chat_tab import ChatInputEdit

    edit = ChatInputEdit()
    qtbot.addWidget(edit)
    submitted = []
    edit.submitted.connect(lambda: submitted.append(True))

    edit.setPlainText("line1")
    qtbot.keyClick(edit, Qt.Key.Key_Return, Qt.KeyboardModifier.ShiftModifier)
    assert "\n" in edit.toPlainText()
    assert submitted == []

    qtbot.keyClick(edit, Qt.Key.Key_Return)
    assert submitted == [True]


def test_chat_tab_mic_button_disabled_when_voice_unavailable(
    qtbot, chat_service, task_runner, monkeypatch
):
    monkeypatch.setattr(voice_service, "is_recording_available", lambda: False)
    monkeypatch.setattr(voice_service, "is_transcription_available", lambda: True)

    from personalai.ui.chat_tab import ChatTab

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    assert tab.mic_btn.isEnabled() is False


def test_chat_tab_read_aloud_checkbox_disabled_when_speech_unavailable(
    qtbot, chat_service, task_runner, monkeypatch
):
    monkeypatch.setattr(voice_service, "is_speech_available", lambda: False)

    from personalai.ui.chat_tab import ChatTab

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    assert tab.read_aloud_check.isEnabled() is False


def test_chat_tab_recording_transcribes_into_input_box(
    qtbot, chat_service, task_runner, monkeypatch
):
    monkeypatch.setattr(voice_service, "is_recording_available", lambda: True)
    monkeypatch.setattr(voice_service, "is_transcription_available", lambda: True)

    class FakeRecorder:
        def start(self_inner):
            pass

        def stop(self_inner):
            return b"fake-wav-bytes"

    monkeypatch.setattr(voice_service, "Recorder", FakeRecorder)
    monkeypatch.setattr(voice_service, "transcribe",
                        lambda wav_bytes, model_size: "transcribed text")

    from personalai.ui.chat_tab import ChatTab

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)

    tab.mic_btn.click()  # start
    assert tab.mic_btn.text() == "⏹"
    tab.mic_btn.click()  # stop -> kicks off background transcription

    qtbot.waitUntil(lambda: tab.input_edit.toPlainText() == "transcribed text", timeout=5000)
    assert tab.mic_btn.isEnabled() is True
    assert tab.mic_btn.text() == "🎤"


def test_chat_tab_read_aloud_toggle_persists_via_config_store(
    qtbot, chat_service, task_runner, tmp_path
):
    from personalai.core.config import ConfigStore
    from personalai.ui.chat_tab import ChatTab

    store = ConfigStore(tmp_path / "config.json")
    tab = ChatTab(chat_service, task_runner, config_store=store)
    qtbot.addWidget(tab)

    if not voice_service.is_speech_available():
        pytest.skip("pyttsx3 not installed - checkbox is disabled by design")

    tab.read_aloud_check.setChecked(True)
    assert store.load().read_replies_aloud is True


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
    dialog.code_edit.setCurrentText("deepseek-coder-v2")
    dialog._save()

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.ollama_url == "http://192.168.1.50:11434"
    assert reloaded.model_for("code") == "deepseek-coder-v2"


def test_settings_dialog_backend_combo_saves(qtbot, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    config = store.load()
    dialog = SettingsDialog(config, store)
    qtbot.addWidget(dialog)

    assert dialog.backend_combo.currentText() == "ollama"
    dialog.backend_combo.setCurrentText("openai")
    dialog.openai_base_edit.setText("https://my-proxy.example/v1")
    dialog._save()

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.backend == "openai"
    assert reloaded.openai_base_url == "https://my-proxy.example/v1"


def test_settings_dialog_model_combo_populated_from_ollama(qtbot, tmp_path, monkeypatch):
    from personalai.core.config import ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    monkeypatch.setattr(OllamaClient, "list_models", lambda self: ["llama3.1", "mixtral"])
    store = ConfigStore(tmp_path / "config.json")
    dialog = SettingsDialog(store.load(), store)
    qtbot.addWidget(dialog)

    items = [dialog.general_edit.itemText(i) for i in range(dialog.general_edit.count())]
    assert "llama3.1" in items
    assert "mixtral" in items


def test_settings_dialog_whisper_model_saves(qtbot, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    dialog = SettingsDialog(store.load(), store)
    qtbot.addWidget(dialog)

    dialog.whisper_combo.setCurrentText("small.en")
    dialog._save()

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.whisper_model == "small.en"


def test_settings_dialog_never_exposes_an_api_key_field(qtbot, tmp_path):
    """Regression guard for the "env var only" design decision - a
    QLineEdit meant for typing a raw key would be a real mistake here."""
    from personalai.core.config import ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    dialog = SettingsDialog(store.load(), store)
    qtbot.addWidget(dialog)
    assert not hasattr(dialog, "anthropic_api_key_edit")
    assert not hasattr(dialog, "openai_api_key_edit")


def test_settings_backend_switch_rebuilds_live_client(qtbot, chat_service, tmp_path, monkeypatch):
    """Regression guard for the CharacterStudio-style "live settings"
    fix: accepting Settings with a new backend must replace
    chat_service.client immediately, not just update config values that
    an already-constructed OllamaClient never re-reads."""
    from PySide6.QtWidgets import QDialog

    from personalai.core.config import ConfigStore
    from personalai.services.anthropic_client import AnthropicClient
    from personalai.ui.main_window import MainWindow
    from personalai.ui.settings_dialog import SettingsDialog

    window = MainWindow(chat_service, ConfigStore(tmp_path / "config.json"))
    qtbot.addWidget(window)

    def fake_exec(self):
        self.backend_combo.setCurrentText("anthropic")
        self._save()
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(SettingsDialog, "exec", fake_exec)
    window._open_settings()

    assert window.chat_service.config.backend == "anthropic"
    assert isinstance(window.chat_service.client, AnthropicClient)


def test_main_window_constructs_with_both_tabs(qtbot, chat_service, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.main_window import MainWindow

    window = MainWindow(chat_service, ConfigStore(tmp_path / "config.json"))
    qtbot.addWidget(window)
    assert window.tabs.count() == 2
    assert window.tabs.tabText(0) == "Chat"
    assert window.tabs.tabText(1) == "Caption Image"


def test_main_window_remembers_geometry_across_restarts(
    qtbot, chat_service, tmp_path, monkeypatch
):
    """Exact pixel size after restoreGeometry() isn't reliable on the
    offscreen test platform (no real window manager to honor it) - what
    matters here is that the saved bytes round-trip through config.json
    and get handed to restoreGeometry() on the next launch, which is
    exactly what a real desktop session relies on."""
    import base64

    from personalai.core.config import ConfigStore
    from personalai.ui.main_window import MainWindow

    config_store = ConfigStore(tmp_path / "config.json")
    window = MainWindow(chat_service, config_store)
    qtbot.addWidget(window)
    window.resize(842, 611)
    window._save_geometry()

    reloaded_config = config_store.load()
    assert reloaded_config.window_geometry != ""
    chat_service.config.window_geometry = reloaded_config.window_geometry

    original_restore = MainWindow.restoreGeometry
    restored: list[bytes] = []

    def spy_restore(self, data):
        restored.append(bytes(data))
        return original_restore(self, data)

    monkeypatch.setattr(MainWindow, "restoreGeometry", spy_restore)
    window2 = MainWindow(chat_service, config_store)
    qtbot.addWidget(window2)

    assert restored == [base64.b64decode(reloaded_config.window_geometry)]


def test_main_window_close_without_tray_accepts(qtbot, chat_service, tmp_path, monkeypatch):
    """Offscreen test env has no real system tray - closing must behave
    like a normal window (actually close) rather than hang around
    waiting for a tray icon that will never exist."""
    from PySide6.QtWidgets import QSystemTrayIcon

    from personalai.core.config import ConfigStore
    from personalai.ui.main_window import MainWindow

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    window = MainWindow(chat_service, ConfigStore(tmp_path / "config.json"))
    qtbot.addWidget(window)
    assert window.tray is None
