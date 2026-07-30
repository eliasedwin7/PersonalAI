"""Builds the active LLMClient from Config.backend. This is the ONE
place that knows how to construct each backend - cli.py and ui/app.py
never construct OllamaClient/AnthropicClient/OpenAIClient directly, so
swapping backends (or adding a new one later) only ever touches this
file plus one new client module.
"""

from __future__ import annotations

import os

from personalai.core.config import BACKEND_NAMES, Config
from personalai.core.errors import UserFacingError
from personalai.services.llm_client import LLMClient


def build_llm_client(config: Config) -> LLMClient:
    if config.backend == "ollama":
        from personalai.services.ollama_client import OllamaClient

        return OllamaClient(config.ollama_url)

    if config.backend == "anthropic":
        from personalai.services.anthropic_client import AnthropicClient

        return AnthropicClient(api_key=os.environ.get("ANTHROPIC_API_KEY", ""))

    if config.backend == "openai":
        from personalai.services.openai_client import OpenAIClient

        return OpenAIClient(
            base_url=config.openai_base_url,
            api_key=os.environ.get("OPENAI_API_KEY", ""),
        )

    if config.backend == "airllm":
        from personalai.services.airllm_client import AirLLMClient

        return AirLLMClient(max_new_tokens=config.airllm_max_new_tokens)

    raise UserFacingError(
        f"Unknown backend '{config.backend}' (expected one of: "
        f"{', '.join(BACKEND_NAMES)}). Fix it with: "
        f"myai config set backend ollama"
    )
