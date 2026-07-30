"""File-context injection: `myai story --context STORY_OUTLINE.md "..."`
reads a local file and folds it into the prompt as reference material.
`--context` also accepts a FOLDER (e.g. a whole chapters/ directory) -
its eligible text files are concatenated, each under its own filename
header, then truncated exactly like a single file would be. That reuse
is deliberate: folder mode never needs its own size setting, it just
shares context_char_limit.

Truncation is a character budget, not a real tokenizer (a rough guard,
same spirit as the tag-length heuristic in the Dune pipeline) so a huge
file or folder can't silently blow the model's context window; it keeps
the END of the text, since for a running story/script the most recent
content is usually the most relevant continuation point.
"""

from __future__ import annotations

from pathlib import Path

from personalai.core.errors import UserFacingError

CONTEXT_HEADER = "--- Reference material from {name} ---"
CONTEXT_FOOTER = "--- End of reference material ---"

# Extensions treated as "text" when scanning a folder - deliberately not
# just .txt/.md, since story/code reference material is often source
# files or structured data, not prose. Binary/image formats are excluded
# on purpose (nothing here decodes or describes them).
FOLDER_TEXT_EXTS = {
    ".txt", ".md", ".rst", ".rpy", ".py", ".json", ".yaml", ".yml",
    ".csv", ".cfg", ".ini", ".log",
}
# Safety cap on file COUNT for a folder scan - total combined *size* is
# still bounded by char_limit regardless, this just avoids stat-ing and
# reading thousands of files in a folder someone points at by mistake.
MAX_FILES_FROM_FOLDER = 50


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


def load_context_folder(folder: Path, char_limit: int) -> str:
    if not folder.exists():
        raise UserFacingError(f"Context folder not found: {folder}")
    files = sorted(
        p for p in folder.rglob("*")
        if p.is_file() and p.suffix.lower() in FOLDER_TEXT_EXTS
    )
    if not files:
        raise UserFacingError(
            f"No text files found in {folder} (looked for: "
            f"{', '.join(sorted(FOLDER_TEXT_EXTS))})"
        )
    files = files[:MAX_FILES_FROM_FOLDER]

    parts = []
    for f in files:
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue  # unreadable file (permissions, etc.) - skip, don't fail the whole folder
        rel = f.relative_to(folder).as_posix()
        parts.append(f"--- {rel} ---\n{text}")
    combined = "\n\n".join(parts)

    truncated = len(combined) > char_limit
    if truncated:
        combined = combined[-char_limit:]
    header = CONTEXT_HEADER.format(name=f"{folder.name}/ ({len(files)} file(s))")
    if truncated:
        header += f" (truncated to the last {char_limit} characters combined)"
    return f"{header}\n{combined}\n{CONTEXT_FOOTER}"


def load_context_path(path: Path, char_limit: int) -> str:
    """Entry point --context should actually call: dispatches to a file
    or a folder transparently."""
    if path.is_dir():
        return load_context_folder(path, char_limit)
    return load_context(path, char_limit)


def build_user_message(message: str, context_blocks: list[str]) -> str:
    """Combine the user's actual message with any --context file content.
    Context comes first so the model reads "here's material" before
    "here's what I want you to do with it"."""
    if not context_blocks:
        return message
    return "\n\n".join(context_blocks) + "\n\n" + message
