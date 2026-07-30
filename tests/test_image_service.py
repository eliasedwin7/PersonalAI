"""ForgeClient against a stubbed urllib.request.urlopen - no real Forge
server needed, same mocking approach as test_ollama_client.py."""

from __future__ import annotations

import base64
import io
import json
import urllib.error

import pytest

from personalai.core.config import Config
from personalai.core.errors import UserFacingError
from personalai.services.image_service import ForgeClient, ForgeUnavailable, build_forge_client

FAKE_PNG_BYTES = b"\x89PNG\r\n\x1a\nfake png data"
FAKE_PNG_B64 = base64.b64encode(FAKE_PNG_BYTES).decode()


class _FakeResp:
    def __init__(self, body: dict, status: int = 200) -> None:
        self._body = json.dumps(body).encode()
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def read(self):
        return self._body


def test_health_true_on_200(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp({}))
    assert ForgeClient("http://127.0.0.1:7860").health() is True


def test_health_false_on_connection_error(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
    )
    assert ForgeClient("http://127.0.0.1:7860").health() is False


def test_txt2img_returns_decoded_image_bytes(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return _FakeResp({"images": [FAKE_PNG_B64]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = ForgeClient("http://127.0.0.1:7860")
    result = client.txt2img("a red circle", steps=15, cfg=6.0, width=768, height=768)

    assert result == FAKE_PNG_BYTES
    assert captured["url"] == "http://127.0.0.1:7860/sdapi/v1/txt2img"
    assert captured["body"]["prompt"] == "a red circle"
    assert captured["body"]["steps"] == 15
    assert captured["body"]["cfg_scale"] == 6.0
    assert captured["body"]["width"] == 768


def test_txt2img_raises_when_no_images_returned(monkeypatch):
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: _FakeResp({"images": []}))
    client = ForgeClient("http://127.0.0.1:7860")
    with pytest.raises(UserFacingError, match="no image"):
        client.txt2img("a prompt")


def test_img2img_sends_init_image_and_denoising_strength(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return _FakeResp({"images": [FAKE_PNG_B64]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = ForgeClient("http://127.0.0.1:7860")
    reference = b"\x89PNG reference bytes"
    result = client.img2img("make it blue", reference, denoising_strength=0.4)

    assert result == FAKE_PNG_BYTES
    assert captured["url"] == "http://127.0.0.1:7860/sdapi/v1/img2img"
    assert captured["body"]["denoising_strength"] == 0.4
    assert captured["body"]["init_images"] == [base64.b64encode(reference).decode()]


def test_list_checkpoints_returns_titles(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: _FakeResp([{"title": "model_a.safetensors"},
                                   {"title": "model_b.safetensors"}]),
    )
    client = ForgeClient("http://127.0.0.1:7860")
    assert client.list_checkpoints() == ["model_a.safetensors", "model_b.safetensors"]


def test_list_checkpoints_empty_on_connection_error(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
    )
    client = ForgeClient("http://127.0.0.1:7860")
    assert client.list_checkpoints() == []


def test_set_checkpoint_posts_the_right_option(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["url"] = req.full_url
        captured["body"] = json.loads(req.data)
        return _FakeResp({})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    ForgeClient("http://127.0.0.1:7860").set_checkpoint("my_model.safetensors")

    assert captured["url"] == "http://127.0.0.1:7860/sdapi/v1/options"
    assert captured["body"] == {"sd_model_checkpoint": "my_model.safetensors"}


def test_connection_error_becomes_forge_unavailable(monkeypatch):
    monkeypatch.setattr(
        "urllib.request.urlopen",
        lambda *a, **k: (_ for _ in ()).throw(urllib.error.URLError("refused")),
    )
    client = ForgeClient("http://127.0.0.1:7860")
    with pytest.raises(ForgeUnavailable):
        client.txt2img("a prompt")


def test_http_401_becomes_user_facing_auth_hint(monkeypatch):
    def fake_urlopen(*a, **k):
        raise urllib.error.HTTPError("url", 401, "unauthorized", None, io.BytesIO(b"{}"))

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = ForgeClient("http://127.0.0.1:7860")
    with pytest.raises(UserFacingError, match="FORGE_USERNAME"):
        client.txt2img("a prompt")


def test_basic_auth_header_sent_when_credentials_set(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        return _FakeResp({"images": [FAKE_PNG_B64]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    client = ForgeClient("http://127.0.0.1:7860", username="alice", password="secret")
    client.txt2img("a prompt")

    expected = "Basic " + base64.b64encode(b"alice:secret").decode()
    assert captured["headers"]["Authorization"] == expected


def test_no_auth_header_when_no_username(monkeypatch):
    captured = {}

    def fake_urlopen(req, timeout=None):
        captured["headers"] = dict(req.header_items())
        return _FakeResp({"images": [FAKE_PNG_B64]})

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    ForgeClient("http://127.0.0.1:7860").txt2img("a prompt")

    assert "Authorization" not in captured["headers"]


def test_build_forge_client_reads_env_vars(monkeypatch):
    monkeypatch.setenv("FORGE_USERNAME", "bob")
    monkeypatch.setenv("FORGE_PASSWORD", "hunter2")
    config = Config(forge_url="http://192.168.1.50:7860")

    client = build_forge_client(config)

    assert client.base_url == "http://192.168.1.50:7860"
    assert client.username == "bob"
    assert client.password == "hunter2"


def test_build_forge_client_no_credentials_when_env_unset(monkeypatch):
    monkeypatch.delenv("FORGE_USERNAME", raising=False)
    monkeypatch.delenv("FORGE_PASSWORD", raising=False)
    client = build_forge_client(Config())
    assert client.username is None
    assert client.password is None
