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


@dataclass(frozen=True)
class ConversationSearchResult:
    name: str
    task: str
    snippet: str


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

    def as_ollama_messages(self, system_prompt: str, char_limit: int | None = None) -> list[dict]:
        """The turn history in Ollama's {role, content} shape, with the
        task's system prompt prepended fresh each time (so editing a
        system prompt takes effect on old conversations too, rather than
        being baked in at conversation-creation time).

        `char_limit`, when given, drops the OLDEST turns first once the
        history exceeds it - a long-running conversation would otherwise
        send its entire transcript on every single turn forever, and
        eventually exceed the model's real context window (silently
        truncated or outright rejected, depending on the backend). None
        means no trimming, matching the old unconditional behavior."""
        turns = self.messages if char_limit is None else _trim_to_char_budget(
            self.messages, char_limit)
        out = [{"role": "system", "content": system_prompt}]
        out += [{"role": m.role, "content": m.content} for m in turns]
        return out


def _trim_to_char_budget(messages: list[Message], char_limit: int) -> list[Message]:
    """Keeps as many of the MOST RECENT turns as fit under char_limit
    (measured on message content only), dropping the oldest turns first
    rather than truncating mid-message so every kept message still
    reads as a complete thought. Always keeps at least the single most
    recent message even if it alone exceeds the budget - a huge last
    message shouldn't make the request disappear entirely."""
    kept: list[Message] = []
    total = 0
    for msg in reversed(messages):
        total += len(msg.content)
        if total > char_limit and kept:
            break
        kept.append(msg)
    kept.reverse()
    return kept


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

    def rename(self, old_name: str, new_name: str) -> Conversation:
        """Rename one persisted conversation without changing its history."""
        old_path = self._path(old_name)
        new_path = self._path(new_name)
        if not old_path.exists():
            raise UserFacingError(f"No conversation named '{old_name}'.")
        if new_path.exists() and new_path != old_path:
            raise UserFacingError(f"A conversation named '{new_name}' already exists.")
        conversation = self.load_or_create(old_name, "general")
        conversation.name = safe_session_name(new_name)
        self.save(conversation)
        if new_path != old_path:
            old_path.unlink()
        return conversation

    def list_all(self) -> list[str]:
        return sorted(p.stem for p in self.directory.glob("*.json"))

    def search(self, query: str, limit: int = 50) -> list[ConversationSearchResult]:
        """Search chat titles and message text across all persisted sessions."""
        needle = query.strip().casefold()
        if not needle:
            return []
        results: list[ConversationSearchResult] = []
        for name in self.list_all():
            conversation = self.load_or_create(name, "general")
            if needle in conversation.name.casefold():
                results.append(ConversationSearchResult(name, conversation.task, conversation.name))
            else:
                for message in conversation.messages:
                    content = " ".join(message.content.split())
                    index = content.casefold().find(needle)
                    if index >= 0:
                        start = max(0, index - 42)
                        end = min(len(content), index + len(query) + 72)
                        snippet = ("..." if start else "") + content[start:end]
                        if end < len(content):
                            snippet += "..."
                        results.append(ConversationSearchResult(name, conversation.task, snippet))
                        break
            if len(results) >= limit:
                break
        return results
