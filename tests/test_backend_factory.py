"""backend_factory.build_llm_client dispatches Config.backend to the
right client class, wiring env vars for API keys and config for URLs."""

from __future__ import annotations

import pytest

from personalai.core.config import Config
from personalai.core.errors import UserFacingError
from personalai.services.airllm_client import AirLLMClient
from personalai.services.anthropic_client import AnthropicClient
from personalai.services.backend_factory import build_llm_client
from personalai.services.ollama_client import OllamaClient
from personalai.services.openai_client import OpenAIClient


def test_default_backend_is_ollama():
    client = build_llm_client(Config())
    assert isinstance(client, OllamaClient)
    assert client.base_url == "http://127.0.0.1:11434"


def test_ollama_uses_configured_url():
    config = Config(backend="ollama", ollama_url="http://192.168.1.50:11434")
    client = build_llm_client(config)
    assert isinstance(client, OllamaClient)
    assert client.base_url == "http://192.168.1.50:11434"


def test_anthropic_reads_env_var(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-fromenv")
    client = build_llm_client(Config(backend="anthropic"))
    assert isinstance(client, AnthropicClient)
    assert client.api_key == "sk-ant-fromenv"


def test_anthropic_without_env_var_still_builds_but_unconfigured(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    client = build_llm_client(Config(backend="anthropic"))
    assert isinstance(client, AnthropicClient)
    assert client.api_key == ""
    assert client.is_available() is False


def test_openai_reads_env_var_and_configured_base_url(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fromenv")
    config = Config(backend="openai", openai_base_url="https://my-proxy.example/v1")
    client = build_llm_client(config)
    assert isinstance(client, OpenAIClient)
    assert client.api_key == "sk-fromenv"
    assert client.base_url == "https://my-proxy.example/v1"


def test_airllm_uses_configured_token_limit():
    client = build_llm_client(Config(backend="airllm", airllm_max_new_tokens=123))
    assert isinstance(client, AirLLMClient)
    assert client.max_new_tokens == 123


def test_unknown_backend_raises_user_facing_error():
    with pytest.raises(UserFacingError, match="ollama, anthropic, openai, airllm"):
        build_llm_client(Config(backend="nonsense"))
