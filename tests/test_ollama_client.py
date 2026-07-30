"""OllamaClient against a stubbed urllib.request.urlopen - no real
Ollama server needed. Same mocking approach used for AI Character
Studio's OllamaAssistant tests."""

from __future__ import annotations

import io
import json
import urllib.error

import pytest

from personalai.core.errors import OllamaUnavailable, UserFacingError
from personalai.services.ollama_client import OllamaClient


def test_is_available_false_on_connection_error(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
    )
    client = OllamaClient("http://127.0.0.1:11434")
    assert client.is_available() is False


def test_list_models(monkeypatch):
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"models": [{"name": "llama3.1"}, {"name": "qwen2.5-coder"}]}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())
    client = OllamaClient("http://127.0.0.1:11434")
    assert client.list_models() == ["llama3.1", "qwen2.5-coder"]


def test_list_models_empty_on_error(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
    )
    client = OllamaClient("http://127.0.0.1:11434")
    assert client.list_models() == []


def test_chat_non_streaming(monkeypatch):
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"message": {"content": "hello there"}}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())
    client = OllamaClient("http://127.0.0.1:11434")
    reply = client.chat([{"role": "user", "content": "hi"}], "llama3.1")
    assert reply == "hello there"


def test_chat_streaming_calls_on_token(monkeypatch):
    lines = [
        json.dumps({"message": {"content": "hello "}, "done": False}).encode(),
        json.dumps({"message": {"content": "there"}, "done": True}).encode(),
    ]

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __iter__(self): return iter(lines)

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())
    client = OllamaClient("http://127.0.0.1:11434")
    tokens = []
    reply = client.chat([{"role": "user", "content": "hi"}], "llama3.1",
                        on_token=tokens.append)
    assert tokens == ["hello ", "there"]
    assert reply == "hello there"


def test_chat_http_error_becomes_user_facing(monkeypatch):
    def fake_urlopen(*a, **k):
        raise urllib.error.HTTPError(
            "url", 404, "not found", None, io.BytesIO(b'{"error": "model not found"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OllamaClient("http://127.0.0.1:11434")
    with pytest.raises(UserFacingError, match="model not found"):
        client.chat([{"role": "user", "content": "hi"}], "missing-model")


def test_chat_connection_error_becomes_ollama_unavailable(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
    )
    client = OllamaClient("http://127.0.0.1:11434")
    with pytest.raises(OllamaUnavailable):
        client.chat([{"role": "user", "content": "hi"}], "llama3.1")
