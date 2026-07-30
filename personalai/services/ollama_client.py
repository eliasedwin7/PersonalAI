"""Thin HTTP client for a local Ollama server. Standard library only
(urllib) - PersonalAI has almost no dependencies, and Ollama's HTTP API
is simple enough that a requests-shaped wrapper isn't worth an extra
runtime dependency for something this small (requests is still pulled in
for other things, but this client avoids depending on it so it stays
easy to test with a stubbed urlopen).
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Callable

from personalai.core.errors import OllamaUnavailable, UserFacingError

PROBE_TIMEOUT_S = 3
CHAT_TIMEOUT_S = 600


class OllamaClient:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url.rstrip("/")

    def is_available(self) -> bool:
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags",
                                        timeout=PROBE_TIMEOUT_S) as resp:
                return resp.status == 200
        except (urllib.error.URLError, OSError):
            return False

    def list_models(self) -> list[str]:
        try:
            with urllib.request.urlopen(self.base_url + "/api/tags",
                                        timeout=PROBE_TIMEOUT_S) as resp:
                data = json.loads(resp.read())
            return [m.get("name", "") for m in data.get("models", [])]
        except (urllib.error.URLError, OSError, json.JSONDecodeError):
            return []

    def chat(
        self,
        messages: list[dict],
        model: str,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Send the full message history to `model`. Streams if on_token
        is given (each fragment forwarded as it arrives - useful for a
        terminal REPL that wants to print as it goes), otherwise blocks
        and returns the whole reply at once."""
        payload = {"model": model, "messages": messages, "stream": on_token is not None}
        req = urllib.request.Request(
            self.base_url + "/api/chat",
            data=json.dumps(payload).encode(),
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=CHAT_TIMEOUT_S) as resp:
                if on_token is None:
                    data = json.loads(resp.read())
                    return data.get("message", {}).get("content", "")
                chunks: list[str] = []
                for raw_line in resp:
                    line = raw_line.decode("utf-8", "replace").strip()
                    if not line:
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    fragment = data.get("message", {}).get("content", "")
                    if fragment:
                        chunks.append(fragment)
                        on_token(fragment)
                    if data.get("done"):
                        break
                return "".join(chunks)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise UserFacingError(
                f"Ollama rejected the request: {detail} "
                f"(is model '{model}' pulled? try: ollama pull {model})"
            ) from exc
        except (urllib.error.URLError, OSError) as exc:
            raise OllamaUnavailable(
                f"Cannot reach Ollama at {self.base_url}: {exc}\n"
                "Is it installed and running? See SETUP.md."
            ) from exc
