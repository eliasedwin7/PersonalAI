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

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import (
    QColor,
    QFont,
    QTextCharFormat,
    QTextDocumentFragment,
    QTextLength,
    QTextTableFormat,
)
from PySide6.QtWidgets import QTextEdit

from personalai.core.conversation import Conversation

ROLE_LABELS = {
    "user": ("YOU", "#9fb2ff"),
    "assistant": ("NEXUS", "#7ee0b2"),
    "error": ("ERROR", "#ff8a9a"),
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
        append_message_block(text_edit, msg.role, msg.content, msg.timestamp)
    scroll_to_bottom(text_edit)


def render_messages(text_edit: QTextEdit, messages) -> None:
    text_edit.clear()
    for msg in messages:
        append_message_block(text_edit, msg.role, msg.content, getattr(msg, "timestamp", ""))
    scroll_to_bottom(text_edit)


def append_message_block(text_edit: QTextEdit, role: str, content: str, timestamp: str = "") -> None:
    label, color = ROLE_LABELS.get(role, (role.upper(), "#c8c8c8"))
    cursor = text_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)

    table_format = QTextTableFormat()
    table_format.setCellPadding(13)
    table_format.setCellSpacing(0)
    table_format.setBorder(0)
    table_format.setBackground(QColor(_bubble_background(role)))
    table_format.setAlignment(
        Qt.AlignmentFlag.AlignRight if role == "user" else Qt.AlignmentFlag.AlignLeft
    )
    table_format.setWidth(QTextLength(QTextLength.Type.PercentageLength, _bubble_width(role)))
    table = cursor.insertTable(1, 1, table_format)
    cell_cursor = table.cellAt(0, 0).firstCursorPosition()

    role_format = QTextCharFormat()
    role_format.setForeground(QColor(color))
    role_format.setFontWeight(QFont.Weight.Bold)
    cell_cursor.setCharFormat(role_format)
    cell_cursor.insertText(label)

    when = _short_time(timestamp)
    if when:
        meta_format = QTextCharFormat()
        meta_format.setForeground(QColor("#7f8798"))
        cell_cursor.setCharFormat(meta_format)
        cell_cursor.insertText(f"  {when}")

    cell_cursor.insertBlock()
    cell_cursor.setCharFormat(QTextCharFormat())
    if role == "assistant":
        cell_cursor.insertFragment(QTextDocumentFragment.fromMarkdown(content))
    else:
        cell_cursor.insertText(content)

    cursor = table.lastCursorPosition()
    text_edit.setTextCursor(cursor)
    append_body(text_edit, "\n\n")


def _bubble_background(role: str) -> str:
    if role == "user":
        return "#1a2440"
    if role == "error":
        return "#2a151b"
    return "#151922"


def _bubble_width(role: str) -> int:
    if role == "user":
        return 58
    if role == "error":
        return 70
    return 72


def _short_time(timestamp: str) -> str:
    if not timestamp:
        return ""
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        return ""
    return parsed.strftime("%H:%M")
