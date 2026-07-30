"""Anthropic (Claude) LLMClient - one of the swappable backends alongside
Ollama and the generic OpenAI-compatible client (see
services/backend_factory.py). Standard library only (urllib), same
philosophy as ollama_client.py: no SDK dependency for something this
small, and it stays easy to test with a stubbed urlopen.

Reads the API key from the ANTHROPIC_API_KEY environment variable only -
never stored in config.json. That file is fine for non-secret settings
(URLs, model names); an API key gets the same treatment any other tool
gives credentials: an env var set once in your shell profile, never
written into a config file that could get copied or shared by accident.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Callable

from personalai.core.errors import BackendUnavailable, UserFacingError
from personalai.services.vision_service import sniff_media_type

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"
CHAT_TIMEOUT_S = 600
DEFAULT_MAX_TOKENS = 4096


def _split_system(messages: list[dict]) -> tuple[str, list[dict]]:
    """Claude's Messages API takes the system prompt as its own top-level
    field, not a role="system" entry in the messages list the way Ollama
    and OpenAI do - split ChatService's Ollama-shaped history apart to fit."""
    system_parts = []
    chat_messages = []
    for m in messages:
        if m.get("role") == "system":
            system_parts.append(str(m.get("content", "")))
        else:
            chat_messages.append(m)
    return "\n\n".join(system_parts), chat_messages


def _attach_images(messages: list[dict], images: list[str]) -> list[dict]:
    """Turn the last message's plain-text content into Claude's
    content-block shape with image blocks appended, sniffing each
    image's media type since the base64 string alone doesn't carry it."""
    if not messages:
        return messages
    last = messages[-1]
    blocks = [{"type": "text", "text": last.get("content", "")}]
    for b64 in images:
        raw = base64.b64decode(b64)
        blocks.append({
            "type": "image",
            "source": {
                "type": "base64",
                "media_type": sniff_media_type(raw),
                "data": b64,
            },
        })
    return messages[:-1] + [{**last, "content": blocks}]


class AnthropicClient:
    def __init__(self, api_key: str, max_tokens: int = DEFAULT_MAX_TOKENS) -> None:
        self.api_key = api_key
        self.max_tokens = max_tokens

    def is_available(self) -> bool:
        return bool(self.api_key)

    def chat(
        self,
        messages: list[dict],
        model: str,
        on_token: Callable[[str], None] | None = None,
        images: list[str] | None = None,
    ) -> str:
        if not self.api_key:
            raise BackendUnavailable(
                "No Anthropic API key found. Set the ANTHROPIC_API_KEY "
                "environment variable, then try again."
            )
        system, chat_messages = _split_system(messages)
        if images:
            chat_messages = _attach_images(chat_messages, images)

        payload: dict = {
            "model": model,
            "max_tokens": self.max_tokens,
            "messages": chat_messages,
            "stream": on_token is not None,
        }
        if system:
            payload["system"] = system

        req = urllib.request.Request(
            API_URL,
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "x-api-key": self.api_key,
                "anthropic-version": API_VERSION,
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=CHAT_TIMEOUT_S) as resp:
                if on_token is None:
                    data = json.loads(resp.read())
                    return "".join(
                        block.get("text", "") for block in data.get("content", [])
                        if block.get("type") == "text"
                    )
                return self._stream(resp, on_token)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise UserFacingError(
                f"Claude API rejected the request (HTTP {exc.code}): {detail}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise BackendUnavailable(f"Could not reach the Claude API: {exc}") from exc

    @staticmethod
    def _stream(resp, on_token: Callable[[str], None]) -> str:
        """Parse Claude's SSE stream: `data: {...}` lines, extracting
        text from content_block_delta events, until message_stop."""
        chunks: list[str] = []
        for raw_line in resp:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            try:
                event = json.loads(line[len("data:"):].strip())
            except json.JSONDecodeError:
                continue
            event_type = event.get("type")
            if event_type == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    fragment = delta.get("text", "")
                    if fragment:
                        chunks.append(fragment)
                        on_token(fragment)
            elif event_type == "message_stop":
                break
        return "".join(chunks)
