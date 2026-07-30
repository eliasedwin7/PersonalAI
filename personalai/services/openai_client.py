"""OpenAI-compatible LLMClient - covers OpenAI's own API, Codex-style
endpoints, and any other service exposing the same /chat/completions
wire format (OpenRouter, a local llama.cpp/vLLM server, LM Studio, etc.)
via a configurable base_url. One of the swappable backends alongside
Ollama and Claude - see services/backend_factory.py.

Standard library only (urllib), same philosophy as ollama_client.py and
anthropic_client.py. Reads the API key from the OPENAI_API_KEY
environment variable only - never stored in config.json.
"""

from __future__ import annotations

import base64
import json
import urllib.error
import urllib.request
from collections.abc import Callable

from personalai.core.errors import BackendUnavailable, UserFacingError
from personalai.services.vision_service import sniff_media_type

CHAT_TIMEOUT_S = 600


def _attach_images(messages: list[dict], images: list[str]) -> list[dict]:
    """OpenAI's vision content-block shape: text + image_url data: URIs
    on the last message. Sniffs each image's media type for the data:
    URI prefix, same as the Claude client."""
    if not messages:
        return messages
    last = messages[-1]
    blocks = [{"type": "text", "text": last.get("content", "")}]
    for b64 in images:
        raw = base64.b64decode(b64)
        mime = sniff_media_type(raw)
        blocks.append({
            "type": "image_url",
            "image_url": {"url": f"data:{mime};base64,{b64}"},
        })
    return messages[:-1] + [{**last, "content": blocks}]


class OpenAIClient:
    def __init__(self, base_url: str, api_key: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

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
                "No API key found. Set the OPENAI_API_KEY environment "
                "variable (used for OpenAI, Codex-compatible, and other "
                "OpenAI-API-compatible endpoints), then try again."
            )
        chat_messages = messages
        if images:
            chat_messages = _attach_images(messages, images)

        payload = {"model": model, "messages": chat_messages,
                  "stream": on_token is not None}
        req = urllib.request.Request(
            self.base_url + "/chat/completions",
            data=json.dumps(payload).encode(),
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {self.api_key}",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=CHAT_TIMEOUT_S) as resp:
                if on_token is None:
                    data = json.loads(resp.read())
                    choices = data.get("choices") or []
                    if not choices:
                        return ""
                    return choices[0].get("message", {}).get("content") or ""
                return self._stream(resp, on_token)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise UserFacingError(
                f"API rejected the request (HTTP {exc.code}): {detail}"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise BackendUnavailable(f"Could not reach {self.base_url}: {exc}") from exc

    @staticmethod
    def _stream(resp, on_token: Callable[[str], None]) -> str:
        """Parse the OpenAI-style SSE stream: `data: {...}` lines with
        choices[0].delta.content fragments, terminated by `data: [DONE]`."""
        chunks: list[str] = []
        for raw_line in resp:
            line = raw_line.decode("utf-8", "replace").strip()
            if not line.startswith("data:"):
                continue
            payload_str = line[len("data:"):].strip()
            if payload_str == "[DONE]":
                break
            try:
                event = json.loads(payload_str)
            except json.JSONDecodeError:
                continue
            choices = event.get("choices") or []
            if not choices:
                continue
            fragment = choices[0].get("delta", {}).get("content", "")
            if fragment:
                chunks.append(fragment)
                on_token(fragment)
        return "".join(chunks)
