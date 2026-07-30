"""Conversation persistence: one JSON file per named conversation under
~/.personalai/conversations/<name>.json.

Each task (general/story/code) has a default ongoing conversation named
after the task, so `myai story` just keeps talking to the same thread
unless you explicitly start a new one with --session. Plain JSON, not a
database - a conversation is small, human-readable, and easy to grep,
copy, or delete by hand if you ever want to.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from personalai.core import config as config_mod
from personalai.core.errors import UserFacingError

_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_-]+")


@dataclass
class Message:
    role: str          # "user" | "assistant" | "system"
    content: str
    timestamp: str = ""


@dataclass
class Conversation:
    name: str
    task: str
    messages: list[Message] = field(default_factory=list)

    def append(self, role: str, content: str) -> Message:
        msg = Message(role=role, content=content,
                     timestamp=datetime.now(UTC).isoformat(timespec="seconds"))
        self.messages.append(msg)
        return msg

    def as_ollama_messages(self, system_prompt: str) -> list[dict]:
        """The full turn history in Ollama's {role, content} shape, with
        the task's system prompt prepended fresh each time (so editing a
        system prompt takes effect on old conversations too, rather than
        being baked in at conversation-creation time)."""
        out = [{"role": "system", "content": system_prompt}]
        out += [{"role": m.role, "content": m.content} for m in self.messages]
        return out


def safe_session_name(name: str) -> str:
    name = _SAFE_NAME_RE.sub("_", name.strip())
    if not name:
        raise UserFacingError("A session name can't be empty.")
    return name


class ConversationStore:
    def __init__(self, directory: Path | None = None) -> None:
        # Read config_mod.CONVERSATIONS_DIR dynamically (not imported by name)
        # so patching it in tests actually takes effect - see config.py.
        self.directory = directory or config_mod.CONVERSATIONS_DIR
        self.directory.mkdir(parents=True, exist_ok=True)

    def _path(self, name: str) -> Path:
        return self.directory / f"{safe_session_name(name)}.json"

    def load_or_create(self, name: str, task: str) -> Conversation:
        path = self._path(name)
        if not path.exists():
            return Conversation(name=name, task=task)
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise UserFacingError(f"Conversation '{name}' is corrupted: {exc}") from exc
        messages = [Message(**m) for m in raw.get("messages", [])]
        return Conversation(name=raw.get("name", name), task=raw.get("task", task),
                            messages=messages)

    def save(self, conversation: Conversation) -> None:
        path = self._path(conversation.name)
        data = {
            "name": conversation.name,
            "task": conversation.task,
            "messages": [
                {"role": m.role, "content": m.content, "timestamp": m.timestamp}
                for m in conversation.messages
            ],
        }
        tmp = path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        tmp.replace(path)

    def delete(self, name: str) -> bool:
        path = self._path(name)
        if path.exists():
            path.unlink()
            return True
        return False

    def list_all(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.json"))
