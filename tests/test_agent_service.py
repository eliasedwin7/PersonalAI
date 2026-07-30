"""agent_service tests: workspace sandboxing, each tool in isolation,
mode-gating (PLAN never touches disk/spawns a process, AUTO_ACCEPT runs
without asking, MANUAL asks first), and the run_turn tool-call loop
against a fake LLMClient that returns a scripted sequence of replies.
"""

from __future__ import annotations

import json

import pytest

from personalai.core.config import Config
from personalai.core.conversation import ConversationStore
from personalai.services.agent_service import (
    Activity,
    AgentError,
    AgentMode,
    AgentService,
    _parse_tool_call,
    _resolve_in_workspace,
    _tool_edit_file,
    _tool_grep,
    _tool_list_dir,
    _tool_read_file,
    _tool_run_command,
    _tool_search_files,
    _tool_write_file,
)
from personalai.services.chat_service import ChatService


class FakeSequenceClient:
    """Returns replies from a fixed list, one per .chat() call, in
    order - lets a test script a whole tool-call conversation (e.g.
    "call read_file" then "here's my final answer")."""

    def __init__(self, replies: list[str]) -> None:
        self.replies = list(replies)
        self.calls: list[tuple[list[dict], str]] = []

    def chat(self, messages, model, on_token=None, images=None):
        self.calls.append((messages, model))
        reply = self.replies.pop(0)
        if on_token:
            on_token(reply)
        return reply

    def is_available(self):
        return True


def _make_service(replies: list[str], tmp_path) -> tuple[AgentService, ChatService]:
    chat_service = ChatService(
        config=Config(), store=ConversationStore(tmp_path / "conversations"),
        client=FakeSequenceClient(replies),
    )
    return AgentService(chat_service=chat_service), chat_service


def _tool_call_json(tool: str, **args) -> str:
    return json.dumps({"tool": tool, "args": args})


# ---- workspace sandboxing ----

def test_resolve_in_workspace_allows_paths_inside(tmp_path):
    (tmp_path / "sub").mkdir()
    (tmp_path / "sub" / "f.txt").write_text("hi", encoding="utf-8")
    resolved = _resolve_in_workspace(tmp_path, "sub/f.txt")
    assert resolved == (tmp_path / "sub" / "f.txt").resolve()


def test_resolve_in_workspace_rejects_parent_escape(tmp_path):
    with pytest.raises(AgentError, match="outside the workspace"):
        _resolve_in_workspace(tmp_path, "../outside.txt")


def test_resolve_in_workspace_rejects_absolute_path_elsewhere(tmp_path, monkeypatch):
    other = tmp_path.parent / "definitely-not-the-workspace"
    with pytest.raises(AgentError, match="outside the workspace"):
        _resolve_in_workspace(tmp_path, str(other / "f.txt"))


def test_resolve_in_workspace_allows_the_workspace_root_itself(tmp_path):
    assert _resolve_in_workspace(tmp_path, ".") == tmp_path.resolve()


# ---- read-only tools ----

def test_read_file_returns_contents(tmp_path):
    (tmp_path / "a.txt").write_text("hello world", encoding="utf-8")
    assert _tool_read_file({"path": "a.txt"}, tmp_path) == "hello world"


def test_read_file_missing_raises(tmp_path):
    with pytest.raises(AgentError, match="Not a file"):
        _tool_read_file({"path": "nope.txt"}, tmp_path)


def test_read_file_truncates_long_content(tmp_path):
    (tmp_path / "big.txt").write_text("x" * 10_000, encoding="utf-8")
    result = _tool_read_file({"path": "big.txt"}, tmp_path)
    assert "truncated" in result
    assert len(result) < 10_000


def test_list_dir_lists_entries_with_trailing_slash_for_dirs(tmp_path):
    (tmp_path / "file.txt").write_text("x", encoding="utf-8")
    (tmp_path / "subdir").mkdir()
    result = _tool_list_dir({"path": "."}, tmp_path)
    assert "file.txt" in result
    assert "subdir/" in result


def test_list_dir_empty_directory(tmp_path):
    (tmp_path / "empty").mkdir()
    assert _tool_list_dir({"path": "empty"}, tmp_path) == "(empty directory)"


def test_search_files_finds_glob_matches(tmp_path):
    (tmp_path / "a.py").write_text("x", encoding="utf-8")
    (tmp_path / "b.py").write_text("x", encoding="utf-8")
    (tmp_path / "c.txt").write_text("x", encoding="utf-8")
    result = _tool_search_files({"pattern": "*.py"}, tmp_path)
    assert "a.py" in result and "b.py" in result and "c.txt" not in result


def test_search_files_no_matches(tmp_path):
    assert _tool_search_files({"pattern": "*.nonexistent"}, tmp_path) == "(no matches)"


