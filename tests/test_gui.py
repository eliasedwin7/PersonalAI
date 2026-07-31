"""GUI tests via pytest-qt. Run offscreen (QT_QPA_PLATFORM set below)
against real ChatService/ConversationStore + a fake OllamaClient - no
real Qt display and no real Ollama server needed."""

from __future__ import annotations

import os
import threading

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtCore import Qt

from personalai.core.config import Config
from personalai.core.conversation import ConversationStore
from personalai.services import voice_service
from personalai.services.chat_service import ChatService
from personalai.services.image_service import ForgeClient
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


@pytest.fixture(autouse=True)
def _fake_forge(monkeypatch):
    """ImageTab probes Forge (health + checkpoint list) as soon as it's
    constructed - keep that off the real network in every GUI test
    (there's usually no Forge server on this machine at all), same
    spirit as the Ollama/mic fakes above. Individual Image-tab tests
    override these to test the probing itself."""
    monkeypatch.setattr(ForgeClient, "health", lambda self: False)
    monkeypatch.setattr(ForgeClient, "list_checkpoints", lambda self: [])


@pytest.fixture(autouse=True)
def _fake_mic_devices(monkeypatch):
    """SettingsDialog also probes real audio hardware for its Microphone
    picker - keep that off real (and possibly absent/CI-flaky) hardware
    in every GUI test; individual tests override this to test the
    picker itself."""
    monkeypatch.setattr(voice_service, "list_input_devices_detailed", list)


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
    # Wait for _sending to clear, not just for the reply text to show up -
    # _on_token (streaming) fires via a queued cross-thread signal BEFORE
    # chat_service.send() has necessarily finished conversation.append()/
    # store.save() on the worker thread, so "reply text visible" and
    # "already saved to disk" are NOT the same moment. _sending only
    # clears in _on_done(), which Qt only delivers after send() has fully
    # returned - a real race this test used to lose intermittently in CI.
    qtbot.waitUntil(lambda: not tab._sending, timeout=5000)

    assert "hello there" in tab.transcript.toPlainText()
    assert "canned reply" in tab.transcript.toPlainText()
    reloaded = chat_service.store.load_or_create("general", "general")
    assert len(reloaded.messages) == 2


def test_chat_tab_stop_keeps_the_user_message_without_a_partial_reply(
    qtbot, chat_service, task_runner
):
    from personalai.ui.chat_tab import ChatTab

    class SlowClient:
        def __init__(self):
            self.release = threading.Event()

        def chat(self, messages, model, on_token=None, images=None):
            on_token("partial")
            self.release.wait(timeout=2)
            on_token("late")
            return "partial late"

    client = SlowClient()
    chat_service.client = client
    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab.input_edit.setPlainText("please stop")
    tab._send()
    qtbot.waitUntil(lambda: "partial" in tab.transcript.toPlainText(), timeout=5000)

    tab._stop_generation()
    client.release.set()
    qtbot.waitUntil(lambda: not tab._sending, timeout=5000)

    assert [message.content for message in tab.conversation.messages] == ["please stop"]
    assert "partial" not in tab.transcript.toPlainText()


def test_chat_tab_regenerate_replaces_latest_reply(qtbot, chat_service, task_runner):
    from personalai.ui.chat_tab import ChatTab

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab.input_edit.setPlainText("hello")
    tab._send()
    qtbot.waitUntil(lambda: not tab._sending, timeout=5000)

    chat_service.client.reply = "fresh reply"
    tab._regenerate()
    qtbot.waitUntil(lambda: not tab._sending, timeout=5000)

    assert "fresh reply" in tab.transcript.toPlainText()
    assert [message.content for message in tab.conversation.messages] == ["hello", "fresh reply"]


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
    qtbot.waitUntil(lambda: not tab._sending, timeout=5000)  # see comment in the test above

    conv = chat_service.store.load_or_create("general", "general")
    sent = conv.messages[0].content
    assert "The arrival at dawn." in sent
    assert "A loose note." in sent
    assert sent.endswith("continue")
    assert tab.context_paths == []  # cleared after a successful send


