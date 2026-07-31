"""Suggest and merge user-approved personal memory without silent writes."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable

from personalai.core.config import MemoryEntry

MEMORY_SUGGESTION_PROMPT = """Review this Nexus conversation and suggest at most five durable,
useful facts or preferences that would help an assistant in future chats. Only include facts
the user stated or clearly confirmed. Exclude temporary requests, sensitive details, and
anything about other people unless the user explicitly asked to remember it. Phrase each fact
as a neutral, standalone statement such as "The user prefers concise answers." Return only a
JSON array of short strings. Return [] when there is nothing useful to remember."""

MAX_SUGGESTION_LENGTH = 240


def parse_suggestions(response: str) -> list[str]:
    """Extract a small, safe list from a model response that may include code fences."""
    start, end = response.find("["), response.rfind("]")
    if start < 0 or end < start:
        return []
    try:
        raw = json.loads(response[start:end + 1])
    except json.JSONDecodeError:
        return []
    if not isinstance(raw, list):
        return []

    suggestions: list[str] = []
    seen: set[str] = set()
    for item in raw[:5]:
        if not isinstance(item, str):
            continue
        text = re.sub(r"\s+", " ", item).strip(" -\t\r\n")[:MAX_SUGGESTION_LENGTH]
        key = text.casefold()
        if len(text) >= 3 and key not in seen:
            seen.add(key)
            suggestions.append(text)
    return suggestions


def merge_approved_memory(existing: str, approved: Iterable[str]) -> str:
    """Append approved facts once, preserving the user's hand-written memory."""
    lines = [line.strip() for line in existing.splitlines() if line.strip()]
    seen = {line.lstrip("- ").casefold() for line in lines}
    for fact in approved:
        clean = re.sub(r"\s+", " ", fact).strip(" -\t\r\n")
        if clean and clean.casefold() not in seen:
            lines.append(f"- {clean}")
            seen.add(clean.casefold())
    return "\n".join(lines)


def add_approved_entries(entries: list[MemoryEntry], approved: Iterable[str]) -> list[MemoryEntry]:
    """Append new approvals once while retaining their reviewable history."""
    known = {entry.text.casefold() for entry in entries}
    for fact in approved:
        clean = re.sub(r"\s+", " ", fact).strip(" -\t\r\n")
        if clean and clean.casefold() not in known:
            entries.append(MemoryEntry(text=clean, category=categorize_memory(clean)))
            known.add(clean.casefold())
    return entries


def categorize_memory(text: str) -> str:
    lower = text.casefold()
    if any(word in lower for word in ("prefer", "likes", "dislikes", "wants", "style")):
        return "preferences"
    if any(word in lower for word in ("project", "working on", "building", "developing")):
        return "projects"
    if any(word in lower for word in ("call the user", "name is", "lives in", "works as")):
        return "profile"
    if any(word in lower for word in ("remember to", "needs to", "todo", "task")):
        return "tasks"
    return "general"
