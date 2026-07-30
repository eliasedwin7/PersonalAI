"""LLMClient: the contract every chat backend implements (Ollama, Claude,
an OpenAI-compatible API). ChatService and AssistantService-equivalent
code only ever call .chat() (and .is_available() for status checks), so
this is a Protocol for documentation and type-checking - Python's duck
typing already makes any class with a matching chat() method work as a
drop-in, this just names the shape so a new backend has a clear target
and mismatches show up as a type error instead of a runtime surprise.

See services/backend_factory.py for how Config.backend picks which
concrete implementation gets built.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, runtime_checkable


@runtime_checkable
class LLMClient(Protocol):
    def chat(
        self,
        messages: list[dict],
        model: str,
        on_token: Callable[[str], None] | None = None,
        images: list[str] | None = None,
    ) -> str:
        """Send the full message history (Ollama-shaped: a list of
        {"role", "content"} dicts, the first optionally role="system") to
        `model` and return the full reply text.

        Streams if on_token is given, calling it with each text fragment
        as it arrives; otherwise blocks and returns the whole reply at
        once. `images` (base64-encoded strings, no data: prefix) attach
        to the LAST message only - implementations translate that into
        whatever content-block shape their API actually wants.
        """
        ...

    def is_available(self) -> bool:
        """Cheap status check for a UI status light. For Ollama this is a
        real network probe; for an API-key-based backend it's typically
        just "is a key configured" - deliberately not a live API call,
        so checking status doesn't burn API usage."""
        ...
