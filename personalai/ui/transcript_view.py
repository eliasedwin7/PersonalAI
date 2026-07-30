"""Shared colored-transcript rendering, used by both ChatTab and
VoiceTab so a conversation looks the same everywhere it's shown -
role labels bold/colored, body text in the default color.
"""

from __future__ import annotations

from PySide6.QtGui import QColor, QFont, QTextCharFormat
from PySide6.QtWidgets import QTextEdit

from personalai.core.conversation import Conversation

ROLE_LABELS = {
    "user": ("you", "#6fb1fc"),
    "assistant": ("ai", "#8fd68f"),
}


def append_role_label(text_edit: QTextEdit, role: str) -> None:
    label, color = ROLE_LABELS.get(role, (role, "#c8c8c8"))
    cursor = text_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    bold = QTextCharFormat()
    bold.setForeground(QColor(color))
    bold.setFontWeight(QFont.Weight.Bold)
    cursor.setCharFormat(bold)
    cursor.insertText(f"{label}> ")
    cursor.setCharFormat(QTextCharFormat())  # back to default for the body text
    text_edit.setTextCursor(cursor)


def append_body(text_edit: QTextEdit, text: str) -> None:
    cursor = text_edit.textCursor()
    cursor.movePosition(cursor.MoveOperation.End)
    cursor.insertText(text)
    text_edit.setTextCursor(cursor)


def render_transcript(text_edit: QTextEdit, conversation: Conversation | None) -> None:
    text_edit.clear()
    if conversation is None:
        return
    for msg in conversation.messages:
        append_role_label(text_edit, msg.role)
        append_body(text_edit, msg.content + "\n\n")
