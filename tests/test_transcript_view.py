"""transcript_view tests: assistant replies get markdown-rendered (code
blocks, bold, ...) while user messages and live-streamed tokens stay
plain text, exactly as typed/streamed.
"""

from __future__ import annotations

from PySide6.QtWidgets import QTextEdit

from personalai.core.conversation import Conversation, Message
from personalai.ui import transcript_view


def test_append_role_label_shows_prefix(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    transcript_view.append_role_label(edit, "user")
    assert edit.toPlainText() == "YOU\n"


def test_append_role_label_unknown_role_falls_back_to_role_name(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    transcript_view.append_role_label(edit, "system")
    assert edit.toPlainText() == "system\n"


def test_append_body_is_literal_plain_text(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    transcript_view.append_body(edit, "**not bold** literally")
    assert edit.toPlainText() == "**not bold** literally"
    assert "font-weight:700" not in edit.toHtml()


def test_append_markdown_body_renders_bold_and_inline_code(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    transcript_view.append_markdown_body(edit, "**bold** and `code`")
    html = edit.toHtml()
    assert "font-weight:700" in html
    assert "monospace" in html
    assert "**bold**" not in edit.toPlainText()  # markers consumed, not shown literally


def test_append_markdown_body_renders_code_fence_as_pre_block(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    transcript_view.append_markdown_body(edit, "```\nprint(1)\n```")
    assert "<pre" in edit.toHtml()


def test_render_transcript_shows_all_messages(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    conv = Conversation(name="test", task="general", messages=[
        Message(role="user", content="hi"),
        Message(role="assistant", content="hello"),
    ])
    transcript_view.render_transcript(edit, conv)
    text = edit.toPlainText()
    assert "YOU\nhi" in text
    assert "NEXUS\nhello" in text


def test_render_transcript_renders_assistant_markdown_but_keeps_user_literal(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    conv = Conversation(name="test", task="general", messages=[
        Message(role="user", content="**not markdown**"),
        Message(role="assistant", content="**is markdown**"),
    ])
    transcript_view.render_transcript(edit, conv)
    text = edit.toPlainText()
    assert "**not markdown**" in text  # user text kept exactly as typed
    assert "is markdown" in text
    assert "**is markdown**" not in text  # assistant's ** consumed by rendering
    assert "font-weight:700" in edit.toHtml()


def test_render_transcript_clears_stale_content_for_none_conversation(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("stale content")
    transcript_view.render_transcript(edit, None)
    assert edit.toPlainText() == ""


def test_render_transcript_clears_previous_content_before_rendering(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    edit.setPlainText("leftover from a previous session")
    conv = Conversation(name="test", task="general", messages=[
        Message(role="user", content="fresh message"),
    ])
    transcript_view.render_transcript(edit, conv)
    assert "leftover" not in edit.toPlainText()


def test_scroll_to_bottom_sets_scrollbar_to_max(qtbot):
    edit = QTextEdit()
    qtbot.addWidget(edit)
    edit.resize(200, 100)
    edit.setPlainText("\n".join(f"line {i}" for i in range(200)))
    transcript_view.scroll_to_bottom(edit)
    scrollbar = edit.verticalScrollBar()
    assert scrollbar.value() == scrollbar.maximum()