def test_grep_finds_matching_lines_with_path_and_line_number(tmp_path):
    (tmp_path / "code.py").write_text("def foo():\n    return 42\n", encoding="utf-8")
    result = _tool_grep({"pattern": "return"}, tmp_path)
    assert "code.py:2:" in result
    assert "return 42" in result


def test_grep_invalid_regex_raises(tmp_path):
    with pytest.raises(AgentError, match="Invalid regex"):
        _tool_grep({"pattern": "(unclosed"}, tmp_path)


def test_grep_no_matches(tmp_path):
    (tmp_path / "f.txt").write_text("nothing interesting", encoding="utf-8")
    assert _tool_grep({"pattern": "xyz123"}, tmp_path) == "(no matches)"


# ---- mutating tools (direct calls - mode gating is tested separately below) ----

def test_write_file_creates_new_file(tmp_path):
    result = _tool_write_file({"path": "new.txt", "content": "hi"}, tmp_path)
    assert (tmp_path / "new.txt").read_text(encoding="utf-8") == "hi"
    assert "Wrote" in result


def test_write_file_creates_parent_dirs(tmp_path):
    _tool_write_file({"path": "sub/dir/new.txt", "content": "x"}, tmp_path)
    assert (tmp_path / "sub" / "dir" / "new.txt").exists()


def test_edit_file_replaces_unique_match(tmp_path):
    (tmp_path / "f.py").write_text("x = 1\ny = 2\n", encoding="utf-8")
    _tool_edit_file({"path": "f.py", "old_text": "x = 1", "new_text": "x = 100"}, tmp_path)
    assert (tmp_path / "f.py").read_text(encoding="utf-8") == "x = 100\ny = 2\n"


def test_edit_file_old_text_not_found_raises(tmp_path):
    (tmp_path / "f.py").write_text("x = 1\n", encoding="utf-8")
    with pytest.raises(AgentError, match="not found"):
        _tool_edit_file({"path": "f.py", "old_text": "z = 9", "new_text": "z = 10"}, tmp_path)


def test_edit_file_old_text_not_unique_raises(tmp_path):
    (tmp_path / "f.py").write_text("x = 1\nx = 1\n", encoding="utf-8")
    with pytest.raises(AgentError, match="unique"):
        _tool_edit_file({"path": "f.py", "old_text": "x = 1", "new_text": "x = 2"}, tmp_path)


def test_run_command_captures_output_and_exit_code(tmp_path):
    result = _tool_run_command({"command": "echo hello"}, tmp_path)
    assert "exit code 0" in result
    assert "hello" in result


def test_run_command_runs_in_the_workspace_directory(tmp_path):
    (tmp_path / "marker.txt").write_text("x", encoding="utf-8")
    result = _tool_run_command({"command": "dir /b" if _is_windows() else "ls"}, tmp_path)
    assert "marker.txt" in result


def _is_windows() -> bool:
    import sys
    return sys.platform.startswith("win")


# ---- _parse_tool_call ----

def test_parse_tool_call_recognizes_whole_message_json():
    parsed = _parse_tool_call('{"tool": "read_file", "args": {"path": "a.txt"}}')
    assert parsed == ("read_file", {"path": "a.txt"})


def test_parse_tool_call_ignores_plain_text():
    assert _parse_tool_call("Here is my final answer.") is None


def test_parse_tool_call_ignores_json_mentioned_inside_prose():
    assert _parse_tool_call('I could call {"tool": "x"} but I will not.') is None


def test_parse_tool_call_missing_tool_key_is_not_a_call():
    assert _parse_tool_call('{"args": {"path": "a.txt"}}') is None


def test_parse_tool_call_defaults_missing_args_to_empty_dict():
    assert _parse_tool_call('{"tool": "list_dir"}') == ("list_dir", {})


# ---- mode gating via run_turn ----

