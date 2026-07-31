from __future__ import annotations

import pytest

from personalai.core.config import Config
from personalai.core.conversation import ConversationStore
from personalai.services.chat_service import SYSTEM_PROMPTS, ChatService, system_prompt_for


class FakeOllamaClient:
    def __init__(self, reply: str = "a reply") -> None:
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


def test_system_prompt_for_known_and_unknown_tasks():
    assert system_prompt_for("story") == SYSTEM_PROMPTS["story"]
    assert system_prompt_for("nonsense") == SYSTEM_PROMPTS["general"]


def test_system_prompt_for_uses_override_when_present():
    overrides = {"story": "Always write in second person."}
    assert system_prompt_for("story", overrides) == "Always write in second person."
    assert system_prompt_for("code", overrides) == SYSTEM_PROMPTS["code"]


def test_system_prompt_for_ignores_blank_override():
    assert system_prompt_for("story", {"story": ""}) == SYSTEM_PROMPTS["story"]


def test_system_prompt_for_appends_user_approved_memory():
    prompt = system_prompt_for("general", assistant_memory="My name is Edwin. I prefer concise answers.")
    assert prompt.startswith(SYSTEM_PROMPTS["general"])
    assert "User-approved personal context:" in prompt
    assert "My name is Edwin." in prompt


def test_send_uses_configured_system_prompt_override(tmp_path):
    config = Config(system_prompts={"story": "Always write in second person."})
    client = FakeOllamaClient()
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)

    conv = service.store.load_or_create("story", "story")
    service.send(conv, "hello")

    messages, _model = client.calls[0]
    assert messages[0] == {"role": "system", "content": "Always write in second person."}


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


def test_send_trims_history_to_configured_char_limit(tmp_path):
    config = Config(history_char_limit=250)
    client = FakeOllamaClient()
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)
    conv = service.store.load_or_create("general", "general")
    conv.append("user", "a" * 100)
    conv.append("assistant", "b" * 100)
    service.store.save(conv)

    service.send(conv, "c" * 100)

    messages, _model = client.calls[0]
    contents = [m["content"] for m in messages]
    assert "a" * 100 not in contents  # oldest turn dropped once the budget's exceeded
    assert "c" * 100 in contents      # the message just sent always survives


def test_send_streams_tokens_when_callback_given(tmp_path):
    config = Config()
    client = FakeOllamaClient(reply="streamed")
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)
    conv = service.store.load_or_create("general", "general")

    seen = []
    service.send(conv, "hi", on_token=seen.append)
    assert seen == ["streamed"]


def test_suggest_memory_returns_reviewable_facts_without_persisting(tmp_path):
    config = Config()
    client = FakeOllamaClient(reply='["The user prefers concise answers."]')
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)
    conversation = service.store.load_or_create("general", "general")
    conversation.append("user", "Please keep answers concise.")

    suggestions = service.suggest_memory(conversation)

    assert suggestions == ["The user prefers concise answers."]
    assert config.assistant_memory == ""
    assert "durable" in client.calls[0][0][0]["content"]


def test_regenerate_replaces_only_the_latest_text_reply(tmp_path):
    config = Config()
    client = FakeOllamaClient(reply="first reply")
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)
    conv = service.store.load_or_create("general", "general")
    service.send(conv, "hello")

    service.discard_last_reply(conv)
    assert [message.role for message in conv.messages] == ["user"]

    client.reply = "second reply"
    assert service.regenerate(conv) == "second reply"
    assert [message.content for message in conv.messages] == ["hello", "second reply"]


def test_regenerate_refuses_image_turns(tmp_path):
    config = Config()
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=FakeOllamaClient())
    conv = service.store.load_or_create("general", "general")
    conv.append("user", "[image: photo.png] describe it")
    conv.append("assistant", "A photo")

    from personalai.core.errors import UserFacingError

    with pytest.raises(UserFacingError, match="Image replies"):
        service.discard_last_reply(conv)


def test_send_with_image_persists_text_note_not_raw_bytes(tmp_path):
    from personalai.services.chat_service import VISION_TASK

    image = tmp_path / "cat.png"
    image.write_bytes(b"fake png bytes")
    config = Config()
    client = FakeOllamaClient(reply="A cat sitting on a windowsill.")
    store = ConversationStore(tmp_path / "conversations")
    service = ChatService(config=config, store=store, client=client)
    conv = store.load_or_create(VISION_TASK, VISION_TASK)

    reply = service.send_with_image(conv, "what is this?", image)

    assert reply == "A cat sitting on a windowsill."
    assert conv.messages[0].role == "user"
    assert "cat.png" in conv.messages[0].content
    assert "what is this?" in conv.messages[0].content
    assert "fake png bytes" not in conv.messages[0].content  # never the raw bytes/base64

    # the on-disk JSON must not contain the image bytes either
    raw = (tmp_path / "conversations" / f"{VISION_TASK}.json").read_text(encoding="utf-8")
    assert "fake png bytes" not in raw
    import base64
    assert base64.b64encode(b"fake png bytes").decode() not in raw


def test_send_with_image_passes_base64_to_client(tmp_path):
    import base64

    from personalai.services.chat_service import VISION_TASK

    image = tmp_path / "dog.png"
    image.write_bytes(b"woof bytes")
    config = Config()
    client = FakeOllamaClient(reply="a dog")
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)
    conv = service.store.load_or_create(VISION_TASK, VISION_TASK)

    service.send_with_image(conv, "describe", image)

    assert client.image_calls == [[base64.b64encode(b"woof bytes").decode()]]


def test_send_with_image_uses_vision_system_prompt(tmp_path):
    from personalai.services.chat_service import SYSTEM_PROMPTS, VISION_TASK

    image = tmp_path / "x.png"
    image.write_bytes(b"x")
    config = Config()
    client = FakeOllamaClient()
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)
    conv = service.store.load_or_create(VISION_TASK, VISION_TASK)

    service.send_with_image(conv, "describe", image)

    messages, _model = client.calls[0]
    assert messages[0] == {"role": "system", "content": SYSTEM_PROMPTS["vision"]}


def test_send_with_image_missing_file_raises_before_touching_conversation(tmp_path):
    from personalai.core.errors import UserFacingError
    from personalai.services.chat_service import VISION_TASK

    config = Config()
    client = FakeOllamaClient()
    service = ChatService(config=config, store=ConversationStore(tmp_path), client=client)
    conv = service.store.load_or_create(VISION_TASK, VISION_TASK)

    with pytest.raises(UserFacingError):
        service.send_with_image(conv, "describe", tmp_path / "nope.png")

    assert conv.messages == []  # nothing appended on failure
    assert client.calls == []
