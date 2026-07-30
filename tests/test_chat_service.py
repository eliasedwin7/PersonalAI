from __future__ import annotations

from personalai.core.config import Config
from personalai.core.conversation import ConversationStore
from personalai.services.chat_service import ChatService, SYSTEM_PROMPTS, system_prompt_for


class FakeOllamaClient:
    def __init__(self, reply: str = "a reply") -> None:
        self.reply = reply
        self.calls: list[tuple[list[dict], str]] = []

    def chat(self, messages, model, on_token=None):
        self.calls.append((messages, model))
        if on_token:
            on_token(self.reply)
        return self.reply


def test_system_prompt_for_known_and_unknown_tasks():
    assert system_prompt_for("story") == SYSTEM_PROMPTS["story"]
    assert system_prompt_for("nonsense") == SYSTEM_PROMPTS["general"]


def test_send_appends_both_turns_and_saves(tmp_path):
    config = Config(models={"general": "llama3.1", "story": "llama3.1", "code": "qwen2.5-coder"})
    store = ConversationStore(tmp_path)
    client = FakeOllamaClient(reply="Kellan drew his blade.")
    service = ChatService(config=config, store=store, client=client)

    conv = store.load_or_create("story", "story")
    reply = service.send(conv, "continue chapter 3")

    assert reply == "Kellan drew his blade."
    assert [m.role for m in conv.messages] == ["user", "assistant"]
    assert conv.messages[0].content == "continue chapter 3"

    reloaded = ConversationStore(tmp_path).load_or_create("story", "story")
    assert len(reloaded.messages) == 2


def test_send_uses_the_right_model_for_the_task(tmp_path):
    config = Config(models={"general": "llama3.1", "story": "a-story-model",
                            "code": "a-code-model"})
    client = FakeOllamaClient()
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)

    conv = service.store.load_or_create("code", "code")
    service.send(conv, "write fizzbuzz")

    _messages, model_used = client.calls[0]
    assert model_used == "a-code-model"


def test_send_includes_system_prompt_matching_task(tmp_path):
    config = Config()
    client = FakeOllamaClient()
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)

    conv = service.store.load_or_create("story", "story")
    service.send(conv, "hello")

    messages, _model = client.calls[0]
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPTS["story"]}


def test_send_streams_tokens_when_callback_given(tmp_path):
    config = Config()
    client = FakeOllamaClient(reply="streamed")
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)
    conv = service.store.load_or_create("general", "general")

    seen = []
    service.send(conv, "hi", on_token=seen.append)
    assert seen == ["streamed"]
