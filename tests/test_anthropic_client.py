"""AnthropicClient against a stubbed urllib.request.urlopen - no real
Claude API calls needed. Same mocking approach as test_ollama_client.py."""

from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest

from personalai.core.errors import BackendUnavailable, UserFacingError
from personalai.services.anthropic_client import AnthropicClient, _split_system


def test_missing_api_key_raises_before_any_network_call(monkeypatch):
    called = []
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: called.append(1))
    client = AnthropicClient(api_key="")
    with pytest.raises(BackendUnavailable, match="ANTHROPIC_API_KEY"):
        client.chat([{"role": "user", "content": "hi"}], "claude-sonnet-5")
    assert called == []


def test_is_available_reflects_key_presence():
    assert AnthropicClient(api_key="").is_available() is False
    assert AnthropicClient(api_key="sk-ant-x").is_available() is True


def test_split_system_extracts_system_message():
    messages = [
        {"role": "system", "content": "be helpful"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    system, chat = _split_system(messages)
    assert system == "be helpful"
    assert chat == [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]


def test_chat_non_streaming_sends_system_separately(monkeypatch):
    captured = {}

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({
                "content": [{"type": "text", "text": "hello there"}]
            }).encode()

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        captured["headers"] = {k.lower(): v for k, v in req.headers.items()}
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AnthropicClient(api_key="sk-ant-test")
    reply = client.chat(
        [{"role": "system", "content": "be terse"}, {"role": "user", "content": "hi"}],
        "claude-sonnet-5",
    )
    assert reply == "hello there"
    assert captured["body"]["system"] == "be terse"
    assert captured["body"]["messages"] == [{"role": "user", "content": "hi"}]
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["headers"]["anthropic-version"]


def test_chat_streaming_calls_on_token(monkeypatch):
    sse_lines = [
        b'event: content_block_delta\n',
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"Hello "}}\n',
        b'\n',
        b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"there"}}\n',
        b'\n',
        b'data: {"type":"message_stop"}\n',
    ]

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def __iter__(self): return iter(sse_lines)

    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: FakeResp())
    client = AnthropicClient(api_key="sk-ant-test")
    tokens = []
    reply = client.chat([{"role": "user", "content": "hi"}], "claude-sonnet-5",
                        on_token=tokens.append)
    assert tokens == ["Hello ", "there"]
    assert reply == "Hello there"


def test_chat_with_images_builds_content_blocks(monkeypatch):
    captured = {}
    png_bytes = b"\x89PNG\r\n\x1a\n" + b"fake rest of png"
    b64 = base64.b64encode(png_bytes).decode()

    class FakeResp:
        def __enter__(self): return self
        def __exit__(self, *a): return False
        def read(self):
            return json.dumps({"content": [{"type": "text", "text": "a cat"}]}).encode()

    def fake_urlopen(req, timeout=None):
        captured["body"] = json.loads(req.data)
        return FakeResp()

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AnthropicClient(api_key="sk-ant-test")
    client.chat(
        [{"role": "user", "content": "what is this?"}], "claude-sonnet-5", images=[b64]
    )
    blocks = captured["body"]["messages"][0]["content"]
    assert blocks[0] == {"type": "text", "text": "what is this?"}
    assert blocks[1]["type"] == "image"
    assert blocks[1]["source"]["media_type"] == "image/png"
    assert blocks[1]["source"]["data"] == b64


def test_chat_http_error_becomes_user_facing(monkeypatch):
    def fake_urlopen(*a, **k):
        raise urllib.error.HTTPError(
            "url", 401, "unauthorized", None, io.BytesIO(b'{"error":"invalid key"}')
        )

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = AnthropicClient(api_key="sk-ant-bad")
    with pytest.raises(UserFacingError, match="invalid key"):
        client.chat([{"role": "user", "content": "hi"}], "claude-sonnet-5")


def test_chat_connection_error_becomes_backend_unavailable(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
    )
    client = AnthropicClient(api_key="sk-ant-test")
    with pytest.raises(BackendUnavailable):
        client.chat([{"role": "user", "content": "hi"}], "claude-sonnet-5")
