"""Shared colored-transcript rendering, used by both ChatTab and
VoiceTab so a conversation looks the same everywhere it's shown -
role labels bold/colored, assistant replies markdown-rendered (code
blocks, bold, lists, etc. via Qt's built-in CommonMark parser) so a
code or story reply is actually readable instead of showing raw
```/**/- markup as literal text.

User messages are deliberately kept as plain text, not markdown-parsed -
whatever you typed (a filename with underscores, "5 - 3 = 2", ...)
should show up exactly as typed, not get reinterpreted as formatting
you didn't intend.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat, QTextDocumentFragment
from PySide6.QtWidgets import QTextEdit

from personalai.core.conversation import Conversation

ROLE_LABELS = {
    "user": ("YOU", "#aeb4a7"),
    "assistant": ("NEXUS", "#75d8a1"),
}


def append_role_label(text_edit: QTextEdit, role: str) -> None:
    label, color = ROLE_LABELS.get(role, (role, "#c8c8c8"))
    cursor = text_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    bold = QTextCharFormat()
    bold.setForeground(QColor(color))
    bold.setFontWeight(QFont.Weight.Bold)
    cursor.setCharFormat(bold)
    cursor.insertText(f"{label}\n")
    cursor.setCharFormat(QTextCharFormat())  # back to default for the body text
    text_edit.setTextCursor(cursor)


def append_body(text_edit: QTextEdit, text: str) -> None:
    """Plain-text append - used while a reply is still streaming in
    token by token (parsing partial/incomplete markdown mid-stream, e.g.
    an unclosed code fence or a half-typed **bold**, looks worse than
    just showing the raw text until the message is actually finished),
    and always for user messages (see module docstring)."""
    cursor = text_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(text)
    text_edit.setTextCursor(cursor)


def append_markdown_body(text_edit: QTextEdit, markdown_text: str) -> None:
    """Renders `markdown_text` (code blocks, bold, lists, etc.) and
    inserts it at the current cursor position - call once a message is
    complete, not per streamed token (see append_body)."""
    cursor = text_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertFragment(QTextDocumentFragment.fromMarkdown(markdown_text))
    text_edit.setTextCursor(cursor)


def scroll_to_bottom(text_edit: QTextEdit) -> None:
    scrollbar = text_edit.verticalScrollBar()
    scrollbar.setValue(scrollbar.maximum())


def render_transcript(text_edit: QTextEdit, conversation: Conversation | None) -> None:
    text_edit.clear()
    if conversation is None:
        return
    for msg in conversation.messages:
        append_role_label(text_edit, msg.role)
        if msg.role == "assistant":
            append_markdown_body(text_edit, msg.content)
        else:
            append_body(text_edit, msg.content)
        append_body(text_edit, "\n\n")
    scroll_to_bottom(text_edit)
