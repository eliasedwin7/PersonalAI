"""File-context injection: `myai story --context STORY_OUTLINE.md "..."`
reads a local file and folds it into the prompt as reference material.

Truncated to a character budget (not a real tokenizer - this is a rough
guard, same spirit as the tag-length heuristic in the Dune pipeline) so a
huge file can't silently blow the model's context window; it keeps the
END of the file by default, since for a running story/script the most
recent content is usually the most relevant continuation point.
"""

from __future__ import annotations

from pathlib import Path

from personalai.core.errors import UserFacingError

CONTEXT_HEADER = "--- Reference material from {name} ---"
CONTEXT_FOOTER = "--- End of reference material ---"


def load_context(path: Path, char_limit: int) -> str:
    if not path.exists():
        raise UserFacingError(f"Context file not found: {path}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise UserFacingError(f"Could not read {path}: {exc}") from exc
    truncated = len(text) > char_limit
    if truncated:
        text = text[-char_limit:]
    header = CONTEXT_HEADER.format(name=path.name)
    if truncated:
        header += f" (truncated to the last {char_limit} characters)"
    return f"{header}\n{text}\n{CONTEXT_FOOTER}"


def build_user_message(message: str, context_blocks: list[str]) -> str:
    """Combine the user's actual message with any --context file content.
    Context comes first so the model reads "here's material" before
    "here's what I want you to do with it"."""
    if not context_blocks:
        return message
    return "\n\n".join(context_blocks) + "\n\n" + message