def test_chat_tab_attached_image_is_sent_with_next_message(
    qtbot, chat_service, task_runner, tmp_path
):
    from personalai.ui.chat_tab import ChatTab

    image = tmp_path / "scene.png"
    image.write_bytes(b"fake image bytes")

    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab._attach_image(image)
    tab.input_edit.setPlainText("what is in this image?")
    tab._send()

    qtbot.waitUntil(lambda: not tab._sending, timeout=5000)

    assert chat_service.client.image_calls
    conv = chat_service.store.load_or_create("general", "general")
    assert "[image: scene.png]" in conv.messages[0].content
    assert "what is in this image?" in conv.messages[0].content
    assert tab.attached_image_path is None


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


def test_chat_tab_rename_session_updates_the_current_conversation(
    qtbot, chat_service, task_runner, monkeypatch
):
    from PySide6.QtWidgets import QInputDialog

    from personalai.ui.chat_tab import ChatTab

    chat_service.store.save(chat_service.store.load_or_create("draft", "general"))
    monkeypatch.setattr(QInputDialog, "getText", lambda *a, **k: ("renamed chat", True))
    tab = ChatTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab._load_session("draft")

    tab._rename_session("draft")

    assert tab.conversation.name == "renamed_chat"
    assert "renamed_chat" in chat_service.store.list_all()


