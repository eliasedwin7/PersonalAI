"""Agent mode: a file-aware assistant that can read/search/edit files (and
run shell commands) inside a chosen workspace folder, gated by an
AgentMode:

- PLAN: read-only tools run for real; write_file/edit_file/run_command
  are only *simulated* - the tool describes what it would do (a diff,
  or the command text) without ever touching disk or spawning a
  process. Nothing destructive can happen in this mode, period.
- AUTO_ACCEPT: every tool actually runs, immediately, no per-call
  confirmation - including run_command. Every call is still reported
  via on_activity (visible, never silent).
- MANUAL: every write/edit/run call pauses and calls on_confirm(desc)
  first; read-only tools still run immediately (nothing to confirm
  about a read).

Tool-calling is deliberately backend-agnostic rather than three separate
native function-calling integrations (Anthropic's tool_use blocks,
OpenAI's tool_calls, Ollama's own tools field are three different wire
shapes). Every backend already implements the same LLMClient.chat()
text-in/text-out contract, so this uses one prompted "JSON action"
protocol instead: the system prompt tells the model to reply with
*only* a JSON object naming a tool + arguments when it wants to use
one, and a normal reply when it's done. That works identically through
Ollama, Claude, and OpenAI today with zero changes to any of the three
existing client classes. Upgrading a specific backend to its native
tool-calling API later (if the prompted approach proves unreliable for
some model) is a clean, isolated follow-up, not a rewrite.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from personalai.core.conversation import Conversation
from personalai.core.errors import UserFacingError
from personalai.services.chat_service import ChatService

log = logging.getLogger(__name__)

MAX_TOOL_TURNS = 8           # hard cap on tool-call round-trips per user message
COMMAND_TIMEOUT_S = 120      # run_command's hard wall-clock limit
OUTPUT_TRUNCATE_CHARS = 4000  # tool results fed back to the model are capped this long
MAX_LIST_RESULTS = 200       # search_files/grep result cap

MUTATING_TOOLS = frozenset({"write_file", "edit_file", "run_command"})


class AgentMode(str, Enum):
    PLAN = "plan"
    AUTO_ACCEPT = "auto"
    MANUAL = "manual"


class AgentError(UserFacingError):
    """A tool call itself failed (bad path, timeout, declined, ...) - fed
    back to the model as that tool's result so it can react/retry
    intelligently, not raised out of run_turn."""


@dataclass
class Activity:
    """One reported tool-call event - what the GUI's Activity panel lists
    and the CLI prints, in both cases regardless of mode (visibility is
    not something any mode turns off, only whether the action was
    actually applied)."""

    tool: str
    args: dict
    result: str
    applied: bool  # False in PLAN mode (proposed only) or a declined MANUAL confirmation


def _resolve_in_workspace(workspace: Path, relative: str) -> Path:
    """Every tool path goes through this - resolves `relative` against
    `workspace` and refuses anything that would escape it (../.. tricks,
    an absolute path elsewhere, a symlink pointing outside). No
    exceptions to this, regardless of mode."""
    workspace = workspace.resolve()
    candidate = (workspace / relative).resolve()
    if candidate != workspace and workspace not in candidate.parents:
        raise AgentError(f"Path '{relative}' is outside the workspace ({workspace}).")
    return candidate


# ---- read-only tools ----

def _tool_read_file(args: dict, workspace: Path) -> str:
    path = _resolve_in_workspace(workspace, args["path"])
    if not path.is_file():
        raise AgentError(f"Not a file: {args['path']}")
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        raise AgentError(f"Could not read {args['path']}: {exc}") from exc
    if len(text) > OUTPUT_TRUNCATE_CHARS:
        text = text[:OUTPUT_TRUNCATE_CHARS] + "\n... (truncated)"
    return text


def _tool_list_dir(args: dict, workspace: Path) -> str:
    rel = args.get("path", ".")
    path = _resolve_in_workspace(workspace, rel)
    if not path.is_dir():
        raise AgentError(f"Not a directory: {rel}")
    entries = sorted(p.name + ("/" if p.is_dir() else "") for p in path.iterdir())
    return "\n".join(entries) if entries else "(empty directory)"


def _tool_search_files(args: dict, workspace: Path) -> str:
    pattern = args["pattern"]
    workspace = workspace.resolve()
    matches = sorted(str(p.relative_to(workspace)) for p in workspace.rglob(pattern))
    if not matches:
        return "(no matches)"
    truncated = len(matches) > MAX_LIST_RESULTS
    matches = matches[:MAX_LIST_RESULTS]
    text = "\n".join(matches)
    return text + "\n... (truncated)" if truncated else text


def _tool_grep(args: dict, workspace: Path) -> str:
    pattern = args["pattern"]
    root = _resolve_in_workspace(workspace, args.get("path", "."))
    try:
        regex = re.compile(pattern)
    except re.error as exc:
        raise AgentError(f"Invalid regex '{pattern}': {exc}") from exc

    workspace = workspace.resolve()
    candidates = [root] if root.is_file() else sorted(root.rglob("*"))
    hits: list[str] = []
    for f in candidates:
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for i, line in enumerate(text.splitlines(), start=1):
            if regex.search(line):
                hits.append(f"{f.relative_to(workspace)}:{i}: {line.strip()}")
                if len(hits) >= MAX_LIST_RESULTS:
                    break
        if len(hits) >= MAX_LIST_RESULTS:
            break
    if not hits:
        return "(no matches)"
    return "\n".join(hits) + ("\n... (truncated)" if len(hits) >= MAX_LIST_RESULTS else "")


# ---- mutating tools (real effect - gating happens in AgentService, not here) ----

def _tool_write_file(args: dict, workspace: Path) -> str:
    path = _resolve_in_workspace(workspace, args["path"])
    content = args.get("content", "")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return f"Wrote {len(content)} character(s) to {args['path']}."


def _tool_edit_file(args: dict, workspace: Path) -> str:
    path = _resolve_in_workspace(workspace, args["path"])
    if not path.is_file():
        raise AgentError(f"Not a file: {args['path']}")
    old_text, new_text = args["old_text"], args["new_text"]
    text = path.read_text(encoding="utf-8", errors="replace")
    count = text.count(old_text)
    if count == 0:
        raise AgentError(f"old_text not found in {args['path']} - edit not applied.")
    if count > 1:
        raise AgentError(
            f"old_text appears {count} times in {args['path']} - it must be unique. "
            "Include more surrounding context and try again."
        )
    path.write_text(text.replace(old_text, new_text, 1), encoding="utf-8")
    return f"Edited {args['path']}."


def _tool_run_command(args: dict, workspace: Path) -> str:
    command = args["command"]
    try:
        result = subprocess.run(
            command, shell=True, cwd=workspace, capture_output=True, text=True,
            timeout=COMMAND_TIMEOUT_S, check=False,
        )
    except subprocess.TimeoutExpired as exc:
        raise AgentError(
            f"Command timed out after {COMMAND_TIMEOUT_S}s: {command}"
        ) from exc
    output = (result.stdout or "") + (result.stderr or "")
    if len(output) > OUTPUT_TRUNCATE_CHARS:
        output = output[:OUTPUT_TRUNCATE_CHARS] + "\n... (truncated)"
    return f"(exit code {result.returncode})\n{output}".strip()


def _diff_preview(path: str, old_text: str, new_text: str) -> str:
    diff = difflib.unified_diff(
        old_text.splitlines(keepends=True), new_text.splitlines(keepends=True),
        fromfile=path, tofile=path, n=2,
    )
    return "".join(diff) or "(no textual difference)"


TOOLS: dict[str, Callable[[dict, Path], str]] = {
    "read_file": _tool_read_file,
    "list_dir": _tool_list_dir,
    "search_files": _tool_search_files,
    "grep": _tool_grep,
    "write_file": _tool_write_file,
    "edit_file": _tool_edit_file,
    "run_command": _tool_run_command,
}

TOOL_DESCRIPTIONS = """Available tools - to use one, reply with ONLY a
single JSON object (no other text before or after it) of the form
{"tool": "<name>", "args": {...}}. When you're done and ready to give
your final answer, reply normally in plain text instead (no JSON).

