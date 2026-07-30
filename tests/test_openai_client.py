"""OpenAIClient against a stubbed urllib.request.urlopen - covers OpenAI
itself, Codex-compatible endpoints, and any other OpenAI-wire-format
API, all via the same class parameterized by base_url."""

from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest

from personalai.core.errors import BackendUnavailable, UserFacingError
from personalai.services.openai_client import OpenAIClient


def test_missing_api_key_raises_before_any_network_call(monkeypatch):
    called = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: called.append(1))
    client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="")
    with pytest.raises(BackendUnavailable, match="OPENAI_API_KEY"):
        client.chat([{"role": "user", "content": "hi"}], "gpt-4o")
    assert called == []


def test_is_available_reflects_key_presence():
    assert OpenAIClient(base_url="x", api_key="").is_available() is False
    assert OpenAIClient(base_url="x", api_key="sk-x").is_available() is True


def test_chat_non_streaming_hits_configured_base_url(monkeypatch):
    captured = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({
                "choices": [{"message": {"content": "hello there"}}]
            }).encode()

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        captured["auth"] = req.headers.get("Authorization")
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    # a Codex-compatible endpoint, not the real OpenAI URL - proves base_url
    # is actually used, not hardcoded
    client = OpenAIClient(base_url="https://my-codex-proxy.example/v1", api_key="sk-test")
    reply = client.chat([{"role": "user", "content": "hi"}], "gpt-4o")

    assert reply == "hello there"
    assert captured["url"] == "https://my-codex-proxy.example/v1/chat/completions"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["auth"] == "Bearer sk-test"


def test_chat_streaming_calls_on_token_and_stops_at_done(monkeypatch):
    sse_lines = [
        b'data: {"choices":[{"delta":{"content":"Hello "}}]}\n',
        b'data: {"choices":[{"delta":{"content":"there"}}]}\n',
        b'data: [DONE]\n',
    ]

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __iter__(self): return iter(sse_lines)

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())
    client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="sk-test")
    tokens = []
    reply = client.chat([{"role": "user", "content": "hi"}], "gpt-4o", on_token=tokens.append)
    assert tokens == ["Hello ", "there"]
    assert reply == "Hello there"


def test_chat_with_images_builds_data_uri(monkeypatch):
    captured = {}
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake rest of png"
    b64 = base64.b64encode(png_bytes).decode()

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"choices": [{"message": {"content": "a cat"}}]}).encode()

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="sk-test")
    client.chat([{"role": "user", "content": "what is this?"}], "gpt-4o", images=[b64])

    blocks = captured["body"]["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "what is this?"}
    assert blocks[1]["type"] == "image_url"
    assert blocks[1]["image_url"]["url"] == f"data:image/png;base64,{b64}"


def test_chat_http_error_becomes_user_facing(monkeypatch):
    def fake_urlopen(*a, **k):
        raise urllib.error.HTTPError(
            "url", 401, "unauthorized", None, io.BytesIO(b'{"error":"invalid key"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="sk-bad")
    with pytest.raises(UserFacingError, match="invalid key"):
        client.chat([{"role": "user", "content": "hi"}], "gpt-4o")


def test_chat_connection_error_becomes_backend_unavailable(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
    )
    client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="sk-test")
    with pytest.raises(BackendUnavailable):
        client.chat([{"role": "user", "content": "hi"}], "gpt-4o")


def test_no_choices_returns_empty_string(monkeypatch):
    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"choices": []}).encode()

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())
    client = OpenAIClient(base_url="https://api.openai.com/v1", api_key="sk-test")
    assert client.chat([{"role": "user", "content": "hi"}], "gpt-4o") == ""
