from __future__ import annotations

import pytest

from personalai.core.conversation import ConversationStore, safe_session_name
from personalai.core.errors import UserFacingError


def test_safe_session_name_sanitizes():
    assert safe_session_name("my story!") == "my_story_"
    assert safe_session_name("dune chapter-2") == "dune_chapter-2"


def test_safe_session_name_rejects_empty():
    with pytest.raises(UserFacingError):
        safe_session_name("   ")


def test_new_conversation_has_no_messages(tmp_path):
    store = ConversationStore(tmp_path)
    conv = store.load_or_create("story", "story")
    assert conv.messages == []
    assert conv.task == "story"


def test_append_and_reload_round_trips(tmp_path):
    store = ConversationStore(tmp_path)
    conv = store.load_or_create("story", "story")
    conv.append("user", "continue chapter 3")
    conv.append("assistant", "Kellan drew his blade.")
    store.save(conv)

    reloaded = ConversationStore(tmp_path).load_or_create("story", "story")
    assert len(reloaded.messages) == 2
    assert reloaded.messages[0].role == "user"
    assert reloaded.messages[1].content == "Kellan drew his blade."


def test_as_ollama_messages_prepends_system_prompt(tmp_path):
    store = ConversationStore(tmp_path)
    conv = store.load_or_create("code", "code")
    conv.append("user", "write a fizzbuzz")
    messages = conv.as_ollama_messages("you are a coding assistant")
    assert messages[0] == {"role": "system", "content": "you are a coding assistant"}
    assert messages[1] == {"role": "user", "content": "write a fizzbuzz"}


def test_as_ollama_messages_no_limit_keeps_everything(tmp_path):
    store = ConversationStore(tmp_path)
    conv = store.load_or_create("general", "general")
    for i in range(10):
        conv.append("user", f"message {i}" * 50)
    messages = conv.as_ollama_messages("system")
    assert len(messages) == 1 + 10  # system + all 10, no trimming when char_limit is None


def test_as_ollama_messages_char_limit_drops_oldest_turns(tmp_path):
    store = ConversationStore(tmp_path)
    conv = store.load_or_create("general", "general")
    conv.append("user", "a" * 100)     # oldest - should be dropped
    conv.append("assistant", "b" * 100)
    conv.append("user", "c" * 100)     # newest - must survive

    messages = conv.as_ollama_messages("system", char_limit=250)

    contents = [m["content"] for m in messages]
    assert "c" * 100 in contents
    assert "a" * 100 not in contents


def test_as_ollama_messages_char_limit_always_keeps_the_last_message(tmp_path):
    """Even a single message bigger than the whole budget must not
    disappear entirely - the request should still include it."""
    store = ConversationStore(tmp_path)
    conv = store.load_or_create("general", "general")
    conv.append("user", "x" * 5000)

    messages = conv.as_ollama_messages("system", char_limit=10)

    assert messages[-1] == {"role": "user", "content": "x" * 5000}


def test_as_ollama_messages_char_limit_keeps_chronological_order(tmp_path):
    store = ConversationStore(tmp_path)
    conv = store.load_or_create("general", "general")
    conv.append("user", "first" * 20)
    conv.append("assistant", "second" * 20)
    conv.append("user", "third" * 20)

    messages = conv.as_ollama_messages("system", char_limit=1000)

    contents = [m["content"] for m in messages[1:]]
    assert contents == ["first" * 20, "second" * 20, "third" * 20]


def test_list_all_and_delete(tmp_path):
    store = ConversationStore(tmp_path)
    store.save(store.load_or_create("alpha", "general"))
    store.save(store.load_or_create("beta", "story"))
    assert store.list_all() == ["alpha", "beta"]
    assert store.delete("alpha") is True
    assert store.delete("alpha") is False  # already gone
    assert store.list_all() == ["beta"]


def test_corrupt_conversation_file_raises_user_facing(tmp_path):
    store = ConversationStore(tmp_path)
    (tmp_path / "broken.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(UserFacingError):
        store.load_or_create("broken", "general")