- read_file(path): read a text file's contents.
- list_dir(path="."): list a directory's entries.
- search_files(pattern): find files by glob pattern (e.g. "**/*.py").
- grep(pattern, path="."): regex search file contents, returns
  "path:line: text" per match.
- write_file(path, content): create or overwrite a file.
- edit_file(path, old_text, new_text): replace one exact, unique
  occurrence of old_text with new_text in an existing file.
- run_command(command): run a shell command in the workspace folder.

All paths are relative to the workspace folder; anything that would
resolve outside it is refused."""


MODE_NOTES = {
    AgentMode.PLAN: (
        "You are in PLAN mode: write_file/edit_file/run_command are NOT "
        "actually applied - each one only shows you a preview of what it "
        "WOULD do (a diff, or the command text), and the file/command "
        "state never actually changes no matter how many times you try. "
        "Do not keep retrying a write/edit/command expecting it to take "
        "effect - once you've seen what each proposed action would do, "
        "give your final answer summarizing the plan as plain text."
    ),
    AgentMode.AUTO_ACCEPT: (
        "You are in AUTO-ACCEPT mode: every tool call actually runs "
        "immediately, including run_command - there is no confirmation "
        "step, so only call a tool when you actually intend that effect."
    ),
    AgentMode.MANUAL: (
        "You are in MANUAL mode: write_file/edit_file/run_command will "
        "pause for the user's explicit approval before running - a "
        "declined call will tell you so in its result; don't just retry "
        "the identical call, ask a clarifying question or try a "
        "different approach instead."
    ),
}


def system_prompt_for(workspace: Path, mode: AgentMode) -> str:
    return (
        "You are a coding/file assistant working inside a specific folder:\n"
        f"{workspace}\n\n"
        f"{MODE_NOTES[mode]}\n\n"
        f"{TOOL_DESCRIPTIONS}"
    )


def _parse_tool_call(reply: str) -> tuple[str, dict] | None:
    """A reply counts as a tool call only if the WHOLE (trimmed) message
    is a single JSON object shaped like {"tool": ..., "args": ...} -
    anything else (including JSON embedded in a longer explanation) is
    treated as the model's final natural-language answer, not a tool
    call, so it can't accidentally get stuck in a loop over a reply that
    merely mentions JSON."""
    stripped = reply.strip()
    if not (stripped.startswith("{") and stripped.endswith("}")):
        return None
    try:
        data = json.loads(stripped)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict) or "tool" not in data:
        return None
    return data["tool"], data.get("args") or {}


@dataclass
class AgentService:
    chat_service: ChatService

    def run_turn(
        self,
        conversation: Conversation,
        user_message: str,
        workspace: Path,
        mode: AgentMode,
        on_activity: Callable[[Activity], None] | None = None,
        on_confirm: Callable[[str], bool] | None = None,
        on_token: Callable[[str], None] | None = None,
    ) -> str:
        """Runs the tool-call loop for one user message, returns the
        final natural-language reply. Appends every turn (including
        intermediate tool-result turns) to `conversation` and saves it,
        same as ChatService.send()."""
        if mode is AgentMode.MANUAL and on_confirm is None:
            raise AgentError("MANUAL mode needs an on_confirm callback.")

        conversation.append("user", user_message)
        system_prompt = system_prompt_for(workspace, mode)
        model = self.chat_service.config.model_for(conversation.task)

        for _ in range(MAX_TOOL_TURNS):
            messages = conversation.as_ollama_messages(system_prompt)
            reply = self.chat_service.client.chat(messages, model, on_token=on_token)
            conversation.append("assistant", reply)

            parsed = _parse_tool_call(reply)
            if parsed is None:
                self.chat_service.store.save(conversation)
                return reply

            tool_name, tool_args = parsed
            result_text, applied = self._execute(tool_name, tool_args, workspace, mode, on_confirm)
            if on_activity is not None:
                on_activity(Activity(tool=tool_name, args=tool_args,
                                     result=result_text, applied=applied))
            conversation.append("user", f"[tool result for {tool_name}]\n{result_text}")

        self.chat_service.store.save(conversation)
        return (
            "(stopped after reaching the tool-call limit for this turn - "
            "ask again to continue, or try a more specific request)"
        )

    def _execute(
        self,
        tool_name: str,
        tool_args: dict,
        workspace: Path,
        mode: AgentMode,
        on_confirm: Callable[[str], bool] | None,
    ) -> tuple[str, bool]:
        tool = TOOLS.get(tool_name)
        if tool is None:
            return f"Unknown tool '{tool_name}'.", False

        is_mutating = tool_name in MUTATING_TOOLS
        if is_mutating and mode is AgentMode.PLAN:
            return self._propose(tool_name, tool_args, workspace), False

        if is_mutating and mode is AgentMode.MANUAL:
            description = self._describe(tool_name, tool_args, workspace)
            assert on_confirm is not None
            if not on_confirm(description):
                return "User declined this action - not applied.", False

        try:
            return tool(tool_args, workspace), True
        except AgentError as exc:
            return f"Error: {exc}", False
        except KeyError as exc:
            return f"Error: missing required argument {exc}.", False

    def _describe(self, tool_name: str, tool_args: dict, workspace: Path) -> str:
        if tool_name == "run_command":
            return f"Run command: {tool_args.get('command', '')}"
        if tool_name == "write_file":
            path = tool_args.get("path", "?")
            content = tool_args.get("content", "")
            return f"Write {len(content)} character(s) to {path}"
        if tool_name == "edit_file":
            path = tool_args.get("path", "?")
            try:
                resolved = _resolve_in_workspace(workspace, path)
                old_on_disk = resolved.read_text(encoding="utf-8", errors="replace")
            except (AgentError, OSError):
                old_on_disk = ""
            diff = _diff_preview(path, old_on_disk, old_on_disk.replace(
                tool_args.get("old_text", ""), tool_args.get("new_text", ""), 1))
            return f"Edit {path}:\n{diff}"
        return f"{tool_name}({tool_args})"

    def _propose(self, tool_name: str, tool_args: dict, workspace: Path) -> str:
        """PLAN mode: describe what the tool WOULD do, without doing it."""
        description = self._describe(tool_name, tool_args, workspace)
        return f"[PLAN mode - proposed, not applied]\n{description}"