def test_plan_mode_never_writes_to_disk(tmp_path):
    replies = [
        _tool_call_json("write_file", path="new.txt", content="should not appear"),
        "All done.",
    ]
    agent, _service = _make_service(replies, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    activities: list[Activity] = []
    reply = agent.run_turn(conv, "create a file", workspace, AgentMode.PLAN,
                           on_activity=activities.append)

    assert reply == "All done."
    assert not (workspace / "new.txt").exists()
    assert activities[0].applied is False
    assert "PLAN mode" in activities[0].result


def test_plan_mode_never_runs_commands(tmp_path):
    replies = [
        _tool_call_json("run_command", command="echo should-not-run > marker.txt"),
        "Done.",
    ]
    agent, _service = _make_service(replies, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    agent.run_turn(conv, "run something", workspace, AgentMode.PLAN)

    assert not (workspace / "marker.txt").exists()


def test_plan_mode_still_executes_read_only_tools(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("real content", encoding="utf-8")
    replies = [
        _tool_call_json("read_file", path="a.txt"),
        "The file says: real content",
    ]
    agent, _service = _make_service(replies, tmp_path)
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    activities: list[Activity] = []
    agent.run_turn(conv, "read a.txt", workspace, AgentMode.PLAN, on_activity=activities.append)

    assert activities[0].applied is True
    assert activities[0].result == "real content"


def test_auto_accept_mode_writes_without_confirmation(tmp_path):
    replies = [
        _tool_call_json("write_file", path="new.txt", content="applied for real"),
        "Done.",
    ]
    agent, _service = _make_service(replies, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    confirm_calls = []
    agent.run_turn(conv, "create a file", workspace, AgentMode.AUTO_ACCEPT,
                   on_confirm=lambda desc: confirm_calls.append(desc) or True)

    assert (workspace / "new.txt").read_text(encoding="utf-8") == "applied for real"
    assert confirm_calls == []  # never asked


def test_manual_mode_requires_confirmation_before_writing(tmp_path):
    replies = [
        _tool_call_json("write_file", path="new.txt", content="only if approved"),
        "Done.",
    ]
    agent, _service = _make_service(replies, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    seen_descriptions = []

    def on_confirm(description):
        seen_descriptions.append(description)
        return True

    agent.run_turn(conv, "create a file", workspace, AgentMode.MANUAL, on_confirm=on_confirm)

    assert (workspace / "new.txt").exists()
    assert len(seen_descriptions) == 1
    assert "new.txt" in seen_descriptions[0]


def test_manual_mode_declining_skips_the_write(tmp_path):
    replies = [
        _tool_call_json("write_file", path="new.txt", content="rejected"),
        "OK, I won't.",
    ]
    agent, _service = _make_service(replies, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    activities: list[Activity] = []
    agent.run_turn(conv, "create a file", workspace, AgentMode.MANUAL,
                   on_activity=activities.append, on_confirm=lambda desc: False)

    assert not (workspace / "new.txt").exists()
    assert activities[0].applied is False
    assert "declined" in activities[0].result.lower()


def test_manual_mode_without_on_confirm_raises(tmp_path):
    from personalai.core.conversation import Conversation

    chat_service = ChatService(
        config=Config(), store=ConversationStore(tmp_path), client=FakeSequenceClient(["x"]),
    )
    agent = AgentService(chat_service=chat_service)
    with pytest.raises(AgentError, match="on_confirm"):
        agent.run_turn(Conversation(name="agent", task="general"), "hi", tmp_path,
                       AgentMode.MANUAL)


def test_manual_mode_read_only_tools_do_not_need_confirmation(tmp_path):
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("content", encoding="utf-8")
    replies = [_tool_call_json("read_file", path="a.txt"), "Got it."]
    agent, _service = _make_service(replies, tmp_path)
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    def on_confirm(_description):
        raise AssertionError("read_file should never need confirmation")

    agent.run_turn(conv, "read it", workspace, AgentMode.MANUAL, on_confirm=on_confirm)


# ---- run_turn plumbing ----

def test_run_turn_returns_final_reply_when_no_tool_call(tmp_path):
    agent, _service = _make_service(["Just a normal answer."], tmp_path)
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    reply = agent.run_turn(conv, "hello", tmp_path, AgentMode.PLAN)
    assert reply == "Just a normal answer."


def test_run_turn_appends_and_saves_the_conversation(tmp_path):
    agent, service = _make_service(["Final answer."], tmp_path)
    conv = service.store.load_or_create("agent", "general")

    agent.run_turn(conv, "hello", tmp_path, AgentMode.PLAN)

    reloaded = service.store.load_or_create("agent", "general")
    assert reloaded.messages[0].content == "hello"
    assert reloaded.messages[-1].content == "Final answer."


def test_run_turn_stops_after_max_tool_turns(tmp_path):
    from personalai.services.agent_service import MAX_TOOL_TURNS

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "a.txt").write_text("x", encoding="utf-8")
    endless_tool_calls = [_tool_call_json("read_file", path="a.txt")] * (MAX_TOOL_TURNS + 2)
    agent, _service = _make_service(endless_tool_calls, tmp_path)
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    reply = agent.run_turn(conv, "loop forever", workspace, AgentMode.PLAN)
    assert "tool-call limit" in reply


def test_run_turn_unknown_tool_reports_error_and_continues(tmp_path):
    replies = [
        _tool_call_json("not_a_real_tool", foo="bar"),
        "I could not use that tool.",
    ]
    agent, _service = _make_service(replies, tmp_path)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    from personalai.core.conversation import Conversation
    conv = Conversation(name="agent", task="general")

    activities: list[Activity] = []
    reply = agent.run_turn(conv, "do something odd", workspace, AgentMode.PLAN,
                           on_activity=activities.append)

    assert reply == "I could not use that tool."
    assert "Unknown tool" in activities[0].result