def test_chat_tab_memory_approval_persists_only_checked_facts(
    qtbot, chat_service, task_runner, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QDialog

    from personalai.core.config import ConfigStore
    from personalai.ui.chat_tab import ChatTab, MemoryApprovalDialog

    config_store = ConfigStore(tmp_path / "config.json")

    def accept_first(dialog):
        dialog.checkboxes[0].setChecked(True)
        return QDialog.DialogCode.Accepted

    monkeypatch.setattr(MemoryApprovalDialog, "exec", accept_first)
    tab = ChatTab(chat_service, task_runner, config_store)
    qtbot.addWidget(tab)

    tab._show_memory_suggestions(["Prefers concise answers.", "Works on Nexus."])

    assert chat_service.config.assistant_memory == "- Prefers concise answers."
    assert config_store.load().assistant_memory == "- Prefers concise answers."


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


def test_voice_tab_orb_disabled_when_recording_unavailable(
    qtbot, chat_service, task_runner, monkeypatch
):
    monkeypatch.setattr(voice_service, "is_recording_available", lambda: False)
    monkeypatch.setattr(voice_service, "is_transcription_available", lambda: True)

    from personalai.ui.voice_tab import VoiceTab

    tab = VoiceTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    assert tab.orb.isEnabled() is False


def test_voice_tab_speak_checkbox_disabled_when_speech_unavailable(
    qtbot, chat_service, task_runner, monkeypatch
):
    monkeypatch.setattr(voice_service, "is_speech_available", lambda: False)

    from personalai.ui.voice_tab import VoiceTab

    tab = VoiceTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    assert tab.speak_check.isEnabled() is False


def test_voice_tab_full_turn_transcribes_replies_and_speaks(
    qtbot, chat_service, task_runner, monkeypatch
):
    """Covers the whole tap-to-talk loop: idle -> listening -> transcribing
    -> thinking (reply streams in) -> speaking -> back to idle."""
    monkeypatch.setattr(voice_service, "is_recording_available", lambda: True)
    monkeypatch.setattr(voice_service, "is_transcription_available", lambda: True)
    monkeypatch.setattr(voice_service, "is_speech_available", lambda: True)

    class FakeRecorder:
        def __init__(self_inner, device=None):
            pass

        def start(self_inner):
            pass

        def stop(self_inner):
            return b"fake-wav-bytes"

        def heard_speech(self_inner):
            return True

        def should_auto_stop(self_inner):
            return False

    spoken = []
    monkeypatch.setattr(voice_service, "Recorder", FakeRecorder)
    monkeypatch.setattr(voice_service, "transcribe",
                        lambda wav_bytes, model_size: "what time is it")
    monkeypatch.setattr(voice_service, "speak", lambda text: spoken.append(text))

    from personalai.ui.voice_tab import VoiceTab

    tab = VoiceTab(chat_service, task_runner)
    qtbot.addWidget(tab)

    tab.orb.clicked.emit()  # start listening
    assert tab._state == "listening"
    tab.orb.clicked.emit()  # stop -> transcribe -> reply -> speak

    qtbot.waitUntil(lambda: tab._state == "idle", timeout=5000)
    assert "what time is it" in tab.transcript.toPlainText()
    assert "canned reply" in tab.transcript.toPlainText()
    assert spoken == ["canned reply"]


def test_voice_tab_skips_transcription_when_no_speech_heard(
    qtbot, chat_service, task_runner, monkeypatch
):
    """Regression guard for the "always transcribes to 'you'" bug -
    silence must never even reach faster-whisper."""
    monkeypatch.setattr(voice_service, "is_recording_available", lambda: True)
    monkeypatch.setattr(voice_service, "is_transcription_available", lambda: True)

    class SilentFakeRecorder:
        def __init__(self_inner, device=None):
            pass

        def start(self_inner):
            pass

        def stop(self_inner):
            return b"fake-wav-bytes"

        def heard_speech(self_inner):
            return False

        def peak_rms(self_inner):
            return 12.0

        def should_auto_stop(self_inner):
            return False

    monkeypatch.setattr(voice_service, "Recorder", SilentFakeRecorder)
    called = []
    monkeypatch.setattr(voice_service, "transcribe", lambda *a, **k: called.append(1))

    from personalai.ui.voice_tab import VoiceTab

    tab = VoiceTab(chat_service, task_runner)
    qtbot.addWidget(tab)

    tab.orb.clicked.emit()  # start
    tab.orb.clicked.emit()  # stop - recorder says nothing was heard

    assert tab._state == "idle"
    assert called == []
    assert "Didn't hear anything" in tab.status_label.text()


def test_voice_tab_auto_stops_without_a_second_tap(
    qtbot, chat_service, task_runner, monkeypatch
):
    """Covers the silence-poll QTimer actually driving a stop, not just
    a manual second click - this is what removes the "click stop"
    requirement the user asked to get rid of."""
    monkeypatch.setattr(voice_service, "is_recording_available", lambda: True)
    monkeypatch.setattr(voice_service, "is_transcription_available", lambda: True)
    monkeypatch.setattr(voice_service, "is_speech_available", lambda: False)

    class AutoStoppingRecorder:
        def __init__(self_inner, device=None):
            self_inner.polls = 0

        def start(self_inner):
            pass

        def stop(self_inner):
            return b"fake-wav-bytes"

        def heard_speech(self_inner):
            return True

        def should_auto_stop(self_inner):
            self_inner.polls += 1
            return self_inner.polls >= 2

    monkeypatch.setattr(voice_service, "Recorder", AutoStoppingRecorder)
    monkeypatch.setattr(voice_service, "transcribe",
                        lambda wav_bytes, model_size: "auto stopped")

    from personalai.ui.voice_tab import VoiceTab

    tab = VoiceTab(chat_service, task_runner)
    qtbot.addWidget(tab)

    tab.orb.clicked.emit()  # only ONE tap - no manual stop at all
    assert tab._state == "listening"

    qtbot.waitUntil(lambda: "auto stopped" in tab.transcript.toPlainText(), timeout=5000)
    qtbot.waitUntil(lambda: tab._state == "idle", timeout=5000)


def test_voice_tab_speak_toggle_persists_via_config_store(
    qtbot, chat_service, task_runner, tmp_path, monkeypatch
):
    monkeypatch.setattr(voice_service, "is_speech_available", lambda: True)

    from personalai.core.config import ConfigStore
    from personalai.ui.voice_tab import VoiceTab

    store = ConfigStore(tmp_path / "config.json")
    tab = VoiceTab(chat_service, task_runner, config_store=store)
    qtbot.addWidget(tab)

    tab.speak_check.setChecked(False)
    assert store.load().read_replies_aloud is False


def test_voice_tab_always_uses_system_default_microphone(
    qtbot, chat_service, task_runner, monkeypatch
):
    from personalai.ui.voice_tab import VoiceTab

    devices: list[int | None] = []

    class FakeRecorder:
        def __init__(self, device=None):
            devices.append(device)

        def start(self):
            pass

    chat_service.config.mic_device = 14  # legacy value must be ignored.
    monkeypatch.setattr(voice_service, "Recorder", FakeRecorder)
    tab = VoiceTab(chat_service, task_runner)
    qtbot.addWidget(tab)

    tab._start_listening()
    assert devices == [None]


def test_voice_tab_microphone_test_explains_silent_and_live_results(qtbot, chat_service, task_runner):
    from personalai.ui.voice_tab import VoiceTab

    tab = VoiceTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab._on_microphone_tested((0.0, []))
    assert "No usable microphone signal" in tab.status_label.text()

    tab._on_microphone_tested((500.0, [500.0]))
    assert "receiving sound" in tab.status_label.text()
    assert tab.level_bar.value() > 0


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

    # Wait for _working to clear, not just for the reply text to show up -
    # same cross-thread-signal-vs-store.save() race as ChatTab's send()
    # tests above (see the comment on the first one).
    qtbot.waitUntil(lambda: not tab._working, timeout=5000)
    assert "canned reply" in tab.output.toPlainText()
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


def test_settings_dialog_groups_related_controls_into_tabs(qtbot, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    dialog = SettingsDialog(store.load(), store)
    qtbot.addWidget(dialog)

    assert [dialog.tabs.tabText(index) for index in range(dialog.tabs.count())] == [
        "Connection", "Models", "Voice", "Assistant"
    ]


def test_settings_dialog_history_char_limit_saves(qtbot, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    dialog = SettingsDialog(store.load(), store)
    qtbot.addWidget(dialog)

    dialog.history_limit_spin.setValue(5000)
    dialog._save()

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.history_char_limit == 5000


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


def test_settings_dialog_airllm_token_limit_saves(qtbot, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    dialog = SettingsDialog(store.load(), store)
    qtbot.addWidget(dialog)

    dialog.backend_combo.setCurrentText("airllm")
    dialog.airllm_tokens_spin.setValue(256)
    dialog._save()

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.backend == "airllm"
    assert reloaded.airllm_max_new_tokens == 256


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


def test_settings_dialog_resets_legacy_microphone_selection_to_system_default(
    qtbot, tmp_path
):
    from personalai.core.config import Config, ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    dialog = SettingsDialog(Config(mic_device=14), store)
    qtbot.addWidget(dialog)

    assert not hasattr(dialog, "mic_combo")
    dialog._save()

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.mic_device is None


def test_settings_dialog_prompt_editor_saves_an_override(qtbot, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.services.chat_service import SYSTEM_PROMPTS
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    dialog = SettingsDialog(store.load(), store)
    qtbot.addWidget(dialog)

    assert dialog.prompt_task_combo.currentText() == "general"
    assert dialog.prompt_edit.toPlainText() == SYSTEM_PROMPTS["general"]

    dialog.prompt_edit.setPlainText("Always write in second person.")
    dialog._save()

    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.system_prompts["general"] == "Always write in second person."


def test_settings_dialog_prompt_editor_switching_tasks_preserves_edits(qtbot, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    dialog = SettingsDialog(store.load(), store)
    qtbot.addWidget(dialog)

    dialog.prompt_edit.setPlainText("General override.")
    dialog.prompt_task_combo.setCurrentText("code")
    dialog.prompt_edit.setPlainText("Code override.")
    dialog.prompt_task_combo.setCurrentText("general")
    assert dialog.prompt_edit.toPlainText() == "General override."

    dialog._save()
    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert reloaded.system_prompts["general"] == "General override."
    assert reloaded.system_prompts["code"] == "Code override."


def test_settings_dialog_prompt_editor_reset_clears_override(qtbot, tmp_path):
    from personalai.core.config import Config, ConfigStore
    from personalai.services.chat_service import SYSTEM_PROMPTS
    from personalai.ui.settings_dialog import SettingsDialog

    store = ConfigStore(tmp_path / "config.json")
    config = Config(system_prompts={"general": "An old override."})
    dialog = SettingsDialog(config, store)
    qtbot.addWidget(dialog)

    assert dialog.prompt_edit.toPlainText() == "An old override."
    dialog._reset_current_prompt()
    assert dialog.prompt_edit.toPlainText() == SYSTEM_PROMPTS["general"]

    dialog._save()
    reloaded = ConfigStore(tmp_path / "config.json").load()
    assert "general" not in reloaded.system_prompts


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


def test_main_window_constructs_with_focused_workspaces(qtbot, chat_service, tmp_path):
    from personalai.core.config import ConfigStore
    from personalai.ui.main_window import MainWindow

    window = MainWindow(chat_service, ConfigStore(tmp_path / "config.json"))
    qtbot.addWidget(window)
    assert window.pages.count() == 4
    assert [window.navigation.tabText(i) for i in range(window.navigation.count())] == [
        "Chat", "Voice", "Images", "Agent"
    ]
    assert window.images_page.tabs.tabText(0) == "Describe"
    assert window.images_page.tabs.tabText(1) == "Generate"


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


def test_agent_tab_constructs_with_defaults(qtbot, chat_service, task_runner):
    from personalai.ui.agent_tab import AgentTab

    tab = AgentTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    assert tab.workspace_edit.text() == ""
    assert tab._current_mode().value == "plan"


def test_agent_tab_requires_a_workspace_before_sending(
    qtbot, chat_service, task_runner, monkeypatch
):
    """_send() pops a real QMessageBox.warning() when no workspace is
    set - that's a MODAL call (its own event loop, blocks until
    dismissed), so it must be stubbed out here or this test hangs
    forever waiting for a click that will never come."""
    from PySide6.QtWidgets import QMessageBox

    from personalai.ui.agent_tab import AgentTab

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    tab = AgentTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab.input_edit.setPlainText("do something")
    tab._send()  # no workspace chosen - must not crash or start a task
    assert tab._sending is False


def test_agent_tab_plan_mode_send_shows_final_reply_and_stays_readonly(
    qtbot, chat_service, task_runner, tmp_path
):
    """A plain final-answer reply (no tool call) should render in the
    transcript and never touch the workspace folder."""
    from personalai.ui.agent_tab import AgentTab

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    chat_service.client.reply = "Sure, here's the plan."

    tab = AgentTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab.workspace_edit.setText(str(workspace))
    tab.input_edit.setPlainText("what would you do?")
    tab._send()

    qtbot.waitUntil(lambda: "Sure, here's the plan." in tab.transcript.toPlainText(),
                    timeout=5000)
    assert "what would you do?" in tab.transcript.toPlainText()
    assert list(workspace.iterdir()) == []


def test_agent_tab_filters_tool_call_bookkeeping_from_transcript(
    qtbot, chat_service, task_runner, tmp_path
):
    """A JSON tool-call reply and its synthetic tool-result echo must
    show up in the Activity log, not as if the model "said" them in the
    conversation transcript."""
    from personalai.ui.agent_tab import AgentTab

    workspace = tmp_path / "workspace"
    workspace.mkdir()

    replies = iter([
        '{"tool": "list_dir", "args": {}}',
        "Nothing's there yet.",
    ])
    chat_service.client.chat = lambda messages, model, on_token=None, images=None: next(replies)

    tab = AgentTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab.workspace_edit.setText(str(workspace))
    tab.input_edit.setPlainText("what's in this folder?")
    tab._send()

    qtbot.waitUntil(lambda: "Nothing's there yet." in tab.transcript.toPlainText(),
                    timeout=5000)
    assert "list_dir" not in tab.transcript.toPlainText()
    assert "[tool result for" not in tab.transcript.toPlainText()
    assert "list_dir" in tab.activity_log.toPlainText()


def test_image_tab_constructs_offline(qtbot, chat_service, task_runner):
    from personalai.ui.image_tab import ImageTab

    tab = ImageTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    qtbot.waitUntil(lambda: "offline" in tab.status_label.text(), timeout=5000)
    assert tab.reference_path is None
    assert tab.denoise_spin.isEnabled() is False


def test_image_tab_requires_a_prompt_before_generating(
    qtbot, chat_service, task_runner, monkeypatch
):
    """Same modal-dialog hazard as the Agent tab's equivalent test -
    _generate() pops a real QMessageBox.warning() on an empty prompt,
    which must be stubbed or this hangs on its own event loop."""
    from PySide6.QtWidgets import QMessageBox

    from personalai.ui.image_tab import ImageTab

    monkeypatch.setattr(QMessageBox, "warning", lambda *a, **k: None)
    tab = ImageTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab._generate()  # empty prompt - must not crash or start a task
    assert tab._working is False


def test_image_tab_generate_saves_and_shows_result(
    qtbot, chat_service, task_runner, tmp_path, monkeypatch
):
    from personalai.ui.image_tab import ImageTab

    fake_png = b"\x89PNG\r\n\x1a\nfake bytes"
    monkeypatch.setattr(ForgeClient, "txt2img", lambda self, *a, **k: fake_png)
    chat_service.config.image_save_dir = str(tmp_path / "gen")

    tab = ImageTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab.prompt_edit.setPlainText("a red circle on white background")
    tab._generate()

    qtbot.waitUntil(lambda: tab.last_saved_path is not None, timeout=5000)
    assert tab.last_saved_path.read_bytes() == fake_png
    assert tab.last_saved_path.parent == tmp_path / "gen"
    assert tab.save_as_btn.isEnabled() is True


def test_image_tab_reference_image_enables_denoise_and_uses_img2img(
    qtbot, chat_service, task_runner, tmp_path, monkeypatch
):
    from PySide6.QtWidgets import QFileDialog

    from personalai.ui.image_tab import ImageTab

    reference = tmp_path / "ref.png"
    reference.write_bytes(b"fake reference bytes")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *a, **k: (str(reference), ""))

    captured = {}

    def fake_img2img(self, prompt, reference_image, **kwargs):
        captured["prompt"] = prompt
        captured["reference_image"] = reference_image
        return b"\x89PNG fake"

    monkeypatch.setattr(ForgeClient, "img2img", fake_img2img)
    chat_service.config.image_save_dir = str(tmp_path / "gen")

    tab = ImageTab(chat_service, task_runner)
    qtbot.addWidget(tab)
    tab._choose_reference()
    assert tab.denoise_spin.isEnabled() is True

    tab.prompt_edit.setPlainText("make it blue")
    tab._generate()

    qtbot.waitUntil(lambda: tab.last_saved_path is not None, timeout=5000)
    assert captured["prompt"] == "make it blue"
    assert captured["reference_image"] == b"fake reference bytes"


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
    window.show()

    assert window.close() is True
    qtbot.waitUntil(lambda: not window.isVisible())


def test_main_window_minimize_hides_to_tray(qtbot, chat_service, tmp_path, monkeypatch):
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QSystemTrayIcon

    from personalai.core.config import ConfigStore
    from personalai.ui.main_window import MainWindow

    monkeypatch.setattr(QSystemTrayIcon, "isSystemTrayAvailable", staticmethod(lambda: False))
    window = MainWindow(chat_service, ConfigStore(tmp_path / "config.json"))
    qtbot.addWidget(window)
    window.tray = object()
    window.show()

    window.setWindowState(Qt.WindowState.WindowMinimized)

    qtbot.waitUntil(lambda: not window.isVisible())
